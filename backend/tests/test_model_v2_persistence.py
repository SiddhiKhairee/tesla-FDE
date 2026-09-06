"""
Sanity check that the persisted v2 model artifact (model_v2.pkl +
model_v2_meta.json) is actually the model ml_detector.py evaluated and
reported — not something that drifted during saving. Every pytest run is
its own fresh process, so loading via joblib here genuinely exercises
"a new process loading the saved artifact from disk," not reuse of
whatever was in memory when persist_model_v2.py ran.

Requires model_v2.pkl / model_v2_meta.json to exist (run persist_model_v2.py
first) and data-gen/sensor/ai4i2020.csv (Section 0) to rebuild the same
deterministic split the model was evaluated against.
"""
import json
from pathlib import Path

import joblib
import pytest

from ml_detector import ALL_SENSOR_COLUMNS, load_dataset, split_dataset

MODEL_PATH = Path(__file__).resolve().parent.parent / "model_v2.pkl"
META_PATH = Path(__file__).resolve().parent.parent / "model_v2_meta.json"

# The exact confusion matrix reported in data-gen/sensor/sensor_detection_eval.json
# under v2_ml_classifier's test_set_confusion_matrix — the number this test
# exists to reproduce from the saved artifact alone.
EXPECTED_CONFUSION_MATRIX = {
    "true_positives": 57,
    "false_positives": 15,
    "true_negatives": 1917,
    "false_negatives": 11,
}

pytestmark = pytest.mark.skipif(
    not (MODEL_PATH.exists() and META_PATH.exists()),
    reason="model_v2.pkl/model_v2_meta.json not present — run persist_model_v2.py first",
)


@pytest.fixture(scope="module")
def meta() -> dict:
    return json.loads(META_PATH.read_text())


@pytest.fixture(scope="module")
def model():
    return joblib.load(MODEL_PATH)


def test_metadata_feature_order_matches_ml_detector(meta):
    assert meta["feature_columns"] == ALL_SENSOR_COLUMNS


def test_metadata_carries_threshold_not_hardcoded_elsewhere(meta):
    assert meta["classification_threshold"] == 0.60


def test_loaded_model_reproduces_reported_test_confusion_matrix(model, meta):
    df = load_dataset()
    _, _, df_test, _, _, y_test = split_dataset(df)
    X_test = df_test[meta["feature_columns"]]

    proba = model.predict_proba(X_test)[:, 1]
    pred = (proba >= meta["classification_threshold"]).astype(int)

    tp = int(((pred == 1) & (y_test == 1)).sum())
    fp = int(((pred == 1) & (y_test == 0)).sum())
    tn = int(((pred == 0) & (y_test == 0)).sum())
    fn = int(((pred == 0) & (y_test == 1)).sum())
    cm = {"true_positives": tp, "false_positives": fp, "true_negatives": tn, "false_negatives": fn}

    assert cm == EXPECTED_CONFUSION_MATRIX
