"""Forest City controller. Independent of Prineville OCP A–H regions.

Source-supported envelope (DESIGN_SPEC unless noted):
  T_INLET_MAX = 85 F   (Maguire 2011 planned; OCP 2013 operator blog)
  RH_MAX      = 90 %   (same)
  DX          = installed backup; OPERATOR_OBSERVED unused summer 2012
  evaporative / free cooling primary
  high-RH: mix hot return air to stay within 90% RH cap
  hot/dry: evaporative cooling; DX not required on 2012-07-01

NOT copied from Prineville (UNIDENTIFIED here, do not fill):
  dewpoint minimum 41.9 F
  SAT mix target 65 F
  SAT floor 54 F
  SAT max 80 F
  RH max 65%
  wet-bulb splits 65.76 F / 70.3 F
  regions A–H
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from psychrometrics_adapter import (
    MoistAirState,
    assert_physically_valid_state,
    c_to_f,
    f_to_c,
    mix_moist_air,
    oa_fraction_for_rh_cap,
    state_on_constant_enthalpy,
)

T_INLET_MAX_F = 85.0
RH_MAX = 0.90
T_INLET_MAX_C = f_to_c(T_INLET_MAX_F)

# Forest City sources do not document a SAT lower bound independent of Prineville.
T_INLET_MIN_C = None
T_DP_MIN_C = None

CONTROL_CONTRACT_ID = "FOREST_CITY_REFERENCE_CONTROL_CONTRACT_V1"
EVIDENCE_CLASS_ENVELOPE = "DESIGN_SPEC"
AS_OPERATED_STATUS = "UNIDENTIFIED"


class MissingReturnAirError(ValueError):
    pass


@dataclass
class ForestCityControlRequest:
    region: str
    control_mode: str
    oa_fraction: float
    mixed: MoistAirState
    spray_enabled: bool
    dx_required: bool
    primary_control_objective: str
    available_actuators: tuple[str, ...]
    t_sa_max_c: float
    rh_max: float
    t_cool_target_c: float | None
    evidence_class: str = "DESIGN_SPEC"
    as_operated_status: str = "UNIDENTIFIED"
    design_vs_observed: str = "DESIGN_SPEC"
    notes: str = ""
    source_ids: tuple[str, ...] = ()
    unresolved: bool = False


def _oa_in_envelope(oa: MoistAirState) -> bool:
    return oa.T_C <= T_INLET_MAX_C + 1e-6 and oa.rh <= RH_MAX + 1e-6


def _mix_for_rh_cap(oa: MoistAirState, ra: MoistAirState) -> tuple[float, MoistAirState, bool]:
    """Maximum OA (minimum hot-RA) that keeps mixed RH <= 90% and T <= 85 F.

    Source: OCP 2013 operator blog — high-RH days mix hot return air to bring
    supply RH within the 90% cap. SAT minimum is UNIDENTIFIED; not forced.
    """
    x, mixed = oa_fraction_for_rh_cap(oa, ra, RH_MAX, t_min_c=-100.0, t_max_c=T_INLET_MAX_C)
    ok = mixed.rh <= RH_MAX + 1e-5 and mixed.T_C <= T_INLET_MAX_C + 1e-5
    if mixed.T_C > T_INLET_MAX_C + 1e-5:
        # Too much hot RA. Search for any x keeping both constraints.
        found = False
        best_x, best = 1.0, oa
        for i in range(101):
            xi = i / 100.0
            m = mix_moist_air(oa, ra, xi)
            if m.rh <= RH_MAX + 1e-5 and m.T_C <= T_INLET_MAX_C + 1e-5:
                best_x, best, found = xi, m, True
                break
        return best_x, best, found
    return x, mixed, ok


def forest_city_control_request(
    oa: MoistAirState,
    ra: MoistAirState | None,
    *,
    evap_thermal_effectiveness: float = 1.0,
) -> ForestCityControlRequest:
    """Map outdoor state to a Forest-City-sourced control request.

    Physics (evaporation reachability) is evaluated later. This function only
    chooses actuators from the documented envelope. Effectiveness is used only
    to classify whether evaporative cooling can reach 85 F in the hot-dry
    branch so DX_REQUIRED can be labeled without a hidden Prineville region.
    """
    assert_physically_valid_state(oa)
    if ra is None:
        raise MissingReturnAirError(
            "Forest City mixing modes require an explicit return-air state "
            "(DESIGN_REFERENCE_SCENARIO or DIRECT_INPUT). AS_OPERATED_RA is UNIDENTIFIED."
        )
    assert_physically_valid_state(ra)

    t_f = c_to_f(oa.T_C)
    rh = oa.rh

    # --- Case 1: outdoor already inside 85 F / 90% RH envelope ---
    if _oa_in_envelope(oa):
        return ForestCityControlRequest(
            region="OA_IN_ENVELOPE",
            control_mode="OA_FREE_COOLING",
            oa_fraction=1.0,
            mixed=oa,
            spray_enabled=False,
            dx_required=False,
            primary_control_objective="NONE",
            available_actuators=("FAN_AIRFLOW_CONTROL",),
            t_sa_max_c=T_INLET_MAX_C,
            rh_max=RH_MAX,
            t_cool_target_c=None,
            design_vs_observed="DESIGN_SPEC",
            source_ids=("MAGUIRE_2011_OCP_REFLECTIONS", "OCP_2013_HOT_HUMID"),
            notes="OA already T<=85F and RH<=90%. 100% OA; evaporative off; DX off. SAT min UNIDENTIFIED.",
        )

    # --- Case 2: T already acceptable, RH above 90% — hot-RA mixing ---
    if oa.T_C <= T_INLET_MAX_C + 1e-6 and rh > RH_MAX:
        x, mixed, ok = _mix_for_rh_cap(oa, ra)
        dx = not ok
        return ForestCityControlRequest(
            region="HIGH_RH_MODERATE_T",
            control_mode="HIGH_RH_RETURN_AIR_MIXING" if ok else "DX_REQUIRED_DEHUMIDIFY",
            oa_fraction=float(x),
            mixed=mixed,
            spray_enabled=False,
            dx_required=bool(dx),
            primary_control_objective="RH_CAP",
            available_actuators=("OA_RA_MIXING", "FAN_AIRFLOW_CONTROL")
            + (("DX_BACKUP",) if dx else ()),
            t_sa_max_c=T_INLET_MAX_C,
            rh_max=RH_MAX,
            t_cool_target_c=None,
            design_vs_observed="OPERATOR_OBSERVED_MECHANISM" if ok else "DESIGN_SPEC_DX_BACKUP",
            source_ids=("OCP_2013_HOT_HUMID", "HSU_MULAY_FOREST_CITY_DX"),
            notes=(
                "High RH, DB already <=85F. Mix hot return air to reduce supply RH to 90% cap. "
                "Evaporative off (cannot dry by adding water). DX only if mixing cannot meet both caps."
            ),
            unresolved=not ok,
        )

    # --- Case 3: T above 85 F — try evaporative cooling at 100% OA ---
    # Reachable T under constant-enthalpy evaporation: T_out >= T_wb (ideal) or
    # T_in - eps*(T_in-T_wb). DX required if even the assumed process cannot reach 85 F
    # without violating RH<=90%.
    t_wb = oa.T_wb_C
    eps = float(np.clip(evap_thermal_effectiveness, 0.0, 1.0))
    t_limit = oa.T_C - eps * max(oa.T_C - t_wb, 0.0)
    can_reach_t = t_limit <= T_INLET_MAX_C + 1e-6
    # RH after cooling toward 85 F (or to the wet-bulb limit).
    t_try = min(oa.T_C, max(t_limit, T_INLET_MAX_C))
    supply_try = state_on_constant_enthalpy(oa, t_try)
    rh_ok = supply_try.rh <= RH_MAX + 1e-5
    if can_reach_t and rh_ok:
        return ForestCityControlRequest(
            region="HOT_DRY_EVAPORATIVE",
            control_mode="EVAPORATIVE_COOLING",
            oa_fraction=1.0,
            mixed=oa,
            spray_enabled=True,
            dx_required=False,
            primary_control_objective="COOLING",
            available_actuators=("DIRECT_EVAPORATIVE_WATER_ADDITION", "FAN_AIRFLOW_CONTROL"),
            t_sa_max_c=T_INLET_MAX_C,
            rh_max=RH_MAX,
            t_cool_target_c=T_INLET_MAX_C,
            design_vs_observed="OPERATOR_OBSERVED_MECHANISM",
            source_ids=("OCP_2013_HOT_HUMID", "MAGUIRE_2011_OCP_REFLECTIONS"),
            notes=(
                f"OA {t_f:.1f}F > 85F. 100% OA evaporative cooling toward 85F. "
                f"T_wb={c_to_f(t_wb):.1f}F. DX not requested under assumed effectiveness."
            ),
        )

    # Simultaneous high T and insufficient evaporative margin (high WB / high RH).
    # Mixing hot RA raises T further — it cannot substitute for cooling.
    # DX is the documented backup (Hsu/Mulay: sized to dehumidify OA in extremes).
    return ForestCityControlRequest(
        region="EXTREME_HOT_HUMID",
        control_mode="DX_REQUIRED",
        oa_fraction=1.0,
        mixed=oa,
        spray_enabled=True,
        dx_required=True,
        primary_control_objective="COOLING_OR_DEHUMIDIFY",
        available_actuators=("DIRECT_EVAPORATIVE_WATER_ADDITION", "DX_BACKUP", "FAN_AIRFLOW_CONTROL"),
        t_sa_max_c=T_INLET_MAX_C,
        rh_max=RH_MAX,
        t_cool_target_c=T_INLET_MAX_C,
        design_vs_observed="DESIGN_SPEC_DX_BACKUP",
        source_ids=("OCP_2013_HOT_HUMID", "HSU_MULAY_FOREST_CITY_DX"),
        notes=(
            "OA above 85F and evaporative process cannot meet 85F/90%RH under the assumed "
            "effectiveness. DX backup is the documented actuator. Not fitted."
        ),
        unresolved=False,
    )


def classify_mode_label(req: ForestCityControlRequest) -> str:
    if req.dx_required:
        return "DX_REQUIRED"
    if req.spray_enabled:
        return "EVAPORATIVE_COOLING"
    if req.oa_fraction < 0.999:
        return "RETURN_AIR_MIXING"
    return "OA_FREE_COOLING"
