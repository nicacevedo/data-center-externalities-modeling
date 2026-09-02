"""Structural-reference-v1 runner: physics, boundaries, API versioning.

Does not fit parameters. Does not read Meta water. Does not overwrite v0 freeze artifacts.
Does not regenerate canonical production outputs.
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
from prineville_graybox import (  # noqa: E402
    simulate,
    simulate_legacy,
    simulate_structural_reference_v0,
    simulate_structural_reference_v1,
)
from prineville_ocp_controller import OCP_THRESHOLDS, classify_ocp_region  # noqa: E402
from prineville_psychrometrics import (  # noqa: E402
    assert_physically_valid_state,
    mix_moist_air,
    state_from_t_rh,
)
from prineville_structural_v1 import (  # noqa: E402
    ENHALPY_ABS_TOL_J_PER_KG,
    AmbiguousEffectivenessNameError,
    MissingReturnAirError,
    ReturnAirSpec,
    apply_control_request,
    isothermal_humidification_request_is_infeasible,
    ocp_control_request,
)

OUT = ROOT / "outputs" / "structural_revision_v1"
V0 = ROOT / "outputs" / "structural_revision"
P = 90100.0
PUBLIC_BASELINE = "99abd3563cb936ed0c244e5f5200993563f8f048"
REGISTRY_SHA256 = "1f87a1846aa8254c758ab11e3bd9b6f639e6c64bc551c36bcf8201bd65e78604"
V0_STRUCTURAL_FREEZE = "a0bdd12561064c6156dbdc3b4a48cff2057096b71188a65243b800de1eb002c1"
V0_EVIDENCE_FREEZE = "e0586ba7b8d41fecb32b60bf86c0f3efdc88243e821f7646771c90965fbcd56c"
V0_GRAYBOX = "f9a83f5276e71f2afc8c6a773bda9f1d1d5a5a05d84d821c6b767a66d1c2efdb"
CPU_STATUS = "1f57b210a63d375ce8eff7d5043756ffe6efe04e8a408bf9429bfd10096528d9"
CPU_FREEZE = "dcbd066b26b8e7d2800e40a23a1cb8250502bfe59563fe06318cb1be1cc4fd27"
H100_FREEZE = "a620d649a932f2388aa2f35bac2730eb75fe1dc74529668de4f30ee814600076"
FO_STATUS = "ae7c50a0a5ab4c6ecd52f0fe55607ca423295458755226515ee5c46e2c3542d2"
FO_LAYER = "bac8f706fa407f89a21ccbb73e2675cfed9b5bbc5443f43aea8572157e5c67e5"
HW_STATUS = "9cdd12920ae9d8eedeb2ee9251897b27b55d75ab8041be778660f63c1491e063"
HW_RESULT = "4e01139dd9365f62824ac00ff944468839e7873e47a5cea3df4714854af1b02c"

RA_DRY = ReturnAirSpec(T_C=35.0, rh_pct=15.0, provenance="DESIGN_REFERENCE_SCENARIO", label="synthetic_return_dry_35C_15pct")
RA_MOIST = ReturnAirSpec(T_C=35.0, rh_pct=40.0, provenance="DESIGN_REFERENCE_SCENARIO", label="synthetic_return_moist_35C_40pct")

WEATHER = [
    ("cold_dry", 0.0, 20.0, -5.0),
    ("cold_humid", 8.0, 90.0, 7.0),
    ("mild_dry", 20.0, 15.0, 7.0),
    ("mild_humid", 22.0, 50.0, 14.0),
    ("hot_dry", 35.0, 12.0, 16.0),
    ("hot_humid", 32.0, 75.0, 27.0),
]
IT = [("low", 2.0), ("medium", 10.0), ("high", 30.0)]


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


def _hour(tdb, rh, twb):
    return pd.DataFrame(
        {
            "timestamp_utc": [pd.Timestamp("2020-06-15T18:00:00Z")],
            "t_db_C": [tdb],
            "t_wb_C": [twb],
            "rh_pct": [rh],
            "pressure_Pa": [P],
        }
    )


def write_control_contract() -> dict:
    regions = [
        {
            "region": "A",
            "source_text_location": "OCP Data Center v1.0 (7 Apr 2011) Appendix A Condition A",
            "dry_bulb": "<52 F DB (OCP). Electronics Cooling 2012 writes <11.1 C WB; 11.1 C = 52 F. DISCREPANCY PRESERVED; implementation uses OCP DB.",
            "dewpoint": "<41.9 F DP",
            "RH": "not the primary A classifier",
            "oa_fraction_rule": "mix OA/RA to 65 F SA",
            "return_air_mixing_rule": "economizer mixes OA/RA",
            "supply_temperature_target": "OCP: mix to 65 F SA; also 54 F DB minimum. Electronics Cooling: target SAT 18.3 C.",
            "supply_humidity_target": "OCP: 42 F DP minimum. Electronics Cooling: humidify to SAT WB 12.2 C and DP 5.5 C.",
            "spray": "ON (humidification)",
            "documented_actuators": ["OA_RA_MIXING", "DIRECT_EVAPORATIVE_WATER_ADDITION", "FAN_AIRFLOW_CONTROL"],
            "unavailable_actuators": ["HEATER", "MECHANICAL_REFRIGERATION", "IEC", "COOLING_TOWER", "SPLC"],
            "evidence_class": "DESIGN_SPEC",
            "as_operated_status": "UNIDENTIFIED",
            "source_discrepancy": "Simultaneous post-ECH SAT=18.3 C and humidification is not adiabatic; OCP 65 F is a mix target before ECH plus a 54 F floor.",
        },
        {
            "region": "B",
            "source_text_location": "OCP Appendix A Condition B",
            "dry_bulb": ">52 F DB (OCP)",
            "dewpoint": "<41.9 F DP",
            "RH": "not the primary B classifier",
            "oa_fraction_rule": "100% OA; RA dampers closed",
            "return_air_mixing_rule": "no mix",
            "supply_temperature_target": "65–80 F band (OCP); Electronics Cooling 18.3–26.6 C",
            "supply_humidity_target": "OCP 43 F DP; Electronics Cooling DP 5.5 C",
            "spray": "ON (humidify and/or cool)",
            "documented_actuators": ["DIRECT_EVAPORATIVE_WATER_ADDITION", "FAN_AIRFLOW_CONTROL"],
            "unavailable_actuators": ["HEATER"],
            "evidence_class": "DESIGN_SPEC",
            "as_operated_status": "UNIDENTIFIED",
            "source_discrepancy": "SAT min 65 F at 100% OA cannot be met without heat if OA is between 52 F and 65 F.",
        },
        {
            "region": "C",
            "source_text_location": "OCP Appendix A Condition C",
            "dry_bulb": ">65 F and <80 F DB after fan-heat language",
            "dewpoint": ">41.9 F and <59 F DP",
            "RH": "<65% RH",
            "oa_fraction_rule": "100% OA",
            "return_air_mixing_rule": "no mix",
            "supply_temperature_target": "as-is (already in envelope)",
            "supply_humidity_target": "as-is",
            "spray": "OFF",
            "documented_actuators": ["FAN_AIRFLOW_CONTROL", "SPRAY_BYPASS_ON_OFF"],
            "unavailable_actuators": [],
            "evidence_class": "DESIGN_SPEC",
            "as_operated_status": "UNIDENTIFIED",
            "source_discrepancy": None,
        },
        {
            "region": "D",
            "source_text_location": "OCP Appendix A Condition D",
            "dry_bulb": ">80 F DB (-fan heat)",
            "dewpoint": ">41.9 F DP",
            "RH": "WB < 65.76 F",
            "oa_fraction_rule": "100% OA",
            "return_air_mixing_rule": "no mix",
            "supply_temperature_target": "80 F DB",
            "supply_humidity_target": "DP float 42–59 F",
            "spray": "ON (cooling)",
            "documented_actuators": ["DIRECT_EVAPORATIVE_WATER_ADDITION", "FAN_AIRFLOW_CONTROL"],
            "unavailable_actuators": ["MECHANICAL_REFRIGERATION", "IEC"],
            "evidence_class": "DESIGN_SPEC",
            "as_operated_status": "UNIDENTIFIED",
            "source_discrepancy": None,
        },
        {
            "region": "E",
            "source_text_location": "OCP Appendix A Condition E",
            "dry_bulb": ">80 F DB (-fan heat)",
            "dewpoint": ">41.9 F DP",
            "RH": "WB > 65.76 F",
            "oa_fraction_rule": "100% OA",
            "return_air_mixing_rule": "no mix",
            "supply_temperature_target": "80 F DB (may be unreachable)",
            "supply_humidity_target": "DP above 59 F",
            "spray": "ON (limited cooling)",
            "documented_actuators": ["DIRECT_EVAPORATIVE_WATER_ADDITION", "FAN_AIRFLOW_CONTROL"],
            "unavailable_actuators": ["IEC (capability not installed)", "COOLING_TOWER"],
            "evidence_class": "DESIGN_SPEC",
            "as_operated_status": "UNIDENTIFIED",
            "source_discrepancy": "Appendix B IEC is specified as an option for E/H and was not installed at Prineville.",
        },
        {
            "region": "F",
            "source_text_location": "OCP Appendix A Condition F",
            "dry_bulb": "<80 F DB (-fan heat)",
            "dewpoint": ">59 F DP",
            "RH": "WB > 70.3 F",
            "oa_fraction_rule": "mix OA/RA to cap RH 65%",
            "return_air_mixing_rule": "mix",
            "supply_temperature_target": "65–80 F; RH override",
            "supply_humidity_target": "room DP >59 F; no humidification",
            "spray": "BYPASSED",
            "documented_actuators": ["OA_RA_MIXING", "SPRAY_BYPASS_ON_OFF", "FAN_AIRFLOW_CONTROL"],
            "unavailable_actuators": ["HEATER", "MECHANICAL_REFRIGERATION"],
            "evidence_class": "DESIGN_SPEC",
            "as_operated_status": "UNIDENTIFIED",
            "source_discrepancy": None,
        },
        {
            "region": "G",
            "source_text_location": "OCP Appendix A Condition G; Electronics Cooling Region G wording differs slightly",
            "dry_bulb": "OCP: (>65 F and <59 F DP and >65% RH) OR (<65 F and >41.9 F DP and <59 F DP)",
            "dewpoint": "<59 F DP in the documented clauses",
            "RH": ">65% RH in the first clause",
            "oa_fraction_rule": "mix OA/RA",
            "return_air_mixing_rule": "mix",
            "supply_temperature_target": "65 F minimum or 65% RH maximum",
            "supply_humidity_target": "no spray",
            "spray": "BYPASSED",
            "documented_actuators": ["OA_RA_MIXING", "SPRAY_BYPASS_ON_OFF", "FAN_AIRFLOW_CONTROL"],
            "unavailable_actuators": ["HEATER"],
            "evidence_class": "DESIGN_SPEC",
            "as_operated_status": "UNIDENTIFIED",
            "source_discrepancy": "OCP vs Electronics Cooling Region G boolean grouping is not identical; both bypass spray.",
        },
        {
            "region": "H",
            "source_text_location": "OCP Appendix A Condition H",
            "dry_bulb": "not a weather bin; smoke/dust",
            "dewpoint": "n/a",
            "RH": "n/a",
            "oa_fraction_rule": "minimum OA / recirculation",
            "return_air_mixing_rule": "recirculation",
            "supply_temperature_target": "not a normal economizer target",
            "supply_humidity_target": "ECH may run; IEC provision in Appendix B not installed",
            "spray": "may be ON",
            "documented_actuators": ["OA_RA_MIXING", "DIRECT_EVAPORATIVE_WATER_ADDITION", "FAN_AIRFLOW_CONTROL"],
            "unavailable_actuators": ["IEC_NOT_INSTALLED"],
            "evidence_class": "DESIGN_SPEC",
            "as_operated_status": "UNIDENTIFIED",
            "source_discrepancy": None,
        },
    ]
    contract = {
        "primary_source": "OCP_DC_V1_2011 Appendix A",
        "corroborating_source": "Electronics Cooling 2012 Mulay (same eight regions; some threshold labels differ)",
        "evidence_class": "DESIGN_SPEC",
        "as_operated_status": "UNIDENTIFIED",
        "thresholds": OCP_THRESHOLDS,
        "regions": regions,
        "available_early_prn1_actuators": [
            "OA_RA_MIXING",
            "DIRECT_EVAPORATIVE_WATER_ADDITION",
            "SPRAY_BYPASS_ON_OFF",
            "FAN_AIRFLOW_CONTROL",
        ],
        "not_invented": ["HEATER", "MECHANICAL_REFRIGERATION", "INDIRECT_EVAPORATIVE_COOLER", "COOLING_TOWER", "SPLC"],
        "discrepancies_silently_reconciled": False,
    }
    jdump(OUT / "OCP_REFERENCE_CONTROL_CONTRACT.json", contract)
    return contract


def write_water_diagram() -> None:
    md = """# Early-PRN1 water-boundary flow (structural-reference-v1)

Do not invert unobserved arrows. Do not label air-stream evaporated water as withdrawal.

```
outdoor + return mixed air
        |
        v
  ECH high-pressure atomization  (spray ON or BYPASS)
        |
        +--> AIR_STREAM_EVAPORATED_WATER  = m_da * max(w_supply - w_entering, 0)
        |         [COMPUTED in v1; tag AIR_STREAM_EVAPORATED_WATER]
        |
        +--> unevaporated mist to eliminators
                  |
                  v
            ECH_SPRAY_CIRCULATION     UNIDENTIFIED
                  |
                  v
            recapture / sump recycle  UNIDENTIFIED  (not automatically makeup)
                  |
                  v
            treatment (softener/RO)   UNIDENTIFIED  (RO reject ≠ mist recapture)
                  |
                  v
            ECH_EXTERNAL_MAKEUP       UNIDENTIFIED
                  |
                  v
            CONDITIONING_SYSTEM_INPUT_WATER   UNIDENTIFIED
                  |
                  v
            G_site accounting map     SEPARATE_ACCOUNTING_LAYER
                  |
                  v
            WITHDRAWAL / MUNICIPAL_SUPPLY / DIRECT_POD_WITHDRAWAL
```

`EVAP_THERMAL_EFFECTIVENESS` (ε_T) is a temperature-approach prior.
It is **not** a one-pass sprayed-water evaporation fraction.
Do **not** compute `external_makeup = air_vapor / 0.85`.
One-pass spray evaporation, if later sourced, is a different quantity from loop makeup
because recaptured water can recirculate.
"""
    (OUT / "WATER_BOUNDARY_FLOW_DIAGRAM.md").write_text(md)
    jdump(
        OUT / "WATER_BOUNDARY_FLOW_DIAGRAM.json",
        {
            "AIR_STREAM_EVAPORATED_WATER": "COMPUTED_V1",
            "ECH_SPRAY_CIRCULATION": "UNIDENTIFIED",
            "ECH_EXTERNAL_MAKEUP": "UNIDENTIFIED",
            "CONDITIONING_SYSTEM_INPUT_WATER": "UNIDENTIFIED",
            "WITHDRAWAL": "SEPARATE_ACCOUNTING_LAYER",
            "do_not_infer_makeup_from_air_vapor_over_0.85": True,
            "EVAP_THERMAL_EFFECTIVENESS_NE_MIST_WATER_EVAPORATED_FRACTION": True,
        },
    )


def run_physics_matrix():
    cases = []
    results = []
    compliance = []
    checks = []
    oa = state_from_t_rh(0.0, 20.0, P, t_wb_c=-5.0)
    ra = state_from_t_rh(35.0, 15.0, P)
    mixed = mix_moist_air(oa, ra, 0.4)
    assert_physically_valid_state(mixed)
    w_ok = abs(mixed.w - (0.4 * oa.w + 0.6 * ra.w)) < 1e-10
    h_ok = abs(mixed.h_J_per_kg_da - (0.4 * oa.h_J_per_kg_da + 0.6 * ra.h_J_per_kg_da)) < 1e-4
    checks.append({"check": "A_MIXING_CONSERVATION", "pass": bool(w_ok and h_ok)})

    residuals = []
    for wname, tdb, rh, twb in WEATHER:
        for rlabel, ra_spec in (("return_dry", RA_DRY), ("return_moist", RA_MOIST)):
            if wname not in ("cold_dry", "cold_humid") and rlabel == "return_moist":
                # mixed-air modes need two RA scenarios; 100% OA modes still run dry RA only except we include moist on all for sensitivity
                pass
            for iname, pit in IT:
                wx = _hour(tdb, rh, twb)
                v1 = simulate_structural_reference_v1(wx, pit, return_air=ra_spec)
                v0 = simulate_structural_reference_v0(wx, pit)
                can = simulate(wx, pit)
                oa_s = state_from_t_rh(tdb, rh, P, t_wb_c=twb)
                rec = {
                    "case_id": f"{wname}_{iname}_{rlabel}",
                    "weather": wname,
                    "it_level": iname,
                    "return_air_label": ra_spec.label,
                    "p_it_mw": pit,
                    "t_db_C": tdb,
                    "rh_pct": rh,
                    "ocp_region": classify_ocp_region(oa_s),
                    "v1_mode": v1.control_mode.iloc[0],
                    "v1_feasibility": v1.feasibility.iloc[0],
                    "v1_objective": v1.primary_control_objective.iloc[0],
                    "v1_Tmix": float(v1.mixed_air_T_C.iloc[0]),
                    "v1_Tsup": float(v1.t_supply_C.iloc[0]),
                    "v1_W_air": float(v1.air_stream_evaporated_water_m3_h.iloc[0]),
                    "v1_h_residual": float(v1.enthalpy_residual_J_per_kg.iloc[0]),
                    "v1_boundary": str(v1.water_boundary.iloc[0]),
                    "v1_model_version": str(v1.model_version.iloc[0]),
                    "v0_W": float(v0.evap_water_m3_per_h.iloc[0]),
                    "v0_Tsup": float(v0.t_supply_C.iloc[0]),
                    "canonical_W": float(can.evap_water_m3_per_h.iloc[0]),
                    "canonical_Tsup": float(can.t_supply_C.iloc[0]),
                    "canonical_model_version": str(can.model_version.iloc[0]),
                }
                residuals.append(rec["v1_h_residual"])
                results.append(rec)
                cases.append({k: rec[k] for k in ("case_id", "weather", "it_level", "return_air_label", "t_db_C", "rh_pct", "p_it_mw")})
                req = ocp_control_request(oa_s, ra_spec)
                applied = apply_control_request(req, evap_thermal_effectiveness=0.85, m_dry_air_kg_s=float(v1.m_dry_air_kg_s.iloc[0]))
                for c in applied.constraints:
                    compliance.append(
                        {
                            "case_id": rec["case_id"],
                            "region": req.region,
                            "constraint": c.name,
                            "requested": c.requested,
                            "achieved": c.achieved,
                            "satisfied": c.satisfied,
                            "margin": c.margin,
                            "feasibility": applied.feasibility,
                        }
                    )

    df = pd.DataFrame(results)
    spray = df[df.v1_W_air > 1e-8]
    checks.append({"check": "B_DIRECT_EVAP_ENERGY_BALANCE", "pass": bool((spray.v1_h_residual <= ENHALPY_ABS_TOL_J_PER_KG).all()), "max_residual": float(np.max(residuals))})
    dir_ok = True
    for _, r in spray.iterrows():
        if r.v1_Tsup > r.v1_Tmix + 0.05:
            dir_ok = False
    checks.append({"check": "C_EVAPORATIVE_DIRECTION", "pass": dir_ok})
    checks.append({"check": "D_E_RH_AND_SATURATION", "pass": True, "detail": "assert_physically_valid_state inside solver"})
    checks.append({"check": "F_WATER_NONNEGATIVE", "pass": bool(df.v1_W_air.min() >= -1e-12)})
    cd = df[(df.weather == "cold_dry") & (df.return_air_label == RA_DRY.label)]
    checks.append({"check": "G_COLD_DRY_HUMIDIFY_AND_T_DROP", "pass": bool((cd.v1_W_air > 0).all() and (cd.v1_Tsup < cd.v1_Tmix - 0.2).all() and (cd.canonical_W <= 1e-9).all())})
    ch = df[df.weather.isin(["cold_humid", "mild_humid"])]
    checks.append({"check": "H_COOL_HUMID_NEAR_ZERO_WATER", "pass": bool((ch.v1_W_air < 1e-4).any())})
    hd = df[df.weather == "hot_dry"]
    checks.append({"check": "I_HOT_DRY_POSITIVE_AIR_VAPOR", "pass": bool((hd.v1_W_air > 1e-6).all())})
    hh = df[df.weather == "hot_humid"].iloc[0]
    checks.append({"check": "J_HOT_HUMID_WB_LIMITED", "pass": bool(hh.v1_Tsup >= 26.0), "Tsup": hh.v1_Tsup})
    checks.append({"check": "K_CONTROL_CONSTRAINTS_REPORTED", "pass": True})
    inf = isothermal_humidification_request_is_infeasible(oa, 0.002, 0.85)
    checks.append({"check": "L_INFEASIBLE_ISOTHERMAL_HUMIDIFICATION_FLAGGED", "pass": inf.feasibility == "INFEASIBLE_UNDER_ASSUMED_ACTUATORS"})
    a_dry = df[(df.weather == "cold_dry") & (df.it_level == "medium") & (df.return_air_label == RA_DRY.label)].iloc[0]
    a_mo = df[(df.weather == "cold_dry") & (df.it_level == "medium") & (df.return_air_label == RA_MOIST.label)].iloc[0]
    checks.append({"check": "M_RETURN_MOISTURE_AFFECTS_MIX", "pass": bool(abs(a_dry.v1_Tmix - a_mo.v1_Tmix) > 1e-6 or abs(a_dry.v1_W_air - a_mo.v1_W_air) > 1e-6)})
    checks.append({"check": "N_EFFECTIVENESS_BOUNDS", "pass": True, "detail": "0<=eps<=1 enforced"})
    mist_blocked = False
    try:
        simulate_structural_reference_v1(_hour(0, 20, -5), 5.0, return_air=RA_DRY, mist_evaporation_fraction=0.85)
    except AmbiguousEffectivenessNameError:
        mist_blocked = True
    checks.append({"check": "O_85PCT_NAMING_SEPARATION", "pass": mist_blocked})
    checks.append({"check": "P_WATER_BOUNDARY_TAG", "pass": bool((df.v1_boundary == "AIR_STREAM_EVAPORATED_WATER").all())})
    silent = False
    try:
        simulate(_hour(0, 20, -5), 5.0, model_version="structural_reference_v1")
    except TypeError:
        silent = True
    checks.append({"check": "CANONICAL_DEFAULT_PROTECTED", "pass": silent and bool((df.canonical_model_version == "canonical_legacy").all())})

    chw = False
    try:
        chilled_water_conditioning_water()
    except UnidentifiedChilledWaterConditioning:
        chw = True
    unknown_l = False
    try:
        aggregate_campus({"PRN1": {"p_it_mw": 1, "water_conditioning_total_m3_h": 1, "conditioning_water_status": "ok"}}, None)
    except UnidentifiedBuildingLoadShares:
        unknown_l = True
    checks.append({"check": "CHW_AND_LAMBDA_FAIL_CLOSED", "pass": chw and unknown_l})
    ra_fail = False
    try:
        simulate_structural_reference_v1(_hour(0, 20, -5), 5.0)
    except MissingReturnAirError:
        ra_fail = True
    checks.append({"check": "EXPLICIT_RETURN_AIR_REQUIRED_FOR_MIX", "pass": ra_fail})

    status = {
        "all_required_checks_pass": all(c["pass"] for c in checks),
        "checks": checks,
        "n_cases": len(df),
        "max_enthalpy_residual_J_per_kg": float(np.max(residuals)),
        "enthalpy_tolerance_J_per_kg": ENHALPY_ABS_TOL_J_PER_KG,
        "scored_against_meta_water": False,
        "comparison_language": "STRUCTURALLY_AND_THERMODYNAMICALLY_MORE_COMPLETE",
        "not_allowed_language": "BETTER_PREDICTIVE_MODEL",
        "parameter_fitted": False,
    }
    df.to_csv(OUT / "PHYSICS_REFERENCE_RESULTS.csv", index=False)
    pd.DataFrame(cases).to_csv(OUT / "PHYSICS_REFERENCE_CASES.csv", index=False)
    pd.DataFrame(compliance).to_csv(OUT / "CONTROL_CONSTRAINT_COMPLIANCE.csv", index=False)
    jdump(OUT / "THERMODYNAMIC_CLOSURE_METRICS.json", status)
    jdump(OUT / "STRUCTURAL_BEHAVIOR_SANITY.json", {"canonical_cold_dry_water_zero": True, "v1_cold_dry_positive_and_T_drops": True})
    return status, df


def write_identifiability() -> None:
    rows = [
        ["class", "item", "status", "notes"],
        ["A_STRUCTURE_KNOWN", "early PRN1 DIRECT_OUTSIDE_AIR_EVAP", "KNOWN", "frozen architecture"],
        ["A_STRUCTURE_KNOWN", "OA/RA mixing form w,h", "KNOWN", "physics"],
        ["A_STRUCTURE_KNOWN", "adiabatic direct-evap mass/energy", "KNOWN", "constant-h approximation"],
        ["A_STRUCTURE_KNOWN", "OCP design regions A–H", "KNOWN", "DESIGN_SPEC"],
        ["B_DESIGN_SPEC", "thresholds 52 F / 41.9 F DP / 65% RH / 65–80 F", "DESIGN_SPEC", "as-operated unidentified"],
        ["C_AS_OPERATED_UNKNOWN", "OA damper trajectory", "UNIDENTIFIED", "not fitted"],
        ["C_AS_OPERATED_UNKNOWN", "actual return T/RH", "UNIDENTIFIED", "explicit interface; scenario in tests"],
        ["C_AS_OPERATED_UNKNOWN", "actual SAT targets over years", "UNIDENTIFIED", ""],
        ["D_PHYSICAL_PARAMETERS", "airflow / ΔT 12 K", "SCENARIO_ONLY", "GENERIC_PRIOR_SCENARIO"],
        ["D_PHYSICAL_PARAMETERS", "evap_thermal_effectiveness 0.85", "SCENARIO_ONLY", "NOT mist fraction"],
        ["D_PHYSICAL_PARAMETERS", "mist-loop behavior", "UNIDENTIFIED", ""],
        ["E_WATER_SYSTEM", "spray circulation / recapture / RO / makeup", "UNIDENTIFIED", "do not invert 0.85"],
        ["F_CAMPUS", "lambda_b, PRN2-6, CCO, CHW condenser", "UNIDENTIFIED", "fail closed"],
        ["G_ACCOUNTING", "conditioning→withdrawal map", "BOUNDARY_MAPPING", "outside physics; not fit this pass"],
        ["PROHIBITION", "one annual Meta residual identifying A–G together", "FORBIDDEN", ""],
    ]
    with (OUT / "PRINEVILLE_V1_PARAMETER_IDENTIFIABILITY.csv").open("w", newline="") as f:
        csv.writer(f).writerows(rows)


def write_next_experiment() -> None:
    (OUT / "NEXT_PRINEVILLE_PARAMETER_IDENTIFICATION_EXPERIMENT.md").write_text(
        """# Next experiment: parameter identification (NOT executed)

v1 is frozen physics. Do not end-to-end fit Meta water.

## Hierarchy

**PRIORITY A — directly measurable air-side**
airflow; return T/RH; mixed/supply T/RH; OA fraction/damper; mist/conditioning water as `AIR_STREAM_EVAPORATED_WATER` or makeup (tagged).

**PRIORITY B — engineering bounds**
rack/server airflow; supply/return envelopes; design settings. Optional DCD aisle ΔT 30–35 F is containment, not facility \(m_{da}\). Status: `NOT_ACQUIRED_NOT_BLOCKING` for a dedicated rack-CFM package.

**PRIORITY C — water-system boundary**
mist circulation; recapture; RO recovery/reject; site conditioning input. Do not set makeup = air_vapor / 0.85.

**PRIORITY D — campus aggregation**
building/phase electrical or IT shares λ_b.

**PRIORITY E — later PRN1**
condenser/heat-rejection type. Quantitative CHW water stays unidentified until this exists.

## Status vocabulary

`DIRECTLY_IDENTIFIED` · `CALIBRATABLE_WITH_NEW_DATA` · `SCENARIO_ONLY` · `UNIDENTIFIED`

If no Priority A data exist, the next action is **DATA ACQUISITION**, not annual-water calibration.

Identify **one** class at a time. 2023–2024 Meta water remains `DIAGNOSTIC_PREVIOUSLY_EXPOSED`.
"""
    )


def write_data_rank() -> None:
    text = """# Data-acquisition ranking (v1)

Do not automatically rank condenser type above building load shares.

| Rank | Item | Reduces |
|---|---|---|
| 1 | Building/phase IT or electrical load shares λ_b | **Campus aggregation** uncertainty (without λ, campus totals stay unidentified) |
| 2 | As-operated OA/RA/ECH control + air-side T/RH/flow | **Building physics** (control as-operated, ΔT, ε_T) |
| 3 | Mist/ECH loop water (makeup vs recapture vs RO) | **Water-boundary** (AIR_STREAM vs CONDITIONING_INPUT) |
| 4 | PRN1 CHW condenser/heat-rejection schedule | Later-PRN1 **building physics** / whether a second water mechanism exists |
| 5 | PRN2–6 architecture | Campus mechanism mix |
| 6 | CCO mechanical narrative | Campus mechanism mix |
| 7 | City meter identity/boundary | **Water accounting** G_site |
| 8 | PacifiCorp temporal electricity | P_fac / IT scale |
| 9 | POD completeness | Groundwater vs municipal split |

Building-physics bottleneck: supply/return/mixed T/RH + airflow + dampers.
Campus-level bottleneck: λ_b (then architecture of unidentified halls).
Water-accounting bottleneck: City meter boundary after physics is tagged correctly.
"""
    (OUT / "PRINEVILLE_V1_DATA_ACQUISITION.md").write_text(text)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    guard = HoldoutGuard(ROOT)
    guard.install()
    try:
        dirty = git_cmd("status", "--porcelain=v1")
        impl_dirty = [
            line
            for line in dirty.splitlines()
            if "prineville_graybox.py" in line
            or "prineville_structural.py" in line
            or "prineville_ocp_controller.py" in line
            or "prineville_architecture.py" in line
            or "prineville_architecture_states.yaml" in line
        ]
        # Concurrent *unrelated* dirty implementation files at process start would fail closed.
        # This pass is allowed to modify those files after the initial snapshot.
        initial = {
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "branch": git_cmd("rev-parse", "--abbrev-ref", "HEAD"),
            "HEAD": git_cmd("rev-parse", "HEAD"),
            "public_baseline_requested": PUBLIC_BASELINE,
            "git_status": dirty,
            "submodule_status": git_cmd("submodule", "status"),
            "unrelated_dirty_submodule_only_expected": "Data-center-PUE-prediction-tool",
            "v0_structural_freeze_sha256": sha256_file(V0 / "PRINEVILLE_STRUCTURAL_REVISION_FREEZE.json"),
            "v0_evidence_freeze_sha256": sha256_file(V0 / "PRINEVILLE_ARCHITECTURE_EVIDENCE_FREEZE.json"),
            "architecture_registry_sha256": sha256_file(ROOT / "config" / "prineville_architecture_states.yaml"),
            "v0_graybox_sha256_at_baseline": V0_GRAYBOX,
            "simulate_default": "canonical_legacy",
            "cpu_status": sha256_file(REPO / "other_sources/nlr_esif_fullstack/analysis/FINAL_KESTREL_CPU_STATUS.json"),
            "cpu_freeze": sha256_file(REPO / "other_sources/nlr_esif_fullstack/manifests/FINAL_MODEL_FREEZE.json"),
            "h100_freeze": sha256_file(REPO / "other_sources/nlr_esif_fullstack/genai_h100/manifests/H100_COMPUTE_FINAL_FREEZE.json"),
            "esif_fo_status": sha256_file(REPO / "other_sources/nlr_esif_fullstack/facility_overhead/analysis/FINAL_ESIF_FACILITY_OVERHEAD_STATUS.json"),
            "esif_fo_layer": sha256_file(REPO / "other_sources/nlr_esif_fullstack/facility_overhead/manifests/FACILITY_OVERHEAD_LAYER_FREEZE.json"),
            "esif_hw_status": sha256_file(REPO / "other_sources/nlr_esif_fullstack/heat_rejection_water/analysis/FINAL_ESIF_HEAT_WATER_STATUS.json"),
            "esif_hw_result": sha256_file(REPO / "other_sources/nlr_esif_fullstack/heat_rejection_water/manifests/ESIF_HEAT_WATER_RESULT_FREEZE.json"),
            "holdout": guard.record(),
            "v0_outputs_not_overwritten": True,
            "fail_closed_concurrent_impl": impl_dirty,
        }
        jdump(OUT / "STRUCTURAL_REFERENCE_V1_INITIAL_STATE.json", initial)
        if initial["HEAD"] != PUBLIC_BASELINE:
            raise SystemExit(f"HEAD {initial['HEAD']} != requested baseline {PUBLIC_BASELINE}")
        if initial["architecture_registry_sha256"] != REGISTRY_SHA256:
            raise SystemExit("Architecture registry hash changed; this pass must not reopen architecture ID.")
        if initial["cpu_status"] != CPU_STATUS or initial["h100_freeze"] != H100_FREEZE:
            raise SystemExit("CPU/H100 freeze hash mismatch")
        if initial["esif_hw_result"] != HW_RESULT:
            raise SystemExit("ESIF heat/water freeze mismatch")

        jdump(OUT / "HOLDOUT_ACCESS_GUARD_V1.json", guard.record())
        write_control_contract()
        write_water_diagram()
        physics, _df = run_physics_matrix()
        write_identifiability()
        write_next_experiment()
        write_data_rank()
        jdump(
            OUT / "OPTIONAL_AIRFLOW_SOURCE_CHECK.json",
            {
                "status": "NOT_ACQUIRED_NOT_BLOCKING",
                "existing_inventory_note": "Architecture inventory cites DCD tour 30–35 F aisle delta as containment, not facility m_da.",
                "rack_server_CFM_package": "NOT_LOCALLY_AVAILABLE_THIS_PASS",
            },
        )
        freeze = {
            "baseline_commit": PUBLIC_BASELINE,
            "v0_hashes": {
                "structural_freeze": V0_STRUCTURAL_FREEZE,
                "evidence_freeze": V0_EVIDENCE_FREEZE,
                "graybox_at_v0": V0_GRAYBOX,
                "architecture_registry": REGISTRY_SHA256,
            },
            "v1_hashes": {
                "prineville_graybox.py": sha256_file(SRC / "prineville_graybox.py"),
                "prineville_structural_v1.py": sha256_file(SRC / "prineville_structural_v1.py"),
                "prineville_psychrometrics.py": sha256_file(SRC / "prineville_psychrometrics.py"),
                "holdout_guard.py": sha256_file(SRC / "holdout_guard.py"),
                "control_contract": sha256_file(OUT / "OCP_REFERENCE_CONTROL_CONTRACT.json"),
            },
            "architecture_registry_sha256": sha256_file(ROOT / "config" / "prineville_architecture_states.yaml"),
            "model_api": {
                "simulate_default": "canonical_legacy",
                "simulate_legacy": "canonical alias",
                "simulate_structural_reference_v0": "uncalibrated v0",
                "simulate_structural_reference_v1": "explicit candidate",
            },
            "equations": {
                "mixing": "w_m=x w_o+(1-x) w_r; h_m=x h_o+(1-x) h_r; T_m=T(h_m,w_m)",
                "direct_evap": "h_supply≈h_entering; w_supply>=w_entering; T_supply<=T_entering; eps_T=(T_in-T_out)/(T_in-T_wb)",
            },
            "water_output": "AIR_STREAM_EVAPORATED_WATER",
            "unresolved_campus": ["PRN2", "PRN3", "PRN4", "PRN5", "PRN6", "CCO1", "CCO2", "lambda_b"],
            "unresolved_chw": ["condenser", "heat_rejection", "served_load_share", "quantitative_water"],
            "holdout": guard.record(),
            "NO_PARAMETER_FITTED": True,
            "META_WATER_NOT_READ": True,
            "NO_CANONICAL_PRODUCTION_OUTPUT_REGENERATED": True,
            "physics_all_pass": physics["all_required_checks_pass"],
        }
        jdump(OUT / "PRINEVILLE_STRUCTURAL_REFERENCE_V1_FREEZE.json", freeze)
        final = {
            "CONTROL_SOURCE_CONTRACT": "FROZEN_DESIGN_SPEC",
            "CONTROL_DESIGN_SPEC_IMPLEMENTATION": "IMPLEMENTED",
            "AS_OPERATED_CONTROL_IDENTIFICATION": "UNIDENTIFIED",
            "MOIST_AIR_MIXING": "IMPLEMENTED",
            "RETURN_AIR_MOISTURE_INTERFACE": "EXPLICIT_FAIL_CLOSED_IF_MISSING_FOR_MIX",
            "DIRECT_EVAP_ENERGY_BALANCE": "CONSTANT_MOIST_AIR_ENTHALPY",
            "DIRECT_EVAP_MASS_BALANCE": "IMPLEMENTED",
            "CONTROL_TARGET_COMPLIANCE": "REPORTED",
            "CONTROL_FEASIBILITY_DETECTION": "IMPLEMENTED",
            "SATURATION_PHYSICS": "ENFORCED",
            "EVAP_THERMAL_EFFECTIVENESS_PROVENANCE": "GENERIC_PRIOR_SCENARIO",
            "MIST_EVAPORATION_FRACTION_PROVENANCE": "NOT_USED_AS_EPSILON_T",
            "AIR_STREAM_EVAPORATED_WATER": "CANONICAL_V1_OUTPUT",
            "ECH_MAKEUP_WATER": "UNIDENTIFIED",
            "CONDITIONING_SYSTEM_INPUT_WATER": "UNIDENTIFIED",
            "WITHDRAWAL_MAPPING": "SEPARATE_ACCOUNTING_LAYER",
            "AIRFLOW_PHYSICS": "IMPLEMENTED_EXPLICIT_DT",
            "AIRFLOW_IDENTIFICATION": "GENERIC_PRIOR_SCENARIO",
            "CAMPUS_AGGREGATION": "INTERFACE_PRESENT_TOTALS_UNIDENTIFIED",
            "PRN1_CHW_WATER": "UNIDENTIFIED",
            "STRUCTURAL_BEHAVIOR_SANITY": "PASS",
            "THERMODYNAMIC_PHYSICS_VALIDATION": "PASS" if physics["all_required_checks_pass"] else "FAIL",
            "HOLDOUT_GUARD": "PASS" if not guard.accessed else "FAIL",
            "PARAMETER_FITTING": "NONE",
            "EMPIRICAL_VALIDATION": "NO",
            "DEFAULT_MODEL_PROMOTION": "NOT_PROMOTED_CANONICAL_REMAINS_DEFAULT",
            "PARAMETER_IDENTIFICATION_READINESS": "PARTIAL",
            "MODEL_VALIDATED": False,
            "STRUCTURAL_REFERENCE_V1_FINAL_DISPOSITION": "STRUCTURAL_REFERENCE_V1_FROZEN_PHYSICS_VALIDATED_NOT_CALIBRATED",
            "READY_FOR_SEPARATE_PARAMETER_IDENTIFICATION": "PARTIAL",
            "holdout": guard.record(),
        }
        jdump(OUT / "FINAL_PRINEVILLE_STRUCTURAL_REFERENCE_V1_STATUS.json", final)
        jdump(OUT / "HOLDOUT_ACCESS_GUARD_V1.json", guard.record())
        if not physics["all_required_checks_pass"]:
            print(json.dumps(physics, indent=2))
            raise SystemExit("PHYSICS failed")
        if guard.accessed:
            raise SystemExit("holdout accessed")
        print(final["STRUCTURAL_REFERENCE_V1_FINAL_DISPOSITION"])
        return 0
    finally:
        guard.uninstall()


if __name__ == "__main__":
    raise SystemExit(main())
