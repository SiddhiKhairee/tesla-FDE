"""
Version A v2 — ML classifier, per sensor_detection_version_a.md Section 1.5.
Planned there, implemented here: a Random Forest trained on the same 8
features v1.5's z-score detector already computes (5 raw sensor columns +
temp_differential/mechanical_power/strain_proxy), replacing the z-score
threshold's anomalous/not-anomalous gating decision only — the z-score
deviation math itself keeps running unchanged to produce the "which sensors
were off, by how much" description for gather_context_sensor.py and the
Slack message (see Section 1.5 point 4). This module only trains and
evaluates the classifier; it doesn't wire it into the live pipeline.

Trust condition (Section 1.5 point 5): this is only worth shipping if it
beats v1.5's test-comparable numbers (75.0% precision / 29.2% recall /
97.3% accuracy) on BOTH precision and recall, on held-out data the model
never touched during training or tuning — not accuracy alone, and not one
metric improving while the other collapses.

Usage (from backend/, with the venv active):
    python ml_detector.py
Writes its results into data-gen/sensor/sensor_detection_eval.json
alongside the existing v1/v1.5 entries (adds a new top-level key, doesn't
touch the existing ones) and prints the full report.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import average_precision_score
from sklearn.model_selection import train_test_split

from sensor_adapter import ALL_SENSOR_COLUMNS, add_derived_features_df

DATA_PATH = Path(__file__).resolve().parent.parent / "data-gen" / "sensor" / "ai4i2020.csv"
RESULTS_PATH = Path(__file__).resolve().parent.parent / "data-gen" / "sensor" / "sensor_detection_eval.json"

FAILURE_TYPE_COLUMNS = ["TWF", "HDF", "PWF", "OSF", "RNF"]

RANDOM_STATE = 42

# v1.5's numbers (Sections 1 + 4 of sensor_detection_version_a.md) — the bar
# v2 has to clear on BOTH metrics, per the Section 1.5 trust condition.
V1_5_BENCHMARK = {"precision": 0.750, "recall": 0.292, "accuracy": 0.973}

# Modest, explicit grid — not an exhaustive search. Values chosen to bracket
# sane Random Forest defaults (100-400 trees; unconstrained vs. moderately
# constrained depth; leaf size from "fit tightly" to "regularize against
# this small a positive class"), matching Section 1.5's "simplest thing
# that could work first" instruction rather than reaching for an expansive
# search on the first attempt.
HYPERPARAM_GRID = [
    {"n_estimators": n, "max_depth": d, "min_samples_leaf": leaf}
    for n in (100, 300)
    for d in (None, 10)
    for leaf in (1, 5)
]

THRESHOLDS = np.round(np.arange(0.05, 0.96, 0.05), 2)


def load_dataset() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH)
    return add_derived_features_df(df)


def split_dataset(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Series, pd.Series, pd.Series]:
    """Stratified 60/20/20 train/val/test split on `Machine failure`, so the
    real ~3.4% failure rate is preserved in every split rather than any one
    split's balance drifting from the true distribution. Returns the full
    per-split dataframes (not just X/y) so the failure-type columns
    (TWF/HDF/PWF/OSF/RNF) stay available for the per-failure-type breakdown
    after prediction, aligned to the same rows.
    """
    y = df["Machine failure"]
    df_train, df_temp = train_test_split(
        df, test_size=0.4, stratify=y, random_state=RANDOM_STATE
    )
    df_val, df_test = train_test_split(
        df_temp, test_size=0.5, stratify=df_temp["Machine failure"], random_state=RANDOM_STATE
    )
    return df_train, df_val, df_test, df_train["Machine failure"], df_val["Machine failure"], df_test["Machine failure"]


def _split_summary(name: str, df_split: pd.DataFrame) -> dict:
    total = len(df_split)
    positives = int(df_split["Machine failure"].sum())
    return {
        "split": name,
        "rows": total,
        "positives": positives,
        "negatives": total - positives,
        "positive_rate_pct": round(positives / total * 100, 2) if total else None,
    }


def sweep_hyperparameters(
    X_train: pd.DataFrame, y_train: pd.Series, X_val: pd.DataFrame, y_val: pd.Series
) -> tuple[dict, list[dict]]:
    """Fits one RandomForestClassifier(class_weight='balanced') per grid
    entry on the training split only, scores each on the validation split
    using average precision (area under the precision-recall curve) —
    deliberately threshold-independent, so hyperparameter selection isn't
    entangled with the separate classification-threshold tuning pass that
    follows it. Returns (best_params, all_results) so every attempt is
    visible, not just the winner.
    """
    results = []
    for params in HYPERPARAM_GRID:
        model = RandomForestClassifier(
            class_weight="balanced", random_state=RANDOM_STATE, n_jobs=-1, **params
        )
        model.fit(X_train, y_train)
        val_proba = model.predict_proba(X_val)[:, 1]
        val_ap = average_precision_score(y_val, val_proba)
        results.append({"params": params, "val_average_precision": round(float(val_ap), 4)})

    best = max(results, key=lambda r: r["val_average_precision"])
    return best["params"], results


def sweep_threshold(y_val: pd.Series, val_proba: np.ndarray) -> tuple[float, list[dict], str]:
    """Sweeps classification thresholds against the validation split's
    predicted probabilities (never the test split). Selection rule: among
    thresholds where validation precision >= the v1.5 benchmark (75.0%),
    pick the one with the highest recall — i.e. don't accept a precision
    regression versus what's already shipped in exchange for more recall.
    If no threshold clears that precision floor on validation, fall back to
    the threshold maximizing F1 and say so explicitly, since that means the
    trust condition is already unlikely to be met before test evaluation
    even happens.
    """
    sweep = []
    for threshold in THRESHOLDS:
        preds = (val_proba >= threshold).astype(int)
        tp = int(((preds == 1) & (y_val == 1)).sum())
        fp = int(((preds == 1) & (y_val == 0)).sum())
        fn = int(((preds == 0) & (y_val == 1)).sum())
        precision = tp / (tp + fp) if (tp + fp) > 0 else None
        recall = tp / (tp + fn) if (tp + fn) > 0 else None
        f1 = (2 * precision * recall / (precision + recall)) if precision and recall else 0.0
        sweep.append({"threshold": float(threshold), "precision": precision, "recall": recall, "f1": f1})

    above_floor = [s for s in sweep if s["precision"] is not None and s["precision"] >= V1_5_BENCHMARK["precision"]]
    if above_floor:
        best = max(above_floor, key=lambda s: s["recall"])
        method = (
            f"validation precision >= v1.5 benchmark ({V1_5_BENCHMARK['precision']:.1%}), "
            "then max recall among those thresholds"
        )
    else:
        best = max(sweep, key=lambda s: s["f1"])
        method = (
            "no threshold reached the v1.5 precision benchmark on validation — "
            "fell back to max F1 (flagging that the trust condition is already at risk)"
        )
    return best["threshold"], sweep, method


def _confusion_matrix(y_true: pd.Series, y_pred: np.ndarray) -> dict:
    tp = int(((y_pred == 1) & (y_true == 1)).sum())
    fp = int(((y_pred == 1) & (y_true == 0)).sum())
    tn = int(((y_pred == 0) & (y_true == 0)).sum())
    fn = int(((y_pred == 0) & (y_true == 1)).sum())
    return {"true_positives": tp, "false_positives": fp, "true_negatives": tn, "false_negatives": fn}


def _precision_recall_f1_accuracy(cm: dict) -> dict:
    tp, fp, tn, fn = cm["true_positives"], cm["false_positives"], cm["true_negatives"], cm["false_negatives"]
    total = tp + fp + tn + fn
    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    recall = tp / (tp + fn) if (tp + fn) > 0 else None
    f1 = (2 * precision * recall / (precision + recall)) if precision and recall else None
    accuracy = (tp + tn) / total if total > 0 else None
    return {"precision": precision, "recall": recall, "f1": f1, "accuracy": accuracy}


def _per_failure_type_breakdown(df_split: pd.DataFrame, y_pred: np.ndarray) -> dict:
    breakdown = {}
    for failure_type in FAILURE_TYPE_COLUMNS:
        mask = df_split[failure_type] == 1
        total = int(mask.sum())
        caught = int((mask.values & (y_pred == 1)).sum())
        breakdown[failure_type] = {
            "real_instances": total,
            "caught": caught,
            "missed": total - caught,
            "recall_pct": round(caught / total * 100, 1) if total else None,
        }
    return breakdown


def _fmt_pct(value) -> str:
    return f"{value * 100:.1f}%" if isinstance(value, (int, float)) else "n/a"


def run() -> dict:
    df = load_dataset()
    df_train, df_val, df_test, y_train, y_val, y_test = split_dataset(df)

    split_summary = {
        "train": _split_summary("train", df_train),
        "val": _split_summary("val", df_val),
        "test": _split_summary("test", df_test),
    }

    X_train, X_val, X_test = df_train[ALL_SENSOR_COLUMNS], df_val[ALL_SENSOR_COLUMNS], df_test[ALL_SENSOR_COLUMNS]

    best_params, hyperparam_results = sweep_hyperparameters(X_train, y_train, X_val, y_val)

    # Refit with the winning hyperparameters (train split only) to get the
    # predict_proba values the threshold sweep tunes against.
    model = RandomForestClassifier(class_weight="balanced", random_state=RANDOM_STATE, n_jobs=-1, **best_params)
    model.fit(X_train, y_train)
    val_proba = model.predict_proba(X_val)[:, 1]

    chosen_threshold, threshold_sweep, threshold_method = sweep_threshold(y_val, val_proba)

    # Final, one-time test-set evaluation.
    test_proba = model.predict_proba(X_test)[:, 1]
    test_pred = (test_proba >= chosen_threshold).astype(int)
    cm = _confusion_matrix(y_test, test_pred)
    metrics = _precision_recall_f1_accuracy(cm)
    per_failure_type = _per_failure_type_breakdown(df_test, test_pred)

    feature_importances = dict(
        sorted(
            zip(ALL_SENSOR_COLUMNS, (float(x) for x in model.feature_importances_)),
            key=lambda kv: kv[1],
            reverse=True,
        )
    )

    meets_trust_condition = (
        metrics["precision"] is not None
        and metrics["recall"] is not None
        and metrics["precision"] > V1_5_BENCHMARK["precision"]
        and metrics["recall"] > V1_5_BENCHMARK["recall"]
    )

    return {
        "model": "RandomForestClassifier(class_weight='balanced')",
        "feature_columns": ALL_SENSOR_COLUMNS,
        "random_state": RANDOM_STATE,
        "split_summary": split_summary,
        "hyperparameter_sweep": {
            "method": "grid search over train split, selected by validation average precision (PR-AUC)",
            "grid": HYPERPARAM_GRID,
            "all_results": hyperparam_results,
            "best_params": best_params,
        },
        "threshold_tuning": {
            "method": threshold_method,
            "swept_against": "validation split predict_proba only",
            "chosen_threshold": chosen_threshold,
            "full_sweep": threshold_sweep,
        },
        "test_set_confusion_matrix": cm,
        "test_set_metrics": metrics,
        "test_set_per_failure_type": per_failure_type,
        "feature_importances": feature_importances,
        "v1_5_benchmark": V1_5_BENCHMARK,
        "meets_trust_condition": meets_trust_condition,
    }


def _print_report(results: dict) -> None:
    print("=== Split sizes and class balance ===")
    header = f"{'split':<8}{'rows':>8}{'positives':>11}{'negatives':>11}{'positive_rate':>15}"
    print(header)
    print("-" * len(header))
    for split_name in ("train", "val", "test"):
        s = results["split_summary"][split_name]
        print(f"{s['split']:<8}{s['rows']:>8}{s['positives']:>11}{s['negatives']:>11}{s['positive_rate_pct']:>14.2f}%")

    print("\n=== Hyperparameter sweep (selected by validation average precision) ===")
    for r in results["hyperparameter_sweep"]["all_results"]:
        marker = "  <-- best" if r["params"] == results["hyperparameter_sweep"]["best_params"] else ""
        print(f"  {r['params']}  val_avg_precision={r['val_average_precision']}{marker}")
    print(f"Best params: {results['hyperparameter_sweep']['best_params']}")

    print(f"\n=== Threshold tuning ===\nMethod: {results['threshold_tuning']['method']}")
    print(f"Swept against: {results['threshold_tuning']['swept_against']}")
    print(f"Chosen threshold: {results['threshold_tuning']['chosen_threshold']}")
    print(f"{'threshold':>10}{'precision':>12}{'recall':>10}{'f1':>8}")
    for s in results["threshold_tuning"]["full_sweep"]:
        marker = "  <-- chosen" if s["threshold"] == results["threshold_tuning"]["chosen_threshold"] else ""
        print(
            f"{s['threshold']:>10.2f}{_fmt_pct(s['precision']):>12}{_fmt_pct(s['recall']):>10}"
            f"{s['f1']:>8.3f}{marker}"
        )

    print("\n=== Test-set evaluation (held out, touched once) ===")
    cm = results["test_set_confusion_matrix"]
    m = results["test_set_metrics"]
    print(f"{'TP':>6}{'FP':>6}{'TN':>6}{'FN':>6}")
    print(f"{cm['true_positives']:>6}{cm['false_positives']:>6}{cm['true_negatives']:>6}{cm['false_negatives']:>6}")
    print(
        f"precision: {_fmt_pct(m['precision'])}   recall: {_fmt_pct(m['recall'])}   "
        f"f1: {m['f1']:.3f}   accuracy: {_fmt_pct(m['accuracy'])}"
    )

    print("\n=== Per-failure-type breakdown (test set) ===")
    header2 = f"{'failure_type':<14}{'real_instances':>15}{'caught':>8}{'missed':>8}{'recall':>9}"
    print(header2)
    print("-" * len(header2))
    for failure_type, d in results["test_set_per_failure_type"].items():
        print(
            f"{failure_type:<14}{d['real_instances']:>15}{d['caught']:>8}{d['missed']:>8}"
            f"{_fmt_pct(d['recall_pct'] / 100 if d['recall_pct'] is not None else None):>9}"
        )

    print("\n=== Feature importances (Random Forest, global) ===")
    for feature, importance in results["feature_importances"].items():
        print(f"  {feature:<28}{importance:.4f}")

    print("\n=== Trust condition (v1.5 benchmark: 75.0% precision / 29.2% recall) ===")
    b = results["v1_5_benchmark"]
    print(f"v1.5:  precision={_fmt_pct(b['precision'])}  recall={_fmt_pct(b['recall'])}  accuracy={_fmt_pct(b['accuracy'])}")
    print(
        f"v2:    precision={_fmt_pct(m['precision'])}  recall={_fmt_pct(m['recall'])}  accuracy={_fmt_pct(m['accuracy'])}"
    )
    print(f"Meets trust condition (BOTH precision AND recall genuinely improve): {results['meets_trust_condition']}")


if __name__ == "__main__":
    results = run()
    _print_report(results)

    existing = json.loads(RESULTS_PATH.read_text()) if RESULTS_PATH.exists() else {}
    existing["v2_ml_classifier"] = results
    RESULTS_PATH.write_text(json.dumps(existing, indent=2, default=str))
    print(f"\nResults written to {RESULTS_PATH} (key: v2_ml_classifier, existing v1/v1.5 entries preserved)")
