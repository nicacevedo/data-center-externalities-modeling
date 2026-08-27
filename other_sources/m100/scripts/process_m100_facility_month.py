#!/usr/bin/env python3
"""Extract selected facility metrics to $TMPDIR and write hourly Parquet.

Does not persist raw partitions. Reuses January node panel if present.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from m100_2021_common import (
    ARCHIVES_DIR,
    CATALOG_DIR,
    CINECA_ELEVATION_M,
    LOGICS_ENERGY,
    LOGICS_POWER_KW,
    LOGICS_PUE,
    LOGICS_QC,
    LOGICS_WATTS,
    PROCESSED_DIR,
    VERTIV_CONTINUOUS,
    VERTIV_STATE,
    WEATHER_METRICS,
    hive_ym,
    month_bounds,
    month_calendar,
    n_threads,
    save_status,
    schneider_physical,
    schneider_suffix,
    sea_level_to_station_pa,
)


def _inv(month: str) -> pd.DataFrame:
    p = CATALOG_DIR / "inventory" / f"{month}.csv"
    if not p.exists():
        raise FileNotFoundError(p)
    return pd.read_csv(p)


def _wanted(inv: pd.DataFrame) -> pd.DataFrame:
    def keep(row):
        plugin = str(row["plugin"]).lower()
        metric = str(row["metric"])
        suf = schneider_suffix(metric)
        if "logics" in plugin and metric in (
            *LOGICS_POWER_KW, *LOGICS_PUE, *LOGICS_WATTS, *LOGICS_ENERGY, *LOGICS_QC
        ):
            return True
        if "schneider" in plugin and suf in {
            "Temp_mandata", "Temp_ritorno", "T_mandata_hmi", "T_ritorno_hmi",
            "Delta_temp", "Portata_attiva", "Portata_1", "Portata_2",
            "Portata_1_hmi", "Portata_2_hmi", "Out_pid_pompe", "Set_temperatura",
            "Pos_valvola1", "Pos_valvola_2", "Start_impianto",
            "P101_in_marcia", "P102_in_marcia", "P103_in_marcia", "P104_in_marcia",
            "Allarme_on", "Allarme_presente",
        }:
            return True
        if "vertiv" in plugin and metric in (*VERTIV_CONTINUOUS, *VERTIV_STATE):
            return True
        if "weather" in plugin and metric in WEATHER_METRICS:
            return True
        return False
    return inv.loc[inv.apply(keep, axis=1)].copy()


def extract_members(archive: Path, members: list[str], dest: Path) -> float:
    dest.mkdir(parents=True, exist_ok=True)
    dirs = []
    for m in members:
        if m.endswith(".parquet"):
            dirs.append(str(Path(m).parent).rstrip("/") + "/")
        else:
            dirs.append(m if m.endswith("/") else m.rstrip("/") + "/")
    dirs = sorted(set(dirs))
    t0 = time.time()
    cmd = ["tar", "-xf", str(archive), "-C", str(dest), "--"] + dirs
    subprocess.run(cmd, check=True)
    return time.time() - t0


def configure_duckdb(con):
    tmp = os.environ.get("TMPDIR") or "/tmp"
    Path(tmp).mkdir(parents=True, exist_ok=True)
    con.execute(f"SET threads={int(n_threads())}")
    con.execute(f"SET temp_directory='{tmp.replace(chr(39), chr(39)*2)}'")


def parquet_glob(root: Path, plugin: str, metric: str) -> str | None:
    matches = list(root.glob(f"**/plugin={plugin}/metric={metric}/*.parquet"))
    if not matches:
        return None
    return str(matches[0].parent / "*.parquet").replace("'", "''")


def identity_logics(con, glob: str, metric: str) -> pd.DataFrame:
    return con.execute(f"""
        SELECT '{metric}' AS metric,
               CAST(panel AS VARCHAR) AS panel,
               CAST(device AS VARCHAR) AS device,
               COUNT(value) AS n,
               AVG(CAST(value AS DOUBLE)) AS mean_value,
               MIN(CAST(timestamp AS TIMESTAMP)) AS tmin,
               MAX(CAST(timestamp AS TIMESTAMP)) AS tmax
        FROM read_parquet('{glob}')
        GROUP BY 2, 3
        ORDER BY n DESC
    """).df()


def hourly_entity(con, glob: str, metric: str, entity_cols: list[str],
                  start_ts: str, end_ts: str, cumulative: bool) -> pd.DataFrame:
    ents = ", ".join(f"CAST({c} AS VARCHAR) AS {c}" for c in entity_cols)
    grp = ", ".join(["1"] + [str(i) for i in range(2, 2 + len(entity_cols))])
    extra = ""
    if cumulative:
        extra = f", MIN(CAST(value AS DOUBLE)) AS {metric}_min_raw, MAX(CAST(value AS DOUBLE)) AS {metric}_max_raw"
    sql = f"""
        SELECT
            date_trunc('hour', CAST(timestamp AS TIMESTAMP)) AS timestamp_utc,
            {ents},
            AVG(CAST(value AS DOUBLE)) AS {metric}_mean,
            MIN(CAST(value AS DOUBLE)) AS {metric}_min,
            MAX(CAST(value AS DOUBLE)) AS {metric}_max,
            STDDEV_SAMP(CAST(value AS DOUBLE)) AS {metric}_std,
            COUNT(value) AS {metric}_count
            {extra}
        FROM read_parquet('{glob}')
        WHERE timestamp >= TIMESTAMP '{start_ts}'
          AND timestamp < TIMESTAMP '{end_ts}'
        GROUP BY {grp}
    """
    return con.execute(sql).df()


def reindex_hours(df: pd.DataFrame, month: str, keys: list[str]) -> pd.DataFrame:
    cal = month_calendar(month)
    if df.empty:
        out = pd.DataFrame({"timestamp_utc": cal})
        return out
    df = df.copy()
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    pieces = []
    if keys:
        for _, g in df.groupby(keys, dropna=False):
            g = g.set_index("timestamp_utc").sort_index()
            g = g[~g.index.duplicated(keep="first")]
            g = g.reindex(cal)
            for k in keys:
                g[k] = g[k].ffill().bfill()
            g["timestamp_utc"] = g.index
            pieces.append(g.reset_index(drop=True))
        return pd.concat(pieces, ignore_index=True)
    g = df.set_index("timestamp_utc").sort_index()
    g = g[~g.index.duplicated(keep="first")].reindex(cal)
    g["timestamp_utc"] = g.index
    return g.reset_index(drop=True)


def add_rome_fields(df: pd.DataFrame) -> pd.DataFrame:
    ts = pd.to_datetime(df["timestamp_utc"], utc=True)
    rome = ts.dt.tz_convert("Europe/Rome")
    df["timestamp_rome"] = rome.astype(str)
    df["hour_of_day_rome"] = rome.dt.hour
    df["date_rome"] = rome.dt.strftime("%Y-%m-%d")
    return df


def process_month(month: str, force: bool = False) -> dict:
    timings = {}
    inv = _inv(month)
    wanted = _wanted(inv)
    start, end = month_bounds(month)
    start_ts = start.strftime("%Y-%m-%d %H:%M:%S")
    end_ts = end.strftime("%Y-%m-%d %H:%M:%S")
    archive = ARCHIVES_DIR / f"{hive_ym(month)}.tar"
    products = []

    # Preserve existing January node panel; do not rebuild here.
    node_src = PROCESSED_DIR / "hourly" / month / "m100_node_hourly.parquet"
    node_dst_dir = PROCESSED_DIR / "node_hourly" / month
    node_dst = node_dst_dir / "m100_node_hourly.parquet"
    if node_src.exists() and not node_dst.exists():
        node_dst_dir.mkdir(parents=True, exist_ok=True)
        if not node_dst.exists():
            os.symlink(os.path.relpath(node_src, node_dst_dir), node_dst)
        products.append(str(node_dst))

    if wanted.empty:
        save_status(month, facility_extraction_status="skipped_no_facility_metrics",
                    processed_products=products)
        return {"month": month, "timings": timings, "products": products, "n_metrics": 0}

    expected = []
    plugins = set(wanted.plugin.astype(str).str.lower())
    if any("logics" in p for p in plugins):
        expected.append(PROCESSED_DIR / "facility_hourly" / month / "m100_facility_hourly.parquet")
    if any("schneider" in p for p in plugins):
        expected.append(PROCESSED_DIR / "liquid_cooling_hourly" / month / "m100_liquid_hourly.parquet")
    if any("vertiv" in p for p in plugins):
        expected.append(PROCESSED_DIR / "crac_hourly" / month / "m100_crac_hourly.parquet")
    if any("weather" in p for p in plugins):
        expected.append(PROCESSED_DIR / "weather_hourly" / month / "m100_weather_hourly.parquet")
    if expected and all(p.exists() and p.stat().st_size > 1000 for p in expected) and not force:
        products.extend(str(p) for p in expected)
        save_status(month, facility_extraction_status="done", processed_products=products)
        return {"month": month, "timings": {"skipped_existing": 1}, "products": products, "n_metrics": len(wanted)}

    tmp = Path(os.environ.get("TMPDIR") or "/tmp") / f"m100_{month}_{os.getpid()}"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        members = wanted["archive_member"].dropna().unique().tolist()
        # also extract parent dirs? tar file members are enough
        t0 = time.time()
        extract_members(archive, members, tmp)
        timings["tar_extract_s"] = round(time.time() - t0, 2)

        con = duckdb.connect()
        configure_duckdb(con)
        t1 = time.time()
        # --- logics identity then hourly ---
        logics = wanted.loc[wanted.plugin.str.contains("logics", case=False, na=False)]
        ident_rows = []
        fac_hourly = None
        for metric in logics["metric"].unique():
            plugin = logics.loc[logics.metric.eq(metric), "plugin"].iloc[0]
            glob = parquet_glob(tmp, plugin, metric)
            if glob is None:
                continue
            ident_rows.append(identity_logics(con, glob, metric))
            hdf = hourly_entity(
                con, glob, metric, ["panel", "device"], start_ts, end_ts,
                cumulative=metric in LOGICS_ENERGY,
            )
            fac_hourly = hdf if fac_hourly is None else fac_hourly.merge(
                hdf, on=["timestamp_utc", "panel", "device"], how="outer"
            )
        if ident_rows:
            ident = pd.concat(ident_rows, ignore_index=True)
            ident_dir = PROCESSED_DIR / "facility_hourly" / month
            ident_dir.mkdir(parents=True, exist_ok=True)
            ident.to_csv(ident_dir / "logics_entity_identity.csv", index=False)
        if fac_hourly is not None:
            fac_hourly = reindex_hours(fac_hourly, month, ["panel", "device"])
            fac_hourly = add_rome_fields(fac_hourly)
            outp = PROCESSED_DIR / "facility_hourly" / month / "m100_facility_hourly.parquet"
            outp.parent.mkdir(parents=True, exist_ok=True)
            fac_hourly.to_parquet(outp, index=False)
            products.append(str(outp))

        # --- schneider by panel ---
        schn = wanted.loc[wanted.plugin.str.contains("schneider", case=False, na=False)]
        liq = None
        for metric in schn["metric"].unique():
            plugin = schn.loc[schn.metric.eq(metric), "plugin"].iloc[0]
            glob = parquet_glob(tmp, plugin, metric)
            if glob is None:
                continue
            col = schneider_suffix(metric)
            hdf = hourly_entity(con, glob, col, ["panel"], start_ts, end_ts, False)
            _, unit, scale = schneider_physical(metric, 1.0)
            for stat in ("mean", "min", "max"):
                c = f"{col}_{stat}"
                if c in hdf.columns:
                    hdf[c] = hdf[c] / scale if scale != 1 else hdf[c]
            hdf[f"{col}_unit"] = unit
            liq = hdf if liq is None else liq.merge(hdf, on=["timestamp_utc", "panel"], how="outer")
        if liq is not None:
            if {"Temp_ritorno_mean", "Temp_mandata_mean"}.issubset(liq.columns):
                liq["delta_T_c"] = liq["Temp_ritorno_mean"] - liq["Temp_mandata_mean"]
            if {"Portata_attiva_mean", "delta_T_c"}.issubset(liq.columns):
                liq["heat_transfer_index"] = liq["Portata_attiva_mean"] * liq["delta_T_c"]
            liq = reindex_hours(liq, month, ["panel"])
            liq = add_rome_fields(liq)
            outp = PROCESSED_DIR / "liquid_cooling_hourly" / month / "m100_liquid_hourly.parquet"
            outp.parent.mkdir(parents=True, exist_ok=True)
            liq.to_parquet(outp, index=False)
            products.append(str(outp))

        # --- vertiv by device ---
        vert = wanted.loc[wanted.plugin.str.contains("vertiv", case=False, na=False)]
        crac = None
        for metric in vert["metric"].unique():
            plugin = vert.loc[vert.metric.eq(metric), "plugin"].iloc[0]
            glob = parquet_glob(tmp, plugin, metric)
            if glob is None:
                continue
            hdf = hourly_entity(con, glob, metric, ["device"], start_ts, end_ts, False)
            crac = hdf if crac is None else crac.merge(hdf, on=["timestamp_utc", "device"], how="outer")
        if crac is not None:
            if {"Return_Air_Temperature_mean", "Supply_Air_Temperature_mean"}.issubset(crac.columns):
                crac["air_delta_T"] = (
                    crac["Return_Air_Temperature_mean"] - crac["Supply_Air_Temperature_mean"]
                )
            crac = reindex_hours(crac, month, ["device"])
            crac = add_rome_fields(crac)
            outp = PROCESSED_DIR / "crac_hourly" / month / "m100_crac_hourly.parquet"
            outp.parent.mkdir(parents=True, exist_ok=True)
            crac.to_parquet(outp, index=False)
            products.append(str(outp))

        # --- weather ---
        wsub = wanted.loc[wanted.plugin.str.contains("weather", case=False, na=False)]
        weather = None
        for metric in wsub["metric"].unique():
            plugin = wsub.loc[wsub.metric.eq(metric), "plugin"].iloc[0]
            glob = parquet_glob(tmp, plugin, metric)
            if glob is None:
                continue
            hdf = con.execute(f"""
                SELECT date_trunc('hour', CAST(timestamp AS TIMESTAMP)) AS timestamp_utc,
                       AVG(CAST(value AS DOUBLE)) AS {metric}_mean,
                       MIN(CAST(value AS DOUBLE)) AS {metric}_min,
                       MAX(CAST(value AS DOUBLE)) AS {metric}_max,
                       STDDEV_SAMP(CAST(value AS DOUBLE)) AS {metric}_std,
                       COUNT(value) AS {metric}_count
                FROM read_parquet('{glob}')
                WHERE timestamp >= TIMESTAMP '{start_ts}' AND timestamp < TIMESTAMP '{end_ts}'
                GROUP BY 1
            """).df()
            weather = hdf if weather is None else weather.merge(hdf, on="timestamp_utc", how="outer")
        if weather is not None:
            weather = reindex_hours(weather, month, [])
            if {"pressure_mean", "temp_mean"}.issubset(weather.columns):
                weather["pressure_station_pa"] = [
                    sea_level_to_station_pa(p, t) if pd.notna(p) and pd.notna(t) else np.nan
                    for p, t in zip(weather["pressure_mean"], weather["temp_mean"])
                ]
                weather["pressure_is_sea_level"] = True
                weather["elevation_m_assumed"] = CINECA_ELEVATION_M
                try:
                    import psychrolib
                    psychrolib.SetUnitSystem(psychrolib.SI)
                    twb = []
                    for t, td, p in zip(
                        weather.get("temp_mean", []),
                        weather.get("dew_point_mean", [np.nan] * len(weather)),
                        weather["pressure_station_pa"],
                    ):
                        if pd.isna(t) or pd.isna(td) or pd.isna(p):
                            twb.append(np.nan)
                        else:
                            try:
                                twb.append(float(psychrolib.GetTWetBulbFromTDewPoint(float(t), float(td), float(p))))
                            except Exception:
                                twb.append(np.nan)
                    weather["twb_c"] = twb
                except Exception:
                    weather["twb_c"] = np.nan
            weather = add_rome_fields(weather)
            outp = PROCESSED_DIR / "weather_hourly" / month / "m100_weather_hourly.parquet"
            outp.parent.mkdir(parents=True, exist_ok=True)
            weather.to_parquet(outp, index=False)
            products.append(str(outp))

        timings["duckdb_s"] = round(time.time() - t1, 2)
        con.close()
        save_status(
            month,
            facility_extraction_status="done",
            processed_products=products,
            runtime_s=sum(timings.values()),
            failure=None,
        )
        Path(PROCESSED_DIR / "facility_hourly" / month).mkdir(parents=True, exist_ok=True)
        (PROCESSED_DIR / "facility_hourly" / month / "timings.json").write_text(
            pd.Series(timings).to_json()
        )
        return {"month": month, "timings": timings, "products": products, "n_metrics": len(wanted)}
    except Exception as exc:
        save_status(month, facility_extraction_status="failed", failure=str(exc))
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    # conversion sanity
    v, u, s = schneider_physical("PLC_PLC_Q101.Temp_mandata", 250)
    assert abs(v - 25.0) < 1e-9 and u == "C" and s == 10.0
    v, u, s = schneider_physical("PLC_PLC_Q101.Portata_attiva", 120)
    assert abs(v - 12.0) < 1e-9 and u == "m3/h"
    out = process_month(args.month, force=args.force)
    print(out)


if __name__ == "__main__":
    main()
