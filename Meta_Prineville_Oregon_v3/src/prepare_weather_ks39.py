"""QC, hourly KS39 product, coverage audit, KRDM overlap, and canonical weather.

Does not retune gray-box or water models. Reuses prepare_weather psychrometrics.
"""
from __future__ import annotations

import argparse
import calendar
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from madis_qc import (
    HARD_INVALID_DD,
    MODEL_USABLE_DD,
    QCR_SPATIAL_CONSISTENCY,
    QCR_VALIDITY,
    model_usable_series,
)
from prepare_weather import rh_from_t_td, wetbulb

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "noaa_madis_ks39"
SHARD_DIR = RAW_DIR / "shards"
MANIFEST = RAW_DIR / "download_manifest.csv"
REPORTS_GZ = RAW_DIR / "ks39_metar_reports.csv.gz"
KRDM = ROOT / "data" / "processed" / "weather_krdm_hourly.csv"
KS39_HOURLY = ROOT / "data" / "processed" / "weather_ks39_hourly.csv"
CANONICAL = ROOT / "data" / "processed" / "weather_hourly.csv"
OUT = ROOT / "outputs" / "weather_ks39"

TZ_LOCAL = "America/Los_Angeles"
KS39_ELEV_M_DEFAULT = 991.0
SWITCH_LOCAL = pd.Timestamp("2015-09-01 00:00:00", tz=TZ_LOCAL)
LOCAL_START = pd.Timestamp("2011-01-01 00:00:00", tz=TZ_LOCAL)
LOCAL_END_EXCLUSIVE = pd.Timestamp("2025-01-01 00:00:00", tz=TZ_LOCAL)
DEW_TOL_C = 0.3
T_RANGE = (-60.0, 60.0)
TD_RANGE = (-80.0, 50.0)
ALT_PA_RANGE = (56800.0, 110000.0)  # MADIS validity 568-1100 mb
WIND_MAX = 80.0  # m/s, well above 250 kt MADIS limit but physically wild


def station_pressure_from_altimeter_pa(alt_pa: float, elev_m: float) -> float:
    """ICAO standard-atmosphere inversion of altimeter setting (Doc 7488 / WMO).

    Altimeter setting A is sea-level pressure in the standard atmosphere that
    corresponds to station pressure P at elevation h:
        P = A * (1 - L h / T0) ** (g / (R L))
    with L=0.0065 K/m, T0=288.15 K, exponent ≈ 5.2559.
    Mark the result as DERIVED, not measured.
    """
    if not np.isfinite(alt_pa) or not np.isfinite(elev_m):
        return np.nan
    return float(alt_pa * (1.0 - 2.25577e-5 * float(elev_m)) ** 5.2559)


def load_raw_reports() -> pd.DataFrame:
    if REPORTS_GZ.exists():
        df = pd.read_csv(REPORTS_GZ, low_memory=False)
    else:
        files = sorted(SHARD_DIR.glob("ks39_*.csv"))
        if not files:
            raise FileNotFoundError(f"No KS39 reports in {SHARD_DIR} or {REPORTS_GZ}")
        df = pd.concat([pd.read_csv(p, low_memory=False) for p in files], ignore_index=True)
    for c in ("timeObs", "timeNominal", "timeReceived"):
        df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
    df["stationName"] = df["stationName"].astype(str).str.upper().str.strip()
    df["rawMETAR"] = df["rawMETAR"].fillna("").astype(str)
    df["report_key"] = (
        df["stationName"]
        + "|"
        + df["timeObs"].dt.strftime("%Y-%m-%dT%H:%M:%SZ").fillna("")
        + "|"
        + df["rawMETAR"].str.replace(r"\s+", " ", regex=True).str.strip()
    )
    return df


def resolve_reports(df: pd.DataFrame) -> pd.DataFrame:
    """Drop exact copies; prefer corrected METAR when correction indicator > 0."""
    z = df[df["stationName"].eq("KS39") & df["timeObs"].notna()].copy()
    z["correction"] = pd.to_numeric(z["correction"], errors="coerce").fillna(0)
    z["timeReceived_ts"] = pd.to_datetime(z["timeReceived"], utc=True, errors="coerce")
    z = z.sort_values(["report_key", "correction", "timeReceived_ts"], na_position="last")
    z = z.drop_duplicates("report_key", keep="last")
    # Same observation time: if any corrected copy exists, keep the highest correction.
    z = z.sort_values(["stationName", "timeObs", "correction", "timeReceived_ts"])
    corrected = z.groupby(["stationName", "timeObs"], sort=False)["correction"].transform("max")
    z = z.loc[~((corrected > 0) & (z["correction"] < corrected))].copy()
    z = z.drop_duplicates(["stationName", "timeObs", "rawMETAR"], keep="last")
    return z.reset_index(drop=True)


def _num(s) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def attach_qc(z: pd.DataFrame) -> pd.DataFrame:
    z = z.copy()
    z["t_k"] = _num(z["temperature"])
    z["td_k"] = _num(z["dewpoint"])
    z["t_db_C_raw"] = z["t_k"] - 273.15
    z["t_dew_C_raw"] = z["td_k"] - 273.15
    z["altimeter_Pa"] = _num(z["altimeter"])
    z["slp_Pa"] = _num(z["seaLevelPress"])
    z["wind_m_s_raw"] = _num(z["windSpeed"])
    z["precip_m_raw"] = _num(z["precip1Hour"])
    z["elevation_m"] = _num(z["elevation"])
    z["temp_usable"] = model_usable_series(z["t_k"], z["temperatureDD"], z["temperatureQCR"])
    z["dew_usable"] = model_usable_series(z["td_k"], z["dewpointDD"], z["dewpointQCR"])
    z["alt_usable"] = model_usable_series(z["altimeter_Pa"], z["altimeterDD"], z["altimeterQCR"])
    z["slp_usable"] = model_usable_series(z["slp_Pa"], z["seaLevelPressDD"], z["seaLevelPressQCR"])
    z["wind_usable"] = model_usable_series(z["wind_m_s_raw"], z["windSpeedDD"], z["windSpeedQCR"])
    z["precip_usable"] = model_usable_series(z["precip_m_raw"], z["precip1HourDD"], z["precip1HourQCR"])
    t_ok = z["t_db_C_raw"].between(*T_RANGE)
    td_ok = z["t_dew_C_raw"].between(*TD_RANGE)
    dew_le = z["t_dew_C_raw"] <= z["t_db_C_raw"] + DEW_TOL_C
    z["temp_usable"] = z["temp_usable"] & t_ok
    z["dew_usable"] = z["dew_usable"] & td_ok & dew_le & z["temp_usable"]
    z["alt_usable"] = z["alt_usable"] & z["altimeter_Pa"].between(*ALT_PA_RANGE)
    z["wind_usable"] = z["wind_usable"] & z["wind_m_s_raw"].between(0, WIND_MAX)
    z["precip_usable"] = z["precip_usable"] & (z["precip_m_raw"] >= 0) & (z["precip_m_raw"] < 0.2)
    elev = float(z["elevation_m"].median()) if z["elevation_m"].notna().any() else KS39_ELEV_M_DEFAULT
    z["pressure_Pa_derived"] = np.where(
        z["alt_usable"],
        z["altimeter_Pa"] * (1.0 - 2.25577e-5 * elev) ** 5.2559,
        np.nan,
    )
    z["pressure_source"] = np.where(z["alt_usable"], "derived_from_altimeter_icao", "")
    z["hour_utc"] = z["timeObs"].dt.floor("h")
    z["station_elevation_used_m"] = elev
    return z


def aggregate_hourly(z: pd.DataFrame) -> pd.DataFrame:
    """One row per physical UTC hour of timeObs.

    Continuous variables: arithmetic mean of QC-usable reports in the hour
    (same rule as prepare_weather.py for KRDM).
    precip1Hour is an overlapping 1-hour accumulation — take the last usable
    report in the hour; do not sum.
    """
    hour = z["hour_utc"]
    t_mean = z["t_db_C_raw"].where(z["temp_usable"]).groupby(hour).mean()
    td_mean = z["t_dew_C_raw"].where(z["dew_usable"]).groupby(hour).mean()
    wind_mean = z["wind_m_s_raw"].where(z["wind_usable"]).groupby(hour).mean()
    p_mean = z["pressure_Pa_derived"].where(z["alt_usable"]).groupby(hour).mean()
    n_raw = z.groupby(hour).size()
    n_t = z.groupby(hour)["temp_usable"].sum()
    n_td = z.groupby(hour)["dew_usable"].sum()
    n_alt = z.groupby(hour)["alt_usable"].sum()
    n_slp = z.groupby(hour)["slp_usable"].sum()
    lat = z.groupby(hour)["latitude"].median()
    lon = z.groupby(hour)["longitude"].median()
    elev = z.groupby(hour)["elevation_m"].median()
    last_precip = (
        z.loc[z["precip_usable"], ["hour_utc", "timeObs", "precip_m_raw"]]
        .sort_values("timeObs")
        .groupby("hour_utc")
        .tail(1)
        .set_index("hour_utc")["precip_m_raw"]
        * 1000.0
    )
    idx = n_raw.index.sort_values()
    h = pd.DataFrame({"timestamp_utc": idx})
    h["t_db_C"] = t_mean.reindex(idx).to_numpy()
    h["t_dew_C"] = td_mean.reindex(idx).to_numpy()
    h["pressure_Pa"] = p_mean.reindex(idx).to_numpy()
    h["wind_m_s"] = wind_mean.reindex(idx).to_numpy()
    h["precip_mm"] = last_precip.reindex(idx).to_numpy()
    h["rh_pct"] = [rh_from_t_td(t, td) for t, td in zip(h.t_db_C, h.t_dew_C)]
    h["t_wb_C"] = [
        wetbulb(t, td, p, rh) for t, td, p, rh in zip(h.t_db_C, h.t_dew_C, h.pressure_Pa, h.rh_pct)
    ]
    rh = h["rh_pct"].to_numpy(dtype=float)
    twb = h["t_wb_C"].to_numpy(dtype=float)
    tdb = h["t_db_C"].to_numpy(dtype=float)
    bad_rh = np.isfinite(rh) & ((rh < 0) | (rh > 100))
    bad_twb = np.isfinite(twb) & np.isfinite(tdb) & (twb > tdb + DEW_TOL_C)
    h.loc[bad_rh, ["rh_pct", "t_wb_C"]] = np.nan
    h.loc[bad_twb, "t_wb_C"] = np.nan
    h["station"] = "KS39 / Prineville Airport"
    h["weather_source"] = "KS39"
    h["source_method"] = "madis_metar_hourly_mean_usable"
    h["n_raw_reports"] = n_raw.reindex(idx).astype(int).to_numpy()
    h["n_usable_temp"] = n_t.reindex(idx).astype(int).to_numpy()
    h["n_usable_dew"] = n_td.reindex(idx).astype(int).to_numpy()
    h["n_usable_altimeter"] = n_alt.reindex(idx).astype(int).to_numpy()
    h["n_usable_slp"] = n_slp.reindex(idx).astype(int).to_numpy()
    h["qc_status"] = np.where((h.n_usable_temp > 0) & (h.n_usable_dew > 0), "usable", "partial_or_missing")
    h["pressure_method"] = np.where(h.n_usable_altimeter > 0, "ks39_altimeter_derived", "")
    h["latitude"] = lat.reindex(idx).to_numpy()
    h["longitude"] = lon.reindex(idx).to_numpy()
    h["elevation_m"] = elev.reindex(idx).to_numpy()
    h["timestamp_utc"] = pd.to_datetime(h["timestamp_utc"], utc=True)
    h["timestamp_local"] = h["timestamp_utc"].dt.tz_convert(TZ_LOCAL)
    h["year_utc"] = h["timestamp_utc"].dt.year
    h["year_local"] = h["timestamp_local"].dt.year
    h["month_local"] = h["timestamp_local"].dt.month
    h["date_local"] = h["timestamp_local"].dt.strftime("%Y-%m-%d")
    h["hour_local"] = h["timestamp_local"].dt.hour
    h["utc_offset"] = h["timestamp_local"].dt.strftime("%z")
    return h.sort_values("timestamp_utc").reset_index(drop=True)


def _longest_run(mask: np.ndarray) -> int:
    best = cur = 0
    for v in mask:
        if v:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return int(best)


def coverage_tables(hourly: pd.DataFrame, raw: pd.DataFrame, manifest: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Archive-hour and physical-hour coverage. Do not treat a missing archive file as KS39 absent."""
    man = manifest.copy()
    man["hour_utc"] = pd.to_datetime(man["hour_utc"], utc=True, errors="coerce")
    man["status"] = man["status"].astype(str)
    man["n_ks39"] = pd.to_numeric(man.get("n_ks39", 0), errors="coerce").fillna(0)
    start = pd.Timestamp("2015-08-01T00:00:00Z")
    end = pd.Timestamp("2025-01-02T00:00:00Z")
    archive = pd.DataFrame({"archive_hour_utc": pd.date_range(start, end, freq="h", tz="UTC")})
    archive = archive.merge(man[["hour_utc", "status", "n_ks39"]], left_on="archive_hour_utc", right_on="hour_utc", how="left")
    archive["archive_status"] = archive["status"].fillna("not_attempted")
    archive["file_ok"] = archive["archive_status"].eq("ok")
    archive["file_missing"] = archive["archive_status"].eq("not_found")
    archive["file_error"] = archive["archive_status"].eq("error")
    archive["ks39_in_file"] = archive["file_ok"] & (archive["n_ks39"] > 0)
    archive["ks39_absent_file_ok"] = archive["file_ok"] & (archive["n_ks39"] <= 0)
    archive["year"] = archive["archive_hour_utc"].dt.year
    archive["month"] = archive["archive_hour_utc"].dt.month

    phys = pd.DataFrame({"timestamp_utc": pd.date_range(start, end, freq="h", tz="UTC")})
    hs = hourly.set_index("timestamp_utc")
    phys = phys.join(
        hs[["n_raw_reports", "n_usable_temp", "n_usable_dew", "n_usable_altimeter"]],
        on="timestamp_utc",
    )
    phys["has_report"] = phys["n_raw_reports"].fillna(0) > 0
    phys["usable_t"] = phys["n_usable_temp"].fillna(0) > 0
    phys["usable_td"] = phys["n_usable_dew"].fillna(0) > 0
    phys["usable_both"] = phys["usable_t"] & phys["usable_td"]
    phys["usable_p"] = phys["n_usable_altimeter"].fillna(0) > 0
    phys["present_unusable"] = phys["has_report"] & ~phys["usable_both"]
    phys["year"] = phys["timestamp_utc"].dt.year
    phys["month"] = phys["timestamp_utc"].dt.month

    def archive_agg(g):
        ok = int(g.file_ok.sum())
        return pd.Series({
            "expected_archive_hours": int(len(g)),
            "source_hours_ok": ok,
            "source_hours_unavailable": int(g.file_missing.sum()),
            "source_hours_error": int(g.file_error.sum()),
            "source_hours_unattempted": int(g.archive_status.eq("not_attempted").sum()),
            "archive_hours_ks39_present": int(g.ks39_in_file.sum()),
            "archive_hours_ks39_absent_file_ok": int(g.ks39_absent_file_ok.sum()),
            "pct_ks39_present_given_file_ok": 100.0 * int(g.ks39_in_file.sum()) / ok if ok else np.nan,
            "longest_consecutive_archive_absent_when_file_ok": _longest_run(g.ks39_absent_file_ok.to_numpy()),
        })

    def phys_agg(g):
        expected = int(len(g))
        with_rep = int(g.has_report.sum())
        return pd.Series({
            "expected_physical_utc_hours": expected,
            "hours_with_ks39_report": with_rep,
            "hours_usable_temperature": int(g.usable_t.sum()),
            "hours_usable_dewpoint": int(g.usable_td.sum()),
            "hours_usable_temp_and_dew": int(g.usable_both.sum()),
            "hours_usable_pressure_input": int(g.usable_p.sum()),
            "hours_present_but_unusable": int(g.present_unusable.sum()),
            "n_raw_reports": int(g.n_raw_reports.fillna(0).sum()),
            "pct_physical_hours_with_report": 100.0 * with_rep / expected if expected else np.nan,
            "pct_physical_hours_usable_temp_dew": 100.0 * int(g.usable_both.sum()) / expected if expected else np.nan,
            "longest_consecutive_physical_hour_without_report": _longest_run((~g.has_report).to_numpy()),
        })

    a_m = archive.groupby(["year", "month"], sort=True).apply(archive_agg, include_groups=False).reset_index()
    p_m = phys.groupby(["year", "month"], sort=True).apply(phys_agg, include_groups=False).reset_index()
    monthly = a_m.merge(p_m, on=["year", "month"], how="outer")
    a_y = archive.groupby(["year"], sort=True).apply(archive_agg, include_groups=False).reset_index()
    p_y = phys.groupby(["year"], sort=True).apply(phys_agg, include_groups=False).reset_index()
    annual = a_y.merge(p_y, on=["year"], how="outer")

    n_alt = int(raw["altimeter"].notna().sum()) if "altimeter" in raw else 0
    n_slp = int(pd.to_numeric(raw.get("seaLevelPress"), errors="coerce").notna().sum()) if "seaLevelPress" in raw else 0
    n_rep = len(raw)
    daily_both = hourly.assign(dl=hourly["timestamp_local"].dt.strftime("%Y-%m-%d")).groupby("dl").apply(
        lambda g: pd.Series({"n": len(g), "n_both": int(((g.n_usable_temp > 0) & (g.n_usable_dew > 0)).sum())}),
        include_groups=False,
    )
    full_days = daily_both[daily_both.n_both >= 24]
    # first sustained: first local date after which sampled-style gaps are gone — first 7 consecutive full days
    sustained = ""
    if len(full_days):
        dates = pd.to_datetime(full_days.index)
        dates = dates.sort_values()
        run_start = dates[0]
        run_len = 1
        found = None
        for i in range(1, len(dates)):
            if dates[i] == dates[i - 1] + pd.Timedelta(days=1):
                run_len += 1
                if run_len >= 7 and found is None:
                    found = run_start
            else:
                run_start = dates[i]
                run_len = 1
        sustained = str(pd.Timestamp(found).date()) if found is not None else str(pd.Timestamp(dates[0]).date())
    gap = pd.DataFrame(
        [
            {"item": "first_timeObs_utc", "value": str(raw["timeObs"].min())},
            {"item": "last_timeObs_utc", "value": str(raw["timeObs"].max())},
            {"item": "first_hourly_utc", "value": str(hourly.timestamp_utc.min())},
            {"item": "last_hourly_utc", "value": str(hourly.timestamp_utc.max())},
            {"item": "first_local_date_with_24_usable_hours", "value": str(full_days.index.min()) if len(full_days) else ""},
            {"item": "first_sustained_7day_full_coverage_local", "value": sustained},
            {"item": "n_unique_raw_reports", "value": int(raw.report_key.nunique()) if "report_key" in raw else n_rep},
            {"item": "n_hourly_rows", "value": int(len(hourly))},
            {"item": "report_altimeter_nonmissing", "value": n_alt},
            {"item": "report_sealevelpress_nonmissing", "value": n_slp},
            {"item": "report_altimeter_pct", "value": 100.0 * n_alt / n_rep if n_rep else ""},
            {"item": "report_sealevelpress_pct", "value": 100.0 * n_slp / n_rep if n_rep else ""},
            {"item": "lat_median", "value": float(hourly.latitude.median()) if hourly.latitude.notna().any() else ""},
            {"item": "lon_median", "value": float(hourly.longitude.median()) if hourly.longitude.notna().any() else ""},
            {"item": "elev_m_median", "value": float(hourly.elevation_m.median()) if hourly.elevation_m.notna().any() else ""},
            {"item": "discovery_sample_note", "value": "2011-2024 madis_test sample rates are discovery estimates, not these exact counts"},
        ]
    )
    return monthly, annual, gap


def _metrics(pred, obs) -> dict:
    pred = np.asarray(pred, dtype=float)
    obs = np.asarray(obs, dtype=float)
    mask = np.isfinite(pred) & np.isfinite(obs)
    pred, obs = pred[mask], obs[mask]
    if pred.size == 0:
        return {k: np.nan for k in ("n", "mean_bias", "median_bias", "mae", "rmse", "corr", "p05", "p50", "p95")}
    d = pred - obs  # KS39 minus KRDM
    return {
        "n": int(pred.size),
        "mean_bias": float(d.mean()),
        "median_bias": float(np.median(d)),
        "mae": float(np.mean(np.abs(d))),
        "rmse": float(np.sqrt(np.mean(d ** 2))),
        "corr": float(np.corrcoef(pred, obs)[0, 1]) if pred.size > 2 else np.nan,
        "p05": float(np.quantile(d, 0.05)),
        "p50": float(np.quantile(d, 0.50)),
        "p95": float(np.quantile(d, 0.95)),
    }


def overlap_validation(ks39: pd.DataFrame, krdm: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    a = ks39.rename(columns={c: f"ks39_{c}" for c in ks39.columns if c != "timestamp_utc"})
    b = krdm.rename(columns={c: f"krdm_{c}" for c in krdm.columns if c != "timestamp_utc"})
    j = a.merge(b, on="timestamp_utc", how="inner")
    both = j[j["ks39_t_db_C"].notna() & j["krdm_t_db_C"].notna() & j["ks39_t_dew_C"].notna() & j["krdm_t_dew_C"].notna()].copy()
    vars_ = [
        ("t_db_C", "dry_bulb_C"),
        ("t_dew_C", "dewpoint_C"),
        ("rh_pct", "rh_pct"),
        ("t_wb_C", "wet_bulb_C"),
        ("wind_m_s", "wind_m_s"),
    ]
    rows = []
    for col, name in vars_:
        m = _metrics(both[f"ks39_{col}"], both[f"krdm_{col}"])
        m["variable"] = name
        m["subset"] = "all_overlap"
        rows.append(m)
    if both["ks39_t_wb_C"].notna().any():
        p90 = float(both["ks39_t_wb_C"].quantile(0.90))
        hot = both[both["ks39_t_wb_C"] >= p90]
        for col, name in vars_[:4]:
            m = _metrics(hot[f"ks39_{col}"], hot[f"krdm_{col}"])
            m["variable"] = name
            m["subset"] = f"ks39_twb_ge_p90_{p90:.2f}C"
            rows.append(m)
    summary = pd.DataFrame(rows)
    both["month"] = both["timestamp_utc"].dt.month
    monthly_rows = []
    for month, g in both.groupby("month"):
        for col, name in vars_[:4]:
            m = _metrics(g[f"ks39_{col}"], g[f"krdm_{col}"])
            m["variable"] = name
            m["month"] = int(month)
            monthly_rows.append(m)
    return summary, pd.DataFrame(monthly_rows)


def monthly_bias_test(ks39: pd.DataFrame, krdm: pd.DataFrame) -> dict:
    a = ks39[["timestamp_utc", "t_db_C", "t_dew_C"]].rename(columns={"t_db_C": "ks_t", "t_dew_C": "ks_td"})
    b = krdm[["timestamp_utc", "t_db_C", "t_dew_C", "pressure_Pa"]].rename(
        columns={"t_db_C": "kr_t", "t_dew_C": "kr_td", "pressure_Pa": "kr_p"}
    )
    j = a.merge(b, on="timestamp_utc", how="inner").dropna(subset=["ks_t", "ks_td", "kr_t", "kr_td"])
    j["year"] = j["timestamp_utc"].dt.year
    j["month"] = j["timestamp_utc"].dt.month
    train = j[j.year.between(2016, 2021)]
    hold = j[j.year.between(2022, 2024)]
    if len(train) < 1000 or len(hold) < 100:
        return {"adopt": False, "reason": "insufficient overlap for chronological split"}
    bias_t = train.groupby("month").apply(lambda g: float((g.ks_t - g.kr_t).mean()), include_groups=False)
    bias_td = train.groupby("month").apply(lambda g: float((g.ks_td - g.kr_td).mean()), include_groups=False)
    hold = hold.copy()
    hold["kr_t_corr"] = hold["kr_t"] + hold["month"].map(bias_t)
    hold["kr_td_corr"] = hold["kr_td"] + hold["month"].map(bias_td)
    # physical: dewpoint not above dry-bulb
    n_viol = int((hold["kr_td_corr"] > hold["kr_t_corr"] + DEW_TOL_C).sum())
    mae_t0 = float((hold.ks_t - hold.kr_t).abs().mean())
    mae_t1 = float((hold.ks_t - hold.kr_t_corr).abs().mean())
    mae_d0 = float((hold.ks_td - hold.kr_td).abs().mean())
    mae_d1 = float((hold.ks_td - hold.kr_td_corr).abs().mean())
    yearly = []
    for y, g in hold.groupby("year"):
        yearly.append({
            "year": int(y),
            "mae_t_raw": float((g.ks_t - g.kr_t).abs().mean()),
            "mae_t_corr": float((g.ks_t - (g.kr_t + g.month.map(bias_t))).abs().mean()),
            "mae_td_raw": float((g.ks_td - g.kr_td).abs().mean()),
            "mae_td_corr": float((g.ks_td - (g.kr_td + g.month.map(bias_td))).abs().mean()),
        })
    improve_all_years = all(r["mae_t_corr"] < r["mae_t_raw"] - 0.05 and r["mae_td_corr"] < r["mae_td_raw"] - 0.05 for r in yearly)
    material = (mae_t0 - mae_t1) >= 0.20 and (mae_d0 - mae_d1) >= 0.20
    adopt = bool(improve_all_years and material and n_viol == 0)
    return {
        "adopt": adopt,
        "reason": (
            "adopted: stable material holdout MAE improvement, no Td>T violations"
            if adopt
            else "rejected: improvement not material and stable across holdout years, or physical violations"
        ),
        "train_years": "2016-2021",
        "holdout_years": "2022-2024",
        "n_train": int(len(train)),
        "n_holdout": int(len(hold)),
        "holdout_mae_t_raw": mae_t0,
        "holdout_mae_t_corrected": mae_t1,
        "holdout_mae_td_raw": mae_d0,
        "holdout_mae_td_corrected": mae_d1,
        "holdout_td_gt_t_violations": n_viol,
        "yearly": yearly,
        "monthly_bias_t_C": {int(k): float(v) for k, v in bias_t.items()},
        "monthly_bias_td_C": {int(k): float(v) for k, v in bias_td.items()},
    }


def add_local_fields(h: pd.DataFrame) -> pd.DataFrame:
    z = h.copy()
    z["timestamp_utc"] = pd.to_datetime(z["timestamp_utc"], utc=True)
    z["timestamp_local"] = z["timestamp_utc"].dt.tz_convert(TZ_LOCAL)
    z["year_utc"] = z["timestamp_utc"].dt.year
    z["year_local"] = z["timestamp_local"].dt.year
    z["month_local"] = z["timestamp_local"].dt.month
    z["date_local"] = z["timestamp_local"].dt.strftime("%Y-%m-%d")
    z["hour_local"] = z["timestamp_local"].dt.hour
    z["utc_offset"] = z["timestamp_local"].dt.strftime("%z")
    return z


def canonical_utc_index() -> pd.DatetimeIndex:
    """Physical UTC hours covering local 2011-01-01 00:00 <= t < 2025-01-01 00:00."""
    start = LOCAL_START.tz_convert("UTC")
    end = LOCAL_END_EXCLUSIVE.tz_convert("UTC") - pd.Timedelta(hours=1)
    return pd.date_range(start, end, freq="h", tz="UTC")


def altimeter_qc_audit_2015_2017(qced: pd.DataFrame, hourly: pd.DataFrame) -> pd.DataFrame:
    """Compact 2015–2017 KS39 altimeter QC audit. Does not change MADIS acceptance rules."""
    z = qced.copy()
    z["year"] = z["timeObs"].dt.year
    z = z[z["year"].isin([2015, 2016, 2017])].copy()
    z["altimeterDD"] = z["altimeterDD"].fillna("").astype(str).str.strip().str.upper().str[:1]
    z["altimeterQCR"] = pd.to_numeric(z["altimeterQCR"], errors="coerce").fillna(0).astype(int)
    z["validity_bit_failed"] = (z["altimeterQCR"].to_numpy() & QCR_VALIDITY) != 0
    z["spatial_consistency_failed"] = (z["altimeterQCR"].to_numpy() & QCR_SPATIAL_CONSISTENCY) != 0
    z["accepted"] = z["alt_usable"].astype(bool)
    alt = z["altimeter_Pa"].to_numpy(dtype=float)
    dd = z["altimeterDD"].to_numpy()
    known_dd = set(MODEL_USABLE_DD) | set(HARD_INVALID_DD) | {"Q", ""}
    reason = np.full(len(z), "other", dtype=object)
    accepted = z["accepted"].to_numpy()
    reason[accepted] = "accepted"
    rejected = ~accepted
    missing = ~np.isfinite(alt)
    reason[rejected & missing] = "missing_or_nonfinite"
    hard = np.isin(dd, list(HARD_INVALID_DD))
    reason[rejected & ~missing & hard] = "dd_hard_invalid"
    reason[rejected & ~missing & (dd == "Q")] = "dd_questioned_failed_level2_or_3"
    validity = z["validity_bit_failed"].to_numpy()
    reason[rejected & ~missing & validity & (dd != "Q") & ~hard] = "qcr_validity_bit"
    reason[rejected & ~missing & ~np.isin(dd, list(known_dd))] = "dd_unrecognized"
    in_range = (alt >= ALT_PA_RANGE[0]) & (alt <= ALT_PA_RANGE[1])
    still_other = rejected & ~missing & (reason == "other") & ~in_range
    reason[still_other] = "physical_range"
    z["rejection_reason"] = reason
    z["accepted_flag"] = np.where(accepted, "accepted", "rejected")
    report = (
        z.groupby(
            [
                "year",
                "altimeterDD",
                "altimeterQCR",
                "validity_bit_failed",
                "spatial_consistency_failed",
                "accepted_flag",
                "rejection_reason",
            ],
            dropna=False,
        )
        .size()
        .reset_index(name="n")
        .sort_values(["year", "accepted_flag", "n"], ascending=[True, True, False])
    )
    report["level"] = "report"
    report["conclusion"] = ""

    hs = hourly.copy()
    hs["year"] = hs["timestamp_utc"].dt.year
    hs = hs[hs["year"].isin([2015, 2016, 2017])]
    hour_rows = []
    for year, g in hs.groupby("year"):
        n_hours = int(len(g))
        n_p = int((g["n_usable_altimeter"].fillna(0) > 0).sum())
        n_t = int((g["n_usable_temp"].fillna(0) > 0).sum())
        yrep = z[z["year"] == year]
        n_q = int((yrep["altimeterDD"] == "Q").sum())
        n_qcr65 = int((yrep["altimeterQCR"] == 65).sum())
        if int(year) == 2016:
            conclusion = (
                "genuine_noaa_qc_not_parser_bug; "
                "2016 usable-pressure drop is DD=Q / QCR=65 (master+spatial consistency); "
                "validity bit is not set; MADIS rules already exclude Q; keep KRDM pressure fallback"
            )
        else:
            conclusion = "no_parser_bug; questioned-altimeter spike is 2016-specific"
        hour_rows.append({
            "year": int(year),
            "altimeterDD": "",
            "altimeterQCR": np.nan,
            "validity_bit_failed": False,
            "spatial_consistency_failed": False,
            "accepted_flag": "hourly_summary",
            "rejection_reason": "",
            "n": n_hours,
            "level": "hourly",
            "hours_usable_temperature": n_t,
            "hours_usable_pressure": n_p,
            "n_reports_dd_Q": n_q,
            "n_reports_qcr_65": n_qcr65,
            "conclusion": conclusion,
        })
    hourly_sum = pd.DataFrame(hour_rows)
    report["hours_usable_temperature"] = np.nan
    report["hours_usable_pressure"] = np.nan
    report["n_reports_dd_Q"] = np.nan
    report["n_reports_qcr_65"] = np.nan
    return pd.concat([report, hourly_sum], ignore_index=True)


def build_canonical(krdm: pd.DataFrame, ks39: pd.DataFrame, bias: dict) -> pd.DataFrame:
    idx = canonical_utc_index()
    grid = add_local_fields(pd.DataFrame({"timestamp_utc": idx}))
    k = krdm.copy()
    k["timestamp_utc"] = pd.to_datetime(k["timestamp_utc"], utc=True)
    k = k.sort_values("timestamp_utc").drop_duplicates("timestamp_utc")
    k_keep = [
        "timestamp_utc", "t_db_C", "t_dew_C", "slp_hPa", "pressure_Pa",
        "wind_m_s", "precip_mm", "source_file", "tmp_qc", "dew_qc", "slp_qc",
        "pressure_method",
    ]
    k = k[[c for c in k_keep if c in k.columns]].rename(
        columns={
            "t_db_C": "kr_t_db_C",
            "t_dew_C": "kr_t_dew_C",
            "pressure_Pa": "kr_pressure_Pa",
            "wind_m_s": "kr_wind_m_s",
            "precip_mm": "kr_precip_mm",
            "pressure_method": "kr_pressure_method",
        }
    )
    ks = ks39.copy()
    ks["timestamp_utc"] = pd.to_datetime(ks["timestamp_utc"], utc=True)
    ks_keep = [
        "timestamp_utc", "t_db_C", "t_dew_C", "pressure_Pa",
        "wind_m_s", "precip_mm", "n_usable_temp", "n_usable_dew", "qc_status",
        "pressure_method",
    ]
    ks = ks[[c for c in ks_keep if c in ks.columns]].rename(
        columns={c: f"ks_{c}" for c in ks_keep if c != "timestamp_utc"}
    )
    j = grid.merge(k, on="timestamp_utc", how="left").merge(ks, on="timestamp_utc", how="left")
    in_ks_window = j["timestamp_local"] >= SWITCH_LOCAL
    ks_ok = (
        in_ks_window
        & (j["ks_n_usable_temp"].fillna(0) > 0)
        & (j["ks_n_usable_dew"].fillna(0) > 0)
        & j["ks_t_db_C"].notna()
        & j["ks_t_dew_C"].notna()
    )
    ks_p_ok = ks_ok & j["ks_pressure_Pa"].notna()
    kr_method = (
        j["kr_pressure_method"].fillna("").astype(str)
        if "kr_pressure_method" in j.columns
        else pd.Series("", index=j.index)
    )
    need = j["kr_pressure_Pa"].notna() & kr_method.eq("")
    kr_method = kr_method.mask(need & j["slp_hPa"].notna(), "krdm_slp_derived")
    kr_method = kr_method.mask(need & j["slp_hPa"].isna(), "krdm_standard_atmosphere_fallback")

    out = pd.DataFrame({
        "timestamp_utc": j["timestamp_utc"],
        "timestamp_local": j["timestamp_local"],
        "year_utc": j["year_utc"],
        "year_local": j["year_local"],
        "month_local": j["month_local"],
        "date_local": j["date_local"],
        "hour_local": j["hour_local"],
        "utc_offset": j["utc_offset"],
    })
    out["t_db_C"] = np.where(ks_ok, j["ks_t_db_C"], j["kr_t_db_C"])
    out["t_dew_C"] = np.where(ks_ok, j["ks_t_dew_C"], j["kr_t_dew_C"])
    out["pressure_Pa"] = np.where(ks_p_ok, j["ks_pressure_Pa"], j["kr_pressure_Pa"])
    out["pressure_method"] = np.where(ks_p_ok, "ks39_altimeter_derived", kr_method)
    out.loc[out["pressure_Pa"].isna(), "pressure_method"] = ""
    out["rh_pct"] = [rh_from_t_td(t, td) for t, td in zip(out.t_db_C, out.t_dew_C)]
    out["t_wb_C"] = [
        wetbulb(t, td, p, rh)
        for t, td, p, rh in zip(out.t_db_C, out.t_dew_C, out.pressure_Pa, out.rh_pct)
    ]
    out["wind_m_s"] = np.where(ks_ok, j["ks_wind_m_s"], j["kr_wind_m_s"])
    out["precip_mm"] = np.where(ks_ok, j["ks_precip_mm"], j["kr_precip_mm"])
    out["station"] = np.where(ks_ok, "KS39 / Prineville Airport", "KRDM / 72692024230")
    out["weather_source"] = np.where(ks_ok, "KS39", "KRDM")
    out["weather_method"] = np.select(
        [ks_ok, in_ks_window],
        ["ks39_valid_observed", "krdm_gapfill"],
        default="krdm_observed",
    )
    out["weather_observed"] = np.where(out["t_db_C"].notna(), "yes", "no")
    out["weather_gapfilled"] = np.where(out["weather_method"].eq("krdm_gapfill"), "yes", "no")
    out["qc_status"] = np.where(ks_ok, j["ks_qc_status"].fillna("usable"), "krdm_baseline")
    out["slp_hPa"] = j["slp_hPa"] if "slp_hPa" in j.columns else np.nan
    out["source_file"] = j["source_file"] if "source_file" in j.columns else ""
    if "tmp_qc" in j.columns:
        out["tmp_qc"] = j["tmp_qc"]
        out["dew_qc"] = j["dew_qc"]
        out["slp_qc"] = j["slp_qc"]
    out["provenance"] = np.select(
        [ks_ok & ks_p_ok, ks_ok, in_ks_window],
        [
            "canonical KS39/KRDM weather; ks39_valid_observed; T/Td measured MADIS METAR; pressure ks39_altimeter_derived; RH/Twb recomputed from final T/Td/P",
            "canonical KS39/KRDM weather; ks39_valid_observed; T/Td measured MADIS METAR; pressure KRDM fallback; RH/Twb recomputed from final T/Td/P",
            "canonical KS39/KRDM weather; krdm_gapfill; T/Td measured KRDM; RH/Twb recomputed from final T/Td/P",
        ],
        default="canonical KS39/KRDM weather; krdm_observed; T/Td measured KRDM; RH/Twb recomputed from final T/Td/P",
    )
    if bias.get("adopt"):
        # Reserved: monthly additive T/Td would apply only to pre-switch KRDM rows.
        raise RuntimeError("KRDM correction adopt=True is not applied automatically; inspect bias JSON first.")
    if not out["timestamp_utc"].is_unique:
        raise ValueError("Canonical UTC hourly key is not unique")
    if not out["timestamp_utc"].is_monotonic_increasing:
        out = out.sort_values("timestamp_utc").reset_index(drop=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-canonical-overwrite", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    raw = load_raw_reports()
    n_loaded = len(raw)
    resolved = resolve_reports(raw)
    if resolved["report_key"].duplicated().any():
        raise ValueError("Duplicate report_key after correction resolution")
    REPORTS_GZ.parent.mkdir(parents=True, exist_ok=True)
    resolved.to_csv(REPORTS_GZ, index=False, compression="gzip")
    qced = attach_qc(resolved)
    hourly = aggregate_hourly(qced)
    if hourly["timestamp_utc"].duplicated().any():
        raise ValueError("Duplicate UTC hour in KS39 hourly product")
    KS39_HOURLY.parent.mkdir(parents=True, exist_ok=True)
    hourly.to_csv(KS39_HOURLY, index=False)

    if not MANIFEST.exists():
        raise FileNotFoundError(MANIFEST)
    manifest = pd.read_csv(MANIFEST)
    monthly, annual, gap = coverage_tables(hourly, qced, manifest)
    monthly.to_csv(OUT / "ks39_coverage_monthly.csv", index=False)
    annual.to_csv(OUT / "ks39_coverage_annual.csv", index=False)
    gap.to_csv(OUT / "ks39_gap_summary.csv", index=False)
    # also project-root outputs copies requested by the brief
    monthly.to_csv(ROOT / "outputs" / "ks39_coverage_monthly.csv", index=False)
    annual.to_csv(ROOT / "outputs" / "ks39_coverage_annual.csv", index=False)
    gap.to_csv(ROOT / "outputs" / "ks39_gap_summary.csv", index=False)
    n_rep = len(qced)
    completeness = pd.DataFrame(
        [
            {
                "field": field,
                "n_nonmissing": int(pd.to_numeric(qced[field], errors="coerce").notna().sum())
                if field in qced
                else 0,
                "pct": 100.0
                * (
                    int(pd.to_numeric(qced[field], errors="coerce").notna().sum()) / n_rep
                    if n_rep and field in qced
                    else 0
                ),
                "role": role,
            }
            for field, role in [
                ("temperature", "measured K"),
                ("dewpoint", "measured K"),
                ("altimeter", "measured Pa; pressure input"),
                ("seaLevelPress", "measured Pa; usually missing"),
                ("windSpeed", "measured m/s"),
                ("precip1Hour", "measured m; overlapping accumulation"),
            ]
        ]
    )
    completeness.to_csv(OUT / "ks39_field_completeness.csv", index=False)
    completeness.to_csv(ROOT / "outputs" / "ks39_field_completeness.csv", index=False)

    audit = altimeter_qc_audit_2015_2017(qced, hourly)
    audit.to_csv(OUT / "ks39_altimeter_qc_2015_2017.csv", index=False)
    audit.to_csv(ROOT / "outputs" / "ks39_altimeter_qc_2015_2017.csv", index=False)

    if not KRDM.exists():
        raise FileNotFoundError(f"Preserve KRDM baseline first: {KRDM}")
    krdm = pd.read_csv(KRDM)
    krdm["timestamp_utc"] = pd.to_datetime(krdm["timestamp_utc"], utc=True)
    summary, monthly_ov = overlap_validation(hourly, krdm)
    summary.to_csv(OUT / "ks39_krdm_overlap_summary.csv", index=False)
    monthly_ov.to_csv(OUT / "ks39_krdm_overlap_monthly.csv", index=False)
    summary.to_csv(ROOT / "outputs" / "ks39_krdm_overlap_summary.csv", index=False)
    monthly_ov.to_csv(ROOT / "outputs" / "ks39_krdm_overlap_monthly.csv", index=False)

    bias = monthly_bias_test(hourly, krdm)
    (OUT / "ks39_krdm_monthly_bias_test.json").write_text(json.dumps(bias, indent=2), encoding="utf-8")
    if bias.get("adopt"):
        print("WARNING: monthly KRDM correction would be adopted; this path is implemented only if holdout evidence is strong.")
    else:
        print("Pre-2015 KRDM correction REJECTED:", bias.get("reason"))

    canonical = build_canonical(krdm, hourly, bias)
    if canonical["timestamp_utc"].duplicated().any():
        raise ValueError("Canonical UTC hourly key is not unique")
    expected_index = canonical_utc_index()
    if len(canonical) != len(expected_index):
        raise ValueError(f"Canonical has {len(canonical)} hours, expected {len(expected_index)}")
    if canonical["timestamp_utc"].min() != expected_index.min() or canonical["timestamp_utc"].max() != expected_index.max():
        raise ValueError("Canonical UTC bounds do not match local calendar years 2011-2024")
    for year, n in canonical.groupby("year_local").size().items():
        expect = 8784 if calendar.isleap(int(year)) else 8760
        if int(n) != expect:
            raise ValueError(f"Canonical local year {year} has {n} hours, expected {expect}")
    years = set(pd.to_numeric(canonical["year_local"], errors="coerce").astype(int))
    if years != set(range(2011, 2025)):
        raise ValueError(f"Canonical local years are {sorted(years)}, expected 2011-2024")
    if not args.no_canonical_overwrite:
        canonical.to_csv(CANONICAL, index=False)
    canonical.to_csv(ROOT / "data" / "processed" / "weather_canonical_hourly.csv", index=False)

    pre = canonical[canonical.timestamp_local < SWITCH_LOCAL]
    if pre["weather_source"].ne("KRDM").any():
        raise ValueError("Pre-2015-09-01 local canonical weather must remain KRDM-based")

    print(
        f"raw_loaded={n_loaded} unique_reports={len(resolved)} hourly={len(hourly)} "
        f"canonical={len(canonical)} first_obs={qced.timeObs.min()} last_obs={qced.timeObs.max()}"
    )


if __name__ == "__main__":
    main()
