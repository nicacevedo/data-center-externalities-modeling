"""Shared M100 hourly-panel constants and helpers."""

from __future__ import annotations

import os
from calendar import monthrange
from pathlib import Path

import duckdb
import pandas as pd


NOMINAL_SAMPLES_PER_HOUR = 180
HQ_COVERAGE_THRESHOLD = 0.90

METRICS = {
    "total_power": "ipmi_pub",
    "ambient": "ipmi_pub",
    "p0_power": "ipmi_pub",
    "p1_power": "ipmi_pub",
    "p0_mem_power": "ipmi_pub",
    "p1_mem_power": "ipmi_pub",
    "p0_io_power": "ipmi_pub",
    "p1_io_power": "ipmi_pub",
    "gpu0_core_temp": "ipmi_pub",
    "gpu1_core_temp": "ipmi_pub",
    "gpu3_core_temp": "ipmi_pub",
    "gpu4_core_temp": "ipmi_pub",
    "ps0_input_power": "ipmi_pub",
    "ps1_input_power": "ipmi_pub",
    "cpu_user": "ganglia_pub",
    "cpu_system": "ganglia_pub",
    "cpu_idle": "ganglia_pub",
    "proc_run": "ganglia_pub",
}

GPU_MEAN_COLS = [
    "gpu0_core_temp_mean",
    "gpu1_core_temp_mean",
    "gpu3_core_temp_mean",
    "gpu4_core_temp_mean",
]
GPU_MAX_COLS = [
    "gpu0_core_temp_max",
    "gpu1_core_temp_max",
    "gpu3_core_temp_max",
    "gpu4_core_temp_max",
]


def parse_month(month: str) -> tuple[int, int]:
    year_s, month_s = month.split("-")
    return int(year_s), int(month_s)


def month_bounds(month: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    year, mon = parse_month(month)
    start = pd.Timestamp(year=year, month=mon, day=1)
    last = monthrange(year, mon)[1]
    end = pd.Timestamp(year=year, month=mon, day=last) + pd.Timedelta(days=1)
    return start, end


def month_calendar(month: str) -> pd.DatetimeIndex:
    start, end = month_bounds(month)
    return pd.date_range(start, end, freq="h", inclusive="left")


def hive_year_month(month: str) -> str:
    year, mon = parse_month(month)
    return f"{year % 100:02d}-{mon:02d}"


def default_archive_name(month: str) -> str:
    return f"{hive_year_month(month)}.tar"


def n_threads() -> int:
    for key in ("SLURM_CPUS_PER_TASK", "SLURM_CPUS_ON_NODE"):
        val = os.environ.get(key)
        if val:
            try:
                return max(1, int(str(val).split("(")[0]))
            except ValueError:
                continue
    return max(1, min(8, os.cpu_count() or 4))


def configure_duckdb(con) -> None:
    threads = n_threads()
    tmpdir = os.environ.get("TMPDIR") or os.environ.get("SLURM_TMPDIR") or "/tmp"
    Path(tmpdir).mkdir(parents=True, exist_ok=True)
    safe_tmp = str(Path(tmpdir)).replace("'", "''")
    con.execute(f"SET threads={int(threads)}")
    con.execute(f"SET temp_directory='{safe_tmp}'")
    print(f"DuckDB threads={threads} temp_directory={tmpdir}")


def metric_dir(interim_month: Path, plugin: str, metric: str) -> Path:
    return interim_month / f"plugin={plugin}" / f"metric={metric}"


def required_missing(interim_month: Path) -> list[tuple[str, str]]:
    missing = []
    for metric, plugin in METRICS.items():
        path = metric_dir(interim_month, plugin, metric)
        if not path.exists() or not any(path.glob("*.parquet")):
            missing.append((plugin, metric))
    return missing


def extract_required_metrics(archive: Path, month: str, interim_month: Path) -> None:
    """Extract only required hive partitions in one tar pass."""
    ym = hive_year_month(month)
    missing = required_missing(interim_month)
    if not missing:
        print(f"All required metrics already present under {interim_month}")
        return
    if not archive.exists():
        raise FileNotFoundError(f"Archive not found: {archive}")

    members = []
    for plugin, metric in missing:
        members.append(f"year_month={ym}/plugin={plugin}/metric={metric}/")
    print(f"Extracting {len(members)} metric partition(s) from {archive}")
    interim_month.mkdir(parents=True, exist_ok=True)
    dest = str(interim_month)
    # Strip year_month=YY-MM so selected_metrics/plugin=... matches the layout.
    cmd = ["tar", "-xf", str(archive), "-C", dest, "--strip-components=1", *members]
    import subprocess

    subprocess.run(cmd, check=True)
    still = required_missing(interim_month)
    if still:
        raise RuntimeError(f"Still missing after extract: {still}")


def aggregate_metric(con, interim_month: Path, plugin: str, metric: str, start_ts, end_ts):
    path = metric_dir(interim_month, plugin, metric)
    if not path.exists():
        print(f"WARNING: missing {plugin}/{metric}")
        return None
    parquet_glob = str(path / "*.parquet").replace("'", "''")
    print(f"Aggregating {plugin}/{metric} ...")
    sql = f"""
        SELECT
            date_trunc('hour', CAST(timestamp AS TIMESTAMP)) AS hour,
            CAST(node AS VARCHAR) AS node,
            AVG(CAST(value AS DOUBLE)) AS {metric}_mean,
            MIN(CAST(value AS DOUBLE)) AS {metric}_min,
            MAX(CAST(value AS DOUBLE)) AS {metric}_max,
            STDDEV_SAMP(CAST(value AS DOUBLE)) AS {metric}_std,
            COUNT(value) AS {metric}_count
        FROM read_parquet('{parquet_glob}')
        WHERE timestamp >= TIMESTAMP '{start_ts}'
          AND timestamp < TIMESTAMP '{end_ts}'
        GROUP BY 1, 2
        ORDER BY 1, 2
    """
    return con.execute(sql).df()


def add_derived_variables(hourly: pd.DataFrame) -> pd.DataFrame:
    hourly = hourly.copy()
    hourly["hour"] = pd.to_datetime(hourly["hour"])
    node_num = pd.to_numeric(hourly["node"], errors="coerce")
    n_bad = int(node_num.isna().sum())
    if n_bad:
        print(f"WARNING: {n_bad} node IDs are non-numeric; keeping original identifier.")
    else:
        print("All node IDs are numeric; adding node_num for sorting.")
    hourly["node_num"] = node_num

    if "cpu_idle_mean" in hourly.columns:
        hourly["cpu_busy_pct"] = 100.0 - hourly["cpu_idle_mean"]
    if {"p0_power_mean", "p1_power_mean"}.issubset(hourly.columns):
        hourly["cpu_socket_power_w"] = hourly["p0_power_mean"] + hourly["p1_power_mean"]
    if {"p0_mem_power_mean", "p1_mem_power_mean"}.issubset(hourly.columns):
        hourly["memory_power_w"] = hourly["p0_mem_power_mean"] + hourly["p1_mem_power_mean"]
    if {"p0_io_power_mean", "p1_io_power_mean"}.issubset(hourly.columns):
        hourly["io_power_w"] = hourly["p0_io_power_mean"] + hourly["p1_io_power_mean"]

    gpu_mean = [c for c in GPU_MEAN_COLS if c in hourly.columns]
    gpu_max = [c for c in GPU_MAX_COLS if c in hourly.columns]
    if gpu_mean:
        hourly["gpu_core_temp_mean"] = hourly[gpu_mean].mean(axis=1, skipna=True)
        hourly["n_gpu_temp_sensors"] = hourly[gpu_mean].notna().sum(axis=1)
    if gpu_max:
        hourly["gpu_core_temp_max"] = hourly[gpu_max].max(axis=1, skipna=True)
    if {"ps0_input_power_mean", "ps1_input_power_mean"}.issubset(hourly.columns):
        hourly["psu_input_power_w"] = (
            hourly["ps0_input_power_mean"] + hourly["ps1_input_power_mean"]
        )
    if "total_power_count" in hourly.columns:
        hourly["total_power_coverage"] = (
            hourly["total_power_count"] / float(NOMINAL_SAMPLES_PER_HOUR)
        )

    hourly["has_ipmi_power"] = (
        hourly["total_power_mean"].notna()
        if "total_power_mean" in hourly.columns
        else False
    )
    hourly["has_ganglia_cpu"] = (
        hourly["cpu_idle_mean"].notna()
        if "cpu_idle_mean" in hourly.columns
        else False
    )
    hourly["high_quality"] = hourly["has_ipmi_power"] & hourly[
        "total_power_coverage"
    ].fillna(0).ge(HQ_COVERAGE_THRESHOLD)
    hourly["analysis_hq"] = hourly["high_quality"] & hourly["has_ganglia_cpu"]
    hourly["date"] = hourly["hour"].dt.normalize()
    hourly["hour_of_day"] = hourly["hour"].dt.hour
    return hourly


def population_summary(hourly: pd.DataFrame) -> dict:
    ipmi = set(hourly.loc[hourly["has_ipmi_power"], "node"].unique())
    ganglia = set(hourly.loc[hourly["has_ganglia_cpu"], "node"].unique())
    common = ipmi & ganglia
    return {
        "n_ipmi_power_nodes": len(ipmi),
        "n_ganglia_cpu_nodes": len(ganglia),
        "n_common_cpu_power_nodes": len(common),
        "n_outer_union_nodes": int(hourly["node"].nunique()),
        "n_node_hours": int(len(hourly)),
        "n_hq_power_node_hours": int(hourly["high_quality"].sum()),
        "n_analysis_hq_node_hours": int(hourly["analysis_hq"].sum()),
        "n_observed_hours": int(hourly["hour"].nunique()),
    }
