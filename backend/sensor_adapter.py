"""
Version A adapter (forward-looking stretch — see sensor_detection_version_a.md):
translates AI4I 2020 sensor rows into the same shared DiscrepancyEvent shape
detection.py's ERP rules and human_report.py's floor reports already produce,
so diagnosis.py, ticketing, and notification logic run unchanged regardless
of source. Tesla has no real plant sensors today — AI4I stands in for real
telemetry, and this whole module is the "ready to retrain the moment sensors
exist" piece, not a claim of solving a problem Tesla has right now.

Known simplification: `Product ID` is used as the shared schema's entity_id,
but in AI4I it turns out to be unique per row (confirmed against the real
file — see data-gen/sensor/data_summary.json), not a repeated physical-
machine identifier the way a real plant's asset tag would be. So unlike the
ERP/human-report paths, there's no "has this machine failed before" history
to draw on for a sensor event — same spirit as the BOM-quantity
simplification on the Odoo side, called out explicitly rather than implied.

AI4I carries no real per-row timestamp column, so events get a synthetic one
(wall-clock time of the adapter run) — documented here rather than implied
to be a real sensor-reading time.
"""
import json
import math
from datetime import datetime
from pathlib import Path

import joblib
import pandas as pd

from schemas import DiscrepancyEvent

_MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL_PATH = _MODULE_DIR / "model_v2.pkl"
DEFAULT_MODEL_META_PATH = _MODULE_DIR / "model_v2_meta.json"

SENSOR_COLUMNS = [
    "Air temperature [K]",
    "Process temperature [K]",
    "Rotational speed [rpm]",
    "Torque [Nm]",
    "Tool wear [min]",
]

# Physics-level composite features, added to catch the failure modes the
# five raw columns are structurally blind to (see the module docstring's
# known limitation) — three of AI4I's five failure types are defined by
# *combinations* of sensors, not any single raw column crossing a
# threshold: HDF ties a temperature differential to rotational speed, PWF
# is a power (torque x speed) condition, OSF is a strain (torque x wear)
# condition. These are standard derived quantities computed and thresholded
# the same statistical way as the raw five (baseline mean/std from
# Machine failure==0 rows, per-column z-score, k swept against real
# labels) — not AI4I's literal label-generation constants (e.g. the
# 8.6K/1380rpm HDF rule), which are never referenced here.
DERIVED_COLUMNS = [
    "temp_differential",
    "mechanical_power",
    "strain_proxy",
]

ALL_SENSOR_COLUMNS = SENSOR_COLUMNS + DERIVED_COLUMNS


def _mechanical_power(torque_nm, rotational_speed_rpm):
    """Torque x angular velocity, in watts — rotational speed is converted
    from rpm to rad/s (2*pi*rpm/60) first so the result is real mechanical
    power rather than an arbitrary torque*rpm product in mixed units.
    """
    return torque_nm * (2 * math.pi * rotational_speed_rpm / 60.0)


def add_derived_features_df(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorized version of the three derived features, for baseline
    computation over the whole dataset. Returns a copy — does not mutate
    `df`.
    """
    df = df.copy()
    df["temp_differential"] = df["Process temperature [K]"] - df["Air temperature [K]"]
    df["mechanical_power"] = _mechanical_power(df["Torque [Nm]"], df["Rotational speed [rpm]"])
    df["strain_proxy"] = df["Torque [Nm]"] * df["Tool wear [min]"]
    return df


def add_derived_features_row(row: dict) -> dict:
    """Per-row version of the same three derived features, for use on a
    single AI4I row dict (e.g. inside process_row). Returns a new dict —
    does not mutate `row`.
    """
    row = dict(row)
    row["temp_differential"] = row["Process temperature [K]"] - row["Air temperature [K]"]
    row["mechanical_power"] = _mechanical_power(row["Torque [Nm]"], row["Rotational speed [rpm]"])
    row["strain_proxy"] = row["Torque [Nm]"] * row["Tool wear [min]"]
    return row

# Tuned per column against eval_detection_sensor.py's real precision/recall
# over the full 10,000-row dataset (Section 4) — started at a uniform k=3
# per sensor_detection_version_a.md Section 1, then adjusted per column
# using that script's per-column diagnostics (data-gen/sensor/
# sensor_detection_eval.json has the full k-sweep and final confusion
# matrix). None of these were assumed; each was picked from the swept
# numbers:
#   - Torque [Nm]: k=3.0 kept as-is — already 95.5% precision (42/44) at
#     that threshold, the best column by far.
#   - Rotational speed [rpm]: raised 3.0 -> 5.5. At k=3.0 it catches 33 real
#     failures but drags in 153 false alarms (17.7% precision); at k=5.5 it
#     still catches 28 of those 33 with only 9 false alarms (75.7%
#     precision) — a much better trade for 5 fewer hits.
#   - Tool wear [min]: lowered 3.0 -> 2.0. At k=3.0 (and above) it catches
#     nothing at all; k=2.0 is the loosest threshold with real signal
#     (31.2% precision, 10 hits) rather than pure noise.
#   - Air temperature [K] / Process temperature [K]: left at k=3.0. Neither
#     column ever clears ~5% precision at any k tried (1.0-6.0) — the
#     signal isn't there standalone, consistent with AI4I's HDF failure
#     mode being a temperature-differential-vs-rpm *combination* rather
#     than either sensor being individually extreme (see the module
#     docstring's known limitation). Keeping k=3.0 means these two
#     contribute zero false alarms rather than chasing recall at a cost of
#     ~19-to-1 false alarms per real hit.
#   - mechanical_power / strain_proxy: k=3.0 — both essentially clean at
#     that threshold (100% precision standalone: 48/48 and 32/32). These
#     directly target PWF and OSF, which are close to genuinely being
#     single-derived-quantity conditions, and it shows: aggregate PWF
#     recall goes 58.9% -> 72.6% and OSF 10.2% -> 35.7% once these two are
#     added, at zero added false alarms.
#   - temp_differential: also left at k=3.0 (inert — 0 standalone
#     detections), despite being real signal at looser k. This one's a
#     genuine precision/recall trade, not a clear win like the two above,
#     and was decided explicitly rather than defaulted into:
#       k=3.0 (chosen): aggregate 75.0% precision / 29.2% recall / 97.3%
#         accuracy. HDF recall stays weak (5.2%, only incidental overlap
#         via mechanical_power/strain_proxy on multi-label rows).
#       k=2.0 (considered, rejected): HDF recall jumps to 31.3% (36/115),
#         but temp_differential alone drags in 244 false alarms against 38
#         hits, crashing aggregate precision to 32.4% (recall 38.9%).
#       k=1.5 (considered, rejected): HDF recall reaches 89.6% (103/115),
#         but aggregate precision falls to 19.1% — worse than the original
#         5-raw-column baseline (66.7%) this whole exercise started from.
#     k=3.0 was picked to keep the headline numbers pitch-defensible; HDF's
#     partial-only fix (5.2% recall, up from 0.9% pre-derived-features) is
#     the honest, stated cost of that choice — see
#     data-gen/sensor/sensor_detection_eval.json's per_failure_type
#     breakdown, which records the rejected k=2.0/1.5 alternatives too.
DEFAULT_K_PER_COLUMN: dict[str, float] = {
    "Air temperature [K]": 3.0,
    "Process temperature [K]": 3.0,
    "Rotational speed [rpm]": 5.5,
    "Torque [Nm]": 3.0,
    "Tool wear [min]": 2.0,
    "temp_differential": 3.0,
    "mechanical_power": 3.0,
    "strain_proxy": 3.0,
}

# Known, stated limitation (see sensor_detection_version_a.md Section 1.4):
# this only flags individual sensor columns crossing their own threshold.
# AI4I's own failure modes are partly defined by *combinations* of sensors
# (e.g. HDF ties temperature differential to rotational speed together) — a
# single-column threshold detector structurally can't catch a combination
# that trips only when read jointly, no matter how k is tuned per column.


def compute_baselines(
    df: pd.DataFrame, columns: list[str] = ALL_SENSOR_COLUMNS
) -> dict[str, dict[str, float]]:
    """Per-column mean/std of "normal" operation, i.e. computed only from
    rows where Machine failure == 0 — so a row's own failure doesn't pollute
    what "normal" means for judging it (or any other row).

    `columns` defaults to every raw + derived column; pass `SENSOR_COLUMNS`
    to get the original raw-only baselines (e.g. to reproduce the
    pre-derived-features numbers for comparison — see
    eval_detection_sensor.py). Derived columns are computed on the fly if
    `df` doesn't already carry them.
    """
    if any(col in DERIVED_COLUMNS for col in columns) and not set(DERIVED_COLUMNS).issubset(df.columns):
        df = add_derived_features_df(df)
    normal = df[df["Machine failure"] == 0]
    return {col: {"mean": float(normal[col].mean()), "std": float(normal[col].std())} for col in columns}


def detect_deviations(
    row: dict,
    baselines: dict[str, dict[str, float]],
    k_per_column: dict[str, float] | None = None,
) -> list[dict]:
    """Compare one AI4I row (a plain dict, e.g. from
    `df.to_dict("records")`) against the baselines, independently per
    column. Iterates over whatever columns `baselines` was computed for
    (raw, derived, or both) rather than a hardcoded list, so it
    automatically extends to however many columns the caller is checking —
    a column missing from `row` (e.g. a derived feature the caller didn't
    compute for this particular row) is skipped rather than treated as an
    error. Returns one deviation dict per column whose reading falls more
    than that column's `k` standard deviations from its baseline mean —
    empty list if the row is clean on every column checked.
    """
    k_per_column = k_per_column or DEFAULT_K_PER_COLUMN
    deviations = []
    for col, baseline in baselines.items():
        if col not in row:
            continue
        std = baseline["std"]
        if not std:
            continue
        z_score = (row[col] - baseline["mean"]) / std
        k = k_per_column.get(col, 3.0)
        if abs(z_score) > k:
            deviations.append(
                {
                    "column": col,
                    "value": row[col],
                    "baseline_mean": baseline["mean"],
                    "baseline_std": std,
                    "z_score": z_score,
                    "direction": "above" if z_score > 0 else "below",
                }
            )
    return deviations


DEFAULT_TOP_N_RANKED = 3


def rank_all_deviations(
    row: dict,
    baselines: dict[str, dict[str, float]],
    k_per_column: dict[str, float] | None = None,
    top_n: int = DEFAULT_TOP_N_RANKED,
) -> list[dict]:
    """Z-scores for *every* column in `baselines` (raw + derived), computed
    regardless of whether each one crosses its own tuned `k` — unlike
    `detect_deviations`, which only returns columns that actually crossed
    their threshold and can come back empty. This exists specifically so
    the description layer always has something to report for a row the ML
    gate flags: the v2 model can flag a row via a combination that never
    crosses any single column's threshold (see MLGate above), and in that
    case `detect_deviations` alone would leave `gather_sensor_context` with
    nothing to say.

    Ranks by absolute z-score magnitude (largest deviation first) and
    returns the top `top_n`. Each entry carries `crossed_threshold` so the
    caller (gather_context_sensor.gather_sensor_context) can phrase it
    honestly — "exceeded normal range" for an actual threshold violation vs.
    "furthest from normal, though not individually abnormal" when it's
    merely the most unusual reading among several that never crossed
    anything. Never returns an empty list for a row with at least one
    column present with nonzero baseline std, so a flagged row always has
    at least one thing to describe.
    """
    k_per_column = k_per_column or DEFAULT_K_PER_COLUMN
    scored = []
    for col, baseline in baselines.items():
        if col not in row:
            continue
        std = baseline["std"]
        if not std:
            continue
        z_score = (row[col] - baseline["mean"]) / std
        k = k_per_column.get(col, 3.0)
        scored.append(
            {
                "column": col,
                "value": row[col],
                "baseline_mean": baseline["mean"],
                "baseline_std": std,
                "z_score": z_score,
                "direction": "above" if z_score > 0 else "below",
                "crossed_threshold": abs(z_score) > k,
            }
        )
    scored.sort(key=lambda d: abs(d["z_score"]), reverse=True)
    return scored[:top_n]


def is_anomalous(
    row: dict,
    baselines: dict[str, dict[str, float]],
    k_per_column: dict[str, float] | None = None,
) -> bool:
    return bool(detect_deviations(row, baselines, k_per_column))


class MLGate:
    """Wraps the persisted v2 Random Forest (model_v2.pkl + model_v2_meta.json
    — see persist_model_v2.py) so it can replace the z-score threshold as
    the thing that decides anomalous-or-not (sensor_detection_version_a.md
    Section 1.5). The z-score/derived-feature deviations from
    detect_deviations keep running unchanged regardless of which gate is
    active — they describe *what* looked off; this only decides *whether*
    to raise a flag at all.
    """

    def __init__(self, model, feature_columns: list[str], threshold: float):
        self.model = model
        self.feature_columns = feature_columns
        self.threshold = threshold

    def predict_proba(self, row: dict) -> float:
        frame = pd.DataFrame([{col: row[col] for col in self.feature_columns}])
        return float(self.model.predict_proba(frame)[0, 1])

    def is_anomalous(self, row: dict) -> tuple[bool, float]:
        proba = self.predict_proba(row)
        return proba >= self.threshold, proba


def load_ml_gate(model_path: Path = DEFAULT_MODEL_PATH, meta_path: Path = DEFAULT_MODEL_META_PATH) -> MLGate:
    """Loads the model once — callers should hold onto the returned MLGate
    and reuse it across every row rather than reloading per row.
    """
    model = joblib.load(model_path)
    meta = json.loads(Path(meta_path).read_text())
    return MLGate(model, meta["feature_columns"], meta["classification_threshold"])


def deviations_to_events(
    entity_id: str,
    deviations: list[dict],
    timestamp: str | None = None,
) -> list[DiscrepancyEvent]:
    """One DiscrepancyEvent per deviating column, not one event bundling every
    deviating column together — keeps expected_value/actual_value scalar,
    matching every other adapter in this codebase (stuck_order,
    quantity_mismatch, etc. all carry exactly one field per event); a
    multi-column event would break that convention for every downstream
    consumer that expects a single expected/actual pair. `field` is set to
    `dev["column"]` directly, so a deviation on a derived feature reads as
    its own thing (e.g. "mechanical_power") rather than being reported
    under one of the raw sensor names it's built from — gather_context_sensor.py
    and the Slack message can then reference it distinctly.
    """
    timestamp = timestamp or datetime.now().isoformat()
    return [
        DiscrepancyEvent(
            source="sensor",
            entity_id=entity_id,
            field=dev["column"],
            expected_value=round(dev["baseline_mean"], 3),
            actual_value=dev["value"],
            timestamp=timestamp,
            anomaly_type="sensor_deviation",
        )
        for dev in deviations
    ]


def process_row(
    row: dict,
    baselines: dict[str, dict[str, float]],
    k_per_column: dict[str, float] | None = None,
    timestamp: str | None = None,
    ml_gate: MLGate | None = None,
) -> dict:
    """Full adapter output for one row: the shared event(s) if flagged, plus
    the deviation detail itself (which column(s), by how much, which
    direction) — per sensor_detection_version_a.md Section 1, that detail
    isn't discarded on the way to the event schema, since gather_context and
    the diagnosis agent need it to reason about which failure type is
    plausible, and the shared DiscrepancyEvent schema has no room to carry
    z-scores/direction itself.

    Adds the three derived features (temp_differential, mechanical_power,
    strain_proxy) to `row` before checking it, regardless of whether the
    caller already computed them — so this is the one place real usage is
    guaranteed to check all eight signals, raw and derived, without every
    caller having to remember to call add_derived_features_row itself.

    `ml_gate`, when given, replaces the z-score threshold as the thing that
    decides `flagged` (Section 1.5's v2) — `detect_deviations` still runs in
    full either way, since it's the description ("which sensors were off,
    by how much"), not the gate; `events` (the shared DiscrepancyEvent
    schema) only cover columns that actually crossed their threshold, same
    as before. Separately, `ranked_deviations` (via `rank_all_deviations`)
    always carries the top-N columns by z-score magnitude regardless of
    whether any crossed their threshold — this is what
    gather_context_sensor.gather_sensor_context should be given, so an
    ML-only catch (one that never crosses any single column's threshold)
    still comes with real, honestly-labeled evidence instead of an empty
    description. Omit `ml_gate` (the default) to keep the original v1/v1.5
    behavior, where `deviations` are both the description and the gate —
    this is what eval_detection_sensor.py and the existing test suite still
    exercise.
    """
    row = add_derived_features_row(row)
    deviations = detect_deviations(row, baselines, k_per_column)
    ranked_deviations = rank_all_deviations(row, baselines, k_per_column)

    if ml_gate is not None:
        flagged, ml_probability = ml_gate.is_anomalous(row)
    else:
        flagged, ml_probability = bool(deviations), None

    events = deviations_to_events(row["Product ID"], deviations, timestamp) if flagged and deviations else []
    return {
        "entity_id": row["Product ID"],
        "udi": row.get("UDI"),
        "flagged": flagged,
        "ml_probability": ml_probability,
        "zscore_flagged": bool(deviations),
        "ranked_deviations": ranked_deviations,
        "deviations": deviations,
        "events": events,
    }


def process_dataframe(
    df: pd.DataFrame,
    baselines: dict[str, dict[str, float]] | None = None,
    k_per_column: dict[str, float] | None = None,
    ml_gate: MLGate | None = None,
) -> list[dict]:
    """Runs the adapter across every row of the dataframe. Returns one
    `process_row` result per row, in row order — including unflagged rows
    (with empty `deviations`/`events`), since eval_detection_sensor.py needs
    every row's flag status compared against its real label, not just the
    flagged ones.
    """
    baselines = baselines or compute_baselines(df)
    return [process_row(row, baselines, k_per_column, ml_gate=ml_gate) for row in df.to_dict("records")]
