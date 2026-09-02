"""Structural-reference-v1 thermodynamic, boundary, and API tests. No Meta-water calibration."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from holdout_guard import HoldoutAccessError, HoldoutGuard  # noqa: E402
from prineville_architecture import (  # noqa: E402
    UnidentifiedBuildingLoadShares,
    UnidentifiedChilledWaterConditioning,
    aggregate_campus,
    chilled_water_conditioning_water,
    load_architecture_registry,
)
from prineville_graybox import simulate, simulate_structural_reference_v1  # noqa: E402
from prineville_psychrometrics import mix_moist_air, state_from_t_rh  # noqa: E402
from prineville_structural_v1 import (  # noqa: E402
    ENHALPY_ABS_TOL_J_PER_KG,
    AmbiguousEffectivenessNameError,
    MissingReturnAirError,
    ReturnAirSpec,
    isothermal_humidification_request_is_infeasible,
)

P = 90100.0
REGISTRY_SHA256 = "1f87a1846aa8254c758ab11e3bd9b6f639e6c64bc551c36bcf8201bd65e78604"
CPU_STATUS_SHA256 = "1f57b210a63d375ce8eff7d5043756ffe6efe04e8a408bf9429bfd10096528d9"
H100_FREEZE_SHA256 = "a620d649a932f2388aa2f35bac2730eb75fe1dc74529668de4f30ee814600076"
HW_RESULT_SHA256 = "4e01139dd9365f62824ac00ff944468839e7873e47a5cea3df4714854af1b02c"
RA = ReturnAirSpec(T_C=35.0, rh_pct=15.0, provenance="DESIGN_REFERENCE_SCENARIO", label="test_dry")


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _w(tdb, rh, twb):
    return pd.DataFrame(
        {
            "timestamp_utc": [pd.Timestamp("2020-01-01T00:00:00Z")],
            "t_db_C": [tdb],
            "t_wb_C": [twb],
            "rh_pct": [rh],
            "pressure_Pa": [P],
        }
    )


def test_upstream_freezes_and_registry_unchanged():
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/analysis/FINAL_KESTREL_CPU_STATUS.json") == CPU_STATUS_SHA256
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/genai_h100/manifests/H100_COMPUTE_FINAL_FREEZE.json") == H100_FREEZE_SHA256
    freeze = json.loads(
        (REPO / "other_sources/nlr_esif_fullstack/heat_rejection_water/manifests/ESIF_HEAT_WATER_RESULT_FREEZE.json").read_text()
    )
    assert freeze["WUE_obs"] == 0.7
    assert _sha(ROOT / "config" / "prineville_architecture_states.yaml") == REGISTRY_SHA256


def test_canonical_simulate_is_not_v1():
    out = simulate(_w(0.0, 20.0, -5.0), 10.0)
    assert str(out.model_version.iloc[0]) == "canonical_legacy"
    assert float(out.evap_water_m3_per_h.iloc[0]) <= 1e-9
    with pytest.raises(TypeError, match="not a silent default"):
        simulate(_w(0.0, 20.0, -5.0), 10.0, model_version="structural_reference_v1")


def test_holdout_pandas_and_open_blocked(tmp_path):
    guard = HoldoutGuard(ROOT)
    protected = Path(guard.protected_files[0])
    with guard:
        with pytest.raises(HoldoutAccessError):
            protected.open("r")
        with pytest.raises(HoldoutAccessError):
            pd.read_csv(protected)
        v1 = simulate_structural_reference_v1(_w(22.0, 50.0, 14.0), 5.0, return_air=RA)
        assert np.isfinite(v1.air_stream_evaporated_water_m3_h.iloc[0])


def test_mixing_and_adiabatic_humidification():
    oa = state_from_t_rh(0.0, 20.0, P)
    ra = state_from_t_rh(35.0, 20.0, P)
    m = mix_moist_air(oa, ra, 0.3)
    assert abs(m.w - (0.3 * oa.w + 0.7 * ra.w)) < 1e-12
    assert abs(m.h_J_per_kg_da - (0.3 * oa.h_J_per_kg_da + 0.7 * ra.h_J_per_kg_da)) < 1e-4
    v1 = simulate_structural_reference_v1(_w(0.0, 20.0, -5.0), 10.0, return_air=RA)
    assert float(v1.air_stream_evaporated_water_m3_h.iloc[0]) > 0
    assert float(v1.t_supply_C.iloc[0]) < float(v1.mixed_air_T_C.iloc[0]) - 0.2
    assert float(v1.enthalpy_residual_J_per_kg.iloc[0]) <= ENHALPY_ABS_TOL_J_PER_KG
    assert str(v1.water_boundary.iloc[0]) == "AIR_STREAM_EVAPORATED_WATER"
    assert str(v1.calibration_status.iloc[0]) == "NOT_CALIBRATED"
    assert str(v1.validation_status.iloc[0]) == "PHYSICS_ONLY"


def test_dry_free_hot_dry_hot_humid_and_infeasible_isothermal():
    free = simulate_structural_reference_v1(_w(22.0, 50.0, 14.0), 10.0, return_air=RA)
    assert float(free.air_stream_evaporated_water_m3_h.iloc[0]) < 1e-6
    hot = simulate_structural_reference_v1(_w(35.0, 12.0, 16.0), 10.0, return_air=RA)
    assert float(hot.air_stream_evaporated_water_m3_h.iloc[0]) > 0
    assert float(hot.t_supply_C.iloc[0]) <= float(hot.mixed_air_T_C.iloc[0]) + 1e-6
    humid = simulate_structural_reference_v1(_w(32.0, 75.0, 27.0), 10.0, return_air=RA)
    assert float(humid.air_stream_evaporated_water_m3_h.iloc[0]) >= 0
    oa = state_from_t_rh(0.0, 20.0, P, t_wb_c=-5.0)
    inf = isothermal_humidification_request_is_infeasible(oa, 0.002, 0.85)
    assert inf.feasibility == "INFEASIBLE_UNDER_ASSUMED_ACTUATORS"


def test_return_air_required_and_sensitivity():
    with pytest.raises(MissingReturnAirError):
        simulate_structural_reference_v1(_w(0.0, 20.0, -5.0), 8.0)
    moist = ReturnAirSpec(T_C=35.0, rh_pct=40.0, provenance="DESIGN_REFERENCE_SCENARIO", label="moist")
    a = simulate_structural_reference_v1(_w(0.0, 20.0, -5.0), 10.0, return_air=RA)
    b = simulate_structural_reference_v1(_w(0.0, 20.0, -5.0), 10.0, return_air=moist)
    assert abs(float(a.mixed_air_w.iloc[0]) - float(b.mixed_air_w.iloc[0])) > 1e-8


def test_mist_fraction_not_thermal_effectiveness():
    with pytest.raises(AmbiguousEffectivenessNameError):
        simulate_structural_reference_v1(_w(35.0, 12.0, 16.0), 5.0, return_air=RA, mist_evaporation_fraction=0.85)
    src = (ROOT / "src" / "prineville_structural_v1.py").read_text()
    assert "EVAP_THERMAL_EFFECTIVENESS != MIST_WATER_EVAPORATED_FRACTION" in src


def test_chw_campus_and_no_production_regen():
    with pytest.raises(UnidentifiedChilledWaterConditioning):
        chilled_water_conditioning_water()
    with pytest.raises(UnidentifiedBuildingLoadShares):
        aggregate_campus({"PRN1": {"p_it_mw": 1.0, "water_conditioning_total_m3_h": 0.1, "conditioning_water_status": "ok"}}, None)
    for a in load_architecture_registry():
        assert a.load_share_numeric() is None
    pred = ROOT / "outputs" / "conditional_water_model.csv"
    assert pred.exists()
    freeze = ROOT / "outputs" / "structural_revision_v1" / "PRINEVILLE_STRUCTURAL_REFERENCE_V1_FREEZE.json"
    if freeze.exists():
        rec = json.loads(freeze.read_text())
        assert rec["NO_PARAMETER_FITTED"] is True
        assert rec["META_WATER_NOT_READ"] is True
        assert rec["NO_CANONICAL_PRODUCTION_OUTPUT_REGENERATED"] is True
        assert rec["architecture_registry_sha256"] == REGISTRY_SHA256
