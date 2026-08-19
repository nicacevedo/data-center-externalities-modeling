import gzip
import os
import tempfile

import numpy as np
import xarray as xr


# RAW_DIR = "raw/20140710"
# RAW_DIR = "raw/20260425"
RAW_DIR = "raw/20240715"

TARGET_IDS = {"KS39", "S39"}
TARGET_LAT = 44.2870
TARGET_LON = -120.9038


def clean_string(x):
    if isinstance(x, bytes):
        return x.decode("ascii", errors="ignore").strip("\x00 ").upper()
    return str(x).strip("\x00 ").upper()


for fname in sorted(os.listdir(RAW_DIR)):
    if not fname.endswith(".gz"):
        continue

    gz_path = os.path.join(RAW_DIR, fname)

    with gzip.open(gz_path, "rb") as f_in:
        with tempfile.NamedTemporaryFile(suffix=".nc") as tmp:
            tmp.write(f_in.read())
            tmp.flush()

            ds = xr.open_dataset(tmp.name, engine="netcdf4")

            station = np.array(
                [clean_string(x) for x in ds["stationName"].values],
                dtype=object,
            )

            exact = np.array([x in TARGET_IDS for x in station])

            lat = ds["latitude"].values
            lon = ds["longitude"].values

            near = (
                np.isfinite(lat)
                & np.isfinite(lon)
                & (np.abs(lat - TARGET_LAT) <= 0.10)
                & (np.abs(lon - TARGET_LON) <= 0.10)
            )

            if exact.any() or near.any():
                print("\nFILE:", fname)

                for i in np.where(exact | near)[0]:
                    print(
                        "station=", station[i],
                        "lat=", float(lat[i]),
                        "lon=", float(lon[i]),
                        "temp=", ds["temperature"].values[i],
                        "dew=", ds["dewpoint"].values[i],
                    )