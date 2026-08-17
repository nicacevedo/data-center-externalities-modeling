"""Validate the Stage 4 Crook County permit chronology and code-facing campus table.

This audit is deliberately conservative. It checks provenance and date consistency but
never infers missing square footage, electrical capacity, or commissioning dates.
"""
from pathlib import Path
import json
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BUILDINGS = ROOT / "data" / "manual_templates" / "campus_buildings.csv"
EVIDENCE = ROOT / "data" / "canonical" / "campus_permit_evidence.csv"
EVENTS = ROOT / "data" / "canonical" / "campus_permit_events.csv"
OUT = ROOT / "outputs" / "campus_permit_audit.csv"

BUILDING_REQUIRED = [
    "building_id", "permit_id", "issue_date", "final_or_co_date", "sqft",
    "electrical_capacity_mw_if_stated", "cooling_system_description",
    "source_record", "quality_note",
]
EVIDENCE_REQUIRED = [
    "permit_id", "source_filename", "building_id", "project_scope", "permit_type",
    "record_status", "opened_date", "final_or_co_date", "model_use", "relevance",
    "source_record", "quality_note",
]
EVENT_REQUIRED = [
    "date", "date_precision", "event_type", "event", "source_id", "model_use", "confidence"
]


def _require_columns(df, required, label):
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise AssertionError(f"{label} missing required columns: {missing}")


def _split_source_ids(value):
    if pd.isna(value):
        return []
    return [x.strip() for x in str(value).split(";") if x.strip()]


def main():
    for p in [BUILDINGS, EVIDENCE, EVENTS]:
        if not p.exists():
            raise FileNotFoundError(f"Missing Stage 4 file: {p.relative_to(ROOT)}")

    b = pd.read_csv(BUILDINGS)
    e = pd.read_csv(EVIDENCE)
    v = pd.read_csv(EVENTS)
    _require_columns(b, BUILDING_REQUIRED, "campus_buildings.csv")
    _require_columns(e, EVIDENCE_REQUIRED, "campus_permit_evidence.csv")
    _require_columns(v, EVENT_REQUIRED, "campus_permit_events.csv")

    issues = []
    def check(name, condition, detail):
        passed = bool(condition)
        issues.append({"check": name, "status": "PASS" if passed else "FAIL", "detail": detail})
        if not passed:
            raise AssertionError(f"Stage 4 audit failed: {name}: {detail}")

    check("evidence_permit_ids_unique", e["permit_id"].notna().all() and not e["permit_id"].duplicated().any(),
          f"rows={len(e)}, unique_permit_ids={e['permit_id'].nunique(dropna=True)}")
    check("model_facing_permit_ids_unique", b["permit_id"].notna().all() and not b["permit_id"].duplicated().any(),
          f"rows={len(b)}, unique_permit_ids={b['permit_id'].nunique(dropna=True)}")
    check("model_facing_subset_of_evidence", set(b["permit_id"]).issubset(set(e["permit_id"])),
          f"unmatched={sorted(set(b['permit_id'])-set(e['permit_id']))}")

    # Dates: issue_date is explicitly an ePermitting Opened-date proxy in this dataset.
    issue = pd.to_datetime(b["issue_date"], errors="coerce")
    final = pd.to_datetime(b["final_or_co_date"], errors="coerce")
    check("model_facing_dates_parse", issue.notna().all() and final.notna().all(),
          f"invalid_issue={int(issue.isna().sum())}, invalid_final={int(final.isna().sum())}")
    check("final_not_before_opened_proxy", not (final < issue).any(),
          f"violations={int((final < issue).sum())}")

    evdate = pd.to_datetime(v["date"], errors="coerce")
    check("event_dates_parse", evdate.notna().all(), f"invalid_event_dates={int(evdate.isna().sum())}")
    check("event_rows_unique", not v.duplicated().any(), f"rows={len(v)}, duplicate_rows={int(v.duplicated().sum())}")

    evidence_ids = set(e["permit_id"])
    event_sources = []
    for x in v["source_id"]:
        event_sources.extend(_split_source_ids(x))
    unmatched_event_sources = sorted(set(event_sources) - evidence_ids)
    check("event_sources_resolve_to_evidence", len(unmatched_event_sources) == 0,
          f"unmatched={unmatched_event_sources}")

    # Provenance must be explicit for all model-facing rows.
    check("model_facing_source_record_present", b["source_record"].fillna("").str.strip().ne("").all(),
          f"missing={int(b['source_record'].fillna('').str.strip().eq('').sum())}")
    check("model_facing_quality_note_present", b["quality_note"].fillna("").str.strip().ne("").all(),
          f"missing={int(b['quality_note'].fillna('').str.strip().eq('').sum())}")

    # These fields are intentionally blank unless directly supported by reviewed documents.
    sqft_nonnull = int(b["sqft"].notna().sum())
    mw_nonnull = int(b["electrical_capacity_mw_if_stated"].notna().sum())
    checks = pd.DataFrame(issues)
    OUT.parent.mkdir(exist_ok=True)
    checks.to_csv(OUT, index=False)

    anchors = v[v["confidence"].astype(str).str.lower().isin(["high", "very_high"])].copy()
    anchors = anchors.sort_values("date")

    print("PASS: campus permit evidence and chronology validated.")
    print(f"  reviewed permit records: {len(e)}")
    print(f"  model-facing relevant permits: {len(b)}")
    print(f"  chronology events: {len(v)}")
    print(f"  duplicate evidence permit IDs: {int(e['permit_id'].duplicated().sum())}")
    print(f"  final dates before opened-date proxy: {int((final < issue).sum())}")
    print(f"  square-footage values directly supported: {sqft_nonnull}")
    print(f"  electrical MW values directly supported: {mw_nonnull}")
    print(f"  audit table: {OUT.relative_to(ROOT)}")
    if len(anchors):
        print("  high-confidence chronology anchors:")
        for _, r in anchors.iterrows():
            print(f"    {r['date']}  {r['event_type']}: {r['event']}")


if __name__ == "__main__":
    main()
