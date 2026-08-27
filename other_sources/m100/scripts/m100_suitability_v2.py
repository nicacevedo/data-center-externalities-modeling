#!/usr/bin/env python3
"""M100 2021 v2 facility-model assessment library.

Frozen pilot scientific definitions. Writes nowhere unless asked.
Does not reprocess raw archives or overwrite original result directories.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from m100_2021_common import (
    CATALOG_DIR,
    EXPECTED_MONTHS,
    PREFERRED_LOGICS,
    ROOT,
    SCHEMA_VERSION,
    STATUS_DIR,
    WATER_NAME_RE,
    ZENODO,
    archive_path,
    grain_parquet,
    load_status,
    month_calendar,
)
from qualify_m100_2021 import qualify

OUT_DIR = ROOT / "results" / "suitability_2021_v2"
ORIGINAL_SUITABILITY = ROOT / "results" / "suitability_2021"
ORIGINAL_PILOT = ROOT / "results" / "pilot_facility_2021"

CANON_PANEL, CANON_DEVICE = PREFERRED_LOGICS["Tot"]
STATE_CONCEPT = "Free_Cooling_Status"
STATE_ROLE = "STATE-INFORMED ORACLE"
B3_FORBIDDEN = (
    "heat_transfer_index", "liquid_flow", "liquid_flow_m3h", "flow_delta_t_mean",
    "Portata_attiva", "Portata_attiva_mean", "temp_sq",
)
FORMULAS = {
    "B0": "P_nonIT = c * P_IT   (OLS, no intercept)",
    "B1": "P_nonIT = a + b * P_IT",
    "B2_twb": "P_nonIT = a + b*P_IT + c*T_wb + d*P_IT*T_wb",
    "B2_fallback": "P_nonIT = a + b*P_IT + c*T_drybulb + d*RH",
    "B3": "B2 terms + e * Free_Cooling_Status   [STATE-INFORMED ORACLE]",
}
ORIGINAL_DAG_SCRIPTS = (
    "analyze_m100_suitability.py",
    "qc_m100_month.py",
    "qualify_m100_2021.py",
    "process_m100_month.py",
    "cleanup_m100_month.py",
    "catalog_m100_2021.py",
    "m100_2021_common.py",
    "run_m100_facility_pilot.py",
    "submit_m100_2021_pipeline.sh",
    "run_m100_final.sbatch",
)


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def git_provenance() -> dict:
    def _run(args):
        try:
            return subprocess.check_output(args, cwd=ROOT.parents[1], text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            try:
                return subprocess.check_output(args, cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
            except Exception as exc:
                return f"unavailable: {exc}"

    repo = ROOT.parents[1]
    head = _run(["git", "-C", str(repo), "rev-parse", "HEAD"])
    status = _run(["git", "-C", str(repo), "status", "--short", "--", "other_sources/m100"])
    return {
        "git_head": head,
        "git_status_m100": status or "clean",
        "limitation": (
            "Original monthly DAG jobs ran from git HEAD 01374109c4f1b456fc4e1a74c3b0906e82547f65 "
            "(working tree clean at assessment start). "
            "analyze_m100_suitability.py at that commit contains an IndentationError; "
            "final job 21334082 failed in 5s after qualify. "
            "The preserved suitability_2021 tables/figures dated 2026-08-26 15:03 are an "
            "earlier Apr–Jun exploratory run, not a completed full-year DAG analysis. "
            "month_qualification.csv was overwritten by job 21334082's qualify step."
        ),
    }


def ols_fit(y, X, intercept=True):
    X = np.asarray(X, float)
    if X.ndim == 1:
        X = X.reshape(-1, 1)
    y = np.asarray(y, float)
    Xd = np.column_stack([np.ones(len(X)), X]) if intercept else X
    beta, *_ = np.linalg.lstsq(Xd, y, rcond=None)
    return np.asarray(beta, float)


def ols_pred(beta, X, intercept=True):
    X = np.asarray(X, float)
    if X.ndim == 1:
        X = X.reshape(-1, 1)
    Xd = np.column_stack([np.ones(len(X)), X]) if intercept else X
    return Xd @ np.asarray(beta, float)


def b2_feature_names(weather: str) -> tuple[str, ...]:
    if weather == "twb":
        return ("P_IT", "T_wetbulb", "P_IT:T_wetbulb")
    if weather == "tdb_rh":
        return ("P_IT", "T_drybulb", "RH")
    raise ValueError(weather)


def b3_feature_names(weather: str) -> tuple[str, ...]:
    return b2_feature_names(weather) + ("cooling_state",)


def design_matrix(df: pd.DataFrame, model: str, weather: str) -> tuple[np.ndarray, bool, tuple[str, ...]]:
    """Return (X, intercept, names). Model in {B0,B1,B2,B3}."""
    pit = df["P_IT"].to_numpy(float)
    if model == "B0":
        return pit.reshape(-1, 1), False, ("P_IT",)
    if model == "B1":
        return pit.reshape(-1, 1), True, ("P_IT",)
    if model == "B2":
        names = b2_feature_names(weather)
        X = _weather_X(df, weather, pit)
        return X, True, names
    if model == "B3":
        names = b3_feature_names(weather)
        X = np.column_stack([_weather_X(df, weather, pit), df["cooling_state"].to_numpy(float)])
        return X, True, names
    raise ValueError(model)


def _weather_X(df, weather, pit):
    if weather == "twb":
        twb = df["T_wetbulb"].to_numpy(float)
        return np.column_stack([pit, twb, pit * twb])
    rh = df["RH"].to_numpy(float)
    tdb = df["T_drybulb"].to_numpy(float)
    return np.column_stack([pit, tdb, rh])


def metrics(y, p, pit=None, p_fac=None) -> dict:
    y = np.asarray(y, float)
    p = np.asarray(p, float)
    err = p - y
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err ** 2)))
    ymean = float(np.mean(y))
    sst = float(np.sum((y - ymean) ** 2))
    out = {
        "n": int(len(y)),
        "mae": mae,
        "rmse": rmse,
        "nrmse": rmse / ymean if ymean else np.nan,
        "bias": float(np.mean(err)),
        "r2": float(1.0 - np.sum(err ** 2) / sst) if sst else np.nan,
        "obs_energy_kwh": float(np.sum(y)),
        "pred_energy_kwh": float(np.sum(p)),
        "energy_error_pct": float(100.0 * np.sum(err) / np.sum(y)) if np.sum(y) else np.nan,
        "frac_pred_negative": float(np.mean(p < 0)),
    }
    if pit is not None and p_fac is not None:
        pit = np.asarray(pit, float)
        p_fac = np.asarray(p_fac, float)
        pue_obs = p_fac / np.where(pit > 0, pit, np.nan)
        pue_hat = (pit + p) / np.where(pit > 0, pit, np.nan)
        ok = np.isfinite(pue_obs) & np.isfinite(pue_hat)
        out["pue_mae"] = float(np.mean(np.abs(pue_hat[ok] - pue_obs[ok]))) if ok.any() else np.nan
        out["pue_bias"] = float(np.mean(pue_hat[ok] - pue_obs[ok])) if ok.any() else np.nan
        out["n_pue"] = int(ok.sum())
        out["n_pit_le_0"] = int((pit <= 0).sum())
    return out


def rel_mae_improvement(mae_simple, mae_rich) -> float:
    if mae_simple is None or not np.isfinite(mae_simple) or mae_simple == 0:
        return np.nan
    return float((mae_simple - mae_rich) / mae_simple)


def acf_lag(series: pd.Series, hours: int) -> float:
    s = series.dropna().sort_index()
    if s.empty:
        return np.nan
    aligned = pd.concat(
        [s.rename("a"), s.shift(freq=pd.Timedelta(hours=hours)).rename("b")],
        axis=1,
    ).dropna()
    if len(aligned) < 8:
        return np.nan
    return float(aligned["a"].corr(aligned["b"]))


def _parquet_ok(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    try:
        n = pq.ParquetFile(path).metadata.num_rows
        if n <= 0:
            return False, "empty"
        return True, f"rows={n}"
    except Exception as exc:
        return False, str(exc)


def source_disposition(month: str, st: dict) -> str:
    cleanup = str(st.get("cleanup") or "")
    arch = str(st.get("archive_status") or "")
    if cleanup == "tar_deleted" or arch in {"deleted_after_cert", "deleted_after_certification"}:
        return "deleted_after_certification"
    tar = archive_path(month)
    official = int(ZENODO[month]["size"])
    if tar.exists() and tar.stat().st_size == official:
        return "present_verified"
    if tar.exists():
        return "present_size_mismatch"
    return "missing_unverified"


def required_grains_from_qual_row(row: dict) -> list[str]:
    need = []
    if row.get("facility_total_power") or row.get("facility_it_power"):
        need.append("facility")
    if row.get("liquid_flow_temp"):
        need.append("liquid_cooling")
    if row.get("air_cooling"):
        need.append("crac")
    if row.get("weather"):
        need.append("weather")
    if row.get("run_node_aggregation"):
        need.append("node")
    return need


def list_actual_products(month: str) -> list[str]:
    out = []
    for grain in ("facility", "weather", "crac", "liquid_cooling", "node"):
        p = grain_parquet(grain, month)
        ok, _ = _parquet_ok(p)
        if ok:
            out.append(str(p))
    return out


def repair_month_certification(month: str, qual_row: dict | None, st: dict | None = None) -> dict:
    """Recompute certification from current inventory/qualification/products. No deletion."""
    st = st if st is not None else load_status(month)
    disp = source_disposition(month, st)
    products = list_actual_products(month)
    product_grains = {Path(p).parent.parent.name for p in products}
    required = required_grains_from_qual_row(qual_row or {})
    grain_status = {}
    failed = []
    for g in required:
        ok, detail = _parquet_ok(grain_parquet(g, month))
        grain_status[g] = {"ok": ok, "detail": detail}
        if not ok:
            failed.append(g)
    if required and not failed and disp in {"present_verified", "deleted_after_certification"}:
        cert = "PASS"
    elif required and failed and any(grain_status[g]["ok"] for g in required):
        cert = "PASS_PARTIAL"
    elif required and failed:
        cert = "FAIL"
    else:
        cert = "PASS_PARTIAL"
    would_allow = (
        cert == "PASS"
        and disp in {"present_verified", "deleted_after_certification"}
        and not failed
    )
    classes = (qual_row or {}).get("classes") or "none"
    full_fac = "full-facility-qualified" in str(classes)
    return {
        "month": month,
        "certification_v2": cert,
        "certification_original": st.get("certification"),
        "source_disposition": disp,
        "raw_deletion_would_be_allowed": would_allow,
        "raw_deletion_performed_this_task": False,
        "required_grains": "|".join(required) if required else "",
        "failed_required_grains": "|".join(failed) if failed else "",
        "processed_products": "|".join(products),
        "n_processed_products": len(products),
        "product_grains": "|".join(sorted(product_grains)),
        "qualification_classes": classes,
        "full_facility_qualified": full_fac,
        "schema_version": st.get("schema_version") or SCHEMA_VERSION,
        "original_processed_products_n": len(st.get("processed_products") or []),
        "original_archive_status": st.get("archive_status"),
        "original_cleanup": st.get("cleanup"),
    }


def load_metric_inventory() -> pd.DataFrame:
    p = CATALOG_DIR / "m100_2021_metric_inventory.csv"
    if p.exists():
        inv = pd.read_csv(p)
        if "month" in inv.columns:
            return inv
    rows = []
    inv_dir = CATALOG_DIR / "inventory"
    if inv_dir.exists():
        for f in sorted(inv_dir.glob("2021-*.csv")):
            d = pd.read_csv(f)
            d["month"] = f.stem
            rows.append(d)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def canon_facility(month: str) -> pd.DataFrame:
    p = grain_parquet("facility", month)
    if not p.exists():
        return pd.DataFrame()
    fac = pd.read_parquet(p)
    fac["hour_utc"] = pd.to_datetime(fac["timestamp_utc"], utc=True)
    g = fac.loc[
        (fac["panel"].astype(str) == CANON_PANEL) & (fac["device"].astype(str) == CANON_DEVICE)
    ].copy()
    if g.empty:
        return g
    g = g.drop_duplicates("hour_utc").set_index("hour_utc").sort_index()
    g = g.reindex(month_calendar(month))
    g.index.name = "hour_utc"
    return g


def load_month_hourly(month: str) -> pd.DataFrame:
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
    cool = [c for c in ("Tot_cdz_mean", "Tot_chiller_mean", "Tot_qpompe_mean") if c in fac.columns]
    if len(cool) == 3:
        df["P_cooling"] = fac[cool].sum(axis=1).to_numpy()
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
        df = df.reset_index()
    cp = grain_parquet("crac", month)
    if cp.exists():
        c = pd.read_parquet(cp)
        c["hour_utc"] = pd.to_datetime(c["timestamp_utc"], utc=True)
        use = None
        if "Free_Cooling_Status_fraction_time_active" in c.columns:
            use = "Free_Cooling_Status_fraction_time_active"
        elif "Free_Cooling_Status_mean" in c.columns:
            use = "Free_Cooling_Status_mean"
        if use:
            fc = c.groupby("hour_utc")[use].mean()
            df = df.set_index("hour_utc")
            df["cooling_state"] = fc
            df = df.reset_index()
    lp = grain_parquet("liquid_cooling", month)
    if lp.exists():
        l = pd.read_parquet(lp)
        l["hour_utc"] = pd.to_datetime(l["timestamp_utc"], utc=True)
        if "flow_delta_t_mean" in l.columns:
            hti = l.groupby("hour_utc")["flow_delta_t_mean"].median()
            df = df.set_index("hour_utc")
            df["heat_transfer_index"] = hti
            df = df.reset_index()
        if "panel" in l.columns:
            df.attrs["liquid_panels"] = sorted(l["panel"].astype(str).dropna().unique().tolist())
    df["month"] = month
    return df


def choose_weather_formulation(train: pd.DataFrame, test: pd.DataFrame,
                               min_train: int = 50, min_test: int = 20) -> str:
    """Availability only — not model score. Uses valid-hour counts, not calendar fraction."""
    def n_ok(df, cols):
        if not set(cols).issubset(df.columns):
            return 0
        return int(df[cols].notna().all(axis=1).sum())

    if n_ok(train, ["P_IT", "P_nonIT", "T_wetbulb"]) >= min_train and \
       n_ok(test, ["P_IT", "P_nonIT", "T_wetbulb"]) >= min_test:
        return "twb"
    if n_ok(train, ["P_IT", "P_nonIT", "T_drybulb", "RH"]) >= min_train and \
       n_ok(test, ["P_IT", "P_nonIT", "T_drybulb", "RH"]) >= min_test:
        return "tdb_rh"
    return "unsupported"


def base_mask(df: pd.DataFrame, weather: str) -> pd.Series:
    cols = ["P_IT", "P_nonIT", "P_facility"]
    if weather == "twb":
        cols.append("T_wetbulb")
    elif weather == "tdb_rh":
        cols.extend(["T_drybulb", "RH"])
    m = df[cols].notna().all(axis=1) & (df["P_IT"] > 0)
    return m


def state_mask(df: pd.DataFrame, weather: str) -> pd.Series:
    return base_mask(df, weather) & df["cooling_state"].notna() if "cooling_state" in df.columns \
        else pd.Series(False, index=df.index)


def expanding_folds(months: list[str]) -> list[dict]:
    """earlier months → next month. No future in training."""
    folds = []
    for i in range(1, len(months)):
        train = months[:i]
        test = months[i]
        assert test not in train
        assert all(t < test for t in train)
        folds.append({"train_months": train, "test_month": test, "fold_id": f"{train[0]}_to_{test}"})
    return folds


def fit_models(train: pd.DataFrame, test: pd.DataFrame, weather: str, models: list[str]):
    ytr = train["P_nonIT"].to_numpy(float)
    yte = test["P_nonIT"].to_numpy(float)
    pit_te = test["P_IT"].to_numpy(float)
    fac_te = test["P_facility"].to_numpy(float)
    rows, coef_rows, pred = [], [], {}
    for model in models:
        Xtr, intercept, names = design_matrix(train, model, weather)
        Xte, _, _ = design_matrix(test, model, weather)
        beta = ols_fit(ytr, Xtr, intercept=intercept)
        phat = ols_pred(beta, Xte, intercept=intercept)
        pred[model] = phat
        sc = metrics(yte, phat, pit=pit_te, p_fac=fac_te)
        sc.update({"model": model, "weather": weather, "role": STATE_ROLE if model == "B3" else "nested_ols"})
        rows.append(sc)
        terms = (["intercept"] if intercept else []) + list(names)
        for name, val in zip(terms, beta.ravel()):
            coef_rows.append({"model": model, "term": name, "value": float(val), "weather": weather})
    return rows, coef_rows, pred


def marginal_effects_b2(beta, weather: str, train: pd.DataFrame) -> list[dict]:
    """Interpret B2 without changing the fitted model. beta includes intercept."""
    rows = []
    if weather != "twb" or len(beta) < 4:
        # fallback: d(nonIT)/d(IT) = b; d(nonIT)/dT = c; d(nonIT)/dRH = d
        b = float(beta[1]) if len(beta) > 1 else np.nan
        rows.append({"kind": "dP_nonIT/dP_IT", "at": "constant", "support": "tdb_rh", "value": b})
        if len(beta) > 2:
            rows.append({"kind": "dP_nonIT/dT_drybulb", "at": "constant", "support": "tdb_rh", "value": float(beta[2])})
        if len(beta) > 3:
            rows.append({"kind": "dP_nonIT/dRH", "at": "constant", "support": "tdb_rh", "value": float(beta[3])})
        return rows
    b, c, d = float(beta[1]), float(beta[2]), float(beta[3])
    twb = train["T_wetbulb"].dropna()
    pit = train["P_IT"].dropna()
    for q in (0.1, 0.5, 0.9):
        t = float(twb.quantile(q))
        rows.append({
            "kind": "dP_nonIT/dP_IT", "at": f"T_wb_p{int(q*100)}",
            "support_value": t, "value": b + d * t, "units": "kW/kW",
        })
    for q in (0.1, 0.5, 0.9):
        p = float(pit.quantile(q))
        rows.append({
            "kind": "dP_nonIT/dT_wb", "at": f"P_IT_p{int(q*100)}",
            "support_value": p, "value": c + d * p, "units": "kW/K",
        })
    return rows


def transfer_semantics(ranking_train: list[str], ranking_test: list[str],
                       mae_ref: float, mae_out: float) -> dict:
    """Split ranking transfer from absolute numerical transfer. Never a single CONSISTENT label."""
    same_rank = list(ranking_train) == list(ranking_test)
    return {
        "structural_ranking_transfer": "YES" if same_rank else "NO",
        "ranking_train": "|".join(ranking_train),
        "ranking_heldout": "|".join(ranking_test),
        "mae_reference": mae_ref,
        "mae_heldout": mae_out,
        "absolute_mae_ratio": (mae_out / mae_ref) if mae_ref and np.isfinite(mae_ref) else np.nan,
        "absolute_numerical_transfer": "see_mae_nrmse_bias_r2_energy_error",
        "forbidden_overall_label": None,
    }


def water_audit(inv: pd.DataFrame) -> pd.DataFrame:
    if inv.empty or "metric" not in inv.columns:
        return pd.DataFrame([{
            "n_name_hits": 0, "example_metrics": "",
            "consumptive_meter_verified": False,
            "empirical_WUE": "UNSUPPORTED",
            "note": "no inventory; circulating Schneider flow is not withdrawal",
        }])
    names = inv["metric"].astype(str)
    hits = names[names.str.contains(WATER_NAME_RE)]
    # circulating loop names are not consumptive
    circulating = hits.str.contains(r"Portata|flow|portata", case=False, regex=True)
    consumptive_like = hits[~circulating]
    verified = False  # no independently documented makeup meter in this corpus
    return pd.DataFrame([{
        "n_name_hits": int(len(hits)),
        "n_circulating_like": int(circulating.sum()),
        "n_consumptive_like_names": int(len(consumptive_like)),
        "example_metrics": "|".join(sorted(hits.unique())[:12]),
        "consumptive_meter_verified": verified,
        "empirical_WUE": "UNSUPPORTED",
        "water_withdrawal": "UNSUPPORTED",
        "water_consumption": "UNSUPPORTED",
        "note": "Closed-loop Portata_attiva is circulating RDHx flow, not makeup/withdrawal.",
    }])


def label_from_fold_improvements(improvements: list[float], n_folds: int) -> str:
    xs = [x for x in improvements if np.isfinite(x)]
    if n_folds <= 0 or not xs:
        return "UNSUPPORTED BY AVAILABLE DATA"
    n_ge5 = sum(x >= 0.05 for x in xs)
    n_pos = sum(x > 0 for x in xs)
    if n_ge5 == n_folds and n_pos == n_folds:
        return "STRONG SUPPORT"
    if n_ge5 == 0 and n_pos == 0:
        return "NOT SUPPORTED"
    if 0 < n_ge5 < n_folds or (n_pos > 0 and n_ge5 < n_folds):
        return "MIXED / REGIME-DEPENDENT"
    if n_ge5 == n_folds:
        return "STRONG SUPPORT"
    return "UNRESOLVED"


def classify_benchmark(evidence: dict) -> tuple[str, str]:
    """A/B/C from evidence labels only. Not 'B if months else C'."""
    meas = evidence.get("measurement_boundary_confidence", "UNRESOLVED")
    weather = evidence.get("weather_increment", "UNRESOLVED")
    affine = evidence.get("constant_PUE_vs_affine", "UNRESOLVED")
    state = evidence.get("state_increment", "UNRESOLVED")
    n_folds = int(evidence.get("n_chronological_folds") or 0)
    abs_xfer = evidence.get("absolute_transfer", "UNRESOLVED")
    if meas in {"UNSUPPORTED BY AVAILABLE DATA", "NOT SUPPORTED"} or n_folds < 2:
        return "C", (
            "Measurement boundaries or chronological coverage are inadequate "
            f"(measurement={meas}, n_folds={n_folds})."
        )
    strong_struct = weather == "STRONG SUPPORT" or affine == "STRONG SUPPORT"
    restrictions = []
    if abs_xfer in {"NOT SUPPORTED", "MIXED / REGIME-DEPENDENT"}:
        restrictions.append(f"absolute numerical transfer is {abs_xfer}")
    if state in {"NOT SUPPORTED", "MIXED / REGIME-DEPENDENT"}:
        restrictions.append(f"the Free_Cooling_Status oracle increment is {state}")
    if meas == "STRONG SUPPORT" and strong_struct and n_folds >= 6 and weather != "NOT SUPPORTED":
        # A requires strong measurement plus stable cross-season structure without
        # mixed absolute transfer or state ambiguity that restrict generic conclusions.
        if not restrictions:
            return "A", (
                "Measurement boundaries and cross-season chronological evidence are strong enough "
                "to identify/falsify important structural dependencies. Numerical M100 parameters "
                "remain non-generic."
            )
        return "B", (
            "Useful structural/physics benchmark: expanding month-forward folds identify weather "
            "dependence in P_nonIT and can falsify a weather-independent load-only map. "
            + "; ".join(restrictions).capitalize()
            + ", which restricts the strength of generic conclusions. "
            "M100 coefficients, PUE levels, and control thresholds are not generic."
        )
    if n_folds >= 2 and meas in {"STRONG SUPPORT", "MIXED / REGIME-DEPENDENT"}:
        return "B", (
            f"Useful structural/physics benchmark (measurement={meas}, weather={weather}, "
            f"affine={affine}, n_folds={n_folds}), but regime dependence, state ambiguity, "
            "or poor numerical transfer restrict generic conclusions."
        )
    return "C", (
        f"Coverage or measurement confidence is too weak for reliable facility-response "
        f"identification (measurement={meas}, n_folds={n_folds})."
    )


def build_evidence(
    cert: pd.DataFrame,
    folds: pd.DataFrame,
    incremental: pd.DataFrame,
    memory: pd.DataFrame,
    thermal: pd.DataFrame,
    cooling: pd.DataFrame,
    water: pd.DataFrame,
    transfer: pd.DataFrame,
    boundary: pd.DataFrame,
) -> dict:
    n_folds = int(folds["test_month"].nunique()) if len(folds) else 0
    def _inc(name):
        sub = incremental.loc[incremental["increment"].eq(name)] if len(incremental) else pd.DataFrame()
        return sub["mae_rel_improvement"].tolist() if len(sub) else []

    b0b1 = _inc("B0_to_B1")
    b1b2 = _inc("B1_to_B2")
    b2b3 = _inc("B2_to_B3_state_sample")

    # measurement: canonical meters + small closure residual
    meas = "UNRESOLVED"
    if len(boundary):
        frac_bad = float(boundary.get("frac_facility_lt_IT", pd.Series([np.nan])).median())
        pue_lt1 = float(boundary.get("frac_PUE_lt_1", pd.Series([np.nan])).median()) if "frac_PUE_lt_1" in boundary else np.nan
        clos = float(boundary.get("closure_rel_median_pct", pd.Series([np.nan])).median()) if "closure_rel_median_pct" in boundary else np.nan
        n_full = int(cert["full_facility_qualified"].sum()) if len(cert) and "full_facility_qualified" in cert else 0
        if n_full >= 6 and (not np.isfinite(frac_bad) or frac_bad < 0.01) and (not np.isfinite(pue_lt1) or pue_lt1 < 0.01):
            meas = "STRONG SUPPORT"
        elif n_full >= 3:
            meas = "MIXED / REGIME-DEPENDENT"
        elif n_full == 0:
            meas = "UNSUPPORTED BY AVAILABLE DATA"

    mem_label = "UNRESOLVED"
    if len(memory) and "acf_1h" in memory:
        ac = memory.loc[memory["model"].isin(["B1", "B2"]), "acf_1h"]
        if ac.notna().any():
            med = float(ac.median())
            mem_label = "STRONG SUPPORT" if med >= 0.3 else "NOT SUPPORTED"
            # STRONG SUPPORT here means strong evidence OF residual memory
            if med >= 0.3:
                mem_label = "STRONG SUPPORT"
            elif med >= 0.15:
                mem_label = "MIXED / REGIME-DEPENDENT"
            else:
                mem_label = "NOT SUPPORTED"

    therm_label = "UNSUPPORTED BY AVAILABLE DATA"
    if len(thermal) and "pearson" in thermal:
        r = float(pd.to_numeric(thermal["pearson"], errors="coerce").median())
        if np.isfinite(r) and abs(r) >= 0.2:
            therm_label = "STRONG SUPPORT"  # sanity, not kW closure
        elif np.isfinite(r):
            therm_label = "MIXED / REGIME-DEPENDENT"

    cool_label = "UNSUPPORTED BY AVAILABLE DATA"
    if len(cooling) and "frac_nonIT_energy_from_cooling" in cooling:
        fr = float(pd.to_numeric(cooling["frac_nonIT_energy_from_cooling"], errors="coerce").median())
        if np.isfinite(fr) and fr >= 0.8:
            cool_label = "STRONG SUPPORT"
        elif np.isfinite(fr):
            cool_label = "MIXED / REGIME-DEPENDENT"

    water_label = "UNSUPPORTED BY AVAILABLE DATA"
    if len(water) and str(water.iloc[0].get("empirical_WUE", "UNSUPPORTED")) == "UNSUPPORTED":
        water_label = "UNSUPPORTED BY AVAILABLE DATA"

    abs_label = "UNRESOLVED"
    if len(transfer) and "nrmse" in transfer:
        nr = pd.to_numeric(transfer["nrmse"], errors="coerce")
        if nr.notna().any():
            med = float(nr.median())
            # no post-hoc pass threshold: describe magnitude
            if med >= 0.25:
                abs_label = "NOT SUPPORTED"
            elif med >= 0.10:
                abs_label = "MIXED / REGIME-DEPENDENT"
            else:
                abs_label = "STRONG SUPPORT"

    struct_label = label_from_fold_improvements(b1b2, n_folds)

    return {
        "n_chronological_folds": n_folds,
        "measurement_boundary_confidence": meas,
        "constant_PUE_vs_affine": label_from_fold_improvements(b0b1, n_folds),
        "weather_increment": label_from_fold_improvements(b1b2, n_folds),
        "state_increment": label_from_fold_improvements(b2b3, len(b2b3)),
        "temporal_memory": mem_label,
        "cooling_target_support": cool_label,
        "thermal_measurement_sanity": therm_label,
        "thermal_load_closure": "UNSUPPORTED BY AVAILABLE DATA",
        "absolute_transfer": abs_label,
        "structural_transfer": struct_label,
        "water_support": water_label,
        "n_folds_weather_ge5pct": int(sum(x >= 0.05 for x in b1b2 if np.isfinite(x))),
        "n_folds_state_ge5pct": int(sum(x >= 0.05 for x in b2b3 if np.isfinite(x))),
        "n_folds_affine_ge5pct": int(sum(x >= 0.05 for x in b0b1 if np.isfinite(x))),
        "frac_folds_weather_ge5pct": (sum(x >= 0.05 for x in b1b2 if np.isfinite(x)) / n_folds) if n_folds else np.nan,
        "frac_folds_state_ge5pct": (sum(x >= 0.05 for x in b2b3 if np.isfinite(x)) / len(b2b3)) if b2b3 else np.nan,
    }
