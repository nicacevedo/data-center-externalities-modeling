#!/bin/bash
#SBATCH -J m100_v3
#SBATCH -p sched_mit_sloan_batch_r8
#SBATCH -N 1
#SBATCH -c 4
#SBATCH --mem=16G
#SBATCH -t 01:00:00
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/v3_%x_%j.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/v3_%x_%j.err

set -eo pipefail
export PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
unset PYTHONPATH PYTHONHOME
PY="/home/nacevedo/.conda/envs/dc_externalities/bin/python"
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100"
cd "${ROOT}"
export PYTHONPATH="${ROOT}/scripts"
export TMPDIR="${SLURM_TMPDIR:-/orcd/scratch/orcd/008/nacevedo/m100/tmp/${SLURM_JOB_ID}}"
mkdir -p "${TMPDIR}" logs/slurm
STAGE="${STAGE:?STAGE env required}"
echo "host=$(hostname) job=${SLURM_JOB_ID} stage=${STAGE} partition=${SLURM_JOB_PARTITION} cpus=${SLURM_CPUS_PER_TASK} start=$(date -Is)"
"${PY}" scripts/analyze_m100_suitability_v3.py --stage "${STAGE}"
echo "end=$(date -Is)"
