"""
The shared event schema — ERP discrepancies, human failure reports, and
(later) sensor readings all normalize to this shape before diagnosis/
ticketing logic ever sees them. Matches the shape used in
data-gen/output/ground_truth.json so the eval script can compare detected
events against ground truth without translation.
"""
from typing import Any, Literal

from pydantic import BaseModel


class DiscrepancyEvent(BaseModel):
    source: Literal["erp", "human_report", "sensor"]
    entity_id: str
    field: str
    expected_value: Any
    actual_value: Any
    timestamp: str

    anomaly_type: str | None = None
    product: str | None = None
    location: str | None = None
    duplicate_of: str | None = None
