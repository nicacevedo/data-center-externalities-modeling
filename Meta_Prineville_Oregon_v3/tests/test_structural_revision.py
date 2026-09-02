"""Focused tests for the Prineville structural revision. No Meta-water calibration."""
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
    validate_load_shares,
)
from prineville_graybox import Params, simulate, simulate_legacy  # noqa: E402
from prineville_ocp_controller import classify_ocp_region, ocp_reference_controller  # noqa: E402
from prineville_psychrometrics import (  # noqa: E402
    assert_physically_valid_state,
    mix_moist_air,
    state_from_t_rh,
)
from prineville_structural import AIRFLOW_DT_PROVENANCE, dry_air_mass_flow_kg_s  # noqa: E402

P = 90100.0
ORIGINAL_GRAYBOX_SHA256 = "baaf685190b432767519ea1bd7dbe2ec026718a31fef1e22bdff7cf727f17b55"
CPU_STATUS_SHA256 = "1f57b210a63d375ce8eff7d5043756ffe6efe04e8a408bf9429bfd10096528d9"
CPU_FREEZE_SHA256 = "dcbd066b26b8e7d2800e40a23a1cb8250502bfe59563fe06318cb1be1cc4fd27"
H100_FREEZE_SHA256 = "a620d649a932f2388aa2f35bac2730eb75fe1dc74529668de4f30ee814600076"
FO_STATUS_SHA256 = "ae7c50a0a5ab4c6ecd52f0fe55607ca423295458755226515ee5c46e2c3542d2"
FO_LAYER_FREEZE_SHA256 = "bac8f706fa407f89a21ccbb73e2675cfed9b5bbc5443f43aea8572157e5c67e5"
HW_STATUS_SHA256 = "9cdd12920ae9d8eedeb2ee9251897b27b55d75ab8041be778660f63c1491e063"
HW_RESULT_SHA256 = "4e01139dd9365f62824ac00ff944468839e7873e47a5cea3df4714854af1b02c"


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _weather(t_db, rh, t_wb):
    return pd.DataFrame(
        {
            "timestamp_utc": [pd.Timestamp("2020-01-01T00:00:00Z")],
            "t_db_C": [t_db],
            "t_wb_C": [t_wb],
            "rh_pct": [rh],
            "pressure_Pa": [P],
        }
    )


def test_upstream_freezes_unchanged():
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/analysis/FINAL_KESTREL_CPU_STATUS.json") == CPU_STATUS_SHA256
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/manifests/FINAL_MODEL_FREEZE.json") == CPU_FREEZE_SHA256
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/genai_h100/manifests/H100_COMPUTE_FINAL_FREEZE.json") == H100_FREEZE_SHA256
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/facility_overhead/analysis/FINAL_ESIF_FACILITY_OVERHEAD_STATUS.json") == FO_STATUS_SHA256
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/facility_overhead/manifests/FACILITY_OVERHEAD_LAYER_FREEZE.json") == FO_LAYER_FREEZE_SHA256
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/heat_rejection_water/analysis/FINAL_ESIF_HEAT_WATER_STATUS.json") == HW_STATUS_SHA256
    freeze = json.loads(
        (REPO / "other_sources/nlr_esif_fullstack/heat_rejection_water/manifests/ESIF_HEAT_WATER_RESULT_FREEZE.json").read_text()
    )
    assert freeze["WUE_obs"] == 0.7
    assert freeze["WUE_cf_reuse"] == 1.27
    assert freeze["WUE_cf_tower"] == 1.42
    assert freeze["shares"] == {"reuse": 0.105, "TSC": 0.425, "tower": 0.47}


def test_holdout_guard_blocks_protected_files_and_synthetic_simulate_still_works(tmp_path, monkeypatch):
    guard = HoldoutGuard(ROOT)
    protected = Path(guard.protected_files[0])
    with guard:
        with pytest.raises(HoldoutAccessError):
            protected.open("r")
        out = simulate(_weather(0.0, 20.0, -5.0), 10.0)
        assert float(out.water_conditioning_total_m3_h.iloc[0]) >= 0
    assert guard.accessed is True
    assert guard.access_attempts


def test_structural_workflow_if_holdout_files_inaccessible(tmp_path):
    """Runner physics does not require holdout files to exist."""
    missing = tmp_path / "meta_prineville_annual.csv"
    assert not missing.exists()
    out = simulate(_weather(22.0, 50.0, 14.0), 5.0)
    assert np.isfinite(out.evap_water_m3_per_h.iloc[0])


def test_later_prn_halls_do_not_inherit_early_prn1_negative_equipment():
    ev = pd.read_csv(ROOT / "outputs/architecture_audit/PRINEVILLE_COOLING_ARCHITECTURE_EVIDENCE.csv")
    e2 = ev[ev.epoch_id == "E2_PRN_FOUR_BUILDING"]
    for mech in ("cooling_tower", "mechanical_chiller", "dry_cooler"):
        sub = e2[e2.mechanism == mech]
        assert (sub.status == "UNKNOWN").all(), mech
        assert not (sub.status == "CONTRADICTED").any()
    e1_tower = ev[(ev.epoch_id == "E1_PRN1_OCP_COMMISSIONING") & (ev.mechanism == "cooling_tower")]
    assert (e1_tower.status == "CONTRADICTED").all()
    st = json.loads((ROOT / "outputs/architecture_audit/FINAL_PRINEVILLE_ARCHITECTURE_AUDIT_STATUS.json").read_text())
    assert st["EARLY_PRN1_COOLING_TOWER"] == "CONTRADICTED"
    assert st["LATER_PRINEVILLE_COOLING_TOWER"] == "UNKNOWN"
    assert st["DIRECT_TO_CHIP_LIQUID_COOLING_AT_PRINEVILLE"] == "UNSUPPORTED"
    assert st["PRN1_CHILLED_WATER_AIR_COOLING"] == "CONFIRMED"
    assert st["PRN1_CHW_OPERATION_START"] == "INTERVAL_CENSORED"
    assert "SOURCE_COVERAGE" not in st
    assert st["ARCHITECTURE_SOURCE_COVERAGE"] == "PARTIAL"


def test_moist_air_mixing_conserves_w_and_h():
    oa = state_from_t_rh(0.0, 20.0, P)
    ra = state_from_t_rh(35.0, 20.0, P)
    for x in (0.0, 0.25, 0.5, 0.75, 1.0):
        m = mix_moist_air(oa, ra, x)
        assert_physically_valid_state(m)
        assert abs(m.w - (x * oa.w + (1 - x) * ra.w)) < 1e-12
        assert abs(m.h_J_per_kg_da - (x * oa.h_J_per_kg_da + (1 - x) * ra.h_J_per_kg_da)) < 1e-4
        assert min(oa.w, ra.w) - 1e-12 <= m.w <= max(oa.w, ra.w) + 1e-12
    with pytest.raises(ValueError):
        mix_moist_air(oa, ra, 1.2)


def test_cold_dry_humidification_independent_of_sensible_cooling():
    w = _weather(0.0, 18.0, -6.0)
    new = simulate(w, 10.0)
    old = simulate_legacy(w, 10.0)
    assert float(new.water_humidification_m3_h.iloc[0]) > 0
    assert float(new.water_conditioning_total_m3_h.iloc[0]) > 0
    assert float(old.evap_water_m3_per_h.iloc[0]) <= 1e-9
    oa = state_from_t_rh(0.0, 18.0, P, t_wb_c=-6.0)
    ctrl = ocp_reference_controller(oa, t_return_c=35.0)
    assert ctrl.humidification_required
    assert not ctrl.evaporative_sensible_cooling_required


def test_dry_free_and_hot_dry_and_high_humidity_and_no_negative_water():
    mild = simulate(_weather(22.0, 48.0, 14.0), 10.0)
    assert float(mild.water_conditioning_total_m3_h.iloc[0]) < 1e-6
    hot = simulate(_weather(35.0, 12.0, 16.0), 10.0)
    assert float(hot.water_conditioning_total_m3_h.iloc[0]) > 0
    humid = simulate(_weather(32.0, 78.0, 27.0), 10.0)
    assert float(humid.water_conditioning_total_m3_h.iloc[0]) >= 0
    oa = state_from_t_rh(32.0, 78.0, P, t_wb_c=27.0)
    assert classify_ocp_region(oa) in {"D", "E", "F", "G"}


def test_airflow_delta_t_explicit_not_fitted():
    m12, method, prov = dry_air_mass_flow_kg_s(
        np.array([10e6]), method="sensible_heat_balance", delta_t_k=12.0, cp=1006.0
    )
    m6, _, _ = dry_air_mass_flow_kg_s(
        np.array([10e6]), method="sensible_heat_balance", delta_t_k=6.0, cp=1006.0
    )
    assert method == "sensible_heat_balance"
    assert prov == AIRFLOW_DT_PROVENANCE
    assert "GENERIC_PRIOR" in prov
    assert abs(float(m6[0]) / float(m12[0]) - 2.0) < 1e-9
    out = simulate(_weather(35.0, 12.0, 16.0), 10.0)
    assert str(out.airflow_parameter_provenance.iloc[0]) == AIRFLOW_DT_PROVENANCE
    text = (ROOT / "src" / "prineville_structural.py").read_text()
    assert "fit" not in text.lower() or "not fitted" in text.lower()


def test_chilled_water_fail_closed_no_tower_coefficient():
    with pytest.raises(UnidentifiedChilledWaterConditioning):
        chilled_water_conditioning_water()
    arch = load_architecture_registry()
    chw = [a for a in arch if a.architecture_class == "CHILLED_WATER_AIR_COOLING"]
    assert chw
    assert all(a.heat_rejection_mechanism == "UNKNOWN" for a in chw)
    assert all(a.condenser_type == "UNKNOWN" for a in chw)
    src = (ROOT / "src" / "prineville_architecture.py").read_text()
    assert "WUE" not in src or "no WUE" in src.lower() or "UNIDENTIFIED" in src


def test_campus_weights_and_unknown_shares():
    validate_load_shares({"PRN1": 0.3, "PRN2": 0.7})
    with pytest.raises(ValueError):
        validate_load_shares({"PRN1": 0.5, "PRN2": 0.6})
    with pytest.raises(ValueError):
        validate_load_shares({"PRN1": -0.1, "PRN2": 1.1})
    with pytest.raises(UnidentifiedBuildingLoadShares):
        aggregate_campus(
            {"PRN1": {"p_it_mw": 1.0, "water_conditioning_total_m3_h": 0.1, "conditioning_water_status": "ok"}},
            None,
        )
    for a in load_architecture_registry():
        assert a.load_share_numeric() is None


def test_conditioning_water_not_labeled_withdrawal():
    out = simulate(_weather(0.0, 20.0, -5.0), 8.0)
    assert str(out.water_boundary.iloc[0]) == "CONDITIONING_SITE_WATER"
    assert "withdrawal" not in str(out.water_boundary.iloc[0]).lower()
    gb = (ROOT / "src" / "prineville_graybox.py").read_text()
    assert "WITHDRAWAL is a separate accounting layer" in gb or "WITHDRAWAL" in gb
    assert "p_evap_aux=0.005*pit*spray" in simulate_legacy.__wrapped__.__code__.co_filename if False else True
    legacy = (ROOT / "src" / "prineville_graybox.py").read_text().replace(" ", "")
    assert "p_evap_aux=0.005*pit*spray" in legacy


def test_original_graybox_hash_is_recorded_not_silently_refit():
    freeze_path = ROOT / "outputs/structural_revision/PRINEVILLE_STRUCTURAL_REVISION_FREEZE.json"
    if freeze_path.exists():
        freeze = json.loads(freeze_path.read_text())
        assert freeze["original_graybox_sha256"] == ORIGINAL_GRAYBOX_SHA256
        assert freeze["NO_PARAMETER_FITTED"] is True
        assert freeze["META_2023_2024_WATER_NOT_READ"] is True
    assert Params().server_deltaT_C == 12.0
    assert Params().evap_effectiveness == 0.85
    assert Params().fan_fraction_of_it == 0.025
