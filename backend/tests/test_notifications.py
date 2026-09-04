"""
Tests for notifications.py's Slack webhook notifier — both the "no webhook
configured" fallback and the actual post, with requests.post mocked out
(no real network call).
"""
import notifications


def _sample_diagnosis():
    return {
        "event": {"entity_id": "P00003", "anomaly_type": "stuck_order", "source": "erp"},
        "context": {},
        "report": {
            "likely_cause": "Order stalled.",
            "confidence": "medium",
            "recommended_action": "Check the picking.",
        },
    }


def test_notify_ticket_skips_when_no_webhook_configured(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)

    sent = notifications.notify_ticket(_sample_diagnosis())

    assert sent is False


def test_notify_ticket_posts_when_webhook_configured(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.com/test")

    calls = []

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_post(url, json, timeout):
        calls.append((url, json, timeout))
        return FakeResponse()

    monkeypatch.setattr(notifications.requests, "post", fake_post)

    sent = notifications.notify_ticket(_sample_diagnosis())

    assert sent is True
    assert len(calls) == 1
    url, payload, _ = calls[0]
    assert url == "https://hooks.example.com/test"
    assert "P00003" in payload["text"]
    assert "stuck_order" in payload["text"]
