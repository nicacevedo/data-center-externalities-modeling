"""Shared fixtures. Adds `other_sources/` to sys.path so the module imports as a package."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

MODULE_ROOT = Path(__file__).resolve().parent.parent
OTHER_SOURCES = MODULE_ROOT.parent
REPO_ROOT = OTHER_SOURCES.parent

if str(OTHER_SOURCES) not in sys.path:
    sys.path.insert(0, str(OTHER_SOURCES))

from groundwater_identifiability_synthetic.src.design import (  # noqa: E402
    load_design,
    resolve_regime,
    seed_list,
)


@pytest.fixture(scope="session")
def design():
    return load_design()


@pytest.fixture(scope="session")
def module_root() -> Path:
    return MODULE_ROOT


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def g0_regime(design):
    spec = design["gates"]["SGI_G0"]["required_cells"]["C_G0"]
    return resolve_regime(
        design, "C_G0", spec["scenario"], spec["topology"], overrides=spec.get("overrides")
    )


@pytest.fixture(scope="session")
def g0_seed(design) -> int:
    return seed_list(design, "G0")[0]


@pytest.fixture(scope="session")
def smoke_seed(design) -> int:
    return seed_list(design, "SMOKE")[0]


@pytest.fixture(scope="session")
def network_regime(design):
    return resolve_regime(design, "TEST_NET", "S5", "path5", overrides={})
