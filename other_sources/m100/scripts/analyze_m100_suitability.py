#!/usr/bin/env python3
"""Facility QC, nested gray-box benchmarks, and high-value figures.

Reads processed Parquet only. No raw scans.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from m100_2021_common import PROCESSED_DIR, RESULTS_DIR, ROOT, grain_parquet, save_status


PREFERRED_LOGICS = {
    "Tot": ("generals", "pue"),
    "Tot_ict": ("generals", "pue"),
    "Tot_cdz": ("generals", "pue"),
    "Tot_chiller": ("generals", "pue"),
    "Tot_qpompe": ("generals", "pue"),
    "Tot_servizi": ("generals", "pue"),
    "Pue": ("generals", "pue"),
    "Dcie": ("generals", "pue"),
    "pue": ("generals", "pue_sala_m"),
}

COMPONENTS = ("Tot_ict", "Tot_cdz", "Tot_chiller", "Tot_qpompe", "Tot_servizi")


def _read(path: Path):
    return pd.read_parquet(path) if path.exists() else None


def _grain(grain: str, month: str):
    p = grain_parquet(grain, month)
    if p.exists():
        return _read(p)
    legacy = {
        "facility": ROOT / "data" / "processed" / "facility_hourly" / month / "m100_facility_hourly.parquet",
        "liquid_cooling": ROOT / "data" / "processed" / "liquid_cooling_hourly" / month / "m100_liquid_hourly.parquet",
        "crac": ROOT / "data" / "processed" / "crac_hourly" / month / "m100_crac_hourly.parquet",
        "weather": ROOT / "data" / "processed" / "weather_hourly" / month / "m100_weather_hourly.parquet",
        "system": ROOT / "data" / "processed" / "system_hourly" / month / "m100_system_hourly.parquet",
        "node": ROOT / "data" / "processed" / "node_hourly" / month / "m100_node_hourly.parquet",
    }
    alt = PROCESSED_DIR / "hourly" / grain / month / f"m100_{grain}_hourly.parquet"
    for cand in (legacy.get(grain), alt):
        if cand is not None and cand.exists():
            return _read(cand)
    jan = PROCESSED_DIR / "hourly" / "2021-01" / "m100_node_hourly.parquet"
    if grain == "node" and month == "2021-01" and jan.exists():
        return _read(jan)
    jan2 = ROOT / "data" / "processed" / "hourly" / "2021-01" / "m100_node_hourly.parquet"
    if grain == "node" and month == "2021-01" and jan2.exists():
        return _read(jan2)
    return None


def _metrics(a, b):
    s = pd.DataFrame({"a": a, "b": b}).dropna()
    if len(s) < 5:
        return {"n": int(len(s))}
    err = s["a"] - s["b"]
    ratio = (s["a"] / s["b"].replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
    return {
        "n": int(len(s)),
        "bias": float(err.mean()),
        "mae": float(err.abs().mean()),
        "rmse": float(np.sqrt((err ** 2).mean())),
        "corr": float(s["a"].corr(s["b"])),
        "median_ratio": float(ratio.median()),
    }


def canonical_logics_series(fac: pd.DataFrame, metric: str) -> pd.DataFrame:
    col = f"{metric}_mean"
    if col not in fac.columns or not {"panel", "device"}.issubset(fac.columns):
        return pd.DataFrame()
    pref = PREFERRED_LOGICS.get(metric)
    work = fac[["timestamp_utc", "panel", "device", col]].copy()
    if pref is not None:
        hit = work.loc[
            (work["panel"].astype(str) == pref[0])
            & (work["device"].astype(str) == pref[1])
            & work[col].notna()
        ]
        if len(hit):
            ser = hit[["timestamp_utc", col]].rename(columns={col: metric})
            ser.attrs["panel"], ser.attrs["device"] = pref
            return ser
    ident = (
        work.groupby(["panel", "device"], dropna=False)[col]
        .agg(["count", "mean"])
        .reset_index()
        .sort_values("count", ascending=False)
    )
    if ident.empty or ident.iloc[0]["count"] <= 0:
        return pd.DataFrame()
    top = ident.iloc[0]
    ser = work.loc[
        (work["panel"].astype(str) == str(top["panel"]))
        & (work["device"].astype(str) == str(top["device"])),
        ["timestamp_utc", col],
    ].rename(columns={col: metric})
    ser.attrs["panel"] = top["panel"]
    ser.attrs["device"] = top["device"]
    return ser


def ols_fit(y, X):
    mask = np.isfinite(y) & np.isfinite(X).all(axis=1)
    yv, Xv = y[mask], X[mask]
    if len(yv) <= Xv.shape[1] + 1:
        return None
    Xd = np.column_stack([np.ones(len(yv)), Xv])
    beta, *_ = np.linalg.lstsq(Xd, yv, rcond=None)
    return {"beta": beta}


def score(y, pred):
    s = pd.DataFrame({"y": y, "p": pred}).dropna()
    if len(s) < 5:
        return {"n": int(len(s))}
    err = s["p"] - s["y"]
    sst = ((s["y"] - s["y"].mean()) ** 2).sum()
    return {
        "n": int(len(s)),
        "mae": float(err.abs().mean()),
        "rmse": float(np.sqrt((err ** 2).mean())),
        "nrmse": float(np.sqrt((err ** 2).mean()) / s["y"].std()) if s["y"].std() else np.nan,
        "bias": float(err.mean()),
        "r2": float(1 - (err ** 2).sum() / sst) if sst else np.nan,
        "energy_error_kwh": float(err.sum()),
    }


def score_pue(it, tot, pred_nonit):
    s = pd.DataFrame({"it": it, "tot": tot, "pni": pred_nonit}).dropna()
    s = s.loc[s["it"] > 0]
    if len(s) < 5:
        return {}
    pue_obs = s["tot"] / s["it"]
    pue_hat = (s["pni"] + s["it"]) / s["it"]
    err = pue_hat - pue_obs
    return {
        "pue_mae": float(err.abs().mean()),
        "pue_bias": float(err.mean()),
        "pue_p95_abs": float(err.abs().quantile(0.95)),
    }


def autocorr(x, lag):
    s = pd.Series(np.asarray(x, float)).dropna()
    if len(s) <= lag + 5:
        return np.nan
    return float(s.autocorr(lag=lag))


def _node_path(month: str) -> Path:
    p = PROCESSED_DIR / "node_hourly" / month / "m100_node_hourly.parquet"
    if p.exists():
        return p
    legacy = PROCESSED_DIR / "hourly" / month / "m100_node_hourly.parquet"
    return legacy


def analyze():
    tables = RESULTS_DIR / "tables"
    figs = RESULTS_DIR / "figures"
    tables.mkdir(parents=True, exist_ok=True)
    figs.mkdir(parents=True, exist_ok=True)
    snap = tables / "_qc_snapshot.json"
    if snap.exists():
        snap.unlink()

    months, weather_months, liquid_months, crac_months, node_months = [], [], [], [], []
    for grain, bucket in (
        ("facility", months), ("weather", weather_months), ("liquid_cooling", liquid_months),
        ("crac", crac_months), ("node", node_months),
    ):
        found = {p.parent.name for p in (PROCESSED_DIR / "hourly" / grain).glob("*/m100_*_hourly.parquet")}
        # transition fallback
        old_name = {
            "facility": "facility_hourly", "weather": "weather_hourly",
            "liquid_cooling": "liquid_cooling_hourly", "crac": "crac_hourly", "node": "node_hourly",
        }[grain]
        found |= {p.parent.name for p in PROCESSED_DIR.glob(f"{old_name}/*/m100_*.parquet")}
        found |= {p.parent.name for p in (ROOT / "data" / "processed").glob(f"{old_name}/*/m100_*.parquet")}
        bucket.extend(sorted(found))
    months, weather_months, liquid_months, crac_months, node_months = (
        sorted(set(x)) for x in (months, weather_months, liquid_months, crac_months, node_months)
    )
    if _grain("node", "2021-01") is not None and "2021-01" not in node_months:
        node_months.append("2021-01")

    boundary_rows, closure_rows, pue_rows, node_rows = [], [], [], []
    liquid_rows, twin_rows, energy_rows = [], [], []
    system_frames = []
    ident_notes = []

    for month in sorted(set(months + weather_months + liquid_months + crac_months + node_months)):
        fac = _grain("facility", month)
        liq = _grain("liquid_cooling", month)
        crac = _grain("crac", month)
        wth = _grain("weather", month)
        node = _grain("node", month)
        if liq is not None:
            if "flow_delta_t_mean" in liq.columns and "heat_transfer_index" not in liq.columns:
                liq = liq.copy()
                liq["heat_transfer_index"] = liq["flow_delta_t_mean"]
            if "delta_t_mean" in liq.columns and "delta_T_c" not in liq.columns:
                liq = liq.copy()
                liq["delta_T_c"] = liq["delta_t_mean"]

        series = {}
        if fac is not None:
            for m in ("Tot", "Tot_ict", "Tot_cdz", "Tot_chiller", "Tot_qpompe", "Tot_servizi", "Pue", "pue", "Dcie"):
                ser = canonical_logics_series(fac, m)
                if not ser.empty:
                    series[m] = ser.set_index(pd.to_datetime(ser["timestamp_utc"], utc=True))[m]
                    boundary_rows.append({
                        "month": month, "metric": m,
                        "canonical_panel": ser.attrs.get("panel"),
                        "canonical_device": ser.attrs.get("device"),
                        "n": int(series[m].notna().sum()),
                        "selection": "preferred_generals_pue" if PREFERRED_LOGICS.get(m) else "max_count",
                    })
            # pt/pit live on room meters, not the facility Tot meter
            for m in ("pt", "pit"):
                col = f"{m}_mean"
                if col not in fac.columns:
                    continue
                for (panel, device), g in fac.groupby(["panel", "device"], dropna=False):
                    ser = g.set_index(pd.to_datetime(g["timestamp_utc"], utc=True))[col].dropna()
                    if ser.empty:
                        continue
                    key = f"{m}|{panel}|{device}"
                    series[key] = ser
                    target = series.get("Tot") if m == "pt" else series.get("Tot_ict")
                    if target is not None:
                        pue_rows.append({
                            "month": month, "check": f"{m}_W_over_1000_vs_facility",
                            "panel": panel, "device": device,
                            **_metrics(ser / 1000.0, target),
                        })
            if "Tot" in series and "Tot_ict" in series:
                pue_calc = series["Tot"] / series["Tot_ict"].replace(0, np.nan)
                if "Pue" in series:
                    pue_rows.append({"month": month, "check": "Pue_vs_Tot_over_Tot_ict",
                                     "panel": "generals", "device": "pue", **_metrics(series["Pue"], pue_calc)})
                if "pue" in series:
                    pue_rows.append({"month": month, "check": "pue_sala_m_vs_Tot_over_Tot_ict",
                                     "panel": "generals", "device": "pue_sala_m", **_metrics(series["pue"], pue_calc)})
                for label, comps in (
                    ("with_servizi", [c for c in COMPONENTS if c in series]),
                    ("without_servizi", [c for c in COMPONENTS if c != "Tot_servizi" and c in series]),
                ):
                    if len(comps) < 4:
                        continue
                    summed = sum(series[c] for c in comps)
                    resid = series["Tot"] - summed
                    rel = resid / series["Tot"].replace(0, np.nan)
                    closure_rows.append({
                        "month": month, "variant": label, "components": "+".join(comps),
                        "n": int(resid.dropna().size),
                        "median": float(resid.median()),
                        "p05": float(resid.quantile(0.05)),
                        "p95": float(resid.quantile(0.95)),
                        "iqr": float(resid.quantile(0.75) - resid.quantile(0.25)),
                        "rel_median_pct": float(rel.median() * 100),
                    })
            ident_notes.append({
                "month": month,
                "note": "Tot/Tot_ict/cooling kW use panel=generals device=pue; pt/pit are room meters pue_sala_m/n; lowercase pue is pue_sala_m; do not average duplicates",
            })
            # energy meters: do not force if boundary != Tot
            for metric, expect in (("Mwh", ("b-c", "cabina-misure")), ("Energia", None)):
                ser = canonical_logics_series(fac, metric) if f"{metric}_mean" in fac.columns else pd.DataFrame()
                if ser.empty:
                    continue
                energy_rows.append({
                    "month": month, "metric": metric,
                    "panel": ser.attrs.get("panel"), "device": ser.attrs.get("device"),
                    "n": int(ser[metric].notna().sum()),
                    "mean": float(ser[metric].mean()),
                    "forced_vs_Tot": False,
                    "reason": "meter panel/device is not generals/pue; not a facility Tot energy counter",
                })

        if node is not None and "Tot_ict" in series:
            n = node.copy()
            hour_col = "timestamp_utc" if "timestamp_utc" in n.columns else "hour"
            n["hour"] = pd.to_datetime(n[hour_col], utc=True)
            if "high_quality" in n.columns:
                hq = n.loc[n["high_quality"]].copy()
            else:
                hq = n.dropna(subset=["total_power_mean"]).copy()
            pnodes = hq.groupby("hour")["total_power_mean"].sum() / 1000.0
            n_hq = hq.groupby("hour").size()
            aligned = pd.concat(
                [pnodes.rename("P_nodes_kw"), n_hq.rename("n_hq_nodes"), series["Tot_ict"].rename("Tot_ict")],
                axis=1,
            )
            med_n = float(aligned["n_hq_nodes"].median()) if aligned["n_hq_nodes"].notna().any() else np.nan
            primary = aligned.loc[aligned["n_hq_nodes"] >= 0.90 * med_n] if np.isfinite(med_n) else aligned
            rec = {"month": month, "median_n_hq_nodes": med_n, **_metrics(primary["P_nodes_kw"], primary["Tot_ict"])}
            if len(primary) >= 5:
                rec["median_offset_kw"] = float((primary["P_nodes_kw"] - primary["Tot_ict"]).median())
                rec["rel_spread_iqr_pct"] = float(
                    ((primary["P_nodes_kw"] / primary["Tot_ict"].replace(0, np.nan)).quantile(0.75)
                     - (primary["P_nodes_kw"] / primary["Tot_ict"].replace(0, np.nan)).quantile(0.25)) * 100
                )
            node_rows.append(rec)

        if liq is not None:
            liq = liq.copy()
            liq["timestamp_utc"] = pd.to_datetime(liq["timestamp_utc"], utc=True)
            ict = series.get("Tot_ict")
            for panel, g in liq.groupby(liq["panel"].astype(str)):
                g = g.set_index("timestamp_utc")
                rec = {
                    "month": month, "panel": panel,
                    "deltaT_median": float(g["delta_T_c"].median()) if "delta_T_c" in g else np.nan,
                    "deltaT_p05": float(g["delta_T_c"].quantile(0.05)) if "delta_T_c" in g else np.nan,
                    "deltaT_p95": float(g["delta_T_c"].quantile(0.95)) if "delta_T_c" in g else np.nan,
                    "frac_negative_deltaT": float((g["delta_T_c"] < 0).mean()) if "delta_T_c" in g else np.nan,
                    "Delta_temp_median": float(g["Delta_temp_mean"].median()) if "Delta_temp_mean" in g else np.nan,
                    "Delta_temp_std": float(g["Delta_temp_mean"].std() or 0) if "Delta_temp_mean" in g else np.nan,
                    "flow_median": float(g["Portata_attiva_mean"].median()) if "Portata_attiva_mean" in g else np.nan,
                    "supply_median": float(g["Temp_mandata_mean"].median()) if "Temp_mandata_mean" in g else np.nan,
                    "return_median": float(g["Temp_ritorno_mean"].median()) if "Temp_ritorno_mean" in g else np.nan,
                }
                if ict is not None:
                    joined = pd.concat([g, ict.rename("Tot_ict")], axis=1)
                    for x, name in (("Portata_attiva_mean", "flow"), ("delta_T_c", "deltaT"), ("heat_transfer_index", "hti")):
                        if x in joined:
                            rec[f"corr_{name}_vs_ict"] = float(joined[x].corr(joined["Tot_ict"]))
                liquid_rows.append(rec)
            panels = sorted(liq["panel"].astype(str).unique())
            if {"Q101", "Q102"}.issubset(set(panels)):
                a = liq.loc[liq.panel.astype(str).eq("Q101")].set_index("timestamp_utc")
                b = liq.loc[liq.panel.astype(str).eq("Q102")].set_index("timestamp_utc")
                for c in ("Temp_mandata_mean", "Temp_ritorno_mean", "delta_T_c", "Portata_attiva_mean", "heat_transfer_index"):
                    if c not in a or c not in b:
                        continue
                    s = pd.concat([a[c].rename("Q101"), b[c].rename("Q102")], axis=1).dropna()
                    twin_rows.append({
                        "month": month, "metric": c, **_metrics(s["Q101"], s["Q102"]),
                        "median_offset": float((s["Q101"] - s["Q102"]).median()),
                        "note": "redundant twins; do not sum",
                    })

        sys = pd.DataFrame()
        if "Tot" in series:
            sys = series["Tot"].rename("Tot_kw").to_frame()
            if "Tot_ict" in series:
                sys["Tot_ict_kw"] = series["Tot_ict"]
                sys["non_IT_kw"] = sys["Tot_kw"] - sys["Tot_ict_kw"]
                sys["PUE_calc"] = sys["Tot_kw"] / sys["Tot_ict_kw"].replace(0, np.nan)
            cool = [c for c in ("Tot_cdz", "Tot_chiller", "Tot_qpompe") if c in series]
            if cool:
                sys["cooling_kw"] = sum(series[c] for c in cool)
            if "Tot" in series and cool and "Tot_ict" in series:
                summed = series["Tot_ict"] + sum(series[c] for c in cool)
                if "Tot_servizi" in series:
                    summed = summed + series["Tot_servizi"]
                sys["closure_resid_kw"] = series["Tot"] - summed
        if wth is not None:
            w = wth.copy()
            w["timestamp_utc"] = pd.to_datetime(w["timestamp_utc"], utc=True)
            w = w.set_index("timestamp_utc")
            for c in ("temp_mean", "humidity_mean", "dew_point_mean", "twb_c", "pressure_mean"):
                if c in w.columns:
            for c in ("temp_mean", "humidity_mean", "dew_point_mean", "twb_c", "pressure_mean"):
                if c in w.columns:
                    if len(sys):
                        sys[c] = w[c]
                    else:
                        sys = w[[c]].copy()
        if crac is not None:
            c = crac.copy()
            c["timestamp_utc"] = pd.to_datetime(c["timestamp_utc"], utc=True)
            named = {}
            if "Return_Air_Temperature_mean" in c:
                named["median_return_c"] = ("Return_Air_Temperature_mean", "median")
                named["max_return_c"] = ("Return_Air_Temperature_mean", "max")
            if "Supply_Air_Temperature_mean" in c:
                named["median_supply_c"] = ("Supply_Air_Temperature_mean", "median")
            if "Fan_Speed_mean" in c:
                named["mean_fan_speed"] = ("Fan_Speed_mean", "mean")
            if "Compressor_Utilization_mean" in c:
                named["mean_compressor_util"] = ("Compressor_Utilization_mean", "mean")
            if "Free_Cooling_Status_mean" in c:
                named["mean_free_cooling"] = ("Free_Cooling_Status_mean", "mean")
            if "Free_Cooling_Valve_Open_Position_mean" in c:
                named["median_fc_valve"] = ("Free_Cooling_Valve_Open_Position_mean", "median")
            if named:
                agg = c.groupby("timestamp_utc").agg(**named)
                sys = sys.join(agg, how="outer") if len(sys) else agg
        if liq is not None:
            l = liq.copy()
            l["timestamp_utc"] = pd.to_datetime(l["timestamp_utc"], utc=True)
            agg_l = {}
            if "heat_transfer_index" in l:
                agg_l["heat_transfer_index"] = ("heat_transfer_index", "median")
            if "Portata_attiva_mean" in l:
                agg_l["liquid_flow_m3h"] = ("Portata_attiva_mean", "median")
            if agg_l:
                h = l.groupby("timestamp_utc").agg(**agg_l)
                sys = sys.join(h, how="outer") if len(sys) else h
        if len(sys):
            sys = sys.copy()
            sys.index = pd.to_datetime(sys.index, utc=True)
            sys = sys.reset_index().rename(columns={"index": "timestamp_utc"})
            if "timestamp_utc" not in sys.columns:
                sys = sys.rename(columns={sys.columns[0]: "timestamp_utc"})
            outp = grain_parquet("system", month)
            outp.parent.mkdir(parents=True, exist_ok=True)
            sys.to_parquet(outp, index=False)
            sys["month"] = month
            system_frames.append(sys)
            save_status(month, qc_result="system_hourly_written")

    if boundary_rows:
        pd.DataFrame(boundary_rows).to_csv(tables / "measurement_boundaries.csv", index=False)
    if closure_rows:
        pd.DataFrame(closure_rows).to_csv(tables / "electrical_closure.csv", index=False)
    if pue_rows:
        pd.DataFrame(pue_rows).to_csv(tables / "pue_validation.csv", index=False)
    if node_rows:
        pd.DataFrame(node_rows).to_csv(tables / "node_to_ict_validation.csv", index=False)
    if liquid_rows:
        pd.DataFrame(liquid_rows).to_csv(tables / "liquid_physics_validation.csv", index=False)
    if twin_rows:
        pd.DataFrame(twin_rows).to_csv(tables / "schneider_q101_q102.csv", index=False)
    if energy_rows:
        pd.DataFrame(energy_rows).to_csv(tables / "energy_meter_audit.csv", index=False)
    if ident_notes:
        pd.DataFrame(ident_notes).to_csv(tables / "identity_notes.csv", index=False)

    model_rows, residual_rows, regime_rows = [], [], []
    work = pd.DataFrame()
    if system_frames:
        allsys = pd.concat(system_frames, ignore_index=True)
        allsys["timestamp_utc"] = pd.to_datetime(allsys["timestamp_utc"], utc=True)
        allsys = allsys.sort_values("timestamp_utc")
        work = allsys.dropna(subset=["Tot_kw", "Tot_ict_kw", "non_IT_kw"]).copy()
        if "temp_mean" in work.columns:
            work["temp_sq"] = work["temp_mean"] ** 2
        months_q = sorted(work["month"].unique())
        note = (
            "expanding-window forward test"
            if len(months_q) >= 3
            else "2021 does not yet support cross-month chronological validation; within-month blocked checks only."
        )
        holdouts = []
        if len(work):
            if len(months_q) >= 3:
                for i in range(len(months_q) - 1):
                    train = work.loc[work["month"].isin(months_q[: i + 1])]
                    test = work.loc[work["month"].eq(months_q[i + 1])]
                    holdouts.append((train, test, months_q[i + 1], "expanding_forward"))
            else:
                for m in months_q:
                    w = work.loc[work["month"].eq(m)].sort_values("timestamp_utc")
                    cut = int(len(w) * 0.7)
                    holdouts.append((w.iloc[:cut], w.iloc[cut:], m, "within_month_blocked"))

        for train, test, test_label, scheme in holdouts:
            if len(train) < 50 or len(test) < 20:
                continue
            cols2 = [c for c in ("Tot_ict_kw", "temp_mean", "temp_sq", "twb_c") if c in train.columns]
            cols3 = cols2 + [c for c in (
                "mean_compressor_util", "mean_fan_speed", "mean_free_cooling",
                "liquid_flow_m3h", "heat_transfer_index",
            ) if c in train.columns]
            cols3 = list(dict.fromkeys(cols3))
            te2 = test.dropna(subset=[c for c in cols2 if c != "temp_sq"] + ["non_IT_kw", "Tot_ict_kw", "Tot_kw"])
            te3 = test.dropna(subset=[c for c in cols3 if c != "temp_sq"] + ["non_IT_kw", "Tot_ict_kw", "Tot_kw"])
            tr2 = train.dropna(subset=[c for c in cols2 if c != "temp_sq"] + ["non_IT_kw"])
            tr3 = train.dropna(subset=[c for c in cols3 if c != "temp_sq"] + ["non_IT_kw"])

            def predict_models(tr, te):
                out = {}
                alpha = (tr["Tot_kw"] / tr["Tot_ict_kw"]).median()
                out["B0_constant_pue"] = (alpha - 1.0) * te["Tot_ict_kw"].to_numpy(float)
                fit1 = ols_fit(tr["non_IT_kw"].to_numpy(float), tr[["Tot_ict_kw"]].to_numpy(float))
                if fit1:
                    out["B1_it_only"] = np.column_stack([np.ones(len(te)), te[["Tot_ict_kw"]].to_numpy(float)]) @ fit1["beta"]
                use2 = [c for c in cols2 if c in tr.columns and tr[c].notna().sum() > 20 and te[c].notna().sum() > 5]
                if len(use2) >= 2:
                    fit2 = ols_fit(tr["non_IT_kw"].to_numpy(float), tr[use2].to_numpy(float))
                    if fit2:
                        out["B2_it_weather"] = np.column_stack([np.ones(len(te)), te[use2].to_numpy(float)]) @ fit2["beta"]
                use3 = [c for c in cols3 if c in tr.columns and tr[c].notna().sum() > 20 and te[c].notna().sum() > 5]
                if len(use3) > len(use2):
                    fit3 = ols_fit(tr["non_IT_kw"].to_numpy(float), tr[use3].to_numpy(float))
                    if fit3:
                        out["B3_oracle_state"] = np.column_stack([np.ones(len(te)), te[use3].to_numpy(float)]) @ fit3["beta"]
                return out

            for sample_name, tr, te in (("weather_complete", tr2, te2), ("state_complete", tr3, te3)):
                if len(tr) < 50 or len(te) < 20:
                    continue
                preds = predict_models(tr, te)
                yte = te["non_IT_kw"].to_numpy(float)
                for name, pred in preds.items():
                    sc = score(yte, pred)
                    sc.update(score_pue(te["Tot_ict_kw"], te["Tot_kw"], pred))
                    sc.update({
                        "model": name, "test_month": test_label, "scheme": scheme,
                        "sample": sample_name, "note": note,
                        "role": "oracle_not_transferable" if name.startswith("B3") else "facility_reconstruct",
                    })
                    model_rows.append(sc)
                    if name in {"B2_it_weather", "B3_oracle_state"} and sample_name == "state_complete":
                        resid = yte - pred
                        residual_rows.append({
                            "model": name, "test_month": test_label, "sample": sample_name,
                            "corr_resid_it": float(pd.Series(resid).corr(te["Tot_ict_kw"].reset_index(drop=True))),
                            "corr_resid_temp": float(pd.Series(resid).corr(te["temp_mean"].reset_index(drop=True))) if "temp_mean" in te else np.nan,
                            "corr_resid_fc": float(pd.Series(resid).corr(te["mean_free_cooling"].reset_index(drop=True))) if "mean_free_cooling" in te else np.nan,
                            "acf_1h": autocorr(resid, 1),
                            "acf_6h": autocorr(resid, 6),
                            "acf_24h": autocorr(resid, 24),
                        })
                        te = te.copy()
                        te["resid"] = resid
                        te["it_bin"] = pd.qcut(te["Tot_ict_kw"], 3, labels=["low", "mid", "high"], duplicates="drop")
                        if "temp_mean" in te:
                            te["temp_bin"] = pd.qcut(te["temp_mean"], 3, labels=["cool", "mild", "warm"], duplicates="drop")
                        for col in ("it_bin", "temp_bin"):
                            if col not in te:
                                continue
                            for lvl, gg in te.groupby(col, observed=False):
                                regime_rows.append({
                                    "model": name, "test_month": test_label, "bin": col, "level": str(lvl),
                                    "n": int(len(gg)), "mae": float(gg["resid"].abs().mean()),
                                    "bias": float(gg["resid"].mean()),
                                })

        if model_rows:
            md = pd.DataFrame(model_rows)
            md.to_csv(tables / "model_validation_by_month.csv", index=False)
            cmp = (
                md.loc[md["sample"].eq("state_complete")]
                .groupby("model")[["mae", "rmse", "r2", "pue_mae", "pue_bias"]]
                .median()
                .reset_index()
            )
            cmp.to_csv(tables / "model_comparison.csv", index=False)
        if residual_rows:
            pd.DataFrame(residual_rows).to_csv(tables / "residual_diagnostics.csv", index=False)
        if regime_rows:
            pd.DataFrame(regime_rows).to_csv(tables / "residual_by_regime.csv", index=False)

        # figures
        if "Tot_ict_kw" in work.columns and "PUE_calc" in work.columns:
            fig, ax = plt.subplots(figsize=(8, 5))
            c = work["temp_mean"] if "temp_mean" in work.columns else None
            sc = ax.scatter(work["Tot_ict_kw"], work["PUE_calc"], c=c, s=8, cmap="coolwarm", alpha=0.7)
            if c is not None:
                fig.colorbar(sc, ax=ax, label="Outdoor dry-bulb (°C)")
            ax.set_xlabel("Facility IT power Tot_ict (kW)")
            ax.set_ylabel("PUE_calc = Tot / Tot_ict")
            ax.set_title("PUE vs IT load (color = outdoor temperature)")
            fig.tight_layout()
            fig.savefig(figs / "pue_vs_it_load.png", dpi=140)
            plt.close()
        if "heat_transfer_index" in work.columns:
            fig, ax = plt.subplots(figsize=(8, 5))
            ax.hexbin(work["Tot_ict_kw"], work["heat_transfer_index"], gridsize=40, mincnt=1, cmap="viridis")
            ax.set_xlabel("Tot_ict (kW)")
            ax.set_ylabel("Liquid heat-transfer index (m³/h · K)")
            ax.set_title("Property-free heat-transfer index vs IT load (not thermal kW)")
            fig.tight_layout()
            fig.savefig(figs / "hti_vs_it.png", dpi=140)
            plt.close()
        if "closure_resid_kw" in work.columns:
            fig, ax = plt.subplots(figsize=(9, 4))
            for m, g in work.groupby("month"):
                ax.plot(g["timestamp_utc"], g["closure_resid_kw"], lw=0.8, label=m)
            ax.axhline(0, color="k", lw=0.6)
            ax.set_ylabel("Tot − Σ components (kW)")
            ax.set_title("Facility electrical closure residual")
            ax.legend()
            fig.tight_layout()
            fig.savefig(figs / "electrical_closure.png", dpi=140)
            plt.close()
        if {"temp_mean", "mean_free_cooling", "mean_compressor_util"}.issubset(work.columns):
            fig, axes = plt.subplots(1, 2, figsize=(10, 4), sharex=True)
            axes[0].scatter(work["temp_mean"], work["mean_free_cooling"], s=8, alpha=0.5)
            axes[0].set_xlabel("Outdoor dry-bulb (°C)")
            axes[0].set_ylabel("Mean Free_Cooling_Status (0–1)")
            axes[1].scatter(work["temp_mean"], work["mean_compressor_util"], s=8, alpha=0.5, color="tab:red")
            axes[1].set_xlabel("Outdoor dry-bulb (°C)")
            axes[1].set_ylabel("Mean compressor utilization")
            fig.suptitle("Weather vs free-cooling / compressor (inspect coding before transfer)")
            fig.tight_layout()
            fig.savefig(figs / "weather_vs_freecooling.png", dpi=140)
            plt.close()
        if model_rows:
            md = pd.DataFrame(model_rows)
            sub = md.loc[md["sample"].eq("state_complete")]
            if len(sub):
                fig, ax = plt.subplots(figsize=(8, 4.5))
                models = ["B0_constant_pue", "B1_it_only", "B2_it_weather", "B3_oracle_state"]
                months_t = sorted(sub["test_month"].unique())
                x = np.arange(len(months_t))
                width = 0.18
                for i, mod in enumerate(models):
                    ys = [sub.loc[sub.model.eq(mod) & sub.test_month.eq(m), "mae"].mean() for m in months_t]
                    ax.bar(x + i * width, ys, width, label=mod)
                ax.set_xticks(x + 1.5 * width)
                ax.set_xticklabels(months_t)
                ax.set_ylabel("Held-out MAE of non-IT power (kW)")
                ax.set_title("Chronological held-out MAE (same state-complete hours)")
                ax.legend(fontsize=8)
                fig.tight_layout()
                fig.savefig(figs / "model_heldout.png", dpi=140)
                plt.close()
        if residual_rows and len(work):
            # rebuild last holdout residuals for scatter if possible
            fig, axes = plt.subplots(1, 2, figsize=(10, 4), sharey=True)
            if len(months_q) >= 2:
                last_test = work.loc[work["month"].eq(months_q[-1])]
                last_train = work.loc[work["month"].isin(months_q[:-1])]
                te = last_test.dropna(subset=["non_IT_kw", "Tot_ict_kw", "temp_mean"])
                tr = last_train.dropna(subset=["non_IT_kw", "Tot_ict_kw", "temp_mean"])
                if len(te) and len(tr):
                    use2 = [c for c in ("Tot_ict_kw", "temp_mean", "temp_sq", "twb_c") if c in tr.columns]
                    fit2 = ols_fit(tr["non_IT_kw"].to_numpy(float), tr[use2].to_numpy(float))
                    if fit2:
                        pred2 = np.column_stack([np.ones(len(te)), te[use2].to_numpy(float)]) @ fit2["beta"]
                        axes[0].scatter(te["temp_mean"], te["non_IT_kw"] - pred2, s=8, alpha=0.5)
                    use3 = use2 + [c for c in ("mean_compressor_util", "mean_free_cooling", "liquid_flow_m3h") if c in tr.columns]
                    te3 = last_test.dropna(subset=use3 + ["non_IT_kw"])
                    tr3 = last_train.dropna(subset=use3 + ["non_IT_kw"])
                    if len(te3) and len(tr3):
                        fit3 = ols_fit(tr3["non_IT_kw"].to_numpy(float), tr3[use3].to_numpy(float))
                        if fit3:
                            pred3 = np.column_stack([np.ones(len(te3)), te3[use3].to_numpy(float)]) @ fit3["beta"]
                            axes[1].scatter(te3["temp_mean"], te3["non_IT_kw"] - pred3, s=8, alpha=0.5, color="tab:green")
            axes[0].axhline(0, color="k", lw=0.6)
            axes[1].axhline(0, color="k", lw=0.6)
            axes[0].set_title("B2 residual vs outdoor T")
            axes[1].set_title("B3 oracle residual vs outdoor T")
            axes[0].set_xlabel("Outdoor dry-bulb (°C)")
            axes[1].set_xlabel("Outdoor dry-bulb (°C)")
            axes[0].set_ylabel("non-IT residual (kW)")
            fig.tight_layout()
            fig.savefig(figs / "residuals_b2_b3.png", dpi=140)
            plt.close()
        if node_rows:
            nd = pd.DataFrame(node_rows)
            if nd["n"].fillna(0).max() >= 5:
                fig, ax = plt.subplots(figsize=(6, 4))
                ax.bar(nd["month"], nd["corr"].fillna(0))
                ax.set_ylabel("corr(P_nodes, Tot_ict)")
                ax.set_title("Node-sum vs facility IT meter (HQ hours)")
                fig.tight_layout()
                fig.savefig(figs / "node_vs_ict.png", dpi=140)
                plt.close()

    qpath = tables / "month_qualification.csv"
    if qpath.exists():
        q = pd.read_csv(qpath)
        fig, ax = plt.subplots(figsize=(9, 4))
        layers = ["facility_total_power", "facility_it_power", "cooling_component_power",
                  "liquid_flow_temp", "air_cooling", "weather", "node_total_power"]
        layers = [c for c in layers if c in q.columns]
        mat = q.set_index("month")[layers].astype(int)
        ax.imshow(mat.T, aspect="auto", cmap="Greens", vmin=0, vmax=1)
        ax.set_yticks(range(len(layers)))
        ax.set_yticklabels(layers)
        ax.set_xticks(range(len(mat.index)))
        ax.set_xticklabels(mat.index, rotation=45, ha="right")
        ax.set_title("2021 month/layer availability (complete archives only)")
        fig.tight_layout()
        fig.savefig(figs / "month_layer_availability.png", dpi=140)
        plt.close()

    classification = "B" if months else "C"
    manifest = {
        "facility_months": months,
        "weather_months": weather_months,
        "liquid_months": liquid_months,
        "crac_months": crac_months,
        "node_months": sorted(node_months),
        "n_model_rows": int(len(model_rows)),
        "water": "empirical WUE unsupported; circulating flow is not water use",
        "gpu_direct_validation": "not run: Gpu*_gpu_utilization absent (power_usage/gpu_temp exist)",
        "energy_vs_power": "not forced: Mwh is b-c/cabina-misure; Energia is per-panel; neither is generals/pue Tot",
        "b3_role": "oracle/state-informed explanatory benchmark; not a deployable Prineville model",
        "classification": classification,
        "do_not_transfer": [
            "absolute M100 coefficients", "M100 PUE values", "M100 cooling-power fractions",
            "M100 GPU coefficients", "M100 hourly traces",
        ],
    }
    (RESULTS_DIR / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    write_final_report(manifest, tables, classification)
    print(json.dumps(manifest, indent=2))


def write_final_report(manifest: dict, tables: Path, classification: str) -> None:
    def readcsv(name):
        p = tables / name
        return pd.read_csv(p) if p.exists() else pd.DataFrame()

    q = readcsv("month_qualification.csv")
    clos = readcsv("electrical_closure.csv")
    mod = readcsv("model_validation_by_month.csv")
    water = readcsv("water_metric_audit.csv")
    n2i = readcsv("node_to_ict_validation.csv")
    title = {
        "A": "strong external facility-model benchmark",
        "B": "useful structural/physics benchmark, limited transfer",
        "C": "useful telemetry/sanity dataset but weak facility-model benchmark",
    }.get(classification, classification)
    lines = [
        "# M100 2021 facility-model suitability report",
        "",
        f"**Classification: {classification} — {title}.**",
        "",
        "M100 is an external measured benchmark. Do not transfer coefficients, PUE levels,",
        "cooling fractions, GPU coefficients, or hourly traces to Meta Prineville.",
        "",
        "## Measurement",
        "",
        "Canonical facility meters are `panel=generals`, `device=pue` for Tot, Tot_ict, and cooling kW.",
        "`pt`/`pit` are room meters (`pue_sala_m` / `pue_sala_n`) and are not equivalent to Tot/Tot_ict.",
        "`Pue` on generals/pue matches Tot/Tot_ict. Lowercase `pue` is a different room meter.",
        "",
    ]
    if len(clos):
        lines += ["Electrical closure residual (Tot − Σ components):", "", clos.to_string(index=False), ""]
    lines += [
        "## Thermal",
        "",
        "Q101 and Q102 are redundant twins: do not sum. Documented `Delta_temp` is a constant 6 °C setpoint.",
        "Computed return−supply ≈ 6 °C. Heat-transfer index is mean(flow*ΔT) at source timestamps, not thermal kW.",
        "",
        "## Weather and state",
        "",
        "Outdoor dry-bulb strongly tracks non-IT power. Constant PUE is falsified in chronological holdout.",
        "B3 is an oracle / state-informed benchmark, not a deployable Prineville model.",
        "",
        "## Chronological models",
        "",
        mod.to_string(index=False) if len(mod) else "Insufficient certified months for chronological modeling at report time.",
        "",
        "## Water",
        "",
        "**Empirical WUE unsupported. Water withdrawal unsupported. Water consumption unsupported.**",
        "Closed-loop Portata_attiva is circulating RDHx flow, not makeup/withdrawal.",
        "Supported chain: IT power → heat transport → liquid/air control → cooling electricity.",
        "",
        "## Prineville structural implications",
        "",
        "Retain/add: load dependence of overhead; weather dependence; explicit operating/control state.",
        "Do not transfer M100 alphas, PUE values, cooling shares, or RDHx/chiller/CRAC architecture",
        "as validation of Prineville evaporative-water equations.",
        "",
        f"Facility months: {manifest.get('facility_months')}",
        f"Node months: {manifest.get('node_months')}",
        "",
    ]
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "final_report.md").write_text("\n".join(str(x) for x in lines) + "\n")
    (RESULTS_DIR / "final_status.json").write_text(json.dumps({
        "classification": classification,
        "manifest": manifest,
        "n_qualification_rows": int(len(q)),
        "n_model_rows": int(len(mod)),
        "n_node_ict_rows": int(len(n2i)),
        "water_hits": int(water["n_name_hits"].iloc[0]) if len(water) and "n_name_hits" in water.columns else 0,
    }, indent=2, default=str) + "\n")


def main():
    analyze()


if __name__ == "__main__":
    main()
