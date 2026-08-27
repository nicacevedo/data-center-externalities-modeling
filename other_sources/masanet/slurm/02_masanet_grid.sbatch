#!/bin/bash
#SBATCH -J masanet_grid
#SBATCH -p sched_mit_sloan_batch
#SBATCH -N 1
#SBATCH -c 2
#SBATCH --mem=8G
#SBATCH -t 01:00:00
#SBATCH --chdir=/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet/logs/02_masanet_grid_%j.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet/logs/02_masanet_grid_%j.err

set -euo pipefail
export PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
unset PYTHONPATH PYTHONHOME
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet"
PY="/home/nacevedo/.conda/envs/masanet_lei/bin/python"
cd "${ROOT}"
export PYTHONPATH="${ROOT}/scripts"
echo "host=$(hostname) job=${SLURM_JOB_ID:-local} start=$(date -Is)"
GATE="${ROOT}/results/masanet_boundary_audit.json"
python_gate() {
  "${PY}" - << 'PY'
import json, sys
from pathlib import Path
p = Path("/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet/results/masanet_boundary_audit.json")
if not p.exists():
    print("missing boundary audit"); sys.exit(2)
d = json.loads(p.read_text())
if d.get("hard_gate") != "PROCEED":
    print("hard_gate", d.get("hard_gate"), d.get("status")); sys.exit(2)
print("hard_gate PROCEED")
PY
}
python_gate
"${PY}" scripts/run_masanet_grid.py
echo "end=$(date -Is)"
