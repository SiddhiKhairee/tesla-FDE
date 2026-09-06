"""
Unit tests for sensor_adapter.py — Version A's sensor-path adapter. Pure
fixture data (a tiny in-memory dataframe), no real AI4I CSV needed.
"""
import math

import pandas as pd
import pytest

from sensor_adapter import (
    ALL_SENSOR_COLUMNS,
    SENSOR_COLUMNS,
    add_derived_features_df,
    add_derived_features_row,
    compute_baselines,
    deviations_to_events,
    detect_deviations,
    is_anomalous,
    process_dataframe,
    process_row,
)


def _normal_rows(n: int) -> list[dict]:
    return [
        {
            "UDI": i,
            "Product ID": f"M{i:05d}",
            "Air temperature [K]": 298.0,
            "Process temperature [K]": 308.0,
            "Rotational speed [rpm]": 1500,
            "Torque [Nm]": 40.0,
            "Tool wear [min]": 100,
            "Machine failure": 0,
        }
        for i in range(n)
    ]


@pytest.fixture
def baseline_df():
    # 10 identical "normal" rows plus a couple of small, real variance so std
    # isn't exactly zero (a zero std would make every deviation infinite —
    # detect_deviations guards that case, but the fixture shouldn't rely on
    # the guard when it can just have real variance instead).
    rows = _normal_rows(10)
    for i, row in enumerate(rows):
        row["Air temperature [K]"] += (i % 3) * 0.1
        row["Torque [Nm]"] += (i % 3) * 0.5
        row["Tool wear [min]"] += (i % 3) * 2
    return pd.DataFrame(rows)


def test_compute_baselines_uses_only_non_failure_rows(baseline_df):
    df = pd.concat(
        [
            baseline_df,
            pd.DataFrame(
                [
                    {
                        "UDI": 999,
                        "Product ID": "M99999",
                        "Air temperature [K]": 500.0,  # wildly abnormal
                        "Process temperature [K]": 308.0,
                        "Rotational speed [rpm]": 1500,
                        "Torque [Nm]": 40.0,
                        "Tool wear [min]": 100,
                        "Machine failure": 1,  # excluded from baseline
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    baselines = compute_baselines(df)

    # The failure row's extreme reading must not have dragged the baseline
    # mean anywhere near 500.
    assert baselines["Air temperature [K]"]["mean"] < 300.0


def test_detect_deviations_flags_column_beyond_k_std(baseline_df):
    baselines = compute_baselines(baseline_df)
    row = {
        "Air temperature [K]": 350.0,  # far beyond baseline
        "Process temperature [K]": baselines["Process temperature [K]"]["mean"],
        "Rotational speed [rpm]": baselines["Rotational speed [rpm]"]["mean"],
        "Torque [Nm]": baselines["Torque [Nm]"]["mean"],
        "Tool wear [min]": baselines["Tool wear [min]"]["mean"],
    }

    deviations = detect_deviations(row, baselines)

    assert len(deviations) == 1
    assert deviations[0]["column"] == "Air temperature [K]"
    assert deviations[0]["direction"] == "above"
    assert is_anomalous(row, baselines) is True


def test_detect_deviations_clean_row_flags_nothing(baseline_df):
    baselines = compute_baselines(baseline_df)
    row = {col: baselines[col]["mean"] for col in SENSOR_COLUMNS}

    deviations = detect_deviations(row, baselines)

    assert deviations == []
    assert is_anomalous(row, baselines) is False


def test_detect_deviations_respects_per_column_k(baseline_df):
    baselines = compute_baselines(baseline_df)
    row = {col: baselines[col]["mean"] for col in SENSOR_COLUMNS}
    row["Tool wear [min]"] = baselines["Tool wear [min]"]["mean"] + 4 * (
        baselines["Tool wear [min]"]["std"] or 1.0
    )

    # Loose k (5) for tool wear: not flagged.
    assert detect_deviations(row, baselines, {"Tool wear [min]": 5.0}) == []
    # Tight k (1) for tool wear: flagged.
    deviations = detect_deviations(row, baselines, {"Tool wear [min]": 1.0})
    assert len(deviations) == 1
    assert deviations[0]["column"] == "Tool wear [min]"


def test_deviations_to_events_one_event_per_deviating_column():
    deviations = [
        {"column": "Air temperature [K]", "value": 350.0, "baseline_mean": 298.0, "baseline_std": 2.0, "z_score": 26.0, "direction": "above"},
        {"column": "Torque [Nm]", "value": 5.0, "baseline_mean": 40.0, "baseline_std": 5.0, "z_score": -7.0, "direction": "below"},
    ]

    events = deviations_to_events("M14860", deviations, timestamp="2026-01-01T00:00:00")

    assert len(events) == 2
    assert {e.field for e in events} == {"Air temperature [K]", "Torque [Nm]"}
    for event in events:
        assert event.source == "sensor"
        assert event.entity_id == "M14860"
        assert event.anomaly_type == "sensor_deviation"
        assert event.timestamp == "2026-01-01T00:00:00"


def test_process_dataframe_flags_only_deviating_rows(baseline_df):
    abnormal_row = dict(baseline_df.iloc[0])
    abnormal_row["Air temperature [K]"] = 500.0
    abnormal_row["Product ID"] = "M-ABNORMAL"
    abnormal_row["UDI"] = 12345
    df = pd.concat([baseline_df, pd.DataFrame([abnormal_row])], ignore_index=True)

    results = process_dataframe(df)

    flagged = [r for r in results if r["flagged"]]
    assert len(flagged) == 1
    assert flagged[0]["entity_id"] == "M-ABNORMAL"
    # An Air temperature spike legitimately also blows up temp_differential
    # (it's derived from that same reading) — both are expected to fire,
    # not just the raw column.
    flagged_columns = {dev["column"] for dev in flagged[0]["deviations"]}
    assert flagged_columns == {"Air temperature [K]", "temp_differential"}
    assert len(flagged[0]["events"]) == len(flagged[0]["deviations"])


def test_add_derived_features_row_computes_expected_values():
    row = {
        "Air temperature [K]": 298.0,
        "Process temperature [K]": 308.0,
        "Rotational speed [rpm]": 1500,
        "Torque [Nm]": 40.0,
        "Tool wear [min]": 100,
    }

    result = add_derived_features_row(row)

    assert result["temp_differential"] == pytest.approx(10.0)
    assert result["mechanical_power"] == pytest.approx(40.0 * (2 * math.pi * 1500 / 60.0))
    assert result["strain_proxy"] == pytest.approx(40.0 * 100)
    # Original row must not be mutated.
    assert "temp_differential" not in row


def test_add_derived_features_df_matches_row_version(baseline_df):
    df_with_derived = add_derived_features_df(baseline_df)
    row_derived = add_derived_features_row(dict(baseline_df.iloc[0]))

    assert df_with_derived.iloc[0]["temp_differential"] == pytest.approx(row_derived["temp_differential"])
    assert df_with_derived.iloc[0]["mechanical_power"] == pytest.approx(row_derived["mechanical_power"])
    assert df_with_derived.iloc[0]["strain_proxy"] == pytest.approx(row_derived["strain_proxy"])


def test_compute_baselines_defaults_to_all_columns_including_derived(baseline_df):
    baselines = compute_baselines(baseline_df)

    assert set(ALL_SENSOR_COLUMNS).issubset(baselines.keys())
    assert "temp_differential" in baselines
    assert "mechanical_power" in baselines
    assert "strain_proxy" in baselines


def test_compute_baselines_raw_only_excludes_derived(baseline_df):
    baselines = compute_baselines(baseline_df, columns=SENSOR_COLUMNS)

    assert set(baselines.keys()) == set(SENSOR_COLUMNS)


def test_detect_deviations_catches_derived_feature_when_raw_columns_disabled(baseline_df):
    """The point of the derived features: a deviation that only shows up on
    the combination, not on any raw column alone (the structural gap
    HDF/PWF/OSF exposed — see sensor_detection_version_a.md). Simulated
    here by giving every raw column an effectively infinite k (so none of
    them can ever fire) and a tight k for strain_proxy alone, then
    confirming strain_proxy is still the one that trips.
    """
    baselines = compute_baselines(baseline_df)
    row = {col: baselines[col]["mean"] for col in SENSOR_COLUMNS}
    row["Tool wear [min]"] = baselines["Tool wear [min]"]["mean"] * 1.5
    row = add_derived_features_row(row)

    k_per_column = {col: 1000.0 for col in SENSOR_COLUMNS}
    k_per_column["strain_proxy"] = 0.5

    deviations = detect_deviations(row, baselines, k_per_column)

    assert any(dev["column"] == "strain_proxy" for dev in deviations)
    assert all(dev["column"] not in SENSOR_COLUMNS for dev in deviations)


def test_process_row_field_names_derived_deviation_distinctly(baseline_df):
    baselines = compute_baselines(baseline_df)
    row = dict(baseline_df.iloc[0])
    row["Torque [Nm]"] = baselines["Torque [Nm]"]["mean"] * 5
    row["Tool wear [min]"] = baselines["Tool wear [min]"]["mean"] * 5

    result = process_row(row, baselines)

    fields = {event.field for event in result["events"]}
    # The derived deviation must be named as its own thing, not folded
    # into "Torque [Nm]" or "Tool wear [min]".
    assert "strain_proxy" in fields or "mechanical_power" in fields
