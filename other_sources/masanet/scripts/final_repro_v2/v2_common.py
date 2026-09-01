"""Final-repro v2 shared paths. Does not modify followup_v1 or upstream source."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

WORK_ROOT = Path("/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet")
PARENT = Path("/home/nacevedo/RA/data-center-externalities-modeling")
UPSTREAM = WORK_ROOT / "external" / "Data-Center-Water-footprint"
V1 = WORK_ROOT / "results" / "followup_v1"
MAN = WORK_ROOT / "manifests" / "final_repro_v2"
RES = WORK_ROOT / "results" / "final_repro_v2"
AN = RES / "analysis"
REPS = RES / "reps"
LOGS = WORK_ROOT / "logs" / "final_repro_v2"
DOCS = WORK_ROOT / "docs" / "final_repro_v2"
PY = Path("/home/nacevedo/.conda/envs/masanet_lei/bin/python")
PY_DC = Path("/home/nacevedo/.conda/envs/dc_externalities/bin/python")
UPSTREAM_COMMIT = "2cc53bee89b0a61bdad10c02b4d170d7f673e2dc"
ENV_ID = "masanet_lei_PYTHONNOUSERSITE_py3.9.23_sklearn1.0.2_scipy1.7.3"

LOCKED_CELLS = [
    {"paper_case": 1, "climate_zone": "1A"},
    {"paper_case": 2, "climate_zone": "8"},
    {"paper_case": 2, "climate_zone": "1A"},
    {"paper_case": 5, "climate_zone": "2A"},
    {"paper_case": 7, "climate_zone": "8"},
    {"paper_case": 10, "climate_zone": "5A"},
]


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str | None:
    if not Path(path).exists():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, default=str) + "\n")
    tmp.replace(path)


def set_threads():
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
    os.environ.setdefault("PYTHONNOUSERSITE", "1")
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
