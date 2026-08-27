#!/usr/bin/env python3
"""IPMI total_power only → node_hourly. Extract to $TMPDIR, do not persist raw."""

from __future__ import annotations

import argparse
import os
import shutil
import time
from pathlib import Path

import duckdb
import pandas as pd

from m100_2021_common import (
    ARCHIVES_DIR,
    CATALOG_DIR,
    PROCESSED_DIR,
    hive_ym,
    month_bounds,
    n_threads,
    save_status,
)
from process_m100_facility_month import configure_duckdb, extract_members, parquet_glob


NOMINAL_SAMPLES_PER_HOUR = 180
HQ_COVERAGE = 0.90


def process_node_month(month: str, force: bool = False) -> dict:
    outp = PROCESSED_DIR / "node_hourly" / month / "m100_node_hourly.parquet"
    if outp.exists() and outp.stat().st_size > 10_000 and not force:
        save_status(month, node_extraction_status="done", processed_products=[str(outp)])
        return {"month": month, "skipped": True, "path": str(outp)}

    inv = pd.read_csv(CATALOG_DIR / "inventory" / f"{month}.csv")
    sub = inv.loc[
        inv.plugin.astype(str).str.contains("ipmi", case=False, na=False)
        & inv.metric.eq("total_power")
        & inv.archive_member.astype(str).str.endswith(".parquet")
    ]
    if sub.empty:
        save_status(month, node_extraction_status="skipped_no_total_power")
        return {"month": month, "skipped": True, "reason": "no total_power"}

    archive = ARCHIVES_DIR / f"{hive_ym(month)}.tar"
    members = sub["archive_member"].dropna().unique().tolist()
    start, end = month_bounds(month)
    start_ts = start.strftime("%Y-%m-%d %H:%M:%S")
    end_ts = end.strftime("%Y-%m-%d %H:%M:%S")
    tmp = Path(os.environ.get("TMPDIR") or "/tmp") / f"m100_node_{month}_{os.getpid()}"
    tmp.mkdir(parents=True, exist_ok=True)
    timings = {}
    try:
        t0 = time.time()
        extract_members(archive, members, tmp)
        timings["tar_extract_s"] = round(time.time() - t0, 2)
        plugin = str(sub["plugin"].iloc[0])
        glob = parquet_glob(tmp, plugin, "total_power")
        if glob is None:
            raise FileNotFoundError("extracted total_power parquet not found")
        con = duckdb.connect()
        configure_duckdb(con)
        t1 = time.time()
        df = con.execute(f"""
            SELECT
                date_trunc('hour', CAST(timestamp AS TIMESTAMP)) AS timestamp_utc,
                CAST(node AS VARCHAR) AS node,
                AVG(CAST(value AS DOUBLE)) AS total_power_mean,
                MIN(CAST(value AS DOUBLE)) AS total_power_min,
                MAX(CAST(value AS DOUBLE)) AS total_power_max,
                STDDEV_SAMP(CAST(value AS DOUBLE)) AS total_power_std,
                COUNT(value) AS total_power_count
            FROM read_parquet('{glob}')
            WHERE timestamp >= TIMESTAMP '{start_ts}'
              AND timestamp < TIMESTAMP '{end_ts}'
            GROUP BY 1, 2
        """).df()
        con.close()
        timings["duckdb_s"] = round(time.time() - t1, 2)
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
        df["total_power_coverage"] = df["total_power_count"] / float(NOMINAL_SAMPLES_PER_HOUR)
        df["high_quality"] = df["total_power_coverage"].ge(HQ_COVERAGE) & df["total_power_mean"].notna()
        outp.parent.mkdir(parents=True, exist_ok=True)
        t2 = time.time()
        df.to_parquet(outp, index=False)
        timings["parquet_write_s"] = round(time.time() - t2, 2)
        save_status(
            month,
            node_extraction_status="done",
            processed_products=[str(outp)],
            runtime_s=sum(timings.values()),
            failure=None,
        )
        return {
            "month": month,
            "timings": timings,
            "n_rows": int(len(df)),
            "n_nodes": int(df["node"].nunique()),
            "path": str(outp),
        }
    except Exception as exc:
        save_status(month, node_extraction_status="failed", failure=str(exc))
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--month", required=True)
    p.add_argument("--force", action="store_true")
    args = p.parse_args()
    print(process_node_month(args.month, force=args.force))


if __name__ == "__main__":
    main()
