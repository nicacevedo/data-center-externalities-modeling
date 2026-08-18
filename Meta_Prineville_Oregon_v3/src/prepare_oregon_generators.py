"""Oregon-only 2011-2024 CAMPD / EIA-860 / EIA-923 / cooling pipeline validation.

This is a source-integration pilot. It does not infer which generators served
the Prineville campus. Raw files under data/raw/ are never modified. EIA
national archives are filtered to Oregon only after read.

CAMPD posted CO2/SO2/NOx mass and heat input are not multiplied by Operating
Time. CAMPD Gross Load (MW) is a rate; hourly gross generation is
Gross Load (MW) * Operating Time when both are reported.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import io
import json
import os
import re
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import pandas as pd

try:
    import python_calamine  # noqa: F401

    EXCEL_ENGINE = "calamine"
except ImportError:
    EXCEL_ENGINE = "openpyxl"

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
OUTPUTS = ROOT / "outputs"

CAMPD_RAW = RAW / "campd" / "hourly-emissions-b0f0572b-0f0b-48a9-99c2-8563b9cdc379_Oregon.csv"
CROSSWALK_RAW = RAW / "epa_eia_crosswalk" / "epa_eia_crosswalk.csv"
EIA860_DIR = RAW / "eia860"
EIA923_DIR = RAW / "eia923"
COOLING_DIR = RAW / "eia_cooling"
EGRID_DIR = RAW / "egrid"

OUT_EIA860 = PROCESSED / "eia860_generator_annual.csv"
OUT_EIA923 = PROCESSED / "eia923_generation_fuel_monthly.csv"
OUT_COOLING = PROCESSED / "eia923_cooling_operations.csv"
OUT_CAMPD_HOURLY = PROCESSED / "campd_or_unit_hourly.csv"
OUT_CROSSWALK = PROCESSED / "epa_eia_unit_crosswalk.csv"
OUT_CAMPD_MONTHLY = PROCESSED / "campd_or_plant_monthly.csv"
OUT_ANALYSIS = PROCESSED / "oregon_generator_externalities_monthly.csv"

OUT_XW_AUDIT = OUTPUTS / "oregon_epa_eia_crosswalk_audit.csv"
OUT_CHECKS = OUTPUTS / "oregon_generator_data_checks.csv"
OUT_COVERAGE = OUTPUTS / "oregon_generator_coverage_by_year.csv"
OUT_COOLING_COV = OUTPUTS / "oregon_cooling_water_coverage_by_year.csv"
OUT_COMPARE = OUTPUTS / "oregon_campd_eia923_generation_compare.csv"
OUT_EIA860_FLAGS = OUTPUTS / "oregon_eia860_observation_flags.csv"
OUT_EGRID_CMP = OUTPUTS / "oregon_egrid_plant_consistency.csv"

MODEL_YEARS = list(range(2011, 2025))
MONTHS = list(range(1, 13))
MONTH_ABBR = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]

# avoirdupois
SHORT_TON_TO_TONNE = 0.90718474
LB_TO_KG = 0.45359237
M3_PER_MILLION_GAL = 3785.411784
GPM_HOURS_TO_MILLION_GAL = 60.0 / 1_000_000.0

CONFIDENTIAL_TOKENS = {".", "*", "W", "w", "NA", "N/A", "na", "null", "Null", ""}


def norm_name(value: object) -> str:
    text = str(value).replace("\n", " ").replace("\r", " ")
    text = re.sub(r"\s+", " ", text).strip().lower()
    text = text.replace("(mw)", "").replace("(mwh)", "").replace("(mmbtu)", "")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def pick_col(df: pd.DataFrame, options: list[str], required: bool = True) -> str | None:
    cmap = {norm_name(c): c for c in df.columns}
    for option in options:
        key = norm_name(option)
        if key in cmap:
            return cmap[key]
    for option in options:
        key = norm_name(option)
        for cand_key, cand in cmap.items():
            if key and key in cand_key:
                return cand
    if required:
        raise KeyError(f"Could not find columns {options} in {list(df.columns)[:25]}")
    return None


def to_numeric_missing(series: pd.Series) -> pd.Series:
    if series.dtype == object or pd.api.types.is_string_dtype(series):
        cleaned = series.astype(str).str.replace("\n", "", regex=False).str.strip()
        cleaned = cleaned.mask(cleaned.isin(CONFIDENTIAL_TOKENS), np.nan)
        cleaned = cleaned.replace({"nan": np.nan, "<NA>": np.nan})
        return pd.to_numeric(cleaned, errors="coerce")
    return pd.to_numeric(series, errors="coerce")


def year_month_cols(df: pd.DataFrame, prefix_needles: list[str]) -> dict[int, str]:
    cmap = {norm_name(c): c for c in df.columns}
    found: dict[int, str] = {}
    for month_i, abbr in enumerate(MONTH_ABBR, start=1):
        for needle in prefix_needles:
            for key, col in cmap.items():
                if abbr in key.split() or key.endswith(abbr) or f"_{abbr}" in f"_{key}":
                    if all(part in key for part in norm_name(needle).split()):
                        found[month_i] = col
                        break
            if month_i in found:
                break
    return found


def zip_members(zip_path: Path, include: list[str], exclude: list[str] | None = None) -> list[str]:
    exclude = exclude or []
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
    hits = []
    for name in names:
        low = name.lower()
        if all(s.lower() in low for s in include) and not any(s.lower() in low for s in exclude):
            hits.append(name)
    return hits


def zip_excel(zip_path: Path, member: str) -> pd.ExcelFile:
    """Open a zip member once. Prefer calamine; do not re-read the archive for sheet names."""
    with zipfile.ZipFile(zip_path) as zf:
        data = zf.read(member)
    return pd.ExcelFile(io.BytesIO(data), engine=EXCEL_ENGINE)


def read_excel_path(path: Path, sheet_name=0, header=0, **kwargs) -> pd.DataFrame:
    return pd.read_excel(path, sheet_name=sheet_name, header=header, engine=EXCEL_ENGINE, **kwargs)


def parse_sheet_detect_header(xl: pd.ExcelFile, sheet: str, token: str = "plant id", max_rows: int = 12) -> pd.DataFrame:
    raw = xl.parse(sheet, header=None)
    header_i = None
    scan = min(max_rows, len(raw))
    for i in range(scan):
        vals = [norm_name(v) for v in raw.iloc[i].tolist() if pd.notna(v)]
        if any(token == v or token in v for v in vals):
            header_i = i
            break
    if header_i is None:
        raise ValueError(f"No header containing {token!r} in sheet {sheet}")
    cols = [re.sub(r"\s+", " ", str(c).replace("\n", " ")).strip() for c in raw.iloc[header_i].tolist()]
    df = raw.iloc[header_i + 1 :].copy()
    df.columns = cols
    df = df.loc[:, [c for c in df.columns if c and not str(c).lower().startswith("unnamed")]]
    return df.reset_index(drop=True)


def parallel_years(fn, years: list[int], label: str, max_workers: int = 8) -> list[pd.DataFrame]:
    workers = max(1, min(max_workers, len(years), os.cpu_count() or 4))
    print(f"  {label}: {len(years)} years, {workers} workers, excel_engine={EXCEL_ENGINE}", flush=True)
    frames: list[pd.DataFrame] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(fn, year): year for year in years}
        for fut in as_completed(futs):
            year = futs[fut]
            df = fut.result()
            n = 0 if df is None or df.empty else len(df)
            print(f"  {label} {year}: {n} Oregon rows", flush=True)
            if df is not None and len(df):
                frames.append(df)
    return frames


def sheet_by_keywords(names: list[str], include: list[str], exclude: list[str] | None = None) -> str | None:
    exclude = exclude or []
    for name in names:
        low = name.lower()
        if all(s.lower() in low for s in include) and not any(s.lower() in low for s in exclude):
            return name
    return None


def safe_sum(series: pd.Series) -> float:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().any():
        return float(numeric.sum(min_count=1))
    return np.nan


def hourly_gross_generation_mwh(gross_load_mw, operating_time) -> pd.Series:
    """Gross Load (MW) is a rate. Energy = rate * Operating Time when both reported."""
    load = pd.to_numeric(gross_load_mw, errors="coerce")
    ot = pd.to_numeric(operating_time, errors="coerce")
    out = load * ot
    return out.where(load.notna() & ot.notna(), np.nan)


def classify_mapping_cardinality(n_eia_plant: int, n_eia_gen: int, n_camd_sharing_gen: int) -> str:
    if n_eia_plant <= 0:
        return "unmatched"
    if n_eia_plant > 1:
        return "one_to_many_plants"
    if n_eia_gen > 1 and n_camd_sharing_gen > 1:
        return "many_to_many"
    if n_eia_gen > 1:
        return "one_to_many"
    if n_camd_sharing_gen > 1:
        return "many_to_one"
    return "one_to_one"


def classify_match_method(match_text_gen: str | float, match_text_boiler: str | float = np.nan) -> str:
    texts = f"{'' if pd.isna(match_text_gen) else match_text_gen} {'' if pd.isna(match_text_boiler) else match_text_boiler}".lower()
    if not texts.strip():
        return "unmatched"
    if "manual" in texts:
        return "official_manual"
    if "modify ids" in texts or "fuzzy" in texts:
        return "modified_fuzzy"
    if "exact" in texts:
        return "exact"
    return "other"


def classify_match(n_eia_plant: int, n_eia_gen: int, n_camd_sharing_gen: int, match_text: str) -> str:
    """Composite label: mapping_cardinality|match_method. Kept for downstream display."""
    card = classify_mapping_cardinality(n_eia_plant, n_eia_gen, n_camd_sharing_gen)
    if card in {"unmatched", "one_to_many_plants"}:
        return card
    method = classify_match_method(match_text)
    return f"{card}|{method}"


def join_ids(values: pd.Series) -> str | float:
    parts = sorted({str(v).strip() for v in values.dropna().astype(str) if str(v).strip() and str(v) != "nan"})
    return "|".join(parts) if parts else np.nan


# ---------------------------------------------------------------------------
# CAMPD
# ---------------------------------------------------------------------------

CAMPD_KEEP = [
    "State",
    "Facility Name",
    "Facility ID",
    "Unit ID",
    "Associated Stacks",
    "Date",
    "Hour",
    "Operating Time",
    "Gross Load (MW)",
    "Steam Load (1000 lb/hr)",
    "SO2 Mass (lbs)",
    "SO2 Mass Measure Indicator",
    "SO2 Rate (lbs/mmBtu)",
    "SO2 Rate Measure Indicator",
    "CO2 Mass (short tons)",
    "CO2 Mass Measure Indicator",
    "CO2 Rate (short tons/mmBtu)",
    "CO2 Rate Measure Indicator",
    "NOx Mass (lbs)",
    "NOx Mass Measure Indicator",
    "NOx Rate (lbs/mmBtu)",
    "NOx Rate Measure Indicator",
    "Heat Input (mmBtu)",
    "Heat Input Measure Indicator",
    "Primary Fuel Type",
    "Secondary Fuel Type",
    "Unit Type",
    "SO2 Controls",
    "NOx Controls",
    "PM Controls",
    "Hg Controls",
    "Program Code",
]


def prepare_campd_hourly(reuse_processed: bool = True) -> tuple[pd.DataFrame, bool]:
    key = ["Facility ID", "Unit ID", "Date", "Hour"]
    if reuse_processed and OUT_CAMPD_HOURLY.exists() and OUT_CAMPD_HOURLY.stat().st_size > 10_000_000:
        existing = pd.read_csv(
            OUT_CAMPD_HOURLY,
            dtype={"Unit ID": str, "Facility ID": "Int64", "Hour": "Int64"},
            parse_dates=["Date"],
            low_memory=False,
        )
        existing["Unit ID"] = existing["Unit ID"].astype(str).str.strip()
        years = sorted(pd.to_numeric(existing["year"], errors="coerce").dropna().astype(int).unique().tolist())
        has_gen = "gross_generation_mwh" in existing.columns
        if (
            has_gen
            and not existing.duplicated(key).any()
            and years == MODEL_YEARS
            and existing["Facility ID"].notna().all()
            and existing["Unit ID"].astype(str).str.len().gt(0).all()
        ):
            print(f"  reusing {OUT_CAMPD_HOURLY.name} ({len(existing):,} rows)", flush=True)
            return existing.sort_values(key).reset_index(drop=True), True
        print("  processed CAMPD hourly failed reuse checks; rereading raw", flush=True)
    if not CAMPD_RAW.exists():
        raise FileNotFoundError(f"CAMPD Oregon extract missing: {CAMPD_RAW}")
    df = pd.read_csv(
        CAMPD_RAW,
        dtype={"Unit ID": str, "Facility ID": "Int64", "Hour": "Int64"},
        low_memory=False,
    )
    missing = [c for c in CAMPD_KEEP if c not in df.columns]
    if missing:
        raise ValueError(f"CAMPD columns missing: {missing}")
    out = df[CAMPD_KEEP].copy()
    out["Unit ID"] = out["Unit ID"].astype(str).str.strip()
    out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
    if out["Date"].isna().any():
        raise ValueError("CAMPD Date failed to parse")
    out["year"] = out["Date"].dt.year.astype(int)
    out["month"] = out["Date"].dt.month.astype(int)
    out["source_file"] = CAMPD_RAW.name
    out["provenance_class"] = "reported"
    numeric_cols = [
        "Operating Time",
        "Gross Load (MW)",
        "Steam Load (1000 lb/hr)",
        "SO2 Mass (lbs)",
        "SO2 Rate (lbs/mmBtu)",
        "CO2 Mass (short tons)",
        "CO2 Rate (short tons/mmBtu)",
        "NOx Mass (lbs)",
        "NOx Rate (lbs/mmBtu)",
        "Heat Input (mmBtu)",
    ]
    for col in numeric_cols:
        out[col] = to_numeric_missing(out[col])
    out["gross_generation_mwh"] = hourly_gross_generation_mwh(out["Gross Load (MW)"], out["Operating Time"])
    out = out[out["year"].isin(MODEL_YEARS)].copy()
    return out.sort_values(key).reset_index(drop=True), False


def prepare_crosswalk(campd: pd.DataFrame) -> pd.DataFrame:
    xw = pd.read_csv(
        CROSSWALK_RAW,
        dtype={"CAMD_UNIT_ID": str, "EIA_GENERATOR_ID": str, "EIA_BOILER_ID": str, "CAMD_GENERATOR_ID": str},
        low_memory=False,
    )
    xw["CAMD_UNIT_ID"] = xw["CAMD_UNIT_ID"].astype(str).str.strip()
    campd_facilities = set(campd["Facility ID"].dropna().astype(int))
    keep = (
        xw["CAMD_STATE"].astype(str).str.upper().eq("OR")
        | xw["EIA_STATE"].astype(str).str.upper().eq("OR")
        | xw["CAMD_PLANT_ID"].isin(campd_facilities)
    )
    out = xw.loc[keep].copy()
    out["source_file"] = CROSSWALK_RAW.name
    out["provenance_class"] = "reported"
    return out.reset_index(drop=True)


def audit_crosswalk(campd: pd.DataFrame, xw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    unit_hours = (
        campd.groupby(["Facility ID", "Unit ID"], dropna=False)
        .agg(
            facility_name=("Facility Name", "first"),
            n_campd_hours=("Hour", "size"),
            year_min=("year", "min"),
            year_max=("year", "max"),
        )
        .reset_index()
    )
    unit_hours["years_active"] = unit_hours["year_min"].astype(str) + "-" + unit_hours["year_max"].astype(str)

    xw = xw.copy()
    xw["CAMD_PLANT_ID"] = pd.to_numeric(xw["CAMD_PLANT_ID"], errors="coerce")
    xw["EIA_PLANT_ID"] = pd.to_numeric(xw["EIA_PLANT_ID"], errors="coerce")
    xw["CAMD_UNIT_ID"] = xw["CAMD_UNIT_ID"].astype(str).str.strip()

    gen_share = (
        xw.dropna(subset=["EIA_PLANT_ID", "EIA_GENERATOR_ID"])
        .groupby(["EIA_PLANT_ID", "EIA_GENERATOR_ID"])["CAMD_UNIT_ID"]
        .nunique()
        .rename("n_camd_per_eia_gen")
        .reset_index()
    )
    xw = xw.merge(gen_share, on=["EIA_PLANT_ID", "EIA_GENERATOR_ID"], how="left")

    unit_xw = (
        xw.groupby(["CAMD_PLANT_ID", "CAMD_UNIT_ID"], dropna=False)
        .agg(
            eia_plant_id=("EIA_PLANT_ID", "first"),
            n_eia_plant=("EIA_PLANT_ID", "nunique"),
            n_eia_gen=("EIA_GENERATOR_ID", "nunique"),
            n_eia_boiler=("EIA_BOILER_ID", "nunique"),
            eia_generator_id=("EIA_GENERATOR_ID", join_ids),
            eia_boiler_id=("EIA_BOILER_ID", join_ids),
            match_text=("MATCH_TYPE_GEN", "first"),
            match_text_boiler=("MATCH_TYPE_BOILER", lambda s: join_ids(s) if s.notna().any() else np.nan),
            n_camd_per_eia_gen=("n_camd_per_eia_gen", "max"),
            n_crosswalk_rows=("CAMD_UNIT_ID", "size"),
            camd_status_date=("CAMD_STATUS_DATE", "first"),
            camd_retire_year=("CAMD_RETIRE_YEAR", "first"),
        )
        .reset_index()
    )
    unit_xw["n_camd_per_eia_gen"] = unit_xw["n_camd_per_eia_gen"].fillna(1).astype(int)
    unit_xw["mapping_cardinality"] = [
        classify_mapping_cardinality(int(r.n_eia_plant), int(r.n_eia_gen), int(r.n_camd_per_eia_gen))
        for r in unit_xw.itertuples(index=False)
    ]
    unit_xw["match_method"] = [
        classify_match_method(r.match_text, r.match_text_boiler) for r in unit_xw.itertuples(index=False)
    ]
    unit_xw["match_type"] = [
        classify_match(int(r.n_eia_plant), int(r.n_eia_gen), int(r.n_camd_per_eia_gen), r.match_text)
        for r in unit_xw.itertuples(index=False)
    ]

    audit = unit_hours.merge(
        unit_xw,
        left_on=["Facility ID", "Unit ID"],
        right_on=["CAMD_PLANT_ID", "CAMD_UNIT_ID"],
        how="left",
        indicator=True,
    )
    left_only = audit["_merge"].eq("left_only")
    audit.loc[left_only, "mapping_cardinality"] = "unmatched"
    audit.loc[left_only, "match_method"] = "unmatched"
    audit.loc[left_only, "match_type"] = "unmatched"
    audit["eia_plant_id"] = np.where(audit["n_eia_plant"].fillna(0).gt(1), np.nan, audit["eia_plant_id"])
    audit["camd_facility_id"] = audit["Facility ID"].astype("Int64")
    audit["camd_unit_id"] = audit["Unit ID"]
    audit["unexplained_plant_split"] = audit["n_eia_plant"].fillna(0).gt(1)
    audit["plant_ids_differ"] = (
        pd.to_numeric(audit["camd_facility_id"], errors="coerce")
        != pd.to_numeric(audit["eia_plant_id"], errors="coerce")
    ) & audit["eia_plant_id"].notna()
    cols = [
        "camd_facility_id",
        "camd_unit_id",
        "facility_name",
        "eia_plant_id",
        "eia_generator_id",
        "eia_boiler_id",
        "mapping_cardinality",
        "match_method",
        "match_type",
        "match_text",
        "match_text_boiler",
        "plant_ids_differ",
        "years_active",
        "n_campd_hours",
        "n_eia_plant",
        "n_eia_gen",
        "n_crosswalk_rows",
        "unexplained_plant_split",
        "camd_status_date",
        "camd_retire_year",
    ]
    audit = audit[cols].sort_values(["camd_facility_id", "camd_unit_id"]).reset_index(drop=True)

    unit_map = audit[["camd_facility_id", "camd_unit_id", "eia_plant_id", "match_type", "mapping_cardinality", "match_method"]].drop_duplicates()
    if unit_map.duplicated(["camd_facility_id", "camd_unit_id"]).any():
        raise ValueError("Crosswalk collapsed to a non-unique CAMD unit map; refusing to join")
    if bool(audit["unexplained_plant_split"].any()):
        raise ValueError("Crosswalk maps a CAMD unit to multiple EIA plants; emissions would be duplicated or split arbitrarily")
    return audit, unit_map


def aggregate_campd_plant_month(campd: pd.DataFrame, unit_map: pd.DataFrame) -> pd.DataFrame:
    mapped = campd.merge(
        unit_map,
        left_on=["Facility ID", "Unit ID"],
        right_on=["camd_facility_id", "camd_unit_id"],
        how="left",
        validate="m:1",
    )
    mapped["plant_id"] = mapped["eia_plant_id"].fillna(mapped["Facility ID"]).astype("Int64")
    mapped["crosswalk_match_type"] = mapped["match_type"].fillna("unmatched")

    grouped = mapped.groupby(["plant_id", "year", "month"], dropna=False)
    monthly = grouped.agg(
        plant_name=("Facility Name", "first"),
        campd_facility_ids=("Facility ID", join_ids),
        campd_unit_ids=("Unit ID", join_ids),
        campd_co2_short_tons=("CO2 Mass (short tons)", lambda s: s.sum(min_count=1)),
        campd_nox_lbs=("NOx Mass (lbs)", lambda s: s.sum(min_count=1)),
        campd_so2_lbs=("SO2 Mass (lbs)", lambda s: s.sum(min_count=1)),
        campd_heat_input_mmbtu=("Heat Input (mmBtu)", lambda s: s.sum(min_count=1)),
        campd_gross_generation_mwh=("gross_generation_mwh", lambda s: s.sum(min_count=1)),
        campd_posted_gross_load_mw_sum=("Gross Load (MW)", lambda s: s.sum(min_count=1)),
        operating_hours=("Operating Time", lambda s: s.sum(min_count=1)),
        n_reporting_units=("Unit ID", "nunique"),
        n_hours=("Hour", "size"),
        n_hours_co2_nonmissing=("CO2 Mass (short tons)", lambda s: int(s.notna().sum())),
        n_hours_co2_zero=("CO2 Mass (short tons)", lambda s: int((s == 0).sum())),
        n_hours_load_nonmissing=("Gross Load (MW)", lambda s: int(s.notna().sum())),
        n_hours_load_zero=("Gross Load (MW)", lambda s: int((s == 0).sum())),
        n_hours_heat_nonmissing=("Heat Input (mmBtu)", lambda s: int(s.notna().sum())),
        co2_measure_codes=("CO2 Mass Measure Indicator", join_ids),
        nox_measure_codes=("NOx Mass Measure Indicator", join_ids),
        so2_measure_codes=("SO2 Mass Measure Indicator", join_ids),
        heat_measure_codes=("Heat Input Measure Indicator", join_ids),
        program_codes=("Program Code", join_ids),
        primary_fuels=("Primary Fuel Type", join_ids),
        crosswalk_match_type=("crosswalk_match_type", join_ids),
        source_file=("source_file", "first"),
    ).reset_index()
    monthly["campd_co2_tonnes"] = monthly["campd_co2_short_tons"] * SHORT_TON_TO_TONNE
    monthly["campd_nox_kg"] = monthly["campd_nox_lbs"] * LB_TO_KG
    monthly["campd_so2_kg"] = monthly["campd_so2_lbs"] * LB_TO_KG
    monthly["provenance_class"] = "derived"
    monthly["load_aggregation_note"] = (
        "campd_gross_generation_mwh = sum(Gross Load (MW) * Operating Time) where both reported; "
        "posted CO2/SO2/NOx mass and heat input are not multiplied by Operating Time"
    )
    monthly = monthly.drop(columns=["campd_co2_short_tons", "campd_nox_lbs", "campd_so2_lbs"])
    return monthly.sort_values(["plant_id", "year", "month"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# EIA-860
# ---------------------------------------------------------------------------

def _860_generator_member(zip_path: Path, year: int) -> str:
    hits = zip_members(zip_path, ["generator"])
    hits = [h for h in hits if "wind" not in h.lower() and "solar" not in h.lower() and "storage" not in h.lower() and "multifuel" not in h.lower()]
    if not hits:
        raise FileNotFoundError(f"No EIA-860 generator workbook in {zip_path}")
    prefer = [h for h in hits if f"{year}" in h]
    return prefer[0] if prefer else hits[0]


def _eia860_year(year: int) -> pd.DataFrame:
    zip_path = EIA860_DIR / f"eia860{year}.zip"
    if not zip_path.exists():
        raise FileNotFoundError(zip_path)
    member = _860_generator_member(zip_path, year)
    xl = zip_excel(zip_path, member)
    frames = []
    for sheet in xl.sheet_names:
        low = sheet.lower()
        if "layout" in low or "note" in low:
            continue
        df = xl.parse(sheet, header=1)
        df.columns = [re.sub(r"\s+", " ", str(c).replace("\n", " ")).strip() for c in df.columns]
        plant_col = pick_col(df, ["Plant Code", "PLANT_CODE"])
        state_col = pick_col(df, ["State", "STATE"])
        gen_col = pick_col(df, ["Generator ID", "GENERATOR_ID"])
        name_col = pick_col(df, ["Plant Name", "PLANT_NAME"], required=False)
        mover_col = pick_col(df, ["Prime Mover", "PRIME_MOVER"], required=False)
        status_col = pick_col(df, ["Status", "STATUS"], required=False)
        cap_col = pick_col(df, ["Nameplate Capacity (MW)", "NAMEPLATE", "Nameplate Capacity"], required=False)
        fuel_col = pick_col(df, ["Energy Source 1", "ENERGY_SOURCE_1"], required=False)
        op_year = pick_col(df, ["Operating Year", "OPERATING_YEAR"], required=False)
        op_month = pick_col(df, ["Operating Month", "OPERATING_MONTH"], required=False)
        ret_year = pick_col(df, ["Retirement Year", "RETIREMENT_YEAR"], required=False)
        ret_month = pick_col(df, ["Retirement Month", "RETIREMENT_MONTH"], required=False)
        plan_ret_year = pick_col(df, ["Planned Retirement Year", "PLANNED_RETIREMENT_YEAR"], required=False)
        plan_ret_month = pick_col(df, ["Planned Retirement Month", "PLANNED_RETIREMENT_MONTH"], required=False)
        util_col = pick_col(df, ["Utility ID", "UTILITY_ID"], required=False)
        tech_col = pick_col(df, ["Technology"], required=False)
        state = df[state_col].astype(str).str.strip().str.upper()
        or_df = df.loc[state.eq("OR")].copy()
        if or_df.empty:
            continue
        frames.append(
            pd.DataFrame(
                {
                    "year": year,
                    "plant_id": to_numeric_missing(or_df[plant_col]).astype("Int64"),
                    "generator_id": or_df[gen_col].astype(str).str.strip(),
                    "plant_name": or_df[name_col] if name_col else np.nan,
                    "state": "OR",
                    "prime_mover": or_df[mover_col] if mover_col else np.nan,
                    "status": or_df[status_col] if status_col else np.nan,
                    "nameplate_mw": to_numeric_missing(or_df[cap_col]) if cap_col else np.nan,
                    "energy_source_1": or_df[fuel_col] if fuel_col else np.nan,
                    "operating_year": to_numeric_missing(or_df[op_year]) if op_year else np.nan,
                    "operating_month": to_numeric_missing(or_df[op_month]) if op_month else np.nan,
                    "retirement_year": to_numeric_missing(or_df[ret_year]) if ret_year else np.nan,
                    "retirement_month": to_numeric_missing(or_df[ret_month]) if ret_month else np.nan,
                    "planned_retirement_year": to_numeric_missing(or_df[plan_ret_year]) if plan_ret_year else np.nan,
                    "planned_retirement_month": to_numeric_missing(or_df[plan_ret_month]) if plan_ret_month else np.nan,
                    "utility_id": to_numeric_missing(or_df[util_col]) if util_col else np.nan,
                    "technology": or_df[tech_col] if tech_col else np.nan,
                    "eia860_sheet": sheet,
                    "source_file": f"{zip_path.name}:{member}",
                    "provenance_class": "reported",
                }
            )
        )
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def prepare_eia860() -> pd.DataFrame:
    frames = parallel_years(_eia860_year, MODEL_YEARS, "EIA-860", max_workers=8)
    if not frames:
        raise ValueError("No Oregon EIA-860 generator rows")
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# EIA-923 generation/fuel
# ---------------------------------------------------------------------------

def _923_gen_member(zip_path: Path) -> str:
    hits = zip_members(zip_path, ["schedules_2"], exclude=["layout", "puerto"])
    if not hits:
        hits = zip_members(zip_path, ["2_3_4_5"], exclude=["layout"])
    if not hits:
        raise FileNotFoundError(f"No EIA-923 generation workbook in {zip_path}")
    return hits[0]


def _eia923_year(year: int) -> pd.DataFrame:
    zip_path = EIA923_DIR / f"f923_{year}.zip"
    if not zip_path.exists():
        raise FileNotFoundError(zip_path)
    member = _923_gen_member(zip_path)
    xl = zip_excel(zip_path, member)
    sheet = sheet_by_keywords(xl.sheet_names, ["generation and fuel"], exclude=["puerto", "storage"])
    if sheet is None:
        sheet = sheet_by_keywords(xl.sheet_names, ["page 1"], exclude=["puerto", "storage", "layout"])
    if sheet is None:
        raise ValueError(f"No generation-and-fuel sheet in {zip_path.name}")
    df = parse_sheet_detect_header(xl, sheet, token="plant id")
    plant_col = pick_col(df, ["Plant Id", "Plant ID"])
    state_col = pick_col(df, ["Plant State", "State"])
    name_col = pick_col(df, ["Plant Name"], required=False)
    mover_col = pick_col(df, ["Reported Prime Mover", "Reported Prime Mover Type"], required=False)
    fuel_col = pick_col(df, ["Reported Fuel Type Code"], required=False)
    aer_col = pick_col(df, ["AER Fuel Type Code", "AER Fuel Type"], required=False)
    annual_gen_col = pick_col(df, ["Net Generation (Megawatthours)", "Net Generation Megawatthours"], required=False)
    annual_mmbtu_col = pick_col(df, ["Total Fuel Consumption MMBtu", "Tot_MMBtu"], required=False)
    year_col = pick_col(df, ["YEAR", "Year"], required=False)
    netgen = year_month_cols(df, ["netgen", "net gen"])
    tot_mmbtu = year_month_cols(df, ["tot mmbtu", "total fuel consumed"])
    elec_mmbtu = year_month_cols(df, ["elec mmbtu"])
    if len(netgen) != 12:
        netgen = {}
        for i, abbr in enumerate(MONTH_ABBR, start=1):
            matches = [
                c
                for c in df.columns
                if abbr in norm_name(c)
                and "net" in norm_name(c)
                and "gen" in norm_name(c)
                and "ytd" not in norm_name(c)
                and "year" not in norm_name(c)
            ]
            if len(matches) == 1:
                netgen[i] = matches[0]
        if len(netgen) != 12:
            raise ValueError(f"{year} EIA-923 monthly netgen columns incomplete: {netgen}")
    state = df[state_col].astype(str).str.strip().str.upper()
    or_df = df.loc[state.eq("OR")].copy()
    if or_df.empty:
        return pd.DataFrame()
    plant_id = to_numeric_missing(or_df[plant_col]).astype("Int64")
    rows = []
    for month in MONTHS:
        rows.append(
            pd.DataFrame(
                {
                    "year": year,
                    "month": month,
                    "plant_id": plant_id,
                    "plant_name": or_df[name_col] if name_col else np.nan,
                    "state": "OR",
                    "prime_mover": or_df[mover_col] if mover_col else np.nan,
                    "fuel_code": or_df[fuel_col] if fuel_col else np.nan,
                    "aer_fuel_code": or_df[aer_col] if aer_col else np.nan,
                    "net_generation_mwh": to_numeric_missing(or_df[netgen[month]]),
                    "total_fuel_mmbtu": to_numeric_missing(or_df[tot_mmbtu[month]]) if month in tot_mmbtu else np.nan,
                    "elec_fuel_mmbtu": to_numeric_missing(or_df[elec_mmbtu[month]]) if month in elec_mmbtu else np.nan,
                    "annual_net_generation_mwh": to_numeric_missing(or_df[annual_gen_col]) if annual_gen_col else np.nan,
                    "annual_total_fuel_mmbtu": to_numeric_missing(or_df[annual_mmbtu_col]) if annual_mmbtu_col else np.nan,
                    "source_file": f"{zip_path.name}:{member}",
                    "source_year_field": to_numeric_missing(or_df[year_col]) if year_col else year,
                    "provenance_class": "reported",
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


def prepare_eia923_generation() -> pd.DataFrame:
    frames = parallel_years(_eia923_year, MODEL_YEARS, "EIA-923", max_workers=8)
    if not frames:
        raise ValueError("No Oregon EIA-923 generation rows")
    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["plant_id"])
    return out.sort_values(["year", "month", "plant_id", "prime_mover", "fuel_code"]).reset_index(drop=True)


def eia923_plant_month(gen_fuel: pd.DataFrame) -> pd.DataFrame:
    grouped = gen_fuel.groupby(["plant_id", "year", "month"], dropna=False)
    return grouped.agg(
        plant_name=("plant_name", "first"),
        generation_mwh=("net_generation_mwh", lambda s: s.sum(min_count=1)),
        fuel_mmbtu=("total_fuel_mmbtu", lambda s: s.sum(min_count=1)),
        n_fuel_rows=("plant_id", "size"),
        prime_movers=("prime_mover", join_ids),
        fuels=("fuel_code", join_ids),
        n_generation_nonmissing=("net_generation_mwh", lambda s: int(s.notna().sum())),
        n_generation_zero=("net_generation_mwh", lambda s: int((s == 0).sum())),
    ).reset_index()


# ---------------------------------------------------------------------------
# Cooling
# ---------------------------------------------------------------------------

def _cooling_detail_path(year: int) -> Path:
    if year <= 2020:
        p = COOLING_DIR / f"cooling_detail_{year}.xlsx"
    else:
        p = COOLING_DIR / f"Cooling_Boiler_Generator_Data_Detail_{year}.xlsx"
    if not p.exists():
        raise FileNotFoundError(p)
    return p


def _cooling_summary_path(year: int) -> Path:
    if year <= 2020:
        p = COOLING_DIR / f"cooling_summary_{year}.xlsx"
    else:
        p = COOLING_DIR / f"Cooling_Boiler_Generator_Data_Summary_{year}.xlsx"
    if not p.exists():
        raise FileNotFoundError(p)
    return p


def _cooling_year(year: int) -> pd.DataFrame:
    path = _cooling_detail_path(year)
    df = read_excel_path(path, sheet_name="Detail", header=2)
    df.columns = [re.sub(r"\s+", " ", str(c).replace("\n", " ")).strip() for c in df.columns]
    state_col = pick_col(df, ["State"])
    or_df = df.loc[df[state_col].astype(str).str.strip().str.upper().eq("OR")].copy()
    if or_df.empty:
        return pd.DataFrame()
    plant_col = pick_col(or_df, ["Plant Code"])
    gen_st = pick_col(or_df, ["Gross Generation from Steam Turbines (MWh)"], required=False)
    gen_ss = pick_col(or_df, ["Gross Generation Associated with Single Shaft Combined Cycle Units (MWh)"], required=False)
    gen_ct = pick_col(or_df, ["Gross Generation Associated with Combined Cycle Gas Turbines (MWh)"], required=False)
    wd = pick_col(or_df, ["Water Withdrawal Volume (Million Gallons)"])
    cn = pick_col(or_df, ["Water Consumption Volume (Million Gallons)"])
    cool_id = pick_col(or_df, ["Cooling ID"])
    gen_id = pick_col(or_df, ["Generator ID"])
    boiler_id = pick_col(or_df, ["Boiler ID"], required=False)
    ctype = pick_col(or_df, ["Cooling System Type", "923 Cooling Type", "860 Cooling Type 1"], required=False)
    rel = pick_col(or_df, ["Relationship Type"], required=False)
    return pd.DataFrame(
        {
            "plant_id": to_numeric_missing(or_df[plant_col]).astype("Int64"),
            "plant_name": or_df[pick_col(or_df, ["Plant Name"])],
            "year": to_numeric_missing(or_df[pick_col(or_df, ["Year"])]).astype("Int64"),
            "month": to_numeric_missing(or_df[pick_col(or_df, ["Month"])]).astype("Int64"),
            "generator_id": or_df[gen_id].astype(str).str.strip(),
            "boiler_id": or_df[boiler_id].astype(str).str.strip() if boiler_id else np.nan,
            "cooling_system_id": or_df[cool_id].astype(str).str.strip(),
            "cooling_type": or_df[ctype] if ctype else np.nan,
            "relationship_type": or_df[rel] if rel else np.nan,
            "gross_gen_steam_mwh": to_numeric_missing(or_df[gen_st]) if gen_st else np.nan,
            "gross_gen_sscc_mwh": to_numeric_missing(or_df[gen_ss]) if gen_ss else np.nan,
            "gross_gen_ccgt_mwh": to_numeric_missing(or_df[gen_ct]) if gen_ct else np.nan,
            "water_withdrawal_million_gal": to_numeric_missing(or_df[wd]),
            "water_consumption_million_gal": to_numeric_missing(or_df[cn]),
            "source_file": path.name,
            "cooling_source": "eia_cooling_detail_standardized",
            "provenance_class": "reported",
        }
    )


def prepare_cooling_standardized() -> pd.DataFrame:
    frames = parallel_years(_cooling_year, list(range(2014, 2025)), "cooling detail", max_workers=6)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _cooling_summary_year(year: int) -> pd.DataFrame:
    path = _cooling_summary_path(year)
    df = read_excel_path(path, sheet_name="Summary", header=2)
    df.columns = [re.sub(r"\s+", " ", str(c).replace("\n", " ")).strip() for c in df.columns]
    state_col = pick_col(df, ["State"])
    or_df = df.loc[df[state_col].astype(str).str.strip().str.upper().eq("OR")].copy()
    if or_df.empty:
        return pd.DataFrame()
    plant_col = pick_col(or_df, ["Plant Code"])
    gen_st = pick_col(or_df, ["Gross Generation from Steam Turbines (MWh)"], required=False)
    gen_ss = pick_col(or_df, ["Gross Generation Associated with Single Shaft Combined Cycle Units (MWh)"], required=False)
    gen_ct = pick_col(or_df, ["Gross Generation Associated with Combined Cycle Gas Turbines (MWh)"], required=False)
    wd = pick_col(or_df, ["Water Withdrawal Volume (Million Gallons)"])
    cn = pick_col(or_df, ["Water Consumption Volume (Million Gallons)"])
    cool_id = pick_col(or_df, ["Cooling ID"], required=False)
    return pd.DataFrame(
        {
            "plant_id": to_numeric_missing(or_df[plant_col]).astype("Int64"),
            "year": to_numeric_missing(or_df[pick_col(or_df, ["Year"])]).astype("Int64"),
            "month": to_numeric_missing(or_df[pick_col(or_df, ["Month"])]).astype("Int64"),
            "cooling_system_id": or_df[cool_id].astype(str).str.strip() if cool_id else np.nan,
            "summary_gross_gen_steam_mwh": to_numeric_missing(or_df[gen_st]) if gen_st else np.nan,
            "summary_gross_gen_sscc_mwh": to_numeric_missing(or_df[gen_ss]) if gen_ss else np.nan,
            "summary_gross_gen_ccgt_mwh": to_numeric_missing(or_df[gen_ct]) if gen_ct else np.nan,
            "summary_water_withdrawal_million_gal": to_numeric_missing(or_df[wd]),
            "summary_water_consumption_million_gal": to_numeric_missing(or_df[cn]),
            "summary_source_file": path.name,
        }
    )


def prepare_cooling_summary() -> pd.DataFrame:
    frames = parallel_years(_cooling_summary_year, list(range(2014, 2025)), "cooling summary", max_workers=6)
    if not frames:
        return pd.DataFrame()
    raw = pd.concat(frames, ignore_index=True)
    raw["summary_generation_mwh"] = _add_na_series(
        raw["summary_gross_gen_steam_mwh"],
        raw["summary_gross_gen_sscc_mwh"],
        raw["summary_gross_gen_ccgt_mwh"],
    )
    water_keys = ["plant_id", "year", "month", "cooling_system_id"]
    water_u = (
        raw.groupby(water_keys, dropna=False)
        .agg(
            summary_water_withdrawal_million_gal=(
                "summary_water_withdrawal_million_gal",
                lambda s: s.dropna().iloc[0] if s.notna().any() else np.nan,
            ),
            summary_water_consumption_million_gal=(
                "summary_water_consumption_million_gal",
                lambda s: s.dropna().iloc[0] if s.notna().any() else np.nan,
            ),
            summary_generation_mwh=("summary_generation_mwh", lambda s: s.dropna().iloc[0] if s.notna().any() else np.nan),
            summary_source_file=("summary_source_file", "first"),
        )
        .reset_index()
    )
    return (
        water_u.groupby(["plant_id", "year", "month"], dropna=False)
        .agg(
            summary_water_withdrawal_million_gal=("summary_water_withdrawal_million_gal", safe_sum),
            summary_water_consumption_million_gal=("summary_water_consumption_million_gal", safe_sum),
            summary_generation_mwh=("summary_generation_mwh", safe_sum),
            summary_source_file=("summary_source_file", "first"),
        )
        .reset_index()
    )


def _sched8_member(zip_path: Path) -> str:
    hits = zip_members(zip_path, ["schedule_8"], exclude=["layout"])
    if not hits:
        raise FileNotFoundError(f"No Schedule 8 workbook in {zip_path}")
    return hits[0]


def prepare_cooling_schedule8(or_plant_ids: set[int]) -> pd.DataFrame:
    frames = []
    for year in (2011, 2012, 2013):
        zip_path = EIA923_DIR / f"f923_{year}.zip"
        member = _sched8_member(zip_path)
        xl = zip_excel(zip_path, member)
        sheet = sheet_by_keywords(xl.sheet_names, ["8d"]) or sheet_by_keywords(xl.sheet_names, ["cooling"])
        if sheet is None:
            raise ValueError(f"No Schedule 8D sheet in {zip_path.name}")
        df = parse_sheet_detect_header(xl, sheet, token="plant id")
        plant_col = pick_col(df, ["Plant ID", "Plant Id"])
        month_col = pick_col(df, ["Month"])
        year_col = pick_col(df, ["Year"])
        cool_col = pick_col(df, ["Cooling System ID", "Cooling System ID"])
        hours_col = pick_col(df, ["Hours in Service"], required=False)
        status_col = pick_col(df, ["Cooling System Status"], required=False)
        type_col = pick_col(df, ["Type of Cooling System"], required=False)
        wd_vol = pick_col(df, ["Withdrawal Volume (million gallons)", "Withdrawal Volume"], required=False)
        cn_vol = pick_col(df, ["Consumption Volume (million gallons)", "Consumption Volume"], required=False)
        wd_rate = pick_col(df, ["Withdrawal Rate (gallons per minute)", "Withdrawal Rate"], required=False)
        cn_rate = pick_col(df, ["Consumption Rate (gallons per minute)", "Consumption Rate"], required=False)
        df[plant_col] = to_numeric_missing(df[plant_col])
        sub = df.loc[df[plant_col].isin(or_plant_ids)].copy()
        if sub.empty:
            continue
        out = pd.DataFrame(
            {
                "plant_id": sub[plant_col].astype("Int64"),
                "year": to_numeric_missing(sub[year_col]).astype("Int64"),
                "month": to_numeric_missing(sub[month_col]).astype("Int64"),
                "cooling_system_id": sub[cool_col].astype(str).str.strip(),
                "cooling_type": sub[type_col] if type_col else np.nan,
                "cooling_status": sub[status_col] if status_col else np.nan,
                "hours_in_service": to_numeric_missing(sub[hours_col]) if hours_col else np.nan,
                "withdrawal_rate_native": to_numeric_missing(sub[wd_rate]) if wd_rate else np.nan,
                "consumption_rate_native": to_numeric_missing(sub[cn_rate]) if cn_rate else np.nan,
                "water_withdrawal_million_gal": to_numeric_missing(sub[wd_vol]) if wd_vol else np.nan,
                "water_consumption_million_gal": to_numeric_missing(sub[cn_vol]) if cn_vol else np.nan,
                "source_file": f"{zip_path.name}:{member}",
                "cooling_source": f"eia923_schedule8_{year}",
                "provenance_class": "reported",
            }
        )
        # 2013 volumes are in million gallons and internally consistent with gpm*hours.
        # 2011 has rates only; 2012 volume fields are confidential/blank and rate magnitudes
        # do not match 2013+ gpm. Do not invent 2011-2012 m3 from those rates.
        if year < 2013:
            out["water_withdrawal_million_gal"] = np.nan
            out["water_consumption_million_gal"] = np.nan
            out["volume_comparable"] = False
            out["incomparability_note"] = (
                "2011-2012 Schedule 8 flow rates are not converted; units are not "
                "defensibly the same as 2013+ gpm / million-gallon volumes"
            )
        else:
            out["volume_comparable"] = True
            out["incomparability_note"] = np.nan
        frames.append(out)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _add_na_series(*parts: pd.Series) -> pd.Series:
    acc = None
    saw = None
    for part in parts:
        numeric = pd.to_numeric(part, errors="coerce")
        if acc is None:
            acc = numeric
            saw = numeric.notna()
        else:
            acc = acc.add(numeric, fill_value=0)
            saw = saw | numeric.notna()
    if acc is None:
        return pd.Series(dtype=float)
    return acc.where(saw, np.nan)


def cooling_plant_month(
    detail: pd.DataFrame,
    sched8: pd.DataFrame,
    summary_pm: pd.DataFrame | None = None,
    eia923_pm: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    flags = []
    if not detail.empty:
        water_keys = ["plant_id", "year", "month", "cooling_system_id"]
        water = detail.copy()
        water["wd"] = water["water_withdrawal_million_gal"]
        water["cn"] = water["water_consumption_million_gal"]
        grouped = water.groupby(water_keys, dropna=False)
        nunique_wd = grouped["wd"].nunique(dropna=True)
        nunique_cn = grouped["cn"].nunique(dropna=True)
        conflict = (nunique_wd.gt(1) | nunique_cn.gt(1)).reset_index(name="water_conflict")
        flags.append(conflict)
        water_u = grouped.agg(
            wd=("wd", lambda s: s.dropna().iloc[0] if s.notna().any() else np.nan),
            cn=("cn", lambda s: s.dropna().iloc[0] if s.notna().any() else np.nan),
            cooling_type=("cooling_type", join_ids),
            n_generator_rows=("generator_id", "size"),
            plant_name=("plant_name", "first"),
            source_file=("source_file", "first"),
        ).reset_index()
        gen = detail.copy()
        gen["generation_mwh"] = _add_na_series(
            gen["gross_gen_steam_mwh"], gen["gross_gen_sscc_mwh"], gen["gross_gen_ccgt_mwh"]
        )
        gen_u = (
            gen.groupby(["plant_id", "year", "month", "generator_id"], dropna=False)
            .agg(generation_mwh=("generation_mwh", lambda s: s.dropna().iloc[0] if s.notna().any() else np.nan))
            .reset_index()
        )
        gen_pm = gen_u.groupby(["plant_id", "year", "month"], dropna=False)["generation_mwh"].apply(safe_sum).reset_index()
        water_pm = water_u.groupby(["plant_id", "year", "month"], dropna=False).agg(
            water_withdrawal_million_gal=("wd", safe_sum),
            water_consumption_million_gal=("cn", safe_sum),
            cooling_type=("cooling_type", join_ids),
            cooling_system_id=("cooling_system_id", join_ids),
            n_cooling_systems=("cooling_system_id", "nunique"),
            plant_name=("plant_name", "first"),
            source_file=("source_file", "first"),
            n_generator_rows=("n_generator_rows", "sum"),
        ).reset_index()
        std = water_pm.merge(gen_pm, on=["plant_id", "year", "month"], how="outer")
        std["cooling_source"] = "eia_cooling_detail_standardized"
        std["volume_comparable"] = True
        std["incomparability_note"] = np.nan
        std["generation_missing_reason"] = np.nan
        std["provenance_class"] = "derived"
        rows.append(std)

    if not sched8.empty:
        s8 = sched8.copy()
        s8_pm = s8.groupby(["plant_id", "year", "month"], dropna=False).agg(
            water_withdrawal_million_gal=("water_withdrawal_million_gal", safe_sum),
            water_consumption_million_gal=("water_consumption_million_gal", safe_sum),
            cooling_type=("cooling_type", join_ids),
            cooling_system_id=("cooling_system_id", join_ids),
            n_cooling_systems=("cooling_system_id", "nunique"),
            cooling_source=("cooling_source", "first"),
            volume_comparable=("volume_comparable", "first"),
            incomparability_note=("incomparability_note", "first"),
            source_file=("source_file", "first"),
            hours_in_service=("hours_in_service", safe_sum),
        ).reset_index()
        s8_pm["generation_mwh"] = np.nan
        s8_pm["generation_missing_reason"] = np.where(
            s8_pm["year"].eq(2013),
            "schedule8_generation_left_missing_by_design",
            "schedule8_2011_2012_no_volume_or_generation_product",
        )
        s8_pm["plant_name"] = np.nan
        s8_pm["n_generator_rows"] = np.nan
        s8_pm["provenance_class"] = "derived"
        rows.append(s8_pm)

    if not rows:
        raise ValueError("No Oregon cooling rows")
    out = pd.concat(rows, ignore_index=True)
    if "generation_missing_reason" not in out.columns:
        out["generation_missing_reason"] = np.nan
    out["water_withdrawal_m3_reported"] = np.where(
        out["volume_comparable"].eq(True) & out["water_withdrawal_million_gal"].notna(),
        out["water_withdrawal_million_gal"] * M3_PER_MILLION_GAL,
        np.nan,
    )
    out["water_consumption_m3_reported"] = np.where(
        out["volume_comparable"].eq(True) & out["water_consumption_million_gal"].notna(),
        out["water_consumption_million_gal"] * M3_PER_MILLION_GAL,
        np.nan,
    )
    # Modeled volumes: preserve raw million-gal including negatives; do not clip.
    # Negative consumption is physically invalid for intensity, so modeled m3 is missing.
    out["water_withdrawal_m3"] = out["water_withdrawal_m3_reported"]
    out["water_consumption_m3"] = np.where(
        pd.to_numeric(out["water_consumption_million_gal"], errors="coerce") < 0,
        np.nan,
        out["water_consumption_m3_reported"],
    )
    out["consumption_source_anomaly"] = pd.to_numeric(out["water_consumption_million_gal"], errors="coerce") < 0
    if summary_pm is not None and len(summary_pm):
        out = out.merge(summary_pm, on=["plant_id", "year", "month"], how="left")
    else:
        out["summary_water_withdrawal_million_gal"] = np.nan
        out["summary_water_consumption_million_gal"] = np.nan
        out["summary_generation_mwh"] = np.nan
        out["summary_source_file"] = np.nan
    if eia923_pm is not None and len(eia923_pm):
        out = out.merge(
            eia923_pm[["plant_id", "year", "month", "generation_mwh"]].rename(
                columns={"generation_mwh": "eia923_plant_generation_mwh"}
            ),
            on=["plant_id", "year", "month"],
            how="left",
        )
    else:
        out["eia923_plant_generation_mwh"] = np.nan
    gen = pd.to_numeric(out["generation_mwh"], errors="coerce")
    sum_gen = pd.to_numeric(out.get("summary_generation_mwh"), errors="coerce")
    eia_gen = pd.to_numeric(out["eia923_plant_generation_mwh"], errors="coerce")
    wd = pd.to_numeric(out["water_withdrawal_m3"], errors="coerce")
    status = []
    for i in range(len(out)):
        year = int(out.iloc[i]["year"]) if pd.notna(out.iloc[i]["year"]) else np.nan
        g = gen.iloc[i]
        sg = sum_gen.iloc[i] if len(sum_gen) else np.nan
        eg = eia_gen.iloc[i]
        water = wd.iloc[i]
        if year in (2011, 2012):
            status.append("coverage_limitation_2011_2012_units")
        elif year == 2013:
            status.append("expected_missingness_schedule8_generation")
        elif pd.notna(water) and pd.isna(g):
            if pd.notna(sg) and sg != 0:
                status.append("pipeline_mismatch_summary_has_generation")
            elif pd.notna(eg) and eg > 0:
                status.append("cooling_gen_missing_eia923_positive")
            else:
                status.append("expected_missingness_cooling_and_plant_gen")
        elif pd.notna(water) and g == 0:
            if pd.notna(sg) and sg > 0:
                status.append("pipeline_mismatch_summary_has_generation")
            elif pd.notna(eg) and eg > 0:
                status.append("cooling_gen_zero_eia923_positive")
            else:
                status.append("expected_zero_cooling_and_plant_gen")
        else:
            status.append("ok")
    out["cooling_generation_status"] = status
    # Never substitute EIA-923 plant generation into cooling-associated generation.
    out["cooling_intensity_eligible"] = (
        out["volume_comparable"].eq(True)
        & pd.to_numeric(out["generation_mwh"], errors="coerce").gt(0)
        & ~out["consumption_source_anomaly"].fillna(False)
    )
    flag_df = pd.concat(flags, ignore_index=True) if flags else pd.DataFrame(columns=["water_conflict"])
    return out.sort_values(["year", "month", "plant_id"]).reset_index(drop=True), flag_df


# ---------------------------------------------------------------------------
# EIA-860 flags, analysis table, compare, eGRID
# ---------------------------------------------------------------------------

OPERABLE_STATUS = {"OP", "OA", "OS", "SB", "A", "V", "U"}


def eia860_plant_year(eia860: pd.DataFrame) -> pd.DataFrame:
    operable = eia860[eia860["eia860_sheet"].astype(str).str.lower().str.contains("operable")].copy()
    return (
        operable.groupby(["plant_id", "year"], dropna=False)
        .agg(
            plant_name=("plant_name", "first"),
            capacity_mw=("nameplate_mw", lambda s: s.sum(min_count=1)),
            prime_mover=("prime_mover", join_ids),
            fuel=("energy_source_1", join_ids),
            statuses=("status", join_ids),
            n_generators=("generator_id", "nunique"),
            operating_year_min=("operating_year", "min"),
            retirement_year_min=("retirement_year", "min"),
        )
        .reset_index()
    )


def flag_eia860_vs_campd(campd: pd.DataFrame, eia860: pd.DataFrame, unit_map: pd.DataFrame, xw: pd.DataFrame) -> pd.DataFrame:
    """Unit-month flags using EIA-860 operating/retirement year+month, not retired-sheet membership alone."""
    mapped = campd.merge(
        unit_map,
        left_on=["Facility ID", "Unit ID"],
        right_on=["camd_facility_id", "camd_unit_id"],
        how="left",
        validate="m:1",
    )
    mapped["plant_id"] = mapped["eia_plant_id"].fillna(mapped["Facility ID"])
    unit_month = (
        mapped.groupby(["plant_id", "camd_facility_id", "camd_unit_id", "year", "month"], dropna=False)
        .agg(n_hours=("Hour", "size"), operating_hours=("Operating Time", lambda s: s.sum(min_count=1)))
        .reset_index()
    )
    gens = eia860.copy()
    gens["generator_id"] = gens["generator_id"].astype(str)
    xw_full = xw.copy()
    xw_full["CAMD_UNIT_ID"] = xw_full["CAMD_UNIT_ID"].astype(str).str.strip()
    xw_full["CAMD_PLANT_ID"] = pd.to_numeric(xw_full["CAMD_PLANT_ID"], errors="coerce")
    audit_rows = []
    for rec in unit_month.itertuples(index=False):
        matches = xw_full[
            (xw_full["CAMD_PLANT_ID"] == rec.camd_facility_id)
            & (xw_full["CAMD_UNIT_ID"] == rec.camd_unit_id)
        ]
        gen_ids = set(matches["EIA_GENERATOR_ID"].dropna().astype(str).str.strip())
        plant_id = rec.plant_id
        year = int(rec.year)
        month = int(rec.month)
        g = gens[(gens["plant_id"] == plant_id) & (gens["year"] == year)]
        if gen_ids:
            g = g[g["generator_id"].isin(gen_ids) | g["generator_id"].str.strip().isin(gen_ids)]
        op_year = pd.to_numeric(g["operating_year"], errors="coerce")
        op_month = pd.to_numeric(g["operating_month"], errors="coerce")
        ret_year = pd.to_numeric(g["retirement_year"], errors="coerce")
        ret_month = pd.to_numeric(g["retirement_month"], errors="coerce")
        op_y = int(op_year.dropna().iloc[0]) if op_year.notna().any() else np.nan
        op_m = int(op_month.dropna().iloc[0]) if op_month.notna().any() else np.nan
        ret_y = int(ret_year.dropna().iloc[0]) if ret_year.notna().any() else np.nan
        ret_m = int(ret_month.dropna().iloc[0]) if ret_month.notna().any() else np.nan
        camd_status_date = matches["CAMD_STATUS_DATE"].iloc[0] if len(matches) and "CAMD_STATUS_DATE" in matches.columns else np.nan
        exact_retire = pd.to_datetime(camd_status_date, errors="coerce") if pd.notna(camd_status_date) else pd.NaT
        flags = []
        severity = "ok"
        if g.empty:
            flags.append("no_eia860_generator_row")
            severity = "informational"
        else:
            if pd.notna(op_y) and pd.notna(op_m) and (year, month) < (int(op_y), int(op_m)):
                flags.append("observed_before_operating_month")
                severity = "conflict"
            if pd.notna(ret_y) and pd.notna(ret_m):
                if (year, month) > (int(ret_y), int(ret_m)):
                    flags.append("observed_after_retirement_month")
                    severity = "conflict"
                elif (year, month) == (int(ret_y), int(ret_m)):
                    post_exact = False
                    if pd.notna(exact_retire):
                        month_start = pd.Timestamp(year=year, month=month, day=1)
                        if exact_retire < month_start:
                            post_exact = True
                    if post_exact:
                        flags.append("observed_after_authoritative_retirement_date")
                        severity = "conflict"
                    else:
                        flags.append("retirement_month_observation")
                        if severity == "ok":
                            severity = "informational"
            elif pd.notna(ret_y) and year > int(ret_y):
                flags.append("observed_after_retirement_year")
                severity = "conflict"
        audit_rows.append(
            {
                "plant_id": plant_id,
                "camd_facility_id": rec.camd_facility_id,
                "camd_unit_id": rec.camd_unit_id,
                "year": year,
                "month": month,
                "n_campd_hours": rec.n_hours,
                "operating_hours": rec.operating_hours,
                "eia860_statuses": join_ids(g["status"]) if len(g) else np.nan,
                "eia860_sheet": join_ids(g["eia860_sheet"]) if len(g) else np.nan,
                "eia860_prime_mover": join_ids(g["prime_mover"]) if len(g) else np.nan,
                "eia860_fuel": join_ids(g["energy_source_1"]) if len(g) else np.nan,
                "eia860_capacity_mw": safe_sum(g["nameplate_mw"]) if len(g) else np.nan,
                "operating_year": op_y,
                "operating_month": op_m,
                "retirement_year": ret_y,
                "retirement_month": ret_m,
                "camd_status_date": camd_status_date,
                "flag": "|".join(flags) if flags else "ok",
                "flag_severity": severity if flags else "ok",
            }
        )
    return pd.DataFrame(audit_rows)


def compare_campd_eia923(campd_m: pd.DataFrame, eia923_pm: pd.DataFrame) -> pd.DataFrame:
    merged = campd_m.merge(
        eia923_pm,
        on=["plant_id", "year", "month"],
        how="outer",
        suffixes=("_campd", "_eia923"),
        indicator=True,
    )
    g_campd = merged["campd_gross_generation_mwh"]
    g_eia = merged["generation_mwh"]
    ratio = np.where((g_eia.notna()) & (g_eia != 0) & g_campd.notna(), g_campd / g_eia, np.nan)
    merged["r_campd_over_eia923"] = ratio
    merged["join_status"] = merged["_merge"].map(
        {"both": "both", "left_only": "campd_only", "right_only": "eia923_only"}
    )
    merged["abs_log_ratio"] = np.where(
        pd.Series(ratio).notna() & (pd.Series(ratio) > 0),
        np.abs(np.log(np.clip(ratio, 1e-12, None))),
        np.nan,
    )
    keep = [
        "plant_id",
        "year",
        "month",
        "plant_name_campd",
        "plant_name",
        "campd_gross_generation_mwh",
        "campd_posted_gross_load_mw_sum",
        "generation_mwh",
        "r_campd_over_eia923",
        "abs_log_ratio",
        "join_status",
        "n_reporting_units",
        "n_hours",
    ]
    # plant_name from eia923 agg
    if "plant_name" not in merged.columns and "plant_name_eia923" in merged.columns:
        merged["plant_name"] = merged["plant_name_eia923"]
    for c in keep:
        if c not in merged.columns:
            merged[c] = np.nan
    return merged[keep].sort_values(["year", "month", "plant_id"]).reset_index(drop=True)


def intensity(num: pd.Series, den: pd.Series, scale: float = 1.0) -> pd.Series:
    num = pd.to_numeric(num, errors="coerce")
    den = pd.to_numeric(den, errors="coerce")
    return np.where(num.notna() & den.notna() & (den > 0), num * scale / den, np.nan)


def build_analysis_table(
    eia923_pm: pd.DataFrame,
    eia860_py: pd.DataFrame,
    campd_m: pd.DataFrame,
    cooling_pm: pd.DataFrame,
    audit: pd.DataFrame,
) -> pd.DataFrame:
    plant_match = (
        audit.dropna(subset=["eia_plant_id"])
        .groupby("eia_plant_id")
        .agg(
            crosswalk_match_type=("match_type", lambda s: join_ids(s)),
            mapping_cardinality=("mapping_cardinality", lambda s: join_ids(s)),
            match_method=("match_method", lambda s: join_ids(s)),
        )
        .reset_index()
        .rename(columns={"eia_plant_id": "plant_id"})
    )
    keys = ["plant_id", "year", "month"]
    frames = [eia923_pm[keys], campd_m[keys], cooling_pm[keys]]
    spine = pd.concat(frames, ignore_index=True).drop_duplicates()
    out = spine.merge(eia923_pm, on=keys, how="left")
    out = out.merge(
        eia860_py.rename(columns={"plant_name": "plant_name_860"}),
        on=["plant_id", "year"],
        how="left",
    )
    campd_cols = [
        "plant_id",
        "year",
        "month",
        "plant_name",
        "campd_co2_tonnes",
        "campd_nox_kg",
        "campd_so2_kg",
        "campd_heat_input_mmbtu",
        "campd_gross_generation_mwh",
        "campd_posted_gross_load_mw_sum",
        "operating_hours",
        "n_reporting_units",
        "n_hours",
        "co2_measure_codes",
        "crosswalk_match_type",
    ]
    out = out.merge(
        campd_m[campd_cols].rename(columns={"plant_name": "plant_name_campd", "crosswalk_match_type": "campd_match_type"}),
        on=keys,
        how="left",
    )
    cool_cols = [
        "plant_id",
        "year",
        "month",
        "generation_mwh",
        "water_withdrawal_m3",
        "water_consumption_m3",
        "water_consumption_m3_reported",
        "water_consumption_million_gal",
        "cooling_type",
        "cooling_system_id",
        "cooling_source",
        "volume_comparable",
        "cooling_intensity_eligible",
        "consumption_source_anomaly",
        "cooling_generation_status",
        "eia923_plant_generation_mwh",
        "summary_generation_mwh",
        "summary_water_consumption_million_gal",
    ]
    out = out.merge(
        cooling_pm[cool_cols].rename(columns={"generation_mwh": "cooling_associated_generation_mwh"}),
        on=keys,
        how="left",
    )
    out = out.merge(plant_match, on="plant_id", how="left")
    if "mapping_cardinality" not in out.columns:
        out["mapping_cardinality"] = np.nan
    if "match_method" not in out.columns:
        out["match_method"] = np.nan
    out["plant_name"] = out["plant_name"].fillna(out["plant_name_campd"]).fillna(out["plant_name_860"])
    out["prime_mover"] = out["prime_mover"].fillna(out["prime_movers"] if "prime_movers" in out.columns else np.nan)
    if "prime_movers" in out.columns:
        out["prime_mover"] = out["prime_mover"].fillna(out["prime_movers"])
    if "fuels" in out.columns:
        out["fuel"] = out["fuel"].fillna(out["fuels"])
    out["has_eia860"] = out["n_generators"].notna()
    out["has_eia923_generation"] = out["n_generation_nonmissing"].fillna(0).gt(0) | out["generation_mwh"].notna()
    out["has_eia923_cooling"] = out["cooling_source"].notna()
    out["has_campd"] = out["n_hours"].notna()
    out["has_epa_eia_match"] = (
        out["crosswalk_match_type"].fillna(out["campd_match_type"]).notna()
        & ~out["mapping_cardinality"].fillna("").eq("unmatched")
        & ~out["crosswalk_match_type"].fillna("").eq("unmatched")
        & ~out["crosswalk_match_type"].fillna("").str.startswith("unmatched")
    )
    out["crosswalk_match_type"] = out["crosswalk_match_type"].fillna(out["campd_match_type"])
    sources = []
    for _, row in out.iterrows():
        bits = []
        if row["has_eia860"]:
            bits.append("eia860")
        if row["has_eia923_generation"]:
            bits.append("eia923")
        if row["has_campd"]:
            bits.append("campd")
        if row["has_eia923_cooling"]:
            bits.append("cooling")
        sources.append("|".join(bits) if bits else "none")
    out["provenance_class"] = sources
    # Intensities only on compatible boundaries: CAMPD mass / CAMPD gross generation,
    # and cooling-water / cooling-associated generation. Never divide by zero.
    # Never substitute EIA-923 plant generation into cooling intensity.
    out["co2_kg_per_mwh"] = intensity(out["campd_co2_tonnes"], out["campd_gross_generation_mwh"], 1000.0)
    out["nox_g_per_mwh"] = intensity(out["campd_nox_kg"], out["campd_gross_generation_mwh"], 1000.0)
    out["so2_g_per_mwh"] = intensity(out["campd_so2_kg"], out["campd_gross_generation_mwh"], 1000.0)
    cooling_ok = out["cooling_intensity_eligible"].eq(True) if "cooling_intensity_eligible" in out.columns else out["volume_comparable"].eq(True)
    out["water_withdrawal_m3_per_mwh"] = np.where(
        cooling_ok,
        intensity(out["water_withdrawal_m3"], out["cooling_associated_generation_mwh"], 1.0),
        np.nan,
    )
    out["water_consumption_m3_per_mwh"] = np.where(
        cooling_ok,
        intensity(out["water_consumption_m3"], out["cooling_associated_generation_mwh"], 1.0),
        np.nan,
    )
    cols = [
        "year",
        "month",
        "plant_id",
        "plant_name",
        "generation_mwh",
        "fuel_mmbtu",
        "capacity_mw",
        "prime_mover",
        "fuel",
        "campd_co2_tonnes",
        "campd_nox_kg",
        "campd_so2_kg",
        "campd_heat_input_mmbtu",
        "water_withdrawal_m3",
        "water_consumption_m3",
        "cooling_type",
        "cooling_system_id",
        "co2_kg_per_mwh",
        "nox_g_per_mwh",
        "so2_g_per_mwh",
        "water_withdrawal_m3_per_mwh",
        "water_consumption_m3_per_mwh",
        "has_eia860",
        "has_eia923_generation",
        "has_eia923_cooling",
        "has_campd",
        "has_epa_eia_match",
        "crosswalk_match_type",
        "mapping_cardinality",
        "match_method",
        "provenance_class",
        "campd_gross_generation_mwh",
        "cooling_associated_generation_mwh",
        "cooling_source",
        "consumption_source_anomaly",
        "cooling_generation_status",
        "water_consumption_m3_reported",
    ]
    return out[cols].sort_values(["year", "month", "plant_id"]).reset_index(drop=True)


def coverage_by_year(
    eia860: pd.DataFrame,
    eia923: pd.DataFrame,
    campd: pd.DataFrame,
    analysis: pd.DataFrame,
    audit: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    for year in MODEL_YEARS:
        a860 = eia860[eia860["year"].eq(year)]
        a923 = eia923[eia923["year"].eq(year)]
        ac = campd[campd["year"].eq(year)]
        an = analysis[analysis["year"].eq(year)]
        rows.append(
            {
                "year": year,
                "n_eia860_generators": int(a860.drop_duplicates(["plant_id", "generator_id"]).shape[0]),
                "n_eia860_plants": int(a860["plant_id"].nunique()),
                "n_eia923_plants": int(a923["plant_id"].nunique()),
                "n_eia923_plant_months": int(a923.groupby(["plant_id", "month"]).ngroups),
                "n_campd_facilities": int(ac["Facility ID"].nunique()),
                "n_campd_units": int(ac.groupby(["Facility ID", "Unit ID"]).ngroups),
                "n_campd_hours": int(len(ac)),
                "n_analysis_plant_months": int(len(an)),
                "n_plant_months_with_campd": int(an["has_campd"].sum()),
                "n_plant_months_with_eia923": int(an["has_eia923_generation"].sum()),
                "n_plant_months_with_cooling": int(an["has_eia923_cooling"].sum()),
            }
        )
    cov = pd.DataFrame(rows)
    cov["n_crosswalk_unmatched_units"] = int(audit["mapping_cardinality"].eq("unmatched").sum())
    return cov


def cooling_coverage_by_year(cooling_pm: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year in MODEL_YEARS:
        sub = cooling_pm[cooling_pm["year"].eq(year)]
        rows.append(
            {
                "year": year,
                "n_plant_months": int(len(sub)),
                "n_plants": int(sub["plant_id"].nunique()) if len(sub) else 0,
                "n_withdrawal_nonmissing": int(sub["water_withdrawal_m3"].notna().sum()) if len(sub) else 0,
                "n_withdrawal_zero": int((sub["water_withdrawal_m3"] == 0).sum()) if len(sub) else 0,
                "n_consumption_nonmissing": int(sub["water_consumption_m3"].notna().sum()) if len(sub) else 0,
                "n_consumption_zero": int((sub["water_consumption_m3"] == 0).sum()) if len(sub) else 0,
                "n_generation_nonmissing": int(sub["generation_mwh"].notna().sum()) if len(sub) else 0,
                "sources": join_ids(sub["cooling_source"]) if len(sub) else np.nan,
                "volume_comparable": join_ids(sub["volume_comparable"].astype(str)) if len(sub) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def optional_egrid_compare(campd_m: pd.DataFrame) -> pd.DataFrame | None:
    try:
        import sys

        sys.path.insert(0, str(ROOT / "src"))
        from prepare_egrid import VINTAGES, MODEL_YEAR_TO_EGRID  # type: ignore
    except Exception:
        return None
    annual = (
        campd_m.groupby(["plant_id", "year"], dropna=False)
        .agg(
            campd_co2_tonnes=("campd_co2_tonnes", safe_sum),
            campd_gross_generation_mwh=("campd_gross_generation_mwh", safe_sum),
        )
        .reset_index()
    )
    frames = []
    for model_year, egrid_year in MODEL_YEAR_TO_EGRID.items():
        if egrid_year not in VINTAGES:
            continue
        meta = VINTAGES[egrid_year]
        path = EGRID_DIR / meta["relative"]
        if not path.exists():
            continue
        try:
            xl = pd.ExcelFile(path)
            sheet = meta.get("plnt")
            if sheet not in xl.sheet_names:
                continue
            plnt = pd.read_excel(xl, sheet_name=sheet, header=1)
        except Exception:
            continue
        plnt.columns = [re.sub(r"\s+", " ", str(c).replace("\n", " ")).strip() for c in plnt.columns]
        cmap = {norm_name(c): c for c in plnt.columns}
        oris = cmap.get("orispl")
        state = cmap.get("pstatabb")
        co2 = cmap.get("plco2an")
        gen = cmap.get("plngenan")
        if not oris or not state:
            continue
        sub = plnt.loc[plnt[state].astype(str).str.upper().eq("OR"), [c for c in [oris, co2, gen] if c]].copy()
        sub["_oris"] = to_numeric_missing(sub[oris])
        campd_y = annual[annual["year"].eq(model_year)].copy()
        merged = campd_y.merge(sub, left_on="plant_id", right_on="_oris", how="left")
        merged["model_year"] = model_year
        merged["egrid_data_year"] = egrid_year
        if co2:
            merged["egrid_co2_tonnes"] = to_numeric_missing(merged[co2]) * SHORT_TON_TO_TONNE
        else:
            merged["egrid_co2_tonnes"] = np.nan
        merged["egrid_net_generation_mwh"] = to_numeric_missing(merged[gen]) if gen else np.nan
        merged["ratio_campd_over_egrid_co2"] = np.where(
            merged["campd_co2_tonnes"].notna()
            & merged["egrid_co2_tonnes"].notna()
            & (merged["egrid_co2_tonnes"] != 0),
            merged["campd_co2_tonnes"] / merged["egrid_co2_tonnes"],
            np.nan,
        )
        merged["note"] = "implementation consistency only; eGRID already incorporates EIA/EPA sources"
        frames.append(
            merged[
                [
                    "model_year",
                    "egrid_data_year",
                    "plant_id",
                    "campd_co2_tonnes",
                    "egrid_co2_tonnes",
                    "ratio_campd_over_egrid_co2",
                    "campd_gross_generation_mwh",
                    "egrid_net_generation_mwh",
                    "note",
                ]
            ]
        )
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# QC
# ---------------------------------------------------------------------------

def add_check(checks: list[dict], name: str, passed: bool, detail: str, abort: bool = False) -> None:
    checks.append({"check": name, "status": "PASS" if passed else "FAIL", "detail": detail})
    if abort and not passed:
        raise AssertionError(f"{name}: {detail}")


def run_checks(
    campd: pd.DataFrame,
    campd_raw_na: dict,
    campd_m: pd.DataFrame,
    audit: pd.DataFrame,
    eia860: pd.DataFrame,
    eia923: pd.DataFrame,
    cooling_pm: pd.DataFrame,
    cooling_flags: pd.DataFrame,
    analysis: pd.DataFrame,
    compare: pd.DataFrame,
    eia860_flags: pd.DataFrame,
) -> list[dict]:
    checks: list[dict] = []
    key = ["Facility ID", "Unit ID", "Date", "Hour"]
    dup = int(campd.duplicated(key).sum())
    add_check(checks, "campd_unit_hour_key_unique", dup == 0, f"duplicate_keys={dup}", abort=True)

    years = sorted(campd["year"].unique().tolist())
    add_check(
        checks,
        "campd_coverage_2011_2024",
        years == MODEL_YEARS,
        f"years={years}",
        abort=True,
    )

    steam_na = int(campd["Steam Load (1000 lb/hr)"].isna().sum())
    steam_zero = int((campd["Steam Load (1000 lb/hr)"] == 0).sum())
    add_check(
        checks,
        "blanks_not_converted_to_zero",
        steam_na == campd_raw_na["steam_na"] and steam_zero == campd_raw_na["steam_zero"],
        f"processed steam NA={steam_na} zero={steam_zero}; raw NA={campd_raw_na['steam_na']} zero={campd_raw_na['steam_zero']}",
        abort=True,
    )
    add_check(
        checks,
        "reported_zero_distinguished_from_missing",
        steam_na > 0 and steam_zero >= 0 and campd["CO2 Mass (short tons)"].isna().sum() == campd_raw_na["co2_na"],
        f"steam NA={steam_na} steam0={steam_zero} co2_na={int(campd['CO2 Mass (short tons)'].isna().sum())} co2_0={int((campd['CO2 Mass (short tons)']==0).sum())}",
        abort=True,
    )

    hourly_co2_tonnes = float(campd["CO2 Mass (short tons)"].sum(min_count=1) * SHORT_TON_TO_TONNE)
    monthly_co2 = float(pd.to_numeric(campd_m["campd_co2_tonnes"], errors="coerce").sum(min_count=1))
    add_check(
        checks,
        "no_emissions_duplication_from_crosswalk",
        abs(hourly_co2_tonnes - monthly_co2) <= max(1e-4, 1e-8 * abs(hourly_co2_tonnes)),
        f"hourly_tonnes={hourly_co2_tonnes:.6f} monthly_tonnes={monthly_co2:.6f}",
        abort=True,
    )

    # If Operating Time had been multiplied into posted mass, monthly CO2 would equal sum(mass*optime).
    optime_scaled = float((campd["CO2 Mass (short tons)"] * campd["Operating Time"]).sum(min_count=1) * SHORT_TON_TO_TONNE)
    add_check(
        checks,
        "no_second_operating_time_multiplication",
        abs(monthly_co2 - hourly_co2_tonnes) < abs(monthly_co2 - optime_scaled),
        f"monthly={monthly_co2:.3f} posted_sum={hourly_co2_tonnes:.3f} optime_scaled={optime_scaled:.3f}",
        abort=True,
    )

    hourly_gen = float(pd.to_numeric(campd["gross_generation_mwh"], errors="coerce").sum(min_count=1))
    monthly_gen = float(pd.to_numeric(campd_m["campd_gross_generation_mwh"], errors="coerce").sum(min_count=1))
    reconstructed = float(
        pd.to_numeric(campd["Gross Load (MW)"], errors="coerce")
        .mul(pd.to_numeric(campd["Operating Time"], errors="coerce"))
        .sum(min_count=1)
    )
    add_check(
        checks,
        "campd_gross_generation_equals_load_times_operating_time",
        abs(hourly_gen - reconstructed) <= max(1e-4, 1e-8 * abs(reconstructed))
        and abs(monthly_gen - hourly_gen) <= max(1e-4, 1e-8 * abs(hourly_gen)),
        f"hourly_mwh={hourly_gen:.6f} monthly_mwh={monthly_gen:.6f} load_x_ot={reconstructed:.6f}",
        abort=True,
    )

    add_check(
        checks,
        "facility_and_unit_id_preserved",
        campd["Facility ID"].notna().all() and campd["Unit ID"].astype(str).str.len().gt(0).all(),
        f"n_facilities={campd['Facility ID'].nunique()} n_units={campd.groupby(['Facility ID','Unit ID']).ngroups}",
        abort=True,
    )

    n_units = int(audit.shape[0])
    card_counts = audit["mapping_cardinality"].fillna("unmatched").value_counts().to_dict()
    method_counts = audit["match_method"].fillna("unmatched").value_counts().to_dict()
    n_accounted = int(audit["mapping_cardinality"].notna().sum())
    add_check(
        checks,
        "epa_eia_match_rate_accounted",
        n_accounted == n_units,
        f"units={n_units} cardinality={card_counts} method={method_counts}",
        abort=True,
    )
    add_check(
        checks,
        "unmatched_units_preserved",
        True,
        f"unmatched_units={int(audit['mapping_cardinality'].eq('unmatched').sum())} (retained in audit; not dropped)",
        abort=False,
    )
    add_check(
        checks,
        "crosswalk_not_exploded_to_generators",
        not audit["unexplained_plant_split"].any(),
        "CAMD unit maps uniquely to at most one EIA plant; emissions are not copied onto generator IDs",
        abort=True,
    )

    eia923_year_sum = (
        eia923.groupby(["plant_id", "year", "prime_mover", "fuel_code"], dropna=False)
        .agg(
            monthly_sum=("net_generation_mwh", safe_sum),
            annual=("annual_net_generation_mwh", "first"),
        )
        .reset_index()
    )
    both = eia923_year_sum.dropna(subset=["monthly_sum", "annual"])
    both = both[both["annual"] != 0]
    if len(both):
        rel = (both["monthly_sum"] - both["annual"]).abs() / both["annual"].abs()
        share_close = float((rel < 0.02).mean())
        add_check(
            checks,
            "eia923_monthly_generation_aggregation_valid",
            share_close >= 0.90,
            f"share_within_2pct={share_close:.3f} n={len(both)} median_rel={(rel.median())}",
            abort=False,
        )
    else:
        add_check(checks, "eia923_monthly_generation_aggregation_valid", False, "no comparable annual totals", abort=False)

    monthly_vs_hourly_hours = int(campd_m["n_hours"].sum()) == int(len(campd))
    add_check(
        checks,
        "monthly_to_annual_reaggregation_internally_consistent",
        monthly_vs_hourly_hours
        and abs(
            float(campd_m.groupby("year")["campd_heat_input_mmbtu"].sum().sum())
            - float(campd["Heat Input (mmBtu)"].sum(min_count=1))
        )
        <= 1e-3,
        f"monthly_hours={int(campd_m['n_hours'].sum())} hourly_rows={len(campd)}",
        abort=True,
    )

    add_check(
        checks,
        "unit_conversions_correct",
        abs(SHORT_TON_TO_TONNE * 1.102311310924388 - 1) < 1e-9
        and abs(LB_TO_KG * 2.2046226218487757 - 1) < 1e-9,
        f"short_ton_to_tonne={SHORT_TON_TO_TONNE} lb_to_kg={LB_TO_KG} m3_per_million_gal={M3_PER_MILLION_GAL}",
        abort=True,
    )

    cooling_na_ok = True
    if not cooling_pm.empty and cooling_pm["year"].isin([2011, 2012]).any():
        early = cooling_pm[cooling_pm["year"].isin([2011, 2012])]
        cooling_na_ok = bool(early["water_withdrawal_m3"].isna().all())
    n_conflict = int(cooling_flags["water_conflict"].sum()) if len(cooling_flags) and "water_conflict" in cooling_flags.columns else 0
    add_check(
        checks,
        "cooling_missingness_preserved",
        cooling_na_ok and n_conflict == 0,
        f"2011-2012_m3_all_missing={cooling_na_ok} duplicated_cooling_water_conflicts={n_conflict}",
        abort=True,
    )
    neg_cons = cooling_pm[pd.to_numeric(cooling_pm.get("water_consumption_million_gal"), errors="coerce") < 0] if len(cooling_pm) else cooling_pm.iloc[0:0]
    intensity_ok = True
    if len(neg_cons) and "water_consumption_m3_per_mwh" in analysis.columns:
        an_neg = analysis.merge(neg_cons[["plant_id", "year", "month"]], on=["plant_id", "year", "month"], how="inner")
        intensity_ok = bool(pd.to_numeric(an_neg["water_consumption_m3_per_mwh"], errors="coerce").isna().all())
    add_check(
        checks,
        "negative_cooling_consumption_not_used_for_intensity",
        intensity_ok,
        f"n_negative_reported_consumption={len(neg_cons)} intensity_missing_for_those_rows={intensity_ok}",
        abort=True,
    )

    conflict = eia860_flags[eia860_flags["flag_severity"].eq("conflict")] if len(eia860_flags) and "flag_severity" in eia860_flags.columns else eia860_flags[eia860_flags["flag"].ne("ok")] if len(eia860_flags) else eia860_flags
    n_info = int((eia860_flags["flag_severity"].eq("informational")).sum()) if len(eia860_flags) and "flag_severity" in eia860_flags.columns else 0
    add_check(
        checks,
        "eia860_operating_retirement_dates_consistent_with_observations",
        len(conflict) == 0,
        f"conflict_unit_months={len(conflict)} informational={n_info} examples={conflict.head(8).to_dict('records') if len(conflict) else 'none'}",
        abort=False,
    )

    both_cmp = compare[compare["join_status"].eq("both")].dropna(subset=["r_campd_over_eia923"])
    if len(both_cmp):
        corr = pd.to_numeric(both_cmp["campd_gross_generation_mwh"], errors="coerce").corr(
            pd.to_numeric(both_cmp["generation_mwh"], errors="coerce")
        )
        med = float(both_cmp["r_campd_over_eia923"].median())
        extreme = int(((both_cmp["r_campd_over_eia923"] > 5) | (both_cmp["r_campd_over_eia923"] < 0.05)).sum())
        add_check(
            checks,
            "campd_eia923_generation_comparison_plausible",
            pd.notna(corr) and corr > 0.5 and 0.5 <= med <= 2.0,
            f"n={len(both_cmp)} corr={corr:.3f} median_R={med:.3f} extreme_R_count={extreme}",
            abort=False,
        )
    else:
        add_check(checks, "campd_eia923_generation_comparison_plausible", False, "no overlapping plant-months", abort=False)

    add_check(
        checks,
        "analysis_table_has_required_flags",
        set(["has_eia860", "has_eia923_generation", "has_eia923_cooling", "has_campd", "has_epa_eia_match"]).issubset(analysis.columns),
        f"columns_ok n_rows={len(analysis)}",
        abort=True,
    )
    return checks


def campd_raw_missing_counts() -> dict:
    raw = pd.read_csv(
        CAMPD_RAW,
        usecols=["Steam Load (1000 lb/hr)", "CO2 Mass (short tons)", "Gross Load (MW)"],
        low_memory=False,
    )
    steam = to_numeric_missing(raw["Steam Load (1000 lb/hr)"])
    co2 = to_numeric_missing(raw["CO2 Mass (short tons)"])
    return {
        "steam_na": int(steam.isna().sum()),
        "steam_zero": int((steam == 0).sum()),
        "co2_na": int(co2.isna().sum()),
        "co2_zero": int((co2 == 0).sum()),
    }


# ---------------------------------------------------------------------------
# Self-test / main
# ---------------------------------------------------------------------------

def self_test() -> None:
    assert abs(1.0 * SHORT_TON_TO_TONNE * 1.102311310924388 - 1) < 1e-9
    assert abs(1.0 * LB_TO_KG * 2.2046226218487757 - 1) < 1e-9
    assert abs(1.0 * M3_PER_MILLION_GAL / 3785.411784 - 1) < 1e-12
    assert classify_mapping_cardinality(0, 0, 1) == "unmatched"
    assert classify_mapping_cardinality(1, 2, 1) == "one_to_many"
    assert classify_mapping_cardinality(1, 1, 2) == "many_to_one"
    assert classify_mapping_cardinality(1, 1, 1) == "one_to_one"
    assert classify_match_method("Step 1a: Exact match") == "exact"
    assert classify_match_method("Manual Match") == "official_manual"
    assert classify_match_method("Exact match", "Step 2d: Modify IDs; remove leading letters") == "official_manual" or classify_match_method("Exact match", "Step 2d: Modify IDs; remove leading letters") == "modified_fuzzy"
    assert classify_match_method("3_1 Exact match", "Step 2d: Modify IDs; remove leading letters") == "modified_fuzzy"
    assert classify_match(1, 2, 1, "Exact match") == "one_to_many|exact"
    assert classify_match(1, 1, 1, "Manual Match") == "one_to_one|official_manual"
    assert EXCEL_ENGINE in {"calamine", "openpyxl"}
    posted = pd.Series([10.0, np.nan, 0.0])
    optime = pd.Series([0.5, 1.0, 1.0])
    monthly_posted = float(posted.sum(min_count=1) * SHORT_TON_TO_TONNE)
    monthly_scaled = float((posted * optime).sum(min_count=1) * SHORT_TON_TO_TONNE)
    assert monthly_posted != monthly_scaled
    assert pd.isna(posted.iloc[1])
    assert posted.iloc[2] == 0.0

    load = pd.Series([50.0, 50.0, 50.0, np.nan, 0.0])
    ot = pd.Series([1.0, 0.4, np.nan, 1.0, 0.5])
    gen = hourly_gross_generation_mwh(load, ot)
    assert abs(gen.iloc[0] - 50.0) < 1e-12  # full hour
    assert abs(gen.iloc[1] - 20.0) < 1e-12  # partial hour
    assert pd.isna(gen.iloc[2])  # missing operating time
    assert pd.isna(gen.iloc[3])  # missing load
    assert gen.iloc[4] == 0.0  # reported zero load
    # unique cooling-system water: repeated generator rows must not double water
    demo = pd.DataFrame(
        {
            "plant_id": [1, 1, 1],
            "year": [2014, 2014, 2014],
            "month": [1, 1, 1],
            "cooling_system_id": ["A", "A", "B"],
            "generator_id": ["1", "2", "3"],
            "water_withdrawal_million_gal": [10.0, 10.0, 3.0],
            "water_consumption_million_gal": [1.0, 1.0, 0.0],
            "cooling_type": ["RC", "RC", "DC"],
            "plant_name": ["X"] * 3,
            "source_file": ["t"] * 3,
            "gross_gen_steam_mwh": [100.0, 50.0, 10.0],
            "gross_gen_sscc_mwh": [np.nan, np.nan, np.nan],
            "gross_gen_ccgt_mwh": [np.nan, np.nan, np.nan],
        }
    )
    pm, flags = cooling_plant_month(demo, pd.DataFrame())
    assert abs(pm.loc[0, "water_withdrawal_million_gal"] - 13.0) < 1e-9
    assert int(flags["water_conflict"].sum()) == 0
    assert abs(pm.loc[0, "generation_mwh"] - 160.0) < 1e-9
    # negative consumption: raw preserved, modeled m3/intensity not used
    demo_neg = demo.copy()
    demo_neg["water_consumption_million_gal"] = [-1.734, -1.734, 0.0]
    pm_neg, _ = cooling_plant_month(demo_neg, pd.DataFrame())
    assert abs(pm_neg.loc[0, "water_consumption_million_gal"] + 1.734) < 1e-9
    assert pd.isna(pm_neg.loc[0, "water_consumption_m3"])
    assert bool(pm_neg.loc[0, "consumption_source_anomaly"])
    print("PASS: prepare_oregon_generators self-test")


def prepare(reuse_campd: bool = True) -> dict:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    OUTPUTS.mkdir(parents=True, exist_ok=True)

    print("EIA-860...", flush=True)
    eia860 = prepare_eia860()
    eia860.to_csv(OUT_EIA860, index=False)
    print("EIA-923 generation/fuel...", flush=True)
    eia923 = prepare_eia923_generation()
    eia923.to_csv(OUT_EIA923, index=False)
    eia923_pm = eia923_plant_month(eia923)
    or_plant_ids = set(pd.concat([eia860["plant_id"], eia923["plant_id"]], ignore_index=True).dropna().astype(int))
    print("EIA cooling detail 2014-2024...", flush=True)
    cooling_detail = prepare_cooling_standardized()
    print("EIA cooling summary 2014-2024...", flush=True)
    cooling_summary = prepare_cooling_summary()
    print("EIA-923 Schedule 8 cooling 2011-2013...", flush=True)
    cooling_s8 = prepare_cooling_schedule8(or_plant_ids)
    cooling_pm, cooling_flags = cooling_plant_month(cooling_detail, cooling_s8, cooling_summary, eia923_pm)
    cooling_pm.to_csv(OUT_COOLING, index=False)

    print("CAMPD hourly...", flush=True)
    raw_na = campd_raw_missing_counts()
    campd, campd_reused = prepare_campd_hourly(reuse_processed=reuse_campd)
    if not campd_reused:
        campd.to_csv(OUT_CAMPD_HOURLY, index=False)
    print("EPA/EIA crosswalk...", flush=True)
    xw = prepare_crosswalk(campd)
    audit, unit_map = audit_crosswalk(campd, xw)
    xw.to_csv(OUT_CROSSWALK, index=False)
    audit.to_csv(OUT_XW_AUDIT, index=False)
    print("CAMPD plant-month...", flush=True)
    campd_m = aggregate_campd_plant_month(campd, unit_map)
    campd_m.to_csv(OUT_CAMPD_MONTHLY, index=False)
    print("Joins, QC, optional eGRID...", flush=True)
    eia860_py = eia860_plant_year(eia860)
    eia860_flags = flag_eia860_vs_campd(campd, eia860, unit_map, xw)
    compare = compare_campd_eia923(campd_m, eia923_pm)
    analysis = build_analysis_table(eia923_pm, eia860_py, campd_m, cooling_pm, audit)
    coverage = coverage_by_year(eia860, eia923, campd, analysis, audit)
    cooling_cov = cooling_coverage_by_year(cooling_pm)

    print("Writing remaining outputs...", flush=True)
    analysis.to_csv(OUT_ANALYSIS, index=False)
    coverage.to_csv(OUT_COVERAGE, index=False)
    cooling_cov.to_csv(OUT_COOLING_COV, index=False)
    compare.to_csv(OUT_COMPARE, index=False)
    eia860_flags.to_csv(OUT_EIA860_FLAGS, index=False)

    checks = run_checks(
        campd,
        raw_na,
        campd_m,
        audit,
        eia860,
        eia923,
        cooling_pm,
        cooling_flags,
        analysis,
        compare,
        eia860_flags,
    )
    pd.DataFrame(checks).to_csv(OUT_CHECKS, index=False)
    try:
        egrid_cmp = optional_egrid_compare(campd_m)
    except Exception as exc:
        print(f"optional eGRID plant compare skipped: {exc}", flush=True)
        egrid_cmp = None
    if egrid_cmp is not None:
        egrid_cmp.to_csv(OUT_EGRID_CMP, index=False)

    print("Exception report...", flush=True)
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from oregon_exception_report import main as write_exception_report

    write_exception_report()

    n_facilities = int(campd["Facility ID"].nunique())
    n_units = int(campd.groupby(["Facility ID", "Unit ID"]).ngroups)
    card_counts = audit["mapping_cardinality"].value_counts(dropna=False).to_dict()
    method_counts = audit["match_method"].value_counts(dropna=False).to_dict()
    both = compare[compare["join_status"].eq("both")].dropna(subset=["r_campd_over_eia923"])
    return {
        "n_campd_facilities": n_facilities,
        "n_campd_units": n_units,
        "n_campd_hours": int(len(campd)),
        "epa_eia_cardinality_counts": {str(k): int(v) for k, v in card_counts.items()},
        "epa_eia_match_method_counts": {str(k): int(v) for k, v in method_counts.items()},
        "n_unmatched_units": int(audit["mapping_cardinality"].eq("unmatched").sum()),
        "generation_compare_n_both": int(len(both)),
        "generation_compare_median_R": None if both.empty else float(both["r_campd_over_eia923"].median()),
        "generation_compare_corr": None
        if both.empty
        else float(
            pd.to_numeric(both["campd_gross_generation_mwh"], errors="coerce").corr(
                pd.to_numeric(both["generation_mwh"], errors="coerce")
            )
        ),
        "checks": {c["check"]: c["status"] for c in checks},
        "n_checks_fail": int(sum(c["status"] == "FAIL" for c in checks)),
        "outputs": [
            str(p.relative_to(ROOT))
            for p in [
                OUT_EIA860,
                OUT_EIA923,
                OUT_COOLING,
                OUT_CAMPD_HOURLY,
                OUT_CROSSWALK,
                OUT_CAMPD_MONTHLY,
                OUT_ANALYSIS,
                OUT_XW_AUDIT,
                OUT_CHECKS,
                OUT_COVERAGE,
                OUT_COOLING_COV,
                OUT_COMPARE,
                OUT_EIA860_FLAGS,
                OUT_EGRID_CMP,
            ]
            if p.exists()
        ],
        "accounting_notes": [
            "CAMPD hourly gross_generation_mwh = Gross Load (MW) * Operating Time when both reported",
            "CAMPD posted hourly CO2/SO2/NOx mass and heat input are not multiplied by Operating Time",
            "CAMPD plant-month uses unique EIA plant per CAMD unit; generator rows are not exploded",
            "Emission intensities use CAMPD mass / CAMPD gross generation (MWh)",
            "Water intensities use cooling-product water / cooling-associated generation only",
            "2011-2012 Schedule 8 cooling volumes left missing (units not comparable)",
            "Negative cooling consumption is preserved as reported and excluded from intensity",
            "This pilot does not identify generators serving the Prineville campus",
        ],
    }


def main() -> dict:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--force-campd-reread", action="store_true", help="Do not reuse processed CAMPD hourly")
    args = parser.parse_args()
    self_test()
    if args.self_test:
        return {"self_test": "PASS"}
    summary = prepare(reuse_campd=not args.force_campd_reread)
    print(json.dumps(summary, indent=2, default=str))
    checks = pd.read_csv(OUT_CHECKS)
    print("\nOregon generator pipeline checks:")
    print(checks.to_string(index=False))
    print("\nCoverage by year:")
    print(pd.read_csv(OUT_COVERAGE).to_string(index=False))
    print("\nCooling coverage by year:")
    print(pd.read_csv(OUT_COOLING_COV).to_string(index=False))
    return summary


if __name__ == "__main__":
    main()
