"""
Persists the v2 Random Forest classifier (sensor_detection_version_a.md
Section 1.5) so it doesn't need retraining every time something downstream
needs a prediction — the live demo, a diagnosis-agent eval, or anything
else. See tests/test_model_v2_persistence.py for the fresh-process sanity
check that the saved artifact actually reproduces ml_detector.py's reported
test-set confusion matrix (57 TP / 15 FP / 1917 TN / 11 FN) rather than
something that drifted during saving.

Hyperparameters and threshold below are hardcoded to the exact winning
values ml_detector.py's grid search and threshold sweep already found and
reported — this script does not re-run that search. Deliberately fits on
the train split only (not train+val combined), so the saved model is
bit-identical to the one those already-reported test-set numbers describe,
not a slightly different model trained on more data.

Usage (from backend/, with the venv active):
    python persist_model_v2.py
Writes model_v2.pkl and model_v2_meta.json alongside this script.
"""
import json
from pathlib import Path

import joblib
from sklearn.ensemble import RandomForestClassifier

from ml_detector import ALL_SENSOR_COLUMNS, RANDOM_STATE, load_dataset, split_dataset

MODEL_PATH = Path(__file__).resolve().parent / "model_v2.pkl"
META_PATH = Path(__file__).resolve().parent / "model_v2_meta.json"

# Exact winning configuration from ml_detector.py's hyperparameter sweep and
# threshold sweep (see data-gen/sensor/sensor_detection_eval.json's
# v2_ml_classifier entry) — not re-derived here, just applied.
BEST_PARAMS = {"n_estimators": 300, "max_depth": 10, "min_samples_leaf": 5}
CHOSEN_THRESHOLD = 0.60

# The exact confusion matrix ml_detector.py reported on the test split for
# this configuration — used as an immediate self-check that refitting with
# the same random_state on the same (deterministic) split reproduces the
# same model, before this artifact is trusted enough to save.
EXPECTED_TEST_CONFUSION_MATRIX = {
    "true_positives": 57,
    "false_positives": 15,
    "true_negatives": 1917,
    "false_negatives": 11,
}


def _confusion_matrix(y_true, y_pred) -> dict:
    tp = int(((y_pred == 1) & (y_true == 1)).sum())
    fp = int(((y_pred == 1) & (y_true == 0)).sum())
    tn = int(((y_pred == 0) & (y_true == 0)).sum())
    fn = int(((y_pred == 0) & (y_true == 1)).sum())
    return {"true_positives": tp, "false_positives": fp, "true_negatives": tn, "false_negatives": fn}


def main() -> None:
    df = load_dataset()
    df_train, df_val, df_test, y_train, y_val, y_test = split_dataset(df)
    X_train = df_train[ALL_SENSOR_COLUMNS]
    X_test = df_test[ALL_SENSOR_COLUMNS]

    model = RandomForestClassifier(
        class_weight="balanced", random_state=RANDOM_STATE, n_jobs=-1, **BEST_PARAMS
    )
    model.fit(X_train, y_train)

    # Self-check before saving: this refit must reproduce the exact
    # confusion matrix ml_detector.py already reported, or something about
    # the split/params/random_state has drifted and the artifact shouldn't
    # be trusted.
    test_proba = model.predict_proba(X_test)[:, 1]
    test_pred = (test_proba >= CHOSEN_THRESHOLD).astype(int)
    cm = _confusion_matrix(y_test, test_pred)
    if cm != EXPECTED_TEST_CONFUSION_MATRIX:
        raise RuntimeError(
            f"Refit confusion matrix {cm} does not match the previously reported "
            f"{EXPECTED_TEST_CONFUSION_MATRIX} — refusing to save a drifted model. "
            "Check that ml_detector.py's split_dataset/RANDOM_STATE haven't changed."
        )
    print(f"Self-check passed: refit reproduces the reported test-set confusion matrix {cm}")

    joblib.dump(model, MODEL_PATH)

    meta = {
        "feature_columns": ALL_SENSOR_COLUMNS,
        "classification_threshold": CHOSEN_THRESHOLD,
        "threshold_note": (
            "Not part of the sklearn model object — predict_proba has no concept of "
            "it. Anything loading this model must read this threshold from here "
            "rather than hardcoding 0.5 or any other value separately."
        ),
        "random_state": RANDOM_STATE,
        "hyperparameters": {"class_weight": "balanced", **BEST_PARAMS},
        "training_data": "train split only (60% of data-gen/sensor/ai4i2020.csv, stratified on Machine failure) — not train+val combined",
        "split_method": (
            "Two-stage stratified train_test_split via ml_detector.split_dataset: "
            "60/20/20 train/val/test, stratified on Machine failure at each stage, "
            f"random_state={RANDOM_STATE}"
        ),
        "reported_test_set_confusion_matrix": EXPECTED_TEST_CONFUSION_MATRIX,
        "reported_test_set_metrics_source": "data-gen/sensor/sensor_detection_eval.json (key: v2_ml_classifier)",
    }
    META_PATH.write_text(json.dumps(meta, indent=2))

    print(f"Model saved to {MODEL_PATH}")
    print(f"Metadata saved to {META_PATH}")


if __name__ == "__main__":
    main()
