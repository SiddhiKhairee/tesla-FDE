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

    def to_dict(self):
        return asdict(self)
