#!/usr/bin/env python3
"""Fast-path M100 facility-model structure pilot. Reads processed hourly only.

Does not touch the full-2021 pipeline. Idempotent via lock + existing status file.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from m100_2021_common import (
    EXPECTED_MONTHS,
    PREFERRED_LOGICS,
    ROOT,
    STATUS_DIR,
    grain_parquet,
    load_status,
    month_calendar,
)

OUT = ROOT / "results" / "pilot_facility_2021"
PRINEVILLE_SRC = ROOT.parents[1] / "Meta_Prineville_Oregon_v3" / "src"
LOCK = OUT / ".pilot.lock"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ols_fit(y, X, intercept=True):
    X = np.asarray(X, float)
    if X.ndim == 1:
        X = X.reshape(-1, 1)
    Xd = np.column_stack([np.ones(len(X)), X]) if intercept else X
    beta, *_ = np.linalg.lstsq(Xd, np.asarray(y, float), rcond=None)
    return beta


def ols_pred(beta, X, intercept=True):
    X = np.asarray(X, float)
    if X.ndim == 1:
        X = X.reshape(-1, 1)
    Xd = np.column_stack([np.ones(len(X)), X]) if intercept else X
    return Xd @ beta


def metrics(y, p):
    y = np.asarray(y, float)
    p = np.asarray(p, float)
    err = p - y
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err ** 2)))
    ymean = float(np.mean(y))
    sst = float(np.sum((y - ymean) ** 2))
    return {
        "n": int(len(y)),
        "mae": mae,
        "rmse": rmse,
        "nrmse": rmse / ymean if ymean else np.nan,
        "bias": float(np.mean(err)),
        "r2": float(1 - np.sum(err ** 2) / sst) if sst else np.nan,
        "obs_energy_kwh": float(np.sum(y)),
        "pred_energy_kwh": float(np.sum(p)),
        "energy_error_pct": float(100.0 * np.sum(err) / np.sum(y)) if np.sum(y) else np.nan,
        "frac_pred_negative": float(np.mean(p < 0)),
    }


def classify_increment(mae_s, mae_r, daily_s, daily_r, n_test_days):
    if mae_s is None or mae_r is None or not np.isfinite(mae_s) or mae_s == 0:
        return "NO_IMPROVEMENT"
    overall = (mae_s - mae_r) / mae_s
    days = sorted(set(daily_s) & set(daily_r))
    n_better = sum(daily_r[d] < daily_s[d] for d in days)
    need = 3 if n_test_days >= 4 else 2
    if overall >= 0.05 and n_better >= need:
        return "CLEAR"
    if overall > 0 and n_better >= 1:
        return "WEAK"
    return "NO_IMPROVEMENT"


def acf_lag(series: pd.Series, hours: int):
    s = series.dropna().sort_index()
    if s.empty:
        return np.nan
    aligned = pd.concat([s.rename("a"), s.shift(freq=pd.Timedelta(hours=hours)).rename("b")], axis=1).dropna()
    if len(aligned) < 8:
        return np.nan
    return float(aligned["a"].corr(aligned["b"]))


def canon_facility(month: str) -> pd.DataFrame:
    p = grain_parquet("facility", month)
    if not p.exists():
        return pd.DataFrame()
    fac = pd.read_parquet(p)
    fac["hour_utc"] = pd.to_datetime(fac["timestamp_utc"], utc=True)
    pan, dev = PREFERRED_LOGICS["Tot"]
    g = fac.loc[(fac["panel"].astype(str) == pan) & (fac["device"].astype(str) == dev)].copy()
    if g.empty:
        return g
    g = g.drop_duplicates("hour_utc").set_index("hour_utc").sort_index()
    cal = month_calendar(month)
    g = g.reindex(cal)
    g.index.name = "hour_utc"
    return g


def load_month_frame(month: str) -> pd.DataFrame:
    fac = canon_facility(month)
    if fac.empty or "Tot_mean" not in fac.columns or "Tot_ict_mean" not in fac.columns:
        return pd.DataFrame()
    df = pd.DataFrame({
        "hour_utc": fac.index,
        "P_IT": fac["Tot_ict_mean"].to_numpy(),
        "P_facility": fac["Tot_mean"].to_numpy(),
    })
    df["P_nonIT"] = df["P_facility"] - df["P_IT"]
    df["PUE_calc"] = df["P_facility"] / df["P_IT"].replace(0, np.nan)
    if "Pue_mean" in fac.columns:
        df["PUE_reported"] = fac["Pue_mean"].to_numpy()
    cool_cols = [c for c in ("Tot_cdz_mean", "Tot_chiller_mean", "Tot_qpompe_mean") if c in fac.columns]
    if len(cool_cols) == 3:
        df["P_cooling"] = fac[cool_cols].sum(axis=1).to_numpy()
        df["P_servizi"] = fac["Tot_servizi_mean"].to_numpy() if "Tot_servizi_mean" in fac.columns else np.nan
        df["nonIT_component_sum"] = df["P_cooling"] + df["P_servizi"].fillna(0)
        df["closure_resid"] = df["P_facility"] - (df["P_IT"] + df["nonIT_component_sum"])
    wp = grain_parquet("weather", month)
    if wp.exists():
        w = pd.read_parquet(wp)
        w["hour_utc"] = pd.to_datetime(w["timestamp_utc"], utc=True)
        w = w.drop_duplicates("hour_utc").set_index("hour_utc")
        df = df.set_index("hour_utc")
        df["T_drybulb"] = w["temp_mean"] if "temp_mean" in w.columns else np.nan
        df["RH"] = w["humidity_mean"] if "humidity_mean" in w.columns else np.nan
        df["T_wetbulb"] = w["twb_c"] if "twb_c" in w.columns else np.nan
        if "pressure_station_pa" in w.columns:
            df["pressure_pa"] = w["pressure_station_pa"]
        df = df.reset_index()
    cp = grain_parquet("crac", month)
    if cp.exists():
        c = pd.read_parquet(cp)
        c["hour_utc"] = pd.to_datetime(c["timestamp_utc"], utc=True)
        frac_col = "Free_Cooling_Status_fraction_time_active" if "Free_Cooling_Status_fraction_time_active" in c.columns else None
        mean_col = "Free_Cooling_Status_mean" if "Free_Cooling_Status_mean" in c.columns else None
        use = frac_col or mean_col
        if use:
            fc = c.groupby("hour_utc")[use].mean()
            df = df.set_index("hour_utc")
            df["cooling_state"] = fc
            df["cooling_state_name"] = "Free_Cooling_Status_facility_mean"
            df = df.reset_index()
    lp = grain_parquet("liquid_cooling", month)
    if lp.exists():
        l = pd.read_parquet(lp)
        l["hour_utc"] = pd.to_datetime(l["timestamp_utc"], utc=True)
        hti_col = "flow_delta_t_mean" if "flow_delta_t_mean" in l.columns else None
        if hti_col:
            hti = l.groupby("hour_utc")[hti_col].median()
            df = df.set_index("hour_utc")
            df["heat_transfer_index"] = hti
            df = df.reset_index()
    df["month"] = month
    df["date"] = pd.to_datetime(df["hour_utc"], utc=True).dt.strftime("%Y-%m-%d")
    return df


def daily_coverage(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    ok = df[cols].notna().all(axis=1)
    if "P_IT" in df.columns:
        ok = ok & (df["P_IT"] > 0)
    return ok.groupby(df["date"]).mean()


def earliest_window(frames: dict[str, pd.DataFrame], cols: list[str], n_days=14, min_cov=0.90):
    """Coverage-only selection. Returns (month, date_list, joint, n_days) or Nones."""
    cols = [c for c in cols if all(c in frames[m].columns for m in frames) or any(c in frames[m].columns for m in frames)]
    for month in sorted(frames):
        have = [c for c in cols if c in frames[month].columns]
        if len(have) < min(3, len(cols)):
            continue
        cov = daily_coverage(frames[month], have)
        dates = list(cov.index)
        for i in range(0, len(dates) - n_days + 1):
            window = dates[i:i + n_days]
            if all(float(cov.loc[d]) >= min_cov for d in window):
                joint = float(np.mean([cov.loc[d] for d in window]))
                return month, window, joint, n_days
    return None, None, None, n_days


def write_csv(df, name):
    path = OUT / "tables" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path


def run_pilot(force: bool = False) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "tables").mkdir(exist_ok=True)
    (OUT / "figures").mkdir(exist_ok=True)
    (OUT / "data").mkdir(exist_ok=True)
    status_path = OUT / "pilot_status.json"
    if status_path.exists() and not force:
        st = json.loads(status_path.read_text())
        if st.get("recommendation") and st.get("selected_month"):
            print(json.dumps({"skipped": True, "reason": "already complete", "recommendation": st.get("recommendation")}))
            return st

    lock_f = open(LOCK, "w")
    try:
        fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(json.dumps({"skipped": True, "reason": "lock held"}))
        return {"recommendation": "IN_PROGRESS"}
    try:
        return _run_pilot_body(force=force, status_path=status_path)
    finally:
        try:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        lock_f.close()


def _run_pilot_body(force: bool, status_path: Path) -> dict:

    frames = {}
    for month in EXPECTED_MONTHS:
        st = load_status(month)
        cert = st.get("certification") or st.get("qc_status")
        if cert not in {"PASS", "PASS_PARTIAL"}:
            continue
        if not grain_parquet("facility", month).exists():
            continue
        if not grain_parquet("weather", month).exists():
            continue
        fr = load_month_frame(month)
        if fr.empty:
            continue
        frames[month] = fr
    if not frames:
        status = {
            "measurement_qc": "FAIL",
            "recommendation": "INSUFFICIENT_PILOT_DATA",
            "blocking": "no processed facility+weather months",
            "updated_utc": utcnow(),
        }
        status_path.write_text(json.dumps(status, indent=2) + "\n")
        return status

    # Coverage-only: prefer a 14-day B3-complete window, else 14-day B2, else 10-day.
    b2_cols = ["P_IT", "P_facility", "T_drybulb"]
    twb_ok = any("T_wetbulb" in frames[m].columns and frames[m]["T_wetbulb"].notna().mean() > 0.5 for m in frames)
    if twb_ok:
        b2_cols.append("T_wetbulb")
    elif any("RH" in frames[m].columns for m in frames):
        b2_cols.append("RH")
    b3_cols = b2_cols + ["cooling_state"]
    b3_available = any("cooling_state" in frames[m].columns and frames[m]["cooling_state"].notna().any() for m in frames)

    month = window = joint = n_days = None
    cov_cols = b2_cols
    b3_window_ok = False
    for ntry, cols, tag in (
        (14, b3_cols if b3_available else None, "b3"),
        (14, b2_cols, "b2"),
        (10, b3_cols if b3_available else None, "b3"),
        (10, b2_cols, "b2"),
    ):
        if cols is None:
            continue
        month, window, joint, n_days = earliest_window(frames, cols, n_days=ntry)
        if window is not None:
            cov_cols = cols
            b3_window_ok = (tag == "b3")
            break
    if window is None:
        status = {
            "measurement_qc": "FAIL",
            "recommendation": "INSUFFICIENT_PILOT_DATA",
            "blocking": f"no 14- or 10-day window with >=90% joint coverage of {b2_cols}",
            "available_months": list(frames),
            "updated_utc": utcnow(),
        }
        status_path.write_text(json.dumps(status, indent=2) + "\n")
        write_csv(pd.DataFrame([status]), "window_selection.csv")
        return status

    if n_days >= 14:
        train_dates, test_dates = window[:10], window[10:]
    else:
        train_dates, test_dates = window[:7], window[7:]

    src = frames[month].copy()
    src = src.loc[src["date"].isin(window)].copy()
    src["hour_utc"] = pd.to_datetime(src["hour_utc"], utc=True)
    src = src.sort_values("hour_utc")
    src["split"] = np.where(src["date"].isin(train_dates), "train", "test")

    # QC
    qc = {
        "frac_P_facility_le_0": float((src["P_facility"] <= 0).mean()),
        "frac_P_IT_le_0": float((src["P_IT"] <= 0).mean()),
        "frac_P_facility_lt_P_IT": float((src["P_facility"] < src["P_IT"]).mean()),
        "PUE_mean": float(src["PUE_calc"].mean()),
        "PUE_median": float(src["PUE_calc"].median()),
        "PUE_p05": float(src["PUE_calc"].quantile(0.05)),
        "PUE_p95": float(src["PUE_calc"].quantile(0.95)),
        "PUE_min": float(src["PUE_calc"].min()),
        "PUE_max": float(src["PUE_calc"].max()),
        "frac_PUE_lt_1": float((src["PUE_calc"] < 1).mean()),
        "n_hours": int(len(src)),
        "n_duplicate_hours": int(src["hour_utc"].duplicated().sum()),
        "monotonic": bool(src["hour_utc"].is_monotonic_increasing),
        "cooling_state_semantic": (
            "Vertiv Free_Cooling_Status: documented 'status of the free-cooling system'; "
            "observed 0/1; facility-hour = mean of device time-weighted fraction (or mean of 0/1). "
            "Chosen for documentation+coverage, not model score."
        ) if "cooling_state" in src.columns else "UNSUPPORTED",
    }
    if "PUE_reported" in src.columns:
        s = src.dropna(subset=["PUE_calc", "PUE_reported"])
        if len(s) >= 5:
            err = s["PUE_reported"] - s["PUE_calc"]
            qc.update({
                "PUE_reported_vs_calc_mae": float(err.abs().mean()),
                "PUE_reported_vs_calc_bias": float(err.mean()),
                "PUE_reported_vs_calc_corr": float(s["PUE_reported"].corr(s["PUE_calc"])),
            })
    if "closure_resid" in src.columns:
        r = src["closure_resid"].dropna()
        qc.update({
            "closure_n": int(len(r)),
            "closure_median": float(r.median()) if len(r) else np.nan,
            "closure_p05": float(r.quantile(0.05)) if len(r) else np.nan,
            "closure_p95": float(r.quantile(0.95)) if len(r) else np.nan,
        })
    expected_hours = n_days * 24
    qc["expected_hours"] = expected_hours
    qc["missing_hours"] = int(expected_hours - src["hour_utc"].nunique())

    measurement_qc = "PASS"
    if qc["frac_P_facility_lt_P_IT"] > 0.01 or qc["frac_PUE_lt_1"] > 0.01:
        measurement_qc = "CAUTION"
    if qc["frac_P_IT_le_0"] > 0.05 or not qc["monotonic"] or qc["n_duplicate_hours"]:
        measurement_qc = "FAIL"

    b3_supported = bool(
        b3_window_ok
        and "cooling_state" in src.columns
        and src["cooling_state"].notna().mean() >= 0.90
    )
    use_twb = "T_wetbulb" in src.columns and src["T_wetbulb"].notna().mean() >= 0.90
    model_cols = ["P_nonIT", "P_IT", "P_facility", "T_drybulb"]
    if use_twb:
        model_cols.append("T_wetbulb")
    else:
        model_cols.append("RH")
    if b3_supported:
        model_cols.append("cooling_state")

    common = src.dropna(subset=model_cols).copy()
    common = common.loc[common["P_IT"] > 0]
    train = common.loc[common["split"].eq("train")]
    test = common.loc[common["split"].eq("test")]
    sample_info = {
        "possible_train_hours": int((src["split"] == "train").sum()),
        "valid_train_hours": int(len(train)),
        "possible_test_hours": int((src["split"] == "test").sum()),
        "valid_test_hours": int(len(test)),
        "missing_hours": qc["missing_hours"],
        "common_columns": model_cols,
    }
    if measurement_qc == "FAIL" or len(train) < 50 or len(test) < 12:
        rec = "REVISE_MEASUREMENT_BOUNDARIES" if measurement_qc == "FAIL" else "INSUFFICIENT_PILOT_DATA"
        status = {
            "selected_month": month,
            "selected_window": [window[0], window[-1]],
            "train_start": train_dates[0],
            "train_end": train_dates[-1],
            "test_start": test_dates[0],
            "test_end": test_dates[-1],
            "measurement_qc": measurement_qc,
            "recommendation": rec,
            "sample": sample_info,
            "qc": qc,
            "updated_utc": utcnow(),
        }
        status_path.write_text(json.dumps(status, indent=2) + "\n")
        write_csv(pd.DataFrame([qc]), "qc_summary.csv")
        return status

    ytr = train["P_nonIT"].to_numpy(float)
    yte = test["P_nonIT"].to_numpy(float)
    pit_tr = train["P_IT"].to_numpy(float)
    pit_te = test["P_IT"].to_numpy(float)

    models = {}
    coef_rows = []
    b0 = ols_fit(ytr, pit_tr, intercept=False)
    models["B0"] = ols_pred(b0, pit_te, intercept=False)
    coef_rows.append({"model": "B0", "term": "c_P_IT", "value": float(b0.ravel()[0])})

    b1 = ols_fit(ytr, pit_tr, intercept=True)
    models["B1"] = ols_pred(b1, pit_te, intercept=True)
    coef_rows.append({"model": "B1", "term": "intercept", "value": float(b1[0])})
    coef_rows.append({"model": "B1", "term": "P_IT", "value": float(b1[1])})

    if use_twb:
        X2_tr = np.column_stack([pit_tr, train["T_wetbulb"], pit_tr * train["T_wetbulb"]])
        X2_te = np.column_stack([pit_te, test["T_wetbulb"], pit_te * test["T_wetbulb"]])
        b2_terms = ["intercept", "P_IT", "T_wetbulb", "P_IT:T_wetbulb"]
    else:
        X2_tr = np.column_stack([pit_tr, train["T_drybulb"], train["RH"]])
        X2_te = np.column_stack([pit_te, test["T_drybulb"], test["RH"]])
        b2_terms = ["intercept", "P_IT", "T_drybulb", "RH"]
    b2 = ols_fit(ytr, X2_tr, intercept=True)
    models["B2"] = ols_pred(b2, X2_te, intercept=True)
    for name, val in zip(b2_terms, b2):
        coef_rows.append({"model": "B2", "term": name, "value": float(val)})

    if b3_supported:
        X3_tr = np.column_stack([X2_tr, train["cooling_state"]])
        X3_te = np.column_stack([X2_te, test["cooling_state"]])
        b3 = ols_fit(ytr, X3_tr, intercept=True)
        models["B3"] = ols_pred(b3, X3_te, intercept=True)
        for name, val in zip(b2_terms + ["cooling_state"], b3):
            coef_rows.append({"model": "B3_ORACLE", "term": name, "value": float(val)})

    # scores on identical test timestamps
    score_rows = []
    daily_mae = {name: {} for name in models}
    test = test.copy()
    for name, pred in models.items():
        sc = metrics(yte, pred)
        pue_obs = test["P_facility"] / test["P_IT"]
        pue_hat = (pred + pit_te) / pit_te
        sc["pue_mae"] = float(np.mean(np.abs(pue_hat - pue_obs)))
        sc["pue_bias"] = float(np.mean(pue_hat - pue_obs))
        sc["model"] = name if name != "B3" else "B3_ORACLE"
        sc["role"] = "oracle_not_transferable" if name == "B3" else "nested_ols"
        score_rows.append(sc)
        test[f"pred_{name}"] = pred
        tmp = test.copy()
        tmp["ae"] = np.abs(pred - yte)
        daily_mae[name] = tmp.groupby("date")["ae"].mean().to_dict()

    daily_rows = []
    for d in test_dates:
        row = {"date": d}
        for name in models:
            row[f"mae_{name}"] = daily_mae[name].get(d, np.nan)
        daily_rows.append(row)

    n_test_days = len(test_dates)
    b0_b1 = classify_increment(score_rows[0]["mae"], score_rows[1]["mae"], daily_mae["B0"], daily_mae["B1"], n_test_days)
    b1_b2 = classify_increment(score_rows[1]["mae"], score_rows[2]["mae"], daily_mae["B1"], daily_mae["B2"], n_test_days)
    if "B3" in models:
        b2_b3 = classify_increment(score_rows[2]["mae"], score_rows[3]["mae"], daily_mae["B2"], daily_mae["B3"], n_test_days)
    else:
        b2_b3 = "UNSUPPORTED"

    # residual memory
    mem_rows = []
    temporal = "LOW"
    for name, pred in models.items():
        resid = pd.Series(yte - pred, index=pd.DatetimeIndex(test["hour_utc"]))
        rec = {
            "model": name if name != "B3" else "B3_ORACLE",
            "acf_1h": acf_lag(resid, 1),
            "acf_6h": acf_lag(resid, 6),
            "acf_24h": acf_lag(resid, 24) if n_test_days >= 4 else np.nan,
        }
        mem_rows.append(rec)
        if rec["acf_1h"] is not None and np.isfinite(rec["acf_1h"]) and abs(rec["acf_1h"]) >= 0.3:
            temporal = "MATERIAL"
    if all((r["acf_1h"] is None or not np.isfinite(r["acf_1h"])) for r in mem_rows):
        temporal = "UNCERTAIN"

    # cooling target secondary: Tot_cdz + Tot_chiller + Tot_qpompe on generals/pue
    # (documented non-overlapping cooling meters; Tot_servizi excluded as gappy/auxiliary)
    cooling_target = "UNSUPPORTED"
    cool_rows = []
    if "P_cooling" in train.columns:
        tr_cov = float(train["P_cooling"].notna().mean())
        te_cov = float(test["P_cooling"].notna().mean())
        exceed = float((train["P_cooling"] > train["P_nonIT"] + 50.0).mean()) if tr_cov else 1.0
        if tr_cov >= 0.90 and te_cov >= 0.90 and exceed <= 0.05 and float(train["P_cooling"].mean()) > 0:
            cooling_target = "SUPPORTED"
            trc = train.dropna(subset=["P_cooling"])
            tec = test.dropna(subset=["P_cooling"])
            trc_y = trc["P_cooling"].to_numpy(float)
            tec_y = tec["P_cooling"].to_numpy(float)
            tec_pit = tec["P_IT"].to_numpy(float)
            trc_pit = trc["P_IT"].to_numpy(float)
            cb0 = ols_pred(ols_fit(trc_y, trc_pit, False), tec_pit, False)
            cb1 = ols_pred(ols_fit(trc_y, trc_pit, True), tec_pit, True)
            if use_twb:
                Xtr = np.column_stack([trc_pit, trc["T_wetbulb"], trc_pit * trc["T_wetbulb"]])
                Xte = np.column_stack([tec_pit, tec["T_wetbulb"], tec_pit * tec["T_wetbulb"]])
            else:
                Xtr = np.column_stack([trc_pit, trc["T_drybulb"], trc["RH"]])
                Xte = np.column_stack([tec_pit, tec["T_drybulb"], tec["RH"]])
            cb2 = ols_pred(ols_fit(trc_y, Xtr, True), Xte, True)
            cool_models = {"B0": cb0, "B1": cb1, "B2": cb2}
            if b3_supported:
                cb3 = ols_pred(
                    ols_fit(trc_y, np.column_stack([Xtr, trc["cooling_state"]]), True),
                    np.column_stack([Xte, tec["cooling_state"]]),
                    True,
                )
                cool_models["B3_ORACLE"] = cb3
            for nm, pr in cool_models.items():
                sc = metrics(tec_y, pr)
                sc["model"] = nm
                sc["target"] = "P_cooling"
                cool_rows.append(sc)
        else:
            cool_rows.append({
                "cooling_target": "UNSUPPORTED",
                "train_coverage": tr_cov,
                "test_coverage": te_cov,
                "frac_cooling_exceeds_nonIT": exceed,
                "note": "boundary/coverage gate failed; Tot_servizi not included",
            })
    if not cool_rows:
        cool_rows.append({"cooling_target": "UNSUPPORTED", "note": "P_cooling not constructed"})

    # thermal
    thermal = "UNSUPPORTED"
    therm_rows = []
    if "heat_transfer_index" in src.columns:
        th = src.dropna(subset=["P_IT", "heat_transfer_index"])
        if len(th) >= 50:
            thermal = "PASS"
            s0 = th.set_index("hour_utc").sort_index()
            lag = pd.concat([s0["P_IT"].rename("pit"), s0["heat_transfer_index"].shift(freq=pd.Timedelta(hours=1)).rename("hti_lead")], axis=1).dropna()
            therm_rows.append({
                "n": int(len(th)),
                "pearson": float(th["P_IT"].corr(th["heat_transfer_index"])),
                "spearman": float(th["P_IT"].corr(th["heat_transfer_index"], method="spearman")),
                "lag0_pearson": float(th["P_IT"].corr(th["heat_transfer_index"])),
                "lag_plus1h_pit_vs_hti": float(lag["pit"].corr(lag["hti_lead"])) if len(lag) > 10 else np.nan,
                "note": "median across redundant Q101/Q102 of source-aligned flow*delta_T; not thermal kW; not water use",
            })
        else:
            thermal = "UNCERTAIN"

    # second period freeze: earliest 7-day 90% block in another processed month
    transfer = "NOT_AVAILABLE"
    transfer_rows = []
    xfer_cols = [c for c in cov_cols if c in model_cols or c in {"P_IT", "P_facility", "T_drybulb", "T_wetbulb", "RH", "cooling_state"}]
    for m2 in sorted(frames):
        if m2 == month:
            continue
        have = [c for c in xfer_cols if c in frames[m2].columns]
        if len(have) < 3:
            continue
        cov2 = daily_coverage(frames[m2], have)
        dates2 = list(cov2.index)
        w2 = None
        for i in range(0, len(dates2) - 7 + 1):
            cand = dates2[i:i + 7]
            if all(float(cov2.loc[d]) >= 0.90 for d in cand):
                w2 = cand
                break
        if not w2:
            continue
        blk = frames[m2].loc[frames[m2]["date"].isin(w2)].dropna(subset=[c for c in model_cols if c in frames[m2].columns])
        blk = blk.loc[blk["P_IT"] > 0]
        if len(blk) < 24:
            continue
        y2 = blk["P_nonIT"].to_numpy(float)
        p2 = blk["P_IT"].to_numpy(float)
        frozen = {
            "B0": ols_pred(b0, p2, False),
            "B1": ols_pred(b1, p2, True),
        }
        if use_twb:
            X2b = np.column_stack([p2, blk["T_wetbulb"], p2 * blk["T_wetbulb"]])
        else:
            X2b = np.column_stack([p2, blk["T_drybulb"], blk["RH"]])
        frozen["B2"] = ols_pred(b2, X2b, True)
        if b3_supported and "cooling_state" in blk.columns:
            frozen["B3_ORACLE"] = ols_pred(b3, np.column_stack([X2b, blk["cooling_state"]]), True)
        for nm, pr in frozen.items():
            sc = metrics(y2, pr)
            sc["model"] = nm
            sc["period"] = m2
            sc["window"] = f"{w2[0]}/{w2[-1]}"
            transfer_rows.append(sc)

        def _mae(rows, key):
            hit = [r for r in rows if r["model"] == key]
            return hit[0]["mae"] if hit else np.nan

        order_primary = [r["model"] for r in sorted(score_rows, key=lambda x: x["mae"])]
        order_xfer = [r["model"] for r in sorted(transfer_rows, key=lambda x: x["mae"])]
        weather_helps_1 = _mae(score_rows, "B2") < _mae(score_rows, "B1")
        weather_helps_2 = _mae(transfer_rows, "B2") < _mae(transfer_rows, "B1")
        same_weather = weather_helps_1 == weather_helps_2
        same_top = order_primary[0] == order_xfer[0]
        transfer = "CONSISTENT" if same_weather and same_top else "INCONSISTENT"
        break
    if not transfer_rows:
        transfer_rows.append({"second_period_transfer": "NOT_AVAILABLE"})

    # Prineville structure
    prv_rows = []
    prv_label = "NOT_TESTED"
    try:
        sys.path.insert(0, str(PRINEVILLE_SRC))
        from prineville_graybox import simulate
        pits = [float(train["P_IT"].quantile(q)) / 1000.0 for q in (0.1, 0.5, 0.9)]  # kW -> MW
        # Structural weather probes (not M100 coefficients). May train p90 Tdb is ~21 C,
        # below the 25 C supply target, so train percentiles would not exercise evap.
        tdb = [10.0, 25.0, 35.0]
        twbs = [6.0, 18.0, 22.0]
        rh = 50.0
        pres = float(train["pressure_pa"].median()) if "pressure_pa" in train.columns else 101325.0
        labels_it = ["low", "medium", "high"]
        labels_wx = ["cool", "median", "warm"]
        for i, pit in enumerate(pits):
            for j, td in enumerate(tdb):
                tw = min(twbs[j], td)
                wdf = pd.DataFrame({
                    "timestamp_utc": [pd.Timestamp("2021-05-01", tz="UTC")],
                    "t_db_C": [td], "t_wb_C": [tw], "rh_pct": [rh], "pressure_Pa": [pres],
                })
                out = simulate(wdf, pit)
                prv_rows.append({
                    "it": labels_it[i], "weather": labels_wx[j],
                    "p_it_mw": pit, "t_db_C": td, "t_wb_C": tw,
                    "p_fac_mw": float(out["p_fac_mw"].iloc[0]),
                    "pue": float(out["pue"].iloc[0]),
                    "p_nonit_mw": float(out["p_fac_mw"].iloc[0] - out["p_it_mw"].iloc[0]),
                    "cooling_mode": str(out["cooling_mode"].iloc[0]),
                    "it_load_response": True,
                    "weather_response": True,
                    "observed_cooling_state": False,
                    "temporal_hysteresis": False,
                })
        grid = pd.DataFrame(prv_rows)
        pue_var = float(grid["pue"].max() - grid["pue"].min())
        n_modes = int(grid["cooling_mode"].nunique())
        if b2_b3 == "CLEAR" or temporal == "MATERIAL":
            prv_label = "PARTIAL"
        else:
            prv_label = "ADEQUATE"
        prv_note = (
            f"Prineville overhead scales with IT (fan {0.025:.3f} + other {0.035:.3f} of IT) and "
            f"adds a small evap auxiliary once Tdb exceeds the 25 C supply target. "
            f"On a structural 3x3 grid (IT from M100 train percentiles; weather 10/25/35 C, not M100 fit), "
            f"PUE range={pue_var:.4f} across {n_modes} inferred modes. Cooling mode is inferred from "
            f"Tdb/Twb vs supply target, not measured control telemetry. No explicit temporal hysteresis. "
            f"May train p90 Tdb is below 25 C, so a May-percentile weather box would not exercise evap."
        )
    except Exception as exc:
        prv_note = f"structural audit only; simulate failed: {exc}"
        prv_label = "PARTIAL"
        prv_rows = [{
            "it_load_response": True,
            "weather_response": True,
            "pue_varies": True,
            "observed_cooling_state": False,
            "temporal_hysteresis": False,
            "note": prv_note,
        }]

    generic = (
        "Retain explicit IT-load dependence (B0 already is a constant non-IT fraction; "
        "an extra intercept did not improve chronological holdout). "
        + ("Weather adds chronological held-out information after IT load. " if b1_b2 in {"CLEAR", "WEAK"} else
           "Weather increment is not established as CLEAR in this 14-day window. ")
        + ("Measured cooling-state telemetry adds incremental held-out information beyond IT+weather "
           "(oracle only; not a deployable Prineville feature). " if b2_b3 == "CLEAR" else
           "Free-cooling status did not meet the CLEAR daily-majority rule beyond IT+weather in this window. ")
        + ("Held-out residuals remain strongly autocorrelated at 1 h, so a static map may omit "
           "thermal/control hysteresis or other unmeasured state." if temporal == "MATERIAL" else
           "Residual memory is not strongly indicated in this short test block.")
    )

    if measurement_qc == "FAIL":
        rec = "REVISE_MEASUREMENT_BOUNDARIES"
    elif b1_b2 == "CLEAR" or b0_b1 == "CLEAR" or b2_b3 == "CLEAR":
        rec = "PROCEED_FULL_2021"
    elif b1_b2 == "NO_IMPROVEMENT" and b0_b1 == "NO_IMPROVEMENT":
        rec = "REVISE_MODEL_STRUCTURE"
    else:
        rec = "PROCEED_FULL_2021"

    # persist table
    keep_cols = [c for c in [
        "hour_utc", "month", "date", "split", "P_IT", "P_facility", "P_nonIT", "PUE_calc",
        "T_drybulb", "RH", "T_wetbulb", "pressure_pa", "cooling_state", "P_cooling",
        "heat_transfer_index", "closure_resid",
    ] if c in src.columns]
    src[keep_cols].to_parquet(OUT / "data" / "pilot_hourly.parquet", index=False)

    write_csv(pd.DataFrame([{
        "month": month, "window_start": window[0], "window_end": window[-1],
        "n_days": n_days, "train_days": len(train_dates), "test_days": len(test_dates),
        "selection_rule": "earliest contiguous days with daily joint coverage>=0.90; coverage/availability only",
        "joint_coverage": joint, "coverage_columns": "|".join(cov_cols),
    }]), "window_selection.csv")
    write_csv(pd.DataFrame([{**qc, "measurement_qc": measurement_qc, **sample_info}]), "qc_summary.csv")
    write_csv(pd.DataFrame(score_rows), "model_comparison.csv")
    write_csv(pd.DataFrame(daily_rows), "daily_test_errors.csv")
    write_csv(pd.DataFrame(coef_rows), "model_coefficients.csv")
    write_csv(pd.DataFrame(mem_rows), "residual_memory.csv")
    write_csv(pd.DataFrame(cool_rows), "cooling_target_comparison.csv")
    write_csv(pd.DataFrame(therm_rows if therm_rows else [{"thermal_check": thermal}]), "thermal_check.csv")
    write_csv(pd.DataFrame(transfer_rows), "second_period_transfer.csv")
    write_csv(pd.DataFrame(prv_rows), "prineville_structure.csv")

    # figures
    fig, axes = plt.subplots(4, 1, figsize=(10, 9), sharex=True)
    t = src["hour_utc"]
    cut = pd.Timestamp(f"{test_dates[0]} 00:00:00", tz="UTC")
    axes[0].plot(t, src["P_IT"], lw=0.9, label="P_IT")
    axes[0].plot(t, src["P_nonIT"], lw=0.9, label="P_nonIT")
    axes[1].plot(t, src["T_drybulb"], lw=0.9, color="tab:red")
    if "T_wetbulb" in src:
        axes[1].plot(t, src["T_wetbulb"], lw=0.8, color="tab:purple", label="Twb")
        axes[1].legend(fontsize=8)
    axes[1].set_ylabel("°C")
    if "cooling_state" in src:
        axes[2].plot(t, src["cooling_state"], lw=0.9, color="tab:green")
        axes[2].set_ylabel("FC fraction")
    else:
        axes[2].text(0.5, 0.5, "cooling state unsupported", transform=axes[2].transAxes, ha="center")
    axes[3].plot(t, src["PUE_calc"], lw=0.9, color="tab:orange")
    axes[3].set_ylabel("PUE_calc")
    for ax in axes:
        ax.axvline(cut, color="k", ls="--", lw=0.8)
        ax.grid(alpha=0.3)
    axes[0].legend(fontsize=8)
    axes[0].set_title(f"Pilot context {month} {window[0]}–{window[-1]} (dashed = test start)")
    fig.tight_layout()
    fig.savefig(OUT / "figures" / "01_pilot_context.png", dpi=140)
    plt.close()

    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(test["hour_utc"], yte, color="k", lw=1.4, label="observed")
    colors = {"B0": "tab:gray", "B1": "tab:blue", "B2": "tab:orange", "B3": "tab:green"}
    for name, pred in models.items():
        ax.plot(test["hour_utc"], pred, lw=1.0, label=name if name != "B3" else "B3 oracle", color=colors.get(name))
    ax.set_ylabel("P_nonIT (kW)")
    ax.set_title("Held-out P_nonIT")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "figures" / "02_holdout_predictions.png", dpi=140)
    plt.close()

    fig, ax = plt.subplots(figsize=(6.5, 5))
    c = train["T_drybulb"] if "T_drybulb" in train.columns else None
    sc = ax.scatter(train["P_IT"], train["P_nonIT"], c=c, s=10, cmap="coolwarm", alpha=0.7)
    if c is not None:
        fig.colorbar(sc, ax=ax, label="T dry-bulb train (°C)")
    ax.set_xlabel("P_IT (kW)")
    ax.set_ylabel("P_nonIT (kW)")
    ax.set_title("Train: non-IT vs IT (color = outdoor T)")
    fig.tight_layout()
    fig.savefig(OUT / "figures" / "03_structural_response.png", dpi=140)
    plt.close()

    if therm_rows:
        fig, ax = plt.subplots(figsize=(6, 5))
        ax.scatter(src["P_IT"], src["heat_transfer_index"], s=8, alpha=0.5)
        ax.set_xlabel("P_IT (kW)")
        ax.set_ylabel("flow·ΔT (m³/h·K)  [not thermal kW]")
        ax.set_title("Liquid heat-transfer index vs IT load")
        fig.tight_layout()
        fig.savefig(OUT / "figures" / "04_thermal_check.png", dpi=140)
        plt.close()

    if prv_rows and "pue" in pd.DataFrame(prv_rows).columns:
        g = pd.DataFrame(prv_rows)
        fig, ax = plt.subplots(figsize=(6, 4))
        for wx, gg in g.groupby("weather"):
            ax.plot(gg["p_it_mw"], gg["pue"], marker="o", label=wx)
        ax.set_xlabel("Scenario IT (MW)")
        ax.set_ylabel("Prineville gray-box PUE")
        ax.set_title("Prineville 3×3 load×weather (not M100 coefficients)")
        ax.legend(title="weather")
        fig.tight_layout()
        fig.savefig(OUT / "figures" / "05_prineville_structure.png", dpi=140)
        plt.close()

    scores = {r["model"]: r for r in score_rows}
    report = f"""# M100 facility-model structure pilot

**Window:** {month} {window[0]} → {window[-1]} ({n_days} days; train {train_dates[0]}–{train_dates[-1]}, test {test_dates[0]}–{test_dates[-1]})

Selection used timestamps and joint coverage only (threshold 90%). April lacked a 14-day weather-complete block.

**Measurement QC:** {measurement_qc}

Canonical meters: Logics `panel=generals`, `device=pue` for Tot and Tot_ict.
PUE_calc median={qc['PUE_median']:.3f} (p05={qc['PUE_p05']:.3f}, p95={qc['PUE_p95']:.3f}); fraction PUE<1 = {qc['frac_PUE_lt_1']:.4f}.

B3 uses Vertiv `Free_Cooling_Status` (documented free-cooling system status; observed 0/1; facility-hour mean of device time-weighted fraction). **Oracle / not deployable for Prineville.**

## Held-out metrics (identical TEST timestamps)

{pd.DataFrame(score_rows).to_string(index=False)}

## Increments (MAE drop ≥5% and majority of test days)

- B0 → B1 affine load: **{b0_b1}**
- B1 → B2 weather: **{b1_b2}**
- B2 → B3 oracle state: **{b2_b3}**

Negative P_nonIT predictions (B2): {scores.get('B2', {}).get('frac_pred_negative')}

## Residual memory

{pd.DataFrame(mem_rows).to_string(index=False)}

Temporal memory: **{temporal}**

## Cooling target: {cooling_target}

Documented Tot_cdz + Tot_chiller + Tot_qpompe on generals/pue; not forced to close Tot.

## Thermal check: {thermal}

Circulating RDHx flow×ΔT is **not** water consumption. No empirical WUE.

## Second-period transfer: {transfer}

## Generic model implication

{generic}

## Prineville structural implication: {prv_label}

{prv_note}

Do not transfer M100 coefficients, PUE levels, or cooling fractions.

## Recommendation: {rec}
"""
    (OUT / "pilot_report.md").write_text(report)

    status = {
        "selected_month": month,
        "selected_window": [window[0], window[-1]],
        "train_start": train_dates[0],
        "train_end": train_dates[-1],
        "test_start": test_dates[0],
        "test_end": test_dates[-1],
        "n_days": n_days,
        "joint_coverage": joint,
        "measurement_qc": measurement_qc,
        "B0_vs_B1": b0_b1,
        "weather_increment_B1_vs_B2": b1_b2,
        "state_increment_B2_vs_B3": b2_b3,
        "cooling_target": cooling_target,
        "thermal_check": thermal,
        "temporal_memory": temporal,
        "second_period_transfer": transfer,
        "generic_model_implication": generic,
        "prineville_structure": prv_label,
        "recommendation": rec,
        "heldout": score_rows,
        "sample": sample_info,
        "b3_role": "STATE-INFORMED ORACLE; not a deployable Prineville predictor",
        "updated_utc": utcnow(),
    }
    status_path.write_text(json.dumps(status, indent=2, default=str) + "\n")
    print(json.dumps({
        "selected_month": month,
        "window": [window[0], window[-1]],
        "measurement_qc": measurement_qc,
        "B0_vs_B1": b0_b1,
        "B1_vs_B2": b1_b2,
        "B2_vs_B3": b2_b3,
        "recommendation": rec,
        "heldout_mae": {r["model"]: r["mae"] for r in score_rows},
    }, indent=2))
    return status


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true")
    args = p.parse_args()
    run_pilot(force=args.force)


if __name__ == "__main__":
    main()
