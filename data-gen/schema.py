"""
The shared event schema used across the whole project — ERP anomalies,
human failure reports, and (later) sensor readings all normalize to this
shape before diagnosis/ticketing logic ever sees them.
"""
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Event:
    source: str  # e.g. "erp"
    entity_id: str  # Odoo record id or human-readable reference (e.g. "PO00042")
    field: str  # the field that's wrong, e.g. "state", "qty_on_hand", "date_done"
    expected_value: Any
    actual_value: Any
    timestamp: str  # ISO 8601
    anomaly_type: str  # extra metadata beyond the core schema, useful for eval scoring
    duplicate_of: str | None = None  # for anomaly_type "duplicate_entry": the paired record's
    # own reference (entity_id holds the original; this holds the duplicate that was created)
    product: str | None = None  # for anomaly_type "quantity_mismatch": the product's SKU
    location: str | None = None  # for anomaly_type "quantity_mismatch": the location's name
    qty_before_injection: float | None = None  # for anomaly_type "quantity_mismatch": true on-hand
    # value read immediately before corruption — self-contained even if the live quant changes later
    qty_after_injection: float | None = None  # for anomaly_type "quantity_mismatch": corrupted value
    # read immediately after — should equal actual_value; both survive independent of live state

    def to_dict(self):
        return asdict(self)
