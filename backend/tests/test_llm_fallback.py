"""
Tests for GeminiWithStubFallbackLLM: the narrow, quota-only fallback from
Gemini to StubDiagnosisLLM. Gemini itself is mocked out — no network call,
no API key needed — so both the "falls back" and "does NOT fall back"
branches are exercised deterministically rather than depending on the real
free-tier quota being exhausted (or not) whenever this runs.
"""
import pytest
from google.genai import errors

from llm_client import GeminiWithStubFallbackLLM


class _FakeResponse:
    status_code = 429


def _quota_error() -> errors.ClientError:
    return errors.ClientError(
        429,
        {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "quota exceeded"}},
        _FakeResponse(),
    )


def _auth_error() -> errors.ClientError:
    return errors.ClientError(
        401,
        {"error": {"code": 401, "status": "UNAUTHENTICATED", "message": "bad API key"}},
        _FakeResponse(),
    )


@pytest.fixture
def wrapper(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    instance = GeminiWithStubFallbackLLM()
    return instance


def test_falls_back_to_stub_on_quota_exhaustion(wrapper, monkeypatch):
    def raise_quota_error(event, context):
        raise _quota_error()

    monkeypatch.setattr(wrapper._gemini, "generate", raise_quota_error)

    report = wrapper.generate({"entity_id": "P00001", "anomaly_type": "stuck_order"}, {})

    assert report.llm_used == "stub"


def test_reraises_non_quota_client_errors(wrapper, monkeypatch):
    def raise_auth_error(event, context):
        raise _auth_error()

    monkeypatch.setattr(wrapper._gemini, "generate", raise_auth_error)

    with pytest.raises(errors.ClientError):
        wrapper.generate({"entity_id": "P00001", "anomaly_type": "stuck_order"}, {})


def test_returns_gemini_report_when_call_succeeds(wrapper, monkeypatch):
    from llm_client import DiagnosisReport

    def fake_generate(event, context):
        return DiagnosisReport(
            likely_cause="cause",
            reasoning="reasoning",
            confidence="high",
            recommended_action="action",
            llm_used="gemini",
        )

    monkeypatch.setattr(wrapper._gemini, "generate", fake_generate)

    report = wrapper.generate({"entity_id": "P00001", "anomaly_type": "stuck_order"}, {})

    assert report.llm_used == "gemini"
