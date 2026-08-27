#!/bin/bash
#SBATCH -J m100_hourly
#SBATCH -p sched_mit_sloan_batch_r8
#SBATCH -N 1
#SBATCH -c 16
#SBATCH --mem=16G
#SBATCH -t 01:00:00
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/m100_hourly_%j.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/m100_hourly_%j.err

# Usage:
#   sbatch --export=ALL,MONTH=2021-01 scripts/run_m100_hourly.sbatch
# Rebuild the processed panel:
#   sbatch --export=ALL,MONTH=2021-01,FORCE_REBUILD=1 scripts/run_m100_hourly.sbatch

set -eo pipefail
unset PYTHONPATH PYTHONHOME
export PYTHONNOUSERSITE=1
export PYTHONUNBUFFERED=1
export OMP_NUM_THREADS=${SLURM_CPUS_PER_TASK}
export MKL_NUM_THREADS=${SLURM_CPUS_PER_TASK}
export OPENBLAS_NUM_THREADS=${SLURM_CPUS_PER_TASK}

MONTH="${MONTH:-2021-01}"
FORCE_REBUILD="${FORCE_REBUILD:-0}"
PY="/home/nacevedo/.conda/envs/dc_externalities/bin/python"
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100"
cd "${ROOT}"
mkdir -p logs/slurm data/processed/hourly results/hourly
export TMPDIR="${SLURM_TMPDIR:-/tmp}"
export PYTHONPATH="${ROOT}/scripts${PYTHONPATH:+:${PYTHONPATH}}"

echo "host=$(hostname) partition=${SLURM_JOB_PARTITION} job=${SLURM_JOB_ID} cpus=${SLURM_CPUS_PER_TASK} mem=${SLURM_MEM_PER_NODE}"
echo "month=${MONTH} force_rebuild=${FORCE_REBUILD} TMPDIR=${TMPDIR}"
echo "start=$(date -Is)"
"${PY}" --version

BUILD_ARGS=(--month "${MONTH}" --archive "data/raw/archives/$(echo "${MONTH}" | awk -F- '{printf "%02d-%02d.tar", $1%100, $2}')")
if [[ "${FORCE_REBUILD}" == "1" ]]; then
  BUILD_ARGS+=(--force-rebuild)
fi

"${PY}" scripts/build_m100_hourly.py "${BUILD_ARGS[@]}"
"${PY}" scripts/analyze_m100_hourly.py --month "${MONTH}"

echo "end=$(date -Is)"
ls -lh "data/processed/hourly/${MONTH}/m100_node_hourly.parquet"
ls "results/hourly/${MONTH}/figures"
ls "results/hourly/${MONTH}/tables"
