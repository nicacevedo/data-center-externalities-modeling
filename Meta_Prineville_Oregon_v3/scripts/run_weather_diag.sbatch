#!/bin/bash
#SBATCH -J prn_wx_diag
#SBATCH -p sched_mit_sloan_batch_r8
#SBATCH -t 01:00:00
#SBATCH -c 4
#SBATCH --mem=16G
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/Meta_Prineville_Oregon_v3/outputs/slurm_logs/weather_diag_%j.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/Meta_Prineville_Oregon_v3/outputs/slurm_logs/weather_diag_%j.err

set -eo pipefail
unset PYTHONPATH PYTHONHOME
export PYTHONNOUSERSITE=1
export PATH="/home/nacevedo/.conda/envs/dc_externalities/bin:${PATH}"
PY="/home/nacevedo/.conda/envs/dc_externalities/bin/python"
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/Meta_Prineville_Oregon_v3"
cd "${ROOT}"
mkdir -p outputs/slurm_logs

echo "host=$(hostname) job=${SLURM_JOB_ID} start=$(date -Is)"
"${PY}" --version
"${PY}" scripts/diagnose_tertiary_weather.py
echo "end=$(date -Is)"
