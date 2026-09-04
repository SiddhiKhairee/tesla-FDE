"""
Adapter for Version B's intake path: translates a human's plain-language
floor report into the shared DiscrepancyEvent shape — the same schema
detection.py's ERP rules produce — so diagnosis.py, ticketing, and
notification logic run unchanged regardless of source.
"""
from schemas import DiscrepancyEvent, FailureReportIn


def report_to_event(report: FailureReportIn) -> DiscrepancyEvent:
    return DiscrepancyEvent(
        source="human_report",
        entity_id=report.machine,
        field="equipment_status",
        expected_value="normal_operation",
        actual_value=report.issue,
        timestamp=report.timestamp,
        anomaly_type="equipment_failure",
        location=report.machine,
    )
