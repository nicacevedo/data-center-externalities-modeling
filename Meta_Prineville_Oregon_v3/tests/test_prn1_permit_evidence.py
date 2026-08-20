"""Focused tests for PRN1 strictly-valuable permit integration."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "data" / "raw" / "prineville_strictly_valuable_permits_v2"
FACTS = ROOT / "data" / "canonical" / "facility" / "prn1_addition_facts.csv"
EVIDENCE = ROOT / "data" / "canonical" / "campus_permit_evidence.csv"
EVENTS = ROOT / "data" / "canonical" / "campus_permit_events.csv"
BUILDINGS = ROOT / "data" / "manual_templates" / "campus_buildings.csv"
GRAYBOX = ROOT / "src" / "prineville_graybox.py"
CONDITIONAL = ROOT / "src" / "conditional_reconstruction.py"


def test_fact_source_files_exist_locally():
    facts = pd.read_csv(FACTS)
    assert not facts.empty
    assert facts["provenance_class"].eq("reported_permit_document_evidence").all()
    for sources in facts["source_file"].astype(str):
        for name in sources.split(";"):
            name = name.strip()
            assert name, "empty source_file"
            assert (PACKAGE / name).exists(), name


def test_area_remains_range_or_proxy_not_exact():
    facts = pd.read_csv(FACTS)
    proxy = facts[facts.quantity_name.eq("addition_area_proxy_ft2")].iloc[0]
    exact = facts[facts.quantity_name.eq("exact_final_area")].iloc[0]
    assert float(proxy.value_low) == 82273
    assert float(proxy.value_high) == 82736
    assert float(proxy.value_proxy) == 82700
    assert exact.status == "missing"
    assert pd.isna(exact.value_exact) or str(exact.value_exact).strip() == ""
    buildings = pd.read_csv(BUILDINGS)
    prn1 = buildings[buildings.permit_id.astype(str).str.startswith("217-21-00372")]
    assert prn1["sqft"].isna().all() or (prn1["sqft"].astype(str).str.strip() == "").all()


def test_electrical_counts_never_converted_to_mw():
    facts = pd.read_csv(FACTS)
    mw = facts[facts.quantity_name.eq("electrical_capacity_mw")].iloc[0]
    assert mw.status == "missing"
    assert pd.isna(mw.value_exact) or str(mw.value_exact).strip() == ""
    counts = facts[facts.quantity_name.isin(
        ["n_circuits_200A", "n_circuits_400A", "n_circuits_600A", "n_circuits_gt_1000A", "n_branch_circuits"]
    )]
    assert set(counts.quantity_name) == {
        "n_circuits_200A",
        "n_circuits_400A",
        "n_circuits_600A",
        "n_circuits_gt_1000A",
        "n_branch_circuits",
    }
    buildings = pd.read_csv(BUILDINGS)
    prn1 = buildings[buildings.permit_id.isin(facts.permit_id.astype(str).str.split(";").explode())]
    assert prn1["electrical_capacity_mw_if_stated"].isna().all() or (
        prn1["electrical_capacity_mw_if_stated"].astype(str).str.strip() == ""
    ).all()
    gray = GRAYBOX.read_text(encoding="utf-8")
    assert "217-21-003727" not in gray
    assert "electrical_capacity_mw" not in gray


def test_permit_evidence_does_not_modify_graybox_or_holdout():
    gray = GRAYBOX.read_text(encoding="utf-8")
    cond = CONDITIONAL.read_text(encoding="utf-8")
    for needle in (
        "217-21-003734",
        "prn1_addition_facts",
        "post-2023",
        "chiller breakpoint",
        "cooling regime",
    ):
        assert needle not in gray
        assert needle not in cond
    assert "supply_target_C: float = 25.0" in gray
    assert "evap_effectiveness: float = 0.85" in gray
    events = pd.read_csv(EVENTS)
    prn1 = events[events.source_id.astype(str).str.contains("217-21-00373|217-24-000066")]
    assert not prn1.empty
    assert prn1["model_use"].astype(str).str.contains("not a gray-box breakpoint|not holdout tuning|not a gray-box", regex=True).any()
    evidence = pd.read_csv(EVIDENCE)
    assert "217-21-003734-MECH" in set(evidence.permit_id.astype(str))
    assert evidence["permit_id"].is_unique
