"""Conditional public-data reconstruction for Meta Prineville.

This module performs the strongest subannual reconstruction that annual public data alone
support without fabricating hourly IT telemetry:

1. For each calendar year, infer ONE latent IT-power scale so the physics model closes to
   Meta's reported annual *facility* electricity. This is calibration closure, not electricity validation.
2. Use hourly observed weather + the gray-box cooling model to generate hourly PUE/cooling/water shape.
3. Fit a parsimonious global or one-break multiplicative water factor on TRAINING years only.
4. Predict held-out annual water from weather + reported annual electricity; report holdout errors.

The water break is statistical only. It must not be named as a physical technology change unless
independent permit/engineering evidence supports it.
"""
from __future__ import annotations
from pathlib import Path
import math
import numpy as np
import pandas as pd

from prineville_graybox import Params, assert_finite_physical_outputs, assert_finite_weather, simulate

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ROOT / "data" / "canonical" / "meta_prineville_annual.csv"
WEATHER = ROOT / "data" / "processed" / "weather_hourly.csv"


def _fit_log_scale(raw: np.ndarray, obs: np.ndarray) -> float:
    mask = np.isfinite(raw) & np.isfinite(obs) & (raw > 0) & (obs > 0)
    if mask.sum() == 0:
        return 1.0
    return float(np.exp(np.mean(np.log(obs[mask] / raw[mask]))))


def _log_sse(raw: np.ndarray, obs: np.ndarray, scale: float) -> float:
    mask = np.isfinite(raw) & np.isfinite(obs) & (raw > 0) & (obs > 0)
    if mask.sum() == 0:
        return np.nan
    r = np.log(obs[mask]) - np.log(scale * raw[mask])
    return float(np.sum(r * r))


def select_water_scale_model(train_annual: pd.DataFrame, min_segment_years: int = 3):
    """Choose global vs one-break log-scale model using BIC on training years only."""
    d = train_annual.dropna(subset=["water_raw_m3", "water_withdrawal_m3_reported"]).copy()
    d = d[(d.water_raw_m3 > 0) & (d.water_withdrawal_m3_reported > 0)].sort_values("year")
    n = len(d)
    if n < 2 * min_segment_years:
        s = _fit_log_scale(d.water_raw_m3.to_numpy(), d.water_withdrawal_m3_reported.to_numpy())
        return {"kind": "global", "scale": s, "bic": np.nan, "break_year": None}

    raw = d.water_raw_m3.to_numpy(float)
    obs = d.water_withdrawal_m3_reported.to_numpy(float)
    s0 = _fit_log_scale(raw, obs)
    sse0 = max(_log_sse(raw, obs, s0), 1e-12)
    bic0 = n * math.log(sse0 / n) + 1 * math.log(n)
    best = {"kind": "global", "scale": s0, "bic": bic0, "break_year": None}

    years = d.year.to_numpy(int)
    for j in range(min_segment_years, n - min_segment_years + 1):
        s1 = _fit_log_scale(raw[:j], obs[:j])
        s2 = _fit_log_scale(raw[j:], obs[j:])
        sse = max(_log_sse(raw[:j], obs[:j], s1) + _log_sse(raw[j:], obs[j:], s2), 1e-12)
        # 3 effective parameters: two scales + break location.
        bic = n * math.log(sse / n) + 3 * math.log(n)
        if bic < best["bic"] - 2.0:  # require modest evidence over global model
            best = {
                "kind": "one_break",
                "scale_pre": s1,
                "scale_post": s2,
                "break_year": int(years[j]),
                "bic": bic,
                "global_bic": bic0,
            }
    return best


def _scale_for_year(model: dict, year: int) -> float:
    if model["kind"] == "global":
        return float(model["scale"])
    return float(model["scale_pre"] if year < model["break_year"] else model["scale_post"])


def _finite_sum(series, name: str, year: int) -> float:
    arr = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    n_bad = int((~np.isfinite(arr)).sum())
    if n_bad:
        raise ValueError(
            f"Cannot annually aggregate {name} for {year}: {n_bad} non-finite values. "
            "Missing hours are not skipped."
        )
    return float(np.sum(arr))


def reconstruct(target_years=None, train_end_year: int = 2022, params: Params = Params()):
    if not WEATHER.exists():
        raise FileNotFoundError(
            f"Missing {WEATHER}. Run src/download_noaa_global_hourly.py and src/prepare_weather.py first."
        )
    t = pd.read_csv(TARGETS)
    if target_years is not None:
        t = t[t.year.isin(list(target_years))].copy()

    w = pd.read_csv(WEATHER)
    w["timestamp_utc"] = pd.to_datetime(w["timestamp_utc"], utc=True)
    if "year_local" in w.columns and w["year_local"].notna().all():
        w["year"] = pd.to_numeric(w["year_local"], errors="coerce").astype(int)
    else:
        w["year"] = w["timestamp_utc"].dt.tz_convert("America/Los_Angeles").dt.year

    hourly_parts = []
    annual_rows = []
    for r in t.itertuples(index=False):
        wy = w[w.year == r.year].copy()
        if wy.empty:
            continue
        expected = int(r.hours_in_year)
        coverage = len(wy) / expected
        if coverage < 0.98:
            raise ValueError(f"Weather coverage for {r.year} is only {coverage:.1%}; fill/flag gaps before reconstruction.")
        assert_finite_weather(wy, year=int(r.year))

        # Facility MWh per 1 MW constant latent IT scale. The model is linear in IT power.
        unit = simulate(wy, 1.0, params=params)
        fac_mwh_per_it_mw = _finite_sum(unit.p_fac_mw, "p_fac_mw", int(r.year))
        p_it_scale = float(r.electricity_mwh_reported) / fac_mwh_per_it_mw
        hy = simulate(wy, p_it_scale, params=params)
        assert_finite_physical_outputs(hy, year=int(r.year))
        hy["year"] = int(r.year)
        hy["electricity_closure_target_mwh"] = float(r.electricity_mwh_reported)
        hy["it_power_provenance"] = "fitted annual scale; NOT observed hourly IT telemetry"
        hourly_parts.append(hy)

        e_it = _finite_sum(hy.p_it_mw, "p_it_mw", int(r.year))
        e_fac = _finite_sum(hy.p_fac_mw, "p_fac_mw", int(r.year))
        water_raw = _finite_sum(hy.evap_water_m3_per_h, "evap_water_m3_per_h", int(r.year))
        annual_rows.append({
            "year": int(r.year),
            "electricity_mwh_reported": float(r.electricity_mwh_reported),
            "electricity_mwh_model_closure": e_fac,
            "it_energy_mwh_fitted": e_it,
            "annual_pue_model": e_fac / e_it if e_it > 0 else np.nan,
            "water_raw_m3": water_raw,
            "water_withdrawal_m3_reported": getattr(r, "water_withdrawal_m3_reported"),
            "weather_hour_coverage": coverage,
        })

    if not annual_rows:
        raise ValueError("No overlapping target/weather years.")
    annual = pd.DataFrame(annual_rows).sort_values("year")
    train = annual[annual.year <= train_end_year].copy()
    water_model = select_water_scale_model(train)
    annual["water_scale_fitted_train_only"] = annual.year.map(lambda y: _scale_for_year(water_model, int(y)))
    annual["water_pred_m3"] = annual.water_raw_m3 * annual.water_scale_fitted_train_only
    annual["water_pct_error"] = 100 * (annual.water_pred_m3 - annual.water_withdrawal_m3_reported) / annual.water_withdrawal_m3_reported
    annual["split"] = np.where(annual.year <= train_end_year, "train", "holdout")

    hourly = pd.concat(hourly_parts, ignore_index=True)
    scale_map = annual.set_index("year")["water_scale_fitted_train_only"].to_dict()
    hourly["water_scale_fitted_train_only"] = hourly.year.map(scale_map)
    hourly["water_withdrawal_proxy_m3_per_h"] = hourly.evap_water_m3_per_h * hourly.water_scale_fitted_train_only
    hourly["water_provenance"] = "physics-shaped + training-year scale; inferred, not meter data"

    # Report initial design benchmark as a falsification diagnostic, not a fit target.
    if 2011 in annual.year.values:
        a11 = annual.loc[annual.year == 2011].iloc[0]
        water_model["modeled_2011_annual_pue"] = float(a11.annual_pue_model)
        water_model["meta_2011_full_load_pue_benchmark"] = 1.07
        water_model["meta_2011_wue_benchmark_L_per_kWh_it"] = 0.31

    return hourly, annual, water_model


def main():
    outdir = ROOT / "outputs"
    outdir.mkdir(exist_ok=True)
    hourly, annual, model = reconstruct()
    hourly.to_csv(outdir / "hourly_conditional_reconstruction.csv", index=False)
    annual.to_csv(outdir / "conditional_annual_compare.csv", index=False)
    pd.DataFrame([model]).to_csv(outdir / "conditional_water_model.csv", index=False)
    print(annual.to_string(index=False))
    print("\nWater model:", model)


if __name__ == "__main__":
    main()
