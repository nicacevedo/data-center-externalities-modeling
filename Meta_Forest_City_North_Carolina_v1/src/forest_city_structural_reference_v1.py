"""Forest City structural-reference-v1: shared direct-air physics + local controller.

NOT calibrated. NOT fitted to Forest City water, PUE, or WUE.
WATER_OUTPUT_TAG = AIR_STREAM_EVAPORATED_WATER
Airflow uses an explicit ΔT boundary tag. IT_EQUIPMENT_DELTA_T_DESIGN is not
automatically EFFECTIVE_HEAT_BALANCE_DELTA_T.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from forest_city_controller import (
    T_INLET_MAX_C,
    ForestCityControlRequest,
    MissingReturnAirError,
    forest_city_control_request,
)
from psychrometrics_adapter import (
    CP_DRY_AIR_J_KGK,
    MoistAirState,
    assert_physically_valid_state,
    c_to_f,
    dry_air_mass_flow_from_sensible_heat_kg_s,
    humidity_ratio_saturation,
    moist_air_state,
    state_from_t_rh,
    state_on_constant_enthalpy,
    t_from_enthalpy_humidity,
    water_m3_h_from_delta_w,
)

MODEL_VERSION = "forest_city_structural_reference_v1"
CALIBRATION_STATUS = "NOT_CALIBRATED"
VALIDATION_STATUS = "PHYSICS_AND_OPERATOR_EVENTS_ONLY"
WATER_OUTPUT_TAG = "AIR_STREAM_EVAPORATED_WATER"
ENHALPY_ABS_TOL_J_PER_KG = 80.0

IT_EQUIPMENT_DELTA_T_DESIGN_F = 35.0
IT_EQUIPMENT_DELTA_T_DESIGN_K = IT_EQUIPMENT_DELTA_T_DESIGN_F * 5.0 / 9.0
IT_DELTA_T_STATUS = "IDENTIFIED_DESIGN_SPEC"
FACILITY_EFFECTIVE_DELTA_T_STATUS = "UNIDENTIFIED"
AIRFLOW_BOUNDARY = "IT_EQUIPMENT_DELTA_T_DESIGN_NOT_EFFECTIVE_HEAT_BALANCE"

# Generic prior used only when a numeric evaporative process is required.
# NOT a Forest City sourced value. Primary DX classification also reports eps=1.0.
EVAP_THERMAL_EFFECTIVENESS_GENERIC_PRIOR = 0.85
EVAP_THERMAL_EFFECTIVENESS_PROVENANCE = "GENERIC_PRIOR_SCENARIO_NOT_FOREST_CITY_SOURCED"


class AmbiguousEffectivenessNameError(ValueError):
    pass


class AmbiguousDeltaTBoundaryError(ValueError):
    pass


@dataclass
class ReturnAirSpec:
    T_C: float
    provenance: str
    rh_pct: float | None = None
    w: float | None = None
    label: str = ""

    def __post_init__(self):
        allowed = ("DIRECT_INPUT", "DESIGN_REFERENCE_SCENARIO")
        if self.provenance not in allowed:
            raise MissingReturnAirError(
                f"Return-air provenance must be one of {allowed}. "
                "AS_OPERATED_UNKNOWN is not usable."
            )
        if self.w is None and self.rh_pct is None:
            raise MissingReturnAirError("ReturnAirSpec requires w or RH.")

    def to_state(self, p_pa: float) -> MoistAirState:
        if self.w is not None and np.isfinite(self.w):
            st = moist_air_state(float(self.T_C), float(self.w), p_pa)
        else:
            st = state_from_t_rh(float(self.T_C), float(self.rh_pct), p_pa)
        assert_physically_valid_state(st)
        return st


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
    t_cool_target_c: float | None = None,
    **kwargs,
) -> tuple[MoistAirState, float, float]:
    """Ideal direct evaporative process: h_supply ≈ h_entering; w nondecreasing.

    epsilon_T = (T_in - T_out) / (T_in - T_wb). Same equation as Prineville
    structural-reference-v1; not a copied controller.
    """
    _check_effectiveness_name(**kwargs)
    eps = float(np.clip(evap_thermal_effectiveness, 0.0, 1.0))
    if not spray_on:
        return entering, 0.0, 0.0
    t_in = entering.T_C
    t_wb = entering.T_wb_C
    t_limit = t_in - eps * max(t_in - t_wb, 0.0)
    t_obj = t_in
    if t_cool_target_c is not None and t_cool_target_c < t_in - 1e-12:
        t_obj = min(t_obj, float(t_cool_target_c))
    t_out = min(t_in, max(t_limit, t_obj))
    supply = state_on_constant_enthalpy(entering, t_out)
    w_sat = humidity_ratio_saturation(supply.T_C, supply.P_Pa)
    if supply.w > w_sat * 1.0005:
        supply = moist_air_state(supply.T_C, w_sat, supply.P_Pa)
    assert_physically_valid_state(supply)
    dw = max(supply.w - entering.w, 0.0)
    residual = abs(supply.h_J_per_kg_da - entering.h_J_per_kg_da)
    return supply, dw, residual


def design_return_air_from_supply(supply: MoistAirState) -> MoistAirState:
    """DESIGN_REFERENCE_SCENARIO: sensible-only IT rise of 35 F.

    T_RA = T_supply + 35 F; w_RA = w_supply.
    This is IT_EQUIPMENT_DELTA_T_DESIGN, not measured AHU or facility ΔT.
    """
    t_ra = supply.T_C + IT_EQUIPMENT_DELTA_T_DESIGN_K
    return moist_air_state(t_ra, supply.w, supply.P_Pa)


def iterate_return_air(
    oa: MoistAirState,
    *,
    evap_thermal_effectiveness: float,
    n_iter: int = 8,
) -> tuple[ForestCityControlRequest, MoistAirState, MoistAirState]:
    """Close RA = supply + 35 F design IT rise. Not as-operated RA."""
    ra = moist_air_state(oa.T_C + IT_EQUIPMENT_DELTA_T_DESIGN_K, oa.w, oa.P_Pa)
    req = forest_city_control_request(oa, ra, evap_thermal_effectiveness=evap_thermal_effectiveness)
    supply, _, _ = adiabatic_direct_evaporation(
        req.mixed,
        spray_on=req.spray_enabled,
        evap_thermal_effectiveness=evap_thermal_effectiveness,
        t_cool_target_c=req.t_cool_target_c,
    )
    for _ in range(n_iter):
        ra = design_return_air_from_supply(supply)
        req = forest_city_control_request(oa, ra, evap_thermal_effectiveness=evap_thermal_effectiveness)
        supply, _, _ = adiabatic_direct_evaporation(
            req.mixed,
            spray_on=req.spray_enabled,
            evap_thermal_effectiveness=evap_thermal_effectiveness,
            t_cool_target_c=req.t_cool_target_c,
        )
    return req, ra, supply


def _airflow_kg_s(
    p_it_w: float,
    *,
    airflow_delta_t_k: float | None,
    airflow_boundary: str,
) -> tuple[float, str]:
    if airflow_boundary == "UNIDENTIFIED":
        return float("nan"), "UNIDENTIFIED"
    if airflow_boundary == "IT_EQUIPMENT_DELTA_T_DESIGN":
        dt = IT_EQUIPMENT_DELTA_T_DESIGN_K
        tag = "SCENARIO_ONLY_IT_EQUIPMENT_DELTA_T_DESIGN_NOT_EFFECTIVE"
    elif airflow_boundary == "EXPLICIT_EFFECTIVE_HEAT_BALANCE":
        if airflow_delta_t_k is None or not np.isfinite(airflow_delta_t_k):
            raise AmbiguousDeltaTBoundaryError("Effective ΔT was requested but not supplied.")
        dt = float(airflow_delta_t_k)
        tag = "EXPLICIT_EFFECTIVE_HEAT_BALANCE"
    else:
        raise AmbiguousDeltaTBoundaryError(
            "airflow_boundary must be UNIDENTIFIED, IT_EQUIPMENT_DELTA_T_DESIGN, "
            "or EXPLICIT_EFFECTIVE_HEAT_BALANCE. Do not silently use 12 K."
        )
    return dry_air_mass_flow_from_sensible_heat_kg_s(p_it_w, dt), tag


def simulate_hour(
    *,
    t_db_C: float,
    rh_pct: float,
    pressure_Pa: float,
    t_dew_C: float | None = None,
    p_it_w: float = 1.0,
    evap_thermal_effectiveness: float = EVAP_THERMAL_EFFECTIVENESS_GENERIC_PRIOR,
    airflow_boundary: str = "UNIDENTIFIED",
    airflow_delta_t_k: float | None = None,
    return_air: ReturnAirSpec | None = None,
    **kwargs,
) -> dict:
    _check_effectiveness_name(**kwargs)
    oa = state_from_t_rh(float(t_db_C), float(rh_pct), float(pressure_Pa))
    if return_air is not None:
        ra = return_air.to_state(oa.P_Pa)
        req = forest_city_control_request(oa, ra, evap_thermal_effectiveness=evap_thermal_effectiveness)
        supply, dw, residual = adiabatic_direct_evaporation(
            req.mixed,
            spray_on=req.spray_enabled,
            evap_thermal_effectiveness=evap_thermal_effectiveness,
            t_cool_target_c=req.t_cool_target_c,
        )
    else:
        req, ra, supply = iterate_return_air(oa, evap_thermal_effectiveness=evap_thermal_effectiveness)
        dw = max(supply.w - req.mixed.w, 0.0)
        residual = abs(supply.h_J_per_kg_da - req.mixed.h_J_per_kg_da) if req.spray_enabled else 0.0

    m_air, airflow_tag = _airflow_kg_s(p_it_w, airflow_delta_t_k=airflow_delta_t_k, airflow_boundary=airflow_boundary)
    if np.isfinite(m_air):
        water = water_m3_h_from_delta_w(m_air, dw)
        intensity = water / (p_it_w * 3600.0 / 3.6e6) if p_it_w > 0 else float("nan")  # L/kWh if m3 and kWh
        # water m3/h ; energy kWh/h = p_it_w * 3600 / 3.6e6 = p_it_w / 1000
        kwh = p_it_w / 1000.0
        intensity_L_per_kWh = (water * 1000.0) / kwh if kwh > 0 else float("nan")
    else:
        water = float("nan")
        intensity_L_per_kWh = float("nan")

    t_ok = supply.T_C <= T_INLET_MAX_C + 0.15
    rh_ok = supply.rh <= 0.90 + 1e-3
    dx_physics = bool(req.dx_required) or (req.spray_enabled and not t_ok)
    return {
        "model_version": MODEL_VERSION,
        "calibration_status": CALIBRATION_STATUS,
        "validation_status": VALIDATION_STATUS,
        "water_boundary": WATER_OUTPUT_TAG,
        "region": req.region,
        "control_mode": req.control_mode,
        "oa_fraction": req.oa_fraction,
        "spray_enabled": req.spray_enabled,
        "dx_required": bool(dx_physics),
        "dx_required_controller": bool(req.dx_required),
        "primary_control_objective": req.primary_control_objective,
        "t_oa_C": oa.T_C,
        "t_oa_F": c_to_f(oa.T_C),
        "rh_oa": oa.rh,
        "t_wb_C": oa.T_wb_C,
        "t_supply_C": supply.T_C,
        "t_supply_F": c_to_f(supply.T_C),
        "rh_supply": supply.rh,
        "t_ra_C": ra.T_C,
        "rh_ra": ra.rh,
        "mixed_T_C": req.mixed.T_C,
        "mixed_rh": req.mixed.rh,
        "dw": dw,
        "air_stream_evaporated_water_m3_h": water,
        "air_stream_intensity_L_per_kWh_IT": intensity_L_per_kWh,
        "airflow_boundary": airflow_tag,
        "airflow_kg_s": m_air,
        "enthalpy_residual_J_per_kg": residual,
        "t_inlet_max_satisfied": bool(t_ok),
        "rh_max_satisfied": bool(rh_ok),
        "margin_T_K": T_INLET_MAX_C - supply.T_C,
        "margin_RH": 0.90 - supply.rh,
        "evap_thermal_effectiveness": evap_thermal_effectiveness,
        "evap_effectiveness_provenance": EVAP_THERMAL_EFFECTIVENESS_PROVENANCE
        if abs(evap_thermal_effectiveness - EVAP_THERMAL_EFFECTIVENESS_GENERIC_PRIOR) < 1e-12
        else "EXPLICIT_ARGUMENT",
        "notes": req.notes,
        "design_vs_observed": req.design_vs_observed,
        "unresolved": req.unresolved,
    }


def simulate_frame(
    weather: pd.DataFrame,
    *,
    p_it_w: float = 1.0,
    evap_thermal_effectiveness: float = EVAP_THERMAL_EFFECTIVENESS_GENERIC_PRIOR,
    airflow_boundary: str = "UNIDENTIFIED",
    airflow_delta_t_k: float | None = None,
    rh_col: str = "rh_pct",
) -> pd.DataFrame:
    rows = []
    for _, r in weather.iterrows():
        t = r.get("t_db_C")
        rh = r.get(rh_col)
        p = r.get("pressure_Pa")
        if not (np.isfinite(t) and np.isfinite(rh) and np.isfinite(p)):
            rec = {k: np.nan for k in (
                "oa_fraction", "dw", "air_stream_evaporated_water_m3_h",
                "t_supply_C", "rh_supply",
            )}
            rec.update({
                "control_mode": "WEATHER_MISSING",
                "dx_required": False,
                "region": "WEATHER_MISSING",
                "unresolved": True,
                "spray_enabled": False,
            })
            rows.append(rec)
            continue
        rec = simulate_hour(
            t_db_C=float(t),
            rh_pct=float(rh),
            pressure_Pa=float(p),
            p_it_w=p_it_w,
            evap_thermal_effectiveness=evap_thermal_effectiveness,
            airflow_boundary=airflow_boundary,
            airflow_delta_t_k=airflow_delta_t_k,
        )
        rows.append(rec)
    out = pd.concat([weather.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    return out
