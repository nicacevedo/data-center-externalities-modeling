#!/bin/bash
#SBATCH --job-name=fc3_masanet
#SBATCH --partition=sched_mit_sloan_batch_r8
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=02:00:00
#SBATCH --output=/home/nacevedo/RA/data-center-externalities-modeling/Meta_Forest_City_North_Carolina_v3/outputs/slurm/%x_%j.out
#SBATCH --error=/home/nacevedo/RA/data-center-externalities-modeling/Meta_Forest_City_North_Carolina_v3/outputs/slurm/%x_%j.err
# CPU only. Do not use mit_normal. Do not request a GPU.

set -euo pipefail
export PYTHONNOUSERSITE=1
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
MASANET_PY=/home/nacevedo/.conda/envs/masanet_lei/bin/python
SCRIPT=/home/nacevedo/RA/data-center-externalities-modeling/Meta_Forest_City_North_Carolina_v3/scripts/run_masanet_transfer.py
echo "host=$(hostname) partition=${SLURM_JOB_PARTITION:-unset} job=${SLURM_JOB_ID:-local}"
"$MASANET_PY" "$SCRIPT"
