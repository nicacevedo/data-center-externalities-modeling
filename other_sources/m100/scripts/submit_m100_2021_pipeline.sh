#!/bin/bash
# Submit the rolling 2021 M100 DAG. Safe to re-run: skips existing jobs/products.
set -euo pipefail
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100"
PY="/home/nacevedo/.conda/envs/dc_externalities/bin/python"
cd "${ROOT}"
export PYTHONPATH="${ROOT}/scripts"
mkdir -p logs/slurm manifests results/2021_status

echo "=== sinfo (abbrev) ==="
sinfo -s | head -20
echo "=== squeue user ==="
squeue -u "${USER}"

"${PY}" scripts/catalog_m100_2021.py
"${PY}" scripts/qualify_m100_2021.py || true

python3 - << 'PY'
import json, os, subprocess, time
from pathlib import Path
import pandas as pd

ROOT = Path("/home/nacevedo/RA/data-center-externalities-modeling/other_sources/m100")
os.chdir(ROOT)
os.environ["PYTHONPATH"] = str(ROOT / "scripts")
from m100_2021_common import EXPECTED_MONTHS, SCHEMA_VERSION, archive_path, grain_parquet, load_status, ZENODO

def sbatch(script, env=None, depend=None, extra=None):
    cmd = ["sbatch", "--parsable"]
    if depend:
        cmd += [f"--depend={depend}"]
    if extra:
        cmd += extra
    if env:
        export = ",".join(f"{k}={v}" for k, v in env.items())
        cmd += [f"--export=ALL,{export}"]
    cmd.append(str(ROOT / "scripts" / script))
    print("SUBMIT", " ".join(cmd), flush=True)
    out = subprocess.check_output(cmd, text=True).strip()
    jid = out.split(";")[0].strip()
    print("  ->", jid, flush=True)
    return jid

cat = pd.read_csv(ROOT / "data/catalog/m100_2021_archives.csv")
status = dict(zip(cat.month, cat.status))
jobs = {"download": {}, "process": {}, "qc": {}, "cleanup": {}, "notes": []}
qc_ids = []
prev_download = None
n_proc_active = 0
last_two_proc = []

# process at most 2 concurrently by chaining every 3rd process on earlier process afterok? 
# Simpler: chain process jobs in pairs via aftercorr-like: P[i] depends afterok:P[i-2]
proc_chain = []

for month in EXPECTED_MONTHS:
    st = load_status(month)
    tar = archive_path(month)
    official = ZENODO[month]["size"]
    complete = tar.exists() and tar.stat().st_size == official
    missing = not tar.exists()
    incomplete = tar.exists() and tar.stat().st_size != official

    dl = None
    if incomplete or missing:
        extra = []
        if prev_download:
            extra_dep = f"afterok:{prev_download}"
        else:
            extra_dep = None
        dl = sbatch("run_m100_download.sbatch", env={"MONTH": month}, depend=extra_dep)
        jobs["download"][month] = dl
        prev_download = dl

    # skip process if v2 facility or no-facility already certified PASS
    fac = grain_parquet("facility", month)
    already_v2 = fac.exists() and (fac.with_suffix(".schema.json").exists())
    if already_v2 and st.get("schema_version") == SCHEMA_VERSION and st.get("certification") == "PASS":
        jobs["notes"].append(f"{month} already certified v2; skip process")
        continue

    proc_dep = None
    deps = []
    if dl:
        deps.append(f"afterok:{dl}")
    if len(proc_chain) >= 2:
        deps.append(f"afterok:{proc_chain[-2]}")
    if deps:
        # afterok of download AND throttle predecessor: Slurm allows one --depend
        # combine with afterok:id1?id2 (all must succeed) 
        proc_dep = "afterok:" + ":".join(d.split(":", 1)[1] for d in deps)

    proc = sbatch("run_m100_process.sbatch", env={"MONTH": month}, depend=proc_dep)
    jobs["process"][month] = proc
    proc_chain.append(proc)

    qc = sbatch("run_m100_qc.sbatch", env={"MONTH": month}, depend=f"afterok:{proc}")
    jobs["qc"][month] = qc
    qc_ids.append(qc)

    cln = sbatch("run_m100_cleanup.sbatch", env={"MONTH": month}, depend=f"afterok:{qc}")
    jobs["cleanup"][month] = cln

if qc_ids:
    final_dep = "afterany:" + ":".join(qc_ids)
else:
    final_dep = None
final = sbatch("run_m100_final.sbatch", depend=final_dep)
jobs["final"] = final
audit = sbatch("run_m100_storage_audit.sbatch", depend=f"afterok:{final}")
jobs["storage_audit"] = audit
jobs["submitted_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
out = ROOT / "manifests" / "pipeline_jobs.json"
out.write_text(json.dumps(jobs, indent=2) + "\n")
print("WROTE", out)
print(json.dumps(jobs, indent=2))
PY
echo "=== squeue after submit ==="
squeue -u "${USER}"
