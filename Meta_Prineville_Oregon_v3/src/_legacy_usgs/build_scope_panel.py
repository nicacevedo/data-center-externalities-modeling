import sys
from pathlib import Path

import pandas as pd


if len(sys.argv) != 2:
    raise SystemExit(
        "Usage: python build_scope_panel.py "
        "[scope_local|scope_hydro_near|same_site_huc10|same_site_huc8]"
    )

SCOPE = sys.argv[1]


HYDRO_DIR = (
    Path("usgs_nwaa")
    / "hydrology"
    / SCOPE
)

PS_DIR = (
    Path("usgs_nwaa")
    / "pscutot"
    / SCOPE
)

CROSSWALK = Path(
    "meta_prineville_study_hucs.csv"
)

OUTFILE = Path(
    f"meta_prineville_water_panel_{SCOPE}.csv"
)


# ============================================================
# HYDROLOGY
# ============================================================

hydro_files = sorted(
    HYDRO_DIR.glob("hydrology_*.csv")
)

if not hydro_files:
    raise RuntimeError(
        f"No hydrology files in {HYDRO_DIR}"
    )

hydro = pd.concat(
    [
        pd.read_csv(
            f,
            dtype={"huc12_id": str}
        )
        for f in hydro_files
    ],
    ignore_index=True,
)

hydro = hydro.rename(
    columns={
        "sui_frac":
            "sui",

        "availab_mm/mo":
            "availability_mm_month",

        "strflow_mm/mo":
            "streamflow_mm_month",

        "consum_mm/mo":
            "total_consumption_mm_month",
    }
)


# ============================================================
# PSCUTOT
# ============================================================

ps_files = sorted(
    PS_DIR.glob("pscutot_*.csv")
)

if not ps_files:
    raise RuntimeError(
        f"No PSCUTOT files in {PS_DIR}"
    )

ps = pd.concat(
    [
        pd.read_csv(
            f,
            dtype={"huc12_id": str}
        )
        for f in ps_files
    ],
    ignore_index=True,
)

ps = ps.rename(
    columns={
        "pscutot_mgd":
            "public_supply_consumption_mgd"
    }
)

# Restrict to common hydrology period
ps = ps[
    ps["year_month"].between(
        "2009-10",
        "2020-09"
    )
].copy()


# ============================================================
# MERGE WATER SERIES
# ============================================================

assert not hydro.duplicated(
    ["huc12_id", "year_month"]
).any()

assert not ps.duplicated(
    ["huc12_id", "year_month"]
).any()


panel = hydro.merge(
    ps,
    on=[
        "huc12_id",
        "year_month",
    ],
    how="outer",
    validate="one_to_one",
    indicator=True,
)

print("\nMerge:")
print(
    panel["_merge"]
    .value_counts()
)

if not (
    panel["_merge"] == "both"
).all():
    print(
        "\nWARNING: unmatched observations exist."
    )

panel = panel.drop(
    columns="_merge"
)


# ============================================================
# GEOGRAPHY
# ============================================================

geo = pd.read_csv(
    CROSSWALK,
    dtype={"huc12": str}
)

geo = geo.rename(
    columns={
        "huc12": "huc12_id"
    }
)

panel = panel.merge(
    geo,
    on="huc12_id",
    how="left",
    validate="many_to_one",
)


# Keep only requested scope
panel = panel[
    panel[SCOPE] == 1
].copy()


# ============================================================
# DATE
# ============================================================

panel["date"] = pd.to_datetime(
    panel["year_month"]
    + "-01"
)

panel["year"] = (
    panel["date"].dt.year
)

panel["month"] = (
    panel["date"].dt.month
)


# ============================================================
# QA
# ============================================================

panel = panel.sort_values(
    [
        "huc12_id",
        "date",
    ]
).reset_index(drop=True)


n_hucs = (
    panel["huc12_id"]
    .nunique()
)

n_months = (
    panel["year_month"]
    .nunique()
)


print()
print("=" * 80)
print("PANEL QA")
print("=" * 80)

print(
    "Scope:",
    SCOPE
)

print(
    "HUC12s:",
    n_hucs
)

print(
    "Months:",
    n_months
)

print(
    "Rows:",
    len(panel)
)

print(
    "Expected:",
    n_hucs * n_months
)

print(
    "Period:",
    panel["year_month"].min(),
    "to",
    panel["year_month"].max()
)


counts = (
    panel
    .groupby("huc12_id")
    .size()
)

print(
    "\nMin rows/HUC:",
    counts.min()
)

print(
    "Max rows/HUC:",
    counts.max()
)


water_cols = [
    "streamflow_mm_month",
    "availability_mm_month",
    "sui",
    "total_consumption_mm_month",
    "public_supply_consumption_mgd",
]

print("\nMissing:")
print(
    panel[water_cols]
    .isna()
    .sum()
)


# Accounting check
error = (
    panel["availability_mm_month"]
    -
    (
        panel["streamflow_mm_month"]
        -
        panel["total_consumption_mm_month"]
    )
).abs()

print(
    "\nMax accounting error:",
    error.max()
)


# ============================================================
# SAVE
# ============================================================

panel.to_csv(
    OUTFILE,
    index=False
)

print(
    "\nSaved:",
    OUTFILE
)

print(
    "Shape:",
    panel.shape
)
