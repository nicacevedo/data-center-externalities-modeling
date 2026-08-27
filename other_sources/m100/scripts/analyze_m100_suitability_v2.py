#!/usr/bin/env python3
"""Full-year M100 facility-model assessment v2.

Reads processed hourly Parquet only. Writes exclusively to results/suitability_2021_v2/.
Does not overwrite the original pilot or suitability_2021 outputs.
Does not redownload, re-extract, or delete archives.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from m100_2021_common import EXPECTED_MONTHS, ROOT, grain_parquet, load_status
from m100_suitability_v2 import (
    B3_FORBIDDEN,
    FORMULAS,
    ORIGINAL_DAG_SCRIPTS,
    ORIGINAL_PILOT,
    ORIGINAL_SUITABILITY,
    OUT_DIR,
    STATE_CONCEPT,
    STATE_ROLE,
    acf_lag,
    base_mask,
    build_evidence,
    choose_weather_formulation,
    classify_benchmark,
    design_matrix,
    expanding_folds,
    fit_models,
    git_provenance,
    load_metric_inventory,
    load_month_hourly,
    marginal_effects_b2,
    metrics,
    ols_fit,
    ols_pred,
    rel_mae_improvement,
    repair_month_certification,
    sha256_file,
    state_mask,
    water_audit,
)
from qualify_m100_2021 import qualify as qualify_inventory


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_csv(df: pd.DataFrame, name: str) -> Path:
    path = OUT_DIR / "tables" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path


def original_artifact_hashes() -> dict:
    paths = {
        "pilot_status": ORIGINAL_PILOT / "pilot_status.json",
        "pilot_report": ORIGINAL_PILOT / "pilot_report.md",
        "old_run_manifest": ORIGINAL_SUITABILITY / "run_manifest.json",
        "old_model_validation": ORIGINAL_SUITABILITY / "tables" / "model_validation_by_month.csv",
        "old_model_comparison": ORIGINAL_SUITABILITY / "tables" / "model_comparison.csv",
        "old_month_qualification": ORIGINAL_SUITABILITY / "tables" / "month_qualification.csv",
        "old_measurement_boundaries": ORIGINAL_SUITABILITY / "tables" / "measurement_boundaries.csv",
        "old_electrical_closure": ORIGINAL_SUITABILITY / "tables" / "electrical_closure.csv",
    }
    return {k: {"path": str(p), "sha256": sha256_file(p), "mtime_utc": (
        datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if p.exists() else None
    )} for k, p in paths.items()}


def load_original_conclusions() -> dict:
    """Claims actually present in the frozen original artifacts (not v2)."""
    claims = {
        "original_facility_months": None,
        "original_classification_rule": "classification = 'B' if months else 'C' (hard-coded in analyze_m100_suitability.py)",
        "original_B0_definition": "median(PUE)-1 times P_IT (not OLS no-intercept)",
        "original_B2_definition": "OLS on available subset of {Tot_ict, temp_mean, temp_sq, twb_c}",
        "original_B3_definition": "OLS kitchen-sink including compressor, fan, free cooling, liquid flow, HTI",
        "original_hardcoded_report_claims": [
            "Outdoor dry-bulb strongly tracks non-IT power. Constant PUE is falsified in chronological holdout.",
            "Retain/add: load dependence of overhead; weather dependence; explicit operating/control state.",
        ],
        "original_run_manifest": None,
        "original_pilot": None,
    }
    man = ORIGINAL_SUITABILITY / "run_manifest.json"
    if man.exists():
        claims["original_run_manifest"] = json.loads(man.read_text())
        claims["original_facility_months"] = claims["original_run_manifest"].get("facility_months")
    pst = ORIGINAL_PILOT / "pilot_status.json"
    if pst.exists():
        claims["original_pilot"] = json.loads(pst.read_text())
    return claims


def boundary_row(df: pd.DataFrame, month: str) -> dict:
    s = df.dropna(subset=["P_IT", "P_facility"])
    row = {
        "month": month,
        "n_hours": int(len(df)),
        "n_valid_IT_facility": int(len(s)),
        "frac_facility_le_0": float((df["P_facility"] <= 0).mean()) if len(df) else np.nan,
        "frac_IT_le_0": float((df["P_IT"] <= 0).mean()) if len(df) else np.nan,
        "frac_facility_lt_IT": float((df["P_facility"] < df["P_IT"]).mean()) if len(df) else np.nan,
        "canonical_panel": "generals",
        "canonical_device": "pue",
        "PUE_median": float(s["PUE_calc"].median()) if len(s) else np.nan,
        "PUE_p05": float(s["PUE_calc"].quantile(0.05)) if len(s) else np.nan,
        "PUE_p95": float(s["PUE_calc"].quantile(0.95)) if len(s) else np.nan,
        "frac_PUE_lt_1": float((s["PUE_calc"] < 1).mean()) if len(s) else np.nan,
    }
    if "PUE_reported" in s.columns:
        both = s.dropna(subset=["PUE_calc", "PUE_reported"])
        if len(both) >= 5:
            err = both["PUE_reported"] - both["PUE_calc"]
            row["PUE_reported_vs_calc_mae"] = float(err.abs().mean())
            row["PUE_reported_vs_calc_corr"] = float(both["PUE_reported"].corr(both["PUE_calc"]))
    if "closure_resid" in s.columns:
        r = s["closure_resid"].dropna()
        if len(r):
            row["closure_n"] = int(len(r))
            row["closure_median_kW"] = float(r.median())
            row["closure_p05_kW"] = float(r.quantile(0.05))
            row["closure_p95_kW"] = float(r.quantile(0.95))
            tot = s["P_facility"].mean()
            row["closure_rel_median_pct"] = float(100.0 * r.median() / tot) if tot else np.nan
    return row


def thermal_rows(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    recs = []
    for month, df in frames.items():
        if "heat_transfer_index" not in df.columns:
            continue
        sub = df.dropna(subset=["P_IT", "heat_transfer_index"])
        if len(sub) < 24:
            continue
        s0 = sub.set_index("hour_utc").sort_index()
        lag = pd.concat([
            s0["P_IT"].rename("pit"),
            s0["heat_transfer_index"].shift(freq=pd.Timedelta(hours=1)).rename("hti_lead"),
        ], axis=1, sort=True).dropna()
        recs.append({
            "month": month,
            "n": int(len(sub)),
            "coverage_vs_calendar": float(len(sub) / max(len(df), 1)),
            "pearson": float(sub["P_IT"].corr(sub["heat_transfer_index"])),
            "spearman": float(sub["P_IT"].corr(sub["heat_transfer_index"], method="spearman")),
            "lag0_pearson": float(sub["P_IT"].corr(sub["heat_transfer_index"])),
            "lag_plus1h_pit_vs_hti": float(lag["pit"].corr(lag["hti_lead"])) if len(lag) > 10 else np.nan,
            "claim": "thermal measurement sanity (not thermal-load closure; HTI is not kW)",
            "note": "median across Q101/Q102 of source-aligned flow*delta_T; twins not summed",
        })
    # panel consistency
    for month in frames:
        lp = grain_parquet("liquid_cooling", month)
        if not lp.exists():
            continue
        l = pd.read_parquet(lp, columns=None)
        if "panel" not in l.columns or "flow_delta_t_mean" not in l.columns:
            continue
        l["hour_utc"] = pd.to_datetime(l["timestamp_utc"], utc=True)
        wide = l.pivot_table(index="hour_utc", columns="panel", values="flow_delta_t_mean", aggfunc="mean")
        if wide.shape[1] >= 2:
            a, b = wide.columns[:2]
            recs.append({
                "month": month, "n": int(wide.dropna().shape[0]),
                "panel_pair": f"{a}|{b}",
                "panel_hti_corr": float(wide[a].corr(wide[b])),
                "claim": "panel consistency (redundant twins; do not sum)",
            })
    return pd.DataFrame(recs) if recs else pd.DataFrame([{"claim": "no HTI"}])


def run() -> dict:
    if ORIGINAL_PILOT.exists() and ORIGINAL_SUITABILITY.exists():
        # refuse to write into original dirs
        assert OUT_DIR.resolve() != ORIGINAL_PILOT.resolve()
        assert OUT_DIR.resolve() != ORIGINAL_SUITABILITY.resolve()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "tables").mkdir(exist_ok=True)
    (OUT_DIR / "figures").mkdir(exist_ok=True)

    inv = load_metric_inventory()
    qual = qualify_inventory(inv) if len(inv) else pd.DataFrame()
    qual_map = {r["month"]: r for r in qual.to_dict("records")} if len(qual) else {}

    cert_rows = []
    for month in EXPECTED_MONTHS:
        cert_rows.append(repair_month_certification(month, qual_map.get(month), load_status(month)))
    cert = pd.DataFrame(cert_rows)
    write_csv(cert, "month_certification_repaired.csv")

    layer_rows = []
    for month in EXPECTED_MONTHS:
        q = qual_map.get(month) or {}
        row = {"month": month}
        for g in ("facility", "weather", "crac", "liquid_cooling", "node"):
            row[g] = int(grain_parquet(g, month).exists())
        row["full_facility_qualified"] = bool(q.get("classes") and "full-facility-qualified" in str(q.get("classes")))
        layer_rows.append(row)
    layers = pd.DataFrame(layer_rows)
    write_csv(layers, "month_layer_availability.csv")

    qualified = [
        r["month"] for r in cert_rows
        if r["full_facility_qualified"] and r["certification_v2"] in {"PASS", "PASS_PARTIAL"}
        and "facility" in (r["product_grains"] or "") and "weather" in (r["product_grains"] or "")
    ]
    # PASS_PARTIAL with full-facility class + products: include if weather+facility exist.
    # Prefer PASS. If Jul-Dec become PASS after repair they are included.
    qualified = [m for m in EXPECTED_MONTHS if m in qualified]

    frames = {m: load_month_hourly(m) for m in qualified}
    frames = {m: df for m, df in frames.items() if not df.empty}

    bound_rows = [boundary_row(df, m) for m, df in frames.items()]
    boundary = pd.DataFrame(bound_rows)
    write_csv(boundary, "measurement_boundary_checks.csv")

    folds_meta = expanding_folds(sorted(frames))
    base_rows, state_rows, inc_rows, mem_rows, coef_rows, marg_rows = [], [], [], [], [], []
    fold_rows, transfer_rows = [], []
    cooling_model_rows = []
    example_plot = None

    for spec in folds_meta:
        train = pd.concat([frames[m] for m in spec["train_months"]], ignore_index=True)
        test = frames[spec["test_month"]].copy()
        train["hour_utc"] = pd.to_datetime(train["hour_utc"], utc=True)
        test["hour_utc"] = pd.to_datetime(test["hour_utc"], utc=True)
        weather = choose_weather_formulation(train, test)
        if weather == "unsupported":
            fold_rows.append({**spec, "weather": weather, "status": "SKIPPED_NO_WEATHER",
                              "train_months": "|".join(spec["train_months"])})
            continue
        tr_base = train.loc[base_mask(train, weather)].copy()
        te_base = test.loc[base_mask(test, weather)].copy()
        b3_ok = "cooling_state" in train.columns and "cooling_state" in test.columns
        tr_st = train.loc[state_mask(train, weather)].copy() if b3_ok else tr_base.iloc[0:0]
        te_st = test.loc[state_mask(test, weather)].copy() if b3_ok else te_base.iloc[0:0]
        state_cov = (len(te_st) / len(te_base)) if len(te_base) else np.nan
        state_supported = b3_ok and len(tr_st) >= 50 and len(te_st) >= 20 and (
            state_cov >= 0.50 if np.isfinite(state_cov) else False
        )
        fold_rec = {
            "fold_id": spec["fold_id"],
            "train_months": "|".join(spec["train_months"]),
            "test_month": spec["test_month"],
            "weather_formulation": weather,
            "weather_formula": FORMULAS["B2_twb"] if weather == "twb" else FORMULAS["B2_fallback"],
            "state_variable": STATE_CONCEPT,
            "state_status": "SUPPORTED" if state_supported else "UNSUPPORTED",
            "base_train_n": int(len(tr_base)),
            "base_test_n": int(len(te_base)),
            "state_train_n": int(len(tr_st)),
            "state_test_n": int(len(te_st)),
            "state_test_coverage_vs_base": state_cov,
            "future_in_train": False,
        }
        if len(tr_base) < 50 or len(te_base) < 20:
            fold_rec["status"] = "SKIPPED_SMALL_SAMPLE"
            fold_rows.append(fold_rec)
            continue
        fold_rec["n_test_pit_below_train_p05"] = int((te_base["P_IT"] < tr_base["P_IT"].quantile(0.05)).sum())
        fold_rec["train_pit_p05"] = float(tr_base["P_IT"].quantile(0.05))
        fold_rec["status"] = "FIT"
        fold_rows.append(fold_rec)

        # --- base sample B0 B1 B2 ---
        brow, bcoef, bpred = fit_models(tr_base, te_base, weather, ["B0", "B1", "B2"])
        for r in brow:
            r.update({"fold_id": spec["fold_id"], "test_month": spec["test_month"],
                      "sample": "base", "train_months": fold_rec["train_months"]})
            base_rows.append(r)
        for r in bcoef:
            r.update({"fold_id": spec["fold_id"], "test_month": spec["test_month"], "sample": "base"})
            coef_rows.append(r)
        mae = {r["model"]: r["mae"] for r in brow}
        inc_rows.append({
            "fold_id": spec["fold_id"], "test_month": spec["test_month"], "sample": "base",
            "increment": "B0_to_B1",
            "mae_simple": mae["B0"], "mae_rich": mae["B1"],
            "mae_rel_improvement": rel_mae_improvement(mae["B0"], mae["B1"]),
        })
        inc_rows.append({
            "fold_id": spec["fold_id"], "test_month": spec["test_month"], "sample": "base",
            "increment": "B1_to_B2",
            "mae_simple": mae["B1"], "mae_rich": mae["B2"],
            "mae_rel_improvement": rel_mae_improvement(mae["B1"], mae["B2"]),
        })
        # residual memory on base test
        te_idx = pd.DatetimeIndex(te_base["hour_utc"])
        for model in ("B1", "B2"):
            resid = pd.Series(te_base["P_nonIT"].to_numpy(float) - bpred[model], index=te_idx)
            mem_rows.append({
                "fold_id": spec["fold_id"], "test_month": spec["test_month"],
                "model": model, "sample": "base",
                "acf_1h": acf_lag(resid, 1), "acf_6h": acf_lag(resid, 6), "acf_24h": acf_lag(resid, 24),
            })
        b2_beta = [r["value"] for r in bcoef if r["model"] == "B2"]
        for mr in marginal_effects_b2(b2_beta, weather, tr_base):
            mr.update({"fold_id": spec["fold_id"], "test_month": spec["test_month"], "model": "B2", "sample": "base"})
            marg_rows.append(mr)

        ranking_base = [r["model"] for r in sorted(brow, key=lambda x: x["mae"])]
        for r in brow:
            transfer_rows.append({
                "fold_id": spec["fold_id"], "test_month": spec["test_month"], "sample": "base",
                "model": r["model"], "mae": r["mae"], "nrmse": r["nrmse"], "bias": r["bias"],
                "r2": r["r2"], "energy_error_pct": r["energy_error_pct"],
                "structural_ranking": "|".join(ranking_base),
            })

        # --- state sample ---
        if state_supported:
            srow, scoef, spreds = fit_models(tr_st, te_st, weather, ["B0", "B1", "B2", "B3"])
            # guard: B3 features must not include forbidden names
            _, _, b3names = design_matrix(tr_st, "B3", weather)
            assert not set(b3names) & set(B3_FORBIDDEN)
            for r in srow:
                r.update({"fold_id": spec["fold_id"], "test_month": spec["test_month"],
                          "sample": "state", "train_months": fold_rec["train_months"],
                          "role": STATE_ROLE if r["model"] == "B3" else r["role"]})
                state_rows.append(r)
            for r in scoef:
                r.update({"fold_id": spec["fold_id"], "test_month": spec["test_month"], "sample": "state"})
                coef_rows.append(r)
            smae = {r["model"]: r["mae"] for r in srow}
            inc_rows.append({
                "fold_id": spec["fold_id"], "test_month": spec["test_month"], "sample": "state",
                "increment": "B2_to_B3_state_sample",
                "mae_simple": smae["B2"], "mae_rich": smae["B3"],
                "mae_rel_improvement": rel_mae_improvement(smae["B2"], smae["B3"]),
            })
            te_idx_s = pd.DatetimeIndex(te_st["hour_utc"])
            resid = pd.Series(te_st["P_nonIT"].to_numpy(float) - spreds["B3"], index=te_idx_s)
            mem_rows.append({
                "fold_id": spec["fold_id"], "test_month": spec["test_month"],
                "model": "B3", "sample": "state",
                "acf_1h": acf_lag(resid, 1), "acf_6h": acf_lag(resid, 6), "acf_24h": acf_lag(resid, 24),
            })
            if example_plot is None and spec["test_month"] >= "2021-07":
                example_plot = (spec, te_base, bpred, te_st, spreds if state_supported else None)
        else:
            inc_rows.append({
                "fold_id": spec["fold_id"], "test_month": spec["test_month"], "sample": "state",
                "increment": "B2_to_B3_state_sample",
                "mae_simple": np.nan, "mae_rich": np.nan,
                "mae_rel_improvement": np.nan, "status": "UNSUPPORTED",
            })

        # cooling secondary on base timestamps if available
        if "P_cooling" in tr_base.columns and tr_base["P_cooling"].notna().mean() >= 0.9 \
                and te_base["P_cooling"].notna().mean() >= 0.9:
            trc = tr_base.dropna(subset=["P_cooling"])
            tec = te_base.dropna(subset=["P_cooling"])
            # reuse design on a swapped target via temporary column
            tr_c = trc.copy(); te_c = tec.copy()
            ytr_c, yte_c = tr_c["P_cooling"].to_numpy(float), te_c["P_cooling"].to_numpy(float)
            for model in ("B0", "B1", "B2"):
                Xtr, intercept, _ = design_matrix(tr_c, model, weather)
                Xte, _, _ = design_matrix(te_c, model, weather)
                ph = ols_pred(ols_fit(ytr_c, Xtr, intercept), Xte, intercept)
                sc = metrics(yte_c, ph)
                sc.update({"model": model, "target": "P_cooling", "fold_id": spec["fold_id"],
                           "test_month": spec["test_month"]})
                cooling_model_rows.append(sc)
            overlap = te_base.dropna(subset=["P_cooling", "P_nonIT"])
            if len(overlap):
                cooling_model_rows.append({
                    "model": "ACCOUNTING", "target": "P_cooling",
                    "fold_id": spec["fold_id"], "test_month": spec["test_month"],
                    "frac_nonIT_energy_from_cooling": float(overlap["P_cooling"].sum() / overlap["P_nonIT"].sum()),
                    "n": int(len(overlap)),
                })

        if example_plot is None:
            example_plot = (spec, te_base, bpred, te_st if state_supported else None,
                            None)

    folds_df = pd.DataFrame(fold_rows)
    base_df = pd.DataFrame(base_rows)
    state_df = pd.DataFrame(state_rows) if state_rows else pd.DataFrame()
    inc_df = pd.DataFrame(inc_rows)
    mem_df = pd.DataFrame(mem_rows) if mem_rows else pd.DataFrame()
    coef_df = pd.DataFrame(coef_rows) if coef_rows else pd.DataFrame()
    marg_df = pd.DataFrame(marg_rows) if marg_rows else pd.DataFrame()
    xfer_df = pd.DataFrame([r for r in transfer_rows if "model" in r])
    therm_df = thermal_rows(frames)
    water_df = water_audit(inv)

    cool_df = pd.DataFrame(cooling_model_rows) if cooling_model_rows else pd.DataFrame(
        [{"cooling_target": "UNSUPPORTED"}]
    )
    if "frac_nonIT_energy_from_cooling" not in cool_df.columns and frames:
        acc = []
        for m, df in frames.items():
            if "P_cooling" not in df.columns:
                continue
            o = df.dropna(subset=["P_cooling", "P_nonIT"])
            if o.empty:
                continue
            acc.append({
                "month": m, "target": "P_cooling", "model": "ACCOUNTING",
                "frac_nonIT_energy_from_cooling": float(o["P_cooling"].sum() / o["P_nonIT"].sum()),
                "n": int(len(o)),
            })
        if acc:
            cool_df = pd.concat([cool_df, pd.DataFrame(acc)], ignore_index=True)

    write_csv(folds_df, "chronological_folds.csv")
    write_csv(base_df if len(base_df) else pd.DataFrame([{"note": "no base folds"}]), "model_comparison_base.csv")
    write_csv(state_df if len(state_df) else pd.DataFrame([{"B3": "UNSUPPORTED"}]), "model_comparison_state.csv")
    write_csv(inc_df, "incremental_skill.csv")
    write_csv(mem_df if len(mem_df) else pd.DataFrame([{"note": "no residuals"}]), "residual_memory.csv")
    write_csv(coef_df if len(coef_df) else pd.DataFrame(), "model_coefficients.csv")
    write_csv(marg_df if len(marg_df) else pd.DataFrame(), "marginal_effects.csv")
    write_csv(xfer_df if len(xfer_df) else pd.DataFrame(), "transfer_summary.csv")
    write_csv(cool_df, "cooling_target_comparison.csv")
    write_csv(therm_df, "thermal_check.csv")
    write_csv(water_df, "water_audit.csv")

    evidence = build_evidence(cert, folds_df, inc_df, mem_df, therm_df, cool_df, water_df, xfer_df, boundary)
    classification, rationale = classify_benchmark(evidence)

    old = load_original_conclusions()
    old_vs = _old_vs_v2(old, evidence, classification, inc_df, base_df)
    write_csv(old_vs, "old_vs_v2_conclusions.csv")

    _write_figures(frames, folds_df, base_df, state_df, inc_df, mem_df, therm_df, marg_df, layers, example_plot)
    _write_report(cert, qualified, folds_df, base_df, state_df, inc_df, mem_df, therm_df, cool_df,
                  water_df, evidence, classification, rationale, old_vs, marg_df)

    script_hashes = {name: sha256_file(ROOT / "scripts" / name) for name in ORIGINAL_DAG_SCRIPTS}
    script_hashes["m100_suitability_v2.py"] = sha256_file(ROOT / "scripts" / "m100_suitability_v2.py")
    script_hashes["analyze_m100_suitability_v2.py"] = sha256_file(Path(__file__))

    status = {
        "created_utc": utcnow(),
        "output_dir": str(OUT_DIR),
        "original_pilot_untouched": True,
        "original_suitability_2021_untouched": True,
        "no_raw_reprocessing": True,
        "no_additional_tar_deletion": True,
        "provenance": git_provenance(),
        "original_dag": {
            "manifest": str(ROOT / "manifests" / "pipeline_jobs.json"),
            "final_job": "21334082 FAILED IndentationError in analyze_m100_suitability.py",
            "audit_job": "21334083 CANCELLED afterok of final",
            "monthly_process_qc_cleanup": "Jan–Dec completed 0:0",
        },
        "script_sha256": script_hashes,
        "original_artifact_sha256": original_artifact_hashes(),
        "input_processed_root": "/orcd/pool/005/nacevedo/m100/processed/hourly",
        "qualified_full_facility_months": qualified,
        "fold_definitions": folds_df.to_dict("records"),
        "model_formulas": FORMULAS,
        "weather_choice_rule": "twb interaction if train has >=50 and test >=20 hours with finite P_IT, P_nonIT, T_wetbulb; else T_drybulb+RH under the same hour counts; never chosen by MAE",
        "state_variable": STATE_CONCEPT,
        "state_role": STATE_ROLE,
        "b3_forbidden_features": list(B3_FORBIDDEN),
        "evidence": evidence,
        "classification": classification,
        "classification_rationale": rationale,
        "tests": "see tests/test_m100_suitability_v2.py",
    }
    (OUT_DIR / "final_status.json").write_text(json.dumps(status, indent=2, default=str) + "\n")
    return status


def _old_vs_v2(old, evidence, classification, inc_df, base_df) -> pd.DataFrame:
    rows = []
    def add(topic, original, v2, changed):
        rows.append({"topic": topic, "original": original, "v2": v2, "changed": changed})

    old_months = str(old.get("original_facility_months"))
    add("facility_months_in_original_run_manifest", old_months,
        "recomputed from current products/qualification (see certification table)",
        True)
    add("B0_definition", old["original_B0_definition"], FORMULAS["B0"], True)
    add("B2_definition", old["original_B2_definition"], FORMULAS["B2_twb"], True)
    add("B3_definition", old["original_B3_definition"], FORMULAS["B3"], True)
    add("classification_rule", old["original_classification_rule"],
        "derived from evidence table via classify_benchmark()", True)
    add("classification_value",
        "B (hard-coded if any facility months)",
        classification, classification != "B")
    add("constant_PUE_claim",
        "hard-coded: 'Constant PUE is falsified in chronological holdout'",
        evidence.get("constant_PUE_vs_affine"), True)
    add("weather_claim",
        "hard-coded retain weather dependence / dry-bulb tracks non-IT",
        evidence.get("weather_increment"), True)
    add("state_claim",
        "hard-coded retain explicit operating/control state (B3 included HTI/flow)",
        evidence.get("state_increment"), True)
    add("transfer_label",
        "pilot second_period_transfer=CONSISTENT (ranking only)",
        "structural_ranking_transfer vs absolute_numerical_transfer reported separately",
        True)
    add("water",
        "empirical WUE unsupported",
        evidence.get("water_support"), False)
    add("original_final_job",
        "21334082 FAILED; full-year tables never written",
        "this v2 analysis is the first completed full-year B0–B3 matching the pilot spec",
        True)
    return pd.DataFrame(rows)


def _write_figures(frames, folds, base, state, inc, mem, therm, marg, layers, example):
    figs = OUT_DIR / "figures"
    # 1 layer heatmap
    fig, ax = plt.subplots(figsize=(9, 3.6))
    cols = [c for c in ("facility", "weather", "crac", "liquid_cooling", "node") if c in layers.columns]
    mat = layers.set_index("month")[cols].astype(int)
    ax.imshow(mat.T, aspect="auto", cmap="Greens", vmin=0, vmax=1)
    ax.set_yticks(range(len(cols))); ax.set_yticklabels(cols)
    ax.set_xticks(range(len(mat.index))); ax.set_xticklabels(mat.index, rotation=45, ha="right")
    ax.set_title("Processed hourly layer availability")
    fig.tight_layout(); fig.savefig(figs / "01_month_layer_availability.png", dpi=140); plt.close()

    if len(base):
        fig, ax = plt.subplots(figsize=(8.5, 4.2))
        for model, gg in base.groupby("model"):
            ax.plot(gg["test_month"], gg["mae"], marker="o", label=model)
        ax.set_ylabel("Held-out MAE (kW)")
        ax.set_title("Base sample: expanding-month MAE")
        ax.legend(); ax.grid(alpha=0.3)
        fig.tight_layout(); fig.savefig(figs / "02_fold_mae_base.png", dpi=140); plt.close()

    if len(inc):
        fig, ax = plt.subplots(figsize=(8.5, 4.2))
        for name, gg in inc.groupby("increment"):
            ax.bar(np.arange(len(gg)) + (0.2 if "B3" in name else 0),
                   100 * gg["mae_rel_improvement"].to_numpy(),
                   width=0.4, label=name)
        ax.axhline(5, color="k", ls="--", lw=0.8, label="5% descriptive")
        ax.set_ylabel("MAE relative improvement (%)")
        ax.set_title("Incremental skill (descriptive ≥5% line, not significance)")
        ax.legend(fontsize=8); ax.grid(alpha=0.3, axis="y")
        fig.tight_layout(); fig.savefig(figs / "03_incremental_skill.png", dpi=140); plt.close()

    if example is not None:
        spec, te_base, bpred, te_st, spreds = example
        fig, ax = plt.subplots(figsize=(9, 3.8))
        t = pd.to_datetime(te_base["hour_utc"], utc=True)
        ax.plot(t, te_base["P_nonIT"], color="k", lw=1.2, label="observed")
        for m, c in (("B0", "tab:gray"), ("B1", "tab:blue"), ("B2", "tab:orange")):
            if m in bpred:
                ax.plot(t, bpred[m], lw=1.0, label=m, color=c)
        ax.set_ylabel("P_nonIT (kW)")
        ax.set_title(f"Held-out base sample {spec['test_month']}")
        ax.legend(fontsize=8)
        fig.tight_layout(); fig.savefig(figs / "04_holdout_example.png", dpi=140); plt.close()

    if len(mem) and "acf_1h" in mem:
        fig, ax = plt.subplots(figsize=(8, 4))
        for model, gg in mem.groupby("model"):
            ax.plot(gg["test_month"], gg["acf_1h"], marker="o", label=f"{model} 1h")
        ax.axhline(0.3, color="k", ls="--", lw=0.7)
        ax.set_ylabel("Residual ACF (1 h)")
        ax.set_title("Timestamp-aware residual memory")
        ax.legend(fontsize=8); ax.grid(alpha=0.3)
        fig.tight_layout(); fig.savefig(figs / "05_residual_memory.png", dpi=140); plt.close()

    if len(therm) and "pearson" in therm:
        fig, ax = plt.subplots(figsize=(6, 4))
        sub = therm.dropna(subset=["pearson"])
        if "month" in sub:
            ax.bar(sub["month"].astype(str), sub["pearson"])
            ax.set_ylabel("Pearson(P_IT, HTI)")
            ax.set_title("Thermal measurement sanity (HTI is not kW)")
            ax.tick_params(axis="x", rotation=45)
            fig.tight_layout(); fig.savefig(figs / "06_thermal_check.png", dpi=140)
        plt.close()

    if len(marg):
        sub = marg.loc[marg["kind"].eq("dP_nonIT/dP_IT")] if "kind" in marg else marg
        if len(sub):
            fig, ax = plt.subplots(figsize=(8, 4))
            for at, gg in sub.groupby("at"):
                ax.plot(gg["test_month"], gg["value"], marker="o", label=str(at))
            ax.set_ylabel("∂P_nonIT / ∂P_IT  (kW/kW)")
            ax.set_title("B2 marginal IT effect over train weather support")
            ax.legend(fontsize=8); ax.grid(alpha=0.3)
            fig.tight_layout(); fig.savefig(figs / "07_marginal_effects.png", dpi=140); plt.close()


def _write_report(cert, qualified, folds, base, state, inc, mem, therm, cool, water,
                  evidence, classification, rationale, old_vs, marg):
    def _tbl(df):
        return df.to_string(index=False) if len(df) else "(empty)"

    n_folds = evidence.get("n_chronological_folds")
    lines = [
        "# M100 2021 facility-model suitability report (v2)",
        "",
        f"**Classification: {classification}.** {rationale}",
        "",
        "This label assesses M100 as an external measured benchmark for identifying or falsifying",
        "generic facility-model *structure*. It does **not** mean M100 numerical parameters are generic.",
        "Do not transfer coefficients, PUE levels, cooling fractions, GPU coefficients, traces, or",
        "control thresholds to Prineville.",
        "",
        "## Provenance",
        "",
        "Original DAG monthly download/process/QC/cleanup jobs completed. Final job 21334082 failed",
        "(IndentationError in `analyze_m100_suitability.py`); storage audit 21334083 was cancelled.",
        "Original `results/pilot_facility_2021/` and `results/suitability_2021/` were not overwritten.",
        "This report uses already-processed hourly Parquet only.",
        "",
        "## Model definitions (frozen to the May pilot)",
        "",
        f"- B0: `{FORMULAS['B0']}`",
        f"- B1: `{FORMULAS['B1']}`",
        f"- B2: `{FORMULAS['B2_twb']}` (fallback `{FORMULAS['B2_fallback']}` if wet-bulb coverage is inadequate)",
        f"- B3: `{FORMULAS['B3']}`",
        "",
        "B0/B1/B2 are compared on a common **base** timestamp sample (IT, non-IT, weather).",
        "B2 vs B3 uses a **state** sample that additionally requires Free_Cooling_Status.",
        "B3 is a STATE-INFORMED ORACLE, not a deployable planning predictor.",
        "Weather formulation is chosen by coverage, never by held-out MAE.",
        "",
        "## Repaired monthly certification",
        "",
        _tbl(cert[[c for c in cert.columns if c in {"month","certification_v2","certification_original","source_disposition","full_facility_qualified","n_processed_products","required_grains"}]]),
        "",
        "Apr–Jun tars were verified, certified PASS, and deleted by the original cleanup gate;",
        "they are `deleted_after_certification`, not ordinary missing sources.",
        "",
        f"**Qualified full-facility months used in chronological folds:** {qualified}",
        "",
        "## Chronological folds",
        "",
        _tbl(folds),
        "",
        "## Base-sample held-out metrics (B0, B1, B2)",
        "",
        _tbl(base),
        "",
        "## State-sample held-out metrics (B0–B3, common timestamps)",
        "",
        _tbl(state) if len(state) else "B3 UNSUPPORTED on all folds, or no state-common rows.",
        "",
        "## Incremental MAE skill (descriptive ≥5% line is not statistical significance)",
        "",
        _tbl(inc),
        "",
        f"Weather increment B1→B2: **{evidence.get('weather_increment')}** "
        f"({evidence.get('n_folds_weather_ge5pct')}/{n_folds} folds with ≥5% MAE drop).",
        f"Affine increment B0→B1: **{evidence.get('constant_PUE_vs_affine')}** "
        f"({evidence.get('n_folds_affine_ge5pct')}/{n_folds} folds).",
        f"State increment B2→B3 (state sample only): **{evidence.get('state_increment')}** "
        f"({evidence.get('n_folds_state_ge5pct')} folds with ≥5% MAE drop).",
        "",
        "## Residual memory",
        "",
        _tbl(mem),
        "",
        f"Temporal memory conclusion: **{evidence.get('temporal_memory')}** "
        "(1-hour residual autocorrelation on held-out B1/B2; persistent memory is evidence of missing slowly varying state, not a unique hysteresis identification).",
        "",
        "## Thermal measurement sanity (not thermal-load closure)",
        "",
        _tbl(therm),
        "",
        f"Thermal measurement sanity: **{evidence.get('thermal_measurement_sanity')}**. "
        f"Thermal-load closure: **{evidence.get('thermal_load_closure')}** "
        "(HTI is not converted to kW; circulating flow is not water use).",
        "",
        "## Cooling-power secondary target",
        "",
        _tbl(cool.head(40) if len(cool) else cool),
        "",
        f"Cooling aggregate support: **{evidence.get('cooling_target_support')}** "
        "(Tot_cdz + Tot_chiller + Tot_qpompe on generals/pue; Tot_servizi not included).",
        "",
        "## Transfer: ranking versus absolute numbers",
        "",
        f"Structural/ranking transfer (weather increment across folds): **{evidence.get('structural_transfer')}**.",
        f"Absolute numerical transfer (held-out NRMSE/bias magnitude): **{evidence.get('absolute_transfer')}**.",
        "These are different questions. Identical ranking plus large absolute error is not overall 'CONSISTENT'.",
        "",
        "## Water",
        "",
        _tbl(water),
        "",
        f"Empirical M100 WUE: **{evidence.get('water_support')}**.",
        "Supported chain: IT power → heat transport / thermal response → cooling operating behavior → cooling/facility electricity.",
        "",
        "## Evidence summary",
        "",
    ]
    for k in ("measurement_boundary_confidence", "constant_PUE_vs_affine", "weather_increment",
              "state_increment", "temporal_memory", "cooling_target_support",
              "thermal_measurement_sanity", "absolute_transfer", "structural_transfer", "water_support"):
        lines.append(f"- `{k}`: **{evidence.get(k)}**")
    lines += [
        "",
        "## Original vs v2 scientific conclusions",
        "",
        _tbl(old_vs),
        "",
        "## Generic-model implication (structural only)",
        "",
        "Implications below are about *which dependencies a reduced generic model should keep explicit*.",
        "They are not M100 coefficient, PUE, or cooling-fraction transfers.",
        "",
        f"- Load: B0 is already a constant non-IT fraction; affine intercept increment is {evidence.get('constant_PUE_vs_affine')}.",
        f"- Weather: {evidence.get('weather_increment')} for chronological held-out information after IT load.",
        f"- Observed cooling state (oracle): {evidence.get('state_increment')}. Internal Free_Cooling_Status is not assumed observable in generic planning.",
        f"- Static maps: residual 1 h memory is {evidence.get('temporal_memory')}.",
        "",
    ]
    (OUT_DIR / "final_report.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    run()
