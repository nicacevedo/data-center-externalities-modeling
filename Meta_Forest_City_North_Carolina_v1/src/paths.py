"""Canonical paths for Meta_Forest_City_North_Carolina_v1. Do not write into Prineville."""
from __future__ import annotations

from pathlib import Path

FC_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = FC_ROOT.parent
PRINEVILLE_ROOT = REPO_ROOT / "Meta_Prineville_Oregon_v3"
PRINEVILLE_SRC = PRINEVILLE_ROOT / "src"

CONFIG = FC_ROOT / "config"
DATA_RAW = FC_ROOT / "data" / "raw"
DATA_PROCESSED = FC_ROOT / "data" / "processed"
SRC = FC_ROOT / "src"
SCRIPTS = FC_ROOT / "scripts"
TESTS = FC_ROOT / "tests"
OUTPUTS = FC_ROOT / "outputs"

RAW_SOURCES = DATA_RAW / "sources"
RAW_WEATHER = DATA_RAW / "weather"
RAW_SUSTAINABILITY = DATA_RAW / "sustainability"
RAW_LWSP = DATA_RAW / "lwsp"
RAW_PERMITS = DATA_RAW / "permits"
RAW_DASHBOARD = DATA_RAW / "dashboard"
RAW_EMISSIONS = DATA_RAW / "emissions"

PYTHON = "/home/nacevedo/.conda/envs/dc_externalities/bin/python"
