#!/usr/bin/env python3
"""Focused M100 v3 closure tests. Synthetic where possible."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from m100_suitability_v2 import expanding_folds  # noqa: E402
from m100_suitability_v3 import (  # noqa: E402
    FORMULAS,
    LITERATURE,
    R1_FORBIDDEN,
    active_liquid_panel,
    build_contract,
    complete_case_mask,
    coverage_status,
    design_W,
    energy_quality_mask,
    expanding_folds as expanding_folds_v3,
    hq_mask_from_coverage,
    independent_wetbulb,
    joint_support_label,
    lag_pairs,
    predict_d1_one_step,
    predict_d1_recursive,
    stull_wetbulb_c,
    support_label,
    w_feature_names,
    within_month_split,
)


def test_no_future_leakage_all_folds():
    months = [f"2021-{m:02d}" for m in range(4, 13)]
    folds = expanding_folds(months)
    assert folds == expanding_folds_v3(months)
    for f in folds:
        assert f["test_month"] not in f["train_months"]
        assert all(t < f["test_month"] for t in f["train_months"])


def test_w0_w1_w2_nested_formulas():
    n = 30
    df = pd.DataFrame({
        "P_IT": np.linspace(700, 900, n),
        "T_wetbulb": np.linspace(8, 20, n),
        "cooling_state": np.linspace(0, 1, n),
    })
    x0, i0, n0 = design_W(df, "W0")
    assert i0 and n0 == ("P_IT",) and x0.shape == (n, 1)
    x1, i1, n1 = design_W(df, "W1")
    assert n1 == ("P_IT", "T_wetbulb") and x1.shape[1] == 2
    x2, _, n2 = design_W(df, "W2")
    assert n2 == ("P_IT", "T_wetbulb", "P_IT:T_wetbulb")
    np.testing.assert_allclose(x2[:, 2], df["P_IT"] * df["T_wetbulb"])
    assert FORMULAS["W1"].startswith("P_nonIT")
    assert "P_IT*T_wb" in FORMULAS["W2"] or "P_IT*T_wb" in FORMULAS["W2"].replace(" ", "")


def test_identical_timestamps_nested():
    hours = pd.date_range("2021-05-01", periods=12, freq="h", tz="UTC")
    df = pd.DataFrame({
        "hour_utc": hours,
        "P_IT": 800.0,
        "P_nonIT": 300.0,
        "P_facility": 1100.0,
        "T_wetbulb": 12.0,
    })
    m = complete_case_mask(df, ["P_IT", "P_nonIT", "P_facility", "T_wetbulb"])
    sub = df.loc[m]
    assert (sub["hour_utc"].to_numpy() == hours.to_numpy()).all()
    assert w_feature_names("W0")[0] == "P_IT"
    assert w_feature_names("W1")[:1] == ("P_IT",)
    assert w_feature_names("W2")[:2] == ("P_IT", "T_wetbulb")


def test_state_interactions_no_hti_flow():
    names = w_feature_names("R1")
    assert "cooling_state" in names
    assert "state:P_IT" in names
    assert set(names).isdisjoint(R1_FORBIDDEN)
    assert "heat_transfer_index" not in names
    df = pd.DataFrame({
        "P_IT": [800.0], "T_wetbulb": [10.0], "cooling_state": [1.0],
        "heat_transfer_index": [999.0],
    })
    _, _, n3 = design_W(df, "R1")
    assert "heat_transfer_index" not in n3


def test_one_step_and_recursive_paths_distinct():
    rng = np.random.default_rng(0)
    n = 48
    hours = pd.date_range("2021-07-01", periods=n, freq="h", tz="UTC")
    pit = 800 + rng.normal(0, 10, n)
    twb = 15 + rng.normal(0, 1, n)
    y = 200 + 0.3 * pit + 4 * twb + 0.6 * np.concatenate([[200], np.zeros(n - 1)])
    # AR-ish
    for i in range(1, n):
        y[i] = 0.4 * y[i - 1] + 0.2 * pit[i] + 3 * twb[i]
    df = pd.DataFrame({"hour_utc": hours, "P_IT": pit, "T_wetbulb": twb, "P_nonIT": y, "P_facility": pit + y})
    tr, te = df.iloc[:32], df.iloc[32:]
    from m100_suitability_v3 import fit_d1
    pairs_tr = lag_pairs(tr, "P_nonIT")
    pairs_te = lag_pairs(te, "P_nonIT")
    beta, _ = fit_d1(pairs_tr)
    os_ = predict_d1_one_step(beta, pairs_te)
    rec = predict_d1_recursive(beta, te, float(tr["P_nonIT"].iloc[-1]))
    assert os_.shape[0] == len(pairs_te)
    assert rec.shape[0] == len(te)
    assert not np.allclose(os_, rec[:len(os_)], atol=1e-8, equal_nan=True)


def test_recursive_never_uses_future_observed_target():
    n = 10
    hours = pd.date_range("2021-08-01", periods=n, freq="h", tz="UTC")
    te = pd.DataFrame({
        "hour_utc": hours,
        "P_IT": np.full(n, 800.0),
        "T_wetbulb": np.full(n, 12.0),
        "P_nonIT": np.linspace(100, 400, n),  # would leak if used
        "P_facility": 900.0,
    })
    beta = np.array([10.0, 0.0, 0.0, 0.0, 0.9])  # intercept + W2 zeros + phi
    rec = predict_d1_recursive(beta, te, y0=50.0)
    # With zero W2 weights, pred_t = 10 + 0.9 * pred_{t-1}, independent of observed y
    expected = []
    prev = 50.0
    for _ in range(n):
        yhat = 10.0 + 0.9 * prev
        expected.append(yhat)
        prev = yhat
    np.testing.assert_allclose(rec, expected, rtol=1e-10)
    assert not np.allclose(rec, te["P_nonIT"].to_numpy())


def test_hq_mask_behavior():
    df = pd.DataFrame({"Tot_coverage": [0.95, 0.5, np.nan], "x": [1, 2, 3]})
    m = hq_mask_from_coverage(df, "Tot_coverage")
    assert list(m.astype(int)) == [1, 0, 0]
    st = coverage_status(["Tot_mean", "Tot_count"], "Tot")
    assert st["status"] == "HQ_COVERAGE_NOT_AVAILABLE"
    st2 = coverage_status(["Tot_coverage"], "Tot")
    assert st2["status"] == "AVAILABLE"
    m_missing = hq_mask_from_coverage(df, None)
    assert not m_missing.any()


def test_energy_accounting_missing_timestamps():
    df = pd.DataFrame({
        "Tot_energy_kwh": [10.0, np.nan, 12.0],
        "Tot_ict_energy_kwh": [8.0, 8.0, 9.0],
        "Tot_largest_gap_seconds": [10.0, 10.0, 500.0],
        "Tot_ict_largest_gap_seconds": [10.0, 10.0, 10.0],
        "P_IT": [1, 1, 1],
    })
    m = energy_quality_mask(df)
    # row0 ok; row1 missing Tot energy; row2 gap 500 > 180
    assert list(m.astype(int)) == [1, 0, 0]
    # do not fill missing hours
    assert np.isnan(df["Tot_energy_kwh"].iloc[1])


def test_wetbulb_qa_calculation():
    import psychrolib
    psychrolib.SetUnitSystem(psychrolib.SI)
    t, td, rh, p = 20.0, 10.0, 50.0, 101325.0
    out = independent_wetbulb(t, td, rh, p)
    assert np.isfinite(out["twb_from_tdew"])
    assert np.isfinite(out["twb_from_rh"])
    assert out["twb_from_tdew"] <= t + 1e-6
    twb_lib = psychrolib.GetTWetBulbFromTDewPoint(t, td, p)
    assert abs(out["twb_from_tdew"] - twb_lib) < 1e-8
    st = stull_wetbulb_c(np.array([t]), np.array([rh]))[0]
    assert np.isfinite(st)


def test_node_to_ict_coverage_logic():
    nodes = pd.DataFrame({
        "hour_utc": pd.to_datetime(["2021-05-01 00:00Z", "2021-05-01 00:00Z", "2021-05-01 01:00Z"]),
        "node": ["a", "b", "a"],
        "total_power_mean": [1000.0, 2000.0, 1500.0],  # Watts
        "high_quality": [True, True, False],
        "total_power_coverage": [1.0, 0.95, 0.2],
    })
    hq = nodes.loc[nodes["high_quality"]]
    agg = hq.groupby("hour_utc").agg(n_hq_nodes=("node", "nunique"), P_nodes_W=("total_power_mean", "sum"))
    agg["P_nodes_kW"] = agg["P_nodes_W"] / 1000.0
    assert float(agg.iloc[0]["P_nodes_kW"]) == 3.0
    assert int(agg.iloc[0]["n_hq_nodes"]) == 2
    # coverage-adjusted is diagnostic: do not force equality
    ict = 10.0
    raw_ratio = float(agg.iloc[0]["P_nodes_kW"] / ict)
    assert raw_ratio != 1.0


def test_support_extrapolation_labels():
    assert support_label(10, 5, 15, 0, 20) == "inside_train_p05_p95"
    assert support_label(3, 5, 15, 0, 20) == "inside_train_minmax_outside_p05_p95"
    assert support_label(-1, 5, 15, 0, 20) == "outside_train_minmax"
    assert joint_support_label(["inside_train_p05_p95", "outside_train_minmax"]) == "outside_train_minmax"
    assert joint_support_label(["inside_train_p05_p95", "inside_train_p05_p95"]) == "inside_train_p05_p95"


def test_q101_q102_active_path_selection():
    active = pd.Series({
        "Start_impianto_fraction_time_active": 1.0,
        "Portata_attiva_mean": 80.0,
        "P101_in_marcia_fraction_time_active": 1.0,
    })
    inactive = pd.Series({
        "Start_impianto_fraction_time_active": 0.0,
        "Portata_attiva_mean": 0.0,
        "P101_in_marcia_fraction_time_active": 0.0,
    })
    assert active_liquid_panel(active) == "active"
    assert active_liquid_panel(inactive) == "inactive"
    # do not median inactive with active in selection helper: statuses differ
    assert active_liquid_panel(active) != active_liquid_panel(inactive)


def test_literature_tagged_same_data_triangulation():
    assert LITERATURE["independence"] == "same-data triangulation; not independent validation"
    blob = json.dumps(LITERATURE)
    assert "independent validation" in blob
    assert "not independent" in blob or "same-data" in blob


def test_generic_contract_from_evidence_not_hardcoded():
    ev_strong = {
        "facility_decomposition": "STRONG SUPPORT",
        "weather_additive": "STRONG SUPPORT",
        "weather_interaction": "MIXED / REGIME-DEPENDENT",
        "regime_interaction": "NOT SUPPORTED",
        "pue_derived": "STRONG SUPPORT",
        "temporal_state": "STRONG SUPPORT",
        "water": "UNSUPPORTED BY AVAILABLE DATA",
        "generic_coefficients": "NOT IDENTIFIED BY M100",
        "generic_pue": "NOT IDENTIFIED BY M100",
        "generic_cooling_fraction": "NOT IDENTIFIED BY M100",
        "universal_weather_variable": "NOT IDENTIFIED BY M100",
        "universal_thresholds": "NOT IDENTIFIED BY M100",
        "generic_state_parameters": "NOT IDENTIFIED BY M100",
        "modern_ai_it": "NOT IDENTIFIED BY M100",
    }
    ev_none = dict(ev_strong)
    ev_none["weather_additive"] = "NOT SUPPORTED"
    ev_none["facility_decomposition"] = "UNSUPPORTED BY AVAILABLE DATA"
    c_strong = build_contract(ev_strong)
    c_none = build_contract(ev_none)
    claims_s = " ".join(x["claim"] for x in c_strong["STRUCTURALLY_SUPPORTED"])
    claims_n = " ".join(x["claim"] for x in c_none["STRUCTURALLY_SUPPORTED"])
    assert "weather" in claims_s.lower() or "f_k" in claims_s
    assert "f_k(P_IT, weather" not in claims_n
    assert c_strong["STRUCTURALLY_SUPPORTED"] != c_none["STRUCTURALLY_SUPPORTED"]
    assert any("WUE" in x["claim"] or "water" in x["claim"].lower() for x in c_strong["NOT_IDENTIFIED_BY_M100"])


def test_within_month_split_is_chronological():
    hours = pd.date_range("2021-06-01", periods=30, freq="h", tz="UTC")
    df = pd.DataFrame({
        "hour_utc": hours,
        "P_IT": 1.0, "P_nonIT": 1.0, "P_facility": 2.0, "T_wetbulb": 10.0,
    })
    mask = pd.Series(True, index=df.index)
    tr, te = within_month_split(df, mask)
    assert tr["hour_utc"].max() < te["hour_utc"].min()
    assert len(tr) == 20 and len(te) == 10
