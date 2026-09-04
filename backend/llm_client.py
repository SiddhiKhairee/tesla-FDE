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
import os
from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel

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


class DiagnosisReport(BaseModel):
    likely_cause: str
    reasoning: str
    confidence: Literal["low", "medium", "high"]
    recommended_action: str


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
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": json.dumps({"event": event, "context": context}, default=str),
                }
            ],
            output_format=DiagnosisReport,
        )
        return response.parsed_output


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
                system_instruction=SYSTEM_PROMPT,
                temperature=0,
                response_mime_type="application/json",
                response_schema=DiagnosisReport,
            ),
        )
        # Parse from the raw JSON text rather than relying on response.parsed
        # (a convenience field whose availability has shifted across SDK
        # versions) — response_mime_type + response_schema already guarantee
        # response.text is JSON matching DiagnosisReport's shape.
        return DiagnosisReport.model_validate_json(response.text)


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
        )


def get_diagnosis_llm() -> DiagnosisLLM:
    """Gemini first (the chosen free-tier provider), then Anthropic if
    somehow configured instead, otherwise the free stub. This is the one
    place that needs to change when the provider changes again.
    """
    if os.environ.get("GEMINI_API_KEY"):
        return GeminiDiagnosisLLM()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicDiagnosisLLM()
    return StubDiagnosisLLM()
