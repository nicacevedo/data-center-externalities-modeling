#!/bin/bash
#SBATCH -J frontier_val
#SBATCH -p sched_mit_sloan_batch
#SBATCH -N 1
#SBATCH -c 2
#SBATCH --mem=8G
#SBATCH -t 01:00:00
#SBATCH --chdir=/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet/logs/03_frontier_validate_%j.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet/logs/03_frontier_validate_%j.err

set -euo pipefail
export PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
unset PYTHONPATH PYTHONHOME
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet"
PY="/home/nacevedo/.conda/envs/masanet_lei/bin/python"
cd "${ROOT}"
export PYTHONPATH="${ROOT}/scripts"
echo "host=$(hostname) job=${SLURM_JOB_ID:-local} start=$(date -Is)"
test -f "${ROOT}/external/frontier/Frontier HPC & Facility Data.xlsx"
"${PY}" scripts/run_frontier_validate.py
echo "end=$(date -Is)"
