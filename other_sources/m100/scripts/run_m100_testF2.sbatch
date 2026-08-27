#!/bin/bash
#SBATCH -J m100_tF2
#SBATCH -p sched_mit_sloan_batch,sched_mit_sloan_batch_r8
#SBATCH -N 1
#SBATCH -c 1
#SBATCH --mem=1G
#SBATCH -t 00:10:00
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/testF2_%j.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/testF2_%j.err
set -euo pipefail
echo "TEST_F2_OK job=${SLURM_JOB_ID} after F1" | tee /orcd/scratch/orcd/008/nacevedo/m100/tests/testF2.txt
test -f /orcd/scratch/orcd/008/nacevedo/m100/tests/testF1.txt
