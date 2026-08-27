#!/usr/bin/env python3
"""Focused M100 v2 assessment tests. Synthetic where possible; no raw reprocessing."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from m100_suitability_v2 import (  # noqa: E402
    B3_FORBIDDEN,
    FORMULAS,
    b2_feature_names,
    b3_feature_names,
    build_evidence,
    classify_benchmark,
    design_matrix,
    expanding_folds,
    label_from_fold_improvements,
    repair_month_certification,
    source_disposition,
    transfer_semantics,
)


def _df(n=20, twb=True, state=True):
    rng = np.random.default_rng(0)
    pit = 800 + rng.normal(0, 20, n)
    twb_v = 12 + rng.normal(0, 2, n)
    return pd.DataFrame({
        "P_IT": pit,
        "P_nonIT": 0.4 * pit + 3 * twb_v,
        "P_facility": 800 + 0.4 * pit,
        "T_wetbulb": twb_v,
        "T_drybulb": twb_v + 4,
        "RH": np.full(n, 50.0),
        "cooling_state": rng.uniform(0, 1, n) if state else np.full(n, np.nan),
        "heat_transfer_index": pit * 0.5,
    })


def test_model_definitions_match_pilot():
    df = _df()
    x0, i0, n0 = design_matrix(df, "B0", "twb")
    assert i0 is False and n0 == ("P_IT",) and x0.shape == (len(df), 1)
    x1, i1, n1 = design_matrix(df, "B1", "twb")
    assert i1 is True and n1 == ("P_IT",)
    x2, i2, n2 = design_matrix(df, "B2", "twb")
    assert i2 and n2 == ("P_IT", "T_wetbulb", "P_IT:T_wetbulb")
    assert "temp_sq" not in n2 and "T_drybulb" not in n2
    np.testing.assert_allclose(x2[:, 2], df["P_IT"] * df["T_wetbulb"])
    _, _, n2f = design_matrix(df, "B2", "tdb_rh")
    assert n2f == ("P_IT", "T_drybulb", "RH")
    _, _, n3 = design_matrix(df, "B3", "twb")
    assert n3 == ("P_IT", "T_wetbulb", "P_IT:T_wetbulb", "cooling_state")
    assert FORMULAS["B0"].startswith("P_nonIT = c * P_IT")
    assert "STATE-INFORMED ORACLE" in FORMULAS["B3"]


def test_timestamp_comparability_base_and_state():
    hours = pd.date_range("2021-05-01", periods=10, freq="h", tz="UTC")
    base_idx = hours[:8]
    state_idx = hours[:6]
    assert set(state_idx).issubset(set(base_idx))
    names_b2 = b2_feature_names("twb")
    names_b3 = b3_feature_names("twb")
    assert names_b2 == names_b3[:-1]


def test_no_future_data_in_expanding_folds():
    months = [f"2021-{m:02d}" for m in range(4, 13)]
    folds = expanding_folds(months)
    assert folds[0]["train_months"] == ["2021-04"]
    assert folds[0]["test_month"] == "2021-05"
    for f in folds:
        assert f["test_month"] not in f["train_months"]
        assert all(t < f["test_month"] for t in f["train_months"])
        assert f["test_month"] > max(f["train_months"])


def test_state_oracle_does_not_include_hti():
    names = b3_feature_names("twb")
    assert "cooling_state" in names
    assert set(names).isdisjoint(B3_FORBIDDEN)
    assert "heat_transfer_index" not in names
    df = _df()
    _, _, n3 = design_matrix(df, "B3", "twb")
    assert "heat_transfer_index" not in n3


def test_transfer_semantics_not_overall_consistent():
    s = transfer_semantics(
        ranking_train=["B2", "B1", "B0"],
        ranking_test=["B2", "B1", "B0"],
        mae_ref=10.0,
        mae_out=400.0,
    )
    assert s["structural_ranking_transfer"] == "YES"
    assert s.get("forbidden_overall_label") is None
    blob = json_blob(s)
    assert "CONSISTENT" not in blob
    assert s["mae_heldout"] > 10 * s["mae_reference"]
    s2 = transfer_semantics(["B2", "B1"], ["B0", "B1"], 10, 11)
    assert s2["structural_ranking_transfer"] == "NO"


def json_blob(d):
    return " ".join(str(v) for v in d.values())


def test_stale_qc_recognizes_omitted_month():
    stale_table_months = {"2021-01", "2021-04", "2021-05", "2021-06"}
    assert "2021-07" not in stale_table_months
    qual_row = {
        "month": "2021-07",
        "facility_total_power": True,
        "facility_it_power": True,
        "liquid_flow_temp": True,
        "air_cooling": True,
        "weather": True,
        "run_node_aggregation": True,
        "classes": "full-facility-qualified",
    }
    rec = repair_month_certification("2021-07", qual_row)
    assert rec["month"] == "2021-07"
    assert rec["full_facility_qualified"] is True
    if rec["n_processed_products"] >= 4:
        assert rec["certification_v2"] in {"PASS", "PASS_PARTIAL"}
        assert rec["certification_v2"] != "FAIL"


def test_certified_deletion_not_ordinary_missing():
    st = {"cleanup": "tar_deleted", "archive_status": "missing", "certification": "PASS"}
    assert source_disposition("2021-04", st) == "deleted_after_certification"
    rec = repair_month_certification("2021-04", {
        "facility_total_power": True, "facility_it_power": True, "liquid_flow_temp": True,
        "air_cooling": True, "weather": True, "run_node_aggregation": True,
        "classes": "full-facility-qualified",
    })
    assert rec["source_disposition"] == "deleted_after_certification"
    assert rec["source_disposition"] != "missing_unverified"


def _empty_tables():
    return {
        "cert": pd.DataFrame({"full_facility_qualified": [True] * 9}),
        "folds": pd.DataFrame({"test_month": [f"2021-{m:02d}" for m in range(5, 13)]}),
        "memory": pd.DataFrame({"model": ["B1", "B2"], "acf_1h": [0.9, 0.85]}),
        "thermal": pd.DataFrame({"pearson": [0.4]}),
        "cooling": pd.DataFrame({"frac_nonIT_energy_from_cooling": [0.95]}),
        "water": pd.DataFrame({"empirical_WUE": ["UNSUPPORTED"]}),
        "transfer": pd.DataFrame({"nrmse": [0.5, 0.6, 0.4]}),
        "boundary": pd.DataFrame({
            "frac_facility_lt_IT": [0.0], "frac_PUE_lt_1": [0.0],
            "closure_rel_median_pct": [0.02],
        }),
    }


def test_report_classification_follows_synthetic_evidence():
    t = _empty_tables()
    inc_strong = pd.DataFrame({"increment": ["B1_to_B2"] * 8, "mae_rel_improvement": [0.2] * 8})
    inc_none = pd.DataFrame({"increment": ["B1_to_B2"] * 8, "mae_rel_improvement": [-0.05] * 8})
    ev_strong = build_evidence(t["cert"], t["folds"], inc_strong, t["memory"], t["thermal"],
                               t["cooling"], t["water"], t["transfer"], t["boundary"])
    ev_none = build_evidence(t["cert"], t["folds"], inc_none, t["memory"], t["thermal"],
                             t["cooling"], t["water"], t["transfer"], t["boundary"])
    assert ev_strong["weather_increment"] == "STRONG SUPPORT"
    assert ev_none["weather_increment"] == "NOT SUPPORTED"
    ev_strong_abs = dict(ev_strong)
    ev_strong_abs["absolute_transfer"] = "STRONG SUPPORT"
    ev_strong_abs["state_increment"] = "STRONG SUPPORT"
    c_a, r_a = classify_benchmark(ev_strong_abs)
    ev_mixed = dict(ev_strong)
    ev_mixed["absolute_transfer"] = "MIXED / REGIME-DEPENDENT"
    ev_mixed["state_increment"] = "MIXED / REGIME-DEPENDENT"
    c_b, r_b = classify_benchmark(ev_mixed)
    ev_c = dict(ev_none)
    ev_c["measurement_boundary_confidence"] = "UNSUPPORTED BY AVAILABLE DATA"
    ev_c["n_chronological_folds"] = 0
    c_c, _ = classify_benchmark(ev_c)
    assert c_a != c_c
    assert c_a == "A"
    assert c_b == "B"
    assert c_c == "C"
    assert "generic numerical parameters" not in r_b or "not generic" in r_b or "restrict" in r_b.lower()
    assert "Constant PUE is falsified" not in r_a
    assert label_from_fold_improvements([0.2, 0.2], 2) == "STRONG SUPPORT"
    assert label_from_fold_improvements([-0.1, -0.1], 2) == "NOT SUPPORTED"
    assert label_from_fold_improvements([0.2, -0.1], 2) == "MIXED / REGIME-DEPENDENT"
