#!/bin/bash
#SBATCH -J m100_fac
#SBATCH -p sched_mit_sloan_batch_r8
#SBATCH -N 1
#SBATCH -c 8
#SBATCH --mem=16G
#SBATCH -t 02:00:00
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/fac_%j.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/fac_%j.err

# sbatch --export=ALL,MONTH=2021-01 scripts/run_m100_2021_facility.sbatch

set -eo pipefail
export PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
unset PYTHONPATH PYTHONHOME
PY="/home/nacevedo/.conda/envs/dc_externalities/bin/python"
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100"
cd "${ROOT}"
export PYTHONPATH="${ROOT}/scripts"
export TMPDIR="${SLURM_TMPDIR:-/tmp}"
MONTH="${MONTH:?set MONTH=YYYY-MM}"
echo "host=$(hostname) job=${SLURM_JOB_ID} month=${MONTH} start=$(date -Is) TMPDIR=${TMPDIR}"
"${PY}" scripts/process_m100_facility_month.py --month "${MONTH}"
echo "end=$(date -Is)"
