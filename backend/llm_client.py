"""
Every provider-specific detail of the diagnosis LLM call lives here, and
nowhere else. diagnosis.py talks only to the `DiagnosisLLM` interface below
— it never imports a provider SDK or names a model directly. Gemini (free
tier) is the current live provider; Anthropic is kept as a working
reference implementation. Switching providers again means adding one more
`DiagnosisLLM` subclass here and pointing `get_diagnosis_llm()` at it —
nothing in diagnosis.py, main.py, or detection.py needs to change.

Providers differ in how they request structured output (Anthropic's
`messages.parse(output_format=...)`, Gemini's `response_schema`) — that's
exactly the kind of divergence this interface exists to absorb.
"""
import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a reconciliation assistant for a manufacturing \
ERP system (purchase orders, receipts, deliveries, stock on hand). You are \
given one flagged discrepancy event plus context facts computed from the \
current dataset (how overdue something is, whether similar events are \
happening elsewhere, drift magnitude, etc.).

Diagnose the most likely operational cause using only the facts given — do \
not invent details (vendors, employee names, root causes) that aren't \
supported by the event or context. If the context suggests a systemic issue \
(many similar events at once) versus an isolated one, say so explicitly and \
let it inform your confidence and recommended action. Keep the recommended \
action concrete enough that someone on the floor or in supply chain could \
act on it directly."""

# Version A (sensor path) only. SYSTEM_PROMPT above is written for the ERP/
# human-report paths (explicitly "reconciliation assistant for a
# manufacturing ERP system") and never mentions sensor readings, the
# failure taxonomy, or predicted_failure_type — using it unmodified for a
# sensor row would leave the model with no instruction to actually
# classify into TWF/HDF/PWF/OSF/RNF/Unclear, wasting real API calls on an
# uninstructed request. Selected automatically (see _select_system_prompt)
# whenever the context passed to generate() carries a "failure_taxonomy"
# key — a reliable signal this is a sensor-path call, since the ERP/
# human-report context-gathering never produces that key.
SENSOR_SYSTEM_PROMPT = """You are a predictive-maintenance assistant for industrial \
sensor telemetry (temperature, rotational speed, torque, tool wear, and derived \
composite readings such as mechanical power and strain). You are given one flagged \
sensor reading plus the deviation evidence a statistical detector already computed \
(which sensors were off, by how much, in which direction) and a fixed taxonomy of \
five known failure categories plus an "Unclear" fallback.

Classify the most likely failure category using only the deviation evidence and the \
taxonomy provided — do not invent sensor readings or failure mechanisms that aren't \
supported by the evidence. Set `predicted_failure_type` to the taxonomy code (TWF, \
HDF, PWF, OSF, or RNF) that best matches the evidence, or `Unclear` if the evidence \
doesn't cleanly fit any one category — do not force a best guess into one of the \
five when it doesn't fit. Each deviation's `note` distinguishes an actual threshold \
violation ("exceeded normal range") from a reading that's merely the most unusual \
among several that never crossed anything ("furthest from normal, though not \
individually abnormal") — that distinction is real evidence about how much the data \
actually supports any conclusion, and should inform your own self-reported \
confidence, not just your choice of category. Keep the recommended action concrete \
enough that a maintenance technician could act on it directly."""


def _select_system_prompt(context: dict) -> str:
    return SENSOR_SYSTEM_PROMPT if "failure_taxonomy" in context else SYSTEM_PROMPT


class DiagnosisReport(BaseModel):
    likely_cause: str
    reasoning: str
    confidence: Literal["low", "medium", "high"]
    recommended_action: str
    # Not part of what any provider is asked to produce (kept optional so it
    # never becomes a required field in a provider's structured-output
    # schema) — always set host-side, after generation, by whichever
    # DiagnosisLLM actually produced the report. Lets a caller tell real
    # model reasoning apart from the deterministic stub without reading logs.
    llm_used: Literal["gemini", "groq", "anthropic", "stub"] | None = None
    # Version A (sensor path) only — see sensor_detection_version_a.md
    # Section 3. Reusing this shared schema rather than forking a
    # sensor-specific one, per that doc's instruction not to fork if
    # avoidable: `likely_cause`/`reasoning`/`recommended_action` already
    # cover what the spec calls explanation/suggested_solution, and
    # `confidence` is kept categorical (not a separate 0-1/0-100 field) so
    # the same field means the same thing across every path instead of
    # forking its type per source — that's the "open decision" from
    # Section 8, locked in as categorical for schema consistency. The one
    # field with no ERP/human-report equivalent is `predicted_failure_type`,
    # added here, optional and unused by the other two paths. Diagnosis
    # *accuracy* (aggregate, ground-truth-validated, eval-only) is a
    # separate concept from this field and is never computed or stored here
    # — see eval_diagnosis.py (not yet built) for that number.
    predicted_failure_type: Literal["TWF", "HDF", "PWF", "OSF", "RNF", "Unclear"] | None = None


class _DiagnosisReportFields(BaseModel):
    """Same fields as DiagnosisReport, minus `llm_used`, all required.
    Groq's strict structured-output mode requires every schema property to
    be required (and disallows additionalProperties) — DiagnosisReport
    itself can't be used as-is because `llm_used` is optional. Groq
    responses are parsed against this narrower schema, then used to build
    a full DiagnosisReport with `llm_used` set host-side, same as every
    other provider.

    `predicted_failure_type` is required here (unlike on DiagnosisReport
    itself, where it's optional) purely because Groq's strict mode forces
    every declared property to be required — it was missed when this field
    was first added to DiagnosisReport, which meant Groq was never actually
    asked to produce it at all and every Groq-generated report silently
    carried `predicted_failure_type=None` regardless of what the model's
    own reasoning concluded. Fixed here; see the field's description for
    how a non-sensor (ERP/human-report) call is expected to fill it.
    """

    model_config = {"extra": "forbid"}

    likely_cause: str
    reasoning: str
    confidence: Literal["low", "medium", "high"]
    recommended_action: str
    predicted_failure_type: Literal["TWF", "HDF", "PWF", "OSF", "RNF", "Unclear"] = Field(
        description=(
            "Version A (sensor) field — classify into this taxonomy only when "
            "the context includes a failure_taxonomy block. For every other "
            "kind of diagnosis (ERP/human-report), set this to 'Unclear' — it "
            "has no meaning outside the sensor path and nothing there reads it."
        )
    )


class DiagnosisLLM(ABC):
    @abstractmethod
    def generate(self, event: dict, context: dict) -> DiagnosisReport: ...


class AnthropicDiagnosisLLM(DiagnosisLLM):
    def __init__(self, model: str = "claude-opus-5"):
        import anthropic

        self._client = anthropic.Anthropic()
        self._model = model

    def generate(self, event: dict, context: dict) -> DiagnosisReport:
        response = self._client.messages.parse(
            model=self._model,
            max_tokens=2000,
            system=_select_system_prompt(context),
            messages=[
                {
                    "role": "user",
                    "content": json.dumps({"event": event, "context": context}, default=str),
                }
            ],
            output_format=DiagnosisReport,
        )
        report = response.parsed_output
        report.llm_used = "anthropic"
        return report


class GeminiDiagnosisLLM(DiagnosisLLM):
    """Google Gemini free-tier implementation, via the google-genai SDK."""

    def __init__(self, model: str | None = None):
        from google import genai

        self._client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self._model = model or os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

    def generate(self, event: dict, context: dict) -> DiagnosisReport:
        from google.genai import types

        payload = json.dumps({"event": event, "context": context}, default=str)
        response = self._client.models.generate_content(
            model=self._model,
            contents=payload,
            config=types.GenerateContentConfig(
                system_instruction=_select_system_prompt(context),
                temperature=0,
                response_mime_type="application/json",
                response_schema=DiagnosisReport,
            ),
        )
        # Parse from the raw JSON text rather than relying on response.parsed
        # (a convenience field whose availability has shifted across SDK
        # versions) — response_mime_type + response_schema already guarantee
        # response.text is JSON matching DiagnosisReport's shape.
        report = DiagnosisReport.model_validate_json(response.text)
        report.llm_used = "gemini"
        return report


class GroqDiagnosisLLM(DiagnosisLLM):
    """Groq free-tier implementation, via the groq SDK. Used as the middle
    tier of the fallback chain (Gemini -> Groq -> stub) — see
    GeminiGroqStubFallbackLLM below.

    Model: openai/gpt-oss-120b. Chosen because it's one of the few models
    on Groq's free tier with `strict: true` structured-output support
    (constrained decoding — guaranteed schema adherence, not best-effort
    JSON matching), which this diagnosis pipeline depends on for reliable
    parsing. Confirmed free-tier limits: 30 RPM / 1,000 RPD / 8,000 TPM /
    200,000 TPD — well above what a single pipeline run (12 anomalies)
    needs.
    """

    def __init__(self, model: str | None = None):
        from groq import Groq

        self._client = Groq(api_key=os.environ["GROQ_API_KEY"])
        self._model = model or os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

    def generate(self, event: dict, context: dict) -> DiagnosisReport:
        payload = json.dumps({"event": event, "context": context}, default=str)
        response = self._client.chat.completions.create(
            model=self._model,
            temperature=0,
            messages=[
                {"role": "system", "content": _select_system_prompt(context)},
                {"role": "user", "content": payload},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "diagnosis_report",
                    "strict": True,
                    "schema": _DiagnosisReportFields.model_json_schema(),
                },
            },
        )
        fields = _DiagnosisReportFields.model_validate_json(response.choices[0].message.content)
        report = DiagnosisReport(**fields.model_dump(), llm_used="groq")
        return report


class StubDiagnosisLLM(DiagnosisLLM):
    """Deterministic, rule-based stand-in — no network call, no cost, no API
    key required. Used when no provider key is configured at all; kept
    around for offline/CI runs of the pipeline. Produces a plausible-shaped
    report from the same context facts a real model would see, so the
    pipeline's output shape is already correct.
    """

    def generate(self, event: dict, context: dict) -> DiagnosisReport:
        anomaly_type = event.get("anomaly_type")
        systemic = context.get("other_events_same_anomaly_type", 0) > 0

        if anomaly_type == "stuck_order":
            days = context.get("days_overdue", "an unknown number of")
            cause = (
                f"Order {event['entity_id']} is {days} days past its scheduled date "
                "and never reached a completed state — likely a stalled receipt/"
                "delivery step rather than a cancelled order."
            )
            action = "Check the picking's current stage in Odoo and confirm with the vendor/carrier."
        elif anomaly_type == "delayed_delivery":
            delay = context.get("delay_days", "an unknown number of")
            cause = f"Order {event['entity_id']} completed {delay} days late relative to its scheduled date."
            action = "Review lead time assumptions for this vendor/route; may need buffer adjustment."
        elif anomaly_type == "duplicate_entry":
            cause = (
                f"Order {event['entity_id']} appears to duplicate order "
                f"{event.get('duplicate_of')} — same partner, product, and quantity within days."
            )
            action = "Confirm with the requester whether both orders are intentional; cancel the duplicate if not."
        elif anomaly_type == "equipment_failure":
            similar = context.get("similar_past_incidents") or []
            cause = f"{event['entity_id']} reported as: {event.get('actual_value')}."
            if similar:
                top = similar[0]
                if top["same_machine"]:
                    cause += (
                        f" This machine had a similar issue before ('{top['issue']}'), "
                        f"resolved by: {top['resolution']}"
                    )
                else:
                    cause += (
                        f" A similar issue occurred on {top['machine']} before ('{top['issue']}'), "
                        f"resolved by: {top['resolution']}"
                    )
                action = f"Try the same fix that resolved the closest past incident ({top['machine']}); escalate if it doesn't apply."
                confidence = "medium" if top["match_score"] >= 0.7 else "low"
            else:
                action = "No similar past incident found — escalate to the equipment owner for manual diagnosis."
                confidence = "low"

            return DiagnosisReport(
                likely_cause=cause,
                reasoning=(
                    "[STUB — no LLM call made] Generated directly from computed context "
                    "fields as a placeholder until a provider is configured."
                ),
                confidence=confidence,
                recommended_action=action,
                llm_used="stub",
            )
        elif anomaly_type == "quantity_mismatch":
            direction = context.get("drift_direction", "a mismatch")
            pct = context.get("drift_pct_of_expected")
            pct_str = f"{pct:.1f}%" if isinstance(pct, (int, float)) else "an unknown %"
            cause = (
                f"{event.get('product', event['entity_id'])} shows {direction} of {pct_str} "
                "relative to the completed-move ledger."
            )
            action = "Run a physical cycle count at the affected location and compare against the ledger."
        else:
            cause = f"Unrecognized anomaly type for event {event['entity_id']}."
            action = "Escalate for manual review."

        if systemic:
            cause += " Other events of the same type are present in this batch, suggesting a systemic issue."
            confidence: Literal["low", "medium", "high"] = "medium"
        else:
            confidence = "low"

        return DiagnosisReport(
            likely_cause=cause,
            reasoning=(
                "[STUB — no LLM call made] Generated directly from computed context "
                "fields as a placeholder until a provider is configured."
            ),
            confidence=confidence,
            recommended_action=action,
            llm_used="stub",
        )


class GeminiGroqStubFallbackLLM(DiagnosisLLM):
    """Wraps GeminiDiagnosisLLM -> GroqDiagnosisLLM -> StubDiagnosisLLM,
    falling through the chain only on each provider's own quota/rate-limit
    error — an expected, temporary condition on a free tier, not a bug, so
    it shouldn't 500 the request. A diagnosis (even the deterministic stub
    one) is more useful to the caller than an error.

    Gemini quota exhaustion is `google.genai.errors.ClientError` with
    `code == 429` and `status == "RESOURCE_EXHAUSTED"` (Gemini overloads
    ClientError for several 4xx cases, so those two fields must both be
    checked). Groq quota exhaustion is `groq.RateLimitError` — Groq gives
    rate-limit errors their own exception class (distinct from
    BadRequestError/AuthenticationError/etc.), so no field-checking is
    needed there, just the type.

    Any other failure from either provider (bad API key, network error,
    malformed request, a non-429 API error) is re-raised as-is — those are
    real bugs that should surface, not get silently swallowed by the
    fallback.
    """

    def __init__(self):
        # Gemini is the primary tier here, so get_diagnosis_llm has already
        # confirmed GEMINI_API_KEY is set before selecting this class —
        # eager construction is safe. Groq/stub are only reached on
        # fallback, and GROQ_API_KEY is *not* guaranteed set in this branch
        # (get_diagnosis_llm only reaches it when GROQ_API_KEY was absent),
        # so both are constructed lazily, on first actual need — see the
        # GroqGeminiStubFallbackLLM fix below for why eager construction of
        # a fallback tier crashes the whole request when its key is unset.
        self._gemini = GeminiDiagnosisLLM()
        self._groq: GroqDiagnosisLLM | None = None
        self._stub: StubDiagnosisLLM | None = None

    def generate(self, event: dict, context: dict) -> DiagnosisReport:
        from google.genai import errors as genai_errors
        from groq import RateLimitError as GroqRateLimitError

        try:
            return self._gemini.generate(event, context)
        except genai_errors.ClientError as e:
            if not (e.code == 429 and e.status == "RESOURCE_EXHAUSTED"):
                raise
            logger.warning(
                "Gemini quota exhausted (429 RESOURCE_EXHAUSTED) for event %s — "
                "falling back to Groq for this request: %s",
                event.get("entity_id"),
                e,
            )

        if os.environ.get("GROQ_API_KEY"):
            if self._groq is None:
                self._groq = GroqDiagnosisLLM()
            try:
                return self._groq.generate(event, context)
            except GroqRateLimitError as e:
                logger.warning(
                    "Groq quota exhausted (429) for event %s — falling back to "
                    "StubDiagnosisLLM for this request: %s",
                    event.get("entity_id"),
                    e,
                )
        else:
            logger.info(
                "GROQ_API_KEY not set — skipping Groq fallback tier for event %s, "
                "going straight to StubDiagnosisLLM",
                event.get("entity_id"),
            )

        if self._stub is None:
            self._stub = StubDiagnosisLLM()
        return self._stub.generate(event, context)


class GroqGeminiStubFallbackLLM(DiagnosisLLM):
    """Wraps GroqDiagnosisLLM -> GeminiDiagnosisLLM -> StubDiagnosisLLM. Groq
    is now the primary provider for the ERP/Version B diagnosis path (see
    get_diagnosis_llm) — Gemini stays in the chain as a real fallback tier,
    not dropped, same two providers as GeminiGroqStubFallbackLLM above with
    the try order reversed.

    Unlike that narrower, quota-only chain, this one treats ANY failure
    from the primary/secondary provider as fall-through-worthy — a 503
    overload, a network error, a malformed response, not just a 429. This
    is the same philosophy as eval_diagnosis_sensor.py's
    probe_and_select_llm: a genuine failure of any kind means "this
    provider isn't answering right now," and the caller is better served by
    the next tier (down to the deterministic stub) than by a 500. This
    closes a real gap the narrower chain had — a reproduced Gemini 503
    propagated unhandled into a 500 because only the 429 RESOURCE_EXHAUSTED
    case was ever caught.
    """

    def __init__(self):
        # Groq is the primary tier here, so get_diagnosis_llm has already
        # confirmed GROQ_API_KEY is set before selecting this class —
        # eager construction is safe. Gemini/stub are only reached on
        # fallback, and GEMINI_API_KEY is NOT guaranteed set in this branch
        # (this is the primary diagnosis path in production, where only
        # GROQ_API_KEY is configured) — constructing GeminiDiagnosisLLM()
        # unconditionally here crashed every /reports/intake request with
        # KeyError: 'GEMINI_API_KEY', since __init__ ran in full before any
        # actual fallback was needed. Both are now constructed lazily, on
        # first actual need.
        self._groq = GroqDiagnosisLLM()
        self._gemini: GeminiDiagnosisLLM | None = None
        self._stub: StubDiagnosisLLM | None = None

    def generate(self, event: dict, context: dict) -> DiagnosisReport:
        try:
            return self._groq.generate(event, context)
        except Exception as e:  # noqa: BLE001 — any real failure falls through, not just quota
            logger.warning(
                "Groq failed (%s) for event %s — falling back to Gemini for this request: %s",
                type(e).__name__,
                event.get("entity_id"),
                e,
            )

        if os.environ.get("GEMINI_API_KEY"):
            if self._gemini is None:
                self._gemini = GeminiDiagnosisLLM()
            try:
                return self._gemini.generate(event, context)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "Gemini failed (%s) for event %s — falling back to StubDiagnosisLLM for this request: %s",
                    type(e).__name__,
                    event.get("entity_id"),
                    e,
                )
        else:
            logger.info(
                "GEMINI_API_KEY not set — skipping Gemini fallback tier for event %s, "
                "going straight to StubDiagnosisLLM",
                event.get("entity_id"),
            )

        if self._stub is None:
            self._stub = StubDiagnosisLLM()
        return self._stub.generate(event, context)


def get_diagnosis_llm() -> DiagnosisLLM:
    """Groq first — the primary provider for this path since the Groq-
    primary switch, wrapped with a fallback chain through Gemini then the
    stub (see GroqGeminiStubFallbackLLM) that catches any real failure, not
    just quota errors. Falls back to the older Gemini-primary chain if only
    a Gemini key is configured, then Anthropic if somehow configured
    instead, otherwise the free stub. This is the one place that needs to
    change when the provider changes again.
    """
    if os.environ.get("GROQ_API_KEY"):
        return GroqGeminiStubFallbackLLM()
    if os.environ.get("GEMINI_API_KEY"):
        return GeminiGroqStubFallbackLLM()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicDiagnosisLLM()
    return StubDiagnosisLLM()
