"""
Eval script for Version A's sensor_adapter.py — sensor_detection_version_a.md
Section 4. Runs the adapter's threshold detector against the *full* AI4I
2020 dataset (all 10,000 rows) and compares its flag (anomalous / not)
against the real `Machine failure` label. Zero API calls, zero cost — pure
statistical comparison, same spirit as eval.py for the ERP path.

This is the number that validates (or invalidates) the per-column `k`
choices in sensor_adapter.DEFAULT_K_PER_COLUMN — run it, read the per-column
diagnostics, adjust k, rerun, before calling any k value "final" per Section
1's instruction not to just assume k=3 is right.

Also runs and reports a "before" pass using only the original five raw
sensor columns (pre derived-features) alongside the "after" pass using all
eight (raw + temp_differential/mechanical_power/strain_proxy), so the
recall lift the derived features actually bought is a directly comparable,
sourced number rather than an implied one — both are kept in
sensor_detection_eval.json rather than the before numbers being overwritten.

Usage (from backend/, with the venv active):
    python eval_detection_sensor.py
Writes sensor_detection_eval.json alongside data-gen/sensor/ai4i2020.csv and
prints a confusion matrix, a per-column breakdown, and a per-failure-type
breakdown for the "after" (raw + derived) run.
"""
import json
from pathlib import Path

import pandas as pd

from sensor_adapter import (
    ALL_SENSOR_COLUMNS,
    DEFAULT_K_PER_COLUMN,
    DERIVED_COLUMNS,
    SENSOR_COLUMNS,
    add_derived_features_df,
    compute_baselines,
    detect_deviations,
)

DATA_PATH = Path(__file__).resolve().parent.parent / "data-gen" / "sensor" / "ai4i2020.csv"
RESULTS_PATH = Path(__file__).resolve().parent.parent / "data-gen" / "sensor" / "sensor_detection_eval.json"

FAILURE_TYPE_COLUMNS = ["TWF", "HDF", "PWF", "OSF", "RNF"]

# Per sensor_detection_version_a.md's instruction to call these out
# explicitly rather than let the eval numbers surface them unexplained —
# both are expected to stay weak even after adding the derived features,
# for reasons unrelated to detector tuning.
FAILURE_TYPE_NOTES = {
    "TWF": (
        "Expected to stay weak: AI4I assigns each tool a randomly-drawn wear "
        "failure limit (200-240 min) rather than a fixed physical threshold, "
        "so a tool's own wear deviating from the population baseline doesn't "
        "reliably line up with that particular tool's actual limit."
    ),
    "HDF": (
        "Only partially fixed by design, not an unexplained miss: "
        "temp_differential (which targets HDF) is deliberately kept at "
        "k=3.0, where it's inert, to protect aggregate precision. Looser "
        "thresholds were measured and rejected — k=2.0 raises HDF recall to "
        "31.3% (36/115) but crashes aggregate precision to 32.4%; k=1.5 "
        "raises HDF recall to 89.6% (103/115) but aggregate precision falls "
        "to 19.1%, worse than the pre-derived-features baseline (66.7%). "
        "See sensor_adapter.DEFAULT_K_PER_COLUMN's comment for the full "
        "numbers behind this trade-off."
    ),
    "RNF": (
        "Expected to stay weak by design: a low-probability random failure "
        "with no sensor signature at all, independent of every measured "
        "column (raw or derived). No threshold-based detector, however "
        "tuned, is expected to catch this reliably."
    ),
}


def _flag_rows(rows: list[dict], baselines: dict, k_per_column: dict) -> list[bool]:
    return [bool(detect_deviations(row, baselines, k_per_column)) for row in rows]


def _confusion_matrix(rows: list[dict], flags: list[bool]) -> dict:
    tp = fp = tn = fn = 0
    for row, flagged in zip(rows, flags):
        actual_failure = bool(row["Machine failure"])
        if flagged and actual_failure:
            tp += 1
        elif flagged and not actual_failure:
            fp += 1
        elif not flagged and actual_failure:
            fn += 1
        else:
            tn += 1
    return {"true_positives": tp, "false_positives": fp, "true_negatives": tn, "false_negatives": fn}


def _precision_recall_accuracy(cm: dict) -> dict:
    tp, fp, tn, fn = cm["true_positives"], cm["false_positives"], cm["true_negatives"], cm["false_negatives"]
    total = tp + fp + tn + fn
    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    recall = tp / (tp + fn) if (tp + fn) > 0 else None
    accuracy = (tp + tn) / total if total > 0 else None
    return {"precision": precision, "recall": recall, "accuracy": accuracy}


def _per_column_diagnostics(rows: list[dict], baselines: dict, k_per_column: dict) -> dict:
    """For each column independently: how many rows does *that column
    alone* flag (ignoring every other column), and of those, how many are
    real failures? This is what actually justifies loosening/tightening a
    given column's k — a column flagging mostly normal rows is noisy and
    wants a larger k; a column that only ever flags real failures could
    afford a smaller one.
    """
    diagnostics = {}
    for col, baseline in baselines.items():
        std = baseline["std"]
        k = k_per_column.get(col, 3.0)
        flagged_total = 0
        flagged_true_failure = 0
        for row in rows:
            if not std or col not in row:
                continue
            z = (row[col] - baseline["mean"]) / std
            if abs(z) > k:
                flagged_total += 1
                if row["Machine failure"]:
                    flagged_true_failure += 1
        diagnostics[col] = {
            "k": k,
            "rows_flagged_by_this_column_alone": flagged_total,
            "of_those_real_failures": flagged_true_failure,
            "of_those_false_alarms": flagged_total - flagged_true_failure,
        }
    return diagnostics


def _per_failure_type_breakdown(rows: list[dict], flags: list[bool]) -> dict:
    """For each of AI4I's five real failure-type columns: how many rows are
    actually that failure type, how many of those did the detector catch
    (flagged, regardless of which column triggered it), and how many did it
    miss. This is the number that shows whether the derived features
    actually closed the gap they were built for (HDF/PWF/OSF should
    visibly improve) versus the two types expected to stay weak for
    unrelated reasons (TWF, RNF — see FAILURE_TYPE_NOTES).
    """
    breakdown = {}
    for failure_type in FAILURE_TYPE_COLUMNS:
        total = 0
        caught = 0
        for row, flagged in zip(rows, flags):
            if row.get(failure_type):
                total += 1
                if flagged:
                    caught += 1
        entry = {
            "real_instances": total,
            "caught": caught,
            "missed": total - caught,
            "recall_pct": round(caught / total * 100, 1) if total else None,
        }
        if failure_type in FAILURE_TYPE_NOTES:
            entry["note"] = FAILURE_TYPE_NOTES[failure_type]
        breakdown[failure_type] = entry
    return breakdown


def run_eval(columns: list[str], k_per_column: dict | None = None) -> dict:
    """`columns` selects which baselines/detections to run over —
    SENSOR_COLUMNS for the original raw-only "before" numbers,
    ALL_SENSOR_COLUMNS (the default) for the "after" raw+derived numbers.
    """
    k_per_column = k_per_column or DEFAULT_K_PER_COLUMN
    df = pd.read_csv(DATA_PATH)
    if set(columns) & set(DERIVED_COLUMNS):
        df = add_derived_features_df(df)
    baselines = compute_baselines(df, columns=columns)
    rows = df.to_dict("records")
    flags = _flag_rows(rows, baselines, k_per_column)

    cm = _confusion_matrix(rows, flags)
    metrics = _precision_recall_accuracy(cm)
    diagnostics = _per_column_diagnostics(rows, baselines, k_per_column)
    by_failure_type = _per_failure_type_breakdown(rows, flags)

    return {
        "dataset_path": str(DATA_PATH),
        "total_rows": len(rows),
        "columns_used": columns,
        "k_per_column": {col: k_per_column.get(col, 3.0) for col in columns},
        "confusion_matrix": cm,
        "metrics": metrics,
        "per_column_diagnostics": diagnostics,
        "per_failure_type": by_failure_type,
    }


def _fmt_pct(value: float | None) -> str:
    return f"{value * 100:.1f}%" if value is not None else "n/a"


def _print_summary(label: str, results: dict) -> None:
    cm = results["confusion_matrix"]
    metrics = results["metrics"]
    print(f"\n=== {label} ({len(results['columns_used'])} columns: {', '.join(results['columns_used'])}) ===")
    print(f"{'TP':>6}{'FP':>6}{'TN':>6}{'FN':>6}")
    print(f"{cm['true_positives']:>6}{cm['false_positives']:>6}{cm['true_negatives']:>6}{cm['false_negatives']:>6}")
    print(f"precision: {_fmt_pct(metrics['precision'])}   recall: {_fmt_pct(metrics['recall'])}   "
          f"accuracy: {_fmt_pct(metrics['accuracy'])}")
    print()
    print("Per-column diagnostics (each column judged alone, ignoring the others):")
    header = f"{'column':<28}{'k':>5}{'flagged':>10}{'real_failure':>14}{'false_alarm':>13}"
    print(header)
    print("-" * len(header))
    for col, d in results["per_column_diagnostics"].items():
        print(
            f"{col:<28}{d['k']:>5.1f}{d['rows_flagged_by_this_column_alone']:>10}"
            f"{d['of_those_real_failures']:>14}{d['of_those_false_alarms']:>13}"
        )
    print()
    print("Per-failure-type breakdown (caught = detector flagged the row, regardless of which column):")
    header2 = f"{'failure_type':<14}{'real_instances':>15}{'caught':>8}{'missed':>8}{'recall':>9}"
    print(header2)
    print("-" * len(header2))
    for failure_type, d in results["per_failure_type"].items():
        print(
            f"{failure_type:<14}{d['real_instances']:>15}{d['caught']:>8}{d['missed']:>8}"
            f"{_fmt_pct(d['recall_pct'] / 100 if d['recall_pct'] is not None else None):>9}"
        )
        if "note" in d:
            print(f"    note: {d['note']}")


if __name__ == "__main__":
    before = run_eval(columns=SENSOR_COLUMNS)
    after = run_eval(columns=ALL_SENSOR_COLUMNS)

    _print_summary("BEFORE (5 raw columns only)", before)
    _print_summary("AFTER (5 raw + 3 derived columns)", after)

    print("\n=== Before vs. after ===")
    bm, am = before["metrics"], after["metrics"]
    print(f"{'':<12}{'precision':>12}{'recall':>10}{'accuracy':>11}")
    print(f"{'before':<12}{_fmt_pct(bm['precision']):>12}{_fmt_pct(bm['recall']):>10}{_fmt_pct(bm['accuracy']):>11}")
    print(f"{'after':<12}{_fmt_pct(am['precision']):>12}{_fmt_pct(am['recall']):>10}{_fmt_pct(am['accuracy']):>11}")

    output = {
        "before_derived_features": before,
        "after_derived_features": after,
    }
    RESULTS_PATH.write_text(json.dumps(output, indent=2, default=str))
    print(f"\nFull before/after results written to {RESULTS_PATH}")
