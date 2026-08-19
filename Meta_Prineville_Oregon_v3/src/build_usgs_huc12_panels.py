"""Build USGS NWAA HUC12 × month processed panels.

Creates source-specific full-period tables and a common-overlap panel.
Adds monthly volumes (*_m3_month) without altering native source values.
Does not add pscutot or irrcutot into IWA consum.
"""
from __future__ import annotations

import calendar
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from usgs_nwaa_config import (
    GEO_COLUMNS,
    IWA_MM_COLUMNS,
    IWA_RENAME,
    M3_PER_MILLION_US_GALLONS,
    MM_OVER_KM2_TO_M3,
    PROCESSED,
    SCOPES,
    SERIES,
    STUDY_HUCS,
    huc12_raw_dir,
    pad_huc12,
)

OVERLAP_START = "2009-10"
OVERLAP_END = "2020-09"


def load_geo() -> pd.DataFrame:
    geo = pd.read_csv(STUDY_HUCS, dtype=str)
    geo = geo.rename(columns={"huc12": "huc12_id"})
    geo["huc12_id"] = geo["huc12_id"].map(pad_huc12)
    for col in [
        "is_site",
        "is_touching_site",
        "same_site_huc10",
        "same_site_huc8",
        "scope_local",
        "scope_hydro_near",
        "network_depth",
        "areasqkm",
    ]:
        if col in geo.columns:
            geo[col] = pd.to_numeric(geo[col], errors="coerce")
    return geo


def concat_scope_files(model: str, variable: str, scope: str, prefix: str) -> pd.DataFrame:
    folder = huc12_raw_dir(model, variable, scope)
    files = sorted(folder.glob(f"{prefix}_*.csv"))
    if not files:
        return pd.DataFrame()
    frames = []
    for path in files:
        df = pd.read_csv(path, dtype={"huc12_id": str})
        df["huc12_id"] = df["huc12_id"].map(pad_huc12)
        df["_source_file"] = path.name
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    return out.drop(columns=["_source_file"])


def add_time_parts(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["year_month"] + "-01")
    df["year"] = df["date"].dt.year.astype(int)
    df["month"] = df["date"].dt.month.astype(int)
    return df


def attach_geo(df: pd.DataFrame, geo: pd.DataFrame, scope: str) -> pd.DataFrame:
    out = df.merge(geo, on="huc12_id", how="left", validate="many_to_one")
    out = out.loc[out[scope] == 1].copy()
    return out


def mm_to_m3(mm, areasqkm):
    return mm * areasqkm * MM_OVER_KM2_TO_M3


def mgd_to_m3_month(mgd, year, month):
    mgd_s = pd.Series(mgd, dtype="float64").reset_index(drop=True)
    days = [
        calendar.monthrange(int(y), int(m))[1]
        for y, m in zip(year, month)
    ]
    return (mgd_s * pd.Series(days, dtype="float64") * M3_PER_MILLION_US_GALLONS).to_numpy()


def expected_months(start: str, end: str) -> list[str]:
    return [
        ts.strftime("%Y-%m")
        for ts in pd.period_range(start, end, freq="M")
    ]


def complete_grid(hucs: list[str], months: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [(h, ym) for h in hucs for ym in months],
        columns=["huc12_id", "year_month"],
    )


def build_iwa(geo: pd.DataFrame, scope: str) -> pd.DataFrame:
    spec = SERIES["iwa_all"]
    raw = concat_scope_files(spec.model, spec.variable, scope, "hydrology")
    if raw.empty:
        return raw
    raw = raw.rename(columns=IWA_RENAME)
    hucs = geo.loc[geo[scope] == 1, "huc12_id"].tolist()
    grid = complete_grid(hucs, expected_months(spec.startdate, spec.enddate))
    panel = grid.merge(raw, on=["huc12_id", "year_month"], how="left")
    panel = attach_geo(panel, geo, scope)
    panel = add_time_parts(panel)
    for col in IWA_MM_COLUMNS:
        panel[col] = pd.to_numeric(panel[col], errors="coerce")
        panel[col.replace("_mm_month", "_m3_month")] = mm_to_m3(
            panel[col], panel["areasqkm"]
        )
    panel["iwa_sui"] = pd.to_numeric(panel["iwa_sui"], errors="coerce")
    cols = GEO_COLUMNS + [
        "year_month",
        "date",
        "year",
        "month",
        "iwa_sui",
        *IWA_MM_COLUMNS,
        *[c.replace("_mm_month", "_m3_month") for c in IWA_MM_COLUMNS],
    ]
    return panel[cols].sort_values(["huc12_id", "date"]).reset_index(drop=True)


def build_single_series(
    geo: pd.DataFrame,
    scope: str,
    spec_key: str,
) -> pd.DataFrame:
    spec = SERIES[spec_key]
    raw = concat_scope_files(spec.model, spec.variable, scope, spec.variable)
    if raw.empty:
        return raw
    if spec.native_column not in raw.columns:
        raise ValueError(
            f"{spec.variable} missing native column {spec.native_column}"
        )
    raw = raw.rename(columns={spec.native_column: spec.processed_column})
    keep = raw[["huc12_id", "year_month", spec.processed_column]].copy()
    hucs = geo.loc[geo[scope] == 1, "huc12_id"].tolist()
    grid = complete_grid(hucs, expected_months(spec.startdate, spec.enddate))
    panel = grid.merge(keep, on=["huc12_id", "year_month"], how="left")
    panel = attach_geo(panel, geo, scope)
    panel = add_time_parts(panel)
    panel[spec.processed_column] = pd.to_numeric(
        panel[spec.processed_column], errors="coerce"
    )
    panel[spec.processed_column.replace("_mgd", "_m3_month")] = mgd_to_m3_month(
        panel[spec.processed_column], panel["year"], panel["month"]
    )
    return panel.sort_values(["huc12_id", "date"]).reset_index(drop=True)


def merge_source_group(
    geo: pd.DataFrame,
    scope: str,
    spec_keys: list[str],
    name: str,
) -> pd.DataFrame:
    frames = []
    for key in spec_keys:
        frames.append(build_single_series(geo, scope, key))
    if any(f.empty for f in frames):
        missing = [k for k, f in zip(spec_keys, frames) if f.empty]
        raise RuntimeError(f"{name} {scope}: missing series {missing}")
    out = frames[0]
    for extra in frames[1:]:
        value_cols = [
            c
            for c in extra.columns
            if c.endswith("_mgd") or c.endswith("_m3_month")
        ]
        out = out.merge(
            extra[["huc12_id", "year_month", *value_cols]],
            on=["huc12_id", "year_month"],
            how="outer",
            validate="one_to_one",
        )
    cols = GEO_COLUMNS + ["year_month", "date", "year", "month"]
    value_cols = [
        c for c in out.columns if c.endswith("_mgd") or c.endswith("_m3_month")
    ]
    return out[cols + value_cols].sort_values(["huc12_id", "year_month"]).reset_index(
        drop=True
    )


def build_overlap(
    iwa: pd.DataFrame,
    pscu: pd.DataFrame,
    pswd: pd.DataFrame,
    irr: pd.DataFrame,
) -> pd.DataFrame:
    iwa_o = iwa.loc[iwa["year_month"].between(OVERLAP_START, OVERLAP_END)].copy()
    keys = ["huc12_id", "year_month"]
    geo_time = GEO_COLUMNS + ["year_month", "date", "year", "month"]

    def values(df: pd.DataFrame) -> pd.DataFrame:
        cols = [
            c
            for c in df.columns
            if c.endswith("_mgd")
            or c.endswith("_m3_month")
            or c.endswith("_mm_month")
            or c == "iwa_sui"
        ]
        return df[keys + cols]

    out = iwa_o[geo_time + [
        "iwa_sui",
        *IWA_MM_COLUMNS,
        *[c.replace("_mm_month", "_m3_month") for c in IWA_MM_COLUMNS],
    ]]
    for extra in (pscu, pswd, irr):
        extra_o = extra.loc[extra["year_month"].between(OVERLAP_START, OVERLAP_END)]
        out = out.merge(values(extra_o), on=keys, how="left", validate="one_to_one")
    ordered = geo_time + [
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
    present = [c for c in ordered if c in out.columns]
    return out[present].sort_values(["huc12_id", "date"]).reset_index(drop=True)


def save(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    print(f"Saved {path} {df.shape}")


def main() -> None:
    geo = load_geo()
    PROCESSED.mkdir(parents=True, exist_ok=True)
    for scope in SCOPES:
        print(f"\n=== {scope} ===")
        iwa = build_iwa(geo, scope)
        pscu = merge_source_group(geo, scope, ["pscutot"], "public_supply_cu")
        pswd = merge_source_group(
            geo, scope, ["pswdtot", "pswdgw", "pswdsw"], "public_supply_wd"
        )
        irr = merge_source_group(
            geo, scope, ["irrwdtot", "irrcutot"], "irrigation"
        )
        overlap = build_overlap(iwa, pscu, pswd, irr)
        save(iwa, PROCESSED / f"usgs_iwa_huc12_monthly_{scope}.csv")
        save(pscu, PROCESSED / f"usgs_public_supply_cu_huc12_monthly_{scope}.csv")
        save(pswd, PROCESSED / f"usgs_public_supply_wd_huc12_monthly_{scope}.csv")
        save(irr, PROCESSED / f"usgs_irrigation_huc12_monthly_{scope}.csv")
        save(overlap, PROCESSED / f"usgs_huc12_monthly_overlap_{scope}.csv")

    pd.DataFrame(
        [
            {
                "native_model": spec.model,
                "native_variable": spec.variable,
                "native_column": spec.native_column or "sui_frac/availab_mm/mo/strflow_mm/mo/consum_mm/mo",
                "processed_column": spec.processed_column or "iwa_*",
                "native_units": spec.units,
                "period": f"{spec.startdate}/{spec.enddate}",
                "description": spec.description,
            }
            for spec in SERIES.values()
        ]
    ).to_csv(PROCESSED / "variable_map.csv", index=False)
    (PROCESSED / "UNIT_CONVERSIONS.md").write_text(
        "\n".join(
            [
                "# USGS NWAA unit conversions",
                "",
                "Native API values are preserved in `data/raw/usgs_nwaa/`.",
                "Processed tables keep native-unit columns and add `*_m3_month`.",
                "",
                "## mm/month → m³/month (IWA depth variables)",
                "",
                "`m3_month = mm_month * areasqkm * 1000`",
                "",
                "Identity: 1 mm over 1 km² = 0.001 m × 1,000,000 m² = 1,000 m³.",
                "`areasqkm` is the Watershed Boundary Dataset HUC12 area from the study geography table.",
                "SUI is a fraction and is not converted to volume.",
                "",
                "## MGD → m³/month (public-supply and irrigation rates)",
                "",
                "`m3_month = mgd * days_in_month * 3785.411784`",
                "",
                "USGS NWAA water-use models report monthly *mean* rates in million U.S. gallons per day.",
                "`days_in_month` is the actual calendar length of that year-month (leap years included).",
                "1 million U.S. gallons = 3785.411784 m³.",
                "",
                "## Non-additivity",
                "",
                "Do not sum `pscutot` or `irrcutot` into IWA `consum`.",
                "IWA already routes sectoral consumptive use through the HUC12 network.",
                "Sector series are for interpretation/decomposition, not additive reconstruction.",
                "",
            ]
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
