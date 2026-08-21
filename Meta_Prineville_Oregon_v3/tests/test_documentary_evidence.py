"""Focused tests for the documentary/regulatory evidence layer."""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import integrate_prineville_documentary_evidence as docint  # noqa: E402
from integrate_prineville_documentary_evidence import (  # noqa: E402
    ALIASES,
    EVIDENCE,
    EVENTS,
    FORBIDDEN_CAMPUS_LOAD_ROLES,
    FORBIDDEN_CAMPUS_WATER_ROLES,
    META_REPORTING_BOUNDARY_STATUS,
    MW_GUARDRAIL_FACTS,
    OUT_ALIASES,
    OUT_AUDIT,
    OUT_EVENTS,
    OUT_EVIDENCE,
    SOURCES,
    YAML_PATH,
    main,
)

ANNUAL = ROOT / "data" / "canonical" / "meta_prineville_annual.csv"
GRAYBOX = ROOT / "src" / "prineville_graybox.py"
CONDITIONAL = ROOT / "src" / "conditional_reconstruction.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bind_tmp_root(monkeypatch: pytest.MonkeyPatch, tmp_root: Path) -> None:
    config = tmp_root / "config"
    monkeypatch.setattr(docint, "ROOT", tmp_root)
    monkeypatch.setattr(docint, "CONFIG", config)
    monkeypatch.setattr(docint, "SOURCES", config / "prineville_documentary_sources.csv")
    monkeypatch.setattr(docint, "EVIDENCE", config / "prineville_documentary_evidence.csv")
    monkeypatch.setattr(docint, "ALIASES", config / "prineville_documentary_aliases.csv")
    monkeypatch.setattr(docint, "EVENTS", config / "prineville_documentary_events.csv")
    monkeypatch.setattr(docint, "YAML_PATH", config / "prineville.yaml")
    monkeypatch.setattr(docint, "ANNUAL", tmp_root / "data" / "canonical" / "meta_prineville_annual.csv")
    monkeypatch.setattr(docint, "OUT_EVIDENCE", tmp_root / "data" / "canonical" / "campus_documentary_evidence.csv")
    monkeypatch.setattr(docint, "OUT_ALIASES", tmp_root / "data" / "canonical" / "campus_identity_crosswalk.csv")
    monkeypatch.setattr(docint, "OUT_EVENTS", tmp_root / "data" / "canonical" / "campus_regulatory_events.csv")
    monkeypatch.setattr(docint, "OUT_AUDIT", tmp_root / "outputs" / "documentary_evidence_audit.csv")


def test_seed_schema_and_unique_ids():
    sources = pd.read_csv(SOURCES, dtype=str, keep_default_na=False)
    evidence = pd.read_csv(EVIDENCE, dtype=str, keep_default_na=False)
    aliases = pd.read_csv(ALIASES, dtype=str, keep_default_na=False)
    events = pd.read_csv(EVENTS, dtype=str, keep_default_na=False)
    assert sources["source_id"].is_unique and sources["source_id"].ne("").all()
    assert evidence["evidence_id"].is_unique and evidence["evidence_id"].ne("").all()
    assert events["event_id"].is_unique and events["event_id"].ne("").all()
    assert set(evidence["doc_id"]).issubset(set(sources["source_id"]))
    assert set(aliases["source_doc_id"]).issubset(set(sources["source_id"]))
    assert set(events["source_doc_id"]).issubset(set(sources["source_id"]))
    assert len(sources) == 21
    assert len(evidence) == 48
    assert len(events) == 14
    assert "2021-10-28" not in aliases.to_csv(index=False)
    ev004 = events[events.event_id.eq("EV004")].iloc[0]
    assert ev004.date_start == "2014"
    assert ev004.date_end == ""
    assert ev004.date_precision == "early_year"
    assert "2014-04-30" not in events.to_csv(index=False)
    ev007 = events[events.event_id.eq("EV007")].iloc[0]
    ev014 = events[events.event_id.eq("EV014")].iloc[0]
    assert ev007.source_doc_id == "CITY_ORD1242_2018"
    assert ev014.source_doc_id == "CITY_ORD1243_2018"
    assert "first and second" not in ev007.description.lower()


def test_raw_sha256_when_files_exist():
    sources = pd.read_csv(SOURCES, dtype=str, keep_default_na=False)
    present = 0
    for r in sources.itertuples(index=False):
        path = ROOT / r.raw_relative_path
        if not path.exists():
            continue
        present += 1
        assert _sha256(path) == r.sha256, r.source_id
    # Partial local raw-PDF trees are valid: each present file is hashed;
    # each absent file is recorded as NOT_VERIFIED_RAW_MISSING by integration.


def test_missing_raw_pdfs_record_not_verified_status(tmp_path, monkeypatch):
    tmp_root = tmp_path / "clone"
    shutil.copytree(ROOT / "config", tmp_root / "config")
    _bind_tmp_root(monkeypatch, tmp_root)
    main()
    audit = pd.read_csv(tmp_root / "outputs" / "documentary_evidence_audit.csv", dtype=str, keep_default_na=False)
    sha_rows = audit[audit.check.str.startswith("raw_sha256:")]
    assert len(sha_rows) == 21
    assert set(sha_rows.status) == {"NOT_VERIFIED_RAW_MISSING"}
    events = pd.read_csv(tmp_root / "data" / "canonical" / "campus_regulatory_events.csv")
    assert len(events) == 14
    evidence = pd.read_csv(tmp_root / "data" / "canonical" / "campus_documentary_evidence.csv")
    assert len(evidence) == 48


def test_prn_cco_distinct_and_prn1_prn6_present():
    aliases = pd.read_csv(ALIASES, dtype=str, keep_default_na=False)
    ids = set(aliases["canonical_entity_id"])
    assert "PRN_CAMPUS" in ids
    assert "CCO_CAMPUS" in ids
    assert "PRN_CAMPUS" != "CCO_CAMPUS"
    assert {"PRN1", "PRN2", "PRN3", "PRN4", "PRN5", "PRN6"}.issubset(ids)


def test_2015_200k_facility_unmapped():
    evidence = pd.read_csv(EVIDENCE, dtype=str, keep_default_na=False)
    row = evidence[evidence.fact_key.eq("planned_facility_area")].iloc[0]
    assert row.building_id == "UNRESOLVED"
    assert float(row.value_numeric) == 200000.0
    assert row.value_relation == "approximately"
    aliases = pd.read_csv(ALIASES, dtype=str, keep_default_na=False)
    mapped = aliases[aliases.canonical_entity_id.isin(["PRN1", "PRN2", "PRN3", "PRN4", "PRN5", "PRN6", "CCO1_CCO2", "CCO_CAMPUS"])]
    assert "200000" not in " ".join(mapped.alias.tolist())
    assert "200,000" not in " ".join(mapped.notes.tolist())


def test_mw_semantic_guardrails():
    evidence = pd.read_csv(EVIDENCE, dtype=str, keep_default_na=False)
    for fact_key, mw in MW_GUARDRAIL_FACTS.items():
        row = evidence[evidence.fact_key.eq(fact_key)].iloc[0]
        assert float(row.value_numeric) == mw
        assert row.unit == "MW"
        assert row.model_role not in FORBIDDEN_CAMPUS_LOAD_ROLES
        assert "load" not in row.model_role.lower() or row.model_role in {
            "capacity_constraint",
            "service_context",
            "renewable_accounting_context",
        }


def test_2022_2023_no_new_capacity_semantics():
    evidence = pd.read_csv(EVIDENCE, dtype=str, keep_default_na=False)
    r2022 = evidence[evidence.fact_key.eq("no_additional_capacity_authorized")].iloc[0]
    r2023 = evidence[evidence.fact_key.eq("no_additional_capacity_reservation")].iloc[0]
    assert "no additional capacity" in r2022.value_text.lower()
    assert "no additional capacity reservation" in r2023.value_text.lower()
    assert r2022.model_role == "capacity_guardrail"
    assert r2023.model_role == "capacity_guardrail"


def test_meta_reporting_boundary_unresolved():
    cfg = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
    assert cfg["site"]["meta_reporting_boundary_status"] == META_REPORTING_BOUNDARY_STATUS
    evidence = pd.read_csv(EVIDENCE, dtype=str, keep_default_na=False)
    row = evidence[evidence.fact_key.eq("meta_reporting_boundary_status")].iloc[0]
    assert "UNRESOLVED" in row.value_text
    assert row.boundary_id == "UNRESOLVED_PRN_VS_PRN_PLUS_CCO"


def test_no_documentary_campus_meter_roles():
    evidence = pd.read_csv(EVIDENCE, dtype=str, keep_default_na=False)
    forbidden = FORBIDDEN_CAMPUS_LOAD_ROLES | FORBIDDEN_CAMPUS_WATER_ROLES
    bad = evidence[evidence.model_role.isin(forbidden)]
    assert bad.empty, sorted(bad.evidence_id)
    water = evidence[evidence.domain.eq("water_infrastructure")]
    assert not water.model_role.isin(FORBIDDEN_CAMPUS_WATER_ROLES).any()


def test_integration_does_not_alter_annual_targets_or_models():
    before = _sha256(ANNUAL)
    gray_before = GRAYBOX.read_text(encoding="utf-8")
    cond_before = CONDITIONAL.read_text(encoding="utf-8")
    main()
    assert _sha256(ANNUAL) == before
    assert GRAYBOX.read_text(encoding="utf-8") == gray_before
    assert CONDITIONAL.read_text(encoding="utf-8") == cond_before
    assert "holdout_years: [2023, 2024]" in YAML_PATH.read_text(encoding="utf-8")
    events_seed = ROOT / "data" / "canonical" / "campus_events_seed.csv"
    assert events_seed.exists()
    seed = pd.read_csv(events_seed)
    reg = pd.read_csv(OUT_EVENTS)
    assert len(reg) == 14
    assert list(seed.columns) != list(reg.columns) or not seed.equals(reg)
    evidence = pd.read_csv(OUT_EVIDENCE)
    aliases = pd.read_csv(OUT_ALIASES)
    audit = pd.read_csv(OUT_AUDIT)
    assert len(evidence) == 48
    assert len(aliases) == 18
    assert audit["check"].str.contains("meta_reporting_boundary_unresolved").any()
    assert (audit.loc[audit.check.eq("meta_reporting_boundary_unresolved"), "status"] == "PASS").all()
    sha_rows = audit[audit.check.str.startswith("raw_sha256:")]
    assert len(sha_rows) == 21
    allowed = {"PASS", "NOT_VERIFIED_RAW_MISSING"}
    assert set(sha_rows.status).issubset(allowed)
    sources = pd.read_csv(SOURCES, dtype=str, keep_default_na=False)
    present = sum((ROOT / r.raw_relative_path).exists() for r in sources.itertuples(index=False))
    if present == len(sources):
        assert set(sha_rows.status) == {"PASS"}
    elif present == 0:
        assert set(sha_rows.status) == {"NOT_VERIFIED_RAW_MISSING"}
