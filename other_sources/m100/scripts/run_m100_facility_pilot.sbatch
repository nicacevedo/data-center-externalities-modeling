#!/bin/bash
#SBATCH -J m100_pilot
#SBATCH -p mit_normal
#SBATCH -N 1
#SBATCH -c 1
#SBATCH --mem=4G
#SBATCH -t 00:30:00
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/pilot_%j.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/pilot_%j.err

set -eo pipefail
export PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
unset PYTHONPATH PYTHONHOME
PY="/home/nacevedo/.conda/envs/dc_externalities/bin/python"
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100"
cd "${ROOT}"
export PYTHONPATH="${ROOT}/scripts"
echo "host=$(hostname) job=${SLURM_JOB_ID} start=$(date -Is) partition=${SLURM_JOB_PARTITION}"
"${PY}" scripts/run_m100_facility_pilot.py
echo "end=$(date -Is)"
ls -l results/pilot_facility_2021/pilot_status.json results/pilot_facility_2021/pilot_report.md
