#!/bin/bash
#SBATCH -J ks39_recon
#SBATCH -p sched_mit_sloan_batch_r8
#SBATCH -t 04:00:00
#SBATCH -c 4
#SBATCH --mem=16G
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/logs/ks39_recon_%j.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/logs/ks39_recon_%j.err

set -eo pipefail
unset PYTHONPATH PYTHONHOME
export PATH="/home/nacevedo/.conda/envs/dc_externalities/bin:${PATH}"
PY="/home/nacevedo/.conda/envs/dc_externalities/bin/python"
cd /home/nacevedo/RA/data-center-externalities-modeling/Meta_Prineville_Oregon_v3
echo "host=$(hostname) python=${PY}"
"${PY}" --version
"${PY}" run_prineville.py conditional
"${PY}" src/summarize_weather_reconstruction.py --out outputs/weather_ks39/canonical_reconstruction_metrics.csv
echo "KS39 reconstruction finished"
