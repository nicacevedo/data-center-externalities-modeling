from pathlib import Path
import pandas as pd


# ============================================================
# PATHS
# ============================================================

HYDRO_DIR = Path(
    "usgs_nwaa/hydrology/scope_local"
)

PSCUTOT_DIR = Path(
    "usgs_nwaa/pscutot/scope_local"
)

CROSSWALK = Path(
    "meta_prineville_study_hucs.csv"
)

OUTFILE = Path(
    "meta_prineville_local_water_panel.csv"
)


# ============================================================
# 1. READ HYDROLOGY
# ============================================================

hydro_files = sorted(
    HYDRO_DIR.glob("hydrology_*.csv")
)

print(
    f"Hydrology files: {len(hydro_files)}"
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


# Rename awkward slash-containing columns
hydro = hydro.rename(
    columns={
        "sui_frac": "sui",
        "availab_mm/mo": "availability_mm_month",
        "strflow_mm/mo": "streamflow_mm_month",
        "consum_mm/mo": "total_consumption_mm_month",
    }
)


# ============================================================
# 2. READ PUBLIC-SUPPLY CONSUMPTIVE USE
# ============================================================

ps_files = sorted(
    PSCUTOT_DIR.glob("pscutot_*.csv")
)

print(
    f"Public-supply files: {len(ps_files)}"
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


# ============================================================
# 3. LIMIT PSCUTOT TO HYDROLOGY PERIOD
# ============================================================

# Hydrology:
# 2009-10 through 2020-09
#
# PSCUTOT:
# 2009-01 through 2020-12
#
# Keep common sample for master panel.

ps = ps[
    (ps["year_month"] >= "2009-10")
    &
    (ps["year_month"] <= "2020-09")
].copy()


# ============================================================
# 4. BASIC DUPLICATE CHECKS
# ============================================================

hydro_duplicates = hydro.duplicated(
    ["huc12_id", "year_month"]
).sum()

ps_duplicates = ps.duplicated(
    ["huc12_id", "year_month"]
).sum()

print(
    "Hydrology duplicate HUC-months:",
    hydro_duplicates
)

print(
    "PSCUTOT duplicate HUC-months:",
    ps_duplicates
)

assert hydro_duplicates == 0
assert ps_duplicates == 0


# ============================================================
# 5. MERGE WATER DATA
# ============================================================

panel = hydro.merge(
    ps,
    on=[
        "huc12_id",
        "year_month"
    ],
    how="outer",
    validate="one_to_one",
    indicator=True,
)


print("\nWater-data merge:")
print(
    panel["_merge"].value_counts()
)

# Every local HUC-month should appear in both
assert (
    panel["_merge"] == "both"
).all()

panel = panel.drop(
    columns="_merge"
)


# ============================================================
# 6. READ STUDY-GEOGRAPHY CROSSWALK
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


# Keep the geography variables that matter
geo_cols = [
    "huc12_id",
    "name",
    "tohuc",
    "areasqkm",
    "states",
    "is_site",
    "is_touching_site",
    "network_direction",
    "network_depth",
    "same_site_huc10",
    "same_site_huc8",
    "scope_local",
    "scope_hydro_near",
]

geo = geo[geo_cols]


# ============================================================
# 7. ADD GEOGRAPHIC ATTRIBUTES
# ============================================================

panel = panel.merge(
    geo,
    on="huc12_id",
    how="left",
    validate="many_to_one",
)


# ============================================================
# 8. DATE VARIABLES
# ============================================================

panel["date"] = pd.to_datetime(
    panel["year_month"] + "-01"
)

panel["year"] = panel["date"].dt.year
panel["month"] = panel["date"].dt.month


# ============================================================
# 9. ORDER VARIABLES
# ============================================================

cols = [
    # identifiers
    "huc12_id",
    "name",
    "year_month",
    "date",
    "year",
    "month",

    # treatment / geographic structure
    "is_site",
    "is_touching_site",
    "network_direction",
    "network_depth",
    "same_site_huc10",
    "same_site_huc8",
    "scope_local",
    "scope_hydro_near",

    # watershed metadata
    "tohuc",
    "areasqkm",
    "states",

    # physical hydrology
    "streamflow_mm_month",
    "availability_mm_month",
    "sui",
    "total_consumption_mm_month",

    # public supply water use
    "public_supply_consumption_mgd",
]

panel = panel[cols]


# ============================================================
# 10. SORT
# ============================================================

panel = panel.sort_values(
    [
        "huc12_id",
        "date"
    ]
).reset_index(drop=True)


# ============================================================
# 11. INTEGRITY TESTS
# ============================================================

n_hucs = panel["huc12_id"].nunique()
n_months = panel["year_month"].nunique()

expected_rows = (
    n_hucs * n_months
)


print("\n" + "=" * 70)
print("PANEL CHECK")
print("=" * 70)

print("HUC12s :", n_hucs)
print("Months :", n_months)
print("Rows   :", len(panel))

print(
    "Expected balanced rows:",
    expected_rows
)

print(
    "First month:",
    panel["year_month"].min()
)

print(
    "Last month :",
    panel["year_month"].max()
)


assert n_hucs == 9
assert n_months == 132
assert len(panel) == 9 * 132

assert (
    panel["year_month"].min()
    == "2009-10"
)

assert (
    panel["year_month"].max()
    == "2020-09"
)


# Every HUC should have 132 observations
counts = (
    panel
    .groupby("huc12_id")
    .size()
)

print("\nRows per HUC:")
print(counts.to_string())

assert (
    counts == 132
).all()


# Missingness
water_cols = [
    "streamflow_mm_month",
    "availability_mm_month",
    "sui",
    "total_consumption_mm_month",
    "public_supply_consumption_mgd",
]

print("\nMissing values:")
print(
    panel[water_cols]
    .isna()
    .sum()
    .to_string()
)


# ============================================================
# 12. CHECK USGS ACCOUNTING IDENTITY
# ============================================================

# USGS defines:
# availability = streamflow - consumption

panel["availability_check"] = (
    panel["streamflow_mm_month"]
    -
    panel["total_consumption_mm_month"]
)

panel["availability_error"] = (
    panel["availability_mm_month"]
    -
    panel["availability_check"]
).abs()


print(
    "\nMax availability identity error:",
    panel["availability_error"].max()
)


# Remove QA variables from final file
panel = panel.drop(
    columns=[
        "availability_check",
        "availability_error",
    ]
)


# ============================================================
# 13. SAVE
# ============================================================

panel.to_csv(
    OUTFILE,
    index=False
)

print("\nSaved:")
print(OUTFILE)

print("\nFinal shape:")
print(panel.shape)
