#!/bin/bash
#SBATCH --job-name=fc_v2_airside
#SBATCH --partition=sched_mit_sloan_batch
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=04:00:00
#SBATCH --output=/orcd/home/002/nacevedo/RA/data-center-externalities-modeling/Meta_Forest_City_North_Carolina_v2/outputs/logs/%x_%j.out
#SBATCH --error=/orcd/home/002/nacevedo/RA/data-center-externalities-modeling/Meta_Forest_City_North_Carolina_v2/outputs/logs/%x_%j.err
# Do not use mit_normal. CPU only.
# This script is for nontrivial re-runs. The first v2 pass is intended interactive.

set -euo pipefail
export OMP_NUM_THREADS=1
cd /orcd/home/002/nacevedo/RA/data-center-externalities-modeling/Meta_Forest_City_North_Carolina_v2
/home/nacevedo/.conda/envs/dc_externalities/bin/python scripts/run_v2_pipeline.py
