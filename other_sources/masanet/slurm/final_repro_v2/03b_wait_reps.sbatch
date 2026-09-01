#!/bin/bash
#SBATCH -J v2_wait
#SBATCH -p sched_mit_sloan_batch
#SBATCH -N 1
#SBATCH -c 1
#SBATCH --mem=2G
#SBATCH -t 01:00:00
#SBATCH --chdir=/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet/logs/final_repro_v2/wait_%j.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet/logs/final_repro_v2/wait_%j.err

set -euo pipefail
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet"
PY="/home/nacevedo/.conda/envs/masanet_lei/bin/python"
export PYTHONNOUSERSITE=1 PYTHONUNBUFFERED=1
export PYTHONPATH="${ROOT}/scripts:${ROOT}/scripts/final_repro_v2"
"${PY}" - << 'PY'
import json, sys, time
from pathlib import Path
man = json.loads(Path("/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet/manifests/final_repro_v2/TASK_MANIFEST.json").read_text())
reps = Path("/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet/results/final_repro_v2/reps")
need = [t["task_id"] for t in man["tasks"]]
missing = []
for tid in need:
    p = reps / f"rep_{tid:04d}.json"
    ok = False
    if p.exists():
        try:
            d = json.loads(p.read_text())
            ok = d.get("n_hours") == 8760 and d.get("finite_all") is True
        except Exception:
            ok = False
    if not ok:
        missing.append(tid)
print("n_ok", len(need) - len(missing), "n_missing", len(missing))
if missing:
    print("missing_task_ids", missing[:50], "..." if len(missing) > 50 else "")
    Path("/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet/manifests/final_repro_v2/MISSING_TASKS.json").write_text(
        json.dumps({"missing": missing, "n": len(missing)}, indent=2) + "\n"
    )
    sys.exit(2)
print("all 160 publication-scale replications present")
PY
