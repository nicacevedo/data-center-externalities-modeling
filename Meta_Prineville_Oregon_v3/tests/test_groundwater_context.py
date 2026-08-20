"""Focused tests for the groundwater observation scaffold."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from build_groundwater_context import (  # noqa: E402
    BOUNDARY_CITY,
    BOUNDARY_DIRECT,
    BOUNDARY_META,
    INV_OUT,
    LEVEL_OUT,
    PARAM_OUT,
    PUMP_OUT,
    XWALK_OUT,
)

CITY_MODEL = ROOT / "data" / "processed" / "owrd" / "owrd_city_monthly_model_use.csv"
DIRECT_MONTHLY = ROOT / "data" / "processed" / "owrd" / "owrd_meta_direct_monthly_use.csv"
HUC = ROOT / "data" / "canonical" / "municipal_source_huc12_crosswalk.csv"


def test_well_ids_unique():
    inv = pd.read_csv(INV_OUT)
    assert inv["well_node_id"].is_unique
    assert inv["well_node_id"].notna().all()


def test_unresolved_coordinates_remain_unresolved():
    inv = pd.read_csv(INV_OUT)
    huc = pd.read_csv(HUC)
    official = set(huc.loc[huc.latitude.notna() & huc.longitude.notna(), "source_id"].astype(str))
    city = inv[inv.oha_source_id.astype(str).str.startswith("SRC-", na=False)]
    extra = city[city.latitude.notna() & ~city.oha_source_id.astype(str).isin(official)]
    assert extra.empty, extra[["well_node_id", "latitude", "longitude"]]
    unresolved = inv[inv.mapping_method.eq("unresolved_missing_coordinates")]
    assert unresolved["latitude"].isna().all()
    assert unresolved["longitude"].isna().all()
    vitesse = inv[inv.role.eq("Vitesse_Facebook_direct")]
    assert vitesse["latitude"].isna().all()


def test_huc12_is_not_aquifer_or_network_node():
    inv = pd.read_csv(INV_OUT)
    xw = pd.read_csv(XWALK_OUT)
    assert inv["huc12_is_not_aquifer_node"].astype(str).str.lower().isin(["true", "1"]).all()
    assert xw["huc12_is_not_aquifer_node"].astype(str).str.lower().isin(["true", "1"]).all()
    assert not inv["well_node_id"].astype(str).str.fullmatch(r"\d{12}").any()


def test_pumping_totals_unchanged_and_no_join_explosion():
    pump = pd.read_csv(PUMP_OUT)
    city = pd.read_csv(CITY_MODEL)
    direct = pd.read_csv(DIRECT_MONTHLY)
    city_sum = float(pd.to_numeric(city["volume_m3"], errors="coerce").fillna(0).sum())
    pump_city = float(pump.loc[pump.boundary_id.eq(BOUNDARY_CITY), "pump_m3"].fillna(0).sum())
    assert abs(city_sum - pump_city) < 1e-6
    direct_sum = float(pd.to_numeric(direct["volume_m3"], errors="coerce").fillna(0).sum())
    pump_direct = float(pump.loc[pump.boundary_id.eq(BOUNDARY_DIRECT), "pump_m3"].fillna(0).sum())
    assert abs(direct_sum - pump_direct) < 1e-6
    assert len(pump.loc[pump.boundary_id.eq(BOUNDARY_CITY)]) == len(city)
    assert len(pump.loc[pump.boundary_id.eq(BOUNDARY_DIRECT)]) == len(direct)
    combined = pump["node_or_reporting_group_id"].astype(str).str.startswith("COMBINED_ACCEPTED:")
    assert combined.any()
    city_keys = set(city.model_source_key.astype(str))
    pump_keys = set(pump.loc[pump.boundary_id.eq(BOUNDARY_CITY), "node_or_reporting_group_id"].astype(str))
    assert pump_keys == city_keys


def test_boundaries_kept_distinct():
    pump = pd.read_csv(PUMP_OUT)
    assert set(pump.boundary_id) <= {BOUNDARY_CITY, BOUNDARY_DIRECT, BOUNDARY_META}
    assert pump.loc[pump.boundary_id.eq(BOUNDARY_META), "measurement_or_reporting_method"].eq(
        "annual_reported_not_monthly"
    ).all()


def test_level_rows_unique_and_no_absolute_head_without_datum():
    lv = pd.read_csv(LEVEL_OUT)
    if lv.empty:
        return
    if "measurement_date" in lv.columns:
        dated = lv[lv["measurement_date"].astype(str).str.len() > 0]
        if not dated.empty:
            assert not dated.duplicated(["well_id", "measurement_date"]).any()
    assert lv["water_surface_elevation_or_head"].isna().all()
    numeric = lv["water_level_below_land_surface"].notna()
    if numeric.any():
        assert lv.loc[numeric, "observation_type"].ne("unresolved_document_hydrograph").all()


def test_parameters_not_merged_into_one_value():
    p = pd.read_csv(PARAM_OUT)
    assert p["parameter"].notna().all()
    measured = p[p.provenance_class.eq("measured_pumping_test")]
    assert measured.empty or measured["value"].notna().all()
    assert "reported_engineering_estimate" in set(p.provenance_class)
