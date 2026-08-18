"""Case-level Oregon generator-pilot exception report.

Read-only over existing processed/QC tables. Does not modify mappings or source
values. Distinguishes pipeline_error, qc_logic_error, source_anomaly,
structural_relationship, coverage_limitation, expected_missingness, and
unresolved_source_conflict. needs_manual_review is reserved for residual
unresolved cases.
"""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oregon_generation_qc import (
    MONTHLY_EXTREME_HIGH,
    MONTHLY_EXTREME_LOW,
    is_annual_only_eia923,
    monthly_generation_basis,
    monthly_outlier_is_primary_conflict,
    monthly_ratio_is_extreme,
    normalize_reporting_frequency,
)

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
OUTPUTS = ROOT / "outputs"

OUT_REPORT = OUTPUTS / "oregon_exception_report.csv"
OUT_SUMMARY = OUTPUTS / "oregon_exception_summary.csv"
OUT_ANNUAL_RECON = OUTPUTS / "oregon_campd_eia923_annual_reconciliation.csv"

COLS = [
    "issue_type",
    "root_cause_class",
    "root_cause_id",
    "severity",
    "year",
    "month",
    "plant_name",
    "camd_facility_id",
    "camd_unit_id",
    "eia_plant_id",
    "eia_generator_id",
    "eia_boiler_id",
    "mapping_cardinality",
    "match_method",
    "match_type",
    "source_a",
    "value_a",
    "source_b",
    "value_b",
    "difference",
    "ratio",
    "reason_flagged",
    "agent_interpretation",
    "confidence",
    "recommended_action",
    "needs_manual_review",
]

EXTREME_HIGH = MONTHLY_EXTREME_HIGH
EXTREME_LOW = MONTHLY_EXTREME_LOW


def row(**kwargs) -> dict:
    out = {c: np.nan for c in COLS}
    out["needs_manual_review"] = False
    out.update(kwargs)
    out["needs_manual_review"] = bool(out.get("needs_manual_review", False))
    return out


def _num(value):
    if value is None:
        return np.nan
    try:
        if pd.isna(value):
            return np.nan
    except Exception:
        pass
    return value


def plant_name_map(*frames: pd.DataFrame) -> dict:
    names: dict[int, str] = {}
    for src in frames:
        if src is None or src.empty or "plant_id" not in src.columns:
            continue
        pname = "plant_name" if "plant_name" in src.columns else None
        if pname is None:
            continue
        tmp = src.dropna(subset=["plant_id", pname])
        for rec in tmp.itertuples(index=False):
            key = int(rec.plant_id)
            val = str(getattr(rec, pname)).strip()
            if val and val.lower() != "nan" and key not in names:
                names[key] = val
    return names


def lookup_name(names: dict, plant_id, fallback=np.nan):
    if pd.isna(plant_id):
        return fallback
    return names.get(int(plant_id), fallback)


def crosswalk_exceptions(audit: pd.DataFrame) -> list[dict]:
    rows = []
    unmatched = audit[audit["mapping_cardinality"].eq("unmatched")]
    for rec in unmatched.itertuples(index=False):
        rows.append(
            row(
                issue_type="epa_eia_crosswalk_unmatched",
                root_cause_class="unresolved_source_conflict",
                root_cause_id=f"unmatched_{rec.camd_facility_id}_{rec.camd_unit_id}",
                severity="high",
                year=rec.years_active,
                plant_name=rec.facility_name,
                camd_facility_id=rec.camd_facility_id,
                camd_unit_id=rec.camd_unit_id,
                mapping_cardinality="unmatched",
                match_method="unmatched",
                match_type="unmatched",
                source_a="CAMPD unit",
                value_a=f"{rec.camd_facility_id}|{rec.camd_unit_id}",
                source_b="EPA/EIA crosswalk",
                value_b="no EIA plant",
                reason_flagged="CAMD unit has no EIA plant in the published crosswalk",
                agent_interpretation="Unresolved plant mapping. Unit is retained in CAMPD and is not allocated to an EIA generator.",
                confidence="high",
                recommended_action="Leave unmatched. Do not invent a plant mapping or split CEMS onto a generator.",
                needs_manual_review=True,
            )
        )

    split = audit[audit["mapping_cardinality"].eq("one_to_many_plants")]
    for rec in split.itertuples(index=False):
        rows.append(
            row(
                issue_type="epa_eia_crosswalk_plant_split",
                root_cause_class="pipeline_error",
                root_cause_id=f"plant_split_{rec.camd_facility_id}_{rec.camd_unit_id}",
                severity="high",
                plant_name=rec.facility_name,
                camd_facility_id=rec.camd_facility_id,
                camd_unit_id=rec.camd_unit_id,
                mapping_cardinality=rec.mapping_cardinality,
                match_method=rec.match_method,
                reason_flagged="CAMD unit maps to multiple EIA plants",
                agent_interpretation="This would duplicate or arbitrarily split CEMS. The pipeline aborts rather than explode the join.",
                confidence="high",
                recommended_action="Do not proceed with generator-level emission copies.",
                needs_manual_review=True,
            )
        )

    structural = audit[audit["mapping_cardinality"].isin(["one_to_many", "many_to_one", "many_to_many"])]
    structural = structural[structural["n_eia_plant"].fillna(1).le(1)]
    if len(structural):
        plants = sorted({int(p) for p in structural["eia_plant_id"].dropna()})
        rows.append(
            row(
                issue_type="epa_eia_crosswalk_generator_cardinality",
                root_cause_class="structural_relationship",
                root_cause_id="combined_cycle_or_shared_generator_cardinality",
                severity="low",
                plant_name="|".join(sorted({str(n) for n in structural["facility_name"].dropna()})),
                camd_facility_id="|".join(structural["camd_facility_id"].astype(str)),
                camd_unit_id="|".join(structural["camd_unit_id"].astype(str)),
                eia_plant_id="|".join(str(p) for p in plants),
                mapping_cardinality=join_unique(structural["mapping_cardinality"]),
                match_method=join_unique(structural["match_method"]),
                match_type=join_unique(structural["match_type"]),
                source_a="n CAMD units with generator cardinality != one_to_one",
                value_a=len(structural),
                source_b="defensible unique CAMD-unit to EIA-plant map",
                value_b=f"n_plants={len(plants)}",
                reason_flagged="Combined-cycle CT+ST (or shared ST) generator links in the published EPA/EIA crosswalk",
                agent_interpretation="Expected generator cardinality. CAMPD emissions stay on the CAMD unit and are not copied onto each EIA generator ID.",
                confidence="high",
                recommended_action="Keep the unique unit→plant map. Do not explode CEMS across generator IDs.",
                needs_manual_review=False,
            )
        )

    differ = audit[audit.get("plant_ids_differ", pd.Series(False)).eq(True)]
    for rec in differ.itertuples(index=False):
        review = rec.match_method != "official_manual"
        rows.append(
            row(
                issue_type="epa_eia_crosswalk_plant_id_differs",
                root_cause_class="unresolved_source_conflict" if review else "structural_relationship",
                root_cause_id=f"plant_id_differ_{rec.camd_facility_id}_{rec.camd_unit_id}",
                severity="medium" if not review else "high",
                year=rec.years_active,
                plant_name=rec.facility_name,
                camd_facility_id=rec.camd_facility_id,
                camd_unit_id=rec.camd_unit_id,
                eia_plant_id=_num(rec.eia_plant_id),
                eia_generator_id=rec.eia_generator_id,
                mapping_cardinality=rec.mapping_cardinality,
                match_method=rec.match_method,
                match_type=rec.match_type,
                source_a="CAMD Facility ID",
                value_a=rec.camd_facility_id,
                source_b="EIA_PLANT_ID in published crosswalk",
                value_b=rec.eia_plant_id,
                reason_flagged=f"CAMD facility ID differs from EIA plant ID; MATCH_TYPE_GEN={rec.match_text}",
                agent_interpretation=(
                    "Official EPA/EIA manual plant assignment is used as published. "
                    "No new mapping was created. CEMS remain on the CAMD unit and join to the crosswalk EIA plant."
                    if rec.match_method == "official_manual"
                    else "Plant IDs differ without an official manual provenance label."
                ),
                confidence="high" if rec.match_method == "official_manual" else "medium",
                recommended_action="Preserve official provenance. Do not recode CAMD Facility ID.",
                needs_manual_review=bool(review),
            )
        )

    fuzzy = audit[audit["match_method"].eq("modified_fuzzy")]
    if len(fuzzy):
        rows.append(
            row(
                issue_type="epa_eia_crosswalk_modified_fuzzy_provenance",
                root_cause_class="structural_relationship",
                root_cause_id="epa_eia_modified_boiler_or_generator_ids",
                severity="low",
                plant_name="|".join(sorted({str(n) for n in fuzzy["facility_name"].dropna()})),
                camd_unit_id="|".join(fuzzy["camd_unit_id"].astype(str)),
                mapping_cardinality=join_unique(fuzzy["mapping_cardinality"]),
                match_method="modified_fuzzy",
                source_a="n units with MATCH_TYPE_BOILER/GEN ID modification",
                value_a=len(fuzzy),
                source_b="published EPA/EIA crosswalk",
                value_b=join_unique(fuzzy["match_text_boiler"]) if "match_text_boiler" in fuzzy.columns else np.nan,
                reason_flagged="EPA/EIA boiler or generator match required ID modification in the published crosswalk",
                agent_interpretation="Official fuzzy/modified-ID provenance is retained. Native CAMD and EIA IDs are not recoded.",
                confidence="high",
                recommended_action="Keep native IDs. Do not treat CAMD unit ID as equal to EIA boiler ID.",
                needs_manual_review=False,
            )
        )
    return rows


def join_unique(series: pd.Series) -> str | float:
    parts = sorted({str(v).strip() for v in series.dropna().astype(str) if str(v).strip() and str(v) != "nan"})
    return "|".join(parts) if parts else np.nan


def temporal_exceptions(flags: pd.DataFrame, names: dict) -> list[dict]:
    rows = []
    if flags.empty:
        return rows
    conflict = flags[flags.get("flag_severity", pd.Series(dtype=str)).eq("conflict")] if "flag_severity" in flags.columns else flags[flags["flag"].ne("ok")]
    for rec in conflict.itertuples(index=False):
        name = lookup_name(names, rec.plant_id)
        rows.append(
            row(
                issue_type="eia860_campd_temporal_conflict",
                root_cause_class="unresolved_source_conflict",
                root_cause_id=f"after_retirement_{int(rec.camd_facility_id)}_{rec.camd_unit_id}_{int(rec.year)}_{int(rec.month)}",
                severity="high",
                year=int(rec.year),
                month=int(rec.month) if "month" in flags.columns and pd.notna(rec.month) else np.nan,
                plant_name=name,
                camd_facility_id=rec.camd_facility_id,
                camd_unit_id=rec.camd_unit_id,
                eia_plant_id=_num(rec.plant_id),
                match_type=rec.flag,
                source_a="CAMPD unit-month hours",
                value_a=int(rec.n_campd_hours),
                source_b="EIA-860 operating/retirement year+month",
                value_b=(
                    f"operating={getattr(rec, 'operating_year', np.nan)}-{getattr(rec, 'operating_month', np.nan)}; "
                    f"retirement={getattr(rec, 'retirement_year', np.nan)}-{getattr(rec, 'retirement_month', np.nan)}; "
                    f"CAMD_STATUS_DATE={getattr(rec, 'camd_status_date', np.nan)}"
                ),
                reason_flagged=rec.flag,
                agent_interpretation="CAMPD hours occur after the EIA-860 retirement month (or before operating month). Hours were not deleted.",
                confidence="high",
                recommended_action="Leave CAMPD hours as reported. Do not rewrite EIA-860 dates.",
                needs_manual_review=True,
            )
        )
    return rows


def generation_outliers(compare: pd.DataFrame, audit: pd.DataFrame) -> list[dict]:
    rows = []
    both = compare[compare["join_status"].eq("both")].copy()
    both["r_campd_over_eia923"] = pd.to_numeric(both["r_campd_over_eia923"], errors="coerce")
    if "reporting_frequency" in both.columns:
        both["reporting_frequency"] = both["reporting_frequency"].map(normalize_reporting_frequency)
    else:
        both["reporting_frequency"] = ""
    if "monthly_generation_basis" not in both.columns:
        both["monthly_generation_basis"] = both["reporting_frequency"].map(monthly_generation_basis)
    gen_col = "campd_gross_generation_mwh" if "campd_gross_generation_mwh" in both.columns else "campd_gross_load_mwh_or_equivalent"
    ext = both[both["r_campd_over_eia923"].map(monthly_ratio_is_extreme)]
    ext = ext.sort_values(["year", "month", "plant_id"])
    unit_map = (
        audit.dropna(subset=["eia_plant_id"])
        .groupby("eia_plant_id")
        .agg(
            camd_facility_id=("camd_facility_id", "first"),
            camd_unit_id=("camd_unit_id", lambda s: "|".join(sorted(s.astype(str)))),
            eia_generator_id=("eia_generator_id", lambda s: join_unique(s)),
            mapping_cardinality=("mapping_cardinality", lambda s: join_unique(s)),
            match_method=("match_method", lambda s: join_unique(s)),
            match_type=("match_type", lambda s: join_unique(s)),
        )
        .reset_index()
        .rename(columns={"eia_plant_id": "plant_id"})
    )
    merged = ext.merge(unit_map, on="plant_id", how="left")
    for rec in merged.itertuples(index=False):
        g_campd = getattr(rec, gen_col)
        g_eia = rec.generation_mwh
        r = rec.r_campd_over_eia923
        campd_name = rec.plant_name_campd if pd.notna(rec.plant_name_campd) else rec.plant_name
        freq = normalize_reporting_frequency(getattr(rec, "reporting_frequency", ""))
        basis = monthly_generation_basis(freq)
        primary = monthly_outlier_is_primary_conflict(freq)
        if is_annual_only_eia923(freq) or (not primary and basis == "eia_allocated_from_annual"):
            rows.append(
                row(
                    issue_type="campd_eia923_generation_outlier",
                    root_cause_class="coverage_limitation",
                    root_cause_id="eia923_annual_respondent_monthly_not_observed",
                    severity="low",
                    year=int(rec.year),
                    month=int(rec.month),
                    plant_name=campd_name,
                    camd_facility_id=_num(rec.camd_facility_id),
                    camd_unit_id=rec.camd_unit_id,
                    eia_plant_id=_num(rec.plant_id),
                    eia_generator_id=rec.eia_generator_id,
                    mapping_cardinality=rec.mapping_cardinality,
                    match_method=rec.match_method,
                    match_type=rec.match_type,
                    source_a="CAMPD plant-month gross generation MWh (Gross Load MW × Operating Time)",
                    value_a=_num(g_campd),
                    source_b="EIA-923 published monthly net generation MWh (annual respondent; not observed)",
                    value_b=_num(g_eia),
                    difference=_num(g_campd) - _num(g_eia) if pd.notna(g_campd) and pd.notna(g_eia) else np.nan,
                    ratio=_num(r),
                    reason_flagged=(
                        f"EIA-923 Plant Frame frequency={freq}; monthly_generation_basis={basis}. "
                        f"Monthly R={r} is a diagnostic only. Primary QC is annual CAMPD/EIA-923 reconciliation."
                    ),
                    agent_interpretation=(
                        "Annual EIA-923 respondents report calendar-year totals and do not break generation "
                        "down by month. Published monthly Netgen columns are EIA allocations/estimates, not "
                        "respondent monthly observations. Monthly CAMPD vs EIA-923 disagreement is expected "
                        "and is not an unresolved source conflict."
                    ),
                    confidence="high",
                    recommended_action="Use the plant-year CAMPD/EIA-923 reconciliation. Do not rescale CAMPD or EIA-923 monthly values.",
                    needs_manual_review=False,
                )
            )
            continue
        rows.append(
            row(
                issue_type="campd_eia923_generation_outlier",
                root_cause_class="unresolved_source_conflict",
                root_cause_id=f"extreme_R_{int(rec.plant_id)}_{int(rec.year)}_{int(rec.month)}",
                severity="high",
                year=int(rec.year),
                month=int(rec.month),
                plant_name=campd_name,
                camd_facility_id=_num(rec.camd_facility_id),
                camd_unit_id=rec.camd_unit_id,
                eia_plant_id=_num(rec.plant_id),
                eia_generator_id=rec.eia_generator_id,
                mapping_cardinality=rec.mapping_cardinality,
                match_method=rec.match_method,
                match_type=rec.match_type,
                source_a="CAMPD plant-month gross generation MWh (Gross Load MW × Operating Time)",
                value_a=_num(g_campd),
                source_b="EIA-923 plant-month net generation MWh (respondent monthly)",
                value_b=_num(g_eia),
                difference=_num(g_campd) - _num(g_eia) if pd.notna(g_campd) and pd.notna(g_eia) else np.nan,
                ratio=_num(r),
                reason_flagged=(
                    f"EIA-923 Plant Frame frequency={freq or 'unknown'}; monthly_generation_basis={basis}. "
                    f"Respondent monthly ratio R={r} outside {EXTREME_LOW}-{EXTREME_HIGH}; "
                    f"n_reporting_units={rec.n_reporting_units}; n_hours={rec.n_hours}; "
                    f"CAMPD name={campd_name}; EIA-923 name={rec.plant_name}"
                ),
                agent_interpretation=(
                    "CAMPD is unit-level gross generation; EIA-923 is plant-level net generation. "
                    "This plant-year is a monthly EIA-923 reporter, so monthly disagreement remains "
                    "eligible for discrepancy QC. Values were not rescaled or forced equal."
                ),
                confidence="high",
                recommended_action="Inspect EIA-923 fuel-row coverage for this plant-month. Do not multiply posted CAMPD mass by Operating Time.",
                needs_manual_review=True,
            )
        )
    return rows


def annual_reconciliation_exceptions(recon: pd.DataFrame, audit: pd.DataFrame) -> list[dict]:
    rows = []
    if recon is None or recon.empty:
        return rows
    unit_map = (
        audit.dropna(subset=["eia_plant_id"])
        .groupby("eia_plant_id")
        .agg(
            camd_facility_id=("camd_facility_id", "first"),
            camd_unit_id=("camd_unit_id", lambda s: "|".join(sorted(s.astype(str)))),
            mapping_cardinality=("mapping_cardinality", lambda s: join_unique(s)),
            match_method=("match_method", lambda s: join_unique(s)),
        )
        .reset_index()
        .rename(columns={"eia_plant_id": "plant_id"})
        if len(audit) and "eia_plant_id" in audit.columns
        else pd.DataFrame()
    )
    warn = recon[recon["qc_status"].eq("annual_comparability_warning")].copy()
    if unit_map.empty:
        merged = warn
        for col in ["camd_facility_id", "camd_unit_id", "mapping_cardinality", "match_method"]:
            if col not in merged.columns:
                merged[col] = np.nan
    else:
        merged = warn.merge(unit_map, on="plant_id", how="left")
    for rec in merged.itertuples(index=False):
        freq = normalize_reporting_frequency(getattr(rec, "reporting_frequency", ""))
        rows.append(
            row(
                issue_type="campd_eia923_annual_comparability_warning",
                root_cause_class="coverage_limitation",
                root_cause_id=f"annual_comparability_{int(rec.plant_id)}_{int(rec.year)}",
                severity="medium",
                year=int(rec.year),
                plant_name=getattr(rec, "plant_name", np.nan),
                camd_facility_id=_num(getattr(rec, "camd_facility_id", np.nan)),
                camd_unit_id=getattr(rec, "camd_unit_id", np.nan),
                eia_plant_id=_num(rec.plant_id),
                mapping_cardinality=getattr(rec, "mapping_cardinality", np.nan),
                match_method=getattr(rec, "match_method", np.nan),
                source_a="CAMPD annual gross generation MWh",
                value_a=_num(rec.campd_gross_generation_mwh),
                source_b="EIA-923 annual net generation MWh",
                value_b=_num(rec.eia923_net_generation_mwh),
                difference=_num(rec.annual_difference_mwh),
                ratio=_num(rec.annual_ratio),
                reason_flagged=str(getattr(rec, "notes", "")),
                agent_interpretation=(
                    "Annual CAMPD gross vs EIA-923 net is outside the documented envelope. "
                    "Monthly EIA-923 allocation cannot explain an annual gap. "
                    "Evidence is insufficient to choose a source correction; values were not rescaled."
                    if is_annual_only_eia923(freq)
                    else "Annual CAMPD gross vs EIA-923 net is outside the documented envelope. "
                    "This may reflect gross vs net, CEMS coverage versus plant-level EIA-923, or another "
                    "source-boundary difference. Values were not rescaled."
                ),
                confidence="medium",
                recommended_action="Leave both sources as reported. Do not use this plant-year as a monthly-forced-agreement check.",
                needs_manual_review=False,
            )
        )
    return rows


def cooling_exceptions(cool: pd.DataFrame, names: dict) -> list[dict]:
    rows = []
    cool = cool.copy()
    for rec in cool.itertuples(index=False):
        year = int(rec.year) if pd.notna(rec.year) else np.nan
        month = int(rec.month) if pd.notna(rec.month) else np.nan
        pid = rec.plant_id
        name = rec.plant_name if pd.notna(getattr(rec, "plant_name", np.nan)) else lookup_name(names, pid)
        status = str(getattr(rec, "cooling_generation_status", "") or "")

        if year in (2011, 2012) or status == "coverage_limitation_2011_2012_units":
            rows.append(
                row(
                    issue_type="cooling_schedule8_units_not_comparable",
                    root_cause_class="coverage_limitation",
                    root_cause_id="sched8_2011_2012_flow_rate_units",
                    severity="low",
                    year=year,
                    month=month,
                    plant_name=name,
                    eia_plant_id=_num(pid),
                    source_a="EIA-923 Schedule 8 native rates",
                    value_a=getattr(rec, "incomparability_note", np.nan),
                    source_b="standardized million-gallon cooling product",
                    value_b="water_m3 left missing",
                    reason_flagged="2011-2012 Schedule 8 flow-rate units are not converted",
                    agent_interpretation="Documented coverage limitation. Native rates are retained; m3 was not invented.",
                    confidence="high",
                    recommended_action="Keep water m3 missing. Do not apply an unreviewed cfs/gpm conversion.",
                    needs_manual_review=False,
                )
            )
            continue

        if year == 2013 or status == "expected_missingness_schedule8_generation":
            if pd.notna(getattr(rec, "water_withdrawal_m3", np.nan)) or pd.notna(getattr(rec, "water_consumption_m3", np.nan)):
                rows.append(
                    row(
                        issue_type="cooling_schedule8_generation_left_missing",
                        root_cause_class="expected_missingness",
                        root_cause_id="sched8_2013_generation_left_nan",
                        severity="low",
                        year=year,
                        month=month,
                        plant_name=name,
                        eia_plant_id=_num(pid),
                        source_a="Schedule 8 water_withdrawal_m3",
                        value_a=_num(getattr(rec, "water_withdrawal_m3", np.nan)),
                        source_b="cooling-associated generation_mwh",
                        value_b="NaN by design (Schedule 8 has no cooling-associated generation fields)",
                        reason_flagged="2013 Schedule 8 generation_mwh left missing deliberately",
                        agent_interpretation="Expected missingness. Intensity is not computed. EIA-923 plant generation is not substituted.",
                        confidence="high",
                        recommended_action="Do not divide 2013 Schedule 8 water by EIA-923 plant generation.",
                        needs_manual_review=False,
                    )
                )
            continue

        if bool(getattr(rec, "consumption_source_anomaly", False)):
            summary_cn = getattr(rec, "summary_water_consumption_million_gal", np.nan)
            official_agrees = pd.notna(summary_cn) and float(summary_cn) < 0
            rows.append(
                row(
                    issue_type="cooling_negative_consumption_source_anomaly",
                    root_cause_class="source_anomaly",
                    root_cause_id=f"neg_consumption_{int(pid)}_{year}_{month}",
                    severity="high",
                    year=year,
                    month=month,
                    plant_name=name,
                    eia_plant_id=_num(pid),
                    source_a="cooling-detail Water Consumption Volume (Million Gallons)",
                    value_a=_num(rec.water_consumption_million_gal),
                    source_b="official cooling summary consumption million gal / modeled m3",
                    value_b=f"summary={summary_cn}; modeled_m3=missing; reported_m3={getattr(rec, 'water_consumption_m3_reported', np.nan)}",
                    reason_flagged="reported cooling consumption is negative; intensity left missing",
                    agent_interpretation=(
                        "Official detail and summary both report negative consumption. "
                        "The raw million-gallon value is preserved. Modeled consumption m3 and intensity are missing; the value was not clipped to zero."
                        if official_agrees
                        else "Negative consumption on the detail file. Modeled intensity left missing; raw million-gallon value preserved."
                    ),
                    confidence="high",
                    recommended_action="Do not use this intensity. Do not clip the official negative to zero.",
                    needs_manual_review=not official_agrees,
                )
            )

        if status == "pipeline_mismatch_summary_has_generation":
            rows.append(
                row(
                    issue_type="cooling_generation_pipeline_mismatch",
                    root_cause_class="pipeline_error",
                    root_cause_id=f"cool_gen_mismatch_{int(pid)}_{year}_{month}",
                    severity="high",
                    year=year,
                    month=month,
                    plant_name=name,
                    eia_plant_id=_num(pid),
                    source_a="detail cooling-associated generation_mwh",
                    value_a=_num(rec.generation_mwh),
                    source_b="official cooling summary generation_mwh",
                    value_b=_num(getattr(rec, "summary_generation_mwh", np.nan)),
                    reason_flagged="cooling summary has generation while the detail aggregation does not",
                    agent_interpretation="Possible aggregation error versus the official summary file.",
                    confidence="medium",
                    recommended_action="Inspect native cooling-detail generator rows for this plant-month.",
                    needs_manual_review=True,
                )
            )
        elif status in {"cooling_gen_zero_eia923_positive", "cooling_gen_missing_eia923_positive"}:
            rows.append(
                row(
                    issue_type="cooling_associated_generation_missing_or_zero",
                    root_cause_class="coverage_limitation",
                    root_cause_id=f"cool_gen_boundary_{int(pid)}_{year}_{month}",
                    severity="medium",
                    year=year,
                    month=month,
                    plant_name=name,
                    eia_plant_id=_num(pid),
                    source_a="cooling-associated generation_mwh",
                    value_a=_num(rec.generation_mwh),
                    source_b="EIA-923 plant net generation / cooling summary generation",
                    value_b=(
                        f"eia923={getattr(rec, 'eia923_plant_generation_mwh', np.nan)}; "
                        f"summary={getattr(rec, 'summary_generation_mwh', np.nan)}"
                    ),
                    reason_flagged=status,
                    agent_interpretation=(
                        "Cooling-associated generation is missing/zero while EIA-923 plant generation is positive. "
                        "Official cooling summary also lacks positive cooling-associated generation. "
                        "Boundaries are not demonstrably compatible; plant generation is not used as the intensity denominator."
                    ),
                    confidence="high",
                    recommended_action="Leave cooling intensity missing. Do not substitute EIA-923 plant generation.",
                    needs_manual_review=False,
                )
            )
        elif status == "expected_zero_cooling_and_plant_gen":
            rows.append(
                row(
                    issue_type="cooling_water_with_zero_generation_expected",
                    root_cause_class="expected_missingness",
                    root_cause_id="cooling_and_plant_generation_both_zero_or_missing",
                    severity="low",
                    year=year,
                    month=month,
                    plant_name=name,
                    eia_plant_id=_num(pid),
                    source_a="cooling-associated generation_mwh",
                    value_a=_num(rec.generation_mwh),
                    source_b="EIA-923 plant generation_mwh",
                    value_b=_num(getattr(rec, "eia923_plant_generation_mwh", np.nan)),
                    reason_flagged="cooling water present; cooling-associated and EIA-923 plant generation are zero/missing",
                    agent_interpretation="Expected missing intensity: both cooling-associated and plant generation are non-positive. No zero-division.",
                    confidence="high",
                    recommended_action="Keep intensity missing.",
                    needs_manual_review=False,
                )
            )
        elif status == "expected_missingness_cooling_and_plant_gen":
            rows.append(
                row(
                    issue_type="cooling_water_without_generation_expected",
                    root_cause_class="expected_missingness",
                    root_cause_id="cooling_generation_and_eia923_both_missing",
                    severity="low",
                    year=year,
                    month=month,
                    plant_name=name,
                    eia_plant_id=_num(pid),
                    source_a="cooling water_withdrawal_m3",
                    value_a=_num(getattr(rec, "water_withdrawal_m3", np.nan)),
                    source_b="cooling-associated generation / EIA-923 plant generation",
                    value_b="both missing or non-positive",
                    reason_flagged=status,
                    agent_interpretation="Water is present without a compatible generation denominator. Intensity left missing.",
                    confidence="high",
                    recommended_action="Do not invent a generation denominator.",
                    needs_manual_review=False,
                )
            )

    std = cool[cool["cooling_source"].astype(str).eq("eia_cooling_detail_standardized")]
    if not std.empty and "n_generator_rows" in std.columns and "n_cooling_systems" in std.columns:
        risk = (
            std.groupby("plant_id", dropna=False)
            .agg(
                plant_name=("plant_name", "first"),
                n_generator_rows_max=("n_generator_rows", "max"),
                n_cooling_systems_max=("n_cooling_systems", "max"),
                years=("year", lambda s: f"{int(s.min())}-{int(s.max())}"),
            )
            .reset_index()
        )
        risk = risk[risk["n_generator_rows_max"].fillna(0) > risk["n_cooling_systems_max"].fillna(0)]
        for rec in risk.itertuples(index=False):
            rows.append(
                row(
                    issue_type="cooling_repeated_system_generator_links",
                    root_cause_class="structural_relationship",
                    root_cause_id="cooling_detail_repeat_generator_links",
                    severity="low",
                    year=rec.years,
                    plant_name=rec.plant_name if pd.notna(rec.plant_name) else lookup_name(names, rec.plant_id),
                    eia_plant_id=_num(rec.plant_id),
                    source_a="max n_generator_rows",
                    value_a=_num(rec.n_generator_rows_max),
                    source_b="max n_cooling_systems after unique cooling_id collapse",
                    value_b=_num(rec.n_cooling_systems_max),
                    difference=_num(rec.n_generator_rows_max) - _num(rec.n_cooling_systems_max),
                    reason_flagged="cooling-detail repeats generator/boiler links on a cooling system; water is collapsed to unique cooling_id",
                    agent_interpretation="Structural/expected. Existing aggregation sums unique cooling-system water and hard-fails if those values conflict.",
                    confidence="high",
                    recommended_action="Keep unique cooling-system water. Do not sum water across generator rows.",
                    needs_manual_review=False,
                )
            )
    return rows


def qc_failures(checks: pd.DataFrame) -> list[dict]:
    rows = []
    failed = checks[checks["status"].astype(str).str.upper().eq("FAIL")]
    for rec in failed.itertuples(index=False):
        logic_error = rec.check in {
            "eia860_operating_retirement_dates_consistent_with_observations",
            "no_second_operating_time_multiplication",
            "campd_gross_generation_equals_load_times_operating_time",
        }
        rows.append(
            row(
                issue_type="qc_check_fail",
                root_cause_class="qc_logic_error" if logic_error else "unresolved_source_conflict",
                root_cause_id=f"qc_{rec.check}",
                severity="high",
                source_a="oregon_generator_data_checks.csv",
                value_a=rec.check,
                source_b="status",
                value_b=rec.status,
                reason_flagged=str(rec.detail),
                agent_interpretation="Existing QC recorded FAIL after the pipeline repair.",
                confidence="high",
                recommended_action="Keep the FAIL visible. Do not treat the pipeline as having silently resolved it.",
                needs_manual_review=True,
            )
        )
    return rows


def build() -> tuple[pd.DataFrame, pd.DataFrame]:
    audit = pd.read_csv(OUTPUTS / "oregon_epa_eia_crosswalk_audit.csv")
    flags = pd.read_csv(OUTPUTS / "oregon_eia860_observation_flags.csv")
    compare = pd.read_csv(OUTPUTS / "oregon_campd_eia923_generation_compare.csv")
    checks = pd.read_csv(OUTPUTS / "oregon_generator_data_checks.csv")
    cool = pd.read_csv(PROCESSED / "eia923_cooling_operations.csv")
    campd_m = pd.read_csv(PROCESSED / "campd_or_plant_monthly.csv")
    analysis = pd.read_csv(PROCESSED / "oregon_generator_externalities_monthly.csv")
    names = plant_name_map(campd_m, analysis, cool)
    annual_recon = pd.read_csv(OUT_ANNUAL_RECON) if OUT_ANNUAL_RECON.exists() else pd.DataFrame()

    records = []
    records.extend(crosswalk_exceptions(audit))
    records.extend(temporal_exceptions(flags, names))
    records.extend(generation_outliers(compare, audit))
    records.extend(annual_reconciliation_exceptions(annual_recon, audit))
    records.extend(cooling_exceptions(cool, names))
    records.extend(qc_failures(checks))

    report = pd.DataFrame(records, columns=COLS)
    report["needs_manual_review"] = report["needs_manual_review"].astype(bool)
    summary = (
        report.groupby(["root_cause_class", "issue_type"], dropna=False)
        .agg(
            n_raw_flag_rows=("issue_type", "size"),
            n_unique_root_causes=("root_cause_id", "nunique"),
            n_needs_manual_review=("needs_manual_review", "sum"),
        )
        .reset_index()
        .sort_values(["root_cause_class", "issue_type"])
    )
    return report, summary


def main() -> None:
    report, summary = build()
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    report.to_csv(OUT_REPORT, index=False)
    summary.to_csv(OUT_SUMMARY, index=False)
    by_class = report.groupby("root_cause_class").size().to_dict()
    n_review = int(report["needs_manual_review"].sum())
    n_review_causes = int(report.loc[report["needs_manual_review"], "root_cause_id"].nunique())
    print("exceptions_by_root_cause_class:")
    for k, v in sorted(by_class.items()):
        print(f"  {k}: {v}")
    print(f"n_raw_flag_rows: {len(report)}")
    print(f"n_unique_root_causes: {int(report['root_cause_id'].nunique())}")
    print(f"needs_manual_review_rows: {n_review}")
    print(f"needs_manual_review_root_causes: {n_review_causes}")
    print(f"report: {OUT_REPORT}")
    print(f"summary: {OUT_SUMMARY}")


if __name__ == "__main__":
    main()
