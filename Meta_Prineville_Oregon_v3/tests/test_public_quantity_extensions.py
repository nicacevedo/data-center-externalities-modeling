"""Focused tests for early-water, 2011 Scope-2 proxy, EWIF, and monthly reconstructions."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
META = ROOT / "data" / "canonical" / "meta_prineville_annual.csv"
ENVELOPE = ROOT / "data" / "processed" / "water" / "meta_water_early_proxy_envelope.csv"
SCOPE2 = ROOT / "data" / "processed" / "egrid_2011_location_based_scope2_proxy.csv"
EGRID_COMPARE = ROOT / "outputs" / "egrid_meta_annual_compare.csv"
EWIF = ROOT / "data" / "processed" / "water" / "regional_electricity_water_intensity.csv"
ELEC_M = ROOT / "data" / "processed" / "electricity" / "meta_campus_monthly_electricity_reconstruction.csv"
WATER_M = ROOT / "data" / "processed" / "water" / "meta_campus_monthly_water_scenarios.csv"
SRC_EXT = ROOT / "src" / "build_public_quantity_extensions.py"
SRC_EGRID = ROOT / "src" / "prepare_egrid.py"

PUE_DESIGN = 1.07
WUE_DESIGN = 0.31
LB_PER_T = 2204.6226218487757


def test_early_water_does_not_overwrite_reported_meta():
    meta = pd.read_csv(META)
    env = pd.read_csv(ENVELOPE)
    assert set(env.year.astype(int)) == {2011, 2012, 2013}
    assert env["reported_meta_water_m3"].isna().all()
    later = meta[meta.year.ge(2014)]
    assert later["water_withdrawal_m3_reported"].notna().all()
    text = env["provenance"].str.lower().str.cat(sep=" ")
    assert "2011-2013" in text or "2011–2013" in text
    assert env["direct_pod_is_not_total_meta_water"].astype(str).str.lower().isin(["true", "1"]).all()
    assert "not total" in text or env["direct_pod_is_not_total_meta_water"].all()
    src = SRC_EXT.read_text(encoding="utf-8")
    assert "PUE_DESIGN = 1.07" in src
    assert "WUE_DESIGN_L_PER_KWH_IT = 0.31" in src
    e = pd.read_csv(META)
    for _, r in env.iterrows():
        e_fac = float(e.loc[e.year.eq(int(r.year)), "electricity_mwh_reported"].iloc[0])
        expected = WUE_DESIGN * (e_fac / PUE_DESIGN)
        assert abs(float(r.design_wue_proxy_m3) - expected) < 1e-6


def test_2011_scope2_is_proxy_and_matches_canonical_electricity():
    meta = pd.read_csv(META)
    proxy = pd.read_csv(SCOPE2)
    compare = pd.read_csv(EGRID_COMPARE)
    mwh = float(meta.loc[meta.year.eq(2011), "electricity_mwh_reported"].iloc[0])
    assert float(proxy.iloc[0]["meta_electricity_mwh"]) == mwh
    assert proxy.iloc[0]["provenance"] == "eGRID_location_based_accounting_proxy"
    assert not bool(proxy.iloc[0]["is_meta_reported_scope2"])
    r2011 = compare.loc[compare.year.eq(2011)].iloc[0]
    assert pd.isna(r2011["meta_location_based_scope2_tonnes"])
    assert "eGRID_location_based_accounting_proxy" in str(r2011["comparison_note"])
    assert "not Meta-reported Scope 2" in str(r2011["comparison_note"])
    factor = float(r2011["egrid_co2e_lb_per_mwh"])
    expected = mwh * factor / LB_PER_T
    assert abs(float(proxy.iloc[0]["co2e_lb_proxy_tco2e"]) - expected) < 1e-6
    canonical = meta.loc[meta.year.eq(2011), "location_based_scope2_tco2e_reported"]
    assert canonical.isna().all()


def test_ewif_coverage_and_no_zero_fill_or_meta_attribution():
    ew = pd.read_csv(EWIF)
    src = SRC_EXT.read_text(encoding="utf-8")
    assert "generation_coverage_fraction" in ew.columns
    assert ew["is_meta_generator_attribution"].astype(str).str.lower().isin(["false", "0"]).all()
    assert ew["missing_cooling_water_treated_as_zero"].astype(str).str.lower().isin(["false", "0"]).all()
    assert "Missing cooling water is not assumed zero" in src or "not treated as zero" in src.lower()
    assert ew["scientifically_meaningful_grid_ewif"].astype(str).str.lower().isin(["false", "0"]).all()
    for y in (2011, 2012):
        row = ew.loc[ew.year.eq(y)].iloc[0]
        assert pd.isna(row["EWIF_withdrawal"])
    if ew["EWIF_withdrawal"].notna().any():
        assert (ew.loc[ew.EWIF_withdrawal.notna(), "covered_generation_mwh"] > 0).all()


def test_monthly_electricity_closes_and_is_reconstruction():
    if not ELEC_M.exists():
        return
    meta = pd.read_csv(META)
    m = pd.read_csv(ELEC_M)
    assert m["series_label"].eq("reconstructed / annual-closed").all()
    assert m["is_meter_observation"].astype(str).str.lower().isin(["false", "0"]).all()
    chk = m.groupby("calendar_year", as_index=False).agg(
        flat=("electricity_mwh_flat", "sum"),
        cond=("electricity_mwh_conditional", "sum"),
    )
    merged = chk.merge(meta, left_on="calendar_year", right_on="year")
    assert (merged["flat"] - merged["electricity_mwh_reported"]).abs().max() < 1e-6
    assert (merged["cond"] - merged["electricity_mwh_reported"]).abs().max() < 1e-6
    assert m["electricity_mwh_stochastic"].isna().all()


def test_monthly_water_scenarios_close_and_are_not_observations():
    if not WATER_M.exists():
        return
    meta = pd.read_csv(META)
    w = pd.read_csv(WATER_M)
    assert w["series_label"].eq("scenario allocation").all()
    assert w["is_observation"].astype(str).str.lower().isin(["false", "0"]).all()
    assert w["is_prediction"].astype(str).str.lower().isin(["false", "0"]).all()
    for year, gy in w.groupby("calendar_year"):
        target = float(meta.loc[meta.year.eq(int(year)), "water_withdrawal_m3_reported"].iloc[0])
        assert abs(float(gy["water_m3_flat"].sum()) - target) < 1e-3
        assert abs(float(gy["water_m3_graybox_evaporation"].sum()) - target) < 1e-3
        if gy["water_m3_direct_pod_shape"].notna().all():
            assert abs(float(gy["water_m3_direct_pod_shape"].sum()) - target) < 1e-3
            assert gy["direct_pod_shape_status"].str.contains("scenario allocation").all()
        else:
            assert gy["water_m3_direct_pod_shape"].isna().all()
            assert gy["direct_pod_shape_status"].eq("skipped_incomplete_direct_pod_shape").all()
    assert set(w.calendar_year.astype(int)).isdisjoint({2011, 2012, 2013})


def test_missing_direct_pod_month_is_not_treated_as_zero():
    from build_public_quantity_extensions import allocate_direct_pod_year

    missing = pd.Series([10.0] * 11 + [float("nan")])
    out, status = allocate_direct_pod_year(missing, 120.0)
    assert out.isna().all()
    assert status == "skipped_incomplete_direct_pod_shape"
    assert not (out.fillna(999) == 0).any()

    zeros = pd.Series([0.0] * 11 + [12.0])
    out, status = allocate_direct_pod_year(zeros, 120.0)
    assert status.startswith("scenario allocation")
    assert abs(float(out.iloc[-1]) - 120.0) < 1e-9
    assert (out.iloc[:11] == 0).all()

    incomplete_year = pd.read_csv(WATER_M) if WATER_M.exists() else pd.DataFrame()
    if not incomplete_year.empty:
        skipped = incomplete_year[
            incomplete_year["direct_pod_shape_status"].eq("skipped_incomplete_direct_pod_shape")
        ]
        if not skipped.empty:
            assert skipped["water_m3_direct_pod_shape"].isna().all()
            src = SRC_EXT.read_text(encoding="utf-8")
            assert "fillna(0.0)" not in src.split("def build_monthly_water")[1].split("def _usgs_end_dates")[0]
            assert "skipped_incomplete_direct_pod_shape" in src
