import csv
import sys
import time
from pathlib import Path

import requests


BASE_URL = "https://api.water.usgs.gov/nwaa-data/data"

if len(sys.argv) != 2:
    raise SystemExit(
        "Usage: python download_scope_water.py "
        "[scope_local|scope_hydro_near|same_site_huc10|same_site_huc8]"
    )

SCOPE_FIELD = sys.argv[1]

VALID_SCOPES = {
    "scope_local",
    "scope_hydro_near",
    "same_site_huc10",
    "same_site_huc8",
}

if SCOPE_FIELD not in VALID_SCOPES:
    raise SystemExit(
        f"Invalid scope: {SCOPE_FIELD}"
    )


# ============================================================
# READ HUC CROSSWALK
# ============================================================

with open(
    "meta_prineville_study_hucs.csv",
    newline=""
) as f:
    rows = list(csv.DictReader(f))

selected = [
    r for r in rows
    if r[SCOPE_FIELD] == "1"
]

print()
print("=" * 80)
print("SCOPE:", SCOPE_FIELD)
print("HUC12 count:", len(selected))
print("=" * 80)


# ============================================================
# GENERIC DOWNLOAD FUNCTION
# ============================================================

def download_series(
    model,
    variable,
    start,
    end,
    subdir,
    filename_prefix,
):

    outdir = (
        Path("usgs_nwaa")
        / subdir
        / SCOPE_FIELD
    )

    outdir.mkdir(
        parents=True,
        exist_ok=True
    )

    print()
    print(
        f"Downloading {variable} "
        f"for {len(selected)} HUC12s"
    )
    print()

    failures = []

    for i, row in enumerate(
        selected,
        start=1
    ):
        huc = row["huc12"]
        name = row["name"]

        outfile = (
            outdir
            / f"{filename_prefix}_{huc}.csv"
        )

        # Don't redownload good existing files
        if (
            outfile.exists()
            and outfile.stat().st_size > 50
        ):
            print(
                f"[{i}/{len(selected)}] "
                f"{huc} | already exists"
            )
            continue

        params = {
            "model": model,
            "variable": variable,
            "location": f"huc12:{huc}",
            "startdate": start,
            "enddate": end,
            "timeres": "monthly",
            "format": "csv",
        }

        print(
            f"[{i}/{len(selected)}] "
            f"{huc} | {name}"
        )

        try:
            r = requests.get(
                BASE_URL,
                params=params,
                timeout=120,
            )

            print("  HTTP:", r.status_code)

            if not r.ok:
                print("  URL:", r.url)
                print(
                    "  RESPONSE:",
                    r.text[:1000]
                )

                failures.append(
                    (huc, r.status_code)
                )

                continue

            outfile.write_bytes(
                r.content
            )

            print(
                "  Saved:",
                outfile
            )

        except Exception as e:
            print(
                "  ERROR:",
                repr(e)
            )

            failures.append(
                (huc, str(e))
            )

        time.sleep(0.2)

    return failures


# ============================================================
# 1. INTEGRATED HYDROLOGY
# ============================================================

hydro_failures = download_series(
    model="iwa-assessment-outputs-conus-2025",
    variable="all",
    start="2009-10",
    end="2020-09",
    subdir="hydrology",
    filename_prefix="hydrology",
)


# ============================================================
# 2. PUBLIC-SUPPLY CONSUMPTIVE USE
# ============================================================

ps_failures = download_series(
    model="wu-public-supply-cu",
    variable="pscutot",
    start="2009-01",
    end="2020-12",
    subdir="pscutot",
    filename_prefix="pscutot",
)


# ============================================================
# SUMMARY
# ============================================================

print()
print("=" * 80)
print("DOWNLOAD SUMMARY")
print("=" * 80)

print(
    "Hydrology failures:",
    len(hydro_failures)
)

for x in hydro_failures:
    print(" ", x)

print(
    "PSCUTOT failures:",
    len(ps_failures)
)

for x in ps_failures:
    print(" ", x)

print()
print("Done.")
