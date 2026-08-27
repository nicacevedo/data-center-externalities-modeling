#!/bin/bash
#SBATCH -J m100_dl
#SBATCH -p mit_data_transfer
#SBATCH -N 1
#SBATCH -c 1
#SBATCH --mem=2G
#SBATCH -t 12:00:00
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/dl_%j.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/dl_%j.err

set -eo pipefail
export PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
unset PYTHONPATH PYTHONHOME
PY="/home/nacevedo/.conda/envs/dc_externalities/bin/python"
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100"
cd "${ROOT}"
export PYTHONPATH="${ROOT}/scripts"
export TMPDIR="${SLURM_TMPDIR:-/orcd/scratch/orcd/008/nacevedo/m100/tmp}"
mkdir -p "${TMPDIR}" logs/slurm
echo "host=$(hostname) job=${SLURM_JOB_ID} month=${MONTH} start=$(date -Is)"
"${PY}" scripts/download_m100_month.py --month "${MONTH}"
echo "end=$(date -Is)"
