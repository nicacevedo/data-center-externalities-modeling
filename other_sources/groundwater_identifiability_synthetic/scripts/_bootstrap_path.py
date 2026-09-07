"""Shared import bootstrap for the scripts in this module."""

from __future__ import annotations

import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent.parent
OTHER_SOURCES = MODULE_ROOT.parent

if str(OTHER_SOURCES) not in sys.path:
    sys.path.insert(0, str(OTHER_SOURCES))
