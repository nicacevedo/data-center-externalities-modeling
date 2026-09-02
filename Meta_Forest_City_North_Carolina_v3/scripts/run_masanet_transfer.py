#!/usr/bin/env python3
"""Replay frozen Masanet Case 1 on Forest City / Prineville weather. Do not refit.

Must run under masanet_lei. Writes only under Meta_Forest_City_North_Carolina_v3/outputs/masanet/.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

FC3 = Path(__file__).resolve().parents[1]
REPO = FC3.parent
MASANET = REPO / "other_sources" / "masanet"
OUT = FC3 / "outputs" / "masanet"

sys.path.insert(0, str(MASANET / "scripts"))

from facility_adapter import FacilityIntensityAdapter, paper_mean_intensity  # noqa: E402
from followup_common import active_params_for_function  # noqa: E402
from instrument_upstream import load_instrumented  # noqa: E402

SEED = 2025
PAPER_CASE = 1
P_IT = 1.0
ARCHITECTURE_NOTE = (
    "Paper Case 1 = airside economizer + adiabatic cooling + water-cooled chiller "
    "(PUE_WUE_AE_Chiller). Forest City documented architecture is direct evaporative "
    "with unused DX backup. This is a transfer stress test, not calibration."
)


def theta_mid(case: int) -> dict:
    spec = active_params_for_function(case)
    return {k: 0.5 * (v["lo"] + v["hi"]) for k, v in spec.items()}


def eval_frame(ad, theta, weather_df: pd.DataFrame, weather_name: str) -> pd.DataFrame:
    rows = []
    for _, r in weather_df.iterrows():
        climate = {
            "T_oa": float(r["t_db_C"]),
            "RH_oa": float(r["rh_pct"]),
            "P_oa": float(r["pressure_Pa"]),
        }
        hr = ad.evaluate_hour(climate, theta, P_IT_kW=P_IT, rng_seed=SEED)
        rows.append(
            {
                "timestamp_utc": r["timestamp_utc"],
                "weather": weather_name,
                "t_db_C": climate["T_oa"],
                "rh_pct": climate["RH_oa"],
                "PUE": hr.PUE,
                "WUE_L_per_kWh": hr.WUE_L_per_kWh,
                "evidence_class": "TRANSFERRED_MODEL",
                "IT_load": "SCENARIO_P_IT=1_normalized",
                "theta_provenance": "SCENARIO Table 3 midpoints",
                "paper_case": PAPER_CASE,
            }
        )
    return pd.DataFrame(rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    theta = theta_mid(PAPER_CASE)
    inst = load_instrumented(1.0, rewrite=True)
    ad = FacilityIntensityAdapter(inst, PAPER_CASE)
    monthly_rows = []
    summaries = []
    frames = []
    for name in ("KFQD", "KRDM"):
        p = OUT / f"weather_{name}_common.csv"
        if not p.exists():
            raise FileNotFoundError(p)
        w = pd.read_csv(p)
        out = eval_frame(ad, theta, w, name)
        out.to_csv(OUT / f"MASANET_HOURLY_{name}.csv", index=False)
        frames.append(out)
        out = out.copy()
        out["month"] = pd.to_datetime(out["timestamp_utc"], utc=True).dt.month
        g = out.groupby("month").agg(PUE_mean=("PUE", "mean"), WUE_mean=("WUE_L_per_kWh", "mean"), n=("PUE", "size"))
        g = g.reset_index()
        g["weather"] = name
        monthly_rows.append(g)
        corr = float(np.corrcoef(out.t_db_C, out.PUE)[0, 1]) if len(out) > 2 else float("nan")
        summaries.append(
            {
                "weather": name,
                "n": int(len(out)),
                "PUE_mean": paper_mean_intensity(out.PUE.to_numpy()),
                "WUE_mean": paper_mean_intensity(out.WUE_L_per_kWh.to_numpy()),
                "corr_PUE_vs_tdb": corr,
                "evidence_class": "TRANSFERRED_MODEL",
                "not_fc_pue_validation": True,
                "not_fc_wue_validation": True,
                "not_cooling_water_magnitude_validation": True,
            }
        )
    monthly = pd.concat(monthly_rows, ignore_index=True)
    monthly.to_csv(OUT / "MASANET_MONTHLY.csv", index=False)
    # Directional comparison: does PUE rise with Tdb at both sites?
    k = next(s for s in summaries if s["weather"] == "KFQD")
    p = next(s for s in summaries if s["weather"] == "KRDM")
    status = "PARTIAL"
    rec = {
        "status": status,
        "refit": False,
        "paper_case": PAPER_CASE,
        "fn": "PUE_WUE_AE_Chiller",
        "P_IT": P_IT,
        "seed": SEED,
        "theta_midpoint": theta,
        "theta_provenance": "SCENARIO Table 3 midpoints; not Forest City calibrated",
        "architecture_note": ARCHITECTURE_NOTE,
        "QUANTITATIVE_PHYSICS_TRANSFER": "NOT_VALIDATED",
        "suitable": [
            "directional consistency of climate response",
            "seasonal consistency of intensity",
            "scenario mismatch vs Forest City direct-evap",
        ],
        "not_suitable": [
            "Forest City PUE validated",
            "Forest City WUE validated",
            "Forest City cooling-water magnitude validated",
        ],
        "summaries": summaries,
        "fc_pue_minus_prn_pue": k["PUE_mean"] - p["PUE_mean"],
        "both_positive_tdb_pue_corr": (k["corr_PUE_vs_tdb"] > 0) and (p["corr_PUE_vs_tdb"] > 0),
    }
    (OUT / "MASANET_TRANSFER.json").write_text(json.dumps(rec, indent=2, default=str) + "\n")
    print(json.dumps({"status": status, "summaries": summaries}, indent=2, default=str))


if __name__ == "__main__":
    main()
