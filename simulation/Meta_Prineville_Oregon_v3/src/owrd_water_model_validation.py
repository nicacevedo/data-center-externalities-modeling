"""External OWRD consistency layer for the reconstructed Meta Prineville water series.

This module does **not** calibrate the water model and does **not** replace Meta-reported
annual campus withdrawal. It joins three separately bounded series by calendar month:

1. modeled campus withdrawal (physics-shaped reconstruction; fitted/proxy, not a meter);
2. OWRD Vitesse/Facebook direct groundwater POD use (facility-adjacent evidence);
3. OWRD City of Prineville accepted municipal production (system context).

Missing OWRD values remain missing. Reported zeros remain zeros. City candidate/conflict
mappings never enter the default City total. OWRD volumes are reported water-use records
that may be measured or estimated; the retained measurement method is not assumed.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(__file__).resolve().parent
CONFIG = ROOT / "config" / "prineville.yaml"
TARGETS = ROOT / "data" / "canonical" / "meta_prineville_annual.csv"
DIRECT_REGISTRY = ROOT / "data" / "canonical" / "meta_owrd_direct_sources.csv"
CITY_ACCEPTED = ROOT / "data" / "processed" / "owrd_city_monthly_model_use.csv"
CITY_CANDIDATE = ROOT / "data" / "processed" / "owrd_city_monthly_candidate_use.csv"
CITY_REPORT = ROOT / "data" / "processed" / "owrd_city_monthly_report_use.csv"
DIRECT_MONTHLY = ROOT / "data" / "processed" / "owrd_meta_direct_monthly_use.csv"
HOURLY = ROOT / "outputs" / "hourly_conditional_reconstruction.csv"
ANNUAL_COMPARE = ROOT / "outputs" / "conditional_annual_compare.csv"
WATER_MODEL = ROOT / "outputs" / "conditional_water_model.csv"
OUT_MONTHLY = ROOT / "outputs" / "owrd_water_model_validation.csv"
OUT_ANNUAL = ROOT / "outputs" / "owrd_water_model_validation_annual.csv"
OUT_CHECKS = ROOT / "outputs" / "owrd_water_model_validation_checks.csv"
OUT_FIG = ROOT / "outputs" / "owrd_water_model_validation.png"

REGISTRY_DIRECT_REPORT_IDS = (64500, 64845, 64846)
DIRECT_PROVENANCE = (
    "reported OWRD water-use record (may be measured or estimated); "
    "Vitesse/Facebook direct groundwater POD use; separate boundary from Meta campus "
    "withdrawal and City production"
)
CITY_PROVENANCE = (
    "reported OWRD water-use record (may be measured or estimated); "
    "City accepted municipal POD production; system context only; not Meta campus "
    "meter data; candidate/conflict mappings excluded"
)
BOUNDARY_NOTE = (
    "Distinct accounting boundaries: Meta annual campus withdrawal, reconstructed "
    "monthly campus withdrawal, OWRD Vitesse/Facebook direct POD use, and OWRD City "
    "accepted municipal production are never treated as equivalent or additive."
)


def _month_start(values) -> pd.Series:
    return pd.to_datetime(values).dt.to_period("M").dt.to_timestamp()


def _join_ids(values) -> str:
    ids = []
    for value in values:
        if pd.isna(value):
            continue
        for token in str(value).replace(",", ";").split(";"):
            token = token.strip()
            if token and token not in ids:
                ids.append(token)
    return ";".join(ids)


def _join_text(values) -> str:
    out = []
    for value in values:
        if pd.isna(value):
            continue
        text = str(value).strip()
        if text and text not in out:
            out.append(text)
    return "; ".join(out)


def load_direct_registry() -> pd.DataFrame:
    registry = pd.read_csv(DIRECT_REGISTRY)
    registry["report_id"] = pd.to_numeric(registry["report_id"], errors="raise").astype(int)
    ids = tuple(sorted(int(x) for x in registry["report_id"].unique()))
    if ids != tuple(sorted(REGISTRY_DIRECT_REPORT_IDS)):
        raise ValueError(
            f"Direct POD registry IDs {ids} do not match the verified set "
            f"{REGISTRY_DIRECT_REPORT_IDS}."
        )
    return registry


def rebuild_hourly_reconstruction() -> pd.DataFrame:
    """Always rebuild the conditional reconstruction before validation.

    The hourly file is a deterministic generated artifact. Loading a stale copy
    would silently validate an outdated water series after model/weather/target changes.
    """

    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    from conditional_reconstruction import reconstruct

    HOURLY.parent.mkdir(parents=True, exist_ok=True)
    hourly, annual, model = reconstruct()
    hourly.to_csv(HOURLY, index=False)
    annual.to_csv(ANNUAL_COMPARE, index=False)
    pd.DataFrame([model]).to_csv(WATER_MODEL, index=False)
    return _prepare_hourly(hourly)


def _prepare_hourly(hourly: pd.DataFrame) -> pd.DataFrame:
    required = {
        "timestamp_utc",
        "water_withdrawal_proxy_m3_per_h",
        "p_fac_mw",
        "year",
    }
    missing = required - set(hourly.columns)
    if missing:
        raise ValueError(f"Hourly reconstruction is missing columns: {sorted(missing)}")
    hourly = hourly.copy()
    hourly["timestamp_utc"] = pd.to_datetime(hourly["timestamp_utc"], utc=True)
    return hourly


def load_existing_hourly() -> pd.DataFrame:
    if not HOURLY.exists():
        raise FileNotFoundError(f"Missing {HOURLY}; rebuild the reconstruction first.")
    return _prepare_hourly(pd.read_csv(HOURLY))


def modeled_monthly_campus_withdrawal(hourly: pd.DataFrame) -> pd.DataFrame:
    """Aggregate reconstructed hourly campus water to UTC calendar months.

    UTC months match the reconstruction's year assignment. This preserves the
    identity that monthly modeled water sums to the existing annual water_pred_m3
    series. That annual series is a train-only prediction, not a forced closure
    to Meta-reported withdrawal.
    """

    z = hourly.copy()
    ts_naive_utc = z["timestamp_utc"].dt.tz_convert("UTC").dt.tz_localize(None)
    z["calendar_month"] = ts_naive_utc.dt.to_period("M").dt.to_timestamp()
    z["calendar_year"] = z["calendar_month"].dt.year
    grouped = z.groupby(["calendar_month", "calendar_year"], dropna=False)
    out = grouped.agg(
        modeled_campus_withdrawal_m3=("water_withdrawal_proxy_m3_per_h", "sum"),
        modeled_hours=("water_withdrawal_proxy_m3_per_h", "size"),
        modeled_finite_hours=("water_withdrawal_proxy_m3_per_h", lambda s: int(s.notna().sum())),
        modeled_facility_energy_mwh=("p_fac_mw", "sum"),
    ).reset_index()
    out["modeled_water_provenance"] = (
        "fitted/proxy monthly aggregation of physics-shaped campus withdrawal; "
        "not City or OWRD meter data; not annual Meta closure"
    )
    return out.sort_values("calendar_month").reset_index(drop=True)


def direct_reporting_intervals(direct: pd.DataFrame) -> dict[int, tuple[pd.Timestamp, pd.Timestamp]]:
    """Active/reporting interval per direct POD report.

    Intervals are the first and last calendar months present in the bundled OWRD
    entity export for that report_id. A report is not expected before it appears
    in the export. This is not a well-commissioning record.
    """

    d = direct.copy()
    d["report_id"] = pd.to_numeric(d["report_id"], errors="raise").astype(int)
    d["calendar_month"] = _month_start(d["calendar_month"])
    out: dict[int, tuple[pd.Timestamp, pd.Timestamp]] = {}
    for rid, g in d.groupby("report_id"):
        out[int(rid)] = (g["calendar_month"].min(), g["calendar_month"].max())
    return out


def aggregate_direct_groundwater(
    direct: pd.DataFrame,
    registry: pd.DataFrame,
    months: pd.Series | None = None,
) -> pd.DataFrame:
    """Sum verified Vitesse/Facebook POD reports without converting blanks to zero.

    Expected coverage is lifecycle-aware: a report is expected only inside its
    documented export interval. Months before a report appears are not missing reports.
    """

    d = direct.copy()
    d["report_id"] = pd.to_numeric(d["report_id"], errors="raise").astype(int)
    d["calendar_month"] = _month_start(d["calendar_month"])
    d["calendar_year"] = d["calendar_month"].dt.year
    allowed = set(int(x) for x in registry["report_id"])
    extra = sorted(set(d["report_id"]) - allowed)
    if extra:
        raise ValueError(f"Direct monthly file contains report IDs outside the registry: {extra}")
    d = d[d["report_id"].isin(allowed)].copy()
    if d.duplicated(["report_id", "calendar_month"]).any():
        raise ValueError("Duplicate report_id/calendar_month rows in direct OWRD monthly use.")

    intervals = direct_reporting_intervals(d)
    if months is None:
        month_index = sorted(set(d["calendar_month"]))
    else:
        month_index = sorted(set(_month_start(pd.Series(months))))

    lookup = {(int(r.report_id), pd.Timestamp(r.calendar_month)): r for r in d.itertuples(index=False)}
    rows = []
    for month in month_index:
        month = pd.Timestamp(month)
        expected_ids = sorted(
            rid for rid, (first, last) in intervals.items() if first <= month <= last
        )
        expected_n = len(expected_ids)
        not_yet = sorted(rid for rid, (first, last) in intervals.items() if month < first)
        after = sorted(rid for rid, (first, last) in intervals.items() if month > last)

        reported_rows = []
        missing_ids = []
        for rid in expected_ids:
            rec = lookup.get((rid, month))
            if rec is not None and bool(getattr(rec, "reported_flag", False)):
                reported_rows.append(rec)
            else:
                missing_ids.append(rid)

        n_reported = len(reported_rows)
        volumes = [getattr(r, "volume_m3") for r in reported_rows]
        volume = np.nan
        if reported_rows:
            volume = pd.Series(volumes, dtype="float64").sum(min_count=1)
        n_zero = int(sum(bool(getattr(r, "zero_reported_flag", False)) for r in reported_rows))
        n_positive = int(sum(pd.notna(v) and float(v) > 0 for v in volumes))
        methods = _join_text([getattr(r, "measurement_method", None) for r in reported_rows])
        n_missing = expected_n - n_reported

        if expected_n == 0:
            status = "not_applicable"
        elif n_reported == 0:
            status = "missing"
        elif n_missing > 0:
            status = "partial_missing"
        elif n_positive == 0:
            status = "reported_zero"
        else:
            status = "reported"

        rows.append(
            {
                "calendar_month": month,
                "calendar_year": int(month.year),
                "owrd_meta_direct_groundwater_m3": float(volume) if pd.notna(volume) else np.nan,
                "owrd_meta_direct_report_count": n_reported,
                "owrd_meta_direct_expected_report_count": expected_n,
                "owrd_meta_direct_report_ids": _join_ids([getattr(r, "report_id") for r in reported_rows]),
                "owrd_meta_direct_expected_report_ids": ";".join(str(x) for x in expected_ids),
                "owrd_meta_direct_not_yet_applicable_ids": ";".join(str(x) for x in not_yet),
                "owrd_meta_direct_after_interval_ids": ";".join(str(x) for x in after),
                "owrd_meta_direct_missing_report_ids": ";".join(str(x) for x in missing_ids),
                "owrd_meta_direct_measurement_method": methods,
                "owrd_meta_direct_reporting_status": status,
                "owrd_meta_direct_n_missing_reports": n_missing,
                "owrd_meta_direct_n_not_yet_applicable": len(not_yet),
                "owrd_meta_direct_n_after_interval": len(after),
                "owrd_meta_direct_n_zero_reports": n_zero,
                "owrd_meta_direct_n_positive_reports": n_positive,
                "owrd_meta_direct_provenance": DIRECT_PROVENANCE,
            }
        )
    return pd.DataFrame(rows).sort_values("calendar_month").reset_index(drop=True)


def city_measurement_methods_by_month(
    city: pd.DataFrame,
    report_use: pd.DataFrame | None,
) -> pd.Series:
    """Retain OWRD measurement_method on the City monthly series."""

    if report_use is None or report_use.empty:
        if "measurement_method" in city.columns:
            return city.groupby(_month_start(city["calendar_month"]))["measurement_method"].apply(_join_text)
        return pd.Series(dtype=object)

    ru = report_use.copy()
    ru["calendar_month"] = _month_start(ru["calendar_month"])
    ru["report_id"] = pd.to_numeric(ru["report_id"], errors="coerce")
    accepted_ids: set[int] = set()
    if "report_ids" in city.columns:
        for value in city["report_ids"].dropna():
            for token in str(value).replace(",", ";").split(";"):
                token = token.strip()
                if token:
                    accepted_ids.add(int(float(token)))
    if accepted_ids:
        ru = ru[ru["report_id"].isin(accepted_ids)].copy()
    tier_col = "model_mapping_tier" if "model_mapping_tier" in ru.columns else (
        "mapping_tier" if "mapping_tier" in ru.columns else None
    )
    if tier_col is not None:
        ru = ru[ru[tier_col].fillna("").eq("accepted")].copy()
    if "measurement_method" not in ru.columns:
        return pd.Series(dtype=object)
    return ru.groupby("calendar_month")["measurement_method"].apply(_join_text)


def aggregate_city_production(
    city: pd.DataFrame,
    *,
    tier: str,
    volume_name: str,
    report_use: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Aggregate City OWRD groups. Default validation uses accepted mappings only."""

    d = city.copy()
    if "mapping_tier" in d.columns:
        d = d[d["mapping_tier"].fillna("").eq(tier)].copy()
    d["calendar_month"] = _month_start(d["calendar_month"])
    d["calendar_year"] = d["calendar_month"].dt.year
    key = "model_source_key"
    if d.duplicated([key, "calendar_month"]).any():
        raise ValueError(f"Duplicate {key}/calendar_month rows in City {tier} OWRD use.")

    methods = city_measurement_methods_by_month(d, report_use) if tier == "accepted" else pd.Series(dtype=object)
    prefix = "owrd_city" if tier == "accepted" else "owrd_city_candidate"
    rows = []
    for month, g in d.groupby("calendar_month", dropna=False):
        reported = g[g["reported_flag"].fillna(False)]
        volume = reported["volume_m3"].sum(min_count=1) if len(reported) else np.nan
        if reported.empty:
            volume = np.nan
        n_groups = int(g[key].nunique())
        n_reported = int(reported[key].nunique()) if len(reported) else 0
        n_missing = n_groups - n_reported
        n_zero = int(reported["zero_reported_flag"].fillna(False).sum()) if len(reported) else 0
        if n_reported == 0:
            status = "missing"
        elif n_missing > 0:
            status = "partial_missing"
        elif pd.notna(volume) and float(volume) == 0:
            status = "reported_zero"
        else:
            status = "reported"
        method = methods.get(pd.Timestamp(month), "") if len(methods) else ""
        if not method and "measurement_method" in g.columns:
            method = _join_text(g["measurement_method"])
        row = {
            "calendar_month": month,
            "calendar_year": int(pd.Timestamp(month).year),
            volume_name: float(volume) if pd.notna(volume) else np.nan,
            f"{prefix}_n_source_groups": n_groups,
            f"{prefix}_n_reported_groups": n_reported,
            f"{prefix}_n_missing_groups": n_missing,
            f"{prefix}_n_zero_groups": n_zero,
            f"{prefix}_report_ids": _join_ids(g["report_ids"] if "report_ids" in g else g.get("report_id", [])),
            f"{prefix}_source_groups": _join_ids(g[key]),
            f"{prefix}_reporting_status": status,
        }
        if tier == "accepted":
            row["owrd_city_mapping_confidence_min"] = (
                float(g["mapping_confidence"].min()) if "mapping_confidence" in g else np.nan
            )
            row["owrd_city_measurement_method"] = method
            row["owrd_city_production_provenance"] = CITY_PROVENANCE
        else:
            row["owrd_city_candidate_note"] = (
                "sensitivity/context only; excluded from owrd_city_production_m3"
            )
        rows.append(row)
    return pd.DataFrame(rows).sort_values("calendar_month").reset_index(drop=True)


def _ratio(numer, denom) -> float:
    if pd.notna(numer) and pd.notna(denom) and float(denom) > 0 and np.isfinite(float(numer)):
        return float(numer) / float(denom)
    return np.nan


def assign_validation_flags(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    flags = []
    notes = []
    for r in out.itertuples(index=False):
        note_parts = []
        modeled = r.modeled_campus_withdrawal_m3
        direct = r.owrd_meta_direct_groundwater_m3
        city = r.owrd_city_production_m3
        n_rep = int(r.owrd_meta_direct_report_count) if pd.notna(r.owrd_meta_direct_report_count) else 0
        n_exp = int(r.owrd_meta_direct_expected_report_count) if pd.notna(r.owrd_meta_direct_expected_report_count) else 0
        city_status = getattr(r, "owrd_city_reporting_status", "missing")

        direct_applicable = n_exp > 0
        direct_missing = direct_applicable and (
            n_rep == 0 or not (pd.notna(direct) and np.isfinite(float(direct)))
        )
        modeled_gt_city = (
            pd.notna(modeled) and pd.notna(city)
            and np.isfinite(float(modeled)) and np.isfinite(float(city))
            and float(modeled) > float(city) + 1e-9
        )
        high_city_share = (
            pd.notna(modeled) and pd.notna(city)
            and np.isfinite(float(modeled)) and float(city) > 0
            and float(modeled) / float(city) >= 0.5
        )
        if modeled_gt_city:
            flag = "review_boundary"
            note_parts.append(
                "Reconstructed campus withdrawal exceeds accepted City municipal production. "
                "Context diagnostic only; City production is not Meta meter data."
            )
        elif (
            (not direct_missing)
            and pd.notna(direct)
            and np.isfinite(float(direct))
            and np.isfinite(float(modeled))
            and float(direct) > float(modeled) + 1e-9
        ):
            flag = "review_boundary"
            note_parts.append(
                "Direct POD volume exceeds reconstructed campus withdrawal. This is a boundary/"
                "coverage/model review trigger, not an automatic invalidation."
            )
        elif direct_missing:
            flag = "missing_owrd"
            note_parts.append(
                "No reported Vitesse/Facebook direct POD volume this month among reports in their "
                "documented interval; blank was not converted to zero."
            )
        elif (n_exp > 0 and n_rep < n_exp) or city_status == "partial_missing":
            flag = "partial_owrd_coverage"
            if n_exp > 0 and n_rep < n_exp:
                note_parts.append(
                    f"{n_rep} of {n_exp} interval-expected direct POD reports have reported values."
                )
            if city_status == "partial_missing":
                note_parts.append("Some accepted City source groups are unreported this month.")
        else:
            flag = "no_diagnostic_trigger"
            note_parts.append(
                "Series overlap and neither simple threshold was triggered. This is not evidence "
                "that OWRD validates the reconstruction."
            )
            if not direct_applicable:
                note_parts.append(
                    "No direct POD report is in its documented reporting interval this month."
                )

        if city_status == "missing":
            note_parts.append("Accepted City production is missing this month.")
        if high_city_share:
            note_parts.append(
                "Reconstructed campus withdrawal is at least half of accepted City production "
                "this month (system-context diagnostic, not evidence of Meta deliveries)."
            )
        flags.append(flag)
        notes.append(" ".join(note_parts))
    out["validation_flag"] = flags
    out["validation_note"] = notes
    out["accounting_boundary_note"] = BOUNDARY_NOTE
    return out


def join_monthly_validation(
    modeled: pd.DataFrame,
    direct: pd.DataFrame,
    city: pd.DataFrame,
    candidate: pd.DataFrame,
    targets: pd.DataFrame,
) -> pd.DataFrame:
    spine = modeled[["calendar_month", "calendar_year"]].drop_duplicates()
    z = spine.merge(modeled, on=["calendar_month", "calendar_year"], how="left")
    z = z.merge(direct, on=["calendar_month", "calendar_year"], how="left")
    city_keep = [
        c for c in [
            "calendar_month",
            "calendar_year",
            "owrd_city_production_m3",
            "owrd_city_n_source_groups",
            "owrd_city_n_reported_groups",
            "owrd_city_n_missing_groups",
            "owrd_city_n_zero_groups",
            "owrd_city_report_ids",
            "owrd_city_source_groups",
            "owrd_city_reporting_status",
            "owrd_city_mapping_confidence_min",
            "owrd_city_measurement_method",
            "owrd_city_production_provenance",
        ] if c in city.columns
    ]
    z = z.merge(city[city_keep], on=["calendar_month", "calendar_year"], how="left")
    if len(candidate):
        cand_keep = [
            "calendar_month",
            "calendar_year",
            "owrd_city_candidate_production_m3",
            "owrd_city_candidate_note",
        ]
        z = z.merge(candidate[cand_keep], on=["calendar_month", "calendar_year"], how="left")
    else:
        z["owrd_city_candidate_production_m3"] = np.nan
        z["owrd_city_candidate_note"] = "no candidate monthly rows"

    annual_water = targets[["year", "water_withdrawal_m3_reported"]].rename(
        columns={
            "year": "calendar_year",
            "water_withdrawal_m3_reported": "meta_annual_reported_withdrawal_m3",
        }
    )
    z = z.merge(annual_water, on="calendar_year", how="left")
    z["owrd_meta_direct_report_count"] = z["owrd_meta_direct_report_count"].fillna(0).astype(int)
    z["owrd_meta_direct_expected_report_count"] = z["owrd_meta_direct_expected_report_count"].fillna(0).astype(int)
    z["owrd_meta_direct_n_missing_reports"] = z["owrd_meta_direct_n_missing_reports"].fillna(
        z["owrd_meta_direct_expected_report_count"]
    ).astype(int)
    z["owrd_meta_direct_n_not_yet_applicable"] = z.get(
        "owrd_meta_direct_n_not_yet_applicable", pd.Series(0, index=z.index)
    ).fillna(0).astype(int)
    z["owrd_meta_direct_n_after_interval"] = z.get(
        "owrd_meta_direct_n_after_interval", pd.Series(0, index=z.index)
    ).fillna(0).astype(int)
    z["owrd_city_reporting_status"] = z["owrd_city_reporting_status"].fillna("missing")
    z["owrd_meta_direct_reporting_status"] = z["owrd_meta_direct_reporting_status"].fillna("not_applicable")
    z["owrd_meta_direct_expected_report_ids"] = z["owrd_meta_direct_expected_report_ids"].fillna("")
    z["owrd_meta_direct_report_ids"] = z["owrd_meta_direct_report_ids"].fillna("")
    z["owrd_meta_direct_provenance"] = z["owrd_meta_direct_provenance"].fillna(DIRECT_PROVENANCE)
    z["owrd_city_production_provenance"] = z["owrd_city_production_provenance"].fillna(CITY_PROVENANCE)
    z["direct_pod_to_modeled_ratio"] = [
        _ratio(d, m)
        for d, m in zip(z["owrd_meta_direct_groundwater_m3"], z["modeled_campus_withdrawal_m3"])
    ]
    z["modeled_to_city_production_ratio"] = [
        _ratio(m, c)
        for m, c in zip(z["modeled_campus_withdrawal_m3"], z["owrd_city_production_m3"])
    ]
    z = assign_validation_flags(z)
    z["calendar_month"] = pd.to_datetime(z["calendar_month"]).dt.strftime("%Y-%m-01")
    preferred = [
        "calendar_month",
        "calendar_year",
        "modeled_campus_withdrawal_m3",
        "owrd_meta_direct_groundwater_m3",
        "owrd_city_production_m3",
        "meta_annual_reported_withdrawal_m3",
        "owrd_meta_direct_report_count",
        "owrd_meta_direct_expected_report_count",
        "owrd_meta_direct_report_ids",
        "owrd_meta_direct_expected_report_ids",
        "owrd_city_reporting_status",
        "validation_flag",
        "validation_note",
        "direct_pod_to_modeled_ratio",
        "modeled_to_city_production_ratio",
        "owrd_meta_direct_measurement_method",
        "owrd_city_measurement_method",
        "owrd_meta_direct_reporting_status",
        "owrd_meta_direct_n_missing_reports",
        "owrd_meta_direct_n_not_yet_applicable",
        "owrd_meta_direct_n_after_interval",
        "owrd_city_source_groups",
        "owrd_city_report_ids",
        "owrd_city_n_source_groups",
        "owrd_city_n_reported_groups",
        "owrd_city_candidate_production_m3",
        "owrd_city_candidate_note",
        "modeled_water_provenance",
        "owrd_meta_direct_provenance",
        "owrd_city_production_provenance",
        "accounting_boundary_note",
    ]
    cols = [c for c in preferred if c in z.columns] + [c for c in z.columns if c not in preferred]
    return z[cols].sort_values(["calendar_year", "calendar_month"]).reset_index(drop=True)


def annual_validation(monthly: pd.DataFrame, annual_compare: pd.DataFrame | None) -> pd.DataFrame:
    z = monthly.copy()
    z["calendar_month"] = pd.to_datetime(z["calendar_month"])
    rows = []
    for year, g in z.groupby("calendar_year"):
        modeled = g["modeled_campus_withdrawal_m3"].sum(min_count=1)
        direct = g["owrd_meta_direct_groundwater_m3"].sum(min_count=1)
        city = g["owrd_city_production_m3"].sum(min_count=1)
        reported = g["meta_annual_reported_withdrawal_m3"].dropna()
        reported_val = float(reported.iloc[0]) if len(reported) else np.nan
        expected_report_months = int(g["owrd_meta_direct_expected_report_count"].sum())
        reported_report_months = int(g["owrd_meta_direct_report_count"].sum())
        coverage = (
            reported_report_months / expected_report_months if expected_report_months > 0 else np.nan
        )
        complete = bool(expected_report_months > 0 and reported_report_months == expected_report_months)
        rows.append(
            {
                "calendar_year": int(year),
                "modeled_campus_withdrawal_m3": modeled,
                "owrd_meta_direct_groundwater_m3": direct,
                "owrd_city_production_m3": city,
                "meta_annual_reported_withdrawal_m3": reported_val,
                "n_months": int(len(g)),
                "n_months_direct_reported": int(g["owrd_meta_direct_groundwater_m3"].notna().sum()),
                "n_months_city_reported": int(g["owrd_city_production_m3"].notna().sum()),
                "direct_expected_report_months": expected_report_months,
                "direct_reported_report_months": reported_report_months,
                "direct_coverage_fraction": coverage,
                "direct_annual_complete": complete,
                "direct_pod_to_modeled_ratio": _ratio(direct, modeled) if complete else np.nan,
                "modeled_to_city_production_ratio": _ratio(modeled, city),
                "direct_pod_to_meta_reported_ratio": _ratio(direct, reported_val) if complete else np.nan,
                "modeled_to_meta_reported_ratio": _ratio(modeled, reported_val),
                "n_review_boundary_months": int(g["validation_flag"].eq("review_boundary").sum()),
                "n_missing_owrd_months": int(g["validation_flag"].eq("missing_owrd").sum()),
                "n_partial_owrd_months": int(g["validation_flag"].eq("partial_owrd_coverage").sum()),
                "n_no_diagnostic_trigger_months": int(g["validation_flag"].eq("no_diagnostic_trigger").sum()),
                "annual_comparison_note": (
                    "Descriptive annual totals. Equality with Meta-reported withdrawal is not "
                    "expected. Direct POD and City production remain separate boundaries. "
                    "OWRD annual sums use reported months only; missing months are not zero-filled. "
                    "Direct annual ratios are NaN unless every interval-expected report-month is reported."
                ),
            }
        )
    out = pd.DataFrame(rows).sort_values("calendar_year").reset_index(drop=True)
    if annual_compare is not None and len(annual_compare):
        ac = annual_compare[["year", "water_pred_m3", "electricity_mwh_reported", "electricity_mwh_model_closure"]].rename(
            columns={"year": "calendar_year", "water_pred_m3": "modeled_annual_water_pred_m3"}
        )
        out = out.merge(ac, on="calendar_year", how="left")
        out["modeled_monthly_sum_minus_annual_pred_m3"] = (
            out["modeled_campus_withdrawal_m3"] - out["modeled_annual_water_pred_m3"]
        )
    return out


def coverage_diagnostics(monthly: pd.DataFrame, modeled: pd.DataFrame, direct: pd.DataFrame, city: pd.DataFrame) -> dict:
    modeled_months = pd.to_datetime(modeled["calendar_month"])
    direct_months = pd.to_datetime(direct.loc[direct["owrd_meta_direct_groundwater_m3"].notna(), "calendar_month"])
    city_months = pd.to_datetime(city.loc[city["owrd_city_production_m3"].notna(), "calendar_month"])
    overlap_direct = monthly["owrd_meta_direct_groundwater_m3"].notna() & monthly["modeled_campus_withdrawal_m3"].notna()
    overlap_city = monthly["owrd_city_production_m3"].notna() & monthly["modeled_campus_withdrawal_m3"].notna()
    overlap_both = overlap_direct & overlap_city
    return {
        "modeled_first_month": modeled_months.min().strftime("%Y-%m"),
        "modeled_last_month": modeled_months.max().strftime("%Y-%m"),
        "direct_first_reported_month": direct_months.min().strftime("%Y-%m") if len(direct_months) else None,
        "direct_last_reported_month": direct_months.max().strftime("%Y-%m") if len(direct_months) else None,
        "city_first_reported_month": city_months.min().strftime("%Y-%m") if len(city_months) else None,
        "city_last_reported_month": city_months.max().strftime("%Y-%m") if len(city_months) else None,
        "n_modeled_months": int(monthly["modeled_campus_withdrawal_m3"].notna().sum()),
        "n_overlap_direct_and_modeled": int(overlap_direct.sum()),
        "n_overlap_city_and_modeled": int(overlap_city.sum()),
        "n_overlap_all_three": int(overlap_both.sum()),
        "n_review_boundary": int(monthly["validation_flag"].eq("review_boundary").sum()),
        "n_missing_owrd": int(monthly["validation_flag"].eq("missing_owrd").sum()),
        "n_partial_owrd_coverage": int(monthly["validation_flag"].eq("partial_owrd_coverage").sum()),
        "n_no_diagnostic_trigger": int(monthly["validation_flag"].eq("no_diagnostic_trigger").sum()),
        "direct_exceeds_modeled_months": int(
            (
                monthly["owrd_meta_direct_groundwater_m3"]
                > monthly["modeled_campus_withdrawal_m3"] + 1e-9
            ).fillna(False).sum()
        ),
        "role": "external validation / consistency layer; not a calibration target",
    }


def run_checks(
    monthly: pd.DataFrame,
    annual: pd.DataFrame,
    hourly: pd.DataFrame,
    targets: pd.DataFrame,
    city_raw: pd.DataFrame,
    candidate_raw: pd.DataFrame,
    registry: pd.DataFrame,
) -> list[dict]:
    checks: list[dict] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "status": "PASS" if passed else "FAIL", "detail": detail})
        if not passed:
            raise AssertionError(f"{name}: {detail}")

    add("unique_calendar_month", monthly["calendar_month"].is_unique, f"n={len(monthly)}")
    add("units_are_m3_column_names", all("m3" in c for c in [
        "modeled_campus_withdrawal_m3",
        "owrd_meta_direct_groundwater_m3",
        "owrd_city_production_m3",
    ]), "volume columns use cubic metres")
    add(
        "no_combined_observed_campus_water_column",
        not any("observed_campus" in c or "owrd_plus" in c or "summed_water" in c for c in monthly.columns),
        "three boundaries remain separate columns",
    )
    add(
        "no_ok_validation_flag",
        not monthly["validation_flag"].eq("ok").any(),
        "ok was renamed so it cannot be read as model validated",
    )
    add(
        "provenance_is_reported_not_measured",
        monthly["owrd_meta_direct_provenance"].fillna("").str.startswith("reported OWRD").all()
        and monthly["owrd_city_production_provenance"].fillna("").str.startswith("reported OWRD").all(),
        "OWRD provenance is reported water-use record",
    )

    ids = set()
    for value in monthly["owrd_meta_direct_report_ids"].dropna():
        for token in str(value).split(";"):
            if token.strip():
                ids.add(int(token))
    allowed = set(int(x) for x in registry["report_id"])
    add("direct_report_ids_match_registry", ids <= allowed, f"observed={sorted(ids)}")
    add(
        "registry_contains_verified_pods",
        set(REGISTRY_DIRECT_REPORT_IDS) <= allowed,
        f"registry={sorted(allowed)}",
    )

    jan2011 = monthly.loc[monthly["calendar_month"].eq("2011-01-01")]
    if len(jan2011):
        add(
            "early_64500_not_expected_before_interval",
            int(jan2011["owrd_meta_direct_expected_report_count"].iloc[0]) == 2,
            f"expected={jan2011['owrd_meta_direct_expected_report_count'].iloc[0]}",
        )
        add(
            "early_two_report_month_not_partial_for_inactive_id",
            jan2011["validation_flag"].iloc[0] != "partial_owrd_coverage"
            or "64500" in str(jan2011["owrd_meta_direct_expected_report_ids"].iloc[0]),
            f"flag={jan2011['validation_flag'].iloc[0]}",
        )

    oct2013 = monthly.loc[monthly["calendar_month"].eq("2013-10-01")]
    if len(oct2013):
        add(
            "64500_expected_once_in_export_interval",
            int(oct2013["owrd_meta_direct_expected_report_count"].iloc[0]) == 3,
            f"expected={oct2013['owrd_meta_direct_expected_report_count'].iloc[0]}",
        )

    missing_month = monthly.loc[monthly["calendar_month"].eq("2024-04-01")]
    if len(missing_month):
        val = missing_month["owrd_meta_direct_groundwater_m3"].iloc[0]
        add(
            "missing_owrd_not_converted_to_zero",
            pd.isna(val),
            f"2024-04 direct volume={val!r}",
        )
        add(
            "in_interval_blank_is_missing_not_not_applicable",
            missing_month["owrd_meta_direct_reporting_status"].iloc[0] == "missing",
            f"status={missing_month['owrd_meta_direct_reporting_status'].iloc[0]}",
        )

    after = monthly.loc[monthly["calendar_month"].eq("2024-10-01")]
    if len(after):
        add(
            "after_export_interval_not_expected",
            int(after["owrd_meta_direct_expected_report_count"].iloc[0]) == 0,
            f"expected={after['owrd_meta_direct_expected_report_count'].iloc[0]}",
        )

    a2024 = annual.loc[annual["calendar_year"].eq(2024)]
    if len(a2024):
        add(
            "incomplete_year_direct_ratios_are_nan",
            (not bool(a2024["direct_annual_complete"].iloc[0]))
            and pd.isna(a2024["direct_pod_to_modeled_ratio"].iloc[0])
            and pd.isna(a2024["direct_pod_to_meta_reported_ratio"].iloc[0]),
            f"complete={a2024['direct_annual_complete'].iloc[0]} ratio={a2024['direct_pod_to_modeled_ratio'].iloc[0]}",
        )

    accepted_keys = set(city_raw["model_source_key"].dropna())
    candidate_keys = set(candidate_raw["model_source_key"].dropna()) if len(candidate_raw) else set()
    add("accepted_and_candidate_keys_disjoint", accepted_keys.isdisjoint(candidate_keys), "no silent candidate inclusion")
    if "mapping_tier" in city_raw.columns:
        add("city_default_file_is_accepted_only", set(city_raw["mapping_tier"].unique()) == {"accepted"}, "accepted only")

    both = monthly["owrd_city_production_m3"].notna() & monthly["owrd_city_candidate_production_m3"].notna()
    if both.any():
        same = np.allclose(
            monthly.loc[both, "owrd_city_production_m3"].to_numpy(float),
            monthly.loc[both, "owrd_city_candidate_production_m3"].to_numpy(float),
            equal_nan=True,
        )
        add("candidate_series_not_copied_into_accepted", not same, "candidate remains a separate field")

    joined = hourly.copy()
    joined["timestamp_utc"] = pd.to_datetime(joined["timestamp_utc"], utc=True)
    elec = joined.groupby(joined["timestamp_utc"].dt.year)["p_fac_mw"].sum().rename("modeled_mwh")
    tgt = targets.set_index("year")["electricity_mwh_reported"]
    err = (elec.reindex(tgt.index) - tgt).abs().max()
    add("electricity_annual_closure_unchanged", float(err) < 1e-4, f"max_abs_mwh={float(err):.3e}")

    if "modeled_monthly_sum_minus_annual_pred_m3" in annual.columns:
        water_err = annual["modeled_monthly_sum_minus_annual_pred_m3"].abs().max()
        add(
            "monthly_modeled_water_aggregates_to_annual_prediction",
            pd.isna(water_err) or float(water_err) < 1e-4,
            f"max_abs_m3={float(water_err) if pd.notna(water_err) else np.nan:.3e}",
        )

    ratio_ok = (
        monthly.loc[
            monthly["modeled_campus_withdrawal_m3"].fillna(0) <= 0,
            "direct_pod_to_modeled_ratio",
        ]
        .isna()
        .all()
    )
    add("ratios_nan_when_denominator_invalid", bool(ratio_ok), "direct/modeled NaN if modeled <= 0")
    add(
        "city_measurement_method_retained",
        "owrd_city_measurement_method" in monthly.columns
        and monthly["owrd_city_measurement_method"].fillna("").ne("").any(),
        "City series keeps aggregated measurement_method",
    )
    return checks


def plot_validation(monthly: pd.DataFrame, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    z = monthly.copy()
    z["calendar_month"] = pd.to_datetime(z["calendar_month"])
    fig, ax = plt.subplots(figsize=(11, 5.5), constrained_layout=True)
    ax.plot(
        z["calendar_month"],
        z["modeled_campus_withdrawal_m3"] / 1000.0,
        label="Modeled campus withdrawal (reconstructed; not a meter)",
        linewidth=1.8,
    )
    ax.plot(
        z["calendar_month"],
        z["owrd_meta_direct_groundwater_m3"] / 1000.0,
        label="OWRD Vitesse/Facebook direct groundwater PODs",
        linewidth=1.4,
    )
    ax.plot(
        z["calendar_month"],
        z["owrd_city_production_m3"] / 1000.0,
        label="OWRD City accepted municipal production (system context)",
        linewidth=1.2,
        alpha=0.85,
    )
    ax.set(
        title="External water consistency comparison — distinct accounting boundaries",
        xlabel="Calendar month",
        ylabel="Volume (thousand m³ / month)",
    )
    ax.legend(loc="upper left", frameon=False)
    ax.grid(alpha=0.25)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def self_test() -> None:
    """Synthetic checks that do not touch Meta annual calibration or raw OWRD files."""

    registry = pd.DataFrame({"report_id": list(REGISTRY_DIRECT_REPORT_IDS)})
    months = pd.to_datetime(["2019-12-01", "2020-01-01", "2020-02-01", "2020-03-01"])
    direct = pd.DataFrame(
        {
            "report_id": [64845, 64846, 64500, 64845, 64846, 64500, 64845, 64846, 64500, 64845, 64846],
            "calendar_month": [
                months[0], months[0],
                months[1], months[1], months[1],
                months[2], months[2], months[2],
                months[3], months[3], months[3],
            ],
            "volume_m3": [
                4.0, 2.0,                 # Dec 2019: 64500 not yet in export
                10.0, 5.0, 1.0,           # Jan complete
                np.nan, np.nan, np.nan,   # Feb missing, must stay missing
                0.0, 0.0, 0.0,            # Mar reported zeros
            ],
            "reported_flag": [
                True, True,
                True, True, True,
                False, False, False,
                True, True, True,
            ],
            "zero_reported_flag": [
                False, False,
                False, False, False,
                False, False, False,
                True, True, True,
            ],
            "measurement_method": ["Flowmeter"] * 11,
        }
    )
    city = pd.DataFrame(
        {
            "model_source_key": ["SRC-AA", "SRC-FA"] * 4,
            "calendar_month": np.repeat(months, 2),
            "volume_m3": [100.0, 50.0, 100.0, 50.0, 80.0, np.nan, 40.0, 20.0],
            "reported_flag": [True, True, True, True, True, False, True, True],
            "zero_reported_flag": [False, False, False, False, False, False, False, False],
            "mapping_tier": ["accepted"] * 8,
            "mapping_confidence": [1.0] * 8,
            "report_ids": ["12037", "26843"] * 4,
            "measurement_method": ["Flowmeter", "Estimate"] * 4,
        }
    )
    candidate = pd.DataFrame(
        {
            "model_source_key": ["SRC-KC"] * 4,
            "calendar_month": months,
            "volume_m3": [999.0, 999.0, 999.0, 999.0],
            "reported_flag": [True, True, True, True],
            "zero_reported_flag": [False, False, False, False],
            "mapping_tier": ["candidate"] * 4,
            "report_ids": ["67985"] * 4,
        }
    )
    modeled = pd.DataFrame(
        {
            "calendar_month": months,
            "calendar_year": [2019, 2020, 2020, 2020],
            "modeled_campus_withdrawal_m3": [20.0, 12.0, 20.0, 5.0],
            "modeled_hours": [744, 744, 696, 744],
            "modeled_finite_hours": [744, 744, 696, 744],
            "modeled_facility_energy_mwh": [1.0, 1.0, 1.0, 1.0],
            "modeled_water_provenance": "test",
        }
    )
    targets = pd.DataFrame({"year": [2019, 2020], "water_withdrawal_m3_reported": [1000.0, 1000.0]})
    d = aggregate_direct_groundwater(direct, registry, months=pd.Series(months))
    c = aggregate_city_production(city, tier="accepted", volume_name="owrd_city_production_m3")
    cand = aggregate_city_production(
        candidate, tier="candidate", volume_name="owrd_city_candidate_production_m3"
    )
    joined = join_monthly_validation(modeled, d, c, cand, targets)
    annual = annual_validation(joined, None)

    dec = joined.loc[joined.calendar_month.eq("2019-12-01")].iloc[0]
    jan = joined.loc[joined.calendar_month.eq("2020-01-01")].iloc[0]
    feb = joined.loc[joined.calendar_month.eq("2020-02-01")].iloc[0]
    mar = joined.loc[joined.calendar_month.eq("2020-03-01")].iloc[0]
    assert dec.owrd_meta_direct_expected_report_count == 2
    assert "64500" in str(dec.owrd_meta_direct_not_yet_applicable_ids)
    assert dec.validation_flag != "partial_owrd_coverage"
    assert jan.owrd_meta_direct_groundwater_m3 == 16.0
    assert jan.owrd_meta_direct_expected_report_count == 3
    assert pd.isna(feb.owrd_meta_direct_groundwater_m3), "missing OWRD must not become zero"
    assert mar.owrd_meta_direct_groundwater_m3 == 0.0
    assert jan.owrd_city_production_m3 == 150.0
    assert "Flowmeter" in str(jan.owrd_city_measurement_method)
    assert jan.owrd_city_production_m3 != jan.owrd_city_candidate_production_m3
    assert jan.validation_flag == "review_boundary"  # 16 > 12 modeled
    assert feb.validation_flag == "missing_owrd"
    assert mar.validation_flag == "no_diagnostic_trigger"
    assert "measured OWRD" not in jan.owrd_meta_direct_provenance
    assert jan.owrd_meta_direct_provenance.startswith("reported OWRD")
    assert pd.isna(feb.direct_pod_to_modeled_ratio)
    assert joined.calendar_month.is_unique
    a2020 = annual.loc[annual.calendar_year.eq(2020)].iloc[0]
    assert a2020.direct_annual_complete is False or a2020.direct_annual_complete == False
    assert pd.isna(a2020.direct_pod_to_modeled_ratio)
    a2019 = annual.loc[annual.calendar_year.eq(2019)].iloc[0]
    assert bool(a2019.direct_annual_complete)
    print("PASS: owrd_water_model_validation self-test")


def build(*, rebuild_hourly: bool = True) -> tuple[pd.DataFrame, pd.DataFrame, dict, list[dict]]:
    if not CITY_ACCEPTED.exists() or not DIRECT_MONTHLY.exists():
        raise FileNotFoundError(
            "Processed OWRD files are missing. Run: python run_prineville.py water"
        )
    registry = load_direct_registry()
    targets = pd.read_csv(TARGETS)
    hourly = rebuild_hourly_reconstruction() if rebuild_hourly else load_existing_hourly()
    modeled = modeled_monthly_campus_withdrawal(hourly)
    direct_raw = pd.read_csv(DIRECT_MONTHLY)
    city_raw = pd.read_csv(CITY_ACCEPTED)
    candidate_raw = pd.read_csv(CITY_CANDIDATE) if CITY_CANDIDATE.exists() else pd.DataFrame()
    report_use = pd.read_csv(CITY_REPORT) if CITY_REPORT.exists() else pd.DataFrame()
    direct = aggregate_direct_groundwater(direct_raw, registry, months=modeled["calendar_month"])
    city = aggregate_city_production(
        city_raw, tier="accepted", volume_name="owrd_city_production_m3", report_use=report_use
    )
    candidate = (
        aggregate_city_production(candidate_raw, tier="candidate", volume_name="owrd_city_candidate_production_m3")
        if len(candidate_raw)
        else pd.DataFrame()
    )
    monthly = join_monthly_validation(modeled, direct, city, candidate, targets)
    annual_compare = pd.read_csv(ANNUAL_COMPARE) if ANNUAL_COMPARE.exists() else None
    annual = annual_validation(monthly, annual_compare)
    checks = run_checks(monthly, annual, hourly, targets, city_raw, candidate_raw, registry)
    diagnostics = coverage_diagnostics(monthly, modeled, direct, city)
    return monthly, annual, diagnostics, checks


def main() -> dict:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="Run synthetic assertions only.")
    parser.add_argument("--skip-plot", action="store_true")
    parser.add_argument(
        "--reuse-hourly",
        action="store_true",
        help="Load existing hourly reconstruction instead of rebuilding. Default is rebuild.",
    )
    args = parser.parse_args()
    self_test()
    if args.self_test:
        return {"self_test": "PASS"}

    monthly, annual, diagnostics, checks = build(rebuild_hourly=not args.reuse_hourly)
    OUT_MONTHLY.parent.mkdir(parents=True, exist_ok=True)
    monthly.to_csv(OUT_MONTHLY, index=False)
    annual.to_csv(OUT_ANNUAL, index=False)
    pd.DataFrame(checks).to_csv(OUT_CHECKS, index=False)
    if not args.skip_plot:
        plot_validation(monthly, OUT_FIG)

    summary = {
        "purpose": "OWRD external water-model validation / consistency layer; not calibration",
        "outputs": [str(p.relative_to(ROOT)) for p in [OUT_MONTHLY, OUT_ANNUAL, OUT_CHECKS, OUT_FIG] if p.exists()],
        "diagnostics": diagnostics,
        "checks_passed": int(sum(c["status"] == "PASS" for c in checks)),
        "accounting_rule": BOUNDARY_NOTE,
        "hourly_rebuild": not args.reuse_hourly,
    }
    print(json.dumps(summary, indent=2))
    print("\nValidation flag counts:")
    print(monthly["validation_flag"].value_counts().to_string())
    print("\nAnnual descriptive comparison:")
    cols = [
        "calendar_year",
        "modeled_campus_withdrawal_m3",
        "owrd_meta_direct_groundwater_m3",
        "owrd_city_production_m3",
        "meta_annual_reported_withdrawal_m3",
        "direct_coverage_fraction",
        "direct_annual_complete",
        "direct_pod_to_modeled_ratio",
        "n_review_boundary_months",
    ]
    print(annual[cols].to_string(index=False))
    return summary


if __name__ == "__main__":
    main()
