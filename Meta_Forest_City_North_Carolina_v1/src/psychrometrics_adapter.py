"""Site-independent moist-air primitives.

These functions are imported from the frozen Prineville psychrometrics module
because the equations (mixing, enthalpy, saturation) are architecture-agnostic.
This adapter does NOT import Prineville controllers, OCP A–H regions, or
12 K airflow priors.

Equation-level equivalence is asserted in tests/test_psychrometrics_equivalence.py.
"""
from __future__ import annotations

import sys

from paths import PRINEVILLE_SRC

if str(PRINEVILLE_SRC) not in sys.path:
    sys.path.insert(0, str(PRINEVILLE_SRC))

from prineville_psychrometrics import (  # noqa: E402
    CP_DRY_AIR_J_KGK,
    H_FG_J_KG,
    WATER_DENSITY_KG_M3,
    MoistAirState,
    assert_physically_valid_state,
    c_to_f,
    dewpoint_from_rh,
    enthalpy_j_per_kg_da,
    f_to_c,
    humidity_ratio_from_dewpoint,
    humidity_ratio_from_enthalpy_t,
    humidity_ratio_from_rh,
    humidity_ratio_saturation,
    mix_moist_air,
    moist_air_state,
    oa_fraction_for_rh_cap,
    oa_fraction_for_target_temperature,
    rel_hum_from_humidity_ratio,
    state_from_t_rh,
    state_on_constant_enthalpy,
    t_from_enthalpy_humidity,
    water_m3_h_from_delta_w,
    wetbulb_from_rh,
)

__all__ = [
    "CP_DRY_AIR_J_KGK",
    "H_FG_J_KG",
    "WATER_DENSITY_KG_M3",
    "MoistAirState",
    "assert_physically_valid_state",
    "c_to_f",
    "dewpoint_from_rh",
    "enthalpy_j_per_kg_da",
    "f_to_c",
    "humidity_ratio_from_dewpoint",
    "humidity_ratio_from_enthalpy_t",
    "humidity_ratio_from_rh",
    "humidity_ratio_saturation",
    "mix_moist_air",
    "moist_air_state",
    "oa_fraction_for_rh_cap",
    "oa_fraction_for_target_temperature",
    "rel_hum_from_humidity_ratio",
    "state_from_t_rh",
    "state_on_constant_enthalpy",
    "t_from_enthalpy_humidity",
    "water_m3_h_from_delta_w",
    "wetbulb_from_rh",
]


def dry_air_mass_flow_from_sensible_heat_kg_s(p_it_w: float, delta_t_k: float, cp: float = CP_DRY_AIR_J_KGK) -> float:
    """Generic m_dot = Q / (cp ΔT). ΔT boundary must be tagged by the caller."""
    if delta_t_k <= 0:
        raise ValueError("ΔT must be positive.")
    return float(p_it_w) / (float(cp) * float(delta_t_k))
