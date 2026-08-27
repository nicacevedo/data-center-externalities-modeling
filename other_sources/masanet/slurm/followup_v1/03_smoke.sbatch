#!/bin/bash
#SBATCH -J fu_smoke
#SBATCH -p sched_mit_sloan_batch
#SBATCH -N 1
#SBATCH -c 8
#SBATCH --mem=16G
#SBATCH -t 08:00:00
#SBATCH --chdir=/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet/logs/followup_v1/03_smoke_%j.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet/logs/followup_v1/03_smoke_%j.err

set -euo pipefail
export PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
unset PYTHONPATH PYTHONHOME
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet"
PY="/home/nacevedo/.conda/envs/masanet_lei/bin/python"
cd "${ROOT}"
export PYTHONPATH="${ROOT}/scripts"
echo "host=$(hostname) job=${SLURM_JOB_ID:-local} start=$(date -Is) cpus=${SLURM_CPUS_PER_TASK}"
test -f "${ROOT}/results/followup_v1/annual_smoke_short.json"
"${PY}" scripts/followup_annual.py --mode smoke-full --workers "${SLURM_CPUS_PER_TASK}"
echo "end=$(date -Is)"
