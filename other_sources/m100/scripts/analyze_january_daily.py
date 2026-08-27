from pathlib import Path
import argparse

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------

METRICS = {
    # IPMI
    "total_power": ("ipmi_pub", "W"),
    "ambient": ("ipmi_pub", "C"),
    "p0_power": ("ipmi_pub", "W"),
    "p1_power": ("ipmi_pub", "W"),

    # Ganglia
    "cpu_user": ("ganglia_pub", "%"),
    "cpu_system": ("ganglia_pub", "%"),
    "cpu_idle": ("ganglia_pub", "%"),
    "load_five": ("ganglia_pub", "load"),
}


# ------------------------------------------------------------
# Read + aggregate one metric
# ------------------------------------------------------------

def aggregate_metric(con, data_root, plugin, metric):
    """
    Aggregate one raw M100 metric to:

        date x node

    without loading the raw Parquet file into Pandas.
    """

    metric_dir = (
        data_root
        / "year_month=21-01"
        / f"plugin={plugin}"
        / f"metric={metric}"
    )

    if not metric_dir.exists():
        print(f"WARNING: missing {plugin}/{metric}")
        return None

    parquet_glob = str(metric_dir / "*.parquet").replace("'", "''")

    print(f"Aggregating {plugin}/{metric} ...")

    sql = f"""
        SELECT
            CAST(timestamp AS DATE) AS date,
            CAST(node AS VARCHAR) AS node,

            AVG(CAST(value AS DOUBLE)) AS {metric}_mean,
            MIN(CAST(value AS DOUBLE)) AS {metric}_min,
            MAX(CAST(value AS DOUBLE)) AS {metric}_max,
            STDDEV_SAMP(CAST(value AS DOUBLE)) AS {metric}_std,

            COUNT(*) AS {metric}_count

        FROM read_parquet('{parquet_glob}')

        WHERE
            timestamp >= TIMESTAMP '2021-01-01 00:00:00'
            AND timestamp < TIMESTAMP '2021-02-01 00:00:00'

        GROUP BY
            CAST(timestamp AS DATE),
            CAST(node AS VARCHAR)

        ORDER BY
            date,
            node
    """

    return con.execute(sql).df()


# ------------------------------------------------------------
# Merge all metrics
# ------------------------------------------------------------

def build_daily_dataset(data_root):

    con = duckdb.connect()

    daily = None

    for metric, (plugin, unit) in METRICS.items():

        df = aggregate_metric(
            con,
            data_root,
            plugin,
            metric
        )

        if df is None:
            continue

        print(
            f"  {metric}: "
            f"{len(df):,} node-days, "
            f"{df['node'].nunique():,} nodes"
        )

        if daily is None:
            daily = df
        else:
            daily = daily.merge(
                df,
                on=["date", "node"],
                how="outer"
            )

    con.close()

    return daily


# ------------------------------------------------------------
# Derived physical quantities
# ------------------------------------------------------------

def add_derived_variables(daily):

    # CPU activity from idle percentage
    if "cpu_idle_mean" in daily.columns:
        daily["cpu_busy_pct"] = 100.0 - daily["cpu_idle_mean"]

    # Sum of the two CPU sockets
    if (
        "p0_power_mean" in daily.columns
        and "p1_power_mean" in daily.columns
    ):
        daily["cpu_socket_power_w"] = (
            daily["p0_power_mean"]
            + daily["p1_power_mean"]
        )

    # Fraction of node power attributable to CPU sockets
    if (
        "cpu_socket_power_w" in daily.columns
        and "total_power_mean" in daily.columns
    ):
        daily["cpu_socket_power_share"] = (
            daily["cpu_socket_power_w"]
            / daily["total_power_mean"]
        )

    # IPMI total_power nominally samples every 20 seconds.
    #
    # 24 * 60 * 60 / 20 = 4320 expected samples / full node-day.
    if "total_power_count" in daily.columns:
        daily["total_power_coverage"] = (
            daily["total_power_count"] / 4320.0
        )

    return daily


# ------------------------------------------------------------
# Cluster-level daily summary
# ------------------------------------------------------------

def build_cluster_daily(daily):

    named = {"nodes": ("node", "nunique")}

    if "total_power_mean" in daily.columns:
        named["mean_node_power_w"] = ("total_power_mean", "mean")
        # Sum of each node's daily mean power, converted to kW.
        named["observed_node_power_kw"] = ("total_power_mean", "sum")

    if "cpu_busy_pct" in daily.columns:
        named["mean_cpu_busy_pct"] = ("cpu_busy_pct", "mean")

    if "cpu_user_mean" in daily.columns:
        named["mean_cpu_user_pct"] = ("cpu_user_mean", "mean")

    if "ambient_mean" in daily.columns:
        named["mean_ambient_c"] = ("ambient_mean", "mean")

    if "cpu_socket_power_w" in daily.columns:
        named["mean_cpu_socket_power_w"] = ("cpu_socket_power_w", "mean")

    cluster = (
        daily
        .groupby("date", as_index=False)
        .agg(**named)
        .sort_values("date")
    )

    if "observed_node_power_kw" in cluster.columns:
        cluster["observed_node_power_kw"] = cluster["observed_node_power_kw"] / 1000.0

    return cluster


# ------------------------------------------------------------
# Correlations
# ------------------------------------------------------------

def correlation_analysis(daily, output_dir):

    candidate_columns = [
        "total_power_mean",
        "total_power_max",
        "cpu_user_mean",
        "cpu_system_mean",
        "cpu_idle_mean",
        "cpu_busy_pct",
        "load_five_mean",
        "ambient_mean",
        "p0_power_mean",
        "p1_power_mean",
        "cpu_socket_power_w",
        "cpu_socket_power_share",
    ]

    cols = [
        c for c in candidate_columns
        if c in daily.columns
    ]

    # Raw correlation across all node-days
    raw_corr = daily[cols].corr()

    raw_corr.to_csv(
        output_dir / "correlations_raw.csv"
    )

    print("\nRaw node-day correlations:")
    print(raw_corr.round(3))

    # --------------------------------------------------------
    # Within-node correlations
    #
    # Removes each node's persistent baseline.
    # This asks:
    #
    #   "When THIS node is busier than normal,
    #    is it also using more power than normal?"
    #
    # rather than allowing node-to-node differences
    # to dominate the correlation.
    # --------------------------------------------------------

    within = daily[["node"] + cols].copy()

    for col in cols:
        within[col] = (
            within[col]
            - within.groupby("node")[col].transform("mean")
        )

    within_corr = within[cols].corr()

    within_corr.to_csv(
        output_dir / "correlations_within_node.csv"
    )

    print("\nWithin-node correlations:")
    print(within_corr.round(3))

    return raw_corr, within_corr


# ------------------------------------------------------------
# Plots
# ------------------------------------------------------------

def make_plots(daily, cluster, output_dir):

    # -------------------------------
    # Node-day power vs CPU busy
    # -------------------------------

    if {
        "total_power_mean",
        "cpu_busy_pct"
    }.issubset(daily.columns):

        plot_df = daily[
            ["total_power_mean", "cpu_busy_pct"]
        ].dropna()

        plt.figure(figsize=(8, 6))

        plt.scatter(
            plot_df["cpu_busy_pct"],
            plot_df["total_power_mean"],
            s=6,
            alpha=0.25
        )

        plt.xlabel("Daily mean CPU busy (%)")
        plt.ylabel("Daily mean node power (W)")
        plt.title("January 2021: CPU activity vs node power")

        plt.tight_layout()

        plt.savefig(
            output_dir / "power_vs_cpu_busy.png",
            dpi=150
        )

        plt.close()

    # -------------------------------
    # Node power vs CPU socket power
    # -------------------------------

    if {
        "total_power_mean",
        "cpu_socket_power_w"
    }.issubset(daily.columns):

        plot_df = daily[
            ["total_power_mean", "cpu_socket_power_w"]
        ].dropna()

        plt.figure(figsize=(8, 6))

        plt.scatter(
            plot_df["cpu_socket_power_w"],
            plot_df["total_power_mean"],
            s=6,
            alpha=0.25
        )

        plt.xlabel("Daily mean CPU socket power (W)")
        plt.ylabel("Daily mean node power (W)")
        plt.title("January 2021: CPU power vs total node power")

        plt.tight_layout()

        plt.savefig(
            output_dir / "power_vs_cpu_socket_power.png",
            dpi=150
        )

        plt.close()

    # -------------------------------
    # Ambient temperature vs node power
    # -------------------------------

    if {
        "total_power_mean",
        "ambient_mean"
    }.issubset(daily.columns):

        plot_df = daily[
            ["total_power_mean", "ambient_mean"]
        ].dropna()

        plt.figure(figsize=(8, 6))

        plt.scatter(
            plot_df["ambient_mean"],
            plot_df["total_power_mean"],
            s=6,
            alpha=0.25
        )

        plt.xlabel("Daily mean ambient temperature (°C)")
        plt.ylabel("Daily mean node power (W)")
        plt.title("January 2021: ambient temperature vs node power")

        plt.tight_layout()

        plt.savefig(
            output_dir / "power_vs_ambient.png",
            dpi=150
        )

        plt.close()

    # -------------------------------
    # Cluster power over January
    # -------------------------------

    if "observed_node_power_kw" in cluster.columns:

        plt.figure(figsize=(10, 5))

        plt.plot(
            cluster["date"],
            cluster["observed_node_power_kw"],
            marker="o"
        )

        plt.xlabel("Date")
        plt.ylabel("Observed mean node power (kW)")
        plt.title("M100 observed node power — January 2021")

        plt.xticks(rotation=45)
        plt.tight_layout()

        plt.savefig(
            output_dir / "january_cluster_power.png",
            dpi=150
        )

        plt.close()


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("daily_input_january"),
        help="Directory containing extracted January partitions"
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("derived/january"),
        help="Output directory"
    )

    args = parser.parse_args()

    args.output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    print("Building daily January dataset...\n")

    daily = build_daily_dataset(args.data_root)

    if daily is None or daily.empty:
        raise RuntimeError(
            "No data found. Check --data-root."
        )

    daily = add_derived_variables(daily)

    daily = daily.sort_values(
        ["date", "node"]
    ).reset_index(drop=True)

    # Save compact node-day dataset
    daily_path = (
        args.output_dir
        / "m100_2021_01_node_daily.parquet"
    )

    daily.to_parquet(
        daily_path,
        index=False
    )

    # Also CSV for convenient inspection
    daily.to_csv(
        args.output_dir
        / "m100_2021_01_node_daily.csv",
        index=False
    )

    print("\nDaily dataset:")
    print(daily.shape)

    print("\nNumber of node-days:")
    print(len(daily))

    print("\nNumber of nodes:")
    print(daily["node"].nunique())

    print("\nDate range:")
    print(
        daily["date"].min(),
        "to",
        daily["date"].max()
    )
    dates = sorted(daily["date"].unique())
    print(f"Unique dates: {len(dates)}")

    if "total_power_count" in daily.columns:
        n = len(daily)
        n_power = daily["total_power_count"].notna().sum()
        n_missing = n - n_power
        print("\nTotal power sample-count coverage:")
        print(f"  node-days with total_power: {n_power:,} / {n:,}")
        print(f"  node-days missing total_power: {n_missing:,}")
        if "total_power_coverage" in daily.columns:
            cov = daily["total_power_coverage"].dropna()
            print(
                "  coverage vs 20s nominal (count/4320): "
                f"mean={cov.mean():.3f}, "
                f"median={cov.median():.3f}, "
                f"min={cov.min():.3f}, "
                f"p10={cov.quantile(0.10):.3f}"
            )

    print("\nFirst rows:")
    print(daily.head().to_string())

    # Cluster-level summary
    cluster = build_cluster_daily(daily)

    cluster.to_csv(
        args.output_dir
        / "m100_2021_01_cluster_daily.csv",
        index=False
    )

    print("\nCluster daily summary:")
    print(cluster.to_string(index=False))

    # Correlations
    correlation_analysis(
        daily,
        args.output_dir
    )

    # Plots
    make_plots(
        daily,
        cluster,
        args.output_dir
    )

    print("\nFinished.")
    print(f"Results written to: {args.output_dir}")


if __name__ == "__main__":
    main()