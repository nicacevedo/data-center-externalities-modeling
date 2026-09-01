#!/bin/bash
#SBATCH -J v2_rep
#SBATCH -N 1
#SBATCH -c 8
#SBATCH --mem=16G
#SBATCH --chdir=/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet/logs/final_repro_v2/rep_%A_%a.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet/logs/final_repro_v2/rep_%A_%a.err

set -euo pipefail
export PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
unset PYTHONPATH PYTHONHOME
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet"
PY="/home/nacevedo/.conda/envs/masanet_lei/bin/python"
cd "${ROOT}"
export PYTHONPATH="${ROOT}/scripts:${ROOT}/scripts/final_repro_v2"
SPLIT="${V2_SPLIT_FILE:-${ROOT}/manifests/final_repro_v2/TASK_SPLIT.json}"
PART="${SLURM_JOB_PARTITION}"
TASK_ID="$("${PY}" -c "import json,os; m=json.load(open('${SPLIT}')); print(m['${PART}'][int(os.environ['SLURM_ARRAY_TASK_ID'])])")"
echo "host=$(hostname) job=${SLURM_JOB_ID:-local} array=${SLURM_ARRAY_TASK_ID} task_id=${TASK_ID} part=${PART} start=$(date -Is)"
OUT="${ROOT}/results/final_repro_v2/reps/rep_$(printf '%04d' "${TASK_ID}").json"
if [[ -f "${OUT}" ]]; then
  "${PY}" -c "import json,sys; json.load(open(sys.argv[1])); print('already complete', sys.argv[1])" "${OUT}"
  echo "end=$(date -Is) skip"
  exit 0
fi
"${PY}" scripts/final_repro_v2/run_replication.py --task-id "${TASK_ID}" --workers "${SLURM_CPUS_PER_TASK}"
echo "end=$(date -Is)"
