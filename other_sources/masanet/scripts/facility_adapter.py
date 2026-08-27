"""Project adapter: intensity model with explicit conditioning-water components.

Does not modify upstream Lei–Masanet physics. Does not interpret water as
groundwater, municipal source, consumption-only, or source pumping.

Chiller_load remains an exogenous facility/scenario parameter, not a function of P_IT.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from common import POWER_LABELS
from followup_common import (
    CANONICAL_WATER_KEYS,
    PAPER_CASES,
    case_vector,
    map_water_components,
)

# Intensity evaluation is at Power_IT = 1 in the upstream functions.


def paper_mean_intensity(hourly: np.ndarray) -> float:
    """Paper annual aggregation: unweighted mean of hourly intensities (equal Δt, P_IT=1)."""
    x = np.asarray(hourly, dtype=float)
    return float(np.mean(x))


def energy_weighted_annual(hourly_intensity: np.ndarray, p_it: np.ndarray, dt=None) -> float:
    """Project aggregation: sum(P_fac Δt)/sum(P_IT Δt) = sum(intensity * P_IT * Δt)/sum(P_IT * Δt)."""
    i = np.asarray(hourly_intensity, dtype=float)
    p = np.asarray(p_it, dtype=float)
    if dt is None:
        w = p
    else:
        w = p * np.asarray(dt, dtype=float)
    den = float(np.sum(w))
    if den <= 0:
        raise ValueError("total IT energy must be positive")
    return float(np.sum(i * w) / den)


@dataclass
class HourResult:
    P_IT_kW: float
    P_fac_kW: float
    P_nonIT_kW: float
    PUE: float
    WUE_L_per_kWh: float
    W_conditioning_kg_s: float
    W_components_kg_s: dict
    P_components_kW: dict
    AE_use: float | None
    WE_use: float | None
    HD_use: float | None
    chiller_load_is_scenario_parameter: bool = True


class FacilityIntensityAdapter:
    def __init__(self, inst, paper_case: int):
        self.inst = inst
        self.paper_case = int(paper_case)
        self.fn_name = PAPER_CASES[paper_case]["top_level_code_function"]
        self.fn = getattr(inst, self.fn_name)
        if getattr(inst, "_POWER_IT", 1.0) != 1.0:
            raise ValueError("adapter expects upstream intensity evaluation at Power_IT=1")

    def evaluate_hour(self, weather: dict, theta: dict, P_IT_kW: float, rng_seed: int | None = None) -> HourResult:
        if rng_seed is not None:
            np.random.seed(int(rng_seed))
        x = case_vector(self.paper_case, weather, theta)
        pue, wue = self.fn(x)
        rec = dict(self.inst._LAST)
        p_it = float(P_IT_kW)
        pue = float(pue)
        wue = float(wue)
        p_fac = p_it * pue
        wmap_unit = map_water_components(self.fn_name, rec.get("Water_comp") or [])
        w_comp = {k: p_it * float(v) for k, v in wmap_unit.items()}
        w_cond = float(sum(w_comp.values()))
        plabels = POWER_LABELS[self.fn_name]
        pc = rec.get("Power_comp") or []
        # Upstream power components are at Power_IT=1; scale absolute kW with P_IT.
        p_comp = {}
        for lab, val in zip(plabels, pc):
            p_comp[lab] = p_it * float(val)
        return HourResult(
            P_IT_kW=p_it,
            P_fac_kW=p_fac,
            P_nonIT_kW=p_fac - p_it,
            PUE=pue,
            WUE_L_per_kWh=wue,
            W_conditioning_kg_s=w_cond,
            W_components_kg_s=w_comp,
            P_components_kW=p_comp,
            AE_use=None if rec.get("AE_use") is None else float(rec["AE_use"]),
            WE_use=None if rec.get("WE_use") is None else float(rec["WE_use"]),
            HD_use=None if rec.get("HD_use") is None else float(rec["HD_use"]),
        )


FORBIDDEN_NAME_FRAGMENTS = (
    "groundwater",
    "gw_",
    "municipal",
    "source_pump",
    "withdrawal",
    "wellhead",
)
