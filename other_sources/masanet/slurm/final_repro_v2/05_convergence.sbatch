#!/bin/bash
#SBATCH -J v2_conv
#SBATCH -p sched_mit_sloan_batch
#SBATCH -N 1
#SBATCH -c 8
#SBATCH --mem=16G
#SBATCH -t 24:00:00
#SBATCH --chdir=/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet/logs/final_repro_v2/conv_%j.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet/logs/final_repro_v2/conv_%j.err

set -euo pipefail
export PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
unset PYTHONPATH PYTHONHOME
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet"
PY="/home/nacevedo/.conda/envs/masanet_lei/bin/python"
cd "${ROOT}"
export PYTHONPATH="${ROOT}/scripts:${ROOT}/scripts/final_repro_v2"
echo "host=$(hostname) job=${SLURM_JOB_ID:-local} start=$(date -Is)"
if [[ ! -f "${ROOT}/manifests/final_repro_v2/CONVERGENCE_REQUESTED.json" ]]; then
  echo "convergence not requested; skip"
  exit 0
fi
"${PY}" scripts/final_repro_v2/run_convergence.py
"${PY}" scripts/final_repro_v2/analyze_and_finalize.py
echo "end=$(date -Is)"
