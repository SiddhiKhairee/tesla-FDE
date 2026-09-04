"""
Synthetic data generator — pushes purchase orders, manufacturing orders,
sales orders, and their stock movements into Odoo over a simulated
multi-month window, then injects a known set of anomalies into a controlled
subset and writes a ground-truth log of exactly what was made wrong.

NOT YET RUN AGAINST A LIVE ODOO INSTANCE. The Odoo-side workflow calls below
(button_confirm / button_validate / button_mark_done, and the backorder-wizard
handling in validate_picking) are written against the documented Odoo 17 API,
but haven't been exercised end-to-end yet — expect to need small fixes on the
first real run. Use --dry-run and --limit to test incrementally rather than
firing the full 2-3 month run on the first attempt.

Usage:
    python verify_entities.py      # confirm config.py matches the live Odoo instance
    python generate.py --dry-run   # print the planned schedule, touch nothing
    python generate.py --limit 5   # push a small batch for real, sanity-check in the UI
    python generate.py             # full run
"""
import argparse
import json
import os
import random
from collections import Counter
from datetime import timedelta

import numpy as np
import pandas as pd
from faker import Faker

import config
from anomalies import (
    inject_delayed_delivery,
    inject_duplicate_entry,
    inject_quantity_mismatch,
    inject_stuck_order,
)

# quantity_mismatch candidates: every distinct (product, its natural location)
# combo available. Capped at this length — beyond it, two anomalies would have
# to collide on the same quant. See inject_quantity_mismatches().
QUANTITY_MISMATCH_CANDIDATES = [
    ("cell", "raw_materials"),
    ("bms", "raw_materials"),
    ("enclosure", "raw_materials"),
    ("bracket", "raw_materials"),
    ("finished_good", "finished_goods"),
]
from odoo_client import OdooClient

fake = Faker()


def resolve_entities(client: OdooClient) -> dict:
    warehouse_id = client.get_warehouse_id(config.WAREHOUSE_NAME)
    locations = {
        key: client.get_location_id(name, warehouse_id)
        for key, name in config.LOCATION_NAMES.items()
    }
    suppliers = {key: client.get_partner_id(name) for key, name in config.SUPPLIER_NAMES.items()}
    products = {key: client.get_product_id(sku) for key, sku in config.PRODUCT_SKUS.items()}
    bom_id = client.get_bom_id(products["finished_good"])

    return {
        "warehouse_id": warehouse_id,
        "locations": locations,
        "suppliers": suppliers,
        "products": products,
        "bom_id": bom_id,
    }


def build_schedule(months: int) -> pd.DataFrame:
    """Business-day calendar with Poisson-distributed order counts per day, so
    volume looks like natural plant activity rather than a uniform drip."""
    end = pd.Timestamp.now().normalize()
    start = end - pd.DateOffset(months=months)
    business_days = pd.bdate_range(start, end)

    rng = np.random.default_rng(config.RANDOM_SEED)
    schedule = pd.DataFrame({"date": business_days})
    schedule["purchase_orders"] = rng.poisson(lam=1.2, size=len(business_days))
    schedule["manufacturing_orders"] = rng.poisson(lam=0.8, size=len(business_days))
    schedule["sales_orders"] = rng.poisson(lam=0.9, size=len(business_days))
    return schedule


def confirm_wizard_if_returned(client: OdooClient, result, confirm_method="process"):
    """Some button methods return a confirmation wizard instead of acting
    directly (stock.backorder.confirmation, mrp.consumption.warning, ...).
    Drive it: create the wizard from the action's own context (letting Odoo's
    default_get populate it, rather than us guessing which context keys are
    real writable fields) and call its confirm method.
    """
    if isinstance(result, dict) and result.get("res_model"):
        wizard_model = result["res_model"]
        wizard_id = client.execute_kw(wizard_model, "create", [{}], {"context": result.get("context", {})})
        client.call_button(wizard_model, confirm_method, [wizard_id])
        return True
    return False


def force_move_line_quantities(client: OdooClient, moves: list, picking_id: int | None = None):
    """Set each move's done quantity to full demand, creating the move.line if
    reservation didn't produce one. Odoo 17 uses `quantity` on stock.move.line
    (the older `quantity_done` field was renamed).

    This only forces the *quantity on an already-reserved/available move* —
    it does not conjure stock that isn't there. Callers are responsible for
    checking availability (see check_component_availability) before calling
    this for anything that consumes stock.
    """
    move_ids = [m["id"] for m in moves]
    move_lines = client.search_read(
        "stock.move.line", [["move_id", "in", move_ids]], ["id", "move_id"]
    )
    line_by_move = {line["move_id"][0]: line["id"] for line in move_lines}

    for move in moves:
        line_id = line_by_move.get(move["id"])
        if line_id is not None:
            client.write("stock.move.line", [line_id], {"quantity": move["product_uom_qty"]})
        else:
            vals = {
                "move_id": move["id"],
                "product_id": move["product_id"][0],
                "quantity": move["product_uom_qty"],
                "location_id": move["location_id"][0],
                "location_dest_id": move["location_dest_id"][0],
            }
            if picking_id is not None:
                vals["picking_id"] = picking_id
            client.create("stock.move.line", vals)


def validate_picking(client: OdooClient, picking_id: int, effective_date=None):
    """Reserve, then set move-line quantities to full demand and validate the transfer.

    Odoo's button_validate stamps date_done with the real current server
    time regardless of scheduled_date, so if effective_date is given we
    backdate it afterward to stay inside the simulated historical window.
    """
    client.call_button("stock.picking", "action_assign", [picking_id])

    moves = client.search_read(
        "stock.move",
        [["picking_id", "=", picking_id]],
        ["id", "product_id", "product_uom_qty", "location_id", "location_dest_id"],
    )
    force_move_line_quantities(client, moves, picking_id=picking_id)

    result = client.call_button("stock.picking", "button_validate", [picking_id])
    confirm_wizard_if_returned(client, result, confirm_method="process")

    if effective_date is not None:
        client.write("stock.picking", [picking_id], {"date_done": effective_date.strftime("%Y-%m-%d %H:%M:%S")})


def create_purchase_order(client, entities, product_key, qty, order_date):
    supplier_key = config.PRODUCT_SUPPLIER[product_key]
    po_id = client.create(
        "purchase.order",
        {
            "partner_id": entities["suppliers"][supplier_key],
            "date_order": order_date.strftime("%Y-%m-%d %H:%M:%S"),
            "order_line": [
                (
                    0,
                    0,
                    {
                        "product_id": entities["products"][product_key],
                        "product_qty": qty,
                        "date_planned": order_date.strftime("%Y-%m-%d %H:%M:%S"),
                    },
                )
            ],
        },
    )
    client.call_button("purchase.order", "button_confirm", [po_id])
    # button_confirm stamps date_approve (Confirmation Date) with the real
    # current server time — backdate it to the simulated order date.
    client.write("purchase.order", [po_id], {"date_approve": order_date.strftime("%Y-%m-%d %H:%M:%S")})
    po = client.search_read("purchase.order", [["id", "=", po_id]], ["name"])[0]

    pickings = client.search_read(
        "stock.picking",
        [["origin", "=", po["name"]], ["picking_type_id.code", "=", "incoming"]],
        ["id"],
    )
    # Route the receipt into our specific Raw Materials location rather than
    # wherever the warehouse's default incoming route would otherwise land it.
    for p in pickings:
        client.write("stock.picking", [p["id"]], {"location_dest_id": entities["locations"]["raw_materials"]})

    return po_id, po["name"], [p["id"] for p in pickings]


class InsufficientComponentsError(Exception):
    """Raised when an MO's components aren't actually available to consume."""


def create_manufacturing_order(client, entities, qty, order_date):
    """Create and confirm an MO. Does NOT mark it done — completion is a
    separate step (complete_manufacturing_order) that first checks real
    component availability, so a shortage never gets silently forced through.
    """
    mo_id = client.create(
        "mrp.production",
        {
            "product_id": entities["products"]["finished_good"],
            "product_qty": qty,
            "bom_id": entities["bom_id"],
            "date_start": order_date.strftime("%Y-%m-%d %H:%M:%S"),
            "location_src_id": entities["locations"]["raw_materials"],
            "location_dest_id": entities["locations"]["finished_goods"],
        },
    )
    client.call_button("mrp.production", "action_confirm", [mo_id])
    mo = client.search_read("mrp.production", [["id", "=", mo_id]], ["name"])[0]
    return mo_id, mo["name"]


def complete_manufacturing_order(client, mo_id, qty, effective_date):
    """Reserve components, verify every one is actually available in full,
    and only then force the move quantities and mark the MO done.

    This is the fix for the root cause found in live testing: previously we
    force-set qty_producing and called button_mark_done unconditionally, so
    an MO with zero enclosure/bracket stock on hand still got "completed,"
    landing it in Odoo's "to_close" state (never truly done) while later
    code still counted its output as available — which is exactly what let
    downstream sales-order deliveries ship stock that was never produced.

    Raises InsufficientComponentsError instead of forcing through a shortage;
    the caller is expected to cancel the MO in that case, not fake success.
    """
    client.call_button("mrp.production", "action_assign", [mo_id])

    raw_moves = client.search_read(
        "stock.move",
        [["raw_material_production_id", "=", mo_id]],
        ["id", "product_id", "product_uom_qty", "quantity", "location_id", "location_dest_id"],
    )
    shortfall = [m for m in raw_moves if m["quantity"] < m["product_uom_qty"]]
    if shortfall:
        raise InsufficientComponentsError(
            "; ".join(
                f"{m['product_id'][1]}: need {m['product_uom_qty']}, have {m['quantity']} reserved"
                for m in shortfall
            )
        )

    finished_moves = client.search_read(
        "stock.move",
        [["production_id", "=", mo_id]],
        ["id", "product_id", "product_uom_qty", "location_id", "location_dest_id"],
    )

    force_move_line_quantities(client, raw_moves)
    force_move_line_quantities(client, finished_moves)
    client.write("mrp.production", [mo_id], {"qty_producing": qty})

    result = client.call_button("mrp.production", "button_mark_done", [mo_id])
    confirm_wizard_if_returned(client, result, confirm_method="action_confirm")

    final_state = client.search_read("mrp.production", [["id", "=", mo_id]], ["state"])[0]["state"]
    if final_state != "done":
        raise RuntimeError(f"MO did not reach 'done' state after button_mark_done (got '{final_state}')")

    # button_mark_done stamps date_finished with the real current server
    # time — backdate it to stay inside the simulated historical window.
    client.write("mrp.production", [mo_id], {"date_finished": effective_date.strftime("%Y-%m-%d %H:%M:%S")})


def create_sales_order(client, entities, customer_name, qty, order_date):
    customer_id = client.get_or_create_customer_id(customer_name)
    so_id = client.create(
        "sale.order",
        {
            "partner_id": customer_id,
            "date_order": order_date.strftime("%Y-%m-%d %H:%M:%S"),
            "order_line": [
                (
                    0,
                    0,
                    {
                        "product_id": entities["products"]["finished_good"],
                        "product_uom_qty": qty,
                    },
                )
            ],
        },
    )
    client.call_button("sale.order", "action_confirm", [so_id])
    # action_confirm overwrites date_order with the real current server time
    # even though we set it explicitly on create — force it back.
    client.write("sale.order", [so_id], {"date_order": order_date.strftime("%Y-%m-%d %H:%M:%S")})
    so = client.search_read("sale.order", [["id", "=", so_id]], ["name"])[0]

    pickings = client.search_read(
        "stock.picking",
        [["origin", "=", so["name"]], ["picking_type_id.code", "=", "outgoing"]],
        ["id"],
    )
    # Unlike a PO's receipt (whose scheduled_date inherits date_planned from
    # the order line we set at create), a delivery picking's scheduled_date
    # defaults to real "now" — backdate it here for parity with POs.
    for p in pickings:
        client.write(
            "stock.picking",
            [p["id"]],
            {
                "location_id": entities["locations"]["finished_goods"],
                "scheduled_date": order_date.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )

    return so_id, so["name"], [p["id"] for p in pickings]


def run(client, entities, schedule: pd.DataFrame, limit: int | None, dry_run: bool):
    ground_truth = []
    created_count = 0
    failed_count = 0
    skipped_count = 0

    raw_material_keys = ["cell", "bms", "enclosure", "bracket"]

    for _, day in schedule.iterrows():
        order_date = day["date"].to_pydatetime()

        for _ in range(int(day["purchase_orders"])):
            if limit is not None and created_count >= limit:
                break
            product_key = random.choice(raw_material_keys)
            qty = random.randint(20, 200)
            anomalous = random.random() < config.ANOMALY_RATE

            if dry_run:
                print(f"[dry-run] PO: {product_key} x{qty} on {order_date.date()} anomaly={anomalous}")
                created_count += 1
                continue

            try:
                po_id, po_name, pickings = create_purchase_order(client, entities, product_key, qty, order_date)

                if anomalous and pickings:
                    anomaly_type = random.choice(["stuck", "delayed", "duplicate"])
                    if anomaly_type == "stuck":
                        ground_truth.append(
                            inject_stuck_order(client, "stock.picking", pickings[0], po_name, "done", order_date)
                        )
                    elif anomaly_type == "delayed":
                        # date_done gets fully overwritten by inject_delayed_delivery
                        # below, so the exact effective_date here doesn't matter.
                        validate_picking(client, pickings[0], effective_date=order_date)
                        ground_truth.append(
                            inject_delayed_delivery(client, pickings[0], po_name, order_date, order_date)
                        )
                    else:  # duplicate
                        receipt_date = order_date + timedelta(days=random.randint(1, 4))
                        validate_picking(client, pickings[0], effective_date=receipt_date)
                        supplier_key = config.PRODUCT_SUPPLIER[product_key]
                        dup_vals = {
                            "partner_id": entities["suppliers"][supplier_key],
                            "date_order": order_date.strftime("%Y-%m-%d %H:%M:%S"),
                            "order_line": [
                                (0, 0, {
                                    "product_id": entities["products"][product_key],
                                    "product_qty": qty,
                                    "date_planned": order_date.strftime("%Y-%m-%d %H:%M:%S"),
                                })
                            ],
                        }
                        _, event = inject_duplicate_entry(client, "purchase.order", dup_vals, po_name, order_date)
                        ground_truth.append(event)
                else:
                    if pickings:
                        receipt_date = order_date + timedelta(days=random.randint(1, 4))
                        validate_picking(client, pickings[0], effective_date=receipt_date)

                created_count += 1
            except Exception as e:  # noqa: BLE001 — log and keep going, first live run will surface real issues
                print(f"[FAILED] PO {product_key} x{qty} on {order_date.date()}: {e}")
                failed_count += 1

        for _ in range(int(day["manufacturing_orders"])):
            if limit is not None and created_count >= limit:
                break
            qty = random.randint(1, 10)

            if dry_run:
                print(f"[dry-run] MO: PW3-ASSY x{qty} on {order_date.date()}")
                created_count += 1
                continue

            mo_id = None
            try:
                mo_id, mo_name = create_manufacturing_order(client, entities, qty, order_date)
                finish_date = order_date + timedelta(days=random.randint(0, 1))
                complete_manufacturing_order(client, mo_id, qty, finish_date)
                created_count += 1
            except InsufficientComponentsError as e:
                # Real shortage, not a bug — don't fake completion. Cancel the
                # MO instead of leaving it stuck in a half-done state.
                if mo_id is not None:
                    client.call_button("mrp.production", "action_cancel", [mo_id])
                print(f"[SKIPPED] MO PW3-ASSY x{qty} on {order_date.date()}: insufficient components ({e})")
                skipped_count += 1
            except Exception as e:  # noqa: BLE001
                print(f"[FAILED] MO PW3-ASSY x{qty} on {order_date.date()}: {e}")
                failed_count += 1

        for _ in range(int(day["sales_orders"])):
            if limit is not None and created_count >= limit:
                break
            qty = random.randint(1, 5)
            customer_name = fake.company()
            anomalous = random.random() < config.ANOMALY_RATE

            if dry_run:
                print(f"[dry-run] SO: {customer_name} PW3-ASSY x{qty} on {order_date.date()} anomaly={anomalous}")
                created_count += 1
                continue

            # Hard rule: never generate/validate a delivery for stock that
            # hasn't actually been produced. This is checked fresh right
            # before creating the order, not assumed from timing/sequencing —
            # a shortage here means we skip the SO outright rather than
            # create one whose delivery would ship phantom stock.
            on_hand = client.get_on_hand_qty(
                entities["products"]["finished_good"], entities["locations"]["finished_goods"]
            )
            if on_hand < qty:
                print(
                    f"[SKIPPED] SO {customer_name} PW3-ASSY x{qty} on {order_date.date()}: "
                    f"only {on_hand} on hand in Finished Goods"
                )
                skipped_count += 1
                continue

            try:
                so_id, so_name, pickings = create_sales_order(client, entities, customer_name, qty, order_date)

                if anomalous and pickings:
                    ground_truth.append(
                        inject_stuck_order(client, "stock.picking", pickings[0], so_name, "done", order_date)
                    )
                else:
                    if pickings:
                        ship_date = order_date + timedelta(days=random.randint(0, 2))
                        validate_picking(client, pickings[0], effective_date=ship_date)

                created_count += 1
            except Exception as e:  # noqa: BLE001
                print(f"[FAILED] SO {customer_name} PW3-ASSY x{qty} on {order_date.date()}: {e}")
                failed_count += 1

    return ground_truth, created_count, failed_count, skipped_count


def inject_quantity_mismatches(client, entities, end_date, count):
    """Inject quantity_mismatch anomalies as a separate pass at the very end
    of the simulated window, after every other order has already been
    created — so nothing legitimate touches these quants afterward within
    this run, and a diagnosis agent querying Odoo's *current* state will
    still find the corrupted value.

    Each anomaly targets a distinct product/location combo (see
    QUANTITY_MISMATCH_CANDIDATES) so multiple anomalies never collide on the
    same quant. count is capped at the number of distinct combos available.
    """
    if count > len(QUANTITY_MISMATCH_CANDIDATES):
        print(f"[WARN] quantity_mismatch count {count} exceeds {len(QUANTITY_MISMATCH_CANDIDATES)} "
              f"distinct product/location combos available — capping to avoid collisions.")
        count = len(QUANTITY_MISMATCH_CANDIDATES)

    chosen = random.sample(QUANTITY_MISMATCH_CANDIDATES, count)
    events = []
    for product_key, location_key in chosen:
        event = inject_quantity_mismatch(
            client,
            entities["products"][product_key],
            entities["locations"][location_key],
            config.PRODUCT_SKUS[product_key],
            config.LOCATION_NAMES[location_key],
            end_date,
        )
        events.append(event)
        print(f"  quantity_mismatch: {event.product}@{event.location} "
              f"{event.qty_before_injection} -> {event.qty_after_injection}")
    return events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="print the planned schedule, touch nothing in Odoo")
    parser.add_argument("--limit", type=int, default=None, help="cap total orders created, for a small first test")
    args = parser.parse_args()

    random.seed(config.RANDOM_SEED)

    schedule = build_schedule(config.SIMULATION_MONTHS)
    print(f"Schedule: {len(schedule)} business days, "
          f"~{schedule['purchase_orders'].sum()} POs, "
          f"~{schedule['manufacturing_orders'].sum()} MOs, "
          f"~{schedule['sales_orders'].sum()} SOs planned.")

    if args.dry_run:
        client = None
        entities = None
    else:
        print("Connecting to Odoo and resolving entities...")
        client = OdooClient()
        entities = resolve_entities(client)
        print("All entities resolved.")

    ground_truth, created, failed, skipped = run(client, entities, schedule, args.limit, args.dry_run)

    if not args.dry_run:
        end_date = schedule["date"].max().to_pydatetime()
        print(f"\nInjecting {config.QUANTITY_MISMATCH_COUNT} quantity_mismatch anomalies "
              f"at end of window ({end_date.date()})...")
        ground_truth.extend(
            inject_quantity_mismatches(client, entities, end_date, config.QUANTITY_MISMATCH_COUNT)
        )

    print(f"\nDone. Created: {created}, Failed: {failed}, Skipped (dependency not met): {skipped}, "
          f"Anomalies logged: {len(ground_truth)}")
    if ground_truth:
        counts = Counter(e.anomaly_type for e in ground_truth)
        for anomaly_type, count in sorted(counts.items()):
            print(f"  {anomaly_type}: {count}")

    if not args.dry_run and ground_truth:
        # generated_through anchors "is this overdue" checks (e.g. stuck_order)
        # to the end of the simulated window rather than real wall-clock time,
        # so eval precision/recall stays reproducible run over run.
        end_date = schedule["date"].max().to_pydatetime()
        os.makedirs(os.path.dirname(config.GROUND_TRUTH_PATH), exist_ok=True)
        with open(config.GROUND_TRUTH_PATH, "w") as f:
            json.dump(
                {
                    "generated_through": end_date.isoformat(),
                    "events": [e.to_dict() for e in ground_truth],
                },
                f,
                indent=2,
            )
        print(f"Ground truth written to {config.GROUND_TRUTH_PATH}")


if __name__ == "__main__":
    main()
