#!/usr/bin/env python3
"""Stage B: analyze an already-built M100 hourly node panel.

Does not rescan raw telemetry.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from m100_hourly_common import (
    HQ_COVERAGE_THRESHOLD,
    month_calendar,
    population_summary,
)


COMPONENT_VARS = [
    "cpu_socket_power_w",
    "memory_power_w",
    "io_power_w",
    "gpu_core_temp_mean",
    "ambient_mean",
]


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
    """Pair rows of the same node separated by exactly lag_hours."""
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


def build_cluster_calendar(hourly: pd.DataFrame, month: str) -> pd.DataFrame:
    cal = month_calendar(month)
    power_rows = hourly.loc[hourly["has_ipmi_power"]].copy()
    named = {
        "power_reporting_nodes": ("node", "nunique"),
        "hq_power_nodes": ("high_quality", "sum"),
        "mean_node_power_w": ("total_power_mean", "mean"),
        "observed_compute_node_power_kw": ("total_power_mean", "sum"),
        "median_total_power_coverage": ("total_power_coverage", "median"),
        "mean_total_power_coverage": ("total_power_coverage", "mean"),
    }
    if "cpu_busy_pct" in power_rows.columns:
        named["mean_cpu_busy_pct"] = ("cpu_busy_pct", "mean")
    if "gpu_core_temp_mean" in power_rows.columns:
        named["mean_gpu_core_temp_c"] = ("gpu_core_temp_mean", "mean")
    grouped = power_rows.groupby("hour", as_index=False).agg(**named).sort_values("hour")
    grouped["observed_compute_node_power_kw"] /= 1000.0
    grouped["hour"] = pd.to_datetime(grouped["hour"])
    cluster = pd.DataFrame({"hour": cal})
    cluster = cluster.merge(grouped, on="hour", how="left")
    cluster["missing_interval"] = cluster["power_reporting_nodes"].isna()
    cluster["low_sample_coverage"] = cluster["median_total_power_coverage"].lt(0.90)
    return cluster


def plot_coverage(cluster: pd.DataFrame, month: str, path: Path) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(11, 8.2), sharex=True)
    axes[0].plot(cluster["hour"], cluster["mean_node_power_w"], lw=0.9, color="#1d4ed8")
    axes[0].set_ylabel("Mean node power (W)")
    axes[0].set_title(
        f"M100 {month} — observed node power and coverage "
        "(line breaks on missing hours)"
    )
    axes[1].plot(cluster["hour"], cluster["hq_power_nodes"], lw=0.9, color="#0f766e")
    axes[1].set_ylabel("HQ power-reporting nodes")
    axes[2].plot(
        cluster["hour"], cluster["median_total_power_coverage"], lw=0.9, color="#7c3aed"
    )
    axes[2].axhline(0.90, color="0.4", ls="--", lw=0.8)
    axes[2].set_ylabel("Median sample coverage")
    axes[2].set_xlabel("Hour")
    for ax in axes:
        ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_hour_of_day(hod: pd.DataFrame, path: Path) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(8, 5.8), sharex=True)
    axes[0].plot(hod["hour_of_day"], hod["mean_node_power_w"], color="#1d4ed8", marker="o")
    axes[0].set_ylabel("Mean node power (W)")
    axes[0].set_title("Hour-of-day profile (high-quality CPU–power node-hours)")
    axes[1].plot(hod["hour_of_day"], hod["mean_cpu_busy_pct"], color="#b45309", marker="o")
    axes[1].set_ylabel("Mean CPU busy (%)")
    axes[1].set_xlabel("Hour of day")
    axes[1].set_xticks(range(0, 24, 2))
    for ax in axes:
        ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def analyze(hourly: pd.DataFrame, month: str, tables: Path, figures: Path) -> None:
    tables.mkdir(parents=True, exist_ok=True)
    figures.mkdir(parents=True, exist_ok=True)

    summary = population_summary(hourly)
    print("\n=== Populations ===")
    print(f"IPMI power-reporting nodes: {summary['n_ipmi_power_nodes']}")
    print(f"Ganglia CPU-reporting nodes: {summary['n_ganglia_cpu_nodes']}")
    print(f"Common CPU-power nodes: {summary['n_common_cpu_power_nodes']}")
    print(f"Outer-union nodes (NOT the compute population): {summary['n_outer_union_nodes']}")
    print(
        f"High-quality IPMI node-hours (coverage>={HQ_COVERAGE_THRESHOLD:.2f}): "
        f"{summary['n_hq_power_node_hours']:,}"
    )
    print(f"Analysis HQ ∩ Ganglia: {summary['n_analysis_hq_node_hours']:,}")
    pd.DataFrame([summary]).to_csv(tables / "populations.csv", index=False)

    if "cpu_idle_count" in hourly.columns:
        gcount = hourly.loc[hourly["has_ganglia_cpu"], "cpu_idle_count"]
        print("\nGanglia cpu_idle samples/hour (no coverage mask applied):")
        print(gcount.quantile([0.1, 0.25, 0.5, 0.75, 0.9]).round(1).to_string())

    cluster = build_cluster_calendar(hourly, month)
    cluster.to_csv(tables / "cluster_hourly.csv", index=False)
    n_missing = int(cluster["missing_interval"].sum())
    n_thin = int(cluster["low_sample_coverage"].fillna(False).sum())
    print(f"\nCalendar hours: {len(cluster)}; missing intervals: {n_missing}; median coverage <0.90: {n_thin}")
    plot_coverage(cluster, month, figures / "hourly_power_and_coverage.png")

    analysis = hourly.loc[hourly["analysis_hq"]].copy()
    hq = hourly.loc[hourly["high_quality"]].copy()

    rel_vars = [
        v for v in [
            "cpu_busy_pct", "cpu_user_mean", "cpu_system_mean", "proc_run_mean",
            *COMPONENT_VARS, "gpu_core_temp_max",
        ] if v in analysis.columns
    ]
    within = demean_within_node(analysis, ["total_power_mean"] + rel_vars)
    rows = []
    for var in rel_vars:
        r_p, n_p = corr_pair(analysis, var, "total_power_mean", "pearson")
        r_s, n_s = corr_pair(analysis, var, "total_power_mean", "spearman")
        r_w, n_w = corr_pair(within, var, "total_power_mean", "pearson")
        rows.append({
            "variable": var,
            "pearson": r_p,
            "spearman": r_s,
            "within_node_pearson": r_w,
            "n_pearson": n_p,
            "n_spearman": n_s,
            "n_within": n_w,
        })
    corr_tbl = pd.DataFrame(rows)
    corr_tbl.to_csv(tables / "hourly_correlations.csv", index=False)
    corr_tbl.loc[corr_tbl["variable"].isin(COMPONENT_VARS)].to_csv(
        tables / "component_correlations.csv", index=False
    )
    print("\nCorrelations with total_power_mean (analysis HQ):")
    print(corr_tbl.round(3).to_string(index=False))

    cpu_row = corr_tbl.loc[corr_tbl["variable"].eq("cpu_busy_pct")].iloc[0]
    print(
        f"\nCPU busy vs total power: Pearson={cpu_row.pearson:.3f} "
        f"Spearman={cpu_row.spearman:.3f} within-node={cpu_row.within_node_pearson:.3f}"
    )

    cpu_plot = analysis.dropna(subset=["cpu_busy_pct", "total_power_mean"])
    hexbin_plot(
        cpu_plot["cpu_busy_pct"], cpu_plot["total_power_mean"],
        "Hourly mean CPU busy (%)", "Hourly mean node power (W)",
        "High-quality node-hours: CPU busy vs total power",
        figures / "cpu_busy_vs_power.png",
    )

    model_vars = [
        v for v in ("cpu_socket_power_w", "memory_power_w", "io_power_w", "ambient_mean")
        if v in analysis.columns
    ]
    overlap_cols = ["total_power_mean"] + model_vars
    gpu_cols = [c for c in ("gpu_core_temp_mean", "gpu_core_temp_max") if c in analysis.columns]
    ov = analysis.dropna(subset=overlap_cols + (["gpu_core_temp_mean"] if gpu_cols else [])).copy()
    dm = demean_within_node(ov, overlap_cols + gpu_cols)
    y = dm["total_power_mean"].to_numpy(dtype=float)
    X = dm[model_vars].to_numpy(dtype=float)
    base_fit, resid, mask = ols_fit(y, X, model_vars)
    model_rows = []
    if base_fit is not None:
        base_fit["model"] = "descriptive_within_node_cpu_mem_io_ambient"
        print(
            "\nContemporaneous descriptive model (node-demeaned; not a causal/power predictor):"
        )
        print(f"  base R2={base_fit['r2']:.3f} n={base_fit['n']:,}")
        if gpu_cols:
            gpu_mean_dm = dm["gpu_core_temp_mean"].to_numpy(dtype=float)[mask]
            gpu_corr_mean = float(np.corrcoef(resid, gpu_mean_dm)[0, 1])
            gpu_corr_max = np.nan
            if "gpu_core_temp_max" in dm.columns:
                gpu_max_dm = dm["gpu_core_temp_max"].to_numpy(dtype=float)[mask]
                gpu_corr_max = float(np.corrcoef(resid, gpu_max_dm)[0, 1])
            Xg = dm[model_vars + ["gpu_core_temp_mean"]].to_numpy(dtype=float)
            fit_g, _, _ = ols_fit(y, Xg, model_vars + ["gpu_core_temp_mean"])
            base_fit["gpu_residual_corr_mean"] = gpu_corr_mean
            base_fit["gpu_residual_corr_max"] = gpu_corr_max
            model_rows.append(base_fit)
            if fit_g is not None:
                fit_g["model"] = "descriptive_within_node_cpu_mem_io_ambient_gpu_temp"
                model_rows.append(fit_g)
                print(
                    f"  extended + gpu_core_temp_mean R2={fit_g['r2']:.3f} "
                    f"(delta={fit_g['r2'] - base_fit['r2']:+.3f})"
                )
            print(
                "  GPU core temperature is the strongest observed contemporaneous "
                "proxy for the GPU-dominated node power state "
                f"(residual r={gpu_corr_mean:.3f})."
            )
            ov = ov.copy()
            ov["power_resid"] = np.nan
            ov.loc[ov.index[mask], "power_resid"] = resid
            rp = ov.dropna(subset=["power_resid", "gpu_core_temp_mean"])
            hexbin_plot(
                rp["gpu_core_temp_mean"], rp["power_resid"],
                "GPU core temperature mean (°C)",
                "Within-node power residual after CPU/mem/I/O/ambient (W)",
                "Descriptive residual vs GPU core temperature (proxy, not causal)",
                figures / "residual_vs_gpu_temp.png",
            )
            p75 = ov["total_power_mean"].quantile(0.75)
            hp_lc = ov["total_power_mean"].ge(p75) & ov["cpu_busy_pct"].lt(20)
            print(f"  high-power (≥p75) and CPU busy <20%: {int(hp_lc.sum()):,} / {len(ov):,}")
            if hp_lc.any() and (~hp_lc).any():
                print(
                    "  mean GPU temp in that regime: "
                    f"{ov.loc[hp_lc, 'gpu_core_temp_mean'].mean():.2f} °C vs rest "
                    f"{ov.loc[~hp_lc, 'gpu_core_temp_mean'].mean():.2f} °C"
                )
        else:
            model_rows.append(base_fit)
    pd.DataFrame(model_rows).to_csv(tables / "model_summary.csv", index=False)

    lag_cols = ["total_power_mean", "cpu_busy_pct"]
    if "gpu_core_temp_mean" in analysis.columns:
        lag_cols.append("gpu_core_temp_mean")
    lag_src = analysis[["node", "hour"] + lag_cols].dropna(subset=["total_power_mean"])
    lag_rows = []
    for lag, label in [(1, "power persistence lag 1h"), (24, "power persistence lag 24h")]:
        paired = aligned_lag_frame(lag_src, ["total_power_mean"], lag)
        r, n = corr_pair(paired, "total_power_mean", f"total_power_mean_lag{lag}")
        lag_rows.append({"diagnostic": label, "pearson": r, "n_pairs": n, "lag_hours": lag})

    cpu_lag_src = lag_src.dropna(subset=["cpu_busy_pct"])
    r, n = corr_pair(cpu_lag_src, "cpu_busy_pct", "total_power_mean")
    lag_rows.append({"diagnostic": "CPU busy vs power lag 0h", "pearson": r, "n_pairs": n, "lag_hours": 0})
    paired = aligned_lag_frame(cpu_lag_src, ["total_power_mean", "cpu_busy_pct"], 1)
    r, n = corr_pair(paired, "cpu_busy_pct_lag1", "total_power_mean")
    lag_rows.append({"diagnostic": "CPU busy leads power by 1h", "pearson": r, "n_pairs": n, "lag_hours": 1})
    r, n = corr_pair(paired, "cpu_busy_pct", "total_power_mean_lag1")
    lag_rows.append({"diagnostic": "CPU busy lags power by 1h", "pearson": r, "n_pairs": n, "lag_hours": -1})

    if "gpu_core_temp_mean" in lag_src.columns:
        gpu_lag = lag_src.dropna(subset=["gpu_core_temp_mean"])
        r, n = corr_pair(gpu_lag, "gpu_core_temp_mean", "total_power_mean")
        lag_rows.append({"diagnostic": "GPU temp vs power lag 0h", "pearson": r, "n_pairs": n, "lag_hours": 0})
        paired = aligned_lag_frame(gpu_lag, ["total_power_mean", "gpu_core_temp_mean"], 1)
        r, n = corr_pair(paired, "gpu_core_temp_mean_lag1", "total_power_mean")
        lag_rows.append({"diagnostic": "GPU temp leads power by 1h", "pearson": r, "n_pairs": n, "lag_hours": 1})
        r, n = corr_pair(paired, "gpu_core_temp_mean", "total_power_mean_lag1")
        lag_rows.append({"diagnostic": "GPU temp lags power by 1h", "pearson": r, "n_pairs": n, "lag_hours": -1})
    pd.DataFrame(lag_rows).to_csv(tables / "lag_diagnostics.csv", index=False)
    for row in lag_rows:
        print(f"{row['diagnostic']}: r={row['pearson']:.3f} n={row['n_pairs']:,}")

    if "psu_input_power_w" in hq.columns:
        psu = hq.dropna(subset=["total_power_mean", "psu_input_power_w"]).copy()
        psu["psu_minus_total_w"] = psu["psu_input_power_w"] - psu["total_power_mean"]
        print("\nPSU input vs total_power (measurement consistency only):")
        print(f"  n={len(psu):,} pearson={psu['psu_input_power_w'].corr(psu['total_power_mean']):.4f}")
        print(
            "  psu-total W: mean={:.1f} median={:.1f} p01={:.1f} p99={:.1f}".format(
                psu["psu_minus_total_w"].mean(), psu["psu_minus_total_w"].median(),
                psu["psu_minus_total_w"].quantile(0.01), psu["psu_minus_total_w"].quantile(0.99),
            )
        )
        n_bad = int((psu["psu_minus_total_w"].abs() > 200).sum())
        print(f"  |PSU-total| > 200 W: {n_bad:,} ({100 * n_bad / max(len(psu), 1):.2f}%)")
        print("  Systematic offset is not interpreted as PSU inefficiency.")
        hexbin_plot(
            psu["total_power_mean"], psu["psu_input_power_w"],
            "IPMI total_power (W)", "PSU input power ps0+ps1 (W)",
            "Sensor consistency: PSU input vs node total power",
            figures / "psu_vs_total_power.png",
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
    hod.to_csv(tables / "hour_of_day_profile.csv", index=False)
    plot_hour_of_day(hod, figures / "hour_of_day_profile.png")

    gpu_plot = analysis.dropna(subset=["gpu_core_temp_mean", "total_power_mean"])
    hexbin_plot(
        gpu_plot["gpu_core_temp_mean"], gpu_plot["total_power_mean"],
        "GPU core temperature mean (°C)", "Hourly mean node power (W)",
        "High-quality node-hours: GPU core temperature vs total power",
        figures / "gpu_temp_vs_power.png",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument(
        "--processed-root", type=Path, default=Path("data/processed/hourly")
    )
    parser.add_argument("--results-root", type=Path, default=Path("results/hourly"))
    args = parser.parse_args()

    parquet_path = args.processed_root / args.month / "m100_node_hourly.parquet"
    if not parquet_path.exists():
        raise FileNotFoundError(f"Processed panel not found: {parquet_path}")
    out = args.results_root / args.month
    tables = out / "tables"
    figures = out / "figures"
    print(f"Reading {parquet_path}")
    hourly = pd.read_parquet(parquet_path)
    analyze(hourly, args.month, tables, figures)
    print(f"\nWrote results to {out}")


if __name__ == "__main__":
    main()
