"""Focused QA for the cooling-technology proxy module.

Does not rerun Masanet. Does not open Meta 2023–2024 water holdout files.
"""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from pathlib import Path

import pandas as pd

ROOT = Path("/home/nacevedo/RA/data-center-externalities-modeling/other_sources/cooling_technology_proxies")
PARENT = Path("/home/nacevedo/RA/data-center-externalities-modeling")
UES = ROOT / "sources" / "lei2025" / "UEs_16cases.csv"
UES_SHA256 = "4924fdb451dfefc433b4de375322dadbbf5fb056876c12e5cc1a913d5cf4c031"
HOLDOUT_DENYLIST = [
    "water_holdout_baseline_compare.csv",
    "conditional_annual_compare.csv",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def test_ues_hash_and_rowcount():
    assert UES.exists()
    assert sha256_file(UES) == UES_SHA256
    df = pd.read_csv(UES)
    assert len(df) == 19000
    assert list(df.columns) == [
        "PUE",
        "WUE",
        "Case",
        "Climate Zone",
        "Cooling system (Original)",
        "Cooling system",
        "Data center size",
        "type",
        "Case (Original)",
    ]


def test_pue_wue_bounds_and_finite():
    df = pd.read_csv(UES)
    assert (df["PUE"] >= 1).all()
    assert (df["WUE"] >= 0).all()
    assert df["PUE"].notna().all() and df["WUE"].notna().all()


def test_user_copy_matches_git_ues():
    git_copy = ROOT / "sources" / "lei2025" / "upstream" / "data" / "UEs_16cases.csv"
    assert sha256_file(UES) == sha256_file(git_copy)


def test_paired_parquet_preserves_pairs():
    parq = ROOT / "data_processed" / "cooling_proxy_scenarios.parquet"
    raw = pd.read_csv(UES)
    sc = pd.read_parquet(parq)
    assert len(sc) == 19000
    assert sc["paired"].all()
    assert (sc["PUE"].to_numpy() == raw["PUE"].to_numpy()).all()
    assert (sc["WUE"].to_numpy() == raw["WUE"].to_numpy()).all()


def test_summary_cells_n50():
    s = pd.read_csv(ROOT / "data_processed" / "cooling_proxy_summary.csv")
    assert len(s) == 380
    assert (s["n"] == 50).all()
    assert s["paired"].astype(str).str.lower().isin(["true", "1"]).all()


def test_quantile_reproduction_schema():
    q = pd.read_csv(ROOT / "analysis" / "lei2025_reproduction.csv")
    for c in ["PUE_5th", "PUE_95th", "WUE_5th", "WUE_95th", "n"]:
        assert c in q.columns
    assert (q["PUE_5th"] <= q["PUE_95th"]).all()
    assert (q["WUE_5th"] <= q["WUE_95th"]).all()
    audit = json.loads((ROOT / "results" / "LEI2025_DATA_AUDIT.json").read_text())
    assert audit["reproduction_status"] == "PASS"
    assert audit["quantile_definition"].startswith("SI Supporting Code.Rmd")


def test_taxonomy_and_crosswalk_complete():
    tax = pd.read_csv(ROOT / "data_processed" / "COOLING_TAXONOMY.csv")
    df = pd.read_csv(UES)
    labels = set(df["Cooling system"].unique())
    mapped = set(tax["source_label"].unique())
    assert labels <= mapped
    xw = pd.read_csv(ROOT / "data_processed" / "MASANET_LEI2025_LBNL_CROSSWALK.csv")
    assert len(xw) >= 8
    for c in ["mapping", "confidence", "rationale", "uncertainty"]:
        assert c in xw.columns


def test_paired_sampling_required():
    qc = json.loads((ROOT / "analysis" / "COOLING_PROXY_QC.json").read_text())
    assert qc["independence_diagnostic"]["PAIRED_SAMPLING_REQUIRED"] is True
    assert qc["did_read_meta_2023_2024_water"] is False


def test_no_masanet_mutation():
    r = subprocess.run(
        ["git", "status", "--short", "other_sources/masanet"],
        cwd=str(PARENT),
        capture_output=True,
        text=True,
        check=True,
    )
    assert r.stdout.strip() == ""


def test_scripts_do_not_reference_holdout_files():
    hits = []
    for p in (ROOT / "scripts").glob("*.py"):
        text = p.read_text(errors="replace")
        for name in HOLDOUT_DENYLIST:
            if name in text:
                hits.append(f"{p.name}:{name}")
    assert hits == []


def test_source_registry_exists():
    csv_path = ROOT / "manifests" / "SOURCE_REGISTRY.csv"
    with open(csv_path, newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= 10
    ids = {r["source_id"] for r in rows}
    assert "LEI2025_UES16" in ids
    assert "LBNL2024_REPORT" in ids


def test_engineering_priors_have_provenance():
    p = pd.read_csv(ROOT / "data_processed" / "ENGINEERING_PRIORS.csv")
    assert p["source_id"].notna().all()
    assert (p["kind"] == "ENGINEERING_PRIOR").all()
