"""
Rule-based detection logic — one function per anomaly type from Day 2's
anomaly injector (see data-gen/anomalies.py and output/ground_truth.json).
Each function takes plain dicts from the odoo_fetch layer and returns a list
of DiscrepancyEvent. No Odoo calls happen in here — fetching and detecting
are kept separate so each rule can be unit-tested against fixture data.
"""
from collections import defaultdict
from datetime import datetime, timedelta

from schemas import DiscrepancyEvent

STUCK_ORDER_BUFFER_DAYS = 2
DELAYED_DELIVERY_THRESHOLD_DAYS = 4
DUPLICATE_ORDER_WINDOW_DAYS = 2
QUANTITY_MISMATCH_TOLERANCE = 0.5


def _parse_dt(value: str | bool | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def _m2o_id(value) -> int | None:
    """Odoo many2one fields come back as [id, display_name] or False."""
    return value[0] if value else None


def detect_stuck_orders(
    pickings: list[dict],
    reference_date: datetime | None = None,
    buffer_days: int = STUCK_ORDER_BUFFER_DAYS,
) -> list[DiscrepancyEvent]:
    """Flag receipts/deliveries whose scheduled date is already well in the
    past but which never reached state "done". `pickings` is the concatenation
    of fetch_incoming_receipts() and fetch_outgoing_deliveries() results.

    `reference_date` is what "overdue" is measured against. Defaults to real
    wall-clock time, which is genuinely correct for a live system watching a
    real ERP. The eval script must instead pass the fixed date the dataset
    was generated through (ground_truth.json's "generated_through") — using
    real "now" there would make precision/recall drift as time passes, since
    orders creep further "overdue" the longer you wait to run the eval.
    """
    reference_date = reference_date or datetime.now()
    events = []
    for picking in pickings:
        if picking["state"] in ("done", "cancel"):
            continue
        scheduled = _parse_dt(picking.get("scheduled_date"))
        if scheduled is None:
            continue
        if reference_date - scheduled > timedelta(days=buffer_days):
            events.append(
                DiscrepancyEvent(
                    source="erp",
                    entity_id=picking.get("origin") or picking["name"],
                    field="state",
                    expected_value="done",
                    actual_value=picking["state"],
                    timestamp=scheduled.isoformat(),
                    anomaly_type="stuck_order",
                )
            )
    return events


def detect_delayed_deliveries(
    pickings: list[dict], threshold_days: int = DELAYED_DELIVERY_THRESHOLD_DAYS
) -> list[DiscrepancyEvent]:
    """Flag completed receipts/deliveries whose actual completion date landed
    well past their scheduled date. `pickings` is the concatenation of
    fetch_incoming_receipts() and fetch_outgoing_deliveries() results.
    """
    events = []
    for picking in pickings:
        if picking["state"] != "done":
            continue
        scheduled = _parse_dt(picking.get("scheduled_date"))
        done = _parse_dt(picking.get("date_done"))
        if scheduled is None or done is None:
            continue
        if done - scheduled > timedelta(days=threshold_days):
            events.append(
                DiscrepancyEvent(
                    source="erp",
                    entity_id=picking.get("origin") or picking["name"],
                    field="date_done",
                    expected_value=scheduled.isoformat(),
                    actual_value=done.isoformat(),
                    timestamp=scheduled.isoformat(),
                    anomaly_type="delayed_delivery",
                )
            )
    return events


def detect_duplicate_orders(
    orders: list[dict],
    order_lines: list[dict],
    qty_field: str = "product_qty",
    window_days: int = DUPLICATE_ORDER_WINDOW_DAYS,
) -> list[DiscrepancyEvent]:
    """Flag pairs of orders (purchase or sales) with the same vendor/customer,
    the same product/quantity line(s), and order dates close together.
    `order_lines` must be the matching *.order.line fetch (product_qty for
    purchase.order.line, product_uom_qty for sale.order.line — pass via
    qty_field).
    """
    lines_by_order = defaultdict(list)
    for line in order_lines:
        order_id = _m2o_id(line["order_id"])
        if order_id is not None:
            lines_by_order[order_id].append((_m2o_id(line["product_id"]), line[qty_field]))

    def signature(order_id: int) -> frozenset:
        return frozenset(lines_by_order.get(order_id, []))

    candidates = []
    for order in orders:
        date_order = _parse_dt(order.get("date_order"))
        partner_id = _m2o_id(order.get("partner_id"))
        if date_order is None or partner_id is None:
            continue
        candidates.append((order, date_order, partner_id, signature(order["id"])))

    candidates.sort(key=lambda c: c[1])

    events = []
    flagged_ids = set()
    for i, (order, date_order, partner_id, sig) in enumerate(candidates):
        if order["id"] in flagged_ids or not sig:
            continue
        for other, other_date, other_partner, other_sig in candidates[i + 1 :]:
            if other_date - date_order > timedelta(days=window_days):
                break
            if other["id"] in flagged_ids:
                continue
            if other_partner == partner_id and other_sig == sig:
                events.append(
                    DiscrepancyEvent(
                        source="erp",
                        entity_id=order["name"],
                        field="order_count",
                        expected_value=1,
                        actual_value=2,
                        timestamp=date_order.isoformat(),
                        anomaly_type="duplicate_entry",
                        duplicate_of=other["name"],
                    )
                )
                flagged_ids.add(order["id"])
                flagged_ids.add(other["id"])
                break
    return events


def detect_quantity_mismatches(
    quants: list[dict],
    moves: list[dict],
    internal_locations: list[dict],
    products: list[dict],
    tolerance: float = QUANTITY_MISMATCH_TOLERANCE,
) -> list[DiscrepancyEvent]:
    """Flag quants at real physical locations whose actual on-hand quantity
    drifts from the quantity implied by the completed-move ledger (`moves`
    must already be filtered to state=done and exclude quant-adjustment
    moves — see fetch_stock_moves). `internal_locations` restricts the check
    to physical locations (usage="internal"), excluding virtual accounting
    locations that legitimately carry large positive/negative balances.
    """
    internal_location_ids = {loc["id"] for loc in internal_locations}
    location_names = {loc["id"]: loc["name"] for loc in internal_locations}
    product_skus = {p["id"]: p["default_code"] for p in products}

    ledger = defaultdict(float)
    for move in moves:
        product_id = _m2o_id(move["product_id"])
        dest_id = _m2o_id(move["location_dest_id"])
        src_id = _m2o_id(move["location_id"])
        qty = move["quantity"]
        if dest_id in internal_location_ids:
            ledger[(product_id, dest_id)] += qty
        if src_id in internal_location_ids:
            ledger[(product_id, src_id)] -= qty

    events = []
    for quant in quants:
        location_id = _m2o_id(quant["location_id"])
        if location_id not in internal_location_ids:
            continue
        product_id = _m2o_id(quant["product_id"])
        actual = quant["quantity"]
        expected = ledger.get((product_id, location_id), 0.0)
        if abs(actual - expected) > tolerance:
            sku = product_skus.get(product_id) or str(product_id)
            location_name = location_names.get(location_id, str(location_id))
            events.append(
                DiscrepancyEvent(
                    source="erp",
                    entity_id=f"{sku}@{location_name}",
                    field="qty_on_hand",
                    expected_value=expected,
                    actual_value=actual,
                    timestamp=datetime.now().isoformat(),
                    anomaly_type="quantity_mismatch",
                    product=sku,
                    location=location_name,
                )
            )
    return events
