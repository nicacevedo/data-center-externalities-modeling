#!/usr/bin/env python3
"""Phase 4/5: paper-faithful annual LHS on selected cells; internal-RNG test.

Does not overwrite first-run artifacts. Does not tune ranges to UE.xlsx.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

from common import (
    ARCHETYPE_PARAMS,
    POWER_LABELS,
    UPSTREAM,
    UPSTREAM_COMMIT,
    WATER_LABELS,
    atomic_write_json,
    set_threads,
    utcnow,
)
from followup_common import (
    CANONICAL_WATER_KEYS,
    CLIMATE_CITIES,
    ENVIRONMENT_ID,
    FOLLOWUP,
    PAPER_CASES,
    SELECTED_CELLS,
    SMOKE_CELL,
    case_vector,
    cell_lhs_seed,
    internal_stream_seed,
    lhs_facility_samples,
    map_water_components,
)
from instrument_upstream import load_instrumented, write_instrumented

_WORKER = {}


def n_workers(requested: int | None) -> int:
    if requested and requested > 0:
        return int(requested)
    return max(1, int(os.environ.get("SLURM_CPUS_PER_TASK", "1")))


def load_zone_weather(zone: str) -> pd.DataFrame:
    p = FOLLOWUP / f"weather_{zone}.parquet"
    if not p.exists():
        raise FileNotFoundError(f"missing weather parquet {p}; run followup_weather.py first")
    df = pd.read_parquet(p)
    if len(df) != 8760:
        raise ValueError(f"{zone} weather has {len(df)} rows, expected 8760")
    return df


def ue_table() -> pd.DataFrame:
    return pd.read_excel(UPSTREAM / "Simulation Results" / "UE.xlsx")


def ue_cell(ue: pd.DataFrame, case: int, zone: str) -> dict:
    sub = ue[(ue["Case"] == case) & (ue["Climate Zone"] == zone)]
    out = {}
    for _, r in sub.iterrows():
        out[str(r["Quantile"])] = {"PUE": float(r["PUE"]), "WUE": float(r["WUE"])}
    return out


def init_worker():
    set_threads()
    warnings.filterwarnings("ignore")
    _WORKER["inst"] = load_instrumented(1.0, rewrite=False)


def _simulate_sample_payload(payload: dict) -> dict:
    inst = _WORKER["inst"]
    case = payload["paper_case"]
    fn_name = PAPER_CASES[case]["top_level_code_function"]
    fn = getattr(inst, fn_name)
    facility = payload["facility"]
    T = np.asarray(payload["T"], dtype=float)
    RH = np.asarray(payload["RH"], dtype=float)
    P = np.asarray(payload["P"], dtype=float)
    n_hours = int(payload["n_hours"])
    np.random.seed(int(payload["internal_seed"]))
    names = ARCHETYPE_PARAMS[fn_name]
    iT, iRH, iP = names.index("T_oa"), names.index("RH_oa"), names.index("P_oa")
    x0 = case_vector(case, {"T_oa": float(T[0]), "RH_oa": float(RH[0]), "P_oa": float(P[0])}, facility)
    pues = np.empty(n_hours)
    wues = np.empty(n_hours)
    ae = np.full(n_hours, np.nan)
    we = np.full(n_hours, np.nan)
    hd = np.full(n_hours, np.nan)
    wmat = {k: np.zeros(n_hours) for k in CANONICAL_WATER_KEYS}
    p_labels = POWER_LABELS[fn_name]
    pmat = {lab: np.zeros(n_hours) for lab in p_labels}
    for t in range(n_hours):
        x = list(x0)
        x[iT] = float(T[t])
        x[iRH] = float(RH[t])
        x[iP] = float(P[t])
        pue, wue = fn(x)
        rec = inst._LAST
        pues[t] = float(pue)
        wues[t] = float(wue)
        if rec.get("AE_use") is not None:
            ae[t] = float(rec["AE_use"])
        if rec.get("WE_use") is not None:
            we[t] = float(rec["WE_use"])
        if rec.get("HD_use") is not None:
            hd[t] = float(rec["HD_use"])
        wmap = map_water_components(fn_name, rec.get("Water_comp") or [])
        for k, v in wmap.items():
            wmat[k][t] = v
        pc = rec.get("Power_comp") or []
        for lab, val in zip(p_labels, pc):
            pmat[lab][t] = float(val)
    pit = np.ones(n_hours)
    annual_pue_mean = float(np.mean(pues))
    annual_wue_mean = float(np.mean(wues))
    pue_from_energy = float(np.sum(pues * pit) / np.sum(pit))
    wue_from_mass = float(np.sum(wues * pit) / np.sum(pit))
    identity_pue_ok = abs(annual_pue_mean - pue_from_energy) <= 1e-12
    identity_wue_ok = abs(annual_wue_mean - wue_from_mass) <= 1e-12
    out = {
        "facility_sample_id": payload["facility_sample_id"],
        "lhs_seed": payload["lhs_seed"],
        "internal_seed": payload["internal_seed"],
        "replicate": payload.get("replicate", 0),
        "n_hours": n_hours,
        "annual_PUE_paper_mean": annual_pue_mean,
        "annual_WUE_paper_mean": annual_wue_mean,
        "annual_PUE_energy_weighted": pue_from_energy,
        "annual_WUE_energy_weighted": wue_from_mass,
        "paper_aggregation_identity_PUE": identity_pue_ok,
        "paper_aggregation_identity_WUE": identity_wue_ok,
        "frac_AE": None if np.isnan(ae).all() else float(np.nanmean(ae)),
        "frac_WE": None if np.isnan(we).all() else float(np.nanmean(we)),
        "frac_HD": None if np.isnan(hd).all() else float(np.nanmean(hd)),
        "facility": facility,
        "finite": bool(np.isfinite(pues).all() and np.isfinite(wues).all()),
        "min_PUE": float(np.min(pues)),
        "max_PUE": float(np.max(pues)),
        "min_WUE": float(np.min(wues)),
        "max_WUE": float(np.max(wues)),
        "water_annual_mean_kg_s": {k: float(np.mean(v)) for k, v in wmat.items()},
        "water_annual_mean_L_per_kWh": {k: float(np.mean(v) * 3600.0) for k, v in wmat.items()},
    }
    if payload.get("store_hourly"):
        out["hourly"] = {
            "PUE": pues.tolist(),
            "WUE": wues.tolist(),
            "AE_use": ae.tolist(),
            "WE_use": we.tolist(),
            "HD_use": hd.tolist(),
            "water": {k: v.tolist() for k, v in wmat.items()},
            "power": {k: v.tolist() for k, v in pmat.items()},
        }
    return out


def run_design(case: int, zone: str, n_samples: int, n_hours: int, replicate: int, workers: int, store_hourly: bool):
    wx = load_zone_weather(zone)
    city = CLIMATE_CITIES[zone]
    lhs_seed = cell_lhs_seed(case, zone, replicate)
    samples = lhs_facility_samples(case, n_samples, lhs_seed)
    T = wx["T_oa"].to_numpy(dtype=float)[:n_hours]
    RH = wx["RH_oa"].to_numpy(dtype=float)[:n_hours]
    P = wx["P_oa"].to_numpy(dtype=float)[:n_hours]
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
                "lhs_seed": lhs_seed,
                "internal_seed": internal_stream_seed(lhs_seed, i, 0),
                "replicate": replicate,
                "store_hourly": store_hourly,
            }
        )
    t0 = time.time()
    nw = min(workers, n_samples)
    write_instrumented()
    results = []
    if nw == 1:
        init_worker()
        for p in payloads:
            results.append(_simulate_sample_payload(p))
    else:
        with ProcessPoolExecutor(max_workers=nw, initializer=init_worker) as ex:
            futs = [ex.submit(_simulate_sample_payload, p) for p in payloads]
            for fut in as_completed(futs):
                results.append(fut.result())
    results.sort(key=lambda r: r["facility_sample_id"])
    elapsed = time.time() - t0
    return {
        "paper_case": case,
        "climate_zone": zone,
        "representative_city": city["city"],
        "epw_id": city["epw_id"],
        "lhs_seed": lhs_seed,
        "n_samples": n_samples,
        "n_hours": n_hours,
        "replicate": replicate,
        "workers": nw,
        "elapsed_s": elapsed,
        "evals_per_s": (n_samples * n_hours) / elapsed if elapsed else None,
        "samples": samples,
        "results": results,
        "weather_T_C_range": [float(T.min()), float(T.max())],
        "weather_RH_pct_range": [float(RH.min()), float(RH.max())],
        "weather_P_Pa_range": [float(P.min()), float(P.max())],
        "upstream_commit": UPSTREAM_COMMIT,
        "environment_id": ENVIRONMENT_ID,
        "fn": PAPER_CASES[case]["top_level_code_function"],
    }


def bootstrap_quantile_interval(vals, q, n_boot=1000, seed=7):
    rng = np.random.default_rng(seed)
    n = len(vals)
    stats = np.empty(n_boot)
    for i in range(n_boot):
        stats[i] = np.quantile(rng.choice(vals, size=n, replace=True), q)
    return float(np.quantile(stats, 0.05)), float(np.quantile(stats, 0.95))


def classify_against_ue(pue_vals, wue_vals, published: dict, extra_quantile_estimates=None) -> dict:
    pue_vals = np.asarray(pue_vals, dtype=float)
    wue_vals = np.asarray(wue_vals, dtype=float)
    hat = {
        "PUE_5th": float(np.quantile(pue_vals, 0.05)),
        "PUE_95th": float(np.quantile(pue_vals, 0.95)),
        "WUE_5th": float(np.quantile(wue_vals, 0.05)),
        "WUE_95th": float(np.quantile(wue_vals, 0.95)),
    }
    pub = {
        "PUE_5th": published["5th"]["PUE"],
        "PUE_95th": published["95th"]["PUE"],
        "WUE_5th": published["5th"]["WUE"],
        "WUE_95th": published["95th"]["WUE"],
    }
    boot = {}
    inside_boot = True
    for name, arr, q in (
        ("PUE_5th", pue_vals, 0.05),
        ("PUE_95th", pue_vals, 0.95),
        ("WUE_5th", wue_vals, 0.05),
        ("WUE_95th", wue_vals, 0.95),
    ):
        lo, hi = bootstrap_quantile_interval(arr, q)
        boot[name] = {"lo": lo, "hi": hi, "published": pub[name], "hat": hat[name]}
        if not (lo <= pub[name] <= hi):
            inside_boot = False
    status = "CONSISTENT_WITH_PUBLISHED_RANGE"
    if not inside_boot:
        if extra_quantile_estimates:
            extra_ok = True
            for name in hat:
                xs = [e[name] for e in extra_quantile_estimates]
                if not (min(xs) <= pub[name] <= max(xs)):
                    extra_ok = False
            status = "CONSISTENT_WITH_PUBLISHED_RANGE" if extra_ok else "INCONSISTENT"
        else:
            status = "NEEDS_REPLICATE"
    return {
        "status": status,
        "reproduced": hat,
        "published": pub,
        "delta_hat_minus_published": {k: hat[k] - pub[k] for k in hat},
        "bootstrap_5_95_of_quantile_estimator": boot,
        "published_inside_first_design_bootstrap": inside_boot,
        "n_annual_samples": int(len(pue_vals)),
        "method": (
            "Compare bundled UE.xlsx 5th/95th to the sampling distribution of those quantiles. "
            "First: bootstrap the 50 annual values. If published lies outside, run independent 50-sample LHS replications."
        ),
    }


def write_cell_outputs(bundle: dict, tag: str, store_hourly: bool, classification: dict | None):
    FOLLOWUP.mkdir(parents=True, exist_ok=True)
    case, zone = bundle["paper_case"], bundle["climate_zone"]
    stem = f"{tag}_case{case}_{zone}_r{bundle['replicate']}"
    sample_rows = []
    annual_rows = []
    hourly_frames = []
    wx = load_zone_weather(zone).iloc[: bundle["n_hours"]].reset_index(drop=True)
    for rec, fac in zip(bundle["results"], bundle["samples"]):
        sample_rows.append(
            {
                "paper_case": case,
                "climate_zone": zone,
                "representative_city": bundle["representative_city"],
                "lhs_seed": rec["lhs_seed"],
                "facility_sample_id": rec["facility_sample_id"],
                "replicate": rec["replicate"],
                "internal_seed": rec["internal_seed"],
                **{f"theta_{k}": v for k, v in fac.items()},
            }
        )
        annual_rows.append(
            {
                "paper_case": case,
                "climate_zone": zone,
                "representative_city": bundle["representative_city"],
                "lhs_seed": rec["lhs_seed"],
                "facility_sample_id": rec["facility_sample_id"],
                "replicate": rec["replicate"],
                "internal_seed": rec["internal_seed"],
                "n_hours": rec["n_hours"],
                "annual_PUE_paper_mean": rec["annual_PUE_paper_mean"],
                "annual_WUE_paper_mean": rec["annual_WUE_paper_mean"],
                "paper_aggregation_identity_PUE": rec["paper_aggregation_identity_PUE"],
                "paper_aggregation_identity_WUE": rec["paper_aggregation_identity_WUE"],
                "frac_AE": rec["frac_AE"],
                "frac_WE": rec["frac_WE"],
                "frac_HD": rec["frac_HD"],
                "finite": rec["finite"],
                "upstream_commit": UPSTREAM_COMMIT,
                "environment_id": ENVIRONMENT_ID,
                **{f"Wmean_{k}_kg_s": rec["water_annual_mean_kg_s"][k] for k in CANONICAL_WATER_KEYS},
            }
        )
        if store_hourly and "hourly" in rec:
            h = rec["hourly"]
            hdf = pd.DataFrame(
                {
                    "paper_case": case,
                    "climate_zone": zone,
                    "representative_city": bundle["representative_city"],
                    "lhs_seed": rec["lhs_seed"],
                    "facility_sample_id": rec["facility_sample_id"],
                    "hour": np.arange(bundle["n_hours"]),
                    "T_oa": wx["T_oa"].to_numpy(),
                    "RH_oa": wx["RH_oa"].to_numpy(),
                    "P_oa": wx["P_oa"].to_numpy(),
                    "PUE": h["PUE"],
                    "WUE": h["WUE"],
                    "AE_use": h["AE_use"],
                    "WE_use": h["WE_use"],
                    "HD_use": h["HD_use"],
                    "upstream_commit": UPSTREAM_COMMIT,
                    "environment_id": ENVIRONMENT_ID,
                }
            )
            for k in CANONICAL_WATER_KEYS:
                hdf[f"W_{k}_kg_s"] = h["water"][k]
            hourly_frames.append(hdf)
    samples_p = FOLLOWUP / f"{stem}_facility_samples.parquet"
    annual_p = FOLLOWUP / f"{stem}_annual.parquet"
    pd.DataFrame(sample_rows).to_parquet(samples_p, index=False)
    pd.DataFrame(annual_rows).to_parquet(annual_p, index=False)
    hourly_p = None
    if hourly_frames:
        hourly_p = FOLLOWUP / f"{stem}_hourly.parquet"
        pd.concat(hourly_frames, ignore_index=True).to_parquet(hourly_p, index=False)
    slim = {k: v for k, v in bundle.items() if k not in ("results", "samples")}
    slim["identity_all_pass"] = all(
        r["paper_aggregation_identity_PUE"] and r["paper_aggregation_identity_WUE"] for r in bundle["results"]
    )
    slim["n_nonfinite"] = sum(1 for r in bundle["results"] if not r["finite"])
    slim["paths"] = {"facility_samples": str(samples_p), "annual": str(annual_p), "hourly": str(hourly_p) if hourly_p else None}
    if classification:
        slim["vs_ue"] = classification
    slim["timestamp_utc"] = utcnow()
    json_p = FOLLOWUP / f"{stem}.json"
    atomic_write_json(json_p, slim)
    return json_p, slim


def mode_smoke_short(workers: int):
    cell = SMOKE_CELL
    bundle = run_design(cell["paper_case"], cell["climate_zone"], n_samples=2, n_hours=168, replicate=0, workers=workers, store_hourly=True)
    identities = all(r["paper_aggregation_identity_PUE"] and r["paper_aggregation_identity_WUE"] for r in bundle["results"])
    finite = all(r["finite"] for r in bundle["results"])
    path, slim = write_cell_outputs(bundle, "smoke_short", True, None)
    out = {
        "status": "PASS" if identities and finite else "FAIL",
        "timestamp_utc": utcnow(),
        "cell": cell,
        "elapsed_s": bundle["elapsed_s"],
        "evals_per_s": bundle["evals_per_s"],
        "projected_50x8760_s_one_worker": None
        if not bundle["evals_per_s"]
        else (50 * 8760) / bundle["evals_per_s"],
        "identity_pass": identities,
        "finite": finite,
        "path": str(path),
        "rss_note": "RSS not sampled; size array jobs from evals_per_s",
    }
    atomic_write_json(FOLLOWUP / "annual_smoke_short.json", out)
    print(json.dumps(out, indent=2))
    if out["status"] != "PASS":
        raise SystemExit(2)
    return out


def _run_one_full_cell(cell: dict, workers: int, store_hourly: bool, tag: str):
    ue = ue_table()
    published = ue_cell(ue, cell["paper_case"], cell["climate_zone"])
    bundle = run_design(
        cell["paper_case"],
        cell["climate_zone"],
        n_samples=50,
        n_hours=8760,
        replicate=0,
        workers=workers,
        store_hourly=store_hourly,
    )
    pues = [r["annual_PUE_paper_mean"] for r in bundle["results"]]
    wues = [r["annual_WUE_paper_mean"] for r in bundle["results"]]
    cls = classify_against_ue(pues, wues, published)
    extra_hats = []
    extra_elapsed = []
    if cls["status"] == "NEEDS_REPLICATE":
        for rep in range(1, 5):
            b2 = run_design(
                cell["paper_case"],
                cell["climate_zone"],
                n_samples=50,
                n_hours=8760,
                replicate=rep,
                workers=workers,
                store_hourly=False,
            )
            p2 = [r["annual_PUE_paper_mean"] for r in b2["results"]]
            w2 = [r["annual_WUE_paper_mean"] for r in b2["results"]]
            extra_hats.append(
                {
                    "replicate": rep,
                    "lhs_seed": b2["lhs_seed"],
                    "PUE_5th": float(np.quantile(p2, 0.05)),
                    "PUE_95th": float(np.quantile(p2, 0.95)),
                    "WUE_5th": float(np.quantile(w2, 0.05)),
                    "WUE_95th": float(np.quantile(w2, 0.95)),
                }
            )
            extra_elapsed.append(b2["elapsed_s"])
            write_cell_outputs(b2, f"{tag}_extra", False, None)
        cls = classify_against_ue(pues, wues, published, extra_quantile_estimates=extra_hats)
    cls["extra_lhs_quantile_estimates"] = extra_hats
    cls["extra_elapsed_s"] = extra_elapsed
    path, slim = write_cell_outputs(bundle, tag, store_hourly, cls)
    slim["vs_ue"] = cls
    atomic_write_json(path, slim)
    return path, slim


def mode_smoke_full(workers: int):
    path, slim = _run_one_full_cell(SMOKE_CELL, workers, store_hourly=True, tag="annual")
    out = {
        "status": "PASS" if slim["identity_all_pass"] and slim["n_nonfinite"] == 0 else "FAIL",
        "vs_ue_status": slim.get("vs_ue", {}).get("status"),
        "path": str(path),
        "elapsed_s": slim["elapsed_s"],
        "evals_per_s": slim["evals_per_s"],
    }
    atomic_write_json(FOLLOWUP / "annual_smoke_full.json", out)
    print(json.dumps(out, indent=2))
    if out["status"] != "PASS":
        raise SystemExit(2)


def mode_cell(index: int, workers: int):
    cell = SELECTED_CELLS[index]
    path, slim = _run_one_full_cell(cell, workers, store_hourly=True, tag="annual")
    print(json.dumps({"cell": cell, "path": str(path), "vs_ue": slim.get("vs_ue", {}).get("status"), "elapsed_s": slim["elapsed_s"]}, indent=2))
    if slim["n_nonfinite"] or not slim["identity_all_pass"]:
        raise SystemExit(2)


def mode_compare():
    ue = ue_table()
    rows = []
    for cell in SELECTED_CELLS:
        p = FOLLOWUP / f"annual_case{cell['paper_case']}_{cell['climate_zone']}_r0.json"
        if not p.exists():
            rows.append({**cell, "status": "NOT_RUN"})
            continue
        d = json.loads(p.read_text())
        st = d.get("vs_ue", {}).get("status", "NOT_RUN")
        rows.append(
            {
                **cell,
                "status": st,
                "reproduced": d.get("vs_ue", {}).get("reproduced"),
                "published": d.get("vs_ue", {}).get("published"),
                "delta": d.get("vs_ue", {}).get("delta_hat_minus_published"),
                "extra_n": len(d.get("vs_ue", {}).get("extra_lhs_quantile_estimates") or []),
            }
        )
    statuses = [r["status"] for r in rows]
    if any(s == "INCONSISTENT" for s in statuses):
        overall = "INCONSISTENT"
    elif any(s == "NOT_RUN" for s in statuses):
        overall = "NOT_RUN"
    elif any(s in ("NEEDS_REPLICATE", "PARTIAL_NUMERIC_DIFFERENCE") for s in statuses):
        overall = "PARTIAL_NUMERIC_DIFFERENCE"
    else:
        overall = "CONSISTENT_WITH_PUBLISHED_RANGE"
    out = {
        "status": overall,
        "timestamp_utc": utcnow(),
        "selection_locked_before_errors": True,
        "cells": rows,
        "ue_source": str(UPSTREAM / "Simulation Results" / "UE.xlsx"),
    }
    atomic_write_json(FOLLOWUP / "annual_selected_comparison.json", out)
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(1, 2, figsize=(8.5, 3.6))
        for i, metric in enumerate(("PUE", "WUE")):
            xs, ys5, ys95 = [], [], []
            for r in rows:
                if not r.get("published"):
                    continue
                xs.append(r["published"][f"{metric}_5th"])
                ys5.append(r["reproduced"][f"{metric}_5th"])
                ys95.append(r["reproduced"][f"{metric}_95th"])
                ax[i].scatter(r["published"][f"{metric}_95th"], r["reproduced"][f"{metric}_95th"], marker="^")
            ax[i].scatter(xs, ys5, marker="o", label="5th")
            lim = [min(xs + ys5 + ys95), max(xs + ys5 + ys95)] if xs else [0, 1]
            ax[i].plot(lim, lim, ls="--", c="k", lw=0.8)
            ax[i].set_title(metric)
            ax[i].set_xlabel("UE.xlsx")
            ax[i].set_ylabel("reproduced")
        fig.tight_layout()
        fig.savefig(FOLLOWUP / "fig_annual_vs_ue.png", dpi=140)
        plt.close(fig)
    except Exception as e:
        out["figure_error"] = str(e)
        atomic_write_json(FOLLOWUP / "annual_selected_comparison.json", out)
    print(json.dumps({"status": overall, "cells": [{k: r[k] for k in ("paper_case", "climate_zone", "status")} for r in rows]}, indent=2))
    if overall == "INCONSISTENT":
        raise SystemExit(2)


def mode_rng(workers: int, n_seeds: int = 10):
    cell = SMOKE_CELL
    # Hold facility sample 0 of the canonical LHS design fixed; vary only internal stream offset.
    wx = load_zone_weather(cell["climate_zone"])
    lhs_seed = cell_lhs_seed(cell["paper_case"], cell["climate_zone"], 0)
    fac = lhs_facility_samples(cell["paper_case"], 50, lhs_seed)[0]
    T = wx["T_oa"].to_numpy(dtype=float)
    RH = wx["RH_oa"].to_numpy(dtype=float)
    P = wx["P_oa"].to_numpy(dtype=float)
    write_instrumented()
    payloads = []
    for s in range(n_seeds):
        payloads.append(
            {
                "paper_case": cell["paper_case"],
                "facility": fac,
                "T": T,
                "RH": RH,
                "P": P,
                "n_hours": 8760,
                "facility_sample_id": 0,
                "lhs_seed": lhs_seed,
                "internal_seed": internal_stream_seed(lhs_seed, 0, s + 1),
                "replicate": 0,
                "store_hourly": False,
            }
        )
    t0 = time.time()
    nw = min(workers, n_seeds)
    recs = []
    if nw == 1:
        init_worker()
        recs = [_simulate_sample_payload(p) for p in payloads]
    else:
        with ProcessPoolExecutor(max_workers=nw, initializer=init_worker) as ex:
            recs = [fut.result() for fut in as_completed([ex.submit(_simulate_sample_payload, p) for p in payloads])]
    elapsed = time.time() - t0
    annual_p = FOLLOWUP / f"annual_case{cell['paper_case']}_{cell['climate_zone']}_r0_annual.parquet"
    if not annual_p.exists():
        raise FileNotFoundError(annual_p)
    fac_ann = pd.read_parquet(annual_p)
    seed_pue = np.array([r["annual_PUE_paper_mean"] for r in recs])
    seed_wue = np.array([r["annual_WUE_paper_mean"] for r in recs])
    fac_pue = fac_ann["annual_PUE_paper_mean"].to_numpy()
    fac_wue = fac_ann["annual_WUE_paper_mean"].to_numpy()
    def spread(a):
        return float(np.max(a) - np.min(a))
    pue_ratio = spread(seed_pue) / spread(fac_pue) if spread(fac_pue) > 0 else (0.0 if spread(seed_pue) < 1e-12 else float("inf"))
    wue_ratio = spread(seed_wue) / spread(fac_wue) if spread(fac_wue) > 0 else (0.0 if spread(seed_wue) < 1e-12 else float("inf"))
    water_ratios = {}
    for k in CANONICAL_WATER_KEYS:
        sk = np.array([r["water_annual_mean_kg_s"][k] for r in recs])
        fk = fac_ann[f"Wmean_{k}_kg_s"].to_numpy()
        water_ratios[k] = spread(sk) / spread(fk) if spread(fk) > 0 else (0.0 if spread(sk) < 1e-12 else float("inf"))
    material = (pue_ratio >= 0.10) or (wue_ratio >= 0.10)
    status = "ANNUAL_RNG_MATERIAL" if material else "ANNUAL_RNG_IMMATERIAL"
    out = {
        "status": status,
        "timestamp_utc": utcnow(),
        "cell": cell,
        "n_internal_seeds": n_seeds,
        "elapsed_s": elapsed,
        "held_fixed": ["weather", "facility_LHS_sample_0", "explicit_facility_parameters"],
        "varied": "upstream np.random stream start only",
        "seed_PUE": {"min": float(seed_pue.min()), "max": float(seed_pue.max()), "spread": spread(seed_pue)},
        "seed_WUE": {"min": float(seed_wue.min()), "max": float(seed_wue.max()), "spread": spread(seed_wue)},
        "facility_design_PUE_spread": spread(fac_pue),
        "facility_design_WUE_spread": spread(fac_wue),
        "ratio_seed_over_facility_PUE": pue_ratio,
        "ratio_seed_over_facility_WUE": wue_ratio,
        "ratio_seed_over_facility_water_components": water_ratios,
        "decision_rule": "MATERIAL if PUE or WUE seed/facility spread ratio >= 0.10",
        "did_not_modify_upstream_stochastic_helpers": True,
    }
    atomic_write_json(FOLLOWUP / "annual_rng.json", out)
    print(json.dumps({k: out[k] for k in ("status", "ratio_seed_over_facility_PUE", "ratio_seed_over_facility_WUE")}, indent=2))
    if status == "ANNUAL_RNG_MATERIAL":
        raise SystemExit(2)


def main():
    set_threads()
    FOLLOWUP.mkdir(parents=True, exist_ok=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["smoke-short", "smoke-full", "cell", "compare", "rng"])
    ap.add_argument("--cell-index", type=int, default=None)
    ap.add_argument("--workers", type=int, default=0)
    args = ap.parse_args()
    w = n_workers(args.workers)
    if args.mode == "smoke-short":
        mode_smoke_short(w)
    elif args.mode == "smoke-full":
        mode_smoke_full(w)
    elif args.mode == "cell":
        if args.cell_index is None:
            idx = int(os.environ.get("SLURM_ARRAY_TASK_ID", "1"))
        else:
            idx = args.cell_index
        mode_cell(idx, w)
    elif args.mode == "compare":
        mode_compare()
    elif args.mode == "rng":
        mode_rng(w)


if __name__ == "__main__":
    main()
