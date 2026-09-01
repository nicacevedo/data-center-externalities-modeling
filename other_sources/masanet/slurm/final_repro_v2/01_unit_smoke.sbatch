#!/bin/bash
#SBATCH -J v2_smoke
#SBATCH -p sched_mit_sloan_batch
#SBATCH -N 1
#SBATCH -c 8
#SBATCH --mem=16G
#SBATCH -t 01:00:00
#SBATCH --chdir=/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet/logs/final_repro_v2/smoke_%j.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet/logs/final_repro_v2/smoke_%j.err

set -euo pipefail
export PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
unset PYTHONPATH PYTHONHOME
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet"
PY="/home/nacevedo/.conda/envs/masanet_lei/bin/python"
cd "${ROOT}"
export PYTHONPATH="${ROOT}/scripts:${ROOT}/scripts/final_repro_v2"
echo "host=$(hostname) job=${SLURM_JOB_ID:-local} start=$(date -Is)"
# Short scientific smoke: same frozen task 0 seeds, 24 hours only. Output goes to a smoke path via n-hours override.
# run_replication writes rep_0000.json; move aside if a full rep is not intended.
SMOKE_DIR="${ROOT}/results/final_repro_v2/smoke"
mkdir -p "${SMOKE_DIR}"
"${PY}" scripts/final_repro_v2/run_replication.py --task-id 0 --workers "${SLURM_CPUS_PER_TASK}" --n-hours 24
if [[ -f "${ROOT}/results/final_repro_v2/reps/rep_0000.json" ]]; then
  mv "${ROOT}/results/final_repro_v2/reps/rep_0000.json" "${SMOKE_DIR}/rep_0000_nhours24.json"
fi
echo "end=$(date -Is)"
