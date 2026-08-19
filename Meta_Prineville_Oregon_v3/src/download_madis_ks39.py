"""Resumable NOAA MADIS METAR extractor for KS39 / Prineville Airport.

Downloads nationwide hourly MADIS METAR netCDF gz files from the public archive,
extracts only KS39 records, then discards the nationwide temporary file.

Public archive (confirmed working without credentials):
  https://madis-data.ncep.noaa.gov/madisPublic1/data/archive/YYYY/MM/DD/point/metar/netcdf/YYYYMMDD_HH00.gz

Station-specific MADIS Text/XML dump is not usable here without credentials
(sfcdump returned HTTP 404 unauthenticated). Do not wait for an account.

Default period: 2015-08-01 00:00 UTC through 2025-01-02 00:00 UTC inclusive.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import os
import sys
import tempfile
import threading
import time
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "noaa_madis_ks39"
SHARD_DIR = RAW_DIR / "shards"
MANIFEST = RAW_DIR / "download_manifest.csv"
REPORTS = RAW_DIR / "ks39_metar_reports.csv.gz"

BASE_URL = "https://madis-data.ncep.noaa.gov/madisPublic1/data/archive"
STATION = "KS39"
DEFAULT_START = "2015-08-01T00:00:00Z"
DEFAULT_END = "2025-01-02T00:00:00Z"
MAX_WORKERS = 4
USER_AGENT = "MIT-Prineville-Research/KS39-MADIS/1.0"

SCALAR_FIELDS = [
    "latitude",
    "longitude",
    "elevation",
    "timeObs",
    "timeNominal",
    "timeReceived",
    "correction",
    "temperature",
    "temperatureQCA",
    "temperatureQCR",
    "temperatureQCD",
    "temperatureICA",
    "temperatureICR",
    "dewpoint",
    "dewpointQCA",
    "dewpointQCR",
    "dewpointQCD",
    "dewpointICA",
    "dewpointICR",
    "seaLevelPress",
    "seaLevelPressQCA",
    "seaLevelPressQCR",
    "seaLevelPressQCD",
    "seaLevelPressICA",
    "seaLevelPressICR",
    "altimeter",
    "altimeterQCA",
    "altimeterQCR",
    "altimeterQCD",
    "altimeterICA",
    "altimeterICR",
    "windDir",
    "windDirQCA",
    "windDirQCR",
    "windDirQCD",
    "windDirICA",
    "windDirICR",
    "windSpeed",
    "windSpeedQCA",
    "windSpeedQCR",
    "windSpeedQCD",
    "windSpeedICA",
    "windSpeedICR",
    "windGust",
    "windGustQCA",
    "windGustQCR",
    "windGustQCD",
    "precip1Hour",
    "precip1HourQCA",
    "precip1HourQCR",
    "precip1HourQCD",
    "precip1HourICA",
    "precip1HourICR",
]

QCD_FIELDS = [
    "temperatureQCD",
    "dewpointQCD",
    "seaLevelPressQCD",
    "altimeterQCD",
    "windDirQCD",
    "windSpeedQCD",
    "windGustQCD",
    "precip1HourQCD",
]

CHAR_FIELDS = [
    "stationName",
    "reportType",
    "rawMETAR",
    "temperatureDD",
    "dewpointDD",
    "seaLevelPressDD",
    "altimeterDD",
    "windDirDD",
    "windSpeedDD",
    "windGustDD",
    "precip1HourDD",
]

MANIFEST_FIELDS = [
    "hour_utc",
    "source_url",
    "http_status",
    "status",
    "sha256",
    "n_bytes",
    "n_ks39",
    "elapsed_s",
    "completed_at",
    "error",
]


def hour_url(ts: pd.Timestamp) -> str:
    ts = pd.Timestamp(ts).tz_convert("UTC")
    return (
        f"{BASE_URL}/{ts:%Y/%m/%d}/point/metar/netcdf/{ts:%Y%m%d_%H}00.gz"
    )


def decode_char_rows(var, idx: np.ndarray, uppercase: bool = False) -> list[str]:
    if var is None or len(idx) == 0:
        return [""] * len(idx)
    sl = var[idx]
    out = []
    for row in sl:
        if np.ma.is_masked(row) and np.ndim(row) == 0:
            s = ""
        elif isinstance(row, (bytes, np.bytes_)):
            s = bytes(row).decode("ascii", "ignore")
        elif getattr(row, "dtype", None) is not None and row.dtype.kind in {"S", "V", "U"}:
            if getattr(row, "ndim", 0) == 0:
                s = bytes(row).decode("ascii", "ignore") if row.dtype.kind == "S" else str(row)
            else:
                parts = []
                for b in np.ma.filled(row, b"\x00"):
                    if isinstance(b, (bytes, np.bytes_)):
                        parts.append(bytes(b))
                    elif isinstance(b, (int, np.integer)):
                        parts.append(bytes([int(b) & 0xFF]))
                    else:
                        parts.append(b"")
                s = b"".join(parts).decode("ascii", "ignore")
        else:
            s = str(row)
        s = s.replace("\x00", "").strip()
        if uppercase:
            s = s.upper()
        out.append(s)
    return out


def _station_idx(st_var) -> np.ndarray:
    raw = st_var[:]
    if np.ma.isMaskedArray(raw):
        raw = np.ma.filled(raw, b"\x00")
    raw = np.ascontiguousarray(raw)
    if raw.ndim == 1:
        names = np.char.rstrip(raw.astype("S"))
        return np.flatnonzero(names == np.bytes_(STATION))
    n, w = raw.shape
    names = raw.view(f"S{w}").reshape(n)
    padded = np.bytes_(STATION).ljust(w, b"\x00")
    return np.flatnonzero(names == padded)


def _scalar_array(var, idx: np.ndarray) -> np.ndarray:
    out = np.full(len(idx), np.nan, dtype=float)
    if var is None or len(idx) == 0:
        return out
    vals = var[idx]
    if np.ma.isMaskedArray(vals):
        vals = np.ma.filled(vals, np.nan)
    vals = np.asarray(vals, dtype=float)
    bad = ~np.isfinite(vals) | np.isin(vals, (-9999.0, -2147483647.0)) | (np.abs(vals) > 1e30)
    vals = vals.astype(float)
    vals[bad] = np.nan
    return vals


def _qcd_strings(var, idx: np.ndarray) -> list[str]:
    if var is None or len(idx) == 0:
        return [""] * len(idx)
    vals = var[idx]
    if np.ma.isMaskedArray(vals):
        vals = np.ma.filled(vals, np.nan)
    vals = np.asarray(vals, dtype=float)
    if vals.ndim == 1:
        return ["" if not np.isfinite(x) else f"{x:.6g}" for x in vals]
    out = []
    for row in vals:
        out.append("|".join("" if not np.isfinite(x) else f"{x:.6g}" for x in row))
    return out


def _time_iso_array(var, idx: np.ndarray) -> list[str]:
    if var is None or len(idx) == 0:
        return [""] * len(idx)
    import netCDF4

    units = getattr(var, "units", "seconds since 1970-01-01 00:00:00")
    try:
        raw = np.asarray(var[idx], dtype=float)
        times = netCDF4.num2date(raw, units)
    except Exception:
        try:
            raw = np.asarray(var[idx], dtype=float)
            return [
                pd.to_datetime(v, unit="s", utc=True).isoformat() if np.isfinite(v) and v > 1e8 else ""
                for v in raw
            ]
        except Exception:
            return [""] * len(idx)
    out = []
    for t in np.atleast_1d(times):
        try:
            out.append(pd.Timestamp(str(t), tz="UTC").isoformat())
        except Exception:
            out.append("")
    return out


def _open_netcdf(nc_bytes: bytes):
    import netCDF4

    try:
        return netCDF4.Dataset("inmemory.nc", memory=nc_bytes), None
    except Exception:
        tmp = tempfile.NamedTemporaryFile(
            suffix=".nc", dir="/dev/shm" if os.path.isdir("/dev/shm") else None, delete=False
        )
        tmp.write(nc_bytes)
        tmp.flush()
        tmp.close()
        return netCDF4.Dataset(tmp.name), tmp.name


def extract_ks39(gz_bytes: bytes) -> list[dict]:
    ds, tmp_name = _open_netcdf(gz_bytes)
    try:
        st_var = ds.variables.get("stationName")
        if st_var is None:
            return []
        idx = _station_idx(st_var)
        if len(idx) == 0:
            return []
        vars_ = ds.variables
        char_decoded = {}
        for name in CHAR_FIELDS:
            upper = name != "rawMETAR"
            char_decoded[name] = (
                decode_char_rows(vars_.get(name), idx, uppercase=upper)
                if name in vars_
                else [""] * len(idx)
            )
        scalars = {
            name: _scalar_array(vars_.get(name), idx)
            for name in SCALAR_FIELDS
            if name not in {"timeObs", "timeNominal", "timeReceived"} and name not in QCD_FIELDS
        }
        qcd = {name: _qcd_strings(vars_.get(name), idx) for name in QCD_FIELDS}
        t_obs = _time_iso_array(vars_.get("timeObs"), idx)
        t_nom = _time_iso_array(vars_.get("timeNominal"), idx)
        t_rcv = _time_iso_array(vars_.get("timeReceived"), idx)
        rows = []
        for j in range(len(idx)):
            rec = {
                "stationName": STATION,
                "reportType": char_decoded.get("reportType", [""] * len(idx))[j],
                "rawMETAR": char_decoded.get("rawMETAR", [""] * len(idx))[j],
                "temperatureDD": char_decoded.get("temperatureDD", [""] * len(idx))[j],
                "dewpointDD": char_decoded.get("dewpointDD", [""] * len(idx))[j],
                "seaLevelPressDD": char_decoded.get("seaLevelPressDD", [""] * len(idx))[j],
                "altimeterDD": char_decoded.get("altimeterDD", [""] * len(idx))[j],
                "windDirDD": char_decoded.get("windDirDD", [""] * len(idx))[j],
                "windSpeedDD": char_decoded.get("windSpeedDD", [""] * len(idx))[j],
                "windGustDD": char_decoded.get("windGustDD", [""] * len(idx))[j],
                "precip1HourDD": char_decoded.get("precip1HourDD", [""] * len(idx))[j],
                "timeObs": t_obs[j],
                "timeNominal": t_nom[j],
                "timeReceived": t_rcv[j],
            }
            for name, arr in scalars.items():
                rec[name] = "" if not np.isfinite(arr[j]) else float(arr[j])
            for name, arr in qcd.items():
                rec[name] = arr[j]
            rows.append(rec)
        return rows
    finally:
        ds.close()
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def load_manifest() -> dict[str, dict]:
    if not MANIFEST.exists():
        return {}
    df = pd.read_csv(MANIFEST, dtype=str).fillna("")
    out = {}
    for r in df.to_dict("records"):
        out[str(r["hour_utc"])] = r
    return out


def write_manifest(rows: dict[str, dict]) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST.with_suffix(".csv.tmp")
    ordered = [rows[k] for k in sorted(rows)]
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS, extrasaction="ignore")
        w.writeheader()
        for rec in ordered:
            w.writerow({k: rec.get(k, "") for k in MANIFEST_FIELDS})
    tmp.replace(MANIFEST)


def append_reports(records: list[dict], source_url: str, source_file: str) -> None:
    if not records:
        return
    SHARD_DIR.mkdir(parents=True, exist_ok=True)
    # shard by timeObs month if present, else timeNominal
    by_month: dict[str, list[dict]] = {}
    for rec in records:
        rec = dict(rec)
        rec["source_url"] = source_url
        rec["source_file"] = source_file
        ts = rec.get("timeObs") or rec.get("timeNominal") or ""
        month = ts[:7].replace("-", "") if len(ts) >= 7 else "unknown"
        by_month.setdefault(month, []).append(rec)
    fieldnames = [
        "source_file", "source_url", "stationName",
        "latitude", "longitude", "elevation",
        "timeObs", "timeNominal", "timeReceived", "reportType", "correction", "rawMETAR",
        "temperature", "temperatureDD", "temperatureQCA", "temperatureQCR", "temperatureQCD",
        "temperatureICA", "temperatureICR",
        "dewpoint", "dewpointDD", "dewpointQCA", "dewpointQCR", "dewpointQCD",
        "dewpointICA", "dewpointICR",
        "seaLevelPress", "seaLevelPressDD", "seaLevelPressQCA", "seaLevelPressQCR",
        "seaLevelPressQCD", "seaLevelPressICA", "seaLevelPressICR",
        "altimeter", "altimeterDD", "altimeterQCA", "altimeterQCR", "altimeterQCD",
        "altimeterICA", "altimeterICR",
        "windDir", "windDirDD", "windDirQCA", "windDirQCR", "windDirQCD",
        "windDirICA", "windDirICR",
        "windSpeed", "windSpeedDD", "windSpeedQCA", "windSpeedQCR", "windSpeedQCD",
        "windSpeedICA", "windSpeedICR",
        "windGust", "windGustDD", "windGustQCA", "windGustQCR", "windGustQCD",
        "precip1Hour", "precip1HourDD", "precip1HourQCA", "precip1HourQCR", "precip1HourQCD",
        "precip1HourICA", "precip1HourICR",
    ]
    for month, recs in by_month.items():
        path = SHARD_DIR / f"ks39_{month}.csv"
        new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            if new:
                w.writeheader()
            for rec in recs:
                w.writerow({k: rec.get(k, "") for k in fieldnames})


_tls = threading.local()


def session() -> requests.Session:
    s = getattr(_tls, "session", None)
    if s is None:
        s = requests.Session()
        s.headers["User-Agent"] = USER_AGENT
        _tls.session = s
    return s


def fetch_hour(ts: pd.Timestamp, timeout: int = 90) -> tuple[int, bytes, str]:
    url = hour_url(ts)
    last_err = ""
    delay = 2.0
    for attempt in range(5):
        try:
            r = session().get(url, timeout=timeout)
            if r.status_code == 404:
                return 404, b"", url
            if r.status_code >= 500:
                last_err = f"HTTP {r.status_code}"
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            r.raise_for_status()
            return r.status_code, r.content, url
        except (requests.RequestException, OSError) as e:
            last_err = str(e)
            time.sleep(delay)
            delay = min(delay * 2, 60)
    raise RuntimeError(last_err or "download failed")


def local_cache_path(ts: pd.Timestamp) -> Path | None:
    """Reuse already-downloaded discovery files when present."""
    utc = pd.Timestamp(ts).tz_convert("UTC")
    name = f"{utc:%Y%m%d_%H}00.gz"
    roots = [
        ROOT / "madis_test" / "raw" / f"{utc:%Y%m%d}",
        ROOT / "madis_test" / "raw",
        ROOT / "madis_test" / "raw" / "history_sample",
        ROOT / "madis_test" / "raw" / "ks39_transition_2015",
    ]
    for root in roots:
        p = root / name
        if p.is_file():
            return p
    return None


def hour_key(ts: pd.Timestamp) -> str:
    return pd.Timestamp(ts).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def hours_to_fetch(hours, done: dict, force_retry_errors: bool = False) -> list:
    """Skip completed ok/not_found hours. Retry errors unless they should stay skipped.

    Default: retry `error` rows. `force_retry_errors` is accepted for CLI symmetry;
    errors are always retried so a transient NOAA failure is not frozen as missing KS39.
    """
    pending = []
    for ts in hours:
        prev = done.get(hour_key(ts), {})
        if prev.get("status") in {"ok", "not_found"}:
            continue
        pending.append(ts)
    return pending


def process_hour(ts: pd.Timestamp) -> dict:
    t0 = time.time()
    hour_utc_key = pd.Timestamp(ts).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    url = hour_url(ts)
    local = local_cache_path(ts)
    try:
        if local is not None:
            gz = local.read_bytes()
            status_code = 200
            url = f"file://{local.as_posix()}"
        else:
            status_code, gz, url = fetch_hour(ts)
        if status_code == 404:
            return {
                "hour_utc": hour_utc_key,
                "source_url": url,
                "http_status": 404,
                "status": "not_found",
                "sha256": "",
                "n_bytes": 0,
                "n_ks39": 0,
                "elapsed_s": round(time.time() - t0, 3),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "error": "archive file unavailable",
                "_records": [],
            }
        sha = hashlib.sha256(gz).hexdigest()
        # gzip payload is the netCDF; some files are already gzip-compressed netcdf
        try:
            unzipped = gzip.decompress(gz)
        except OSError:
            unzipped = gz
        records = extract_ks39(unzipped)
        return {
            "hour_utc": hour_utc_key,
            "source_url": url,
            "http_status": status_code,
            "status": "ok",
            "sha256": sha,
            "n_bytes": len(gz),
            "n_ks39": len(records),
            "elapsed_s": round(time.time() - t0, 3),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "error": "",
            "_records": records,
        }
    except Exception as e:
        return {
            "hour_utc": hour_utc_key,
            "source_url": url,
            "http_status": "",
            "status": "error",
            "sha256": "",
            "n_bytes": 0,
            "n_ks39": 0,
            "elapsed_s": round(time.time() - t0, 3),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "error": str(e)[:500],
            "_records": [],
        }


def export_combined_reports() -> Path:
    files = sorted(SHARD_DIR.glob("ks39_*.csv"))
    if not files:
        raise FileNotFoundError(f"No KS39 shards in {SHARD_DIR}")
    parts = [pd.read_csv(p, low_memory=False) for p in files]
    df = pd.concat(parts, ignore_index=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(REPORTS, index=False, compression="gzip")
    return REPORTS


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEFAULT_END)
    ap.add_argument("--workers", type=int, default=MAX_WORKERS)
    ap.add_argument("--smoke", action="store_true", help="Four known days only")
    ap.add_argument("--export-only", action="store_true")
    ap.add_argument("--force-retry-errors", action="store_true")
    args = ap.parse_args()
    args.workers = min(max(args.workers, 1), MAX_WORKERS)

    if args.export_only:
        path = export_combined_reports()
        print(f"Wrote {path}")
        return

    if args.smoke:
        days = ["2015-08-12", "2015-09-15", "2019-07-15", "2024-07-15"]
        hours = pd.DatetimeIndex([])
        for d in days:
            hours = hours.append(pd.date_range(f"{d}T00:00:00Z", f"{d}T23:00:00Z", freq="h", tz="UTC"))
    else:
        hours = pd.date_range(args.start, args.end, freq="h", tz="UTC")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    SHARD_DIR.mkdir(parents=True, exist_ok=True)
    done = load_manifest()
    pending = hours_to_fetch(hours, done, force_retry_errors=args.force_retry_errors)

    print(
        f"KS39 MADIS extract: {len(hours)} hours in window, "
        f"{len(done)} in manifest, {len(pending)} to fetch, workers={args.workers}"
    )
    if not pending:
        print("Nothing to fetch.")
        return

    # netCDF4/HDF5 is not thread-safe. Use processes so each worker has its own HDF5 state.
    # Submit in batches so we do not pickle ~80k futures at once.
    n_ok = n_miss = n_err = n_rep = 0
    completed_since_flush = 0
    ctx = mp.get_context("spawn")
    batch_size = 400
    k = 0
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=ctx) as ex:
        for i0 in range(0, len(pending), batch_size):
            batch = pending[i0 : i0 + batch_size]
            futs = [ex.submit(process_hour, ts) for ts in batch]
            for fut in as_completed(futs):
                rec = fut.result()
                records = rec.pop("_records", [])
                done[rec["hour_utc"]] = rec
                append_reports(records, rec["source_url"], rec["hour_utc"].replace(":", "") + ".gz")
                n_rep += len(records)
                if rec["status"] == "ok":
                    n_ok += 1
                elif rec["status"] == "not_found":
                    n_miss += 1
                else:
                    n_err += 1
                completed_since_flush += 1
                k += 1
                if completed_since_flush >= 50 or k == len(pending):
                    write_manifest(done)
                    completed_since_flush = 0
                if k % 100 == 0 or k == len(pending):
                    print(
                        f"  {k}/{len(pending)} this run  ok={n_ok} not_found={n_miss} "
                        f"error={n_err} reports={n_rep}",
                        flush=True,
                    )

    write_manifest(done)
    print(f"Manifest {MANIFEST}: {len(done)} hours. Reports appended under {SHARD_DIR}")


if __name__ == "__main__":
    main()
