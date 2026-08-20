"""Additive public-data quantities from existing repository artifacts.

Early Meta water envelope (2011-2013), 2011 eGRID location-based Scope 2 proxy,
regional EWIF from EIA-923 cooling, and annual-closed monthly reconstructions
from current pipeline outputs. Does not retune models or acquire new data.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CANON = ROOT / "data" / "canonical"
WATER = ROOT / "data" / "processed" / "water"
ELEC = ROOT / "data" / "processed" / "electricity"
QC = ROOT / "outputs" / "qc"
OUT_GW = ROOT / "outputs" / "groundwater"

META = CANON / "meta_prineville_annual.csv"
DIRECT_ANNUAL = ROOT / "data" / "processed" / "owrd" / "owrd_meta_direct_annual_use.csv"
DIRECT_MONTHLY = ROOT / "data" / "processed" / "owrd" / "owrd_meta_direct_monthly_use.csv"
COND_ANNUAL = ROOT / "outputs" / "conditional_annual_compare.csv"
HOURLY = ROOT / "outputs" / "hourly_conditional_reconstruction.csv"
EGRID_ANNUAL = ROOT / "data" / "processed" / "egrid_prineville_annual.csv"
EGRID_COMPARE = ROOT / "outputs" / "egrid_meta_annual_compare.csv"
COOLING = ROOT / "data" / "processed" / "eia923_cooling_operations.csv"
GEN_FUEL = ROOT / "data" / "processed" / "eia923_generation_fuel_monthly.csv"
FEAS = OUT_GW / "groundwater_model_feasibility.csv"
LEVELS = ROOT / "data" / "processed" / "groundwater" / "groundwater_level_observations.csv"

PUE_DESIGN = 1.07
WUE_DESIGN_L_PER_KWH_IT = 0.31
LB_PER_METRIC_TONNE = 2204.6226218487757
LOCAL_TZ = "America/Los_Angeles"

ENVELOPE_OUT = WATER / "meta_water_early_proxy_envelope.csv"
SCOPE2_PROXY_OUT = ROOT / "data" / "processed" / "egrid_2011_location_based_scope2_proxy.csv"
EWIF_OUT = WATER / "regional_electricity_water_intensity.csv"
EWIF_QA = QC / "regional_electricity_water_qa.csv"
ELEC_MONTHLY_OUT = ELEC / "meta_campus_monthly_electricity_reconstruction.csv"
WATER_MONTHLY_OUT = WATER / "meta_campus_monthly_water_scenarios.csv"
GAP_OUT = ROOT / "outputs" / "data_gap_priority_assessment.csv"

PROXY_PROVENANCE = "eGRID_location_based_accounting_proxy"


def _mkdirs() -> None:
    for p in (WATER, ELEC, QC, ROOT / "data" / "processed"):
        p.mkdir(parents=True, exist_ok=True)


def _close_shape(shape: pd.Series, target: float) -> pd.Series:
    s = pd.to_numeric(shape, errors="coerce").fillna(0.0)
    tot = float(s.sum())
    if tot <= 0 or not np.isfinite(tot) or not np.isfinite(target):
        return pd.Series(np.nan, index=s.index)
    return s * (float(target) / tot)


def allocate_direct_pod_year(monthly_shape: pd.Series, target: float) -> tuple[pd.Series, str]:
    """Annual-close a 12-month POD shape only when every month is observed.

    Missing months stay missing and skip the year. Explicit zeros remain zeros.
    """
    s = pd.to_numeric(monthly_shape, errors="coerce")
    if len(s) != 12 or s.isna().any():
        return pd.Series(np.nan, index=s.index), "skipped_incomplete_direct_pod_shape"
    tot = float(s.sum())
    if tot <= 0 or not np.isfinite(tot) or not np.isfinite(target):
        return (
            pd.Series(np.nan, index=s.index),
            "skipped; calendar-year direct POD total is zero or missing",
        )
    return s * (float(target) / tot), "scenario allocation using OWRD direct-POD monthly shape"


def direct_pod_monthly_calendar(direct: pd.DataFrame) -> pd.DataFrame:
    """Calendar-month POD totals that distinguish reported zero from missing."""
    d = direct.copy()
    d["calendar_month"] = pd.to_datetime(d["calendar_month"], errors="coerce")
    d["year"] = d["calendar_month"].dt.year
    d["month"] = d["calendar_month"].dt.month
    d["reported"] = d["reported_flag"].astype(str).str.lower().eq("true")
    d["volume_m3"] = pd.to_numeric(d["volume_m3"], errors="coerce")
    report_ids = sorted(pd.unique(d["report_id"].dropna()))
    n_expected = len(report_ids)
    rows = []
    years = sorted(d["year"].dropna().astype(int).unique())
    for year in years:
        for month in range(1, 13):
            sub = d[(d["year"] == year) & (d["month"] == month)]
            n_reported = 0
            vols = []
            complete = True
            for rid in report_ids:
                r = sub[sub["report_id"] == rid]
                if r.empty or not bool(r["reported"].iloc[0]):
                    complete = False
                    continue
                n_reported += 1
                vols.append(r["volume_m3"].iloc[0])
            vol = np.nan
            if complete and n_reported == n_expected:
                vol = float(pd.Series(vols).sum(min_count=1)) if vols else np.nan
            else:
                complete = False
            rows.append(
                {
                    "calendar_year": int(year),
                    "month": int(month),
                    "direct_pod_m3": vol,
                    "n_reported": n_reported,
                    "n_expected": n_expected,
                    "month_complete": complete,
                }
            )
    return pd.DataFrame(rows)


def build_early_water_envelope() -> pd.DataFrame:
    meta = pd.read_csv(META)
    direct = pd.read_csv(DIRECT_ANNUAL)
    cond = pd.read_csv(COND_ANNUAL)

    pod = (
        direct.groupby("calendar_year", as_index=False)["volume_m3"]
        .sum()
        .rename(columns={"calendar_year": "year", "volume_m3": "direct_owrd_pod_m3"})
    )
    back = cond[["year", "water_pred_m3", "it_energy_mwh_fitted"]].rename(
        columns={"water_pred_m3": "existing_statistical_backcast_m3"}
    )
    z = meta.merge(pod, on="year", how="left").merge(back, on="year", how="left")
    z = z[z["year"].between(2011, 2013)].copy()

    # Reported Meta water must remain missing for these years.
    reported = pd.to_numeric(z["water_withdrawal_m3_reported"], errors="coerce")
    if reported.notna().any():
        raise ValueError("2011-2013 envelope must not overwrite or invent reported Meta water")

    e_fac = pd.to_numeric(z["electricity_mwh_reported"], errors="coerce")
    z["reported_meta_water_m3"] = np.nan
    z["design_wue_proxy_m3"] = WUE_DESIGN_L_PER_KWH_IT * (e_fac / PUE_DESIGN)
    # 0.31 L/kWh_IT * E_IT_kWh * 0.001 m3/L = 0.31 * E_fac_MWh / PUE

    proxy_cols = ["direct_owrd_pod_m3", "design_wue_proxy_m3", "existing_statistical_backcast_m3"]
    z["proxy_low"] = z[proxy_cols].min(axis=1, skipna=True)
    z["proxy_high"] = z[proxy_cols].max(axis=1, skipna=True)
    # Three independent constructs disagree in magnitude and boundary; no center.
    z["proxy_center_if_defensible"] = np.nan
    z["pue_design"] = PUE_DESIGN
    z["wue_design_L_per_kWh_IT"] = WUE_DESIGN_L_PER_KWH_IT
    z["design_proxy_equation"] = "W_design = WUE_design * (E_fac / PUE_design); WUE in L/kWh_IT → m3"
    z["direct_pod_is_not_total_meta_water"] = True
    z["design_wue_is_not_reported_meta_water"] = True
    z["statistical_backcast_is_not_observation"] = True
    z["reported_meta_water_status"] = "not publicly reported at site level"
    z["provenance"] = (
        "2011-2013 envelope only. direct_owrd_pod_m3 = observed Vitesse/Facebook OWRD POD "
        "calendar-year total (not campus withdrawal). design_wue_proxy_m3 uses documented "
        "2011 initial-design PUE 1.07 and WUE 0.31 L/kWh_IT from META_ENGINEERING_2011 only. "
        "existing_statistical_backcast_m3 = conditional reconstruction water_pred_m3 "
        "(gray-box evaporation × train-only scale; model-based backcast). "
        "No proxy_center: the three series have different boundaries and are not averaged."
    )
    z["notes"] = (
        "Do not treat this table as Meta-reported water. Later-year reported Meta values "
        "are not modified."
    )
    cols = [
        "year",
        "reported_meta_water_m3",
        "direct_owrd_pod_m3",
        "design_wue_proxy_m3",
        "existing_statistical_backcast_m3",
        "proxy_low",
        "proxy_center_if_defensible",
        "proxy_high",
        "pue_design",
        "wue_design_L_per_kWh_IT",
        "design_proxy_equation",
        "direct_pod_is_not_total_meta_water",
        "design_wue_is_not_reported_meta_water",
        "statistical_backcast_is_not_observation",
        "reported_meta_water_status",
        "provenance",
        "notes",
    ]
    return z[cols].sort_values("year").reset_index(drop=True)


def build_2011_scope2_proxy() -> tuple[pd.DataFrame, pd.DataFrame]:
    meta = pd.read_csv(META)
    egrid = pd.read_csv(EGRID_ANNUAL)
    compare = pd.read_csv(EGRID_COMPARE)

    m2011 = meta.loc[meta.year.eq(2011)].iloc[0]
    e2011 = egrid.loc[egrid.model_year.eq(2011)].iloc[0]
    electricity = float(m2011.electricity_mwh_reported)
    factor = float(e2011.co2e_lb_per_mwh)
    tonnes = electricity * factor / LB_PER_METRIC_TONNE
    expected = float(compare.loc[compare.year.eq(2011), "egrid_estimated_co2e_tonnes"].iloc[0])
    if abs(tonnes - expected) > 1e-6:
        raise ValueError(f"2011 proxy {tonnes} != existing eGRID compare {expected}")
    if pd.notna(m2011.location_based_scope2_tco2e_reported):
        raise ValueError("2011 Meta-reported Scope 2 is unexpectedly present; do not overwrite")

    proxy = pd.DataFrame(
        [
            {
                "year": 2011,
                "meta_electricity_mwh": electricity,
                "electricity_input_source": "data/canonical/meta_prineville_annual.csv::electricity_mwh_reported",
                "egrid_data_year": int(e2011.egrid_data_year),
                "egrid_subregion": e2011.egrid_subregion,
                "nwpp_co2e_lb_per_mwh": factor,
                "co2e_lb_proxy_tco2e": tonnes,
                "equation": "CO2_LB_proxy_2011 = Meta_Electricity_2011 × NWPP_eGRID_factor / 2204.6226218487757",
                "vintage_mapping": "2011 uses eGRID2010 (existing pipeline convention)",
                "is_meta_reported_scope2": False,
                "provenance": PROXY_PROVENANCE,
                "provenance_class": "proxy",
                "notes": (
                    "Location-based accounting proxy using the same eGRID NWPP methodology as "
                    "other years. Not Meta-reported Scope 2. Not hourly carbon intensity."
                ),
            }
        ]
    )

    cmp = compare.copy()
    cmp["egrid_location_based_scope2_proxy_tco2e"] = cmp["egrid_estimated_co2e_tonnes"]
    cmp["egrid_location_based_scope2_proxy_provenance"] = PROXY_PROVENANCE
    cmp["is_meta_reported_scope2"] = cmp["meta_location_based_scope2_tonnes"].notna()
    year2011 = cmp["year"].eq(2011)
    if cmp.loc[year2011, "meta_location_based_scope2_tonnes"].notna().any():
        raise ValueError("must not fill Meta-reported Scope 2 for 2011")
    cmp.loc[year2011, "comparison_note"] = (
        str(cmp.loc[year2011, "comparison_note"].iloc[0])
        + " 2011 eGRID CO2e tonnes are an eGRID_location_based_accounting_proxy because "
        "Meta location-based Scope 2 is not separately disclosed; this is not Meta-reported Scope 2."
    )
    return proxy, cmp


def build_ewif() -> tuple[pd.DataFrame, pd.DataFrame]:
    cool = pd.read_csv(COOLING)
    fuel = pd.read_csv(GEN_FUEL, usecols=["year", "month", "plant_id", "state", "net_generation_mwh"])
    meta = pd.read_csv(META, usecols=["year", "electricity_mwh_reported"])

    cool["generation_mwh"] = pd.to_numeric(cool["generation_mwh"], errors="coerce")
    cool["water_withdrawal_m3"] = pd.to_numeric(cool["water_withdrawal_m3"], errors="coerce")
    cool["water_consumption_m3"] = pd.to_numeric(cool["water_consumption_m3"], errors="coerce")
    cool["eia923_plant_generation_mwh"] = pd.to_numeric(cool["eia923_plant_generation_mwh"], errors="coerce")

    or_fuel = fuel[fuel["state"].astype(str).str.upper().eq("OR")].copy()
    or_fuel["net_generation_mwh"] = pd.to_numeric(or_fuel["net_generation_mwh"], errors="coerce")
    or_tot = or_fuel.groupby(["year", "month"], as_index=False)["net_generation_mwh"].sum()
    or_tot = or_tot.rename(columns={"net_generation_mwh": "total_oregon_generation_mwh"})

    cooling_univ = (
        cool.groupby(["year", "month"], as_index=False)
        .agg(
            cooling_universe_generation_mwh=("eia923_plant_generation_mwh", "sum"),
            n_cooling_plant_rows=("plant_id", "size"),
        )
    )

    base = cool[
        cool["cooling_intensity_eligible"].astype(str).str.lower().eq("true")
        & cool["generation_mwh"].gt(0)
    ].copy()
    # Missing cooling water is not treated as zero.
    wd_ok = base[base["water_withdrawal_m3"].notna()].copy()
    cu_ok = base[base["water_consumption_m3"].notna()].copy()
    wd_ok["WI_withdrawal"] = wd_ok["water_withdrawal_m3"] / wd_ok["generation_mwh"]
    cu_ok["WI_consumption"] = cu_ok["water_consumption_m3"] / cu_ok["generation_mwh"]

    def _agg(df: pd.DataFrame, water_col: str, n_name: str) -> pd.DataFrame:
        g = df.groupby(["year"], as_index=False).agg(
            covered_generation_mwh=("generation_mwh", "sum"),
            covered_water_m3=(water_col, "sum"),
            number_of_plants=("plant_id", "nunique"),
            n_plant_months=("plant_id", "size"),
        )
        g[n_name] = g["covered_water_m3"] / g["covered_generation_mwh"]
        return g

    wd_y = _agg(wd_ok, "water_withdrawal_m3", "EWIF_withdrawal")
    cu_y = _agg(cu_ok, "water_consumption_m3", "EWIF_consumption")
    or_y = or_tot.groupby("year", as_index=False)["total_oregon_generation_mwh"].sum().rename(
        columns={"total_oregon_generation_mwh": "total_generation_mwh"}
    )
    univ_y = cooling_univ.groupby("year", as_index=False)["cooling_universe_generation_mwh"].sum()

    years = pd.DataFrame({"year": list(range(2011, 2025))})
    out = (
        years.merge(wd_y, on="year", how="left")
        .merge(cu_y[["year", "EWIF_consumption", "covered_water_m3"]].rename(
            columns={"covered_water_m3": "covered_consumption_m3"}
        ), on="year", how="left")
        .merge(or_y, on="year", how="left")
        .merge(univ_y, on="year", how="left")
        .merge(meta, on="year", how="left")
    )
    out["generation_coverage_fraction"] = np.where(
        out["total_generation_mwh"].gt(0),
        out["covered_generation_mwh"] / out["total_generation_mwh"],
        np.nan,
    )
    out["cooling_universe_coverage_fraction"] = np.where(
        out["cooling_universe_generation_mwh"].gt(0),
        out["covered_generation_mwh"] / out["cooling_universe_generation_mwh"],
        np.nan,
    )
    # Meaningful as a cooling-plant partial EWIF when eligible water+gen cover a large
    # share of the cooling-universe generation. Never a complete Oregon-grid EWIF.
    out["partial_coverage_cooling_ewif_usable"] = out["cooling_universe_coverage_fraction"].ge(0.70)
    out["scientifically_meaningful_grid_ewif"] = False
    out["regional_average_indirect_water_proxy_m3"] = np.where(
        out["partial_coverage_cooling_ewif_usable"] & out["EWIF_withdrawal"].notna(),
        out["EWIF_withdrawal"] * out["electricity_mwh_reported"],
        np.nan,
    )
    out["is_meta_generator_attribution"] = False
    out["missing_cooling_water_treated_as_zero"] = False
    out["provenance"] = (
        "Partial-coverage EWIF over EIA-923 cooling-intensity-eligible Oregon plant-months "
        "with positive cooling-associated generation and non-missing water volumes. "
        "Missing cooling water is not assumed zero. 2011-2012 Schedule 8 flow rates remain "
        "incomparable. EWIF is a regional cooling-plant diagnostic, not Meta generator "
        "attribution. Indirect water = EWIF_withdrawal × Meta campus MWh is a regional "
        "average proxy only."
    )
    out["provenance_class"] = np.where(
        out["EWIF_withdrawal"].notna(),
        "derived",
        "unavailable",
    )
    cols = [
        "year",
        "covered_generation_mwh",
        "total_generation_mwh",
        "generation_coverage_fraction",
        "cooling_universe_generation_mwh",
        "cooling_universe_coverage_fraction",
        "EWIF_withdrawal",
        "EWIF_consumption",
        "number_of_plants",
        "n_plant_months",
        "partial_coverage_cooling_ewif_usable",
        "scientifically_meaningful_grid_ewif",
        "regional_average_indirect_water_proxy_m3",
        "is_meta_generator_attribution",
        "missing_cooling_water_treated_as_zero",
        "electricity_mwh_reported",
        "provenance",
        "provenance_class",
    ]
    out = out[cols].sort_values("year").reset_index(drop=True)

    n_neg = int((cool["generation_mwh"] < 0).sum())
    n_elig_missing_wd = int(
        (
            cool["cooling_intensity_eligible"].astype(str).str.lower().eq("true")
            & cool["generation_mwh"].gt(0)
            & cool["water_withdrawal_m3"].isna()
        ).sum()
    )
    qa = pd.DataFrame(
        [
            {
                "item": "negative_generation_excluded_from_intensity",
                "value": n_neg,
                "status": "PASS",
                "detail": "intensities require generation_mwh > 0; no division by zero/negative",
            },
            {
                "item": "eligible_plant_months_missing_withdrawal_excluded",
                "value": n_elig_missing_wd,
                "status": "PASS",
                "detail": "missing cooling water is not treated as zero",
            },
            {
                "item": "years_with_usable_partial_cooling_ewif",
                "value": int(out["partial_coverage_cooling_ewif_usable"].fillna(False).sum()),
                "status": "PASS",
                "detail": "usable as cooling-plant diagnostic only; scientifically_meaningful_grid_ewif is always false",
            },
            {
                "item": "meta_generator_attribution",
                "value": False,
                "status": "PASS",
                "detail": "regional average proxy only",
            },
            {
                "item": "2011_2012_ewif",
                "value": "unavailable",
                "status": "PASS",
                "detail": "Schedule 8 units not volume-comparable; cooling_intensity_eligible is false",
            },
        ]
    )
    return out, qa


def _monthly_from_hourly(hourly: pd.DataFrame) -> pd.DataFrame:
    z = hourly.copy()
    z["timestamp_utc"] = pd.to_datetime(z["timestamp_utc"], utc=True)
    local = z["timestamp_utc"].dt.tz_convert(LOCAL_TZ)
    z["month"] = local.dt.month.astype(int)
    z["calendar_year"] = z["year"].astype(int)
    g = z.groupby(["calendar_year", "month"], as_index=False).agg(
        n_hours=("p_fac_mw", "size"),
        facility_mwh_conditional=("p_fac_mw", "sum"),
        evap_water_m3=("evap_water_m3_per_h", "sum"),
        annual_target_mwh=("electricity_closure_target_mwh", "first"),
    )
    g["year_month"] = g.apply(lambda r: f"{int(r.calendar_year):04d}-{int(r.month):02d}", axis=1)
    return g


def build_monthly_electricity() -> pd.DataFrame | None:
    if not HOURLY.exists():
        return None
    hourly = pd.read_csv(
        HOURLY,
        usecols=[
            "timestamp_utc",
            "p_fac_mw",
            "evap_water_m3_per_h",
            "year",
            "electricity_closure_target_mwh",
        ],
    )
    meta = pd.read_csv(META, usecols=["year", "electricity_mwh_reported"])
    g = _monthly_from_hourly(hourly)
    rows = []
    for year, gy in g.groupby("calendar_year"):
        target = float(meta.loc[meta.year.eq(int(year)), "electricity_mwh_reported"].iloc[0])
        gy = gy.copy()
        gy["electricity_mwh_conditional"] = _close_shape(gy["facility_mwh_conditional"], target)
        gy["electricity_mwh_flat"] = _close_shape(gy["n_hours"].astype(float), target)
        if abs(float(gy["electricity_mwh_conditional"].sum()) - target) > 1e-6:
            raise ValueError(f"conditional electricity did not close in {year}")
        if abs(float(gy["electricity_mwh_flat"].sum()) - target) > 1e-6:
            raise ValueError(f"flat electricity did not close in {year}")
        gy["electricity_mwh_stochastic"] = np.nan
        gy["stochastic_shape_status"] = (
            "skipped; no full-period stochastic hourly reconstruction in current outputs"
        )
        gy["series_label"] = "reconstructed / annual-closed"
        gy["is_meter_observation"] = False
        gy["provenance"] = (
            "Annual Meta electricity allocated with existing hourly reconstruction shapes. "
            "flat = equal MWh per reconstructed hour. conditional = gray-box facility power "
            "shape. Not meter data. Stochastic shape not available for 2011-2024."
        )
        rows.append(gy)
    out = pd.concat(rows, ignore_index=True)
    return out[
        [
            "calendar_year",
            "month",
            "year_month",
            "n_hours",
            "electricity_mwh_flat",
            "electricity_mwh_conditional",
            "electricity_mwh_stochastic",
            "stochastic_shape_status",
            "series_label",
            "is_meter_observation",
            "provenance",
        ]
    ].sort_values(["calendar_year", "month"]).reset_index(drop=True)


def build_monthly_water() -> pd.DataFrame | None:
    if not HOURLY.exists():
        return None
    hourly = pd.read_csv(
        HOURLY,
        usecols=["timestamp_utc", "evap_water_m3_per_h", "year", "p_fac_mw", "electricity_closure_target_mwh"],
    )
    meta = pd.read_csv(META)
    direct = pd.read_csv(DIRECT_MONTHLY)
    g = _monthly_from_hourly(hourly)
    pod = direct_pod_monthly_calendar(direct)
    g = g.merge(pod, on=["calendar_year", "month"], how="left")

    rows = []
    for year, gy in g.groupby("calendar_year"):
        mrow = meta.loc[meta.year.eq(int(year))]
        if mrow.empty or pd.isna(mrow["water_withdrawal_m3_reported"].iloc[0]):
            continue
        target = float(mrow["water_withdrawal_m3_reported"].iloc[0])
        gy = gy.copy()
        gy["water_m3_flat"] = _close_shape(pd.Series(1.0, index=gy.index), target)
        gy["water_m3_graybox_evaporation"] = _close_shape(gy["evap_water_m3"], target)
        gy = gy.sort_values("month")
        if list(gy["month"].astype(int)) != list(range(1, 13)):
            gy["water_m3_direct_pod_shape"] = np.nan
            gy["direct_pod_shape_status"] = "skipped_incomplete_direct_pod_shape"
        else:
            closed, status = allocate_direct_pod_year(gy["direct_pod_m3"], target)
            gy["water_m3_direct_pod_shape"] = closed.to_numpy()
            gy["direct_pod_shape_status"] = status
        for col in ("water_m3_flat", "water_m3_graybox_evaporation"):
            if abs(float(gy[col].sum()) - target) > 1e-4:
                raise ValueError(f"{col} did not close in {year}")
        if gy["water_m3_direct_pod_shape"].notna().all():
            if abs(float(gy["water_m3_direct_pod_shape"].sum()) - target) > 1e-4:
                raise ValueError(f"direct-POD water scenario did not close in {year}")
        gy["reported_annual_water_m3"] = target
        gy["series_label"] = "scenario allocation"
        gy["is_observation"] = False
        gy["is_prediction"] = False
        gy["provenance"] = (
            "Scenario allocations of reported annual Meta water using existing shapes. "
            "Not a prediction and not a monthly observation."
        )
        rows.append(gy)
    if not rows:
        return None
    out = pd.concat(rows, ignore_index=True)
    return out[
        [
            "calendar_year",
            "month",
            "year_month",
            "reported_annual_water_m3",
            "water_m3_flat",
            "water_m3_graybox_evaporation",
            "water_m3_direct_pod_shape",
            "direct_pod_shape_status",
            "series_label",
            "is_observation",
            "is_prediction",
            "provenance",
        ]
    ].sort_values(["calendar_year", "month"]).reset_index(drop=True)


def _usgs_end_dates() -> dict[str, str]:
    return {
        "iwa": "2020-09 (USGS IWA documented end; not extended)",
        "irrigation": "2020-12 (USGS irrigation WD/CU documented end; not extended)",
    }


def build_gap_assessment() -> pd.DataFrame:
    n_head = 0
    if LEVELS.exists():
        lv = pd.read_csv(LEVELS)
        n_head = int(
            lv.get("water_level_below_land_surface", pd.Series(dtype=float)).notna().sum()
            + lv.get("water_surface_elevation_or_head", pd.Series(dtype=float)).notna().sum()
        )
    feas = "C"
    if FEAS.exists():
        feas = str(pd.read_csv(FEAS).iloc[0]["feasibility_class"])
    usgs = _usgs_end_dates()

    gwis_high = n_head == 0
    rows = [
        {
            "dataset": "OWRD/GWIS groundwater-level records",
            "specific_missing_model_quantity": "Q_HEAD / Q_GW_OBS (time-indexed groundwater head at municipal and ASR wells)",
            "current_substitute_or_proxy": (
                f"Local GWIS ingest now provides {n_head} numeric well-level observations. "
                "Catalogued ASR application/attachments PDFs were not found under data/raw; "
                "local Crook County permit PDFs were scanned and added no T/S/Sy values."
            ),
            "expected_temporal_spatial_coverage": (
                "OWRD GWIS well-level measurements for Crook County / Prineville municipal and "
                "nearby wells; typically irregular to monthly, well-specific, with official IDs"
            ),
            "new_information_or_duplicate": (
                "GWIS well-level series are now ingested. Remaining gaps are aquifer parameters, "
                "combined Airport pumping identity, unmatched GWIS wells, and mixed vertical datums."
            ),
            "expected_identification_value": (
                "Enables at least class B (validation targets) and is a prerequisite for class A "
                "reduced-order dynamic estimation if pumping–head overlap is adequate."
            ),
            "implementation_effort": "MEDIUM (public query + join to existing well_node_id / wl_id)",
            "priority": "HIGH" if gwis_high else "LOW",
            "recommended_next_action": (
                "Do not re-acquire the current GWIS pull. Remaining reduced-order blockers are "
                "unresolved T/S/Sy/pumping-test parameters, combined Airport POD identity, and "
                "datum/unmatched-well limitations. Catalogued ASR PDFs are still not local."
            ),
            "required_before_reduced_order_gw_model": "YES",
            "notes": f"Current feasibility class {feas}.",
        },
        {
            "dataset": "OpenET 2021-2024 irrigation/ET",
            "specific_missing_model_quantity": (
                "Q_IRRIGATION competing irrigation demand / ET after the USGS NWAA irrigation period"
            ),
            "current_substitute_or_proxy": (
                f"USGS irrigation WD/CU HUC12 model through {usgs['irrigation']}; no post-coverage extension."
            ),
            "expected_temporal_spatial_coverage": "Monthly field/HUC-scale ET, 2021-2024, Crooked River / Prineville HUC12s",
            "new_information_or_duplicate": (
                "New for 2021-2024. Overlaps USGS irrigation only if pulled earlier; the gap is post-2020."
            ),
            "expected_identification_value": (
                "Improves competing-demand context for water-energy-groundwater, not groundwater head itself."
            ),
            "implementation_effort": "MEDIUM (API/export, HUC12 zonal stats, unit conversion)",
            "priority": "MEDIUM",
            "recommended_next_action": (
                "Defer until after GWIS if the immediate goal is a first groundwater model. "
                "Acquire if post-2020 irrigation competition is in the next water-context stage."
            ),
            "required_before_reduced_order_gw_model": "NO",
            "notes": "Not a substitute for well heads or pumping tests.",
        },
        {
            "dataset": "USGS NHM / National Water Model / observed streamflow or recharge",
            "specific_missing_model_quantity": "Q_RECHARGE / Q_IWA_STRFLOW post-2020 hydrologic state",
            "current_substitute_or_proxy": (
                f"USGS IWA HUC12 routed hydrology through {usgs['iwa']}; no post-2020 recharge series."
            ),
            "expected_temporal_spatial_coverage": (
                "NHM/NWM: modeled streamflow/recharge on NHD/HRUs; USGS NWIS: gaged streamflow. "
                "Post-2020 coverage possible; not well-network heads."
            ),
            "new_information_or_duplicate": (
                "New for post-2020 hydrologic context. Duplicates IWA if used inside 2009-10–2020-09."
            ),
            "expected_identification_value": (
                "Supports recharge/boundary priors for a later GW model; does not identify heads."
            ),
            "implementation_effort": "HIGH (model output subsetting, alignment to HUC12, not a drop-in IWA extension)",
            "priority": "MEDIUM",
            "recommended_next_action": (
                "Not required for a first reduced-order GW attempt. Prefer observed local streamflow "
                "plus GWIS heads over a full NWM/NHM ingest if hydrologic context is needed."
            ),
            "required_before_reduced_order_gw_model": "NO",
            "notes": "Do not extend official USGS IWA past its documented period by splicing NWM.",
        },
    ]
    return pd.DataFrame(rows)


def run(skip_gap: bool = False) -> dict[str, Path]:
    _mkdirs()
    env = build_early_water_envelope()
    env.to_csv(ENVELOPE_OUT, index=False)

    proxy, compare = build_2011_scope2_proxy()
    proxy.to_csv(SCOPE2_PROXY_OUT, index=False)
    compare.to_csv(EGRID_COMPARE, index=False)

    ewif, ewif_qa = build_ewif()
    ewif.to_csv(EWIF_OUT, index=False)
    ewif_qa.to_csv(EWIF_QA, index=False)

    elec_m = build_monthly_electricity()
    if elec_m is not None:
        elec_m.to_csv(ELEC_MONTHLY_OUT, index=False)
    water_m = build_monthly_water()
    if water_m is not None:
        water_m.to_csv(WATER_MONTHLY_OUT, index=False)

    out = {
        "early_water": ENVELOPE_OUT,
        "scope2_proxy": SCOPE2_PROXY_OUT,
        "ewif": EWIF_OUT,
        "ewif_qa": EWIF_QA,
        "egrid_compare": EGRID_COMPARE,
    }
    if elec_m is not None:
        out["monthly_electricity"] = ELEC_MONTHLY_OUT
    if water_m is not None:
        out["monthly_water"] = WATER_MONTHLY_OUT
    if not skip_gap:
        gap = build_gap_assessment()
        gap.to_csv(GAP_OUT, index=False)
        out["gap"] = GAP_OUT
    return out


if __name__ == "__main__":
    import sys

    paths = run(skip_gap="--skip-gap" in sys.argv)
    for k, p in paths.items():
        print(f"{k}: {p}")
