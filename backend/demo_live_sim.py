"""
Section 6 live demo — sensor_detection_version_a.md, updated to reflect
what's actually been built since that section was written: "sensor
adapter (flag or not)" now means the v2 ML gate (MLGate / load_ml_gate()
from model_v2.pkl), not the original z-score threshold — the z-score/
derived-feature code (detect_deviations / rank_all_deviations) stays in
its current role, purely producing the deviating_sensors description via
gather_sensor_context(), same as every eval script already does.

Fixed-seed, stratified 20-row sample (8 real failures spanning as many
failure types as fit, 12 normal rows including 2 deliberately borderline),
run once through the real ML-gated pipeline. For each flagged row: build
the context bundle, get a diagnosis, format the Slack message using
Section 6's exact template, and send via notifications.send_to_slack —
the same webhook mechanism Version B's human-report path already uses,
not a second one.

Default mode uses a local stub diagnosis (no API cost, no Slack) for
rehearsing message formatting/timing. Pass --live to use the real
diagnosis agent for the take that's kept — --live implies actually
posting to Slack too, unless --no-send-slack is also passed. Pass
--send-slack on its own to rehearse real Slack delivery/timing with stub
content, without spending on the diagnosis agent.

Usage (from backend/, with the venv active):
    python demo_live_sim.py                       # stub diagnosis, print-only, no Slack
    python demo_live_sim.py --live                 # real diagnosis + real Slack post
    python demo_live_sim.py --live --no-send-slack # real diagnosis, print-only
    python demo_live_sim.py --send-slack           # stub diagnosis, but really posts (timing rehearsal)
"""
import argparse
import random

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from eval_diagnosis_sensor import probe_and_select_llm
from gather_context_sensor import gather_sensor_context
from llm_client import DiagnosisReport
from ml_detector import load_dataset
from notifications import _format_sensor_message, notify_sensor_alert
from sensor_adapter import (
    DEFAULT_K_PER_COLUMN,
    compute_baselines,
    load_ml_gate,
    process_row,
)

FAILURE_TYPE_COLUMNS = ["TWF", "HDF", "PWF", "OSF", "RNF"]
DEMO_SEED = 7
N_FAILURES = 8
N_NORMAL = 12
N_BORDERLINE_NORMAL = 2


class _StubSensorDiagnosisLLM:
    """Local, demo-only stub — no network call, no cost. Default rehearsal
    mode so Slack message formatting/timing can be iterated on without
    spending real diagnosis-agent API calls on every run (Section 6,
    point 5). Deliberately not llm_client.StubDiagnosisLLM, which has no
    branch for anomaly_type='sensor_deviation' and would return a generic
    "unrecognized anomaly type" message — this one is honest about being a
    rehearsal placeholder instead.
    """

    def generate(self, event: dict, context: dict) -> DiagnosisReport:
        return DiagnosisReport(
            likely_cause="[STUB] placeholder — demo rehearsal, not a real diagnosis",
            reasoning="[STUB] no LLM call made; used to rehearse Slack message formatting/timing without API cost.",
            confidence="low",
            recommended_action="[STUB] placeholder action",
            predicted_failure_type="Unclear",
            llm_used="stub",
        )


def _max_abs_z(row: dict, baselines: dict) -> float:
    zs = [
        abs((row[col] - b["mean"]) / b["std"])
        for col, b in baselines.items()
        if b["std"] and col in row
    ]
    return max(zs) if zs else 0.0


def build_demo_sample(df: pd.DataFrame, baselines: dict) -> pd.DataFrame:
    """Fixed-seed, stratified 20-row sample: 8 real failures (one per
    failure type first, for diversity, in a seed-shuffled order, then
    filled randomly to 8), 12 normal rows — the 2 most borderline (highest
    max |z-score| among genuinely normal rows, picked deterministically by
    sorting, not randomly) plus 10 more random normal rows.
    """
    rng = random.Random(DEMO_SEED)

    failure_df = df[df["Machine failure"] == 1]
    normal_df = df[df["Machine failure"] == 0]

    chosen_failure_idx: list = []
    type_order = list(FAILURE_TYPE_COLUMNS)
    rng.shuffle(type_order)
    for ft in type_order:
        candidates = [i for i in failure_df[failure_df[ft] == 1].index if i not in chosen_failure_idx]
        if candidates:
            chosen_failure_idx.append(rng.choice(candidates))
    remaining_pool = [i for i in failure_df.index if i not in chosen_failure_idx]
    rng.shuffle(remaining_pool)
    while len(chosen_failure_idx) < N_FAILURES and remaining_pool:
        chosen_failure_idx.append(remaining_pool.pop())
    chosen_failure_idx = chosen_failure_idx[:N_FAILURES]

    normal_records = normal_df.to_dict("records")
    z_by_index = {idx: _max_abs_z(rec, baselines) for idx, rec in zip(normal_df.index, normal_records)}
    borderline_idx = sorted(z_by_index, key=z_by_index.get, reverse=True)[:N_BORDERLINE_NORMAL]

    remaining_normal_pool = [i for i in normal_df.index if i not in borderline_idx]
    rng.shuffle(remaining_normal_pool)
    normal_idx = borderline_idx + remaining_normal_pool[: N_NORMAL - N_BORDERLINE_NORMAL]

    return df.loc[chosen_failure_idx + normal_idx]


def run_demo(live: bool, send_slack: bool, limit: int | None) -> None:
    df = load_dataset()
    baselines = compute_baselines(df)
    ml_gate = load_ml_gate()
    sample = build_demo_sample(df, baselines)

    if live:
        llm, provider, probe_log = probe_and_select_llm()
        print(f"Provider probe: {probe_log}\nProvider selected: {provider}\n")
    else:
        llm = _StubSensorDiagnosisLLM()

    print(f"{'entity_id':<12}{'Machine_failure':>16}{'real_types':>16}{'ml_probability':>16}{'flagged':>10}")
    flagged = []
    for row in sample.to_dict("records"):
        result = process_row(row, baselines, DEFAULT_K_PER_COLUMN, ml_gate=ml_gate)
        real_types = [c for c in FAILURE_TYPE_COLUMNS if row[c] == 1]
        print(
            f"{result['entity_id']:<12}{row['Machine failure']:>16}{(','.join(real_types) or '-'):>16}"
            f"{result['ml_probability']:>16.3f}{result['flagged']!s:>10}"
        )
        if result["flagged"]:
            flagged.append((row, result))

    real_failure_total = int(sample["Machine failure"].sum())
    real_failure_flagged = sum(1 for row, _ in flagged if row["Machine failure"] == 1)
    normal_flagged = sum(1 for row, _ in flagged if row["Machine failure"] == 0)
    print(f"\n{len(flagged)} of {len(sample)} rows flagged by the ML gate.")
    print(f"Of the {real_failure_total} real failures in the sample: {real_failure_flagged} flagged.")
    print(f"Of the {N_NORMAL} normal rows in the sample: {normal_flagged} flagged (false positives).")
    print(f"\nMode: {'LIVE diagnosis agent' if live else 'STUB (rehearsal)'}  |  Slack: {'ON' if send_slack else 'print-only'}")

    to_process = flagged[:limit] if limit is not None else flagged
    if limit is not None and limit < len(flagged):
        print(f"(--limit {limit}: processing {limit} of {len(flagged)} flagged rows)")

    for row, result in to_process:
        context = gather_sensor_context(result["entity_id"], result["ranked_deviations"])
        event = {"entity_id": result["entity_id"], "anomaly_type": "sensor_deviation"}
        report = llm.generate(event, context).model_dump()

        message_text = _format_sensor_message(result["entity_id"], context, report)["text"]
        print(f"\n{'=' * 70}\n{message_text}\n{'=' * 70}")

        if send_slack:
            sent = notify_sensor_alert(result["entity_id"], context, report)
            print(f"Slack send: {'sent' if sent else 'skipped (no SLACK_WEBHOOK_URL configured)'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Use the real diagnosis agent instead of the local stub.")
    parser.add_argument("--send-slack", dest="send_slack", action="store_true", default=None)
    parser.add_argument("--no-send-slack", dest="send_slack", action="store_false")
    parser.add_argument("--limit", type=int, default=None, help="Only diagnose/notify the first N flagged rows.")
    args = parser.parse_args()

    resolved_send_slack = args.send_slack if args.send_slack is not None else args.live
    run_demo(live=args.live, send_slack=resolved_send_slack, limit=args.limit)
