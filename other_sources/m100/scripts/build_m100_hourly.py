#!/usr/bin/env python3
"""Stage A: extract selected metrics and build the M100 hourly node panel."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import pandas as pd

from m100_hourly_common import (
    HQ_COVERAGE_THRESHOLD,
    METRICS,
    add_derived_variables,
    aggregate_metric,
    configure_duckdb,
    default_archive_name,
    extract_required_metrics,
    month_bounds,
    month_calendar,
    population_summary,
    required_missing,
)


def build_hourly_dataset(interim_month: Path, start_ts: str, end_ts: str) -> pd.DataFrame:
    con = duckdb.connect()
    configure_duckdb(con)
    hourly = None
    for metric, plugin in METRICS.items():
        df = aggregate_metric(con, interim_month, plugin, metric, start_ts, end_ts)
        if df is None:
            continue
        print(f"  {metric}: {len(df):,} node-hours, {df['node'].nunique():,} nodes")
        hourly = df if hourly is None else hourly.merge(df, on=["hour", "node"], how="outer")
    con.close()
    return hourly


def write_panel_diagnostics(hourly: pd.DataFrame, month: str, path: Path) -> dict:
    summary = population_summary(hourly)
    cal = month_calendar(month)
    observed = pd.to_datetime(hourly["hour"].unique())
    missing_hours = cal.difference(pd.DatetimeIndex(observed))
    summary.update({
        "month": month,
        "hq_coverage_threshold": HQ_COVERAGE_THRESHOLD,
        "calendar_hours": int(len(cal)),
        "missing_calendar_hours": int(len(missing_hours)),
        "hour_start": str(hourly["hour"].min()),
        "hour_end": str(hourly["hour"].max()),
    })
    if "total_power_coverage" in hourly.columns:
        cov = hourly.loc[hourly["has_ipmi_power"], "total_power_coverage"]
        summary.update({
            "ipmi_coverage_mean": float(cov.mean()),
            "ipmi_coverage_median": float(cov.median()),
            "ipmi_coverage_p10": float(cov.quantile(0.10)),
        })
    path.write_text(json.dumps(summary, indent=2) + "\n")
    print("\n=== Panel diagnostics ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"  outer_union is NOT the compute-node population")
    if len(missing_hours):
        print(f"  first/last missing calendar hours: {missing_hours.min()} / {missing_hours.max()}")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument("--archive", type=Path, default=None)
    parser.add_argument("--interim-root", type=Path, default=Path("data/interim"))
    parser.add_argument("--processed-root", type=Path, default=Path("data/processed/hourly"))
    parser.add_argument(
        "--force-rebuild",
        action="store_true",
        help="Rebuild the processed Parquet even if it already exists",
    )
    args = parser.parse_args()

    month = args.month
    interim_month = args.interim_root / month / "selected_metrics"
    processed_dir = args.processed_root / month
    processed_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = processed_dir / "m100_node_hourly.parquet"

    archive = args.archive
    if archive is None:
        archive = Path("data/raw/archives") / default_archive_name(month)

    print(f"Month {month}")
    print(f"Archive: {archive} exists={archive.exists()}")
    print(f"Interim: {interim_month} resolve={interim_month.resolve()} exists={interim_month.exists()}")
    print(f"Processed: {parquet_path}")
    missing_now = required_missing(interim_month)
    print(f"Missing required partitions: {len(missing_now)}")
    if missing_now:
        print("  " + ", ".join(f"{p}/{m}" for p, m in missing_now))

    extract_required_metrics(archive, month, interim_month)
    missing = required_missing(interim_month)
    if missing:
        raise RuntimeError(f"Required metrics missing: {missing}")

    if parquet_path.exists() and not args.force_rebuild:
        print(f"Processed panel already exists: {parquet_path}")
        print("Use --force-rebuild to regenerate.")
        hourly = pd.read_parquet(parquet_path)
        write_panel_diagnostics(hourly, month, processed_dir / "panel_diagnostics.json")
        return

    start, end = month_bounds(month)
    start_ts = start.strftime("%Y-%m-%d %H:%M:%S")
    end_ts = end.strftime("%Y-%m-%d %H:%M:%S")
    print(f"Aggregating {start_ts} <= t < {end_ts}\n")
    hourly = build_hourly_dataset(interim_month, start_ts, end_ts)
    if hourly is None or hourly.empty:
        raise RuntimeError("No data found after aggregation.")

    hourly = add_derived_variables(hourly)
    sort_cols = ["hour", "node_num"] if hourly["node_num"].notna().all() else ["hour", "node"]
    hourly = hourly.sort_values(sort_cols).reset_index(drop=True)
    hourly.to_parquet(parquet_path, index=False)
    write_panel_diagnostics(hourly, month, processed_dir / "panel_diagnostics.json")
    print(f"\nWrote {parquet_path}")


if __name__ == "__main__":
    main()
