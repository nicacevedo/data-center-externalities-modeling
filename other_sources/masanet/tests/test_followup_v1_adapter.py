"""Adapter and aggregation tests. No Meta water. No groundwater names."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path("/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet")
sys.path.insert(0, str(ROOT / "scripts"))

from facility_adapter import (  # noqa: E402
    FacilityIntensityAdapter,
    energy_weighted_annual,
    paper_mean_intensity,
)
from followup_common import active_params_for_function, case_vector  # noqa: E402


def test_constant_it_weighted_equals_paper_mean():
    pue_t = np.array([1.1, 1.2, 1.4, 1.3])
    pit = np.ones(4)
    assert energy_weighted_annual(pue_t, pit) == pytest.approx(paper_mean_intensity(pue_t))


def test_variable_it_weighted_differs_from_unweighted_mean():
    pue_t = np.array([1.1, 1.1, 1.5, 1.5])
    pit = np.array([1.0, 1.0, 3.0, 3.0])
    unweighted = paper_mean_intensity(pue_t)
    weighted = energy_weighted_annual(pue_t, pit)
    assert unweighted == pytest.approx(1.3)
    assert weighted == pytest.approx(1.4)
    assert abs(weighted - unweighted) > 0.05


def test_adapter_identifiers_are_not_source_water():
    src = (ROOT / "scripts" / "facility_adapter.py").read_text()
    body = "\n".join(ln for ln in src.splitlines() if "FORBIDDEN_NAME_FRAGMENTS" not in ln and '"groundwater"' not in ln)
    for ident in ("W_groundwater", "W_source", "W_municipal", "W_withdrawal", "q_gw"):
        assert ident not in body


def _theta_mid(case=1):
    spec = active_params_for_function(case)
    return {k: 0.5 * (v["lo"] + v["hi"]) for k, v in spec.items()}


def test_adapter_pit1_matches_upstream_and_scales():
    from instrument_upstream import load_instrumented

    inst = load_instrumented(1.0, rewrite=True)
    theta = _theta_mid(1)
    weather = {"T_oa": 15.0, "RH_oa": 50.0, "P_oa": 101325.0}
    ad = FacilityIntensityAdapter(inst, 1)
    np.random.seed(2025)
    r1 = ad.evaluate_hour(weather, theta, P_IT_kW=1.0, rng_seed=2025)
    np.random.seed(2025)
    pue_u, wue_u = inst.PUE_WUE_AE_Chiller(case_vector(1, weather, theta))
    assert r1.PUE == pytest.approx(float(pue_u), rel=0, abs=1e-12)
    assert r1.WUE_L_per_kWh == pytest.approx(float(wue_u), rel=0, abs=1e-12)
    assert r1.P_fac_kW == pytest.approx(r1.PUE)
    r2 = ad.evaluate_hour(weather, theta, P_IT_kW=2.0, rng_seed=2025)
    assert r2.PUE == pytest.approx(r1.PUE, rel=0, abs=1e-8)
    assert r2.WUE_L_per_kWh == pytest.approx(r1.WUE_L_per_kWh, rel=0, abs=1e-8)
    assert r2.P_fac_kW == pytest.approx(2.0 * r1.P_fac_kW, rel=0, abs=1e-8)
    assert r2.W_conditioning_kg_s == pytest.approx(2.0 * r1.W_conditioning_kg_s, rel=0, abs=1e-8)
    assert r2.W_conditioning_kg_s == pytest.approx(sum(r2.W_components_kg_s.values()), abs=1e-10)
    assert all(v >= -1e-12 for v in r2.W_components_kg_s.values())
    assert r1.chiller_load_is_scenario_parameter is True


def test_chiller_load_is_scenario_parameter_not_pit_callback():
    theta = _theta_mid(1)
    assert "Chiller_load" in theta
    sig = inspect.signature(FacilityIntensityAdapter.evaluate_hour)
    assert "chiller_load_fn" not in sig.parameters
    assert "P_IT_kW" in sig.parameters
