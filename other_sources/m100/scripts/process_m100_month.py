#!/usr/bin/env python3
"""Production monthly processor: extract to scratch, DuckDB hourly ZSTD Parquet on Pool.

Physical grains only. Pre-aggregates liquid flow*delta_T at source timestamps.
Does not persist raw extracts. Idempotent for schema hourly-v2-2021.2.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from m100_2021_common import (
    ARCHIVES_DIR,
    CATALOG_DIR,
    CINECA_ELEVATION_M,
    CRITICAL_QUANTILES,
    LOGICS_ENERGY,
    LOGICS_POWER_KW,
    LOGICS_PUE,
    LOGICS_QC,
    LOGICS_STATE,
    LOGICS_WATTS,
    MAX_GAP_IPMI_S,
    MAX_GAP_POWER_S,
    MAX_GAP_STATE_S,
    NOMINAL_IPMI_PER_HOUR,
    NOMINAL_VERTIV_PER_HOUR,
    SCHEMA_VERSION,
    SCHNEIDER_CONTINUOUS,
    SCHNEIDER_STATE,
    VERTIV_CONTINUOUS,
    VERTIV_STATE,
    WEATHER_METRICS,
    ZENODO,
    archive_path,
    git_commit,
    grain_dir,
    grain_parquet,
    hive_ym,
    month_bounds,
    month_calendar,
    n_threads,
    save_status,
    schneider_physical,
    schneider_suffix,
    sea_level_to_station_pa,
    tmp_root,
    zenodo_url,
)


def write_zstd(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, path, compression="zstd", compression_level=5)


def sidecar(path: Path, **meta) -> None:
    info = {
        "schema_version": SCHEMA_VERSION,
        "git_commit": git_commit(),
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **meta,
    }
    path.with_suffix(".schema.json").write_text(json.dumps(info, indent=2, default=str) + "\n")


def _inv(month: str) -> pd.DataFrame:
    p = CATALOG_DIR / "inventory" / f"{month}.csv"
    if not p.exists():
        raise FileNotFoundError(p)
    return pd.read_csv(p)


def wanted(inv: pd.DataFrame) -> pd.DataFrame:
    def keep(row):
        plugin = str(row["plugin"]).lower()
        metric = str(row["metric"])
        suf = schneider_suffix(metric)
        if "logics" in plugin and metric in (
            *LOGICS_POWER_KW, *LOGICS_PUE, *LOGICS_WATTS, *LOGICS_ENERGY, *LOGICS_QC
        ):
            return True
        if "schneider" in plugin and suf in (SCHNEIDER_CONTINUOUS | SCHNEIDER_STATE):
            return True
        if "vertiv" in plugin and metric in (*VERTIV_CONTINUOUS, *VERTIV_STATE):
            return True
        if "weather" in plugin and metric in WEATHER_METRICS:
            return True
        if "ipmi" in plugin and metric == "total_power":
            return True
        if "ganglia" in plugin and (
            metric.startswith("Gpu") and (
                "gpu_utilization" in metric or "power_usage" in metric or metric.endswith("_gpu_temp")
            )
        ):
            return True
        return False
    out = inv.loc[inv.apply(keep, axis=1)].copy()
    if "archive_member" in out.columns:
        out = out.loc[out.archive_member.astype(str).str.endswith(".parquet")]
    return out


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
    subprocess.run(["tar", "-xf", str(archive), "-C", str(dest), "--"] + dirs, check=True)
    return time.time() - t0


def configure_duckdb(con):
    tmp = str(tmp_root()).replace("'", "''")
    con.execute(f"SET threads={int(n_threads())}")
    con.execute(f"SET temp_directory='{tmp}'")


def parquet_glob(root: Path, plugin: str, metric: str) -> str | None:
    matches = list(root.glob(f"**/plugin={plugin}/metric={metric}/*.parquet"))
    if not matches:
        return None
    return str(matches[0].parent / "*.parquet").replace("'", "''")


def add_rome(df: pd.DataFrame) -> pd.DataFrame:
    ts = pd.to_datetime(df["timestamp_utc"], utc=True)
    rome = ts.dt.tz_convert("Europe/Rome")
    df["timestamp_rome"] = rome.astype(str)
    df["hour_of_day_rome"] = rome.dt.hour
    df["date_rome"] = rome.dt.strftime("%Y-%m-%d")
    return df


def reindex_hours(df: pd.DataFrame, month: str, keys: list[str]) -> pd.DataFrame:
    cal = month_calendar(month)
    if df.empty:
        return pd.DataFrame({"timestamp_utc": cal})
    df = df.copy()
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    pieces = []
    if keys:
        for _, g in df.groupby(keys, dropna=False):
            g = g.set_index("timestamp_utc").sort_index()
            g = g[~g.index.duplicated(keep="first")].reindex(cal)
            for k in keys:
                g[k] = g[k].ffill().bfill()
            g["timestamp_utc"] = g.index
            pieces.append(g.reset_index(drop=True))
        return pd.concat(pieces, ignore_index=True)
    g = df.set_index("timestamp_utc").sort_index()
    g = g[~g.index.duplicated(keep="first")].reindex(cal)
    g["timestamp_utc"] = g.index
    return g.reset_index(drop=True)


def hourly_query(glob: str, col: str, entity_cols: list[str], start_ts: str, end_ts: str,
                 kind: str, scale: float, max_gap: float, expected: int | None,
                 quantiles: bool, power_unit: str | None) -> str:
    ents_sel = ", ".join(f"CAST({c} AS VARCHAR) AS {c}" for c in entity_cols)
    ents_part = ", ".join(entity_cols) if entity_cols else ""
    part = f"PARTITION BY {ents_part}" if entity_cols else ""
    grp = "hour" + ("".join(f", {c}" for c in entity_cols))
    scale_sql = f"(CAST(value AS DOUBLE) / {float(scale)})" if scale != 1 else "CAST(value AS DOUBLE)"
    q = ""
    if quantiles:
        q = f""",
               quantile_cont(v, 0.05) AS {col}_p05,
               quantile_cont(v, 0.50) AS {col}_p50,
               quantile_cont(v, 0.95) AS {col}_p95"""
    extra = ""
    if kind == "power":
        kwh_factor = 1.0 if power_unit == "kW" else 0.001
        extra = f""",
               SUM(CASE WHEN dt_s BETWEEN 1 AND {max_gap} THEN 0.5 * (v + v_prev) * dt_s / 3600.0 * {kwh_factor} END) AS {col}_energy_kwh,
               MAX(dt_s) AS {col}_largest_gap_seconds"""
    elif kind == "state":
        extra = f""",
               SUM(CASE WHEN dt_s BETWEEN 1 AND {max_gap} AND (v_prev > 0.5) THEN dt_s ELSE 0 END)
                 / NULLIF(SUM(CASE WHEN dt_s BETWEEN 1 AND {max_gap} THEN dt_s END), 0) AS {col}_fraction_time_active,
               SUM(CASE WHEN v_prev IS NOT NULL AND ((v > 0.5) <> (v_prev > 0.5)) THEN 1 ELSE 0 END) AS {col}_transition_count,
               arg_min(CAST(v > 0.5 AS INTEGER), ts) AS {col}_first_state,
               arg_max(CAST(v > 0.5 AS INTEGER), ts) AS {col}_last_state,
               mode(CAST(v > 0.5 AS INTEGER)) AS {col}_dominant_state"""
    elif kind == "counter":
        extra = f""",
               arg_min(v, ts) AS {col}_counter_start,
               arg_max(v, ts) AS {col}_counter_end,
               arg_max(v, ts) - arg_min(v, ts) AS {col}_counter_delta,
               SUM(CASE WHEN v_prev IS NOT NULL AND v < v_prev THEN 1 ELSE 0 END) AS {col}_reset_count"""
    cov = ""
    if expected:
        cov = f", COUNT(v) / {float(expected)} AS {col}_coverage"
    ents_outer = (", " + ents_sel) if entity_cols else ""
    return f"""
        WITH raw AS (
            SELECT CAST(timestamp AS TIMESTAMP) AS ts
                   {ents_outer},
                   {scale_sql} AS v
            FROM read_parquet('{glob}')
            WHERE timestamp >= TIMESTAMP '{start_ts}' AND timestamp < TIMESTAMP '{end_ts}'
        ),
        w AS (
            SELECT *,
                   lag(ts) OVER ({part} ORDER BY ts) AS ts_prev,
                   lag(v) OVER ({part} ORDER BY ts) AS v_prev
            FROM raw
        ),
        seg AS (
            SELECT *, date_trunc('hour', ts) AS hour,
                   epoch(ts) - epoch(ts_prev) AS dt_s
            FROM w
        )
        SELECT hour AS timestamp_utc
               {("".join(f", {c}" for c in entity_cols))},
               AVG(v) AS {col}_mean,
               MIN(v) AS {col}_min,
               MAX(v) AS {col}_max,
               STDDEV_SAMP(v) AS {col}_std,
               COUNT(v) AS {col}_count,
               arg_min(v, ts) AS {col}_first,
               arg_max(v, ts) AS {col}_last
               {q}
               {extra}
               {cov}
        FROM seg
        GROUP BY {grp}
    """


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


def merge_on(frames: list[pd.DataFrame], keys: list[str]) -> pd.DataFrame | None:
    out = None
    for hdf in frames:
        out = hdf if out is None else out.merge(hdf, on=keys, how="outer")
    return out


def process_month(month: str, force: bool = False, grains: list[str] | None = None) -> dict:
    inv_path = CATALOG_DIR / "inventory" / f"{month}.csv"
    if not inv_path.exists():
        from catalog_m100_2021 import inventory_month, merge_inventories
        inventory_month(month)
        merge_inventories()
    timings = {}
    products = []
    inv = _inv(month)
    want = wanted(inv)
    start, end = month_bounds(month)
    start_ts = start.strftime("%Y-%m-%d %H:%M:%S")
    end_ts = end.strftime("%Y-%m-%d %H:%M:%S")
    archive = archive_path(month)
    grains = grains or ["facility", "liquid_cooling", "crac", "weather", "node"]
    has_ipmi = bool(
        ((want.plugin.astype(str).str.contains("ipmi", case=False)) & want.metric.eq("total_power")).any()
    )
    has_ict = bool((inv.plugin.astype(str).str.contains("logics", case=False) & inv.metric.eq("Tot_ict")).any())
    has_gpu = bool(
        inv.metric.astype(str).str.contains(r"Gpu\d+_gpu_utilization", regex=True).any()
        and inv.metric.astype(str).str.contains(r"Gpu\d+_power_usage", regex=True).any()
    )
    do_node = ("node" in grains) and has_ipmi and (has_ict or has_gpu)

    def already(grain: str) -> bool:
        p = grain_parquet(grain, month)
        s = p.with_suffix(".schema.json")
        if not p.exists() or p.stat().st_size < 1000:
            return False
        if not s.exists():
            return False
        try:
            meta = json.loads(s.read_text())
        except Exception:
            return False
        return meta.get("schema_version") == SCHEMA_VERSION

    need_extract = False
    plugins = {str(p).lower() for p in want.plugin}
    if "facility" in grains and (force or not already("facility")) and any("logics" in p for p in plugins):
        need_extract = True
    if "liquid_cooling" in grains and (force or not already("liquid_cooling")) and any("schneider" in p for p in plugins):
        need_extract = True
    if "crac" in grains and (force or not already("crac")) and any("vertiv" in p for p in plugins):
        need_extract = True
    if "weather" in grains and (force or not already("weather")) and any("weather" in p for p in plugins):
        need_extract = True
    if do_node and (force or not already("node")):
        need_extract = True

    if not need_extract and not force:
        save_status(month, facility_extraction_status="done", schema_version=SCHEMA_VERSION)
        return {"month": month, "skipped": True, "schema_version": SCHEMA_VERSION}

    tmp = tmp_root() / f"m100_{month}_{os.getpid()}"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        members_df = want
        if grains:
            keep_p = []
            if "facility" in grains:
                keep_p.append("logics")
            if "liquid_cooling" in grains:
                keep_p.append("schneider")
            if "crac" in grains:
                keep_p.append("vertiv")
            if "weather" in grains:
                keep_p.append("weather")
            if "node" in grains:
                keep_p.append("ipmi")
                keep_p.append("ganglia")
            if keep_p:
                pat = "|".join(keep_p)
                members_df = want.loc[want.plugin.astype(str).str.contains(pat, case=False, na=False)]
        members = members_df["archive_member"].dropna().unique().tolist()
        t0 = time.time()
        if members:
            timings["tar_extract_s"] = round(extract_members(archive, members, tmp), 2)
        else:
            timings["tar_extract_s"] = 0.0
        timings["extract_wall_s"] = round(time.time() - t0, 2)

        con = duckdb.connect()
        configure_duckdb(con)
        t_duck = time.time()

        # --- logics / facility ---
        logics = want.loc[want.plugin.str.contains("logics", case=False, na=False)]
        if len(logics) and ("facility" in grains) and (force or not already("facility")):
            ident_rows, frames = [], []
            for metric in logics["metric"].unique():
                plugin = logics.loc[logics.metric.eq(metric), "plugin"].iloc[0]
                glob = parquet_glob(tmp, plugin, metric)
                if glob is None:
                    continue
                ident_rows.append(identity_logics(con, glob, metric))
                if metric in LOGICS_POWER_KW:
                    kind, unit, q = "power", "kW", True
                elif metric in LOGICS_WATTS:
                    kind, unit, q = "power", "W", True
                elif metric in LOGICS_ENERGY:
                    kind, unit, q = "counter", None, False
                elif metric in LOGICS_STATE:
                    kind, unit, q = "state", None, False
                else:
                    kind, unit, q = "continuous", None, metric in CRITICAL_QUANTILES
                sql = hourly_query(
                    glob, metric, ["panel", "device"], start_ts, end_ts,
                    kind, 1.0, MAX_GAP_POWER_S, None, q, unit,
                )
                frames.append(con.execute(sql).df())
            if ident_rows:
                ident = pd.concat(ident_rows, ignore_index=True)
                d = grain_dir("facility", month)
                d.mkdir(parents=True, exist_ok=True)
                ident.to_csv(d / "logics_entity_identity.csv", index=False)
            fac = merge_on(frames, ["timestamp_utc", "panel", "device"])
            if fac is not None:
                fac = reindex_hours(fac, month, ["panel", "device"])
                fac = add_rome(fac)
                outp = grain_parquet("facility", month)
                write_zstd(fac, outp)
                sidecar(outp, month=month, grain="facility", n_rows=len(fac),
                        max_gap_s=MAX_GAP_POWER_S, energy_note="trapezoidal; gaps>max_gap excluded")
                products.append(str(outp))

        # --- schneider / liquid, with raw-resolution physics ---
        schn = want.loc[want.plugin.str.contains("schneider", case=False, na=False)]
        if len(schn) and ("liquid_cooling" in grains) and (force or not already("liquid_cooling")):
            frames = []
            supply = ret = flow = None
            for metric in schn["metric"].unique():
                plugin = schn.loc[schn.metric.eq(metric), "plugin"].iloc[0]
                glob = parquet_glob(tmp, plugin, metric)
                if glob is None:
                    continue
                col = schneider_suffix(metric)
                _, unit, scale = schneider_physical(metric, 1.0)
                kind = "state" if col in SCHNEIDER_STATE else "continuous"
                q = col in CRITICAL_QUANTILES
                sql = hourly_query(
                    glob, col, ["panel"], start_ts, end_ts,
                    kind, scale, MAX_GAP_STATE_S if kind == "state" else MAX_GAP_POWER_S,
                    None, q, None,
                )
                hdf = con.execute(sql).df()
                hdf[f"{col}_unit"] = unit
                frames.append(hdf)
                if col == "Temp_mandata":
                    supply = glob
                    supply_scale = scale
                elif col == "Temp_ritorno":
                    ret = glob
                    ret_scale = scale
                elif col == "Portata_attiva":
                    flow = glob
                    flow_scale = scale
            liq = merge_on(frames, ["timestamp_utc", "panel"])
            if supply and ret:
                phys = con.execute(f"""
                    WITH s AS (
                        SELECT CAST(panel AS VARCHAR) AS panel, CAST(timestamp AS TIMESTAMP) AS ts,
                               CAST(value AS DOUBLE)/{supply_scale} AS t_supply
                        FROM read_parquet('{supply}')
                        WHERE timestamp >= TIMESTAMP '{start_ts}' AND timestamp < TIMESTAMP '{end_ts}'
                    ),
                    r AS (
                        SELECT CAST(panel AS VARCHAR) AS panel, CAST(timestamp AS TIMESTAMP) AS ts,
                               CAST(value AS DOUBLE)/{ret_scale} AS t_return
                        FROM read_parquet('{ret}')
                        WHERE timestamp >= TIMESTAMP '{start_ts}' AND timestamp < TIMESTAMP '{end_ts}'
                    ),
                    j AS (
                        SELECT s.panel, s.ts, r.t_return - s.t_supply AS delta_t
                        FROM s INNER JOIN r
                          ON s.panel = r.panel AND date_trunc('second', s.ts) = date_trunc('second', r.ts)
                    )
                    SELECT date_trunc('hour', ts) AS timestamp_utc, panel,
                           AVG(delta_t) AS delta_t_mean,
                           MIN(delta_t) AS delta_t_min,
                           MAX(delta_t) AS delta_t_max,
                           STDDEV_SAMP(delta_t) AS delta_t_std,
                           quantile_cont(delta_t, 0.05) AS delta_t_p05,
                           quantile_cont(delta_t, 0.50) AS delta_t_p50,
                           quantile_cont(delta_t, 0.95) AS delta_t_p95,
                           COUNT(delta_t) AS delta_t_count
                    FROM j GROUP BY 1, 2
                """).df()
                liq = phys if liq is None else liq.merge(phys, on=["timestamp_utc", "panel"], how="outer")
            if supply and ret and flow:
                hti = con.execute(f"""
                    WITH s AS (
                        SELECT CAST(panel AS VARCHAR) AS panel, CAST(timestamp AS TIMESTAMP) AS ts,
                               CAST(value AS DOUBLE)/{supply_scale} AS t_supply
                        FROM read_parquet('{supply}')
                        WHERE timestamp >= TIMESTAMP '{start_ts}' AND timestamp < TIMESTAMP '{end_ts}'
                    ),
                    r AS (
                        SELECT CAST(panel AS VARCHAR) AS panel, CAST(timestamp AS TIMESTAMP) AS ts,
                               CAST(value AS DOUBLE)/{ret_scale} AS t_return
                        FROM read_parquet('{ret}')
                        WHERE timestamp >= TIMESTAMP '{start_ts}' AND timestamp < TIMESTAMP '{end_ts}'
                    ),
                    f AS (
                        SELECT CAST(panel AS VARCHAR) AS panel, CAST(timestamp AS TIMESTAMP) AS ts,
                               CAST(value AS DOUBLE)/{flow_scale} AS flow
                        FROM read_parquet('{flow}')
                        WHERE timestamp >= TIMESTAMP '{start_ts}' AND timestamp < TIMESTAMP '{end_ts}'
                    ),
                    j AS (
                        SELECT s.panel, s.ts,
                               (r.t_return - s.t_supply) AS delta_t,
                               f.flow * (r.t_return - s.t_supply) AS hti
                        FROM s
                        INNER JOIN r ON s.panel=r.panel AND date_trunc('second', s.ts)=date_trunc('second', r.ts)
                        INNER JOIN f ON s.panel=f.panel AND date_trunc('second', s.ts)=date_trunc('second', f.ts)
                    )
                    SELECT date_trunc('hour', ts) AS timestamp_utc, panel,
                           AVG(hti) AS flow_delta_t_mean,
                           SUM(hti) AS flow_delta_t_integral,
                           MIN(hti) AS flow_delta_t_min,
                           MAX(hti) AS flow_delta_t_max,
                           STDDEV_SAMP(hti) AS flow_delta_t_std,
                           quantile_cont(hti, 0.05) AS flow_delta_t_p05,
                           quantile_cont(hti, 0.50) AS flow_delta_t_p50,
                           quantile_cont(hti, 0.95) AS flow_delta_t_p95,
                           COUNT(hti) AS flow_delta_t_count
                    FROM j GROUP BY 1, 2
                """).df()
                liq = hti if liq is None else liq.merge(hti, on=["timestamp_utc", "panel"], how="outer")
            if liq is not None:
                liq = reindex_hours(liq, month, ["panel"])
                liq = add_rome(liq)
                outp = grain_parquet("liquid_cooling", month)
                write_zstd(liq, outp)
                sidecar(outp, month=month, grain="liquid_cooling", n_rows=len(liq),
                        physics="delta_T and flow*delta_T at source-second alignment before hourly; not thermal kW")
                products.append(str(outp))

        # --- vertiv ---
        vert = want.loc[want.plugin.str.contains("vertiv", case=False, na=False)]
        if len(vert) and ("crac" in grains) and (force or not already("crac")):
            frames = []
            for metric in vert["metric"].unique():
                plugin = vert.loc[vert.metric.eq(metric), "plugin"].iloc[0]
                glob = parquet_glob(tmp, plugin, metric)
                if glob is None:
                    continue
                kind = "state" if metric in VERTIV_STATE else "continuous"
                q = metric in CRITICAL_QUANTILES
                sql = hourly_query(
                    glob, metric, ["device"], start_ts, end_ts, kind, 1.0,
                    MAX_GAP_STATE_S, NOMINAL_VERTIV_PER_HOUR if metric in VERTIV_CONTINUOUS else None,
                    q, None,
                )
                frames.append(con.execute(sql).df())
            crac = merge_on(frames, ["timestamp_utc", "device"])
            if crac is not None:
                if {"Return_Air_Temperature_mean", "Supply_Air_Temperature_mean"}.issubset(crac.columns):
                    crac["air_delta_T_mean"] = (
                        crac["Return_Air_Temperature_mean"] - crac["Supply_Air_Temperature_mean"]
                    )
                crac = reindex_hours(crac, month, ["device"])
                crac = add_rome(crac)
                outp = grain_parquet("crac", month)
                write_zstd(crac, outp)
                sidecar(outp, month=month, grain="crac", n_rows=len(crac),
                        air_delta_T="from hourly means; device-level raw delta_T not joined (different sensors)")
                products.append(str(outp))

        # --- weather ---
        wsub = want.loc[want.plugin.str.contains("weather", case=False, na=False)]
        if len(wsub) and ("weather" in grains) and (force or not already("weather")):
            frames = []
            for metric in wsub["metric"].unique():
                plugin = wsub.loc[wsub.metric.eq(metric), "plugin"].iloc[0]
                glob = parquet_glob(tmp, plugin, metric)
                if glob is None:
                    continue
                sql = hourly_query(
                    glob, metric, [], start_ts, end_ts, "continuous", 1.0,
                    7200.0, None, True, None,
                )
                frames.append(con.execute(sql).df())
            weather = merge_on(frames, ["timestamp_utc"])
            if weather is not None:
                weather = reindex_hours(weather, month, [])
                if {"pressure_mean", "temp_mean"}.issubset(weather.columns):
                    weather["pressure_station_pa"] = [
                        sea_level_to_station_pa(p, t) if pd.notna(p) and pd.notna(t) else np.nan
                        for p, t in zip(weather["pressure_mean"], weather["temp_mean"])
                    ]
                    weather["pressure_is_sea_level"] = True
                    weather["elevation_m_assumed"] = CINECA_ELEVATION_M
                    weather["pressure_method"] = "hypsometric; OpenWeather sea-level hPa -> station Pa at 61 m assumed CINECA/Casalecchio elevation"
                    try:
                        import psychrolib
                        psychrolib.SetUnitSystem(psychrolib.SI)
                        twb = []
                        tdcol = weather["dew_point_mean"] if "dew_point_mean" in weather.columns else [np.nan] * len(weather)
                        for t, td, p in zip(weather["temp_mean"], tdcol, weather["pressure_station_pa"]):
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
                weather = add_rome(weather)
                outp = grain_parquet("weather", month)
                write_zstd(weather, outp)
                sidecar(outp, month=month, grain="weather", n_rows=len(weather),
                        wet_bulb="psychrolib SI from hourly mean T, Td, station P; not sea-level P")
                products.append(str(outp))

        # --- node IPMI total_power only when qualified ---
        if do_node and (force or not already("node")):
            ipmi = want.loc[want.plugin.str.contains("ipmi", case=False, na=False) & want.metric.eq("total_power")]
            if len(ipmi):
                plugin = ipmi["plugin"].iloc[0]
                glob = parquet_glob(tmp, plugin, "total_power")
                if glob:
                    sql = hourly_query(
                        glob, "total_power", ["node"], start_ts, end_ts,
                        "power", 1.0, MAX_GAP_IPMI_S, NOMINAL_IPMI_PER_HOUR, True, "W",
                    )
                    node = con.execute(sql).df()
                    node["timestamp_utc"] = pd.to_datetime(node["timestamp_utc"], utc=True)
                    if "total_power_coverage" not in node.columns and "total_power_count" in node.columns:
                        node["total_power_coverage"] = node["total_power_count"] / float(NOMINAL_IPMI_PER_HOUR)
                    node["high_quality"] = node.get("total_power_coverage", pd.Series(dtype=float)).ge(0.90)
                    outp = grain_parquet("node", month)
                    write_zstd(node, outp)
                    sidecar(outp, month=month, grain="node", n_rows=len(node),
                            n_nodes=int(node["node"].nunique()),
                            energy_unit="kWh from W trapezoid", max_gap_s=MAX_GAP_IPMI_S)
                    products.append(str(outp))

        timings["duckdb_s"] = round(time.time() - t_duck, 2)
        con.close()
        save_status(
            month,
            facility_extraction_status="done",
            node_extraction_status="done" if do_node else "skipped_unqualified",
            processed_products=products,
            schema_version=SCHEMA_VERSION,
            timings=timings,
            runtime_s=sum(v for v in timings.values() if isinstance(v, (int, float))),
            failure=None,
        )
        return {"month": month, "timings": timings, "products": products, "n_metrics": int(len(want))}
    except Exception as exc:
        save_status(month, facility_extraction_status="failed", failure=str(exc))
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--month", required=True)
    p.add_argument("--force", action="store_true")
    p.add_argument("--grains", default=None, help="comma grains, default all applicable")
    p.add_argument("--test-metrics", action="store_true",
                   help="TEST E: weather+one logics metric only")
    args = p.parse_args()
    v, u, s = schneider_physical("PLC_PLC_Q101.Temp_mandata", 250)
    assert abs(v - 25.0) < 1e-9
    grains = args.grains.split(",") if args.grains else None
    if args.test_metrics:
        grains = ["weather"]
    print(process_month(args.month, force=args.force, grains=grains))


if __name__ == "__main__":
    main()
