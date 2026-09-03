"""Forest City v3 paths. Write only under this folder.

Named fc3_paths.py so it cannot shadow Forest City v1 `paths.py` when both
source trees are on sys.path.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

FC3 = Path(__file__).resolve().parents[1]
REPO = FC3.parent
V1 = REPO / "Meta_Forest_City_North_Carolina_v1"
V1_SRC = V1 / "src"
V1_RAW_WEATHER = V1 / "data" / "raw" / "weather"
V1_PROCESSED = V1 / "data" / "processed"
V2 = REPO / "Meta_Forest_City_North_Carolina_v2"
PRN = REPO / "Meta_Prineville_Oregon_v3"
PRN_RAW_WEATHER = PRN / "data" / "raw" / "noaa"
MASANET = REPO / "other_sources" / "masanet"
ESIF_FO = REPO / "other_sources" / "nlr_esif_fullstack" / "facility_overhead"
NLR = REPO / "other_sources" / "nlr_esif_fullstack"

CONFIG = FC3 / "config"
SRC = FC3 / "src"
SCRIPTS = FC3 / "scripts"
TESTS = FC3 / "tests"
OUTPUTS = FC3 / "outputs"

PYTHON = os.environ.get("FC3_PYTHON", sys.executable)
MASANET_PYTHON = os.environ.get(
    "FC3_MASANET_PYTHON", "/home/nacevedo/.conda/envs/masanet_lei/bin/python"
)

CAMPUS_TZ = "America/New_York"
CAMPUS_LAT = 35.314167
CAMPUS_LON = -81.822083

COMMON_START = "2012-06-21 00:00:00+00:00"
COMMON_END = "2012-09-01 00:00:00+00:00"
JJA_START = "2012-06-01 00:00:00+00:00"
JJA_END = "2012-09-01 00:00:00+00:00"

# Same ideal upper bound used for v1 primary DX classification and committed v2.
FC_EVAP_EPS = 1.0

FROZEN_DEPENDENCY_COMMIT = "da7fd6f55e1aef5216ceabe80bfc3e31265f7927"
