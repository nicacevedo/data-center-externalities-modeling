"""USGS NWAA HUC12 water-module paths, catalog, and unit conversions.

Native API values are never modified. Processed tables may rename columns and
add derived volumetric fields. IWA `consum` already includes sectoral
consumptive-use components, so `pscutot` and `irrcutot` must not be added into
it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SITE_HUC12 = "170703051002"
SITE_HUC10 = "1707030510"
SITE_HUC8 = "17070305"
SITE_HUC12_NAME = "Town of Prineville–Crooked River"
SITE_HUC12_DESIGNATION = "site_point_huc12"

API_BASE = "https://api.water.usgs.gov/nwaa-data/data"
API_MODELS_URL = "https://api.water.usgs.gov/nwaa-data/models"
WBD_HUC12_URL = (
    "https://hydro.nationalmap.gov/arcgis/rest/services/wbd/MapServer/6/query"
)
OWRD_WELL_DETAILS = (
    "https://apps.wrd.state.or.us/apps/gw/well_log/wl_details.aspx"
)

SCOPES = (
    "scope_local",
    "scope_hydro_near",
    "same_site_huc10",
    "same_site_huc8",
)
PRIMARY_SCOPES = ("scope_local", "same_site_huc8")

# 1 mm of depth over 1 km^2 = 0.001 m * 1_000_000 m^2 = 1_000 m^3.
MM_OVER_KM2_TO_M3 = 1000.0
# USGS NWAA water-use models report million U.S. gallons per day (mgd).
M3_PER_MILLION_US_GALLONS = 3785.411784

GEO_COLUMNS = [
    "huc12_id",
    "name",
    "is_site",
    "is_touching_site",
    "network_direction",
    "network_depth",
    "same_site_huc10",
    "same_site_huc8",
    "scope_local",
    "scope_hydro_near",
    "areasqkm",
]

IWA_RENAME = {
    "sui_frac": "iwa_sui",
    "availab_mm/mo": "iwa_surface_water_availability_mm_month",
    "strflow_mm/mo": "iwa_cumulative_streamflow_mm_month",
    "consum_mm/mo": "iwa_cumulative_consumption_mm_month",
}

IWA_MM_COLUMNS = [
    "iwa_surface_water_availability_mm_month",
    "iwa_cumulative_streamflow_mm_month",
    "iwa_cumulative_consumption_mm_month",
]


@dataclass(frozen=True)
class SeriesSpec:
    key: str
    model: str
    variable: str
    startdate: str
    enddate: str
    units: str
    native_column: str
    processed_column: str
    expected_months: int
    description: str


SERIES: dict[str, SeriesSpec] = {
    "iwa_all": SeriesSpec(
        key="iwa_all",
        model="iwa-assessment-outputs-conus-2025",
        variable="all",
        startdate="2009-10",
        enddate="2020-09",
        units="frac and mm/mo",
        native_column="",
        processed_column="",
        expected_months=132,
        description=(
            "IWA monthly HUC12 outputs: SUI (fraction) plus cumulative "
            "streamflow, cumulative consumptive use, and availability (mm/month)."
        ),
    ),
    "pscutot": SeriesSpec(
        key="pscutot",
        model="wu-public-supply-cu",
        variable="pscutot",
        startdate="2009-01",
        enddate="2020-12",
        units="mgd",
        native_column="pscutot_mgd",
        processed_column="public_supply_consumption_mgd",
        expected_months=144,
        description="Modeled public-supply consumptive use (not Meta-specific).",
    ),
    "pswdtot": SeriesSpec(
        key="pswdtot",
        model="wu-public-supply-wd",
        variable="pswdtot",
        startdate="2000-01",
        enddate="2020-12",
        units="mgd",
        native_column="pswdtot_mgd",
        processed_column="public_supply_withdrawal_total_mgd",
        expected_months=252,
        description="Modeled total public-supply withdrawals.",
    ),
    "pswdgw": SeriesSpec(
        key="pswdgw",
        model="wu-public-supply-wd",
        variable="pswdgw",
        startdate="2000-01",
        enddate="2020-12",
        units="mgd",
        native_column="pswdgw_mgd",
        processed_column="public_supply_withdrawal_groundwater_mgd",
        expected_months=252,
        description="Modeled groundwater public-supply withdrawals.",
    ),
    "pswdsw": SeriesSpec(
        key="pswdsw",
        model="wu-public-supply-wd",
        variable="pswdsw",
        startdate="2000-01",
        enddate="2020-12",
        units="mgd",
        native_column="pswdsw_mgd",
        processed_column="public_supply_withdrawal_surface_water_mgd",
        expected_months=252,
        description="Modeled surface-water public-supply withdrawals.",
    ),
    "irrwdtot": SeriesSpec(
        key="irrwdtot",
        model="wu-irrigation-wd",
        variable="irrwdtot",
        startdate="2000-01",
        enddate="2020-12",
        units="mgd",
        native_column="irrwdtot_mgd",
        processed_column="irrigation_withdrawal_mgd",
        expected_months=252,
        description="Modeled total crop-irrigation withdrawals.",
    ),
    "irrcutot": SeriesSpec(
        key="irrcutot",
        model="wu-irrigation-cu",
        variable="irrcutot",
        startdate="2000-01",
        enddate="2020-12",
        units="mgd",
        native_column="irrcutot_mgd",
        processed_column="irrigation_consumption_mgd",
        expected_months=252,
        description="Modeled total crop-irrigation consumptive use.",
    ),
}

DOWNLOAD_SERIES = [
    SERIES["pswdtot"],
    SERIES["pswdgw"],
    SERIES["pswdsw"],
    SERIES["irrwdtot"],
    SERIES["irrcutot"],
]

THERMO_SCREEN = SeriesSpec(
    key="tewdftot",
    model="wu-thermoelectric",
    variable="tewdftot",
    startdate="2008-01",
    enddate="2020-12",
    units="mgd",
    native_column="tewdftot_mgd",
    processed_column="thermoelectric_fresh_withdrawal_total_mgd",
    expected_months=156,
    description="Thermoelectric fresh-water total withdrawals (screening only).",
)

LEGACY_ROOT = ROOT
STUDY_HUCS_ROOT = ROOT / "meta_prineville_study_hucs.csv"
NETWORK_ROOT = ROOT / "meta_huc12_hydrologic_network.csv"

CANONICAL_USGS = ROOT / "data" / "canonical" / "usgs"
STUDY_HUCS = CANONICAL_USGS / "meta_prineville_study_hucs.csv"
NETWORK = CANONICAL_USGS / "meta_huc12_hydrologic_network.csv"
SITE_GEOJSON = CANONICAL_USGS / "meta_site_huc12.geojson"
TOUCHING_GEOJSON = CANONICAL_USGS / "touching_huc12s.geojson"
HUC10_GEOJSON = CANONICAL_USGS / "huc12s_in_parent_huc10.geojson"
MUNICIPAL_CROSSWALK = (
    ROOT / "data" / "canonical" / "municipal_source_huc12_crosswalk.csv"
)
SITE_HUC12_NOTE = CANONICAL_USGS / "site_huc12_designation.csv"

RAW_NWAA = ROOT / "data" / "raw" / "usgs_nwaa"
RAW_AGGREGATES = RAW_NWAA / "aggregates"
RAW_HUC12 = RAW_NWAA / "huc12"
PROVENANCE = RAW_NWAA / "provenance.jsonl"

PROCESSED = ROOT / "data" / "processed" / "usgs_nwaa"
QC_DIR = ROOT / "outputs" / "qc"

CITY_SOURCES = ROOT / "data" / "canonical" / "city_water_sources.csv"
OWRD_CROSSWALK = ROOT / "data" / "canonical" / "prineville_owrd_source_crosswalk.csv"

LEGACY_SCRIPTS = [
    "usg_downloader.py",
    "download_hydrology.py",
    "download_pscutot.py",
    "download_scope_water.py",
    "build_local_water_panel.py",
    "build_scope_panel.py",
    "prepare_analysis_panel.py",
]
LEGACY_ARCHIVE = ROOT / "src" / "_legacy_usgs"


def pad_huc12(value) -> str:
    text = str(value).strip().replace(".0", "")
    if text.lower() in {"nan", "none", ""}:
        return ""
    return text.zfill(12)


def huc12_raw_dir(model: str, variable: str, scope: str) -> Path:
    return RAW_HUC12 / model / variable / scope


def huc12_raw_file(model: str, variable: str, scope: str, huc12: str) -> Path:
    prefix = "hydrology" if variable == "all" else variable
    return huc12_raw_dir(model, variable, scope) / f"{prefix}_{pad_huc12(huc12)}.csv"


def aggregate_file(model: str, variable: str, location_label: str) -> Path:
    return RAW_AGGREGATES / f"{model}__{variable}__{location_label}.csv"
