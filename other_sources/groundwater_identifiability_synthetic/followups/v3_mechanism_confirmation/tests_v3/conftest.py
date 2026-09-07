"""V3 test path bootstrap: import src_v3 from the follow-up tree."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

V3_ROOT = Path(__file__).resolve().parent.parent
OTHER_SOURCES = V3_ROOT.parent.parent.parent
if str(V3_ROOT) not in sys.path:
    sys.path.insert(0, str(V3_ROOT))
if str(OTHER_SOURCES) not in sys.path:
    sys.path.insert(0, str(OTHER_SOURCES))

from src_v3.design import load_design, v3_all_cells  # noqa: E402
from src_v3.modes import RNG_NAMED, SEED_ORTHOGONAL  # noqa: E402


@pytest.fixture(scope="session")
def v3_root() -> Path:
    return V3_ROOT


@pytest.fixture(scope="session")
def design():
    return load_design()


@pytest.fixture(scope="session")
def cells(design):
    return v3_all_cells(design)


@pytest.fixture(scope="session")
def v3_modes():
    return RNG_NAMED, SEED_ORTHOGONAL
