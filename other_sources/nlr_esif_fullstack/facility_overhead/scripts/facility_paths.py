"""Paths and frozen identities for the ESIF facility-overhead experiment."""
from pathlib import Path

FO_ROOT = Path(__file__).resolve().parents[1]
NLR_ROOT = FO_ROOT.parent
REPO_ROOT = NLR_ROOT.parents[1]

MANIFESTS = FO_ROOT / "manifests"
ANALYSIS = FO_ROOT / "analysis"
DATA_PROCESSED = FO_ROOT / "data_processed"
FIGURES = FO_ROOT / "figures"
SCRIPTS = FO_ROOT / "scripts"
TESTS = FO_ROOT / "tests"
DOCS = FO_ROOT / "docs"
RESULTS = FO_ROOT / "results"

ESIF_DIR = NLR_ROOT / "data_raw" / "esif_pue"
POWER_PARQUET = ESIF_DIR / "esif.influx.buildingData.PUE.combined.parquet"
WEATHER_PARQUET = ESIF_DIR / "esif.influx.buildingData.outside.combined.parquet"
ESIF_README = ESIF_DIR / "README.md"

CPU_STATUS = NLR_ROOT / "analysis" / "FINAL_KESTREL_CPU_STATUS.json"
CPU_FREEZE = NLR_ROOT / "manifests" / "FINAL_MODEL_FREEZE.json"
H100_FREEZE = NLR_ROOT / "genai_h100" / "manifests" / "H100_COMPUTE_FINAL_FREEZE.json"

ESIF_DOI = "10.7799/3015212"
POWER_SHA256 = "19cd12405dde9144b1a360e8c8418666c399a3d0d15a7f846880d71ab22f9dd4"
WEATHER_SHA256 = "97b424993fa77a15117fb2c4659a2c327fc83280f943fab47d9036260289a6a0"
README_SHA256 = "f69d32f1af598c48a899d54d48b26def2ca78a0c11d848516169570ecae4c029"
CPU_STATUS_SHA256 = "1f57b210a63d375ce8eff7d5043756ffe6efe04e8a408bf9429bfd10096528d9"
CPU_FREEZE_SHA256 = "dcbd066b26b8e7d2800e40a23a1cb8250502bfe59563fe06318cb1be1cc4fd27"
H100_FREEZE_SHA256 = "a620d649a932f2388aa2f35bac2730eb75fe1dc74529668de4f30ee814600076"

CPU_DISPOSITION = "FROZEN_PASS_WITH_DOMAIN_RESTRICTIONS"
H100_DISPOSITION = "FROZEN_PASS_WITH_DOMAIN_RESTRICTIONS"

# Native cadence inferred from median dt on both official series; frozen before modeling.
CADENCE_S = 60.0
MAX_INTEGRATION_GAP_S = 180.0  # 3 cadences; gaps longer than this do not contribute energy
COVERAGE_MIN = 0.90
ALIGN_TOLERANCE_S = 60.0  # one native step; not chosen by correlation

TOWER_FILTER_PUMP_KW = 2.67  # source README; descriptive reclass only

# Documented operational epochs (external announcements; not residual-mined).
EAGLE_DECOMMISSION = "2024-06-15"
GPU_GA = "2024-08-21"
OUTAGE_FULL_START = "2025-06-26"
OUTAGE_FULL_END = "2025-07-01"  # exclusive; documented through 2025-06-30
GPU_INT_OUTAGE_START = "2024-01-29"
GPU_INT_OUTAGE_END = "2024-02-10"

SIMPLEST_ORDER = ("F0", "F1", "F2_PHYS", "F2_RAW", "F3", "F4")
TARGETS = ("cooling_kw", "hvac_kw", "pump_kw", "plug_and_light_kw")
PARSIMONY_REL_WAPE = 0.01
PARSIMONY_BIAS_PP = 0.01
