#!/bin/bash
#SBATCH -J masanet_repro
#SBATCH -p sched_mit_sloan_batch
#SBATCH -N 1
#SBATCH -c 2
#SBATCH --mem=8G
#SBATCH -t 01:00:00
#SBATCH --chdir=/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet/logs/00_masanet_repro_%j.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet/logs/00_masanet_repro_%j.err

set -euo pipefail
export PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
unset PYTHONPATH PYTHONHOME
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet"
PY="/home/nacevedo/.conda/envs/masanet_lei/bin/python"
cd "${ROOT}"
export PYTHONPATH="${ROOT}/scripts"
mkdir -p logs results manifests docs
echo "host=$(hostname) job=${SLURM_JOB_ID:-local} start=$(date -Is) py=${PY}"
"${PY}" scripts/write_provenance.py
"${PY}" scripts/run_masanet_repro.py
"${PY}" -m pytest tests/test_masanet_first_run.py -q --tb=short
echo "end=$(date -Is)"
