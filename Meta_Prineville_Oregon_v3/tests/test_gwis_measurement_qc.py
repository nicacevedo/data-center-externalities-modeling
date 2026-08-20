"""Focused tests for GWIS measurement-semantic QC (no groundwater-model fit)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from audit_gwis_measurement_qc import (  # noqa: E402
    EXCLUDE_METHODS,
    EXCLUDE_STATUSES,
    LARGE_CHANGE,
    QC_OBS,
    QC_SUMMARY,
    classify_eligibility,
)

LEVELS = ROOT / "data" / "processed" / "groundwater" / "groundwater_level_observations.csv"
QC_SRC = ROOT / "src" / "audit_gwis_measurement_qc.py"


def _bool(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s.astype(bool)
    return s.astype(str).str.lower().isin(["true", "1"])


def test_original_gwis_measurements_preserved():
    lv = pd.read_csv(LEVELS)
    qc = pd.read_csv(QC_OBS)
    assert lv["observation_key"].is_unique
    assert qc["observation_key"].is_unique
    assert set(qc["observation_key"].astype(str)) == set(lv["observation_key"].astype(str))
    merged = lv.merge(qc, on="observation_key", suffixes=("_lv", "_qc"))
    bls_lv = pd.to_numeric(merged["water_level_below_land_surface"], errors="coerce")
    bls_qc = pd.to_numeric(merged["water_level_bls_ft"], errors="coerce")
    both = bls_lv.notna() | bls_qc.notna()
    assert np.allclose(bls_lv[both].to_numpy(float), bls_qc[both].to_numpy(float), equal_nan=True)
    amsl_lv = pd.to_numeric(merged["water_surface_elevation_or_head"], errors="coerce")
    amsl_qc = pd.to_numeric(merged["water_surface_elevation_ft"], errors="coerce")
    both_h = amsl_lv.notna() | amsl_qc.notna()
    assert np.allclose(amsl_lv[both_h].to_numpy(float), amsl_qc[both_h].to_numpy(float), equal_nan=True)
    assert int(bls_lv.notna().sum()) == int(bls_qc.notna().sum())


def test_eligibility_from_source_status_method_not_magnitude():
    qc = pd.read_csv(QC_OBS)
    elig = _bool(qc["eligible_for_state_model"])
    method = qc["measurement_method"].fillna("").astype(str).str.upper()
    status = qc["measurement_status"].fillna("").astype(str).str.upper()
    bls = pd.to_numeric(qc["water_level_bls_ft"], errors="coerce")
    excluded_by_metadata = method.isin(EXCLUDE_METHODS) | status.isin(EXCLUDE_STATUSES) | bls.isna()
    assert (~elig[excluded_by_metadata]).all()
    assert elig[~excluded_by_metadata].all()
    # Extreme numeric values remain eligible when status/method do not exclude them.
    numeric = qc[bls.notna()].copy()
    if len(numeric) >= 2:
        extremes = numeric.loc[[numeric["water_level_bls_ft"].idxmin(), numeric["water_level_bls_ft"].idxmax()]]
        for _, r in extremes.iterrows():
            eligible, _, reason = classify_eligibility(
                r["measurement_method"], r["measurement_status"], r["water_level_bls_ft"]
            )
            assert eligible == bool(_bool(pd.Series([r["eligible_for_state_model"]])).iloc[0])
            assert "magnitude" not in reason
    src = QC_SRC.read_text(encoding="utf-8")
    assert "LARGE_CHANGE_FT" not in src.split("def classify_eligibility")[1].split("def build_observation_qc")[0]


def test_unknown_statuses_remain_explicitly_unknown():
    qc = pd.read_csv(QC_OBS)
    unknown = qc["measurement_status"].fillna("").astype(str).str.upper().eq("UNKNOWN")
    numeric = pd.to_numeric(qc["water_level_bls_ft"], errors="coerce").notna()
    method_ok = ~qc["measurement_method"].fillna("").astype(str).str.upper().isin(EXCLUDE_METHODS)
    retained_unknown = unknown & numeric & method_ok
    assert retained_unknown.any()
    assert qc.loc[retained_unknown, "eligibility_class"].eq("unknown_ambiguous").all()
    assert _bool(qc.loc[retained_unknown, "eligible_for_state_model"]).all()
    assert not qc.loc[retained_unknown, "eligibility_class"].isin(["eligible", "excluded", "good", "bad"]).any()


def test_head_anomaly_is_negative_bls_anomaly():
    qc = pd.read_csv(QC_OBS)
    both = qc["bls_anomaly_ft"].notna() & qc["head_anomaly_ft"].notna()
    assert both.any()
    assert np.allclose(
        qc.loc[both, "head_anomaly_ft"].to_numpy(float),
        -qc.loc[both, "bls_anomaly_ft"].to_numpy(float),
        atol=1e-9,
        equal_nan=True,
    )
    inc = pd.to_numeric(qc["bls_amsl_anomaly_inconsistency_ft"], errors="coerce")
    if inc.notna().any():
        assert float(inc.max()) < 1e-6


def test_large_change_audit_does_not_delete_jumps():
    qc = pd.read_csv(QC_OBS)
    jumps = pd.read_csv(LARGE_CHANGE)
    assert not jumps.empty
    src_keys = set(qc["observation_key"].astype(str))
    lv = pd.read_csv(LEVELS)
    assert set(lv["observation_key"].astype(str)) == src_keys
    millican_big = jumps[jumps.well_node_id.eq("SRC-JA") & jumps.abs_delta_bls_ft.ge(100)]
    assert not millican_big.empty
    same_meta = millican_big[
        ~_bool(millican_big.coincides_with_method_change)
        & ~_bool(millican_big.coincides_with_status_change)
    ]
    assert not same_meta.empty
    heliport_flow = jumps[
        jumps.well_node_id.eq("SRC-GC")
        & (jumps.status.eq("FLOWING") | jumps.status_prev.eq("FLOWING"))
    ]
    assert not heliport_flow.empty


def test_summary_counts_match_observation_qc():
    qc = pd.read_csv(QC_OBS)
    summary = pd.read_csv(QC_SUMMARY)
    overall = summary[summary.record_type.eq("overall")].iloc[0]
    elig = _bool(qc["eligible_for_state_model"])
    assert int(overall.n_observations) == len(qc)
    assert int(overall.n_numeric_bls) == int(pd.to_numeric(qc.water_level_bls_ft, errors="coerce").notna().sum())
    assert int(overall.n_eligible_for_state_model) == int(elig.sum())
    assert int(overall.n_excluded) == int((~elig).sum())
    assert int(overall.n_unknown_ambiguous_retained) == int(qc.eligibility_class.eq("unknown_ambiguous").sum())
    wells = summary[summary.record_type.eq("well")]
    assert not wells.empty
    assert "independent" in str(overall.note).lower() or "paired" in str(overall.note).lower()
