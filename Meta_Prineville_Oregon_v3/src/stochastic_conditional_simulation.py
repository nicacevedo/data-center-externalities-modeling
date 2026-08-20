"""Conditional stochastic proxy for the Meta Prineville campus.

This is a generative calibration model, not recovered telemetry and not a
forecasting model.  It implements a first executable subset of the dependency
chain in ``modeling/glossary_mapping.tex``:

    stochastic arrivals -> queued/executed work -> IT power -> facility power
    -> direct-water shape -> location-based emissions shape

The public annual observations remain the empirical anchors:

* facility electricity is closed exactly for every year and simulation;
* reported site withdrawal can be used in a retrospective-closure mode;
* a separate train-only water model (2014-2022 by default) is evaluated on the
  untouched 2023-2024 annual observations;
* reported location-based Scope 2 is closed exactly by annual allocation;
  PACW EIA-930 from the historical workbook can be enabled only as an explicit
  relative-shape sensitivity: EIA consumed CO2 intensity when present (from
  2018-07), otherwise a named fuel/import proxy (demand/interchange from 2015-07).
  It is never treated as Meta-specific marginal emissions.

Synthetic arrivals are dimensionless work units.  Their absolute counts,
queues, utilization, IT power, PUE, hourly water, and hourly emissions are
fitted/scenario quantities and must never be relabeled as observations.

Run from the project root:

    python src/stochastic_conditional_simulation.py

The script writes auditable CSV, JSON, and PNG artifacts under ``outputs/``.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import nnls

from prineville_graybox import Params, simulate


ROOT = Path(__file__).resolve().parents[1]
TARGETS = ROOT / "data" / "canonical" / "meta_prineville_annual.csv"
WEATHER = ROOT / "data" / "processed" / "weather_hourly.csv"
EIA_REGION = ROOT / "data" / "raw" / "eia930" / "PACW_region-data_2019_2024.csv"
EIA_FUEL = ROOT / "data" / "raw" / "eia930" / "PACW_fuel-type-data_2019_2024.csv"
PACW_HOURLY = ROOT / "data" / "processed" / "pacw_hourly.csv"
OUT = ROOT / "outputs"

PROVENANCE = {
    "arrivals": "scenario: scale-free Cox-process work arrivals",
    "execution": "scenario: aggregate queue/service policy",
    "it_power": "fitted: stochastic shape scaled to annual facility-electricity closure",
    "facility_power": "fitted: annual closure + scenario overhead priors",
    "water_closure": "fitted: hourly shape closed to reported annual site withdrawal",
    "water_prediction": "fitted: train-only annual scale; no target-year water used",
    "carbon": (
        "fitted proxy: PACW regional physical carbon shape closed to Meta annual "
        "location Scope 2; prefers EIA-reported consumed CO2 intensity when present, "
        "else the named fuel/import sensitivity proxy; not Meta-specific marginal emissions"
    ),
}


@dataclass(frozen=True)
class WorkloadScenario:
    name: str
    diurnal_amplitude: float
    weekend_drop: float
    ar_rho: float
    ar_sigma: float
    interactive_share: float
    batch_capacity_margin: float
    idle_power_fraction: float
    power_exponent: float


SCENARIOS = {
    "mixed_cox": WorkloadScenario(
        "mixed_cox", 0.18, 0.04, 0.94, 0.10, 0.72, 1.30, 0.36, 0.90
    ),
    "steady_service": WorkloadScenario(
        "steady_service", 0.06, 0.01, 0.85, 0.035, 0.82, 1.45, 0.40, 0.95
    ),
    "bursty_arrivals": WorkloadScenario(
        "bursty_arrivals", 0.24, 0.06, 0.97, 0.18, 0.68, 1.25, 0.33, 0.85
    ),
    "flexible_batch": WorkloadScenario(
        "flexible_batch", 0.18, 0.04, 0.94, 0.10, 0.50, 1.55, 0.36, 0.90
    ),
}


def _safe_quantile(x: np.ndarray, q: float, fallback: float = 1.0) -> float:
    z = x[np.isfinite(x)]
    if not len(z):
        return fallback
    value = float(np.quantile(z, q))
    return value if value > 0 else fallback


def load_weather() -> tuple[pd.DataFrame, dict]:
    """Load a complete weather driver and flag every proxy-filled hour.

    The bundled processed series has very sparse missing psychrometric fields.
    Two-hour interpolation is followed by month-hour climatology only so the
    simulation remains executable.  This is explicitly a proxy fill, not a
    replacement for the missing secondary-station acquisition in the protocol.
    """

    w = pd.read_csv(WEATHER)
    w["timestamp_utc"] = pd.to_datetime(w["timestamp_utc"], utc=True)
    w = w.sort_values("timestamp_utc").reset_index(drop=True)
    required = ["t_db_C", "t_wb_C", "rh_pct", "pressure_Pa"]
    missing_before = w[required].isna().any(axis=1)
    original_missing_cells = int(w[required].isna().sum().sum())

    for col in required:
        w[col] = w[col].interpolate(limit=2, limit_area="inside")
        climatology = w.groupby(
            [w["timestamp_utc"].dt.month, w["timestamp_utc"].dt.hour]
        )[col].transform("median")
        w[col] = w[col].fillna(climatology).fillna(w[col].median())

    if w[required].isna().any().any():
        raise ValueError("Weather proxy filling did not produce a complete driver.")
    w["weather_gap_filled"] = missing_before
    w["weather_driver_provenance"] = np.where(
        missing_before,
        "proxy-filled from short interpolation/month-hour climatology",
        "canonical KS39/KRDM weather; measured station observation with derived psychrometrics",
    )
    if "year_local" in w.columns and w["year_local"].notna().all():
        w["year"] = pd.to_numeric(w["year_local"], errors="coerce").astype(int)
    else:
        w["year"] = w["timestamp_utc"].dt.tz_convert("America/Los_Angeles").dt.year
    diagnostics = {
        "weather_rows": int(len(w)),
        "hours_with_any_required_field_missing_before_fill": int(missing_before.sum()),
        "missing_required_cells_before_fill": original_missing_cells,
        "fraction_hours_proxy_filled": float(missing_before.mean()),
    }
    return w, diagnostics


def precompute_weather_coefficients(w: pd.DataFrame) -> dict[int, pd.DataFrame]:
    """Precompute per-MW facility and water coefficients for each year."""

    coeffs: dict[int, pd.DataFrame] = {}
    for year, wy in w.groupby("year"):
        wy = wy.copy().reset_index(drop=True)
        # fan/other are zero here; those uncertain priors are added per ensemble draw.
        unit = simulate(
            wy,
            1.0,
            params=Params(fan_fraction_of_it=0.0, other_facility_fraction_of_it=0.0),
        )
        c = wy[["timestamp_utc", "t_db_C", "t_wb_C", "rh_pct", "pressure_Pa",
                "weather_gap_filled", "weather_driver_provenance"]].copy()
        c["evap_aux_mw_per_mw_it"] = unit["p_evap_aux_mw"].to_numpy(float)
        c["raw_evap_m3_per_h_per_mw_it"] = unit["evap_water_m3_per_h"].to_numpy(float)
        c["cooling_mode"] = unit["cooling_mode"].astype(str).to_numpy()
        coeffs[int(year)] = c
    return coeffs


def simulate_workload(
    timestamps_utc: pd.Series,
    rng: np.random.Generator,
    scenario: WorkloadScenario,
) -> pd.DataFrame:
    """Generate scale-free Cox-process arrivals and a stable aggregate queue."""

    local = timestamps_utc.dt.tz_convert("America/Los_Angeles")
    hour = local.dt.hour.to_numpy(float)
    dow = local.dt.dayofweek.to_numpy(int)
    n = len(local)

    daily = (
        1.0
        + scenario.diurnal_amplitude
        * (
            0.65 * np.cos(2 * np.pi * (hour - 15.0) / 24.0)
            + 0.35 * np.cos(4 * np.pi * (hour - 15.0) / 24.0)
        )
    )
    weekly = np.where(dow >= 5, 1.0 - scenario.weekend_drop, 1.0)
    latent = np.zeros(n, dtype=float)
    latent[0] = float(rng.normal(0.0, scenario.ar_sigma))
    innovation_scale = scenario.ar_sigma * math.sqrt(max(1 - scenario.ar_rho**2, 1e-6))
    eps = rng.normal(0.0, innovation_scale, n)
    for t in range(1, n):
        latent[t] = scenario.ar_rho * latent[t - 1] + eps[t]
    intensity = np.maximum(daily * weekly * np.exp(latent), 0.05)
    intensity /= float(np.mean(intensity))

    # Counts and work units are deliberately scale-free scenario quantities.
    base_rate = 72.0
    interactive_rate = base_rate * scenario.interactive_share * intensity
    batch_rate = base_rate * (1.0 - scenario.interactive_share) * (
        1.05 - 0.15 * np.cos(2 * np.pi * (hour - 2.0) / 24.0)
    ) * np.exp(0.45 * latent)
    interactive_count = rng.poisson(np.maximum(interactive_rate, 1e-6))
    batch_count = rng.poisson(np.maximum(batch_rate, 1e-6))

    # Gamma compounding approximates a Poisson number of positive job sizes
    # without materializing millions of individual jobs.
    interactive_work = np.where(
        interactive_count > 0,
        rng.gamma(np.maximum(interactive_count * 2.0, 1e-6), 0.5),
        0.0,
    )
    batch_arrival_work = np.where(
        batch_count > 0,
        rng.gamma(np.maximum(batch_count * 1.4, 1e-6), 1.0 / 1.4),
        0.0,
    )

    interactive_norm = interactive_work / _safe_quantile(interactive_work, 0.99)
    batch_base_capacity = float(np.mean(batch_arrival_work)) * scenario.batch_capacity_margin
    batch_capacity = batch_base_capacity * np.clip(1.15 - 0.35 * interactive_norm, 0.55, 1.35)
    batch_service = np.zeros(n, dtype=float)
    backlog_start = np.zeros(n, dtype=float)
    backlog = np.zeros(n, dtype=float)
    # Stationary-style initialization avoids an artificial empty-queue startup.
    queue = float(rng.gamma(2.0, max(float(np.mean(batch_arrival_work)) / 2.0, 1e-6)))
    for t in range(n):
        backlog_start[t] = queue
        queue += float(batch_arrival_work[t])
        batch_service[t] = min(queue, float(batch_capacity[t]))
        queue -= batch_service[t]
        backlog[t] = queue

    executed = interactive_work + batch_service
    service_scale = _safe_quantile(executed, 0.995)
    utilization = np.clip(executed / service_scale, 0.0, 1.0)
    power_shape = scenario.idle_power_fraction + (
        1.0 - scenario.idle_power_fraction
    ) * np.power(utilization, scenario.power_exponent)
    power_shape /= float(np.mean(power_shape))

    return pd.DataFrame(
        {
            "timestamp_utc": timestamps_utc.to_numpy(),
            "interactive_arrivals": interactive_count,
            "batch_arrivals": batch_count,
            "interactive_work_units": interactive_work,
            "batch_arrival_work_units": batch_arrival_work,
            "batch_service_work_units": batch_service,
            "batch_backlog_start_work_units": backlog_start,
            "batch_backlog_work_units": backlog,
            "executed_work_units": executed,
            "utilization_index": utilization,
            "it_power_shape_index": power_shape,
            "workload_scenario": scenario.name,
        }
    )


def sampled_facility_priors(rng: np.random.Generator) -> tuple[float, float]:
    """Sample non-identifiable facility overhead fractions around the 2011 prior."""

    total = float(np.clip(rng.normal(0.065, 0.009), 0.045, 0.090))
    fan_share = float(np.clip(rng.beta(4.0, 5.0), 0.25, 0.65))
    return total * fan_share, total * (1.0 - fan_share)


def close_facility_energy(
    target_mwh: float,
    workload: pd.DataFrame,
    weather_coeff: pd.DataFrame,
    fan_fraction: float,
    other_fraction: float,
) -> pd.DataFrame:
    """Scale the stochastic IT shape to exact reported annual facility MWh."""

    pit_shape = workload["it_power_shape_index"].to_numpy(float)
    evap_aux_coeff = weather_coeff["evap_aux_mw_per_mw_it"].to_numpy(float)
    facility_coeff = 1.0 + fan_fraction + other_fraction + evap_aux_coeff
    scale_mw = float(target_mwh) / float(np.sum(pit_shape * facility_coeff))
    pit = scale_mw * pit_shape
    fan = fan_fraction * pit
    other = other_fraction * pit
    evap_aux = evap_aux_coeff * pit
    pfac = pit + fan + other + evap_aux
    raw_evap = (
        weather_coeff["raw_evap_m3_per_h_per_mw_it"].to_numpy(float) * pit
    )

    out = workload.copy()
    out["p_it_mw"] = pit
    out["p_fan_mw"] = fan
    out["p_other_mw"] = other
    out["p_evap_aux_mw"] = evap_aux
    out["p_fac_mw"] = pfac
    out["pue"] = np.divide(pfac, pit, out=np.full_like(pfac, np.nan), where=pit > 0)
    out["raw_evap_m3_per_h"] = raw_evap
    out["cooling_mode"] = weather_coeff["cooling_mode"].to_numpy()
    out["t_db_C"] = weather_coeff["t_db_C"].to_numpy(float)
    out["t_wb_C"] = weather_coeff["t_wb_C"].to_numpy(float)
    out["weather_gap_filled"] = weather_coeff["weather_gap_filled"].to_numpy(bool)
    out["weather_driver_provenance"] = weather_coeff[
        "weather_driver_provenance"
    ].to_numpy()
    out["it_power_provenance"] = PROVENANCE["it_power"]
    out["facility_power_provenance"] = PROVENANCE["facility_power"]
    return out


def water_shape_weights(
    hourly: pd.DataFrame, rng: np.random.Generator
) -> tuple[np.ndarray, dict]:
    """Create a boundary-explicit mixture for retrospective withdrawal shape."""

    # Annual public data cannot identify this decomposition.  The prior keeps
    # weather-responsive cooling important without letting the instantaneous
    # humidification proxy place nearly all annual withdrawal in a few hot hours.
    evap_share = float(np.clip(rng.normal(0.52, 0.10), 0.25, 0.75))
    base_share = float(np.clip(rng.normal(0.10, 0.04), 0.03, 0.22))
    it_share = 1.0 - evap_share - base_share
    if it_share < 0.03:
        it_share = 0.03
        evap_share = 1.0 - base_share - it_share

    evap = (
        hourly["raw_evap_m3_per_h"]
        .rolling(6, center=True, min_periods=1)
        .mean()
        .to_numpy(float)
    )
    pit = hourly["p_it_mw"].to_numpy(float)
    evap_w = evap / max(float(np.sum(evap)), 1e-12)
    it_w = pit / max(float(np.sum(pit)), 1e-12)
    base_w = np.full(len(hourly), 1.0 / len(hourly))
    weights = evap_share * evap_w + it_share * it_w + base_share * base_w
    weights /= float(np.sum(weights))
    return weights, {
        "water_shape_evap_share": evap_share,
        "water_shape_it_proportional_share": it_share,
        "water_shape_time_constant_share": base_share,
    }


def _pacw_fuel_import_proxy_score(z: pd.DataFrame) -> pd.Series:
    """Named sensitivity proxy from PACW fuel mix plus a residual import score.

    This is not EIA's reported CO2 intensity and is not a marginal-emissions series.
    """
    thermal_kg_proxy = (
        1000.0 * z.get("ng_col_mwh", pd.Series(0.0, index=z.index)).fillna(0.0).clip(lower=0.0)
        + 450.0 * z.get("ng_ng_mwh", pd.Series(0.0, index=z.index)).fillna(0.0).clip(lower=0.0)
        + 500.0 * z.get("ng_oth_mwh", pd.Series(0.0, index=z.index)).fillna(0.0).clip(lower=0.0)
    )
    demand = z["demand_reported_mwh"].clip(lower=1.0)
    net_generation = z["net_generation_reported_mwh"].fillna(0.0).clip(lower=0.0)
    import_residual = (demand - net_generation).clip(lower=0.0)
    return (thermal_kg_proxy.fillna(0.0) + 350.0 * import_residual) / demand


def build_pacw_relative_carbon_shape() -> dict[int, pd.DataFrame]:
    """Build a relative regional carbon-shape series from PACW EIA-930.

    Prefer EIA-reported `co2_intensity_consumed` when it is present and valid.
    Retain the fuel/import score only as `pacw_fuel_import_proxy_score`. Campus
    emissions are still renormalized to Meta's reported annual location-based
    Scope 2. Neither series is Meta-specific marginal emissions.
    """

    if PACW_HOURLY.exists():
        z = pd.read_csv(PACW_HOURLY)
        z["timestamp_utc"] = pd.to_datetime(z["timestamp_utc"], utc=True)
        fuel_proxy = _pacw_fuel_import_proxy_score(z).replace([np.inf, -np.inf], np.nan)
        eia = pd.to_numeric(z.get("co2_intensity_consumed"), errors="coerce")
        eia = eia.where(np.isfinite(eia) & (eia > 0))
        preferred = eia.where(eia.notna(), fuel_proxy)
        preferred.index = z["timestamp_utc"]
        fuel_proxy.index = z["timestamp_utc"]
        eia.index = z["timestamp_utc"]
        preferred = preferred.fillna(preferred.groupby(preferred.index.year).transform("median"))
        source = np.where(
            eia.notna().to_numpy(),
            "eia_co2_intensity_consumed",
            np.where(fuel_proxy.notna().to_numpy(), "fuel_import_proxy", "unavailable"),
        )
        out: dict[int, pd.DataFrame] = {}
        for year, s in preferred.groupby(preferred.index.year):
            idx = s.index
            out[int(year)] = pd.DataFrame(
                {
                    "timestamp_utc": idx,
                    "pacw_relative_carbon_score": s.to_numpy(float),
                    "pacw_eia_co2_intensity_consumed": eia.reindex(idx).to_numpy(float),
                    "pacw_fuel_import_proxy_score": fuel_proxy.reindex(idx).to_numpy(float),
                    "pacw_carbon_shape_source": pd.Series(source, index=preferred.index).reindex(idx).to_numpy(),
                }
            )
        return out

    if not (EIA_REGION.exists() and EIA_FUEL.exists()):
        return {}
    region = pd.read_csv(EIA_REGION)
    fuel = pd.read_csv(EIA_FUEL)
    region["timestamp_utc"] = pd.to_datetime(region["period"], utc=True)
    fuel["timestamp_utc"] = pd.to_datetime(fuel["period"], utc=True)
    rp = region.pivot(index="timestamp_utc", columns="type-name", values="value")
    fp = fuel.pivot(index="timestamp_utc", columns="type-name", values="value")
    for col in ["Coal", "Natural Gas", "Other"]:
        if col not in fp:
            fp[col] = 0.0
    # EIA may omit rows for categories reporting zero; preserve that assumption
    # explicitly here instead of silently treating missing categories as measured.
    thermal_kg_proxy = (
        1000.0 * fp["Coal"].fillna(0.0).clip(lower=0.0)
        + 450.0 * fp["Natural Gas"].fillna(0.0).clip(lower=0.0)
        + 500.0 * fp["Other"].fillna(0.0).clip(lower=0.0)
    )
    demand = rp.get("Demand", pd.Series(index=rp.index, dtype=float)).clip(lower=1.0)
    net_generation = rp.get(
        "Net generation", pd.Series(0.0, index=rp.index, dtype=float)
    ).clip(lower=0.0)
    import_residual = (demand - net_generation).clip(lower=0.0)
    # A neutral import score keeps interchange in the relative shape without
    # pretending the source generators are known.
    score = thermal_kg_proxy.reindex(demand.index).fillna(0.0) + 350.0 * import_residual
    relative = (score / demand).replace([np.inf, -np.inf], np.nan)
    relative = relative.fillna(relative.groupby(relative.index.year).transform("median"))

    out: dict[int, pd.DataFrame] = {}
    for year, s in relative.groupby(relative.index.year):
        z = pd.DataFrame(
            {
                "timestamp_utc": s.index,
                "pacw_relative_carbon_score": s.to_numpy(float),
                "pacw_eia_co2_intensity_consumed": np.nan,
                "pacw_fuel_import_proxy_score": s.to_numpy(float),
                "pacw_carbon_shape_source": "fuel_import_proxy",
            }
        )
        out[int(year)] = z
    return out


def add_carbon_closure(
    hourly: pd.DataFrame,
    annual_tco2e: float | None,
    pacw_shape: pd.DataFrame | None,
) -> pd.DataFrame:
    """Attach an hourly location-emissions proxy that closes annual disclosure."""

    out = hourly.copy()
    if annual_tco2e is None or not np.isfinite(annual_tco2e):
        out["location_emissions_kgco2e"] = np.nan
        out["location_intensity_proxy_kg_per_mwh"] = np.nan
        out["carbon_provenance"] = "not available: no annual site target"
        return out

    pfac = out["p_fac_mw"].to_numpy(float)
    if pacw_shape is not None:
        proxy = out[["timestamp_utc"]].merge(
            pacw_shape, on="timestamp_utc", how="left"
        )["pacw_relative_carbon_score"].to_numpy(float)
        fill = float(np.nanmedian(proxy)) if np.isfinite(proxy).any() else 1.0
        proxy = np.where(np.isfinite(proxy) & (proxy > 0), proxy, fill)
        source = PROVENANCE["carbon"]
    else:
        proxy = np.ones(len(out), dtype=float)
        source = (
            "fitted proxy: constant within-year intensity closed to Meta annual "
            "location Scope 2; PACW hourly shape unavailable"
        )
    scale = float(annual_tco2e) * 1000.0 / float(np.sum(pfac * proxy))
    intensity = proxy * scale
    out["location_intensity_proxy_kg_per_mwh"] = intensity
    out["location_emissions_kgco2e"] = pfac * intensity
    out["carbon_provenance"] = source
    return out


WATER_CANDIDATES = {
    "energy_null": ["electricity_mwh_reported"],
    "evap_physics": ["raw_evap_m3_median"],
    "two_component": ["electricity_mwh_reported", "raw_evap_m3_median"],
}


def fit_nonnegative_water_coefficients(
    data: pd.DataFrame, features: list[str]
) -> np.ndarray:
    """Fit a no-intercept nonnegative annual water model with scaled columns."""

    x = data[features].to_numpy(float)
    y = data["water_withdrawal_m3_reported"].to_numpy(float)
    scale = np.linalg.norm(x, axis=0)
    scale[scale == 0] = 1.0
    beta_scaled, _ = nnls(x / scale, y)
    return beta_scaled / scale


def rolling_candidate_score(
    train: pd.DataFrame,
    features: list[str],
    min_history: int = 3,
) -> float:
    """Expanding-window one-step MAPE using only prior training years."""

    errors: list[float] = []
    for i in range(min_history, len(train)):
        history = train.iloc[:i]
        beta = fit_nonnegative_water_coefficients(history, features)
        pred = float((train.iloc[[i]][features].to_numpy(float) @ beta).item())
        observed = float(train.iloc[i]["water_withdrawal_m3_reported"])
        errors.append(abs(pred / observed - 1.0) * 100.0)
    return float(np.mean(errors)) if errors else np.nan


def select_train_only_water_model(
    annual_features: pd.DataFrame, train_end_year: int
) -> tuple[dict, pd.DataFrame]:
    """Select among pre-registered nonnegative models without holdout leakage."""

    train = annual_features[
        (annual_features["year"] <= train_end_year)
        & annual_features["water_withdrawal_m3_reported"].notna()
    ].sort_values("year")
    years = train["year"].to_numpy(int)
    raw = train["raw_evap_m3_median"].to_numpy(float)
    obs = train["water_withdrawal_m3_reported"].to_numpy(float)
    if len(train) < 4 or np.any(raw <= 0) or np.any(obs <= 0):
        raise ValueError("Insufficient positive training years for water calibration.")

    rows = []
    for name, features in WATER_CANDIDATES.items():
        score = rolling_candidate_score(train, features)
        beta = fit_nonnegative_water_coefficients(train, features)
        rows.append(
            {
                "model": name,
                "features": ";".join(features),
                "n_coefficients": len(features),
                "rolling_one_step_mape_pct": score,
                "coefficients": json.dumps(
                    {feature: float(value) for feature, value in zip(features, beta)}
                ),
            }
        )
    diagnostics = pd.DataFrame(rows).sort_values(
        ["rolling_one_step_mape_pct", "n_coefficients", "model"]
    ).reset_index(drop=True)
    selected = str(diagnostics.iloc[0]["model"])
    features = WATER_CANDIDATES[selected]
    beta = fit_nonnegative_water_coefficients(train, features)
    model = {
        "model": selected,
        "features": features,
        "coefficients": {
            feature: float(value) for feature, value in zip(features, beta)
        },
        "train_start_year": int(years.min()),
        "train_end_year": int(train_end_year),
        "selection_metric": (
            "expanding-window one-step MAPE on training years only; "
            "pre-registered nonnegative no-intercept candidates"
        ),
        "selection_score_pct": float(diagnostics.iloc[0]["rolling_one_step_mape_pct"]),
    }
    diagnostics["selected"] = diagnostics["model"].eq(selected)
    return model, diagnostics


def predictive_water_draws(
    row: pd.Series,
    train: pd.DataFrame,
    model: dict,
    raw_draws: np.ndarray,
    rng: np.random.Generator,
    n_draws: int = 800,
) -> np.ndarray:
    """Generate a broad annual predictive distribution for water withdrawal."""

    features = list(model["features"])
    beta = np.array([model["coefficients"][feature] for feature in features], dtype=float)
    fitted = train[features].to_numpy(float) @ beta
    log_residuals = np.log(
        train["water_withdrawal_m3_reported"].to_numpy(float)
        / np.maximum(fitted, 1e-12)
    )
    draws = np.empty(n_draws, dtype=float)
    for i in range(n_draws):
        sample_idx = rng.integers(0, len(train), len(train))
        bootstrap = train.iloc[sample_idx]
        beta_draw = fit_nonnegative_water_coefficients(bootstrap, features)
        target_values = []
        for feature in features:
            if feature == "raw_evap_m3_median":
                target_values.append(float(rng.choice(raw_draws)))
            else:
                target_values.append(float(row[feature]))
        point = float(np.asarray(target_values) @ beta_draw)
        draws[i] = point * math.exp(float(rng.choice(log_residuals)))
    return np.maximum(draws, 0.0)


def summarize_ensemble(
    targets: pd.DataFrame,
    runs: pd.DataFrame,
    train_end_year: int,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    """Create annual point/interval results and train-only water diagnostics."""

    def q05(x: pd.Series) -> float:
        return float(x.quantile(0.05))

    def q50(x: pd.Series) -> float:
        return float(x.quantile(0.50))

    def q95(x: pd.Series) -> float:
        return float(x.quantile(0.95))

    agg = runs.groupby("year").agg(
        electricity_mwh_model_median=("facility_energy_mwh", q50),
        it_energy_mwh_p05=("it_energy_mwh", q05),
        it_energy_mwh_median=("it_energy_mwh", q50),
        it_energy_mwh_p95=("it_energy_mwh", q95),
        annual_pue_p05=("annual_pue", q05),
        annual_pue_median=("annual_pue", q50),
        annual_pue_p95=("annual_pue", q95),
        facility_peak_mw_p05=("facility_peak_mw", q05),
        facility_peak_mw_median=("facility_peak_mw", q50),
        facility_peak_mw_p95=("facility_peak_mw", q95),
        facility_peak_to_mean_median=("facility_peak_to_mean", q50),
        raw_evap_m3_p05=("raw_evap_m3", q05),
        raw_evap_m3_median=("raw_evap_m3", q50),
        raw_evap_m3_p95=("raw_evap_m3", q95),
        arrival_cv_median=("arrival_cv", q50),
        terminal_backlog_p95=("terminal_backlog_work_units", q95),
        january_it_scale_jump_pct_median=("january_it_scale_jump_pct", q50),
    ).reset_index()
    annual = targets.merge(agg, on="year", how="left")
    annual["electricity_closure_error_pct"] = 100.0 * (
        annual["electricity_mwh_model_median"] - annual["electricity_mwh_reported"]
    ) / annual["electricity_mwh_reported"]
    annual["water_retrospective_closure_m3"] = annual[
        "water_withdrawal_m3_reported"
    ]
    annual["water_retrospective_provenance"] = np.where(
        annual["water_withdrawal_m3_reported"].notna(),
        "fitted annual closure; not prediction",
        "no annual site observation; scenario only",
    )
    annual["location_scope2_retrospective_closure_tco2e"] = annual[
        "location_based_scope2_tco2e_reported"
    ]
    annual["location_scope2_retrospective_provenance"] = np.where(
        annual["location_based_scope2_tco2e_reported"].notna(),
        "fitted hourly proxy can close to reported annual location Scope 2",
        "no annual location Scope 2 target",
    )

    model, diagnostics = select_train_only_water_model(annual, train_end_year)
    train = annual[
        (annual["year"] <= train_end_year)
        & annual["water_withdrawal_m3_reported"].notna()
    ].copy()

    pred_rows = []
    for _, row in annual.iterrows():
        raw_draws = runs.loc[runs["year"].eq(row["year"]), "raw_evap_m3"].to_numpy(float)
        draws = predictive_water_draws(
            row, train, model, raw_draws, rng, n_draws=800
        )
        pred_rows.append(
            {
                "year": int(row["year"]),
                "water_train_only_pred_m3_p05": float(np.quantile(draws, 0.05)),
                "water_train_only_pred_m3_median": float(np.quantile(draws, 0.50)),
                "water_train_only_pred_m3_p95": float(np.quantile(draws, 0.95)),
            }
        )
    annual = annual.merge(pd.DataFrame(pred_rows), on="year", how="left")
    annual["water_train_only_error_pct"] = 100.0 * (
        annual["water_train_only_pred_m3_median"]
        - annual["water_withdrawal_m3_reported"]
    ) / annual["water_withdrawal_m3_reported"]
    annual["split"] = np.where(annual["year"] <= train_end_year, "train", "holdout")
    return annual, model, diagnostics


def annual_run_record(year: int, simulation_id: int, hourly: pd.DataFrame) -> dict:
    arrivals = (
        hourly["interactive_arrivals"].to_numpy(float)
        + hourly["batch_arrivals"].to_numpy(float)
    )
    mean_arrivals = float(np.mean(arrivals))
    facility_mean = float(hourly["p_fac_mw"].mean())
    return {
        "year": int(year),
        "simulation_id": int(simulation_id),
        "facility_energy_mwh": float(hourly["p_fac_mw"].sum()),
        "it_energy_mwh": float(hourly["p_it_mw"].sum()),
        "annual_pue": float(hourly["p_fac_mw"].sum() / hourly["p_it_mw"].sum()),
        "facility_peak_mw": float(hourly["p_fac_mw"].max()),
        "facility_peak_to_mean": float(hourly["p_fac_mw"].max() / facility_mean),
        "raw_evap_m3": float(hourly["raw_evap_m3_per_h"].sum()),
        "arrival_cv": float(np.std(arrivals) / mean_arrivals) if mean_arrivals > 0 else np.nan,
        "terminal_backlog_work_units": float(hourly["batch_backlog_work_units"].iloc[-1]),
        "first_backlog_start_work_units": float(
            hourly["batch_backlog_start_work_units"].iloc[0]
        ),
        "first_it_mw": float(hourly["p_it_mw"].iloc[0]),
        "last_it_mw": float(hourly["p_it_mw"].iloc[-1]),
    }


def make_representative_hourly(
    hourly: pd.DataFrame,
    target: pd.Series,
    rng: np.random.Generator,
    pacw_shape: pd.DataFrame | None,
) -> tuple[pd.DataFrame, dict]:
    """Add annual-closure water and carbon to one representative path."""

    out = hourly.copy()
    water_target = target["water_withdrawal_m3_reported"]
    water_priors: dict = {}
    if pd.notna(water_target):
        weights, water_priors = water_shape_weights(out, rng)
        out["water_withdrawal_proxy_m3_per_h"] = weights * float(water_target)
        out["water_provenance"] = PROVENANCE["water_closure"]
    else:
        out["water_withdrawal_proxy_m3_per_h"] = np.nan
        out["water_provenance"] = "not produced: annual site withdrawal unavailable"
    loc = target["location_based_scope2_tco2e_reported"]
    loc_target = float(loc) if pd.notna(loc) else None
    out = add_carbon_closure(out, loc_target, pacw_shape)
    out["arrival_provenance"] = PROVENANCE["arrivals"]
    out["execution_provenance"] = PROVENANCE["execution"]
    return out, water_priors


def simulate_scenario_comparison(
    year: int,
    target: pd.Series,
    coeff: pd.DataFrame,
    pacw_shape: pd.DataFrame | None,
    seed: int,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    rows = []
    paths: dict[str, pd.DataFrame] = {}
    for j, name in enumerate(["steady_service", "mixed_cox", "bursty_arrivals", "flexible_batch"]):
        scenario = SCENARIOS[name]
        rng = np.random.default_rng(seed + 100_000 + j)
        work = simulate_workload(coeff["timestamp_utc"], rng, scenario)
        fan, other = 0.030, 0.035
        h = close_facility_energy(
            float(target["electricity_mwh_reported"]), work, coeff, fan, other
        )
        # Hold water-component shares fixed across scenarios so the comparison
        # isolates workload/queue shape rather than a different nuisance draw.
        water_rng = np.random.default_rng(seed + 200_000)
        h, _ = make_representative_hourly(h, target, water_rng, pacw_shape)
        paths[name] = h
        facility_mean = float(h["p_fac_mw"].mean())
        rows.append(
            {
                "year": int(year),
                "scenario": name,
                "facility_energy_mwh": float(h["p_fac_mw"].sum()),
                "it_energy_mwh": float(h["p_it_mw"].sum()),
                "annual_pue": float(h["p_fac_mw"].sum() / h["p_it_mw"].sum()),
                "facility_mean_mw": facility_mean,
                "facility_p95_mw": float(h["p_fac_mw"].quantile(0.95)),
                "facility_peak_mw": float(h["p_fac_mw"].max()),
                "facility_peak_to_mean": float(h["p_fac_mw"].max() / facility_mean),
                "it_ramp_p99_mw_per_h": float(h["p_it_mw"].diff().abs().quantile(0.99)),
                "arrival_cv": float(
                    (
                        h["interactive_arrivals"] + h["batch_arrivals"]
                    ).std()
                    / (h["interactive_arrivals"] + h["batch_arrivals"]).mean()
                ),
                "backlog_p95_work_units": float(
                    h["batch_backlog_work_units"].quantile(0.95)
                ),
                "water_peak_m3_per_h": float(
                    h["water_withdrawal_proxy_m3_per_h"].max()
                ),
                "location_emissions_tco2e": float(
                    h["location_emissions_kgco2e"].sum() / 1000.0
                ),
                "provenance": "scenario comparison with identical annual observed closures",
            }
        )
    return pd.DataFrame(rows), paths


def run_checks(
    targets: pd.DataFrame,
    runs: pd.DataFrame,
    representative: pd.DataFrame,
    selected_year: int,
) -> list[dict]:
    checks: list[dict] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "status": "PASS" if passed else "FAIL", "detail": detail})
        if not passed:
            raise AssertionError(f"{name}: {detail}")

    joined = runs.merge(
        targets[["year", "electricity_mwh_reported"]], on="year", how="left"
    )
    closure_error = np.max(
        np.abs(joined["facility_energy_mwh"] - joined["electricity_mwh_reported"])
    )
    add("all_ensemble_electricity_closures", closure_error < 1e-5, f"max_abs_mwh={closure_error:.3e}")
    add(
        "nonnegative_power_and_water",
        bool(
            (representative[["p_it_mw", "p_fac_mw", "raw_evap_m3_per_h"]]
             .to_numpy(float) >= 0).all()
        ),
        f"selected_year={selected_year}",
    )
    add(
        "nonnegative_queue",
        bool((representative["batch_backlog_work_units"] >= -1e-12).all()),
        f"min_backlog={representative['batch_backlog_work_units'].min():.3e}",
    )
    conservation_error = np.max(
        np.abs(
            representative["batch_backlog_start_work_units"]
            + representative["batch_arrival_work_units"]
            - representative["batch_service_work_units"]
            - representative["batch_backlog_work_units"]
        )
    )
    add(
        "queue_conservation",
        bool(conservation_error < 1e-10),
        f"max_abs_work_units={conservation_error:.3e}",
    )
    previous_backlog = runs.groupby("simulation_id")[
        "terminal_backlog_work_units"
    ].shift(1)
    boundary_error = (
        runs.loc[previous_backlog.notna(), "first_backlog_start_work_units"]
        - previous_backlog[previous_backlog.notna()]
    ).abs().max()
    add(
        "queue_state_carried_across_years",
        bool(boundary_error < 1e-10),
        f"max_abs_work_units={boundary_error:.3e}",
    )
    target = targets.loc[targets["year"].eq(selected_year)].iloc[0]
    if pd.notna(target["water_withdrawal_m3_reported"]):
        water_error = abs(
            representative["water_withdrawal_proxy_m3_per_h"].sum()
            - float(target["water_withdrawal_m3_reported"])
        )
        add("representative_water_closure", water_error < 1e-6, f"abs_m3={water_error:.3e}")
    if pd.notna(target["location_based_scope2_tco2e_reported"]):
        carbon_error = abs(
            representative["location_emissions_kgco2e"].sum() / 1000.0
            - float(target["location_based_scope2_tco2e_reported"])
        )
        add("representative_carbon_closure", carbon_error < 1e-6, f"abs_tco2e={carbon_error:.3e}")
    add(
        "required_provenance_columns",
        all(
            c in representative
            for c in [
                "arrival_provenance",
                "it_power_provenance",
                "water_provenance",
                "carbon_provenance",
            ]
        ),
        "arrival, IT, water, and carbon provenance present",
    )
    return checks


def plot_annual_summary(annual: pd.DataFrame, train_end_year: int, path: Path) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(11, 12), constrained_layout=True)
    years = annual["year"].to_numpy(int)

    axes[0].plot(
        years, annual["electricity_mwh_reported"] / 1000.0,
        marker="o", label="Reported facility electricity"
    )
    axes[0].plot(
        years, annual["it_energy_mwh_median"] / 1000.0,
        marker=".", label="Fitted IT energy median"
    )
    axes[0].fill_between(
        years,
        annual["it_energy_mwh_p05"] / 1000.0,
        annual["it_energy_mwh_p95"] / 1000.0,
        alpha=0.2,
        label="IT energy 5–95%",
    )
    axes[0].set(title="Annual facility closure and fitted IT-energy range",
                xlabel="Calendar year", ylabel="Energy (GWh)")
    axes[0].legend()
    axes[0].grid(alpha=0.25)

    obs = annual["water_withdrawal_m3_reported"] / 1000.0
    pred = annual["water_train_only_pred_m3_median"] / 1000.0
    lo = annual["water_train_only_pred_m3_p05"] / 1000.0
    hi = annual["water_train_only_pred_m3_p95"] / 1000.0
    axes[1].plot(years, obs, marker="o", label="Reported site withdrawal")
    axes[1].plot(years, pred, marker=".", label="Train-only stochastic proxy median")
    axes[1].fill_between(years, lo, hi, alpha=0.2, label="Predictive 5–95%")
    axes[1].axvline(train_end_year + 0.5, linestyle="--", linewidth=1, label="Holdout begins")
    axes[1].set(title="Annual water diagnostic: prediction kept separate from closure",
                xlabel="Calendar year", ylabel="Water withdrawal (thousand m³)")
    axes[1].legend()
    axes[1].grid(alpha=0.25)

    axes[2].plot(years, annual["annual_pue_median"], marker="o", label="Fitted PUE median")
    axes[2].fill_between(
        years, annual["annual_pue_p05"], annual["annual_pue_p95"],
        alpha=0.2, label="PUE 5–95%"
    )
    axes[2].axhline(1.07, linestyle="--", linewidth=1, label="2011 full-load design benchmark")
    axes[2].set(title="PUE uncertainty induced by non-identifiable overhead priors",
                xlabel="Calendar year", ylabel="PUE (facility MWh / IT MWh)")
    axes[2].legend()
    axes[2].grid(alpha=0.25)

    fig.suptitle(
        "Meta Prineville conditional stochastic proxy\n"
        "Sources: Meta annual disclosures, canonical KS39/KRDM weather; fitted quantities are not telemetry",
        fontsize=13,
    )
    fig.savefig(path, dpi=170)
    plt.close(fig)


def plot_representative_week(hourly: pd.DataFrame, year: int, path: Path) -> None:
    rolling = hourly["water_withdrawal_proxy_m3_per_h"].rolling(24 * 7, min_periods=1).sum()
    end = int(rolling.idxmax())
    start = max(0, end - 24 * 7 + 1)
    week = hourly.iloc[start : start + 24 * 7].copy()
    ts = pd.to_datetime(week["timestamp_utc"], utc=True)

    fig, axes = plt.subplots(3, 1, figsize=(13, 10), sharex=True, constrained_layout=True)
    axes[0].plot(ts, week["interactive_work_units"], label="Interactive arrivals (work units)", alpha=0.8)
    axes[0].plot(ts, week["batch_service_work_units"], label="Batch service (work units)", alpha=0.8)
    axes[0].set(ylabel="Synthetic work units", title=f"Representative high-water week, {year}")
    axes[0].legend()
    axes[0].grid(alpha=0.25)

    axes[1].plot(ts, week["p_it_mw"], label="Fitted IT power")
    axes[1].plot(ts, week["p_fac_mw"], label="Fitted facility power")
    axes[1].set(ylabel="Power (MW)")
    axes[1].legend()
    axes[1].grid(alpha=0.25)

    axes[2].plot(ts, week["water_withdrawal_proxy_m3_per_h"], label="Withdrawal proxy")
    ax2 = axes[2].twinx()
    ax2.plot(ts, week["t_wb_C"], color="tab:orange", alpha=0.65, label="canonical KS39/KRDM wet bulb")
    axes[2].set(xlabel="UTC timestamp", ylabel="Water (m³/hour)")
    ax2.set_ylabel("Wet-bulb temperature (°C)")
    lines, labels = axes[2].get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    axes[2].legend(lines + lines2, labels + labels2, loc="upper left")
    axes[2].grid(alpha=0.25)

    fig.suptitle(
        "Synthetic workload and physics-shaped operations\n"
        "Annual electricity and water close to observations; hourly values are conditional scenarios",
        fontsize=13,
    )
    fig.savefig(path, dpi=170)
    plt.close(fig)


def plot_scenario_comparison(comparison: pd.DataFrame, year: int, path: Path) -> None:
    labels = comparison["scenario"].str.replace("_", " ").to_list()
    x = np.arange(len(labels))
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.8), constrained_layout=True)
    axes[0].bar(x, comparison["facility_peak_to_mean"])
    axes[0].set(title="Facility peak-to-mean ratio", ylabel="Ratio", xticks=x, xticklabels=labels)
    axes[0].tick_params(axis="x", rotation=25)
    axes[0].grid(axis="y", alpha=0.25)
    axes[1].bar(x, comparison["it_ramp_p99_mw_per_h"])
    axes[1].set(title="99th-percentile IT ramp", ylabel="MW/hour", xticks=x, xticklabels=labels)
    axes[1].tick_params(axis="x", rotation=25)
    axes[1].grid(axis="y", alpha=0.25)
    axes[2].bar(x, comparison["water_peak_m3_per_h"])
    axes[2].set(title="Peak conditional withdrawal", ylabel="m³/hour", xticks=x, xticklabels=labels)
    axes[2].tick_params(axis="x", rotation=25)
    axes[2].grid(axis="y", alpha=0.25)
    fig.suptitle(
        f"{year} workload-scenario sensitivity with identical annual closures\n"
        "Differences are operational-shape consequences, not reconstructed history",
        fontsize=13,
    )
    fig.savefig(path, dpi=170)
    plt.close(fig)


def run(args: argparse.Namespace) -> dict:
    OUT.mkdir(exist_ok=True)
    targets = pd.read_csv(TARGETS)
    weather, weather_diagnostics = load_weather()
    coefficients = precompute_weather_coefficients(weather)
    pacw = build_pacw_relative_carbon_shape() if args.use_pacw_shape else {}
    rng_master = np.random.default_rng(args.seed)

    run_rows: list[dict] = []
    selected_paths: list[pd.DataFrame] = []
    selected_target = targets.loc[targets["year"].eq(args.selected_year)]
    if selected_target.empty:
        raise ValueError(f"Selected year {args.selected_year} is absent from targets.")

    all_coeff = pd.concat(
        [coefficients[int(year)].assign(year=int(year)) for year in targets["year"]],
        ignore_index=True,
    ).sort_values("timestamp_utc").reset_index(drop=True)

    # Workload state and backlog are simulated continuously across 2011-2024.
    # Annual facility-energy scaling is applied only after the continuous shape
    # exists, and any January discontinuity is reported as a closure artifact.
    for simulation_id in range(args.n_simulations):
        rng = np.random.default_rng(
            int(rng_master.integers(0, np.iinfo(np.int32).max))
        )
        base = SCENARIOS[args.scenario]
        scenario = WorkloadScenario(
            name=base.name,
            diurnal_amplitude=float(np.clip(rng.normal(base.diurnal_amplitude, 0.025), 0.0, 0.35)),
            weekend_drop=float(np.clip(rng.normal(base.weekend_drop, 0.015), 0.0, 0.15)),
            ar_rho=float(np.clip(rng.normal(base.ar_rho, 0.012), 0.75, 0.985)),
            ar_sigma=float(np.clip(rng.normal(base.ar_sigma, 0.02), 0.015, 0.25)),
            interactive_share=float(np.clip(rng.normal(base.interactive_share, 0.05), 0.35, 0.9)),
            batch_capacity_margin=float(np.clip(rng.normal(base.batch_capacity_margin, 0.06), 1.12, 1.7)),
            idle_power_fraction=float(np.clip(rng.normal(base.idle_power_fraction, 0.035), 0.25, 0.5)),
            power_exponent=float(np.clip(rng.normal(base.power_exponent, 0.05), 0.7, 1.1)),
        )
        workload_all = simulate_workload(all_coeff["timestamp_utc"], rng, scenario)
        for target in targets.itertuples(index=False):
            year = int(target.year)
            mask = all_coeff["year"].eq(year).to_numpy()
            coeff = all_coeff.loc[mask].drop(columns=["year"]).reset_index(drop=True)
            workload = workload_all.loc[mask].reset_index(drop=True)
            fan, other = sampled_facility_priors(rng)
            hourly = close_facility_energy(
                float(target.electricity_mwh_reported),
                workload,
                coeff,
                fan,
                other,
            )
            run_rows.append(annual_run_record(year, simulation_id, hourly))
            if year == args.selected_year:
                selected_paths.append(hourly)

    runs = pd.DataFrame(run_rows).sort_values(["simulation_id", "year"]).reset_index(drop=True)
    previous_last = runs.groupby("simulation_id")["last_it_mw"].shift(1)
    runs["january_it_scale_jump_pct"] = 100.0 * (
        runs["first_it_mw"] - previous_last
    ) / previous_last
    annual, water_model, water_diagnostics = summarize_ensemble(
        targets, runs, args.train_end_year, rng_master
    )
    representative_base = selected_paths[0]
    target_row = targets.loc[targets["year"].eq(args.selected_year)].iloc[0]
    representative, water_shape_priors = make_representative_hourly(
        representative_base,
        target_row,
        np.random.default_rng(args.seed + 50_000),
        pacw.get(args.selected_year),
    )

    comparison, scenario_paths = simulate_scenario_comparison(
        args.selected_year,
        target_row,
        coefficients[args.selected_year],
        pacw.get(args.selected_year),
        args.seed,
    )

    # Monthly uncertainty from all selected-year stochastic paths, each closing
    # to the same annual observed withdrawal with uncertain component shares.
    monthly_rows: list[dict] = []
    water_target = target_row["water_withdrawal_m3_reported"]
    if pd.notna(water_target):
        for simulation_id, h in enumerate(selected_paths):
            rng = np.random.default_rng(args.seed + 70_000 + simulation_id)
            weights, priors = water_shape_weights(h, rng)
            z = pd.DataFrame(
                {
                    "timestamp_utc": pd.to_datetime(h["timestamp_utc"], utc=True),
                    "water_m3": weights * float(water_target),
                }
            )
            z["month"] = z["timestamp_utc"].dt.month
            for month, value in z.groupby("month")["water_m3"].sum().items():
                monthly_rows.append(
                    {
                        "year": args.selected_year,
                        "month": int(month),
                        "simulation_id": simulation_id,
                        "water_withdrawal_proxy_m3": float(value),
                        **priors,
                    }
                )
    monthly = pd.DataFrame(monthly_rows)
    monthly_summary = (
        monthly.groupby(["year", "month"])["water_withdrawal_proxy_m3"]
        .quantile([0.05, 0.5, 0.95])
        .unstack()
        .rename(columns={0.05: "p05_m3", 0.5: "median_m3", 0.95: "p95_m3"})
        .reset_index()
        if len(monthly)
        else pd.DataFrame()
    )

    checks = run_checks(targets, runs, representative, args.selected_year)
    mutated_annual = annual.copy()
    holdout_mask = mutated_annual["year"] > args.train_end_year
    mutated_annual.loc[holdout_mask, "water_withdrawal_m3_reported"] *= 100.0
    mutated_model, _ = select_train_only_water_model(
        mutated_annual, args.train_end_year
    )
    leakage_free = mutated_model == water_model
    checks.append(
        {
            "check": "water_holdout_mutation_invariance",
            "status": "PASS" if leakage_free else "FAIL",
            "detail": "100x mutation of holdout water leaves selected model unchanged",
        }
    )
    if not leakage_free:
        raise AssertionError("water_holdout_mutation_invariance failed")
    annual_path = OUT / "stochastic_proxy_annual_summary.csv"
    runs_path = OUT / "stochastic_proxy_ensemble_runs.csv"
    hourly_path = OUT / f"stochastic_proxy_hourly_{args.selected_year}.csv"
    scenarios_path = OUT / f"stochastic_proxy_scenarios_{args.selected_year}.csv"
    monthly_path = OUT / f"stochastic_proxy_monthly_uncertainty_{args.selected_year}.csv"
    diagnostics_path = OUT / "stochastic_proxy_water_model_diagnostics.csv"
    checks_path = OUT / "stochastic_proxy_checks.csv"
    annual.to_csv(annual_path, index=False)
    runs.to_csv(runs_path, index=False)
    representative.to_csv(hourly_path, index=False)
    comparison.to_csv(scenarios_path, index=False)
    if len(monthly_summary):
        monthly_summary.to_csv(monthly_path, index=False)
    water_diagnostics.to_csv(diagnostics_path, index=False)
    pd.DataFrame(checks).to_csv(checks_path, index=False)

    annual_fig = OUT / "stochastic_proxy_annual_summary.png"
    week_fig = OUT / f"stochastic_proxy_week_{args.selected_year}.png"
    scenario_fig = OUT / f"stochastic_proxy_scenarios_{args.selected_year}.png"
    plot_annual_summary(annual, args.train_end_year, annual_fig)
    plot_representative_week(representative, args.selected_year, week_fig)
    plot_scenario_comparison(comparison, args.selected_year, scenario_fig)

    holdout = annual[
        annual["split"].eq("holdout")
        & annual["water_withdrawal_m3_reported"].notna()
    ]
    holdout_mape = float(holdout["water_train_only_error_pct"].abs().mean())
    summary = {
        "purpose": "conditional generative fit; not telemetry recovery or prediction",
        "seed": int(args.seed),
        "n_simulations_per_year": int(args.n_simulations),
        "workload_scenario": args.scenario,
        "continuous_workload_horizon": "2011-2024 with queue state carried across year boundaries",
        "selected_year": int(args.selected_year),
        "train_end_year": int(args.train_end_year),
        "water_model": water_model,
        "water_holdout_mape_pct": holdout_mape,
        "weather_diagnostics": weather_diagnostics,
        "selected_year_water_shape_priors": water_shape_priors,
        "selected_year_annual_closures": {
            "facility_electricity_mwh": float(representative["p_fac_mw"].sum()),
            "water_withdrawal_m3": float(
                representative["water_withdrawal_proxy_m3_per_h"].sum()
            ),
            "location_scope2_tco2e": float(
                representative["location_emissions_kgco2e"].sum() / 1000.0
            ),
        },
        "interpretation": {
            "annual_electricity": "calibration closure in every simulation",
            "annual_water_retrospective": "closure where Meta reported withdrawal",
            "annual_water_train_only": "predictive diagnostic; holdout not used for fitting or selection",
            "hourly_outputs": "conditional stochastic scenarios with explicit provenance",
            "carbon_allocation": (
                "annual location Scope 2 allocated over facility energy"
                if not args.use_pacw_shape
                else "optional PACW regional physical-shape sensitivity (EIA consumed CO2 intensity when present); not Meta-specific marginal emissions"
            ),
        },
        "outputs": [
            str(p.relative_to(ROOT))
            for p in [
                annual_path,
                runs_path,
                hourly_path,
                scenarios_path,
                monthly_path,
                diagnostics_path,
                checks_path,
                annual_fig,
                week_fig,
                scenario_fig,
            ]
            if p.exists()
        ],
    }
    summary_path = OUT / "stochastic_proxy_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    print("\nAnnual summary:")
    cols = [
        "year",
        "electricity_mwh_reported",
        "it_energy_mwh_median",
        "annual_pue_median",
        "water_withdrawal_m3_reported",
        "water_train_only_pred_m3_median",
        "water_train_only_error_pct",
        "split",
    ]
    print(annual[cols].to_string(index=False))
    print("\nScenario comparison:")
    print(comparison.to_string(index=False))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Meta Prineville conditional stochastic proxy."
    )
    parser.add_argument(
        "--n-simulations",
        type=int,
        default=32,
        help="Stochastic ensemble members per year (default: 32).",
    )
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIOS),
        default="mixed_cox",
        help="Baseline workload-arrival scenario.",
    )
    parser.add_argument("--selected-year", type=int, default=2024)
    parser.add_argument("--train-end-year", type=int, default=2022)
    parser.add_argument("--seed", type=int, default=20260812)
    parser.add_argument(
        "--use-pacw-shape",
        action="store_true",
        help=(
            "Use processed PACW EIA-930 as an explicit relative hourly carbon-shape "
            "sensitivity. Prefers EIA-reported consumed CO2 intensity from 2018-07; "
            "the fuel/import proxy is retained only as a named sensitivity and for "
            "hours without EIA intensity. Demand/interchange begin 2015-07. Default "
            "allocates annual location Scope 2 in proportion to facility energy. "
            "Not a Meta-specific marginal-emissions estimate."
        ),
    )
    args = parser.parse_args()
    if args.n_simulations < 4:
        parser.error("--n-simulations must be at least 4 for interval summaries.")
    return args


if __name__ == "__main__":
    run(parse_args())
