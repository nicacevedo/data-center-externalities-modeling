#!/usr/bin/env python3
"""Build KFQD 2012 hourly weather. Do not silently fill the pre-2012-06-21 gap."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

FC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FC / "src"))
from hashes import sha256_file, write_json  # noqa: E402
from paths import DATA_PROCESSED, OUTPUTS, RAW_WEATHER  # noqa: E402
from psychrometrics_adapter import wetbulb_from_rh  # noqa: E402

try:
    import psychrolib

    psychrolib.SetUnitSystem(psychrolib.SI)
except Exception:
    psychrolib = None

STATION_PRIMARY = "72314453890"
STATION_CALL = "KFQD"
STATION_NAME = "RUTHERFORD CO MARCHMAN FIELD AIRPORT"
ELEV_M = 328.6
LAT = 35.428
LON = -81.935
TZ = "America/New_York"

NCEI_QC_PASSED = frozenset({"0", "1", "4", "5", "9"})
NCEI_QC_EDITORIAL_RETAIN = frozenset({"A", "C", "M", "P"})
NCEI_QC_SUSPECT = frozenset({"2", "3", "6", "7"})


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


def station_pressure_from_slp(slp_hpa, t_c, elev_m=ELEV_M):
    if np.isfinite(slp_hpa):
        tk = (t_c if np.isfinite(t_c) else 15.0) + 273.15
        return slp_hpa * 100.0 * math.exp(-9.80665 * float(elev_m) / (287.05 * tk))
    return 101325.0 * (1 - 2.25577e-5 * float(elev_m)) ** 5.2559


def altimeter_from_ma1(x):
    """MA1 is SLP,altimeter in tenths of hPa."""
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


def hourlyize(raw: pd.DataFrame) -> pd.DataFrame:
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
    h["pressure_Pa"] = [
        station_pressure_from_slp(s if np.isfinite(s) else a, t)
        for s, a, t in zip(h["slp_hPa"], h["t_db_C"], h["altimeter_hPa"] if False else h["slp_hPa"])
    ]
    # prefer altimeter-derived station pressure when SLP missing
    p2 = []
    for s, a, t in zip(h["slp_hPa"], h["altimeter_hPa"], h["t_db_C"]):
        if np.isfinite(s):
            p2.append(station_pressure_from_slp(s, t))
        elif np.isfinite(a):
            p2.append(station_pressure_from_slp(a, t))
        else:
            p2.append(station_pressure_from_slp(np.nan, t))
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
    h["station"] = STATION_CALL
    h["station_id"] = STATION_PRIMARY
    h["source_station"] = f"{STATION_NAME} ({STATION_CALL} {STATION_PRIMARY})"
    ny = h["hour"].dt.tz_convert(TZ)
    h["timestamp_local"] = ny
    h["timestamp_utc"] = h["hour"]
    # impossible T/RH/dewpoint
    bad = (h["t_dew_C"] > h["t_db_C"] + 0.6) | (h["rh_pct"] < -1) | (h["rh_pct"] > 105)
    h.loc[bad, ["t_db_C", "t_dew_C", "rh_pct", "t_wb_C"]] = np.nan
    return h


def qa_report(h: pd.DataFrame, year: int = 2012) -> dict:
    idx = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00:00", freq="h", tz="UTC")
    aligned = h.set_index("timestamp_utc").reindex(idx)
    n = len(idx)
    usable = aligned[["t_db_C", "rh_pct", "pressure_Pa"]].notna().all(axis=1)
    dst = aligned.index.tz_convert(TZ)
    return {
        "station_id": STATION_PRIMARY,
        "call_sign": STATION_CALL,
        "name": STATION_NAME,
        "lat": LAT,
        "lon": LON,
        "elev_m": ELEV_M,
        "timezone": TZ,
        "ocp_note": "OCP 2013: Rutherfordton weather approximately six miles NW of Forest City used for design analysis.",
        "raw_files": [p.name for p in sorted(RAW_WEATHER.glob(f"{STATION_PRIMARY}_*.csv"))],
        "raw_hashes": {p.name: sha256_file(p) for p in sorted(RAW_WEATHER.glob(f"{STATION_PRIMARY}_*.csv"))},
        "first_valid_utc": str(h.dropna(subset=["t_db_C"])["timestamp_utc"].min()),
        "last_valid_utc": str(h.dropna(subset=["t_db_C"])["timestamp_utc"].max()),
        "n_calendar_hours": n,
        "n_hours_with_any_observation": int(aligned["t_db_C"].notna().sum() + aligned["rh_pct"].notna().sum() > 0)
        if False
        else int(aligned["t_db_C"].notna().sum()),
        "n_usable_hours": int(usable.sum()),
        "missing_fraction_usable": float(1 - usable.mean()),
        "gap_before_first_obs_hours": None,
        "duplicates_in_hourly_index": 0,
        "dst_local_hours": int(len(dst)),
        "large_gap_not_filled": True,
        "kfqd_2012_starts": "2012-06-21T17:55:00Z in ISD/global-hourly and ISD-lite. Jan 1–Jun 21 17:00 UTC are MISSING. Not filled.",
        "secondary_stations_downloaded_not_imputed": ["KEHO 72027763843 Shelby", "KGSP 72312003870"],
        "impossible_T_RH_dewpoint_nullified": True,
        "pressure": "station pressure from SLP or altimeter via hypsometric reduction; missing SLP common at AWOS",
    }


def main() -> None:
    files = sorted(RAW_WEATHER.glob(f"{STATION_PRIMARY}_2012.csv"))
    if not files:
        raise SystemExit("Missing KFQD 2012 global-hourly CSV")
    raw = pd.concat([read_global_hourly(p) for p in files], ignore_index=True)
    h = hourlyize(raw)
    idx = pd.date_range("2012-01-01", "2012-12-31 23:00:00", freq="h", tz="UTC")
    full = h.set_index("timestamp_utc").reindex(idx)
    full.index.name = "timestamp_utc"
    full = full.reset_index()
    full["station"] = STATION_CALL
    full["station_id"] = STATION_PRIMARY
    full["source_station"] = f"{STATION_NAME} ({STATION_CALL})"
    full["timestamp_local"] = full["timestamp_utc"].dt.tz_convert(TZ)
    qa = qa_report(h)
    first = h.dropna(subset=["t_db_C"])["timestamp_utc"].min()
    qa["gap_before_first_obs_hours"] = int((first - idx[0]) / pd.Timedelta(hours=1)) if pd.notna(first) else None
    qa["usable_hours_2012_04_01_to_09_30"] = int(
        full.loc[
            (full["timestamp_utc"] >= "2012-04-01") & (full["timestamp_utc"] < "2012-10-01"),
            ["t_db_C", "rh_pct", "pressure_Pa"],
        ]
        .notna()
        .all(axis=1)
        .sum()
    )
    qa["usable_hours_JJA"] = int(
        full.loc[
            (full["timestamp_utc"] >= "2012-06-01") & (full["timestamp_utc"] < "2012-09-01"),
            ["t_db_C", "rh_pct", "pressure_Pa"],
        ]
        .notna()
        .all(axis=1)
        .sum()
    )
    out = DATA_PROCESSED / "forest_city_weather_2012_hourly.parquet"
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    full.to_parquet(out, index=False)
    qa["parquet_sha256"] = sha256_file(out)
    write_json(OUTPUTS / "weather" / "FOREST_CITY_2012_WEATHER_QA.json", qa)
    print(json.dumps({k: qa[k] for k in ("n_usable_hours", "gap_before_first_obs_hours", "usable_hours_JJA")}, indent=2))


if __name__ == "__main__":
    main()
