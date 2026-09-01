#!/usr/bin/env python3
"""One publication-scale replication: 50 LHS × 8760 hours. Unique output file."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import ARCHETYPE_PARAMS, POWER_LABELS, UPSTREAM_COMMIT  # noqa: E402
from followup_common import (  # noqa: E402
    CANONICAL_WATER_KEYS,
    CLIMATE_CITIES,
    PAPER_CASES,
    case_vector,
    lhs_facility_samples,
    map_water_components,
)
from instrument_upstream import load_instrumented, write_instrumented  # noqa: E402
from v2_common import ENV_ID, MAN, REPS, RES, set_threads, sha256_file, utcnow  # noqa: E402

_WORKER = {}
FROZEN_INSTR = RES / "instrumented" / "simulation_funs_DC_instrumented.py"


def ensure_frozen_instrumented():
    """Copy the diagnostic instrumented module once. Never rewrite during parallel jobs."""
    FROZEN_INSTR.parent.mkdir(parents=True, exist_ok=True)
    if FROZEN_INSTR.exists() and "def PUE_WUE_Chiller_Watereconomier" in FROZEN_INSTR.read_text():
        return FROZEN_INSTR
    src = write_instrumented()
    FROZEN_INSTR.write_text(src.read_text())
    return FROZEN_INSTR


def init_worker():
    set_threads()
    _WORKER["inst"] = load_instrumented(1.0, rewrite=False, path=FROZEN_INSTR)


def _one_sample(payload):
    inst = _WORKER["inst"]
    case = payload["paper_case"]
    fn_name = PAPER_CASES[case]["top_level_code_function"]
    fn = getattr(inst, fn_name)
    facility = payload["facility"]
    T, RH, P = payload["T"], payload["RH"], payload["P"]
    n_hours = payload["n_hours"]
    np.random.seed(int(payload["internal_seed"]))
    names = ARCHETYPE_PARAMS[fn_name]
    iT, iRH, iP = names.index("T_oa"), names.index("RH_oa"), names.index("P_oa")
    x0 = case_vector(case, {"T_oa": float(T[0]), "RH_oa": float(RH[0]), "P_oa": float(P[0])}, facility)
    pues = np.empty(n_hours)
    wues = np.empty(n_hours)
    wmean = {k: 0.0 for k in CANONICAL_WATER_KEYS}
    p_labels = POWER_LABELS[fn_name]
    pmean = {lab: 0.0 for lab in p_labels}
    for t in range(n_hours):
        x = list(x0)
        x[iT] = float(T[t])
        x[iRH] = float(RH[t])
        x[iP] = float(P[t])
        pue, wue = fn(x)
        pues[t] = float(pue)
        wues[t] = float(wue)
        rec = inst._LAST
        wmap = map_water_components(fn_name, rec.get("Water_comp") or [])
        for k, v in wmap.items():
            wmean[k] += v
        pc = rec.get("Power_comp") or []
        for lab, val in zip(p_labels, pc):
            pmean[lab] += float(val)
    n = float(n_hours)
    return {
        "facility_sample_id": payload["facility_sample_id"],
        "annual_PUE": float(np.mean(pues)),
        "annual_WUE": float(np.mean(wues)),
        "finite": bool(np.isfinite(pues).all() and np.isfinite(wues).all()),
        "water_mean_kg_s": {k: wmean[k] / n for k in CANONICAL_WATER_KEYS},
        "power_mean": {k: pmean[k] / n for k in p_labels},
        "facility": facility,
        "internal_seed": int(payload["internal_seed"]),
    }


def estimators(pues, wues):
    pues = np.asarray(pues, dtype=float)
    wues = np.asarray(wues, dtype=float)
    return {
        "PUE_lower_5th": float(np.quantile(pues, 0.05)),
        "PUE_upper_95th": float(np.quantile(pues, 0.95)),
        "WUE_lower_5th": float(np.quantile(wues, 0.05)),
        "WUE_upper_95th": float(np.quantile(wues, 0.95)),
        "PUE_min": float(np.min(pues)),
        "PUE_max": float(np.max(pues)),
        "WUE_min": float(np.min(wues)),
        "WUE_max": float(np.max(wues)),
        "quantile_interpolation": "numpy linear default; not min/max",
    }


def load_weather(zone):
    p = Path("/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet/results/followup_v1") / f"weather_{zone}.parquet"
    df = pd.read_parquet(p)
    if len(df) != 8760:
        raise ValueError(f"{zone} has {len(df)} rows")
    return df


def run_task(task, workers):
    set_threads()
    case, zone = task["paper_case"], task["climate_zone"]
    wx = load_weather(zone)
    n_hours = int(task["n_hours"])
    T = wx["T_oa"].to_numpy(dtype=float)[:n_hours]
    RH = wx["RH_oa"].to_numpy(dtype=float)[:n_hours]
    P = wx["P_oa"].to_numpy(dtype=float)[:n_hours]
    samples = lhs_facility_samples(case, int(task["n_lhs"]), int(task["lhs_seed"]))
    seeds = task.get("facility_internal_seeds")
    if not seeds:
        seeds = [int(task["internal_stream_seed"]) + i * 10007 for i in range(len(samples))]
    ensure_frozen_instrumented()
    payloads = []
    for i, fac in enumerate(samples):
        payloads.append(
            {
                "paper_case": case,
                "facility": fac,
                "T": T,
                "RH": RH,
                "P": P,
                "n_hours": n_hours,
                "facility_sample_id": i,
                "internal_seed": int(seeds[i]),
            }
        )
    t0 = time.time()
    nw = max(1, min(workers, len(payloads)))
    recs = []
    if nw == 1:
        init_worker()
        recs = [_one_sample(p) for p in payloads]
    else:
        with ProcessPoolExecutor(max_workers=nw, initializer=init_worker) as ex:
            recs = [fut.result() for fut in as_completed([ex.submit(_one_sample, p) for p in payloads])]
    recs.sort(key=lambda r: r["facility_sample_id"])
    elapsed = time.time() - t0
    pues = [r["annual_PUE"] for r in recs]
    wues = [r["annual_WUE"] for r in recs]
    wx_path = Path(
        "/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet/external/energyplus_tmy"
    )
    # map zone file
    epw = wx_path / f"{zone}_{CLIMATE_CITIES[zone]['epw_id']}.epw"
    dest = REPS / f"rep_{task['task_id']:04d}.json"
    out = {
        "task_id": task["task_id"],
        "cell": task["cell"],
        "paper_case": case,
        "climate_zone": zone,
        "replication": task["replication"],
        "role": task["role"],
        "lhs_seed": task["lhs_seed"],
        "internal_stream_seed": task["internal_stream_seed"],
        "facility_internal_seeds": [r["internal_seed"] for r in recs],
        "n_lhs": task["n_lhs"],
        "n_hours": n_hours,
        "elapsed_s": elapsed,
        "workers": nw,
        "hostname": os.environ.get("SLURMD_NODENAME") or os.environ.get("HOSTNAME"),
        "partition": os.environ.get("SLURM_JOB_PARTITION"),
        "job_id": os.environ.get("SLURM_JOB_ID"),
        "finite_all": all(r["finite"] for r in recs),
        "estimators": estimators(pues, wues),
        "annual_PUE": pues,
        "annual_WUE": wues,
        "facility_vectors": [r["facility"] for r in recs],
        "water_mean_kg_s": [r["water_mean_kg_s"] for r in recs],
        "power_mean": [r["power_mean"] for r in recs],
        "upstream_commit": UPSTREAM_COMMIT,
        "environment_id": ENV_ID,
        "weather_sha256": sha256_file(epw),
        "source_sha256": sha256_file(
            Path("/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet/external/Data-Center-Water-footprint/simulation_funs_DC.py")
        ),
        "warnings": [],
        "timestamp_utc": utcnow(),
    }
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, default=str) + "\n")
    tmp.replace(dest)
    return dest, out["estimators"], elapsed


def main():
    set_threads()
    REPS.mkdir(parents=True, exist_ok=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id", type=int, required=True)
    ap.add_argument("--workers", type=int, default=int(os.environ.get("SLURM_CPUS_PER_TASK", "1")))
    ap.add_argument("--n-hours", type=int, default=0, help="override hours for smoke/benchmark")
    args = ap.parse_args()
    man = json.loads((MAN / "TASK_MANIFEST.json").read_text())
    task = next(t for t in man["tasks"] if t["task_id"] == args.task_id)
    if args.n_hours:
        task = dict(task)
        task["n_hours"] = args.n_hours
    dest, est, elapsed = run_task(task, args.workers)
    print(json.dumps({"task_id": args.task_id, "path": str(dest), "elapsed_s": elapsed, "estimators": est}, indent=2))


if __name__ == "__main__":
    main()
