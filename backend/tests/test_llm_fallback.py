"""
Tests for GeminiGroqStubFallbackLLM: the narrow, quota-only fallback chain
Gemini -> Groq -> StubDiagnosisLLM. Both real providers are mocked out — no
network call, no API key needed — so every branch is exercised
deterministically rather than depending on real free-tier quotas being
exhausted (or not) whenever this runs.
"""
import httpx
import pytest
from google.genai import errors as genai_errors
from groq import RateLimitError as GroqRateLimitError

from llm_client import DiagnosisReport, GeminiGroqStubFallbackLLM


class _FakeResponse:
    status_code = 429


def _gemini_quota_error() -> genai_errors.ClientError:
    return genai_errors.ClientError(
        429,
        {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "quota exceeded"}},
        _FakeResponse(),
    )


def _gemini_auth_error() -> genai_errors.ClientError:
    return genai_errors.ClientError(
        401,
        {"error": {"code": 401, "status": "UNAUTHENTICATED", "message": "bad API key"}},
        _FakeResponse(),
    )


def _fake_httpx_response(status_code: int) -> httpx.Response:
    # groq's APIStatusError.__init__ reads response.request and
    # response.status_code, so a real httpx.Response (not a bare stub) is
    # needed here.
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return httpx.Response(status_code, request=request)


def _groq_rate_limit_error() -> GroqRateLimitError:
    return GroqRateLimitError(
        message="rate limit exceeded",
        response=_fake_httpx_response(429),
        body={"error": {"message": "rate limit exceeded"}},
    )


def _groq_auth_error():
    from groq import AuthenticationError as GroqAuthenticationError

    return GroqAuthenticationError(
        message="bad API key",
        response=_fake_httpx_response(401),
        body={"error": {"message": "bad API key"}},
    )


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
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-test")
    instance = GeminiGroqStubFallbackLLM()
    return instance


def test_returns_gemini_report_when_call_succeeds(wrapper, monkeypatch):
    monkeypatch.setattr(wrapper._gemini, "generate", lambda event, context: _fake_report("gemini"))

    report = wrapper.generate({"entity_id": "P00001", "anomaly_type": "stuck_order"}, {})

    assert report.llm_used == "gemini"


def test_gemini_quota_exhausted_falls_back_to_groq(wrapper, monkeypatch):
    def raise_quota_error(event, context):
        raise _gemini_quota_error()

    monkeypatch.setattr(wrapper._gemini, "generate", raise_quota_error)
    monkeypatch.setattr(wrapper._groq, "generate", lambda event, context: _fake_report("groq"))

    report = wrapper.generate({"entity_id": "P00001", "anomaly_type": "stuck_order"}, {})

    assert report.llm_used == "groq"


def test_gemini_and_groq_quota_exhausted_falls_back_to_stub(wrapper, monkeypatch):
    def raise_gemini_quota_error(event, context):
        raise _gemini_quota_error()

    def raise_groq_rate_limit_error(event, context):
        raise _groq_rate_limit_error()

    monkeypatch.setattr(wrapper._gemini, "generate", raise_gemini_quota_error)
    monkeypatch.setattr(wrapper._groq, "generate", raise_groq_rate_limit_error)

    report = wrapper.generate({"entity_id": "P00001", "anomaly_type": "stuck_order"}, {})

    assert report.llm_used == "stub"


def test_reraises_non_quota_gemini_errors(wrapper, monkeypatch):
    def raise_auth_error(event, context):
        raise _gemini_auth_error()

    monkeypatch.setattr(wrapper._gemini, "generate", raise_auth_error)

    with pytest.raises(genai_errors.ClientError):
        wrapper.generate({"entity_id": "P00001", "anomaly_type": "stuck_order"}, {})


def test_reraises_non_quota_groq_errors(wrapper, monkeypatch):
    from groq import AuthenticationError as GroqAuthenticationError

    def raise_gemini_quota_error(event, context):
        raise _gemini_quota_error()

    def raise_groq_auth_error(event, context):
        raise _groq_auth_error()

    monkeypatch.setattr(wrapper._gemini, "generate", raise_gemini_quota_error)
    monkeypatch.setattr(wrapper._groq, "generate", raise_groq_auth_error)

    with pytest.raises(GroqAuthenticationError):
        wrapper.generate({"entity_id": "P00001", "anomaly_type": "stuck_order"}, {})
