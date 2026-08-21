"""Integrate the documentary/regulatory evidence layer from tracked seeds.

Reads curated config CSVs. Does not OCR or reparse PDFs. If raw PDFs exist,
verifies SHA-256; missing raw files are recorded as NOT_VERIFIED_RAW_MISSING.
Does not alter Meta annual targets, model parameters, or holdout logic.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
SOURCES = CONFIG / "prineville_documentary_sources.csv"
EVIDENCE = CONFIG / "prineville_documentary_evidence.csv"
ALIASES = CONFIG / "prineville_documentary_aliases.csv"
EVENTS = CONFIG / "prineville_documentary_events.csv"
YAML_PATH = CONFIG / "prineville.yaml"
ANNUAL = ROOT / "data" / "canonical" / "meta_prineville_annual.csv"

OUT_EVIDENCE = ROOT / "data" / "canonical" / "campus_documentary_evidence.csv"
OUT_ALIASES = ROOT / "data" / "canonical" / "campus_identity_crosswalk.csv"
OUT_EVENTS = ROOT / "data" / "canonical" / "campus_regulatory_events.csv"
OUT_AUDIT = ROOT / "outputs" / "documentary_evidence_audit.csv"

META_REPORTING_BOUNDARY_STATUS = "unresolved_prn_vs_prn_plus_cco"

SOURCE_REQUIRED = [
    "source_id",
    "normalized_filename",
    "source_agency",
    "source_title",
    "source_date",
    "sha256",
    "tier",
    "raw_relative_path",
    "parent_source_url",
    "parent_source_sha256",
]
EVIDENCE_REQUIRED = [
    "evidence_id",
    "doc_id",
    "source_locator",
    "event_date",
    "date_precision",
    "entity_id",
    "boundary_id",
    "building_id",
    "domain",
    "fact_key",
    "value_text",
    "value_numeric",
    "value_relation",
    "unit",
    "confidence",
    "provenance_class",
    "model_role",
    "prohibited_use",
]
ALIAS_REQUIRED = [
    "canonical_entity_id",
    "alias",
    "alias_type",
    "source_doc_id",
    "confidence",
]
EVENT_REQUIRED = [
    "event_id",
    "date_start",
    "date_precision",
    "entity_id",
    "event_type",
    "description",
    "source_doc_id",
    "model_use",
    "confidence",
]

ALLOWED_CONFIDENCE = {"VERY_HIGH", "HIGH"}
ALLOWED_PROVENANCE = {"reported", "derived"}
ALLOWED_RELATION = {
    "",
    "stated",
    "approximately",
    "up_to",
    "at_least",
    "greater_than",
    "contractual_maximum",
    "estimate",
}
ALLOWED_TIER = {"core", "supporting"}

FORBIDDEN_CAMPUS_LOAD_ROLES = {
    "campus_load_observation",
    "campus_load_target",
    "campus_electricity_observation",
    "annual_campus_electricity_target",
    "monthly_campus_meter",
    "meter_observation",
    "calibration_target",
}
FORBIDDEN_CAMPUS_WATER_ROLES = {
    "campus_water_observation",
    "campus_water_target",
    "monthly_campus_water",
    "annual_campus_water_target",
    "meter_observation",
    "calibration_target",
}

MW_GUARDRAIL_FACTS = {
    "excess_transmission_capacity_mw": 120.0,
    "cco_interconnection_capacity_mw": 220.0,
    "cco_subject_new_large_load_mw": 180.0,
    "schedule272_resource_capacity_mw": 437.0,
}

PRN_BUILDING_IDS = {"PRN1", "PRN2", "PRN3", "PRN4", "PRN5", "PRN6"}


def _blank(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _require_columns(df: pd.DataFrame, required: list[str], label: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise AssertionError(f"{label} missing required columns: {missing}")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _numeric(value):
    text = _blank(value)
    if text == "":
        return None
    return float(text)


def _load_yaml_boundary() -> str:
    cfg = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
    site = cfg.get("site") or {}
    status = _blank(site.get("meta_reporting_boundary_status"))
    if status != META_REPORTING_BOUNDARY_STATUS:
        raise AssertionError(
            "config/prineville.yaml site.meta_reporting_boundary_status must be "
            f"{META_REPORTING_BOUNDARY_STATUS!r}; got {status!r}"
        )
    return status


def main() -> None:
    for p in [SOURCES, EVIDENCE, ALIASES, EVENTS, YAML_PATH]:
        if not p.exists():
            raise FileNotFoundError(p.relative_to(ROOT))

    sources = pd.read_csv(SOURCES, dtype=str, keep_default_na=False)
    evidence = pd.read_csv(EVIDENCE, dtype=str, keep_default_na=False)
    aliases = pd.read_csv(ALIASES, dtype=str, keep_default_na=False)
    events = pd.read_csv(EVENTS, dtype=str, keep_default_na=False)
    _require_columns(sources, SOURCE_REQUIRED, "prineville_documentary_sources.csv")
    _require_columns(evidence, EVIDENCE_REQUIRED, "prineville_documentary_evidence.csv")
    _require_columns(aliases, ALIAS_REQUIRED, "prineville_documentary_aliases.csv")
    _require_columns(events, EVENT_REQUIRED, "prineville_documentary_events.csv")

    issues: list[dict] = []

    def check(name: str, condition: bool, detail: str, fail: bool = True) -> None:
        issues.append(
            {"check": name, "status": "PASS" if condition else "FAIL", "detail": detail}
        )
        if fail and not condition:
            raise AssertionError(f"Documentary evidence audit failed: {name}: {detail}")

    yaml_status = _load_yaml_boundary()
    check(
        "meta_reporting_boundary_unresolved",
        yaml_status == META_REPORTING_BOUNDARY_STATUS,
        yaml_status,
    )

    check(
        "source_ids_unique",
        sources["source_id"].ne("").all() and not sources["source_id"].duplicated().any(),
        f"n={len(sources)} unique={sources['source_id'].nunique()}",
    )
    check(
        "evidence_ids_unique",
        evidence["evidence_id"].ne("").all() and not evidence["evidence_id"].duplicated().any(),
        f"n={len(evidence)} unique={evidence['evidence_id'].nunique()}",
    )
    check(
        "event_ids_unique",
        events["event_id"].ne("").all() and not events["event_id"].duplicated().any(),
        f"n={len(events)} unique={events['event_id'].nunique()}",
    )
    check(
        "source_tiers_allowed",
        sources["tier"].isin(ALLOWED_TIER).all(),
        f"tiers={sorted(set(sources['tier']))}",
    )

    source_ids = set(sources["source_id"])
    unmatched_docs = sorted(set(evidence["doc_id"]) - source_ids)
    check(
        "evidence_doc_ids_resolve",
        len(unmatched_docs) == 0,
        f"unmatched={unmatched_docs}",
    )
    unmatched_alias_docs = sorted(set(aliases["source_doc_id"]) - source_ids)
    check(
        "alias_doc_ids_resolve",
        len(unmatched_alias_docs) == 0,
        f"unmatched={unmatched_alias_docs}",
    )
    unmatched_event_docs = sorted(set(events["source_doc_id"]) - source_ids)
    check(
        "event_doc_ids_resolve",
        len(unmatched_event_docs) == 0,
        f"unmatched={unmatched_event_docs}",
    )

    bad_conf = sorted(set(evidence["confidence"]) - ALLOWED_CONFIDENCE)
    check("evidence_confidence_allowed", len(bad_conf) == 0, f"unexpected={bad_conf}")
    bad_prov = sorted(set(evidence["provenance_class"]) - ALLOWED_PROVENANCE)
    check("evidence_provenance_allowed", len(bad_prov) == 0, f"unexpected={bad_prov}")

    relation_ok = True
    relation_detail = []
    for r in evidence.itertuples(index=False):
        rel = _blank(r.value_relation)
        unit = _blank(r.unit)
        num = _numeric(r.value_numeric)
        if rel not in ALLOWED_RELATION:
            relation_ok = False
            relation_detail.append(f"{r.evidence_id}:bad_relation={rel}")
        if num is None and (rel or unit):
            relation_ok = False
            relation_detail.append(f"{r.evidence_id}:relation_or_unit_without_numeric")
        if num is not None and (not rel or not unit):
            relation_ok = False
            relation_detail.append(f"{r.evidence_id}:numeric_missing_relation_or_unit")
    check(
        "numeric_value_relation_unit_consistent",
        relation_ok,
        "; ".join(relation_detail) if relation_detail else "ok",
    )

    raw_verified = 0
    raw_missing = 0
    for r in sources.itertuples(index=False):
        path = ROOT / r.raw_relative_path
        expected = _blank(r.sha256).lower()
        if not path.exists():
            raw_missing += 1
            issues.append(
                {
                    "check": f"raw_sha256:{r.source_id}",
                    "status": "NOT_VERIFIED_RAW_MISSING",
                    "detail": r.raw_relative_path,
                }
            )
            continue
        got = _sha256(path)
        if got.lower() != expected:
            raise AssertionError(
                f"SHA-256 mismatch for {r.source_id}: {path.relative_to(ROOT)} "
                f"got {got} expected {expected}"
            )
        raw_verified += 1
        issues.append(
            {
                "check": f"raw_sha256:{r.source_id}",
                "status": "PASS",
                "detail": f"{r.raw_relative_path} sha256={got}",
            }
        )
    check(
        "raw_pdfs_present_or_explicitly_unverified",
        True,
        f"verified={raw_verified} missing={raw_missing} expected={len(sources)}",
        fail=False,
    )

    alias_ids = set(aliases["canonical_entity_id"])
    check("prn_and_cco_distinct", "PRN_CAMPUS" in alias_ids and "CCO_CAMPUS" in alias_ids, sorted(alias_ids))
    prn_codes = set(aliases.loc[aliases["canonical_entity_id"].isin(PRN_BUILDING_IDS), "canonical_entity_id"])
    check("prn1_to_prn6_present", prn_codes == PRN_BUILDING_IDS, sorted(prn_codes))

    area_2015 = evidence[evidence["fact_key"].eq("planned_facility_area")]
    check("2015_200k_ft2_present", len(area_2015) == 1, f"n={len(area_2015)}")
    if len(area_2015) == 1:
        row = area_2015.iloc[0]
        check(
            "2015_200k_ft2_building_unmapped",
            _blank(row.building_id) in {"", "UNRESOLVED"} and _numeric(row.value_numeric) == 200000.0,
            f"building_id={row.building_id!r} value={row.value_numeric} relation={row.value_relation}",
        )

    for fact_key, expected_mw in MW_GUARDRAIL_FACTS.items():
        subset = evidence[evidence["fact_key"].eq(fact_key)]
        check(f"mw_fact_present:{fact_key}", len(subset) == 1, f"n={len(subset)}")
        if len(subset) != 1:
            continue
        row = subset.iloc[0]
        role = _blank(row.model_role)
        check(
            f"mw_not_campus_load:{fact_key}",
            role not in FORBIDDEN_CAMPUS_LOAD_ROLES and _numeric(row.value_numeric) == expected_mw,
            f"model_role={role} value={row.value_numeric} unit={row.unit} relation={row.value_relation}",
        )

    water_rows = evidence[evidence["domain"].eq("water_infrastructure")]
    water_bad = water_rows[water_rows["model_role"].isin(FORBIDDEN_CAMPUS_WATER_ROLES)]
    check(
        "water_infrastructure_not_campus_water_observation",
        water_bad.empty,
        f"bad_ids={sorted(water_bad['evidence_id'])}",
    )

    no_cap_2022 = evidence[evidence["fact_key"].eq("no_additional_capacity_authorized")]
    no_cap_2023 = evidence[evidence["fact_key"].eq("no_additional_capacity_reservation")]
    check("2022_no_additional_capacity", len(no_cap_2022) == 1, f"n={len(no_cap_2022)}")
    check("2023_no_additional_capacity_reservation", len(no_cap_2023) == 1, f"n={len(no_cap_2023)}")

    boundary_rows = evidence[evidence["fact_key"].eq("meta_reporting_boundary_status")]
    check("meta_reporting_boundary_row", len(boundary_rows) == 1, f"n={len(boundary_rows)}")
    if len(boundary_rows) == 1:
        text = _blank(boundary_rows.iloc[0].value_text).upper()
        check(
            "meta_reporting_boundary_value_unresolved",
            "UNRESOLVED" in text,
            boundary_rows.iloc[0].value_text[:180],
        )

    meter_roles = FORBIDDEN_CAMPUS_LOAD_ROLES | FORBIDDEN_CAMPUS_WATER_ROLES
    meter_rows = evidence[evidence["model_role"].isin(meter_roles)]
    check(
        "no_documentary_campus_meter_observation",
        meter_rows.empty,
        f"bad_ids={sorted(meter_rows['evidence_id'])}",
    )

    dated_events = events[events["date_start"].str.strip().ne("")]
    check(
        "regulatory_events_have_dates",
        len(dated_events) == len(events) and events["date_start"].ne("").all(),
        f"n_events={len(events)} dated={len(dated_events)}",
    )

    OUT_EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    OUT_AUDIT.parent.mkdir(parents=True, exist_ok=True)
    evidence.to_csv(OUT_EVIDENCE, index=False)
    aliases.to_csv(OUT_ALIASES, index=False)
    dated_events.to_csv(OUT_EVENTS, index=False)
    pd.DataFrame(issues).to_csv(OUT_AUDIT, index=False)

    print("PASS: documentary/regulatory evidence integrated.")
    print(f"  sources: {len(sources)}")
    print(f"  evidence rows: {len(evidence)}")
    print(f"  identity aliases: {len(aliases)}")
    print(f"  regulatory events: {len(dated_events)}")
    print(f"  raw SHA-256 verified: {raw_verified}")
    print(f"  raw missing: {raw_missing}")
    print(f"  meta reporting boundary: {yaml_status}")
    print(f"  annual targets untouched: {ANNUAL.relative_to(ROOT)}")
    print(f"  audit table: {OUT_AUDIT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
