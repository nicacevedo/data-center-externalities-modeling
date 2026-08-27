#!/bin/bash
#SBATCH -J m100_jan_hourly
#SBATCH -p sched_mit_sloan_batch_r8
#SBATCH -N 1
#SBATCH -c 16
#SBATCH --mem=64G
#SBATCH -t 02:00:00
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/january_hourly_%j.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/january_hourly_%j.err

set -eo pipefail
unset PYTHONPATH PYTHONHOME
export PYTHONNOUSERSITE=1
export OMP_NUM_THREADS=${SLURM_CPUS_PER_TASK}
export MKL_NUM_THREADS=${SLURM_CPUS_PER_TASK}
export OPENBLAS_NUM_THREADS=${SLURM_CPUS_PER_TASK}

PY="/home/nacevedo/.conda/envs/dc_externalities/bin/python"
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100"
cd "${ROOT}"
mkdir -p logs derived/january_hourly/figures

echo "host=$(hostname) partition=${SLURM_JOB_PARTITION} job=${SLURM_JOB_ID} cpus=${SLURM_CPUS_PER_TASK}"
echo "start=$(date -Is)"
"${PY}" --version

# Node-local spill space for DuckDB if present.
export TMPDIR="${SLURM_TMPDIR:-/tmp}"
echo "TMPDIR=${TMPDIR}"

"${PY}" scripts/analyze_january_hourly.py \
  --data-root daily_input_january \
  --output-dir derived/january_hourly

echo "end=$(date -Is)"
echo "parquet=$(ls -lh derived/january_hourly/m100_2021_01_node_hourly.parquet)"
echo "figures=$(ls derived/january_hourly/figures)"
