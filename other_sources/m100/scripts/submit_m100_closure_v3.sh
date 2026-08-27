#!/bin/bash
# Submit M100 v3 closure DAG. Safe to disconnect after successful submission.
set -euo pipefail
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100"
REPO="/home/nacevedo/RA/data-center-externalities-modeling"
PY="/home/nacevedo/.conda/envs/dc_externalities/bin/python"
cd "${ROOT}"
mkdir -p logs/slurm manifests results/suitability_2021_v3_closure
export PYTHONPATH="${ROOT}/scripts"

HEAD="$(git -C "${REPO}" rev-parse HEAD)"
echo "git HEAD=${HEAD}"
echo "=== sinfo ==="
sinfo -s | head -20
echo "=== squeue user ==="
squeue -u "${USER}" -o '%.18i %.9P %.20j %.8T %.10M %R' | head -20

# Hash scripts at submission
HASH_V3="$("${PY}" - << 'PY'
import hashlib
from pathlib import Path
p=Path("/home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/scripts/analyze_m100_suitability_v3.py")
print(hashlib.sha256(p.read_bytes()).hexdigest())
PY
)"
HASH_LIB="$("${PY}" - << 'PY'
import hashlib
from pathlib import Path
p=Path("/home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100/scripts/m100_suitability_v3.py")
print(hashlib.sha256(p.read_bytes()).hexdigest())
PY
)"

# Best-effort pin of literature repo (network). Failure is optional.
VENDOR="/orcd/pool/005/nacevedo/m100/vendor/dc-cooling-thermal-model"
mkdir -p /orcd/pool/005/nacevedo/m100/vendor
if [[ ! -d "${VENDOR}/.git" ]]; then
  git clone --depth 1 https://github.com/cletuzz00/dc-cooling-thermal-model "${VENDOR}" || echo "WARN: literature clone failed at submit; job will retry"
fi
if [[ -d "${VENDOR}/.git" ]]; then
  git -C "${VENDOR}" rev-parse HEAD || true
fi

sbatch_stage () {
  local name="$1" stage="$2" cpus="$3" mem="$4" time="$5" depend="$6"
  local extra=(--job-name="${name}" -c "${cpus}" --mem="${mem}" -t "${time}" --export=ALL,STAGE="${stage}")
  if [[ -n "${depend}" ]]; then
    extra+=(--depend="${depend}")
  fi
  sbatch --parsable "${extra[@]}" "${ROOT}/scripts/run_m100_closure_v3.sbatch"
}

PREP="$(sbatch_stage m100_v3_prep prep 2 8G 00:30:00 "")"
echo "PREP ${PREP}"

STATIC="$(sbatch_stage m100_v3_static static 4 16G 01:00:00 "afterok:${PREP}")"
WITHIN="$(sbatch_stage m100_v3_within within_month 4 8G 01:00:00 "afterok:${PREP}")"
THERM="$(sbatch_stage m100_v3_thermal thermal 4 16G 01:00:00 "afterok:${PREP}")"
DYN="$(sbatch_stage m100_v3_dyn dynamic 4 16G 02:00:00 "afterok:${PREP}")"
LIT="$(sbatch_stage m100_v3_lit literature 4 16G 04:00:00 "afterok:${PREP}")"
SUPP="$(sbatch_stage m100_v3_supp support 2 8G 01:00:00 "afterok:${PREP}")"

NODE="$(sbatch --parsable --depend="afterok:${PREP}" "${ROOT}/scripts/run_m100_closure_v3_node.sbatch")"
echo "NODE_ARRAY ${NODE}"

# afterany so a report is produced even if one branch fails
AGG="$(sbatch_stage m100_v3_agg aggregate 2 8G 01:00:00 "afterany:${STATIC}:${WITHIN}:${THERM}:${DYN}:${LIT}:${SUPP}:${NODE}")"
AUD="$(sbatch_stage m100_v3_aud audit 1 4G 00:30:00 "afterany:${AGG}")"

NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
"${PY}" - << PY
import json, hashlib
from pathlib import Path
from datetime import datetime, timezone
root = Path("${ROOT}")
jobs = {
  "created_utc": "${NOW}",
  "git_head": "${HEAD}",
  "script_sha256": {
    "analyze_m100_suitability_v3.py": "${HASH_V3}",
    "m100_suitability_v3.py": "${HASH_LIB}",
  },
  "partition_default": "sched_mit_sloan_batch_r8",
  "reason": "rocky8 Sloan r8 matches the established 2021 DAG; CPU-only; no GPU",
  "dependency_dag": "PREP(afterok) -> {static, within_month, node_array, thermal, dynamic, literature, support} -> AGG(afterany) -> AUDIT(afterany)",
  "jobs": {
    "prep": {"id": "${PREP}", "name": "m100_v3_prep", "role": "test gate", "partition": "sched_mit_sloan_batch_r8", "cpus": 2, "mem": "8G", "time": "00:30:00", "depend": None},
    "static": {"id": "${STATIC}", "name": "m100_v3_static", "role": "weather/state/HQ/energy/wetbulb/R1/cooling", "partition": "sched_mit_sloan_batch_r8", "cpus": 4, "mem": "16G", "time": "01:00:00", "depend": "afterok:${PREP}"},
    "within_month": {"id": "${WITHIN}", "name": "m100_v3_within", "role": "within-month weather", "partition": "sched_mit_sloan_batch_r8", "cpus": 4, "mem": "8G", "time": "01:00:00", "depend": "afterok:${PREP}"},
    "node_array": {"id": "${NODE}", "name": "m100_v3_node", "role": "node-to-ICT array 1-11%3", "partition": "sched_mit_sloan_batch_r8", "cpus": 8, "mem": "32G", "time": "02:00:00", "depend": "afterok:${PREP}"},
    "thermal": {"id": "${THERM}", "name": "m100_v3_thermal", "role": "Q101/Q102 / HTI audit", "partition": "sched_mit_sloan_batch_r8", "cpus": 4, "mem": "16G", "time": "01:00:00", "depend": "afterok:${PREP}"},
    "dynamic": {"id": "${DYN}", "name": "m100_v3_dyn", "role": "D1 one-step vs recursive", "partition": "sched_mit_sloan_batch_r8", "cpus": 4, "mem": "16G", "time": "02:00:00", "depend": "afterok:${PREP}"},
    "literature": {"id": "${LIT}", "name": "m100_v3_lit", "role": "optional same-data RC reproduction", "partition": "sched_mit_sloan_batch_r8", "cpus": 4, "mem": "16G", "time": "04:00:00", "depend": "afterok:${PREP}"},
    "support": {"id": "${SUPP}", "name": "m100_v3_supp", "role": "interpolation/extrapolation", "partition": "sched_mit_sloan_batch_r8", "cpus": 2, "mem": "8G", "time": "01:00:00", "depend": "afterok:${PREP}"},
    "aggregate": {"id": "${AGG}", "name": "m100_v3_agg", "role": "final report/contract", "partition": "sched_mit_sloan_batch_r8", "cpus": 2, "mem": "8G", "time": "01:00:00", "depend": "afterany:branches"},
    "audit": {"id": "${AUD}", "name": "m100_v3_aud", "role": "output/hash/no-deletion audit", "partition": "sched_mit_sloan_batch_r8", "cpus": 1, "mem": "4G", "time": "00:30:00", "depend": "afterany:${AGG}"},
  },
  "output_dir": str(root / "results" / "suitability_2021_v3_closure"),
  "does_not_overwrite": ["results/pilot_facility_2021", "results/suitability_2021", "results/suitability_2021_v2"],
  "no_raw_deletion": True,
}
(root / "manifests" / "m100_closure_v3_jobs.json").write_text(json.dumps(jobs, indent=2) + "\n")
(root / "results" / "suitability_2021_v3_closure" / "run_manifest.json").write_text(json.dumps(jobs, indent=2) + "\n")
print("wrote manifests/m100_closure_v3_jobs.json")
PY

echo "=== submitted ==="
squeue -u "${USER}" -o '%.18i %.9P %.20j %.8T %.10M %R'
echo "SAFE_TO_DISCONNECT_AFTER_THIS_SCRIPT_EXITS_ZERO"
