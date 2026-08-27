#!/bin/bash
#SBATCH -J m100_v3_node
#SBATCH -p sched_mit_sloan_batch_r8
#SBATCH -N 1
#SBATCH -c 8
#SBATCH --mem=32G
#SBATCH -t 02:00:00
#SBATCH --array=1-11%3
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/v3_node_%A_%a.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/v3_node_%A_%a.err

set -eo pipefail
export PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
unset PYTHONPATH PYTHONHOME
PY="/home/nacevedo/.conda/envs/dc_externalities/bin/python"
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100"
cd "${ROOT}"
export PYTHONPATH="${ROOT}/scripts"
export TMPDIR="${SLURM_TMPDIR:-/orcd/scratch/orcd/008/nacevedo/m100/tmp/${SLURM_JOB_ID}}"
mkdir -p "${TMPDIR}" logs/slurm
echo "host=$(hostname) job=${SLURM_JOB_ID} array=${SLURM_ARRAY_TASK_ID} start=$(date -Is)"
"${PY}" scripts/analyze_m100_suitability_v3.py --stage node
echo "end=$(date -Is)"
