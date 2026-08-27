"""Shared paths, canonical inputs, and upstream loader for the first masanet run."""
from __future__ import annotations

import json
import os
import sys
import hashlib
from pathlib import Path
from datetime import datetime, timezone

import numpy as np

WORK_ROOT = Path("/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet")
PARENT_REPO = Path("/home/nacevedo/RA/data-center-externalities-modeling")
UPSTREAM = WORK_ROOT / "external" / "Data-Center-Water-footprint"
FRONTIER_XLSX = WORK_ROOT / "external" / "frontier" / "Frontier HPC & Facility Data.xlsx"
LBNL_PDF = (
    WORK_ROOT
    / "external"
    / "lbnl_2024"
    / "lbnl-2024-united-states-data-center-energy-usage-report.pdf"
)
PY = Path("/home/nacevedo/.conda/envs/masanet_lei/bin/python")
CANONICAL_SEED = 2025
EXTRA_SEEDS = (2026, 7)
UPSTREAM_COMMIT = "2cc53bee89b0a61bdad10c02b4d170d7f673e2dc"

# Demo.ipynb vector for PUE_WUE_WE_Chiller_Colo (notebook output PUE=1.33916, WUE=2.41739; seed unset).
DEMO_VECTOR = [
    9,
    10,
    101325,
    8.94746094e-01,
    2.84082031e-02,
    4.72167969e-02,
    9.51835937e-01,
    9.49707031e00,
    6.50488281e02,
    6.13867188e-01,
    6.41894531e06,
    6.50976563e-01,
    6.90283203e-01,
    6.91894531e00,
    3.35986328e00,
    2.10712891e00,
    1.56284191e05,
    6.68945312e-01,
    1.71884552e05,
    7.45117188e-01,
    3.08984375e-01,
    5.09960938e00,
    2.46235102e05,
    7.08007812e-01,
    2.93588867e-03,
    1.11650391e01,
    2.72070313e-01,
    3.95898438e02,
    6.11914063e-01,
    2.87041016e01,
    1.54423828e01,
    1.67460938e01,
    -1.11123047e01,
    7.18554688e01,
    2.60351562e01,
    -9.17968750e-02,
]

WE_COLO_PARAM_NAMES = [
    "T_oa",
    "RH_oa",
    "P_oa",
    "UPS_e",
    "PD_lr",
    "L_percentage",
    "SHR",
    "delta_T_air",
    "Fan_Pressure_CRAC",
    "Fan_e_CRAC",
    "Pump_Pressure_HD",
    "Pump_e_HD",
    "HTE",
    "delta_T_water",
    "AT_CT",
    "AT_HE",
    "Pump_Pressure_WE",
    "Pump_e_WE",
    "Pump_Pressure_CW",
    "Pump_e_CW",
    "Chiller_load",
    "delta_T_CT",
    "Pump_Pressure_CT",
    "Pump_e_CT",
    "Windage_p",
    "CC",
    "LGRatio",
    "Fan_Pressure_CT",
    "Fan_e_CT",
    "T_up",
    "T_lw",
    "dp_up",
    "dp_lw",
    "RH_up",
    "RH_lw",
    "pcop",
]

CANONICAL_BY_NAME = dict(zip(WE_COLO_PARAM_NAMES, DEMO_VECTOR))

ARCHETYPE_PARAMS = {
    "PUE_WUE_AE_Chiller": [
        "T_oa",
        "RH_oa",
        "P_oa",
        "UPS_e",
        "PD_lr",
        "L_percentage",
        "delta_T_air",
        "Fan_Pressure_CRAC",
        "Fan_e_CRAC",
        "Pump_Pressure_HD",
        "Pump_e_HD",
        "AT_CT",
        "Chiller_load",
        "delta_T_water",
        "Pump_Pressure_CW",
        "Pump_e_CW",
        "delta_T_CT",
        "Pump_Pressure_CT",
        "Pump_e_CT",
        "Windage_p",
        "CC",
        "Fan_Pressure_CT",
        "Fan_e_CT",
        "SHR",
        "LGRatio",
        "T_up",
        "T_lw",
        "dp_up",
        "dp_lw",
        "RH_up",
        "RH_lw",
        "pcop",
    ],
    "PUE_WUE_Chiller_Watereconomier": list(WE_COLO_PARAM_NAMES),
    "PUE_WUE_AE_Chiller_Colo": [
        "T_oa",
        "RH_oa",
        "P_oa",
        "UPS_e",
        "PD_lr",
        "L_percentage",
        "delta_T_air",
        "Fan_Pressure_CRAC",
        "Fan_e_CRAC",
        "Pump_Pressure_HD",
        "Pump_e_HD",
        "AT_CT",
        "Chiller_load",
        "delta_T_water",
        "Pump_Pressure_CW",
        "Pump_e_CW",
        "delta_T_CT",
        "Pump_Pressure_CT",
        "Pump_e_CT",
        "Windage_p",
        "CC",
        "Fan_Pressure_CT",
        "Fan_e_CT",
        "SHR",
        "LGRatio",
        "T_up",
        "T_lw",
        "dp_up",
        "dp_lw",
        "RH_up",
        "RH_lw",
        "pcop",
    ],
    "PUE_WUE_WE_Chiller_Colo": list(WE_COLO_PARAM_NAMES),
    "PUE_WUE_Chiller": [
        "T_oa",
        "RH_oa",
        "P_oa",
        "UPS_e",
        "PD_lr",
        "L_percentage",
        "SHR",
        "delta_T_air",
        "Fan_Pressure_CRAC",
        "Fan_e_CRAC",
        "Pump_Pressure_HD",
        "Pump_e_HD",
        "HTE",
        "delta_T_water",
        "Pump_Pressure_CW",
        "Pump_e_CW",
        "AT_CT",
        "Chiller_load",
        "delta_T_CT",
        "Pump_Pressure_CT",
        "Pump_e_CT",
        "Windage_p",
        "CC",
        "Fan_Pressure_CT",
        "Fan_e_CT",
        "LGRatio",
        "T_up",
        "T_lw",
        "dp_up",
        "dp_lw",
        "RH_up",
        "RH_lw",
        "pcop",
    ],
    "PUE_WUE_DX": [
        "T_oa",
        "RH_oa",
        "P_oa",
        "UPS_e",
        "PD_lr",
        "L_percentage",
        "SHR",
        "delta_T_air",
        "Fan_Pressure_CRAC",
        "Fan_e_CRAC",
        "T_up",
        "T_lw",
        "dp_up",
        "dp_lw",
        "RH_up",
        "RH_lw",
        "pcop",
    ],
    "PUE_WUE_AIRChiller": [
        "T_oa",
        "RH_oa",
        "P_oa",
        "UPS_e",
        "PD_lr",
        "L_percentage",
        "SHR",
        "delta_T_air",
        "Fan_Pressure_CRAC",
        "Fan_e_CRAC",
        "Pump_Pressure_HD",
        "Pump_e_HD",
        "HTE",
        "delta_T_water",
        "Pump_Pressure_CW",
        "Pump_e_CW",
        "Chiller_load",
        "pcop",
        "T_up",
        "T_lw",
        "dp_up",
        "dp_lw",
        "RH_up",
        "RH_lw",
    ],
    "PUE_WUE_AE_AIRChiller": [
        "T_oa",
        "RH_oa",
        "P_oa",
        "UPS_e",
        "PD_lr",
        "L_percentage",
        "delta_T_air",
        "Fan_Pressure_CRAC",
        "Fan_e_CRAC",
        "SHR",
        "Pump_Pressure_HD",
        "Pump_e_HD",
        "HTE",
        "delta_T_water",
        "Pump_Pressure_CW",
        "Pump_e_CW",
        "pcop",
        "Chiller_load",
        "T_up",
        "T_lw",
        "dp_up",
        "dp_lw",
        "RH_up",
        "RH_lw",
    ],
}

ARCHETYPE_META = {
    "PUE_WUE_AE_Chiller": {
        "class": "hyperscale_AE_adiabatic_water_chiller",
        "has_ct": True,
        "cop": "COP_2",
        "stochastic_helpers": [],
    },
    "PUE_WUE_Chiller_Watereconomier": {
        "class": "hyperscale_WE_water_chiller",
        "has_ct": True,
        "cop": "COP_2",
        "stochastic_helpers": ["Chiller_system"],
    },
    "PUE_WUE_AE_Chiller_Colo": {
        "class": "colo_AE_water_chiller",
        "has_ct": True,
        "cop": "COP_2",
        "stochastic_helpers": ["Air_side_economizer_colo"],
    },
    "PUE_WUE_WE_Chiller_Colo": {
        "class": "colo_WE_water_chiller",
        "has_ct": True,
        "cop": "COP_2",
        "stochastic_helpers": ["Chiller_system"],
    },
    "PUE_WUE_Chiller": {
        "class": "colo_water_chiller",
        "has_ct": True,
        "cop": "COP_2",
        "stochastic_helpers": ["Chiller_system"],
    },
    "PUE_WUE_DX": {
        "class": "dx_air_cooled",
        "has_ct": False,
        "cop": "COP_DX",
        "stochastic_helpers": ["Chiller_system_DX"],
    },
    "PUE_WUE_AIRChiller": {
        "class": "air_cooled_chiller",
        "has_ct": False,
        "cop": "COP_AC",
        "stochastic_helpers": ["Chiller_system"],
    },
    "PUE_WUE_AE_AIRChiller": {
        "class": "AE_air_cooled_chiller",
        "has_ct": False,
        "cop": "COP_AC",
        "stochastic_helpers": [],
    },
}

POWER_LABELS = {
    "PUE_WUE_AE_Chiller": [
        "IT",
        "UPS_loss",
        "PD_loss",
        "lighting",
        "fan_CRAC",
        "pump_hd",
        "chiller",
        "pump_CW",
        "pump_CT",
        "fan_CT",
    ],
    "PUE_WUE_Chiller_Watereconomier": [
        "IT",
        "UPS_loss",
        "PD_loss",
        "lighting",
        "fan_CRAC",
        "pump_hd",
        "pump_WE",
        "chiller",
        "pump_CW",
        "pump_CT",
        "fan_CT",
    ],
    "PUE_WUE_AE_Chiller_Colo": [
        "IT",
        "UPS_loss",
        "PD_loss",
        "lighting",
        "fan_CRAC",
        "pump_hd",
        "chiller",
        "pump_CW",
        "pump_CT",
        "fan_CT",
    ],
    "PUE_WUE_WE_Chiller_Colo": [
        "IT",
        "UPS_loss",
        "PD_loss",
        "lighting",
        "fan_CRAC",
        "pump_hd",
        "pump_WE",
        "chiller",
        "pump_CW",
        "pump_CT",
        "fan_CT",
    ],
    "PUE_WUE_Chiller": [
        "IT",
        "UPS_loss",
        "PD_loss",
        "lighting",
        "fan_CRAC",
        "pump_hd",
        "chiller",
        "pump_CW",
        "pump_CT",
        "fan_CT",
    ],
    "PUE_WUE_DX": [
        "IT",
        "UPS_loss",
        "PD_loss",
        "lighting",
        "fan_CRAC",
        "hd_or_reheat",
        "compressor",
    ],
    "PUE_WUE_AIRChiller": [
        "IT",
        "UPS_loss",
        "PD_loss",
        "lighting",
        "fan_CRAC",
        "pump_hd",
        "chiller",
        "pump_CW",
    ],
    "PUE_WUE_AE_AIRChiller": [
        "IT",
        "UPS_loss",
        "PD_loss",
        "lighting",
        "fan_CRAC",
        "pump_hd",
        "chiller",
        "pump_CW",
    ],
}

WATER_LABELS = {
    "PUE_WUE_AE_Chiller": ["humidification", "CT_evaporation", "CT_windage", "CT_drainoff"],
    "PUE_WUE_Chiller_Watereconomier": [
        "humidification",
        "CT_evaporation",
        "CT_windage",
        "CT_drainoff",
    ],
    "PUE_WUE_AE_Chiller_Colo": ["humidification", "CT_evaporation", "CT_windage", "CT_drainoff"],
    "PUE_WUE_WE_Chiller_Colo": ["humidification", "CT_evaporation", "CT_windage", "CT_drainoff"],
    "PUE_WUE_Chiller": ["humidification", "CT_evaporation", "CT_windage", "CT_drainoff"],
    "PUE_WUE_DX": ["humidification"],
    "PUE_WUE_AIRChiller": ["humidification"],
    "PUE_WUE_AE_AIRChiller": ["humidification"],
}


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def atomic_write_json(path: Path, obj) -> None:
    atomic_write_text(path, json.dumps(obj, indent=2, default=str) + "\n")


def ensure_sys_path() -> None:
    s = str(WORK_ROOT / "scripts")
    if s not in sys.path:
        sys.path.insert(0, s)


def patch_cop_models(mod) -> list:
    """sklearn 1.0.2 load shim for COP_AC.pkl trained on 0.22.2 (missing _y_train_std)."""
    notes = []
    for name in ("COP_gp", "COP_DX_gp", "COP_air_gp"):
        model = getattr(mod, name, None)
        if model is None:
            continue
        if not hasattr(model, "_y_train_std"):
            mean = np.asarray(getattr(model, "_y_train_mean", 0.0), dtype=float)
            model._y_train_std = np.ones_like(mean, dtype=float)
            notes.append(f"{name}: set _y_train_std=1 because normalize_y is False / attr missing")
    return notes


def load_upstream():
    """Import nested upstream module without copying it into our implementation."""
    prev = os.getcwd()
    os.chdir(UPSTREAM)
    if str(UPSTREAM) not in sys.path:
        sys.path.insert(0, str(UPSTREAM))
    import simulation_funs_DC as mod

    os.chdir(prev)
    notes = patch_cop_models(mod)
    return mod, notes


def vector_for(archetype: str, climate=None, overrides=None) -> list:
    names = ARCHETYPE_PARAMS[archetype]
    vals = []
    for n in names:
        if climate and n in climate:
            vals.append(climate[n])
        elif overrides and n in overrides:
            vals.append(overrides[n])
        else:
            vals.append(CANONICAL_BY_NAME[n])
    return vals


def set_threads() -> None:
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
    os.environ.setdefault("PYTHONNOUSERSITE", "1")
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
