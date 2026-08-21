"""NCEI Global Hourly product for KBDN / Bend Municipal Airport.

Tertiary observational fallback only. Canonical weather still prefers KS39 then KRDM.
This script does not retune water or gray-box models.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from download_noaa_global_hourly import download
from prepare_weather import process_ncei_global_hourly

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "noaa"
OUT = ROOT / "data" / "processed" / "weather_kbdn_hourly.csv"
STATION = "72063800224"
ELEV_M = 1055.2
START_YEAR = 2011
END_YEAR = 2024


def ensure_raw(start: int = START_YEAR, end: int = END_YEAR) -> None:
    for year in range(start, end + 1):
        download(year, STATION, RAW, force=False)


def main() -> None:
    ensure_raw()
    process_ncei_global_hourly(
        station=STATION,
        elev_m=ELEV_M,
        raw_dir=RAW,
        out_path=OUT,
        station_label="KBDN / 72063800224",
        slp_method="kbdn_slp_derived",
        std_method="kbdn_standard_atmosphere_fallback",
        qc_freq_out=None,
    )
    print("KBDN tertiary product only. Canonical mix is written by prepare_weather_ks39.py.")


if __name__ == "__main__":
    main()
