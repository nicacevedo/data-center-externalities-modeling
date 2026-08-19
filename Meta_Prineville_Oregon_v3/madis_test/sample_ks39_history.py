from __future__ import annotations

import gzip
import io
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import xarray as xr


# ============================================================
# Configuration
# ============================================================

START_YEAR = 2011
END_YEAR = 2024

SAMPLES_PER_MONTH = 4
RANDOM_SEED = 15087

STATION = "KS39"

BASE_URL = (
    "https://madis-data.ncep.noaa.gov/"
    "madisPublic1/data/archive"
)

OUT_DIR = Path("outputs")
CACHE_DIR = Path("raw/history_sample")

OUT_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

session = requests.Session()
session.headers.update(
    {
        "User-Agent":
            "MIT-Prineville-Research/1.0"
    }
)


# ============================================================
# Helpers
# ============================================================

def clean_string(x):
    if isinstance(x, bytes):
        return (
            x.decode("ascii", errors="ignore")
            .strip("\x00 ")
            .upper()
        )

    return str(x).strip("\x00 ").upper()


def madis_url(ts: datetime) -> str:
    return (
        f"{BASE_URL}/"
        f"{ts:%Y/%m/%d}/"
        f"point/metar/netcdf/"
        f"{ts:%Y%m%d_%H}00.gz"
    )


def cache_path(ts: datetime) -> Path:
    return CACHE_DIR / f"{ts:%Y%m%d_%H}00.gz"


def download_file(ts: datetime):
    url = madis_url(ts)
    path = cache_path(ts)

    # Reuse already-downloaded files
    if path.exists() and path.stat().st_size > 0:
        return path, 200, "cached"

    try:
        r = session.get(
            url,
            timeout=60,
        )

        status = r.status_code

        if status == 200:
            path.write_bytes(r.content)
            return path, status, "downloaded"

        return None, status, "http_error"

    except requests.RequestException as exc:
        return None, None, f"request_error:{exc}"


def inspect_file(path: Path):
    with gzip.open(path, "rb") as f:
        raw = f.read()

    with xr.open_dataset(
        io.BytesIO(raw),
        engine="scipy",
    ) as ds:

        stations = np.array(
            [
                clean_string(x)
                for x in ds["stationName"].values
            ],
            dtype=object,
        )

        idx = np.where(stations == STATION)[0]

        result = {
            "ks39_present": len(idx) > 0,
            "ks39_records": len(idx),
            "temperature_valid": 0,
            "dewpoint_valid": 0,
            "pressure_valid": 0,
            "lat": np.nan,
            "lon": np.nan,
        }

        if len(idx) == 0:
            return result

        if "temperature" in ds:
            vals = ds["temperature"].values[idx]
            result["temperature_valid"] = int(
                np.isfinite(vals).sum()
            )

        if "dewpoint" in ds:
            vals = ds["dewpoint"].values[idx]
            result["dewpoint_valid"] = int(
                np.isfinite(vals).sum()
            )

        if "seaLevelPress" in ds:
            vals = ds["seaLevelPress"].values[idx]
            result["pressure_valid"] = int(
                np.isfinite(vals).sum()
            )

        if "latitude" in ds:
            result["lat"] = float(
                ds["latitude"].values[idx[0]]
            )

        if "longitude" in ds:
            result["lon"] = float(
                ds["longitude"].values[idx[0]]
            )

        return result


# ============================================================
# Build stratified sample
# ============================================================

rng = random.Random(RANDOM_SEED)

sample = []

for year in range(START_YEAR, END_YEAR + 1):
    for month in range(1, 13):

        # Avoid month-length complications:
        # sample day 1–28 and any UTC hour.
        candidates = [
            datetime(
                year,
                month,
                day,
                hour,
                tzinfo=timezone.utc,
            )
            for day in range(1, 29)
            for hour in range(24)
        ]

        selected = rng.sample(
            candidates,
            SAMPLES_PER_MONTH,
        )

        sample.extend(selected)

sample = sorted(sample)

print(f"Sampled timestamps: {len(sample)}")


# ============================================================
# Query archive
# ============================================================

rows = []

for n, ts in enumerate(sample, 1):

    print(
        f"[{n:4d}/{len(sample)}] "
        f"{ts:%Y-%m-%d %H}:00 UTC",
        flush=True,
    )

    path, status, fetch_status = download_file(ts)

    row = {
        "timestamp_utc": ts.isoformat(),
        "year": ts.year,
        "month": ts.month,
        "day": ts.day,
        "hour": ts.hour,
        "url": madis_url(ts),
        "http_status": status,
        "fetch_status": fetch_status,
        "madis_file_available": status == 200,
        "ks39_present": False,
        "ks39_records": 0,
        "temperature_valid": 0,
        "dewpoint_valid": 0,
        "pressure_valid": 0,
        "lat": np.nan,
        "lon": np.nan,
    }

    if path is not None:
        try:
            result = inspect_file(path)
            row.update(result)

        except Exception as exc:
            row["fetch_status"] = (
                f"parse_error:{type(exc).__name__}:{exc}"
            )

    rows.append(row)

    # Be polite to NOAA
    time.sleep(0.15)


# ============================================================
# Save raw audit
# ============================================================

df = pd.DataFrame(rows)

raw_out = OUT_DIR / "ks39_history_sample.csv"
df.to_csv(raw_out, index=False)


# ============================================================
# Summaries
# ============================================================

usable = df[df["madis_file_available"]].copy()

annual = (
    usable
    .groupby("year")
    .agg(
        sampled_hours=("timestamp_utc", "size"),
        ks39_hours=("ks39_present", "sum"),
        ks39_records=("ks39_records", "sum"),
        temp_records=("temperature_valid", "sum"),
        dewpoint_records=("dewpoint_valid", "sum"),
    )
    .reset_index()
)

annual["ks39_presence_pct"] = (
    100
    * annual["ks39_hours"]
    / annual["sampled_hours"]
)

annual_out = OUT_DIR / "ks39_history_sample_annual.csv"
annual.to_csv(annual_out, index=False)


monthly = (
    usable
    .groupby(["year", "month"])
    .agg(
        sampled_hours=("timestamp_utc", "size"),
        ks39_hours=("ks39_present", "sum"),
        ks39_records=("ks39_records", "sum"),
        temp_records=("temperature_valid", "sum"),
        dewpoint_records=("dewpoint_valid", "sum"),
    )
    .reset_index()
)

monthly["ks39_presence_pct"] = (
    100
    * monthly["ks39_hours"]
    / monthly["sampled_hours"]
)

monthly_out = OUT_DIR / "ks39_history_sample_monthly.csv"
monthly.to_csv(monthly_out, index=False)


# ============================================================
# Console summary
# ============================================================

print("\n================ ANNUAL SUMMARY ================\n")

print(
    annual[
        [
            "year",
            "sampled_hours",
            "ks39_hours",
            "ks39_presence_pct",
            "ks39_records",
            "temp_records",
            "dewpoint_records",
        ]
    ].to_string(index=False)
)

print("\nArchive files unavailable:")
print((~df["madis_file_available"]).sum())

print("\nResults written to:")
print(raw_out)
print(annual_out)
print(monthly_out)