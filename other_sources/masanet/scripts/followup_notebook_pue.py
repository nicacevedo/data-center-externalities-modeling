#!/usr/bin/env python3
"""Phase 1A: can ordinary np.random seeds reproduce the stored notebook PUE?"""
from __future__ import annotations

import json
import sys

import numpy as np

from common import DEMO_VECTOR, load_upstream, set_threads, utcnow
from followup_common import FOLLOWUP
from common import atomic_write_json

NOTEBOOK_PUE = 1.339160993824991
NOTEBOOK_WUE = 2.417390377483526
N_SEEDS = 10000
TOL = 1e-8


def main():
    set_threads()
    FOLLOWUP.mkdir(parents=True, exist_ok=True)
    mod, notes = load_upstream()
    fn = mod.PUE_WUE_WE_Chiller_Colo
    pues = np.empty(N_SEEDS)
    wues = np.empty(N_SEEDS)
    hit = None
    for s in range(N_SEEDS):
        np.random.seed(s)
        pue, wue = fn(DEMO_VECTOR)
        pues[s] = float(pue)
        wues[s] = float(wue)
        if abs(pue - NOTEBOOK_PUE) <= TOL:
            hit = s
            # continue to finish the cheap sweep for distribution
    q = np.quantile(pues, [0, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 1.0])
    # simple regime split around 1.40
    n_low = int((pues < 1.40).sum())
    n_high = int((pues >= 1.40).sum())
    if hit is not None or (pues.min() <= NOTEBOOK_PUE <= pues.max()):
        status = "RNG_EXPLAINS_NOTEBOOK"
    else:
        status = "NOTEBOOK_VALUE_NOT_REACHED"
    nb_meta = None
    if status == "NOTEBOOK_VALUE_NOT_REACHED":
        import json as _json
        from pathlib import Path as _P
        from common import UPSTREAM as _U

        nb = _json.loads((_U / "demo.ipynb").read_text())
        nb_meta = {
            "kernelspec": nb.get("metadata", {}).get("kernelspec"),
            "language_info_version": nb.get("metadata", {}).get("language_info", {}).get("version"),
            "cell_execution_counts": [c.get("execution_count") for c in nb.get("cells", [])],
            "n_code_cells": sum(1 for c in nb.get("cells", []) if c.get("cell_type") == "code"),
            "note": (
                "Import cell execution_count is null while the PUE print cell still stores "
                "(1.33916, 2.41739). Stored output is from a prior kernel (metadata Python 3.9.12 base), "
                "not a seeded rerun under the pinned upstream commit."
            ),
        }
    out = {
        "status": status,
        "timestamp_utc": utcnow(),
        "n_seeds": N_SEEDS,
        "seed_range": [0, N_SEEDS - 1],
        "notebook_pue": NOTEBOOK_PUE,
        "notebook_wue": NOTEBOOK_WUE,
        "hit_seed": hit,
        "PUE": {
            "min": float(pues.min()),
            "max": float(pues.max()),
            "mean": float(pues.mean()),
            "quantiles": {k: float(v) for k, v in zip(["0","1","5","25","50","75","95","99","100"], q)},
            "n_below_1.40": n_low,
            "n_atleast_1.40": n_high,
            "abs_notebook_minus_min": float(abs(NOTEBOOK_PUE - pues.min())),
            "abs_notebook_minus_median": float(abs(NOTEBOOK_PUE - np.median(pues))),
        },
        "WUE": {
            "min": float(wues.min()),
            "max": float(wues.max()),
            "unique_rounded_12": int(len(np.unique(np.round(wues, 12)))),
        },
        "cop_notes": notes,
        "notebook_metadata_brief": nb_meta,
        "interpretation": (
            "If status is NOTEBOOK_VALUE_NOT_REACHED, stored demo.ipynb PUE is treated as "
            "stale/non-reproducible under pinned commit 2cc53bee; WUE already matched seed 2025."
        ),
    }
    atomic_write_json(FOLLOWUP / "notebook_pue_sweep.json", out)
    print(json.dumps({"status": status, "pue_min": out["PUE"]["min"], "pue_max": out["PUE"]["max"], "hit": hit}, indent=2))
    if status == "UNRESOLVED":
        sys.exit(2)


if __name__ == "__main__":
    main()
