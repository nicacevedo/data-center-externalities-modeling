#!/bin/bash
#SBATCH -J v2_preflight
#SBATCH -N 1
#SBATCH -c 2
#SBATCH --mem=8G
#SBATCH -t 00:30:00
#SBATCH --chdir=/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet/logs/final_repro_v2/preflight_%j.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet/logs/final_repro_v2/preflight_%j.err

set -euo pipefail
export PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
unset PYTHONPATH PYTHONHOME
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet"
PY="/home/nacevedo/.conda/envs/masanet_lei/bin/python"
cd "${ROOT}"
export PYTHONPATH="${ROOT}/scripts:${ROOT}/scripts/final_repro_v2"
export V2_PREFLIGHT_TAG="${SLURM_JOB_PARTITION:-unknown}"
echo "host=$(hostname) job=${SLURM_JOB_ID:-local} partition=${SLURM_JOB_PARTITION:-none} start=$(date -Is)"
"${PY}" -c "import sys; print(sys.executable); import numpy,scipy,sklearn; print(numpy.__version__, scipy.__version__, sklearn.__file__)"
"${PY}" scripts/final_repro_v2/partition_preflight.py
echo "end=$(date -Is)"
