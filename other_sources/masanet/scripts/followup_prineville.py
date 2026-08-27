#!/usr/bin/env python3
"""Phase 9: Prineville-weather-only smoke for paper cases 1 and 2. Not a fit. No Meta water."""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import pandas as pd

from common import UPSTREAM_COMMIT, atomic_write_json, set_threads, utcnow
from facility_adapter import energy_weighted_annual, paper_mean_intensity
from followup_annual import _simulate_sample_payload, init_worker, n_workers
from followup_common import (
    CANONICAL_WATER_KEYS,
    ENVIRONMENT_ID,
    FOLLOWUP,
    canonical_prineville_weather_path,
    cell_lhs_seed,
    internal_stream_seed,
    lhs_facility_samples,
)
from instrument_upstream import write_instrumented

PRINEVILLE_CASES = [1, 2]
YEAR = 2022
N_SAMPLES = 50
WEATHER_USECOLS = [
    "timestamp_local",
    "year_local",
    "t_db_C",
    "rh_pct",
    "pressure_Pa",
]


def load_prineville_2022() -> pd.DataFrame:
    path = canonical_prineville_weather_path()
    if not path.exists():
        raise FileNotFoundError(f"canonical Prineville weather missing: {path}")
    df = pd.read_csv(path, usecols=WEATHER_USECOLS)
    out = df[df["year_local"] == YEAR].copy()
    out = out.sort_values("timestamp_local").reset_index(drop=True)
    if len(out) != 8760:
        raise ValueError(f"expected 8760 hours for {YEAR}, got {len(out)}")
    for c in ("t_db_C", "rh_pct", "pressure_Pa"):
        if out[c].isna().any():
            raise ValueError(f"non-finite weather in {c}; not interpolating")
    return out


def run_case(case: int, wx: pd.DataFrame, workers: int) -> dict:
    T = wx["t_db_C"].to_numpy(dtype=float)
    RH = wx["rh_pct"].to_numpy(dtype=float)
    P = wx["pressure_Pa"].to_numpy(dtype=float)
    lhs_seed = 202200 + case
    samples = lhs_facility_samples(case, N_SAMPLES, lhs_seed)
    payloads = []
    for i, fac in enumerate(samples):
        payloads.append(
            {
                "paper_case": case,
                "facility": fac,
                "T": T,
                "RH": RH,
                "P": P,
                "n_hours": 8760,
                "facility_sample_id": i,
                "lhs_seed": lhs_seed,
                "internal_seed": internal_stream_seed(lhs_seed, i, 0),
                "replicate": 0,
                "store_hourly": True,
            }
        )
    t0 = time.time()
    nw = min(workers, N_SAMPLES)
    recs = []
    if nw == 1:
        init_worker()
        recs = [_simulate_sample_payload(p) for p in payloads]
    else:
        with ProcessPoolExecutor(max_workers=nw, initializer=init_worker) as ex:
            recs = [fut.result() for fut in as_completed([ex.submit(_simulate_sample_payload, p) for p in payloads])]
    recs.sort(key=lambda r: r["facility_sample_id"])
    elapsed = time.time() - t0
    months = pd.to_datetime(wx["timestamp_local"]).dt.month.to_numpy()
    annual_rows = []
    monthly_rows = []
    hourly_frames = []
    for rec, fac in zip(recs, samples):
        annual_rows.append(
            {
                "paper_case": case,
                "weather_year_local": YEAR,
                "weather_path": str(canonical_prineville_weather_path()),
                "lhs_seed": rec["lhs_seed"],
                "facility_sample_id": rec["facility_sample_id"],
                "annual_PUE_paper_mean": rec["annual_PUE_paper_mean"],
                "annual_WUE_paper_mean": rec["annual_WUE_paper_mean"],
                "P_IT": 1.0,
                "upstream_commit": UPSTREAM_COMMIT,
                "environment_id": ENVIRONMENT_ID,
                **{f"Wmean_{k}_kg_s": rec["water_annual_mean_kg_s"][k] for k in CANONICAL_WATER_KEYS},
            }
        )
        h = rec["hourly"]
        pue = np.asarray(h["PUE"])
        wue = np.asarray(h["WUE"])
        for m in range(1, 13):
            mask = months == m
            monthly_rows.append(
                {
                    "paper_case": case,
                    "month": m,
                    "facility_sample_id": rec["facility_sample_id"],
                    "PUE_paper_mean": float(np.mean(pue[mask])),
                    "WUE_paper_mean": float(np.mean(wue[mask])),
                    "n_hours": int(mask.sum()),
                }
            )
        hdf = pd.DataFrame(
            {
                "paper_case": case,
                "facility_sample_id": rec["facility_sample_id"],
                "hour": np.arange(8760),
                "timestamp_local": wx["timestamp_local"].to_numpy(),
                "T_oa": T,
                "RH_oa": RH,
                "P_oa": P,
                "PUE": pue,
                "WUE": wue,
            }
        )
        for k in CANONICAL_WATER_KEYS:
            hdf[f"W_{k}_kg_s"] = h["water"][k]
        hourly_frames.append(hdf)
        del rec["hourly"]
    tag = f"prineville_{YEAR}_case{case}"
    pd.DataFrame(annual_rows).to_parquet(FOLLOWUP / f"{tag}_annual.parquet", index=False)
    pd.DataFrame(monthly_rows).to_parquet(FOLLOWUP / f"{tag}_monthly.parquet", index=False)
    pd.concat(hourly_frames, ignore_index=True).to_parquet(FOLLOWUP / f"{tag}_hourly.parquet", index=False)
    pues = np.array([r["annual_PUE_paper_mean"] for r in recs])
    wues = np.array([r["annual_WUE_paper_mean"] for r in recs])
    return {
        "paper_case": case,
        "lhs_seed": lhs_seed,
        "elapsed_s": elapsed,
        "n_samples": N_SAMPLES,
        "PUE_q05": float(np.quantile(pues, 0.05)),
        "PUE_q50": float(np.quantile(pues, 0.50)),
        "PUE_q95": float(np.quantile(pues, 0.95)),
        "WUE_q05": float(np.quantile(wues, 0.05)),
        "WUE_q50": float(np.quantile(wues, 0.50)),
        "WUE_q95": float(np.quantile(wues, 0.95)),
        "did_not_compare_to_meta_water": True,
        "did_not_rank_best_archetype": True,
        "P_IT": 1.0,
        "aggregation": "paper_style unweighted hourly mean; P_IT constant so equals energy-weighted",
        "check_weighted_equals_mean": abs(paper_mean_intensity(pues) - energy_weighted_annual(pues, np.ones_like(pues))) < 1e-12,
    }


def main():
    set_threads()
    FOLLOWUP.mkdir(parents=True, exist_ok=True)
    gate = json.loads((FOLLOWUP / "MASANET_ANNUAL_CLOSURE_STATUS.json").read_text())
    if not gate.get("proceed_to_adapter"):
        raise SystemExit("gate forbids Prineville translation test")
    wx = load_prineville_2022()
    write_instrumented()
    workers = n_workers(0)
    cases = {}
    for case in PRINEVILLE_CASES:
        cases[str(case)] = run_case(case, wx, workers)
    # tradeoff figure: case1 vs case2 annual envelopes, not a ranking
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(5.2, 4.2))
        for case, m in (("1", "o"), ("2", "s")):
            a = pd.read_parquet(FOLLOWUP / f"prineville_{YEAR}_case{int(case)}_annual.parquet")
            ax.scatter(a["annual_PUE_paper_mean"], a["annual_WUE_paper_mean"], s=18, alpha=0.75, marker=m, label=f"case {case}")
        ax.set_xlabel("annual PUE (paper mean)")
        ax.set_ylabel("annual WUE L/kWh (paper mean)")
        ax.set_title("Prineville 2022 weather, P_IT=1, 50 LHS (not a Meta-water fit)")
        ax.legend()
        fig.tight_layout()
        fig.savefig(FOLLOWUP / "fig_prineville_2022_case1_case2.png", dpi=140)
        plt.close(fig)
    except Exception as e:
        cases["figure_error"] = str(e)
    out = {
        "status": "PASS",
        "timestamp_utc": utcnow(),
        "weather_year_local": YEAR,
        "weather_path": str(canonical_prineville_weather_path()),
        "holdout_years_not_used": [2023, 2024],
        "reason_year_2022": "canonical pipeline holdout is 2023-2024; 2022 is a complete pre-holdout year",
        "cases": cases,
        "did_read_meta_2023_2024_water": False,
        "question": "Under actual Prineville climate, what energy/conditioning-water envelopes do published large-scale archetypes imply?",
    }
    atomic_write_json(FOLLOWUP / "prineville_weather_smoke.json", out)
    print(json.dumps({"status": "PASS", "case1": cases["1"], "case2": cases["2"]}, indent=2, default=str))


if __name__ == "__main__":
    main()
