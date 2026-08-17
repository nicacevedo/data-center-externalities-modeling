"""Normalize OWRD water-use exports and attach conservative Prineville source mappings.

Rules enforced here:
- OWRD Water Use Query values are in acre-feet after OWRD conversion.
- Water-year Oct-Dec belong to the previous calendar year; Jan-Sep belong to the named water year.
- Zero is preserved as a reported zero; blank remains missing.
- Accepted source mappings and high-confidence candidates are kept separate.
- Reports shared by multiple physical sources (Airport Wells #1/#2) remain one reporting group,
  so volumes are never duplicated by exploding the many-to-one identity relationship.
- Conflicting/legacy aliases are never promoted automatically.
"""
from __future__ import annotations

from pathlib import Path
from collections import defaultdict
import argparse
import math
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "prineville.yaml"
CITY_RAW = ROOT / "data" / "raw" / "owrd" / "wateruse_entity_report.csv"
META_RAW = ROOT / "data" / "raw" / "owrd" / "wateruse_entity_report_facebook.txt"
CROSSWALK = ROOT / "data" / "canonical" / "prineville_owrd_source_crosswalk.csv"
META_SOURCES = ROOT / "data" / "canonical" / "meta_owrd_direct_sources.csv"
OUTDIR = ROOT / "data" / "processed"
AUDIT_OUT = ROOT / "outputs" / "owrd_mapping_audit.csv"

MONTHS = [
    ("October", 10), ("November", 11), ("December", 12),
    ("January", 1), ("February", 2), ("March", 3),
    ("April", 4), ("May", 5), ("June", 6),
    ("July", 7), ("August", 8), ("September", 9),
]
EXPECTED_ENTITY_COLUMNS = {
    "Water Year", "Report ID", "Facility Name", "Total Water Used",
    "Method of Measurement", "Source Name", "Location", "TRSQQ",
    "Water Right Holder's Name", "Company Name",
    *[m for m, _ in MONTHS],
}


def _config() -> dict:
    with CONFIG.open() as f:
        return yaml.safe_load(f)


def _af_to_m3() -> float:
    cfg = _config()
    return float(cfg.get("units", {}).get("acre_foot_to_m3", 1233.48183754752))


def _split_ids(value) -> list[int]:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    out = []
    for token in str(value).replace(",", ";").split(";"):
        token = token.strip()
        if not token:
            continue
        out.append(int(float(token)))
    return out


def _read_entity(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    # The OWRD text export is tab-delimited even when saved with a .csv suffix.
    d = pd.read_csv(path, sep="\t")
    missing = EXPECTED_ENTITY_COLUMNS - set(d.columns)
    if missing:
        raise ValueError(f"{path.name} is missing expected OWRD columns: {sorted(missing)}")
    d["Report ID"] = pd.to_numeric(d["Report ID"], errors="raise").astype(int)
    d["Water Year"] = pd.to_numeric(d["Water Year"], errors="raise").astype(int)
    return d


def _to_monthly(d: pd.DataFrame, dataset_role: str, af_to_m3: float) -> pd.DataFrame:
    id_cols = [
        "Water Year", "Report ID", "Facility Name", "Total Water Used",
        "Method of Measurement", "Source Name", "Location", "TRSQQ",
        "Water Right Holder's Name", "Company Name",
    ]
    z = d.melt(
        id_vars=id_cols,
        value_vars=[m for m, _ in MONTHS],
        var_name="report_month_name",
        value_name="volume_af",
    )
    month_num = {m: n for m, n in MONTHS}
    z["month_number"] = z.report_month_name.map(month_num).astype(int)
    z["calendar_year"] = z["Water Year"] - (z.month_number >= 10).astype(int)
    z["calendar_month"] = pd.to_datetime(
        {"year": z.calendar_year, "month": z.month_number, "day": 1}
    )
    z["volume_af"] = pd.to_numeric(z.volume_af, errors="coerce")
    z["volume_m3"] = z.volume_af * af_to_m3
    z["reported_flag"] = z.volume_af.notna()
    z["zero_reported_flag"] = z.volume_af.eq(0) & z.reported_flag
    z["dataset_role"] = dataset_role
    z["owrd_unit"] = "acre-feet"
    z = z.rename(columns={
        "Water Year": "water_year",
        "Report ID": "report_id",
        "Facility Name": "facility_name",
        "Total Water Used": "water_year_total_af_as_exported",
        "Method of Measurement": "measurement_method",
        "Source Name": "source_name",
        "Location": "location",
        "TRSQQ": "trsqq",
        "Water Right Holder's Name": "water_right_holder",
        "Company Name": "company_name",
    })
    return z


def _mapping_links(cw: pd.DataFrame, field: str) -> dict[int, list[dict]]:
    links: dict[int, list[dict]] = defaultdict(list)
    for _, r in cw.iterrows():
        for rid in _split_ids(r.get(field, "")):
            links[rid].append({
                "oha_facility_id": str(r.oha_facility_id),
                "canonical_source_name": str(r.canonical_source_name),
                "mapping_status": str(r.mapping_status),
                "confidence": float(r.confidence) if pd.notna(r.confidence) and str(r.confidence) != "" else math.nan,
            })
    return links


def _joined(items: list[dict], key: str) -> str:
    vals = []
    for item in items:
        v = str(item[key])
        if v not in vals:
            vals.append(v)
    return ";".join(vals)


def _confidence(items: list[dict]) -> float:
    vals = [x["confidence"] for x in items if pd.notna(x["confidence"])]
    return min(vals) if vals else math.nan


def _group_key(items: list[dict], tier: str) -> str:
    ids = sorted({x["oha_facility_id"] for x in items})
    if not ids:
        return ""
    if len(ids) == 1:
        return ids[0]
    return f"COMBINED_{tier.upper()}:" + "+".join(ids)


def attach_city_mapping(monthly: pd.DataFrame, cw: pd.DataFrame) -> pd.DataFrame:
    accepted = _mapping_links(cw, "accepted_owrd_report_ids")
    candidates = _mapping_links(cw, "candidate_owrd_report_ids")
    conflicts = _mapping_links(cw, "related_or_conflicting_report_ids")

    report_ids = set(monthly.report_id.unique())
    missing_accepted = sorted(set(accepted) - report_ids)
    missing_candidates = sorted(set(candidates) - report_ids)
    if missing_accepted:
        raise ValueError(f"Accepted OWRD Report IDs missing from City raw export: {missing_accepted}")
    if missing_candidates:
        raise ValueError(f"Candidate OWRD Report IDs missing from City raw export: {missing_candidates}")

    def fields_for(rid: int):
        a, c, x = accepted.get(rid, []), candidates.get(rid, []), conflicts.get(rid, [])
        return pd.Series({
            "accepted_source_ids": _joined(a, "oha_facility_id"),
            "accepted_source_names": _joined(a, "canonical_source_name"),
            "accepted_mapping_statuses": _joined(a, "mapping_status"),
            "accepted_confidence_min": _confidence(a),
            "candidate_source_ids": _joined(c, "oha_facility_id"),
            "candidate_source_names": _joined(c, "canonical_source_name"),
            "candidate_mapping_statuses": _joined(c, "mapping_status"),
            "candidate_confidence_min": _confidence(c),
            "conflict_or_related_source_ids": _joined(x, "oha_facility_id"),
            "conflict_or_related_source_names": _joined(x, "canonical_source_name"),
            "model_source_key": _group_key(a, "accepted"),
            "candidate_source_key": _group_key(c, "candidate"),
            "model_mapping_tier": "accepted" if a else "unmapped",
        })

    meta = pd.DataFrame({"report_id": sorted(report_ids)})
    extra = meta.report_id.apply(fields_for)
    meta = pd.concat([meta, extra], axis=1)
    return monthly.merge(meta, on="report_id", how="left", validate="many_to_one")


def _aggregate_model(mapped: pd.DataFrame, tier: str) -> pd.DataFrame:
    if tier == "accepted":
        key, ids, names, conf = "model_source_key", "accepted_source_ids", "accepted_source_names", "accepted_confidence_min"
    elif tier == "candidate":
        key, ids, names, conf = "candidate_source_key", "candidate_source_ids", "candidate_source_names", "candidate_confidence_min"
    else:
        raise ValueError(tier)
    d = mapped[mapped[key].fillna("").ne("")].copy()
    if d.empty:
        return pd.DataFrame()
    d["mapping_tier"] = tier
    grp = [key, ids, names, "calendar_month", "calendar_year"]
    out = d.groupby(grp, dropna=False).agg(
        volume_af=("volume_af", lambda s: s.sum(min_count=1)),
        reported_values=("reported_flag", "sum"),
        contributing_report_rows=("report_id", "size"),
        mapping_confidence=(conf, "min"),
        report_ids=("report_id", lambda s: ";".join(str(x) for x in sorted(set(s)))),
        facility_names=("facility_name", lambda s: ";".join(dict.fromkeys(str(x) for x in s if pd.notna(x)))),
        source_names=("source_name", lambda s: ";".join(dict.fromkeys(str(x) for x in s if pd.notna(x)))),
    ).reset_index()
    out["mapping_tier"] = tier
    out["volume_m3"] = out.volume_af * _af_to_m3()
    out["reported_flag"] = out.reported_values.gt(0)
    out["zero_reported_flag"] = out.volume_af.eq(0) & out.reported_flag
    out = out.rename(columns={key: "model_source_key", ids: "canonical_source_ids", names: "canonical_source_names"})
    out["allocation_note"] = out.canonical_source_ids.map(
        lambda x: "combined POD/reporting group; do not allocate across physical wells without another meter" if ";" in str(x) else "unique canonical source/reporting group"
    )
    return out.sort_values(["model_source_key", "calendar_month"]).reset_index(drop=True)


def _calendar_annual(monthly: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    d = monthly.copy()
    out = d.groupby(group_cols + ["calendar_year"], dropna=False).agg(
        volume_af=("volume_af", lambda s: s.sum(min_count=1)),
        reported_month_values=("reported_flag", "sum"),
        row_month_values=("reported_flag", "size"),
    ).reset_index()
    out["volume_m3"] = out.volume_af * _af_to_m3()
    out["coverage_note"] = "Calendar-year aggregation of available OWRD monthly values; blanks remain missing and are not converted to zero."
    return out


def _mapping_audit(cw: pd.DataFrame, city: pd.DataFrame) -> pd.DataFrame:
    report_ids = set(city.report_id.unique())
    rows = []
    for _, r in cw.iterrows():
        a = _split_ids(r.accepted_owrd_report_ids)
        c = _split_ids(r.candidate_owrd_report_ids)
        x = _split_ids(r.related_or_conflicting_report_ids)
        rows.append({
            "oha_facility_id": r.oha_facility_id,
            "canonical_source_name": r.canonical_source_name,
            "mapping_status": r.mapping_status,
            "confidence": r.confidence,
            "accepted_owrd_report_ids": r.accepted_owrd_report_ids,
            "accepted_ids_present": all(v in report_ids for v in a) if a else False,
            "candidate_owrd_report_ids": r.candidate_owrd_report_ids,
            "candidate_ids_present": all(v in report_ids for v in c) if c else False,
            "related_or_conflicting_report_ids": r.related_or_conflicting_report_ids,
            "conflict_ids_present": any(v in report_ids for v in x) if x else False,
            "owrd_wl_id_known": r.owrd_wl_id_known,
            "production_handling": r.production_handling,
        })
    return pd.DataFrame(rows)


def prepare() -> dict[str, Path]:
    af_to_m3 = _af_to_m3()
    OUTDIR.mkdir(parents=True, exist_ok=True)
    AUDIT_OUT.parent.mkdir(parents=True, exist_ok=True)

    cw = pd.read_csv(CROSSWALK, dtype={"accepted_owrd_report_ids": str, "candidate_owrd_report_ids": str, "related_or_conflicting_report_ids": str})
    city_raw = _read_entity(CITY_RAW)
    city_monthly = attach_city_mapping(_to_monthly(city_raw, "city_of_prineville_owrd_entity", af_to_m3), cw)

    # Keep every City report-month, including unmapped historical/standby records.
    city_report_path = OUTDIR / "owrd_city_monthly_report_use.csv"
    city_monthly.to_csv(city_report_path, index=False)

    accepted = _aggregate_model(city_monthly, "accepted")
    accepted_path = OUTDIR / "owrd_city_monthly_model_use.csv"
    accepted.to_csv(accepted_path, index=False)

    candidates = _aggregate_model(city_monthly, "candidate")
    candidate_path = OUTDIR / "owrd_city_monthly_candidate_use.csv"
    candidates.to_csv(candidate_path, index=False)

    accepted_annual = _calendar_annual(accepted, ["model_source_key", "canonical_source_ids", "canonical_source_names", "mapping_tier"]) if not accepted.empty else pd.DataFrame()
    accepted_annual_path = OUTDIR / "owrd_city_annual_model_use.csv"
    accepted_annual.to_csv(accepted_annual_path, index=False)

    audit = _mapping_audit(cw, city_monthly)
    audit.to_csv(AUDIT_OUT, index=False)

    outputs = {
        "city_report_monthly": city_report_path,
        "city_accepted_monthly": accepted_path,
        "city_candidate_monthly": candidate_path,
        "city_accepted_annual": accepted_annual_path,
        "mapping_audit": AUDIT_OUT,
    }

    if META_RAW.exists():
        meta_raw = _read_entity(META_RAW)
        meta_monthly = _to_monthly(meta_raw, "vitesse_facebook_direct_owrd_entity", af_to_m3)
        meta_sources = pd.read_csv(META_SOURCES)
        meta_monthly = meta_monthly.merge(meta_sources, on="report_id", how="left", validate="many_to_one", suffixes=("", "_registry"))
        if meta_monthly.canonical_name.isna().any():
            bad = sorted(meta_monthly.loc[meta_monthly.canonical_name.isna(), "report_id"].unique())
            raise ValueError(f"Meta/Vitesse report IDs missing from canonical direct-source registry: {bad}")
        meta_monthly_path = OUTDIR / "owrd_meta_direct_monthly_use.csv"
        meta_monthly.to_csv(meta_monthly_path, index=False)
        meta_annual = _calendar_annual(meta_monthly, ["report_id", "canonical_name", "facility_name", "company_name"])
        meta_annual["boundary_note"] = "Direct OWRD POD reporting for VITESSE LLC C/O FACEBOOK INC. Treat as direct-groundwater evidence, not automatically equal to Meta site total withdrawal."
        meta_annual_path = OUTDIR / "owrd_meta_direct_annual_use.csv"
        meta_annual.to_csv(meta_annual_path, index=False)
        outputs["meta_direct_monthly"] = meta_monthly_path
        outputs["meta_direct_annual"] = meta_annual_path

    # Assertions that prevent the known high-risk mistakes from reappearing.
    accepted_ids = set()
    for v in cw.accepted_owrd_report_ids:
        accepted_ids.update(_split_ids(v))
    assert 12941 not in accepted_ids, "Legacy 4th St CROO2121 must not map to current 4th St Deep #2."
    assert 68003 not in accepted_ids, "D13/CROO54734 must not map to current DT13/CROO54789."
    assert (accepted.loc[accepted.model_source_key.str.contains("SRC-GA", na=False), "canonical_source_ids"].str.contains("SRC-GB").all()), "Airport 1/2 combined reporting must remain combined."

    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    outputs = prepare()
    print("PASS: OWRD water-use exports normalized with conservative source mapping.")
    for k, p in outputs.items():
        print(f"  {k}: {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
