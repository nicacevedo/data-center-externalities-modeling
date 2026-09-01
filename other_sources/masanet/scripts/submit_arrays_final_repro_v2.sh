#!/bin/bash
# After preflights: collect, split frozen tasks, submit disjoint arrays + RNG + analyze.
set -euo pipefail
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet"
REPO="/home/nacevedo/RA/data-center-externalities-modeling"
PY="/home/nacevedo/.conda/envs/masanet_lei/bin/python"
SLURM="${ROOT}/slurm/final_repro_v2"
cd "${ROOT}"
export PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
export PYTHONPATH="${ROOT}/scripts:${ROOT}/scripts/final_repro_v2"

"${PY}" scripts/final_repro_v2/collect_preflight.py
"${PY}" scripts/final_repro_v2/split_tasks.py

TIME_SLOAN="16:00:00"
TIME_OU="20:00:00"
TIME_MIT="12:00:00"

split_n () {
  local part="$1"
  "${PY}" -c "import json; m=json.load(open('${ROOT}/manifests/final_repro_v2/TASK_SPLIT.json')); print(len(m.get('${part}', [])))"
}

ARRAY_IDS=()
submit_array () {
  local part="$1"
  local tlim="$2"
  local n
  n="$(split_n "${part}")"
  if [[ "${n}" -lt 1 ]]; then
    echo "skip empty ${part}"
    return 0
  fi
  local last=$((n - 1))
  local jid
  jid="$(sbatch --parsable -p "${part}" -t "${tlim}" --array="0-${last}%40" "${SLURM}/02_replication.sbatch")"
  echo "ARRAY ${part} ${jid} tasks 0-${last}"
  ARRAY_IDS+=("${jid}")
}

submit_array sched_mit_sloan_batch "${TIME_SLOAN}" || true
submit_array sched_mit_sloan_batch_r8 "${TIME_SLOAN}" || true
submit_array ou_sloan_batch "${TIME_OU}" || true
submit_array mit_normal "${TIME_MIT}" || true

if [[ ${#ARRAY_IDS[@]} -eq 0 ]]; then
  echo "ERROR: no arrays submitted"
  exit 2
fi

DEP="$(IFS=:; echo "${ARRAY_IDS[*]}")"

RNG1="$(sbatch --parsable --export=ALL,V2_RNG_MODE=variance,V2_RNG_CELL=case5_2A "${SLURM}/03_rng.sbatch")"
RNG2="$(sbatch --parsable --export=ALL,V2_RNG_MODE=variance,V2_RNG_CELL=case1_1A "${SLURM}/03_rng.sbatch")"
RNG3="$(sbatch --parsable --export=ALL,V2_RNG_MODE=range,V2_RNG_CELL=case5_2A "${SLURM}/03_rng.sbatch")"
echo "RNG ${RNG1} ${RNG2} ${RNG3}"

AN="$(sbatch --parsable --depend="afterok:${DEP}:${RNG1}:${RNG2}:${RNG3}" "${SLURM}/04_analyze.sbatch")"
echo "ANALYZE ${AN}"
CV="$(sbatch --parsable --depend="afterok:${AN}" "${SLURM}/05_convergence.sbatch")"
echo "CONV ${CV}"
PRV="$(sbatch --parsable --depend="afterok:${CV}" "${SLURM}/06_prineville.sbatch")"
echo "PRINEVILLE ${PRV}"

NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
HEAD="$(git -C "${REPO}" rev-parse HEAD 2>/dev/null || echo UNKNOWN)"
"${PY}" - << PY
import json
from pathlib import Path
p = Path("${ROOT}/manifests/final_repro_v2/SLURM_FINAL_REPRO_V2.json")
old = json.loads(p.read_text()) if p.exists() else {}
old.update({
    "arrays_submitted_utc": "${NOW}",
    "git_head": "${HEAD}",
    "phase": "arrays_submitted",
    "array_job_ids": """${ARRAY_IDS[*]}""".split(),
    "job_ids": {
        **old.get("job_ids", {}),
        "ARRAYS": """${ARRAY_IDS[*]}""".split(),
        "RNG_var_case5": "${RNG1}",
        "RNG_var_case1": "${RNG2}",
        "RNG_range_case5": "${RNG3}",
        "ANALYZE": "${AN}",
        "CONVERGENCE": "${CV}",
        "PRINEVILLE": "${PRV}",
    },
})
flat = []
def walk(x):
    if isinstance(x, dict):
        for v in x.values():
            walk(v)
    elif isinstance(x, list):
        for v in x:
            walk(v)
    elif x not in (None, "", "SUBMIT_FAIL"):
        flat.append(str(x))
walk(old.get("job_ids"))
old["all_job_ids"] = flat
p.write_text(json.dumps(old, indent=2) + "\n")
print("UPDATED", p)
PY

echo "=== squeue ==="
squeue -u "${USER}" -o '%.18i %.12P %.22j %.8T %.10M %.12E %R' | head -40
