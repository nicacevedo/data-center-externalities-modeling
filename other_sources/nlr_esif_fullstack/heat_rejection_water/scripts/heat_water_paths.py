"""Paths and frozen identities for the ESIF heat-rejection → water experiment."""
from pathlib import Path

HW_ROOT = Path(__file__).resolve().parents[1]
NLR_ROOT = HW_ROOT.parent
REPO_ROOT = NLR_ROOT.parents[1]
FO_ROOT = NLR_ROOT / "facility_overhead"

MANIFESTS = HW_ROOT / "manifests"
SOURCES = HW_ROOT / "sources"
ANALYSIS = HW_ROOT / "analysis"
DATA_PROCESSED = HW_ROOT / "data_processed"
FIGURES = HW_ROOT / "figures"
SCRIPTS = HW_ROOT / "scripts"
TESTS = HW_ROOT / "tests"
DOCS = HW_ROOT / "docs"

ESIF_DIR = NLR_ROOT / "data_raw" / "esif_pue"
POWER_PARQUET = ESIF_DIR / "esif.influx.buildingData.PUE.combined.parquet"
WEATHER_PARQUET = ESIF_DIR / "esif.influx.buildingData.outside.combined.parquet"
ESIF_README = ESIF_DIR / "README.md"

CPU_STATUS = NLR_ROOT / "analysis" / "FINAL_KESTREL_CPU_STATUS.json"
CPU_FREEZE = NLR_ROOT / "manifests" / "FINAL_MODEL_FREEZE.json"
H100_FREEZE = NLR_ROOT / "genai_h100" / "manifests" / "H100_COMPUTE_FINAL_FREEZE.json"
FO_LAYER_FREEZE = FO_ROOT / "manifests" / "FACILITY_OVERHEAD_LAYER_FREEZE.json"
FO_STATUS = FO_ROOT / "analysis" / "FINAL_ESIF_FACILITY_OVERHEAD_STATUS.json"

LEI_MATRIX = (
    REPO_ROOT
    / "other_sources"
    / "cooling_technology_proxies"
    / "data_processed"
    / "SUPPORTED_DOMAIN_MATRIX.csv"
)

PDF_72196 = SOURCES / "nrel_tp_2c00_72196.pdf"
PDF_66690 = SOURCES / "nrel_cp_2c00_66690.pdf"

POWER_SHA256 = "19cd12405dde9144b1a360e8c8418666c399a3d0d15a7f846880d71ab22f9dd4"
WEATHER_SHA256 = "97b424993fa77a15117fb2c4659a2c327fc83280f943fab47d9036260289a6a0"
README_SHA256 = "f69d32f1af598c48a899d54d48b26def2ca78a0c11d848516169570ecae4c029"
CPU_STATUS_SHA256 = "1f57b210a63d375ce8eff7d5043756ffe6efe04e8a408bf9429bfd10096528d9"
CPU_FREEZE_SHA256 = "dcbd066b26b8e7d2800e40a23a1cb8250502bfe59563fe06318cb1be1cc4fd27"
H100_FREEZE_SHA256 = "a620d649a932f2388aa2f35bac2730eb75fe1dc74529668de4f30ee814600076"
FO_STATUS_SHA256 = "ae7c50a0a5ab4c6ecd52f0fe55607ca423295458755226515ee5c46e2c3542d2"
FO_LAYER_FREEZE_SHA256 = "bac8f706fa407f89a21ccbb73e2675cfed9b5bbc5443f43aea8572157e5c67e5"

# Sickinger first full year; not a fitted breakpoint.
TSC_FIRST_YEAR_START = "2016-09-01"
TSC_FIRST_YEAR_END_EXCLUSIVE = "2017-09-01"
TSC_PRE_START = "2016-06-12"
TSC_PRE_END_INCLUSIVE = "2016-07-31"
TSC_TRANSITION_MONTH = "2016-08"
SICKINGER_OPERATIONAL_CAPTION_DATE = "2016-08-16"
TSC_DB_THRESHOLD_C = 9.4  # documented control example; not estimated from outcomes
TSC_DB_THRESHOLD_F = 49.0

US_GAL_PER_M3 = 264.172052358
L_PER_M3 = 1000.0
ROUNDING_WATER_M3_TOL = 50.0  # predeclared vs 2-decimal WUE
ROUNDING_REL_TOL = 0.02
