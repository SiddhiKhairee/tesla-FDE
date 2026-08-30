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


def inject_quantity_mismatch(client, product_id, location_id, reference, expected_qty, timestamp):
    """Directly corrupt the on-hand quantity for a product at a location via stock.quant."""
    quants = client.search_read(
        "stock.quant",
        [["product_id", "=", product_id], ["location_id", "=", location_id]],
        ["id", "quantity"],
        limit=1,
    )
    if not quants:
        return None

    quant_id = quants[0]["id"]
    drift = random.choice([-1, 1]) * random.randint(1, 5)
    wrong_qty = max(0, expected_qty + drift)
    client.write("stock.quant", [quant_id], {"inventory_quantity": wrong_qty})
    client.call_button("stock.quant", "action_apply_inventory", [quant_id])

    return Event(
        source="erp",
        entity_id=reference,
        field="qty_on_hand",
        expected_value=expected_qty,
        actual_value=wrong_qty,
        timestamp=timestamp.isoformat(),
        anomaly_type="quantity_mismatch",
    )


def inject_duplicate_entry(client, model, vals, reference, timestamp):
    """Create the same order twice — same partner, product, qty, date."""
    dup_id = client.create(model, vals)
    return dup_id, Event(
        source="erp",
        entity_id=reference,
        field="order_count",
        expected_value=1,
        actual_value=2,
        timestamp=timestamp.isoformat(),
        anomaly_type="duplicate_entry",
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
