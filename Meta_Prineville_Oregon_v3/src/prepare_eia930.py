"""Convert the canonical EIA-930 PACW historical workbook into hourly processed files.

The Grid Monitor Excel download is the full reported BA history. This script does not
modify `data/raw/eia930/historical/PACW.xlsx`. It does not concatenate the EIA API
into that history. API files, when present, are used only for 2019-2024 overlap
comparison.

EIA-930 is PacifiCorp West balancing-authority data, not campus feeder telemetry.
Reported, imputed, and adjusted MWh series are retained as separate columns.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import json

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
XLSX = ROOT / "data" / "raw" / "eia930" / "historical" / "PACW.xlsx"
API_REGION = ROOT / "data" / "raw" / "eia930" / "PACW_region-data_2019_2024.csv"
OUT_HOURLY = ROOT / "data" / "processed" / "pacw_hourly.csv"
OUT_COVERAGE = ROOT / "outputs" / "eia930_series_coverage.csv"
OUT_OVERLAP = ROOT / "outputs" / "eia930_xlsx_api_overlap.csv"
OUT_CHECKS = ROOT / "outputs" / "eia930_prepare_checks.csv"

BA = "PACW"
END_UTC = pd.Timestamp("2024-12-31 23:59:59", tz="UTC")
TIMESTAMP_CONVENTION = "hour_ending_utc"
PROVENANCE = (
    "reported EIA-930 PACW historical workbook (Grid Monitor BA download); "
    "balancing-authority electricity demand/generation/interchange; not campus meter data"
)

HOURLY_RENAME = {
    "BA": "ba",
    "UTC time": "timestamp_utc",
    "Local date": "local_date",
    "Hour": "local_hour_ending",
    "Local time": "local_time",
    "Time zone": "time_zone",
    "Generation only?": "generation_only",
    "Demand forecast": "demand_forecast_mwh",
    "Demand": "demand_reported_mwh",
    "Net generation": "net_generation_reported_mwh",
    "Total interchange": "total_interchange_reported_mwh",
    "Imputed demand": "demand_imputed_mwh",
    "Imputed net generation": "net_generation_imputed_mwh",
    "Imputed total interchange": "total_interchange_imputed_mwh",
    "Adjusted demand": "demand_adjusted_mwh",
    "Adjusted net generation": "net_generation_adjusted_mwh",
    "Adjusted total interchange": "total_interchange_adjusted_mwh",
    "NG: COL": "ng_col_mwh",
    "NG: NG": "ng_ng_mwh",
    "NG: NUC": "ng_nuc_mwh",
    "NG: OIL": "ng_oil_mwh",
    "NG: GEO": "ng_geo_mwh",
    "NG: WAT": "ng_wat_mwh",
    "NG: PS": "ng_ps_mwh",
    "NG: SUN": "ng_sun_mwh",
    "NG: SNB": "ng_snb_mwh",
    "NG: WND": "ng_wnd_mwh",
    "NG: WNB": "ng_wnb_mwh",
    "NG: BAT": "ng_bat_mwh",
    "NG: OES": "ng_oes_mwh",
    "NG: UES": "ng_ues_mwh",
    "NG: OTH": "ng_oth_mwh",
    "NG: UNK": "ng_unk_mwh",
    "Imputed COL Gen": "ng_col_imputed_mwh",
    "Imputed NG Gen": "ng_ng_imputed_mwh",
    "Imputed NUC Gen": "ng_nuc_imputed_mwh",
    "Imputed OIL Gen": "ng_oil_imputed_mwh",
    "Imputed GEO Gen": "ng_geo_imputed_mwh",
    "Imputed WAT Gen": "ng_wat_imputed_mwh",
    "Imputed PS Gen": "ng_ps_imputed_mwh",
    "Imputed SUN Gen": "ng_sun_imputed_mwh",
    "Imputed SNB Gen": "ng_snb_imputed_mwh",
    "Imputed WND Gen": "ng_wnd_imputed_mwh",
    "Imputed WNB Gen": "ng_wnb_imputed_mwh",
    "Imputed BAT Gen": "ng_bat_imputed_mwh",
    "Imputed OES Gen": "ng_oes_imputed_mwh",
    "Imputed UES Gen": "ng_ues_imputed_mwh",
    "Imputed OTH Gen": "ng_oth_imputed_mwh",
    "Imputed UNK Gen": "ng_unk_imputed_mwh",
    "Adjusted COL Gen": "ng_col_adjusted_mwh",
    "Adjusted NG Gen": "ng_ng_adjusted_mwh",
    "Adjusted NUC Gen": "ng_nuc_adjusted_mwh",
    "Adjusted OIL Gen": "ng_oil_adjusted_mwh",
    "Adjusted GEO Gen": "ng_geo_adjusted_mwh",
    "Adjusted WAT Gen": "ng_wat_adjusted_mwh",
    "Adjusted PS Gen": "ng_ps_adjusted_mwh",
    "Adjusted SUN Gen": "ng_sun_adjusted_mwh",
    "Adjusted SNB Gen": "ng_snb_adjusted_mwh",
    "Adjusted WND Gen": "ng_wnd_adjusted_mwh",
    "Adjusted WNB Gen": "ng_wnb_adjusted_mwh",
    "Adjusted BAT Gen": "ng_bat_adjusted_mwh",
    "Adjusted OES Gen": "ng_oes_adjusted_mwh",
    "Adjusted UES Gen": "ng_ues_adjusted_mwh",
    "Adjusted OTH Gen": "ng_oth_adjusted_mwh",
    "Adjusted UNK Gen": "ng_unk_adjusted_mwh",
    "AVA": "interchange_ava_mwh",
    "AVRN": "interchange_avrn_mwh",
    "BPAT": "interchange_bpat_mwh",
    "CISO": "interchange_ciso_mwh",
    "GCPD": "interchange_gcpd_mwh",
    "IPCO": "interchange_ipco_mwh",
    "PACE": "interchange_pace_mwh",
    "PGE": "interchange_pge_mwh",
    "CO2 Factor: COL": "co2_factor_col",
    "CO2 Factor: NG": "co2_factor_ng",
    "CO2 Factor: OIL": "co2_factor_oil",
    "CO2 Emissions: COL": "co2_emissions_col",
    "CO2 Emissions: NG": "co2_emissions_ng",
    "CO2 Emissions: OIL": "co2_emissions_oil",
    "CO2 Emissions: Other": "co2_emissions_other",
    "CO2 Emissions Generated": "co2_emissions_generated",
    "CO2 Emissions Imported": "co2_emissions_imported",
    "CO2 Emissions Exported": "co2_emissions_exported",
    "CO2 Emissions Consumed": "co2_emissions_consumed",
    "Positive Generation": "positive_generation_mwh",
    "Consumed Electricity": "consumed_electricity_mwh",
    "CO2 Emissions Intensity for Generated Electricity": "co2_intensity_generated",
    "CO2 Emissions Intensity for Consumed Electricity": "co2_intensity_consumed",
}

ISSUE_USECOLS = [
    "UTC time",
    "Data issue",
    "Missing NG by energy source",
    "DF range error",
    "D range error",
    "NG range error",
    "TI range error",
]
ISSUE_RENAME = {
    "UTC time": "timestamp_utc",
    "Data issue": "known_data_issue",
    "Missing NG by energy source": "missing_ng_by_energy_source",
    "DF range error": "demand_forecast_range_error",
    "D range error": "demand_range_error",
    "NG range error": "net_generation_range_error",
    "TI range error": "total_interchange_range_error",
}
API_TYPES = {
    "D": "demand_reported_mwh",
    "DF": "demand_forecast_mwh",
    "NG": "net_generation_reported_mwh",
    "TI": "total_interchange_reported_mwh",
}


def _cut_to_reconstruction_window(d: pd.DataFrame, ts_col: str = "timestamp_utc") -> pd.DataFrame:
    z = d.copy()
    z[ts_col] = pd.to_datetime(z[ts_col], utc=True)
    return z.loc[z[ts_col] <= END_UTC].copy()


def coverage_table(hourly: pd.DataFrame) -> pd.DataFrame:
    rows = []
    ts = pd.to_datetime(hourly["timestamp_utc"])
    for col in hourly.columns:
        s = hourly[col]
        nn = s.notna()
        if nn.any():
            first = ts[nn].iloc[0]
            last = ts[nn].iloc[-1]
            n = int(nn.sum())
        else:
            first = last = pd.NaT
            n = 0
        rows.append(
            {
                "column": col,
                "n_nonmissing": n,
                "n_rows": int(len(hourly)),
                "first_timestamp_utc": None if pd.isna(first) else pd.Timestamp(first).strftime("%Y-%m-%d %H:%M:%S"),
                "last_timestamp_utc": None if pd.isna(last) else pd.Timestamp(last).strftime("%Y-%m-%d %H:%M:%S"),
                "note": "blank remains missing; zeros are reported zeros",
            }
        )
    return pd.DataFrame(rows)


def normalize_hourly(raw: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in HOURLY_RENAME if c not in raw.columns]
    if missing:
        raise ValueError(f"PACW.xlsx Published Hourly Data missing columns: {missing}")
    extra = [c for c in raw.columns if c not in HOURLY_RENAME]
    if extra:
        raise ValueError(f"Unexpected Published Hourly Data columns: {extra}")
    z = raw.rename(columns=HOURLY_RENAME).copy()
    z["timestamp_utc"] = pd.to_datetime(z["timestamp_utc"], utc=True)
    z["local_date"] = pd.to_datetime(z["local_date"]).dt.strftime("%Y-%m-%d")
    z["local_time"] = pd.to_datetime(z["local_time"])
    ba = set(z["ba"].dropna().astype(str).str.strip().unique())
    if ba != {BA}:
        raise ValueError(f"Expected BA={BA}, found {sorted(ba)}")
    if z["timestamp_utc"].duplicated().any():
        raise ValueError("Duplicate UTC timestamps in PACW.xlsx Published Hourly Data.")
    return z.sort_values("timestamp_utc").reset_index(drop=True)


def load_known_data_issues(path: Path) -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name="Known Data Issues", usecols=ISSUE_USECOLS, engine="openpyxl")
    z = raw.rename(columns=ISSUE_RENAME)
    z["timestamp_utc"] = pd.to_datetime(z["timestamp_utc"], utc=True)
    return z


def attach_issue_flags(hourly: pd.DataFrame, issues: pd.DataFrame) -> pd.DataFrame:
    flag_cols = [c for c in issues.columns if c != "timestamp_utc"]
    out = hourly.merge(issues, on="timestamp_utc", how="left", validate="one_to_one")
    for col in flag_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def add_provenance(hourly: pd.DataFrame) -> pd.DataFrame:
    z = hourly.copy()
    z["timestamp_convention"] = TIMESTAMP_CONVENTION
    z["source_file"] = "data/raw/eia930/historical/PACW.xlsx"
    z["source_sheet"] = "Published Hourly Data"
    z["grid_provenance"] = PROVENANCE
    z["reconstruction_window_note"] = (
        "Rows after 2024-12-31 23:59:59 UTC are excluded from the current Prineville "
        "reconstruction window; the source workbook is left intact."
    )
    preferred = [
        "timestamp_utc",
        "ba",
        "local_date",
        "local_hour_ending",
        "local_time",
        "time_zone",
        "generation_only",
        "demand_forecast_mwh",
        "demand_reported_mwh",
        "demand_imputed_mwh",
        "demand_adjusted_mwh",
        "net_generation_reported_mwh",
        "net_generation_imputed_mwh",
        "net_generation_adjusted_mwh",
        "total_interchange_reported_mwh",
        "total_interchange_imputed_mwh",
        "total_interchange_adjusted_mwh",
        "known_data_issue",
        "missing_ng_by_energy_source",
        "demand_forecast_range_error",
        "demand_range_error",
        "net_generation_range_error",
        "total_interchange_range_error",
    ]
    cols = [c for c in preferred if c in z.columns] + [c for c in z.columns if c not in preferred]
    return z[cols]


def compare_api_overlap(hourly: pd.DataFrame, api_path: Path) -> pd.DataFrame:
    if not api_path.exists():
        return pd.DataFrame(
            [
                {
                    "series": None,
                    "alignment": None,
                    "status": "skipped",
                    "detail": f"API file not present: {api_path.name}",
                }
            ]
        )
    api = pd.read_csv(api_path)
    api["timestamp_utc"] = pd.to_datetime(api["period"], utc=True)
    api["type"] = api["type"].astype(str)
    api["value"] = pd.to_numeric(api["value"], errors="coerce")
    wide = api.pivot_table(index="timestamp_utc", columns="type", values="value", aggfunc="first")
    rows = []
    alignments = {
        "same_timestamp": hourly["timestamp_utc"],
        "xlsx_hour_ending_vs_api_hour_beginning": hourly["timestamp_utc"] - pd.Timedelta(hours=1),
    }
    for align_name, left_ts in alignments.items():
        left = hourly.copy()
        left["_join_ts"] = left_ts
        for code, col in API_TYPES.items():
            if code not in wide.columns:
                rows.append(
                    {
                        "series": col,
                        "alignment": align_name,
                        "status": "missing_api_type",
                        "n_overlap": 0,
                        "n_equal": 0,
                        "n_differ": 0,
                        "max_abs_diff_mwh": np.nan,
                    }
                )
                continue
            merged = pd.DataFrame({"_join_ts": left["_join_ts"], "xlsx": left[col]}).merge(
                wide[code].rename("api"),
                left_on="_join_ts",
                right_index=True,
                how="inner",
            )
            both = merged["xlsx"].notna() & merged["api"].notna()
            n_overlap = int(both.sum())
            if n_overlap == 0:
                rows.append(
                    {
                        "series": col,
                        "alignment": align_name,
                        "status": "no_overlap",
                        "n_overlap": 0,
                        "n_equal": 0,
                        "n_differ": 0,
                        "max_abs_diff_mwh": np.nan,
                    }
                )
                continue
            diff = (merged.loc[both, "xlsx"].to_numpy(float) - merged.loc[both, "api"].to_numpy(float))
            n_equal = int(np.isclose(diff, 0.0, atol=1e-6, rtol=0.0).sum())
            n_differ = n_overlap - n_equal
            rows.append(
                {
                    "series": col,
                    "alignment": align_name,
                    "status": "compared",
                    "n_overlap": n_overlap,
                    "n_equal": n_equal,
                    "n_differ": n_differ,
                    "max_abs_diff_mwh": float(np.nanmax(np.abs(diff))) if n_overlap else np.nan,
                }
            )
    return pd.DataFrame(rows)


def run_checks(hourly: pd.DataFrame, raw_n: int) -> list[dict]:
    checks: list[dict] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "status": "PASS" if passed else "FAIL", "detail": detail})
        if not passed:
            raise AssertionError(f"{name}: {detail}")

    add("ba_is_pacw", set(hourly["ba"].unique()) == {BA}, f"ba={sorted(hourly['ba'].unique())}")
    add("unique_utc", hourly["timestamp_utc"].is_unique, f"n={len(hourly)}")
    add(
        "reconstruction_window_ends_2024",
        hourly["timestamp_utc"].max() <= END_UTC,
        f"max={hourly['timestamp_utc'].max()}",
    )
    add(
        "workbook_not_truncated_before_read",
        raw_n > len(hourly),
        f"raw_n={raw_n} kept={len(hourly)}",
    )
    add(
        "reported_imputed_adjusted_are_separate_columns",
        {"demand_reported_mwh", "demand_imputed_mwh", "demand_adjusted_mwh"} <= set(hourly.columns),
        "reported/imputed/adjusted remain separate columns",
    )
    add(
        "missing_reported_demand_not_converted_to_zero",
        hourly["demand_reported_mwh"].isna().any(),
        f"n_missing={int(hourly['demand_reported_mwh'].isna().sum())}",
    )
    add("known_data_issue_attached", "known_data_issue" in hourly.columns, "issue flag joined")
    return checks


def self_test() -> None:
    hours = pd.to_datetime(
        ["2024-12-31 22:00:00", "2024-12-31 23:00:00", "2025-01-01 00:00:00"], utc=True
    )
    raw = pd.DataFrame(
        {
            src: ([BA] * 3 if src == "BA" else hours if src in {"UTC time", "Local date", "Local time"} else [1, 2, 3])
            for src in HOURLY_RENAME
        }
    )
    raw["Demand"] = [10.0, np.nan, 30.0]
    raw["Imputed demand"] = [np.nan, 11.0, np.nan]
    raw["Adjusted demand"] = [10.0, 11.0, 30.0]
    raw["Demand forecast"] = [12.0, 12.0, 12.0]
    raw["Net generation"] = [8.0, 8.0, 8.0]
    raw["Total interchange"] = [-2.0, -2.0, -2.0]
    raw["Generation only?"] = ["N", "N", "N"]
    raw["Hour"] = [1, 2, 3]
    raw["Time zone"] = ["Pacific", "Pacific", "Pacific"]
    for col in HOURLY_RENAME:
        if col not in raw.columns:
            raw[col] = np.nan
    raw = raw[list(HOURLY_RENAME)]
    z = normalize_hourly(raw)
    z = _cut_to_reconstruction_window(z)
    assert len(z) == 2, z
    assert pd.isna(z.loc[z.timestamp_utc.eq(hours[1]), "demand_reported_mwh"].iloc[0])
    assert float(z.loc[z.timestamp_utc.eq(hours[1]), "demand_imputed_mwh"].iloc[0]) == 11.0
    assert float(z.loc[z.timestamp_utc.eq(hours[0]), "demand_reported_mwh"].iloc[0]) == 10.0
    print("PASS: prepare_eia930 self-test")


def prepare() -> dict:
    if not XLSX.exists():
        raise FileNotFoundError(
            f"Canonical EIA-930 workbook missing: {XLSX}. Place the untouched Grid Monitor PACW.xlsx there."
        )
    raw = pd.read_excel(XLSX, sheet_name="Published Hourly Data", engine="openpyxl")
    raw_n = len(raw)
    hourly = normalize_hourly(raw)
    hourly = _cut_to_reconstruction_window(hourly)
    issues = _cut_to_reconstruction_window(load_known_data_issues(XLSX))
    hourly = attach_issue_flags(hourly, issues)
    hourly = add_provenance(hourly)
    coverage = coverage_table(hourly)
    overlap = compare_api_overlap(hourly, API_REGION)
    checks = run_checks(hourly, raw_n)

    OUT_HOURLY.parent.mkdir(parents=True, exist_ok=True)
    OUT_COVERAGE.parent.mkdir(parents=True, exist_ok=True)
    hourly.to_csv(OUT_HOURLY, index=False)
    coverage.to_csv(OUT_COVERAGE, index=False)
    overlap.to_csv(OUT_OVERLAP, index=False)
    pd.DataFrame(checks).to_csv(OUT_CHECKS, index=False)
    return {
        "canonical_source": str(XLSX.relative_to(ROOT)),
        "n_workbook_rows": raw_n,
        "n_reconstruction_rows": int(len(hourly)),
        "first_timestamp_utc": hourly["timestamp_utc"].min().isoformat(),
        "last_timestamp_utc": hourly["timestamp_utc"].max().isoformat(),
        "outputs": [str(p.relative_to(ROOT)) for p in [OUT_HOURLY, OUT_COVERAGE, OUT_OVERLAP, OUT_CHECKS]],
        "api_role": "overlap validation / future updating; not concatenated into the canonical series",
        "accounting_boundary": "PACW balancing authority; not campus feeder electricity",
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
    overlap = pd.read_csv(OUT_OVERLAP)
    print("\nXLSX vs API overlap (not a concatenation):")
    print(overlap.to_string(index=False))
    cov = pd.read_csv(OUT_COVERAGE)
    core = cov[cov["column"].isin([
        "demand_reported_mwh",
        "demand_forecast_mwh",
        "net_generation_reported_mwh",
        "total_interchange_reported_mwh",
        "ng_col_mwh",
        "ng_ng_mwh",
        "ng_wat_mwh",
        "ng_sun_mwh",
        "ng_wnd_mwh",
        "ng_oth_mwh",
        "demand_imputed_mwh",
        "known_data_issue",
    ])]
    print("\nCore series coverage in the 2015-07-01 to 2024-12-31 window:")
    print(core.to_string(index=False))
    return summary


if __name__ == "__main__":
    main()
