"""Prineville structural conditioning (PHYSICS + CONTROL + ARCHITECTURE interfaces).

Layers (do not conflate):
  CONTROL:            S_t = controller(A, outdoor, return, design_settings)
  PHYSICS:            conditioning = psychrometrics(S_t, mixed air, airflow, parameters)
  ARCHITECTURE:       building_output = architecture_module(A_{b,t}, ...)
  CAMPUS:             campus = sum_b building_output_b   (only if λ identified)
  ACCOUNTING:         W_conditioning -> W_withdrawal is OUTSIDE this module.

No parameter is fitted to Meta water. 12 K ΔT and ε=0.85 remain GENERIC_PRIOR / SCENARIO.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from prineville_architecture import (
    ArchitectureState,
    UnidentifiedArchitectureWater,
    building_conditioning_water_allowed,
    chilled_water_conditioning_water,
)
from prineville_ocp_controller import ocp_reference_controller
from prineville_psychrometrics import (
    CP_DRY_AIR_J_KGK,
    assert_physically_valid_state,
    humidity_ratio_from_enthalpy_t,
    moist_air_state,
    state_from_t_rh,
    water_m3_h_from_delta_w,
)

AIRFLOW_DT_PROVENANCE = "GENERIC_PRIOR / SCENARIO"
EVAP_EFFECTIVENESS_PROVENANCE = "GENERIC_PRIOR / SCENARIO"
ELECTRICAL_PROXY_PROVENANCE = "PROVISIONAL_SCENARIO_NOT_ARCHITECTURE_VALIDATED"
WATER_OUTPUT_BOUNDARY = "CONDITIONING_SITE_WATER"


@dataclass
class StructuralParams:
    return_air_C: float = 35.0
    evap_effectiveness: float = 0.85
    server_deltaT_C: float = 12.0
    dry_air_cp_J_kgK: float = CP_DRY_AIR_J_KGK
    fan_fraction_of_it: float = 0.025
    other_facility_fraction_of_it: float = 0.035
    evap_aux_fraction_of_it: float = 0.005
    airflow_method: str = "sensible_heat_balance"
    architecture_class: str = "DIRECT_OUTSIDE_AIR_EVAP"
    controller: str = "OCP_PRN1_DESIGN_SPEC"


def dry_air_mass_flow_kg_s(
    p_it_w: np.ndarray,
    *,
    method: str,
    delta_t_k: float,
    cp: float,
    m_air_direct_kg_s: np.ndarray | None = None,
) -> tuple[np.ndarray, str, str]:
    """Airflow interface: direct input, sensible-heat balance, or bounded scenario.

    Current 12 K is GENERIC_PRIOR / SCENARIO, not established site truth. Not fitted.
    """
    pit = np.asarray(p_it_w, dtype=float)
    if method == "direct_airflow":
        if m_air_direct_kg_s is None:
            raise ValueError("airflow_method=direct_airflow requires m_air_direct_kg_s.")
        m = np.asarray(m_air_direct_kg_s, dtype=float)
        if m.shape != pit.shape:
            raise ValueError("direct airflow length must match IT power.")
        if np.any(m < 0):
            raise ValueError("Airflow must be nonnegative.")
        return m, "direct_airflow", "MEASURED_OR_SUPPLIED"
    if method == "bounded_scenario":
        if delta_t_k <= 0:
            raise ValueError("Scenario ΔT_air must be positive.")
        return pit / (cp * delta_t_k), "bounded_scenario", AIRFLOW_DT_PROVENANCE
    if method != "sensible_heat_balance":
        raise ValueError(f"Unknown airflow_method {method}.")
    if delta_t_k <= 0:
        raise ValueError("ΔT_air must be explicit and positive.")
    return pit / (cp * delta_t_k), "sensible_heat_balance", AIRFLOW_DT_PROVENANCE


def condition_direct_oa_evap(
    outdoor: object,
    ctrl,
    m_dry_air_kg_s: float,
    evap_effectiveness: float,
) -> dict:
    """Psychrometric conditioning + water mass balance for DIRECT_OUTSIDE_AIR_EVAP.

    Canonical: m_water = m_dry_air * max(w_supply - w_mixed, 0)
    Humidification does not require t_supply < t_entering.
    """
    mixed = moist_air_state(ctrl.mixed_air_T_C, ctrl.mixed_air_w, outdoor.P_Pa)
    assert_physically_valid_state(mixed)
    w_m = mixed.w
    t_m = mixed.T_C
    w_s = float(ctrl.w_supply_target)
    t_s = float(ctrl.T_supply_target_C)

    dw_hum = 0.0
    dw_evap = 0.0
    if ctrl.humidification_required:
        dw_hum = max(w_s - w_m, 0.0)
        t_s = t_m
        w_s = w_m + dw_hum
    elif ctrl.evaporative_sensible_cooling_required:
        t_full = t_m - evap_effectiveness * max(t_m - mixed.T_wb_C, 0.0)
        t_s = min(t_m, max(t_s, t_full)) if t_full <= t_s else t_full
        if t_s < t_m - 1e-12:
            w_from_h = humidity_ratio_from_enthalpy_t(mixed.h_J_per_kg_da, t_s)
            w_s = max(w_m, w_from_h)
            dw_evap = max(w_s - w_m, 0.0)
        else:
            w_s = w_m
            t_s = t_m
    else:
        w_s = w_m
        t_s = t_m

    dw = max(w_s - w_m, 0.0)
    if dw < 0:
        raise ValueError("Negative humidity rise.")
    w_hum = water_m3_h_from_delta_w(m_dry_air_kg_s, dw_hum)
    w_evap = water_m3_h_from_delta_w(m_dry_air_kg_s, dw_evap)
    w_tot = water_m3_h_from_delta_w(m_dry_air_kg_s, dw)
    split_status = "MODEL_DERIVED_DIAGNOSTIC"
    if dw_hum > 0 and dw_evap == 0:
        split_status = "HUMIDIFICATION_ONLY"
    elif dw_evap > 0 and dw_hum == 0:
        split_status = "EVAP_COOLING_ONLY"
    elif dw == 0:
        split_status = "NO_WATER"
    supply = moist_air_state(t_s, w_s, outdoor.P_Pa)
    assert_physically_valid_state(supply)
    if w_tot < -1e-15:
        raise ValueError("Negative conditioning water.")
    return {
        "t_supply_C": t_s,
        "w_supply": w_s,
        "w_mixed": w_m,
        "water_humidification_m3_h": w_hum,
        "water_evap_cooling_m3_h": w_evap,
        "water_conditioning_total_m3_h": w_tot,
        "water_split_status": split_status,
        "water_boundary": WATER_OUTPUT_BOUNDARY,
        "supply_rh": supply.rh,
    }


def simulate_building(
    weather: pd.DataFrame,
    p_it_mw,
    params: StructuralParams = StructuralParams(),
    *,
    architecture: ArchitectureState | None = None,
    m_air_direct_kg_s=None,
) -> pd.DataFrame:
    """Architecture module: quantitative water only for DIRECT_OUTSIDE_AIR_EVAP."""
    arch_class = params.architecture_class
    if architecture is not None:
        arch_class = architecture.architecture_class
        allowed = building_conditioning_water_allowed(architecture)
        if allowed == "UNIDENTIFIED":
            if architecture.architecture_class == "CHILLED_WATER_AIR_COOLING":
                chilled_water_conditioning_water()
            raise UnidentifiedArchitectureWater(
                f"Architecture {architecture.architecture_class} has no identified quantitative water model."
            )

    if arch_class == "CHILLED_WATER_AIR_COOLING":
        chilled_water_conditioning_water()
    if arch_class == "UNKNOWN":
        raise UnidentifiedArchitectureWater(
            "Architecture class UNKNOWN: quantitative conditioning water is UNIDENTIFIED."
        )
    if arch_class != "DIRECT_OUTSIDE_AIR_EVAP":
        raise UnidentifiedArchitectureWater(
            f"No quantitative water model for architecture_class={arch_class}."
        )

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

    from prineville_graybox import assert_finite_weather

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
    water_h = np.empty(n)
    water_e = np.empty(n)
    water_t = np.empty(n)
    oa_frac = np.empty(n)
    mixed_t = np.empty(n)
    mixed_w = np.empty(n)
    mixed_h = np.empty(n)
    modes = []
    split = []
    spray = np.zeros(n)

    for i in range(n):
        oa = state_from_t_rh(tdb[i], rh[i], p[i], t_wb_c=twb[i])
        ctrl = ocp_reference_controller(
            oa,
            t_return_c=params.return_air_C,
            evap_effectiveness=params.evap_effectiveness,
        )
        cond = condition_direct_oa_evap(oa, ctrl, float(m_air[i]), params.evap_effectiveness)
        t_supply[i] = cond["t_supply_C"]
        water_h[i] = cond["water_humidification_m3_h"]
        water_e[i] = cond["water_evap_cooling_m3_h"]
        water_t[i] = cond["water_conditioning_total_m3_h"]
        oa_frac[i] = ctrl.oa_fraction
        mixed_t[i] = ctrl.mixed_air_T_C
        mixed_w[i] = ctrl.mixed_air_w
        mixed_h[i] = ctrl.mixed_air_h
        modes.append(ctrl.control_mode)
        split.append(cond["water_split_status"])
        spray[i] = 1.0 if water_t[i] > 0 else 0.0

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
            "evap_water_m3_per_h": water_t,
            "water_humidification_m3_h": water_h,
            "water_evap_cooling_m3_h": water_e,
            "water_conditioning_total_m3_h": water_t,
            "water_boundary": WATER_OUTPUT_BOUNDARY,
            "water_split_status": split,
            "cooling_mode": modes,
            "control_mode": modes,
            "oa_fraction": oa_frac,
            "mixed_air_T_C": mixed_t,
            "mixed_air_w": mixed_w,
            "mixed_air_h": mixed_h,
            "m_dry_air_kg_s": m_air,
            "airflow_method": airflow_method,
            "airflow_parameter_provenance": airflow_prov,
            "evap_effectiveness_provenance": EVAP_EFFECTIVENESS_PROVENANCE,
            "electrical_proxy_provenance": ELECTRICAL_PROXY_PROVENANCE,
            "architecture_class": arch_class,
            "controller_evidence_class": "DESIGN_SPEC",
            "as_operated_status": "UNIDENTIFIED",
            "provenance": "structural DESIGN_SPEC control + physics; IT power scenario; not fitted to Meta water",
        }
    )
    from prineville_graybox import assert_finite_physical_outputs

    assert_finite_physical_outputs(out)
    return out
