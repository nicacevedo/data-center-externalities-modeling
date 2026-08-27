#!/bin/bash
# Submit follow-up v1 DAG. Safe to disconnect after this script exits 0.
set -euo pipefail
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet"
REPO="/home/nacevedo/RA/data-center-externalities-modeling"
PY="/home/nacevedo/.conda/envs/masanet_lei/bin/python"
cd "${ROOT}"
mkdir -p logs/followup_v1 results/followup_v1 docs/followup_v1 manifests external/energyplus_tmy

export PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
export PYTHONPATH="${ROOT}/scripts"

echo "=== input presence ==="
test -x "${PY}"
test -f "${ROOT}/external/Data-Center-Water-footprint/simulation_funs_DC.py"
test -f "${ROOT}/external/Data-Center-Water-footprint/Simulation Results/UE.xlsx"
test -f "${ROOT}/external/frontier/Frontier HPC & Facility Data.xlsx"
test -f "${REPO}/Meta_Prineville_Oregon_v3/data/processed/weather_hourly.csv"
test -f "${ROOT}/results/FIRST_RUN_STATUS.json"
touch "${ROOT}/logs/followup_v1/.write_test" && rm -f "${ROOT}/logs/followup_v1/.write_test"
touch "${ROOT}/results/followup_v1/.write_test" && rm -f "${ROOT}/results/followup_v1/.write_test"

echo "=== sinfo ==="
sinfo -s | grep -E 'PARTITION|sloan_batch|mit_normal' || sinfo -s | head -15

echo "=== squeue before ==="
squeue -u "${USER}" -o '%.18i %.12P %.22j %.8T %.10M %R' | head -20

submit_one () {
  local script="$1"
  shift
  sbatch --parsable "$@" "${script}"
}

PRE="$(submit_one "${ROOT}/slurm/followup_v1/00_preflight.sbatch")"
echo "PREFLIGHT ${PRE}"
NB="$(submit_one "${ROOT}/slurm/followup_v1/01_notebook.sbatch" --depend="afterok:${PRE}")"
echo "NOTEBOOK ${NB}"
FRONT="$(submit_one "${ROOT}/slurm/followup_v1/02_frontier.sbatch" --depend="afterok:${PRE}")"
echo "FRONTIER ${FRONT}"
SMOKE="$(submit_one "${ROOT}/slurm/followup_v1/03_smoke.sbatch" --depend="afterok:${PRE}")"
echo "SMOKE ${SMOKE}"
CELL="$(submit_one "${ROOT}/slurm/followup_v1/04_selected.sbatch" --depend="afterok:${SMOKE}")"
echo "SELECTED_ARRAY ${CELL}"
RNG="$(submit_one "${ROOT}/slurm/followup_v1/05_rng.sbatch" --depend="afterok:${SMOKE}")"
echo "RNG ${RNG}"
GATE="$(submit_one "${ROOT}/slurm/followup_v1/06_gate.sbatch" --depend="afterok:${CELL}:${RNG}:${NB}:${FRONT}")"
echo "GATE ${GATE}"
ADP="$(submit_one "${ROOT}/slurm/followup_v1/07_adapter.sbatch" --depend="afterok:${GATE}")"
echo "ADAPTER ${ADP}"
PRV="$(submit_one "${ROOT}/slurm/followup_v1/08_prineville.sbatch" --depend="afterok:${ADP}")"
echo "PRINEVILLE ${PRV}"
FIN="$(submit_one "${ROOT}/slurm/followup_v1/09_finalize.sbatch" --depend="afterok:${PRV}")"
echo "FINALIZE ${FIN}"

NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
HEAD="$(git -C "${REPO}" rev-parse HEAD 2>/dev/null || echo UNKNOWN)"
UP="$(git -C "${ROOT}/external/Data-Center-Water-footprint" rev-parse HEAD 2>/dev/null || echo UNKNOWN)"
"${PY}" - << PY
import json
from pathlib import Path
root = Path("${ROOT}")
jobs = {
    "created_utc": "${NOW}",
    "submit_host": __import__("socket").gethostname(),
    "git_head": "${HEAD}",
    "upstream_commit": "${UP}",
    "work_root": str(root),
    "python": "${PY}",
    "partition": "sched_mit_sloan_batch",
    "environment": "masanet_lei",
    "seed_plan": {
        "facility_LHS": "cell_lhs_seed = 2025 + 1000*case + 10*zone_index + replicate",
        "internal_stream": "lhs_seed*100003 + sample_id*1009 + stream_offset",
        "notebook_sweep": "np.random.seed 0:9999 on demo vector",
        "prineville": "lhs_seed = 202200 + paper_case",
    },
    "dependency_graph": {
        "PREFLIGHT": "${PRE}",
        "NOTEBOOK": "${NB}",
        "FRONTIER": "${FRONT}",
        "ANNUAL_SMOKE": "${SMOKE}",
        "ANNUAL_SELECTED_ARRAY": "${CELL}",
        "ANNUAL_RNG": "${RNG}",
        "ANNUAL_GATE": "${GATE}",
        "PROJECT_ADAPTER_TEST": "${ADP}",
        "PRINEVILLE_WEATHER_SMOKE": "${PRV}",
        "FINALIZE": "${FIN}",
        "edges": [
            "NOTEBOOK afterok PREFLIGHT",
            "FRONTIER afterok PREFLIGHT",
            "ANNUAL_SMOKE afterok PREFLIGHT",
            "ANNUAL_SELECTED_ARRAY afterok ANNUAL_SMOKE",
            "ANNUAL_RNG afterok ANNUAL_SMOKE",
            "ANNUAL_GATE afterok SELECTED and RNG and NOTEBOOK and FRONTIER",
            "ADAPTER afterok GATE",
            "PRINEVILLE afterok ADAPTER",
            "FINALIZE afterok PRINEVILLE",
        ],
    },
    "job_ids": {
        "PREFLIGHT": "${PRE}",
        "NOTEBOOK": "${NB}",
        "FRONTIER": "${FRONT}",
        "ANNUAL_SMOKE": "${SMOKE}",
        "ANNUAL_SELECTED_ARRAY": "${CELL}",
        "ANNUAL_RNG": "${RNG}",
        "ANNUAL_GATE": "${GATE}",
        "PROJECT_ADAPTER_TEST": "${ADP}",
        "PRINEVILLE_WEATHER_SMOKE": "${PRV}",
        "FINALIZE": "${FIN}",
    },
    "independent_of_local_session": True,
    "resources": {
        "annual_and_prineville": "8 CPU, 16-24G, no GPU",
        "partition_order": ["sched_mit_sloan_batch"],
    },
    "notes": [
        "Jobs use absolute paths and conda env python binary; no notebook/tmux/SSH session required after sbatch.",
        "Inputs live under /home/nacevedo which is cluster shared storage.",
        "First-run JSON/CSV/Parquet/figures are not overwritten.",
        "GATE also writes a status snapshot; FINALIZE refreshes after Prineville.",
    ],
}
path = root / "manifests" / "SLURM_FOLLOWUP_V1.json"
path.write_text(json.dumps(jobs, indent=2) + "\n")
print("WROTE", path)
PY

echo "=== squeue after submit ==="
squeue -u "${USER}" -o '%.18i %.12P %.22j %.8T %.10M %.12E %R'
echo "Submitted. Jobs do not depend on this shell."
echo "IDs: PRE=${PRE} NB=${NB} FRONT=${FRONT} SMOKE=${SMOKE} CELL=${CELL} RNG=${RNG} GATE=${GATE} ADP=${ADP} PRV=${PRV} FIN=${FIN}"
