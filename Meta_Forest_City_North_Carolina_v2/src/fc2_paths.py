"""Canonical paths. Never write into Forest City v1 or Prineville."""
from __future__ import annotations

from pathlib import Path

FC2 = Path(__file__).resolve().parents[1]
REPO = FC2.parent
V1 = REPO / "Meta_Forest_City_North_Carolina_v1"
PRN = REPO / "Meta_Prineville_Oregon_v3"
PYTHON = "/home/nacevedo/.conda/envs/dc_externalities/bin/python"
