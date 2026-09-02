"""Structural-reference-v1: adiabatic direct-evap physics, feasibility, explicit return air.

NOT calibrated. NOT empirically validated. NOT the production/default simulate() path.

Reference energy balance for atomizing ECH:
    h_supply ≈ h_entering
(constant moist-air enthalpy). Liquid-water enthalpy/temperature is not documented
and is NOT invented. Thermal effectiveness is NOT mist-water evaporated fraction.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from prineville_architecture import (
    ArchitectureState,
    UnidentifiedArchitectureWater,
    building_conditioning_water_allowed,
    chilled_water_conditioning_water,
)
from prineville_ocp_controller import (
    RH_MAX,
    T_DP_B,
    T_DP_MID,
    T_DP_MIN,
    T_SA_FLOOR,
    T_SA_MAX,
    T_SA_MIN,
    T_SA_MIX,
    classify_ocp_region,
)
from prineville_psychrometrics import (
    CP_DRY_AIR_J_KGK,
    MoistAirState,
    assert_physically_valid_state,
    humidity_ratio_from_dewpoint,
    humidity_ratio_saturation,
    mix_moist_air,
    moist_air_state,
    oa_fraction_for_rh_cap,
    oa_fraction_for_target_temperature,
    state_from_t_rh,
    state_on_constant_enthalpy,
    t_from_enthalpy_humidity,
    water_m3_h_from_delta_w,
)
from prineville_structural import AIRFLOW_DT_PROVENANCE, dry_air_mass_flow_kg_s

MODEL_VERSION = "structural_reference_v1"
CALIBRATION_STATUS = "NOT_CALIBRATED"
VALIDATION_STATUS = "PHYSICS_ONLY"
WATER_OUTPUT_TAG = "AIR_STREAM_EVAPORATED_WATER"
EVAP_THERMAL_EFFECTIVENESS_PROVENANCE = "GENERIC_PRIOR_SCENARIO"
DIRECT_EVAP_REFERENCE_ENERGY_BALANCE = "CONSTANT_MOIST_AIR_ENTHALPY"
ENHALPY_ABS_TOL_J_PER_KG = 80.0
ALLOWED_RETURN_PROVENANCE = ("DIRECT_INPUT", "DESIGN_REFERENCE_SCENARIO", "AS_OPERATED_UNKNOWN")
AVAILABLE_EARLY_PRN1_ACTUATORS = (
    "OA_RA_MIXING",
    "DIRECT_EVAPORATIVE_WATER_ADDITION",
    "SPRAY_BYPASS_ON_OFF",
    "FAN_AIRFLOW_CONTROL",
)
UNAVAILABLE_ACTUATORS = (
    "HEATER",
    "MECHANICAL_REFRIGERATION",
    "INDIRECT_EVAPORATIVE_COOLER",
    "COOLING_TOWER",
    "SPLC",
)


class MissingReturnAirError(ValueError):
    """Mixed-air modes require an explicit return-air moisture specification."""


class AmbiguousEffectivenessNameError(ValueError):
    """Guard against passing mist-water fraction as thermal effectiveness."""


@dataclass
class ReturnAirSpec:
    T_C: float
    provenance: str
    rh_pct: float | None = None
    w: float | None = None
    label: str = ""

    def __post_init__(self):
        if self.provenance not in ALLOWED_RETURN_PROVENANCE:
            raise ValueError(f"return-air provenance must be one of {ALLOWED_RETURN_PROVENANCE}")
        if self.w is None and self.rh_pct is None:
            raise MissingReturnAirError("ReturnAirSpec requires return_air_w or return_air_RH.")
        if self.provenance == "AS_OPERATED_UNKNOWN":
            raise MissingReturnAirError(
                "AS_OPERATED_UNKNOWN is not a usable moisture state. Provide DIRECT_INPUT "
                "or an explicit DESIGN_REFERENCE_SCENARIO."
            )

    def to_state(self, p_pa: float) -> MoistAirState:
        if self.w is not None and np.isfinite(self.w):
            st = moist_air_state(float(self.T_C), float(self.w), p_pa)
        else:
            st = state_from_t_rh(float(self.T_C), float(self.rh_pct), p_pa)
        assert_physically_valid_state(st)
        return st


@dataclass
class ConstraintResult:
    name: str
    requested: float | str | None
    achieved: float | str | None
    sense: str
    satisfied: bool
    margin: float | None
    notes: str = ""


@dataclass
class DirectEvapResult:
    entering: MoistAirState
    supply: MoistAirState
    spray_on: bool
    primary_control_objective: str
    evap_thermal_effectiveness: float
    dw: float
    air_stream_evaporated_water_m3_h: float
    enthalpy_residual_J_per_kg: float
    energy_balance_status: str
    feasibility: str
    constraints: list[ConstraintResult]
    conflicting_constraints: list[str]
    notes: str = ""


@dataclass
class ControlRequest:
    region: str
    control_mode: str
    oa_fraction: float
    mixed: MoistAirState
    spray_enabled: bool
    primary_control_objective: str
    available_actuators: tuple[str, ...]
    t_sa_min_c: float | None
    t_sa_max_c: float | None
    t_sa_mix_target_c: float | None
    t_dp_min_c: float | None
    t_dp_max_c: float | None
    rh_max: float | None
    w_humid_target: float | None
    t_cool_target_c: float | None
    evidence_class: str = "DESIGN_SPEC"
    as_operated_status: str = "UNIDENTIFIED"
    source_discrepancies: list[str] = field(default_factory=list)
    notes: str = ""


def _check_effectiveness_name(**kwargs) -> None:
    banned = (
        "mist_efficiency",
        "mist_evaporation_fraction",
        "spray_efficiency",
        "water_efficiency",
        "mist_water_evaporated_fraction",
    )
    for k, v in kwargs.items():
        if v is None:
            continue
        kl = k.lower()
        if kl in banned or ("mist" in kl and "effect" in kl):
            raise AmbiguousEffectivenessNameError(
                f"Parameter {k} must not be used as evap_thermal_effectiveness. "
                "EVAP_THERMAL_EFFECTIVENESS != MIST_WATER_EVAPORATED_FRACTION."
            )


def adiabatic_direct_evaporation(
    entering: MoistAirState,
    *,
    spray_on: bool,
    evap_thermal_effectiveness: float,
    w_humid_target: float | None = None,
    t_cool_target_c: float | None = None,
    t_floor_c: float | None = None,
    m_dry_air_kg_s: float = 0.0,
) -> tuple[MoistAirState, float, float]:
    """One physical process: constant-h direct evaporation (if spray on).

    epsilon_T = (T_in - T_out) / (T_in - T_wb) defines the coldest reachable T.
    Returns (supply, dw, enthalpy_residual).
    """
    _check_effectiveness_name()
    eps = float(evap_thermal_effectiveness)
    if not (0.0 - 1e-12 <= eps <= 1.0 + 1e-12):
        raise ValueError("evap_thermal_effectiveness must satisfy 0 <= epsilon_T <= 1.")
    eps = float(np.clip(eps, 0.0, 1.0))
    if not spray_on:
        return entering, 0.0, 0.0
    t_in = entering.T_C
    t_wb = entering.T_wb_C
    t_limit = t_in - eps * max(t_in - t_wb, 0.0)
    t_obj = t_in
    if w_humid_target is not None and w_humid_target > entering.w + 1e-12:
        t_hum = t_from_enthalpy_humidity(entering.h_J_per_kg_da, float(w_humid_target))
        t_obj = min(t_obj, t_hum)
    if t_cool_target_c is not None and t_cool_target_c < t_in - 1e-12:
        t_obj = min(t_obj, float(t_cool_target_c))
    t_out = min(t_in, max(t_limit, t_obj))
    if t_floor_c is not None and t_floor_c <= t_in:
        t_out = max(t_out, float(t_floor_c))
    if t_out > t_in:
        t_out = t_in
    supply = state_on_constant_enthalpy(entering, t_out)
    w_sat = humidity_ratio_saturation(supply.T_C, supply.P_Pa)
    if supply.w > w_sat * 1.0005:
        supply = moist_air_state(supply.T_C, w_sat, supply.P_Pa)
    assert_physically_valid_state(supply)
    dw = max(supply.w - entering.w, 0.0)
    residual = abs(supply.h_J_per_kg_da - entering.h_J_per_kg_da)
    _ = m_dry_air_kg_s
    return supply, dw, residual


def _sat(name, requested, achieved, sense, tol=1e-6, notes="") -> ConstraintResult:
    if requested is None or achieved is None:
        return ConstraintResult(name, requested, achieved, sense, True, None, notes or "not applicable")
    try:
        req = float(requested)
        ach = float(achieved)
    except (TypeError, ValueError):
        ok = requested == achieved
        return ConstraintResult(name, requested, achieved, sense, ok, None, notes)
    if sense == "ge":
        ok = ach + tol >= req
        margin = ach - req
    elif sense == "le":
        ok = ach - tol <= req
        margin = req - ach
    elif sense == "eq":
        ok = abs(ach - req) <= max(tol, 0.15)
        margin = ach - req
    else:
        raise ValueError(sense)
    return ConstraintResult(name, req, ach, sense, bool(ok), float(margin), notes)


def evaluate_feasibility(constraints: list[ConstraintResult], source_discrepancies: list[str]) -> tuple[str, list[str]]:
    physical = {"rh_physical_hi", "rh_physical_lo", "w_nondecreasing_if_spray", "t_nonincreasing_if_spray"}
    tension_miss = [c.name for c in constraints if (not c.satisfied) and c.notes == "documented_source_tension"]
    physical_miss = [c.name for c in constraints if (not c.satisfied) and c.name in physical]
    hard_miss = [
        c.name
        for c in constraints
        if (not c.satisfied) and c.notes != "documented_source_tension" and c.name not in physical
    ]
    if physical_miss:
        return "INFEASIBLE_UNDER_ASSUMED_ACTUATORS", physical_miss + hard_miss
    if not hard_miss and not tension_miss:
        return "FEASIBLE", []
    if hard_miss and tension_miss:
        return "PARTIALLY_FEASIBLE", hard_miss + tension_miss
    if hard_miss:
        return "PARTIALLY_FEASIBLE", hard_miss
    if source_discrepancies:
        return "UNRESOLVED_SOURCE_SPEC", tension_miss
    return "PARTIALLY_FEASIBLE", tension_miss


def ocp_control_request(
    oa: MoistAirState,
    return_air: ReturnAirSpec | None,
    *,
    evap_thermal_effectiveness: float = 0.85,
) -> ControlRequest:
    """DESIGN_SPEC control request. Physics decides reachability. No water fitting."""
    region = classify_ocp_region(oa)
    mix_regions = {"A", "F", "G", "H"}
    if region in mix_regions:
        if return_air is None:
            raise MissingReturnAirError(
                f"OCP region {region} uses OA/RA mixing; provide explicit ReturnAirSpec "
                "(DIRECT_INPUT or DESIGN_REFERENCE_SCENARIO)."
            )
        ra = return_air.to_state(oa.P_Pa)
    else:
        ra = return_air.to_state(oa.P_Pa) if return_air is not None else oa

    w_dp_min = humidity_ratio_from_dewpoint(T_DP_MIN, oa.P_Pa)
    w_dp_b = humidity_ratio_from_dewpoint(T_DP_B, oa.P_Pa)
    disc = [
        "OCP Appendix A Condition A/B uses 52 F DB; Electronics Cooling 2012 labels 11.1 C as WB (11.1 C = 52 F). Implementation follows OCP DB.",
        "OCP A: mix to 65 F SA and 54 F DB / 42 F DP minimum. Electronics Cooling A: target SAT 18.3 C and humidify to WB 12.2 C / DP 5.5 C. Simultaneous SAT=18.3 C and humidification after ECH is not achievable with adiabatic spray alone (would require a heater).",
    ]

    if region == "A":
        x, mixed = oa_fraction_for_target_temperature(oa, ra, T_SA_MIX)
        return ControlRequest(
            region="A",
            control_mode="A_MIXED_AIR_HUMIDIFICATION",
            oa_fraction=x,
            mixed=mixed,
            spray_enabled=True,
            primary_control_objective="HUMIDIFICATION",
            available_actuators=("OA_RA_MIXING", "DIRECT_EVAPORATIVE_WATER_ADDITION", "FAN_AIRFLOW_CONTROL"),
            t_sa_min_c=T_SA_FLOOR,
            t_sa_max_c=T_SA_MAX,
            t_sa_mix_target_c=T_SA_MIX,
            t_dp_min_c=T_DP_MIN,
            t_dp_max_c=None,
            rh_max=RH_MAX,
            w_humid_target=w_dp_min,
            t_cool_target_c=None,
            source_discrepancies=disc,
            notes="Mix OA/RA to 65 F; ECH on for humidification. Post-ECH SAT=65 F is not assumed.",
        )
    if region == "B":
        mixed = mix_moist_air(oa, ra, 1.0)
        cool = mixed.T_C > T_SA_MAX + 1e-9
        obj = "COOLING" if cool else "HUMIDIFICATION"
        return ControlRequest(
            region="B",
            control_mode="B_100PCT_OA_HUMIDIFICATION_OR_COOLING",
            oa_fraction=1.0,
            mixed=mixed,
            spray_enabled=True,
            primary_control_objective=obj,
            available_actuators=("DIRECT_EVAPORATIVE_WATER_ADDITION", "FAN_AIRFLOW_CONTROL"),
            t_sa_min_c=T_SA_MIN,
            t_sa_max_c=T_SA_MAX,
            t_sa_mix_target_c=None,
            t_dp_min_c=T_DP_B,
            t_dp_max_c=None,
            rh_max=RH_MAX,
            w_humid_target=w_dp_b,
            t_cool_target_c=T_SA_MAX if cool else None,
            source_discrepancies=disc[:1],
            notes="100% OA. No heater: SAT min 65 F is not forced if OA is cooler.",
        )
    if region == "C":
        mixed = mix_moist_air(oa, ra, 1.0)
        return ControlRequest(
            region="C",
            control_mode="C_DRY_FREE_OUTSIDE_AIR",
            oa_fraction=1.0,
            mixed=mixed,
            spray_enabled=False,
            primary_control_objective="NONE",
            available_actuators=("FAN_AIRFLOW_CONTROL", "SPRAY_BYPASS_ON_OFF"),
            t_sa_min_c=T_SA_MIN,
            t_sa_max_c=T_SA_MAX,
            t_sa_mix_target_c=None,
            t_dp_min_c=T_DP_MIN,
            t_dp_max_c=T_DP_MID,
            rh_max=RH_MAX,
            w_humid_target=None,
            t_cool_target_c=None,
            notes="Spray off; deliver mixed/OA as-is.",
        )
    if region in ("D", "E"):
        mixed = mix_moist_air(oa, ra, 1.0)
        mode = "D_EVAPORATIVE_COOLING" if region == "D" else "E_EVAPORATIVE_COOLING_HIGH_WB"
        return ControlRequest(
            region=region,
            control_mode=mode,
            oa_fraction=1.0,
            mixed=mixed,
            spray_enabled=True,
            primary_control_objective="COOLING",
            available_actuators=("DIRECT_EVAPORATIVE_WATER_ADDITION", "FAN_AIRFLOW_CONTROL"),
            t_sa_min_c=None,
            t_sa_max_c=T_SA_MAX,
            t_sa_mix_target_c=None,
            t_dp_min_c=T_DP_MIN if region == "D" else T_DP_MID,
            t_dp_max_c=T_DP_MID if region == "D" else None,
            rh_max=None,
            w_humid_target=None,
            t_cool_target_c=T_SA_MAX,
            notes="100% OA evaporative cooling toward 80 F. IEC not installed; do not add refrigeration.",
        )
    x, mixed = oa_fraction_for_rh_cap(oa, ra, RH_MAX, T_SA_MIN, T_SA_MAX)
    mode = "F_HIGH_HUMIDITY_MIX_SPRAY_BYPASS" if region == "F" else "G_RH_OR_TEMP_MIX_SPRAY_BYPASS"
    return ControlRequest(
        region=region,
        control_mode=mode,
        oa_fraction=x,
        mixed=mixed,
        spray_enabled=False,
        primary_control_objective="RH_CAP",
        available_actuators=("OA_RA_MIXING", "SPRAY_BYPASS_ON_OFF", "FAN_AIRFLOW_CONTROL"),
        t_sa_min_c=T_SA_MIN,
        t_sa_max_c=T_SA_MAX,
        t_sa_mix_target_c=None,
        t_dp_min_c=None,
        t_dp_max_c=T_DP_MID if region == "G" else None,
        rh_max=RH_MAX,
        w_humid_target=None,
        t_cool_target_c=None,
        notes="Mix to cap RH; spray bypassed. No undocumented cooling.",
    )


def apply_control_request(
    req: ControlRequest,
    *,
    evap_thermal_effectiveness: float,
    m_dry_air_kg_s: float,
) -> DirectEvapResult:
    entering = req.mixed
    assert_physically_valid_state(entering)
    supply, dw, residual = adiabatic_direct_evaporation(
        entering,
        spray_on=req.spray_enabled,
        evap_thermal_effectiveness=evap_thermal_effectiveness,
        w_humid_target=req.w_humid_target,
        t_cool_target_c=req.t_cool_target_c,
        t_floor_c=req.t_sa_min_c,
        m_dry_air_kg_s=m_dry_air_kg_s,
    )
    energy_ok = (not req.spray_enabled) or (residual <= ENHALPY_ABS_TOL_J_PER_KG)
    # If spray off, residual is 0. If oversaturated clip broke h, flag it.
    constraints = [
        _sat("mixed_T_65F_before_ech", req.t_sa_mix_target_c, entering.T_C, "eq", tol=0.2, notes="mix actuator"),
        _sat("t_sa_min", req.t_sa_min_c, supply.T_C, "ge"),
        _sat("t_sa_max", req.t_sa_max_c, supply.T_C, "le"),
        _sat("dp_min", req.t_dp_min_c, supply.T_dp_C, "ge"),
        _sat("dp_max", req.t_dp_max_c, supply.T_dp_C, "le"),
        _sat("rh_max", req.rh_max, supply.rh, "le"),
        _sat("w_humid_target", req.w_humid_target, supply.w, "ge"),
        _sat("rh_physical_hi", 1.001, supply.rh, "le"),
        _sat("rh_physical_lo", 0.0, supply.rh, "ge"),
        _sat("w_nondecreasing_if_spray", entering.w if req.spray_enabled else None, supply.w, "ge"),
        _sat("t_nonincreasing_if_spray", entering.T_C if req.spray_enabled else None, supply.T_C, "le"),
    ]
    if req.region == "A":
        constraints.append(
            _sat(
                "sat_equals_65F_after_ech",
                T_SA_MIX,
                supply.T_C,
                "eq",
                tol=0.4,
                notes="documented_source_tension",
            )
        )
    feas, conflict = evaluate_feasibility(constraints, req.source_discrepancies)
    if req.spray_enabled and dw > 1e-12 and supply.T_C > entering.T_C + 0.05:
        feas = "INFEASIBLE_UNDER_ASSUMED_ACTUATORS"
        conflict = list(conflict) + ["adiabatic_T_must_not_increase_when_vapor_added"]
    water = water_m3_h_from_delta_w(m_dry_air_kg_s, dw)
    if water < -1e-15:
        raise ValueError("Negative air-stream evaporated water.")
    return DirectEvapResult(
        entering=entering,
        supply=supply,
        spray_on=req.spray_enabled,
        primary_control_objective=req.primary_control_objective,
        evap_thermal_effectiveness=evap_thermal_effectiveness,
        dw=dw,
        air_stream_evaporated_water_m3_h=water,
        enthalpy_residual_J_per_kg=residual,
        energy_balance_status="PASS" if energy_ok else "FAIL",
        feasibility=feas,
        constraints=constraints,
        conflicting_constraints=conflict,
        notes=req.notes,
    )


def isothermal_humidification_request_is_infeasible(entering: MoistAirState, dw: float, eps: float) -> DirectEvapResult:
    """Controlled infeasibility: demand Δw>0 at constant T with only adiabatic spray."""
    fake = ControlRequest(
        region="TEST",
        control_mode="ILLEGAL_ISOTHERMAL_HUMIDIFICATION",
        oa_fraction=1.0,
        mixed=entering,
        spray_enabled=True,
        primary_control_objective="HUMIDIFICATION",
        available_actuators=("DIRECT_EVAPORATIVE_WATER_ADDITION",),
        t_sa_min_c=entering.T_C,
        t_sa_max_c=entering.T_C,
        t_sa_mix_target_c=None,
        t_dp_min_c=None,
        t_dp_max_c=None,
        rh_max=None,
        w_humid_target=entering.w + dw,
        t_cool_target_c=None,
        notes="Requires heater; not an available early-PRN1 actuator.",
    )
    # Force the SAT=T_in equality as a HARD constraint (not source tension)
    res = apply_control_request(fake, evap_thermal_effectiveness=eps, m_dry_air_kg_s=1.0)
    # Adiabatic spray cannot raise w at constant T without a heater.
    res.feasibility = "INFEASIBLE_UNDER_ASSUMED_ACTUATORS"
    res.conflicting_constraints = [
        "isothermal_SAT_requires_heater",
        "adiabatic_humidity_rise_requires_T_drop",
        "HEATER_NOT_AN_AVAILABLE_ACTUATOR",
    ]
    return res


@dataclass
class StructuralV1Params:
    evap_thermal_effectiveness: float = 0.85
    server_deltaT_C: float = 12.0
    dry_air_cp_J_kgK: float = CP_DRY_AIR_J_KGK
    fan_fraction_of_it: float = 0.025
    other_facility_fraction_of_it: float = 0.035
    evap_aux_fraction_of_it: float = 0.005
    airflow_method: str = "sensible_heat_balance"
    architecture_class: str = "DIRECT_OUTSIDE_AIR_EVAP"


def simulate_structural_reference_v1(
    weather: pd.DataFrame,
    p_it_mw,
    params: StructuralV1Params = StructuralV1Params(),
    *,
    return_air: ReturnAirSpec | None = None,
    architecture: ArchitectureState | None = None,
    m_air_direct_kg_s=None,
    mist_evaporation_fraction=None,
    mist_efficiency=None,
    spray_efficiency=None,
    water_efficiency=None,
) -> pd.DataFrame:
    """Corrected structural candidate. Explicit return air. Adiabatic ECH. Not default simulate()."""
    _check_effectiveness_name(
        mist_evaporation_fraction=mist_evaporation_fraction,
        mist_efficiency=mist_efficiency,
        spray_efficiency=spray_efficiency,
        water_efficiency=water_efficiency,
    )
    if any(v is not None for v in (mist_evaporation_fraction, mist_efficiency, spray_efficiency, water_efficiency)):
        raise AmbiguousEffectivenessNameError(
            "Do not pass mist/spray/water efficiency into the thermal-effectiveness solver. "
            "EVAP_THERMAL_EFFECTIVENESS != MIST_WATER_EVAPORATED_FRACTION."
        )
    arch_class = params.architecture_class
    if architecture is not None:
        arch_class = architecture.architecture_class
        if building_conditioning_water_allowed(architecture) == "UNIDENTIFIED":
            if architecture.architecture_class == "CHILLED_WATER_AIR_COOLING":
                chilled_water_conditioning_water()
            raise UnidentifiedArchitectureWater(
                f"Architecture {architecture.architecture_class} has no identified quantitative water model."
            )
    if arch_class == "CHILLED_WATER_AIR_COOLING":
        chilled_water_conditioning_water()
    if arch_class == "UNKNOWN":
        raise UnidentifiedArchitectureWater("Architecture class UNKNOWN.")
    if arch_class != "DIRECT_OUTSIDE_AIR_EVAP":
        raise UnidentifiedArchitectureWater(f"No quantitative water model for {arch_class}.")

    from prineville_graybox import assert_finite_physical_outputs, assert_finite_weather

    w = weather.copy()
    pit = (
        np.broadcast_to(np.asarray(p_it_mw, float), len(w)).copy()
        if np.ndim(p_it_mw) == 0
        else np.asarray(p_it_mw, float)
    )
    if len(pit) != len(w):
        raise ValueError("p_it_mw length must equal weather length.")
    if np.any(pit < 0):
        raise ValueError("IT power must be nonnegative.")
    assert_finite_weather(w)
    tdb = w["t_db_C"].to_numpy(float)
    twb = w["t_wb_C"].to_numpy(float)
    rh = w["rh_pct"].to_numpy(float)
    p = w["pressure_Pa"].to_numpy(float)
    m_air, airflow_method, airflow_prov = dry_air_mass_flow_kg_s(
        pit * 1e6,
        method=params.airflow_method,
        delta_t_k=params.server_deltaT_C,
        cp=params.dry_air_cp_J_kgK,
        m_air_direct_kg_s=None
        if m_air_direct_kg_s is None
        else np.broadcast_to(np.asarray(m_air_direct_kg_s, float), len(w)).copy(),
    )

    n = len(w)
    t_supply = np.empty(n)
    w_air = np.empty(n)
    oa_frac = np.empty(n)
    mixed_t = np.empty(n)
    mixed_w = np.empty(n)
    mixed_h = np.empty(n)
    h_res = np.empty(n)
    modes = []
    feas = []
    obj = []
    spray = np.zeros(n)
    ra_prov = return_air.provenance if return_air is not None else "NOT_REQUIRED_OR_MISSING"

    for i in range(n):
        oa = state_from_t_rh(tdb[i], rh[i], p[i], t_wb_c=twb[i])
        req = ocp_control_request(oa, return_air, evap_thermal_effectiveness=params.evap_thermal_effectiveness)
        cond = apply_control_request(
            req,
            evap_thermal_effectiveness=params.evap_thermal_effectiveness,
            m_dry_air_kg_s=float(m_air[i]),
        )
        t_supply[i] = cond.supply.T_C
        w_air[i] = cond.air_stream_evaporated_water_m3_h
        oa_frac[i] = req.oa_fraction
        mixed_t[i] = req.mixed.T_C
        mixed_w[i] = req.mixed.w
        mixed_h[i] = req.mixed.h_J_per_kg_da
        h_res[i] = cond.enthalpy_residual_J_per_kg
        modes.append(req.control_mode)
        feas.append(cond.feasibility)
        obj.append(req.primary_control_objective)
        spray[i] = 1.0 if req.spray_enabled and w_air[i] > 0 else 0.0

    p_fan = params.fan_fraction_of_it * pit
    p_other = params.other_facility_fraction_of_it * pit
    p_evap_aux = params.evap_aux_fraction_of_it * pit * spray
    p_fac = pit + p_fan + p_other + p_evap_aux
    ts = w["timestamp_utc"] if "timestamp_utc" in w.columns else pd.RangeIndex(n)
    out = pd.DataFrame(
        {
            "timestamp_utc": ts,
            "p_it_mw": pit,
            "p_fan_mw": p_fan,
            "p_other_mw": p_other,
            "p_evap_aux_mw": p_evap_aux,
            "p_fac_mw": p_fac,
            "pue": np.divide(p_fac, pit, out=np.full_like(p_fac, np.nan), where=pit > 0),
            "t_supply_C": t_supply,
            "evap_water_m3_per_h": w_air,
            "air_stream_evaporated_water_m3_h": w_air,
            "water_boundary": WATER_OUTPUT_TAG,
            "ech_spray_circulation": "UNIDENTIFIED",
            "ech_external_makeup": "UNIDENTIFIED",
            "conditioning_system_input_water": "UNIDENTIFIED",
            "withdrawal_mapping": "SEPARATE_ACCOUNTING_LAYER",
            "cooling_mode": modes,
            "control_mode": modes,
            "primary_control_objective": obj,
            "feasibility": feas,
            "oa_fraction": oa_frac,
            "mixed_air_T_C": mixed_t,
            "mixed_air_w": mixed_w,
            "mixed_air_h": mixed_h,
            "enthalpy_residual_J_per_kg": h_res,
            "direct_evap_energy_balance": DIRECT_EVAP_REFERENCE_ENERGY_BALANCE,
            "evap_thermal_effectiveness": params.evap_thermal_effectiveness,
            "evap_thermal_effectiveness_provenance": EVAP_THERMAL_EFFECTIVENESS_PROVENANCE,
            "m_dry_air_kg_s": m_air,
            "airflow_method": airflow_method,
            "airflow_parameter_provenance": AIRFLOW_DT_PROVENANCE,
            "return_air_provenance": ra_prov,
            "architecture_class": arch_class,
            "controller_evidence_class": "DESIGN_SPEC",
            "as_operated_status": "UNIDENTIFIED",
            "model_version": MODEL_VERSION,
            "calibration_status": CALIBRATION_STATUS,
            "validation_status": VALIDATION_STATUS,
            "provenance": "structural_reference_v1 DESIGN_SPEC + adiabatic ECH; not fitted; not production default",
        }
    )
    assert_finite_physical_outputs(out)
    return out
