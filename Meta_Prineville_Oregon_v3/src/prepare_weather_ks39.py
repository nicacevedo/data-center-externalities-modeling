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
from prepare_weather import (
    ELEV_M as KRDM_ELEV_M,
    SHORT_GAP_LIMIT_HOURS,
    gap_run_lengths,
    rh_from_t_td,
    short_gap_interpolated,
    station_pressure_from_slp,
    wetbulb,
)

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "noaa_madis_ks39"
SHARD_DIR = RAW_DIR / "shards"
MANIFEST = RAW_DIR / "download_manifest.csv"
REPORTS_GZ = RAW_DIR / "ks39_metar_reports.csv.gz"
KRDM = ROOT / "data" / "processed" / "weather_krdm_hourly.csv"
KS39_HOURLY = ROOT / "data" / "processed" / "weather_ks39_hourly.csv"
KBDN = ROOT / "data" / "processed" / "weather_kbdn_hourly.csv"
CANONICAL = ROOT / "data" / "processed" / "weather_hourly.csv"
OUT = ROOT / "outputs" / "weather_ks39"
KBDN_STATION_ID = "72063800224"
KBDN_LABEL = "KBDN / 72063800224"

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


def build_canonical(
    krdm: pd.DataFrame,
    ks39: pd.DataFrame,
    bias: dict,
    kbdn: pd.DataFrame | None = None,
    tertiary_xfer: dict | None = None,
) -> pd.DataFrame:
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
    if kbdn is not None:
        bd = kbdn.copy()
        bd["timestamp_utc"] = pd.to_datetime(bd["timestamp_utc"], utc=True)
        bd_keep = ["timestamp_utc", "t_db_C", "t_dew_C", "slp_hPa"]
        bd = bd[[c for c in bd_keep if c in bd.columns]].rename(
            columns={
                "t_db_C": "bd_t_db_C",
                "t_dew_C": "bd_t_dew_C",
                "slp_hPa": "bd_slp_hPa",
            }
        )
        j = j.merge(bd, on="timestamp_utc", how="left")
    in_ks_window = j["timestamp_local"] >= SWITCH_LOCAL
    kr_method = (
        j["kr_pressure_method"].fillna("").astype(str)
        if "kr_pressure_method" in j.columns
        else pd.Series("", index=j.index)
    )
    need = j["kr_pressure_Pa"].notna() & kr_method.eq("")
    kr_method = kr_method.mask(need & j["slp_hPa"].notna(), "krdm_slp_derived")
    kr_method = kr_method.mask(need & j["slp_hPa"].isna(), "krdm_standard_atmosphere_fallback")

    out = _assemble_canonical_from_merged(j, in_ks_window, kr_method, bias, tertiary_xfer)
    return out


def month_additive_bias(target: np.ndarray, source: np.ndarray, month: np.ndarray, min_n: int = 50) -> dict:
    """Calendar-month mean(target - source) on overlapping finite hours.

    Months with fewer than `min_n` overlap hours inherit the overall mean.
    This is the protocol monthly additive transfer, not an hour-of-day model.
    """
    t = np.asarray(target, dtype=float)
    s = np.asarray(source, dtype=float)
    m = np.asarray(month, dtype=int)
    ok = np.isfinite(t) & np.isfinite(s)
    overall = float(np.mean(t[ok] - s[ok])) if ok.any() else 0.0
    out = {int(mm): overall for mm in range(1, 13)}
    for mm in range(1, 13):
        mask = ok & (m == mm)
        if int(mask.sum()) >= min_n:
            out[mm] = float(np.mean(t[mask] - s[mask]))
    return out


def kbdn_krdm_compatibility(kbdn: pd.DataFrame, krdm: pd.DataFrame) -> dict:
    """Overlap diagnostics for tertiary KBDN vs KRDM. Independent of water-model results."""
    a = kbdn[["timestamp_utc", "t_db_C", "t_dew_C", "slp_hPa"]].rename(
        columns={"t_db_C": "bd_t", "t_dew_C": "bd_td", "slp_hPa": "bd_slp"}
    )
    b = krdm[["timestamp_utc", "t_db_C", "t_dew_C", "slp_hPa"]].rename(
        columns={"t_db_C": "kr_t", "t_dew_C": "kr_td", "slp_hPa": "kr_slp"}
    )
    a["timestamp_utc"] = pd.to_datetime(a["timestamp_utc"], utc=True)
    b["timestamp_utc"] = pd.to_datetime(b["timestamp_utc"], utc=True)
    j = a.merge(b, on="timestamp_utc", how="inner")
    j["month"] = j["timestamp_utc"].dt.month
    t_ok = np.isfinite(j["bd_t"]) & np.isfinite(j["kr_t"])
    td_ok = np.isfinite(j["bd_td"]) & np.isfinite(j["kr_td"])
    p_ok = np.isfinite(j["bd_slp"]) & np.isfinite(j["kr_slp"])
    d_t = (j.loc[t_ok, "kr_t"] - j.loc[t_ok, "bd_t"]).to_numpy(dtype=float)
    d_td = (j.loc[td_ok, "kr_td"] - j.loc[td_ok, "bd_td"]).to_numpy(dtype=float)
    d_slp = (j.loc[p_ok, "kr_slp"] - j.loc[p_ok, "bd_slp"]).to_numpy(dtype=float)
    bias_t = month_additive_bias(j["kr_t"].to_numpy(), j["bd_t"].to_numpy(), j["month"].to_numpy())
    bias_td = month_additive_bias(j["kr_td"].to_numpy(), j["bd_td"].to_numpy(), j["month"].to_numpy())
    return {
        "selected_station_id": KBDN_STATION_ID,
        "selected_station_name": "Bend Municipal Airport",
        "icao": "KBDN",
        "provider": "NOAA NCEI Global Hourly",
        "role": "tertiary gap-only weather fallback",
        "source_selection_independent_of_model_results": True,
        "selection_reason": (
            "Authoritative NCEI observational station 31.7 km from Prineville; "
            "TMP and DEW present at all hours where KS39/KRDM cannot supply QC-usable "
            "required primitives. Not selected using electricity, water, PUE, WUE, "
            "or any fitted-model metric."
        ),
        "candidates_evaluated": [
            {"station_id": "72063800224", "icao": "KBDN", "name": "BEND MUNICIPAL AIRPORT", "result": "selected"},
            {"station_id": "72688799999", "icao": "KS21", "name": "SUNRIVER", "result": "rejected_http_404"},
        ],
        "n_overlap_t": int(t_ok.sum()),
        "n_overlap_td": int(td_ok.sum()),
        "n_overlap_slp": int(p_ok.sum()),
        "mean_bias_t_C_krdm_minus_kbdn": float(np.mean(d_t)) if len(d_t) else np.nan,
        "median_bias_t_C": float(np.median(d_t)) if len(d_t) else np.nan,
        "mae_t_C": float(np.mean(np.abs(d_t))) if len(d_t) else np.nan,
        "rmse_t_C": float(np.sqrt(np.mean(d_t ** 2))) if len(d_t) else np.nan,
        "corr_t": float(np.corrcoef(j.loc[t_ok, "kr_t"], j.loc[t_ok, "bd_t"])[0, 1]) if t_ok.sum() > 2 else np.nan,
        "mean_bias_td_C_krdm_minus_kbdn": float(np.mean(d_td)) if len(d_td) else np.nan,
        "median_bias_td_C": float(np.median(d_td)) if len(d_td) else np.nan,
        "mae_td_C": float(np.mean(np.abs(d_td))) if len(d_td) else np.nan,
        "rmse_td_C": float(np.sqrt(np.mean(d_td ** 2))) if len(d_td) else np.nan,
        "corr_td": float(np.corrcoef(j.loc[td_ok, "kr_td"], j.loc[td_ok, "bd_td"])[0, 1]) if td_ok.sum() > 2 else np.nan,
        "mean_bias_slp_hPa_krdm_minus_kbdn": float(np.mean(d_slp)) if len(d_slp) else np.nan,
        "mae_slp_hPa": float(np.mean(np.abs(d_slp))) if len(d_slp) else np.nan,
        "monthly_bias_t_C": {str(k): v for k, v in bias_t.items()},
        "monthly_bias_td_C": {str(k): v for k, v in bias_td.items()},
        "correction_rule": "MISSING_DATA_PROTOCOL.md monthly additive bias on overlapping observed hours; no hour-of-day interactions",
        "bias_t": bias_t,
        "bias_td": bias_td,
    }


def apply_tertiary_gapfill(
    t_db,
    t_dew,
    pressure,
    p_method,
    ter_t,
    ter_td,
    ter_slp,
    month,
    bias_t_by_month: dict,
    bias_td_by_month: dict,
    target_elev_m: float,
):
    """Fill remaining missing T/Td from a tertiary station. Do not overwrite finite hierarchy values."""
    t_db = np.array(t_db, dtype=float, copy=True)
    t_dew = np.array(t_dew, dtype=float, copy=True)
    pressure = np.array(pressure, dtype=float, copy=True)
    p_method = np.array(p_method, dtype=object, copy=True)
    ter_t = np.asarray(ter_t, dtype=float)
    ter_td = np.asarray(ter_td, dtype=float)
    ter_slp = np.asarray(ter_slp, dtype=float)
    month = np.asarray(month, dtype=int)
    bias_t = np.array([bias_t_by_month.get(int(m), 0.0) for m in month], dtype=float)
    bias_td = np.array([bias_td_by_month.get(int(m), 0.0) for m in month], dtype=float)
    ter_t_c = ter_t + bias_t
    ter_td_c = ter_td + bias_td
    need_t = ~np.isfinite(t_db)
    need_td = ~np.isfinite(t_dew)
    take_t = need_t & np.isfinite(ter_t_c)
    take_td = need_td & np.isfinite(ter_td_c)
    used = take_t | take_td
    t_db[take_t] = ter_t_c[take_t]
    t_dew[take_td] = ter_td_c[take_td]
    t_dew = _clip_dew(t_db, t_dew)
    still_p = used & np.isfinite(t_db) & ~np.isfinite(pressure)
    ter_p = np.array(
        [
            station_pressure_from_slp(slp, t, elev_m=target_elev_m)
            if np.isfinite(slp) and np.isfinite(t)
            else np.nan
            for slp, t in zip(ter_slp, t_db)
        ],
        dtype=float,
    )
    use_ter_p = still_p & np.isfinite(ter_p)
    pressure[use_ter_p] = ter_p[use_ter_p]
    p_method[use_ter_p] = "kbdn_slp_derived_krdm_elevation"
    return t_db, t_dew, pressure, p_method, used, take_t, take_td, use_ter_p


def _clip_dew(t_db, t_dew):
    t_db = np.asarray(t_db, dtype=float)
    t_dew = np.asarray(t_dew, dtype=float)
    cap = t_db + DEW_TOL_C
    over = np.isfinite(t_db) & np.isfinite(t_dew) & (t_dew > cap)
    t_dew = t_dew.copy()
    t_dew[over] = cap[over]
    return t_dew


def _recompute_rh_twb(t_db, t_dew, pressure):
    rh = np.array([rh_from_t_td(t, td) for t, td in zip(t_db, t_dew)], dtype=float)
    twb = np.array(
        [wetbulb(t, td, p, r) for t, td, p, r in zip(t_db, t_dew, pressure, rh)],
        dtype=float,
    )
    return rh, twb


def _assemble_canonical_from_merged(
    j: pd.DataFrame,
    in_ks_window: pd.Series,
    kr_method: pd.Series,
    bias: dict,
    tertiary_xfer: dict | None = None,
) -> pd.DataFrame:
    """Mix KS39/KRDM, then resolve remaining required-driver gaps per protocol."""
    in_ks = np.asarray(in_ks_window, dtype=bool)
    kr_t = np.array(pd.to_numeric(j["kr_t_db_C"], errors="coerce"), dtype=float, copy=True)
    kr_td = np.array(pd.to_numeric(j["kr_t_dew_C"], errors="coerce"), dtype=float, copy=True)
    kr_p = np.array(pd.to_numeric(j["kr_pressure_Pa"], errors="coerce"), dtype=float, copy=True)
    kr_slp = np.array(
        pd.to_numeric(j["slp_hPa"], errors="coerce") if "slp_hPa" in j.columns else np.full(len(j), np.nan),
        dtype=float,
        copy=True,
    )
    kr_wind = np.array(pd.to_numeric(j["kr_wind_m_s"], errors="coerce"), dtype=float, copy=True)
    kr_precip = np.array(pd.to_numeric(j["kr_precip_mm"], errors="coerce"), dtype=float, copy=True)
    ks_t = np.array(pd.to_numeric(j["ks_t_db_C"], errors="coerce"), dtype=float, copy=True)
    ks_td = np.array(pd.to_numeric(j["ks_t_dew_C"], errors="coerce"), dtype=float, copy=True)
    ks_p = np.array(pd.to_numeric(j["ks_pressure_Pa"], errors="coerce"), dtype=float, copy=True)
    ks_wind = np.array(pd.to_numeric(j["ks_wind_m_s"], errors="coerce"), dtype=float, copy=True)
    ks_precip = np.array(pd.to_numeric(j["ks_precip_mm"], errors="coerce"), dtype=float, copy=True)
    ks_t[~in_ks] = np.nan
    ks_td[~in_ks] = np.nan
    ks_p[~in_ks] = np.nan
    kr_method_arr = kr_method.fillna("").astype(str).to_numpy()

    def mix(ks_t_, ks_td_, ks_p_, kr_t_, kr_td_, kr_p_, kr_method_):
        ks_ok = in_ks & np.isfinite(ks_t_) & np.isfinite(ks_td_)
        ks_p_ok = ks_ok & np.isfinite(ks_p_)
        t_db = np.where(ks_ok, ks_t_, kr_t_)
        t_dew = _clip_dew(t_db, np.where(ks_ok, ks_td_, kr_td_))
        pressure = np.where(ks_p_ok, ks_p_, kr_p_)
        p_method = np.where(ks_p_ok, "ks39_altimeter_derived", kr_method_)
        p_method = np.where(np.isfinite(pressure), p_method, "")
        rh, twb = _recompute_rh_twb(t_db, t_dew, pressure)
        return ks_ok, ks_p_ok, t_db, t_dew, pressure, p_method, rh, twb

    _ks_ok0, _ks_p_ok0, t0, td0, p0, _pm0, rh0, tw0 = mix(
        ks_t, ks_td, ks_p, kr_t, kr_td, kr_p, kr_method_arr
    )
    pre_bad = (
        ~np.isfinite(t0) | ~np.isfinite(tw0) | ~np.isfinite(rh0) | ~np.isfinite(p0)
    )
    pre_gap_len = gap_run_lengths(pre_bad)
    affected = []
    for tdb, twb, rh, pres in zip(t0, tw0, rh0, p0):
        miss = []
        if not np.isfinite(tdb):
            miss.append("t_db_C")
        if not np.isfinite(twb):
            miss.append("t_wb_C")
        if not np.isfinite(rh):
            miss.append("rh_pct")
        if not np.isfinite(pres):
            miss.append("pressure_Pa")
        affected.append(";".join(miss))
    kr_td_ok = np.isfinite(kr_t) & np.isfinite(kr_td)
    fallback_available = np.where(in_ks, kr_td_ok, False)
    fallback_source = np.where(in_ks, "KRDM", "")

    kr_t_s, kr_t_was = short_gap_interpolated(pd.Series(kr_t))
    kr_td_s, kr_td_was = short_gap_interpolated(pd.Series(kr_td))
    kr_slp_s, kr_slp_was = short_gap_interpolated(pd.Series(kr_slp))
    kr_t = kr_t_s.to_numpy(dtype=float)
    kr_td = _clip_dew(kr_t, kr_td_s.to_numpy(dtype=float))
    kr_slp = kr_slp_s.to_numpy(dtype=float)
    kr_p = np.array(
        [
            station_pressure_from_slp(slp, t, KRDM_ELEV_M) if np.isfinite(t) or np.isfinite(slp) else np.nan
            for slp, t in zip(kr_slp, kr_t)
        ],
        dtype=float,
    )
    kr_method_arr = np.where(
        np.isfinite(kr_slp),
        "krdm_slp_derived",
        np.where(np.isfinite(kr_p), "krdm_standard_atmosphere_fallback", ""),
    )
    ks_t_s, ks_t_was = short_gap_interpolated(pd.Series(ks_t))
    ks_td_s, ks_td_was = short_gap_interpolated(pd.Series(ks_td))
    ks_p_s, ks_p_was = short_gap_interpolated(pd.Series(ks_p))
    ks_t = ks_t_s.to_numpy(dtype=float)
    ks_td = _clip_dew(ks_t, ks_td_s.to_numpy(dtype=float))
    ks_p = ks_p_s.to_numpy(dtype=float)

    ks_ok, ks_p_ok, t_db, t_dew, pressure, p_method, rh, twb = mix(
        ks_t, ks_td, ks_p, kr_t, kr_td, kr_p, kr_method_arr
    )
    interp_ks = (ks_t_was | ks_td_was).to_numpy(dtype=bool) & ks_ok
    interp_kr = (kr_t_was | kr_td_was | kr_slp_was).to_numpy(dtype=bool) & ~ks_ok
    mix_t_s, mix_t_was = short_gap_interpolated(pd.Series(t_db))
    mix_td_s, mix_td_was = short_gap_interpolated(pd.Series(t_dew))
    t_db = mix_t_s.to_numpy(dtype=float)
    t_dew = _clip_dew(t_db, mix_td_s.to_numpy(dtype=float))
    interp_mix = (mix_t_was | mix_td_was).to_numpy(dtype=bool)
    interpolated = interp_ks | interp_kr | interp_mix

    ter_used = np.zeros(len(j), dtype=bool)
    if tertiary_xfer and "bd_t_db_C" in j.columns:
        month = pd.to_datetime(j["timestamp_utc"], utc=True).dt.month.to_numpy(dtype=int)
        t_db, t_dew, pressure, p_method, ter_used, _take_t, _take_td, _use_ter_p = apply_tertiary_gapfill(
            t_db,
            t_dew,
            pressure,
            p_method,
            j["bd_t_db_C"],
            j["bd_t_dew_C"],
            j["bd_slp_hPa"] if "bd_slp_hPa" in j.columns else np.full(len(j), np.nan),
            month,
            tertiary_xfer.get("bias_t", {}),
            tertiary_xfer.get("bias_td", {}),
            KRDM_ELEV_M,
        )
        ter_used = np.asarray(ter_used, dtype=bool) & ~ks_ok

    still_p = np.isfinite(t_db) & ~np.isfinite(pressure)
    elev = np.where(ks_ok, KS39_ELEV_M_DEFAULT, KRDM_ELEV_M)
    std_p = 101325.0 * (1.0 - 2.25577e-5 * elev.astype(float)) ** 5.2559
    used_std = still_p
    pressure = np.where(used_std, std_p, pressure)
    p_method = np.where(
        used_std & ks_ok,
        "ks39_standard_atmosphere_fallback",
        np.where(used_std, "krdm_standard_atmosphere_fallback", p_method),
    )
    p_method = np.where(np.isfinite(pressure), p_method, "")
    rh, twb = _recompute_rh_twb(t_db, t_dew, pressure)

    fill_method = np.full(len(j), "observed", dtype=object)
    fill_method[interpolated] = "interpolated_short_gap"
    fill_method[ter_used] = "kbdn_tertiary_gapfill_monthly_bias"
    fill_method[used_std & ~interpolated & ~ter_used] = "standard_atmosphere_pressure"
    post_finite = np.isfinite(t_db) & np.isfinite(twb) & np.isfinite(rh) & np.isfinite(pressure)
    fill_method[pre_bad & ~post_finite] = "unresolved"

    weather_method = np.select(
        [ter_used, interpolated, ks_ok, in_ks],
        ["kbdn_tertiary_gapfill", "interpolated_short_gap", "ks39_valid_observed", "krdm_gapfill"],
        default="krdm_observed",
    )
    weather_source = np.where(ter_used, "KBDN", np.where(ks_ok, "KS39", "KRDM"))
    station = np.where(
        ter_used,
        KBDN_LABEL,
        np.where(ks_ok, "KS39 / Prineville Airport", "KRDM / 72692024230"),
    )
    provenance = np.select(
        [
            ter_used,
            fill_method == "interpolated_short_gap",
            ks_ok & ks_p_ok,
            ks_ok,
            in_ks,
        ],
        [
            "canonical weather; kbdn_tertiary_gapfill after KS39/KRDM unavailable; NCEI QC; monthly additive KRDM-KBDN bias; RH/Twb recomputed from final T/Td/P; not observed at preferred station",
            "canonical KS39/KRDM weather; interpolated_short_gap (<=2 h, bracketing QC-passed); RH/Twb recomputed from final T/Td/P; not a generic observed label",
            "canonical KS39/KRDM weather; ks39_valid_observed; T/Td measured MADIS METAR; pressure ks39_altimeter_derived; RH/Twb recomputed from final T/Td/P",
            "canonical KS39/KRDM weather; ks39_valid_observed; T/Td measured MADIS METAR; pressure fallback; RH/Twb recomputed from final T/Td/P",
            "canonical KS39/KRDM weather; krdm_gapfill; T/Td measured KRDM; RH/Twb recomputed from final T/Td/P",
        ],
        default="canonical KS39/KRDM weather; krdm_observed; T/Td measured KRDM; RH/Twb recomputed from final T/Td/P",
    )
    provenance = np.where(
        (fill_method == "standard_atmosphere_pressure") | (ter_used & used_std),
        np.char.add(np.asarray(provenance, dtype=str), "; pressure standard_atmosphere_fallback"),
        provenance,
    )

    resolution = np.full(len(j), "", dtype=object)
    resolution[pre_bad & interpolated] = "interpolated_short_gap"
    resolution[pre_bad & used_std & interpolated] = "interpolated_short_gap+standard_atmosphere_pressure"
    resolution[pre_bad & ter_used] = "kbdn_tertiary_gapfill"
    resolution[pre_bad & ter_used & used_std] = "kbdn_tertiary_gapfill+standard_atmosphere_pressure"
    resolution[pre_bad & used_std & ~interpolated & ~ter_used] = "standard_atmosphere_pressure"
    resolution[pre_bad & post_finite & (resolution == "")] = "station_hierarchy_after_short_gap_fill"
    resolution[pre_bad & ~post_finite] = "unresolved"

    t_prim_gap = gap_run_lengths(~np.isfinite(t0))
    td_prim_gap = gap_run_lengths(~np.isfinite(td0))
    p_prim_gap = gap_run_lengths(~np.isfinite(p0))
    t_interp = (kr_t_was.to_numpy(dtype=bool) & ~ks_ok) | (ks_t_was.to_numpy(dtype=bool) & ks_ok) | mix_t_was.to_numpy(dtype=bool)
    td_interp = (kr_td_was.to_numpy(dtype=bool) & ~ks_ok) | (ks_td_was.to_numpy(dtype=bool) & ks_ok) | mix_td_was.to_numpy(dtype=bool)
    var_ok = (~interpolated) | (
        ((~t_interp) | (t_prim_gap <= SHORT_GAP_LIMIT_HOURS))
        & ((~td_interp) | (td_prim_gap <= SHORT_GAP_LIMIT_HOURS))
    )
    fallback_source = np.where(ter_used, "KBDN", fallback_source)
    fallback_available = np.where(ter_used, 1, fallback_available)

    wind = np.where(ks_ok, ks_wind, kr_wind)
    precip = np.where(ks_ok, ks_precip, kr_precip)

    out = pd.DataFrame({
        "timestamp_utc": j["timestamp_utc"],
        "timestamp_local": j["timestamp_local"],
        "year_utc": j["year_utc"],
        "year_local": j["year_local"],
        "month_local": j["month_local"],
        "date_local": j["date_local"],
        "hour_local": j["hour_local"],
        "utc_offset": j["utc_offset"],
        "t_db_C": t_db,
        "t_dew_C": t_dew,
        "pressure_Pa": pressure,
        "pressure_method": p_method,
        "rh_pct": rh,
        "t_wb_C": twb,
        "wind_m_s": wind,
        "precip_mm": precip,
        "station": station,
        "weather_source": weather_source,
        "weather_method": weather_method,
        "weather_observed": np.where(
            (fill_method == "interpolated_short_gap") | ter_used | ~np.isfinite(t_db),
            "no",
            "yes",
        ),
        "weather_gapfilled": np.where(
            (weather_method == "krdm_gapfill")
            | (fill_method == "interpolated_short_gap")
            | ter_used,
            "yes",
            "no",
        ),
        "qc_status": np.where(
            ter_used,
            "kbdn_ncei",
            np.where(ks_ok, j["ks_qc_status"].fillna("usable"), "krdm_baseline"),
        ),
        "slp_hPa": kr_slp,
        "source_file": j["source_file"] if "source_file" in j.columns else "",
        "weather_fill_method": fill_method,
        "required_driver_pre_fill_nonfinite": pre_bad.astype(int),
        "weather_gap_length": pre_gap_len,
        "weather_gap_class": np.where(
            ~pre_bad,
            "",
            np.where(pre_gap_len <= SHORT_GAP_LIMIT_HOURS, "short_gap", "long_gap"),
        ),
        "affected_drivers_pre_fill": affected,
        "fallback_source": fallback_source,
        "fallback_available": fallback_available.astype(int),
        "resolution_method": resolution,
        "post_resolution_finite": post_finite.astype(int),
        "t_db_primitive_gap_hours": t_prim_gap,
        "t_dew_primitive_gap_hours": td_prim_gap,
        "pressure_primitive_gap_hours": p_prim_gap,
        "short_gap_variable_specific_ok": var_ok.astype(int),
        "tertiary_source": np.array(
            ["KBDN/72063800224" if flag else "" for flag in ter_used],
            dtype=object,
        ),
        "source_selection_independent_of_model_results": "yes",
    })
    if "tmp_qc" in j.columns:
        out["tmp_qc"] = j["tmp_qc"]
        out["dew_qc"] = j["dew_qc"]
        out["slp_qc"] = j["slp_qc"]
    out["provenance"] = provenance
    if bias.get("adopt"):
        raise RuntimeError("KRDM correction adopt=True is not applied automatically; inspect bias JSON first.")
    if not out["timestamp_utc"].is_unique:
        raise ValueError("Canonical UTC hourly key is not unique")
    if not out["timestamp_utc"].is_monotonic_increasing:
        out = out.sort_values("timestamp_utc").reset_index(drop=True)
    return out


def weather_resolution_audit_table(canonical: pd.DataFrame) -> pd.DataFrame:
    """Hour-level audit of required-driver gaps that existed before protocol fill."""
    w = canonical
    if "required_driver_pre_fill_nonfinite" not in w.columns:
        req = ["t_db_C", "t_wb_C", "rh_pct", "pressure_Pa"]
        bad = ~np.isfinite(w[req].to_numpy(dtype=float)).all(axis=1)
        w = w.copy()
        w["required_driver_pre_fill_nonfinite"] = bad.astype(int)
        w["weather_gap_length"] = gap_run_lengths(bad)
        w["weather_gap_class"] = np.where(bad, np.where(w["weather_gap_length"] <= SHORT_GAP_LIMIT_HOURS, "short_gap", "long_gap"), "")
        w["affected_drivers_pre_fill"] = ""
        w["fallback_source"] = np.where(w.get("weather_method", "") == "krdm_gapfill", "KRDM", "")
        w["fallback_available"] = 0
        w["resolution_method"] = np.where(bad, "unresolved", "")
        w["post_resolution_finite"] = (~bad).astype(int)
        w["weather_fill_method"] = w.get("weather_fill_method", pd.Series("", index=w.index))
        w["provenance"] = w.get("provenance", pd.Series("", index=w.index))
        w["station"] = w.get("station", pd.Series("", index=w.index))
    z = w[w["required_driver_pre_fill_nonfinite"].fillna(0).astype(int).eq(1)].copy()
    if z.empty:
        return pd.DataFrame(
            columns=[
                "timestamp_utc",
                "year_local",
                "affected_drivers",
                "source_station",
                "gap_length_hours",
                "gap_class",
                "fallback_source",
                "fallback_available",
                "resolution_method",
                "final_provenance",
                "post_resolution_finite",
            ]
        )
    return pd.DataFrame({
        "timestamp_utc": z["timestamp_utc"],
        "year_local": z["year_local"] if "year_local" in z.columns else "",
        "affected_drivers": z.get("affected_drivers_pre_fill", ""),
        "source_station": z.get("station", z.get("weather_source", "")),
        "gap_length_hours": z.get("weather_gap_length", ""),
        "gap_class": z.get("weather_gap_class", ""),
        "fallback_source": z.get("fallback_source", ""),
        "fallback_available": z.get("fallback_available", 0),
        "resolution_method": z.get("resolution_method", z.get("weather_fill_method", "")),
        "final_provenance": z.get("provenance", ""),
        "post_resolution_finite": z.get("post_resolution_finite", 0),
        "weather_source": z.get("weather_source", ""),
        "weather_method": z.get("weather_method", ""),
        "weather_fill_method": z.get("weather_fill_method", ""),
        "t_db_primitive_gap_hours": z["t_db_primitive_gap_hours"] if "t_db_primitive_gap_hours" in z.columns else "",
        "t_dew_primitive_gap_hours": z["t_dew_primitive_gap_hours"] if "t_dew_primitive_gap_hours" in z.columns else "",
        "pressure_primitive_gap_hours": z["pressure_primitive_gap_hours"] if "pressure_primitive_gap_hours" in z.columns else "",
        "short_gap_variable_specific_ok": z["short_gap_variable_specific_ok"] if "short_gap_variable_specific_ok" in z.columns else "",
        "tertiary_source": (
            z["tertiary_source"].map(lambda x: "" if pd.isna(x) or str(x).strip() in {"", "nan"} else (
                str(int(float(x))) if str(x).replace(".", "", 1).isdigit() or isinstance(x, (int, float)) else str(x)
            ))
            if "tertiary_source" in z.columns
            else ""
        ),
        "source_selection_independent_of_model_results": (
            z["source_selection_independent_of_model_results"]
            if "source_selection_independent_of_model_results" in z.columns
            else "yes"
        ),
    })



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

    if not KBDN.exists():
        raise FileNotFoundError(
            f"KBDN tertiary product missing: {KBDN}. Run src/prepare_weather_kbdn.py first."
        )
    kbdn = pd.read_csv(KBDN)
    kbdn["timestamp_utc"] = pd.to_datetime(kbdn["timestamp_utc"], utc=True)
    kbdn_x = kbdn_krdm_compatibility(kbdn, krdm)
    xfer = {"bias_t": kbdn_x["bias_t"], "bias_td": kbdn_x["bias_td"]}
    kbdn_json = {k: v for k, v in kbdn_x.items() if k not in {"bias_t", "bias_td"}}

    def _jsonable(obj):
        if isinstance(obj, dict):
            return {str(k): _jsonable(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_jsonable(v) for v in obj]
        if isinstance(obj, (np.floating, float)):
            x = float(obj)
            return None if not math.isfinite(x) else x
        if isinstance(obj, (np.integer, int)) and not isinstance(obj, bool):
            return int(obj)
        if isinstance(obj, (np.bool_, bool)):
            return bool(obj)
        return obj

    kbdn_json = _jsonable(kbdn_json)
    (OUT / "kbdn_krdm_overlap_diagnostics.json").write_text(
        json.dumps(kbdn_json, indent=2), encoding="utf-8"
    )
    report_dir = ROOT / "outputs" / "pipeline_report"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "kbdn_krdm_overlap_diagnostics.json").write_text(
        json.dumps(kbdn_json, indent=2), encoding="utf-8"
    )
    print(
        "KBDN/KRDM overlap n_t={n_overlap_t} mae_t={mae_t_C:.3f} mae_td={mae_td_C:.3f} "
        "selection_independent_of_model_results={source_selection_independent_of_model_results}".format(
            **{k: kbdn_json[k] for k in (
                "n_overlap_t", "mae_t_C", "mae_td_C", "source_selection_independent_of_model_results"
            )}
        )
    )

    canonical = build_canonical(krdm, hourly, bias, kbdn=kbdn, tertiary_xfer=xfer)
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
    audit = weather_resolution_audit_table(canonical)
    audit_path = ROOT / "outputs" / "pipeline_report" / "weather_finite_driver_audit.csv"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit.to_csv(audit_path, index=False)
    audit.to_csv(OUT / "weather_finite_driver_audit.csv", index=False)
    if not args.no_canonical_overwrite:
        canonical.to_csv(CANONICAL, index=False)
    canonical.to_csv(ROOT / "data" / "processed" / "weather_canonical_hourly.csv", index=False)

    pre = canonical[canonical.timestamp_local < SWITCH_LOCAL]
    if (~pre["weather_source"].isin(["KRDM", "KBDN"])).any():
        raise ValueError("Pre-2015-09-01 local canonical weather must remain KRDM-based (KBDN tertiary gap-fill only)")
    if (pre["weather_source"].eq("KS39")).any():
        raise ValueError("Pre-2015-09-01 local canonical weather must not use KS39")
    kbdn_pre = pre[pre["weather_source"].eq("KBDN")]
    if len(kbdn_pre) and (~kbdn_pre["weather_method"].eq("kbdn_tertiary_gapfill")).any():
        raise ValueError("KBDN may appear before 2015-09-01 only as tertiary gap-fill")
    unresolved = (
        audit[pd.to_numeric(audit["post_resolution_finite"], errors="coerce").fillna(1).eq(0)]
        if len(audit)
        else audit
    )
    n_pre = int(len(audit))
    n_interp = int(audit["resolution_method"].astype(str).str.contains("interpolated_short_gap").sum()) if len(audit) else 0
    n_tertiary = int(audit["resolution_method"].astype(str).str.contains("kbdn_tertiary_gapfill").sum()) if len(audit) else 0
    n_unresolved = int(len(unresolved))
    print(
        f"raw_loaded={n_loaded} unique_reports={len(resolved)} hourly={len(hourly)} "
        f"canonical={len(canonical)} first_obs={qced.timeObs.min()} last_obs={qced.timeObs.max()} "
        f"pre_fill_nonfinite={n_pre} interpolated={n_interp} tertiary_kbdn={n_tertiary} unresolved={n_unresolved}"
    )
    if n_unresolved:
        ts = unresolved["timestamp_utc"].astype(str).tolist()
        sample = ", ".join(ts[:20])
        extra = f" ... ({len(ts) - 20} more)" if len(ts) > 20 else ""
        raise ValueError(
            f"{len(ts)} canonical hours still have non-finite required weather drivers "
            f"after protocol-compliant short-gap interpolation, KRDM/KS39 substitution, "
            f"and KBDN tertiary gap-fill. "
            f"Wrote {audit_path}. Do not invent values. Unresolved timestamps: {sample}{extra}"
        )


if __name__ == "__main__":
    main()
