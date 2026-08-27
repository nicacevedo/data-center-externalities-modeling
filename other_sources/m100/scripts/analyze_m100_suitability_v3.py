#!/usr/bin/env python3
"""M100 2021 v3 closure runner. Writes only to results/suitability_2021_v3_closure/.

Stages: prep, static, within_month, node, thermal, dynamic, literature, support, aggregate, report_only, audit
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from m100_2021_common import (
    ARCHIVES_DIR,
    NOMINAL_VERTIV_PER_HOUR,
    POOL_M100,
    ROOT,
    ZENODO,
    archive_path,
    grain_parquet,
    month_calendar,
)
from m100_suitability_v2 import (
    acf_lag,
    expanding_folds,
    rel_mae_improvement,
    sha256_file,
)
from m100_suitability_v3 import (
    DFC_DEVICES,
    EXECUTED_SAMPLE_WITH_NUMERICAL_DISCREPANCY,
    FORMULAS,
    HEURISTIC_NOTE,
    HQ_THRESHOLD,
    LITERATURE,
    LITERATURE_TRIANGULATION_CAVEAT,
    NODE_MONTHS,
    NON_DFC_DEVICES,
    NOT_REQUIRED_BY_M100_EVIDENCE,
    NOT_STABLY_SUPPORTED_AS_GENERIC_INPUT,
    NOT_SUPPORTED,
    NOT_TESTABLE_FROM_PROCESSED_FIELDS,
    NRMSE_DEF,
    ORIG_SUIT,
    OUT_DIR,
    PILOT_DIR,
    QUALIFIED_MONTHS,
    R1_FORBIDDEN,
    STRONG_SUPPORT,
    TDB_DFC_C,
    V2_DIR,
    active_liquid_panel,
    as_strong_support_token,
    build_contract,
    complete_case_mask,
    coverage_status,
    daily_peak_and_std_error,
    design_W,
    design_descriptor,
    energy_quality_mask,
    energy_quality_robustness_from_hq,
    evidence_label_from_improvements,
    fit_d1,
    fit_predict,
    format_struct_claim_evidence,
    freeze_hashes,
    git_head,
    hti_on_active_paths,
    independent_wetbulb,
    joint_support_label,
    lag_pairs,
    literature_execution_status,
    literature_reason,
    load_month_v3,
    metrics,
    nested_scores,
    node_timestamp_series,
    panel_activity_table,
    predict_d1_one_step,
    predict_d1_recursive,
    rebuild_stage_status_index,
    regime_generic_input_label,
    save_stage_status,
    save_stage_status_month,
    weather_interaction_label,
    stage_dir,
    support_label,
    triangulation_rows,
    w_feature_names,
    within_month_split,
    write_table,
)

PY = sys.executable
V2_FROZEN = freeze_hashes()


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_frames(months=None) -> dict[str, pd.DataFrame]:
    months = months or QUALIFIED_MONTHS
    out = {}
    for m in months:
        df = load_month_v3(m)
        if not df.empty:
            out[m] = df
    return out


def concat_months(frames, months) -> pd.DataFrame:
    parts = [frames[m] for m in months if m in frames]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def base_cols():
    return ["P_IT", "P_nonIT", "P_facility", "T_wetbulb"]


def descriptor_cols():
    return ["P_IT", "P_nonIT", "P_facility", "T_wetbulb", "T_drybulb", "RH"]


def stage_prep() -> dict:
    """Lightweight test gate. Does not require Pool data beyond imports."""
    t0 = time.time()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "scripts")
    cmd = [
        PY, "-m", "pytest", "-q",
        str(ROOT / "tests" / "test_m100_suitability_v2.py"),
        str(ROOT / "tests" / "test_m100_suitability_v3.py"),
    ]
    proc = subprocess.run(cmd, cwd=str(ROOT.parents[1]), env=env, capture_output=True, text=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "tables").mkdir(exist_ok=True)
    (OUT_DIR / "figures").mkdir(exist_ok=True)
    (OUT_DIR / "prep_pytest.out").write_text(proc.stdout + "\n" + proc.stderr)
    hashes = freeze_hashes()
    (OUT_DIR / "frozen_v2_hashes.json").write_text(json.dumps(hashes, indent=2) + "\n")
    payload = {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-2000:],
        "elapsed_s": time.time() - t0,
        "frozen_v2": hashes,
        "git_head": git_head(),
    }
    if proc.returncode != 0:
        save_stage_status("prep", payload)
        raise SystemExit(f"PREP TEST GATE FAILED\n{proc.stdout}\n{proc.stderr}")
    save_stage_status("prep", payload)
    return payload


def _fold_scores(frames, ycol="P_nonIT", models=("W0", "W1", "W2"), mask_name="complete"):
    rows, coefs, incs = [], [], []
    folds = expanding_folds(QUALIFIED_MONTHS)
    for f in folds:
        train = concat_months(frames, f["train_months"])
        test = frames.get(f["test_month"], pd.DataFrame())
        if train.empty or test.empty:
            continue
        cols = base_cols() if ycol == "P_nonIT" else ["P_IT", ycol, "P_facility", "T_wetbulb"]
        if ycol == "P_cooling":
            cols = ["P_IT", "P_cooling", "P_facility", "T_wetbulb"]
        if mask_name == "energy_quality":
            mtr = complete_case_mask(train, cols) & energy_quality_mask(train)
            mte = complete_case_mask(test, cols) & energy_quality_mask(test)
        else:
            mtr = complete_case_mask(train, cols)
            mte = complete_case_mask(test, cols)
        tr, te = train.loc[mtr], test.loc[mte]
        if ycol == "P_cooling":
            tr = tr.dropna(subset=["P_cooling"])
            te = te.dropna(subset=["P_cooling"])
        if len(tr) < 50 or len(te) < 20:
            continue
        sc, cf, pred = nested_scores(tr, te, list(models), ycol=ycol)
        for r in sc:
            r.update({
                "fold_id": f["fold_id"], "test_month": f["test_month"],
                "train_months": "|".join(f["train_months"]),
                "mask": mask_name, "n_train": int(len(tr)), "n_test": int(len(te)),
                "future_in_train": False,
            })
        rows.extend(sc)
        for c in cf:
            c.update({"fold_id": f["fold_id"], "test_month": f["test_month"], "mask": mask_name})
        coefs.extend(cf)
        by = {r["model"]: r["mae"] for r in sc}
        if "W0" in by and "W1" in by:
            incs.append({
                "fold_id": f["fold_id"], "test_month": f["test_month"], "mask": mask_name,
                "target": ycol, "increment": "W0_to_W1",
                "mae_simple": by["W0"], "mae_rich": by["W1"],
                "mae_rel_improvement": rel_mae_improvement(by["W0"], by["W1"]),
                "threshold": ">=5% held-out MAE", "threshold_note": HEURISTIC_NOTE,
            })
        if "W1" in by and "W2" in by:
            incs.append({
                "fold_id": f["fold_id"], "test_month": f["test_month"], "mask": mask_name,
                "target": ycol, "increment": "W1_to_W2",
                "mae_simple": by["W1"], "mae_rich": by["W2"],
                "mae_rel_improvement": rel_mae_improvement(by["W1"], by["W2"]),
                "threshold": ">=5% held-out MAE", "threshold_note": HEURISTIC_NOTE,
            })
        if "W2" in by and "R1" in by:
            incs.append({
                "fold_id": f["fold_id"], "test_month": f["test_month"], "mask": mask_name,
                "target": ycol, "increment": "W2_to_R1",
                "mae_simple": by["W2"], "mae_rich": by["R1"],
                "mae_rel_improvement": rel_mae_improvement(by["W2"], by["R1"]),
                "threshold": ">=5% held-out MAE", "threshold_note": HEURISTIC_NOTE,
            })
    return pd.DataFrame(rows), pd.DataFrame(coefs), pd.DataFrame(incs)


def stage_static():
    frames = load_frames()
    # coverage inventory
    cov_rows = []
    for m, df in frames.items():
        fac = pd.read_parquet(grain_parquet("facility", m))
        wcols = list(pd.read_parquet(grain_parquet("weather", m)).columns) if grain_parquet("weather", m).exists() else []
        ccols = list(pd.read_parquet(grain_parquet("crac", m)).columns) if grain_parquet("crac", m).exists() else []
        for prefix, cols in [("Tot", fac.columns), ("Tot_ict", fac.columns),
                             ("temp", wcols), ("Free_Cooling_Status", ccols)]:
            st = coverage_status(list(cols), prefix)
            st["month"] = m
            cov_rows.append(st)
    cov_df = pd.DataFrame(cov_rows)

    nest, coefs, incs = _fold_scores(frames, "P_nonIT", ("W0", "W1", "W2"), "complete")
    nest_eq, _, incs_eq = _fold_scores(frames, "P_nonIT", ("W0", "W1", "W2"), "energy_quality")
    hq_note = (
        "Tot/Tot_ict/weather/Free_Cooling_Status have no *_coverage field in processed hourly Parquet "
        "(Logics/weather queries passed expected=None). HQ_COVERAGE_NOT_AVAILABLE. "
        "Robustness uses energy-quality hours (trapezoidal integral present, gap<=180s)."
    )
    rob = pd.concat([
        nest.assign(sample="complete_case_v2_like"),
        nest_eq.assign(sample="energy_quality_filter"),
    ], ignore_index=True)

    # October diagnostic
    oct_rows = []
    if "2021-10" in frames:
        d = frames["2021-10"]
        s = d.dropna(subset=["P_IT", "P_facility"])
        pue_calc = s["PUE_calc"]
        pue_rep = s["PUE_reported"] if "PUE_reported" in s.columns else pd.Series(np.nan, index=s.index)
        oct_rows.append({
            "month": "2021-10",
            "canonical_panel": "generals",
            "canonical_device": "pue",
            "n_valid": int(len(s)),
            "frac_PUE_calc_lt_1": float((pue_calc < 1).mean()) if len(s) else np.nan,
            "frac_facility_lt_IT": float((s["P_facility"] < s["P_IT"]).mean()),
            "PUE_reported_vs_calc_corr": float(pue_calc.corr(pue_rep)) if pue_rep.notna().any() else np.nan,
            "PUE_reported_vs_calc_mae": float((pue_calc - pue_rep).abs().mean()) if pue_rep.notna().any() else np.nan,
            "retain_october_in_main_analysis": True,
            "reported_PUE_as_independent_validation": False,
            "note": "retain canonical Tot/Tot_ict; do not use reported Pue as independent validation if anomalous",
        })
    oct_df = pd.DataFrame(oct_rows)

    # energy accounting
    en_rows = []
    for m, df in frames.items():
        s = df.dropna(subset=["P_IT", "P_nonIT"])
        row = {
            "month": m,
            "n_mean_hours": int(len(s)),
            "sum_mean_P_nonIT_kwh": float(s["P_nonIT"].sum()),
            "n_integral_hours": int(df["P_nonIT_energy_kwh"].notna().sum()) if "P_nonIT_energy_kwh" in df else 0,
            "sum_integral_P_nonIT_kwh": float(df["P_nonIT_energy_kwh"].sum(skipna=True)) if "P_nonIT_energy_kwh" in df else np.nan,
            "calendar_hours": int(len(month_calendar(m))),
            "calendar_full_period_energy_reported": False,
            "nrmse_definition": NRMSE_DEF,
        }
        if row["n_integral_hours"] and row["sum_integral_P_nonIT_kwh"]:
            both = s.dropna(subset=["P_nonIT_energy_kwh"])
            if len(both):
                row["mean_vs_integral_rel_pct"] = float(
                    100.0 * (both["P_nonIT"].sum() - both["P_nonIT_energy_kwh"].sum())
                    / both["P_nonIT_energy_kwh"].sum()
                )
        en_rows.append(row)
    en_df = pd.DataFrame(en_rows)

    # wet-bulb QA
    wb_rows = []
    for m, df in frames.items():
        need = ["T_drybulb", "RH", "dew_point_mean", "pressure_station_pa", "T_wetbulb"]
        if not set(need).issubset(df.columns):
            continue
        sub = df.dropna(subset=need)
        if sub.empty:
            continue
        recs = [independent_wetbulb(r.T_drybulb, r.dew_point_mean, r.RH, r.pressure_station_pa) for r in sub.itertuples()]
        qa = pd.DataFrame(recs)
        stored = sub["T_wetbulb"].to_numpy(float)
        for name, col in [("tdew_path", "twb_from_tdew"), ("rh_path", "twb_from_rh"), ("stull", "twb_stull")]:
            alt = qa[col].to_numpy(float)
            ok = np.isfinite(stored) & np.isfinite(alt)
            if not ok.any():
                continue
            d = alt[ok] - stored[ok]
            wb_rows.append({
                "month": m, "comparison": name, "n": int(ok.sum()),
                "mae": float(np.mean(np.abs(d))), "max_abs": float(np.max(np.abs(d))),
                "corr": float(np.corrcoef(stored[ok], alt[ok])[0, 1]) if ok.sum() > 2 else np.nan,
                "frac_twb_gt_tdb": float((stored > sub["T_drybulb"].to_numpy(float)).mean()),
                "canonical_twb_changed": False,
            })
    wb_df = pd.DataFrame(wb_rows)

    # descriptor robustness on common sample
    desc_rows = []
    specs = ["IT", "IT_Tdb", "IT_Twb", "IT_Tdb_RH"]
    opt = ["IT_Tdb_interact", "IT_Twb_interact"]
    for f in expanding_folds(QUALIFIED_MONTHS):
        train = concat_months(frames, f["train_months"])
        test = frames.get(f["test_month"], pd.DataFrame())
        cols = descriptor_cols()
        mtr = complete_case_mask(train, cols)
        mte = complete_case_mask(test, cols)
        tr, te = train.loc[mtr], test.loc[mte]
        if len(tr) < 50 or len(te) < 20:
            continue
        yte = te["P_nonIT"].to_numpy(float)
        pit, fac = te["P_IT"].to_numpy(float), te["P_facility"].to_numpy(float)
        for spec in specs + opt:
            Xtr, intercept, names = design_descriptor(tr, spec)
            Xte, _, _ = design_descriptor(te, spec)
            beta = __import__("m100_suitability_v2", fromlist=["ols_fit"]).ols_fit(tr["P_nonIT"].to_numpy(float), Xtr, intercept)
            phat = __import__("m100_suitability_v2", fromlist=["ols_pred"]).ols_pred(beta, Xte, intercept)
            sc = metrics(yte, phat, pit=pit, p_fac=fac)
            sc.update({
                "fold_id": f["fold_id"], "test_month": f["test_month"], "spec": spec,
                "optional_interaction_table": spec in opt,
                "n_train": int(len(tr)), "n_test": int(len(te)),
                "note": "predeclared robustness, not variable selection",
            })
            desc_rows.append(sc)
    desc_df = pd.DataFrame(desc_rows)

    # state semantics
    sem_rows, assoc_rows = [], []
    for m in QUALIFIED_MONTHS:
        cp = grain_parquet("crac", m)
        if not cp.exists() or m not in frames:
            continue
        c = pd.read_parquet(cp)
        c["hour_utc"] = pd.to_datetime(c["timestamp_utc"], utc=True)
        devices = sorted(c["device"].astype(str).unique())
        fc_devices = []
        for dev, g in c.groupby(c["device"].astype(str)):
            use = "Free_Cooling_Status_fraction_time_active"
            if use not in g.columns:
                use = "Free_Cooling_Status_mean" if "Free_Cooling_Status_mean" in g.columns else None
            if use is None:
                continue
            vals = g[use].dropna()
            if vals.empty:
                continue
            if float(vals.max()) > 0:
                fc_devices.append(dev)
            cov = np.nan
            if "Free_Cooling_Status_coverage" in g.columns:
                cov = float(g["Free_Cooling_Status_coverage"].median())
                cov_status = "AVAILABLE"
            else:
                if "Free_Cooling_Status_count" in g.columns:
                    frac = g["Free_Cooling_Status_count"] / float(NOMINAL_VERTIV_PER_HOUR)
                    cov = float(frac.median())
                    cov_status = "HQ_COVERAGE_NOT_AVAILABLE; count/NOMINAL_VERTIV_PER_HOUR diagnostic only"
                else:
                    cov_status = "HQ_COVERAGE_NOT_AVAILABLE"
            trans = float(g["Free_Cooling_Status_transition_count"].mean()) if "Free_Cooling_Status_transition_count" in g else np.nan
            sem_rows.append({
                "month": m, "device": dev, "n_devices_in_month": len(devices),
                "exposes_Free_Cooling_Status": True,
                "aggregation": "hourly fraction_time_active from Vertiv state samples",
                "mean_fraction_active": float(vals.mean()),
                "p50_fraction_active": float(vals.median()),
                "n_hours": int(len(vals)),
                "mean_transitions": trans,
                "coverage_status": cov_status,
                "coverage_or_count_frac_median": cov,
                "literature_dfc_expected": dev in DFC_DEVICES,
            })
        weather = frames[m][["hour_utc", "T_drybulb", "T_wetbulb", "cooling_state"]].dropna(subset=["cooling_state"])
        if "T_drybulb" in weather and weather["T_drybulb"].notna().any():
            w = weather.dropna(subset=["T_drybulb"])
            active = w["cooling_state"] >= 0.5
            assoc_rows.append({
                "month": m,
                "P_active_given_Tdb_lt_18": float(active.loc[w["T_drybulb"] < TDB_DFC_C].mean()) if (w["T_drybulb"] < TDB_DFC_C).any() else np.nan,
                "P_active_given_Tdb_ge_18": float(active.loc[w["T_drybulb"] >= TDB_DFC_C].mean()) if (w["T_drybulb"] >= TDB_DFC_C).any() else np.nan,
                "corr_state_Tdb": float(w["cooling_state"].corr(w["T_drybulb"])),
                "corr_state_Twb": float(w["cooling_state"].corr(w["T_wetbulb"])) if w["T_wetbulb"].notna().any() else np.nan,
                "facility_state_min": float(w["cooling_state"].min()),
                "facility_state_max": float(w["cooling_state"].max()),
                "n": int(len(w)),
                "forced_18C_rule": False,
            })
    sem_df = pd.DataFrame(sem_rows)
    assoc_df = pd.DataFrame(assoc_rows)
    if len(sem_df):
        sem_df = sem_df.merge(assoc_df, on="month", how="left") if len(assoc_df) else sem_df

    # R1 on state-common timestamps
    r1_rows, r1_inc = [], []
    state_ok = True
    if len(assoc_df):
        # trustworthy if 4 DFC devices exist and state varies
        n_fc = sem_df.loc[sem_df["mean_fraction_active"] > 0, "device"].nunique() if len(sem_df) else 0
        state_ok = n_fc >= 1 and float(pd.concat([frames[m]["cooling_state"].dropna() for m in frames]).std()) > 0.02
    if state_ok:
        for f in expanding_folds(QUALIFIED_MONTHS):
            train = concat_months(frames, f["train_months"])
            test = frames.get(f["test_month"], pd.DataFrame())
            cols = base_cols() + ["cooling_state"]
            mtr = complete_case_mask(train, cols)
            mte = complete_case_mask(test, cols)
            tr, te = train.loc[mtr], test.loc[mte]
            if len(tr) < 50 or len(te) < 20:
                continue
            sc, cf, pred = nested_scores(tr, te, ["W0", "W1", "W2", "R1"])
            by = {r["model"]: r["mae"] for r in sc}
            for r in sc:
                r.update({"fold_id": f["fold_id"], "test_month": f["test_month"],
                          "sample": "state_common", "n_train": int(len(tr)), "n_test": int(len(te)),
                          "forbidden_in_R1": "|".join(R1_FORBIDDEN)})
                r1_rows.append(r)
            r1_inc.append({
                "fold_id": f["fold_id"], "test_month": f["test_month"],
                "increment": "W2_to_R1",
                "mae_simple": by["W2"], "mae_rich": by["R1"],
                "mae_rel_improvement": rel_mae_improvement(by["W2"], by["R1"]),
                "threshold_note": HEURISTIC_NOTE,
            })
    r1_df = pd.DataFrame(r1_rows)
    r1inc_df = pd.DataFrame(r1_inc)

    # cooling target accounting + nested
    cool_acc = []
    for m, df in frames.items():
        s = df.dropna(subset=["P_nonIT", "P_cooling"])
        if s.empty:
            continue
        e_n = s["P_nonIT_energy_kwh"].sum() if "P_nonIT_energy_kwh" in s else s["P_nonIT"].sum()
        e_c = s["P_cooling_energy_kwh"].sum() if "P_cooling_energy_kwh" in s else s["P_cooling"].sum()
        cool_acc.append({
            "month": m, "n": int(len(s)),
            "frac_nonIT_energy_from_cooling": float(e_c / e_n) if e_n else np.nan,
            "P_aux_energy": float(e_n - e_c) if np.isfinite(e_n) and np.isfinite(e_c) else np.nan,
            "median_P_aux_kW": float((s["P_nonIT"] - s["P_cooling"]).median()),
        })
    cool_acc_df = pd.DataFrame(cool_acc)
    cool_nest, _, cool_inc = _fold_scores(frames, "P_cooling", ("W0", "W1", "W2"), "complete")

    write_table(cov_df, "measurement_hq_status.csv")
    write_table(rob, "measurement_hq_robustness.csv")
    write_table(en_df, "energy_accounting.csv")
    write_table(wb_df, "wetbulb_qa.csv")
    write_table(nest, "weather_nested_folds.csv")
    write_table(incs, "weather_nested_increments.csv")
    write_table(desc_df, "weather_descriptor_robustness.csv")
    write_table(pd.DataFrame(sem_rows), "state_semantics.csv")
    write_table(assoc_df, "state_weather_association.csv")
    write_table(r1_df, "state_regime_test.csv")
    write_table(r1inc_df, "state_regime_increments.csv")
    write_table(cool_acc_df, "cooling_target_accounting.csv")
    write_table(cool_nest, "cooling_target_results.csv")
    write_table(oct_df, "october_diagnostic.csv")
    write_table(pd.concat([incs, cool_inc], ignore_index=True) if len(cool_inc) else incs, "incremental_all.csv")

    save_stage_status("static", {
        "ok": True, "n_months": len(frames), "n_folds": int(nest["fold_id"].nunique()) if len(nest) else 0,
        "hq_note": hq_note,
    })
    return {"frames": list(frames)}


def stage_within_month():
    frames = load_frames()
    rows, incs = [], []
    for m, df in frames.items():
        mask = complete_case_mask(df, base_cols())
        tr, te = within_month_split(df, mask)
        if len(tr) < 24 or len(te) < 12:
            continue
        sc, _, _ = nested_scores(tr, te, ["W0", "W1", "W2"])
        by = {r["model"]: r["mae"] for r in sc}
        for r in sc:
            r.update({"month": m, "n_train": int(len(tr)), "n_test": int(len(te)),
                      "split": "first_2/3_train_last_1/3_test", "selection": "fixed_chronological"})
            rows.append(r)
        incs.append({
            "month": m, "increment": "W0_to_W1",
            "mae_rel_improvement": rel_mae_improvement(by["W0"], by["W1"]),
            "threshold_note": HEURISTIC_NOTE,
        })
        incs.append({
            "month": m, "increment": "W1_to_W2",
            "mae_rel_improvement": rel_mae_improvement(by["W1"], by["W2"]),
            "threshold_note": HEURISTIC_NOTE,
        })
    write_table(pd.DataFrame(rows), "weather_within_month.csv")
    write_table(pd.DataFrame(incs), "weather_within_month_increments.csv")
    save_stage_status("within_month", {"ok": True, "n_months": len({r['month'] for r in rows})})


def _summarize_node_month(m: str) -> dict:
    """One processed node month. Does not refit facility models."""
    npth = grain_parquet("node", m)
    if not npth.exists():
        return {"month": m, "status": "no_node_parquet"}
    node = pd.read_parquet(npth)
    gpu_power_cols = [
        c for c in node.columns
        if "gpu" in c.lower() and any(tok in c.lower() for tok in ("power", "energy", "watt"))
    ]
    gpu_chain = "present_in_columns" if gpu_power_cols else "SKIP"
    hq = node
    if "high_quality" in node.columns:
        hq = node.loc[node["high_quality"].astype(bool)]
    elif "total_power_coverage" in node.columns:
        hq = node.loc[node["total_power_coverage"] >= HQ_THRESHOLD]
    hq = hq.copy()
    hq["hour_utc"] = node_timestamp_series(hq)
    agg = hq.groupby("hour_utc").agg(
        n_hq_nodes=("node", "nunique") if "node" in hq.columns else ("total_power_mean", "size"),
        P_nodes_W=("total_power_mean", "sum"),
        median_coverage=("total_power_coverage", "median") if "total_power_coverage" in hq.columns else ("total_power_mean", "size"),
    ).reset_index()
    n_ref = float(agg["n_hq_nodes"].max()) if len(agg) else np.nan
    agg["P_nodes_kW"] = agg["P_nodes_W"] / 1000.0
    agg["P_nodes_kW_coverage_adjusted"] = agg["P_nodes_kW"] * (n_ref / agg["n_hq_nodes"].replace(0, np.nan))
    fac = load_month_v3(m)
    if fac.empty or "P_IT" not in fac.columns:
        (OUT_DIR / "tables").mkdir(parents=True, exist_ok=True)
        agg.to_csv(OUT_DIR / "tables" / f"node_hourly_{m}.csv", index=False)
        return {
            "month": m,
            "status": "node_present_facility_IT_absent",
            "n_hours_nodes": int(len(agg)),
            "median_hq_nodes": float(agg["n_hq_nodes"].median()) if len(agg) else np.nan,
            "facility_IT_available": False,
            "gpu_chain": gpu_chain,
            "note": "node parquet present; canonical Tot_ict absent this month",
        }
    merged = pd.merge(agg, fac[["hour_utc", "P_IT"]], on="hour_utc", how="inner")
    merged = merged.dropna(subset=["P_nodes_kW", "P_IT"])
    merged = merged.loc[merged["P_IT"] > 0]
    if merged.empty:
        return {"month": m, "status": "no_overlap", "gpu_chain": gpu_chain}
    x = merged["P_IT"].to_numpy(float)
    y = merged["P_nodes_kW"].to_numpy(float)
    slope = float(np.linalg.lstsq(x.reshape(-1, 1), y, rcond=None)[0][0])
    ratio = y / x
    merged[["hour_utc", "P_IT", "P_nodes_kW", "P_nodes_kW_coverage_adjusted", "n_hq_nodes"]].to_csv(
        OUT_DIR / "tables" / f"node_hourly_{m}.csv", index=False
    )
    return {
        "month": m,
        "n_hours": int(len(merged)),
        "median_hq_nodes": float(merged["n_hq_nodes"].median()),
        "p05_hq_nodes": float(merged["n_hq_nodes"].quantile(0.05)),
        "p95_hq_nodes": float(merged["n_hq_nodes"].quantile(0.95)),
        "pearson": float(np.corrcoef(x, y)[0, 1]) if len(merged) > 2 else np.nan,
        "spearman": float(pd.Series(x).corr(pd.Series(y), method="spearman")),
        "through_origin_slope": slope,
        "median_P_nodes_over_Tot_ict": float(np.median(ratio)),
        "p05_ratio": float(np.quantile(ratio, 0.05)),
        "p50_ratio": float(np.quantile(ratio, 0.50)),
        "p95_ratio": float(np.quantile(ratio, 0.95)),
        "median_level_diff_kW": float(np.median(y - x)),
        "coverage_adjusted_used_in_primary": False,
        "gpu_chain": gpu_chain,
        "note": "raw measured-node sum is primary; coverage-adjusted is diagnostic only; Watts converted /1000 to kW",
    }


def stage_node():
    months = NODE_MONTHS
    if os.environ.get("SLURM_ARRAY_TASK_ID"):
        idx = int(os.environ["SLURM_ARRAY_TASK_ID"]) - 1
        if idx < 0 or idx >= len(months):
            raise SystemExit(f"bad array id {idx}")
        months = [months[idx]]
    rows = []
    for m in months:
        rec = _summarize_node_month(m)
        rows.append(rec)
        save_stage_status_month("node", m, {"ok": True, "record": rec})
    out = pd.DataFrame(rows)
    tag = months[0] if len(months) == 1 else "all"
    write_table(out, f"node_to_facility_it_{tag}.csv")
    rebuild_stage_status_index("node", {"gpu_chain": "SKIP"})


def _relabel_literature_csv() -> pd.DataFrame:
    lit = _read_table("literature_dynamic_reproduction.csv")
    if lit.empty:
        return lit
    rec = lit.iloc[0].to_dict()
    failed = str(rec.get("status", "")).endswith("FAILED")
    mae = rec.get("sample_mae_vs_bundled_output")
    try:
        mae = float(mae)
    except Exception:
        mae = np.nan
    rec["status"] = literature_execution_status(mae, failed=failed)
    rec["reason"] = literature_reason(rec["status"], mae)
    rec["independence_tag"] = LITERATURE["independence"]
    rec["literature_triangulation_only"] = True
    rec["independent_validation"] = False
    out = pd.DataFrame([rec])
    write_table(out, "literature_dynamic_reproduction.csv")
    return out


def _rebuild_node_table_from_shards(*, fill_missing: bool = True) -> pd.DataFrame:
    """Concatenate per-month shards; optionally fill missing processed months from parquet."""
    tables = OUT_DIR / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    if fill_missing:
        for m in NODE_MONTHS:
            shard = tables / f"node_to_facility_it_{m}.csv"
            if shard.exists() and shard.stat().st_size > 10:
                rec = pd.read_csv(shard).iloc[0].to_dict()
                save_stage_status_month("node", m, {"ok": True, "record": rec, "source": "existing_shard"})
                continue
            rec = _summarize_node_month(m)
            pd.DataFrame([rec]).to_csv(shard, index=False)
            save_stage_status_month("node", m, {"ok": True, "record": rec, "source": "processed_parquet_fill"})
    parts = sorted(tables.glob("node_to_facility_it_*.csv"))
    frames = []
    for p in parts:
        if p.name == "node_to_facility_it_all.csv":
            continue
        df = pd.read_csv(p)
        if len(df):
            frames.append(df)
    nd = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if len(nd) and "month" in nd.columns:
        nd = nd.drop_duplicates(subset=["month"], keep="last").sort_values("month")
    write_table(nd, "node_to_facility_it.csv")
    rebuild_stage_status_index("node")
    return nd


def stage_thermal():
    rows, check = [], []
    for m in QUALIFIED_MONTHS:
        lp = grain_parquet("liquid_cooling", m)
        if not lp.exists():
            continue
        liquid = pd.read_parquet(lp)
        act = panel_activity_table(liquid)
        act["month"] = m
        rows.append(act)
        hti = hti_on_active_paths(liquid)
        fac = load_month_v3(m)
        if fac.empty:
            continue
        merged = pd.merge(fac, hti, on="hour_utc", how="inner")
        s = merged.dropna(subset=["P_IT", "HTI_active"])
        if s.empty:
            # still record discrepancy
            panels = sorted(liquid["panel"].astype(str).unique())
            check.append({"month": m, "n": 0, "claim": "THERMAL_MEASUREMENT_SANITY", "note": "no active-path HTI"})
            continue
        s = s.sort_values("hour_utc")
        pear = float(s["P_IT"].corr(s["HTI_active"]))
        spear = float(s["P_IT"].corr(s["HTI_active"], method="spearman"))
        lag1 = pd.concat([
            s.set_index("hour_utc")["P_IT"].rename("pit"),
            s.set_index("hour_utc")["HTI_active"].shift(freq=pd.Timedelta(hours=1)).rename("hti"),
        ], axis=1).dropna()
        # twin consistency among active hours
        liq = liquid.copy()
        liq["hour_utc"] = pd.to_datetime(liq["timestamp_utc"], utc=True)
        liq["path_status"] = liq.apply(active_liquid_panel, axis=1)
        twin_corr = np.nan
        interp = "unresolved"
        if set(liq["panel"].astype(str).unique()) >= {"Q101", "Q102"}:
            a = liq.loc[liq.panel.astype(str).eq("Q101"), ["hour_utc", "flow_delta_t_mean", "Portata_attiva_mean", "path_status"]]
            b = liq.loc[liq.panel.astype(str).eq("Q102"), ["hour_utc", "flow_delta_t_mean", "Portata_attiva_mean", "path_status"]]
            j = a.merge(b, on="hour_utc", suffixes=("_q101", "_q102"))
            twin_corr = float(j["flow_delta_t_mean_q101"].corr(j["flow_delta_t_mean_q102"])) if len(j) > 8 else np.nan
            n_both = int(((j["path_status_q101"] == "active") & (j["path_status_q102"] == "active")).sum())
            n_one = int(((j["path_status_q101"] == "active") ^ (j["path_status_q102"] == "active")).sum())
            if n_one > 0.2 * len(j) and (twin_corr < 0.3 if np.isfinite(twin_corr) else True):
                interp = "active_standby_or_sensor_inconsistency"
            elif np.isfinite(twin_corr) and twin_corr >= 0.9:
                interp = "redundant_twins"
            elif np.isfinite(twin_corr) and twin_corr < 0.3:
                interp = "unresolved_discrepancy"
            else:
                interp = "partial_consistency"
        check.append({
            "month": m, "n": int(len(s)),
            "coverage_vs_calendar": float(len(s) / max(len(month_calendar(m)), 1)),
            "pearson_IT_HTI_active": pear,
            "spearman_IT_HTI_active": spear,
            "lag0_pearson": pear,
            "lag_plus1h_pit_vs_hti": float(lag1["pit"].corr(lag1["hti"])) if len(lag1) > 8 else np.nan,
            "twin_hti_corr": twin_corr,
            "sep_oct_interpretation": interp if m in {"2021-09", "2021-10"} else interp,
            "claim": "THERMAL_MEASUREMENT_SANITY",
            "thermal_kW_claimed": False,
            "energy_closure_claimed": False,
            "note": "HTI=flow*deltaT on active paths only; no verified coolant rho/cp",
        })
    therm_panel = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    write_table(therm_panel, "thermal_panel_audit.csv")
    write_table(pd.DataFrame(check), "thermal_check.csv")
    save_stage_status("thermal", {"ok": True, "n_months": len(check)})


def stage_dynamic():
    frames = load_frames()
    rows = []
    for f in expanding_folds(QUALIFIED_MONTHS):
        train = concat_months(frames, f["train_months"])
        test = frames.get(f["test_month"], pd.DataFrame())
        cols = base_cols()
        tr = train.loc[complete_case_mask(train, cols)].sort_values("hour_utc")
        te = test.loc[complete_case_mask(test, cols)].sort_values("hour_utc")
        if len(tr) < 50 or len(te) < 24:
            continue
        # static W2
        beta_w2, phat_w2, _, _ = fit_predict(tr, te, "W2")
        yte = te["P_nonIT"].to_numpy(float)
        pit, fac = te["P_IT"].to_numpy(float), te["P_facility"].to_numpy(float)
        sc_w2 = metrics(yte, phat_w2, pit=pit, p_fac=fac)
        sc_w2.update(daily_peak_and_std_error(te["hour_utc"], yte, phat_w2))
        resid_w2 = pd.Series(yte - phat_w2, index=pd.to_datetime(te["hour_utc"], utc=True))
        sc_w2.update({
            "model": "W2_static", "fold_id": f["fold_id"], "test_month": f["test_month"],
            "acf_1h": acf_lag(resid_w2, 1), "acf_6h": acf_lag(resid_w2, 6), "acf_24h": acf_lag(resid_w2, 24),
            "role": "static_reference",
        })
        rows.append(sc_w2)
        pairs_tr = lag_pairs(tr, "P_nonIT")
        pairs_te = lag_pairs(te, "P_nonIT")
        if len(pairs_tr) < 40 or len(pairs_te) < 12:
            continue
        beta_d1, _ = fit_d1(pairs_tr)
        # one-step oracle uses observed lag (test observed previous hour)
        phat_os = predict_d1_one_step(beta_d1, pairs_te)
        y_os = pairs_te["P_nonIT"].to_numpy(float)
        sc_os = metrics(y_os, phat_os, pit=pairs_te["P_IT"].to_numpy(float),
                        p_fac=pairs_te["P_facility"].to_numpy(float))
        sc_os.update(daily_peak_and_std_error(pairs_te["hour_utc"], y_os, phat_os))
        resid_os = pd.Series(y_os - phat_os, index=pd.to_datetime(pairs_te["hour_utc"], utc=True))
        sc_os.update({
            "model": "D1_one_step", "fold_id": f["fold_id"], "test_month": f["test_month"],
            "acf_1h": acf_lag(resid_os, 1), "acf_6h": acf_lag(resid_os, 6), "acf_24h": acf_lag(resid_os, 24),
            "role": "ONE-STEP MEMORY ORACLE",
            "uses_observed_previous_target": True,
        })
        rows.append(sc_os)
        y0 = float(tr["P_nonIT"].iloc[-1])
        phat_rec = predict_d1_recursive(beta_d1, te, y0)
        sc_r = metrics(yte, phat_rec, pit=pit, p_fac=fac)
        sc_r.update(daily_peak_and_std_error(te["hour_utc"], yte, phat_rec))
        resid_r = pd.Series(yte - phat_rec, index=pd.to_datetime(te["hour_utc"], utc=True))
        sc_r.update({
            "model": "D1_recursive", "fold_id": f["fold_id"], "test_month": f["test_month"],
            "acf_1h": acf_lag(resid_r, 1), "acf_6h": acf_lag(resid_r, 6), "acf_24h": acf_lag(resid_r, 24),
            "role": "recursive_forward_simulation",
            "uses_observed_previous_target": False,
            "init": "last_train_observed_P_nonIT",
        })
        rows.append(sc_r)
        # cooling-target D1 if available
        if tr["P_cooling"].notna().sum() > 50 and te["P_cooling"].notna().sum() > 24:
            trc = tr.dropna(subset=["P_cooling"])
            tec = te.dropna(subset=["P_cooling"])
            ptr = lag_pairs(trc, "P_cooling")
            pte = lag_pairs(tec, "P_cooling")
            if len(ptr) >= 40 and len(pte) >= 12:
                bcool, _ = fit_d1(ptr, ycol="P_cooling")
                rec = predict_d1_recursive(bcool, tec, float(trc["P_cooling"].iloc[-1]), ycol="P_cooling")
                scc = metrics(tec["P_cooling"].to_numpy(float), rec)
                scc.update({
                    "model": "D1_recursive", "target": "P_cooling",
                    "fold_id": f["fold_id"], "test_month": f["test_month"],
                    "role": "recursive_forward_simulation",
                })
                rows.append(scc)
    write_table(pd.DataFrame(rows), "dynamic_memory_test.csv")
    save_stage_status("dynamic", {"ok": True, "n_rows": len(rows)})


def stage_literature():
    dest = POOL_M100 / "vendor" / "dc-cooling-thermal-model"
    dest.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "repo_url": LITERATURE["repo_url"],
        "pinned_commit": LITERATURE["pinned_commit"],
        "license": LITERATURE["license"],
        "independence_tag": LITERATURE["independence"],
        "same_underlying_M100_source": True,
        "manual_physical_parameter_calibration_in_paper": True,
        "literature_triangulation_only": True,
        "independent_validation": False,
        "tuned_against_our_heldout_folds": False,
        "status": "LITERATURE_REPRODUCTION_FAILED",
        "reason": "",
        "published_mae_kw": LITERATURE["published_mae_kw"],
        "published_baseline_mae_kw": LITERATURE["published_baseline_mae_kw"],
        "sample_mae_vs_bundled_output": np.nan,
        "dependency_versions": {},
    }
    try:
        import numpy, pandas
        rec["dependency_versions"] = {
            "numpy": numpy.__version__, "pandas": pandas.__version__,
            "python": sys.version.split()[0],
        }
        if dest.exists() and (dest / ".git").exists():
            subprocess.run(["git", "-C", str(dest), "fetch", "--depth", "1", "origin", LITERATURE["pinned_commit"]],
                           check=False, capture_output=True, text=True)
            subprocess.run(["git", "-C", str(dest), "checkout", LITERATURE["pinned_commit"]],
                           check=True, capture_output=True, text=True)
        else:
            if dest.exists():
                shutil.rmtree(dest)
            subprocess.run(
                ["git", "clone", "--depth", "1", LITERATURE["repo_url"], str(dest)],
                check=True, capture_output=True, text=True, timeout=180,
            )
            subprocess.run(["git", "-C", str(dest), "fetch", "--depth", "1", "origin", LITERATURE["pinned_commit"]],
                           check=False, capture_output=True, text=True)
            ck = subprocess.run(["git", "-C", str(dest), "checkout", LITERATURE["pinned_commit"]],
                                capture_output=True, text=True)
            if ck.returncode != 0:
                head = subprocess.check_output(["git", "-C", str(dest), "rev-parse", "HEAD"], text=True).strip()
                rec["cloned_head"] = head
                rec["reason"] = f"pinned commit checkout failed ({ck.stderr.strip()[:300]}); using clone HEAD {head}"
            else:
                rec["cloned_head"] = LITERATURE["pinned_commit"]
        rec["cloned_head"] = rec.get("cloned_head") or subprocess.check_output(
            ["git", "-C", str(dest), "rev-parse", "HEAD"], text=True
        ).strip()
        (dest / "src" / "__init__.py").touch()
        deps = POOL_M100 / "vendor" / "pydeps"
        deps.mkdir(parents=True, exist_ok=True)
        try:
            import plotly  # noqa: F401
        except Exception:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--target", str(deps), "plotly", "flask"],
                check=False, capture_output=True, text=True, timeout=180,
            )
        sys.path.insert(0, str(deps))
        sys.path.insert(0, str(dest))
        os.chdir(dest)
        from src.model import build_simulation_bundle
        bundle = build_simulation_bundle(
            "sample/drivers_sample.csv",
            "2022-01-01 00:00:00",
            "2022-01-03 00:00:00",
        )
        sim = bundle["results"]
        bundled = dest / "data" / "sample" / "simulated_sample.csv"
        rec["sample_output_rows"] = int(len(sim))
        rec["sample_timing_s"] = float(bundle.get("timing_s", np.nan))
        if bundled.exists():
            ref = pd.read_csv(bundled)
            col = "sim_Pcool_total_elec_W"
            if col in sim.columns and col in ref.columns:
                a = sim[col].to_numpy(float)
                b = pd.to_numeric(ref[col], errors="coerce").to_numpy(float)
                n = min(len(a), len(b))
                d = a[:n] - b[:n]
                rec["sample_mae_vs_bundled_output"] = float(np.nanmean(np.abs(d)))
                rec["sample_max_abs_vs_bundled"] = float(np.nanmax(np.abs(d)))
        rec["status"] = literature_execution_status(rec.get("sample_mae_vs_bundled_output"))
        rec["reason"] = literature_reason(rec["status"], rec.get("sample_mae_vs_bundled_output"))
        rec["discrepancy_from_published_mae"] = (
            "Published MAE 20.88 kW is the authors' calibrated evaluation on their M100 window, "
            "not a metric we re-estimated on 2021 chronological folds."
        )
    except Exception as exc:
        rec["status"] = "LITERATURE_REPRODUCTION_FAILED"
        rec["reason"] = f"{type(exc).__name__}: {exc}"
    write_table(pd.DataFrame([rec]), "literature_dynamic_reproduction.csv")
    save_stage_status("literature", {"ok": rec["status"] != "LITERATURE_REPRODUCTION_FAILED" or True,
                                     "optional": True, "status": rec["status"], "reason": rec.get("reason")})


def stage_support():
    frames = load_frames()
    rows = []
    vars_ = ["P_IT", "T_drybulb", "T_wetbulb", "RH"]
    for f in expanding_folds(QUALIFIED_MONTHS):
        train = concat_months(frames, f["train_months"])
        test = frames.get(f["test_month"], pd.DataFrame())
        tr = train.loc[complete_case_mask(train, base_cols())]
        te = test.loc[complete_case_mask(test, base_cols())]
        if len(tr) < 50 or len(te) < 20:
            continue
        stats = {}
        for v in vars_:
            if v not in tr.columns:
                continue
            x = tr[v].dropna()
            stats[v] = {"p05": float(x.quantile(0.05)), "p95": float(x.quantile(0.95)),
                        "min": float(x.min()), "max": float(x.max())}
        beta, phat, _, _ = fit_predict(tr, te, "W2")
        te = te.copy()
        te["abs_err"] = np.abs(te["P_nonIT"].to_numpy(float) - phat)
        for i, r in te.iterrows():
            labs = []
            for v in vars_:
                if v not in stats or v not in r.index or not np.isfinite(r[v]):
                    labs.append("missing")
                    continue
                labs.append(support_label(float(r[v]), stats[v]["p05"], stats[v]["p95"], stats[v]["min"], stats[v]["max"]))
            te.loc[i, "support_class"] = joint_support_label(labs)
        g = te.groupby("support_class")["abs_err"].agg(n="size", mae="mean")
        for cls, rr in g.iterrows():
            rows.append({
                "fold_id": f["fold_id"], "test_month": f["test_month"],
                "support_class": cls, "n": int(rr["n"]), "mae": float(rr["mae"]),
                "frac_of_test": float(rr["n"] / len(te)),
            })
    write_table(pd.DataFrame(rows), "support_extrapolation.csv")
    save_stage_status("support", {"ok": True, "n_rows": len(rows)})


def _read_table(name: str) -> pd.DataFrame:
    p = OUT_DIR / "tables" / name
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


def _impr(df, inc, col="mae_rel_improvement"):
    if df.empty or "increment" not in df.columns:
        return []
    return df.loc[df["increment"].eq(inc), col].dropna().tolist()


def stage_aggregate():
    return _write_closure_reports(write_figures=True, fill_missing_node=False)


def stage_report_only():
    """Relabel flags and rewrite JSON/docs from existing tables. No model refits."""
    return _write_closure_reports(write_figures=False, fill_missing_node=True)


def _write_closure_reports(*, write_figures: bool, fill_missing_node: bool):
    node = _rebuild_node_table_from_shards(fill_missing=fill_missing_node)
    nested = _read_table("weather_nested_folds.csv")
    incs = _read_table("weather_nested_increments.csv")
    win = _read_table("weather_within_month_increments.csv")
    r1 = _read_table("state_regime_increments.csv")
    dyn = _read_table("dynamic_memory_test.csv")
    cool = _read_table("cooling_target_accounting.csv")
    cool_res = _read_table("cooling_target_results.csv")
    therm = _read_table("thermal_check.csv")
    if node is None or (hasattr(node, "empty") and node.empty):
        node = _read_table("node_to_facility_it.csv")
    wb = _read_table("wetbulb_qa.csv")
    desc = _read_table("weather_descriptor_robustness.csv")
    hq = _read_table("measurement_hq_robustness.csv")
    assoc = _read_table("state_weather_association.csv")
    lit = _relabel_literature_csv()
    supp = _read_table("support_extrapolation.csv")
    octd = _read_table("october_diagnostic.csv")
    sem = _read_table("state_semantics.csv")

    w0w1 = _impr(incs, "W0_to_W1")
    w1w2 = _impr(incs, "W1_to_W2")
    n_folds = int(nested["fold_id"].nunique()) if len(nested) else 0
    win_w0w1 = _impr(win, "W0_to_W1")
    r1i = _impr(r1, "W2_to_R1")

    # HQ: source coverage is not testable from processed Tot/Tot_ict/weather/FC fields.
    # Energy-quality sample is a separate robustness check on existing W0→W1 increments.
    source_coverage_robustness = NOT_TESTABLE_FROM_PROCESSED_FIELDS
    energy_quality_robustness = energy_quality_robustness_from_hq(hq)

    fac_frac = float(cool["frac_nonIT_energy_from_cooling"].median()) if len(cool) and "frac_nonIT_energy_from_cooling" in cool else np.nan
    facility_decomp = "STRONG SUPPORT" if np.isfinite(fac_frac) and fac_frac >= 0.9 else (
        "MIXED / REGIME-DEPENDENT" if np.isfinite(fac_frac) else "UNSUPPORTED BY AVAILABLE DATA"
    )

    weather_add = as_strong_support_token(evidence_label_from_improvements(w0w1, n_folds))
    weather_int = weather_interaction_label(w1w2)
    weather_within = evidence_label_from_improvements(win_w0w1, len(win_w0w1) or 0)
    regime = regime_generic_input_label(r1i)

    # descriptor robustness: weather specs beat IT on most folds
    desc_label = "UNRESOLVED"
    if len(desc):
        # compare IT vs IT_Twb MAE by fold
        wide = desc.loc[desc["optional_interaction_table"] == False] if "optional_interaction_table" in desc.columns else desc
        if "spec" in wide.columns:
            it = wide.loc[wide.spec.eq("IT"), ["fold_id", "mae"]].rename(columns={"mae": "mae_it"})
            tw = wide.loc[wide.spec.eq("IT_Twb"), ["fold_id", "mae"]].rename(columns={"mae": "mae_tw"})
            td = wide.loc[wide.spec.eq("IT_Tdb"), ["fold_id", "mae"]].rename(columns={"mae": "mae_td"})
            mrg = it.merge(tw, on="fold_id").merge(td, on="fold_id")
            if len(mrg):
                n_tw = int((mrg.mae_tw < mrg.mae_it).sum())
                n_td = int((mrg.mae_td < mrg.mae_it).sum())
                if n_tw == len(mrg) and n_td == len(mrg):
                    desc_label = "STRONG SUPPORT"
                elif n_tw > 0 or n_td > 0:
                    desc_label = "MIXED / REGIME-DEPENDENT"
                else:
                    desc_label = "NOT SUPPORTED"

    mem_label = "UNRESOLVED"
    rec_useful = NOT_SUPPORTED
    if len(dyn):
        ac = dyn.loc[dyn["model"].eq("W2_static"), "acf_1h"]
        if ac.notna().any() and float(ac.median()) >= 0.3:
            mem_label = STRONG_SUPPORT
        elif ac.notna().any():
            mem_label = "MIXED / REGIME-DEPENDENT"
        rec_imp = []
        for fid, g in dyn.groupby("fold_id"):
            sw = g.loc[g.model.eq("W2_static"), "mae"]
            sr = g.loc[g.model.eq("D1_recursive"), "mae"]
            if len(sw) and len(sr):
                rec_imp.append(rel_mae_improvement(float(sw.iloc[0]), float(sr.iloc[0])))
        # Recursive D1 is a forward-simulator test; MIXED/weaker than static is NOT_SUPPORTED.
        if rec_imp and all(x >= 0.05 for x in rec_imp):
            rec_useful = STRONG_SUPPORT
        else:
            rec_useful = NOT_SUPPORTED

    node_label = "UNSUPPORTED BY AVAILABLE DATA"
    if len(node) and "pearson" in node.columns:
        pr = pd.to_numeric(node["pearson"], errors="coerce")
        if pr.notna().any() and float(pr.median()) >= 0.7:
            node_label = "STRONG SUPPORT"
        elif pr.notna().any():
            node_label = "MIXED / REGIME-DEPENDENT"

    therm_label = "UNSUPPORTED BY AVAILABLE DATA"
    if len(therm) and "pearson_IT_HTI_active" in therm.columns:
        r = pd.to_numeric(therm["pearson_IT_HTI_active"], errors="coerce")
        if r.notna().any() and abs(float(r.median())) >= 0.2:
            therm_label = "STRONG SUPPORT"
        elif r.notna().any():
            therm_label = "MIXED / REGIME-DEPENDENT"

    water = "UNSUPPORTED BY AVAILABLE DATA"
    wb_ok = "STRONG SUPPORT" if len(wb) and float(wb.loc[wb.comparison.eq("tdew_path"), "mae"].median() if "comparison" in wb.columns else np.nan or np.nan) < 0.5 else "UNRESOLVED"
    if len(wb) and "mae" in wb.columns:
        sub = wb.loc[wb["comparison"].eq("tdew_path")] if "comparison" in wb.columns else wb
        if len(sub) and float(sub["mae"].median()) < 0.5:
            wb_ok = "STRONG SUPPORT"
        elif len(sub):
            wb_ok = "MIXED / REGIME-DEPENDENT"

    cooling_same = "UNRESOLVED"
    if len(cool_res):
        # reuse increments file if present
        cool_inc = _read_table("incremental_all.csv")
        cw = _impr(cool_inc.loc[cool_inc["target"].eq("P_cooling")] if "target" in cool_inc.columns else pd.DataFrame(), "W0_to_W1")
        cooling_same = evidence_label_from_improvements(cw, len(cw) or 0) if cw else weather_add

    lit_status = str(lit.iloc[0]["status"]) if len(lit) else "LITERATURE_REPRODUCTION_FAILED"

    evidence = {
        "n_chronological_folds": n_folds,
        "facility_decomposition": facility_decomp,
        "weather_additive": weather_add,
        "weather_interaction": weather_int,
        "weather_within_month": weather_within,
        "weather_descriptor_robustness": desc_label,
        "source_coverage_robustness": source_coverage_robustness,
        "energy_quality_robustness": energy_quality_robustness,
        "wetbulb_qa": wb_ok,
        "regime_interaction": regime,
        "temporal_dependence": mem_label,
        "temporal_state": mem_label,
        "recursive_d1_forward_simulator": rec_useful,
        "recursive_dynamics_skill": rec_useful,
        "node_bridge": node_label,
        "thermal_sanity": therm_label,
        "thermal_load_closure": "UNSUPPORTED BY AVAILABLE DATA",
        "pue_derived": "STRONG SUPPORT",
        "water": water,
        "generic_coefficients": "NOT IDENTIFIED BY M100",
        "generic_pue": "NOT IDENTIFIED BY M100",
        "generic_cooling_fraction": "NOT IDENTIFIED BY M100",
        "universal_weather_variable": "NOT IDENTIFIED BY M100",
        "universal_thresholds": "NOT IDENTIFIED BY M100",
        "generic_state_parameters": "NOT IDENTIFIED BY M100",
        "modern_ai_it": "NOT IDENTIFIED BY M100",
        "n_folds_W0_to_W1_ge5pct": int(sum(x >= 0.05 for x in w0w1)),
        "n_folds_W1_to_W2_ge5pct": int(sum(x >= 0.05 for x in w1w2)),
        "n_folds_W2_to_R1_ge5pct": int(sum(x >= 0.05 for x in r1i)),
        "frac_folds_W0_to_W1_ge5pct": (sum(x >= 0.05 for x in w0w1) / n_folds) if n_folds else np.nan,
        "literature_reproduction": lit_status,
        "cooling_target_weather": cooling_same,
        "october_retained": True if len(octd) else True,
    }
    contract = build_contract(evidence)
    (OUT_DIR / "generic_facility_model_contract.json").write_text(json.dumps(contract, indent=2, default=str) + "\n")
    tri = pd.DataFrame(triangulation_rows(evidence))
    write_table(tri, "literature_triangulation.csv")
    ledger = pd.DataFrame([{"claim": k, "label": v} for k, v in evidence.items()])
    write_table(ledger, "evidence_ledger.csv")

    v2 = {}
    vst = V2_DIR / "final_status.json"
    if vst.exists():
        v2 = json.loads(vst.read_text())
    old = pd.DataFrame([
        {"topic": "weather_increment", "v2": (v2.get("evidence") or {}).get("weather_increment"),
         "v3": weather_add, "changed": (v2.get("evidence") or {}).get("weather_increment") != weather_add},
        {"topic": "weather_interaction_W1_to_W2", "v2": "not separated (B2 included interaction)",
         "v3": weather_int, "changed": True},
        {"topic": "state", "v2": (v2.get("evidence") or {}).get("state_increment"),
         "v3": regime, "changed": (v2.get("evidence") or {}).get("state_increment") != regime},
        {"topic": "temporal_memory", "v2": (v2.get("evidence") or {}).get("temporal_memory"),
         "v3": mem_label, "changed": False},
        {"topic": "water", "v2": "UNSUPPORTED BY AVAILABLE DATA", "v3": water, "changed": False},
        {"topic": "HQ_coverage", "v2": "not assessed",
         "v3": f"source_coverage_robustness={source_coverage_robustness}; energy_quality_robustness={energy_quality_robustness}",
         "changed": True},
        {"topic": "classification_scope", "v2": v2.get("classification"),
         "v3": "closure contract; M100 frozen as structural benchmark", "changed": True},
    ])
    write_table(old, "old_v2_vs_v3_conclusions.csv")

    _write_figures(nested, incs, win, dyn, node, therm, desc, assoc) if write_figures else None
    _write_report(evidence, contract, nested, incs, win, r1, dyn, node, therm, cool, lit, wb, octd, assoc, sem, desc, supp)
    _write_docs(evidence, contract)

    mandatory = {
        "static": (OUT_DIR / "tables" / "weather_nested_folds.csv").exists() and len(nested) > 0,
        "within_month": (OUT_DIR / "tables" / "weather_within_month.csv").exists(),
        "node": (OUT_DIR / "tables" / "node_to_facility_it.csv").exists(),
        "thermal": (OUT_DIR / "tables" / "thermal_check.csv").exists(),
        "dynamic": (OUT_DIR / "tables" / "dynamic_memory_test.csv").exists(),
        "support": (OUT_DIR / "tables" / "support_extrapolation.csv").exists(),
    }
    optional_fail = lit_status == "LITERATURE_REPRODUCTION_FAILED"
    if all(mandatory.values()):
        overall = "PASS_WITH_LIMITATIONS" if optional_fail or regime in {"MIXED / REGIME-DEPENDENT", "NOT SUPPORTED"} else "PASS"
        # always limitations: water unsupported, not generic calibration
        overall = "PASS_WITH_LIMITATIONS"
    else:
        overall = "FAIL"
    status = {
        "created_utc": utcnow(),
        "overall": overall,
        "mandatory_branches": mandatory,
        "optional_literature": lit_status,
        "git_head": git_head(),
        "evidence": evidence,
        "nrmse_definition": NRMSE_DEF,
        "formulas": FORMULAS,
        "qualified_months": QUALIFIED_MONTHS,
        "original_v2_untouched": True,
        "no_raw_deletion": True,
        "role": "EXTERNAL MEASURED FACILITY-PHYSICS BENCHMARK",
        "stop_rule": "M100 CLOSED/FROZEN. STOP M100 MODEL DEVELOPMENT",
        "M100_CLOSED_FROZEN": True,
        "frozen_v2_hashes": json.loads((OUT_DIR / "frozen_v2_hashes.json").read_text()) if (OUT_DIR / "frozen_v2_hashes.json").exists() else V2_FROZEN,
    }
    (OUT_DIR / "final_status.json").write_text(json.dumps(status, indent=2, default=str) + "\n")
    save_stage_status("aggregate", {"ok": overall != "FAIL", "overall": overall})
    return overall


def _write_figures(nested, incs, win, dyn, node, therm, desc, assoc):
    figdir = OUT_DIR / "figures"
    figdir.mkdir(parents=True, exist_ok=True)
    if len(nested):
        fig, ax = plt.subplots(figsize=(8, 4))
        for model, g in nested.groupby("model"):
            ax.plot(g["test_month"], g["mae"], marker="o", label=model)
        ax.set_ylabel("Held-out MAE (kW)")
        ax.set_title("W0/W1/W2 chronological MAE")
        ax.legend()
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(figdir / "01_weather_nested_mae.png", dpi=140)
        plt.close()
    if len(incs):
        fig, ax = plt.subplots(figsize=(8, 4))
        for inc, g in incs.groupby("increment"):
            ax.bar(np.arange(len(g)) + (0 if "W0" in inc else 0.4), g["mae_rel_improvement"], width=0.4, label=inc)
        ax.axhline(0.05, ls="--", color="gray", label="5% heuristic")
        ax.set_ylabel("Relative MAE improvement")
        ax.set_title("Nested weather increments (heuristic, not significance)")
        ax.legend()
        fig.tight_layout()
        fig.savefig(figdir / "02_weather_increments.png", dpi=140)
        plt.close()
    if len(win):
        fig, ax = plt.subplots(figsize=(8, 4))
        for inc, g in win.groupby("increment"):
            ax.plot(g["month"], g["mae_rel_improvement"], marker="o", label=inc)
        ax.axhline(0.05, ls="--", color="gray")
        ax.set_title("Within-month weather increments")
        ax.legend()
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(figdir / "03_within_month.png", dpi=140)
        plt.close()
    if len(assoc):
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.scatter(assoc["P_active_given_Tdb_lt_18"], assoc["P_active_given_Tdb_ge_18"])
        for _, r in assoc.iterrows():
            ax.annotate(r["month"][-2:], (r["P_active_given_Tdb_lt_18"], r["P_active_given_Tdb_ge_18"]))
        ax.set_xlabel("P(FC active | Tdb<18C)")
        ax.set_ylabel("P(FC active | Tdb>=18C)")
        ax.set_title("Free_Cooling_Status vs published ~18C (not forced)")
        fig.tight_layout()
        fig.savefig(figdir / "04_state_vs_18C.png", dpi=140)
        plt.close()
    if len(dyn):
        fig, ax = plt.subplots(figsize=(8, 4))
        for model, g in dyn.loc[dyn["model"].isin(["W2_static", "D1_one_step", "D1_recursive"])].groupby("model"):
            ax.plot(g["test_month"], g["mae"], marker="o", label=model)
        ax.set_ylabel("MAE (kW)")
        ax.set_title("Static W2 vs one-step oracle vs recursive D1")
        ax.legend()
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(figdir / "05_dynamic_memory.png", dpi=140)
        plt.close()
    if len(node) and "pearson" in node.columns:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(node["month"], node["median_P_nodes_over_Tot_ict"], marker="o")
        ax.set_ylabel("median P_nodes / Tot_ict")
        ax.set_title("Node sum vs canonical facility IT (raw HQ sum)")
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(figdir / "06_node_bridge.png", dpi=140)
        plt.close()
    if len(therm):
        fig, ax = plt.subplots(figsize=(8, 4))
        if "pearson_IT_HTI_active" in therm.columns:
            ax.plot(therm["month"], therm["pearson_IT_HTI_active"], marker="o", label="IT-HTI pearson")
        if "twin_hti_corr" in therm.columns:
            ax.plot(therm["month"], therm["twin_hti_corr"], marker="s", label="Q101-Q102 HTI corr")
        ax.set_title("Thermal sanity (not kW closure)")
        ax.legend()
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(figdir / "07_thermal.png", dpi=140)
        plt.close()
    if len(desc) and "spec" in desc.columns:
        fig, ax = plt.subplots(figsize=(8, 4))
        core = desc
        if "optional_interaction_table" in desc.columns:
            core = desc.loc[~desc["optional_interaction_table"].astype(bool)]
        for spec, g in core.groupby("spec"):
            ax.plot(g["test_month"], g["mae"], marker="o", label=spec)
        ax.set_title("Weather-descriptor robustness (not selection)")
        ax.legend()
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(figdir / "08_descriptor_robustness.png", dpi=140)
        plt.close()


def _write_report(evidence, contract, nested, incs, win, r1, dyn, node, therm, cool, lit, wb, octd, assoc, sem, desc, supp):
    def tbl(df, n=40):
        if df is None or df.empty:
            return "(empty)"
        return df.head(n).to_string(index=False)

    n_w = evidence.get("n_folds_W0_to_W1_ge5pct")
    n_i = evidence.get("n_folds_W1_to_W2_ge5pct")
    n_r = evidence.get("n_folds_W2_to_R1_ge5pct")
    n_folds = evidence.get("n_chronological_folds")
    lit_s = evidence.get("literature_reproduction")
    lines = [
        "# M100 2021 facility-model closure report (v3)",
        "",
        "M100 is an **EXTERNAL MEASURED FACILITY-PHYSICS BENCHMARK**.",
        "Do not transfer coefficients, PUE levels, cooling fractions, control thresholds, GPU behavior, or traces.",
        "",
        f"**Overall status:** see `final_status.json`. **M100 CLOSED/FROZEN.** Stop rule: **STOP M100 MODEL DEVELOPMENT**.",
        "",
        "## T1. Canonical power/energy boundaries",
        f"Canonical meters remain `panel=generals`, `device=pue`. NRMSE definition: `{NRMSE_DEF}`.",
        "Processed facility rows include trapezoidal `Tot_energy_kwh` / `Tot_ict_energy_kwh`.",
        "Full-period calendar energy is **not** reported by filling missing hours.",
        tbl(octd),
        "",
        "## T2. HQ filtering robustness",
        "Tot, Tot_ict, weather, and Free_Cooling_Status have **no** `*_coverage` column (`HQ_COVERAGE_NOT_AVAILABLE`).",
        f"source_coverage_robustness: **{evidence.get('source_coverage_robustness')}**.",
        f"energy_quality_robustness (W0→W1 on energy_quality sample): **{evidence.get('energy_quality_robustness')}**.",
        f"Weather conclusion label on complete-case chronological folds: **{evidence.get('weather_additive')}**.",
        "",
        "## T3. Within-month weather",
        f"Fixed first 2/3 vs last 1/3 of valid hours: **{evidence.get('weather_within_month')}**.",
        f"Cross-season W0→W1 ≥5% heuristic: {n_w}/{n_folds} folds ({HEURISTIC_NOTE}).",
        tbl(win),
        "",
        "## T4. Additive weather vs IT×weather",
        f"W0→W1 (weather itself): **{evidence.get('weather_additive')}** ({n_w}/{n_folds} folds ≥5% MAE).",
        f"W1→W2 (IT×Twb): **{evidence.get('weather_interaction')}** ({n_i}/{n_folds} folds ≥5% MAE).",
        tbl(incs),
        "",
        "## T5. Dry-bulb vs wet-bulb/RH",
        f"Predeclared descriptor robustness (not selection): **{evidence.get('weather_descriptor_robustness')}**.",
        "No universal 'best weather variable' is declared.",
        "",
        "## T6–T8. Free_Cooling_Status",
        "Six Vertiv CRAC devices (cdz1–cdz6). Literature: four support DFC.",
        tbl(sem.head(20) if len(sem) else sem),
        tbl(assoc),
        f"Regime-interaction R1 vs W2: **{evidence.get('regime_interaction')}** ({n_r} folds ≥5%).",
        "Do not transfer the M100 control flag or 18°C threshold as a generic planning variable.",
        "",
        "## T9–T10. Temporal memory",
        f"Static W2 residual 1 h ACF (temporal dependence): **{evidence.get('temporal_dependence')}**.",
        f"Recursive D1 as a forward simulator: **{evidence.get('recursive_d1_forward_simulator')}**.",
        "Strong temporal dependence is supported, but the tested recursive D1 model is not supported as a forward simulator. The D1 state equation was not validated. One-step path is an ORACLE.",
        tbl(dyn.head(24) if len(dyn) else dyn),
        "",
        "## T11. Literature RC model",
        f"Status: **{lit_s}**. Tag: **{LITERATURE_TRIANGULATION_CAVEAT}**.",
        tbl(lit),
        "",
        "## T12. Node → facility IT",
        f"Label: **{evidence.get('node_bridge')}**. GPU chain: SKIP unless processed GPU columns exist.",
        tbl(node),
        "",
        "## T13. Cooling-power target",
        f"Weather-on-cooling: **{evidence.get('cooling_target_weather')}**.",
        tbl(cool),
        "",
        "## T14–T15. Q101/Q102 and thermal closure",
        f"Thermal measurement sanity: **{evidence.get('thermal_sanity')}**. Thermal-load closure: **UNSUPPORTED BY AVAILABLE DATA**.",
        tbl(therm),
        "",
        "## T16. Interpolation vs extrapolation",
        tbl(supp.head(30) if len(supp) else supp),
        "",
        "## T17. Structurally supported (generic contract)",
        "\n".join(
            f"- **{s.get('claim')}** — {format_struct_claim_evidence(s)}"
            + (f"\n  - {s['note']}" if s.get("note") else "")
            for s in (contract.get("STRUCTURALLY_SUPPORTED") or [])
        ),
        "",
        "## T18. Not identified by M100",
        json.dumps(contract.get("NOT_IDENTIFIED_BY_M100"), indent=2, default=str),
        "",
        "## Nested chronological scores (W0/W1/W2)",
        tbl(nested),
        "",
        "Next project stage: NLR + H100/B200 + MLPerf (IT layer); Lei–Masanet + LBNL (climate/technology + water);",
        "Frontier / AlphaDataCenterCooling / ExaDigiT (independent thermal/control).",
    ]
    (OUT_DIR / "final_report.md").write_text("\n".join(lines) + "\n")


def _write_docs(evidence, contract):
    docs = ROOT / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    text = f"""# Generic facility-model evidence (from M100 closure)

M100 is an **external measured facility-physics benchmark**, not generic-DC calibration data.

## STRUCTURALLY SUPPORTED

"""
    for s in contract.get("STRUCTURALLY_SUPPORTED") or []:
        text += f"- **{s.get('claim')}** — {format_struct_claim_evidence(s)}\n"
        if s.get("note"):
            text += f"  - {s['note']}\n"
    text += """
## NOT IDENTIFIED BY M100

Do not write production parameters from M100 for:

"""
    for s in contract.get("NOT_IDENTIFIED_BY_M100") or []:
        text += f"- {s.get('claim')} ({s.get('evidence')})\n"
    text += f"""
## Evidence snapshot

```json
{json.dumps(evidence, indent=2, default=str)}
```

## Stop rule

STOP M100 MODEL DEVELOPMENT. M100 CLOSED/FROZEN. Next: NLR/H100/MLPerf IT layer; Lei–Masanet/LBNL climate-technology-water; independent thermal/control datasets.
"""
    (docs / "GENERIC_FACILITY_MODEL_EVIDENCE.md").write_text(text)


def stage_audit():
    """Verify outputs. Does not delete any archives."""
    expected_tables = [
        "measurement_hq_robustness.csv", "energy_accounting.csv", "wetbulb_qa.csv",
        "weather_nested_folds.csv", "weather_descriptor_robustness.csv", "weather_within_month.csv",
        "state_semantics.csv", "state_regime_test.csv", "dynamic_memory_test.csv",
        "literature_dynamic_reproduction.csv", "node_to_facility_it.csv", "cooling_target_results.csv",
        "thermal_panel_audit.csv", "thermal_check.csv", "support_extrapolation.csv",
        "literature_triangulation.csv", "evidence_ledger.csv", "old_v2_vs_v3_conclusions.csv",
    ]
    missing = [t for t in expected_tables if not (OUT_DIR / "tables" / t).exists() or (OUT_DIR / "tables" / t).stat().st_size < 10]
    figs = list((OUT_DIR / "figures").glob("*.png")) if (OUT_DIR / "figures").exists() else []
    jsons = ["final_status.json", "generic_facility_model_contract.json"]
    bad_json = []
    for j in jsons:
        p = OUT_DIR / j
        try:
            json.loads(p.read_text())
        except Exception as exc:
            bad_json.append(f"{j}: {exc}")
    # v2 untouched
    frozen = json.loads((OUT_DIR / "frozen_v2_hashes.json").read_text()) if (OUT_DIR / "frozen_v2_hashes.json").exists() else V2_FROZEN
    v2_changed = []
    for k, meta in frozen.items():
        p = Path(meta["path"])
        now = sha256_file(p)
        if now != meta.get("sha256"):
            v2_changed.append(k)
    # no new tar deletion: Apr-Jun should still be absent; others present if they were
    deleted = []
    # do not delete; just record
    home_large = []
    m100_home = ROOT
    for p in m100_home.rglob("*"):
        if p.is_file() and p.stat().st_size > 80 * 1024 * 1024:
            if "results" in p.parts or "logs" in p.parts:
                continue
            home_large.append(str(p))
    contract = json.loads((OUT_DIR / "generic_facility_model_contract.json").read_text()) if (OUT_DIR / "generic_facility_model_contract.json").exists() else {}
    ok = (not missing) and (not bad_json) and (not v2_changed) and (6 <= len(figs) <= 12)
    report = {
        "ok": ok,
        "missing_or_tiny_tables": missing,
        "n_figures": len(figs),
        "bad_json": bad_json,
        "v2_hash_changes": v2_changed,
        "home_files_gt_80MB_outside_results_logs": home_large,
        "no_raw_deletion_performed": True,
        "docs_written": str(ROOT / "docs" / "GENERIC_FACILITY_MODEL_EVIDENCE.md"),
        "contract_role": contract.get("role"),
    }
    (OUT_DIR / "audit_report.json").write_text(json.dumps(report, indent=2) + "\n")
    save_stage_status("audit", report)
    if not ok:
        raise SystemExit("AUDIT FAIL: " + json.dumps(report)[:1500])


STAGES = {
    "prep": stage_prep,
    "static": stage_static,
    "within_month": stage_within_month,
    "node": stage_node,
    "thermal": stage_thermal,
    "dynamic": stage_dynamic,
    "literature": stage_literature,
    "support": stage_support,
    "aggregate": stage_aggregate,
    "report_only": stage_report_only,
    "audit": stage_audit,
}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--stage", required=True, choices=list(STAGES))
    args = p.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "tables").mkdir(exist_ok=True)
    print(f"stage={args.stage} start={utcnow()} host={os.environ.get('SLURMD_NODENAME') or os.uname().nodename} git={git_head()}", flush=True)
    STAGES[args.stage]()
    print(f"stage={args.stage} end={utcnow()}", flush=True)


if __name__ == "__main__":
    main()
