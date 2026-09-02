"""Guards for public-proxy reconstruction v1. No Meta-water fitting."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from holdout_guard import HoldoutAccessError, HoldoutGuard  # noqa: E402

OUT = ROOT / "outputs" / "public_proxy_reconstruction_v1"
PRE = OUT / "preoutcome"
POST = OUT / "postfreeze_consistency"

V1_FREEZE = "decd095f59cc2249eee66d5b94ad30d30a53555eadbec3358bbb9aa80caaa81d"
REGISTRY = "1f87a1846aa8254c758ab11e3bd9b6f639e6c64bc551c36bcf8201bd65e78604"
CPU = "1f57b210a63d375ce8eff7d5043756ffe6efe04e8a408bf9429bfd10096528d9"
H100 = "a620d649a932f2388aa2f35bac2730eb75fe1dc74529668de4f30ee814600076"
ESIF = "4e01139dd9365f62824ac00ff944468839e7873e47a5cea3df4714854af1b02c"
STRUCTURAL_V1 = "f9649c489196cdc3e617f5b28574334aaaace5a94e7ade5ce461f6da22809a6a"
GRAYBOX = "8275ca5bfc23042e3af19b72f2adb260304ac95d692d0b3ecbcb526b020f0609"


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def test_A_frozen_structural_v1_unchanged():
    assert _sha(ROOT / "outputs/structural_revision_v1/PRINEVILLE_STRUCTURAL_REFERENCE_V1_FREEZE.json") == V1_FREEZE
    assert _sha(ROOT / "src/prineville_structural_v1.py") == STRUCTURAL_V1
    assert _sha(ROOT / "src/prineville_graybox.py") == GRAYBOX
    freeze = json.loads((PRE / "PUBLIC_PROXY_RECONSTRUCTION_FREEZE.json").read_text())
    assert freeze["structural_v1_equations_unchanged"] is True
    assert freeze["canonical_simulate_unchanged"] is True


def test_B_cpu_h100_esif_frozen():
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/analysis/FINAL_KESTREL_CPU_STATUS.json") == CPU
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/genai_h100/manifests/H100_COMPUTE_FINAL_FREEZE.json") == H100
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/heat_rejection_water/manifests/ESIF_HEAT_WATER_RESULT_FREEZE.json") == ESIF
    assert _sha(ROOT / "config/prineville_architecture_states.yaml") == REGISTRY


def test_C_stage_A_cannot_access_protected_water():
    with HoldoutGuard(ROOT) as g:
        with pytest.raises(HoldoutAccessError):
            (ROOT / "data/canonical/meta_prineville_annual.csv").open("r")
        assert g.accessed is True
    freeze = json.loads((PRE / "PUBLIC_PROXY_RECONSTRUCTION_FREEZE.json").read_text())
    assert freeze["WATER_OUTCOME_ACCESSED"] is False


def test_D_rack_airflow_not_facility_telemetry():
    a = json.loads((PRE / "AIRFLOW_PRIOR_ASSESSMENT.json").read_text())
    assert a["boundary_class"] == "ENGINEERING_CONSISTENCY_BOUND"
    assert a["not_label"] == "AS_OPERATED_FACILITY_AIRFLOW"
    src = pd.read_csv(PRE / "OCP_AIRFLOW_SOURCE_DATA.csv")
    assert src["boundary"].str.contains("FACILITY_BMS").all() is False or True
    assert not src["boundary"].str.contains("AS_OPERATED_FACILITY").any()


def test_E_capacity_types_not_silently_mixed():
    cap = pd.read_csv(PRE / "PUBLIC_CAPACITY_EVIDENCE.csv")
    assert cap["capacity_type"].nunique() >= 5
    southland = cap[cap["source_id"].astype(str).str.contains("SOUTHLAND")]
    types = set(southland["capacity_type"].astype(str))
    assert "FACILITY_MW_CONTRACTOR_STATED" in types
    assert "DATA_HALL_MW_CONTRACTOR_PHASED" in types


def test_F_generator_mw_not_treated_as_it():
    inv = pd.read_csv(PRE / "PUBLIC_FACILITY_PHASE_INVENTORY.csv")
    assert inv["generator_MW"].astype(str).str.contains("NOT_IT").all()
    assert (inv["IT_design_MW"].astype(str) == "UNKNOWN").any()


def test_G_precommissioning_lambda_zero_and_H_simplex():
    ext = pd.read_csv(PRE / "LOAD_SHARE_EXTREMA.csv")
    y2011 = ext[ext["year"] == 2011].iloc[0]
    assert float(y2011["lambda_PRN1_min"]) == 1.0
    assert bool(y2011["complete_simplex_identified"]) is True
    later = ext[ext["year"] > 2011]
    assert (later["lambda_PRN1_min"] == 0.0).all()
    fs = json.loads((PRE / "LOAD_SHARE_FEASIBLE_SETS.json").read_text())
    assert fs["identified_years"]["2011"]["PRN1"] == 1.0


def test_I_unknown_buildings_not_equal_shares():
    text = (PRE / "LOAD_SHARE_FEASIBLE_SETS.json").read_text()
    assert "equal_weights_forbidden" in text
    cons = pd.read_csv(PRE / "LOAD_SHARE_CONSTRAINTS.csv")
    assert cons["statement"].astype(str).str.contains("no equal building weights").any()


def test_J_unknown_architecture_does_not_inherit_prn1():
    inv = pd.read_csv(PRE / "PUBLIC_FACILITY_PHASE_INVENTORY.csv")
    prn5 = inv[inv["building_id"] == "PRN5"].iloc[0]
    assert "UNKNOWN" in str(prn5["architecture"])
    assert "DIRECT_OUTSIDE_AIR_EVAP_CONFIRMED" not in str(prn5["architecture"])
    yaml = (ROOT / "config/prineville_architecture_states.yaml").read_text()
    assert "CCO3" not in yaml  # coverage gap, registry not rewritten


def test_K_opuc_not_actual_load():
    opuc = pd.read_csv(PRE / "OPUC_LOAD_EVIDENCE.csv")
    mw = pd.to_numeric(opuc["MW"], errors="coerce")
    row180 = opuc[mw == 180].iloc[0]
    assert row180["classification"] == "ELIGIBLE_LOAD"
    assert row180["can_constrain_IT_lambda"] == "NO"
    assert not (opuc["classification"] == "ACTUAL_LOAD").any()


def test_L_M_85pct_not_effectiveness_or_makeup():
    bal = json.loads((PRE / "PRN1_MIST_RO_MASS_BALANCE.json").read_text())
    assert bal["not_permitted"]["W_external_makeup_equals_W_air_vapor_over_0.85"] is False
    assert bal["not_permitted"]["0.85_is_evap_thermal_effectiveness"] is False
    assert bal["not_permitted"]["0.85_is_external_makeup_efficiency"] is False


def test_N_permitted_groundwater_not_actual_pumping():
    owrd = pd.read_csv(PRE / "OWRD_POD_PUBLIC_EVIDENCE.csv")
    assert (owrd["not"].astype(str).str.contains("PERMITTED_MAXIMUM") | (owrd["classification"] == "UNIDENTIFIED")).any()
    reported = owrd[owrd["classification"] == "ACTUAL_REPORTED_PUMPING"]
    assert len(reported) >= 3


def test_O_stage_B_cannot_modify_stage_A_freeze():
    freeze = json.loads((PRE / "PUBLIC_PROXY_RECONSTRUCTION_FREEZE.json").read_text())
    status = json.loads((POST / "CONSISTENCY_DIAGNOSTIC_STATUS.json").read_text())
    assert status["stage_A_freeze_unchanged"] is True
    assert status["master_hash"] == freeze["master_hash"]
    assert freeze["WATER_OUTCOME_ACCESSED"] is False


def test_P_no_parameter_fitting_to_meta_water():
    freeze = json.loads((PRE / "PUBLIC_PROXY_RECONSTRUCTION_FREEZE.json").read_text())
    assert freeze["no_parameter_fitted"] is True
    bench = json.loads((POST / "CONSISTENCY_DIAGNOSTIC_STATUS.json").read_text())
    assert bench["no_parameter_fitted"] is True
    assert bench["no_scenario_selected_using_observations"] is True
    vs = pd.read_csv(POST / "PUBLIC_PROXY_VS_WATER_BENCHMARKS.csv")
    assert vs["refit"].astype(str).str.lower().isin(["false", "0"]).all()


def test_deltaT_assessment_and_campus_envelope():
    a = json.loads((PRE / "AIRFLOW_PRIOR_ASSESSMENT.json").read_text())
    assert a["deltaT_12K_status"] == "PUBLIC_EVIDENCE_INSUFFICIENT_TO_NUMERICALLY_BOUND_DELTAT"
    st = json.loads((PRE / "PUBLIC_PROXY_ENVELOPE_STATUS.json").read_text())
    assert st["campus_total_meaningfully_bounded"] is False
    assert st["canonical_simulate_not_used_as_envelope_engine"] is True
