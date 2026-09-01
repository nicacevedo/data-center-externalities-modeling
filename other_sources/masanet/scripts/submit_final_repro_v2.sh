#!/bin/bash
# Submit final_repro_v2 DAG. Recover/notebook must already have been run.
set -euo pipefail
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet"
REPO="/home/nacevedo/RA/data-center-externalities-modeling"
PY="/home/nacevedo/.conda/envs/masanet_lei/bin/python"
SLURM="${ROOT}/slurm/final_repro_v2"
cd "${ROOT}"
mkdir -p logs/final_repro_v2 results/final_repro_v2/reps results/final_repro_v2/rng results/final_repro_v2/notebook manifests/final_repro_v2
export PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
export PYTHONPATH="${ROOT}/scripts:${ROOT}/scripts/final_repro_v2"

test -f "${ROOT}/manifests/final_repro_v2/TASK_MANIFEST.json"
test -f "${ROOT}/manifests/final_repro_v2/TASK_MANIFEST.sha256"

echo "=== sinfo (candidate partitions) ==="
sinfo -s | grep -E 'PARTITION|sloan_batch|mit_normal|ou_sloan' || sinfo -s | head -20

submit_p () {
  local part="$1"
  sbatch --parsable -p "${part}" "${SLURM}/00_preflight.sbatch" || echo "SUBMIT_FAIL:${part}"
}

P_SLOAN="$(submit_p sched_mit_sloan_batch)"
echo "PRE_SLOAN ${P_SLOAN}"
P_R8="$(submit_p sched_mit_sloan_batch_r8 || true)"
echo "PRE_R8 ${P_R8}"
P_OU="$(submit_p ou_sloan_batch || true)"
echo "PRE_OU ${P_OU}"
P_MIT="$(submit_p mit_normal || true)"
echo "PRE_MIT ${P_MIT}"

# Unit smoke after Sloan preflight if that job id is numeric
SMOKE=""
if [[ "${P_SLOAN}" =~ ^[0-9]+$ ]]; then
  SMOKE="$(sbatch --parsable --depend="afterok:${P_SLOAN}" "${SLURM}/01_unit_smoke.sbatch")"
  echo "SMOKE ${SMOKE}"
fi

NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
HEAD="$(git -C "${REPO}" rev-parse HEAD 2>/dev/null || echo UNKNOWN)"
"${PY}" - << PY
import json
from pathlib import Path
root = Path("${ROOT}")
jobs = {
    "created_utc": "${NOW}",
    "git_head": "${HEAD}",
    "phase": "preflight_submitted",
    "job_ids": {
        "PRE_sched_mit_sloan_batch": "${P_SLOAN}",
        "PRE_sched_mit_sloan_batch_r8": "${P_R8}",
        "PRE_ou_sloan_batch": "${P_OU}",
        "PRE_mit_normal": "${P_MIT}",
        "UNIT_SMOKE": "${SMOKE}",
    },
    "notes": [
        "Arrays are submitted after preflights by submit_arrays_final_repro_v2.sh",
        "TASK_MANIFEST frozen before results; hash in TASK_MANIFEST.sha256",
    ],
}
path = root / "manifests" / "final_repro_v2" / "SLURM_FINAL_REPRO_V2.json"
path.write_text(json.dumps(jobs, indent=2) + "\n")
print("WROTE", path)
PY

echo "Preflights submitted. After they finish, run scripts/submit_arrays_final_repro_v2.sh"
squeue -u "${USER}" -o '%.18i %.12P %.22j %.8T %.10M %R' | head -30
