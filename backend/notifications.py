"""
Slack webhook notifier — the "auto-notifies the team" half of Version B,
replacing the manual step Astin described (someone typing what they saw
into Slack themselves) with the diagnosis engine posting a structured
message once a report has been through gather_context + diagnose.

SLACK_WEBHOOK_URL is optional: with none configured (local dev, CI, before
a real Slack workspace is wired up) notify_ticket logs what it would have
sent and returns False instead of erroring — same fallback pattern as
llm_client.get_diagnosis_llm() falling back to the stub when no provider
key is set.
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)


def _format_ticket_message(diagnosis: dict) -> dict:
    event = diagnosis["event"]
    report = diagnosis["report"]
    context = diagnosis["context"]

    lines = [
        f"*New reconciliation ticket* — `{event['entity_id']}` ({event.get('anomaly_type') or 'unclassified'})",
        f"*Source:* {event['source']}",
        f"*Likely cause:* {report['likely_cause']}",
        f"*Confidence:* {report['confidence']}",
        f"*Recommended action:* {report['recommended_action']}",
    ]
    similar = context.get("similar_past_incidents")
    if similar:
        top = similar[0]
        lines.append(
            f"*Similar past incident:* {top['machine']} — {top['issue']} "
            f"(resolved: {top['resolution']})"
        )

    return {"text": "\n".join(lines)}


def notify_ticket(diagnosis: dict) -> bool:
    """Post one diagnosed event/ticket to Slack. Returns True if a webhook
    call was actually made, False if it was skipped (no URL configured).
    """
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        logger.info(
            "SLACK_WEBHOOK_URL not set — skipping notification for %s",
            diagnosis["event"]["entity_id"],
        )
        return False

    response = requests.post(webhook_url, json=_format_ticket_message(diagnosis), timeout=5)
    response.raise_for_status()
    return True
