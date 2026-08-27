#!/bin/bash
#SBATCH -J m100_audit
#SBATCH -p sched_mit_sloan_batch_r8
#SBATCH -N 1
#SBATCH -c 1
#SBATCH --mem=2G
#SBATCH -t 01:00:00
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/audit_%j.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/audit_%j.err

set -eo pipefail
export PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
unset PYTHONPATH PYTHONHOME
PY="/home/nacevedo/.conda/envs/dc_externalities/bin/python"
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100"
cd "${ROOT}"
export PYTHONPATH="${ROOT}/scripts"
"${PY}" scripts/storage_audit_m100.py
