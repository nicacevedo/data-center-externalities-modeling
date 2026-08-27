"""Follow-up v1 shared paths, 10-case Table 3 spec, and LHS helpers.

Does not modify first-run artifacts or nested upstream source.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

from common import (  # noqa: E402
    ARCHETYPE_PARAMS,
    PARENT_REPO,
    PY,
    UPSTREAM,
    UPSTREAM_COMMIT,
    WORK_ROOT,
    atomic_write_json,
    atomic_write_text,
    load_upstream,
    patch_cop_models,
    set_threads,
    sha256_file,
    utcnow,
    vector_for,
)

FOLLOWUP = WORK_ROOT / "results" / "followup_v1"
FOLLOWUP_DOCS = WORK_ROOT / "docs" / "followup_v1"
FOLLOWUP_LOGS = WORK_ROOT / "logs" / "followup_v1"
FOLLOWUP_MANIFESTS = WORK_ROOT / "manifests"
WEATHER_DIR = WORK_ROOT / "external" / "energyplus_tmy"
FIRST_RUN_STATUS = WORK_ROOT / "results" / "FIRST_RUN_STATUS.json"

# Paper Table 2 → public code. Cases 5&8 and 7&9 share a function; ranges differ.
PAPER_CASES = {
    1: {
        "size_class": "large-scale",
        "paper_cooling_configuration": "Airside economizer + adiabatic cooling + (water-cooled chiller)",
        "top_level_code_function": "PUE_WUE_AE_Chiller",
        "shared_function_with_other_case": None,
        "humidifier_type": "adiabatic",
        "economizer_type": "airside",
        "chiller_type": "water-cooled",
        "cooling_tower_present": True,
        "confidence": "high",
        "notes": "Code comment: Hyperscale DCs using adiabatic cooling.",
    },
    2: {
        "size_class": "large-scale",
        "paper_cooling_configuration": "Waterside economizer + (water-cooled chiller)",
        "top_level_code_function": "PUE_WUE_Chiller_Watereconomier",
        "shared_function_with_other_case": None,
        "humidifier_type": "adiabatic",
        "economizer_type": "waterside",
        "chiller_type": "water-cooled",
        "cooling_tower_present": True,
        "confidence": "high",
        "notes": "Code comment: Hyperscale DCs with cooling tower waterside economizer.",
    },
    3: {
        "size_class": "midsize",
        "paper_cooling_configuration": "Airside economizer + (water-cooled chiller)",
        "top_level_code_function": "PUE_WUE_AE_Chiller_Colo",
        "shared_function_with_other_case": None,
        "humidifier_type": "adiabatic",
        "economizer_type": "airside",
        "chiller_type": "water-cooled",
        "cooling_tower_present": True,
        "confidence": "high",
        "notes": "Code comment: Colo DCs with no adiabatic cooling (airside economizer helper has no adiabatic spray).",
    },
    4: {
        "size_class": "midsize",
        "paper_cooling_configuration": "Waterside economizer + (water-cooled chiller)",
        "top_level_code_function": "PUE_WUE_WE_Chiller_Colo",
        "shared_function_with_other_case": None,
        "humidifier_type": "adiabatic",
        "economizer_type": "waterside",
        "chiller_type": "water-cooled",
        "cooling_tower_present": True,
        "confidence": "high",
        "notes": "Code comment: Colo DCs with WE. demo.ipynb uses this function.",
    },
    5: {
        "size_class": "midsize",
        "paper_cooling_configuration": "Water-cooled chiller",
        "top_level_code_function": "PUE_WUE_Chiller",
        "shared_function_with_other_case": 8,
        "humidifier_type": "adiabatic",
        "economizer_type": "none",
        "chiller_type": "water-cooled",
        "cooling_tower_present": True,
        "confidence": "high",
        "notes": "Same top-level function as case 8; midsize vs small Table 3 ranges.",
    },
    6: {
        "size_class": "midsize",
        "paper_cooling_configuration": "Airside economizer + (air-cooled chiller)",
        "top_level_code_function": "PUE_WUE_AE_AIRChiller",
        "shared_function_with_other_case": None,
        "humidifier_type": "adiabatic",
        "economizer_type": "airside",
        "chiller_type": "air-cooled",
        "cooling_tower_present": False,
        "confidence": "high",
        "notes": None,
    },
    7: {
        "size_class": "midsize",
        "paper_cooling_configuration": "Air-cooled chiller",
        "top_level_code_function": "PUE_WUE_AIRChiller",
        "shared_function_with_other_case": 9,
        "humidifier_type": "adiabatic",
        "economizer_type": "none",
        "chiller_type": "air-cooled",
        "cooling_tower_present": False,
        "confidence": "high",
        "notes": "Same top-level function as case 9; midsize vs small Table 3 ranges.",
    },
    8: {
        "size_class": "small",
        "paper_cooling_configuration": "Water-cooled chiller",
        "top_level_code_function": "PUE_WUE_Chiller",
        "shared_function_with_other_case": 5,
        "humidifier_type": "isothermal_in_paper_table2_but_code_uses_humidification_pump",
        "economizer_type": "none",
        "chiller_type": "water-cooled",
        "cooling_tower_present": True,
        "confidence": "medium",
        "notes": (
            "Table 2 lists isothermal humidification; Table 3 still supplies humidification-pump "
            "pressure/efficiency for case 8. Public code PUE_WUE_Chiller uses Pump_Power(hd_amount), "
            "not DX-style Power_hd=Q_latent. Water Eq. (9) is humidifier-type invariant per the paper."
        ),
    },
    9: {
        "size_class": "small",
        "paper_cooling_configuration": "Air-cooled chiller",
        "top_level_code_function": "PUE_WUE_AIRChiller",
        "shared_function_with_other_case": 7,
        "humidifier_type": "isothermal_in_paper_table2_but_code_uses_humidification_pump",
        "economizer_type": "none",
        "chiller_type": "air-cooled",
        "cooling_tower_present": False,
        "confidence": "medium",
        "notes": "Same humidifier caveat as case 8. Function shared with case 7.",
    },
    10: {
        "size_class": "small",
        "paper_cooling_configuration": "Direct expansion system",
        "top_level_code_function": "PUE_WUE_DX",
        "shared_function_with_other_case": None,
        "humidifier_type": "isothermal",
        "economizer_type": "none",
        "chiller_type": "DX",
        "cooling_tower_present": False,
        "confidence": "high",
        "notes": "Power_hd = Q_heat_latent/1 is the isothermal-style energy term. Humidification pump is n/a in Table 3.",
    },
}

# UE.xlsx climate zones (authoritative 15-zone set vs preprint '16').
UE_CLIMATE_ZONES = [
    "1A",
    "2A",
    "2B",
    "3A",
    "3B",
    "3C",
    "4A",
    "4B",
    "4C",
    "5A",
    "5B",
    "6A",
    "6B",
    "7",
    "8",
]

# DOE-designated IECC representative cities (paper cites DOE 2020; Figure 2 labels not OCR-readable).
CLIMATE_CITIES = {
    "1A": {"city": "Miami", "state": "FL", "epw_id": "USA_FL_Miami.Intl.AP.722020_TMY3", "wmo": "722020"},
    "2A": {"city": "Houston", "state": "TX", "epw_id": "USA_TX_Houston-Bush.Intercontinental.AP.722430_TMY3", "wmo": "722430"},
    "2B": {"city": "Phoenix", "state": "AZ", "epw_id": "USA_AZ_Phoenix-Sky.Harbor.Intl.AP.722780_TMY3", "wmo": "722780"},
    "3A": {"city": "Atlanta", "state": "GA", "epw_id": "USA_GA_Atlanta-Hartsfield-Jackson.Intl.AP.722190_TMY3", "wmo": "722190"},
    "3B": {"city": "El_Paso", "state": "TX", "epw_id": "USA_TX_El.Paso.Intl.AP.722700_TMY3", "wmo": "722700"},
    "3C": {"city": "San_Francisco", "state": "CA", "epw_id": "USA_CA_San.Francisco.Intl.AP.724940_TMY3", "wmo": "724940"},
    "4A": {"city": "Baltimore", "state": "MD", "epw_id": "USA_MD_Baltimore-Washington.Intl.AP.724060_TMY3", "wmo": "724060"},
    "4B": {"city": "Albuquerque", "state": "NM", "epw_id": "USA_NM_Albuquerque.Intl.AP.723650_TMY3", "wmo": "723650"},
    "4C": {"city": "Seattle", "state": "WA", "epw_id": "USA_WA_Seattle-Tacoma.Intl.AP.727930_TMY3", "wmo": "727930"},
    "5A": {"city": "Chicago", "state": "IL", "epw_id": "USA_IL_Chicago-OHare.Intl.AP.725300_TMY3", "wmo": "725300"},
    "5B": {"city": "Denver", "state": "CO", "epw_id": "USA_CO_Denver-Aurora-Buckley.AFB.724695_TMY3", "wmo": "724695"},
    "6A": {"city": "Minneapolis", "state": "MN", "epw_id": "USA_MN_Minneapolis-St.Paul.Intl.AP.726580_TMY3", "wmo": "726580"},
    "6B": {"city": "Helena", "state": "MT", "epw_id": "USA_MT_Helena.Rgnl.AP.727720_TMY3", "wmo": "727720"},
    "7": {"city": "Duluth", "state": "MN", "epw_id": "USA_MN_Duluth.Intl.AP.727450_TMY3", "wmo": "727450"},
    "8": {"city": "Fairbanks", "state": "AK", "epw_id": "USA_AK_Fairbanks.Intl.AP.702610_TMY3", "wmo": "702610"},
}

# Selected cells chosen BEFORE comparing to UE.xlsx (coverage, not error-chasing).
SELECTED_CELLS = [
    {"paper_case": 1, "climate_zone": "1A", "why": "large-scale airside/adiabatic; hot-humid"},
    {"paper_case": 2, "climate_zone": "8", "why": "large-scale waterside/wet cooling; cold"},
    {"paper_case": 2, "climate_zone": "1A", "why": "same WE function in a hot-humid climate (economizer hours collapse)"},
    {"paper_case": 5, "climate_zone": "2A", "why": "water-cooled no economizer; hot-humid midsize"},
    {"paper_case": 7, "climate_zone": "8", "why": "air-cooled chiller; cold"},
    {"paper_case": 10, "climate_zone": "5A", "why": "DX; mixed climate; distinct function"},
]
SMOKE_CELL = SELECTED_CELLS[0]


def _r(lo, hi):
    return {"lo": lo, "hi": hi, "inactive": False}


def _na():
    return {"lo": None, "hi": None, "inactive": True}


def _pct_to_frac(lo, hi):
    return {"lo": lo / 100.0, "hi": hi / 100.0, "inactive": False, "paper_unit": "%", "code_unit": "fraction"}


def _kpa_to_pa(lo, hi):
    return {"lo": lo * 1000.0, "hi": hi * 1000.0, "inactive": False, "paper_unit": "kPa", "code_unit": "Pa"}


def table3_ranges(case: int) -> dict:
    """Paper Table 3 ranges transformed into code units. RH rows are physically swapped vs labels."""
    L, M, S = case in (1, 2), case in (3, 4, 5, 6, 7), case in (8, 9, 10)
    ct = case in (1, 2, 3, 4, 5, 8)
    we = case in (2, 4)
    air_chiller = case in (6, 7, 9)
    dx = case == 10
    out = {}
    if L:
        out["UPS_e"] = _pct_to_frac(90, 99)
        out["PD_lr"] = _pct_to_frac(0, 2)
        out["L_percentage"] = _pct_to_frac(0, 0.2)
        out["T_lw"] = _r(10, 18)
        out["T_up"] = _r(27, 35)
        out["dp_lw"] = _r(-12, -9)
        out["dp_up"] = _r(15, 27)
        out["SHR"] = _pct_to_frac(95, 99)
        out["delta_T_air"] = _r(13.9, 19.4)
        out["Fan_e_CRAC"] = _pct_to_frac(65, 90)
    elif M:
        out["UPS_e"] = _pct_to_frac(80, 94)
        out["PD_lr"] = _pct_to_frac(2, 5)
        out["L_percentage"] = _pct_to_frac(2, 5)
        out["T_lw"] = _r(15, 18)
        out["T_up"] = _r(27, 32)
        out["dp_lw"] = _r(-12, -9)
        out["dp_up"] = _r(15, 27)
        out["SHR"] = _pct_to_frac(95, 99)
        out["delta_T_air"] = _r(5, 10)
        out["Fan_e_CRAC"] = _pct_to_frac(60, 80)
    else:
        out["UPS_e"] = _pct_to_frac(77, 85)
        out["PD_lr"] = _pct_to_frac(2, 4)
        out["L_percentage"] = _pct_to_frac(2, 4)
        out["T_lw"] = _r(18, 22.5)
        out["T_up"] = _r(22.5, 27)
        out["dp_lw"] = _r(-9.9, -8.1)
        out["dp_up"] = _r(13.5, 16.5)
        out["SHR"] = _pct_to_frac(95, 99)
        out["delta_T_air"] = _r(5, 8)
        out["Fan_e_CRAC"] = _pct_to_frac(60, 75)

    # RH: paper row 'lower bound' has the HIGH RH numbers → code RH_up; 'higher bound' LOW → RH_lw.
    if case == 1:
        out["RH_up"] = _r(60, 95)
        out["RH_lw"] = _r(8, 20)
    elif case == 2:
        out["RH_up"] = _r(60, 90)
        out["RH_lw"] = _r(8, 20)
    elif M:
        out["RH_up"] = _r(60, 80)
        out["RH_lw"] = _r(10, 30)
    else:
        out["RH_up"] = _r(54, 66)
        out["RH_lw"] = _r(20, 30)

    fan_crac = {
        1: (300, 1000),
        2: (300, 700),
        3: (400, 1000),
        4: (400, 900),
        5: (400, 900),
        6: (400, 1000),
        7: (400, 900),
        8: (400, 900),
        9: (400, 900),
        10: (400, 600),
    }[case]
    out["Fan_Pressure_CRAC"] = _r(*fan_crac)

    if dx:
        out["delta_T_water"] = _na()
        out["Pump_Pressure_HD"] = _na()
        out["Pump_e_HD"] = _na()
        out["Pump_Pressure_CW"] = _na()
        out["Pump_e_CW"] = _na()
        out["HTE"] = _na()
        out["Chiller_load"] = _na()
    else:
        out["delta_T_water"] = _r(5, 10)
        out["Pump_Pressure_HD"] = _kpa_to_pa(6300, 7700)
        out["Pump_e_HD"] = _pct_to_frac(60, 80 if not S else 70)
        out["Pump_Pressure_CW"] = _kpa_to_pa(114.9, 172.4)
        out["Pump_e_CW"] = _pct_to_frac(60, 80 if not S else 70)
        if case == 1 or case == 3:
            out["HTE"] = _na()
        elif case == 2:
            out["HTE"] = _r(0.7, 0.9)
        elif S:
            out["HTE"] = _r(0.65, 0.8)
        else:
            out["HTE"] = _r(0.65, 0.9)
        if L:
            out["Chiller_load"] = _r(0.2, 0.8)
        else:
            out["Chiller_load"] = _r(0.1, 0.5)

    if ct:
        out["delta_T_CT"] = _r(4, 6)
        out["Fan_Pressure_CT"] = _r(100, 400) if L else _r(200, 400)
        out["Fan_e_CT"] = _pct_to_frac(65, 90) if L else _pct_to_frac(60, 80 if M else 75)
        out["Pump_Pressure_CT"] = _kpa_to_pa(166.9, 250.4)
        out["Pump_e_CT"] = _pct_to_frac(60, 80 if not S else 70)
        out["AT_CT"] = _r(2.8, 6.7)
        out["LGRatio"] = _r(0.2, 4) if L else _r(0.2, 2)
        out["Windage_p"] = _pct_to_frac(0.05, 0.5) if case == 8 else _pct_to_frac(0.005, 0.5)
        out["CC"] = _r(3, 15) if L else _r(3, 12)
    else:
        for k in (
            "delta_T_CT",
            "Fan_Pressure_CT",
            "Fan_e_CT",
            "Pump_Pressure_CT",
            "Pump_e_CT",
            "AT_CT",
            "LGRatio",
            "Windage_p",
            "CC",
        ):
            out[k] = _na()

    if we:
        out["Pump_Pressure_WE"] = _kpa_to_pa(114.9, 172.4)
        out["Pump_e_WE"] = _pct_to_frac(60, 80)
        out["AT_HE"] = _r(1.7, 2.8)
    else:
        out["Pump_Pressure_WE"] = _na()
        out["Pump_e_WE"] = _na()
        out["AT_HE"] = _na()

    pcop = {
        1: (-11, 11),
        2: (-11, 11),
        3: (-40, 0),
        4: (-40, 0),
        5: (-40, 0),
        6: (-40, -25),
        7: (-40, -25),
        8: (-60, -20),
        9: (-45, -30),
        10: (-45, 20),
    }[case]
    out["pcop"] = _pct_to_frac(*pcop)
    if case == 10:
        out["pcop"]["notes"] = "Preprint line break parsed as -45 to +20 percent; not -45 to -20."
    return out


def active_params_for_function(case: int) -> dict:
    fn = PAPER_CASES[case]["top_level_code_function"]
    names = ARCHETYPE_PARAMS[fn]
    ranges = table3_ranges(case)
    active = {}
    for n in names:
        if n in ("T_oa", "RH_oa", "P_oa"):
            continue
        spec = ranges.get(n)
        if spec is None:
            raise KeyError(f"case {case} missing Table 3 spec for required code input {n}")
        if spec["inactive"]:
            raise ValueError(f"case {case} required code input {n} is marked N/A in Table 3")
        active[n] = spec
    return active


def lhs_facility_samples(case: int, n: int, seed: int) -> list:
    """Uniform LHS over active facility parameters (not climate). Returns list of override dicts."""
    from scipy.stats.qmc import LatinHypercube, scale

    active = active_params_for_function(case)
    keys = list(active.keys())
    lows = np.array([active[k]["lo"] for k in keys], dtype=float)
    highs = np.array([active[k]["hi"] for k in keys], dtype=float)
    sampler = LatinHypercube(d=len(keys), seed=seed)
    u = sampler.random(n)
    x = scale(u, lows, highs)
    rows = []
    for i in range(n):
        rows.append({k: float(x[i, j]) for j, k in enumerate(keys)})
    return rows


def case_vector(case: int, climate: dict, facility: dict) -> list:
    """Build the upstream input vector with no silent demo-vector defaults."""
    fn = PAPER_CASES[case]["top_level_code_function"]
    names = ARCHETYPE_PARAMS[fn]
    vals = []
    missing = []
    for n in names:
        if n in climate:
            vals.append(float(climate[n]))
        elif n in facility:
            vals.append(float(facility[n]))
        else:
            missing.append(n)
    if missing:
        raise KeyError(f"case {case} missing required inputs (no silent defaults): {missing}")
    return vals


def cell_lhs_seed(paper_case: int, climate_zone: str, replicate: int = 0) -> int:
    z = UE_CLIMATE_ZONES.index(climate_zone)
    return 2025 + 1000 * paper_case + 10 * z + replicate


def internal_stream_seed(lhs_seed: int, sample_id: int, stream_offset: int = 0) -> int:
    return int(lhs_seed) * 100003 + int(sample_id) * 1009 + int(stream_offset)


def canonical_prineville_weather_path() -> Path:
    return PARENT_REPO / "Meta_Prineville_Oregon_v3" / "data" / "processed" / "weather_hourly.csv"


ENVIRONMENT_ID = "masanet_lei_py3.9.23_sklearn1.0.2"
CANONICAL_WATER_KEYS = [
    "humidification_or_adiabatic",
    "CT_evaporation",
    "CT_windage",
    "CT_draw_off",
]


def map_water_components(fn_name: str, water_comp) -> dict:
    """Map upstream Water_comp onto explicit conditioning-water names. Not source/groundwater."""
    from common import WATER_LABELS

    out = {k: 0.0 for k in CANONICAL_WATER_KEYS}
    labels = WATER_LABELS[fn_name]
    vals = list(water_comp or [])
    rename = {
        "humidification": "humidification_or_adiabatic",
        "CT_evaporation": "CT_evaporation",
        "CT_windage": "CT_windage",
        "CT_drainoff": "CT_draw_off",
    }
    for lab, val in zip(labels, vals):
        out[rename.get(lab, lab)] = float(val)
    return out
