"""Source-aware Prineville water context: OWRD + USGS HUC12 + weather + Meta annual.

Does not sum or equate series with different accounting boundaries. Does not
infer missing HUC12s, interpolate USGS past 2020, or estimate monthly Meta water.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from usgs_nwaa_config import (
    MUNICIPAL_CROSSWALK,
    PROCESSED as USGS_PROCESSED,
    QC_DIR,
    SITE_HUC12,
    pad_huc12,
)

ROOT = Path(__file__).resolve().parents[1]
OWRD = ROOT / "data" / "processed" / "owrd"
WATER = ROOT / "data" / "processed" / "water"
CITY_ACCEPTED = OWRD / "owrd_city_monthly_model_use.csv"
CITY_CANDIDATE = OWRD / "owrd_city_monthly_candidate_use.csv"
CITY_REPORT = OWRD / "owrd_city_monthly_report_use.csv"
DIRECT_MONTHLY = OWRD / "owrd_meta_direct_monthly_use.csv"
META_ANNUAL = ROOT / "data" / "canonical" / "meta_prineville_annual.csv"
WEATHER = ROOT / "data" / "processed" / "weather_hourly.csv"
SOURCE_OUT = WATER / "water_source_monthly_context.csv"
MONTH_OUT = WATER / "prineville_water_monthly_context.csv"
QA_OUT = QC_DIR / "water_context_qa.csv"

IWA_START, IWA_END = "2009-10", "2020-09"
PSCU_START, PSCU_END = "2009-01", "2020-12"
WD_START, WD_END = "2000-01", "2020-12"

USGS_VALUE_COLS = [
    "public_supply_consumption_mgd",
    "public_supply_consumption_m3_month",
    "public_supply_withdrawal_total_mgd",
    "public_supply_withdrawal_total_m3_month",
    "public_supply_withdrawal_groundwater_mgd",
    "public_supply_withdrawal_groundwater_m3_month",
    "public_supply_withdrawal_surface_water_mgd",
    "public_supply_withdrawal_surface_water_m3_month",
    "irrigation_withdrawal_mgd",
    "irrigation_withdrawal_m3_month",
    "irrigation_consumption_mgd",
    "irrigation_consumption_m3_month",
    "iwa_cumulative_streamflow_mm_month",
    "iwa_cumulative_streamflow_m3_month",
    "iwa_surface_water_availability_mm_month",
    "iwa_surface_water_availability_m3_month",
    "iwa_cumulative_consumption_mm_month",
    "iwa_cumulative_consumption_m3_month",
    "iwa_sui",
]

BOUNDARY_CITY = "city_municipal_production"
BOUNDARY_CANDIDATE = "city_municipal_candidate_sensitivity"
BOUNDARY_DIRECT = "vitesse_facebook_direct_pod"

CITY_PROVENANCE = (
    "reported OWRD water-use record (may be measured or estimated); "
    "City municipal POD production; not Meta campus delivery"
)
DIRECT_PROVENANCE = (
    "reported OWRD water-use record (may be measured or estimated); "
    "Vitesse/Facebook direct groundwater POD; not total Meta withdrawal"
)
USGS_PROVENANCE = (
    "USGS NWAA modeled HUC12 context; not a campus or POD meter; "
    "IWA consum is cumulative upstream+local"
)
META_PROVENANCE = (
    "Meta-reported annual campus withdrawal copied onto calendar months; "
    "not a monthly measurement"
)
WEATHER_PROVENANCE = (
    "KRDM/Roberts Field NOAA hourly aggregated to calendar month; "
    "nearby station, not on-campus"
)


def _month_start(series) -> pd.Series:
    return pd.to_datetime(series).dt.to_period("M").dt.to_timestamp()


def _year_month(series) -> pd.Series:
    return _month_start(series).dt.strftime("%Y-%m")


def _truthy(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def load_usgs_huc12_monthly() -> pd.DataFrame:
    iwa = pd.read_csv(
        USGS_PROCESSED / "usgs_iwa_huc12_monthly_same_site_huc8.csv",
        dtype={"huc12_id": str},
    )
    pscu = pd.read_csv(
        USGS_PROCESSED / "usgs_public_supply_cu_huc12_monthly_same_site_huc8.csv",
        dtype={"huc12_id": str},
    )
    pswd = pd.read_csv(
        USGS_PROCESSED / "usgs_public_supply_wd_huc12_monthly_same_site_huc8.csv",
        dtype={"huc12_id": str},
    )
    irr = pd.read_csv(
        USGS_PROCESSED / "usgs_irrigation_huc12_monthly_same_site_huc8.csv",
        dtype={"huc12_id": str},
    )
    for df in (iwa, pscu, pswd, irr):
        df["huc12_id"] = df["huc12_id"].map(pad_huc12)
        df["year_month"] = df["year_month"].astype(str)

    keys = ["huc12_id", "year_month"]
    out = iwa[keys + [c for c in USGS_VALUE_COLS if c in iwa.columns]]
    for extra in (pscu, pswd, irr):
        cols = [c for c in USGS_VALUE_COLS if c in extra.columns]
        out = out.merge(extra[keys + cols], on=keys, how="outer", validate="one_to_one")
    return out


def verified_huc12_lookup() -> pd.DataFrame:
    xw = pd.read_csv(MUNICIPAL_CROSSWALK, dtype=str)
    xw["source_id"] = xw["source_id"].astype(str).str.strip()
    xw["huc12_id"] = xw["huc12_id"].map(pad_huc12)
    verified = (
        xw["huc12_id"].fillna("").ne("")
        & xw["huc12_id"].str.len().eq(12)
        & xw["confidence"].eq("coordinate_wbd_intersect")
        & xw["in_study_geography"].map(_truthy)
    )
    keep = xw.loc[:, ["source_id", "huc12_id", "huc12_name", "confidence", "match_method"]].copy()
    keep["huc12_verified_in_study"] = verified
    keep.loc[~verified, ["huc12_id", "huc12_name"]] = ""
    return keep


def group_huc12(source_ids: str, lookup: pd.DataFrame) -> dict:
    ids = [x.strip() for x in str(source_ids or "").replace(",", ";").split(";") if x.strip()]
    if not ids:
        return {
            "huc12_id": "",
            "huc12_name": "",
            "huc12_match_status": "unresolved_missing_coordinates",
            "huc12_match_confidence": "",
        }
    rows = lookup.loc[lookup["source_id"].isin(ids)]
    if len(rows) < len(ids):
        missing = [i for i in ids if i not in set(rows["source_id"])]
        if missing:
            return {
                "huc12_id": "",
                "huc12_name": "",
                "huc12_match_status": "unresolved_missing_coordinates",
                "huc12_match_confidence": "",
            }
    if not bool(rows["huc12_verified_in_study"].all()):
        if bool(rows["huc12_verified_in_study"].any()):
            status = "mixed_verified_and_unresolved"
        elif (rows["confidence"] == "out_of_study_geography").any():
            status = "out_of_study_geography"
        else:
            status = "unresolved_missing_coordinates"
        return {
            "huc12_id": "",
            "huc12_name": "",
            "huc12_match_status": status,
            "huc12_match_confidence": ";".join(rows["confidence"].fillna("")),
        }
    hucs = sorted(set(rows["huc12_id"]))
    if len(hucs) != 1:
        return {
            "huc12_id": "",
            "huc12_name": "",
            "huc12_match_status": "mixed_verified_huc12",
            "huc12_match_confidence": ";".join(rows["confidence"].fillna("")),
        }
    return {
        "huc12_id": hucs[0],
        "huc12_name": rows["huc12_name"].iloc[0],
        "huc12_match_status": "verified_in_study",
        "huc12_match_confidence": rows["confidence"].iloc[0],
    }


def city_measurement_methods(city: pd.DataFrame, report: pd.DataFrame) -> pd.Series:
    if "measurement_method" not in report.columns:
        return pd.Series("", index=city.index)
    rep = report.copy()
    rep["calendar_month"] = _month_start(rep["calendar_month"])
    methods = (
        rep.groupby(["report_id", "calendar_month"])["measurement_method"]
        .agg(lambda s: ";".join(sorted({str(x).strip() for x in s.dropna() if str(x).strip()})))
        .to_dict()
    )
    out = []
    for _, row in city.iterrows():
        month = row["calendar_month"]
        found = []
        for token in str(row.get("report_ids") or "").replace(",", ";").split(";"):
            token = token.strip()
            if not token:
                continue
            try:
                rid = int(float(token))
            except ValueError:
                continue
            text = methods.get((rid, month), "")
            if text:
                found.append(text)
        out.append(";".join(sorted(set(found))))
    return pd.Series(out, index=city.index)


def monthly_weather() -> pd.DataFrame:
    if not WEATHER.exists():
        return pd.DataFrame()
    w = pd.read_csv(WEATHER, usecols=["timestamp_utc", "t_db_C", "t_wb_C", "rh_pct", "precip_mm"])
    w["calendar_month"] = _month_start(w["timestamp_utc"])
    out = w.groupby("calendar_month", as_index=False).agg(
        weather_t_db_C_mean=("t_db_C", "mean"),
        weather_t_wb_C_mean=("t_wb_C", "mean"),
        weather_rh_pct_mean=("rh_pct", "mean"),
        weather_precip_mm_sum=("precip_mm", "sum"),
        weather_n_hours=("timestamp_utc", "size"),
    )
    out["weather_station"] = "KRDM_72692024230"
    out["weather_provenance"] = WEATHER_PROVENANCE
    return out


def apply_usgs_period_mask(df: pd.DataFrame) -> pd.DataFrame:
    ym = df["year_month"].astype(str)
    iwa_ok = ym.between(IWA_START, IWA_END)
    pscu_ok = ym.between(PSCU_START, PSCU_END)
    wd_ok = ym.between(WD_START, WD_END)
    for col in df.columns:
        if col.startswith("iwa_"):
            df.loc[~iwa_ok, col] = pd.NA
        elif col.startswith("public_supply_consumption_"):
            df.loc[~pscu_ok, col] = pd.NA
        elif col.startswith("public_supply_withdrawal_") or col.startswith("irrigation_"):
            df.loc[~wd_ok, col] = pd.NA
    df["usgs_iwa_in_period"] = iwa_ok
    df["usgs_public_supply_cu_in_period"] = pscu_ok
    df["usgs_withdrawal_irrigation_in_period"] = wd_ok
    return df


def attach_usgs(df: pd.DataFrame, usgs: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["year_month"] = _year_month(df["calendar_month"])
    df["huc12_id"] = df["huc12_id"].map(lambda x: pad_huc12(x) if pd.notna(x) and str(x).strip() else "")
    matched = df["huc12_id"].str.len() == 12
    left = df.loc[matched].merge(
        usgs,
        on=["huc12_id", "year_month"],
        how="left",
        validate="many_to_one",
    )
    unmatched = df.loc[~matched].copy()
    for col in USGS_VALUE_COLS:
        if col not in unmatched.columns:
            unmatched[col] = pd.NA
    out = pd.concat([left, unmatched], ignore_index=True)
    out = apply_usgs_period_mask(out)
    out["usgs_join_applied"] = out.get(
        "huc12_match_status", pd.Series("", index=out.index)
    ).eq("verified_in_study")
    out.loc[~out["usgs_join_applied"], USGS_VALUE_COLS] = pd.NA
    return out


def build_source_table(usgs: pd.DataFrame, lookup: pd.DataFrame, report: pd.DataFrame) -> pd.DataFrame:
    city = pd.read_csv(CITY_ACCEPTED)
    cand = pd.read_csv(CITY_CANDIDATE)
    direct = pd.read_csv(DIRECT_MONTHLY)

    frames = []
    for table, boundary, primary in (
        (city, BOUNDARY_CITY, True),
        (cand, BOUNDARY_CANDIDATE, False),
    ):
        t = table.copy()
        t["calendar_month"] = _month_start(t["calendar_month"])
        t["accounting_boundary"] = boundary
        t["in_primary_city_total"] = primary
        t["source_or_group_id"] = t["model_source_key"]
        t["physical_source_ids"] = t["canonical_source_ids"]
        t["source_names"] = t["canonical_source_names"]
        t["owrd_volume_m3"] = t["volume_m3"]
        t["owrd_volume_af"] = t["volume_af"]
        t["reporting_status"] = t["reported_flag"].map(
            lambda x: "reported" if bool(x) else "missing"
        )
        t["measurement_method"] = city_measurement_methods(t, report)
        t["provenance"] = CITY_PROVENANCE
        huc_info = t["canonical_source_ids"].map(lambda s: group_huc12(s, lookup))
        t = pd.concat([t.reset_index(drop=True), pd.DataFrame(list(huc_info))], axis=1)
        frames.append(t)

    d = direct.copy()
    d["calendar_month"] = _month_start(d["calendar_month"])
    d["accounting_boundary"] = BOUNDARY_DIRECT
    d["in_primary_city_total"] = False
    d["source_or_group_id"] = "DIRECT_POD:" + d["report_id"].astype(str)
    d["physical_source_ids"] = d["source_id"].astype(str)
    d["source_names"] = d["canonical_name"]
    d["owrd_volume_m3"] = d["volume_m3"]
    d["owrd_volume_af"] = d["volume_af"]
    d["mapping_tier"] = "direct_pod"
    d["mapping_confidence"] = d["confidence"]
    d["report_ids"] = d["report_id"].astype(str)
    d["reporting_status"] = d["reported_flag"].map(
        lambda x: "reported" if bool(x) else "missing"
    )
    d["provenance"] = DIRECT_PROVENANCE
    d["huc12_id"] = ""
    d["huc12_name"] = ""
    d["huc12_match_status"] = "no_official_coordinates_do_not_infer"
    d["huc12_match_confidence"] = ""
    frames.append(d)

    keep = [
        "accounting_boundary",
        "in_primary_city_total",
        "source_or_group_id",
        "physical_source_ids",
        "source_names",
        "calendar_month",
        "calendar_year",
        "owrd_volume_m3",
        "owrd_volume_af",
        "reported_flag",
        "zero_reported_flag",
        "reporting_status",
        "mapping_tier",
        "mapping_confidence",
        "report_ids",
        "measurement_method",
        "huc12_id",
        "huc12_name",
        "huc12_match_status",
        "huc12_match_confidence",
        "provenance",
    ]
    src = pd.concat(frames, ignore_index=True, sort=False)
    src = src[[c for c in keep if c in src.columns]]
    src = attach_usgs(src, usgs)
    src["usgs_provenance"] = USGS_PROVENANCE
    src["never_sum_across_boundaries"] = True
    return src.sort_values(
        ["accounting_boundary", "source_or_group_id", "calendar_month"]
    ).reset_index(drop=True)


def build_month_table(source: pd.DataFrame, usgs: pd.DataFrame) -> pd.DataFrame:
    accepted = source.loc[source["accounting_boundary"] == BOUNDARY_CITY].copy()
    direct = source.loc[source["accounting_boundary"] == BOUNDARY_DIRECT].copy()
    weather = monthly_weather()
    meta = pd.read_csv(META_ANNUAL)

    months = sorted(
        set(accepted["calendar_month"].dropna())
        | set(direct["calendar_month"].dropna())
        | set(weather["calendar_month"].dropna() if not weather.empty else [])
    )
    spine = pd.DataFrame({"calendar_month": pd.to_datetime(months)})
    spine["calendar_year"] = spine["calendar_month"].dt.year
    spine["year_month"] = spine["calendar_month"].dt.strftime("%Y-%m")
    spine["month"] = spine["calendar_month"].dt.month

    city_m = (
        accepted.groupby("calendar_month", as_index=False)
        .agg(
            city_municipal_production_m3=("owrd_volume_m3", lambda s: s.sum(min_count=1)),
            city_n_source_groups=("source_or_group_id", "nunique"),
            city_n_reported=("reported_flag", lambda s: int(s.fillna(False).sum())),
            city_n_zero=("zero_reported_flag", lambda s: int(s.fillna(False).sum())),
            city_report_ids=("report_ids", lambda s: ";".join(sorted({x for x in s.dropna().astype(str) if x}))),
        )
    )
    city_m["city_accounting_boundary"] = BOUNDARY_CITY
    city_m["city_provenance"] = CITY_PROVENANCE

    dir_m = (
        direct.groupby("calendar_month", as_index=False)
        .agg(
            vitesse_facebook_direct_pod_m3=("owrd_volume_m3", lambda s: s.sum(min_count=1)),
            vitesse_facebook_n_reports=("source_or_group_id", "nunique"),
            vitesse_facebook_n_reported=("reported_flag", lambda s: int(s.fillna(False).sum())),
            vitesse_facebook_n_zero=("zero_reported_flag", lambda s: int(s.fillna(False).sum())),
            vitesse_facebook_report_ids=("report_ids", lambda s: ";".join(sorted({x for x in s.dropna().astype(str) if x}))),
        )
    )
    dir_m["vitesse_facebook_accounting_boundary"] = BOUNDARY_DIRECT
    dir_m["vitesse_facebook_provenance"] = DIRECT_PROVENANCE

    out = spine.merge(city_m, on="calendar_month", how="left")
    out = out.merge(dir_m, on="calendar_month", how="left")
    if not weather.empty:
        out = out.merge(weather, on="calendar_month", how="left")

    meta["year"] = pd.to_numeric(meta["year"], errors="coerce")
    meta_keep = meta.rename(
        columns={
            "water_withdrawal_m3_reported": "meta_campus_withdrawal_m3_annual_reported",
            "water_status": "meta_campus_water_status",
            "water_source_id": "meta_campus_water_source_id",
        }
    )[
        [
            "year",
            "meta_campus_withdrawal_m3_annual_reported",
            "meta_campus_water_status",
            "meta_campus_water_source_id",
        ]
    ]
    out = out.merge(meta_keep, left_on="calendar_year", right_on="year", how="left")
    out = out.drop(columns=["year"])
    out["meta_campus_water_resolution"] = "annual_reported_not_monthly"
    out["meta_campus_water_is_monthly_measurement"] = False
    out["meta_campus_water_provenance"] = META_PROVENANCE

    site = usgs.loc[usgs["huc12_id"] == SITE_HUC12].copy()
    site = apply_usgs_period_mask(site)
    site = site.rename(
        columns={c: f"site_huc12_{c}" for c in USGS_VALUE_COLS if c in site.columns}
    )
    site_cols = ["year_month"] + [c for c in site.columns if c.startswith("site_huc12_")]
    site_cols += [
        c
        for c in [
            "usgs_iwa_in_period",
            "usgs_public_supply_cu_in_period",
            "usgs_withdrawal_irrigation_in_period",
        ]
        if c in site.columns
    ]
    out = out.merge(site[site_cols], on="year_month", how="left", validate="many_to_one")
    out["site_huc12_id"] = SITE_HUC12
    out["site_huc12_designation"] = "site_point_huc12"

    out["usgs_provenance"] = USGS_PROVENANCE
    out["do_not_sum_or_equate_series"] = True
    out["city_production_is_not_meta_delivery"] = True
    out["direct_pod_is_not_total_meta_withdrawal"] = True
    out["usgs_is_not_campus_meter"] = True
    return out.sort_values("calendar_month").reset_index(drop=True)


def qa(source: pd.DataFrame, month: pd.DataFrame) -> pd.DataFrame:
    accepted_src = pd.read_csv(CITY_ACCEPTED)
    accepted_src["calendar_month"] = _month_start(accepted_src["calendar_month"])
    cand_src = pd.read_csv(CITY_CANDIDATE)
    direct_src = pd.read_csv(DIRECT_MONTHLY)
    direct_src["calendar_month"] = _month_start(direct_src["calendar_month"])

    checks = []

    def add(name, passed, detail=""):
        checks.append({"check": name, "status": "PASS" if passed else "FAIL", "detail": detail})

    src_key = source.duplicated(
        ["accounting_boundary", "source_or_group_id", "calendar_month"]
    )
    add("no_duplicate_source_month", not bool(src_key.any()), f"n={int(src_key.sum())}")
    add("no_duplicate_calendar_month", not bool(month.duplicated("calendar_month").any()))

    before_city = accepted_src["volume_m3"].sum(min_count=1)
    after_city = source.loc[
        source["accounting_boundary"] == BOUNDARY_CITY, "owrd_volume_m3"
    ].sum(min_count=1)
    add(
        "city_owrd_totals_unchanged",
        pd.notna(before_city) and abs(before_city - after_city) < 1e-6,
        f"before={before_city} after={after_city}",
    )
    before_direct = direct_src["volume_m3"].sum(min_count=1)
    after_direct = source.loc[
        source["accounting_boundary"] == BOUNDARY_DIRECT, "owrd_volume_m3"
    ].sum(min_count=1)
    add(
        "direct_owrd_totals_unchanged",
        pd.notna(before_direct) and abs(before_direct - after_direct) < 1e-6,
        f"before={before_direct} after={after_direct}",
    )

    city_month_sum = month["city_municipal_production_m3"].sum(min_count=1)
    add(
        "month_city_equals_source_accepted",
        pd.notna(city_month_sum) and abs(city_month_sum - after_city) < 1e-6,
        f"month={city_month_sum} source={after_city}",
    )

    cand_in_primary = source.loc[
        source["accounting_boundary"] == BOUNDARY_CANDIDATE, "in_primary_city_total"
    ]
    add("candidates_excluded_from_primary", not bool(cand_in_primary.fillna(False).any()))

    # zero vs missing
    city_src = source.loc[source["accounting_boundary"] == BOUNDARY_CITY]
    zero_ok = (
        city_src.loc[city_src["zero_reported_flag"].fillna(False), "owrd_volume_m3"] == 0
    ).all() if city_src["zero_reported_flag"].fillna(False).any() else True
    missing_not_zero = (
        ~city_src.loc[~city_src["reported_flag"].fillna(False), "owrd_volume_m3"].fillna(-1).eq(0)
    ).all() if (~city_src["reported_flag"].fillna(False)).any() else True
    add("reported_zero_distinct_from_missing", bool(zero_ok and missing_not_zero))

    hucs = source["huc12_id"].fillna("")
    assigned = hucs != ""
    add(
        "huc12_12_char_when_assigned",
        bool((~assigned | (hucs.map(pad_huc12).str.len() == 12)).all()),
    )

    ym = month["year_month"].astype(str)
    iwa_cols = [c for c in month.columns if c.startswith("site_huc12_iwa_")]
    if iwa_cols:
        late = month.loc[~ym.between(IWA_START, IWA_END), iwa_cols]
        add("usgs_iwa_missing_outside_period", bool(late.isna().all().all()), f"n_months={len(late)}")
    wd_cols = [
        c
        for c in month.columns
        if c.startswith("site_huc12_public_supply_withdrawal_") or c.startswith("site_huc12_irrigation_")
    ]
    if wd_cols:
        late = month.loc[~ym.between(WD_START, WD_END), wd_cols]
        add("usgs_wd_missing_outside_period", bool(late.isna().all().all()), f"n_months={len(late)}")

    add(
        "meta_labeled_annual_not_monthly",
        bool((month["meta_campus_water_is_monthly_measurement"] == False).all())
        and bool((month["meta_campus_water_resolution"] == "annual_reported_not_monthly").all()),
    )
    add(
        "accounting_boundary_labels_present",
        bool(source["accounting_boundary"].notna().all())
        and "city_accounting_boundary" in month.columns
        and "vitesse_facebook_accounting_boundary" in month.columns,
    )
    add("do_not_sum_flag_present", bool(month["do_not_sum_or_equate_series"].all()))

    n_join = int(source["usgs_join_applied"].fillna(False).sum()) if "usgs_join_applied" in source.columns else 0
    n_src = len(source)
    expected_n = len(accepted_src) + len(cand_src) + len(direct_src)
    add(
        "usgs_join_did_not_explode_rows",
        n_src == expected_n,
        f"n_source={n_src} expected={expected_n} usgs_joined_rows={n_join}",
    )

    out = pd.DataFrame(checks)
    failed = out.loc[out["status"] == "FAIL"]
    if len(failed):
        raise RuntimeError("water context QA failed:\n" + failed.to_string(index=False))
    return out


def main() -> None:
    WATER.mkdir(parents=True, exist_ok=True)
    QC_DIR.mkdir(parents=True, exist_ok=True)
    Path(ROOT / "data" / "raw" / "city").mkdir(parents=True, exist_ok=True)

    usgs = load_usgs_huc12_monthly()
    lookup = verified_huc12_lookup()
    report = pd.read_csv(CITY_REPORT)
    report["calendar_month"] = _month_start(report["calendar_month"])

    source = build_source_table(usgs, lookup, report)
    month = build_month_table(source, usgs)
    checks = qa(source, month)

    source.to_csv(SOURCE_OUT, index=False)
    month.to_csv(MONTH_OUT, index=False)
    checks.to_csv(QA_OUT, index=False)
    print("Wrote", SOURCE_OUT, source.shape)
    print(
        "source coverage",
        source["calendar_month"].min(),
        "to",
        source["calendar_month"].max(),
    )
    print("Wrote", MONTH_OUT, month.shape)
    print("month coverage", month["year_month"].min(), "to", month["year_month"].max())
    print("Wrote", QA_OUT)
    print(checks.to_string(index=False))


if __name__ == "__main__":
    main()
