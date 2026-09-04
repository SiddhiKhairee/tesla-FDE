"""
Unit tests for detection.py's rule-based detectors — the ERP path (Version
A's core, and the shared engine's other half from Version B). Pure fixture
dicts shaped like odoo_fetch.py's output; no live Odoo needed.
"""
from datetime import datetime

from detection import (
    detect_delayed_deliveries,
    detect_duplicate_orders,
    detect_quantity_mismatches,
    detect_stuck_orders,
)


def test_detect_stuck_orders_flags_overdue_incomplete_picking():
    pickings = [
        {"name": "WH/IN/00001", "origin": "P00001", "state": "assigned", "scheduled_date": "2026-01-01 00:00:00"},
    ]
    reference_date = datetime(2026, 3, 1)

    events = detect_stuck_orders(pickings, reference_date=reference_date)

    assert len(events) == 1
    assert events[0].entity_id == "P00001"
    assert events[0].anomaly_type == "stuck_order"


def test_detect_stuck_orders_ignores_done_and_recent():
    pickings = [
        {"name": "WH/IN/00002", "origin": "P00002", "state": "done", "scheduled_date": "2026-01-01 00:00:00"},
        {"name": "WH/IN/00003", "origin": "P00003", "state": "assigned", "scheduled_date": "2026-02-27 00:00:00"},
    ]
    reference_date = datetime(2026, 3, 1)

    events = detect_stuck_orders(pickings, reference_date=reference_date)

    assert events == []


def test_detect_delayed_deliveries_flags_late_completion():
    pickings = [
        {
            "name": "WH/OUT/00001",
            "origin": "S00001",
            "state": "done",
            "scheduled_date": "2026-01-01 00:00:00",
            "date_done": "2026-01-10 00:00:00",
        },
    ]

    events = detect_delayed_deliveries(pickings, threshold_days=4)

    assert len(events) == 1
    assert events[0].anomaly_type == "delayed_delivery"


def test_detect_duplicate_orders_flags_matching_pair():
    orders = [
        {"id": 1, "name": "P00010", "date_order": "2026-01-01 00:00:00", "partner_id": [5, "Acme"]},
        {"id": 2, "name": "P00011", "date_order": "2026-01-02 00:00:00", "partner_id": [5, "Acme"]},
    ]
    order_lines = [
        {"order_id": [1, "P00010"], "product_id": [100, "SKU-1"], "product_qty": 10.0},
        {"order_id": [2, "P00011"], "product_id": [100, "SKU-1"], "product_qty": 10.0},
    ]

    events = detect_duplicate_orders(orders, order_lines, qty_field="product_qty")

    assert len(events) == 1
    assert events[0].anomaly_type == "duplicate_entry"
    assert {events[0].entity_id, events[0].duplicate_of} == {"P00010", "P00011"}


def test_detect_duplicate_orders_ignores_different_products():
    orders = [
        {"id": 1, "name": "P00010", "date_order": "2026-01-01 00:00:00", "partner_id": [5, "Acme"]},
        {"id": 2, "name": "P00011", "date_order": "2026-01-02 00:00:00", "partner_id": [5, "Acme"]},
    ]
    order_lines = [
        {"order_id": [1, "P00010"], "product_id": [100, "SKU-1"], "product_qty": 10.0},
        {"order_id": [2, "P00011"], "product_id": [200, "SKU-2"], "product_qty": 10.0},
    ]

    events = detect_duplicate_orders(orders, order_lines, qty_field="product_qty")

    assert events == []


def test_detect_quantity_mismatches_flags_drift_beyond_tolerance():
    internal_locations = [{"id": 1, "name": "WH/Stock", "usage": "internal"}]
    products = [{"id": 100, "default_code": "SKU-1"}]
    moves = [
        {"product_id": [100, "SKU-1"], "location_dest_id": [1, "WH/Stock"], "location_id": [99, "Vendors"], "quantity": 10.0},
    ]
    quants = [{"product_id": [100, "SKU-1"], "location_id": [1, "WH/Stock"], "quantity": 7.0}]

    events = detect_quantity_mismatches(quants, moves, internal_locations, products, tolerance=0.5)

    assert len(events) == 1
    assert events[0].anomaly_type == "quantity_mismatch"
    assert events[0].expected_value == 10.0
    assert events[0].actual_value == 7.0


def test_detect_quantity_mismatches_within_tolerance_is_clean():
    internal_locations = [{"id": 1, "name": "WH/Stock", "usage": "internal"}]
    products = [{"id": 100, "default_code": "SKU-1"}]
    moves = [
        {"product_id": [100, "SKU-1"], "location_dest_id": [1, "WH/Stock"], "location_id": [99, "Vendors"], "quantity": 10.0},
    ]
    quants = [{"product_id": [100, "SKU-1"], "location_id": [1, "WH/Stock"], "quantity": 10.2}]

    events = detect_quantity_mismatches(quants, moves, internal_locations, products, tolerance=0.5)

    assert events == []
