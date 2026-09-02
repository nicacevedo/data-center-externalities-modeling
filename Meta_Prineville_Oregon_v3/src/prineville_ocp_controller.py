"""Early-PRN1 OCP reference psychrometric controller (CONTROLS layer).

Source: Open Compute Project Data Center v1.0 (7 April 2011), Appendix A
(psychrometric sequence of operations), corroborated by Mulay, Electronics
Cooling (10 Dec 2012) for the same eight-region Prineville sequence.

Evidence class: DESIGN_SPEC. This is not AS_OPERATED_CONFIRMED telemetry.
Do not claim the design sequence was followed unchanged every year.
OA fraction is not fitted to Meta water.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from prineville_psychrometrics import (
    MoistAirState,
    f_to_c,
    humidity_ratio_from_dewpoint,
    humidity_ratio_from_enthalpy_t,
    mix_moist_air,
    moist_air_state,
    oa_fraction_for_rh_cap,
    oa_fraction_for_target_temperature,
)

# Documented thresholds — DESIGN_SPEC (OCP Appendix A unless noted).
OCP_THRESHOLDS = {
    "T_DB_A_B_SPLIT_F": {
        "value": 52.0,
        "units": "degF",
        "si_C": f_to_c(52.0),
        "source": "OCP_DC_V1_2011 Appendix A Condition A/B",
        "evidence_class": "DESIGN_SPEC",
        "as_operated": "UNIDENTIFIED",
        "note": "OCP uses dry-bulb. Electronics Cooling 2012 labels 11.1 C as WB; 11.1 C = 52 F. Implementation follows OCP DB.",
    },
    "T_DP_MIN_F": {
        "value": 41.9,
        "units": "degF",
        "si_C": f_to_c(41.9),
        "source": "OCP_DC_V1_2011 §5.1.1 and Appendix A",
        "evidence_class": "DESIGN_SPEC",
        "as_operated": "UNIDENTIFIED",
    },
    "T_SA_MIX_TARGET_F": {
        "value": 65.0,
        "units": "degF",
        "si_C": f_to_c(65.0),
        "source": "OCP_DC_V1_2011 Appendix A Condition A (mix OA/RA to 65 F SA)",
        "evidence_class": "DESIGN_SPEC",
        "as_operated": "UNIDENTIFIED",
    },
    "T_SA_MIN_FLOOR_F": {
        "value": 54.0,
        "units": "degF",
        "si_C": f_to_c(54.0),
        "source": "OCP_DC_V1_2011 Appendix A Condition A (54 F DB minimum)",
        "evidence_class": "DESIGN_SPEC",
        "as_operated": "UNIDENTIFIED",
    },
    "T_SA_MIN_BAND_F": {
        "value": 65.0,
        "units": "degF",
        "si_C": f_to_c(65.0),
        "source": "OCP_DC_V1_2011 Appendix A Conditions B/F; §5.1.1 cold aisle 65–85 F",
        "evidence_class": "DESIGN_SPEC",
        "as_operated": "UNIDENTIFIED",
    },
    "T_SA_MAX_F": {
        "value": 80.0,
        "units": "degF",
        "si_C": f_to_c(80.0),
        "source": "OCP_DC_V1_2011 Appendix A Conditions B/D/E/F",
        "evidence_class": "DESIGN_SPEC",
        "as_operated": "UNIDENTIFIED",
    },
    "T_DP_B_F": {
        "value": 43.0,
        "units": "degF",
        "si_C": f_to_c(43.0),
        "source": "OCP_DC_V1_2011 Appendix A Condition B (43 F DP)",
        "evidence_class": "DESIGN_SPEC",
        "as_operated": "UNIDENTIFIED",
    },
    "T_DP_MID_F": {
        "value": 59.0,
        "units": "degF",
        "si_C": f_to_c(59.0),
        "source": "OCP_DC_V1_2011 Appendix A Conditions C/D/E/F/G",
        "evidence_class": "DESIGN_SPEC",
        "as_operated": "UNIDENTIFIED",
    },
    "T_WB_D_E_SPLIT_F": {
        "value": 65.76,
        "units": "degF",
        "si_C": f_to_c(65.76),
        "source": "OCP_DC_V1_2011 Appendix A Condition D/E",
        "evidence_class": "DESIGN_SPEC",
        "as_operated": "UNIDENTIFIED",
    },
    "T_WB_F_F": {
        "value": 70.3,
        "units": "degF",
        "si_C": f_to_c(70.3),
        "source": "OCP_DC_V1_2011 Appendix A Condition F; §5.1.2 summer WB max",
        "evidence_class": "DESIGN_SPEC",
        "as_operated": "UNIDENTIFIED",
    },
    "RH_MAX": {
        "value": 0.65,
        "units": "1",
        "si_C": None,
        "source": "OCP_DC_V1_2011 §5.1.1 and Appendix A Conditions C/F/G",
        "evidence_class": "DESIGN_SPEC",
        "as_operated": "UNIDENTIFIED",
    },
    "FAN_HEAT_CLEAN_F": {
        "value": 0.62,
        "units": "degF",
        "si_C": f_to_c(32.62) - f_to_c(32.0),
        "source": "OCP_DC_V1_2011 Appendix A note (clean filters, direct systems in bypass)",
        "evidence_class": "DESIGN_SPEC",
        "as_operated": "UNIDENTIFIED",
        "note": "Used only to interpret '(-fan heat)' region boundaries. Not fitted.",
    },
    "T_SA_WB_HUMIDIFY_C": {
        "value": 12.2,
        "units": "degC",
        "si_C": 12.2,
        "source": "Electronics Cooling 2012 Region A (humidify to SAT WB 12.2 C / DP 5.5 C)",
        "evidence_class": "DESIGN_SPEC",
        "as_operated": "UNIDENTIFIED",
        "note": "Corroborating Prineville operations paper; OCP A uses 54 F / 42 F DP minimum.",
    },
}


def _c(name: str) -> float:
    v = OCP_THRESHOLDS[name]["si_C"]
    if v is None:
        return float(OCP_THRESHOLDS[name]["value"])
    return float(v)


T_DB_AB = _c("T_DB_A_B_SPLIT_F")
T_DP_MIN = _c("T_DP_MIN_F")
T_SA_MIX = _c("T_SA_MIX_TARGET_F")
T_SA_FLOOR = _c("T_SA_MIN_FLOOR_F")
T_SA_MIN = _c("T_SA_MIN_BAND_F")
T_SA_MAX = _c("T_SA_MAX_F")
T_DP_B = _c("T_DP_B_F")
T_DP_MID = _c("T_DP_MID_F")
T_WB_DE = _c("T_WB_D_E_SPLIT_F")
T_WB_F = _c("T_WB_F_F")
RH_MAX = float(OCP_THRESHOLDS["RH_MAX"]["value"])
FAN_HEAT_C = float(OCP_THRESHOLDS["FAN_HEAT_CLEAN_F"]["si_C"])


@dataclass
class ControlState:
    control_mode: str
    oa_fraction: float
    mixed_air_T_C: float
    mixed_air_w: float
    mixed_air_h: float
    T_supply_target_C: float
    w_supply_target: float
    humidification_required: bool
    evaporative_sensible_cooling_required: bool
    spray_enabled: bool
    evidence_class: str = "DESIGN_SPEC"
    as_operated_status: str = "UNIDENTIFIED"
    region_source: str = "OCP_DC_V1_2011_Appendix_A"
    notes: str = ""
    extra: dict = field(default_factory=dict)


def classify_ocp_region(oa: MoistAirState) -> str:
    """Classify outdoor state into OCP Appendix A regions A–G (H is not weather-driven)."""
    tdb, tdp, twb, rh = oa.T_C, oa.T_dp_C, oa.T_wb_C, oa.rh
    tdb_fh = tdb - FAN_HEAT_C
    if tdp < T_DP_MIN and tdb <= T_DB_AB:
        return "A"
    if tdp < T_DP_MIN and tdb > T_DB_AB:
        return "B"
    if (tdb_fh > T_SA_MIN and tdp > T_DP_MIN and tdb_fh < T_SA_MAX and tdp < T_DP_MID and rh < RH_MAX):
        return "C"
    if tdb_fh > T_SA_MAX and tdp > T_DP_MIN and twb <= T_WB_DE:
        return "D"
    if tdb_fh > T_SA_MAX and tdp > T_DP_MIN and twb > T_WB_DE:
        return "E"
    if tdb_fh < T_SA_MAX and tdp > T_DP_MID and twb > T_WB_F:
        return "F"
    if (tdb_fh > T_SA_MIN and tdp < T_DP_MID and rh > RH_MAX) or (
        tdb_fh < T_SA_MIN and tdp > T_DP_MIN and tdp < T_DP_MID
    ):
        return "G"
    if tdp < T_DP_MIN:
        return "A" if tdb <= T_DB_AB else "B"
    if tdb_fh > T_SA_MAX:
        return "D" if twb <= T_WB_DE else "E"
    if rh >= RH_MAX:
        return "G"
    if tdp >= T_DP_MID:
        return "F"
    return "C"


def _return_state(oa: MoistAirState, t_return_c: float, w_return: float | None) -> MoistAirState:
    if w_return is None or not np.isfinite(w_return):
        w_return = humidity_ratio_from_dewpoint(T_DP_MIN, oa.P_Pa)
    return moist_air_state(float(t_return_c), float(w_return), oa.P_Pa)


def ocp_reference_controller(
    oa: MoistAirState,
    *,
    t_return_c: float,
    w_return: float | None = None,
    evap_effectiveness: float = 0.85,
    oa_inadmissible: bool = False,
) -> ControlState:
    """Return DESIGN_SPEC control actions. Does not use water outcomes."""
    ra = _return_state(oa, t_return_c, w_return)
    if oa_inadmissible:
        mixed = mix_moist_air(oa, ra, 0.0)
        w_tgt = max(mixed.w, humidity_ratio_from_dewpoint(T_DP_MIN, oa.P_Pa))
        return ControlState(
            control_mode="H_UNACCEPTABLE_OA_MIN_OA_RECIRC",
            oa_fraction=0.0,
            mixed_air_T_C=mixed.T_C,
            mixed_air_w=mixed.w,
            mixed_air_h=mixed.h_J_per_kg_da,
            T_supply_target_C=mixed.T_C,
            w_supply_target=w_tgt,
            humidification_required=w_tgt > mixed.w + 1e-9,
            evaporative_sensible_cooling_required=False,
            spray_enabled=True,
            notes="Condition H: smoke/dust. IEC not installed at Prineville. Not a normal weather mode.",
            extra={"heat_rejection_fallback": "IEC_CAPABILITY_NOT_INSTALLED"},
        )

    region = classify_ocp_region(oa)
    w_dp_min = humidity_ratio_from_dewpoint(T_DP_MIN, oa.P_Pa)
    w_dp_b = humidity_ratio_from_dewpoint(T_DP_B, oa.P_Pa)

    if region == "A":
        x, mixed = oa_fraction_for_target_temperature(oa, ra, T_SA_MIX)
        w_tgt = max(mixed.w, w_dp_min)
        return ControlState(
            control_mode="A_MIXED_AIR_HUMIDIFICATION",
            oa_fraction=x,
            mixed_air_T_C=mixed.T_C,
            mixed_air_w=mixed.w,
            mixed_air_h=mixed.h_J_per_kg_da,
            T_supply_target_C=max(mixed.T_C, T_SA_FLOOR),
            w_supply_target=w_tgt,
            humidification_required=w_tgt > mixed.w + 1e-12,
            evaporative_sensible_cooling_required=False,
            spray_enabled=w_tgt > mixed.w + 1e-12,
            notes="Mix OA/RA to 65 F SA; ECH humidifies to dewpoint minimum. Water may be >0 without sensible cooling.",
        )

    if region == "B":
        mixed = mix_moist_air(oa, ra, 1.0)
        t_sup = float(np.clip(mixed.T_C, T_SA_MIN, T_SA_MAX)) if mixed.T_C >= T_SA_MIN else mixed.T_C
        cool = mixed.T_C > T_SA_MAX + 1e-9
        if cool:
            t_full = mixed.T_C - evap_effectiveness * max(mixed.T_C - mixed.T_wb_C, 0.0)
            t_sup = T_SA_MAX if t_full <= T_SA_MAX else t_full
            w_cool = humidity_ratio_from_enthalpy_t(mixed.h_J_per_kg_da, t_sup)
            w_tgt = max(w_cool, w_dp_b)
        else:
            w_tgt = max(mixed.w, w_dp_b)
        return ControlState(
            control_mode="B_100PCT_OA_HUMIDIFICATION_OR_COOLING",
            oa_fraction=1.0,
            mixed_air_T_C=mixed.T_C,
            mixed_air_w=mixed.w,
            mixed_air_h=mixed.h_J_per_kg_da,
            T_supply_target_C=t_sup,
            w_supply_target=w_tgt,
            humidification_required=(not cool) and (w_tgt > mixed.w + 1e-12),
            evaporative_sensible_cooling_required=cool,
            spray_enabled=w_tgt > mixed.w + 1e-12,
            notes="100% OA. Humidify to ~43 F DP and/or evaporative-cool. SAT 65–80 F is a design band, not a heater.",
        )

    if region == "C":
        mixed = mix_moist_air(oa, ra, 1.0)
        return ControlState(
            control_mode="C_DRY_FREE_OUTSIDE_AIR",
            oa_fraction=1.0,
            mixed_air_T_C=mixed.T_C,
            mixed_air_w=mixed.w,
            mixed_air_h=mixed.h_J_per_kg_da,
            T_supply_target_C=mixed.T_C,
            w_supply_target=mixed.w,
            humidification_required=False,
            evaporative_sensible_cooling_required=False,
            spray_enabled=False,
            notes="100% OA; ECH off. Envelope already satisfied.",
        )

    if region in ("D", "E"):
        mixed = mix_moist_air(oa, ra, 1.0)
        t_full = mixed.T_C - evap_effectiveness * max(mixed.T_C - mixed.T_wb_C, 0.0)
        if t_full <= T_SA_MAX:
            t_sup = T_SA_MAX
        else:
            t_sup = t_full
        if t_sup >= mixed.T_C - 1e-9:
            w_tgt = mixed.w
            cool = False
        else:
            w_tgt = max(mixed.w, humidity_ratio_from_enthalpy_t(mixed.h_J_per_kg_da, t_sup))
            cool = True
        mode = "D_EVAPORATIVE_COOLING" if region == "D" else "E_EVAPORATIVE_COOLING_HIGH_WB"
        return ControlState(
            control_mode=mode,
            oa_fraction=1.0,
            mixed_air_T_C=mixed.T_C,
            mixed_air_w=mixed.w,
            mixed_air_h=mixed.h_J_per_kg_da,
            T_supply_target_C=t_sup,
            w_supply_target=w_tgt,
            humidification_required=False,
            evaporative_sensible_cooling_required=cool,
            spray_enabled=cool,
            notes=(
                "100% OA evaporative cooling toward 80 F SA. "
                "If wet-bulb is too high, sensible target is unreachable; do not add impossible extra water."
            ),
        )

    x, mixed = oa_fraction_for_rh_cap(oa, ra, RH_MAX, T_SA_MIN, T_SA_MAX)
    mode = "F_HIGH_HUMIDITY_MIX_SPRAY_BYPASS" if region == "F" else "G_RH_OR_TEMP_MIX_SPRAY_BYPASS"
    return ControlState(
        control_mode=mode,
        oa_fraction=x,
        mixed_air_T_C=mixed.T_C,
        mixed_air_w=mixed.w,
        mixed_air_h=mixed.h_J_per_kg_da,
        T_supply_target_C=float(np.clip(mixed.T_C, T_SA_MIN, T_SA_MAX)) if T_SA_MIN <= mixed.T_C <= T_SA_MAX else mixed.T_C,
        w_supply_target=mixed.w,
        humidification_required=False,
        evaporative_sensible_cooling_required=False,
        spray_enabled=False,
        notes="Mix OA/RA to cap RH at 65%. Direct evaporation bypassed. No conditioning water from ECH.",
    )
