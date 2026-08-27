"""First-run hard tests. Requires masanet_lei env and nested upstream clone."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path("/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet")
sys.path.insert(0, str(ROOT / "scripts"))

from common import (  # noqa: E402
    ARCHETYPE_PARAMS,
    CANONICAL_SEED,
    DEMO_VECTOR,
    load_upstream,
    vector_for,
)
from instrument_upstream import load_instrumented  # noqa: E402


@pytest.fixture(scope="session")
def upstream():
    mod, notes = load_upstream()
    return mod, notes


def test_cop_models_load_and_predict(upstream):
    mod, notes = upstream
    y2 = float(mod.COP_gp.predict(np.array([[20.0, 0.5]]))[0])
    yac = float(mod.COP_air_gp.predict(np.array([[20.0, 0.5]]))[0])
    ydx = float(mod.COP_DX_gp.predict(np.array([[20.0]]))[0])
    assert np.isfinite([y2, yac, ydx]).all()
    assert y2 > 0 and yac > 0 and ydx > 0


def test_seeded_reproducibility(upstream):
    mod, _ = upstream
    np.random.seed(CANONICAL_SEED)
    a = mod.PUE_WUE_WE_Chiller_Colo(DEMO_VECTOR)
    np.random.seed(CANONICAL_SEED)
    b = mod.PUE_WUE_WE_Chiller_Colo(DEMO_VECTOR)
    assert a == b
    assert np.isfinite(a).all()


def test_repeatability_reset_seed(upstream):
    mod, _ = upstream
    np.random.seed(CANONICAL_SEED)
    a = mod.PUE_WUE_WE_Chiller_Colo(DEMO_VECTOR)
    np.random.seed(7)
    _ = mod.PUE_WUE_WE_Chiller_Colo(DEMO_VECTOR)
    np.random.seed(CANONICAL_SEED)
    b = mod.PUE_WUE_WE_Chiller_Colo(DEMO_VECTOR)
    assert a == b


@pytest.mark.parametrize("name", list(ARCHETYPE_PARAMS))
def test_finite_pue_wue_canonical(upstream, name):
    mod, _ = upstream
    np.random.seed(CANONICAL_SEED)
    pue, wue = getattr(mod, name)(vector_for(name))
    assert np.isfinite(pue) and np.isfinite(wue)
    assert pue >= 1
    assert wue >= 0


def test_no_nan_inf_demo(upstream):
    mod, _ = upstream
    np.random.seed(CANONICAL_SEED)
    pue, wue = mod.PUE_WUE_WE_Chiller_Colo(DEMO_VECTOR)
    assert np.isfinite(pue) and np.isfinite(wue)


def test_cooling_tower_wue_identity(upstream):
    mod, _ = upstream
    wue, _, _, evap, wind, drain = mod.Cooling_Tower(
        25.0, 50.0, 101325.0, 3.36, 1.0, 1.2, 5.1, 0.00294, 11.17, 0.272
    )
    recon = (evap + wind + drain) * 3600 / 1.0
    assert evap >= -1e-15 and wind >= -1e-15 and drain >= -1e-15
    assert abs(wue - recon) <= 1e-10


@pytest.fixture(scope="session")
def instrumented():
    return load_instrumented(1.0)


@pytest.mark.parametrize("name", list(ARCHETYPE_PARAMS))
def test_energy_and_water_component_closure(instrumented, name):
    inst = instrumented
    np.random.seed(CANONICAL_SEED)
    pue, wue = getattr(inst, name)(vector_for(name) if name != "PUE_WUE_WE_Chiller_Colo" else DEMO_VECTOR)
    last = inst._LAST
    pc = np.asarray(last["Power_comp"], dtype=float)
    wc = np.asarray(last["Water_comp"], dtype=float)
    pit = float(last["Power_IT"])
    assert np.isfinite(pc).all() and np.isfinite(wc).all()
    assert (wc >= -1e-12).all()
    assert abs(pc.sum() / pit - pue) <= 1e-10
    assert abs(wc.sum() * 3600 / pit - wue) <= 1e-8
    assert pue >= 1
