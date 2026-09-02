"""Guards A–N for Forest City public validation. No calibration."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

FC = Path(__file__).resolve().parents[1]
REPO = FC.parent
sys.path.insert(0, str(FC / "src"))

from forest_city_controller import RH_MAX, T_INLET_MAX_F, forest_city_control_request  # noqa: E402
from forest_city_structural_reference_v1 import (  # noqa: E402
    AmbiguousDeltaTBoundaryError,
    AmbiguousEffectivenessNameError,
    IT_EQUIPMENT_DELTA_T_DESIGN_F,
    adiabatic_direct_evaporation,
    simulate_hour,
)
from psychrometrics_adapter import f_to_c, mix_moist_air, state_from_t_rh  # noqa: E402

P = 101325.0
EXPECTED = {
    "prineville_structural_v1.py": "f9649c489196cdc3e617f5b28574334aaaace5a94e7ade5ce461f6da22809a6a",
    "prineville_psychrometrics.py": "c10e1487a00ce32023bf3b630f915b2fe9ba303917951ff5f5bcbec3a3aafd30",
    "prineville_graybox.py": "8275ca5bfc23042e3af19b72f2adb260304ac95d692d0b3ecbcb526b020f0609",
    "prineville_architecture_states.yaml": "1f87a1846aa8254c758ab11e3bd9b6f639e6c64bc551c36bcf8201bd65e78604",
    "cpu": "1f57b210a63d375ce8eff7d5043756ffe6efe04e8a408bf9429bfd10096528d9",
    "h100": "a620d649a932f2388aa2f35bac2730eb75fe1dc74529668de4f30ee814600076",
    "esif": "4e01139dd9365f62824ac00ff944468839e7873e47a5cea3df4714854af1b02c",
}


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def test_A_prineville_frozen_hashes_unchanged():
    assert _sha(REPO / "Meta_Prineville_Oregon_v3/src/prineville_structural_v1.py") == EXPECTED["prineville_structural_v1.py"]
    assert _sha(REPO / "Meta_Prineville_Oregon_v3/src/prineville_psychrometrics.py") == EXPECTED["prineville_psychrometrics.py"]
    assert _sha(REPO / "Meta_Prineville_Oregon_v3/src/prineville_graybox.py") == EXPECTED["prineville_graybox.py"]
    assert _sha(REPO / "Meta_Prineville_Oregon_v3/config/prineville_architecture_states.yaml") == EXPECTED["prineville_architecture_states.yaml"]


def test_B_cpu_h100_esif_unchanged():
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/analysis/FINAL_KESTREL_CPU_STATUS.json") == EXPECTED["cpu"]
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/genai_h100/manifests/H100_COMPUTE_FINAL_FREEZE.json") == EXPECTED["h100"]
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/heat_rejection_water/manifests/ESIF_HEAT_WATER_RESULT_FREEZE.json") == EXPECTED["esif"]


def test_C_control_does_not_inherit_prn1_thresholds():
    src = (FC / "src" / "forest_city_controller.py").read_text()
    assert T_INLET_MAX_F == 85.0
    assert RH_MAX == pytest.approx(0.90)
    assert "T_DP_MIN_C = None" in src
    assert "classify_ocp_region" not in src
    assert "T_SA_MIX" not in src
    contract = json.loads((FC / "config" / "FOREST_CITY_REFERENCE_CONTROL_CONTRACT.json").read_text())
    assert "RH_MAX=0.65" in contract["explicitly_not_inherited_from_prn1"]


def test_D_35F_is_IT_not_effective():
    air = json.loads((FC / "config" / "FOREST_CITY_AIRFLOW_BOUNDARY_CONTRACT.json").read_text())
    assert air["final_state"]["IT_DELTA_T_DESIGN"] == "IDENTIFIED"
    assert air["final_state"]["FACILITY_EFFECTIVE_DELTA_T"] == "UNIDENTIFIED"
    assert IT_EQUIPMENT_DELTA_T_DESIGN_F == 35.0
    rec = simulate_hour(t_db_C=38.0, rh_pct=20.0, pressure_Pa=P, airflow_boundary="UNIDENTIFIED")
    assert rec["airflow_boundary"] == "UNIDENTIFIED"
    assert not np.isfinite(rec["air_stream_evaporated_water_m3_h"])
    with pytest.raises(AmbiguousDeltaTBoundaryError):
        simulate_hour(t_db_C=38.0, rh_pct=20.0, pressure_Pa=P, airflow_boundary="12K")


def test_E_design_vs_observed_distinct():
    c = json.loads((FC / "config" / "FOREST_CITY_REFERENCE_CONTROL_CONTRACT.json").read_text())
    assert c["regions"][0]["design_vs_observed"] == "DESIGN_SPEC"
    assert "OPERATOR_OBSERVED" in c["regions"][1]["design_vs_observed"]


def test_F_G_events_and_summer_cannot_modify_controller(tmp_path):
    contract = FC / "config" / "FOREST_CITY_REFERENCE_CONTROL_CONTRACT.json"
    before = _sha(contract)
    ctrl = _sha(FC / "src" / "forest_city_controller.py")
    # simulate reading event outputs if present
    ev = FC / "outputs" / "control_validation" / "HISTORICAL_EVENT_VALIDATION.json"
    if ev.exists():
        rec = json.loads(ev.read_text())
        assert rec.get("no_retune") is True
    sm = FC / "outputs" / "control_validation" / "SUMMER_2012_DX_VALIDATION.json"
    if sm.exists():
        rec = json.loads(sm.read_text())
        assert rec.get("controller_not_modified") is True
    assert _sha(contract) == before
    assert _sha(FC / "src" / "forest_city_controller.py") == ctrl


def test_H_annual_water_not_used_to_fit():
    src = (FC / "src" / "forest_city_structural_reference_v1.py").read_text()
    assert "NOT_CALIBRATED" in src
    audit = FC / "outputs" / "annual_accounting" / "FOREST_CITY_LONG_RUN_WATER_AUDIT.json"
    if audit.exists():
        rec = json.loads(audit.read_text())
        assert rec["not_used_to_fit_2012_controller"] is True
        assert rec["causal_claim"] is False


def test_I_later_campus_not_2012_architecture():
    yml = (FC / "config" / "forest_city_facility_registry.yaml").read_text()
    assert "Do not assume 2012 Building-1 architecture" in yml
    assert "FRC4_COLD_STORAGE" in yml


def test_J_intensity_not_called_WUE():
    p = FC / "data" / "processed" / "FOREST_CITY_ANNUAL_ELECTRICITY.csv"
    if not p.exists():
        pytest.skip("annual series not built")
    inten = pd.read_csv(FC / "outputs" / "annual_accounting" / "FOREST_CITY_SITE_WITHDRAWAL_INTENSITY.csv")
    assert "not_WUE" in inten.columns
    assert (inten["not_WUE"] == True).all()  # noqa: E712
    assert "SITE_WITHDRAWAL_INTENSITY" in set(inten["intensity_name"])


def test_K_municipal_not_meta_consumption():
    p = FC / "outputs" / "annual_accounting" / "FOREST_CITY_MUNICIPAL_SOURCE_ACCOUNTING.csv"
    if not p.exists():
        pytest.skip("municipal accounting not built")
    d = pd.read_csv(p)
    assert d["not_causal_flow"].all()


def test_L_permits_not_measured_load():
    p = FC / "outputs" / "permit_audit" / "FOREST_CITY_PUBLIC_PERMIT_INVENTORY.csv"
    if not p.exists():
        pytest.skip("permit inventory not built")
    d = pd.read_csv(p)
    assert d["do_not_treat_as_measured_load"].all()


def test_M_N_no_invented_customer_data_unknown_remains():
    p = FC / "outputs" / "permit_audit" / "FOREST_CITY_PUBLIC_PERMIT_INVENTORY.csv"
    if not p.exists():
        pytest.skip("permit inventory not built")
    inv = pd.read_csv(p)
    assert (inv["permit_number"] == "UNIDENTIFIED").all()
    air = json.loads((FC / "config" / "FOREST_CITY_AIRFLOW_BOUNDARY_CONTRACT.json").read_text())
    assert air["final_state"]["FACILITY_EFFECTIVE_DELTA_T"] == "UNIDENTIFIED"


def test_psychrometric_equivalence_mixing_and_adiabatic():
    sys.path.insert(0, str(REPO / "Meta_Prineville_Oregon_v3" / "src"))
    from prineville_psychrometrics import mix_moist_air as mix_p
    from prineville_psychrometrics import state_from_t_rh as sfr_p
    from prineville_psychrometrics import state_on_constant_enthalpy as soce_p

    oa = state_from_t_rh(30.0, 40.0, P)
    ra = state_from_t_rh(48.0, 20.0, P)
    m1 = mix_moist_air(oa, ra, 0.4)
    m2 = mix_p(sfr_p(30.0, 40.0, P), sfr_p(48.0, 20.0, P), 0.4)
    assert abs(m1.w - m2.w) < 1e-12
    assert abs(m1.h_J_per_kg_da - m2.h_J_per_kg_da) < 1e-4
    supply, dw, res = adiabatic_direct_evaporation(oa, spray_on=True, evap_thermal_effectiveness=1.0, t_cool_target_c=29.44)
    assert dw >= -1e-15
    assert supply.T_C <= oa.T_C + 1e-6
    assert res < 80.0
    tgt = soce_p(oa, supply.T_C)
    assert abs(tgt.w - supply.w) < 1e-8


def test_july1_and_june25_qualitative():
    # operator snapshots as outdoor state
    jul = simulate_hour(t_db_C=f_to_c(102.0), rh_pct=26.0, pressure_Pa=P, evap_thermal_effectiveness=1.0)
    assert jul["dx_required"] is False
    assert jul["spray_enabled"] is True
    jun = simulate_hour(t_db_C=f_to_c(68.0), rh_pct=97.0, pressure_Pa=P, evap_thermal_effectiveness=1.0)
    assert jun["dx_required"] is False
    assert jun["oa_fraction"] < 0.999 or jun["rh_supply"] <= 0.90 + 1e-3
    with pytest.raises(AmbiguousEffectivenessNameError):
        simulate_hour(t_db_C=38.0, rh_pct=20.0, pressure_Pa=P, mist_evaporation_fraction=0.85)
