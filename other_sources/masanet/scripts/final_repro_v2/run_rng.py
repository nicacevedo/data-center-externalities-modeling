#!/usr/bin/env python3
"""RNG variance components and same-LHS range reruns. Does not alter upstream."""
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

from followup_common import lhs_facility_samples  # noqa: E402
from rng_worker import rng_year_payload  # noqa: E402
from run_replication import _one_sample, ensure_frozen_instrumented, estimators, init_worker, load_weather  # noqa: E402
from v2_common import MAN, RES, set_threads, utcnow  # noqa: E402


def mode_variance(spec, workers, n_hours):
    case, zone = spec["paper_case"], spec["climate_zone"]
    facs = lhs_facility_samples(case, spec["n_facility_vectors"], spec["facility_lhs_seed"])
    seeds = spec["internal_seeds"]
    ensure_frozen_instrumented()
    t0 = time.time()
    payloads = []
    for i, fac in enumerate(facs):
        for s in seeds:
            payloads.append((case, zone, fac, n_hours, int(s), i))

    nw = max(1, workers)
    if nw == 1:
        init_worker()
        rows = [rng_year_payload(p) for p in payloads]
    else:
        with ProcessPoolExecutor(max_workers=nw, initializer=init_worker) as ex:
            rows = [fut.result() for fut in as_completed([ex.submit(rng_year_payload, p) for p in payloads])]
    df = pd.DataFrame(rows)
    outp = RES / "rng" / f"variance_{spec['cell']}.parquet"
    outp.parent.mkdir(parents=True, exist_ok=True)
    df.drop(columns=["water_mean_kg_s"], errors="ignore").to_parquet(outp, index=False)
    # nested ANOVA-style: facility vs residual (seed)
    def var_decomp(col):
        y = df.pivot_table(index="facility_id", columns="internal_seed", values=col)
        arr = y.to_numpy(dtype=float)
        n_fac, n_seed = arr.shape
        grand = float(arr.mean())
        fac_means = arr.mean(axis=1)
        ss_w = float(np.sum((arr - fac_means[:, None]) ** 2))
        ms_w = ss_w / (n_fac * (n_seed - 1))
        ss_b = float(n_seed * np.sum((fac_means - grand) ** 2))
        ms_b = ss_b / (n_fac - 1)
        sigma_rng = ms_w
        sigma_fac = max(0.0, (ms_b - ms_w) / n_seed)
        f = sigma_rng / (sigma_rng + sigma_fac) if (sigma_rng + sigma_fac) > 0 else 0.0
        # bootstrap over facilities
        rng = np.random.default_rng(0)
        boots = []
        for _ in range(2000):
            idx = rng.integers(0, n_fac, size=n_fac)
            a = arr[idx]
            fm = a.mean(axis=1)
            g = float(a.mean())
            ssw = float(np.sum((a - fm[:, None]) ** 2))
            msw = ssw / (n_fac * (n_seed - 1))
            ssb = float(n_seed * np.sum((fm - g) ** 2))
            msb = ssb / (n_fac - 1)
            sr = msw
            sf = max(0.0, (msb - msw) / n_seed)
            boots.append(sr / (sr + sf) if (sr + sf) > 0 else 0.0)
        return {
            "sigma2_facility": sigma_fac,
            "sigma2_rng": sigma_rng,
            "f_RNG": f,
            "f_RNG_boot_q025": float(np.quantile(boots, 0.025)),
            "f_RNG_boot_q975": float(np.quantile(boots, 0.975)),
            "grand_mean": grand,
            "method": "balanced nested ANOVA; bootstrap resamples facility vectors",
            "naive_var_of_facility_means": float(np.var(fac_means, ddof=1)),
        }

    summary = {
        "cell": spec["cell"],
        "elapsed_s": time.time() - t0,
        "n_hours": n_hours,
        "PUE": var_decomp("annual_PUE"),
        "WUE": var_decomp("annual_WUE"),
        "thresholds_are_project_rules_not_paper": True,
        "timestamp_utc": utcnow(),
        "parquet": str(outp),
    }
    (RES / "rng" / f"variance_{spec['cell']}.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


def mode_range(spec, workers, n_hours):
    case, zone = spec["paper_case"], spec["climate_zone"]
    lhs_seed = spec["range_rerun_lhs_seed"]
    facs = lhs_facility_samples(case, 50, lhs_seed)
    seeds = spec["internal_seeds"][: spec["range_rerun_n_internal_seeds"]]
    ensure_frozen_instrumented()
    wx = load_weather(zone)
    T = wx["T_oa"].to_numpy(dtype=float)[:n_hours]
    RH = wx["RH_oa"].to_numpy(dtype=float)[:n_hours]
    P = wx["P_oa"].to_numpy(dtype=float)[:n_hours]
    t0 = time.time()
    per_seed = []
    nw = max(1, workers)
    for s in seeds:
        payloads = []
        for i, fac in enumerate(facs):
            payloads.append(
                {
                    "paper_case": case,
                    "facility": fac,
                    "T": T,
                    "RH": RH,
                    "P": P,
                    "n_hours": n_hours,
                    "facility_sample_id": i,
                    "internal_seed": int(s) + i * 10007,
                }
            )
        if nw == 1:
            init_worker()
            recs = [_one_sample(p) for p in payloads]
        else:
            with ProcessPoolExecutor(max_workers=nw, initializer=init_worker) as ex:
                recs = [fut.result() for fut in as_completed([ex.submit(_one_sample, p) for p in payloads])]
        recs.sort(key=lambda r: r["facility_sample_id"])
        est = estimators([r["annual_PUE"] for r in recs], [r["annual_WUE"] for r in recs])
        per_seed.append({"internal_seed": int(s), "estimators": est})
    out = {
        "cell": spec["cell"],
        "frozen_lhs_seed": lhs_seed,
        "elapsed_s": time.time() - t0,
        "n_hours": n_hours,
        "per_internal_seed": per_seed,
        "timestamp_utc": utcnow(),
    }
    (RES / "rng" / f"range_rerun_{spec['cell']}.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps({"cell": spec["cell"], "n_seeds": len(per_seed), "elapsed_s": out["elapsed_s"]}, indent=2))


def main():
    set_threads()
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["variance", "range"], required=True)
    ap.add_argument("--cell", required=True)
    ap.add_argument("--workers", type=int, default=int(os.environ.get("SLURM_CPUS_PER_TASK", "1")))
    ap.add_argument("--n-hours", type=int, default=8760)
    args = ap.parse_args()
    man = json.loads((MAN / "RNG_TASK_MANIFEST.json").read_text())
    spec = next(c for c in man["cells"] if c["cell"] == args.cell)
    if args.mode == "variance":
        mode_variance(spec, args.workers, args.n_hours)
    else:
        if "range_rerun_lhs_seed" not in spec:
            raise SystemExit(f"no range rerun configured for {args.cell}")
        mode_range(spec, args.workers, args.n_hours)


if __name__ == "__main__":
    main()
