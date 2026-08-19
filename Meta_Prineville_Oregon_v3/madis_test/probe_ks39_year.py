import gzip
import os
import tempfile
import sys

import numpy as np
import xarray as xr

RAW_DIR = sys.argv[1]

def clean_string(x):
    if isinstance(x, bytes):
        return x.decode(
            "ascii", errors="ignore"
        ).strip("\x00 ").upper()
    return str(x).strip("\x00 ").upper()

n_files = 0
n_files_with_ks39 = 0
n_records = 0
n_temp = 0
n_dew = 0

for fname in sorted(os.listdir(RAW_DIR)):
    if not fname.endswith(".gz"):
        continue

    n_files += 1
    path = os.path.join(RAW_DIR, fname)

    with gzip.open(path, "rb") as f:
        with tempfile.NamedTemporaryFile(suffix=".nc") as tmp:
            tmp.write(f.read())
            tmp.flush()

            ds = xr.open_dataset(
                tmp.name,
                engine="netcdf4"
            )

            station = np.array([
                clean_string(x)
                for x in ds["stationName"].values
            ])

            idx = np.where(station == "KS39")[0]

            if len(idx):
                n_files_with_ks39 += 1
                n_records += len(idx)

                temp = ds["temperature"].values[idx]
                dew = ds["dewpoint"].values[idx]

                n_temp += np.isfinite(temp).sum()
                n_dew += np.isfinite(dew).sum()

print(f"directory:            {RAW_DIR}")
print(f"files scanned:        {n_files}")
print(f"files with KS39:      {n_files_with_ks39}")
print(f"KS39 records:         {n_records}")
print(f"valid temperature:    {n_temp}")
print(f"valid dewpoint:       {n_dew}")