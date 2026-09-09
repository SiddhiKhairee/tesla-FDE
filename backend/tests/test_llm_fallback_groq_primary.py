"""
Tests for GroqGeminiStubFallbackLLM: the Groq-primary fallback chain
Groq -> Gemini -> StubDiagnosisLLM, used by get_diagnosis_llm() since the
Groq-primary switch. Unlike the older, narrower GeminiGroqStubFallbackLLM
(quota-only fallback, see test_llm_fallback.py), this chain falls through
on ANY failure from the primary/secondary provider, not just a 429 — so
these tests cover a non-quota error (a plain connection/500-style failure)
falling through too, not just the rate-limit case.

Both real providers are mocked out — no network call, no API key needed —
so every branch is exercised deterministically.
"""
import httpx
import pytest
from groq import APIConnectionError as GroqAPIConnectionError
from groq import RateLimitError as GroqRateLimitError

from llm_client import DiagnosisReport, GeminiDiagnosisLLM, GroqGeminiStubFallbackLLM


def _fake_httpx_request() -> httpx.Request:
    return httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


def _groq_rate_limit_error() -> GroqRateLimitError:
    request = _fake_httpx_request()
    response = httpx.Response(429, request=request)
    return GroqRateLimitError(
        message="rate limit exceeded",
        response=response,
        body={"error": {"message": "rate limit exceeded"}},
    )


def _groq_connection_error() -> GroqAPIConnectionError:
    # Not a quota error at all — a plain network failure, the exact class
    # of thing the old quota-only chain would have let propagate as a 500.
    return GroqAPIConnectionError(request=_fake_httpx_request())


def _gemini_server_error() -> Exception:
    # Stands in for a Gemini 503 overload — any real exception works here
    # since the broadened chain catches by type Exception, not by field.
    return RuntimeError("503 UNAVAILABLE: model overloaded")


def _fake_report(llm_used) -> DiagnosisReport:
    return DiagnosisReport(
        likely_cause="cause",
        reasoning="reasoning",
        confidence="high",
        recommended_action="action",
        llm_used=llm_used,
    )


@pytest.fixture
def wrapper(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-test")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    instance = GroqGeminiStubFallbackLLM()
    return instance


def test_returns_groq_report_when_call_succeeds(wrapper, monkeypatch):
    monkeypatch.setattr(wrapper._groq, "generate", lambda event, context: _fake_report("groq"))

    report = wrapper.generate({"entity_id": "P00001", "anomaly_type": "stuck_order"}, {})

    assert report.llm_used == "groq"


def test_groq_rate_limit_falls_back_to_gemini(wrapper, monkeypatch):
    """wrapper._gemini is lazily constructed (see llm_client.py) — it's
    still None at fixture-build time, so the fallback tier must be patched
    on the class, not the not-yet-existing instance."""

    def raise_rate_limit(event, context):
        raise _groq_rate_limit_error()

    monkeypatch.setattr(wrapper._groq, "generate", raise_rate_limit)
    monkeypatch.setattr(GeminiDiagnosisLLM, "generate", lambda self, event, context: _fake_report("gemini"))

    report = wrapper.generate({"entity_id": "P00001", "anomaly_type": "stuck_order"}, {})

    assert report.llm_used == "gemini"


def test_groq_non_quota_failure_also_falls_back_to_gemini(wrapper, monkeypatch):
    """The behavior change from the old chain: a non-429 failure (a
    connection error here, standing in for the reproduced Gemini-side 503
    that motivated this) must fall through too, not propagate as a 500."""

    def raise_connection_error(event, context):
        raise _groq_connection_error()

    monkeypatch.setattr(wrapper._groq, "generate", raise_connection_error)
    monkeypatch.setattr(GeminiDiagnosisLLM, "generate", lambda self, event, context: _fake_report("gemini"))

    report = wrapper.generate({"entity_id": "P00001", "anomaly_type": "stuck_order"}, {})

    assert report.llm_used == "gemini"


def test_groq_and_gemini_both_failing_falls_back_to_stub(wrapper, monkeypatch):
    def raise_groq_error(event, context):
        raise _groq_connection_error()

    def raise_gemini_error(self, event, context):
        raise _gemini_server_error()

    monkeypatch.setattr(wrapper._groq, "generate", raise_groq_error)
    monkeypatch.setattr(GeminiDiagnosisLLM, "generate", raise_gemini_error)

    report = wrapper.generate({"entity_id": "P00001", "anomaly_type": "stuck_order"}, {})

    assert report.llm_used == "stub"


def test_groq_fails_and_gemini_key_unset_skips_straight_to_stub(monkeypatch):
    """Reproduces the actual production bug: GROQ_API_KEY set, GEMINI_API_KEY
    entirely unset. Groq failing must fall through to the stub without ever
    constructing GeminiDiagnosisLLM (which would KeyError on the missing key)."""
    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-test")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    instance = GroqGeminiStubFallbackLLM()

    def raise_groq_error(event, context):
        raise _groq_connection_error()

    monkeypatch.setattr(instance._groq, "generate", raise_groq_error)

    report = instance.generate({"entity_id": "P00001", "anomaly_type": "stuck_order"}, {})

    assert report.llm_used == "stub"
    assert instance._gemini is None
