from pathlib import Path
import requests

BASE_URL = "https://api.water.usgs.gov/nwaa-data/data"

OUT = Path("data/raw/usgs_nwaa")
OUT.mkdir(parents=True, exist_ok=True)

HUC_N = 8
HUC_CODE = "17070305"

requests_to_make = [
    # Public-supply consumption
    {
        "model": "wu-public-supply-cu",
        "variable": "pscutot",
        "startdate": "2009-01",
        "enddate": "2020-12",
    },

    # Public-supply withdrawals
    {
        "model": "wu-public-supply-wd",
        "variable": "pswdtot",
        "startdate": "2000-01",
        "enddate": "2020-12",
    },
    {
        "model": "wu-public-supply-wd",
        "variable": "pswdgw",
        "startdate": "2000-01",
        "enddate": "2020-12",
    },
    {
        "model": "wu-public-supply-wd",
        "variable": "pswdsw",
        "startdate": "2000-01",
        "enddate": "2020-12",
    },

    # Integrated water availability
    {
        "model": "iwa-assessment-outputs-conus-2025",
        "variable": "consum",
        "startdate": "2009-10",
        "enddate": "2020-09",
    },
    {
        "model": "iwa-assessment-outputs-conus-2025",
        "variable": "availab",
        "startdate": "2009-10",
        "enddate": "2020-09",
    },
    {
        "model": "iwa-assessment-outputs-conus-2025",
        "variable": "sui",
        "startdate": "2009-10",
        "enddate": "2020-09",
    },
    {
        "model": "iwa-assessment-outputs-conus-2025",
        "variable": "strflow",
        "startdate": "2009-10",
        "enddate": "2020-09",
    },
]

for q in requests_to_make:

    params = {
        **q,
        "location": f"huc{HUC_N}:{HUC_CODE}",
        "timeres": "monthly",
        "format": "csv",
    }

    r = requests.get(BASE_URL, params=params, timeout=120)
    r.raise_for_status()

    filename = (
        f"{q['model']}__{q['variable']}__"
        f"huc{HUC_N}-{HUC_CODE}.csv"
    )

    (OUT / filename).write_bytes(r.content)

    print("Saved:", filename)