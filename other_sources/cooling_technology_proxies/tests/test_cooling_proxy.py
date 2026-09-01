"""Freeze-pass tests for the cooling source-scenario proxy."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path("/home/nacevedo/RA/data-center-externalities-modeling/other_sources/cooling_technology_proxies")
PARENT = ROOT.parents[1]
UES = ROOT / "sources/lei2025/UEs_16cases.csv"
UES_SHA256 = "4924fdb451dfefc433b4de375322dadbbf5fb056876c12e5cc1a913d5cf4c031"
HOLDOUT_DENYLIST = ["water_holdout_baseline_compare.csv", "conditional_annual_compare.csv"]
sys.path.insert(0, str(ROOT / "scripts"))
from cooling_proxy_api import CoolingProxyUnsupportedError, get_cooling_scenarios  # noqa: E402

LIQUID_MAP = {
    "15_1": "REAR_DOOR_HEAT_EXCHANGER",
    "16_1": "REAR_DOOR_HEAT_EXCHANGER",
    "15_2": "DIRECT_TO_CHIP_COLD_PLATE",
    "16_2": "DIRECT_TO_CHIP_COLD_PLATE",
    "15_3": "IMMERSION",
    "16_3": "IMMERSION",
}
PAPER_CORE = {
    "Air-cooled chiller",
    "Airside economizer (air-cooled chiller)",
    "Airside economizer (water-cooled chiller)",
    "Airside economizer& adiabatic cooling (air-cooled chiller)",
    "Airside economizer& adiabatic cooling (water-cooled chiller)",
    "Direct expansion system",
    "Water-cooled chiller",
    "Waterside economizer (water-cooled chiller)",
    "IT Liquid cooling: waterside economizer (water-cooled chiller)",
    "IT Liquid cooling: dry cooler with adiabatic assist (air-cooled chiller)",
}


def sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def test_ues_immutable():
    assert sha256_file(UES) == UES_SHA256
    df = pd.read_csv(UES)
    assert len(df) == 19000
    assert df["PUE"].notna().all() and df["WUE"].notna().all()
    assert (df["PUE"] >= 1).all() and (df["WUE"] >= 0).all()


def test_user_copy_matches_git():
    assert sha256_file(UES) == sha256_file(ROOT / "sources/lei2025/upstream/data/UEs_16cases.csv")


def test_paired_parquet():
    raw = pd.read_csv(UES)
    sc = pd.read_parquet(ROOT / "data_processed/cooling_proxy_scenarios.parquet")
    assert len(sc) == 19000
    assert sc["paired"].all()
    assert (sc["PUE"].to_numpy() == raw["PUE"].to_numpy()).all()
    assert (sc["WUE"].to_numpy() == raw["WUE"].to_numpy()).all()
    assert (sc["WUE_site_model"].to_numpy() == raw["WUE"].to_numpy()).all()
    assert (sc["scenario_semantics"] == "SOURCE_MODEL_SCENARIO").all()
    assert (sc["quantile_semantics"] == "SOURCE_SCENARIO_QUANTILE").all()


def test_liquid_subtype_crosswalk():
    sc = pd.read_parquet(ROOT / "data_processed/cooling_proxy_scenarios.parquet")
    liq = sc[sc["Case"].isin([15, 16])]
    assert set(liq["Case (Original)"].astype(str)) == set(LIQUID_MAP)
    for orig, mapped in LIQUID_MAP.items():
        assert set(liq.loc[liq["Case (Original)"].astype(str) == orig, "liquid_cooling_type"]) == {mapped}
    assert set(sc.loc[sc["Case"] == 15, "tech_id"].unique()) == {"LIQ_WE_WCC"}
    assert set(sc.loc[sc["Case"] == 16, "tech_id"].unique()) == {"LIQ_DRY_AD"}
    assert (sc.loc[~sc["Case"].isin([15, 16]), "liquid_cooling_type"] == "NOT_APPLICABLE").all()


def test_paper_core_ten():
    sc = pd.read_parquet(ROOT / "data_processed/cooling_proxy_scenarios.parquet")
    core = set(sc.loc[sc["source_scope_status"] == "PAPER_CORE", "Cooling system"])
    extra = set(sc.loc[sc["source_scope_status"] == "SOURCE_EXTRA_EXTENDED", "Cooling system"])
    assert core == PAPER_CORE
    assert extra == {"Dry cooler (air-cooled chiller)", "Dry cooler with adiabatic assist (air-cooled chiller)"}
    assert len(core) == 10


def test_summary_and_domain():
    s = pd.read_csv(ROOT / "data_processed/cooling_proxy_summary.csv")
    d = pd.read_csv(ROOT / "data_processed/SUPPORTED_DOMAIN_MATRIX.csv")
    assert (s["n"] == 50).all()
    assert (d["n"] == 50).all()
    assert "SOURCE_SCENARIO_QUANTILE" in set(s["quantile_semantics"].astype(str))
    assert "liquid_cooling_type" in s.columns and "liquid_cooling_type" in d.columns


def test_api_fail_closed():
    sc = pd.read_parquet(ROOT / "data_processed/cooling_proxy_scenarios.parquet")
    ok = get_cooling_scenarios("AE_AD_ACC", "5B", "Large-scale", df=sc)
    assert ok.n == 50
    assert ok.paired_pue_wue
    with pytest.raises(CoolingProxyUnsupportedError):
        get_cooling_scenarios("AE_AD_ACC", "5B", "Small", df=sc)
    with pytest.raises(CoolingProxyUnsupportedError):
        get_cooling_scenarios("LIQ_DRY_AD", "5B", "Large-scale", df=sc)
    liq = get_cooling_scenarios(
        "LIQ_DRY_AD", "5B", "Large-scale", liquid_subtype="IMMERSION", df=sc
    )
    assert liq.n == 50
    with pytest.raises(CoolingProxyUnsupportedError):
        get_cooling_scenarios("DRY_ACC", "5B", "Midsize", df=sc)
    extra = get_cooling_scenarios(
        "DRY_ACC", "5B", "Midsize", include_source_extra=True, df=sc
    )
    assert extra.source_scope_status == "SOURCE_EXTRA_EXTENDED"
    with pytest.raises(CoolingProxyUnsupportedError):
        ok.sample_pairs(n=3)
    w = get_cooling_scenarios(
        "AE_AD_ACC", "5B", "Large-scale", scenario_weighting="DESIGN_PRIOR_UNIFORM", df=sc
    )
    samp = w.sample_pairs(n=10, rng=0)
    assert {"PUE", "WUE_site_model"} <= set(samp.columns)


def test_no_masanet_mutation():
    r = subprocess.run(
        ["git", "status", "--short", "other_sources/masanet"],
        cwd=str(PARENT),
        capture_output=True,
        text=True,
        check=True,
    )
    assert r.stdout.strip() == ""


def test_scripts_no_holdout():
    hits = []
    for p in (ROOT / "scripts").glob("*.py"):
        text = p.read_text(errors="replace")
        for name in HOLDOUT_DENYLIST:
            if name in text:
                hits.append(f"{p.name}:{name}")
    assert hits == []


def test_metadata_not_empirical_distribution():
    spec = (ROOT / "docs/PROXY_MODEL_SPEC.md").read_text()
    assert "DESIGN_PRIOR_UNIFORM" in spec
    assert "not an empirically estimated" in spec.lower()
    qc = json.loads((ROOT / "analysis/COOLING_PROXY_QC.json").read_text())
    assert qc["scenario_semantics"] == "SOURCE_MODEL_SCENARIO"
    assert qc["did_read_meta_2023_2024_water"] is False


def test_water_boundary_labels():
    sc = pd.read_parquet(ROOT / "data_processed/cooling_proxy_scenarios.parquet")
    assert "WUE_site_model" in sc.columns
    wb = (ROOT / "docs/WATER_BOUNDARY.md").read_text()
    assert "groundwater" in wb.lower()
    assert "draw-off" in wb.lower() or "blowdown" in wb.lower()


def test_engineering_priors_kind():
    p = pd.read_csv(ROOT / "data_processed/ENGINEERING_PRIORS.csv")
    assert p["source_id"].notna().all()
    assert (p["kind"] == "ENGINEERING_PRIOR").all()


def test_taxonomy_covers_labels():
    tax = pd.read_csv(ROOT / "data_processed/COOLING_TAXONOMY.csv")
    sc = pd.read_parquet(ROOT / "data_processed/cooling_proxy_scenarios.parquet")
    assert set(sc["Cooling system"]) <= set(tax["source_label"])
