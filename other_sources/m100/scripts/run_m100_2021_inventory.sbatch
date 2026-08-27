#!/bin/bash
#SBATCH -J m100_inv
#SBATCH -p sched_mit_sloan_batch_r8
#SBATCH -N 1
#SBATCH -c 2
#SBATCH --mem=4G
#SBATCH -t 00:40:00
#SBATCH --array=1-6%2
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/inv_%A_%a.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/logs/slurm/inv_%A_%a.err

set -eo pipefail
export PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
unset PYTHONPATH PYTHONHOME
PY="/home/nacevedo/.conda/envs/dc_externalities/bin/python"
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100"
cd "${ROOT}"
export PYTHONPATH="${ROOT}/scripts"
mkdir -p logs/slurm data/catalog/inventory results/2021_status

MONTHS=(2021-01 2021-02 2021-03 2021-04 2021-05 2021-06)
MONTH="${MONTHS[$((SLURM_ARRAY_TASK_ID-1))]}"
echo "host=$(hostname) job=${SLURM_JOB_ID} month=${MONTH} start=$(date -Is)"
# Skip tiny incomplete files without scanning.
SZ=$(stat -c%s "archives/${MONTH:2:2}-${MONTH:5:2}.tar" 2>/dev/null || echo 0)
if [[ "${SZ}" -lt 2000000000 ]]; then
  echo "SKIP ${MONTH} size=${SZ} likely incomplete"
  "${PY}" - <<PY
from m100_2021_common import save_status
save_status("${MONTH}", archive_status="downloading/incomplete", inventory_status="skipped")
PY
  exit 0
fi
"${PY}" scripts/catalog_m100_2021.py --inventory --month "${MONTH}"
echo "end=$(date -Is)"
