"""
Slack webhook notifier — the "auto-notifies the team" half of Version B,
replacing the manual step Astin described (someone typing what they saw
into Slack themselves) with the diagnosis engine posting a structured
message once a report has been through gather_context + diagnose.

SLACK_WEBHOOK_URL is optional: with none configured (local dev, CI, before
a real Slack workspace is wired up) send_to_slack logs what it would have
sent and returns False instead of erroring — same fallback pattern as
llm_client.get_diagnosis_llm() falling back to the stub when no provider
key is set.

`send_to_slack` is the one webhook mechanism this codebase has — both
Version B's ticket notifications and Version A's sensor-anomaly alerts
(sensor_detection_version_a.md Section 6, see demo_live_sim.py) funnel
through it. Only the message *formatting* differs per source
(_format_ticket_message vs. _format_sensor_message), since Section 6
specifies its own template distinct from Version B's ticket format — the
actual SLACK_WEBHOOK_URL check / requests.post call is never duplicated.
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


def _format_sensor_message(entity_id: str, context: dict, report: dict) -> dict:
    """Version A's sensor-alert template — sensor_detection_version_a.md
    Section 6's exact format, using the agent's own output only (`report`
    is a DiagnosisReport.model_dump()-shaped dict) plus the deviation
    evidence already computed for the bundle (`context["deviating_sensors"]`)
    — never AI4I's Machine failure/TWF/HDF/PWF/OSF/RNF ground-truth columns,
    which never reach this function in the first place.
    """
    lines = [f":warning: Machine {entity_id} — anomaly detected", "", "Sensor readings deviating from normal baseline:"]
    for dev in context["deviating_sensors"]:
        lines.append(
            f"  {dev['sensor']}: {dev['value']:.2f} "
            f"(normal range: ~{dev['baseline_mean']:.2f} ± {dev['baseline_std']:.2f})"
        )
    lines += [
        "",
        f"Likely failure type: {report['predicted_failure_type']}",
        f"Diagnosis: {report['reasoning']}",
        f"Suggested action: {report['recommended_action']}",
        f"Confidence: {report['confidence']}",
    ]
    return {"text": "\n".join(lines)}


def send_to_slack(payload: dict, *, entity_id_for_log: str) -> bool:
    """The actual webhook mechanism — the one thing every notification path
    in this codebase shares. Returns True if a webhook call was actually
    made, False if it was skipped (no URL configured).
    """
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        logger.info("SLACK_WEBHOOK_URL not set — skipping notification for %s", entity_id_for_log)
        return False

    response = requests.post(webhook_url, json=payload, timeout=5)
    response.raise_for_status()
    return True


def notify_ticket(diagnosis: dict) -> bool:
    """Post one diagnosed event/ticket to Slack — Version B's format."""
    return send_to_slack(_format_ticket_message(diagnosis), entity_id_for_log=diagnosis["event"]["entity_id"])


def notify_sensor_alert(entity_id: str, context: dict, report: dict) -> bool:
    """Post one sensor anomaly alert to Slack — Version A's format
    (sensor_detection_version_a.md Section 6). See demo_live_sim.py for
    the caller that builds `context`/`report`.
    """
    return send_to_slack(_format_sensor_message(entity_id, context, report), entity_id_for_log=entity_id)
