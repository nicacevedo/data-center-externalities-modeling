"""External OWRD consistency layer for the reconstructed Meta Prineville water series.

This module does **not** calibrate the water model and does **not** replace Meta-reported
annual campus withdrawal. It joins three separately bounded series by calendar month:

1. modeled campus withdrawal (physics-shaped reconstruction; fitted/proxy, not a meter);
2. OWRD Vitesse/Facebook direct groundwater POD use (facility-adjacent evidence);
3. OWRD City of Prineville accepted municipal production (system context).

Missing OWRD values remain missing. Reported zeros remain zeros. City candidate/conflict
mappings never enter the default City total.
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
DIRECT_MONTHLY = ROOT / "data" / "processed" / "owrd_meta_direct_monthly_use.csv"
HOURLY = ROOT / "outputs" / "hourly_conditional_reconstruction.csv"
ANNUAL_COMPARE = ROOT / "outputs" / "conditional_annual_compare.csv"
OUT_MONTHLY = ROOT / "outputs" / "owrd_water_model_validation.csv"
OUT_ANNUAL = ROOT / "outputs" / "owrd_water_model_validation_annual.csv"
OUT_CHECKS = ROOT / "outputs" / "owrd_water_model_validation_checks.csv"
OUT_FIG = ROOT / "outputs" / "owrd_water_model_validation.png"

REGISTRY_DIRECT_REPORT_IDS = (64500, 64845, 64846)
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


def ensure_hourly_reconstruction() -> pd.DataFrame:
    """Load the existing reconstruction; build it only if the hourly file is absent."""

    if HOURLY.exists():
        hourly = pd.read_csv(HOURLY)
    else:
        if str(SRC) not in sys.path:
            sys.path.insert(0, str(SRC))
        from conditional_reconstruction import reconstruct

        HOURLY.parent.mkdir(parents=True, exist_ok=True)
        hourly, annual, model = reconstruct()
        hourly.to_csv(HOURLY, index=False)
        annual.to_csv(ANNUAL_COMPARE, index=False)
        pd.DataFrame([model]).to_csv(ROOT / "outputs" / "conditional_water_model.csv", index=False)

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


def aggregate_direct_groundwater(direct: pd.DataFrame, registry: pd.DataFrame) -> pd.DataFrame:
    """Sum verified Vitesse/Facebook POD reports without converting blanks to zero."""

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

    rows = []
    expected_n = int(registry["report_id"].nunique())
    expected_ids = ";".join(str(x) for x in sorted(allowed))
    for month, g in d.groupby("calendar_month", dropna=False):
        reported = g[g["reported_flag"].fillna(False)]
        volume = reported["volume_m3"].sum(min_count=1) if len(reported) else np.nan
        if reported.empty:
            volume = np.nan
        n_reported = int(len(reported))
        n_zero = int(reported["zero_reported_flag"].fillna(False).sum()) if len(reported) else 0
        n_positive = int((reported["volume_m3"] > 0).sum()) if len(reported) else 0
        n_missing = expected_n - n_reported
        if n_reported == 0:
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
                "calendar_year": int(pd.Timestamp(month).year),
                "owrd_meta_direct_groundwater_m3": float(volume) if pd.notna(volume) else np.nan,
                "owrd_meta_direct_report_count": n_reported,
                "owrd_meta_direct_expected_report_count": expected_n,
                "owrd_meta_direct_report_ids": _join_ids(reported["report_id"]),
                "owrd_meta_direct_expected_report_ids": expected_ids,
                "owrd_meta_direct_measurement_method": _join_text(g["measurement_method"]),
                "owrd_meta_direct_reporting_status": status,
                "owrd_meta_direct_n_missing_reports": n_missing,
                "owrd_meta_direct_n_zero_reports": n_zero,
                "owrd_meta_direct_n_positive_reports": n_positive,
                "owrd_meta_direct_provenance": (
                    "measured OWRD Vitesse/Facebook direct groundwater POD use; "
                    "separate boundary from Meta campus withdrawal and City production"
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("calendar_month").reset_index(drop=True)


def aggregate_city_production(city: pd.DataFrame, *, tier: str, volume_name: str) -> pd.DataFrame:
    """Aggregate City OWRD groups. Default validation uses accepted mappings only."""

    d = city.copy()
    if "mapping_tier" in d.columns:
        d = d[d["mapping_tier"].fillna("").eq(tier)].copy()
    d["calendar_month"] = _month_start(d["calendar_month"])
    d["calendar_year"] = d["calendar_month"].dt.year
    key = "model_source_key"
    if d.duplicated([key, "calendar_month"]).any():
        raise ValueError(f"Duplicate {key}/calendar_month rows in City {tier} OWRD use.")

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
            row["owrd_city_production_provenance"] = (
                "measured OWRD City accepted municipal POD production; system context only; "
                "not Meta campus meter data; candidate/conflict mappings excluded"
            )
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
        n_exp = int(r.owrd_meta_direct_expected_report_count) if pd.notna(r.owrd_meta_direct_expected_report_count) else 3
        city_status = getattr(r, "owrd_city_reporting_status", "missing")

        direct_missing = n_rep == 0 or not (pd.notna(direct) and np.isfinite(float(direct)))
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
                "No reported Vitesse/Facebook direct POD volume this month; blank was not converted to zero."
            )
        elif n_rep < n_exp or city_status == "partial_missing":
            flag = "partial_owrd_coverage"
            if n_rep < n_exp:
                note_parts.append(
                    f"{n_rep} of {n_exp} registry direct POD reports have reported values."
                )
            if city_status == "partial_missing":
                note_parts.append("Some accepted City source groups are unreported this month.")
        else:
            flag = "ok"
            note_parts.append("Overlapping reconstructed campus water and reported OWRD values.")

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
        "owrd_city_production_provenance",
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
    z["owrd_meta_direct_expected_report_count"] = z["owrd_meta_direct_expected_report_count"].fillna(
        len(REGISTRY_DIRECT_REPORT_IDS)
    ).astype(int)
    z["owrd_meta_direct_n_missing_reports"] = z["owrd_meta_direct_n_missing_reports"].fillna(
        z["owrd_meta_direct_expected_report_count"]
    ).astype(int)
    z["owrd_city_reporting_status"] = z["owrd_city_reporting_status"].fillna("missing")
    z["owrd_meta_direct_reporting_status"] = z["owrd_meta_direct_reporting_status"].fillna("missing")
    z["owrd_meta_direct_expected_report_ids"] = z["owrd_meta_direct_expected_report_ids"].fillna(
        ";".join(str(x) for x in REGISTRY_DIRECT_REPORT_IDS)
    )
    z["owrd_meta_direct_report_ids"] = z["owrd_meta_direct_report_ids"].fillna("")
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
        "owrd_meta_direct_report_ids",
        "owrd_city_reporting_status",
        "validation_flag",
        "validation_note",
        "direct_pod_to_modeled_ratio",
        "modeled_to_city_production_ratio",
        "owrd_meta_direct_expected_report_count",
        "owrd_meta_direct_expected_report_ids",
        "owrd_meta_direct_measurement_method",
        "owrd_meta_direct_reporting_status",
        "owrd_meta_direct_n_missing_reports",
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
                "direct_pod_to_modeled_ratio": _ratio(direct, modeled),
                "modeled_to_city_production_ratio": _ratio(modeled, city),
                "direct_pod_to_meta_reported_ratio": _ratio(direct, reported_val),
                "modeled_to_meta_reported_ratio": _ratio(modeled, reported_val),
                "n_review_boundary_months": int(g["validation_flag"].eq("review_boundary").sum()),
                "n_missing_owrd_months": int(g["validation_flag"].eq("missing_owrd").sum()),
                "n_partial_owrd_months": int(g["validation_flag"].eq("partial_owrd_coverage").sum()),
                "annual_comparison_note": (
                    "Descriptive annual totals. Equality with Meta-reported withdrawal is not "
                    "expected. Direct POD and City production remain separate boundaries. "
                    "OWRD annual sums use reported months only; missing months are not zero-filled."
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
    m = pd.to_datetime(monthly["calendar_month"])
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
        "n_ok": int(monthly["validation_flag"].eq("ok").sum()),
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

    # Known all-missing direct month in the bundled export: 2024-04 through 2024-07.
    missing_month = monthly.loc[monthly["calendar_month"].eq("2024-04-01")]
    if len(missing_month):
        val = missing_month["owrd_meta_direct_groundwater_m3"].iloc[0]
        add(
            "missing_owrd_not_converted_to_zero",
            pd.isna(val),
            f"2024-04 direct volume={val!r}",
        )

    accepted_keys = set(city_raw["model_source_key"].dropna())
    candidate_keys = set(candidate_raw["model_source_key"].dropna()) if len(candidate_raw) else set()
    add("accepted_and_candidate_keys_disjoint", accepted_keys.isdisjoint(candidate_keys), "no silent candidate inclusion")
    if "mapping_tier" in city_raw.columns:
        add("city_default_file_is_accepted_only", set(city_raw["mapping_tier"].unique()) == {"accepted"}, "accepted only")

    # Candidate totals must not equal accepted totals if both exist.
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
    months = pd.to_datetime(["2020-01-01", "2020-02-01", "2020-03-01"])
    direct = pd.DataFrame(
        {
            "report_id": [64500, 64845, 64846] * 3,
            "calendar_month": np.repeat(months, 3),
            "volume_m3": [
                10.0, 5.0, 1.0,   # Jan complete
                np.nan, np.nan, np.nan,  # Feb missing, must stay missing
                0.0, 0.0, 0.0,    # Mar reported zeros
            ],
            "reported_flag": [True, True, True, False, False, False, True, True, True],
            "zero_reported_flag": [False, False, False, False, False, False, True, True, True],
            "measurement_method": ["Flowmeter"] * 9,
        }
    )
    # Duplicate row would double-count if aggregation is wrong.
    city = pd.DataFrame(
        {
            "model_source_key": ["SRC-AA", "SRC-FA", "SRC-AA", "SRC-FA", "SRC-AA", "SRC-FA"],
            "calendar_month": np.repeat(months, 2),
            "volume_m3": [100.0, 50.0, 80.0, np.nan, 0.0, 0.0],
            "reported_flag": [True, True, True, False, True, True],
            "zero_reported_flag": [False, False, False, False, True, True],
            "mapping_tier": ["accepted"] * 6,
            "mapping_confidence": [1.0] * 6,
            "report_ids": ["12037", "26843"] * 3,
        }
    )
    candidate = pd.DataFrame(
        {
            "model_source_key": ["SRC-KC"] * 3,
            "calendar_month": months,
            "volume_m3": [999.0, 999.0, 999.0],
            "reported_flag": [True, True, True],
            "zero_reported_flag": [False, False, False],
            "mapping_tier": ["candidate"] * 3,
            "report_ids": ["67985"] * 3,
        }
    )
    modeled = pd.DataFrame(
        {
            "calendar_month": months,
            "calendar_year": [2020, 2020, 2020],
            "modeled_campus_withdrawal_m3": [12.0, 20.0, 5.0],
            "modeled_hours": [744, 696, 744],
            "modeled_finite_hours": [744, 696, 744],
            "modeled_facility_energy_mwh": [1.0, 1.0, 1.0],
            "modeled_water_provenance": "test",
        }
    )
    targets = pd.DataFrame({"year": [2020], "water_withdrawal_m3_reported": [1000.0]})
    d = aggregate_direct_groundwater(direct, registry)
    c = aggregate_city_production(city, tier="accepted", volume_name="owrd_city_production_m3")
    cand = aggregate_city_production(
        candidate, tier="candidate", volume_name="owrd_city_candidate_production_m3"
    )
    joined = join_monthly_validation(modeled, d, c, cand, targets)

    jan = joined.loc[joined.calendar_month.eq("2020-01-01")].iloc[0]
    feb = joined.loc[joined.calendar_month.eq("2020-02-01")].iloc[0]
    mar = joined.loc[joined.calendar_month.eq("2020-03-01")].iloc[0]
    assert jan.owrd_meta_direct_groundwater_m3 == 16.0
    assert pd.isna(feb.owrd_meta_direct_groundwater_m3), "missing OWRD must not become zero"
    assert mar.owrd_meta_direct_groundwater_m3 == 0.0
    assert jan.owrd_city_production_m3 == 150.0
    assert pd.isna(feb.owrd_city_candidate_production_m3) or feb.owrd_city_candidate_production_m3 == 999.0
    assert jan.owrd_city_production_m3 != jan.owrd_city_candidate_production_m3
    assert jan.validation_flag == "review_boundary"  # 16 > 12 modeled
    assert feb.validation_flag == "missing_owrd"
    assert mar.validation_flag in {"ok", "partial_owrd_coverage", "review_boundary"}
    assert pd.isna(feb.direct_pod_to_modeled_ratio)
    assert joined.calendar_month.is_unique
    print("PASS: owrd_water_model_validation self-test")


def build() -> tuple[pd.DataFrame, pd.DataFrame, dict, list[dict]]:
    if not CITY_ACCEPTED.exists() or not DIRECT_MONTHLY.exists():
        raise FileNotFoundError(
            "Processed OWRD files are missing. Run: python run_prineville.py water"
        )
    registry = load_direct_registry()
    targets = pd.read_csv(TARGETS)
    hourly = ensure_hourly_reconstruction()
    modeled = modeled_monthly_campus_withdrawal(hourly)
    direct_raw = pd.read_csv(DIRECT_MONTHLY)
    city_raw = pd.read_csv(CITY_ACCEPTED)
    candidate_raw = pd.read_csv(CITY_CANDIDATE) if CITY_CANDIDATE.exists() else pd.DataFrame()
    direct = aggregate_direct_groundwater(direct_raw, registry)
    city = aggregate_city_production(city_raw, tier="accepted", volume_name="owrd_city_production_m3")
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
    args = parser.parse_args()
    self_test()
    if args.self_test:
        return {"self_test": "PASS"}

    monthly, annual, diagnostics, checks = build()
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
        "n_months_direct_reported",
        "direct_pod_to_modeled_ratio",
        "n_review_boundary_months",
    ]
    print(annual[cols].to_string(index=False))
    return summary


if __name__ == "__main__":
    main()
