"""Guards for the Prineville architecture audit. Does not refit models."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "architecture_audit"
GRAYBOX = ROOT / "src" / "prineville_graybox.py"
AUDIT_PY = ROOT / "scripts" / "run_architecture_audit.py"

GRAYBOX_SHA256 = "baaf685190b432767519ea1bd7dbe2ec026718a31fef1e22bdff7cf727f17b55"
CPU_STATUS_SHA256 = "1f57b210a63d375ce8eff7d5043756ffe6efe04e8a408bf9429bfd10096528d9"
CPU_FREEZE_SHA256 = "dcbd066b26b8e7d2800e40a23a1cb8250502bfe59563fe06318cb1be1cc4fd27"
H100_FREEZE_SHA256 = "a620d649a932f2388aa2f35bac2730eb75fe1dc74529668de4f30ee814600076"
FO_STATUS_SHA256 = "ae7c50a0a5ab4c6ecd52f0fe55607ca423295458755226515ee5c46e2c3542d2"
FO_LAYER_FREEZE_SHA256 = "bac8f706fa407f89a21ccbb73e2675cfed9b5bbc5443f43aea8572157e5c67e5"


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _j(p: Path) -> dict:
    return json.loads(p.read_text())


def test_frozen_cpu_h100_fo_unchanged():
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/analysis/FINAL_KESTREL_CPU_STATUS.json") == CPU_STATUS_SHA256
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/manifests/FINAL_MODEL_FREEZE.json") == CPU_FREEZE_SHA256
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/genai_h100/manifests/H100_COMPUTE_FINAL_FREEZE.json") == H100_FREEZE_SHA256
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/facility_overhead/analysis/FINAL_ESIF_FACILITY_OVERHEAD_STATUS.json") == FO_STATUS_SHA256
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/facility_overhead/manifests/FACILITY_OVERHEAD_LAYER_FREEZE.json") == FO_LAYER_FREEZE_SHA256


def test_esif_heat_water_numerics_unchanged():
    freeze = _j(REPO / "other_sources/nlr_esif_fullstack/heat_rejection_water/manifests/ESIF_HEAT_WATER_RESULT_FREEZE.json")
    assert freeze["WUE_obs"] == 0.7
    assert freeze["WUE_cf_reuse"] == 1.27
    assert freeze["WUE_cf_tower"] == 1.42
    assert freeze["shares"] == {"reuse": 0.105, "TSC": 0.425, "tower": 0.47}
    acct = _j(REPO / "other_sources/nlr_esif_fullstack/heat_rejection_water/analysis/FIRST_YEAR_WATER_ACCOUNTING_REPRODUCTION.json")
    assert acct["W_obs_m3_from_WUE"] == 5443.2
    assert acct["FIRST_YEAR_ARITHMETIC_CONSISTENCY"] == "PASS"
    st = _j(REPO / "other_sources/nlr_esif_fullstack/heat_rejection_water/analysis/FINAL_ESIF_HEAT_WATER_STATUS.json")
    assert st["TSC_CAUSAL_TREATMENT_EFFECT"] == "NOT_IDENTIFIED"
    assert st["ESIF_VS_LEI_MASANET"] == "PARTIAL_INDEPENDENT_EXTERNAL_STRUCTURAL_VALIDATION"


def test_graybox_coefficients_and_file_hash_unchanged():
    assert _sha(GRAYBOX) == GRAYBOX_SHA256
    text = GRAYBOX.read_text()
    assert "supply_target_C: float = 25.0" in text
    assert "evap_effectiveness: float = 0.85" in text
    assert "fan_fraction_of_it: float = 0.025" in text
    assert "other_facility_fraction_of_it: float = 0.035" in text
    assert "p_evap_aux=0.005*pit*spray" in text.replace(" ", "")


def test_audit_did_not_use_holdout_or_meta_water_for_structure():
    src = AUDIT_PY.read_text()
    assert "LightGBM" not in src
    assert "build_groundwater_context" not in src
    st = _j(OUT / "FINAL_PRINEVILLE_ARCHITECTURE_AUDIT_STATUS.json")
    assert st["meta_2023_2024_water_not_used_for_structure"] is True
    assert st["fitted_or_refit_graybox"] is False
    assert st["groundwater_run"] is False
    assert st["emissions_run"] is False
    assert "holdout" not in pd.read_csv(OUT / "PRINEVILLE_GRAYBOX_STRUCTURE_GAP_MATRIX.csv").status.str.lower().to_string()


def test_no_esif_or_lei_coefficient_transfer():
    inv = pd.read_csv(OUT / "PRINEVILLE_PARAMETER_PROVENANCE.csv", dtype=str)
    esif = inv[inv.name == "ESIF_WUE_0.70"].iloc[0]
    assert esif.recommended_disposition == "UNSUPPORTED_REMOVE_CANDIDATE"
    assert (inv.lei_masanet == "no").all()


def test_fleet_not_promoted_and_capability_not_installed():
    ev = pd.read_csv(OUT / "PRINEVILLE_COOLING_ARCHITECTURE_EVIDENCE.csv")
    fleet = ev[ev.source_scope == "META_FLEET_CONTEXT"]
    assert not (fleet.status == "CONFIRMED").any()
    iec = ev[ev.mechanism == "indirect_evaporative"]
    assert (iec.status == "UNSUPPORTED").all()
    splc = ev[ev.mechanism == "SPLC"]
    assert not (splc.status.isin(["CONFIRMED", "SUPPORTED"])).any()
    towers = ev[ev.mechanism == "cooling_tower"]
    assert not (towers.status == "CONFIRMED").any()
    chillers = ev[(ev.mechanism == "mechanical_chiller") & (ev.status == "CONFIRMED")]
    assert (chillers.building == "PRN1").all()
    assert "CAPABILITY" in ev[ev.mechanism == "indirect_evaporative"].reason.iloc[0]


def test_every_architecture_claim_has_source_scope_confidence():
    ev = pd.read_csv(OUT / "PRINEVILLE_COOLING_ARCHITECTURE_EVIDENCE.csv")
    for col in ("source", "source_scope", "status", "confidence"):
        assert ev[col].notna().all(), col
    assert set(ev.source_scope.unique()) <= {"PRINEVILLE_SPECIFIC", "META_FLEET_CONTEXT", "GENERIC"}


def test_first_order_terms_have_provenance():
    inv = pd.read_csv(OUT / "CURRENT_PRINEVILLE_MODEL_INVENTORY.csv")
    assert inv.source_provenance.notna().all()
    assert inv.scientific_status.notna().all()
    gap = pd.read_csv(OUT / "PRINEVILLE_GRAYBOX_STRUCTURE_GAP_MATRIX.csv")
    assert "REQUIRED_MISSING" in set(gap.status)
    assert "EPOCH_MISMATCH" in set(gap.status)
    st = _j(OUT / "FINAL_PRINEVILLE_ARCHITECTURE_AUDIT_STATUS.json")
    assert st["STRUCTURAL_REVISION_GATE"] == "MINIMAL_STRUCTURAL_REVISION_REQUIRED"


def test_no_production_prediction_files_rewritten_by_audit():
    # Audit writes only under outputs/architecture_audit plus docs/generic spec.
    pred = ROOT / "outputs" / "conditional_water_model.csv"
    assert pred.exists()
    # gray-box source hash already checked; this file must not be listed as an audit output
    cleanup = _j(OUT / "ESIF_SEMANTIC_CLEANUP_FILES.json")
    assert "conditional_water_model.csv" not in json.dumps(cleanup)
    assert cleanup["numerical_esif_outputs_changed"] is False
    assert cleanup["experiment_rerun"] is False
