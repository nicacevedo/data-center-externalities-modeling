"""Summarize weather-dependent reconstruction metrics for KRDM vs canonical comparison."""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
HOURLY = ROOT / "outputs" / "hourly_conditional_reconstruction.csv"
ANNUAL = ROOT / "outputs" / "conditional_annual_compare.csv"
OUT = ROOT / "outputs" / "weather_ks39" / "canonical_reconstruction_metrics.csv"


def summarize(hourly_path: Path = HOURLY, annual_path: Path = ANNUAL, out_path: Path = OUT) -> pd.DataFrame:
    h = pd.read_csv(hourly_path)
    a = pd.read_csv(annual_path)
    h["timestamp_utc"] = pd.to_datetime(h["timestamp_utc"], utc=True)
    hold = a[a.split == "holdout"]
    rows = {
        "holdout_water_pct_error_2023": float(hold.loc[hold.year == 2023, "water_pct_error"].iloc[0])
        if (hold.year == 2023).any()
        else float("nan"),
        "holdout_water_pct_error_2024": float(hold.loc[hold.year == 2024, "water_pct_error"].iloc[0])
        if (hold.year == 2024).any()
        else float("nan"),
        "holdout_water_mape": float(hold["water_pct_error"].abs().mean()) if len(hold) else float("nan"),
        "max_abs_elec_residual_mwh": float((a.electricity_mwh_model_closure - a.electricity_mwh_reported).abs().max()),
        "annual_raw_evap_m3_sum": float(h["evap_water_m3_per_h"].sum()),
    }
    if "cooling_mode" in h:
        frac = h["cooling_mode"].value_counts(normalize=True)
        for mode, v in frac.items():
            rows[f"cooling_mode_frac_{mode}"] = float(v)
    jja = h[h.timestamp_utc.dt.month.isin([6, 7, 8])]
    rows["summer_jja_mean_evap_m3_h"] = float(jja["evap_water_m3_per_h"].mean()) if len(jja) else float("nan")
    if "t_wb_C" in h:
        rows["mean_t_wb_C"] = float(h["t_wb_C"].mean())
        rows["p95_t_wb_C"] = float(h["t_wb_C"].quantile(0.95))
    out = pd.DataFrame({"metric": list(rows), "value": list(rows.values())})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hourly", default=str(HOURLY))
    ap.add_argument("--annual", default=str(ANNUAL))
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    z = summarize(Path(args.hourly), Path(args.annual), Path(args.out))
    print(z.to_string(index=False))


if __name__ == "__main__":
    main()
