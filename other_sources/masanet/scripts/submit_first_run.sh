#!/bin/bash
# Submit first-run DAG. Safe to disconnect after this script exits 0.
set -euo pipefail
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet"
REPO="/home/nacevedo/RA/data-center-externalities-modeling"
PY="/home/nacevedo/.conda/envs/masanet_lei/bin/python"
cd "${ROOT}"
mkdir -p logs manifests results docs results/figures

export PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
export PYTHONPATH="${ROOT}/scripts"

echo "=== provenance freeze at submit ==="
"${PY}" "${ROOT}/scripts/write_provenance.py"

echo "=== input presence ==="
test -f "${ROOT}/external/Data-Center-Water-footprint/simulation_funs_DC.py"
test -f "${ROOT}/external/frontier/Frontier HPC & Facility Data.xlsx"
test -x "${PY}"
touch "${ROOT}/logs/.write_test" && rm -f "${ROOT}/logs/.write_test"
touch "${ROOT}/results/.write_test" && rm -f "${ROOT}/results/.write_test"

echo "=== sinfo (cpu partitions) ==="
sinfo -s | grep -E 'PARTITION|sloan_batch|mit_normal|mit_quicktest' || sinfo -s | head -20

echo "=== squeue before submit ==="
squeue -u "${USER}" -o '%.18i %.12P %.22j %.8T %.10M %R' | head -20

submit_one () {
  local script="$1"
  shift
  sbatch --parsable "$@" "${script}"
}

REPRO="$(submit_one "${ROOT}/slurm/00_masanet_repro.sbatch")"
echo "REPRO ${REPRO}"
AUDIT="$(submit_one "${ROOT}/slurm/01_boundary_audit.sbatch" --depend="afterok:${REPRO}")"
echo "AUDIT ${AUDIT}"
GRID="$(submit_one "${ROOT}/slurm/02_masanet_grid.sbatch" --depend="afterok:${AUDIT}")"
echo "GRID ${GRID}"
FRONT="$(submit_one "${ROOT}/slurm/03_frontier_validate.sbatch")"
echo "FRONT ${FRONT}"
FINAL="$(submit_one "${ROOT}/slurm/04_finalize.sbatch" --depend="afterok:${GRID}:${FRONT}")"
echo "FINAL ${FINAL}"

NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
HEAD="$(git -C "${REPO}" rev-parse HEAD 2>/dev/null || echo UNKNOWN)"
"${PY}" - << PY
import json
from pathlib import Path
root = Path("${ROOT}")
jobs = {
    "created_utc": "${NOW}",
    "submit_host": __import__("socket").gethostname(),
    "git_head": "${HEAD}",
    "work_root": str(root),
    "python": "${PY}",
    "partition": "sched_mit_sloan_batch",
    "dependency_graph": {
        "MASANET_REPRO": "${REPRO}",
        "BOUNDARY_AUDIT": "${AUDIT}",
        "MASANET_GRID": "${GRID}",
        "FRONTIER": "${FRONT}",
        "FINALIZE": "${FINAL}",
        "edges": [
            "BOUNDARY_AUDIT afterok MASANET_REPRO",
            "MASANET_GRID afterok BOUNDARY_AUDIT",
            "FINALIZE afterok MASANET_GRID and FRONTIER",
            "FRONTIER independent after data freeze",
        ],
    },
    "job_ids": {
        "MASANET_REPRO": "${REPRO}",
        "BOUNDARY_AUDIT": "${AUDIT}",
        "MASANET_GRID": "${GRID}",
        "FRONTIER": "${FRONT}",
        "FINALIZE": "${FINAL}",
    },
    "independent_of_local_session": True,
    "notes": [
        "Jobs use absolute paths and conda env python binary; no notebook/tmux/SSH session required after sbatch.",
        "Inputs live under /home/nacevedo which is cluster shared storage.",
    ],
}
path = root / "manifests" / "SLURM_FIRST_RUN.json"
path.write_text(json.dumps(jobs, indent=2) + "\n")
print("WROTE", path)
PY

echo "=== squeue after submit ==="
squeue -u "${USER}" -o '%.18i %.12P %.22j %.8T %.10M %R' | head -30
echo "Submitted. Jobs do not depend on this shell."
echo "IDs: REPRO=${REPRO} AUDIT=${AUDIT} GRID=${GRID} FRONT=${FRONT} FINAL=${FINAL}"
