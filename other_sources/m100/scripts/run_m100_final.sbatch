#!/bin/bash
#SBATCH -J m100_final
#SBATCH -p sched_mit_sloan_batch_r8
#SBATCH -N 1
#SBATCH -c 4
#SBATCH --mem=16G
#SBATCH -t 04:00:00
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/final_%j.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/final_%j.err

set -eo pipefail
export PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
unset PYTHONPATH PYTHONHOME
PY="/home/nacevedo/.conda/envs/dc_externalities/bin/python"
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100"
cd "${ROOT}"
export PYTHONPATH="${ROOT}/scripts"
export TMPDIR="${SLURM_TMPDIR:-/orcd/scratch/orcd/008/nacevedo/m100/tmp/${SLURM_JOB_ID}}"
mkdir -p "${TMPDIR}" logs/slurm
echo "host=$(hostname) job=${SLURM_JOB_ID} start=$(date -Is)"
"${PY}" scripts/catalog_m100_2021.py --inventory
"${PY}" scripts/qualify_m100_2021.py
"${PY}" scripts/analyze_m100_suitability.py
echo "end=$(date -Is)"
ls -l results/suitability_2021/final_report.md results/suitability_2021/final_status.json
