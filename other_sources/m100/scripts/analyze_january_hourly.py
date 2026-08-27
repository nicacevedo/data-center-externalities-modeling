#!/usr/bin/env python3
"""Historical January 2021 combined hourly script (kept for reference).

The reusable pipeline is:
  scripts/build_m100_hourly.py
  scripts/analyze_m100_hourly.py
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
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
COMPONENT_VARS = [
    "cpu_socket_power_w",
    "memory_power_w",
    "io_power_w",
    "gpu_core_temp_mean",
    "ambient_mean",
]


def n_threads():
    for key in ("SLURM_CPUS_PER_TASK", "SLURM_CPUS_ON_NODE"):
        val = os.environ.get(key)
        if val:
            try:
                return max(1, int(str(val).split("(")[0]))
            except ValueError:
                continue
    return max(1, os.cpu_count() or 4)


def configure_duckdb(con):
    threads = n_threads()
    tmpdir = os.environ.get("TMPDIR") or os.environ.get("SLURM_TMPDIR") or "/tmp"
    Path(tmpdir).mkdir(parents=True, exist_ok=True)
    safe_tmp = str(Path(tmpdir)).replace("'", "''")
    con.execute(f"SET threads={int(threads)}")
    con.execute(f"SET temp_directory='{safe_tmp}'")
    print(f"DuckDB threads={threads} temp_directory={tmpdir}")


def aggregate_metric(con, data_root, plugin, metric, start_ts, end_ts):
    metric_dir = (
        data_root / "year_month=21-01" / f"plugin={plugin}" / f"metric={metric}"
    )
    if not metric_dir.exists():
        print(f"WARNING: missing {plugin}/{metric}")
        return None

    parquet_glob = str(metric_dir / "*.parquet").replace("'", "''")
    print(f"Aggregating {plugin}/{metric} ...")
    sql = f"""
        SELECT
            date_trunc('hour', CAST(timestamp AS TIMESTAMP)) AS hour,
            CAST(node AS VARCHAR) AS node,
            AVG(CAST(value AS DOUBLE)) AS {metric}_mean,
            MIN(CAST(value AS DOUBLE)) AS {metric}_min,
            MAX(CAST(value AS DOUBLE)) AS {metric}_max,
            STDDEV_SAMP(CAST(value AS DOUBLE)) AS {metric}_std,
            COUNT(*) AS {metric}_count
        FROM read_parquet('{parquet_glob}')
        WHERE timestamp >= TIMESTAMP '{start_ts}'
          AND timestamp < TIMESTAMP '{end_ts}'
        GROUP BY 1, 2
        ORDER BY 1, 2
    """
    return con.execute(sql).df()


def build_hourly_dataset(data_root, start_ts, end_ts):
    con = duckdb.connect()
    configure_duckdb(con)
    hourly = None
    for metric, plugin in METRICS.items():
        df = aggregate_metric(con, data_root, plugin, metric, start_ts, end_ts)
        if df is None:
            continue
        print(f"  {metric}: {len(df):,} node-hours, {df['node'].nunique():,} nodes")
        hourly = df if hourly is None else hourly.merge(df, on=["hour", "node"], how="outer")
    con.close()
    return hourly


def add_derived_variables(hourly):
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

    hourly["has_ipmi_power"] = hourly["total_power_mean"].notna() if "total_power_mean" in hourly.columns else False
    hourly["has_ganglia_cpu"] = hourly["cpu_idle_mean"].notna() if "cpu_idle_mean" in hourly.columns else False
    hourly["high_quality"] = hourly["has_ipmi_power"] & hourly["total_power_coverage"].fillna(0).ge(HQ_COVERAGE_THRESHOLD)
    hourly["analysis_hq"] = hourly["high_quality"] & hourly["has_ganglia_cpu"]
    hourly["date"] = hourly["hour"].dt.normalize()
    hourly["hour_of_day"] = hourly["hour"].dt.hour
    return hourly


def demean_within_node(df, cols, node_col="node"):
    out = df[[node_col] + cols].copy()
    for col in cols:
        out[col] = out[col] - out.groupby(node_col)[col].transform("mean")
    return out


def corr_pair(df, x, y, method="pearson"):
    sub = df[[x, y]].dropna()
    if len(sub) < 3:
        return np.nan, len(sub)
    return float(sub[x].corr(sub[y], method=method)), len(sub)


def ols_fit(y, X, names):
    mask = np.isfinite(y) & np.isfinite(X).all(axis=1)
    yv = np.asarray(y)[mask]
    Xv = np.asarray(X)[mask]
    n, k = Xv.shape
    if n <= k + 1:
        return None, None, mask
    Xd = np.column_stack([np.ones(n), Xv])
    beta, *_ = np.linalg.lstsq(Xd, yv, rcond=None)
    resid = yv - Xd @ beta
    sst = np.sum((yv - yv.mean()) ** 2)
    r2 = 1.0 - np.sum(resid ** 2) / sst if sst > 0 else np.nan
    out = {"n": int(n), "r2": float(r2), "intercept": float(beta[0])}
    for name, b in zip(names, beta[1:]):
        out[f"coef_{name}"] = float(b)
    return out, resid, mask


def aligned_lag_frame(df, cols, lag_hours):
    left = df[["node", "hour"] + cols].copy()
    right = df[["node", "hour"] + cols].copy()
    right["hour"] = right["hour"] + pd.Timedelta(hours=lag_hours)
    right = right.rename(columns={c: f"{c}_lag{lag_hours}" for c in cols})
    return left.merge(right, on=["node", "hour"], how="inner")


def hexbin_plot(x, y, xlabel, ylabel, title, path):
    fig, ax = plt.subplots(figsize=(8, 5.5))
    hb = ax.hexbin(x, y, gridsize=60, mincnt=1, cmap="viridis", linewidths=0)
    fig.colorbar(hb, ax=ax, label="node-hours")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def write_value_ranges(df, cols, path):
    rows = []
    for col in cols:
        if col not in df.columns:
            continue
        s = df[col].dropna()
        if s.empty:
            continue
        q = s.quantile([0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99])
        rows.append({
            "variable": col, "n": int(s.size), "min": float(s.min()),
            "p01": float(q.loc[0.01]), "p05": float(q.loc[0.05]),
            "p25": float(q.loc[0.25]), "p50": float(q.loc[0.50]),
            "p75": float(q.loc[0.75]), "p95": float(q.loc[0.95]),
            "p99": float(q.loc[0.99]), "max": float(s.max()), "mean": float(s.mean()),
        })
    out = pd.DataFrame(rows)
    out.to_csv(path, index=False)
    return out


def analyze(hourly, output_dir, fig_dir):
    fig_dir.mkdir(parents=True, exist_ok=True)

    ipmi_nodes = set(hourly.loc[hourly["has_ipmi_power"], "node"].unique())
    ganglia_nodes = set(hourly.loc[hourly["has_ganglia_cpu"], "node"].unique())
    common_nodes = ipmi_nodes & ganglia_nodes
    print("\n=== Populations ===")
    print(f"IPMI power-reporting nodes: {len(ipmi_nodes)}")
    print(f"Ganglia CPU-reporting nodes: {len(ganglia_nodes)}")
    print(f"Common nodes (relationship analysis): {len(common_nodes)}")
    print(f"Outer-union nodes (NOT the compute population): {hourly['node'].nunique()}")

    hq = hourly.loc[hourly["high_quality"]].copy()
    analysis = hourly.loc[hourly["analysis_hq"]].copy()
    print(f"High-quality IPMI node-hours (coverage>={HQ_COVERAGE_THRESHOLD:.2f}): {len(hq):,}")
    print(f"Analysis HQ ∩ Ganglia: {len(analysis):,}")

    if "cpu_idle_count" in hourly.columns:
        gcount = hourly.loc[hourly["has_ganglia_cpu"], "cpu_idle_count"]
        print("\nGanglia cpu_idle samples/hour (no coverage mask applied):")
        print(gcount.quantile([0.1, 0.25, 0.5, 0.75, 0.9]).round(1).to_string())
        print("Documented Ganglia cpu_* period is ~1m30s and varies by node; no Ganglia threshold imposed.")

    power_rows = hourly.loc[hourly["has_ipmi_power"]].copy()
    named = {
        "n_power_nodes": ("node", "nunique"),
        "mean_node_power_w": ("total_power_mean", "mean"),
        "observed_compute_node_power_kw": ("total_power_mean", "sum"),
        "median_total_power_coverage": ("total_power_coverage", "median"),
        "mean_total_power_coverage": ("total_power_coverage", "mean"),
        "n_hq_nodes": ("high_quality", "sum"),
    }
    if "cpu_busy_pct" in power_rows.columns:
        named["mean_cpu_busy_pct"] = ("cpu_busy_pct", "mean")
    if "gpu_core_temp_mean" in power_rows.columns:
        named["mean_gpu_core_temp_c"] = ("gpu_core_temp_mean", "mean")
    cluster = power_rows.groupby("hour", as_index=False).agg(**named).sort_values("hour")
    cluster["observed_compute_node_power_kw"] /= 1000.0
    n_ref = len(ipmi_nodes) if ipmi_nodes else 0
    cluster["low_node_coverage"] = cluster["n_power_nodes"] < (0.90 * n_ref)
    cluster["low_sample_coverage"] = cluster["median_total_power_coverage"] < 0.90
    cluster.to_csv(output_dir / "m100_2021_01_cluster_hourly.csv", index=False)

    outage = cluster.loc[cluster["low_node_coverage"] | cluster["low_sample_coverage"]]
    print(f"\nHours with incomplete node or sample coverage: {len(outage)}")
    if len(outage):
        print(outage.head(30).to_string(index=False))
        outage.to_csv(output_dir / "coverage_incomplete_hours.csv", index=False)

    rel_vars = [
        v for v in [
            "cpu_busy_pct", "cpu_user_mean", "cpu_system_mean", "proc_run_mean",
            "cpu_socket_power_w", "memory_power_w", "io_power_w",
            "gpu_core_temp_mean", "gpu_core_temp_max", "ambient_mean",
        ] if v in analysis.columns
    ]
    within = demean_within_node(analysis, ["total_power_mean"] + rel_vars)
    rows_raw, rows_within = [], []
    for var in rel_vars:
        r_p, n_p = corr_pair(analysis, var, "total_power_mean", "pearson")
        r_s, n_s = corr_pair(analysis, var, "total_power_mean", "spearman")
        r_w, n_w = corr_pair(within, var, "total_power_mean", "pearson")
        rows_raw.append({"variable": var, "pearson": r_p, "spearman": r_s, "n_pearson": n_p, "n_spearman": n_s})
        rows_within.append({"variable": var, "within_node_pearson": r_w, "n": n_w})
    raw_tbl = pd.DataFrame(rows_raw)
    within_tbl = pd.DataFrame(rows_within)
    raw_tbl.to_csv(output_dir / "hourly_correlations.csv", index=False)
    within_tbl.to_csv(output_dir / "hourly_within_node_correlations.csv", index=False)
    print("\nRaw correlations with total_power_mean (analysis HQ):")
    print(raw_tbl.round(3).to_string(index=False))
    print("\nWithin-node Pearson with total_power_mean:")
    print(within_tbl.round(3).to_string(index=False))

    cpu_pearson, _ = corr_pair(analysis, "cpu_busy_pct", "total_power_mean")
    cpu_spearman, _ = corr_pair(analysis, "cpu_busy_pct", "total_power_mean", "spearman")
    cpu_within, _ = corr_pair(within, "cpu_busy_pct", "total_power_mean")
    print(f"\nCPU busy vs total power: Pearson={cpu_pearson:.3f} Spearman={cpu_spearman:.3f} within-node={cpu_within:.3f}")

    model_vars = [v for v in ("cpu_socket_power_w", "memory_power_w", "io_power_w", "ambient_mean") if v in analysis.columns]
    overlap_cols = ["total_power_mean"] + model_vars
    gpu_cols = [c for c in ("gpu_core_temp_mean", "gpu_core_temp_max") if c in analysis.columns]
    ov = analysis.dropna(subset=overlap_cols + (["gpu_core_temp_mean"] if gpu_cols else [])).copy()
    dm = demean_within_node(ov, overlap_cols + gpu_cols)
    y = dm["total_power_mean"].to_numpy(dtype=float)
    X = dm[model_vars].to_numpy(dtype=float)
    base_fit, resid, mask = ols_fit(y, X, model_vars)
    model_rows = []
    gpu_corr_mean = gpu_corr_max = np.nan
    if base_fit is not None:
        base_fit["model"] = "within_node_cpu_mem_io_ambient"
        model_rows.append(base_fit)
        print(f"\nBase within-node OLS R2={base_fit['r2']:.3f} n={base_fit['n']:,}")
        if gpu_cols:
            gpu_mean_dm = dm["gpu_core_temp_mean"].to_numpy(dtype=float)[mask]
            gpu_corr_mean = float(np.corrcoef(resid, gpu_mean_dm)[0, 1])
            if "gpu_core_temp_max" in dm.columns:
                gpu_max_dm = dm["gpu_core_temp_max"].to_numpy(dtype=float)[mask]
                gpu_corr_max = float(np.corrcoef(resid, gpu_max_dm)[0, 1])
            Xg = dm[model_vars + ["gpu_core_temp_mean"]].to_numpy(dtype=float)
            fit_g, _, _ = ols_fit(y, Xg, model_vars + ["gpu_core_temp_mean"])
            if fit_g is not None:
                fit_g["model"] = "within_node_cpu_mem_io_ambient_gpu_temp"
                model_rows.append(fit_g)
                print(f"With GPU core temp mean: R2={fit_g['r2']:.3f} (delta={fit_g['r2'] - base_fit['r2']:+.3f})")
            print(f"Residual vs GPU temp (within-node): mean r={gpu_corr_mean:.3f}, max r={gpu_corr_max:.3f}")
            ov = ov.copy()
            ov["power_resid"] = np.nan
            ov.loc[ov.index[mask], "power_resid"] = resid
            rp = ov.dropna(subset=["power_resid", "gpu_core_temp_mean"])
            hexbin_plot(
                rp["gpu_core_temp_mean"], rp["power_resid"],
                "GPU core temperature mean (°C)", "Within-node power residual (W)",
                "Unexplained node power vs GPU core temperature",
                fig_dir / "residual_vs_gpu_temp.png",
            )
            p75 = ov["total_power_mean"].quantile(0.75)
            hp_lc = ov["total_power_mean"].ge(p75) & ov["cpu_busy_pct"].lt(20)
            print(f"High-power (≥p75) and CPU busy <20%: {int(hp_lc.sum()):,} / {len(ov):,} node-hours")
            if hp_lc.any() and (~hp_lc).any():
                print(
                    "  mean GPU temp in that regime: "
                    f"{ov.loc[hp_lc, 'gpu_core_temp_mean'].mean():.2f} °C vs rest "
                    f"{ov.loc[~hp_lc, 'gpu_core_temp_mean'].mean():.2f} °C"
                )
            base_fit["gpu_residual_corr_mean"] = gpu_corr_mean
            base_fit["gpu_residual_corr_max"] = gpu_corr_max
            model_rows[0] = base_fit
    pd.DataFrame(model_rows).to_csv(output_dir / "model_summary.csv", index=False)

    lag_cols = ["total_power_mean", "cpu_busy_pct"]
    if "gpu_core_temp_mean" in analysis.columns:
        lag_cols.append("gpu_core_temp_mean")
    lag_src = analysis[["node", "hour"] + lag_cols].dropna(subset=["total_power_mean"])
    lag_rows = []
    for lag, label in [(1, "power persistence lag 1h"), (24, "power persistence lag 24h")]:
        paired = aligned_lag_frame(lag_src, ["total_power_mean"], lag)
        r, n = corr_pair(paired, "total_power_mean", f"total_power_mean_lag{lag}")
        lag_rows.append({"diagnostic": label, "pearson": r, "n_pairs": n, "lag_hours": lag})
        print(f"{label}: r={r:.3f} n={n:,}")

    cpu_lag_src = lag_src.dropna(subset=["cpu_busy_pct"])
    r, n = corr_pair(cpu_lag_src, "cpu_busy_pct", "total_power_mean")
    lag_rows.append({"diagnostic": "contemporaneous CPU busy ↔ power", "pearson": r, "n_pairs": n, "lag_hours": 0})
    print(f"contemporaneous CPU busy ↔ power: r={r:.3f} n={n:,}")
    paired = aligned_lag_frame(cpu_lag_src, ["total_power_mean", "cpu_busy_pct"], 1)
    r, n = corr_pair(paired, "cpu_busy_pct_lag1", "total_power_mean")
    lag_rows.append({"diagnostic": "CPU busy leads power by 1h", "pearson": r, "n_pairs": n, "lag_hours": 1})
    print(f"CPU busy leads power by 1h: r={r:.3f} n={n:,}")
    r, n = corr_pair(paired, "cpu_busy_pct", "total_power_mean_lag1")
    lag_rows.append({"diagnostic": "CPU busy lags power by 1h", "pearson": r, "n_pairs": n, "lag_hours": -1})
    print(f"CPU busy lags power by 1h: r={r:.3f} n={n:,}")

    if "gpu_core_temp_mean" in lag_src.columns:
        gpu_lag = lag_src.dropna(subset=["gpu_core_temp_mean"])
        r, n = corr_pair(gpu_lag, "gpu_core_temp_mean", "total_power_mean")
        lag_rows.append({"diagnostic": "contemporaneous GPU temp ↔ power", "pearson": r, "n_pairs": n, "lag_hours": 0})
        print(f"contemporaneous GPU temp ↔ power: r={r:.3f} n={n:,}")
        paired = aligned_lag_frame(gpu_lag, ["total_power_mean", "gpu_core_temp_mean"], 1)
        r, n = corr_pair(paired, "gpu_core_temp_mean_lag1", "total_power_mean")
        lag_rows.append({"diagnostic": "GPU temp leads power by 1h", "pearson": r, "n_pairs": n, "lag_hours": 1})
        print(f"GPU temp leads power by 1h: r={r:.3f} n={n:,}")
        r, n = corr_pair(paired, "gpu_core_temp_mean", "total_power_mean_lag1")
        lag_rows.append({"diagnostic": "GPU temp lags power by 1h", "pearson": r, "n_pairs": n, "lag_hours": -1})
        print(f"GPU temp lags power by 1h: r={r:.3f} n={n:,}")
    pd.DataFrame(lag_rows).to_csv(output_dir / "lag_diagnostics.csv", index=False)

    if "psu_input_power_w" in hq.columns:
        psu = hq.dropna(subset=["total_power_mean", "psu_input_power_w"]).copy()
        psu["psu_minus_total_w"] = psu["psu_input_power_w"] - psu["total_power_mean"]
        print("\nPSU input vs total_power (HQ IPMI):")
        print(f"  n={len(psu):,} pearson={psu['psu_input_power_w'].corr(psu['total_power_mean']):.4f}")
        print(
            "  psu-total W: mean={:.1f} median={:.1f} p01={:.1f} p99={:.1f}".format(
                psu["psu_minus_total_w"].mean(), psu["psu_minus_total_w"].median(),
                psu["psu_minus_total_w"].quantile(0.01), psu["psu_minus_total_w"].quantile(0.99),
            )
        )
        n_bad = int((psu["psu_minus_total_w"].abs() > 200).sum())
        print(f"  |PSU-total| > 200 W: {n_bad:,} ({100 * n_bad / max(len(psu), 1):.2f}%)")
        hexbin_plot(
            psu["total_power_mean"], psu["psu_input_power_w"],
            "IPMI total_power (W)", "PSU input power ps0+ps1 (W)",
            "Sensor check: PSU input vs node total power",
            fig_dir / "psu_vs_total_power.png",
        )

    ranges = write_value_ranges(
        hq,
        [
            "total_power_mean", "cpu_busy_pct", "cpu_socket_power_w", "memory_power_w",
            "io_power_w", "ambient_mean", "gpu_core_temp_mean", "psu_input_power_w",
        ],
        output_dir / "value_ranges_hq.csv",
    )
    print("\nHQ value ranges:")
    print(ranges.round(2).to_string(index=False))

    fig, axes = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True)
    axes[0].plot(cluster["hour"], cluster["mean_node_power_w"], lw=0.9, color="#1d4ed8")
    axes[0].set_ylabel("Mean node power (W)")
    axes[0].set_title("M100 January 2021 — hourly IPMI power-reporting nodes")
    axes[1].plot(cluster["hour"], cluster["n_power_nodes"], lw=0.9, color="#0f766e")
    axes[1].set_ylabel("Power-reporting nodes")
    axes[1].set_xlabel("Hour")
    for ax in axes:
        ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(fig_dir / "hourly_power_and_coverage.png", dpi=150)
    plt.close(fig)

    cpu_plot = analysis.dropna(subset=["cpu_busy_pct", "total_power_mean"])
    hexbin_plot(
        cpu_plot["cpu_busy_pct"], cpu_plot["total_power_mean"],
        "Hourly mean CPU busy (%)", "Hourly mean node power (W)",
        "High-quality node-hours: CPU busy vs total power",
        fig_dir / "cpu_busy_vs_power.png",
    )

    best_var, best_abs = None, -1.0
    for var in COMPONENT_VARS:
        row = within_tbl.loc[within_tbl["variable"].eq(var)]
        if row.empty:
            continue
        val = abs(float(row["within_node_pearson"].iloc[0]))
        if np.isfinite(val) and val > best_abs:
            best_abs, best_var = val, var
    labels = {
        "cpu_socket_power_w": "CPU socket power (W)",
        "memory_power_w": "Memory power (W)",
        "io_power_w": "I/O power (W)",
        "gpu_core_temp_mean": "GPU core temperature (°C)",
        "ambient_mean": "Ambient temperature (°C)",
    }
    if best_var is not None:
        plot_df = analysis.dropna(subset=[best_var, "total_power_mean"])
        hexbin_plot(
            plot_df[best_var], plot_df["total_power_mean"],
            labels.get(best_var, best_var), "Hourly mean node power (W)",
            f"Most informative component ({best_var}) vs total power",
            fig_dir / "top_component_vs_power.png",
        )

    hod = (
        analysis.groupby("hour_of_day", as_index=False)
        .agg(
            mean_node_power_w=("total_power_mean", "mean"),
            mean_cpu_busy_pct=("cpu_busy_pct", "mean"),
            n=("node", "size"),
        )
        .sort_values("hour_of_day")
    )
    hod.to_csv(output_dir / "hour_of_day_profile.csv", index=False)
    fig, ax1 = plt.subplots(figsize=(8, 4.2))
    ax2 = ax1.twinx()
    ax1.plot(hod["hour_of_day"], hod["mean_node_power_w"], color="#1d4ed8", marker="o")
    ax2.plot(hod["hour_of_day"], hod["mean_cpu_busy_pct"], color="#b45309", marker="o")
    ax1.set_xlabel("Hour of day")
    ax1.set_ylabel("Mean node power (W)", color="#1d4ed8")
    ax2.set_ylabel("Mean CPU busy (%)", color="#b45309")
    ax1.set_title("Hour-of-day profile (high-quality node-hours)")
    ax1.set_xticks(range(0, 24, 2))
    fig.tight_layout()
    fig.savefig(fig_dir / "hour_of_day_profile.png", dpi=150)
    plt.close(fig)
    print(f"Most informative component by |within-node r|: {best_var}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("daily_input_january"))
    parser.add_argument("--output-dir", type=Path, default=Path("derived/january_hourly"))
    parser.add_argument("--sample", action="store_true", help="Two-hour path/schema check")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    fig_dir = args.output_dir / "figures"

    if args.sample:
        start_ts, end_ts = "2021-01-01 00:00:00", "2021-01-01 02:00:00"
        print("SAMPLE MODE: 2021-01-01 00:00–02:00")
    else:
        start_ts, end_ts = "2021-01-01 00:00:00", "2021-02-01 00:00:00"

    print("Building hourly January dataset...\n")
    hourly = build_hourly_dataset(args.data_root, start_ts, end_ts)
    if hourly is None or hourly.empty:
        raise RuntimeError("No data found. Check --data-root.")

    hourly = add_derived_variables(hourly)
    sort_cols = ["hour", "node_num"] if hourly["node_num"].notna().all() else ["hour", "node"]
    hourly = hourly.sort_values(sort_cols).reset_index(drop=True)

    parquet_path = args.output_dir / "m100_2021_01_node_hourly.parquet"
    if args.sample:
        parquet_path = args.output_dir / "m100_2021_01_node_hourly_sample.parquet"
    hourly.to_parquet(parquet_path, index=False)

    print("\nHourly dataset:", hourly.shape)
    print("Node-hours:", f"{len(hourly):,}")
    print("Unique nodes (outer union):", hourly["node"].nunique())
    print("Hour range:", hourly["hour"].min(), "to", hourly["hour"].max())
    print("Unique hours:", hourly["hour"].nunique())
    if "total_power_coverage" in hourly.columns:
        cov = hourly.loc[hourly["has_ipmi_power"], "total_power_coverage"]
        print(
            "IPMI coverage vs 180 samples/h: "
            f"mean={cov.mean():.3f} median={cov.median():.3f} p10={cov.quantile(0.10):.3f}"
        )

    analyze(hourly, args.output_dir, fig_dir)
    print("\nFinished.")
    print(f"Parquet: {parquet_path}")
    print(f"Figures: {fig_dir}")


if __name__ == "__main__":
    main()

