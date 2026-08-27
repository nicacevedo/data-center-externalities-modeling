"""Shared paths, Zenodo provenance, conversions, and status for the 2021 M100 pipeline."""

from __future__ import annotations

import json
import os
import re
from calendar import monthrange
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
POOL_M100 = Path("/orcd/pool/005/nacevedo/m100")
SCRATCH_M100 = Path("/orcd/scratch/orcd/008/nacevedo/m100")
ARCHIVES_DIR = POOL_M100 / "raw_staging"
PROCESSED_DIR = POOL_M100 / "processed"
CATALOG_DIR = ROOT / "data" / "catalog"
RESULTS_DIR = ROOT / "results" / "suitability_2021"
STATUS_DIR = ROOT / "results" / "2021_status"
LOG_DIR = ROOT / "logs" / "slurm"
MANIFEST_DIR = ROOT / "manifests"
MODELS_DIR = ROOT / "results" / "models_2021"

SCHEMA_VERSION = "hourly-v2-2021.2"
EXPECTED_MONTHS = [f"2021-{m:02d}" for m in range(1, 13)]
STALE_SECONDS = 20 * 60
MAX_GAP_POWER_S = 180.0
MAX_GAP_STATE_S = 180.0
MAX_GAP_IPMI_S = 90.0
NOMINAL_IPMI_PER_HOUR = 180
NOMINAL_VERTIV_PER_HOUR = 360
CINECA_ELEVATION_M = 61.0

ZENODO = {
    "2021-01": {"record": "7589131", "doi": "10.5281/zenodo.7589131", "size": 6776657920, "md5": "23010c76b0fa8a88b980afe0e53da323"},
    "2021-02": {"record": "7589131", "doi": "10.5281/zenodo.7589131", "size": 6414028800, "md5": "10eed30aa685300d811a42d8feb504b6"},
    "2021-03": {"record": "7589131", "doi": "10.5281/zenodo.7589131", "size": 601907200, "md5": "3ce2cf1131024aeb22caf9cd87bdacb4"},
    "2021-04": {"record": "7589131", "doi": "10.5281/zenodo.7589131", "size": 6922403840, "md5": "5890f5c75368da66302b61be12d6aedc"},
    "2021-05": {"record": "7589131", "doi": "10.5281/zenodo.7589131", "size": 9944637440, "md5": "eed96a2d5b26e3d6f87c603d8104e6fd"},
    "2021-06": {"record": "7589131", "doi": "10.5281/zenodo.7589131", "size": 14624307200, "md5": "1dc58f8cd27c80c54886d742bc82e3d9"},
    "2021-07": {"record": "7589320", "doi": "10.5281/zenodo.7589320", "size": 16085637120, "md5": "c3fd741fceaa58210b2cedcc5d941acb"},
    "2021-08": {"record": "7589320", "doi": "10.5281/zenodo.7589320", "size": 15761971200, "md5": "a298f688670e31b1fc925cd8841beeff"},
    "2021-09": {"record": "7589320", "doi": "10.5281/zenodo.7589320", "size": 9895690240, "md5": "206647f98427a9f4e8139ccd954c5282"},
    "2021-10": {"record": "7589630", "doi": "10.5281/zenodo.7589630", "size": 14755194880, "md5": "c8a5fc0ea2dbc6f1b531ddd3b909d2b7"},
    "2021-11": {"record": "7589630", "doi": "10.5281/zenodo.7589630", "size": 14490163200, "md5": "5d086f756a6dd12b81ee7f50006fcfc9"},
    "2021-12": {"record": "7589630", "doi": "10.5281/zenodo.7589630", "size": 15612385280, "md5": "c0bea042254d228f1c878261671ad3ea"},
}

SCHNEIDER_SCALE_X10_C = (
    "Temp_mandata", "Temp_ritorno", "T_mandata_hmi", "T_ritorno_hmi",
    "Delta_temp", "Set_temperatura", "Max_t_mandata", "Max_t_ritorno",
    "Min_t_mandata",
)
SCHNEIDER_SCALE_X10_M3H = (
    "Portata_attiva", "Portata_1_hmi", "Portata_2_hmi", "Max_portata", "Min_portata",
)
SCHNEIDER_SCALE_X50_M3H = ("Portata_1", "Portata_2")
SCHNEIDER_SCALE_X100_PCT = ("Pos_valvola1", "Pos_valvola_2", "Rif_inverter")

LOGICS_POWER_KW = ("Tot", "Tot_ict", "Tot_cdz", "Tot_chiller", "Tot_qpompe", "Tot_servizi")
LOGICS_PUE = ("Pue", "pue", "Dcie")
LOGICS_WATTS = ("pt", "pit")
LOGICS_ENERGY = ("Energia", "Mwh")
LOGICS_QC = ("Bad_values", "Comlost", "Status", "Stato")
LOGICS_STATE = LOGICS_QC

VERTIV_CONTINUOUS = (
    "Return_Air_Temperature", "Supply_Air_Temperature", "Fan_Speed",
    "Compressor_Utilization", "Free_Cooling_Valve_Open_Position",
    "Free_Cooling_Fluid_Temperature", "Return_Humidity",
    "Actual_Return_Air_Temperature_Set_Point", "Supply_Air_Temperature_Set_Point",
)
VERTIV_STATE = ("Free_Cooling_Status",)
WEATHER_METRICS = ("temp", "humidity", "dew_point", "pressure")
CRITICAL_QUANTILES = {
    "Tot", "Tot_ict", "Tot_cdz", "Tot_chiller", "Tot_qpompe", "Tot_servizi",
    "pt", "pit", "temp", "Return_Air_Temperature", "Supply_Air_Temperature",
    "Temp_mandata", "Temp_ritorno", "Portata_attiva", "total_power",
}

SCHNEIDER_STATE = {
    "Start_impianto", "P101_in_marcia", "P102_in_marcia", "P103_in_marcia",
    "P104_in_marcia", "Allarme_on", "Allarme_presente",
}
SCHNEIDER_CONTINUOUS = {
    "Temp_mandata", "Temp_ritorno", "T_mandata_hmi", "T_ritorno_hmi",
    "Delta_temp", "Portata_attiva", "Portata_1", "Portata_2",
    "Portata_1_hmi", "Portata_2_hmi", "Out_pid_pompe", "Set_temperatura",
    "Pos_valvola1", "Pos_valvola_2",
}

WATER_NAME_RE = re.compile(
    r"(?:makeup|make_up|refill|withdrawal|consum|blowdown|evaporat|"
    r"discharge|tank.?level|water.?meter|acqua|riempimento|reintegro)",
    re.I,
)

PREFERRED_LOGICS = {
    "Tot": ("generals", "pue"),
    "Tot_ict": ("generals", "pue"),
    "Tot_cdz": ("generals", "pue"),
    "Tot_chiller": ("generals", "pue"),
    "Tot_qpompe": ("generals", "pue"),
    "Tot_servizi": ("generals", "pue"),
    "Pue": ("generals", "pue"),
    "Dcie": ("generals", "pue"),
    "pue": ("generals", "pue_sala_m"),
}


def hive_ym(month: str) -> str:
    y, m = month.split("-")
    return f"{int(y) % 100:02d}-{int(m):02d}"


def archive_path(month: str) -> Path:
    return ARCHIVES_DIR / f"{hive_ym(month)}.tar"


def zenodo_url(month: str) -> str:
    meta = ZENODO[month]
    return f"https://zenodo.org/api/records/{meta['record']}/files/{hive_ym(month)}.tar/content"


def grain_dir(grain: str, month: str) -> Path:
    return PROCESSED_DIR / "hourly" / grain / month


def grain_parquet(grain: str, month: str) -> Path:
    return grain_dir(grain, month) / f"m100_{grain}_hourly.parquet"


def month_bounds(month: str):
    y, m = map(int, month.split("-"))
    start = pd.Timestamp(year=y, month=m, day=1, tz="UTC")
    last = monthrange(y, m)[1]
    end = pd.Timestamp(year=y, month=m, day=last, tz="UTC") + pd.Timedelta(days=1)
    return start, end


def month_calendar(month: str) -> pd.DatetimeIndex:
    start, end = month_bounds(month)
    return pd.date_range(start, end, freq="h", inclusive="left", tz="UTC")


def n_threads() -> int:
    for key in ("SLURM_CPUS_PER_TASK", "SLURM_CPUS_ON_NODE"):
        val = os.environ.get(key)
        if val:
            try:
                return max(1, int(str(val).split("(")[0]))
            except ValueError:
                continue
    return max(1, min(8, os.cpu_count() or 4))


def tmp_root() -> Path:
    env = os.environ.get("TMPDIR") or os.environ.get("SLURM_TMPDIR")
    if env:
        p = Path(env)
    else:
        p = SCRATCH_M100 / "tmp" / str(os.getpid())
    p.mkdir(parents=True, exist_ok=True)
    return p


def status_path(month: str) -> Path:
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    return STATUS_DIR / f"{month}.json"


def load_status(month: str) -> dict:
    path = status_path(month)
    if path.exists():
        return json.loads(path.read_text())
    return {
        "month": month,
        "archive_status": "missing",
        "inventory_status": "pending",
        "facility_extraction_status": "pending",
        "node_extraction_status": "pending",
        "qc_status": "pending",
        "certification": None,
        "schema_version": None,
        "processed_products": [],
        "qc_result": None,
        "job_id": os.environ.get("SLURM_JOB_ID"),
        "runtime_s": None,
        "max_rss_kb": None,
        "timings": {},
        "failure": None,
        "updated_utc": None,
        "raw_deletion_allowed": False,
    }


def save_status(month: str, **updates) -> dict:
    st = load_status(month)
    st.update({k: v for k, v in updates.items() if v is not None or k in updates})
    st["updated_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    st["job_id"] = os.environ.get("SLURM_JOB_ID", st.get("job_id"))
    status_path(month).write_text(json.dumps(st, indent=2, default=str) + "\n")
    return st


def schneider_suffix(metric: str) -> str:
    return metric.rsplit(".", 1)[-1] if "." in metric else metric


def schneider_physical(metric: str, value):
    suf = schneider_suffix(metric)
    if suf in SCHNEIDER_SCALE_X10_C:
        return value / 10.0, "C", 10.0
    if suf in SCHNEIDER_SCALE_X10_M3H:
        return value / 10.0, "m3/h", 10.0
    if suf in SCHNEIDER_SCALE_X50_M3H:
        return value / 50.0, "m3/h", 50.0
    if suf in SCHNEIDER_SCALE_X100_PCT:
        return value / 100.0, "pct", 100.0
    return value, "raw", 1.0


def sea_level_to_station_pa(p_sl_hpa, temp_c, elev_m=CINECA_ELEVATION_M):
    import math
    t_k = float(temp_c) + 273.15
    p_sl_pa = float(p_sl_hpa) * 100.0
    return p_sl_pa * math.exp(-0.0289644 * 9.80665 * float(elev_m) / (8.314462618 * t_k))


def plugin_from_member(name: str):
    m = re.search(r"plugin=([^/]+)", name)
    return m.group(1) if m else None


def metric_from_member(name: str):
    m = re.search(r"metric=([^/]+)", name)
    return m.group(1) if m else None


def git_commit() -> str | None:
    head = ROOT.parents[1] / ".git" / "HEAD"
    try:
        import subprocess
        out = subprocess.run(
            ["git", "-C", str(ROOT.parents[1]), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None
