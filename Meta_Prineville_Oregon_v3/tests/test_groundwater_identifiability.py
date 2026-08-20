"""Focused tests for the groundwater identifiability audit."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from audit_groundwater_identifiability import (  # noqa: E402
    COMBINED_AIRPORT,
    LAGS_MONTHS,
    UNMAPPED_VITESSE,
    classify_identifiability,
)

BY_WELL = ROOT / "outputs" / "groundwater" / "groundwater_identifiability_by_well.csv"
SUMMARY = ROOT / "outputs" / "groundwater" / "groundwater_identifiability_summary.csv"
PUMP = ROOT / "data" / "processed" / "groundwater" / "groundwater_pumping_monthly.csv"
LEVELS = ROOT / "data" / "processed" / "groundwater" / "groundwater_level_observations.csv"
AUDIT_SRC = ROOT / "src" / "audit_groundwater_identifiability.py"


def test_accepted_vs_candidate_mappings_and_unsplit_airport():
    by = pd.read_csv(BY_WELL)
    pump = pd.read_csv(PUMP)
    assert not pump["node_or_reporting_group_id"].astype(str).isin(["SRC-GA", "SRC-GB"]).any()
    air = by[by.well_node_id.isin(["SRC-GA", "SRC-GB"])]
    assert not air.empty
    assert air["matched_pumping_group_id"].eq(COMBINED_AIRPORT).all()
    assert air["pumping_allocation_rule"].eq("do_not_split_combined_pod").all()
    for rid in UNMAPPED_VITESSE:
        node = f"VITESSE:{rid}"
        row = by[by.well_node_id.eq(node)]
        assert not row.empty
        assert not bool(row.iloc[0]["defensible_pumping_mapping"])
        assert row.iloc[0]["identifiability_class"] == "INSUFFICIENT"
    candidates = by[by.identity_status.eq("candidate_unresolved")]
    if not candidates.empty:
        assert candidates["defensible_pumping_mapping"].isin([False, 0]).all()
        assert candidates["identifiability_class"].ne("ESTIMATION_CANDIDATE").all()
    confirmed = by[by.identity_status.eq("confirmed_official_id")]
    for _, r in confirmed.iterrows():
        if r.identifiability_class == "ESTIMATION_CANDIDATE":
            assert bool(r.defensible_pumping_mapping)


def test_no_mixed_datum_absolute_gradients_or_interpolation():
    by = pd.read_csv(BY_WELL)
    src = AUDIT_SRC.read_text(encoding="utf-8")
    assert "absolute_cross_well_gradient" in by.columns
    assert by["absolute_cross_well_gradient"].eq("not_computed").all()
    assert by["head_interpolation"].eq("none").all()
    assert "interpolate(" not in src.lower()
    assert "ngvd_to_navd" not in src.lower()


def test_lag_set_fixed_and_small():
    by = pd.read_csv(BY_WELL)
    summary = pd.read_csv(SUMMARY)
    assert LAGS_MONTHS == (0, 1, 3, 6)
    assert by["lags_months_evaluated"].eq("0,1,3,6").all()
    assert str(summary.iloc[0]["lags_months_evaluated"]) == "0,1,3,6"
    assert not bool(summary.iloc[0]["model_fitted"])


def test_classifications_reproducible_from_explicit_criteria():
    by = pd.read_csv(BY_WELL)
    for r in by.to_dict(orient="records"):
        assert classify_identifiability(r) == r["identifiability_class"]
    summary = pd.read_csv(SUMMARY)
    overall = summary.iloc[0]["overall_identifiability_conclusion"]
    assert overall in {"A-small-subsystem-possible", "B-validation-only", "C-not-identifiable"}
    n_est = int(by.identifiability_class.eq("ESTIMATION_CANDIDATE").sum())
    if n_est:
        assert overall == "A-small-subsystem-possible"
    elif int(by.identifiability_class.eq("VALIDATION_ONLY").sum()):
        assert overall == "B-validation-only"
    else:
        assert overall == "C-not-identifiable"


def test_original_head_observations_not_replaced():
    lv = pd.read_csv(LEVELS)
    by = pd.read_csv(BY_WELL)
    qc = pd.read_csv(ROOT / "outputs" / "groundwater" / "gwis_measurement_model_qc.csv")
    numeric = pd.to_numeric(lv["water_level_below_land_surface"], errors="coerce")
    n_by_node = numeric.notna().groupby(lv["well_node_id"]).sum()
    elig = qc["eligible_for_state_model"]
    if elig.dtype != bool:
        elig = elig.astype(str).str.lower().isin(["true", "1"])
    n_elig = qc.loc[elig].groupby("well_node_id").size()
    for node, n in n_by_node.items():
        hit = by[by.well_node_id.eq(node)]
        if hit.empty:
            continue
        assert int(hit.iloc[0]["n_numeric_bls_observations"]) == int(n)
        expected_elig = int(n_elig.get(node, 0))
        assert int(hit.iloc[0]["n_numeric_head_observations"]) == expected_elig
    assert set(qc["observation_key"].astype(str)) == set(lv["observation_key"].astype(str))


def test_head_anomaly_sign_and_eligible_subset_in_identifiability():
    by = pd.read_csv(BY_WELL)
    summary = pd.read_csv(SUMMARY)
    both = by[["head_anomaly_std_ft", "bls_anomaly_std_ft"]].dropna()
    assert not both.empty
    assert np.allclose(
        both["head_anomaly_std_ft"].to_numpy(float),
        both["bls_anomaly_std_ft"].to_numpy(float),
        atol=1e-8,
        equal_nan=True,
    )
    assert "head_anomaly_ft=-(" in str(summary.iloc[0]["head_target_definition"])
    assert "sufficient data to attempt a validated empirical response model" in str(
        summary.iloc[0]["estimation_candidate_means"]
    )
    assert bool(summary.iloc[0]["lags_are_exploratory_diagnostics_not_model_specification"])
    src = AUDIT_SRC.read_text(encoding="utf-8")
    assert "head_anomaly = -bls_anomaly" in src
    assert "delta_head = -delta_bls" in src


def test_no_unresolved_vitesse_or_split_airport_or_interpolation():
    by = pd.read_csv(BY_WELL)
    src = AUDIT_SRC.read_text(encoding="utf-8")
    assert "interpolate(" not in src.lower()
    assert by["head_interpolation"].eq("none").all()
    assert by["absolute_cross_well_gradient"].eq("not_computed").all()
    assert not by.matched_pumping_group_id.astype(str).isin(["SRC-GA", "SRC-GB"]).any()
    for rid in UNMAPPED_VITESSE:
        row = by[by.well_node_id.eq(f"VITESSE:{rid}")].iloc[0]
        assert not bool(row.defensible_pumping_mapping)
        assert row.identifiability_class == "INSUFFICIENT"
