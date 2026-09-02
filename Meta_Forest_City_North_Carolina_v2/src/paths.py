"""Canonical paths for Forest City v2. Do not write into v1 or Prineville."""
from __future__ import annotations

from pathlib import Path

FC2_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = FC2_ROOT.parent
V1_ROOT = REPO_ROOT / "Meta_Forest_City_North_Carolina_v1"
PRINEVILLE_ROOT = REPO_ROOT / "Meta_Prineville_Oregon_v3"
PRINEVILLE_SRC = PRINEVILLE_ROOT / "src"
V1_SRC = V1_ROOT / "src"

CONFIG = FC2_ROOT / "config"
DATA_RAW = FC2_ROOT / "data" / "raw"
DATA_PROCESSED = FC2_ROOT / "data" / "processed"
SRC = FC2_ROOT / "src"
SCRIPTS = FC2_ROOT / "scripts"
TESTS = FC2_ROOT / "tests"
OUTPUTS = FC2_ROOT / "outputs"
WEATHER_DIR = FC2_ROOT / "weather"

V1_RAW_WEATHER = V1_ROOT / "data" / "raw" / "weather"
V1_RAW_SUSTAINABILITY = V1_ROOT / "data" / "raw" / "sustainability"
V1_RAW_LWSP = V1_ROOT / "data" / "raw" / "lwsp"
V1_PROCESSED = V1_ROOT / "data" / "processed"
V1_OUTPUTS = V1_ROOT / "outputs"

PYTHON = "/home/nacevedo/.conda/envs/dc_externalities/bin/python"

# Campus reference point: NC SOS principal office for Andale, Inc. (284 Social Circle).
CAMPUS_LAT = 35.314167
CAMPUS_LON = -81.822083
CAMPUS_TZ = "America/New_York"
