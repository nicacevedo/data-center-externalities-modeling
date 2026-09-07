"""Shared import bootstrap for V3 scripts."""

from __future__ import annotations

import sys
from pathlib import Path

V3_ROOT = Path(__file__).resolve().parent.parent
OTHER_SOURCES = V3_ROOT.parent.parent.parent

if str(V3_ROOT) not in sys.path:
    sys.path.insert(0, str(V3_ROOT))
if str(OTHER_SOURCES) not in sys.path:
    sys.path.insert(0, str(OTHER_SOURCES))
