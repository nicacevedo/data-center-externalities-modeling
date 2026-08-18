"""Prepare EPA eGRID subregion output rates for the Prineville campus.

This script does not modify files under data/raw/egrid/. It reads the US-customary
subregion (SRL) workbooks and the plant (PLNT) sheets only to verify the
Prineville / Crook County, Oregon consumption-location subregion. PacifiCorp West
(PACW) is regional balancing-authority context, not campus electricity.

eGRID total output emission rates are the annual physical-grid factors used here.
Non-baseload output rates are retained as a separately named diagnostic and are
never used as ordinary location-based Scope 2 factors.

The annual emissions benchmark multiplies Meta-reported campus electricity by the
mapped subregion factor. PACW demand is never substituted for campus MWh.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import json
import re

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "egrid"
TARGETS = ROOT / "data" / "canonical" / "meta_prineville_annual.csv"
PACW_HOURLY = ROOT / "data" / "processed" / "pacw_hourly.csv"
OUT_ANNUAL = ROOT / "data" / "processed" / "egrid_prineville_annual.csv"
OUT_COMPARE = ROOT / "outputs" / "egrid_meta_annual_compare.csv"
OUT_CHECKS = ROOT / "outputs" / "egrid_prepare_checks.csv"
OUT_CROSSWALK = ROOT / "outputs" / "egrid_subregion_crosswalk.csv"
OUT_PACW_CARBON = ROOT / "outputs" / "pacw_carbon_shape_compare.csv"

MODEL_YEARS = list(range(2011, 2025))
MODEL_YEAR_TO_EGRID = {
    2011: 2010,
    2012: 2012,
    2013: 2012,
    2014: 2014,
    2015: 2014,
    2016: 2016,
    2017: 2016,
    2018: 2018,
    2019: 2019,
    2020: 2020,
    2021: 2021,
    2022: 2022,
    2023: 2023,
    2024: 2023,
}

# avoirdupois pound per metric tonne
LB_PER_METRIC_TONNE = 2204.6226218487757

VINTAGES: dict[int, dict[str, str]] = {
    2010: {
        "relative": "egrid2010/eGRID2010_Data.xls",
        "srl": "SRL10",
        "plnt": "PLNT10",
    },
    2012: {
        "relative": "egrid2012/eGRID2012_Data.xlsx",
        "srl": "SRL12",
        "plnt": "PLNT12",
    },
    2014: {
        "relative": "egrid2014/eGRID2014_Data_v2.xlsx",
        "srl": "SRL14",
        "plnt": "PLNT14",
    },
    2016: {
        "relative": "egrid2016/egrid2016_data.xlsx",
        "srl": "SRL16",
        "plnt": "PLNT16",
    },
    2018: {
        "relative": "egrid2018/egrid2018_data_v2.xlsx",
        "srl": "SRL18",
        "plnt": "PLNT18",
    },
    2019: {
        "relative": "egrid2019/egrid2019_data.xlsx",
        "srl": "SRL19",
        "plnt": "PLNT19",
    },
    2020: {
        "relative": "egrid2020/eGRID2020_Data_v2.xlsx",
        "srl": "SRL20",
        "plnt": "PLNT20",
    },
    2021: {
        "relative": "egrid2021/eGRID2021_data.xlsx",
        "srl": "SRL21",
        "plnt": "PLNT21",
    },
    2022: {
        "relative": "egrid2022/egrid2022_data.xlsx",
        "srl": "SRL22",
        "plnt": "PLNT22",
    },
    2023: {
        "relative": "egrid2023/egrid2023_data_rev2.xlsx",
        "srl": "SRL23",
        "plnt": "PLNT23",
    },
}

REQUIRED_SRL_CODES = (
    "SUBRGN",
    "SRNAME",
    "SRCO2RTA",
    "SRC2ERTA",
    "SRNOXRTA",
    "SRSO2RTA",
    "SRCH4RTA",
    "SRN2ORTA",
    "SRNBCO2",
    "SRCLPR",
    "SRGSPR",
    "SRHYPR",
    "SRWIPR",
    "SRSOPR",
)
PLANT_WANTED = ("PSTATABB", "CNTYNAME", "SUBRGN", "BACODE", "PCANAME", "PNAME")
RATE_FIELDS = (
    "co2_lb_per_mwh",
    "co2e_lb_per_mwh",
    "nox_lb_per_mwh",
    "so2_lb_per_mwh",
    "ch4_lb_per_mwh",
    "n2o_lb_per_mwh",
    "co2_nonbaseload_lb_per_mwh",
)


class EgridSchemaError(ValueError):
    """Raised when an eGRID workbook does not match an expected, named schema."""


def _engine(path: Path) -> str:
    if path.suffix.lower() == ".xls":
        return "xlrd"
    return "openpyxl"


def _revision_from_name(name: str) -> str:
    lower = name.lower()
    if "rev2" in lower:
        return "rev2"
    if re.search(r"(^|[^a-z])v2([^0-9]|$)", lower):
        return "v2"
    return "unspecified"


def _to_numeric(value):
    if pd.isna(value):
        return np.nan
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    text = str(value).strip()
    if text in {"", "--", "—", "N/A", "NA", "n/a"}:
        return np.nan
    return pd.to_numeric(text.replace(",", ""), errors="coerce")


def _find_code_row(raw: pd.DataFrame, required: tuple[str, ...], label: str) -> int:
    need = set(required)
    for i, row in raw.iterrows():
        vals = {str(v).strip() for v in row if pd.notna(v)}
        if need <= vals:
            return int(i)
    present = set()
    for _, row in raw.iterrows():
        present |= {str(v).strip() for v in row if pd.notna(v)}
    missing = sorted(need - present)
    raise EgridSchemaError(
        f"{label} is missing required eGRID field codes {missing}. "
        "Refusing to guess a column mapping."
    )


def _frame_from_code_row(raw: pd.DataFrame, code_row: int) -> tuple[pd.DataFrame, dict[str, str]]:
    codes = [str(v).strip() if pd.notna(v) else "" for v in raw.iloc[code_row]]
    desc_row = raw.iloc[code_row - 1] if code_row > 0 else pd.Series([""] * len(codes))
    descriptions = {
        codes[j]: str(desc_row.iloc[j]).strip() if pd.notna(desc_row.iloc[j]) else ""
        for j in range(len(codes))
        if codes[j]
    }
    data = raw.iloc[code_row + 1 :].copy()
    data.columns = pd.Index(codes)
    data = data.loc[:, [c for c in data.columns if c]]
    data = data.loc[:, ~data.columns.duplicated()]
    data = data.dropna(how="all")
    return data, descriptions


def _load_sheet(path: Path, sheet: str, required: tuple[str, ...]) -> tuple[pd.DataFrame, dict[str, str]]:
    engine = _engine(path)
    try:
        xl = pd.ExcelFile(path, engine=engine)
    except Exception as exc:
        raise EgridSchemaError(f"Cannot open {path}: {exc}") from exc
    if sheet not in xl.sheet_names:
        raise EgridSchemaError(
            f"{path.name} has no sheet {sheet!r}. Available: {xl.sheet_names}"
        )
    raw = pd.read_excel(path, sheet_name=sheet, header=None, engine=engine)
    code_row = _find_code_row(raw, required, f"{path.name}:{sheet}")
    return _frame_from_code_row(raw, code_row)


def _load_plant_map(path: Path, sheet: str) -> pd.DataFrame:
    engine = _engine(path)
    header = pd.read_excel(path, sheet_name=sheet, header=None, nrows=8, engine=engine)
    code_row = _find_code_row(header, ("PSTATABB", "SUBRGN"), f"{path.name}:{sheet}")
    codes = [str(v).strip() if pd.notna(v) else "" for v in header.iloc[code_row]]
    wanted = [c for c in PLANT_WANTED if c in codes]
    if "CNTYNAME" not in wanted:
        raise EgridSchemaError(
            f"{path.name}:{sheet} is missing CNTYNAME; cannot verify Crook County mapping."
        )
    usecols = [i for i, c in enumerate(codes) if c in wanted]
    data = pd.read_excel(
        path,
        sheet_name=sheet,
        header=None,
        skiprows=code_row + 1,
        usecols=usecols,
        engine=engine,
    )
    data.columns = [codes[i] for i in usecols]
    data = data.dropna(how="all")
    return data


def _parse_rate_units(description: str, code: str) -> str:
    text = description.lower()
    if "kg/" in text or "metric" in text:
        raise EgridSchemaError(
            f"{code} description looks metric ({description!r}). "
            "This package uses the US-customary eGRID workbooks only."
        )
    if "lb/gwh" in text.replace(" ", ""):
        return "lb/GWh"
    if "lb/mwh" in text.replace(" ", ""):
        return "lb/MWh"
    raise EgridSchemaError(
        f"{code} has unexpected units in description {description!r}. "
        "Refusing to guess lb/MWh vs lb/GWh."
    )


def _output_rate(row: pd.Series, descriptions: dict[str, str], code: str) -> tuple[float, str]:
    units = _parse_rate_units(descriptions.get(code, ""), code)
    value = _to_numeric(row.get(code))
    if units == "lb/GWh":
        return float(value) / 1000.0 if pd.notna(value) else np.nan, units
    return float(value) if pd.notna(value) else np.nan, units


def _resource_mix_scale(row: pd.Series) -> str:
    """eGRID labels mix fields as percent, but the stored scale changes by vintage.

    2010-2016 use 0-100; 2018+ store the same 'percent' codes as 0-1 fractions.
    Detect from the selected row instead of trusting the header word 'percent'.
    """
    vals = [
        _to_numeric(row[c])
        for c in ("SRCLPR", "SRGSPR", "SRHYPR", "SRWIPR", "SRSOPR")
        if c in row.index
    ]
    finite = [v for v in vals if pd.notna(v)]
    if not finite:
        raise EgridSchemaError("Resource-mix fields are missing on the selected subregion row.")
    mx = max(finite)
    if mx > 1.5:
        return "percent_0_100"
    if mx <= 1.0000001:
        return "fraction_0_1"
    raise EgridSchemaError(
        f"Ambiguous eGRID resource-mix scale (max={mx}). "
        "Refusing to guess percent vs fraction."
    )


def _mix_to_share(value, scale: str) -> float:
    x = _to_numeric(value)
    if pd.isna(x):
        return np.nan
    if x < 0:
        raise EgridSchemaError(f"Negative resource-mix value {x}")
    if scale == "percent_0_100":
        if x > 100.0001:
            raise EgridSchemaError(f"Fuel-mix percent {x} exceeds 100.")
        return float(x) / 100.0
    if scale == "fraction_0_1":
        if x > 1.0000001:
            raise EgridSchemaError(f"Fuel-mix fraction {x} exceeds 1.")
        return float(x)
    raise EgridSchemaError(f"Unknown resource-mix scale {scale!r}")


def _nonbaseload_co2e_code(columns) -> str:
    if "SRNBC2E" in columns:
        return "SRNBC2E"
    if "SRNBC2ER" in columns:
        return "SRNBC2ER"
    raise EgridSchemaError(
        "Subregion sheet is missing non-baseload CO2e code SRNBC2E/SRNBC2ER."
    )


def _plant_subregions(series: pd.Series) -> list[str]:
    return sorted({str(v).strip() for v in series.dropna() if str(v).strip() and str(v) != "nan"})


def map_prineville_subregion(plants: pd.DataFrame, egrid_data_year: int) -> dict:
    """Map Prineville consumption location to an eGRID subregion from plant data.

    Location-based electricity consumption uses the subregion of the load, not
    the full PACW generator footprint. PACW plants can include a CAMX tail in
    some vintages; that is recorded as evidence and is not the selection rule.
    """
    st = plants["PSTATABB"].astype(str).str.strip()
    cnty = plants["CNTYNAME"].astype(str)
    oregon = plants.loc[st.eq("OR")].copy()
    crook = oregon.loc[cnty.str.contains("Crook", case=False, na=False)].copy()
    oregon_subs = _plant_subregions(oregon["SUBRGN"])
    crook_subs = _plant_subregions(crook["SUBRGN"])

    pacw_counts: dict[str, int] = {}
    pacw_n = 0
    if "BACODE" in plants.columns:
        pacw = plants.loc[plants["BACODE"].astype(str).str.upper().str.strip().eq("PACW")]
        pacw_n = int(len(pacw))
        pacw_counts = (
            pacw["SUBRGN"].astype(str).str.strip().value_counts(dropna=False).to_dict()
            if pacw_n
            else {}
        )
    elif "PCANAME" in plants.columns:
        pacw = plants.loc[
            plants["PCANAME"].astype(str).str.contains(r"PacifiCorp", case=False, na=False)
            & plants["PCANAME"].astype(str).str.contains(r"West|\bPACW\b", case=False, na=False)
        ]
        if not len(pacw):
            pacw = plants.loc[
                plants["PCANAME"].astype(str).str.contains(r"PacifiCorp", case=False, na=False)
            ]
        pacw_n = int(len(pacw))
        pacw_counts = (
            pacw["SUBRGN"].astype(str).str.strip().value_counts(dropna=False).to_dict()
            if pacw_n
            else {}
        )

    if crook_subs:
        if len(crook_subs) != 1:
            raise EgridSchemaError(
                f"eGRID{egrid_data_year} Crook County, Oregon plants map to multiple "
                f"subregions {crook_subs}."
            )
        selected = crook_subs[0]
        method = "crook_county_oregon_plants"
        if oregon_subs and oregon_subs != [selected]:
            raise EgridSchemaError(
                f"eGRID{egrid_data_year} Crook County subregion {selected} disagrees "
                f"with Oregon plant subregions {oregon_subs}."
            )
    else:
        if len(oregon_subs) != 1:
            raise EgridSchemaError(
                f"eGRID{egrid_data_year} has no Crook County plants and Oregon is not "
                f"a unique subregion ({oregon_subs}). Refusing to assume NWPP."
            )
        selected = oregon_subs[0]
        method = "oregon_plants_unique_subregion_no_crook_county_plants"

    return {
        "egrid_data_year": egrid_data_year,
        "egrid_subregion": selected,
        "subregion_selection_method": method,
        "n_crook_county_or_plants": int(len(crook)),
        "crook_county_subregions": ",".join(crook_subs),
        "n_oregon_plants": int(len(oregon)),
        "oregon_subregions": ",".join(oregon_subs),
        "n_pacw_plants": pacw_n,
        "pacw_plant_subregion_counts": json.dumps(pacw_counts, sort_keys=True),
        "selection_note": (
            "Location-based factor uses the eGRID subregion of Prineville / Crook "
            "County, Oregon. PACW generator geography is corroboration only and may "
            "include plants outside NWPP."
        ),
    }


def extract_subregion_row(
    srl: pd.DataFrame,
    descriptions: dict[str, str],
    subregion: str,
    source_file: str,
    source_revision: str,
    egrid_data_year: int,
) -> dict:
    missing = [c for c in REQUIRED_SRL_CODES if c not in srl.columns]
    if missing:
        raise EgridSchemaError(f"{source_file} SRL sheet missing codes {missing}")
    hits = srl.loc[srl["SUBRGN"].astype(str).str.strip().eq(subregion)]
    if len(hits) != 1:
        raise EgridSchemaError(
            f"{source_file} has {len(hits)} rows for subregion {subregion!r}; expected 1."
        )
    row = hits.iloc[0]
    co2, co2_units = _output_rate(row, descriptions, "SRCO2RTA")
    co2e, co2e_units = _output_rate(row, descriptions, "SRC2ERTA")
    nox, nox_units = _output_rate(row, descriptions, "SRNOXRTA")
    so2, so2_units = _output_rate(row, descriptions, "SRSO2RTA")
    ch4, ch4_units = _output_rate(row, descriptions, "SRCH4RTA")
    n2o, n2o_units = _output_rate(row, descriptions, "SRN2ORTA")
    nb_co2, nb_co2_units = _output_rate(row, descriptions, "SRNBCO2")
    nb_code = _nonbaseload_co2e_code(srl.columns)
    nb_co2e, nb_co2e_units = _output_rate(row, descriptions, nb_code)
    for name, units in {
        "SRCO2RTA": co2_units,
        "SRC2ERTA": co2e_units,
        "SRNOXRTA": nox_units,
        "SRSO2RTA": so2_units,
        "SRNBCO2": nb_co2_units,
        nb_code: nb_co2e_units,
    }.items():
        if units != "lb/MWh":
            raise EgridSchemaError(f"{source_file} {name} units are {units}, expected lb/MWh.")
    if ch4_units not in {"lb/MWh", "lb/GWh"} or n2o_units not in {"lb/MWh", "lb/GWh"}:
        raise EgridSchemaError(f"{source_file} CH4/N2O units unexpected: {ch4_units}, {n2o_units}")
    mix_scale = _resource_mix_scale(row)
    return {
        "egrid_data_year": egrid_data_year,
        "egrid_subregion": subregion,
        "egrid_subregion_name": str(row["SRNAME"]).strip(),
        "co2_lb_per_mwh": co2,
        "co2e_lb_per_mwh": co2e,
        "nox_lb_per_mwh": nox,
        "so2_lb_per_mwh": so2,
        "ch4_lb_per_mwh": ch4,
        "n2o_lb_per_mwh": n2o,
        "co2_nonbaseload_lb_per_mwh": nb_co2,
        "co2e_nonbaseload_lb_per_mwh": nb_co2e,
        "coal_share": _mix_to_share(row["SRCLPR"], mix_scale),
        "gas_share": _mix_to_share(row["SRGSPR"], mix_scale),
        "hydro_share": _mix_to_share(row["SRHYPR"], mix_scale),
        "wind_share": _mix_to_share(row["SRWIPR"], mix_scale),
        "solar_share": _mix_to_share(row["SRSOPR"], mix_scale),
        "fuel_mix_input_scale": mix_scale,
        "ch4_n2o_source_units": ch4_units,
        "nonbaseload_co2e_code": nb_code,
        "source_file": source_file,
        "source_revision": source_revision,
        "source_sheet": VINTAGES[egrid_data_year]["srl"],
        "output_rate_units": "lb/MWh",
        "provenance_class": "reported",
    }


def lb_per_mwh_to_tonnes(mwh, lb_per_mwh) -> float:
    if pd.isna(mwh) or pd.isna(lb_per_mwh):
        return np.nan
    return float(mwh) * float(lb_per_mwh) / LB_PER_METRIC_TONNE


def _fuel_import_proxy(hourly: pd.DataFrame) -> pd.Series:
    thermal = (
        1000.0 * pd.to_numeric(hourly.get("ng_col_mwh"), errors="coerce").fillna(0.0).clip(lower=0.0)
        + 450.0 * pd.to_numeric(hourly.get("ng_ng_mwh"), errors="coerce").fillna(0.0).clip(lower=0.0)
        + 500.0 * pd.to_numeric(hourly.get("ng_oth_mwh"), errors="coerce").fillna(0.0).clip(lower=0.0)
    )
    demand = pd.to_numeric(hourly["demand_reported_mwh"], errors="coerce").clip(lower=1.0)
    net_generation = pd.to_numeric(hourly["net_generation_reported_mwh"], errors="coerce").fillna(0.0).clip(lower=0.0)
    import_residual = (demand - net_generation).clip(lower=0.0)
    return (thermal + 350.0 * import_residual) / demand


def write_pacw_carbon_shape_compare(hourly: pd.DataFrame | None = None) -> pd.DataFrame | None:
    """Compare EIA-reported PACW consumed CO2 intensity with the fuel/import proxy.

    Neither series is Meta-specific or a marginal-emissions estimate.
    """
    if hourly is None:
        if not PACW_HOURLY.exists():
            return None
        hourly = pd.read_csv(PACW_HOURLY)
    z = hourly.copy()
    z["timestamp_utc"] = pd.to_datetime(z["timestamp_utc"], utc=True)
    z["year"] = z["timestamp_utc"].dt.year
    eia = pd.to_numeric(z.get("co2_intensity_consumed"), errors="coerce")
    proxy = _fuel_import_proxy(z)
    rows = []
    for year, idx in z.groupby("year").groups.items():
        e = eia.loc[idx]
        p = proxy.loc[idx]
        both = e.notna() & np.isfinite(e) & (e > 0) & p.notna() & np.isfinite(p)
        corr = float(e.loc[both].corr(p.loc[both])) if int(both.sum()) >= 24 else np.nan
        n_eia = int((e.notna() & np.isfinite(e) & (e > 0)).sum())
        rows.append(
            {
                "year": int(year),
                "n_hours": int(len(idx)),
                "n_eia_co2_intensity_consumed": n_eia,
                "n_fuel_import_proxy": int(p.notna().sum()),
                "n_both": int(both.sum()),
                "corr_eia_consumed_vs_fuel_import_proxy": corr,
                "eia_co2_intensity_consumed_mean": float(e.loc[e.notna() & (e > 0)].mean()) if n_eia else np.nan,
                "fuel_import_proxy_mean": float(p.mean()) if p.notna().any() else np.nan,
                "preferred_regional_shape": (
                    "eia_co2_intensity_consumed" if n_eia else "fuel_import_proxy"
                ),
                "accounting_note": (
                    "PACW regional physical carbon-shape diagnostic only; not campus "
                    "electricity and not Meta-specific marginal emissions. The fuel/"
                    "import score is a named sensitivity proxy, not the default shape "
                    "when EIA consumed intensity is present."
                ),
            }
        )
    out = pd.DataFrame(rows).sort_values("year")
    OUT_PACW_CARBON.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_PACW_CARBON, index=False)
    return out


def build_annual() -> tuple[pd.DataFrame, pd.DataFrame]:
    vintage_rows = []
    crosswalk_rows = []
    for data_year, spec in VINTAGES.items():
        path = RAW / spec["relative"]
        if not path.exists():
            raise FileNotFoundError(
                f"Required eGRID workbook missing: {path}. "
                "Organize files under data/raw/egrid/ without modifying originals."
            )
        print(f"Reading eGRID{data_year} {spec['relative']} ...")
        srl, descriptions = _load_sheet(path, spec["srl"], ("SUBRGN", "SRCO2RTA"))
        plants = _load_plant_map(path, spec["plnt"])
        mapped = map_prineville_subregion(plants, data_year)
        rates = extract_subregion_row(
            srl,
            descriptions,
            mapped["egrid_subregion"],
            source_file=f"data/raw/egrid/{spec['relative']}",
            source_revision=_revision_from_name(path.name),
            egrid_data_year=data_year,
        )
        vintage_rows.append(rates)
        crosswalk_rows.append({**mapped, "egrid_subregion_name": rates["egrid_subregion_name"]})
        print(
            f"  {mapped['subregion_selection_method']}: {rates['egrid_subregion']} "
            f"({rates['egrid_subregion_name']})"
        )
    vintages = pd.DataFrame(vintage_rows).set_index("egrid_data_year")
    crosswalk = pd.DataFrame(crosswalk_rows)
    rows = []
    for model_year in MODEL_YEARS:
        data_year = MODEL_YEAR_TO_EGRID[model_year]
        src = vintages.loc[data_year]
        carry = (
            f"Model year {model_year} uses eGRID{data_year} because EPA did not publish "
            f"a matching-year detailed workbook in this package's vintage map."
            if model_year != data_year
            else f"Model year {model_year} uses the matching eGRID{data_year} detailed workbook."
        )
        if model_year == 2024:
            carry = (
                "Model year 2024 explicitly uses eGRID2023; EPA had not published a "
                "2024 detailed workbook in this package."
            )
        cw = crosswalk.loc[crosswalk.egrid_data_year.eq(data_year)].iloc[0]
        rows.append(
            {
                "model_year": model_year,
                "egrid_data_year": int(data_year),
                "egrid_subregion": src["egrid_subregion"],
                "egrid_subregion_name": src["egrid_subregion_name"],
                "co2_lb_per_mwh": src["co2_lb_per_mwh"],
                "co2e_lb_per_mwh": src["co2e_lb_per_mwh"],
                "nox_lb_per_mwh": src["nox_lb_per_mwh"],
                "so2_lb_per_mwh": src["so2_lb_per_mwh"],
                "ch4_lb_per_mwh": src["ch4_lb_per_mwh"],
                "n2o_lb_per_mwh": src["n2o_lb_per_mwh"],
                "co2_nonbaseload_lb_per_mwh": src["co2_nonbaseload_lb_per_mwh"],
                "co2e_nonbaseload_lb_per_mwh": src["co2e_nonbaseload_lb_per_mwh"],
                "coal_share": src["coal_share"],
                "gas_share": src["gas_share"],
                "hydro_share": src["hydro_share"],
                "wind_share": src["wind_share"],
                "solar_share": src["solar_share"],
                "source_file": src["source_file"],
                "source_revision": src["source_revision"],
                "source_sheet": src["source_sheet"],
                "output_rate_units": src["output_rate_units"],
                "ch4_n2o_source_units": src["ch4_n2o_source_units"],
                "fuel_mix_input_scale": src["fuel_mix_input_scale"],
                "nonbaseload_co2e_code": src["nonbaseload_co2e_code"],
                "subregion_selection_method": cw["subregion_selection_method"],
                "vintage_mapping_note": carry,
                "accounting_boundary": (
                    "eGRID subregion total output emission rates for electricity "
                    "consumption at Prineville / Crook County, Oregon; not PACW BA "
                    "demand and not market-based/REC accounting"
                ),
                "provenance_class": "reported",
            }
        )
    annual = pd.DataFrame(rows)
    return annual, crosswalk


def build_meta_compare(annual: pd.DataFrame, targets: pd.DataFrame) -> pd.DataFrame:
    meta = targets[["year", "electricity_mwh_reported", "location_based_scope2_tco2e_reported"]].copy()
    z = annual.merge(meta, left_on="model_year", right_on="year", how="left", validate="one_to_one")
    z["meta_electricity_mwh"] = z["electricity_mwh_reported"]
    z["electricity_input_source"] = "data/canonical/meta_prineville_annual.csv::electricity_mwh_reported"
    z["egrid_co2_lb_per_mwh"] = z["co2_lb_per_mwh"]
    z["egrid_co2e_lb_per_mwh"] = z["co2e_lb_per_mwh"]
    z["egrid_estimated_co2_tonnes"] = [
        lb_per_mwh_to_tonnes(m, ef) for m, ef in zip(z["meta_electricity_mwh"], z["co2_lb_per_mwh"])
    ]
    z["egrid_estimated_co2e_tonnes"] = [
        lb_per_mwh_to_tonnes(m, ef) for m, ef in zip(z["meta_electricity_mwh"], z["co2e_lb_per_mwh"])
    ]
    z["egrid_estimated_nox_tonnes"] = [
        lb_per_mwh_to_tonnes(m, ef) for m, ef in zip(z["meta_electricity_mwh"], z["nox_lb_per_mwh"])
    ]
    z["egrid_estimated_so2_tonnes"] = [
        lb_per_mwh_to_tonnes(m, ef) for m, ef in zip(z["meta_electricity_mwh"], z["so2_lb_per_mwh"])
    ]
    z["meta_location_based_scope2_tonnes"] = z["location_based_scope2_tco2e_reported"]
    # Like-for-like difference uses eGRID CO2e vs Meta location-based Scope 2 (tCO2e).
    # The requested CO2 tonnes column is retained; it is not the same gas inventory.
    z["difference_tonnes"] = z["egrid_estimated_co2e_tonnes"] - z["meta_location_based_scope2_tonnes"]
    z["ratio_or_percent_difference"] = np.where(
        z["meta_location_based_scope2_tonnes"].notna() & (z["meta_location_based_scope2_tonnes"] != 0),
        100.0 * z["difference_tonnes"] / z["meta_location_based_scope2_tonnes"],
        np.nan,
    )
    z["difference_co2_vs_meta_scope2_tonnes"] = (
        z["egrid_estimated_co2_tonnes"] - z["meta_location_based_scope2_tonnes"]
    )
    z["comparison_note"] = (
        "eGRID tonnes = Meta campus MWh × eGRID subregion output rate / 2204.6226218487757 lb per metric tonne. "
        "difference_tonnes and ratio_or_percent_difference compare eGRID CO2e tonnes with Meta location-based "
        "Scope 2 (tCO2e). Market-based/REC accounting is not used. PACW demand is not used."
    )
    z["emissions_provenance_class"] = "derived"
    cols = [
        "year",
        "meta_electricity_mwh",
        "electricity_input_source",
        "egrid_data_year",
        "egrid_subregion",
        "egrid_co2_lb_per_mwh",
        "egrid_co2e_lb_per_mwh",
        "egrid_estimated_co2_tonnes",
        "egrid_estimated_co2e_tonnes",
        "egrid_estimated_nox_tonnes",
        "egrid_estimated_so2_tonnes",
        "meta_location_based_scope2_tonnes",
        "difference_tonnes",
        "ratio_or_percent_difference",
        "difference_co2_vs_meta_scope2_tonnes",
        "comparison_note",
        "emissions_provenance_class",
    ]
    return z[cols].sort_values("year").reset_index(drop=True)


def run_checks(
    annual: pd.DataFrame,
    compare: pd.DataFrame,
    crosswalk: pd.DataFrame,
    targets: pd.DataFrame,
) -> list[dict]:
    checks: list[dict] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "status": "PASS" if passed else "FAIL", "detail": detail})
        if not passed:
            raise AssertionError(f"{name}: {detail}")

    years = annual["model_year"].tolist()
    add("all_model_years_2011_2024", years == MODEL_YEARS, f"years={years}")
    add("no_duplicate_model_years", not annual["model_year"].duplicated().any(), "model_year unique")
    mapped = [MODEL_YEAR_TO_EGRID[int(y)] for y in annual["model_year"]]
    add(
        "correct_egrid_vintage_mapping",
        annual["egrid_data_year"].tolist() == mapped,
        f"mapped={annual['egrid_data_year'].tolist()}",
    )
    one_sub = annual.groupby("model_year")["egrid_subregion"].nunique().eq(1).all()
    add("one_unique_subregion_per_model_year", bool(one_sub), f"subregions={sorted(annual.egrid_subregion.unique())}")
    add(
        "source_workbook_and_vintage_preserved",
        annual["source_file"].notna().all() and annual["source_revision"].notna().all(),
        "source_file and source_revision present on every row",
    )
    add(
        "units_are_lb_per_mwh",
        (annual["output_rate_units"] == "lb/MWh").all(),
        f"units={sorted(annual.output_rate_units.unique())}",
    )
    numeric_ok = True
    missing_fields = []
    for col in RATE_FIELDS:
        s = pd.to_numeric(annual[col], errors="coerce")
        if s.isna().any() or not np.issubdtype(s.dtype, np.number):
            numeric_ok = False
            missing_fields.append(col)
    add("emission_factors_numeric_nonmissing", numeric_ok, f"missing_or_nonnumeric={missing_fields}")
    confused = np.isclose(
        annual["co2_lb_per_mwh"].to_numpy(float),
        annual["co2_nonbaseload_lb_per_mwh"].to_numpy(float),
        rtol=0.0,
        atol=1e-9,
    ).all()
    add(
        "normal_and_nonbaseload_factors_not_confused",
        (not confused) and ("co2_nonbaseload_lb_per_mwh" in annual.columns),
        "total output CO2 rates differ from non-baseload CO2 rates",
    )
    y2024 = annual.loc[annual.model_year.eq(2024)].iloc[0]
    add(
        "model_year_2024_uses_egrid2023",
        int(y2024.egrid_data_year) == 2023 and "eGRID2023" in str(y2024.vintage_mapping_note),
        f"egrid_data_year={int(y2024.egrid_data_year)}; note={y2024.vintage_mapping_note}",
    )
    add(
        "meta_electricity_is_campus_energy_input",
        compare["electricity_input_source"].eq(
            "data/canonical/meta_prineville_annual.csv::electricity_mwh_reported"
        ).all()
        and np.allclose(
            compare["meta_electricity_mwh"].to_numpy(float),
            targets.set_index("year").loc[compare["year"], "electricity_mwh_reported"].to_numpy(float),
        ),
        "compare.meta_electricity_mwh matches canonical Meta campus electricity",
    )
    pacw_substituted = False
    detail = "PACW hourly file absent; campus electricity still taken from Meta annual MWh"
    if PACW_HOURLY.exists():
        pacw = pd.read_csv(PACW_HOURLY, usecols=["timestamp_utc", "demand_reported_mwh"])
        pacw["timestamp_utc"] = pd.to_datetime(pacw["timestamp_utc"], utc=True)
        pacw["year"] = pacw["timestamp_utc"].dt.year
        annual_demand = pacw.groupby("year")["demand_reported_mwh"].sum()
        joined = compare.merge(annual_demand.rename("pacw_demand_mwh"), on="year", how="left")
        overlap = joined["pacw_demand_mwh"].notna()
        pacw_substituted = bool(
            overlap.any()
            and np.isclose(
                joined.loc[overlap, "meta_electricity_mwh"].to_numpy(float),
                joined.loc[overlap, "pacw_demand_mwh"].to_numpy(float),
                rtol=0.0,
                atol=1.0,
            ).any()
        )
        detail = (
            "Meta campus MWh is distinct from annual PACW reported demand on overlapping years"
        )
        add(
            "eia930_co2_intensity_consumed_available_as_regional_shape",
            "co2_intensity_consumed" in pd.read_csv(PACW_HOURLY, nrows=0).columns,
            "pacw_hourly.csv retains EIA consumed CO2 intensity",
        )
    add("pacw_demand_never_substituted_for_campus_electricity", not pacw_substituted, detail)
    add(
        "crosswalk_has_one_row_per_egrid_vintage",
        crosswalk["egrid_data_year"].tolist() == list(VINTAGES),
        f"crosswalk_years={crosswalk['egrid_data_year'].tolist()}",
    )
    mix = annual[["coal_share", "gas_share", "hydro_share", "wind_share", "solar_share"]].sum(axis=1)
    add(
        "fuel_shares_are_fractions_not_percent",
        bool(
            (annual[["coal_share", "gas_share", "hydro_share", "wind_share", "solar_share"]].max(axis=1) <= 1.0000001).all()
            and mix.between(0.5, 1.05).all()
        ),
        f"five-fuel share sums={mix.round(3).tolist()}",
    )
    add(
        "location_based_not_market_based",
        compare["comparison_note"].str.contains("Market-based/REC accounting is not used").all(),
        "market-based/REC excluded from the physical eGRID benchmark",
    )
    return checks


def self_test() -> None:
    assert MODEL_YEAR_TO_EGRID[2011] == 2010
    assert MODEL_YEAR_TO_EGRID[2024] == 2023
    assert abs(lb_per_mwh_to_tonnes(1000.0, 2204.6226218487757) - 1000.0) < 1e-9
    srl = pd.DataFrame(
        {
            "SUBRGN": ["NWPP", "CAMX"],
            "SRNAME": ["WECC Northwest", "WECC California"],
            "SRCO2RTA": [600.0, 500.0],
            "SRC2ERTA": [610.0, 510.0],
            "SRNOXRTA": [0.4, 0.5],
            "SRSO2RTA": [0.2, 0.3],
            "SRCH4RTA": [20.0, 10.0],
            "SRN2ORTA": [10.0, 5.0],
            "SRNBCO2": [900.0, 800.0],
            "SRNBC2ER": [910.0, 810.0],
            "SRCLPR": [25.0, 10.0],
            "SRGSPR": [20.0, 40.0],
            "SRHYPR": [40.0, 5.0],
            "SRWIPR": [10.0, 5.0],
            "SRSOPR": [5.0, 15.0],
        }
    )
    descriptions = {
        "SRCO2RTA": "eGRID subregion annual CO2 total output emission rate (lb/MWh)",
        "SRC2ERTA": "eGRID subregion annual CO2 equivalent total output emission rate (lb/MWh)",
        "SRNOXRTA": "eGRID subregion annual NOx total output emission rate (lb/MWh)",
        "SRSO2RTA": "eGRID subregion annual SO2 total output emission rate (lb/MWh)",
        "SRCH4RTA": "eGRID subregion annual CH4 total output emission rate (lb/GWh)",
        "SRN2ORTA": "eGRID subregion annual N2O total output emission rate (lb/GWh)",
        "SRNBCO2": "eGRID subregion annual CO2 non-baseload output emission rate (lb/MWh)",
        "SRNBC2ER": "eGRID subregion annual CO2e non-baseload output emission rate (lb/MWh)",
    }
    extracted = extract_subregion_row(
        srl, descriptions, "NWPP", "synthetic.xls", "unspecified", 2010
    )
    assert abs(extracted["ch4_lb_per_mwh"] - 0.020) < 1e-12
    assert abs(extracted["coal_share"] - 0.25) < 1e-12
    assert extracted["fuel_mix_input_scale"] == "percent_0_100"
    assert extracted["co2_lb_per_mwh"] == 600.0
    assert extracted["co2_nonbaseload_lb_per_mwh"] == 900.0
    frac = srl.copy()
    for col in ["SRCLPR", "SRGSPR", "SRHYPR", "SRWIPR", "SRSOPR"]:
        frac[col] = frac[col] / 100.0
    extracted_frac = extract_subregion_row(
        frac, descriptions, "NWPP", "synthetic.xls", "unspecified", 2010
    )
    assert abs(extracted_frac["coal_share"] - 0.25) < 1e-12
    assert extracted_frac["fuel_mix_input_scale"] == "fraction_0_1"
    plants = pd.DataFrame(
        {
            "PSTATABB": ["OR", "OR", "CA"],
            "CNTYNAME": ["Crook", "Deschutes", "Siskiyou"],
            "SUBRGN": ["NWPP", "NWPP", "CAMX"],
            "BACODE": ["PACW", "PACW", "PACW"],
        }
    )
    mapped = map_prineville_subregion(plants, 2014)
    assert mapped["egrid_subregion"] == "NWPP"
    assert mapped["subregion_selection_method"] == "crook_county_oregon_plants"
    bad = srl.drop(columns=["SRCO2RTA"])
    try:
        extract_subregion_row(bad, descriptions, "NWPP", "synthetic.xls", "unspecified", 2010)
        raise AssertionError("missing SRCO2RTA should fail")
    except EgridSchemaError:
        pass
    metric = dict(descriptions)
    metric["SRCO2RTA"] = "eGRID subregion annual CO2 total output emission rate (kg/MWh)"
    try:
        extract_subregion_row(srl, metric, "NWPP", "synthetic.xls", "unspecified", 2010)
        raise AssertionError("metric units should fail")
    except EgridSchemaError:
        pass
    print("PASS: prepare_egrid self-test")


def prepare() -> dict:
    if not TARGETS.exists():
        raise FileNotFoundError(f"Canonical Meta annual file missing: {TARGETS}")
    targets = pd.read_csv(TARGETS)
    annual, crosswalk = build_annual()
    compare = build_meta_compare(annual, targets)
    checks = run_checks(annual, compare, crosswalk, targets)
    pacw_compare = write_pacw_carbon_shape_compare()
    OUT_ANNUAL.parent.mkdir(parents=True, exist_ok=True)
    OUT_COMPARE.parent.mkdir(parents=True, exist_ok=True)
    annual.to_csv(OUT_ANNUAL, index=False)
    compare.to_csv(OUT_COMPARE, index=False)
    crosswalk.to_csv(OUT_CROSSWALK, index=False)
    pd.DataFrame(checks).to_csv(OUT_CHECKS, index=False)
    return {
        "n_model_years": int(len(annual)),
        "egrid_subregions": sorted(annual["egrid_subregion"].unique()),
        "vintage_map": {str(k): int(v) for k, v in MODEL_YEAR_TO_EGRID.items()},
        "outputs": [
            str(p.relative_to(ROOT))
            for p in [OUT_ANNUAL, OUT_COMPARE, OUT_CROSSWALK, OUT_CHECKS, OUT_PACW_CARBON]
            if p.exists()
        ],
        "pacw_carbon_shape_compare_rows": None if pacw_compare is None else int(len(pacw_compare)),
        "accounting_boundary": (
            "Meta campus electricity × eGRID subregion total output rates; "
            "PACW is regional context only"
        ),
    }


def main() -> dict:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    self_test()
    if args.self_test:
        return {"self_test": "PASS"}
    summary = prepare()
    print(json.dumps(summary, indent=2))
    checks = pd.read_csv(OUT_CHECKS)
    print("\neGRID prepare checks:")
    print(checks.to_string(index=False))
    compare = pd.read_csv(OUT_COMPARE)
    print("\nMeta × eGRID annual benchmark:")
    print(
        compare[
            [
                "year",
                "meta_electricity_mwh",
                "egrid_data_year",
                "egrid_subregion",
                "egrid_estimated_co2e_tonnes",
                "meta_location_based_scope2_tonnes",
                "difference_tonnes",
                "ratio_or_percent_difference",
            ]
        ].to_string(index=False)
    )
    return summary


if __name__ == "__main__":
    main()
