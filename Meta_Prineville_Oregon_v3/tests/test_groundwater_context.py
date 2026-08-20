"""Focused tests for the groundwater observation scaffold and GWIS ingest."""
from __future__ import annotations

import hashlib
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
from prepare_gwis import (  # noqa: E402
    UNMAPPED_VITESSE_REPORTS,
    compile_gwis_bundle,
    gwis_txt_files,
    hash_inventory,
)

CITY_MODEL = ROOT / "data" / "processed" / "owrd" / "owrd_city_monthly_model_use.csv"
DIRECT_MONTHLY = ROOT / "data" / "processed" / "owrd" / "owrd_meta_direct_monthly_use.csv"
FEAS = ROOT / "outputs" / "groundwater" / "groundwater_model_feasibility.csv"
PDF_SCAN = ROOT / "outputs" / "groundwater" / "local_pdf_hydrogeology_scan.csv"
PERMITS = ROOT / "data" / "raw" / "permits_pdfs"


def test_well_ids_unique():
    inv = pd.read_csv(INV_OUT)
    assert inv["well_node_id"].is_unique
    assert inv["well_node_id"].notna().all()


def test_unresolved_coordinates_remain_unresolved():
    inv = pd.read_csv(INV_OUT)
    unresolved = inv[inv.mapping_method.eq("unresolved_missing_coordinates")]
    assert unresolved["latitude"].isna().all()
    assert unresolved["longitude"].isna().all()
    for rid in UNMAPPED_VITESSE_REPORTS:
        node = inv[inv.well_node_id.eq(f"VITESSE:{rid}")]
        assert not node.empty
        assert node["latitude"].isna().all()
        assert node["gwis_site_id"].fillna("").astype(str).str.len().eq(0).all()


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
    assert not pump.loc[combined, "node_or_reporting_group_id"].astype(str).str.fullmatch(r"SRC-G[AB]").any()


def test_boundaries_kept_distinct():
    pump = pd.read_csv(PUMP_OUT)
    assert set(pump.boundary_id) <= {BOUNDARY_CITY, BOUNDARY_DIRECT, BOUNDARY_META}
    assert pump.loc[pump.boundary_id.eq(BOUNDARY_META), "measurement_or_reporting_method"].eq(
        "annual_reported_not_monthly"
    ).all()


def test_gwis_duplicate_exports_do_not_duplicate_observations():
    files = gwis_txt_files()
    assert files
    inv = hash_inventory(files)
    n_files = len(inv)
    n_unique = inv["sha256"].nunique()
    assert n_files >= n_unique
    bundle = compile_gwis_bundle()
    levels = bundle["levels"]
    assert levels["gw_measured_water_level_id"].is_unique
    raw_level_files = [p for p in files if p.name.startswith("gw_measured_water_level")]
    hashes = {hashlib.sha256(p.read_bytes()).hexdigest() for p in raw_level_files}
    assert len(raw_level_files) >= len(hashes)


def test_processed_gwis_observations_exist_and_retain_provenance():
    lv = pd.read_csv(LEVEL_OUT)
    assert not lv.empty
    assert lv["observation_key"].is_unique
    numeric = pd.to_numeric(lv["water_level_below_land_surface"], errors="coerce")
    assert numeric.notna().sum() > 0
    assert "source_raw_files" in lv.columns
    assert lv["provenance_class"].eq("reported_measured_gwis").all()
    has_head = pd.to_numeric(lv["water_surface_elevation_or_head"], errors="coerce").notna()
    if has_head.any():
        assert lv.loc[has_head, "reference_datum"].astype(str).str.strip().ne("").all()


def test_known_wells_match_official_ids_only():
    inv = pd.read_csv(INV_OUT)

    def row(node):
        hit = inv[inv.well_node_id.eq(node)]
        assert len(hit) == 1, node
        return hit.iloc[0]

    millican = row("SRC-JA")
    heliport = row("SRC-GC")
    air1 = row("SRC-GA")
    air2 = row("SRC-GB")
    v64846 = row("VITESSE:64846")
    assert millican.identity_status == "confirmed_official_id"
    assert str(int(float(millican.gwis_well_tag))) == "108444"
    assert heliport.identity_status == "confirmed_official_id"
    assert str(int(float(heliport.gwis_well_tag))) == "114180"
    assert air1.identity_status == "confirmed_official_id"
    assert str(int(float(air1.gwis_well_tag))) == "105198"
    assert air2.identity_status == "confirmed_official_id"
    assert str(int(float(air2.gwis_well_tag))) == "89932"
    assert v64846.identity_status == "confirmed_official_id"
    assert str(int(float(v64846.gwis_well_tag))) == "105254"
    assert pd.notna(v64846.latitude)


def test_vitesse_named_gwis_well_not_auto_mapped_to_unmatched_pods():
    inv = pd.read_csv(INV_OUT)
    for rid in UNMAPPED_VITESSE_REPORTS:
        sub = inv[inv.well_node_id.eq(f"VITESSE:{rid}")]
        assert not sub.empty
        assert sub["identity_status"].ne("confirmed_official_id").all()
        assert sub["gwis_site_id"].fillna("").astype(str).str.len().eq(0).all()
    candidates = inv[inv.identity_status.eq("candidate_unresolved")]
    assert not candidates.empty
    assert candidates["well_node_id"].astype(str).str.startswith("GWIS:").all()


def test_parameters_not_silently_filled_and_stale_pdf_claim_removed():
    p = pd.read_csv(PARAM_OUT)
    assert p["parameter"].notna().all()
    unresolved = p[p.provenance_class.eq("unresolved")]
    assert unresolved["value"].isna().all()
    measured_test = p[p.provenance_class.eq("measured_pumping_test")]
    assert measured_test.empty or measured_test["value"].notna().all()
    blob = p.astype(str).to_string().lower()
    assert "pdf not local" not in blob
    assert PDF_SCAN.exists()
    scan = pd.read_csv(PDF_SCAN)
    assert PERMITS.exists()
    assert any(PERMITS.rglob("*.pdf"))
    catalog = scan[scan.source_file.astype(str).str.startswith("catalogued:")]
    assert catalog["status"].eq("catalogued_filename_not_found_under_data_raw").all()
    numeric_unresolved = p[p.parameter.isin(["transmissivity", "storativity", "specific_yield"])]
    assert numeric_unresolved["value"].isna().all()
    gwis_params = p[p.provenance_class.eq("reported_measured_gwis")]
    assert not gwis_params.empty
    assert gwis_params["source_file"].astype(str).str.len().gt(0).all()
    assert gwis_params["source_page_table_section"].astype(str).str.len().gt(0).all()


def test_feasibility_recomputed_not_hardcoded_empty_heads():
    feas = pd.read_csv(FEAS)
    assert feas.iloc[0]["feasibility_class"] in {"A", "B", "C"}
    assert int(feas.iloc[0]["n_numeric_level_observations"]) > 0
    assert feas.iloc[0]["feasibility_class"] != "C"
