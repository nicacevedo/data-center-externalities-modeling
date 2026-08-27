#!/usr/bin/env python3
"""M100 2021 v3 closure library.

Structural identification only. Does not overwrite v2/pilot/suitability_2021.
Does not reprocess raw archives or delete tars.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from m100_2021_common import (
    MAX_GAP_POWER_S,
    NOMINAL_VERTIV_PER_HOUR,
    PREFERRED_LOGICS,
    ROOT,
    grain_parquet,
    month_calendar,
    sea_level_to_station_pa,
)
from m100_suitability_v2 import (
    B3_FORBIDDEN,
    acf_lag,
    expanding_folds,
    label_from_fold_improvements,
    load_month_hourly,
    metrics as metrics_v2,
    ols_fit,
    ols_pred,
    rel_mae_improvement,
    sha256_file,
)

OUT_DIR = ROOT / "results" / "suitability_2021_v3_closure"
V2_DIR = ROOT / "results" / "suitability_2021_v2"
PILOT_DIR = ROOT / "results" / "pilot_facility_2021"
ORIG_SUIT = ROOT / "results" / "suitability_2021"
CANON_PANEL, CANON_DEVICE = PREFERRED_LOGICS["Tot"]
HQ_THRESHOLD = 0.90
DFC_DEVICES = ("cdz1", "cdz2", "cdz3", "cdz4")
NON_DFC_DEVICES = ("cdz5", "cdz6")
TDB_DFC_C = 18.0
HEURISTIC_NOTE = "heuristic, not statistical significance"
NRMSE_DEF = "NRMSE = RMSE / mean(observed target)"
R1_FORBIDDEN = B3_FORBIDDEN + (
    "flow_delta_t_integral", "delta_t_mean", "Portata_1_mean", "Portata_2_mean",
)
FORMULAS = {
    "W0": "P_nonIT = a + b * P_IT",
    "W1": "P_nonIT = a + b*P_IT + c*T_wb",
    "W2": "P_nonIT = a + b*P_IT + c*T_wb + d*P_IT*T_wb",
    "R1": "W2 + e*state + f*state*P_IT + g*state*weather   [REGIME-INTERACTION ORACLE]",
    "D1": "W2_t + phi * P_nonIT_(t-1)   [MEMORY DIAGNOSTIC, not a physical model]",
}
LITERATURE = {
    "paper": "Ngwerume, Tong, Ten, Hu (2026) arXiv:2607.28962",
    "repo_url": "https://github.com/cletuzz00/dc-cooling-thermal-model",
    "pinned_commit": "82854bce62ab361c55e639eddc35623c90068bb6",
    "license": "Apache-2.0",
    "independence": "same-data triangulation; not independent validation",
    "published_mae_kw": 20.88,
    "published_baseline_mae_kw": 95.80,
    "calibration_caveat": "RC parameters, deadbands, setpoints, and initial states unavailable from M100 were manually calibrated in the paper",
}

QUALIFIED_MONTHS = [
    "2021-04", "2021-05", "2021-06", "2021-07", "2021-08",
    "2021-09", "2021-10", "2021-11", "2021-12",
]
NODE_MONTHS = [
    "2021-01", "2021-03", "2021-04", "2021-05", "2021-06",
    "2021-07", "2021-08", "2021-09", "2021-10", "2021-11", "2021-12",
]


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(ROOT.parents[1]), "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unavailable"


def coverage_status(columns: list[str], prefix: str) -> dict:
    cov = f"{prefix}_coverage"
    if cov in columns:
        return {"metric": prefix, "status": "AVAILABLE", "field": cov}
    return {"metric": prefix, "status": "HQ_COVERAGE_NOT_AVAILABLE", "field": None}


def hq_mask_from_coverage(df: pd.DataFrame, field: str | None) -> pd.Series:
    if field is None or field not in df.columns:
        return pd.Series(False, index=df.index)
    return pd.to_numeric(df[field], errors="coerce") >= HQ_THRESHOLD


def energy_quality_mask(df: pd.DataFrame) -> pd.Series:
    """Hours with trapezoidal integrals and gaps within the compaction max-gap."""
    m = pd.Series(True, index=df.index)
    for col in ("Tot_energy_kwh", "Tot_ict_energy_kwh"):
        if col in df.columns:
            m &= df[col].notna()
        else:
            return pd.Series(False, index=df.index)
    for col in ("Tot_largest_gap_seconds", "Tot_ict_largest_gap_seconds"):
        if col in df.columns:
            m &= pd.to_numeric(df[col], errors="coerce") <= MAX_GAP_POWER_S
    return m


def complete_case_mask(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    have = [c for c in cols if c in df.columns]
    return df[have].notna().all(axis=1) & (df["P_IT"] > 0)


def w_feature_names(model: str) -> tuple[str, ...]:
    if model == "W0":
        return ("P_IT",)
    if model == "W1":
        return ("P_IT", "T_wetbulb")
    if model == "W2":
        return ("P_IT", "T_wetbulb", "P_IT:T_wetbulb")
    if model == "R1":
        return ("P_IT", "T_wetbulb", "P_IT:T_wetbulb", "cooling_state",
                "state:P_IT", "state:T_wetbulb")
    raise ValueError(model)


def design_W(df: pd.DataFrame, model: str) -> tuple[np.ndarray, bool, tuple[str, ...]]:
    pit = df["P_IT"].to_numpy(float)
    names = w_feature_names(model)
    if model == "W0":
        return pit.reshape(-1, 1), True, names
    twb = df["T_wetbulb"].to_numpy(float)
    if model == "W1":
        return np.column_stack([pit, twb]), True, names
    if model == "W2":
        return np.column_stack([pit, twb, pit * twb]), True, names
    if model == "R1":
        st = df["cooling_state"].to_numpy(float)
        if any(c in df.columns for c in R1_FORBIDDEN if c in ("heat_transfer_index",)):
            pass
        X = np.column_stack([pit, twb, pit * twb, st, st * pit, st * twb])
        assert "heat_transfer_index" not in names
        return X, True, names
    raise ValueError(model)


def design_descriptor(df: pd.DataFrame, spec: str) -> tuple[np.ndarray, bool, tuple[str, ...]]:
    pit = df["P_IT"].to_numpy(float)
    if spec == "IT":
        return pit.reshape(-1, 1), True, ("P_IT",)
    if spec == "IT_Tdb":
        return np.column_stack([pit, df["T_drybulb"].to_numpy(float)]), True, ("P_IT", "T_drybulb")
    if spec == "IT_Twb":
        return np.column_stack([pit, df["T_wetbulb"].to_numpy(float)]), True, ("P_IT", "T_wetbulb")
    if spec == "IT_Tdb_RH":
        return np.column_stack([
            pit, df["T_drybulb"].to_numpy(float), df["RH"].to_numpy(float)
        ]), True, ("P_IT", "T_drybulb", "RH")
    if spec == "IT_Tdb_interact":
        tdb = df["T_drybulb"].to_numpy(float)
        return np.column_stack([pit, tdb, pit * tdb]), True, ("P_IT", "T_drybulb", "P_IT:T_drybulb")
    if spec == "IT_Twb_interact":
        twb = df["T_wetbulb"].to_numpy(float)
        return np.column_stack([pit, twb, pit * twb]), True, ("P_IT", "T_wetbulb", "P_IT:T_wetbulb")
    raise ValueError(spec)


def metrics(y, p, pit=None, p_fac=None, y_energy=None) -> dict:
    out = metrics_v2(y, p, pit=pit, p_fac=p_fac)
    out["nrmse_definition"] = NRMSE_DEF
    if y_energy is not None:
        ye = np.asarray(y_energy, float)
        pe = np.asarray(p, float)
        ok = np.isfinite(ye) & np.isfinite(pe)
        if ok.any() and np.nansum(ye[ok]) != 0:
            out["represented_timestamp_energy_error_pct"] = float(
                100.0 * (np.sum(pe[ok]) - np.sum(ye[ok])) / np.sum(ye[ok])
            )
        else:
            out["represented_timestamp_energy_error_pct"] = np.nan
    else:
        out["represented_timestamp_energy_error_pct"] = out.get("energy_error_pct")
    out["calendar_full_period_energy_error_pct"] = np.nan
    out["calendar_energy_reported"] = False
    return out


def daily_peak_and_std_error(hours, y, p) -> dict:
    d = pd.DataFrame({"hour": pd.to_datetime(hours, utc=True), "y": y, "p": p})
    d["date"] = d["hour"].dt.tz_convert("UTC").dt.floor("D")
    g = d.groupby("date")
    peak_err = (g["p"].max() - g["y"].max()).abs()
    std_err = (g["p"].std() - g["y"].std()).abs()
    return {
        "daily_peak_mae": float(peak_err.mean()) if len(peak_err) else np.nan,
        "daily_std_mae": float(std_err.mean()) if len(std_err) else np.nan,
        "n_days": int(g.ngroups),
    }


def fit_predict(train, test, model: str, ycol="P_nonIT"):
    Xtr, intercept, names = design_W(train, model)
    Xte, _, _ = design_W(test, model)
    beta = ols_fit(train[ycol].to_numpy(float), Xtr, intercept=intercept)
    phat = ols_pred(beta, Xte, intercept=intercept)
    return beta, phat, names, intercept


def nested_scores(train, test, models, ycol="P_nonIT"):
    yte = test[ycol].to_numpy(float)
    pit = test["P_IT"].to_numpy(float)
    fac = test["P_facility"].to_numpy(float) if "P_facility" in test.columns else pit + yte
    y_energy = None
    if ycol == "P_nonIT" and "P_nonIT_energy_kwh" in test.columns:
        y_energy = test["P_nonIT_energy_kwh"].to_numpy(float)
    elif ycol == "P_cooling" and "P_cooling_energy_kwh" in test.columns:
        y_energy = test["P_cooling_energy_kwh"].to_numpy(float)
    rows, coefs, preds = [], [], {}
    for model in models:
        beta, phat, names, intercept = fit_predict(train, test, model, ycol=ycol)
        preds[model] = phat
        sc = metrics(yte, phat, pit=pit, p_fac=fac, y_energy=y_energy)
        sc.update({"model": model, "target": ycol, "formula": FORMULAS.get(model, model)})
        rows.append(sc)
        terms = (["intercept"] if intercept else []) + list(names)
        for name, val in zip(terms, np.ravel(beta)):
            coefs.append({"model": model, "term": name, "value": float(val), "target": ycol})
    return rows, coefs, preds


def within_month_split(df: pd.DataFrame, mask: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame]:
    sub = df.loc[mask].sort_values("hour_utc")
    n = len(sub)
    if n < 24:
        return sub.iloc[0:0], sub.iloc[0:0]
    k = int(math.floor(n * 2 / 3))
    k = min(max(k, 8), n - 8) if n >= 16 else n // 2
    return sub.iloc[:k].copy(), sub.iloc[k:].copy()


def support_label(value: float, p05: float, p95: float, vmin: float, vmax: float) -> str:
    if not np.isfinite(value):
        return "missing"
    if vmin <= value <= vmax:
        if p05 <= value <= p95:
            return "inside_train_p05_p95"
        return "inside_train_minmax_outside_p05_p95"
    return "outside_train_minmax"


def joint_support_label(labels: list[str]) -> str:
    if any(x == "outside_train_minmax" for x in labels):
        return "outside_train_minmax"
    if any(x == "inside_train_minmax_outside_p05_p95" for x in labels):
        return "inside_train_minmax_outside_p05_p95"
    if all(x == "inside_train_p05_p95" for x in labels):
        return "inside_train_p05_p95"
    return "mixed_or_missing"


def stull_wetbulb_c(t_c: np.ndarray, rh_pct: np.ndarray) -> np.ndarray:
    """Stull (2011) empirical wet-bulb; sensitivity check only."""
    t = np.asarray(t_c, float)
    rh = np.clip(np.asarray(rh_pct, float), 0.0, 100.0)
    return (
        t * np.arctan(0.151977 * np.sqrt(rh + 8.313659))
        + np.arctan(t + rh)
        - np.arctan(rh - 1.676331)
        + 0.00391838 * (rh ** 1.5) * np.arctan(0.023101 * rh)
        - 4.686035
    )


def independent_wetbulb(t_c, td_c, rh_pct, p_pa) -> dict:
    import psychrolib
    psychrolib.SetUnitSystem(psychrolib.SI)
    t = float(t_c)
    rh = float(rh_pct) / 100.0
    p = float(p_pa)
    td = float(td_c)
    out = {"twb_from_tdew": np.nan, "twb_from_rh": np.nan, "twb_stull": np.nan}
    try:
        out["twb_from_tdew"] = float(psychrolib.GetTWetBulbFromTDewPoint(t, td, p))
    except Exception:
        pass
    try:
        out["twb_from_rh"] = float(psychrolib.GetTWetBulbFromRelHum(t, rh, p))
    except Exception:
        pass
    try:
        out["twb_stull"] = float(stull_wetbulb_c(t, rh_pct * 1.0 if rh_pct <= 100 else rh_pct))
    except Exception:
        pass
    if not np.isfinite(out["twb_stull"]):
        out["twb_stull"] = float(stull_wetbulb_c(np.array([t]), np.array([rh_pct]))[0])
    return out


def lag_pairs(df: pd.DataFrame, ycol: str) -> pd.DataFrame:
    s = df.sort_values("hour_utc").copy()
    s["hour_utc"] = pd.to_datetime(s["hour_utc"], utc=True)
    s["y_lag"] = s[ycol].shift(1)
    dt = s["hour_utc"].diff()
    s = s.loc[dt == pd.Timedelta(hours=1)].copy()
    return s.dropna(subset=[ycol, "y_lag", "P_IT", "T_wetbulb"])


def fit_d1(train_pairs: pd.DataFrame, ycol="P_nonIT"):
    Xw, intercept, names = design_W(train_pairs, "W2")
    X = np.column_stack([Xw, train_pairs["y_lag"].to_numpy(float)])
    beta = ols_fit(train_pairs[ycol].to_numpy(float), X, intercept=True)
    return beta, names + ("y_lag",)


def predict_d1_one_step(beta, test_pairs: pd.DataFrame) -> np.ndarray:
    Xw, _, _ = design_W(test_pairs, "W2")
    X = np.column_stack([Xw, test_pairs["y_lag"].to_numpy(float)])
    return ols_pred(beta, X, intercept=True)


def predict_d1_recursive(beta, test: pd.DataFrame, y0: float, ycol="P_nonIT") -> np.ndarray:
    """Forward simulation: never reads observed test targets after initialization."""
    test = test.sort_values("hour_utc").copy()
    hours = pd.to_datetime(test["hour_utc"], utc=True).to_numpy()
    n = len(test)
    pred = np.full(n, np.nan)
    prev_y = float(y0)
    prev_h = None
    for i in range(n):
        if prev_h is not None:
            gap = (pd.Timestamp(hours[i]) - pd.Timestamp(prev_h)) / pd.Timedelta(hours=1)
            if not np.isfinite(gap) or abs(gap - 1.0) > 1e-6:
                # cannot use future observed y; hold last prediction across the gap
                pass
        row = test.iloc[i:i + 1]
        Xw, _, _ = design_W(row, "W2")
        X = np.column_stack([Xw, np.array([prev_y], float)])
        yhat = float(ols_pred(beta, X, intercept=True)[0])
        pred[i] = yhat
        prev_y = yhat
        prev_h = hours[i]
    return pred


def active_liquid_panel(row: pd.Series) -> str:
    """Select active RDHX path. Do not median inactive twins."""
    start = float(row.get("Start_impianto_fraction_time_active", np.nan))
    flow = float(row.get("Portata_attiva_mean", np.nan))
    running = 0.0
    for p in ("P101", "P102", "P103", "P104"):
        col = f"{p}_in_marcia_fraction_time_active"
        if col in row.index and pd.notna(row[col]):
            running = max(running, float(row[col]))
    if (np.isfinite(start) and start >= 0.5) or (np.isfinite(flow) and flow >= 5.0) or running >= 0.5:
        return "active"
    if np.isfinite(flow) and flow < 1.0:
        return "inactive"
    return "unresolved"


def panel_activity_table(liquid: pd.DataFrame) -> pd.DataFrame:
    rows = []
    liquid = liquid.copy()
    liquid["hour_utc"] = pd.to_datetime(liquid["timestamp_utc"], utc=True)
    for panel, g in liquid.groupby(liquid["panel"].astype(str)):
        g = g.sort_values("hour_utc")
        act = g.apply(active_liquid_panel, axis=1)
        rows.append({
            "panel": panel,
            "n": int(len(g)),
            "n_active": int((act == "active").sum()),
            "n_inactive": int((act == "inactive").sum()),
            "n_unresolved": int((act == "unresolved").sum()),
            "flow_median": float(g["Portata_attiva_mean"].median()) if "Portata_attiva_mean" in g else np.nan,
            "flow_p05": float(g["Portata_attiva_mean"].quantile(0.05)) if "Portata_attiva_mean" in g else np.nan,
            "deltaT_median": float(g["delta_t_mean"].median()) if "delta_t_mean" in g else np.nan,
            "start_frac_mean": float(g["Start_impianto_fraction_time_active"].mean())
            if "Start_impianto_fraction_time_active" in g else np.nan,
            "alarm_frac_mean": float(g["Allarme_on_fraction_time_active"].mean())
            if "Allarme_on_fraction_time_active" in g else np.nan,
        })
    return pd.DataFrame(rows)


def hti_on_active_paths(liquid: pd.DataFrame) -> pd.DataFrame:
    liquid = liquid.copy()
    liquid["hour_utc"] = pd.to_datetime(liquid["timestamp_utc"], utc=True)
    liquid["path_status"] = liquid.apply(active_liquid_panel, axis=1)
    out_rows = []
    for hour, g in liquid.groupby("hour_utc"):
        act = g.loc[g["path_status"].eq("active")]
        if len(act) == 0:
            hti = np.nan
            rule = "no_active_path"
            panels = ""
        elif len(act) == 1:
            hti = float(act["flow_delta_t_mean"].iloc[0]) if "flow_delta_t_mean" in act else np.nan
            rule = "single_active"
            panels = str(act["panel"].iloc[0])
        else:
            flows = act["flow_delta_t_mean"].to_numpy(float)
            if len(act) == 2:
                a, b = act["flow_delta_t_mean"].to_numpy(float)
                corr_ok = True
                if np.isfinite(a) and np.isfinite(b) and abs(a - b) > 0.5 * max(abs(a), abs(b), 1.0):
                    corr_ok = False
                if corr_ok:
                    hti = float(np.nanmedian(flows))
                    rule = "redundant_active_median"
                else:
                    hti = np.nan
                    rule = "twin_discrepancy_no_median"
            else:
                hti = float(np.nanmedian(flows))
                rule = "multi_active_median"
            panels = "|".join(act["panel"].astype(str))
        out_rows.append({"hour_utc": hour, "HTI_active": hti, "hti_rule": rule, "active_panels": panels})
    return pd.DataFrame(out_rows)


def load_month_v3(month: str) -> pd.DataFrame:
    df = load_month_hourly(month)
    if df.empty:
        return df
    fac = pd.read_parquet(grain_parquet("facility", month))
    fac["hour_utc"] = pd.to_datetime(fac["timestamp_utc"], utc=True)
    g = fac.loc[(fac["panel"].astype(str) == CANON_PANEL) & (fac["device"].astype(str) == CANON_DEVICE)]
    g = g.drop_duplicates("hour_utc").set_index("hour_utc")
    df = df.copy()
    df["hour_utc"] = pd.to_datetime(df["hour_utc"], utc=True)
    df = df.set_index("hour_utc")
    for col in (
        "Tot_energy_kwh", "Tot_ict_energy_kwh", "Tot_count", "Tot_ict_count",
        "Tot_largest_gap_seconds", "Tot_ict_largest_gap_seconds",
        "Tot_cdz_energy_kwh", "Tot_chiller_energy_kwh", "Tot_qpompe_energy_kwh",
        "Pue_mean",
    ):
        if col in g.columns:
            df[col] = g[col]
    if {"Tot_energy_kwh", "Tot_ict_energy_kwh"}.issubset(df.columns):
        df["P_nonIT_energy_kwh"] = df["Tot_energy_kwh"] - df["Tot_ict_energy_kwh"]
    cool_e = [c for c in ("Tot_cdz_energy_kwh", "Tot_chiller_energy_kwh", "Tot_qpompe_energy_kwh") if c in df.columns]
    if len(cool_e) == 3:
        df["P_cooling_energy_kwh"] = df[cool_e].sum(axis=1)
    wp = grain_parquet("weather", month)
    if wp.exists():
        w = pd.read_parquet(wp)
        w["hour_utc"] = pd.to_datetime(w["timestamp_utc"], utc=True)
        w = w.drop_duplicates("hour_utc").set_index("hour_utc")
        for col in (
            "dew_point_mean", "pressure_mean", "pressure_station_pa", "temp_count",
            "humidity_count", "dew_point_count", "twb_c",
        ):
            if col in w.columns:
                df[col] = w[col]
    df = df.reset_index()
    df["month"] = month
    df["energy_quality"] = energy_quality_mask(df)
    return df


def freeze_hashes() -> dict:
    files = {
        "v2_script": ROOT / "scripts" / "m100_suitability_v2.py",
        "v2_runner": ROOT / "scripts" / "analyze_m100_suitability_v2.py",
        "v2_tests": ROOT / "tests" / "test_m100_suitability_v2.py",
        "v2_report": V2_DIR / "final_report.md",
        "v2_status": V2_DIR / "final_status.json",
        "pilot_status": PILOT_DIR / "pilot_status.json",
        "orig_manifest": ORIG_SUIT / "run_manifest.json",
    }
    out = {}
    for k, p in files.items():
        out[k] = {
            "path": str(p),
            "sha256": sha256_file(p),
            "mtime": p.stat().st_mtime if p.exists() else None,
            "size": p.stat().st_size if p.exists() else None,
        }
    return out


def write_table(df: pd.DataFrame, name: str) -> Path:
    path = OUT_DIR / "tables" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path


def stage_dir(stage: str) -> Path:
    d = OUT_DIR / "stages" / stage
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_stage_status(stage: str, payload: dict) -> None:
    d = stage_dir(stage)
    payload = dict(payload)
    payload["stage"] = stage
    payload["git_head"] = git_head()
    (d / "status.json").write_text(json.dumps(payload, indent=2, default=str) + "\n")


def save_stage_status_month(stage: str, month: str, payload: dict) -> None:
    """Per-month status so array tasks cannot overwrite other months."""
    d = stage_dir(stage)
    payload = dict(payload)
    payload["stage"] = stage
    payload["month"] = month
    payload["git_head"] = git_head()
    (d / f"status_{month}.json").write_text(json.dumps(payload, indent=2, default=str) + "\n")


def rebuild_stage_status_index(stage: str, extra: dict | None = None) -> dict:
    d = stage_dir(stage)
    month_files = sorted(
        p for p in d.glob("status_*.json")
        if p.name != "status.json" and p.stem.startswith("status_")
    )
    months = []
    for p in month_files:
        tag = p.stem.replace("status_", "", 1)
        if tag:
            months.append(tag)
    payload = {
        "ok": True,
        "months": months,
        "per_month_status_files": [p.name for p in month_files],
        "note": "index of per-month status files; not last-array-task overwrite",
    }
    if extra:
        payload.update(extra)
    save_stage_status(stage, payload)
    return payload


def evidence_label_from_improvements(xs, n) -> str:
    return label_from_fold_improvements(xs, n)


STRONG_SUPPORT = "STRONG_SUPPORT"
NOT_REQUIRED_BY_M100_EVIDENCE = "NOT_REQUIRED_BY_M100_EVIDENCE"
NOT_STABLY_SUPPORTED_AS_GENERIC_INPUT = "NOT_STABLY_SUPPORTED_AS_GENERIC_INPUT"
NOT_TESTABLE_FROM_PROCESSED_FIELDS = "NOT_TESTABLE_FROM_PROCESSED_FIELDS"
EXECUTED_SAMPLE_WITH_NUMERICAL_DISCREPANCY = "EXECUTED_SAMPLE_WITH_NUMERICAL_DISCREPANCY"
NOT_SUPPORTED = "NOT_SUPPORTED"
LITERATURE_TRIANGULATION_CAVEAT = "same-data triangulation, not independent validation"


def is_strong_support(label) -> bool:
    return label in ("STRONG SUPPORT", STRONG_SUPPORT)


def as_strong_support_token(label: str) -> str:
    return STRONG_SUPPORT if label == "STRONG SUPPORT" else label


def weather_interaction_label(improvements: list[float]) -> str:
    """0/N folds meeting the 5% MAE heuristic is 'not required', not MIXED."""
    if not improvements:
        return "UNRESOLVED"
    n_ge5 = sum(x >= 0.05 for x in improvements)
    if n_ge5 == 0:
        return NOT_REQUIRED_BY_M100_EVIDENCE
    return evidence_label_from_improvements(improvements, len(improvements))


def regime_generic_input_label(improvements: list[float]) -> str:
    """Partial 5% wins plus later-month deterioration is not a stable generic input."""
    if not improvements:
        return "UNRESOLVED"
    n = len(improvements)
    n_ge5 = sum(x >= 0.05 for x in improvements)
    n_worse = sum(x < 0 for x in improvements)
    if 0 < n_ge5 < n and n_worse > 0:
        return NOT_STABLY_SUPPORTED_AS_GENERIC_INPUT
    if n_ge5 == 0 and n_worse > 0:
        return NOT_STABLY_SUPPORTED_AS_GENERIC_INPUT
    return evidence_label_from_improvements(improvements, n)


def literature_execution_status(mae_vs_bundled, *, failed: bool = False) -> str:
    """Status from sample execution vs bundled output. MAE is in Watts if present."""
    if failed:
        return "LITERATURE_REPRODUCTION_FAILED"
    if mae_vs_bundled is None or not np.isfinite(mae_vs_bundled):
        return "EXECUTED_SAMPLE_NO_BUNDLED_COMPARISON"
    # Unexplained discrepancy vs bundled sample (Watts). 1 kW is far above rounding.
    if float(mae_vs_bundled) > 1000.0:
        return EXECUTED_SAMPLE_WITH_NUMERICAL_DISCREPANCY
    return "REPRODUCED_SAMPLE"


def literature_reason(status: str, mae_vs_bundled=None) -> str:
    caveat = LITERATURE_TRIANGULATION_CAVEAT
    if status == EXECUTED_SAMPLE_WITH_NUMERICAL_DISCREPANCY and mae_vs_bundled is not None and np.isfinite(mae_vs_bundled):
        mae_kw = float(mae_vs_bundled) / 1000.0
        return (
            f"Executed authors' sample drivers/parameters. MAE vs bundled simulated_sample.csv "
            f"is {float(mae_vs_bundled):.2f} W (~{mae_kw:.1f} kW) on sim_Pcool_total_elec_W; "
            f"this numerical discrepancy is not explained by a documented unit or window mismatch. "
            f"{caveat}; no retuning."
        )
    return (
        "Ran authors' sample drivers/parameters. Comparison is to bundled simulated_sample.csv "
        f"and published MAE numbers. Same M100 source; {caveat}; no retuning."
    )


def energy_quality_robustness_from_hq(hq: pd.DataFrame) -> str:
    if hq is None or hq.empty:
        return "UNRESOLVED"
    sub = hq
    if "sample" in hq.columns:
        sub = hq.loc[hq["sample"].eq("energy_quality_filter")]
    if sub.empty or "model" not in sub.columns:
        return "UNRESOLVED"
    imps = []
    for _, g in sub.groupby("fold_id"):
        w0 = g.loc[g["model"].eq("W0"), "mae"]
        w1 = g.loc[g["model"].eq("W1"), "mae"]
        if len(w0) and len(w1):
            imps.append(rel_mae_improvement(float(w0.iloc[0]), float(w1.iloc[0])))
    lab = evidence_label_from_improvements(imps, len(imps) or 0)
    return as_strong_support_token(lab)


def node_timestamp_series(df: pd.DataFrame) -> pd.Series:
    for col in ("timestamp_utc", "hour", "hour_utc", "datetime"):
        if col in df.columns:
            return pd.to_datetime(df[col], utc=True)
    raise KeyError("no node timestamp column among timestamp_utc/hour/hour_utc/datetime")


def format_struct_claim_evidence(s: dict) -> str:
    """Prose fragment for a STRUCTURALLY_SUPPORTED item; never dump a raw dict."""
    ev = s.get("evidence")
    if ev is not None and not isinstance(ev, dict):
        extras = []
        for k in (
            "weather_additive", "weather_interaction", "regime_interaction",
            "temporal_dependence", "recursive_d1_forward_simulator",
        ):
            if k in s and s[k] is not None and k != "evidence":
                extras.append(f"{k}={s[k]}")
        if extras:
            return f"{ev}; " + "; ".join(extras)
        return str(ev)
    parts = []
    for k in (
        "weather_additive", "weather_interaction", "regime_interaction",
        "temporal_dependence", "recursive_d1_forward_simulator",
    ):
        if k in s and s[k] is not None:
            parts.append(f"{k}={s[k]}")
    return "; ".join(parts) if parts else ""


def build_contract(evidence: dict) -> dict:
    """Machine-readable generic facility-model contract generated from evidence labels."""
    def supported(key, extra_ok=("STRONG SUPPORT", STRONG_SUPPORT)):
        return evidence.get(key) in extra_ok

    struct = []
    not_id = []
    if supported("facility_decomposition"):
        struct.append({
            "claim": "P_facility = P_IT + P_cooling + P_aux",
            "evidence": evidence.get("facility_decomposition"),
            "note": "M100 cooling aggregate accounts for nearly all non-IT energy; aux is residual, not a generic fraction",
        })
    else:
        not_id.append({"claim": "P_facility = P_IT + P_cooling + P_aux", "evidence": evidence.get("facility_decomposition")})

    if supported("weather_additive"):
        struct.append({
            "claim": "P_cooling = f_k(P_IT, weather)",
            "evidence": evidence.get("weather_additive"),
            "weather_additive": evidence.get("weather_additive"),
            "weather_interaction": evidence.get("weather_interaction"),
            "regime_interaction": evidence.get("regime_interaction"),
            "note": (
                "k is a cooling/facility archetype; M100 coefficients are not generic. "
                f"IT×weather interaction: {evidence.get('weather_interaction')}. "
                f"M100 Free_Cooling_Status / regime interaction: {evidence.get('regime_interaction')}."
            ),
        })
    if supported("pue_derived"):
        struct.append({
            "claim": "PUE = P_facility / P_IT is a derived output, not a primitive",
            "evidence": evidence.get("pue_derived"),
        })
    temporal = evidence.get("temporal_dependence") or evidence.get("temporal_state")
    if is_strong_support(temporal):
        struct.append({
            "claim": (
                "strong temporal dependence is supported, but the tested recursive D1 model "
                "is not supported as a forward simulator"
            ),
            "evidence": temporal if temporal in (STRONG_SUPPORT, "STRONG SUPPORT") else STRONG_SUPPORT,
            "temporal_dependence": evidence.get("temporal_dependence", temporal),
            "recursive_d1_forward_simulator": evidence.get(
                "recursive_d1_forward_simulator", evidence.get("recursive_dynamics_skill", NOT_SUPPORTED)
            ),
            "note": (
                "Static-map residual autocorrelation supports temporal memory as an identifiability result. "
                "The tested D1 recursion is not a validated state equation and is not an operational simulator."
            ),
        })

    for item, key in [
        ("generic coefficients", "generic_coefficients"),
        ("generic PUE values", "generic_pue"),
        ("generic cooling fractions", "generic_cooling_fraction"),
        ("universal weather variable", "universal_weather_variable"),
        ("universal cooling thresholds", "universal_thresholds"),
        ("generic state parameters", "generic_state_parameters"),
        ("site WUE", "water"),
        ("water withdrawal", "water"),
        ("modern AI workload -> IT power", "modern_ai_it"),
        ("validated D1 state equation / recursive forward simulator", "recursive_d1_forward_simulator"),
        ("IT×weather interaction as a required generic term", "weather_interaction"),
        ("M100 Free_Cooling_Status as a generic planning input", "regime_interaction"),
    ]:
        not_id.append({"claim": item, "evidence": evidence.get(key, "NOT IDENTIFIED BY M100")})

    if not is_strong_support(evidence.get("weather_additive")):
        struct = [s for s in struct if "f_k(P_IT, weather" not in s.get("claim", "")]

    return {
        "role": "EXTERNAL MEASURED FACILITY-PHYSICS BENCHMARK",
        "not": ["generic-DC calibration data", "Prineville telemetry", "modern AI workload data", "water-consumption data"],
        "never_transfer": [
            "coefficients", "PUE levels", "cooling fractions", "control thresholds",
            "GPU behavior", "raw traces",
        ],
        "STRUCTURALLY_SUPPORTED": struct,
        "NOT_IDENTIFIED_BY_M100": not_id,
        "evidence_snapshot": evidence,
        "stop_rule": "M100 CLOSED/FROZEN. STOP M100 MODEL DEVELOPMENT.",
        "M100_CLOSED_FROZEN": True,
    }


def triangulation_rows(evidence: dict) -> list[dict]:
    def row(claim, v3, lit, indep, impl, unc):
        return {
            "structural_claim": claim,
            "M100_v3_evidence": v3,
            "M100_literature_evidence": lit,
            "independent_other_facility_or_model_evidence": indep,
            "generic_implication": impl,
            "remaining_uncertainty": unc,
        }
    return [
        row(
            "facility = IT + cooling + auxiliary",
            evidence.get("facility_decomposition"),
            "Borghesi 2023 / ExaData: Logics Tot, Tot_ict, Tot_cdz/chiller/qpompe; same facility",
            "LBNL 2024 archetypes treat cooling as the dominant non-IT block (model evidence, not M100 replication)",
            "Keep explicit decomposition; do not transfer M100 aux fraction",
            "aux composition unidentified; Tot_servizi not forced into closure",
        ),
        row(
            "weather dependence",
            evidence.get("weather_additive"),
            "Ardebili 2026: DFC when outdoor T below ~18C (system description, same site family); Ngwerume 2026 uses Tamb as driver (same M100 data)",
            "Lei-Masanet 2022 climate-specific PUE; AlphaDataCenterCooling FC/partial/mechanical modes (independent facility)",
            "Reduced-order model must take weather as an input; not a universal descriptor",
            "dry-bulb vs wet-bulb universality unresolved; technology-specific",
        ),
        row(
            "weather x load dependence",
            evidence.get("weather_interaction"),
            "Ngwerume 2026 nonlinear RC+control (same-data triangulation, not nested OLS)",
            "AlphaDataCenterCooling / ExaDigiT: load and outdoor conditions jointly drive plant mode",
            "Allow archetype-specific IT×weather response; do not copy M100 interaction coefficient",
            "M100 nested OLS does not require an IT×weather term",
        ),
        row(
            "free-cooling / operating modes",
            evidence.get("regime_interaction"),
            "Ardebili: 6 CRAC, 4 with DFC, ~18C; Ngwerume: deadband/state persistence, manually calibrated",
            "AlphaDataCenterCooling independent FC / partial-mechanical / mechanical; Frontier/ExaDigiT controls",
            "Generic model may include archetype operating modes; do not transfer M100 FC flag or 18C threshold",
            "M100 Free_Cooling_Status is not stably supported as a generic input; flag is an oracle",
        ),
        row(
            "temporal state / thermal memory",
            evidence.get("temporal_dependence") or evidence.get("temporal_state"),
            "Ngwerume 2026 four-state RC + rejection state + deadband, same M100, MAE 20.88 vs 95.80 constant-COP; parameters hand-calibrated; same-data triangulation, not independent validation",
            "ExaDigiT transient thermo-fluid (different facility); AlphaDataCenterCooling dynamics (independent)",
            "Strong temporal dependence is supported; the tested recursive D1 is not a validated forward simulator",
            "D1 phi is not a thermal capacitance; the D1 state equation was not validated; literature RC is same-data not independent proof",
        ),
        row(
            "node -> facility IT bridge",
            evidence.get("node_bridge"),
            "Borghesi 2023 IPMI node total_power plus Logics Tot_ict (same campaign)",
            "NLR/H100/MLPerf will supply modern AI node power (not yet used)",
            "Interface is valid to attempt; do not interpret offset as PSU efficiency without meter-boundary proof",
            "coverage-incomplete node sums; GPU chain skipped if absent in processed node parquet",
        ),
        row(
            "liquid heat transport",
            evidence.get("thermal_sanity"),
            "ExaData Schneider Q101/Q102 redundant RDHX twins (Borghesi/Ardebili)",
            "not independent thermal-kW closure",
            "HTI is thermal measurement sanity only unless coolant properties are documented",
            "Sep–Oct twin discrepancy; no verified rho/cp conversion",
        ),
        row(
            "PUE as derived output",
            evidence.get("pue_derived"),
            "Logics Pue channel exists; October reported-PUE anomaly on M100",
            "Lei-Masanet/LBNL treat PUE as technology×climate output",
            "Do not use constant PUE as a primitive in the generic simulator",
            "reported Pue channel is not independent validation in anomalous months",
        ),
        row(
            "water consumption unsupported by M100",
            evidence.get("water"),
            "No makeup/withdrawal meter in ExaData inventory used here; circulating Portata_attiva is loop flow",
            "Lei-Masanet WUE and LBNL water archetypes are the intended water layer",
            "empirical M100 WUE = UNSUPPORTED",
            "do not infer consumption from RDHX circulation",
        ),
        row(
            "technology-specific archetypes",
            "M100 is one hybrid air+RDHX HPC facility",
            "same",
            "LBNL 2024 multiple cooling archetypes; Lei-Masanet climate×technology",
            "f_k indexed by archetype k; M100 identifies structure for this k only",
            "modern AI liquid-cooled GPU halls are a different k",
        ),
    ]
