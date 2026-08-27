#!/bin/bash
#SBATCH -J m100_fac
#SBATCH -p sched_mit_sloan_batch_r8
#SBATCH -N 1
#SBATCH -c 8
#SBATCH --mem=16G
#SBATCH -t 02:00:00
#SBATCH --array=1-3%2
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/fac_%A_%a.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/fac_%A_%a.err

set -eo pipefail
export PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
unset PYTHONPATH PYTHONHOME
PY="/home/nacevedo/.conda/envs/dc_externalities/bin/python"
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100"
cd "${ROOT}"
export PYTHONPATH="${ROOT}/scripts"
export TMPDIR="${SLURM_TMPDIR:-/tmp}"
MONTHS=(2021-04 2021-05 2021-06)
MONTH="${MONTHS[$((SLURM_ARRAY_TASK_ID-1))]}"
echo "host=$(hostname) job=${SLURM_JOB_ID} month=${MONTH} start=$(date -Is) TMPDIR=${TMPDIR}"
"${PY}" scripts/process_m100_facility_month.py --month "${MONTH}"
echo "end=$(date -Is)"
