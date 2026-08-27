#!/bin/bash
#SBATCH -J m100_tB
#SBATCH -p sched_mit_sloan_batch,sched_mit_sloan_batch_r8
#SBATCH -N 1
#SBATCH -c 1
#SBATCH --mem=1G
#SBATCH -t 00:10:00
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/testB_%j.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/testB_%j.err
set -euo pipefail
echo "TEST_B_OK host=$(hostname) job=${SLURM_JOB_ID} date=$(date -Is)"
echo "${SLURM_JOB_ID}" > /orcd/scratch/orcd/008/nacevedo/m100/tests/testB_jobid.txt
