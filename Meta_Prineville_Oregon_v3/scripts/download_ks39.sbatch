#!/bin/bash
#SBATCH -J ks39_madis
#SBATCH -p sched_mit_sloan_batch_r8
#SBATCH -t 24:00:00
#SBATCH -c 4
#SBATCH --mem=16G
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/logs/ks39_madis_%j.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/logs/ks39_madis_%j.err

set -eo pipefail
unset PYTHONPATH PYTHONHOME
export PATH="/home/nacevedo/.conda/envs/dc_externalities/bin:${PATH}"
PY="/home/nacevedo/.conda/envs/dc_externalities/bin/python"
cd /home/nacevedo/RA/data-center-externalities-modeling/Meta_Prineville_Oregon_v3
echo "host=$(hostname) python=${PY}"
"${PY}" --version
"${PY}" src/download_madis_ks39.py --workers 4
"${PY}" src/download_madis_ks39.py --export-only
echo "KS39 MADIS extract finished"
