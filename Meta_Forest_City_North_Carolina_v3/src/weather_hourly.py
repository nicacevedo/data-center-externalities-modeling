"""Hourly ISD/global-hourly builder. Reuses v1 NOAA files by path. Does not fill gaps."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import psychrolib

    psychrolib.SetUnitSystem(psychrolib.SI)
except Exception:
    psychrolib = None

from fc3_paths import V1_SRC

import sys

if str(V1_SRC) not in sys.path:
    sys.path.insert(0, str(V1_SRC))
from psychrometrics_adapter import wetbulb_from_rh  # noqa: E402

NCEI_QC_PASSED = frozenset({"0", "1", "4", "5", "9"})
NCEI_QC_EDITORIAL_RETAIN = frozenset({"A", "C", "M", "P"})


def ncei_qc_code(x) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return ""
    s = str(x).strip().upper()
    if s in {"", "NAN", "NONE", "NAT"}:
        return ""
    return s[:1]


def ncei_qc_usable(code) -> bool:
    c = ncei_qc_code(code)
    return c in NCEI_QC_PASSED or c in NCEI_QC_EDITORIAL_RETAIN


def scaled_with_qc(x, scale=10.0, missing=9999):
    if pd.isna(x):
        return (np.nan, "")
    p = str(x).split(",")
    try:
        raw = int(p[0])
    except Exception:
        return (np.nan, p[1] if len(p) > 1 else "")
    if abs(raw) >= missing:
        return (np.nan, p[1] if len(p) > 1 else "")
    return (raw / scale, p[1] if len(p) > 1 else "")


def station_pressure_from_slp(slp_hpa, t_c, elev_m):
    if np.isfinite(slp_hpa):
        tk = (t_c if np.isfinite(t_c) else 15.0) + 273.15
        return slp_hpa * 100.0 * math.exp(-9.80665 * float(elev_m) / (287.05 * tk))
    return 101325.0 * (1 - 2.25577e-5 * float(elev_m)) ** 5.2559


def altimeter_from_ma1(x):
    if pd.isna(x):
        return np.nan, np.nan
    p = str(x).split(",")
    try:
        slp = int(p[0])
        slp = np.nan if slp >= 99999 else slp / 10.0
    except Exception:
        slp = np.nan
    alt = np.nan
    if len(p) >= 3:
        try:
            a = int(p[2])
            alt = np.nan if a >= 99999 else a / 10.0
        except Exception:
            alt = np.nan
    return slp, alt


def rh_from_t_td(t, td):
    if not np.isfinite(t) or not np.isfinite(td):
        return np.nan
    a, b = 17.625, 243.04
    return float(np.clip(100 * np.exp(a * td / (b + td) - a * t / (b + t)), 0, 100))


def read_global_hourly(path: Path) -> pd.DataFrame:
    d = pd.read_csv(path, low_memory=False)
    ts = pd.to_datetime(d["DATE"], utc=True, errors="coerce")
    tmp = d["TMP"].apply(lambda x: scaled_with_qc(x, 10, 9999))
    dew = d["DEW"].apply(lambda x: scaled_with_qc(x, 10, 9999))
    slp_alt = d["MA1"].apply(altimeter_from_ma1) if "MA1" in d.columns else [(np.nan, np.nan)] * len(d)
    slp_col = d["SLP"].apply(lambda x: scaled_with_qc(x, 10, 99999)) if "SLP" in d.columns else [(np.nan, "")] * len(d)
    z = pd.DataFrame(
        {
            "timestamp_utc": ts,
            "t_db_C": [x[0] for x in tmp],
            "tmp_qc": [x[1] for x in tmp],
            "t_dew_C": [x[0] for x in dew],
            "dew_qc": [x[1] for x in dew],
            "slp_hPa_field": [x[0] for x in slp_col],
            "slp_qc": [x[1] for x in slp_col],
            "slp_hPa_ma1": [x[0] for x in slp_alt],
            "altimeter_hPa": [x[1] for x in slp_alt],
            "source_file": path.name,
        }
    ).dropna(subset=["timestamp_utc"])
    z.loc[~z["t_db_C"].between(-60, 60), "t_db_C"] = np.nan
    z.loc[~z["t_dew_C"].between(-80, 50), "t_dew_C"] = np.nan
    z["t_db_C"] = z["t_db_C"].where(z["tmp_qc"].map(ncei_qc_usable))
    z["t_dew_C"] = z["t_dew_C"].where(z["dew_qc"].map(ncei_qc_usable))
    z["slp_hPa"] = z["slp_hPa_field"].where(z["slp_qc"].map(ncei_qc_usable))
    z["slp_hPa"] = z["slp_hPa"].fillna(z["slp_hPa_ma1"])
    return z


def hourlyize(raw: pd.DataFrame, *, elev_m: float, call_sign: str, station_id: str, tz: str) -> pd.DataFrame:
    raw = raw.copy()
    raw["hour"] = raw["timestamp_utc"].dt.floor("h")
    h = raw.groupby("hour", as_index=False).agg(
        t_db_C=("t_db_C", "mean"),
        t_dew_C=("t_dew_C", "mean"),
        slp_hPa=("slp_hPa", "mean"),
        altimeter_hPa=("altimeter_hPa", "mean"),
        n_reports=("timestamp_utc", "size"),
    )
    h["rh_pct"] = [rh_from_t_td(t, td) for t, td in zip(h["t_db_C"], h["t_dew_C"])]
    p2 = []
    for s, a, t in zip(h["slp_hPa"], h["altimeter_hPa"], h["t_db_C"]):
        if np.isfinite(s):
            p2.append(station_pressure_from_slp(s, t, elev_m))
        elif np.isfinite(a):
            p2.append(station_pressure_from_slp(a, t, elev_m))
        else:
            p2.append(station_pressure_from_slp(np.nan, t, elev_m))
    h["pressure_Pa"] = p2
    wb = []
    for t, rh, p in zip(h["t_db_C"], h["rh_pct"], h["pressure_Pa"]):
        if psychrolib is not None and np.isfinite(t) and np.isfinite(rh) and np.isfinite(p):
            try:
                wb.append(float(psychrolib.GetTWetBulbFromRelHum(float(t), float(rh) / 100.0, float(p))))
                continue
            except Exception:
                pass
        wb.append(wetbulb_from_rh(t, (rh or 0) / 100.0, p) if np.isfinite(t) and np.isfinite(rh) else np.nan)
    h["t_wb_C"] = wb
    h["station"] = call_sign
    h["station_id"] = station_id
    h["timestamp_utc"] = h["hour"]
    h["timestamp_local"] = h["hour"].dt.tz_convert(tz)
    bad = (h["t_dew_C"] > h["t_db_C"] + 0.6) | (h["rh_pct"] < -1) | (h["rh_pct"] > 105)
    h.loc[bad, ["t_db_C", "t_dew_C", "rh_pct", "t_wb_C"]] = np.nan
    return h


def calendar_2012(hourly: pd.DataFrame, *, call_sign: str, station_id: str, tz: str) -> pd.DataFrame:
    idx = pd.date_range("2012-01-01", "2012-12-31 23:00:00", freq="h", tz="UTC")
    full = hourly.set_index("timestamp_utc").reindex(idx)
    full.index.name = "timestamp_utc"
    full = full.reset_index()
    full["station"] = call_sign
    full["station_id"] = station_id
    full["timestamp_local"] = full["timestamp_utc"].dt.tz_convert(tz)
    return full


def coverage_stats(full: pd.DataFrame, start: str, end: str) -> dict:
    m = (full["timestamp_utc"] >= start) & (full["timestamp_utc"] < end)
    sub = full.loc[m]
    n = int(m.sum())
    t = sub["t_db_C"].notna()
    d = sub["t_dew_C"].notna()
    p = sub["pressure_Pa"].notna()
    usable = sub[["t_db_C", "rh_pct", "pressure_Pa"]].notna().all(axis=1)
    return {
        "n_calendar_hours": n,
        "t_coverage": float(t.mean()) if n else float("nan"),
        "dewpoint_coverage": float(d.mean()) if n else float("nan"),
        "pressure_coverage": float(p.mean()) if n else float("nan"),
        "usable_hours": int(usable.sum()),
        "jja_completeness": float(usable.mean()) if n else float("nan"),
    }


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
