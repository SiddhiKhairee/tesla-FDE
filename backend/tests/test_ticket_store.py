"""
Tests for ticket_store.py — the JSON-file-backed persistence the dashboard
reads from. Each test points at its own temp file so tests don't share or
clobber backend/data/tickets.json.
"""
from ticket_store import list_tickets, save_ticket


def _sample_diagnosis(entity_id="P00003"):
    return {
        "event": {"entity_id": entity_id, "anomaly_type": "stuck_order", "source": "erp"},
        "context": {"days_overdue": 5},
        "report": {
            "likely_cause": "Order stalled.",
            "reasoning": "No movement in 5 days.",
            "confidence": "medium",
            "recommended_action": "Check the picking.",
        },
    }


def test_save_ticket_assigns_id_and_open_status(tmp_path):
    path = tmp_path / "tickets.json"

    ticket = save_ticket(_sample_diagnosis(), path=path)

    assert ticket["status"] == "open"
    assert ticket["id"]
    assert ticket["created_at"]
    assert ticket["event"]["entity_id"] == "P00003"


def test_list_tickets_returns_saved_tickets_newest_first(tmp_path):
    path = tmp_path / "tickets.json"

    first = save_ticket(_sample_diagnosis("P00001"), path=path)
    second = save_ticket(_sample_diagnosis("P00002"), path=path)

    tickets = list_tickets(path=path)

    assert [t["id"] for t in tickets] == [second["id"], first["id"]]


def test_list_tickets_empty_when_no_file(tmp_path):
    path = tmp_path / "nonexistent.json"

    assert list_tickets(path=path) == []
