"""Moist-air state and mixing (PHYSICS layer).

Mass/energy mixing is architecture-agnostic. Controllers choose the OA fraction;
this module does not fit x, ΔT, or effectiveness.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

try:
    import psychrolib

    psychrolib.SetUnitSystem(psychrolib.SI)
except Exception:  # pragma: no cover
    psychrolib = None

CP_DRY_AIR_J_KGK = 1006.0
H_FG_J_KG = 2_501_000.0
CP_VAPOR_J_KGK = 1860.0
WATER_DENSITY_KG_M3 = 1000.0


@dataclass(frozen=True)
class MoistAirState:
    T_C: float
    w: float
    h_J_per_kg_da: float
    rh: float
    T_dp_C: float
    T_wb_C: float
    P_Pa: float


def f_to_c(t_f: float) -> float:
    return (float(t_f) - 32.0) * 5.0 / 9.0


def c_to_f(t_c: float) -> float:
    return float(t_c) * 9.0 / 5.0 + 32.0


def _sat_vapor_pressure_pa(t_c: float) -> float:
    """Buck-style saturation vapor pressure over liquid water (matches gray-box fallback)."""
    if not np.isfinite(t_c):
        return np.nan
    return 611.21 * np.exp((18.678 - t_c / 234.5) * (t_c / (257.14 + t_c)))


def humidity_ratio_from_rh(t_c: float, rh_frac: float, p_pa: float) -> float:
    if not np.isfinite(t_c) or not np.isfinite(rh_frac) or not np.isfinite(p_pa):
        return np.nan
    rh = float(np.clip(rh_frac, 0.0, 1.0))
    if psychrolib is not None:
        return float(psychrolib.GetHumRatioFromRelHum(float(t_c), rh, float(p_pa)))
    pv = rh * _sat_vapor_pressure_pa(t_c)
    pv = min(float(pv), 0.99 * float(p_pa))
    return 0.621945 * pv / (float(p_pa) - pv)


def humidity_ratio_from_dewpoint(t_dp_c: float, p_pa: float) -> float:
    """Humidity ratio is fixed by dewpoint and pressure (saturated vapor pressure at T_dp)."""
    return humidity_ratio_from_rh(t_dp_c, 1.0, p_pa)


def enthalpy_j_per_kg_da(t_c: float, w: float) -> float:
    if psychrolib is not None:
        return float(psychrolib.GetMoistAirEnthalpy(float(t_c), float(w)))
    return CP_DRY_AIR_J_KGK * t_c + w * (H_FG_J_KG + CP_VAPOR_J_KGK * t_c)


def t_from_enthalpy_humidity(h_j_per_kg_da: float, w: float) -> float:
    if psychrolib is not None:
        return float(psychrolib.GetTDryBulbFromEnthalpyAndHumRatio(float(h_j_per_kg_da), float(w)))
    return (h_j_per_kg_da - H_FG_J_KG * w) / (CP_DRY_AIR_J_KGK + CP_VAPOR_J_KGK * w)


def humidity_ratio_from_enthalpy_t(h_j_per_kg_da: float, t_c: float) -> float:
    if psychrolib is not None:
        return float(psychrolib.GetHumRatioFromEnthalpyAndTDryBulb(float(h_j_per_kg_da), float(t_c)))
    return (h_j_per_kg_da - CP_DRY_AIR_J_KGK * t_c) / (H_FG_J_KG + CP_VAPOR_J_KGK * t_c)


def rel_hum_from_humidity_ratio(t_c: float, w: float, p_pa: float) -> float:
    if psychrolib is not None:
        rh = float(psychrolib.GetRelHumFromHumRatio(float(t_c), float(w), float(p_pa)))
        return rh
    w_sat = humidity_ratio_from_rh(t_c, 1.0, p_pa)
    if not np.isfinite(w_sat) or w_sat <= 0:
        return np.nan
    return float(np.clip(w / w_sat, 0.0, 1.5))


def dewpoint_from_rh(t_c: float, rh_frac: float) -> float:
    rh = float(np.clip(rh_frac, 1e-9, 1.0))
    if psychrolib is not None:
        return float(psychrolib.GetTDewPointFromRelHum(float(t_c), rh))
    pv = rh * _sat_vapor_pressure_pa(t_c)
    if pv <= 0:
        return np.nan
    ln = np.log(pv / 611.21)
    return (257.14 * ln) / (18.678 - ln)


def wetbulb_from_rh(t_c: float, rh_frac: float, p_pa: float) -> float:
    rh = float(np.clip(rh_frac, 0.0, 1.0))
    if psychrolib is not None:
        return float(psychrolib.GetTWetBulbFromRelHum(float(t_c), rh, float(p_pa)))
    w = humidity_ratio_from_rh(t_c, rh, p_pa)
    t_dp = dewpoint_from_rh(t_c, rh)
    return 0.5 * (t_c + t_dp) if np.isfinite(t_dp) else t_c * 0.7 + 0.3 * (w * 1000.0)


def moist_air_state(t_c: float, w: float, p_pa: float, t_wb_c: float | None = None) -> MoistAirState:
    h = enthalpy_j_per_kg_da(t_c, w)
    rh = rel_hum_from_humidity_ratio(t_c, w, p_pa)
    t_dp = dewpoint_from_rh(t_c, max(min(rh, 1.0), 1e-9)) if np.isfinite(rh) and rh > 0 else np.nan
    if t_wb_c is None or not np.isfinite(t_wb_c):
        t_wb_c = wetbulb_from_rh(t_c, max(min(rh, 1.0), 0.0), p_pa)
    return MoistAirState(
        T_C=float(t_c),
        w=float(w),
        h_J_per_kg_da=float(h),
        rh=float(rh),
        T_dp_C=float(t_dp),
        T_wb_C=float(t_wb_c),
        P_Pa=float(p_pa),
    )


def state_from_t_rh(t_c: float, rh_pct: float, p_pa: float, t_wb_c: float | None = None) -> MoistAirState:
    w = humidity_ratio_from_rh(t_c, float(rh_pct) / 100.0, p_pa)
    return moist_air_state(t_c, w, p_pa, t_wb_c=t_wb_c)


def mix_moist_air(oa: MoistAirState, ra: MoistAirState, x_oa: float) -> MoistAirState:
    """Full moist-air mixing on dry-air mass fraction x = OA / (OA+RA).

    w_m = x w_o + (1-x) w_r
    h_m = x h_o + (1-x) h_r
    T_m recovered from (h_m, w_m).
    """
    if not np.isfinite(x_oa):
        raise ValueError("OA fraction must be finite.")
    if x_oa < -1e-12 or x_oa > 1.0 + 1e-12:
        raise ValueError(f"OA fraction must be in [0, 1]; got {x_oa}.")
    x = float(np.clip(x_oa, 0.0, 1.0))
    if abs(oa.P_Pa - ra.P_Pa) > 50.0:
        raise ValueError("Mixing streams must share approximately the same pressure.")
    p = 0.5 * (oa.P_Pa + ra.P_Pa)
    w_m = x * oa.w + (1.0 - x) * ra.w
    h_m = x * oa.h_J_per_kg_da + (1.0 - x) * ra.h_J_per_kg_da
    t_m = t_from_enthalpy_humidity(h_m, w_m)
    return moist_air_state(t_m, w_m, p)


def oa_fraction_for_target_temperature(oa: MoistAirState, ra: MoistAirState, t_target_c: float) -> tuple[float, MoistAirState]:
    """Solve x in [0, 1] so mixed dry-bulb is as close as possible to t_target_c."""

    def t_of(x: float) -> float:
        return mix_moist_air(oa, ra, x).T_C

    t1 = t_of(1.0)
    t0 = t_of(0.0)
    t_lo, t_hi = (min(t0, t1), max(t0, t1))
    if t_target_c <= t_lo + 1e-9:
        x = 1.0 if t1 <= t0 else 0.0
        return x, mix_moist_air(oa, ra, x)
    if t_target_c >= t_hi - 1e-9:
        x = 0.0 if t0 >= t1 else 1.0
        return x, mix_moist_air(oa, ra, x)
    lo, hi = 0.0, 1.0
    oa_colder = t1 < t0
    for _ in range(48):
        mid = 0.5 * (lo + hi)
        tm = t_of(mid)
        if oa_colder:
            if tm < t_target_c:
                hi = mid
            else:
                lo = mid
        else:
            if tm < t_target_c:
                lo = mid
            else:
                hi = mid
    x = 0.5 * (lo + hi)
    return x, mix_moist_air(oa, ra, x)


def oa_fraction_for_rh_cap(
    oa: MoistAirState,
    ra: MoistAirState,
    rh_max: float,
    t_min_c: float,
    t_max_c: float,
) -> tuple[float, MoistAirState]:
    """Prefer maximum OA that keeps mixed RH <= rh_max when possible (DESIGN_SPEC mix)."""
    best_x = 0.0
    best = mix_moist_air(oa, ra, 0.0)
    found = False
    for i in range(51):
        x = 1.0 - i / 50.0
        m = mix_moist_air(oa, ra, x)
        if m.rh <= rh_max + 1e-6:
            best_x, best, found = x, m, True
            break
    if not found:
        return 0.0, mix_moist_air(oa, ra, 0.0)
    if best.T_C < t_min_c - 1e-6 or best.T_C > t_max_c + 1e-6:
        x2, mixed = oa_fraction_for_target_temperature(oa, ra, float(np.clip(best.T_C, t_min_c, t_max_c)))
        return x2, mixed
    return best_x, best


def assert_physically_valid_state(state: MoistAirState, *, rh_abs_max: float = 1.05) -> None:
    if not np.isfinite(state.T_C) or not np.isfinite(state.w) or not np.isfinite(state.h_J_per_kg_da):
        raise ValueError("Non-finite moist-air state.")
    if state.w < -1e-9:
        raise ValueError(f"Negative humidity ratio: {state.w}")
    if state.rh < -1e-6 or state.rh > rh_abs_max:
        raise ValueError(f"Physically impossible RH={state.rh}.")


def water_m3_h_from_delta_w(m_dry_air_kg_s: float, dw: float) -> float:
    return float(m_dry_air_kg_s) * float(max(dw, 0.0)) * 3600.0 / WATER_DENSITY_KG_M3
