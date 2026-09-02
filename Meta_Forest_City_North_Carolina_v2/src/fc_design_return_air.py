"""Design-reference return-air iteration with an explicit IT rise.

The 35 F value remains IT_EQUIPMENT_DELTA_T_DESIGN. Other rises are
DESIGN_REFERENCE_SCENARIO only. Not as-operated RAT. Not facility effective ΔT.
Humidity-ratio assumption is always w_RA = w_supply (sensible-only).
"""
from __future__ import annotations

import numpy as np

from v1_bridge import (
    T_INLET_MAX_C,
    adiabatic_direct_evaporation,
    forest_city_control_request,
    moist_air_state,
    state_from_t_rh,
)


def iterate_design_return_air(
    oa,
    *,
    rise_k: float,
    evap_thermal_effectiveness: float,
    n_iter: int = 8,
):
    """Close RA = supply + rise_k. w_RA = w_supply. DESIGN_REFERENCE_SCENARIO."""
    ra = moist_air_state(oa.T_C + float(rise_k), oa.w, oa.P_Pa)
    req = forest_city_control_request(oa, ra, evap_thermal_effectiveness=evap_thermal_effectiveness)
    supply, _, _ = adiabatic_direct_evaporation(
        req.mixed,
        spray_on=req.spray_enabled,
        evap_thermal_effectiveness=evap_thermal_effectiveness,
        t_cool_target_c=req.t_cool_target_c,
    )
    for _ in range(n_iter):
        ra = moist_air_state(supply.T_C + float(rise_k), supply.w, oa.P_Pa)
        req = forest_city_control_request(oa, ra, evap_thermal_effectiveness=evap_thermal_effectiveness)
        supply, _, _ = adiabatic_direct_evaporation(
            req.mixed,
            spray_on=req.spray_enabled,
            evap_thermal_effectiveness=evap_thermal_effectiveness,
            t_cool_target_c=req.t_cool_target_c,
        )
    return req, ra, supply


def simulate_hour_design_rise(
    *,
    t_db_C: float,
    rh_pct: float,
    pressure_Pa: float,
    rise_k: float,
    evap_thermal_effectiveness: float,
) -> dict:
    oa = state_from_t_rh(float(t_db_C), float(rh_pct), float(pressure_Pa))
    req, ra, supply = iterate_design_return_air(
        oa,
        rise_k=float(rise_k),
        evap_thermal_effectiveness=evap_thermal_effectiveness,
    )
    t_ok = supply.T_C <= T_INLET_MAX_C + 0.15
    rh_ok = supply.rh <= 0.90 + 1e-3
    dx_physics = bool(req.dx_required) or (req.spray_enabled and not t_ok)
    return {
        "control_mode": req.control_mode,
        "region": req.region,
        "oa_fraction": req.oa_fraction,
        "spray_enabled": req.spray_enabled,
        "dx_required": bool(dx_physics),
        "dx_required_controller": bool(req.dx_required),
        "primary_control_objective": req.primary_control_objective,
        "t_supply_C": supply.T_C,
        "rh_supply": supply.rh,
        "t_ra_C": ra.T_C,
        "rh_ra": ra.rh,
        "w_ra": ra.w,
        "w_supply": supply.w,
        "humidity_ratio_assumption": "w_RA = w_supply (sensible-only IT rise)",
        "t_inlet_max_satisfied": bool(t_ok),
        "rh_max_satisfied": bool(rh_ok),
        "unresolved": req.unresolved,
        "return_air_provenance": "DESIGN_REFERENCE_SCENARIO",
        "it_rise_K": float(rise_k),
        "not_facility_effective_delta_t": True,
        "not_as_operated_rat": True,
    }
