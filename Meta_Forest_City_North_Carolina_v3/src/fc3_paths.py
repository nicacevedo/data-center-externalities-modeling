"""Forest City v3 paths. Write only under this folder.

Named fc3_paths.py so it cannot shadow Forest City v1 `paths.py` when both
source trees are on sys.path.
"""
from __future__ import annotations

from pathlib import Path

FC3 = Path(__file__).resolve().parents[1]
REPO = FC3.parent
V1 = REPO / "Meta_Forest_City_North_Carolina_v1"
V1_SRC = V1 / "src"
V1_RAW_WEATHER = V1 / "data" / "raw" / "weather"
V1_PROCESSED = V1 / "data" / "processed"
V2 = REPO / "Meta_Forest_City_North_Carolina_v2"
PRN = REPO / "Meta_Prineville_Oregon_v3"
MASANET = REPO / "other_sources" / "masanet"
ESIF_FO = REPO / "other_sources" / "nlr_esif_fullstack" / "facility_overhead"
NLR = REPO / "other_sources" / "nlr_esif_fullstack"

CONFIG = FC3 / "config"
SRC = FC3 / "src"
SCRIPTS = FC3 / "scripts"
TESTS = FC3 / "tests"
OUTPUTS = FC3 / "outputs"

PYTHON = "/home/nacevedo/.conda/envs/dc_externalities/bin/python"
MASANET_PYTHON = "/home/nacevedo/.conda/envs/masanet_lei/bin/python"

CAMPUS_TZ = "America/New_York"
CAMPUS_LAT = 35.314167
CAMPUS_LON = -81.822083

COMMON_START = "2012-06-21 00:00:00+00:00"
COMMON_END = "2012-09-01 00:00:00+00:00"
JJA_START = "2012-06-01 00:00:00+00:00"
JJA_END = "2012-09-01 00:00:00+00:00"

# Same ideal upper bound used for v1 primary DX classification and committed v2.
FC_EVAP_EPS = 1.0

# HEAD-committed v2 JJA KFQD reproduction targets (da7fd6f).
V2_KFQD_JJA_TARGET = {
    "valid_hours": 1253,
    "weather_missing_hours": 955,
    "OA_FREE": 677,
    "HIGH_RH_MIXING": 443,
    "EVAP_COOLING": 133,
    "HUMIDIFICATION": 0,
    "MECHANICAL_COOLING": 0,
    "UNRESOLVED": 0,
    "DX_required_hours": 0,
}
