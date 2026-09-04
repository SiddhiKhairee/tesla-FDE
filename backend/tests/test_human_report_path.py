"""
Tests for Version B's human-report path: the intake adapter, the
historical-incident similarity match, and the diagnosis engine wired
together with the free stub LLM (no network calls, no API key needed —
see llm_client.StubDiagnosisLLM).
"""
from diagnosis import diagnose_event
from historical_incidents import find_similar_incidents
from human_report import report_to_event
from schemas import FailureReportIn


def _incidents():
    return [
        {
            "id": "INC-100",
            "machine": "Cell Winder 3",
            "issue": "Winder jammed mid-cycle, tension arm not resetting",
            "notes": "",
            "resolution": "Replaced worn tension arm spring.",
            "reported_at": "2026-01-01T00:00:00",
        },
        {
            "id": "INC-101",
            "machine": "Busbar Welder A",
            "issue": "Weld quality inconsistent, several welds visibly cold",
            "notes": "",
            "resolution": "Realigned electrode after swap.",
            "reported_at": "2026-01-05T00:00:00",
        },
    ]


def test_report_to_event_shape():
    report = FailureReportIn(
        machine="Cell Winder 3",
        issue="Winder jammed, grinding noise",
        timestamp="2026-09-01T00:00:00",
    )

    event = report_to_event(report)

    assert event.source == "human_report"
    assert event.entity_id == "Cell Winder 3"
    assert event.anomaly_type == "equipment_failure"
    assert event.actual_value == "Winder jammed, grinding noise"


def test_find_similar_incidents_prioritizes_same_machine():
    matches = find_similar_incidents("Cell Winder 3", "Winder jammed again", _incidents())

    assert len(matches) == 1
    assert matches[0]["id"] == "INC-100"
    assert matches[0]["same_machine"] is True


def test_find_similar_incidents_no_match_for_unrelated_report():
    matches = find_similar_incidents("Vacuum Sealer 9", "Completely unrelated symptom text", _incidents())

    assert matches == []


def test_diagnose_event_uses_historical_match_in_stub_report():
    report = FailureReportIn(
        machine="Cell Winder 3",
        issue="Winder jammed mid-cycle again, tension arm stuck",
        timestamp="2026-09-01T00:00:00",
    )
    event = report_to_event(report)
    matches = find_similar_incidents(report.machine, report.issue, _incidents())

    result = diagnose_event(event, historical_matches=matches)

    assert result["context"]["similar_past_incidents"][0]["machine"] == "Cell Winder 3"
    assert "spring" in result["report"]["likely_cause"].lower()
    assert result["report"]["confidence"] in ("low", "medium", "high")


def test_diagnose_event_no_history_still_produces_report():
    report = FailureReportIn(
        machine="Robot Arm 9", issue="Sparks near the base joint", timestamp="2026-09-01T00:00:00"
    )
    event = report_to_event(report)

    result = diagnose_event(event, historical_matches=[])

    assert "similar_past_incidents" not in result["context"]
    assert result["report"]["confidence"] == "low"
