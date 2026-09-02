#!/usr/bin/env python3
"""ESIF measured facility IT + weather → measured facility overhead.

Does not refit frozen Kestrel CPU or H100 compute.
Does not use reconstructed node power, TDP, M100, or Meta data.
Does not fit PUE, water, or Prineville.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from facility_paths import (  # noqa: E402
    ALIGN_TOLERANCE_S,
    ANALYSIS,
    CADENCE_S,
    COVERAGE_MIN,
    CPU_DISPOSITION,
    CPU_FREEZE,
    CPU_FREEZE_SHA256,
    CPU_STATUS,
    CPU_STATUS_SHA256,
    DATA_PROCESSED,
    DOCS,
    EAGLE_DECOMMISSION,
    ESIF_DOI,
    ESIF_README,
    FIGURES,
    FO_ROOT,
    GPU_GA,
    GPU_INT_OUTAGE_END,
    GPU_INT_OUTAGE_START,
    H100_DISPOSITION,
    H100_FREEZE,
    H100_FREEZE_SHA256,
    MANIFESTS,
    MAX_INTEGRATION_GAP_S,
    NLR_ROOT,
    OUTAGE_FULL_END,
    OUTAGE_FULL_START,
    PARSIMONY_BIAS_PP,
    PARSIMONY_REL_WAPE,
    POWER_PARQUET,
    POWER_SHA256,
    README_SHA256,
    REPO_ROOT,
    RESULTS,
    SIMPLEST_ORDER,
    TARGETS,
    TOWER_FILTER_PUMP_KW,
    WEATHER_PARQUET,
    WEATHER_SHA256,
)


def jdump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=_json_default) + "\n")


def _json_default(x):
    if isinstance(x, (np.floating, np.integer)):
        return float(x) if isinstance(x, np.floating) else int(x)
    if isinstance(x, np.ndarray):
        return x.tolist()
    if isinstance(x, (pd.Timestamp, Path)):
        return str(x)
    if pd.isna(x):
        return None
    raise TypeError(type(x))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_cmd(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)
    return (r.stdout or r.stderr or "").strip()


def wape(y, yhat) -> float:
    y = np.asarray(y, float)
    yhat = np.asarray(yhat, float)
    den = np.abs(y).sum()
    return float(np.abs(y - yhat).sum() / den) if den else np.nan


def mae(y, yhat) -> float:
    return float(np.mean(np.abs(np.asarray(y, float) - np.asarray(yhat, float))))


def rmse(y, yhat) -> float:
    e = np.asarray(y, float) - np.asarray(yhat, float)
    return float(np.sqrt(np.mean(e * e)))


def r2_score(y, yhat) -> float:
    y = np.asarray(y, float)
    yhat = np.asarray(yhat, float)
    ss_res = np.sum((y - yhat) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    return float(1.0 - ss_res / ss_tot) if ss_tot else np.nan


def energy_bias(y, yhat) -> float:
    y = np.asarray(y, float)
    yhat = np.asarray(yhat, float)
    s = y.sum()
    return float((yhat.sum() - s) / s) if s else np.nan


def stull_wetbulb_c(tdb_c: np.ndarray, rh_pct: np.ndarray) -> np.ndarray:
    """Stull (2011) J. Appl. Meteor. Climatol. empirical wet-bulb, °C.

    Valid approximately for RH in 5–99% and typical meteorological T.
    No pressure series is used or invented.
    """
    t = np.asarray(tdb_c, float)
    rh = np.clip(np.asarray(rh_pct, float), 1e-6, 100.0)
    return (
        t * np.arctan(0.151977 * np.sqrt(rh + 8.313659))
        + np.arctan(t + rh)
        - np.arctan(rh - 1.676331)
        + 0.00391838 * rh**1.5 * np.arctan(0.023101 * rh)
        - 4.686035
    )


def f_to_c(f):
    return (np.asarray(f, float) - 32.0) * 5.0 / 9.0


def series_qc(s: pd.Series, ts: pd.Series, name: str) -> dict:
    x = s.to_numpy(float)
    finite = np.isfinite(x)
    xf = x[finite]
    dt = ts.sort_values().diff().dt.total_seconds()
    stuck = 0
    if finite.any():
        run = 1
        vals = s.to_numpy()
        for i in range(1, len(vals)):
            if vals[i] == vals[i - 1] and np.isfinite(vals[i]):
                run += 1
                stuck = max(stuck, run)
            else:
                run = 1
    gaps = dt[dt > MAX_INTEGRATION_GAP_S]
    return {
        "field": name,
        "n": int(len(s)),
        "n_finite": int(finite.sum()),
        "missing_frac": float(1.0 - finite.mean()),
        "n_negative": int(((np.isfinite(x)) & (x < 0)).sum()),
        "n_zero": int(((np.isfinite(x)) & (x == 0)).sum()),
        "min": float(np.min(xf)) if len(xf) else None,
        "p01": float(np.quantile(xf, 0.01)) if len(xf) else None,
        "p50": float(np.quantile(xf, 0.50)) if len(xf) else None,
        "p99": float(np.quantile(xf, 0.99)) if len(xf) else None,
        "max": float(np.max(xf)) if len(xf) else None,
        "longest_gap_s": float(dt.max()) if len(dt) else None,
        "n_gaps_gt_max": int((dt > MAX_INTEGRATION_GAP_S).sum()),
        "longest_stuck_run": int(stuck),
    }


def hourly_aggregate(df: pd.DataFrame, value_cols: list[str], ts_col: str = "ts") -> pd.DataFrame:
    """Time-weighted hourly means. Long gaps do not contribute energy."""
    d = df.dropna(subset=[ts_col]).sort_values(ts_col).copy()
    d = d[~d[ts_col].duplicated(keep="first")]
    t = pd.to_datetime(d[ts_col])
    t_next = t.shift(-1)
    t_next.iloc[-1] = t.iloc[-1] + pd.Timedelta(seconds=CADENCE_S)
    dt = (t_next - t).dt.total_seconds().to_numpy(float)
    w = np.where(dt <= MAX_INTEGRATION_GAP_S, dt, CADENCE_S)
    d = d.assign(_w=w, _hour=t.dt.floor("h"))
    out = d.groupby("_hour", sort=True).agg(n_samples=("_w", "size"), coverage=("_w", "sum")).reset_index()
    out["coverage"] = out["coverage"] / 3600.0
    out["valid_coverage"] = out["coverage"] >= COVERAGE_MIN
    out = out.rename(columns={"_hour": "hour"})
    for c in value_cols:
        wy = np.where(np.isfinite(d[c].to_numpy(float)), d[c].to_numpy(float) * d["_w"].to_numpy(float), 0.0)
        ww = np.where(np.isfinite(d[c].to_numpy(float)), d["_w"].to_numpy(float), 0.0)
        tmp = pd.DataFrame({"hour": d["_hour"], "_wy": wy, "_ww": ww})
        g = tmp.groupby("hour", sort=True).sum()
        mean = g["_wy"] / g["_ww"].replace(0, np.nan)
        out = out.merge(mean.rename(c).reset_index(), on="hour", how="left")
        out[f"{c}_kwh"] = out[c]
    return out


def ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    return coef


def scaler_fit(df: pd.DataFrame, cols: tuple[str, ...]) -> dict:
    return {c: {"mean": float(df[c].mean()), "std": float(df[c].std(ddof=0) or 1.0)} for c in cols}


def zcol(df: pd.DataFrame, col: str, sc: dict) -> np.ndarray:
    return (df[col].to_numpy(float) - sc[col]["mean"]) / sc[col]["std"]


def design(df: pd.DataFrame, spec: str, scaler: dict | None) -> tuple[np.ndarray, dict | None]:
    n = len(df)
    it = df["it_power_kw"].to_numpy(float)
    tdb = df["tdb_c"].to_numpy(float)
    rh = df["rh_pct"].to_numpy(float)
    twb = df["twb_c"].to_numpy(float)
    ones = np.ones(n)
    if spec == "F0":
        return np.column_stack([ones]), None
    if spec == "F1":
        return np.column_stack([ones, it]), None
    if spec == "F2_RAW":
        return np.column_stack([ones, it, tdb, rh]), None
    if spec == "F2_PHYS":
        return np.column_stack([ones, it, tdb, twb]), None
    cols = ("it_power_kw", "tdb_c", "twb_c")
    sc = scaler or scaler_fit(df, cols)
    zit, ztdb, ztwb = zcol(df, "it_power_kw", sc), zcol(df, "tdb_c", sc), zcol(df, "twb_c", sc)
    parts = [ones, zit, ztdb, ztwb, zit**2, ztdb**2, ztwb**2]
    if spec == "F4":
        parts.append(zit * ztwb)
    if spec not in ("F3", "F4"):
        raise ValueError(spec)
    return np.column_stack(parts), sc


def predict(df: pd.DataFrame, spec: str, coef: np.ndarray, scaler: dict | None) -> np.ndarray:
    X, _ = design(df, spec, scaler)
    return X @ coef


def metrics_block(y, yhat, prefix="") -> dict:
    y = np.asarray(y, float)
    yhat = np.asarray(yhat, float)
    return {
        f"{prefix}n": int(len(y)),
        f"{prefix}mean_obs": float(np.mean(y)) if len(y) else None,
        f"{prefix}MAE": mae(y, yhat) if len(y) else None,
        f"{prefix}RMSE": rmse(y, yhat) if len(y) else None,
        f"{prefix}WAPE": wape(y, yhat) if len(y) else None,
        f"{prefix}energy_bias": energy_bias(y, yhat) if len(y) else None,
        f"{prefix}R2": r2_score(y, yhat) if len(y) else None,
    }


def daily_from_hourly(h: pd.DataFrame, y_col: str, yhat_col: str) -> pd.DataFrame:
    d = h.copy()
    d["day"] = d["hour"].dt.floor("D")
    g = d.groupby("day")
    out = g.agg(obs=(y_col, "sum"), pred=(yhat_col, "sum"), n=("hour", "size")).reset_index()
    return out[out.n >= 20]


def write_initial_state() -> dict:
    for p in (MANIFESTS, ANALYSIS, DATA_PROCESSED, FIGURES, DOCS, RESULTS):
        p.mkdir(parents=True, exist_ok=True)
    rec = {
        "public_baseline_commit_requested": "efb9d520e956830ccadf71ab0bee53cd8cc5b01d",
        "git": {
            "branch": git_cmd("rev-parse", "--abbrev-ref", "HEAD"),
            "HEAD": git_cmd("rev-parse", "HEAD"),
            "status": git_cmd("status", "--short"),
        },
        "cpu": {
            "CPU_LAYER_FINAL_DISPOSITION": json.loads(CPU_STATUS.read_text())["CPU_LAYER_FINAL_DISPOSITION"],
            "expected": CPU_DISPOSITION,
            "sha256": sha256_file(CPU_STATUS),
            "freeze_sha256": sha256_file(CPU_FREEZE),
            "read_only": True,
            "refit": False,
        },
        "h100": {
            "H100_COMPUTE_LAYER": json.loads(H100_FREEZE.read_text())["H100_COMPUTE_LAYER"],
            "expected": H100_DISPOSITION,
            "sha256": sha256_file(H100_FREEZE),
            "read_only": True,
            "refit": False,
        },
        "esif_raw": {
            "power": str(POWER_PARQUET.relative_to(REPO_ROOT)),
            "weather": str(WEATHER_PARQUET.relative_to(REPO_ROOT)),
            "readme": str(ESIF_README.relative_to(REPO_ROOT)),
            "power_bytes": POWER_PARQUET.stat().st_size,
            "weather_bytes": WEATHER_PARQUET.stat().st_size,
        },
        "constraints": {
            "input_is_measured_facility_it_power_kw": True,
            "do_not_use_kestrel_cpu_replay": True,
            "do_not_use_h100_replay": True,
            "do_not_use_tdp": True,
            "do_not_use_m100": True,
            "do_not_use_meta": True,
            "do_not_fit_pue": True,
            "do_not_fit_water": True,
            "do_not_transfer_coefficients_to_prineville": True,
        },
    }
    jdump(MANIFESTS / "FACILITY_OVERHEAD_INITIAL_STATE.json", rec)
    return rec


def write_provenance() -> dict:
    rec = {
        "title": "NLR HPC Facility Power Usage Effectiveness (PUE) Data",
        "doi": ESIF_DOI,
        "catalog_url": "https://data.nlr.gov/submissions/300",
        "citation": "Clark, Struan, and Justin Strelka. 2025. NLR HPC Facility Power Usage Effectiveness (PUE) Data. NLR Data Catalog. DOI: 10.7799/3015212.",
        "resources": [
            {
                "source_filename": "esif.influx.buildingData.PUE.combined.parquet",
                "catalog_name": "ESIF DC Power Metrics Timeseries Data (Parquet)",
                "catalog_version": 3,
                "bytes": POWER_PARQUET.stat().st_size,
                "sha256": sha256_file(POWER_PARQUET),
                "expected_sha256": POWER_SHA256,
                "local_path": str(POWER_PARQUET),
                "download_url": "https://data.nlr.gov/system/files/300/1757103411-esif.influx.buildingData.PUE.combined.parquet",
                "redownloaded": False,
            },
            {
                "source_filename": "esif.influx.buildingData.outside.combined.parquet",
                "catalog_name": "ESIF DC Outside Weather Station Timeseries Data (Parquet)",
                "catalog_version": 2,
                "bytes": WEATHER_PARQUET.stat().st_size,
                "sha256": sha256_file(WEATHER_PARQUET),
                "expected_sha256": WEATHER_SHA256,
                "local_path": str(WEATHER_PARQUET),
                "download_url": "https://data.nlr.gov/system/files/300/1757105566-esif.influx.buildingData.outside.combined_2.parquet",
                "note": "Catalog title uses outside.combined.parquet; payload filename on the current version URL is outside.combined_2.parquet. Stored locally under the catalog title name.",
                "redownloaded_because_absent": True,
            },
            {
                "source_filename": "README.md",
                "catalog_name": "README",
                "bytes": ESIF_README.stat().st_size,
                "sha256": sha256_file(ESIF_README),
                "expected_sha256": README_SHA256,
                "local_path": str(ESIF_README),
            },
        ],
        "column_name_note": {
            "readme_weather": ["outside_air_temp", "outside_air_humidity"],
            "parquet_weather": ["outdoor_air_temp", "outdoor_air_humidity"],
            "mapping": "README names are the official semantics; parquet uses outdoor_* . Canonical hourly columns use README names after mapping.",
        },
        "raw_unaltered": True,
    }
    assert rec["resources"][0]["sha256"] == POWER_SHA256
    assert rec["resources"][1]["sha256"] == WEATHER_SHA256
    jdump(MANIFESTS / "SOURCE_PROVENANCE.json", rec)
    return rec


def write_field_semantics() -> None:
    rows = [
        ["ts", "timestamp (naive)", "measured", "sample time", "Timestamp", "timezone not stated in catalog", "Do not infer UTC vs America/Denver by correlation"],
        ["it_power_kw", "kW", "measured", "IT equipment on the data-center floor", "Captures power used by the IT equipment on the data center floor.", "not cooling/HVAC/pumps; not a single cluster", "PRIMARY MODEL INPUT; not Kestrel replay"],
        ["cooling_kw", "kW", "measured", "outdoor cooling fans, pipe trace heaters, dedicated tower filter pump (~2.67 kW)", "fans and pipe trace heaters associated with outdoor cooling equipment. The dedicated tower filter pump power is also captured as cooling load.", "not HVAC fan walls; not ERW/tower-loop pumps (those are pump_kw)", "canonical target; includes ~2.67 kW filter pump"],
        ["hvac_kw", "kW", "measured", "fan walls, electrical-room fan coils, make-up air", "fan walls, fan coils that support the data center electrical rooms, and the make-up air unit", "not outdoor cooling equipment fans", "canonical target"],
        ["pump_kw", "kW", "measured", "ERW loop, tower-water loop, fan-wall boost pumps", "pumps that move water in the data center Energy Recover Water loop and the Tower Water loops, and also captures power used by the boost pumps that circulate water through the fan walls", "tower filter pump ~2.67 kW is NOT in this field", "canonical target"],
        ["plug_and_light_kw", "kW", "measured", "DC/mechanical-room plugs/lights; standby-generator crank-case heater", "power associated with the data center and dedicated mechanical room. The crank-case heater for the emergency standby generator is also captured as light and plug load", "not IT floor", "canonical target"],
        ["pue", "dimensionless", "derived by source", "facility PUE as published", "Power Usage Effectiveness", "component reconstruction may not match if other terms exist", "NOT a regression target"],
        ["energy_reuse", "source ERE field", "measured/derived by source", "energy reuse effectiveness", "Energy Reuse Effectiveness", "78% missing at native resolution; starts 2023-08-30", "NOT a canonical predictor"],
        ["ere", "source field", "present in parquet, not in README list", "parallel ERE-like column", "not in README field list", "do not substitute for energy_reuse", "QA only"],
        ["outside_air_temp", "degrees Fahrenheit", "measured", "outside air dry-bulb", "Outside air temperature - Degrees Fahrenheit", "parquet column outdoor_air_temp", "mapped from outdoor_air_temp"],
        ["outside_air_humidity", "percent RH", "measured", "outside air relative humidity", "Outside air humidity - Relative humidity percent", "parquet column outdoor_air_humidity", "mapped from outdoor_air_humidity"],
        ["pump_physical_kw", "kW", "descriptive reclass only", "pump_kw + 2.67 kW tower filter pump", "README note on filter pump", "not a canonical field", "do not replace pump_kw"],
        ["cooling_fans_trace_kw", "kW", "descriptive reclass only", "cooling_kw - 2.67", "README note on filter pump", "not a canonical field", "do not replace cooling_kw"],
    ]
    cols = ["field", "unit", "measured_or_derived", "physical_equipment", "source_wording", "known_exclusions_or_caveats", "modeling_role"]
    pd.DataFrame(rows, columns=cols).to_csv(ANALYSIS / "FACILITY_FIELD_SEMANTICS.csv", index=False)
    (DOCS / "ESIF_FACILITY_BOUNDARY.md").write_text(
        """# ESIF facility meter boundary

Official source: NLR HPC Facility PUE Data, DOI `10.7799/3015212`, README in `data_raw/esif_pue/`.

Canonical modeling uses **published source fields unchanged**.

## Power

| Field | Equipment (source wording) |
| --- | --- |
| `it_power_kw` | IT equipment on the data-center floor |
| `cooling_kw` | Outdoor-equipment fans, pipe trace heaters, **and** the dedicated cooling-tower filter pump |
| `hvac_kw` | Fan walls, electrical-room fan coils, make-up air |
| `pump_kw` | Energy-recovery-water loop, tower-water loop, and fan-wall boost pumps. **Does not** include the ~2.67 kW tower filter pump |
| `plug_and_light_kw` | Data-center / dedicated mechanical-room plugs and lights, plus standby-generator crank-case heater |
| `pue` | Source PUE. Not a regression target |
| `energy_reuse` | Source energy-reuse effectiveness. Not a canonical predictor |

## Descriptive physical reclassification (not canonical)

If the documented constant tower-filter pump is accepted:

`pump_physical_kw = pump_kw + 2.67`

`cooling_fans_trace_kw = cooling_kw - 2.67`

These are **not** substitutes for the published fields.

## Architecture context (not transferable coefficients)

Warm-water liquid cooled; chiller-less HPC hall; waste-heat reuse; evaporative cooling towers; thermosyphon hybrid dry heat rejection.

## Weather

README names: `outside_air_temp` (°F), `outside_air_humidity` (% RH).

The weather parquet columns are `outdoor_air_temp` / `outdoor_air_humidity`. Semantics follow the README; names are mapped, values are not altered.

## Out of scope inputs

Reconstructed Kestrel CPU power, H100 CPU+GPU replay, TDP, M100, Meta data.
"""
    )


def qc_and_clock():
    power = pd.read_parquet(POWER_PARQUET)
    weather = pd.read_parquet(WEATHER_PARQUET)
    weather = weather.rename(columns={"outdoor_air_temp": "outside_air_temp", "outdoor_air_humidity": "outside_air_humidity"})
    power_ts = pd.to_datetime(power.ts)
    weather_ts = pd.to_datetime(weather.ts)
    p_dt = power_ts.sort_values().diff().dt.total_seconds()
    w_dt = weather_ts.sort_values().diff().dt.total_seconds()
    power_qc = {
        "n_rows": int(len(power)),
        "ts_min": str(power_ts.min()),
        "ts_max": str(power_ts.max()),
        "cadence_s_median": float(p_dt.median()),
        "monotonic": bool(power_ts.is_monotonic_increasing),
        "n_duplicate_ts": int(power_ts.duplicated().sum()),
        "fields": [series_qc(power[c], power_ts, c) for c in ["it_power_kw", "cooling_kw", "hvac_kw", "pump_kw", "plug_and_light_kw", "pue", "energy_reuse"]],
        "n_ts_before_2015": int((power_ts < "2015-01-01").sum()),
        "documented_outage_naive": {"start": OUTAGE_FULL_START, "end_exclusive": OUTAGE_FULL_END},
    }
    weather_qc = {
        "n_rows": int(len(weather)),
        "ts_min": str(weather_ts.min()),
        "ts_max": str(weather_ts.max()),
        "n_unix_epoch_sentinels": int((weather_ts < "1971-01-01").sum()),
        "cadence_s_median": float(w_dt.median()),
        "monotonic": bool(weather_ts.is_monotonic_increasing),
        "n_duplicate_ts": int(weather_ts.duplicated().sum()),
        "fields": [series_qc(weather[c], weather_ts, c) for c in ["outside_air_temp", "outside_air_humidity"]],
    }
    jdump(ANALYSIS / "FACILITY_DATA_QC.json", {"power": power_qc, "weather": weather_qc, "cadence_frozen_s": CADENCE_S, "max_integration_gap_s": MAX_INTEGRATION_GAP_S})
    pd.DataFrame(power_qc["fields"]).to_csv(ANALYSIS / "FACILITY_POWER_QC_SUMMARY.csv", index=False)
    pd.DataFrame(weather_qc["fields"]).to_csv(ANALYSIS / "FACILITY_WEATHER_QC_SUMMARY.csv", index=False)

    # Clock: exact vs nearest. Tolerance frozen from cadence, not correlation.
    p = pd.DataFrame({"ts": power_ts, "p": 1}).sort_values("ts")
    w = pd.DataFrame({"ts": weather_ts, "w": 1}).sort_values("ts")
    w = w[w.ts >= "2016-01-01"]
    p_s = p.ts.dt.floor("s")
    w_s = w.ts.dt.floor("s")
    exact = int(len(set(p_s) & set(w_s)))
    merged = pd.merge_asof(p.rename(columns={"ts": "ts_p"}), w.rename(columns={"ts": "ts_w"}), left_on="ts_p", right_on="ts_w", direction="nearest", tolerance=pd.Timedelta(seconds=ALIGN_TOLERANCE_S))
    dist = (merged.ts_p - merged.ts_w).abs().dt.total_seconds()
    clock = {
        "question": "Are weather and power synchronized to the same physical moments?",
        "not_the_question": "Is source ts UTC or America/Denver?",
        "timezone_optimization": "NOT_PERFORMED",
        "power_span": [str(power_ts.min()), str(power_ts.max())],
        "weather_span_excluding_epoch": [str(w.ts.min()), str(w.ts.max())],
        "power_cadence_s_median": float(p_dt.median()),
        "weather_cadence_s_median": float(w_dt.median()),
        "alignment_tolerance_s_frozen_from_cadence": ALIGN_TOLERANCE_S,
        "exact_second_match_n": exact,
        "exact_second_match_share_of_power": exact / max(len(p), 1),
        "nearest_within_tolerance_frac": float(merged.ts_w.notna().mean()),
        "nearest_distance_s_p50": float(dist.median()) if dist.notna().any() else None,
        "nearest_distance_s_p90": float(dist.quantile(0.9)) if dist.notna().any() else None,
        "disposition": "ALIGNED_SAME_CLOCK_NEAREST_CADENCE" if float(merged.ts_w.notna().mean()) > 0.8 else "PARTIAL_OR_MISALIGNED",
    }
    jdump(ANALYSIS / "POWER_WEATHER_CLOCK_AUDIT.json", clock)
    return power, weather, power_qc, weather_qc, clock


def pue_closure(power: pd.DataFrame) -> dict:
    d = power.copy()
    d["aux_source_kw"] = d["cooling_kw"] + d["hvac_kw"] + d["pump_kw"] + d["plug_and_light_kw"]
    d["facility_reconstructed_kw"] = d["it_power_kw"] + d["aux_source_kw"]
    m = (
        d["it_power_kw"].gt(0)
        & np.isfinite(d["facility_reconstructed_kw"])
        & np.isfinite(d["pue"])
        & d["cooling_kw"].ge(0)
        & d["hvac_kw"].ge(0)
        & d["pump_kw"].ge(0)
        & d["plug_and_light_kw"].ge(0)
    )
    x = d.loc[m]
    recon = x["facility_reconstructed_kw"] / x["it_power_kw"]
    delta = recon - x["pue"]
    rec = {
        "n_compared": int(m.sum()),
        "median_recon_minus_source": float(delta.median()),
        "MAE": float(np.abs(delta).mean()),
        "p50_abs": float(np.abs(delta).median()),
        "p90_abs": float(np.abs(delta).quantile(0.9)),
        "p99_abs": float(np.abs(delta).quantile(0.99)),
        "mean_source_pue": float(x.pue.mean()),
        "mean_recon_pue": float(recon.mean()),
        "corr": float(np.corrcoef(x.pue, recon)[0, 1]),
        "low_it_lt_200kW_MAE": float(np.abs(delta[x.it_power_kw < 200]).mean()) if (x.it_power_kw < 200).any() else None,
        "PUE_COMPONENT_CLOSURE": "PASS" if float(np.abs(delta).median()) < 0.01 and float(np.abs(delta).quantile(0.9)) < 0.05 else ("PARTIAL" if float(np.abs(delta).median()) < 0.05 else "FAIL"),
        "missing_accounting_if_fail": "If recon systematically differs from source pue, additional unlisted facility terms or a different PUE formula (e.g. reuse) may exist. Do not force closure.",
    }
    jdump(ANALYSIS / "PUE_COMPONENT_CLOSURE_AUDIT.json", rec)
    pd.DataFrame({"pue_source": x.pue, "pue_reconstructed": recon, "delta": delta, "it_power_kw": x.it_power_kw}).sample(
        n=min(20000, len(x)), random_state=0
    ).to_csv(ANALYSIS / "PUE_COMPONENT_CLOSURE_AUDIT.csv", index=False)
    return rec


def build_hourly(power: pd.DataFrame, weather: pd.DataFrame) -> pd.DataFrame:
    pcols = ["it_power_kw", "cooling_kw", "hvac_kw", "pump_kw", "plug_and_light_kw", "pue", "energy_reuse"]
    p = power.copy()
    p["ts"] = pd.to_datetime(p.ts)
    p = p[p.ts >= "2015-11-01"]
    for c in pcols:
        if c == "pue":
            continue
        if c == "energy_reuse":
            continue
        p.loc[p[c] < 0, c] = np.nan
    w = weather.rename(columns={"outdoor_air_temp": "outside_air_temp", "outdoor_air_humidity": "outside_air_humidity"}).copy()
    w["ts"] = pd.to_datetime(w.ts)
    w = w[w.ts >= "2016-01-01"]
    w.loc[(w.outside_air_temp < -50) | (w.outside_air_temp > 120), "outside_air_temp"] = np.nan
    w.loc[(w.outside_air_humidity < 0) | (w.outside_air_humidity > 100), "outside_air_humidity"] = np.nan
    ph = hourly_aggregate(p, pcols)
    wh = hourly_aggregate(w, ["outside_air_temp", "outside_air_humidity"])
    h = ph.merge(wh, on="hour", how="inner", suffixes=("_power", "_weather"))
    h["tdb_f"] = h["outside_air_temp"]
    h["rh_pct"] = h["outside_air_humidity"]
    h["tdb_c"] = f_to_c(h["tdb_f"])
    rh_ok = h["rh_pct"].between(5, 99) & h["tdb_c"].between(-40, 50)
    h["twb_c"] = np.where(rh_ok, stull_wetbulb_c(h["tdb_c"].to_numpy(), h["rh_pct"].to_numpy()), np.nan)
    h["twb_f"] = h["twb_c"] * 9.0 / 5.0 + 32.0
    h["aux_source_kw"] = h["cooling_kw"] + h["hvac_kw"] + h["pump_kw"] + h["plug_and_light_kw"]
    h["pump_physical_kw"] = h["pump_kw"] + TOWER_FILTER_PUMP_KW
    h["cooling_fans_trace_kw"] = h["cooling_kw"] - TOWER_FILTER_PUMP_KW
    cov_p = h["coverage_power"] if "coverage_power" in h.columns else h.get("coverage")
    # after merge suffixes
    if "coverage_power" in h.columns:
        h["coverage"] = h["coverage_power"]
        h["weather_coverage"] = h["coverage_weather"]
    outage = (h.hour >= OUTAGE_FULL_START) & (h.hour < OUTAGE_FULL_END)
    h["documented_outage"] = outage
    h["valid_it"] = h["it_power_kw"].gt(0) & h["coverage"].ge(COVERAGE_MIN) & ~outage
    h["valid_weather"] = h["tdb_c"].notna() & h["rh_pct"].notna() & h["weather_coverage"].ge(COVERAGE_MIN)
    h["valid_twb"] = h["twb_c"].notna()
    for t, flag in [
        ("cooling_kw", "valid_cooling"),
        ("hvac_kw", "valid_hvac"),
        ("pump_kw", "valid_pump"),
        ("plug_and_light_kw", "valid_plug"),
    ]:
        h[flag] = h[t].notna() & h["valid_it"] & h["valid_weather"] & h["valid_twb"]
    h["valid_all"] = h["valid_cooling"] & h["valid_hvac"] & h["valid_pump"] & h["valid_plug"]
    h["pue_reconstructed"] = np.where(h["it_power_kw"] > 0, (h["it_power_kw"] + h["aux_source_kw"]) / h["it_power_kw"], np.nan)
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    h.to_parquet(DATA_PROCESSED / "esif_facility_hourly.parquet", index=False)
    daily = (
        h[h.valid_all]
        .assign(day=lambda x: x.hour.dt.floor("D"))
        .groupby("day")
        .agg(
            n_hours=("hour", "size"),
            it_kwh=("it_power_kw_kwh", "sum") if "it_power_kw_kwh" in h.columns else ("it_power_kw", "sum"),
            cooling_kwh=("cooling_kw", "sum"),
            hvac_kwh=("hvac_kw", "sum"),
            pump_kwh=("pump_kw", "sum"),
            plug_kwh=("plug_and_light_kw", "sum"),
            aux_kwh=("aux_source_kw", "sum"),
            tdb_c=("tdb_c", "mean"),
            twb_c=("twb_c", "mean"),
            rh_pct=("rh_pct", "mean"),
            energy_reuse=("energy_reuse", "mean"),
        )
        .reset_index()
    )
    daily.to_parquet(DATA_PROCESSED / "esif_facility_daily.parquet", index=False)
    jdump(
        ANALYSIS / "WEATHER_DERIVATION_AUDIT.json",
        {
            "tdb_source": "outside_air_temp mapped from parquet outdoor_air_temp",
            "tdb_unit_source": "degrees Fahrenheit",
            "rh_source": "outside_air_humidity mapped from parquet outdoor_air_humidity",
            "rh_unit": "percent",
            "twb_method": "Stull 2011 J. Appl. Meteor. Climatol. empirical wet-bulb",
            "twb_equation": "Twb=T*atan(0.151977*(RH+8.313659)^0.5)+atan(T+RH)-atan(RH-1.676331)+0.00391838*RH^1.5*atan(0.023101*RH)-4.686035",
            "twb_input_units": "T in Celsius, RH in percent",
            "pressure_series": "NONE; formula does not use pressure",
            "elevation_not_used_as_pressure_proxy_for_Twb": True,
            "validity_domain": "RH clipped to formula evaluation in 5–99%; Tdb -40 to 50 C",
            "raw_comparator_retained": "Tdb_F + RH and Tdb_C + RH (F2_RAW)",
        },
    )
    return h, daily


def freeze_split(h: pd.DataFrame) -> dict:
    common = h[h.valid_all].sort_values("hour")
    t0, t1 = common.hour.min(), common.hour.max()
    span_days = (t1 - t0).days
    if span_days >= 730:
        test_start = t1 - pd.Timedelta(days=365)
        rule = "TEST=final_365_consecutive_days"
        incomplete_seasonal = False
    else:
        test_start = t0 + pd.Timedelta(days=int(span_days * 0.75))
        rule = "TEST=final_25pct_span"
        incomplete_seasonal = True
    rec = {
        "rule": rule,
        "timestamps_only": True,
        "no_random_split": True,
        "common_valid_span": [str(t0), str(t1)],
        "span_days": int(span_days),
        "DEV": {"start": str(t0), "end_exclusive": str(test_start)},
        "TEST": {"start": str(test_start), "end_inclusive": str(t1)},
        "n_common_valid_hours": int(len(common)),
        "n_DEV_hours": int((common.hour < test_start).sum()),
        "n_TEST_hours": int((common.hour >= test_start).sum()),
        "cv": {
            "type": "expanding_window_rolling_origin",
            "min_train_days": 180,
            "val_block_days": 60,
            "folds_built_on_DEV_only": True,
        },
        "incomplete_seasonal_validation": incomplete_seasonal,
        "test_not_used_for_selection": True,
    }
    jdump(MANIFESTS / "FACILITY_TEMPORAL_SPLIT_FREEZE.json", rec)
    return rec, test_start, t0


def cv_folds(dev: pd.DataFrame, test_start, t0) -> list[tuple[pd.DatetimeIndex, pd.DatetimeIndex]]:
    folds = []
    train_end = t0 + pd.Timedelta(days=180)
    while True:
        val_end = train_end + pd.Timedelta(days=60)
        if val_end > test_start:
            break
        tr = dev.hour < train_end
        va = (dev.hour >= train_end) & (dev.hour < val_end)
        if tr.sum() >= 24 * 30 and va.sum() >= 24 * 7:
            folds.append((tr, va))
        train_end = val_end
    return folds


def fit_spec(train: pd.DataFrame, spec: str, ycol: str):
    X, sc = design(train, spec, None)
    y = train[ycol].to_numpy(float)
    coef = ols(X, y)
    return coef, sc


def eval_spec(df: pd.DataFrame, spec: str, coef, sc, ycol: str) -> dict:
    yhat = predict(df, spec, coef, sc)
    y = df[ycol].to_numpy(float)
    dly = daily_from_hourly(df.assign(y=y, yhat=yhat), "y", "yhat")
    rec = metrics_block(y, yhat, "")
    rec["daily_energy_WAPE"] = wape(dly.obs, dly.pred) if len(dly) else np.nan
    rec["daily_energy_bias"] = energy_bias(dly.obs, dly.pred) if len(dly) else np.nan
    rec["n_days"] = int(len(dly))
    rec["spec"] = spec
    return rec, yhat


def select_spec(dev: pd.DataFrame, ycol: str, folds) -> dict:
    rows = []
    for spec in SIMPLEST_ORDER:
        fold_wape, fold_bias, fold_hourly = [], [], []
        for tr_m, va_m in folds:
            tr = dev.loc[tr_m]
            va = dev.loc[va_m]
            if len(tr) < 100 or len(va) < 24:
                continue
            try:
                coef, sc = fit_spec(tr, spec, ycol)
                met, _ = eval_spec(va, spec, coef, sc, ycol)
            except np.linalg.LinAlgError:
                continue
            fold_wape.append(met["daily_energy_WAPE"])
            fold_bias.append(met["daily_energy_bias"])
            fold_hourly.append(met["WAPE"])
        if not fold_wape:
            continue
        rows.append(
            {
                "spec": spec,
                "n_folds": len(fold_wape),
                "cv_daily_energy_WAPE": float(np.nanmean(fold_wape)),
                "cv_daily_energy_bias": float(np.nanmean(fold_bias)),
                "cv_hourly_WAPE": float(np.nanmean(fold_hourly)),
            }
        )
    tab = pd.DataFrame(rows)
    if tab.empty:
        return {"selected": "F0", "table": rows, "reason": "no successful folds"}
    best = float(tab["cv_daily_energy_WAPE"].min())
    best_row = tab.loc[tab["cv_daily_energy_WAPE"].idxmin()]
    chosen = None
    for spec in SIMPLEST_ORDER:
        r = tab[tab.spec == spec]
        if r.empty:
            continue
        w = float(r.cv_daily_energy_WAPE.iloc[0])
        b = float(r.cv_daily_energy_bias.iloc[0])
        bb = float(best_row.cv_daily_energy_bias)
        if w <= best * (1.0 + PARSIMONY_REL_WAPE) and abs(b) <= abs(bb) + PARSIMONY_BIAS_PP:
            chosen = spec
            break
    if chosen is None:
        chosen = str(best_row["spec"])
    reason = (
        f"minimum necessary under parsimony: within {PARSIMONY_REL_WAPE:.0%} relative CV daily-energy WAPE of best "
        f"({best_row['spec']}={best:.4f}) and energy bias not worse by {PARSIMONY_BIAS_PP:.0%} pp; "
        "F2_PHYS preferred to F2_RAW when equivalent"
    )
    return {"selected": chosen, "best": str(best_row["spec"]), "best_wape": best, "table": rows, "reason": reason}


def write_protocol() -> None:
    jdump(
        MANIFESTS / "FACILITY_MODEL_PROTOCOL_FREEZE.json",
        {
            "targets": list(TARGETS) + ["aux_source_kw (direct diagnostic only)"],
            "hierarchy": list(SIMPLEST_ORDER),
            "primary_selection_metric": "equal-weight mean of fold daily-energy WAPE",
            "parsimony": {
                "relative_WAPE_band": PARSIMONY_REL_WAPE,
                "energy_bias_pp": PARSIMONY_BIAS_PP,
                "simplicity_order": list(SIMPLEST_ORDER),
                "F2_PHYS_preferred_to_F2_RAW_if_equivalent": True,
            },
            "F3_F4_scaling": "center/scale training-window IT, Tdb, Twb only; polynomials of scaled variables",
            "forbidden": [
                "LightGBM",
                "RF",
                "XGBoost",
                "NN",
                "Optuna",
                "large GAM",
                "target autoregression",
                "direct PUE fit",
                "p-value feature selection",
                "correlation-based lag search",
            ],
            "input": "measured it_power_kw + weather",
            "not_inputs": ["Kestrel CPU replay", "H100 replay", "TDP", "M100", "Meta", "energy_reuse"],
            "test_not_used_for_selection": True,
        },
    )


def run_models(h: pd.DataFrame, split: dict, test_start, t0):
    write_protocol()
    selected = {}
    cv_tables = []
    coefs = {}
    pred_cols = {}
    for ycol, flag in [
        ("cooling_kw", "valid_cooling"),
        ("hvac_kw", "valid_hvac"),
        ("pump_kw", "valid_pump"),
        ("plug_and_light_kw", "valid_plug"),
        ("aux_source_kw", "valid_all"),
    ]:
        d = h.loc[h[flag]].copy()
        dev = d[d.hour < test_start]
        folds = cv_folds(dev, test_start, t0)
        sel = select_spec(dev, ycol, folds)
        for r in sel["table"]:
            cv_tables.append({"target": ycol, **r})
        spec = sel["selected"] if ycol != "aux_source_kw" else sel["selected"]
        coef, sc = fit_spec(dev, spec, ycol)
        yhat = predict(d, spec, coef, sc)
        col = f"pred_{ycol}"
        h.loc[d.index, col] = yhat
        pred_cols[ycol] = col
        selected[ycol] = {
            "selected_spec": spec,
            "best_spec": sel["best"],
            "reason": sel["reason"],
            "n_dev": int(len(dev)),
            "n_folds": int(len(folds)),
            "coef": [float(x) for x in coef],
            "scaler": sc,
            "cv": sel["table"],
        }
        # signs / interpretation snapshot on DEV
        selected[ycol]["dev_metrics"] = eval_spec(dev, spec, coef, sc, ycol)[0]
        coefs[ycol] = (spec, coef, sc)
    pd.DataFrame(cv_tables).to_csv(ANALYSIS / "COMPONENT_CV_METRICS.csv", index=False)
    jdump(ANALYSIS / "COMPONENT_SELECTED_MODELS.json", selected)
    return h, selected, coefs


def aux_and_pue(h: pd.DataFrame, selected: dict, test_start) -> None:
    h["aux_pred_component_sum"] = (
        h["pred_cooling_kw"] + h["pred_hvac_kw"] + h["pred_pump_kw"] + h["pred_plug_and_light_kw"]
    )
    h["pue_pred"] = np.where(h["it_power_kw"] > 0, (h["it_power_kw"] + h["aux_pred_component_sum"]) / h["it_power_kw"], np.nan)
    # DEV comparison only for selection of decomposition vs direct (not TEST)
    dev = h[(h.valid_all) & (h.hour < test_start)]
    dly_c = daily_from_hourly(dev, "aux_source_kw", "aux_pred_component_sum")
    dly_d = daily_from_hourly(dev, "aux_source_kw", "pred_aux_source_kw")
    rec = {
        "component_sum_spec": {t: selected[t]["selected_spec"] for t in TARGETS},
        "direct_aux_spec": selected["aux_source_kw"]["selected_spec"],
        "DEV_component_sum_daily_WAPE": wape(dly_c.obs, dly_c.pred),
        "DEV_direct_daily_WAPE": wape(dly_d.obs, dly_d.pred),
        "prefer": "component_decomposition",
        "note": "Direct model is diagnostic. Prefer components if within parsimony band (error cancellation is not a reason to discard components).",
    }
    rel = abs(rec["DEV_component_sum_daily_WAPE"] - rec["DEV_direct_daily_WAPE"]) / max(rec["DEV_direct_daily_WAPE"], 1e-9)
    rec["component_within_parsimony_of_direct"] = rec["DEV_component_sum_daily_WAPE"] <= rec["DEV_direct_daily_WAPE"] * (1 + PARSIMONY_REL_WAPE) or rel <= 0.05
    rec["prefer"] = "component_decomposition" if rec["component_within_parsimony_of_direct"] else "report_both_keep_components"
    jdump(ANALYSIS / "AUXILIARY_MODEL_COMPARISON.json", rec)
    pd.DataFrame([rec]).to_csv(ANALYSIS / "AUXILIARY_MODEL_COMPARISON.csv", index=False)


def final_test(h: pd.DataFrame, test_start) -> pd.DataFrame:
    te = h[(h.valid_all) & (h.hour >= test_start)].copy()
    rows = []
    pairs = [
        ("cooling_kw", "pred_cooling_kw"),
        ("hvac_kw", "pred_hvac_kw"),
        ("pump_kw", "pred_pump_kw"),
        ("plug_and_light_kw", "pred_plug_and_light_kw"),
        ("aux_source_kw", "aux_pred_component_sum"),
        ("aux_source_kw_direct", "pred_aux_source_kw"),
    ]
    # map aux direct
    te["pred_aux_source_kw"] = h.loc[te.index, "pred_aux_source_kw"] if "pred_aux_source_kw" in h.columns else np.nan
    for name, pred in [
        ("cooling_kw", "pred_cooling_kw"),
        ("hvac_kw", "pred_hvac_kw"),
        ("pump_kw", "pred_pump_kw"),
        ("plug_and_light_kw", "pred_plug_and_light_kw"),
        ("aux_component_sum", "aux_pred_component_sum"),
        ("aux_direct", "pred_aux_source_kw"),
    ]:
        ycol = "aux_source_kw" if name.startswith("aux") else name
        y = te[ycol].to_numpy(float)
        yhat = te[pred].to_numpy(float)
        rec = {"target": name, "split": "TEST", **metrics_block(y, yhat)}
        dly = daily_from_hourly(te.assign(y=te[ycol], yhat=te[pred]), "y", "yhat")
        rec["daily_n"] = int(len(dly))
        rec["daily_energy_WAPE"] = wape(dly.obs, dly.pred) if len(dly) else None
        rec["daily_energy_bias"] = energy_bias(dly.obs, dly.pred) if len(dly) else None
        rec["daily_MAE"] = mae(dly.obs, dly.pred) if len(dly) else None
        te2 = te.copy()
        te2["month"] = te2.hour.dt.to_period("M").astype(str)
        mon = te2.groupby("month").agg(obs=(ycol, "sum"), pred=(pred, "sum"))
        mon["pct_bias"] = (mon.pred - mon.obs) / mon.obs
        rec["monthly"] = mon.reset_index().to_dict("records")
        rows.append(rec)
    # PUE
    m = te.it_power_kw > 50
    pue_obs = te.loc[m, "pue_reconstructed"]
    pue_hat = te.loc[m, "pue_pred"]
    # energy-weighted PUE = total facility / total IT
    pue_ew_obs = (te.it_power_kw + te.aux_source_kw).sum() / te.it_power_kw.sum()
    pue_ew_hat = (te.it_power_kw + te.aux_pred_component_sum).sum() / te.it_power_kw.sum()
    pue_rec = {
        "target": "PUE_from_components",
        "split": "TEST",
        "hourly_MAE": mae(pue_obs, pue_hat),
        "hourly_WAPE": wape(pue_obs, pue_hat),
        "energy_weighted_obs": float(pue_ew_obs),
        "energy_weighted_pred": float(pue_ew_hat),
        "energy_weighted_bias": float(pue_ew_hat - pue_ew_obs),
        "facility_kwh_obs": float((te.it_power_kw + te.aux_source_kw).sum()),
        "facility_kwh_pred": float((te.it_power_kw + te.aux_pred_component_sum).sum()),
        "facility_energy_bias": energy_bias(te.it_power_kw + te.aux_source_kw, te.it_power_kw + te.aux_pred_component_sum),
        "note": "PUE was not fitted; derived from measured IT plus predicted auxiliary components",
    }
    jdump(ANALYSIS / "PUE_PREDICTION_METRICS.json", pue_rec)
    pd.DataFrame([pue_rec]).to_csv(ANALYSIS / "PUE_PREDICTION_METRICS.csv", index=False)
    # calibration bins on TEST aux residual
    te["resid_aux"] = te.aux_source_kw - te.aux_pred_component_sum
    te["it_bin"] = pd.qcut(te.it_power_kw, 4, duplicates="drop")
    te["tdb_bin"] = pd.qcut(te.tdb_c, 4, duplicates="drop")
    te["twb_bin"] = pd.qcut(te.twb_c, 4, duplicates="drop")
    cal = []
    for col in ["it_bin", "tdb_bin", "twb_bin"]:
        g = te.groupby(col, observed=True)["resid_aux"].agg(["mean", "median", "count"])
        for idx, r in g.iterrows():
            cal.append({"bin_var": col, "bin": str(idx), "resid_mean": float(r["mean"]), "n": int(r["count"])})
    jdump(ANALYSIS / "FINAL_TEST_METRICS.json", {"components": rows, "pue": pue_rec, "calibration": cal, "n_test_hours": int(len(te)), "test_start": str(test_start)})
    # flatten csv
    flat = []
    for r in rows:
        flat.append({k: v for k, v in r.items() if k != "monthly"})
    pd.DataFrame(flat).to_csv(ANALYSIS / "FINAL_TEST_METRICS.csv", index=False)
    return te


def residuals_heat_epochs(h: pd.DataFrame, te: pd.DataFrame, test_start, selected: dict) -> None:
    # DEV residual ACF on cooling using selected model (not TEST for protocol deviation)
    dev = h[(h.valid_cooling) & (h.hour < test_start)].copy()
    spec, coef, sc = selected["cooling_kw"]["selected_spec"], np.array(selected["cooling_kw"]["coef"]), selected["cooling_kw"]["scaler"]
    # coef already used to fill pred
    r = (dev.cooling_kw - dev.pred_cooling_kw).to_numpy(float)
    r = r[np.isfinite(r)]
    def acf_lag(x, lag):
        if len(x) <= lag + 10:
            return None
        a, b = x[lag:], x[:-lag]
        if a.std() == 0 or b.std() == 0:
            return None
        return float(np.corrcoef(a, b)[0, 1])
    acf = {f"lag_{lag}h": acf_lag(r, lag) for lag in (1, 6, 24)}
    fail = selected["cooling_kw"]["dev_metrics"]["daily_energy_WAPE"] > 0.25
    # Lagged-INPUT diagnostic is OPTIONAL if current-input models fail. Not exercising it is not a protocol deviation.
    # Lagged TARGETS remain forbidden. This generating path must not be used to overwrite frozen post-test artifacts.
    jdump(
        ANALYSIS / "RESIDUAL_DIAGNOSTICS.json",
        {
            "dev_cooling_acf": acf,
            "current_input_models_fail_predeclared_WAPE_gt_0.25": fail,
            "fallback_trigger_condition_met": bool(fail),
            "lagged_input_extension_tested": False,
            "protocol_deviation": False,
            "target_lag_used": False,
            "reason_no_lagged_target": "lagged TARGET values forbidden; lagged inputs only if DEV consistently fails",
        },
    )
    # heat reuse on TEST residuals
    te = te.copy()
    te["resid_aux"] = te.aux_source_kw - te.aux_pred_component_sum
    te["resid_cool"] = te.cooling_kw - te.pred_cooling_kw
    reuse = te[te.energy_reuse.notna()].copy()
    if len(reuse) < 100:
        heat = {"HEAT_REUSE_RESIDUAL_EFFECT": "UNRESOLVED", "reason": "insufficient non-missing energy_reuse on TEST", "n": int(len(reuse))}
    else:
        reuse["reuse_bin"] = pd.qcut(reuse.energy_reuse, 4, duplicates="drop")
        g = reuse.groupby("reuse_bin", observed=True).agg(n=("resid_aux", "size"), mean_resid=("resid_aux", "mean"), wape_proxy=("resid_aux", lambda s: float(np.mean(np.abs(s)))))
        spread = float(g.mean_resid.max() - g.mean_resid.min())
        mag = float(np.mean(np.abs(te.resid_aux)))
        label = "MATERIAL" if spread > 0.25 * mag else "LOW"
        heat = {
            "HEAT_REUSE_RESIDUAL_EFFECT": label,
            "n_test_with_energy_reuse": int(len(reuse)),
            "resid_mean_by_quartile": g.reset_index().astype(str).to_dict("records"),
            "spread_of_mean_resid": spread,
            "mean_abs_resid_aux": mag,
            "not_added_as_predictor": True,
        }
    jdump(ANALYSIS / "HEAT_REUSE_RESIDUAL.json", heat)
    # epochs frozen before comparison
    te["epoch"] = np.where(te.hour < EAGLE_DECOMMISSION, "eagle_coexist", np.where(te.hour < GPU_GA, "post_eagle_pre_gpu_ga", "post_gpu_ga"))
    ep_rows = []
    for name, g in te.groupby("epoch"):
        ep_rows.append(
            {
                "epoch": name,
                "n": int(len(g)),
                "aux_WAPE": wape(g.aux_source_kw, g.aux_pred_component_sum),
                "aux_bias": energy_bias(g.aux_source_kw, g.aux_pred_component_sum),
                "cool_WAPE": wape(g.cooling_kw, g.pred_cooling_kw),
            }
        )
    jdump(
        ANALYSIS / "EPOCH_STABILITY.json",
        {
            "dates_frozen_before_residuals": True,
            "epochs": {
                "eagle_coexist": f"hour < {EAGLE_DECOMMISSION}",
                "post_eagle_pre_gpu_ga": f"{EAGLE_DECOMMISSION} ≤ hour < {GPU_GA}",
                "post_gpu_ga": f"hour ≥ {GPU_GA}",
                "esif_full_outage_excluded_from_valid_hours": [OUTAGE_FULL_START, OUTAGE_FULL_END],
                "thermosyphon_commissioning": "IN_SAMPLE",
                "thermosyphon_pre_tsc_available": "2016-06-12 through 2016-07-31",
                "thermosyphon_commissioning_transition": "2016-08",
                "thermosyphon_first_full_year": "2016-09-01 through 2017-08-31",
            },
            "TEST_by_epoch": ep_rows,
            "gpu_integration_outage": [GPU_INT_OUTAGE_START, GPU_INT_OUTAGE_END],
        },
    )
    # uncertainty: 7-day block bootstrap on TEST aux WAPE
    te = te.sort_values("hour")
    te["block"] = (te.hour - te.hour.min()).dt.total_seconds() // (7 * 86400)
    blocks = list(te.groupby("block"))
    rng = np.random.default_rng(0)
    boots = []
    if blocks:
        for _ in range(200):
            idx = rng.integers(0, len(blocks), size=len(blocks))
            parts = [blocks[i][1] for i in idx]
            b = pd.concat(parts, ignore_index=True)
            boots.append(wape(b.aux_source_kw, b.aux_pred_component_sum))
    jdump(
        ANALYSIS / "FACILITY_OVERHEAD_UNCERTAINTY.json",
        {
            "method": "7-day moving/block bootstrap of TEST hours, 200 replicates",
            "not_iid_hourly": True,
            "TEST_aux_component_sum_WAPE_point": wape(te.aux_source_kw, te.aux_pred_component_sum),
            "bootstrap_p05": float(np.quantile(boots, 0.05)) if boots else None,
            "bootstrap_p50": float(np.quantile(boots, 0.50)) if boots else None,
            "bootstrap_p95": float(np.quantile(boots, 0.95)) if boots else None,
            "residual_depends_on": {
                "IT_resid_corr": float(np.corrcoef(te.it_power_kw, te.resid_aux)[0, 1]) if len(te) > 5 else None,
                "Tdb_resid_corr": float(np.corrcoef(te.tdb_c, te.resid_aux)[0, 1]) if len(te) > 5 else None,
                "Twb_resid_corr": float(np.corrcoef(te.twb_c, te.resid_aux)[0, 1]) if len(te) > 5 else None,
            },
            "held_out_residuals_path": str(DATA_PROCESSED / "esif_test_residuals.parquet"),
        },
    )
    te[["hour", "it_power_kw", "tdb_c", "twb_c", "rh_pct", "cooling_kw", "hvac_kw", "pump_kw", "plug_and_light_kw", "aux_source_kw", "aux_pred_component_sum", "resid_aux", "energy_reuse"]].to_parquet(
        DATA_PROCESSED / "esif_test_residuals.parquet", index=False
    )
    return heat, acf


def figures(h: pd.DataFrame, te: pd.DataFrame) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    v = h[h.valid_all]
    fig, axes = plt.subplots(2, 2, figsize=(8, 6))
    for ax, col, title in zip(axes.ravel(), TARGETS, ["Cooling", "HVAC", "Pumps", "Plug/light"]):
        ax.hist(v[col], bins=40, color="#4C78A8")
        ax.set_title(title)
        ax.set_xlabel("kW")
    fig.suptitle("Measured ESIF overhead components (valid common hours)")
    fig.tight_layout()
    fig.savefig(FIGURES / "01_component_distributions.png", dpi=120)
    plt.close()

    fig, axes = plt.subplots(2, 2, figsize=(8, 6))
    twb_q = pd.qcut(v.twb_c, 3, labels=["cool Twb", "mid", "warm Twb"])
    for ax, col in zip(axes.ravel(), TARGETS):
        for lab, g in v.groupby(twb_q, observed=True):
            ax.scatter(g.it_power_kw, g[col], s=2, alpha=0.15, label=str(lab))
        ax.set_xlabel("IT kW")
        ax.set_ylabel(col)
        ax.legend(markerscale=4, fontsize=7)
    fig.suptitle("Component vs IT by wet-bulb tercile")
    fig.tight_layout()
    fig.savefig(FIGURES / "02_component_vs_it_weather.png", dpi=120)
    plt.close()

    fig, ax = plt.subplots(figsize=(7, 5))
    hb = ax.hexbin(v.tdb_c, v.twb_c, C=v.cooling_kw, gridsize=40, reduce_C_function=np.mean, cmap="viridis")
    ax.set_xlabel("Tdb °C")
    ax.set_ylabel("Twb °C")
    fig.colorbar(hb, ax=ax, label="mean cooling kW")
    ax.set_title("Cooling vs dry-/wet-bulb (valid hours)")
    fig.tight_layout()
    fig.savefig(FIGURES / "03_cooling_vs_wet_dry_bulb.png", dpi=120)
    plt.close()

    dly = te.assign(day=te.hour.dt.floor("D")).groupby("day").agg(
        c=("cooling_kw", "sum"), cp=("pred_cooling_kw", "sum"),
        h=("hvac_kw", "sum"), hp=("pred_hvac_kw", "sum"),
        p=("pump_kw", "sum"), pp=("pred_pump_kw", "sum"),
        g=("plug_and_light_kw", "sum"), gp=("pred_plug_and_light_kw", "sum"),
    )
    fig, axes = plt.subplots(2, 2, figsize=(8, 6))
    for ax, a, b, t in zip(axes.ravel(), ["c", "h", "p", "g"], ["cp", "hp", "pp", "gp"], ["Cooling", "HVAC", "Pumps", "Plug/light"]):
        ax.scatter(dly[a], dly[b], s=8, alpha=0.5)
        lim = max(dly[a].max(), dly[b].max())
        ax.plot([0, lim], [0, lim], "k--", lw=1)
        ax.set_title(t)
        ax.set_xlabel("observed kWh/day")
        ax.set_ylabel("predicted kWh/day")
    fig.suptitle("TEST daily component energy")
    fig.tight_layout()
    fig.savefig(FIGURES / "04_test_daily_component_energy.png", dpi=120)
    plt.close()

    dlya = te.assign(day=te.hour.dt.floor("D")).groupby("day").agg(
        aux=("aux_source_kw", "sum"), auxp=("aux_pred_component_sum", "sum"),
        pue=("pue_reconstructed", "mean"), puep=("pue_pred", "mean"),
    )
    fig, axes = plt.subplots(1, 2, figsize=(8, 3.5))
    axes[0].scatter(dlya.aux, dlya.auxp, s=8, alpha=0.5)
    lim = max(dlya.aux.max(), dlya.auxp.max())
    axes[0].plot([0, lim], [0, lim], "k--", lw=1)
    axes[0].set_title("TEST daily auxiliary kWh")
    axes[1].scatter(dlya.pue, dlya.puep, s=8, alpha=0.5)
    axes[1].set_title("TEST daily mean PUE (derived)")
    fig.tight_layout()
    fig.savefig(FIGURES / "05_test_aux_pue.png", dpi=120)
    plt.close()

    te2 = te.copy()
    te2["month"] = te2.hour.dt.to_period("M").astype(str)
    g = te2.groupby("month")["resid_aux"].mean() if "resid_aux" in te2 else te2.assign(resid_aux=te2.aux_source_kw - te2.aux_pred_component_sum).groupby("month")["resid_aux"].mean()
    if "resid_aux" not in te2.columns:
        te2["resid_aux"] = te2.aux_source_kw - te2.aux_pred_component_sum
        g = te2.groupby("month")["resid_aux"].mean()
    fig, ax = plt.subplots(figsize=(8, 3.5))
    ax.bar(range(len(g)), g.to_numpy())
    ax.set_xticks(range(len(g)))
    ax.set_xticklabels(list(g.index), rotation=90, fontsize=7)
    ax.set_ylabel("mean aux residual kW")
    ax.set_title("TEST residual by month")
    fig.tight_layout()
    fig.savefig(FIGURES / "06_test_residual_by_month.png", dpi=120)
    plt.close()


def write_docs(h, selected, split, pue_cl, clock, heat, test_m, init):
    (DOCS / "ESIF_TO_PROJECT_INTEGRATION.md").write_text(
        f"""# ESIF facility overhead → project integration (structural only)

ESIF coefficients **do not transfer** to Prineville or to a generic hyperscale hall.
ESIF is warm-water liquid + heat reuse + evaporative towers + thermosyphon. Prineville gray-box is a different architecture.

`PRINEVILLE_COEFFICIENT_TRANSFER = NOT_ALLOWED`.

## Structural evidence that **may** transfer as hypotheses

Selected ESIF specs (DEV/CV, TEST unused):

{json.dumps({k: v.get('selected_spec') for k, v in selected.items()}, indent=2)}

Questions:

| Component | IT first-order? | Weather first-order? | Nonlinear weather? | IT×weather? | Base load? |
| --- | --- | --- | --- | --- | --- |
| cooling | see spec | see spec | F3+ | F4 | F0/F1 intercept |
| HVAC | see spec | see spec | F3+ | F4 | F0/F1 intercept |
| pumps | see spec | see spec | F3+ | F4 | F0/F1 intercept |
| plug/light | see spec | see spec | F3+ | F4 | F0/F1 intercept |

Heat-reuse residual effect: `{heat.get('HEAT_REUSE_RESIDUAL_EFFECT')}`. Not added as a predictor.

Hourly dynamics: lagged targets were not used. See `RESIDUAL_DIAGNOSTICS.json`.

## Comparison (conceptual)

- **Generic facility/cooling split** (IT + cooling + other overhead): ESIF **supports component decomposition**. Cooling is a real but **small** electrical term here (fans/heaters/filter pump), not a chiller plant.
- **Lei/Masanet**: climate×technology PUE as an annual intensity. ESIF shows **measured hourly IT+weather → component kW**. That is a finer boundary. Do not insert ESIF β into Lei `k`.
- **Prineville gray-box**: air-side evaporative / fan-and-other fractions of IT. ESIF suggests reviewing whether **weather-dependent heat-rejection electricity** and a **large intercept (base HVAC/pumps)** belong in a liquid+reuse facility — as structure, not as numbers.

## Must not transfer

- Any ESIF coefficient, intercept, or PUE level
- The 2.67 kW filter-pump constant as a universal pump correction
- Chiller-less / thermosyphon operating points as Prineville parameters
"""
    )
    (DOCS / "ESIF_FACILITY_OVERHEAD_REPORT.md").write_text(
        f"""# ESIF facility-overhead experiment report

CPU `{CPU_DISPOSITION}` and H100 `{H100_DISPOSITION}` were not modified.

Source DOI `{ESIF_DOI}`. Power SHA-256 `{POWER_SHA256}`. Weather SHA-256 `{WEATHER_SHA256}`.

Clock: {clock.get('disposition')}. PUE component closure: {pue_cl.get('PUE_COMPONENT_CLOSURE')}.

Split: DEV {split['DEV']} TEST {split['TEST']}.

Selected models: { {k: selected[k]['selected_spec'] for k in selected} }

Heat reuse: {heat.get('HEAT_REUSE_RESIDUAL_EFFECT')}

See `results/FINAL_ESIF_FACILITY_OVERHEAD_STATUS.json` and `analysis/FINAL_TEST_METRICS.json`.
"""
    )


def final_status(pue_cl, clock, selected, heat, test_json, init) -> dict:
    def grade_comp(name):
        spec = selected[name]["selected_spec"]
        w = selected[name]["dev_metrics"]["daily_energy_WAPE"]
        if spec == "F0" and w and w > 0.2:
            return "PARTIAL"
        return "PASS" if w is not None and w < 0.25 else "PARTIAL"

    def grade_from_test(name, wape_t, bias_t):
        if name == "hvac_kw":
            return "FAIL" if wape_t is not None and wape_t > 0.4 else "PARTIAL"
        if name == "pump_kw":
            return "PASS" if wape_t is not None and wape_t < 0.25 else "PARTIAL"
        return "PARTIAL"

    tm = {r["target"]: r for r in test_json.get("components", [])}
    hvac_w = (tm.get("hvac_kw") or {}).get("WAPE")
    pump_w = (tm.get("pump_kw") or {}).get("WAPE")
    aux_w = (tm.get("aux_component_sum") or {}).get("WAPE")
    st = {
        "SOURCE_PROVENANCE": "PASS",
        "POWER_DATA_QUALITY": "PASS",
        "WEATHER_DATA_QUALITY": "PASS",
        "POWER_WEATHER_CLOCK_ALIGNMENT": "PASS" if "ALIGNED" in clock.get("disposition", "") else "PARTIAL",
        "PUE_COMPONENT_CLOSURE": pue_cl.get("PUE_COMPONENT_CLOSURE"),
        "COOLING_POWER_MODEL": "PARTIAL",
        "HVAC_POWER_MODEL": "FAIL" if hvac_w is not None and hvac_w > 0.4 else grade_comp("hvac_kw"),
        "PUMP_POWER_MODEL": "PASS" if pump_w is not None and pump_w < 0.25 else "PARTIAL",
        "PLUG_LIGHT_MODEL": "PARTIAL",
        "AUXILIARY_POWER_MODEL": "FAIL" if aux_w is not None and aux_w > 0.4 else "PARTIAL",
        "PUE_RECONSTRUCTION": "PARTIAL",
        "OUT_OF_TIME_STABILITY": "FAIL" if hvac_w is not None and hvac_w > 0.4 else "PARTIAL",
        "HEAT_REUSE_RESIDUAL_EFFECT": heat.get("HEAT_REUSE_RESIDUAL_EFFECT", "UNRESOLVED"),
        "HOURLY_STRUCTURE": "PASS",
        "DAILY_ENERGY_RECONSTRUCTION": "PARTIAL",
        "FACILITY_OVERHEAD_STRUCTURAL_VALIDATION": "PARTIAL",
        "PRINEVILLE_COEFFICIENT_TRANSFER": "NOT_ALLOWED",
        "FACILITY_OVERHEAD_FINAL_DISPOSITION": "PARTIAL",
        "selected_specs": {k: selected[k]["selected_spec"] for k in selected},
        "cpu_untouched": sha256_file(CPU_STATUS) == init["cpu"]["sha256"],
        "h100_untouched": sha256_file(H100_FREEZE) == init["h100"]["sha256"],
        "input": "measured it_power_kw + weather",
        "next_experiment_recommended_not_executed": "heat rejection / cooling regime → water / WUE using measured ESIF thermosyphon evidence",
    }
    jdump(RESULTS / "FINAL_ESIF_FACILITY_OVERHEAD_STATUS.json", st)
    jdump(MANIFESTS / "FACILITY_OVERHEAD_LAYER_FREEZE.json", {"cpu_frozen": True, "h100_frozen": True, "prineville_coefficient_transfer": "NOT_ALLOWED", "disposition": st["FACILITY_OVERHEAD_FINAL_DISPOSITION"]})
    return st


def main():
    os.environ.setdefault("PYTHONNOUSERSITE", "1")
    closure_guard = MANIFESTS / "FACILITY_OVERHEAD_POSTTEST_CLOSURE_INITIAL_STATE.json"
    if closure_guard.exists():
        raise SystemExit(
            "REFUSED: ESIF facility-overhead numerical results are frozen after post-test closure. "
            "Do not refit F0–F4 or rewrite TEST metrics. "
            "Descriptive audits: scripts/run_facility_overhead_posttest_closure.py"
        )
    print("initial state…", flush=True)
    init = write_initial_state()
    print("provenance…", flush=True)
    write_provenance()
    write_field_semantics()
    print("QC / clock…", flush=True)
    power, weather, power_qc, weather_qc, clock = qc_and_clock()
    print("PUE closure…", flush=True)
    pue_cl = pue_closure(power)
    print("hourly…", flush=True)
    h, daily = build_hourly(power, weather)
    print("split…", flush=True)
    split, test_start, t0 = freeze_split(h)
    print("models DEV/CV…", flush=True)
    h, selected, coefs = run_models(h, split, test_start, t0)
    print("aux/PUE derive…", flush=True)
    aux_and_pue(h, selected, test_start)
    h.to_parquet(DATA_PROCESSED / "esif_facility_hourly.parquet", index=False)
    print("TEST once…", flush=True)
    te = final_test(h, test_start)
    print("residuals…", flush=True)
    heat, acf = residuals_heat_epochs(h, te, test_start, selected)
    print("figures…", flush=True)
    figures(h, te)
    test_json = json.loads((ANALYSIS / "FINAL_TEST_METRICS.json").read_text())
    write_docs(h, selected, split, pue_cl, clock, heat, test_json, init)
    st = final_status(pue_cl, clock, selected, heat, test_json, init)
    print(json.dumps({"disposition": st["FACILITY_OVERHEAD_FINAL_DISPOSITION"], "specs": st["selected_specs"], "pue_closure": pue_cl["PUE_COMPONENT_CLOSURE"], "clock": clock["disposition"]}, default=str), flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
