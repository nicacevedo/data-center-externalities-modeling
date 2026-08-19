"""Strict QA for USGS NWAA HUC12 downloads and processed panels.

Failures are written explicitly. HUC12s and months are never dropped here.
"""
from __future__ import annotations

import calendar
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from usgs_nwaa_config import (
    IWA_MM_COLUMNS,
    M3_PER_MILLION_US_GALLONS,
    MM_OVER_KM2_TO_M3,
    MUNICIPAL_CROSSWALK,
    PROCESSED,
    QC_DIR,
    SCOPES,
    SERIES,
    SITE_HUC12,
    STUDY_HUCS,
    huc12_raw_dir,
    pad_huc12,
)

IWA_ATOL = 1e-8
MGD_SUM_ATOL = 1e-6
M3_RTOL = 1e-9
M3_ATOL = 1e-6


def load_geo() -> pd.DataFrame:
    geo = pd.read_csv(STUDY_HUCS, dtype=str)
    geo["huc12"] = geo["huc12"].map(pad_huc12)
    for col in SCOPES:
        geo[col] = pd.to_numeric(geo[col], errors="coerce").fillna(0).astype(int)
    geo["areasqkm"] = pd.to_numeric(geo["areasqkm"], errors="coerce")
    return geo


def expected_n_months(start: str, end: str) -> int:
    return len(pd.period_range(start, end, freq="M"))


def audit_raw_scope(geo: pd.DataFrame, scope: str, spec, prefix: str) -> dict:
    wanted = [pad_huc12(h) for h in geo.loc[geo[scope] == 1, "huc12"]]
    folder = huc12_raw_dir(spec.model, spec.variable, scope)
    rows = {
        "dataset": f"{spec.model}/{spec.variable}",
        "scope": scope,
        "n_huc12_requested": len(wanted),
        "n_files_present": 0,
        "n_files_missing": 0,
        "missing_huc12_ids": "",
        "failed_api_requests": "",
        "first_month": None,
        "last_month": None,
        "expected_rows": None,
        "actual_rows": 0,
        "duplicate_huc12_month": 0,
        "missing_value_cells": 0,
        "huc12_not_12_char": 0,
        "unit_native": spec.units,
        "status": "PASS",
        "failures": "",
    }
    missing_files = []
    frames = []
    for huc in wanted:
        path = folder / f"{prefix}_{huc}.csv"
        if not path.exists() or path.stat().st_size <= 50:
            missing_files.append(huc)
            continue
        df = pd.read_csv(path, dtype={"huc12_id": str})
        df["huc12_id"] = df["huc12_id"].map(pad_huc12)
        frames.append(df)
    rows["n_files_present"] = len(wanted) - len(missing_files)
    rows["n_files_missing"] = len(missing_files)
    rows["missing_huc12_ids"] = ";".join(missing_files)
    failures = []
    if missing_files:
        failures.append(f"missing_files:{len(missing_files)}")
        rows["status"] = "FAIL"
    if not frames:
        rows["failures"] = ";".join(failures) if failures else "no_data"
        rows["status"] = "FAIL"
        return rows
    all_df = pd.concat(frames, ignore_index=True)
    rows["actual_rows"] = int(len(all_df))
    rows["first_month"] = str(all_df["year_month"].min())
    rows["last_month"] = str(all_df["year_month"].max())
    n_months = expected_n_months(spec.startdate, spec.enddate)
    rows["expected_rows"] = len(wanted) * n_months
    if rows["first_month"] != spec.startdate or rows["last_month"] != spec.enddate:
        failures.append(
            f"period:{rows['first_month']}/{rows['last_month']}"
            f"!={spec.startdate}/{spec.enddate}"
        )
    if rows["actual_rows"] != rows["expected_rows"]:
        failures.append(
            f"rowcount:{rows['actual_rows']}!={rows['expected_rows']}"
        )
    dup = int(all_df.duplicated(["huc12_id", "year_month"]).sum())
    rows["duplicate_huc12_month"] = dup
    if dup:
        failures.append(f"duplicates:{dup}")
    bad_id = int((all_df["huc12_id"].str.len() != 12).sum())
    rows["huc12_not_12_char"] = bad_id
    if bad_id:
        failures.append(f"huc12_id_len:{bad_id}")
    value_cols = [c for c in all_df.columns if c not in {"huc12_id", "year_month"}]
    rows["missing_value_cells"] = int(all_df[value_cols].isna().sum().sum())
    if rows["actual_rows"] != rows["expected_rows"] or missing_files or dup or bad_id:
        rows["status"] = "FAIL"
    rows["failures"] = ";".join(failures)
    return rows


def audit_processed_scope(geo: pd.DataFrame, scope: str) -> list[dict]:
    out = []
    n_huc = int((geo[scope] == 1).sum())
    checks = [
        (
            f"usgs_iwa_huc12_monthly_{scope}.csv",
            SERIES["iwa_all"],
            ["iwa_sui", *IWA_MM_COLUMNS],
        ),
        (
            f"usgs_public_supply_cu_huc12_monthly_{scope}.csv",
            SERIES["pscutot"],
            ["public_supply_consumption_mgd"],
        ),
        (
            f"usgs_public_supply_wd_huc12_monthly_{scope}.csv",
            SERIES["pswdtot"],
            [
                "public_supply_withdrawal_total_mgd",
                "public_supply_withdrawal_groundwater_mgd",
                "public_supply_withdrawal_surface_water_mgd",
            ],
        ),
        (
            f"usgs_irrigation_huc12_monthly_{scope}.csv",
            SERIES["irrwdtot"],
            ["irrigation_withdrawal_mgd", "irrigation_consumption_mgd"],
        ),
        (
            f"usgs_huc12_monthly_overlap_{scope}.csv",
            SERIES["iwa_all"],
            [
                "public_supply_consumption_mgd",
                "public_supply_withdrawal_total_mgd",
                "irrigation_withdrawal_mgd",
                "iwa_sui",
            ],
        ),
    ]
    for fname, spec, required in checks:
        path = PROCESSED / fname
        rec = {
            "dataset": fname,
            "scope": scope,
            "n_huc12_requested": n_huc,
            "status": "PASS",
            "failures": "",
        }
        failures = []
        if not path.exists():
            rec["status"] = "FAIL"
            rec["failures"] = "missing_processed_file"
            out.append(rec)
            continue
        df = pd.read_csv(path, dtype={"huc12_id": str})
        df["huc12_id"] = df["huc12_id"].map(pad_huc12)
        rec["actual_rows"] = int(len(df))
        rec["n_huc12_observed"] = int(df["huc12_id"].nunique())
        rec["first_month"] = str(df["year_month"].min())
        rec["last_month"] = str(df["year_month"].max())
        n_months = expected_n_months(spec.startdate, spec.enddate)
        rec["expected_rows"] = n_huc * n_months
        rec["duplicate_huc12_month"] = int(
            df.duplicated(["huc12_id", "year_month"]).sum()
        )
        rec["huc12_not_12_char"] = int((df["huc12_id"].str.len() != 12).sum())
        rec["missing_huc12_ids"] = ";".join(
            sorted(set(geo.loc[geo[scope] == 1, "huc12"]) - set(df["huc12_id"]))
        )
        for col in required:
            if col not in df.columns:
                failures.append(f"missing_column:{col}")
        if rec["n_huc12_observed"] != n_huc:
            failures.append(
                f"huc_count:{rec['n_huc12_observed']}!={n_huc}"
            )
        if rec["actual_rows"] != rec["expected_rows"]:
            failures.append(
                f"rowcount:{rec['actual_rows']}!={rec['expected_rows']}"
            )
        if rec["duplicate_huc12_month"]:
            failures.append(f"duplicates:{rec['duplicate_huc12_month']}")
        if rec["huc12_not_12_char"]:
            failures.append("huc12_id_not_12_char")
        if rec["missing_huc12_ids"]:
            failures.append("hucs_silently_absent")
        if rec["first_month"] != spec.startdate or rec["last_month"] != spec.enddate:
            failures.append(
                f"period:{rec['first_month']}/{rec['last_month']}"
            )
        # IWA identity
        if "iwa_surface_water_availability_mm_month" in df.columns:
            closure = (
                df["iwa_surface_water_availability_mm_month"]
                - (
                    df["iwa_cumulative_streamflow_mm_month"]
                    - df["iwa_cumulative_consumption_mm_month"]
                )
            ).abs()
            rec["iwa_identity_max_abs_error"] = float(closure.max())
            rec["iwa_identity_n_fail"] = int((closure > IWA_ATOL).sum())
            if rec["iwa_identity_n_fail"]:
                failures.append(
                    f"iwa_identity_fail:{rec['iwa_identity_n_fail']}"
                )
        # public-supply GW+SW vs total
        gw = "public_supply_withdrawal_groundwater_mgd"
        sw = "public_supply_withdrawal_surface_water_mgd"
        tot = "public_supply_withdrawal_total_mgd"
        if all(c in df.columns for c in (gw, sw, tot)):
            delta = (df[gw] + df[sw] - df[tot]).abs()
            rec["pswd_gw_sw_vs_total_max_abs_error"] = float(delta.max())
            rec["pswd_gw_sw_vs_total_n_fail"] = int((delta > MGD_SUM_ATOL).sum())
            if rec["pswd_gw_sw_vs_total_n_fail"]:
                failures.append(
                    f"pswd_sum_fail:{rec['pswd_gw_sw_vs_total_n_fail']}"
                )
        # conversion checks
        if "areasqkm" in df.columns:
            for col in [c for c in df.columns if c.endswith("_mm_month")]:
                m3_col = col.replace("_mm_month", "_m3_month")
                if m3_col not in df.columns:
                    failures.append(f"missing_m3:{m3_col}")
                    continue
                expected = df[col] * df["areasqkm"] * MM_OVER_KM2_TO_M3
                err = (df[m3_col] - expected).abs()
                n_fail = int((err > M3_ATOL).sum())
                rec[f"{m3_col}_n_fail"] = n_fail
                if n_fail:
                    failures.append(f"mm_to_m3_fail:{m3_col}:{n_fail}")
        mgd_cols = [c for c in df.columns if c.endswith("_mgd")]
        for col in mgd_cols:
            m3_col = col.replace("_mgd", "_m3_month")
            if m3_col not in df.columns:
                failures.append(f"missing_m3:{m3_col}")
                continue
            days = [
                calendar.monthrange(int(y), int(m))[1]
                for y, m in zip(df["year"], df["month"])
            ]
            expected = df[col] * pd.Series(days, index=df.index) * (
                M3_PER_MILLION_US_GALLONS
            )
            abs_err = (df[m3_col] - expected).abs()
            denom = expected.mask(expected == 0)
            rel = abs_err / denom
            rel_fail = rel.fillna(0) > M3_RTOL
            n_fail = int(((abs_err > M3_ATOL) & rel_fail).sum())
            n_fail += int(((expected == 0) & (df[m3_col].fillna(0) != 0)).sum())
            rec[f"{m3_col}_n_fail"] = n_fail
            if n_fail:
                failures.append(f"mgd_to_m3_fail:{m3_col}:{n_fail}")
        site_ok = SITE_HUC12 in set(df["huc12_id"]) if scope in {
            "scope_local",
            "scope_hydro_near",
            "same_site_huc10",
            "same_site_huc8",
        } else True
        rec["site_huc12_present"] = bool(site_ok)
        if not site_ok:
            failures.append("site_huc12_missing")
        rec["missing_value_cells"] = int(
            df[[c for c in required if c in df.columns]].isna().sum().sum()
        )
        if failures:
            rec["status"] = "FAIL"
            rec["failures"] = ";".join(failures)
        out.append(rec)
    return out


YANCEY_WELL_3 = "SRC-DC"


def _truthy(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def audit_municipal_crosswalk() -> dict:
    rec = {
        "dataset": "municipal_source_huc12_crosswalk",
        "scope": "pws_00682",
        "status": "PASS",
        "failures": "",
    }
    failures = []
    if not MUNICIPAL_CROSSWALK.exists():
        rec["status"] = "FAIL"
        rec["failures"] = "missing_crosswalk_file"
        return rec
    df = pd.read_csv(MUNICIPAL_CROSSWALK, dtype=str)
    rec["actual_rows"] = int(len(df))
    rec["n_huc12_requested"] = int(len(df))
    if "source_id" not in df.columns:
        rec["status"] = "FAIL"
        rec["failures"] = "missing_source_id"
        return rec
    dup = int(df["source_id"].duplicated().sum())
    rec["duplicate_source_ids"] = dup
    if dup:
        failures.append(f"duplicate_source_ids:{dup}")
    assigned = df["huc12_id"].fillna("").str.strip() != ""
    in_study = df["in_study_geography"].map(_truthy)
    rec["n_assigned_in_study"] = int((assigned & in_study).sum())
    rec["n_out_of_study"] = int((assigned & ~in_study).sum())
    rec["n_assigned_huc12"] = rec["n_assigned_in_study"]
    rec["n_unresolved"] = int((~assigned).sum())
    bad_len = int((assigned & (df["huc12_id"].map(pad_huc12).str.len() != 12)).sum())
    rec["huc12_not_12_char"] = bad_len
    if bad_len:
        failures.append(f"huc12_id_len:{bad_len}")
    unresolved = df.loc[~assigned]
    if unresolved.empty:
        failures.append("unresolved_sources_dropped")
    elif (unresolved["confidence"].fillna("") != "unresolved").any():
        failures.append("unresolved_sources_not_flagged_unresolved")
    yancey = df.loc[df["source_id"] == YANCEY_WELL_3]
    if yancey.empty:
        failures.append("yancey_well_3_missing")
    else:
        row = yancey.iloc[0]
        in_study = _truthy(row.get("in_study_geography"))
        conf = str(row.get("confidence") or "")
        rec["yancey_well_3_confidence"] = conf
        rec["yancey_well_3_in_study_geography"] = in_study
        if in_study or conf == "coordinate_wbd_intersect":
            failures.append("yancey_well_3_silently_accepted")
        if conf != "out_of_study_geography":
            failures.append(f"yancey_well_3_confidence:{conf}")
    if failures:
        rec["status"] = "FAIL"
        rec["failures"] = ";".join(failures)
    return rec


def main() -> None:
    geo = load_geo()
    QC_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    raw_specs = [
        (SERIES["iwa_all"], "hydrology"),
        (SERIES["pscutot"], "pscutot"),
        (SERIES["pswdtot"], "pswdtot"),
        (SERIES["pswdgw"], "pswdgw"),
        (SERIES["pswdsw"], "pswdsw"),
        (SERIES["irrwdtot"], "irrwdtot"),
        (SERIES["irrcutot"], "irrcutot"),
    ]
    for scope in SCOPES:
        for spec, prefix in raw_specs:
            rows.append(audit_raw_scope(geo, scope, spec, prefix))
        rows.extend(audit_processed_scope(geo, scope))
    rows.append(audit_municipal_crosswalk())
    out = pd.DataFrame(rows)
    path = QC_DIR / "usgs_nwaa_qa.csv"
    out.to_csv(path, index=False)
    n_fail = int((out["status"] == "FAIL").sum())
    print(f"Wrote {path}")
    print(f"Checks: {len(out)}  FAIL: {n_fail}  PASS: {len(out) - n_fail}")
    if n_fail:
        cols = [c for c in ["dataset", "scope", "failures"] if c in out.columns]
        print(out.loc[out["status"] == "FAIL", cols].to_string(index=False))


if __name__ == "__main__":
    main()
