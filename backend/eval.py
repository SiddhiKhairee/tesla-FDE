"""
Eval script — the defensible precision/recall claim for the pitch.

Runs the real detection pipeline against live Odoo, compares it to Day 2's
injected ground truth, and reports true/false positives and false negatives
per anomaly type. Rerunnable at any point as detection.py evolves; the
numbers should never drift with wall-clock time (see reference_date below).

Usage (from backend/, with the venv active and Odoo running):
    python eval.py
Writes eval_results.json alongside this script and prints a summary table.
"""
import json
from datetime import datetime
from pathlib import Path

from main import _detect_all_events

GROUND_TRUTH_PATH = Path(__file__).resolve().parent.parent / "data-gen" / "output" / "ground_truth.json"
RESULTS_PATH = Path(__file__).resolve().parent / "eval_results.json"

ANOMALY_TYPES = ["stuck_order", "delayed_delivery", "duplicate_entry", "quantity_mismatch"]


def _match_key(event: dict) -> tuple:
    return (event["entity_id"], event["anomaly_type"], event["field"])


def _match(detected: list[dict], ground_truth: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """One-to-one match by (entity_id, anomaly_type, field). Ground-truth
    events are consumed on match (not just deduped by key) so duplicate keys
    are handled correctly rather than over- or under-counting.

    Returns (true_positives, false_positives, false_negatives), where each
    true_positive is {"detected": ..., "expected": ...} and each fp/fn is
    the bare event dict.
    """
    remaining_gt = list(ground_truth)
    true_positives, false_positives = [], []

    for det in detected:
        match = next((gt for gt in remaining_gt if _match_key(gt) == _match_key(det)), None)
        if match is not None:
            remaining_gt.remove(match)
            true_positives.append({"detected": det, "expected": match})
        else:
            false_positives.append(det)

    false_negatives = remaining_gt
    return true_positives, false_positives, false_negatives


def _precision_recall(tp: int, fp: int, fn: int) -> tuple[float | None, float | None]:
    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    recall = tp / (tp + fn) if (tp + fn) > 0 else None
    return precision, recall


def _fmt_pct(value: float | None) -> str:
    return f"{value * 100:.1f}%" if value is not None else "n/a"


def run_eval() -> dict:
    ground_truth_doc = json.loads(GROUND_TRUTH_PATH.read_text())
    reference_date = datetime.fromisoformat(ground_truth_doc["generated_through"])
    ground_truth = ground_truth_doc["events"]

    detected = [e.model_dump() for e in _detect_all_events(reference_date=reference_date)]

    true_positives, false_positives, false_negatives = _match(detected, ground_truth)

    def subset_by_type(anomaly_type: str):
        tp = [m for m in true_positives if m["expected"]["anomaly_type"] == anomaly_type]
        fp = [d for d in false_positives if d["anomaly_type"] == anomaly_type]
        fn = [g for g in false_negatives if g["anomaly_type"] == anomaly_type]
        return tp, fp, fn

    by_type = {}
    for anomaly_type in ANOMALY_TYPES:
        tp, fp, fn = subset_by_type(anomaly_type)
        precision, recall = _precision_recall(len(tp), len(fp), len(fn))
        by_type[anomaly_type] = {
            "true_positives": len(tp),
            "false_positives": len(fp),
            "false_negatives": len(fn),
            "precision": precision,
            "recall": recall,
        }

    overall_precision, overall_recall = _precision_recall(
        len(true_positives), len(false_positives), len(false_negatives)
    )

    results = {
        "reference_date": reference_date.isoformat(),
        "ground_truth_path": str(GROUND_TRUTH_PATH),
        "detected_count": len(detected),
        "ground_truth_count": len(ground_truth),
        "overall": {
            "true_positives": len(true_positives),
            "false_positives": len(false_positives),
            "false_negatives": len(false_negatives),
            "precision": overall_precision,
            "recall": overall_recall,
        },
        "by_anomaly_type": by_type,
        "false_positives": [
            {"entity_id": d["entity_id"], "anomaly_type": d["anomaly_type"], "field": d["field"], "detected": d}
            for d in false_positives
        ],
        "false_negatives": [
            {"entity_id": g["entity_id"], "anomaly_type": g["anomaly_type"], "field": g["field"], "expected": g}
            for g in false_negatives
        ],
    }
    return results


def _print_summary(results: dict) -> None:
    print(f"Reference date (ground_truth.json's generated_through): {results['reference_date']}")
    print(f"Detected: {results['detected_count']}   Ground truth: {results['ground_truth_count']}")
    print()

    header = f"{'anomaly_type':<18}{'TP':>4}{'FP':>4}{'FN':>4}{'precision':>12}{'recall':>10}"
    print(header)
    print("-" * len(header))
    for anomaly_type in ANOMALY_TYPES:
        row = results["by_anomaly_type"][anomaly_type]
        print(
            f"{anomaly_type:<18}{row['true_positives']:>4}{row['false_positives']:>4}{row['false_negatives']:>4}"
            f"{_fmt_pct(row['precision']):>12}{_fmt_pct(row['recall']):>10}"
        )
    print("-" * len(header))
    overall = results["overall"]
    print(
        f"{'OVERALL':<18}{overall['true_positives']:>4}{overall['false_positives']:>4}{overall['false_negatives']:>4}"
        f"{_fmt_pct(overall['precision']):>12}{_fmt_pct(overall['recall']):>10}"
    )

    if results["false_positives"]:
        print("\nFalse positives (detected, not in ground truth):")
        for fp in results["false_positives"]:
            print(f"  - {fp['anomaly_type']:<18} {fp['entity_id']:<20} field={fp['field']}")

    if results["false_negatives"]:
        print("\nFalse negatives (in ground truth, not detected):")
        for fn in results["false_negatives"]:
            print(
                f"  - {fn['anomaly_type']:<18} {fn['entity_id']:<20} field={fn['field']}"
                f"  expected={fn['expected']['expected_value']!r} actual={fn['expected']['actual_value']!r}"
                f"  timestamp={fn['expected']['timestamp']}"
            )


if __name__ == "__main__":
    results = run_eval()
    _print_summary(results)
    RESULTS_PATH.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nFull results written to {RESULTS_PATH}")
