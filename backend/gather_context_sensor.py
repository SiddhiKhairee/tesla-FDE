"""
Sensor-path domain knowledge for the diagnosis agent — the equivalent of
detection.py's fixed stuck_order/delayed_delivery/duplicate_entry/
quantity_mismatch vocabulary, but for Version A's sensor failure modes (see
sensor_detection_version_a.md Section 2). Handed to the agent up front as
known categories to classify into, same pattern as the ERP path, rather than
having it invent categories per event.

Descriptions are written at the level a reliability engineer would use in
practice — which sensors tend to be involved, roughly which direction —
*not* AI4I's literal numeric label-generation formulas (e.g. HDF's actual
trigger is temperature differential < 8.6K and rpm < 1380). Handing the
agent the dataset's exact answer key would turn diagnosis into a lookup
against known thresholds instead of reasoning from the deviation evidence,
which defeats the point of running it through an LLM at all.
"""

SENSOR_FAILURE_TAXONOMY: dict[str, dict[str, str]] = {
    "TWF": {
        "name": "Tool Wear Failure",
        "description": (
            "Cutting/forming tools degrade with accumulated use and are typically retired "
            "or replaced past a wear threshold. Usually shows up as elevated tool wear time "
            "relative to normal, sometimes alongside torque irregularities as a worn tool "
            "cuts less cleanly."
        ),
    },
    "HDF": {
        "name": "Heat Dissipation Failure",
        "description": (
            "The process can't shed heat fast enough for how hard the machine is running — "
            "typically shows up as process or air temperature running high relative to "
            "rotational speed, i.e. heat building up without enough speed/airflow to carry "
            "it away."
        ),
    },
    "PWF": {
        "name": "Power Failure",
        "description": (
            "The mechanical power being delivered (roughly torque combined with rotational "
            "speed) falls outside what the process needs — either too little power to do the "
            "work, or the drive delivering more than intended and overloading."
        ),
    },
    "OSF": {
        "name": "Overstrain Failure",
        "description": (
            "The tool or workpiece is under more mechanical strain than it should be for its "
            "current wear state — typically higher torque combined with higher accumulated "
            "tool wear pushing the assembly past what it can reliably handle together."
        ),
    },
    "RNF": {
        "name": "Random Failure",
        "description": (
            "A failure with no identifiable sensor signature — occurs independent of any "
            "measured process variable. Not something a threshold-based sensor detector is "
            "expected to reliably catch, by definition, no matter how it's tuned."
        ),
    },
    "Unclear": {
        "name": "Unclear",
        "description": (
            "The deviation doesn't cleanly match the pattern typically associated with any "
            "single known failure category above. Use this rather than forcing a best guess "
            "into one of the five when the evidence is ambiguous or contradictory."
        ),
    },
}


def sensor_taxonomy_context() -> dict:
    """The taxonomy block to merge into the diagnosis agent's context —
    same role detection.py's anomaly_type vocabulary already plays for the
    ERP/human-report paths.
    """
    return {"failure_taxonomy": SENSOR_FAILURE_TAXONOMY}


def gather_sensor_context(entity_id: str, ranked_deviations: list[dict]) -> dict:
    """Context block for one flagged sensor row: the deviation evidence from
    sensor_adapter.rank_all_deviations (top-N columns by z-score magnitude,
    each carrying `crossed_threshold` — never AI4I's Machine failure/TWF/
    HDF/PWF/OSF/RNF ground-truth columns, which would leak the answer to
    the agent) plus the failure taxonomy it should classify against.

    `ranked_deviations` always carries at least one entry for any row with
    at least one valid baseline column, unlike the older threshold-only
    `detect_deviations` output — a row the v2 ML model flags via a
    combination that never crosses any single column's threshold still
    gets real evidence here (see sensor_adapter.MLGate), rather than an
    empty `deviating_sensors` list with nothing for the agent to reason
    from. Each entry's `note` is phrased honestly for which case applies:
    an actual threshold violation ("exceeded normal range") is worded
    differently from a reading that's merely the most unusual among
    several that never crossed anything ("furthest from normal, though
    not individually abnormal") — the point is real evidence without
    overstating what the z-score layer actually found.

    Mirrors diagnosis.py's `_gather_context` in shape (a plain dict handed
    to the diagnosis agent alongside the event) without touching that
    function — the ERP/human-report context-gathering stays exactly as it
    was, per sensor_detection_version_a.md's framing that Version A only
    adds a new adapter and a new context source.
    """
    context: dict = {
        "entity_id": entity_id,
        "deviating_sensors": [
            {
                "sensor": dev["column"],
                "value": dev["value"],
                "baseline_mean": dev["baseline_mean"],
                "baseline_std": dev["baseline_std"],
                "z_score": dev["z_score"],
                "direction": dev["direction"],
                "note": (
                    "exceeded normal range"
                    if dev["crossed_threshold"]
                    else "furthest from normal, though not individually abnormal"
                ),
            }
            for dev in ranked_deviations
        ],
    }
    context.update(sensor_taxonomy_context())
    return context
