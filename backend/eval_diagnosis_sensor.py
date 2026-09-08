"""
Eval script for Version A's diagnosis agent — sensor_detection_version_a.md
Section 5. First real LLM calls in the whole Version A build. Scoped
narrowly per the spec: only the true-positive set (ML-flagged rows that are
real failures), a fixed-seed sample of 50 (or the full TP set if it's
<=50), never the whole dataset. No Slack calls anywhere in this script.

Before spending anything on the real batch, `probe_and_select_llm` makes
one minimal real call directly against Gemini, and if that fails for ANY
reason (429 quota, 503 server overload, etc. — checking
GEMINI_API_KEY/GROQ_API_KEY presence alone doesn't prove quota is
available, only a real call does), probes Groq directly next rather than
re-attempting an already-unavailable Gemini across the whole batch. If
Gemini IS confirmed available, the full GeminiGroqStubFallbackLLM chain is
used for the batch anyway, so a mid-run quota exhaustion still degrades
gracefully — but every row's `llm_used` is tracked, and any row that fell
all the way to the stub is excluded from the real accuracy number rather
than silently counted as a real diagnosis.

Usage (from backend/, with the venv active):
    python eval_diagnosis_sensor.py
Writes into data-gen/sensor/sensor_detection_eval.json (new key, existing
entries preserved) and prints a summary plus 3 full example responses.
"""
import json
import random
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from gather_context_sensor import gather_sensor_context
from ml_detector import load_dataset, split_dataset
from sensor_adapter import (
    DEFAULT_K_PER_COLUMN,
    compute_baselines,
    load_ml_gate,
    process_row,
)

RESULTS_PATH = Path(__file__).resolve().parent.parent / "data-gen" / "sensor" / "sensor_detection_eval.json"
FAILURE_TYPE_COLUMNS = ["TWF", "HDF", "PWF", "OSF", "RNF"]
SEED = 42
SAMPLE_SIZE = 50
# Pacing between real calls, sized against Groq's actual free-tier limit
# hit during the first attempt at this batch: 8000 TPM, and each call here
# runs ~2400 tokens (per the 429 error's own "Requested 2401/2413" —
# confirmed, not guessed). 3 calls/minute = ~7200 TPM stays under that with
# margin; 22s between calls keeps to just under 3/minute.
SECONDS_BETWEEN_CALLS = 22.0
# One retry after a rate-limit hit, waiting slightly longer than the
# error's own "try again in Ns" ever asked for in the first attempt — a
# transient 429 shouldn't cost one of the 50 real, budgeted samples if a
# short wait would have let it through.
RATE_LIMIT_RETRY_WAIT_SECONDS = 15.0


def _probe_event_and_context() -> tuple[dict, dict]:
    event = {"entity_id": "PROBE", "anomaly_type": "sensor_deviation"}
    context = {
        "entity_id": "PROBE",
        "deviating_sensors": [
            {
                "sensor": "Torque [Nm]",
                "value": 65.0,
                "baseline_mean": 39.6,
                "baseline_std": 9.5,
                "z_score": 2.7,
                "direction": "above",
                "note": "furthest from normal, though not individually abnormal",
            }
        ],
        "failure_taxonomy": {"Unclear": {"name": "Unclear", "description": "placeholder for probe only"}},
    }
    return event, context


def probe_and_select_llm():
    """One minimal real call against Gemini directly; if that fails for
    ANY reason (429 quota, 503 server overload, whatever), probe Groq
    directly next rather than retrying an already-unavailable Gemini
    repeatedly across the real batch. Returns (llm_to_use_for_batch,
    provider_name, probe_log) — probe_log records what was tried and what
    happened, including the rejected attempt, not just the winner.
    """
    from llm_client import (
        GeminiDiagnosisLLM,
        GeminiGroqStubFallbackLLM,
        GroqDiagnosisLLM,
    )

    event, context = _probe_event_and_context()
    probe_log = []

    try:
        GeminiDiagnosisLLM().generate(event, context)
        probe_log.append({"provider": "gemini", "outcome": "available"})
        # Gemini confirmed live right now — use the full fallback chain for
        # the batch so a mid-run quota exhaustion still degrades gracefully.
        return GeminiGroqStubFallbackLLM(), "gemini", probe_log
    except Exception as e:  # noqa: BLE001 — any failure here means "not available", not just quota
        probe_log.append({"provider": "gemini", "outcome": "unavailable", "error": f"{type(e).__name__}: {e}"})

    try:
        GroqDiagnosisLLM().generate(event, context)
        probe_log.append({"provider": "groq", "outcome": "available"})
        # Gemini already confirmed unavailable above — use Groq directly
        # for the whole batch rather than re-attempting an unavailable
        # Gemini on every one of the 50 rows.
        return GroqDiagnosisLLM(), "groq", probe_log
    except Exception as e:  # noqa: BLE001
        probe_log.append({"provider": "groq", "outcome": "unavailable", "error": f"{type(e).__name__}: {e}"})

    raise RuntimeError(f"Neither Gemini nor Groq answered the probe call — refusing to spend on the batch. {probe_log}")


def build_true_positive_set() -> list[dict]:
    df = load_dataset()
    _, _, df_test, *_ = split_dataset(df)
    baselines = compute_baselines(df)
    ml_gate = load_ml_gate()

    tp_rows = []
    for row in df_test.to_dict("records"):
        result = process_row(row, baselines, DEFAULT_K_PER_COLUMN, ml_gate=ml_gate)
        if result["flagged"] and row["Machine failure"] == 1:
            real_types = [c for c in FAILURE_TYPE_COLUMNS if row[c] == 1]
            tp_rows.append({"result": result, "real_types": real_types})
    return tp_rows


def run_eval(llm, tp_rows: list[dict]) -> dict:
    rng = random.Random(SEED)
    if len(tp_rows) <= SAMPLE_SIZE:
        sample = list(tp_rows)
        sample_method = f"full TP set used ({len(tp_rows)} <= {SAMPLE_SIZE})"
    else:
        sample = rng.sample(tp_rows, SAMPLE_SIZE)
        sample_method = f"fixed-seed random sample of {SAMPLE_SIZE} (seed={SEED})"

    per_row_results = []
    for i, item in enumerate(sample):
        result = item["result"]
        real_types = item["real_types"]
        context = gather_sensor_context(result["entity_id"], result["ranked_deviations"])
        event = {"entity_id": result["entity_id"], "anomaly_type": "sensor_deviation"}

        if i > 0:
            time.sleep(SECONDS_BETWEEN_CALLS)

        report, error = None, None
        for attempt in range(2):  # one retry specifically for a transient rate-limit hit
            try:
                report = llm.generate(event, context)
                break
            except Exception as e:  # noqa: BLE001 — a real batch job must not lose all prior spend to one bad row
                is_rate_limit = type(e).__name__ == "RateLimitError"
                if is_rate_limit and attempt == 0:
                    print(f"    rate limit hit on {result['entity_id']}, waiting {RATE_LIMIT_RETRY_WAIT_SECONDS}s and retrying once...")
                    time.sleep(RATE_LIMIT_RETRY_WAIT_SECONDS)
                    continue
                error = f"{type(e).__name__}: {e}"
                break

        if error is not None:
            correct = None
        elif real_types:
            correct = report.predicted_failure_type in real_types
        else:
            correct = report.predicted_failure_type == "Unclear"

        per_row_results.append(
            {
                "entity_id": result["entity_id"],
                "ml_probability": result["ml_probability"],
                "real_types": real_types,
                "error": error,
                "predicted_failure_type": report.predicted_failure_type if report else None,
                "correct": correct,
                "confidence": report.confidence if report else None,
                "llm_used": report.llm_used if report else None,
                "likely_cause": report.likely_cause if report else None,
                "reasoning": report.reasoning if report else None,
                "recommended_action": report.recommended_action if report else None,
                "deviating_sensors": context["deviating_sensors"],
            }
        )
        print(
            f"  [{i + 1}/{len(sample)}] {result['entity_id']}: "
            f"{'ERROR: ' + error if error else report.llm_used + ' -> ' + str(report.predicted_failure_type)}"
            f"  (real={real_types or 'AMBIGUOUS'})"
        )

    errored = [r for r in per_row_results if r["error"] is not None]
    fell_back_to_stub = [r for r in per_row_results if r["llm_used"] == "stub"]
    scored = [r for r in per_row_results if r["error"] is None and r["llm_used"] != "stub"]
    correct_count = sum(1 for r in scored if r["correct"])

    by_type = {}
    for failure_type in FAILURE_TYPE_COLUMNS:
        in_type = [r for r in scored if failure_type in r["real_types"]]
        by_type[failure_type] = {
            "real_instances_in_sample": len(in_type),
            "correct": sum(1 for r in in_type if r["correct"]),
        }
    ambiguous = [r for r in scored if not r["real_types"]]
    by_type["AMBIGUOUS_NO_TYPE_FLAGGED"] = {
        "real_instances_in_sample": len(ambiguous),
        "correct": sum(1 for r in ambiguous if r["correct"]),
        "note": (
            "Machine failure==1 but no TWF/HDF/PWF/OSF/RNF column was flagged for this "
            "row (see data_summary.json — 9 such rows exist dataset-wide). Scored as "
            "correct only if the agent predicted 'Unclear', since no single correct "
            "label actually exists to match against."
        ),
    }

    return {
        "true_positive_set_size": len(tp_rows),
        "sample_size": len(sample),
        "sample_method": sample_method,
        "seed": SEED,
        "scored_count": len(scored),
        "errored_count": len(errored),
        "fell_back_to_stub_count": len(fell_back_to_stub),
        "accuracy": (correct_count / len(scored)) if scored else None,
        "accuracy_report_string": (
            f"{correct_count} of {len(scored)} sampled true positives correct "
            f"(fixed seed={SEED}); {len(fell_back_to_stub)} fell back to stub and "
            f"{len(errored)} errored — both excluded from this number"
        ),
        "per_failure_type": by_type,
        "confidence_values_returned_ungraded": [r["confidence"] for r in per_row_results if r["confidence"]],
        "per_row_results": per_row_results,
    }


def _print_examples(results: dict, n: int = 3) -> None:
    scored_rows = [r for r in results["per_row_results"] if r["error"] is None and r["llm_used"] != "stub"]
    print(f"\n{'=' * 78}\nFULL EXAMPLE DIAGNOSIS RESPONSES ({min(n, len(scored_rows))} of {len(scored_rows)} scored)\n{'=' * 78}")
    for r in scored_rows[:n]:
        print(f"\nentity_id={r['entity_id']}  llm_used={r['llm_used']}  ml_probability={r['ml_probability']:.3f}")
        print(f"real_types={r['real_types'] or 'AMBIGUOUS (no type flagged)'}  "
              f"predicted_failure_type={r['predicted_failure_type']}  correct={r['correct']}")
        print("deviating_sensors:")
        for dev in r["deviating_sensors"]:
            print(f"  - {dev['sensor']}: {dev['value']:.2f} (z={dev['z_score']:.2f}, {dev['direction']}) — {dev['note']}")
        print(f"likely_cause: {r['likely_cause']}")
        print(f"reasoning: {r['reasoning']}")
        print(f"recommended_action: {r['recommended_action']}")
        print(f"confidence (not graded): {r['confidence']}")


if __name__ == "__main__":
    print("Probing Gemini directly (one minimal real call) before committing to the batch...")
    llm, provider, probe_log = probe_and_select_llm()
    for entry in probe_log:
        print(f"  {entry}")
    print(f"Provider selected for the batch: {provider}\n")

    print("Building true-positive set from the test split (ML-flagged AND Machine failure==1)...")
    tp_rows = build_true_positive_set()
    print(f"True positive set (recomputed directly): {len(tp_rows)} rows\n")

    print("Running the sampled diagnosis-agent eval...")
    results = run_eval(llm, tp_rows)
    results["provider_selected"] = provider
    results["provider_probe_log"] = probe_log

    print(f"\n{results['accuracy_report_string']}")
    print("\nPer-failure-type breakdown (scored rows only):")
    for failure_type, d in results["per_failure_type"].items():
        note = f"  [{d['note']}]" if "note" in d else ""
        print(f"  {failure_type}: {d['correct']}/{d['real_instances_in_sample']}{note}")

    _print_examples(results)

    existing = json.loads(RESULTS_PATH.read_text()) if RESULTS_PATH.exists() else {}
    existing["v_diagnosis_agent_eval"] = results
    RESULTS_PATH.write_text(json.dumps(existing, indent=2, default=str))
    print(f"\nResults written to {RESULTS_PATH} (key: v_diagnosis_agent_eval)")
