from __future__ import annotations

import gzip
import os
import tempfile
import time
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import xarray as xr


# ============================================================
# Configuration
# ============================================================

STATION = "KS39"

# Transition window suggested by broad audit:
# July 2015: 0%
# August 2015: partial
# September 2015 onward: 100% in sample
START = datetime(2015, 7, 1, 0, 0, tzinfo=timezone.utc)
END = datetime(2015, 10, 1, 0, 0, tzinfo=timezone.utc)

# Four observations per UTC day for transition discovery.
SAMPLE_HOURS = [0, 6, 12, 18]

BASE_URL = (
    "https://madis-data.ncep.noaa.gov/"
    "madisPublic1/data/archive"
)

CACHE_DIR = Path("raw/ks39_transition_2015")
OUT_DIR = Path("outputs")

CACHE_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)

session = requests.Session()
session.headers.update(
    {
        "User-Agent": (
            "MIT-Prineville-Research/1.0 "
            "historical-weather-audit"
        )
    }
)

# These warnings concern unrelated six-hour min/max temperature
# variables with multiple documented fill values. They do not affect
# temperature/dewpoint extraction here.
warnings.filterwarnings(
    "ignore",
    message="variable 'minTemp6Hour' has multiple fill values",
)

warnings.filterwarnings(
    "ignore",
    message="variable 'maxTemp6Hour' has multiple fill values",
)


# ============================================================
# Utilities
# ============================================================

def clean_string(x) -> str:
    """Normalize MADIS byte/string fields."""

    if isinstance(x, bytes):
        return (
            x.decode("ascii", errors="ignore")
            .strip("\x00 ")
            .upper()
        )

    return str(x).strip("\x00 ").upper()


def madis_url(ts: datetime) -> str:
    """Construct public MADIS historical METAR URL."""

    return (
        f"{BASE_URL}/"
        f"{ts:%Y/%m/%d}/"
        f"point/metar/netcdf/"
        f"{ts:%Y%m%d_%H}00.gz"
    )


def cache_path(ts: datetime) -> Path:
    return CACHE_DIR / f"{ts:%Y%m%d_%H}00.gz"


# ============================================================
# Download
# ============================================================

def download_file(ts: datetime):
    """
    Download one MADIS hourly file.

    Returns
    -------
    path
        Local cached path, or None.
    http_status
        HTTP status if available.
    fetch_status
        cached / downloaded / http_error / request_error.
    """

    url = madis_url(ts)
    path = cache_path(ts)

    # Reuse previous successful downloads.
    if path.exists() and path.stat().st_size > 0:
        return path, 200, "cached"

    try:
        response = session.get(
            url,
            timeout=60,
        )

        status = response.status_code

        if status == 200:
            path.write_bytes(response.content)
            return path, status, "downloaded"

        return None, status, "http_error"

    except requests.RequestException as exc:
        return (
            None,
            None,
            f"request_error:{type(exc).__name__}:{exc}",
        )


# ============================================================
# MADIS extraction
# ============================================================

def inspect_file(path: Path) -> dict:
    """
    Inspect one compressed MADIS netCDF file and extract KS39 status.

    Important:
    multiple KS39 records within an hourly MADIS file are retained
    as separate reports. They are NOT treated as duplicates here.
    """

    with gzip.open(path, "rb") as f_in:
        with tempfile.NamedTemporaryFile(
            suffix=".nc"
        ) as tmp:

            tmp.write(f_in.read())
            tmp.flush()

            with xr.open_dataset(
                tmp.name,
                engine="netcdf4",
            ) as ds:

                stations = np.array(
                    [
                        clean_string(x)
                        for x in ds["stationName"].values
                    ],
                    dtype=object,
                )

                idx = np.where(
                    stations == STATION
                )[0]

                result = {
                    "ks39_present": len(idx) > 0,
                    "ks39_records": int(len(idx)),

                    "temperature_valid": 0,
                    "dewpoint_valid": 0,
                    "pressure_valid": 0,

                    "lat": np.nan,
                    "lon": np.nan,
                    "elevation": np.nan,

                    "first_timeObs": np.nan,
                    "last_timeObs": np.nan,
                }

                if len(idx) == 0:
                    return result

                # ------------------------------------------------
                # Meteorology
                # ------------------------------------------------

                if "temperature" in ds:
                    values = ds["temperature"].values[idx]

                    result["temperature_valid"] = int(
                        np.isfinite(values).sum()
                    )

                if "dewpoint" in ds:
                    values = ds["dewpoint"].values[idx]

                    result["dewpoint_valid"] = int(
                        np.isfinite(values).sum()
                    )

                # Prefer sea-level pressure for simple availability
                # accounting here.
                if "seaLevelPress" in ds:
                    values = ds["seaLevelPress"].values[idx]

                    result["pressure_valid"] = int(
                        np.isfinite(values).sum()
                    )

                # ------------------------------------------------
                # Station metadata
                # ------------------------------------------------

                if "latitude" in ds:
                    result["lat"] = float(
                        ds["latitude"].values[idx[0]]
                    )

                if "longitude" in ds:
                    result["lon"] = float(
                        ds["longitude"].values[idx[0]]
                    )

                if "elevation" in ds:
                    result["elevation"] = float(
                        ds["elevation"].values[idx[0]]
                    )

                # ------------------------------------------------
                # Observation-time range within this MADIS file
                # ------------------------------------------------

                if "timeObs" in ds:
                    values = ds["timeObs"].values[idx]

                    finite = values[
                        np.isfinite(values)
                    ]

                    if len(finite):
                        result["first_timeObs"] = float(
                            np.min(finite)
                        )

                        result["last_timeObs"] = float(
                            np.max(finite)
                        )

                return result


# ============================================================
# Build deterministic transition sample
# ============================================================

sample = []

day = START

while day < END:

    for hour in SAMPLE_HOURS:
        sample.append(
            day.replace(
                hour=hour,
                minute=0,
                second=0,
                microsecond=0,
            )
        )

    day += timedelta(days=1)

sample = sorted(sample)

print(
    f"Transition sample: {len(sample)} timestamps"
)

print(
    f"Window: {START.isoformat()} "
    f"through {END.isoformat()}"
)

print(
    f"UTC hours per day: {SAMPLE_HOURS}"
)


# ============================================================
# Query MADIS
# ============================================================

rows = []

for n, ts in enumerate(sample, 1):

    print(
        f"[{n:3d}/{len(sample)}] "
        f"{ts:%Y-%m-%d %H}:00 UTC",
        flush=True,
    )

    path, status, fetch_status = download_file(ts)

    row = {
        "timestamp_utc": ts.isoformat(),

        "date_utc": ts.date().isoformat(),

        "year": ts.year,
        "month": ts.month,
        "day": ts.day,
        "hour": ts.hour,

        "url": madis_url(ts),

        "http_status": status,
        "fetch_status": fetch_status,

        "madis_file_available": (
            status == 200
        ),

        "ks39_present": False,
        "ks39_records": 0,

        "temperature_valid": 0,
        "dewpoint_valid": 0,
        "pressure_valid": 0,

        "lat": np.nan,
        "lon": np.nan,
        "elevation": np.nan,

        "first_timeObs": np.nan,
        "last_timeObs": np.nan,
    }

    if path is not None:

        try:
            result = inspect_file(path)
            row.update(result)

        except Exception as exc:

            row["fetch_status"] = (
                "parse_error:"
                f"{type(exc).__name__}:"
                f"{exc}"
            )

    rows.append(row)

    # Small delay so we are gentle with NOAA.
    time.sleep(0.15)


# ============================================================
# Raw timestamp-level audit
# ============================================================

df = pd.DataFrame(rows)

raw_out = (
    OUT_DIR
    / "ks39_transition_2015_sample.csv"
)

df.to_csv(
    raw_out,
    index=False,
)


# ============================================================
# IMPORTANT:
#
# Missing MADIS archive file != KS39 absent.
#
# Presence percentages below use only successfully retrieved
# MADIS files in the denominator.
# ============================================================

usable = df[
    df["madis_file_available"]
].copy()


# ============================================================
# Daily summary
# ============================================================

daily = (
    usable
    .groupby("date_utc")
    .agg(
        sampled_hours=(
            "timestamp_utc",
            "size",
        ),

        ks39_hours=(
            "ks39_present",
            "sum",
        ),

        ks39_records=(
            "ks39_records",
            "sum",
        ),

        temp_records=(
            "temperature_valid",
            "sum",
        ),

        dewpoint_records=(
            "dewpoint_valid",
            "sum",
        ),

        pressure_records=(
            "pressure_valid",
            "sum",
        ),
    )
    .reset_index()
)

daily["ks39_presence_pct"] = (
    100
    * daily["ks39_hours"]
    / daily["sampled_hours"]
)

daily_out = (
    OUT_DIR
    / "ks39_transition_2015_daily.csv"
)

daily.to_csv(
    daily_out,
    index=False,
)


# ============================================================
# Monthly summary
# ============================================================

monthly = (
    usable
    .groupby(
        ["year", "month"]
    )
    .agg(
        sampled_hours=(
            "timestamp_utc",
            "size",
        ),

        ks39_hours=(
            "ks39_present",
            "sum",
        ),

        ks39_records=(
            "ks39_records",
            "sum",
        ),

        temp_records=(
            "temperature_valid",
            "sum",
        ),

        dewpoint_records=(
            "dewpoint_valid",
            "sum",
        ),

        pressure_records=(
            "pressure_valid",
            "sum",
        ),
    )
    .reset_index()
)

monthly["ks39_presence_pct"] = (
    100
    * monthly["ks39_hours"]
    / monthly["sampled_hours"]
)

monthly_out = (
    OUT_DIR
    / "ks39_transition_2015_monthly.csv"
)

monthly.to_csv(
    monthly_out,
    index=False,
)


# ============================================================
# Transition diagnostics
# ============================================================

present = usable[
    usable["ks39_present"]
].copy()

absent = usable[
    ~usable["ks39_present"]
].copy()


print(
    "\n"
    "================ MONTHLY SUMMARY ================"
    "\n"
)

print(
    monthly.to_string(
        index=False
    )
)


print(
    "\n"
    "================ DAILY SUMMARY =================="
    "\n"
)

print(
    daily.to_string(
        index=False
    )
)


print(
    "\n"
    "================ TRANSITION ====================="
    "\n"
)

if len(present):

    first_sampled_presence = (
        present
        .sort_values("timestamp_utc")
        .iloc[0]
    )

    print(
        "First sampled KS39 detection:"
    )

    print(
        first_sampled_presence[
            "timestamp_utc"
        ]
    )

    print(
        "\nRecords in that MADIS file:",
        int(
            first_sampled_presence[
                "ks39_records"
            ]
        ),
    )

else:

    print(
        "KS39 was never detected "
        "in the transition sample."
    )


if len(absent):

    last_sampled_absence = (
        absent
        .sort_values("timestamp_utc")
        .iloc[-1]
    )

    print(
        "\nLast sampled KS39 absence:"
    )

    print(
        last_sampled_absence[
            "timestamp_utc"
        ]
    )


# ============================================================
# First sampled fully-covered day
# ============================================================

full_days = daily[
    (
        daily["sampled_hours"]
        == len(SAMPLE_HOURS)
    )
    &
    (
        daily["ks39_hours"]
        == len(SAMPLE_HOURS)
    )
]

if len(full_days):

    print(
        "\nFirst sampled day with "
        "KS39 present at all four "
        "sampled UTC hours:"
    )

    print(
        full_days.iloc[0][
            "date_utc"
        ]
    )


# ============================================================
# Find candidate sustained transition
#
# Here we simply find the first position after which every
# remaining sampled timestamp has KS39.
#
# This is a SAMPLE-based transition estimate, NOT necessarily
# the exact historical first observation.
# ============================================================

ordered = usable.sort_values(
    "timestamp_utc"
).reset_index(drop=True)

candidate_sustained = None

for i in range(len(ordered)):

    remaining = ordered.iloc[i:]

    if remaining["ks39_present"].all():
        candidate_sustained = ordered.iloc[i]
        break


if candidate_sustained is not None:

    print(
        "\nFirst sampled timestamp after "
        "which every remaining sampled "
        "timestamp contains KS39:"
    )

    print(
        candidate_sustained[
            "timestamp_utc"
        ]
    )

else:

    print(
        "\nNo completely sustained transition "
        "was found in the sampled timestamps."
    )


# ============================================================
# Completeness conditional on KS39 being present
# ============================================================

total_records = int(
    present["ks39_records"].sum()
)

total_temp = int(
    present["temperature_valid"].sum()
)

total_dew = int(
    present["dewpoint_valid"].sum()
)

total_pressure = int(
    present["pressure_valid"].sum()
)


print(
    "\n"
    "================ VARIABLE COMPLETENESS =========="
    "\n"
)

print(
    f"KS39 records:        {total_records}"
)

print(
    f"Valid temperature:   {total_temp}"
)

print(
    f"Valid dewpoint:      {total_dew}"
)

print(
    f"Valid pressure:      {total_pressure}"
)

if total_records > 0:

    print(
        "Temperature completeness: "
        f"{100 * total_temp / total_records:.2f}%"
    )

    print(
        "Dewpoint completeness:    "
        f"{100 * total_dew / total_records:.2f}%"
    )

    print(
        "Pressure completeness:    "
        f"{100 * total_pressure / total_records:.2f}%"
    )


# ============================================================
# Archive availability
# ============================================================

unavailable = int(
    (~df["madis_file_available"]).sum()
)


print(
    "\n"
    "================ ARCHIVE ========================"
    "\n"
)

print(
    f"Requested MADIS files: {len(df)}"
)

print(
    "Successfully available: "
    f"{int(df['madis_file_available'].sum())}"
)

print(
    f"Unavailable:             {unavailable}"
)


# ============================================================
# Output locations
# ============================================================

print(
    "\n"
    "================ OUTPUTS ========================"
    "\n"
)

print(raw_out)
print(daily_out)
print(monthly_out)