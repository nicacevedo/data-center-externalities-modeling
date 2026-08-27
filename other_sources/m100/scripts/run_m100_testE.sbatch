#!/bin/bash
#SBATCH -J m100_tE
#SBATCH -p sched_mit_sloan_batch_r8
#SBATCH -N 1
#SBATCH -c 4
#SBATCH --mem=8G
#SBATCH -t 01:00:00
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/testE_%j.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/testE_%j.err
set -eo pipefail
export PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
unset PYTHONPATH PYTHONHOME
PY="/home/nacevedo/.conda/envs/dc_externalities/bin/python"
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100"
cd "${ROOT}"
export PYTHONPATH="${ROOT}/scripts"
export TMPDIR="${SLURM_TMPDIR:-/orcd/scratch/orcd/008/nacevedo/m100/tmp/${SLURM_JOB_ID}}"
mkdir -p "${TMPDIR}"
MONTH="${MONTH:-2021-04}"
echo "TEST_E start host=$(hostname) month=${MONTH} TMPDIR=${TMPDIR}"
"${PY}" scripts/process_m100_month.py --month "${MONTH}" --grains weather --force
# confirm no leftover extract under repo
if find "${ROOT}/data/interim" -name '*.parquet' 2>/dev/null | grep -q .; then
  echo "FAIL leftover interim parquet in repo"
  exit 1
fi
echo TEST_E_OK
