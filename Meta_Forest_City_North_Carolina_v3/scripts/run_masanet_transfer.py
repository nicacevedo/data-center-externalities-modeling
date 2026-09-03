#!/usr/bin/env python3
"""Replay frozen Masanet Case 1 on Forest City / Prineville weather. Do not refit.

Must run under masanet_lei. Writes only under Meta_Forest_City_North_Carolina_v3/outputs/masanet/.
"""
from __future__ import annotations

import json
import hashlib
import importlib.util
import os
import re
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_name] = "1"
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

FC3 = Path(__file__).resolve().parents[1]
REPO = FC3.parent
MASANET = REPO / "other_sources" / "masanet"
OUT = FC3 / "outputs" / "masanet"

sys.path.insert(0, str(MASANET / "scripts"))

from facility_adapter import FacilityIntensityAdapter, paper_mean_intensity  # noqa: E402
from followup_common import active_params_for_function  # noqa: E402
from common import patch_cop_models  # noqa: E402

UPSTREAM = REPO / "other_sources" / "masanet" / "external" / "Data-Center-Water-footprint"

SEED = 2025
PAPER_CASE = 1
P_IT = 1.0
ARCHITECTURE_NOTE = (
    "Paper Case 1 = airside economizer + adiabatic cooling + water-cooled chiller "
    "(PUE_WUE_AE_Chiller). Forest City documented architecture is direct evaporative "
    "with unused DX backup. This is a transfer stress test, not calibration."
)

RECORD_FN = '''
_POWER_IT = 1.0
_LAST = {}
def _record_eval(loc):
    keep = ["PUE", "WUE", "Power_comp", "Water_comp", "Power_IT", "Q", "AE_use", "WE_use", "HD_use", "COP_chiller", "Chiller_heat_removed", "CT_heat_removed", "Cooling_required", "WE_heat_removed", "hd_amount", "hd_amount_ae", "Power_Fan_CRAC", "Power_Pump_hd", "Power_hd", "Power_Chiller", "Power_Pump_CW", "Power_Pump_CT", "Power_Fan_CT", "Power_Pump_WE", "T_sa", "d_sa", "T_ra"]
    rec = {}
    for k in keep:
        if k in loc:
            v = loc[k]
            try:
                import numpy as _np
                rec[k] = v.tolist() if isinstance(v, _np.ndarray) else v
            except Exception:
                rec[k] = v
    _LAST.clear(); _LAST.update(rec)
'''


def load_local_instrumented(power_it: float = 1.0, tag: str = "main"):
    """Instrument the frozen source under v3 outputs; never write into Masanet."""
    source = (UPSTREAM / "simulation_funs_DC.py").read_text()
    for name in ("COP_2.pkl", "COP_DX.pkl", "COP_AC.pkl"):
        source = source.replace(
            f"pickle.load(open('{name}', 'rb'))",
            f"pickle.load(open(r'{UPSTREAM / name}', 'rb'))",
        )
    source = re.sub(r"^([ \t]*)Power_IT\s*=\s*1[ \t]*(#.*)?$", r"\1Power_IT = float(_POWER_IT)", source, flags=re.M)
    source = source.replace("return PUE, WUE", "_record_eval(locals())\n    return PUE, WUE")
    instrumented = OUT / "_instrumented" / f"simulation_funs_DC_instrumented_{tag}.py"
    instrumented.parent.mkdir(parents=True, exist_ok=True)
    instrumented.write_text("# Runtime diagnostic copy under v3 only.\n" + RECORD_FN + "\n" + source)
    module_name = f"masanet_instrumented_v3_{tag}"
    spec = importlib.util.spec_from_file_location(module_name, instrumented)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    patch_cop_models(module)
    module._POWER_IT = float(power_it)
    return module


def timestamp_hash(series: pd.Series) -> str:
    values = sorted(pd.to_datetime(series, utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ"))
    return hashlib.sha256(("\n".join(values) + "\n").encode()).hexdigest()


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


def evaluate_station(name: str) -> tuple[dict, list[dict]]:
    theta = theta_mid(PAPER_CASE)
    inst = load_local_instrumented(1.0, tag=name)
    ad = FacilityIntensityAdapter(inst, PAPER_CASE)
    p = OUT / f"weather_{name}_target.csv"
    if not p.exists():
        raise FileNotFoundError(p)
    w = pd.read_csv(p)
    out = eval_frame(ad, theta, w, name)
    out.to_csv(OUT / f"MASANET_HOURLY_{name}.csv", index=False)
    monthly = out.copy()
    monthly["month"] = pd.to_datetime(monthly["timestamp_utc"], utc=True).dt.month
    grouped = monthly.groupby("month").agg(PUE_mean=("PUE", "mean"), WUE_mean=("WUE_L_per_kWh", "mean"), n=("PUE", "size")).reset_index()
    grouped["weather"] = name
    corr = float(np.corrcoef(out.t_db_C, out.PUE)[0, 1]) if len(out) > 2 else float("nan")
    corr_twb = float(np.corrcoef(w.t_wb_C, out.PUE)[0, 1]) if len(out) > 2 else float("nan")
    corr_wue_twb = float(np.corrcoef(w.t_wb_C, out.WUE_L_per_kWh)[0, 1]) if len(out) > 2 else float("nan")
    summary = {
        "weather": name,
        "n": int(len(out)),
        "PUE_mean": paper_mean_intensity(out.PUE.to_numpy()),
        "WUE_mean": paper_mean_intensity(out.WUE_L_per_kWh.to_numpy()),
        "corr_PUE_vs_tdb": corr,
        "corr_PUE_vs_twb": corr_twb,
        "corr_WUE_vs_twb": corr_wue_twb,
        "target_n": int(w["target_n"].iloc[0]),
        "matched_timestamp_coverage": float(w["matched_timestamp_coverage"].iloc[0]),
        "timestamp_set_sha256": timestamp_hash(w["timestamp_utc"]),
        "evidence_class": "TRANSFERRED_MODEL",
        "not_fc_pue_validation": True,
        "not_fc_wue_validation": True,
        "not_cooling_water_magnitude_validation": True,
    }
    return summary, grouped.to_dict("records")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    theta = theta_mid(PAPER_CASE)
    names = ("KFQD", "KRDM", "KEHO", "KGSP")
    with ProcessPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(evaluate_station, names))
    summaries = [item[0] for item in results]
    monthly = pd.DataFrame([row for _, rows in results for row in rows])
    monthly.to_csv(OUT / "MASANET_MONTHLY.csv", index=False)
    frames = [pd.read_csv(OUT / f"MASANET_HOURLY_{name}.csv") for name in names]
    all_hourly = pd.concat(frames, ignore_index=True)
    all_hourly["t_wb_C"] = pd.concat([pd.read_csv(OUT / f"weather_{name}_target.csv")["t_wb_C"] for name in ("KFQD", "KRDM", "KEHO", "KGSP")], ignore_index=True)
    all_hourly["twb_bin_lower_C"] = np.floor(all_hourly["t_wb_C"] / 2.0) * 2.0
    bins = all_hourly.groupby(["weather", "twb_bin_lower_C"]).agg(
        n=("PUE", "size"), PUE_mean=("PUE", "mean"), WUE_mean=("WUE_L_per_kWh", "mean")
    ).reset_index()
    bins["PUE_minus_station_mean"] = bins["PUE_mean"] - bins.groupby("weather")["PUE_mean"].transform("mean")
    bins.to_csv(OUT / "MASANET_CLIMATE_BINS.csv", index=False)
    # Directional comparison: does PUE rise with Tdb at both sites?
    k = next(s for s in summaries if s["weather"] == "KFQD")
    p = next(s for s in summaries if s["weather"] == "KRDM")
    main_matched = k["n"] == p["n"] == 1251 and k["timestamp_set_sha256"] == p["timestamp_set_sha256"]
    if not main_matched:
        raise RuntimeError("Masanet main KFQD/KRDM support is not identical n=1,251")
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
        "scenario_output_notice": "PUE/WUE values are scenario outputs, NOT Forest City estimates.",
        "main_fc_prn_identical_timestamp_support": main_matched,
        "main_timestamp_set_sha256": k["timestamp_set_sha256"],
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
