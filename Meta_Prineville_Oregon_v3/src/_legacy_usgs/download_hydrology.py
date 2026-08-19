import csv
import time
from pathlib import Path

import requests

BASE_URL = "https://api.water.usgs.gov/nwaa-data/data"

MODEL = "iwa-assessment-outputs-conus-2025"
VARIABLE = "all"

START = "2009-10"
END = "2020-09"

SCOPE_FIELD = "scope_local"

OUTDIR = Path("usgs_nwaa") / "hydrology" / SCOPE_FIELD
OUTDIR.mkdir(parents=True, exist_ok=True)

with open("meta_prineville_study_hucs.csv", newline="") as f:
    rows = list(csv.DictReader(f))

selected = [
    r for r in rows
    if r[SCOPE_FIELD] == "1"
]

print(f"Downloading hydrology for {len(selected)} HUC12s")
print()

for i, row in enumerate(selected, start=1):
    huc = row["huc12"]
    name = row["name"]

    outfile = OUTDIR / f"hydrology_{huc}.csv"

    params = {
        "model": MODEL,
        "variable": VARIABLE,
        "location": f"huc12:{huc}",
        "startdate": START,
        "enddate": END,
        "timeres": "monthly",
        "format": "csv",
    }

    print(f"[{i}/{len(selected)}] {huc} | {name}")

    r = requests.get(
        BASE_URL,
        params=params,
        timeout=120,
    )

    print("  HTTP:", r.status_code)

    if not r.ok:
        print("  URL:", r.url)
        print("  RESPONSE:", r.text[:2000])
        r.raise_for_status()

    outfile.write_bytes(r.content)

    print("  Saved:", outfile)

    time.sleep(0.2)

print("\nDone.")
