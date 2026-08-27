#!/usr/bin/env python3
"""Phase 0: freeze second-run state. Does not overwrite first-run JSON/CSV/Parquet/figures."""
from __future__ import annotations

import platform
import socket
import subprocess
import sys
from pathlib import Path

from common import PARENT_REPO, PY, UPSTREAM, UPSTREAM_COMMIT, WORK_ROOT, atomic_write_json, set_threads, sha256_file, utcnow
from followup_common import FIRST_RUN_STATUS, FOLLOWUP, FOLLOWUP_DOCS, FOLLOWUP_LOGS


def _run(cmd, cwd=None):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return (p.stdout or "").strip(), p.returncode


def _pkg():
    out = {}
    for name in ("numpy", "pandas", "sklearn", "scipy", "CoolProp", "openpyxl", "pyarrow", "matplotlib", "pytest", "pypdf"):
        try:
            m = __import__(name)
            out[name] = getattr(m, "__version__", "imported")
        except Exception as e:
            out[name] = f"MISSING {e}"
    return out


def main():
    set_threads()
    FOLLOWUP.mkdir(parents=True, exist_ok=True)
    FOLLOWUP_DOCS.mkdir(parents=True, exist_ok=True)
    FOLLOWUP_LOGS.mkdir(parents=True, exist_ok=True)
    head, _ = _run(["git", "rev-parse", "HEAD"], cwd=str(PARENT_REPO))
    branch, _ = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(PARENT_REPO))
    status, _ = _run(["git", "status", "--short"], cwd=str(PARENT_REPO))
    up, _ = _run(["git", "rev-parse", "HEAD"], cwd=str(UPSTREAM))
    first_run_immutable = [
        WORK_ROOT / "results" / "FIRST_RUN_STATUS.json",
        WORK_ROOT / "results" / "masanet_reproduction_summary.json",
        WORK_ROOT / "results" / "masanet_boundary_audit.json",
        WORK_ROOT / "results" / "masanet_grid.parquet",
        WORK_ROOT / "results" / "masanet_grid.csv",
        WORK_ROOT / "results" / "masanet_grid_summary.json",
        WORK_ROOT / "results" / "frontier_qc.json",
        WORK_ROOT / "results" / "frontier_validation.json",
        WORK_ROOT / "docs" / "FIRST_RUN_SUMMARY.md",
        WORK_ROOT / "docs" / "WATER_BOUNDARY_AUDIT.csv",
    ]
    hashes = {}
    for p in [
        UPSTREAM / "simulation_funs_DC.py",
        UPSTREAM / "Simulation Results" / "UE.xlsx",
        WORK_ROOT / "external" / "frontier" / "Frontier HPC & Facility Data.xlsx",
        UPSTREAM / "COP_AC.pkl",
        UPSTREAM / "COP_2.pkl",
        UPSTREAM / "COP_DX.pkl",
        WORK_ROOT / "external" / "lei_masanet_2022" / "Climate-_and_Technology-Specific_PUE_and_WUE_Predi.pdf",
    ]:
        hashes[str(p)] = {"sha256": sha256_file(p), "bytes": p.stat().st_size} if p.exists() else None
    freeze = {
        "timestamp_utc": utcnow(),
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "parent_repository": str(PARENT_REPO),
        "work_root": str(WORK_ROOT),
        "git_rev_parse_HEAD": head,
        "git_branch": branch,
        "git_status_short": status,
        "upstream_commit_recorded": UPSTREAM_COMMIT,
        "upstream_commit_git": up,
        "python": {
            "executable": sys.executable,
            "expected": str(PY),
            "version": sys.version.split()[0],
            "packages": _pkg(),
        },
        "sklearn_compat_intervention": {
            "affected_model": "COP_AC.pkl",
            "missing_sklearn_attribute": "_y_train_std",
            "reason_shim_sets_to_1": "normalize_y is False on the unpickled GPR; sklearn 1.0.2 predict expects _y_train_std. Identity scale is correct when labels were not normalized.",
            "pickle_mutated_on_disk": False,
            "environment_sklearn": "1.0.2",
            "will_not_revisit_0.23_unless_annual_COP_discrepancy": True,
        },
        "first_run_status_path": str(FIRST_RUN_STATUS),
        "first_run_immutable_artifacts": [
            {"path": str(p), "exists": p.exists(), "sha256": sha256_file(p) if p.exists() else None}
            for p in first_run_immutable
        ],
        "source_hashes": hashes,
        "did_not_read_meta_2023_2024_water": True,
        "outputs_root": str(FOLLOWUP),
        "will_not_overwrite_first_run": True,
    }
    atomic_write_json(WORK_ROOT / "manifests" / "FOLLOWUP_V1_FREEZE.json", freeze)
    print("WROTE", WORK_ROOT / "manifests" / "FOLLOWUP_V1_FREEZE.json")


if __name__ == "__main__":
    main()
