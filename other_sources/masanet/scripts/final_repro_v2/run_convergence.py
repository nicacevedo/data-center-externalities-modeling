#!/usr/bin/env python3
"""Optional N=35/50/75/100 range-stability. Runs only if CONVERGENCE_REQUESTED.json exists."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from followup_common import lhs_facility_samples  # noqa: E402
from run_replication import _one_sample, ensure_frozen_instrumented, estimators, init_worker, load_weather  # noqa: E402
from v2_common import AN, MAN, set_threads, utcnow  # noqa: E402
from concurrent.futures import ProcessPoolExecutor, as_completed


def main():
    set_threads()
    flag = MAN / "CONVERGENCE_REQUESTED.json"
    if not flag.exists():
        print("no CONVERGENCE_REQUESTED.json; skip")
        return
    req = json.loads(flag.read_text())
    sizes = req.get("sample_sizes") or [35, 50, 75, 100]
    cells = req.get("cells") or []
    disp = json.loads((MAN / "CELL_DISPOSITION_BEFORE_V2.json").read_text())
    # map cell name -> case, zone
    meta = {}
    for k, v in disp["cells"].items():
        meta[k] = (v["paper_case"], v["climate_zone"])
    ensure_frozen_instrumented()
    init_worker()
    workers = int(os.environ.get("SLURM_CPUS_PER_TASK", "8"))
    rng = np.random.default_rng(20260903)
    out_cells = {}
    for cell in cells:
        case, zone = meta[cell]
        wx = load_weather(zone)
        n_hours = 8760
        T = wx["T_oa"].to_numpy(dtype=float)
        RH = wx["RH_oa"].to_numpy(dtype=float)
        P = wx["P_oa"].to_numpy(dtype=float)
        by_n = {}
        for n in sizes:
            lhs_seed = int(rng.integers(1, 2**31 - 1))
            facs = lhs_facility_samples(case, n, lhs_seed)
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
                        "internal_seed": int(rng.integers(1, 2**31 - 1)),
                    }
                )
            if workers == 1:
                recs = [_one_sample(p) for p in payloads]
            else:
                with ProcessPoolExecutor(max_workers=workers, initializer=init_worker) as ex:
                    recs = [fut.result() for fut in as_completed([ex.submit(_one_sample, p) for p in payloads])]
            est = estimators([r["annual_PUE"] for r in recs], [r["annual_WUE"] for r in recs])
            by_n[str(n)] = {"lhs_seed": lhs_seed, "estimators": est}
        out_cells[cell] = by_n
    atomic = {
        "timestamp_utc": utcnow(),
        "did_not_choose_N_to_match_UE": True,
        "cells": out_cells,
        "question": "Has the 5th/95th annual range estimator materially stabilized near the paper's N=50?",
    }
    (AN / "sample_size_convergence.json").write_text(json.dumps(atomic, indent=2) + "\n")
    print(json.dumps({"cells": list(out_cells), "sizes": sizes}, indent=2))


if __name__ == "__main__":
    main()
