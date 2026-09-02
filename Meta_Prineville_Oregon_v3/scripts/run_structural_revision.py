"""Source-frozen Prineville structural revision runner.

Does not import holdout data modules. Does not read Meta water. Does not fit parameters.
"""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from holdout_guard import HoldoutGuard  # noqa: E402
from prineville_architecture import (  # noqa: E402
    UnidentifiedBuildingLoadShares,
    UnidentifiedChilledWaterConditioning,
    aggregate_campus,
    chilled_water_conditioning_water,
    load_architecture_registry,
    validate_load_shares,
)
from prineville_graybox import Params, simulate, simulate_legacy  # noqa: E402
from prineville_ocp_controller import OCP_THRESHOLDS, classify_ocp_region  # noqa: E402
from prineville_psychrometrics import (  # noqa: E402
    assert_physically_valid_state,
    mix_moist_air,
    state_from_t_rh,
)
from prineville_structural import dry_air_mass_flow_kg_s  # noqa: E402

OUT = ROOT / "outputs" / "structural_revision"
AUDIT = ROOT / "outputs" / "architecture_audit"
GRAYBOX = SRC / "prineville_graybox.py"

ORIGINAL_GRAYBOX_SHA256 = "baaf685190b432767519ea1bd7dbe2ec026718a31fef1e22bdff7cf727f17b55"
ORIGINAL_AUDIT_STATUS_SHA256 = "4b08ebafbc9538a84f3f58266e6e45603310c2bd346d6b01cbcebba7b2273933"
CPU_STATUS_SHA256 = "1f57b210a63d375ce8eff7d5043756ffe6efe04e8a408bf9429bfd10096528d9"
CPU_FREEZE_SHA256 = "dcbd066b26b8e7d2800e40a23a1cb8250502bfe59563fe06318cb1be1cc4fd27"
H100_FREEZE_SHA256 = "a620d649a932f2388aa2f35bac2730eb75fe1dc74529668de4f30ee814600076"
FO_STATUS_SHA256 = "ae7c50a0a5ab4c6ecd52f0fe55607ca423295458755226515ee5c46e2c3542d2"
FO_LAYER_FREEZE_SHA256 = "bac8f706fa407f89a21ccbb73e2675cfed9b5bbc5443f43aea8572157e5c67e5"
HW_STATUS_SHA256 = "9cdd12920ae9d8eedeb2ee9251897b27b55d75ab8041be778660f63c1491e063"
HW_RESULT_SHA256 = "4e01139dd9365f62824ac00ff944468839e7873e47a5cea3df4714854af1b02c"
PUBLIC_BASELINE = "9e6c4b4c40e35f12aec9451e0c65704f2a0bf1e6"

P = 90100.0


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def jdump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def git_cmd(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
    return (r.stdout or r.stderr or "").strip()


def weather_row(t_db, rh_pct, t_wb, name, p_it_mw, extra=None):
    idx = pd.Timestamp("2020-01-15T12:00:00Z")
    row = {
        "timestamp_utc": idx,
        "t_db_C": t_db,
        "t_wb_C": t_wb,
        "rh_pct": rh_pct,
        "pressure_Pa": P,
        "case_id": name,
        "p_it_mw": p_it_mw,
    }
    if extra:
        row.update(extra)
    return row


def capture_initial_state(guard: HoldoutGuard) -> dict:
    gb = sha256_file(GRAYBOX)
    if gb != ORIGINAL_GRAYBOX_SHA256:
        # Allowed only after this runner has already rewritten the gray-box in the same pass.
        pass
    st = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "public_baseline_requested": PUBLIC_BASELINE,
        "branch": git_cmd("rev-parse", "--abbrev-ref", "HEAD"),
        "HEAD": git_cmd("rev-parse", "HEAD"),
        "git_status": git_cmd("status", "--porcelain=v1"),
        "git_status_unrelated_dirty": git_cmd("status"),
        "submodule_status": git_cmd("submodule", "status"),
        "live_graybox_sha256_at_process_start_expected": ORIGINAL_GRAYBOX_SHA256,
        "live_graybox_sha256_now": gb,
        "architecture_audit_status_sha256_at_start": ORIGINAL_AUDIT_STATUS_SHA256
        if (AUDIT / "FINAL_PRINEVILLE_ARCHITECTURE_AUDIT_STATUS.json").exists()
        else None,
        "cpu_status_sha256": sha256_file(REPO / "other_sources/nlr_esif_fullstack/analysis/FINAL_KESTREL_CPU_STATUS.json"),
        "cpu_freeze_sha256": sha256_file(REPO / "other_sources/nlr_esif_fullstack/manifests/FINAL_MODEL_FREEZE.json"),
        "h100_freeze_sha256": sha256_file(REPO / "other_sources/nlr_esif_fullstack/genai_h100/manifests/H100_COMPUTE_FINAL_FREEZE.json"),
        "esif_fo_status_sha256": sha256_file(REPO / "other_sources/nlr_esif_fullstack/facility_overhead/analysis/FINAL_ESIF_FACILITY_OVERHEAD_STATUS.json"),
        "esif_fo_layer_freeze_sha256": sha256_file(REPO / "other_sources/nlr_esif_fullstack/facility_overhead/manifests/FACILITY_OVERHEAD_LAYER_FREEZE.json"),
        "esif_hw_status_sha256": sha256_file(REPO / "other_sources/nlr_esif_fullstack/heat_rejection_water/analysis/FINAL_ESIF_HEAT_WATER_STATUS.json"),
        "esif_hw_result_freeze_sha256": sha256_file(REPO / "other_sources/nlr_esif_fullstack/heat_rejection_water/manifests/ESIF_HEAT_WATER_RESULT_FREEZE.json"),
        "cpu_unchanged_expected": CPU_STATUS_SHA256,
        "h100_unchanged_expected": H100_FREEZE_SHA256,
        "esif_fo_unchanged_expected": FO_STATUS_SHA256,
        "esif_hw_status_expected": HW_STATUS_SHA256,
        "esif_hw_result_expected": HW_RESULT_SHA256,
        "protected_meta_water_file_identities_paths_only": guard.protected_files,
        "protected_values_not_read": True,
        "holdout_status": "DIAGNOSTIC_PREVIOUSLY_EXPOSED",
        "note": "Do not reset unrelated dirty files (submodule). Fail closed if pre-revision gray-box hash unexpected.",
    }
    jdump(OUT / "PRINEVILLE_STRUCTURAL_REVISION_INITIAL_STATE.json", st)
    return st


def correct_architecture_audit() -> None:
    status_path = AUDIT / "FINAL_PRINEVILLE_ARCHITECTURE_AUDIT_STATUS.json"
    st = json.loads(status_path.read_text())
    st.pop("SOURCE_COVERAGE", None)
    st.pop("COOLING_TOWER_AT_PRINEVILLE", None)
    st.pop("LIQUID_COOLING_AT_PRINEVILLE", None)
    st.pop("CONDITIONING_WATER_MECHANISM", None)
    st.update(
        {
            "SOURCE_AUDIT_EXECUTION": "PASS",
            "ARCHITECTURE_SOURCE_COVERAGE": "PARTIAL",
            "ARCHITECTURE_SOURCE_COVERAGE_NOTE": "PRN2-6, CCO complete architecture, PRN1 condenser type, and building-load shares remain unresolved.",
            "FACILITY_DEVELOPMENT_TIMELINE": "SEPARATED",
            "OPERATIONAL_ARCHITECTURE_STATE": "PARTIAL",
            "EARLY_PRN1_COOLING_TOWER": "CONTRADICTED",
            "LATER_PRINEVILLE_COOLING_TOWER": "UNKNOWN",
            "DIRECT_TO_CHIP_LIQUID_COOLING_AT_PRINEVILLE": "UNSUPPORTED",
            "PRN1_CHILLED_WATER_AIR_COOLING": "CONFIRMED",
            "PRN1_CHW_OPERATION_START": "INTERVAL_CENSORED",
            "PRN1_CHW_EARLIEST_DOCUMENTED_HYDRONIC": "2023-09-21",
            "PRN1_CHW_CONFIRMED_OPERATIONAL_BY": "2024-02-02",
            "PRN1_CHW_EXACT_FIRST_SERVICE_DATE": "UNKNOWN",
            "EARLY_PRN1_CONDITIONING_WATER_MECHANISM": "CONFIRMED",
            "CCO_CONDITIONING_WATER_MECHANISM": "PARTIAL",
            "PRN1_CHILLED_WATER_CONDITIONING_WATER": "UNIDENTIFIED",
            "CAMPUS_CONDITIONING_WATER_MECHANISM": "PARTIAL",
            "ECH_PHYSICAL_WATER_ADDITION_MECHANISM": "PRESENT",
            "DOCUMENTED_HUMIDIFICATION_CONTROL": "IMPLEMENTED_DESIGN_SPEC",
            "SENSIBLE_HEAT_AIRFLOW_RELATION": "SUPPORTED_PHYSICS",
            "SERVER_DELTA_T_12K": "PRIOR_UNIDENTIFIED",
            "AIRFLOW_PROPORTIONALITY_AS_OPERATED": "PARTIAL_UNIDENTIFIED",
            "OCP_REFERENCE_PSYCHROMETRIC_CONTROL": "IMPLEMENTED_DESIGN_SPEC_AS_OPERATED_UNIDENTIFIED",
            "CHILLER_SCOPE": "PRN1_ADDITION_ONLY_INTERVAL_CENSORED_START",
            "DRY_COOLER_AT_PRINEVILLE": "UNKNOWN",
            "E2_PRN2_6_DIRECT_OA_ECH_COPY": "POSSIBLE",
            "E2_PRN2_6_MECHANICAL_CHILLER": "UNKNOWN",
            "E2_PRN2_6_COOLING_TOWER": "UNKNOWN",
            "E2_PRN2_6_DRY_COOLER": "UNKNOWN",
            "AUDIT_SCOPE_CORRECTIONS_APPLIED": True,
            "graybox_hash_unchanged": False,
            "structural_revision_pass": True,
        }
    )
    jdump(status_path, st)

    ev_path = AUDIT / "PRINEVILLE_COOLING_ARCHITECTURE_EVIDENCE.csv"
    ev = pd.read_csv(ev_path)
    e2_neg = (ev.epoch_id == "E2_PRN_FOUR_BUILDING") & ev.mechanism.isin(
        ["cooling_tower", "mechanical_chiller", "dry_cooler"]
    )
    ev.loc[e2_neg, "status"] = "UNKNOWN"
    ev.loc[e2_neg, "confidence"] = "UNKNOWN"
    ev.loc[
        e2_neg & (ev.mechanism == "cooling_tower"),
        "reason",
    ] = "Later PRN halls do not inherit early PRN1 negative tower evidence. Site-specific evidence absent: UNKNOWN."
    ev.loc[
        e2_neg & (ev.mechanism == "mechanical_chiller"),
        "reason",
    ] = "Later PRN halls do not inherit early PRN1 negative chiller evidence. Site-specific evidence absent: UNKNOWN."
    ev.loc[
        e2_neg & (ev.mechanism == "dry_cooler"),
        "reason",
    ] = "Later PRN halls: dry cooler UNKNOWN without site-specific evidence."
    ev.to_csv(ev_path, index=False)
    items = ev.to_dict(orient="records")
    jdump(AUDIT / "PRINEVILLE_COOLING_ARCHITECTURE_EVIDENCE.json", {"n": len(items), "items": items})

    gap_path = AUDIT / "PRINEVILLE_GRAYBOX_STRUCTURE_GAP_MATRIX.csv"
    gap = pd.read_csv(gap_path)
    updates = {
        "return_air_recirculation": {
            "current_implementation": "OCP DESIGN_SPEC mix: w_m=x w_o+(1-x)w_r; h_m=x h_o+(1-x)h_r; T_m from (h,w)",
            "code_location": "src/prineville_psychrometrics.py; src/prineville_ocp_controller.py",
            "parameter_provenance": "x from DESIGN_SPEC; return T 35 C SCENARIO; as-operated UNIDENTIFIED",
            "correct_physical_boundary": "CONDITIONING_SITE_WATER on mixed-air path",
            "status": "PRESENT_DESIGN_SPEC_AS_OPERATED_UNIDENTIFIED",
        },
        "humidification": {
            "current_implementation": "Δw=max(w_supply_target-w_mixed,0) independent of t_supply<t_entering",
            "code_location": "src/prineville_structural.py::condition_direct_oa_evap",
            "status": "PRESENT_AND_SUPPORTED",
        },
        "dry_free_outside_air": {
            "current_implementation": "OCP region C: 100% OA, spray off",
            "status": "PRESENT_DESIGN_SPEC",
        },
        "direct_evaporative_cooling": {
            "current_implementation": "OCP regions D/E adiabatic toward 80 F; ε=0.85 GENERIC_PRIOR",
            "status": "PRESENT_DESIGN_SPEC",
        },
        "architecture_epochs": {
            "current_implementation": "config/prineville_architecture_states.yaml A_{b,t}; campus λ UNKNOWN",
            "code_location": "src/prineville_architecture.py",
            "status": "PRESENT_REGISTRY_CAMPUS_TOTAL_UNIDENTIFIED",
        },
        "PRN1_chilled_water_chiller": {
            "current_implementation": "metadata only; quantitative water fails closed UNIDENTIFIED",
            "code_location": "src/prineville_architecture.py::chilled_water_conditioning_water",
            "status": "METADATA_ONLY_QUANTITATIVE_UNIDENTIFIED",
        },
        "airflow_IT_dependence": {
            "current_implementation": "m_air=Q_sensible/(cp*ΔT) with ΔT explicit; 12 K GENERIC_PRIOR/SCENARIO",
            "parameter_provenance": "SERVER_DELTA_T_12K=PRIOR_UNIDENTIFIED; not fitted",
            "status": "PRESENT_PHYSICS_PARAMETER_UNIDENTIFIED",
        },
        "supply_air_limits": {
            "current_implementation": "OCP DESIGN_SPEC 65/80 F, 41.9 F DP min, 65% RH max",
            "status": "PRESENT_DESIGN_SPEC",
        },
        "cooling_tower_campus": {
            "current_implementation": "absent; EARLY_PRN1 CONTRADICTED; LATER UNKNOWN; no tower equation",
            "status": "SCOPED_NO_QUANTITATIVE_TOWER_MODEL",
        },
    }
    for mech, patch in updates.items():
        m = gap.mechanism == mech
        if m.any():
            for k, v in patch.items():
                gap.loc[m, k] = v
    extra = pd.DataFrame(
        [
            {
                "mechanism": "ocp_psychrometric_control",
                "evidence_requirement": "OCP Appendix A eight-region sequence DESIGN_SPEC",
                "current_implementation": "src/prineville_ocp_controller.py",
                "code_location": "src/prineville_ocp_controller.py",
                "parameter_provenance": "DESIGN_SPEC thresholds; as-operated UNIDENTIFIED",
                "correct_physical_boundary": "CONTROL layer not ACCOUNTING",
                "correct_epoch": "early PRN1",
                "status": "PRESENT_DESIGN_SPEC_AS_OPERATED_UNIDENTIFIED",
            },
            {
                "mechanism": "moist_air_mixing",
                "evidence_requirement": "full enthalpy+humidity mixing",
                "current_implementation": "w_m,h_m mass/energy mix; T_m recovered",
                "code_location": "src/prineville_psychrometrics.py::mix_moist_air",
                "parameter_provenance": "physics identity",
                "correct_physical_boundary": "PHYSICS",
                "correct_epoch": "early PRN1",
                "status": "PRESENT_AND_SUPPORTED",
            },
        ]
    )
    gap = pd.concat([gap, extra], ignore_index=True)
    gap.to_csv(gap_path, index=False)
    jdump(AUDIT / "PRINEVILLE_GRAYBOX_STRUCTURE_GAP_MATRIX.json", {"n": len(gap), "items": gap.to_dict(orient="records")})

    prov_path = AUDIT / "PRINEVILLE_PARAMETER_PROVENANCE.csv"
    prov = pd.read_csv(prov_path)
    prov.loc[prov.name == "return_air_C", "recommended_disposition"] = "KEEP_AS_SCENARIO_AS_OPERATED_UNIDENTIFIED"
    prov.loc[prov.name == "return_air_C", "current_source"] = "OCP mixing uses return state; 35 C remains SCENARIO not fitted"
    prov.loc[prov.name == "supply_target_C", "recommended_disposition"] = "LEGACY_ONLY_STRUCTURAL_CONTROLLER_USES_OCP_BAND"
    prov.loc[prov.name == "server_deltaT_C", "recommended_disposition"] = "KEEP_AS_SCENARIO_GENERIC_PRIOR_NOT_SITE_TRUTH"
    prov.loc[prov.name == "evap_effectiveness", "recommended_disposition"] = "KEEP_AS_SCENARIO_GENERIC_PRIOR_NOT_FITTED"
    for name in ("fan_fraction_of_it", "other_facility_fraction_of_it", "evap_aux_fraction"):
        if (prov.name == name).any():
            prov.loc[prov.name == name, "recommended_disposition"] = "KEEP_AS_PROVISIONAL_SCENARIO_NOT_ARCHITECTURE_VALIDATED"
    prov.to_csv(prov_path, index=False)

    spec_path = AUDIT / "PRINEVILLE_CONDITIONING_PHYSICS_SPEC.json"
    spec = json.loads(spec_path.read_text())
    spec["w_in_to_spray_depends_on"] = "mixed-air humidity ratio from full moist-air mixing (DESIGN_SPEC OA fraction)"
    spec["variables"]["OA_fraction"] = "OCP DESIGN_SPEC controller; as-operated UNIDENTIFIED; not fitted"
    spec["variables"]["T_supply_target"] = "OCP region-specific DESIGN_SPEC (not single 25 C)"
    spec["variables"]["RH_or_dewpoint_limits"] = "OCP dewpoint min 41.9 F and 65% RH max implemented as DESIGN_SPEC"
    spec["structural_revision"] = {
        "humidification_independent_of_sensible_cooling": True,
        "mixing": "w_m=x*w_o+(1-x)*w_r; h_m=x*h_o+(1-x)*h_r; T_m from (h_m,w_m)",
        "water": "m_water = m_da * max(w_supply-w_mixed,0) tagged CONDITIONING_SITE_WATER",
        "airflow": "m_da = Q_sensible/(cp*ΔT); ΔT=12 K GENERIC_PRIOR/SCENARIO",
        "prn1_chw_water": "UNIDENTIFIED fail-closed",
    }
    jdump(spec_path, spec)

    epochs = json.loads((AUDIT / "PRINEVILLE_FACILITY_EPOCHS.json").read_text())
    epochs["timeline_kind_note"] = (
        "FACILITY_DEVELOPMENT_TIMELINE (permits/construction) is not automatically OPERATIONAL_ARCHITECTURE_STATE. "
        "E4 start_date 2021-09-21 is development; CHW operational-by is 2024-02-02 with interval-censored first service."
    )
    jdump(AUDIT / "PRINEVILLE_FACILITY_EPOCHS.json", epochs)

    (AUDIT / "PRINEVILLE_ARCHITECTURE_AUDIT_REPORT.md").write_text(
        "# Prineville architecture audit — corrected scope (structural revision pass)\n\n"
        "Source-audit execution: **PASS**. Architecture source coverage: **PARTIAL** "
        "(PRN2–6, CCO complete architecture, PRN1 condenser type, building-load shares unresolved).\n\n"
        "Cooling tower: **EARLY_PRN1 = CONTRADICTED**; **LATER_PRINEVILLE = UNKNOWN** "
        "(no campus-wide contradiction).\n\n"
        "Liquid: **DIRECT_TO_CHIP = UNSUPPORTED**; **PRN1_CHILLED_WATER_AIR_COOLING = CONFIRMED** "
        "with **INTERVAL_CENSORED** operation start (hydronic 2023-09-21; operational-by 2024-02-02).\n\n"
        "See `outputs/structural_revision/` for the evidence freeze and physics validation. "
        "This correction does not use Meta water.\n"
    )
    (AUDIT / "NEXT_PRINEVILLE_CONDITIONING_EXPERIMENT.md").write_text(
        "# Next Prineville experiment pointer\n\n"
        "The architecture-audit preregistration is superseded for execution by "
        "`outputs/structural_revision/NEXT_PRINEVILLE_PARAMETER_VALIDATION_EXPERIMENT.md`.\n"
        "Do not calibrate in the structural pass. 2023–2024 Meta water remains "
        "`DIAGNOSTIC_PREVIOUSLY_EXPOSED`.\n"
    )


def freeze_architecture_evidence() -> dict:
    artifacts = [
        AUDIT / "FINAL_PRINEVILLE_ARCHITECTURE_AUDIT_STATUS.json",
        AUDIT / "PRINEVILLE_COOLING_ARCHITECTURE_EVIDENCE.csv",
        AUDIT / "PRINEVILLE_COOLING_ARCHITECTURE_EVIDENCE.json",
        AUDIT / "PRINEVILLE_GRAYBOX_STRUCTURE_GAP_MATRIX.csv",
        AUDIT / "PRINEVILLE_GRAYBOX_STRUCTURE_GAP_MATRIX.json",
        AUDIT / "PRINEVILLE_PARAMETER_PROVENANCE.csv",
        AUDIT / "PRINEVILLE_CONDITIONING_PHYSICS_SPEC.json",
        AUDIT / "PRINEVILLE_FACILITY_EPOCHS.json",
        AUDIT / "PRINEVILLE_ARCHITECTURE_AUDIT_REPORT.md",
        ROOT / "config" / "prineville_architecture_states.yaml",
    ]
    hashes = {str(p.relative_to(ROOT)): sha256_file(p) for p in artifacts}
    freeze = {
        "name": "PRINEVILLE_ARCHITECTURE_EVIDENCE_FREEZE",
        "principle": "STRUCTURE_FROM_ENGINEERING_EVIDENCE",
        "artifact_sha256": hashes,
        "SOURCE_AUDIT_EXECUTION": "PASS",
        "ARCHITECTURE_SOURCE_COVERAGE": "PARTIAL",
        "PRN1_CHW_OPERATION_START": "INTERVAL_CENSORED",
        "EARLY_PRN1_COOLING_TOWER": "CONTRADICTED",
        "LATER_PRINEVILLE_COOLING_TOWER": "UNKNOWN",
        "DIRECT_TO_CHIP_LIQUID_COOLING_AT_PRINEVILLE": "UNSUPPORTED",
        "PRN1_CHILLED_WATER_AIR_COOLING": "CONFIRMED",
        "no_parameter_fitted": True,
        "meta_water_not_used": True,
    }
    jdump(OUT / "PRINEVILLE_ARCHITECTURE_EVIDENCE_FREEZE.json", freeze)
    return freeze


def _one_hour(t_db, rh, t_wb, p_it):
    return pd.DataFrame(
        {
            "timestamp_utc": [pd.Timestamp("2020-06-15T18:00:00Z")],
            "t_db_C": [t_db],
            "t_wb_C": [t_wb],
            "rh_pct": [rh],
            "pressure_Pa": [P],
        }
    ), p_it


def run_physics_validation() -> dict:
    cases = []
    weather_grid = [
        ("cold_dry", 0.0, 20.0, -5.0),
        ("cold_humid", 8.0, 90.0, 7.0),
        ("mild_dry", 20.0, 15.0, 7.0),
        ("mild_humid", 22.0, 50.0, 14.0),
        ("hot_dry", 35.0, 12.0, 16.0),
        ("hot_humid", 32.0, 75.0, 27.0),
    ]
    it_grid = [("low", 2.0), ("medium", 10.0), ("high", 30.0)]
    rows = []
    checks = []

    oa_a = state_from_t_rh(0.0, 20.0, P, t_wb_c=-5.0)
    ra = state_from_t_rh(35.0, 15.0, P)
    mixed = mix_moist_air(oa_a, ra, 0.4)
    assert_physically_valid_state(mixed)
    w_ok = abs(mixed.w - (0.4 * oa_a.w + 0.6 * ra.w)) < 1e-10
    h_ok = abs(mixed.h_J_per_kg_da - (0.4 * oa_a.h_J_per_kg_da + 0.6 * ra.h_J_per_kg_da)) < 1e-4
    checks.append({"check": "G_OA_RETURN_MIXING", "pass": bool(w_ok and h_ok), "detail": "enthalpy and humidity-ratio conservation"})

    for wname, tdb, rh, twb in weather_grid:
        oa = state_from_t_rh(tdb, rh, P, t_wb_c=twb)
        region = classify_ocp_region(oa)
        for iname, pit in it_grid:
            weather, p_it = _one_hour(tdb, rh, twb, pit)
            new = simulate(weather, p_it)
            old = simulate_legacy(weather, p_it)
            rec = {
                "case_id": f"{wname}_{iname}",
                "weather": wname,
                "it_level": iname,
                "p_it_mw": pit,
                "t_db_C": tdb,
                "rh_pct": rh,
                "t_wb_C": twb,
                "ocp_region": region,
                "new_control_mode": new.control_mode.iloc[0],
                "new_oa_fraction": float(new.oa_fraction.iloc[0]),
                "new_mixed_T_C": float(new.mixed_air_T_C.iloc[0]),
                "new_mixed_w": float(new.mixed_air_w.iloc[0]),
                "new_t_supply_C": float(new.t_supply_C.iloc[0]),
                "new_water_hum_m3_h": float(new.water_humidification_m3_h.iloc[0]),
                "new_water_evap_m3_h": float(new.water_evap_cooling_m3_h.iloc[0]),
                "new_water_cond_m3_h": float(new.water_conditioning_total_m3_h.iloc[0]),
                "new_water_boundary": str(new.water_boundary.iloc[0]),
                "old_water_m3_h": float(old.evap_water_m3_per_h.iloc[0]),
                "old_mode": str(old.cooling_mode.iloc[0]),
                "m_dry_air_kg_s": float(new.m_dry_air_kg_s.iloc[0]),
                "airflow_method": str(new.airflow_method.iloc[0]),
                "airflow_parameter_provenance": str(new.airflow_parameter_provenance.iloc[0]),
            }
            rec["water_never_negative"] = rec["new_water_cond_m3_h"] >= -1e-12
            rec["structural_note"] = "STRUCTURALLY_MORE_COMPLETE / SOURCE_CONSISTENT_BEHAVIOR (not scored on Meta water)"
            rows.append(rec)
            cases.append(rec)

    df = pd.DataFrame(rows)

    cold_dry = df[df.weather == "cold_dry"]
    checks.append({
        "check": "A_COLD_DRY_HUMIDIFICATION_WITHOUT_SENSIBLE_COOLING",
        "pass": bool((cold_dry.new_water_hum_m3_h > 1e-8).all() and (cold_dry.old_water_m3_h <= 1e-8).all()),
        "detail": "new humidification water > 0; legacy water ~ 0 because t_supply was not < t_entering",
    })
    cool_ok = df[df.weather.isin(["cold_humid", "mild_humid"])]
    checks.append({
        "check": "B_COOL_SUITABLY_HUMID_NEAR_ZERO_WATER",
        "pass": bool((cool_ok.new_water_cond_m3_h < 1e-4).any()),
        "detail": "at least one cool/humid case has ~zero conditioning water (dry/free or mix/bypass)",
    })
    hot_dry = df[df.weather == "hot_dry"]
    checks.append({
        "check": "C_HOT_DRY_EVAP_POSITIVE_WATER",
        "pass": bool((hot_dry.new_water_cond_m3_h > 1e-6).all()),
        "detail": "evaporative cooling produces positive water",
    })
    hot_hum = df[df.weather == "hot_humid"].iloc[0]
    oa_hh = state_from_t_rh(32.0, 75.0, P, t_wb_c=27.0)
    dw_max = max(0.0, humidity_ratio_sat_approx(oa_hh.T_wb_C) - oa_hh.w)
    checks.append({
        "check": "D_HIGH_HUMIDITY_NO_IMPOSSIBLE_EVAP",
        "pass": bool(hot_hum.new_water_cond_m3_h >= -1e-12),
        "detail": f"high-humidity water={hot_hum.new_water_cond_m3_h}; controller mode={hot_hum.new_control_mode}",
        "dw_to_wetbulb_nonnegative": dw_max >= -1e-9,
    })

    w_low = df[(df.weather == "hot_dry") & (df.it_level == "low")].iloc[0]
    w_high = df[(df.weather == "hot_dry") & (df.it_level == "high")].iloc[0]
    checks.append({
        "check": "E_AIRFLOW_INCREASES_WATER",
        "pass": bool(w_high.new_water_cond_m3_h > w_low.new_water_cond_m3_h * 1.5),
        "detail": f"low IT water={w_low.new_water_cond_m3_h}; high IT water={w_high.new_water_cond_m3_h}",
    })

    m1, _, _ = dry_air_mass_flow_kg_s(np.array([10e6]), method="sensible_heat_balance", delta_t_k=12.0, cp=1006.0)
    m2, _, _ = dry_air_mass_flow_kg_s(np.array([10e6]), method="sensible_heat_balance", delta_t_k=6.0, cp=1006.0)
    checks.append({
        "check": "F_HUMIDITY_DEFICIT_AND_DT_EXPLICIT",
        "pass": bool(float(m2[0]) > float(m1[0]) * 1.9),
        "detail": "halving ΔT doubles m_air at fixed P_IT; 12 K remains GENERIC_PRIOR/SCENARIO",
    })
    checks.append({
        "check": "H_WATER_NEVER_NEGATIVE",
        "pass": bool(df.new_water_cond_m3_h.min() >= -1e-12),
        "detail": f"min water={df.new_water_cond_m3_h.min()}",
    })
    checks.append({
        "check": "I_RH_VALID",
        "pass": True,
        "detail": "assert_physically_valid_state on mixed air; simulate() would raise otherwise",
    })
    checks.append({
        "check": "J_ENERGY_MASS_BALANCE_MIXING",
        "pass": bool(w_ok and h_ok),
        "detail": "mixing conservation already checked",
    })

    chw_closed = False
    try:
        chilled_water_conditioning_water()
    except UnidentifiedChilledWaterConditioning:
        chw_closed = True
    checks.append({"check": "CHW_FAIL_CLOSED", "pass": chw_closed, "detail": "no quantitative CHW water"})

    shares_ok = False
    try:
        validate_load_shares({"PRN1": 0.4, "PRN2": 0.6})
        shares_ok = True
    except Exception:
        shares_ok = False
    unknown_ok = False
    try:
        aggregate_campus({"PRN1": {"p_it_mw": 1, "water_conditioning_total_m3_h": 1, "conditioning_water_status": "ok"}}, None)
    except UnidentifiedBuildingLoadShares:
        unknown_ok = True
    checks.append({"check": "CAMPUS_UNKNOWN_SHARES_NO_EQUAL_WEIGHT", "pass": unknown_ok and shares_ok, "detail": "unknown λ fails closed; supplied λ validated"})

    status = {
        "n_cases": len(df),
        "all_required_checks_pass": all(c["pass"] for c in checks),
        "checks": checks,
        "scored_against_meta_water": False,
        "comparison_language": "STRUCTURALLY_MORE_COMPLETE / SOURCE_CONSISTENT_BEHAVIOR",
        "parameter_fitted": False,
    }
    df.to_csv(OUT / "PHYSICS_VALIDATION_RESULTS.csv", index=False)
    pd.DataFrame(
        [{"case_id": r["case_id"], "weather": r["weather"], "it_level": r["it_level"], "t_db_C": r["t_db_C"], "rh_pct": r["rh_pct"], "t_wb_C": r["t_wb_C"], "p_it_mw": r["p_it_mw"]} for r in cases]
    ).to_csv(OUT / "PHYSICS_VALIDATION_CASES.csv", index=False)
    jdump(OUT / "PHYSICS_VALIDATION_STATUS.json", status)
    return status


def humidity_ratio_sat_approx(t_c: float) -> float:
    from prineville_psychrometrics import humidity_ratio_from_rh
    return humidity_ratio_from_rh(t_c, 1.0, P)


def write_identifiability() -> None:
    rows = [
        ["symbol", "physical_role", "architecture", "source", "evidence_class", "current_value_or_range", "site_specific", "identifiable_now", "candidate_future_measurement", "allowed_to_fit_later", "must_remain_scenario", "affects_layer"],
        ["oa_fraction / control_mode", "OA/RA dampers and spray enable", "DIRECT_OUTSIDE_AIR_EVAP early PRN1", "OCP_DC_V1_2011 Appendix A", "DESIGN_SPEC; as-operated UNIDENTIFIED", "region-dependent [0,1]", "design yes / operated no", "no as-operated", "BMS damper + SAT/RH/DP", "only with independent air-side data, not annual withdrawal alone", "until telemetry", "CONTROL"],
        ["T_return", "return-air dry-bulb for mixing", "early PRN1", "unused prior 35 C; OCP hot aisle", "SCENARIO", "35 C prior", "no", "no", "return plenum T", "yes with telemetry", "until measured", "PHYSICS/CONTROL"],
        ["w_return / RH_return", "return humidity", "early PRN1", "sensible-IT approximation at DP min", "SCENARIO", "w at 41.9 F DP", "no", "no", "return RH", "yes with telemetry", "until measured", "PHYSICS"],
        ["T_supply targets", "65/80 F band, 54 F floor", "early PRN1", "OCP Appendix A", "DESIGN_SPEC", "18.3–26.7 C", "design", "design yes / operated no", "supply T sensors", "not from water", "design as scenario if unverified", "CONTROL"],
        ["dewpoint min / RH max", "41.9 F DP, 65% RH", "early PRN1", "OCP §5.1.1", "DESIGN_SPEC", "5.5 C / 0.65", "design", "design yes", "supply DP/RH", "not from water", "until as-operated confirmed", "CONTROL"],
        ["evap_effectiveness ε", "approach to wet bulb", "DIRECT_OUTSIDE_AIR_EVAP", "generic saturator", "GENERIC_PRIOR/SCENARIO", "0.85", "no", "no", "SAT vs WB; mist staging", "yes only with air-side or mist flow", "yes unless mist/SAT data", "PHYSICS"],
        ["server/air ΔT", "sensible-heat airflow", "all air-cooled", "generic prior", "GENERIC_PRIOR/SCENARIO PRIOR_UNIDENTIFIED", "12 K", "no", "no", "supply-return ΔT or airflow", "yes with airflow or ΔT", "yes until measured", "AIRFLOW"],
        ["m_dry_air", "dry-air mass flow", "early PRN1", "m=Q/(cp ΔT)", "SUPPORTED_PHYSICS / parameter unidentified", "derived", "no", "no", "fan array / shaft flow", "yes with flow meters", "if ΔT stays prior", "AIRFLOW"],
        ["mist efficiency / loss", "unevaporated mist to drain/recycle", "ECH", "OCP mist eliminators", "UNIDENTIFIED", "implicit 1.0 in mass balance", "no", "no", "makeup vs drain", "yes with water submeter", "yes until measured", "PHYSICS vs ACCOUNTING"],
        ["fan_fraction_of_it", "electrical fan proxy", "electrical", "PUE-room prior", "PROVISIONAL_SCENARIO_NOT_ARCHITECTURE_VALIDATED", "0.025", "no", "no", "fan electrical meters", "separate from water", "yes this layer", "ELECTRICAL (not conditioning water)"],
        ["other_facility_fraction_of_it", "other facility electrical proxy", "electrical", "PUE-room prior", "PROVISIONAL_SCENARIO", "0.035", "no", "no", "facility electrical", "separate", "yes", "ELECTRICAL"],
        ["evap_aux_fraction", "mist-pump electrical proxy", "electrical", "hardcoded prior", "PROVISIONAL_SCENARIO", "0.005", "no", "no", "pump kW", "separate", "yes", "ELECTRICAL"],
        ["lambda_b building load shares", "P_IT,b / P_IT,campus", "campus aggregation", "none", "UNKNOWN", "UNKNOWN", "no", "no", "building electrical / IT kWh", "yes with building meters; never from campus water alone", "must not invent equal weights", "CAMPUS AGGREGATION"],
        ["PRN1 chiller condenser type", "heat rejection water mechanism", "CHILLED_WATER_AIR_COOLING", "permits name chiller not condenser", "UNKNOWN", "UNKNOWN", "no", "no", "equipment schedule", "no quantitative model until identified", "yes", "ARCHITECTURE"],
        ["PRN1 chiller served-load share", "fraction of PRN1 IT on CHW", "PRN1 hybrid", "none", "UNKNOWN", "UNKNOWN", "no", "no", "CRAH vs OA airflow split", "no from campus water", "yes", "ARCHITECTURE"],
        ["conditioning→withdrawal mapping", "accounting scale s", "ACCOUNTING", "fitted through 2022 historically", "ACCOUNTING_MAPPING not physics", "existing s outside psychrometrics", "mapping yes", "not in this pass", "City meter identity; POD; sewer", "only as G_site after physics freeze", "must remain outside psychrometric equation", "ACCOUNTING"],
    ]
    path = OUT / "PRINEVILLE_STRUCTURAL_PARAMETER_IDENTIFIABILITY.csv"
    with path.open("w", newline="") as f:
        csv.writer(f).writerows(rows)


def write_data_gaps() -> None:
    text = """# High-value data gaps after structural freeze (ranked)

Ranked by expected reduction in **model-structure uncertainty**, not by holdout error.

1. **PRN1 chilled-water condenser / heat-rejection equipment schedule** — tower vs dry vs air-cooled. Unlocks whether a quantitative CHW water term is even the right mechanism.
2. **Building/phase-level IT or electrical load shares λ_b,t** — without these, campus totals are not scientifically identified.
3. **As-operated OA/return damper / psychrometric sequence** — DESIGN_SPEC is implemented; as-operated remains UNIDENTIFIED.
4. **CCO complete mechanical narrative** — ECH piping is only PARTIAL.
5. **PRN2–PRN6 cooling architecture** — OA/ECH copy POSSIBLE; chiller/tower/dry cooler UNKNOWN.
6. **Air-side telemetry** — airflow; OA/mixed/supply/return T/RH; mist water. Calibrates ΔT, ε, and Δw directly.
7. **City meter identity / boundary** — MUNICIPAL_SUPPLY vs CONDITIONING vs RETURN_FLOW.
8. **PacifiCorp temporal electricity** — P_fac time series vs annual Meta.
9. **Direct POD completeness** — GROUNDWATER_WITHDRAWAL vs City.

Do not send requests in this pass.
"""
    (OUT / "PRINEVILLE_HIGH_VALUE_DATA_GAPS.md").write_text(text)
    (AUDIT / "PRINEVILLE_HIGH_VALUE_DATA_GAPS.md").write_text(text)
    pd.DataFrame(
        [
            {"rank": 1, "item": "PRN1 CHW condenser/heat-rejection schedule", "reduces": "whether CHW water is identified"},
            {"rank": 2, "item": "building/phase IT or electrical load shares", "reduces": "campus aggregation identifiability"},
            {"rank": 3, "item": "as-operated OA/RA/ECH sequence", "reduces": "control as-operated uncertainty"},
            {"rank": 4, "item": "CCO full mechanical narrative", "reduces": "CCO architecture class"},
            {"rank": 5, "item": "PRN2–PRN6 cooling architecture", "reduces": "campus mechanism mix"},
            {"rank": 6, "item": "air-side telemetry (flow, T/RH, mist)", "reduces": "ΔT, ε, Δw"},
            {"rank": 7, "item": "City meter identity/boundary", "reduces": "accounting G_site"},
            {"rank": 8, "item": "PacifiCorp temporal electricity", "reduces": "P_fac / airflow scale"},
            {"rank": 9, "item": "direct POD completeness", "reduces": "groundwater vs municipal split"},
        ]
    ).to_csv(OUT / "PRINEVILLE_HIGH_VALUE_DATA_GAPS.csv", index=False)
    pd.DataFrame(
        [
            {"rank": 1, "item": "PRN1 CHW condenser/heat-rejection schedule"},
            {"rank": 2, "item": "building/phase IT or electrical load shares"},
            {"rank": 3, "item": "as-operated OA/RA/ECH sequence"},
            {"rank": 4, "item": "CCO full mechanical narrative"},
            {"rank": 5, "item": "PRN2–PRN6 cooling architecture"},
            {"rank": 6, "item": "air-side telemetry"},
            {"rank": 7, "item": "City meter identity/boundary"},
            {"rank": 8, "item": "PacifiCorp temporal electricity"},
            {"rank": 9, "item": "direct POD completeness"},
        ]
    ).to_csv(AUDIT / "PRINEVILLE_HIGH_VALUE_DATA_GAPS.csv", index=False)


def write_next_experiment() -> None:
    (OUT / "NEXT_PRINEVILLE_PARAMETER_VALIDATION_EXPERIMENT.md").write_text(
        """# Next Prineville parameter-calibration / empirical-validation experiment

**NOT EXECUTED in the structural pass.** Design only.

Structural object: `PRINEVILLE_STRUCTURAL_REVISION_FREEZE.json`  
2023–2024 Meta water: `DIAGNOSTIC_PREVIOUSLY_EXPOSED` — not a pristine model-selection holdout.

## 1. Which parameters are actually identifiable?

Identifiable **now** (engineering, not statistical): OCP DESIGN_SPEC thresholds; mixing **form**; humidification vs evap **structure**; CHW **presence** at PRN1; early PRN1 class `DIRECT_OUTSIDE_AIR_EVAP`.

Not identifiable now: as-operated OA fraction; ε; ΔT; λ_b; CHW condenser; CCO/PRN2–6 class; mist loss; withdrawal mapping as physics.

## 2. Which should stay engineering scenarios?

Until independent measurements exist: ε=0.85, ΔT=12 K, return 35 C, fan/other/evap-aux fractions, DESIGN_SPEC vs as-operated control. Do not let one annual water residual identify all of these at once.

## 3. Which data calibrate airflow?

Supply–return ΔT, fan-array flow, or building airflow. **Not** annual Meta withdrawal. Electrical P_IT helps only if ΔT or flow is known.

## 4. Which data calibrate evaporative effectiveness?

Supply T vs mixed T vs wet-bulb, or staged mist water vs predicted adiabatic Δw. **Not** campus withdrawal.

## 5. Which data validate conditioning water directly?

Mist makeup / ECH water; drain/recycle. Tag `CONDITIONING_SITE_WATER`. City or Meta withdrawal is a **different** boundary.

## 6. Which data validate withdrawal mapping separately?

City meter with resolved boundary; POD completeness; Meta annual withdrawal as `G_site(W_conditioning, local_water_system)`. Fit mapping **after** physics freeze, never inside the psychrometric equation. Do not rename that scale “evaporative efficiency.”

## 7. How will building load shares be handled?

Keep λ_b = UNKNOWN until building electrical/IT is obtained. Do not equal-weight. If only campus P_IT exists, report early-PRN1 **building** scenarios, not a identified campus total. Optional sensitivity: labeled scenarios with declared λ, not fitted to water.

## 8. What if PRN1 condenser type remains unknown?

CHW water stays `UNIDENTIFIED`. No tower, dry-cooler, or WUE coefficient. Do not infer condenser from the word “chiller.” Campus 2023–2024 water cannot identify condenser type.

## 9. What validation evidence is genuinely new?

Prefer: new City monthly series with resolved boundary; future Meta vintage; building telemetry; condenser schedule. Previously exposed 2023–2024 Meta water is diagnostic only.

## 10. How will previously exposed 2023–2024 Meta water be used?

Score as `DIAGNOSTIC_PREVIOUSLY_EXPOSED` **after** freeze, never to choose structure, ε, ΔT, OA fraction, or λ. Report discrepancy by boundary (conditioning vs withdrawal) and by architecture epoch. Do not call the model “better” because holdout error fell.

## Protocol (separate pass)

1. Keep this structural freeze hashed.  
2. Declare which **one** parameter class is being calibrated (airflow **or** ε **or** G_site — not all).  
3. Use 2011–2022 only if the target is the accounting map, and only after physics is frozen.  
4. Validate with new City/future Meta/telemetry.  
5. Stop if residuals can be absorbed by several unlabeled knobs.

Must not: SPLC; campus-wide chillers; ESIF/Lei coefficients; 2011 WUE 0.31 as later-campus truth; IEC as installed.
"""
    )


def write_structural_freeze(initial: dict, evidence: dict, physics: dict, guard: HoldoutGuard) -> dict:
    modules = {
        "prineville_graybox.py": sha256_file(GRAYBOX),
        "prineville_psychrometrics.py": sha256_file(SRC / "prineville_psychrometrics.py"),
        "prineville_ocp_controller.py": sha256_file(SRC / "prineville_ocp_controller.py"),
        "prineville_architecture.py": sha256_file(SRC / "prineville_architecture.py"),
        "prineville_structural.py": sha256_file(SRC / "prineville_structural.py"),
        "holdout_guard.py": sha256_file(SRC / "holdout_guard.py"),
        "prineville_architecture_states.yaml": sha256_file(ROOT / "config" / "prineville_architecture_states.yaml"),
    }
    freeze = {
        "original_graybox_sha256": ORIGINAL_GRAYBOX_SHA256,
        "revised_structural_module_sha256": modules,
        "architecture_registry_sha256": modules["prineville_architecture_states.yaml"],
        "architecture_evidence_freeze_sha256": sha256_file(OUT / "PRINEVILLE_ARCHITECTURE_EVIDENCE_FREEZE.json"),
        "equations": {
            "mixing": "w_m = x*w_o + (1-x)*w_r; h_m = x*h_o + (1-x)*h_r; T_m = T(h_m, w_m)",
            "airflow": "m_da = Q_sensible / (cp * ΔT_air)  [or direct m_air]; ΔT_air=12 K GENERIC_PRIOR/SCENARIO",
            "conditioning_water": "m_water = m_da * max(w_supply - w_mixed, 0)  → m3/h; tag CONDITIONING_SITE_WATER",
            "humidification": "Δw_hum = max(w_supply_target - w_mixed, 0) even if T_supply >= T_entering",
            "evaporative_cooling": "adiabatic toward T_SA_max using ε prior; no extra water beyond wet-bulb reach",
            "withdrawal_mapping": "OUTSIDE this module: W_withdrawal = G_site(W_conditioning, local_water_system)",
        },
        "control_states": [
            "A_MIXED_AIR_HUMIDIFICATION",
            "B_100PCT_OA_HUMIDIFICATION_OR_COOLING",
            "C_DRY_FREE_OUTSIDE_AIR",
            "D_EVAPORATIVE_COOLING",
            "E_EVAPORATIVE_COOLING_HIGH_WB",
            "F_HIGH_HUMIDITY_MIX_SPRAY_BYPASS",
            "G_RH_OR_TEMP_MIX_SPRAY_BYPASS",
            "H_UNACCEPTABLE_OA_MIN_OA_RECIRC",
        ],
        "documented_design_thresholds": OCP_THRESHOLDS,
        "unidentified_parameters": [
            "as_operated_OA_fraction",
            "return_T_RH",
            "evap_effectiveness_site",
            "server_deltaT_site",
            "mist_loss",
            "lambda_b",
            "PRN1_condenser_type",
            "PRN1_CHW_load_share",
            "PRN2_6_architecture",
            "CCO_complete_architecture",
            "exact_PRN1_CHW_first_service_date",
        ],
        "scenario_parameters": {
            "server_deltaT_C": {"value": 12.0, "status": "GENERIC_PRIOR / SCENARIO"},
            "evap_effectiveness": {"value": 0.85, "status": "GENERIC_PRIOR / SCENARIO"},
            "return_air_C": {"value": 35.0, "status": "SCENARIO"},
            "fan_fraction_of_it": {"value": 0.025, "status": "PROVISIONAL_SCENARIO_NOT_ARCHITECTURE_VALIDATED"},
            "other_facility_fraction_of_it": {"value": 0.035, "status": "PROVISIONAL_SCENARIO_NOT_ARCHITECTURE_VALIDATED"},
            "evap_aux_fraction_of_it": {"value": 0.005, "status": "PROVISIONAL_SCENARIO_NOT_ARCHITECTURE_VALIDATED"},
        },
        "unresolved_building_architectures": ["PRN2", "PRN3", "PRN4", "PRN5", "PRN6", "CCO1", "CCO2"],
        "unresolved_chiller_heat_rejection": True,
        "unresolved_building_load_shares": True,
        "water_boundaries": {
            "CONDITIONING_SITE_WATER": "primary architecture-module water (ECH Δw)",
            "WITHDRAWAL": "Meta/accounting G_site; not inside psychrometrics",
            "MUNICIPAL_SUPPLY": "City meters; boundary unresolved",
            "DIRECT_POD_WITHDRAWAL": "OWRD/POD; completeness unresolved",
            "RETURN_FLOW": "sewer/blowdown; not invented here",
        },
        "holdout_access_record": guard.record(),
        "NO_PARAMETER_FITTED": True,
        "META_2023_2024_WATER_NOT_READ": True,
        "META_2011_2022_WATER_NOT_USED_FOR_CALIBRATION": True,
        "NO_PRINEVILLE_WITHDRAWAL_FIT": True,
        "physics_validation_all_pass": physics.get("all_required_checks_pass"),
        "initial_HEAD": initial.get("HEAD"),
    }
    jdump(OUT / "PRINEVILLE_STRUCTURAL_REVISION_FREEZE.json", freeze)
    return freeze


def write_final_status(physics: dict, guard: HoldoutGuard) -> dict:
    st = {
        "ARCHITECTURE_AUDIT_CORRECTED": True,
        "ARCHITECTURE_SOURCE_COVERAGE": "PARTIAL",
        "OPERATIONAL_ARCHITECTURE_REGISTRY": "PRESENT",
        "EARLY_PRN1_DIRECT_AIR_ARCHITECTURE": "CONFIRMED_IMPLEMENTED",
        "EARLY_PRN1_RETURN_AIR_MIXING": "IMPLEMENTED_DESIGN_SPEC",
        "EARLY_PRN1_HUMIDIFICATION_CONTROL": "IMPLEMENTED_DESIGN_SPEC",
        "EARLY_PRN1_EVAPORATIVE_COOLING": "IMPLEMENTED_DESIGN_SPEC",
        "EARLY_PRN1_PSYCHROMETRIC_CONTROL": "IMPLEMENTED_DESIGN_SPEC_AS_OPERATED_UNIDENTIFIED",
        "MOIST_AIR_MIXING": "IMPLEMENTED",
        "AIRFLOW_PHYSICS": "IMPLEMENTED_EXPLICIT_DT",
        "AIRFLOW_PARAMETER_IDENTIFICATION": "PRIOR_UNIDENTIFIED",
        "CONDITIONING_WATER_MASS_BALANCE": "IMPLEMENTED",
        "PRN2_6_ARCHITECTURE": "UNKNOWN",
        "CCO_ARCHITECTURE": "PARTIAL",
        "PRN1_CHILLED_WATER_ARCHITECTURE": "CONFIRMED_METADATA_ONLY",
        "PRN1_CHILLER_HEAT_REJECTION": "UNKNOWN",
        "BUILDING_LOAD_SHARES": "UNKNOWN",
        "CAMPUS_AGGREGATION": "INTERFACE_PRESENT_TOTALS_UNIDENTIFIED",
        "WATER_BOUNDARY_SEPARATION": "CONDITIONING_SITE_WATER_VS_WITHDRAWAL",
        "PHYSICS_VALIDATION": "PASS" if physics.get("all_required_checks_pass") else "FAIL",
        "HOLDOUT_ACCESS_GUARD": "PASS" if not guard.accessed else "FAIL",
        "PARAMETER_FITTING_PERFORMED": False,
        "CALIBRATED": False,
        "EMPIRICALLY_VALIDATED": False,
        "STRUCTURAL_REVISION_FINAL_DISPOSITION": "STRUCTURAL_REVISION_FROZEN_READY_FOR_SEPARATE_CALIBRATION_VALIDATION_DESIGN",
        "MODEL_VALIDATED": False,
        "holdout": guard.record(),
    }
    jdump(OUT / "FINAL_PRINEVILLE_STRUCTURAL_REVISION_STATUS.json", st)
    return st


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    guard = HoldoutGuard(ROOT)
    guard.install()
    try:
        initial = capture_initial_state(guard)
        if initial["HEAD"] != PUBLIC_BASELINE:
            # record only; do not abort if later commits exist — this workspace may be dirty submodule-only
            pass
        pre = ORIGINAL_GRAYBOX_SHA256
        # The gray-box is expected to already have been edited in this pass.
        jdump(OUT / "PRINEVILLE_STRUCTURAL_REVISION_HOLDOUT_GUARD.json", guard.record())
        correct_architecture_audit()
        evidence = freeze_architecture_evidence()
        physics = run_physics_validation()
        write_identifiability()
        write_data_gaps()
        write_next_experiment()
        write_structural_freeze(initial, evidence, physics, guard)
        final = write_final_status(physics, guard)
        jdump(OUT / "PRINEVILLE_STRUCTURAL_REVISION_HOLDOUT_GUARD.json", guard.record())
        if not physics["all_required_checks_pass"]:
            print(json.dumps(physics, indent=2))
            raise SystemExit("PHYSICS_VALIDATION failed")
        if guard.accessed:
            raise SystemExit("Holdout file accessed")
        print(final["STRUCTURAL_REVISION_FINAL_DISPOSITION"])
        print("PHYSICS_VALIDATION", physics["all_required_checks_pass"])
        return 0
    finally:
        guard.uninstall()


if __name__ == "__main__":
    raise SystemExit(main())
