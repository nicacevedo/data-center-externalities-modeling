import csv
import time
from pathlib import Path

import requests


BASE_URL = "https://api.water.usgs.gov/nwaa-data/data"

MODEL = "wu-public-supply-cu"
VARIABLE = "pscutot"

START = "2009-01"
END = "2020-12"

SCOPE_FIELD = "scope_local"

OUTDIR = Path(
    "usgs_nwaa"
) / VARIABLE / SCOPE_FIELD

OUTDIR.mkdir(
    parents=True,
    exist_ok=True,
)


# ------------------------------------------------------------
# Read study geography
# ------------------------------------------------------------

with open(
    "meta_prineville_study_hucs.csv",
    newline=""
) as f:

    rows = list(
        csv.DictReader(f)
    )


selected = [
    r
    for r in rows
    if r[SCOPE_FIELD] == "1"
]


print(
    f"Downloading {len(selected)} HUC12s"
)
print()


# ------------------------------------------------------------
# Download each HUC12 separately
# ------------------------------------------------------------

for i, row in enumerate(
    selected,
    start=1
):

    huc = row["huc12"]
    name = row["name"]

    outfile = (
        OUTDIR /
        f"{VARIABLE}_{huc}.csv"
    )

    print(
        f"[{i}/{len(selected)}] "
        f"{huc} | {name}"
    )


    params = {
        "model": MODEL,
        "variable": VARIABLE,

        # Current USGS documented parameter names
        "timeRes": "monthly",
        "startDate": START,
        "endDate": END,

        "location": f"huc12:{huc}",
        "format": "csv",
    }


    r = requests.get(
        BASE_URL,
        params=params,
        timeout=120,
    )


    print(
        "  HTTP:",
        r.status_code
    )

    if not r.ok:
        print(
            "  URL:",
            r.url
        )
        print(
            "  RESPONSE:",
            r.text[:1000]
        )
        r.raise_for_status()


    outfile.write_bytes(
        r.content
    )

    print(
        "  Saved:",
        outfile
    )

    time.sleep(0.15)


print("\nDone.")
