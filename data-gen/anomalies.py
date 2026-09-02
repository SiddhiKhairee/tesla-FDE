"""
Anomaly injection — applied to a controlled, known subset of otherwise-normal
generated records. Every injection returns a schema.Event describing exactly
what was made wrong, which gets appended to the ground-truth log so Day 3's
eval script can compute precision/recall against a real answer key.
"""
import random
from datetime import timedelta

from schema import Event


def inject_stuck_order(client, model, record_id, reference, expected_state, timestamp):
    """Leave an order confirmed but never completed, well past when it should be done."""
    current = client.search_read(model, [["id", "=", record_id]], ["state"])[0]["state"]
    return Event(
        source="erp",
        entity_id=reference,
        field="state",
        expected_value=expected_state,
        actual_value=current,
        timestamp=timestamp.isoformat(),
        anomaly_type="stuck_order",
    )


def inject_quantity_mismatch(client, product_id, location_id, product_sku, location_name, timestamp):
    """Directly corrupt the on-hand quantity for a product at a location via stock.quant.

    Designed to be called near the very end of the simulated window, on a
    product/location combo not touched again afterward — otherwise later
    legitimate activity overwrites the corrupted value before a downstream
    diagnosis agent querying Odoo's *current* state would ever see it.

    expected_value/actual_value ARE the before/after snapshot: expected_value
    is the true on-hand quantity read immediately before corruption, actual_value
    is what we replaced it with. Both are also captured verbatim so the ground
    truth is self-contained even if the live quant changes again later.

    Handles the case where no quant record exists yet for this product/location
    by creating one, rather than silently dropping the anomaly.
    """
    qty_before = client.get_on_hand_qty(product_id, location_id)

    # Snapshot existing "Product Quantity Updated" adjustment move ids for this
    # product/location so we can identify the new one this call creates (Odoo
    # doesn't return the move id from action_apply_inventory).
    before_move_ids = set(
        m["id"]
        for m in client.search_read(
            "stock.move",
            [["product_id", "=", product_id], ["reference", "=", "Product Quantity Updated"],
             ["location_dest_id", "=", location_id]],
            ["id"],
        )
    ) | set(
        m["id"]
        for m in client.search_read(
            "stock.move",
            [["product_id", "=", product_id], ["reference", "=", "Product Quantity Updated"],
             ["location_id", "=", location_id]],
            ["id"],
        )
    )

    drift = random.choice([-1, 1]) * random.randint(2, 10)
    wrong_qty = max(0, qty_before + drift)

    quants = client.search_read(
        "stock.quant",
        [["product_id", "=", product_id], ["location_id", "=", location_id]],
        ["id"],
        limit=1,
    )
    if quants:
        quant_id = quants[0]["id"]
        client.write("stock.quant", [quant_id], {"inventory_quantity": wrong_qty})
    else:
        quant_id = client.create(
            "stock.quant",
            {"product_id": product_id, "location_id": location_id, "inventory_quantity": wrong_qty},
        )
    client.call_button("stock.quant", "action_apply_inventory", [quant_id])

    # Backdate the adjustment move Odoo just created, same as every other
    # date field in this project — Odoo stamps it with real "now" otherwise.
    after_move_ids = set(
        m["id"]
        for m in client.search_read(
            "stock.move",
            [["product_id", "=", product_id], ["reference", "=", "Product Quantity Updated"],
             ["location_dest_id", "=", location_id]],
            ["id"],
        )
    ) | set(
        m["id"]
        for m in client.search_read(
            "stock.move",
            [["product_id", "=", product_id], ["reference", "=", "Product Quantity Updated"],
             ["location_id", "=", location_id]],
            ["id"],
        )
    )
    new_move_ids = list(after_move_ids - before_move_ids)
    if new_move_ids:
        client.write("stock.move", new_move_ids, {"date": timestamp.strftime("%Y-%m-%d %H:%M:%S")})

    qty_after = client.get_on_hand_qty(product_id, location_id)

    return Event(
        source="erp",
        entity_id=f"{product_sku}@{location_name}",
        field="qty_on_hand",
        expected_value=qty_before,
        actual_value=wrong_qty,
        timestamp=timestamp.isoformat(),
        anomaly_type="quantity_mismatch",
        product=product_sku,
        location=location_name,
        qty_before_injection=qty_before,
        qty_after_injection=qty_after,
    )


def inject_duplicate_entry(client, model, vals, reference, timestamp):
    """Create the same order twice — same partner, product, qty, date.
    entity_id is the original record; duplicate_of is the new record created
    here, so both references are directly readable from one ground-truth entry.
    """
    dup_id = client.create(model, vals)
    dup_reference = client.search_read(model, [["id", "=", dup_id]], ["name"])[0]["name"]
    return dup_id, Event(
        source="erp",
        entity_id=reference,
        field="order_count",
        expected_value=1,
        actual_value=2,
        timestamp=timestamp.isoformat(),
        anomaly_type="duplicate_entry",
        duplicate_of=dup_reference,
    )


def inject_delayed_delivery(client, picking_id, reference, scheduled_date, timestamp):
    """Push a picking's actual completion date well past its scheduled date."""
    delay_days = random.randint(5, 15)
    actual_date = scheduled_date + timedelta(days=delay_days)
    client.write("stock.picking", [picking_id], {"date_done": actual_date.isoformat(sep=" ")})

    return Event(
        source="erp",
        entity_id=reference,
        field="date_done",
        expected_value=scheduled_date.isoformat(),
        actual_value=actual_date.isoformat(),
        timestamp=timestamp.isoformat(),
        anomaly_type="delayed_delivery",
    )
