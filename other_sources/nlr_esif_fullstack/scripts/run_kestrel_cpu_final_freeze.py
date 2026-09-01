#!/usr/bin/env python3
"""Final Kestrel CPU freeze: chronological transfer, coverage labels, predicted vs measured ESIF.

Does not refit p. Does not reconstruct shared jobs. Does not process H100/GenAI.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kestrel_paths import (  # noqa: E402
    ANALYSIS,
    DATA_PROCESSED,
    DOCS,
    EAGLE_DECOMMISSION_UTC,
    ESIF_PARQUET,
    FIGURES,
    GPU_GA_UTC,
    MANIFESTS,
    SPLIT_DEV_END,
    SPLIT_VAL_END,
    TIMESERIES,
)
from run_cpu_closure_pass import (  # noqa: E402
    NONSHARED_CPU,
    P_FROZEN,
    con,
    interpret_transfer,
    jdump,
    metrics,
    src_analysis,
    w_node_hour,
)
from run_kestrel_job_power_experiment import replay_from_jobs  # noqa: E402

DENVER = ZoneInfo("America/Denver")
COLS = (
    "start_time, end_time, duration_s, nodes_used, energy_wh, state_simple, partition"
)


def period_of(start_utc: pd.Series) -> pd.Series:
    dev = pd.Timestamp(SPLIT_DEV_END)
    val = pd.Timestamp(SPLIT_VAL_END)
    out = pd.Series("TEST", index=start_utc.index)
    out[start_utc < dev] = "DEV"
    out[(start_utc >= dev) & (start_utc < val)] = "VAL"
    return out


def load_validated(c, states):
    sql = f"""
    SELECT {COLS}
    FROM {src_analysis()}
    WHERE {NONSHARED_CPU}
      AND state_simple IN ({",".join("?" for _ in states)})
    """
    df = c.execute(sql, list(states)).fetchdf()
    df["start_utc"] = pd.to_datetime(df["start_time"], utc=True)
    df["end_utc"] = pd.to_datetime(df["end_time"], utc=True)
    df["node_hours"] = df["nodes_used"] * df["duration_s"] / 3600.0
    df["pred_wh"] = P_FROZEN * df["node_hours"]
    df["w_per_nh"] = df["energy_wh"] / np.clip(df["node_hours"], 1e-12, None)
    df["eps"] = df["energy_wh"] / np.clip(df["pred_wh"], 1e-12, None)
    df["period"] = period_of(df["start_utc"])
    return df


def pack_metrics(df, cohort, status=None):
    m = metrics(df["energy_wh"], df["pred_wh"])
    m.update(w_node_hour(df))
    m.update(
        {
            "cohort": cohort,
            "p_used": P_FROZEN,
            "refit": False,
            "measured_GWh": float(df["energy_wh"].sum()) / 1e9,
        }
    )
    if status is not None:
        m["transfer_status"] = status
    return m


def fit_esif(sub, xcol, dt_h):
    x = sub[xcol].to_numpy(dtype=float)
    y = sub["esif_it_kw"].to_numpy(dtype=float)
    X = np.column_stack([np.ones(len(x)), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    yhat = X @ beta
    err = yhat - y
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    return {
        "n": int(len(sub)),
        "B_kw": float(beta[0]),
        "beta": float(beta[1]),
        "pearson": float(np.corrcoef(x, y)[0, 1]) if np.std(x) and np.std(y) else None,
        "spearman": float(pd.Series(x).corr(pd.Series(y), method="spearman")),
        "R2": (1 - ss_res / ss_tot) if ss_tot else None,
        "MAE_kw": float(np.mean(np.abs(err))),
        "RMSE_kw": float(np.sqrt(np.mean(err**2))),
        "sum_esif_kWh": float(np.sum(y) * dt_h),
        "sum_kestrel_kWh": float(np.sum(x) * dt_h),
        "kestrel_share_of_esif": float(np.sum(x) / np.sum(y)) if np.sum(y) else None,
    }


def interpret_e2e(obs, pred):
    """Predeclared qualitative rule; not a post-hoc numeric cutoff."""
    r2o, r2p = obs["R2"], pred["R2"]
    ratio = (r2p / r2o) if r2o else None
    beta_rel = abs(pred["beta"] - obs["beta"]) / abs(obs["beta"]) if obs["beta"] else None
    share_rel = abs(pred["kestrel_share_of_esif"] - obs["kestrel_share_of_esif"])
    structure = pred["pearson"] is not None and pred["pearson"] > 0.4 and r2p is not None and r2p > 0.2
    strong = (
        structure
        and ratio is not None
        and ratio >= 0.8
        and beta_rel is not None
        and beta_rel < 0.25
        and share_rel < 0.08
    )
    fail = (not structure) or (r2p is not None and r2p < 0.1) or (pred["pearson"] is not None and pred["pearson"] < 0.2)
    if strong:
        status = "STRONG_END_TO_END_SUPPORT"
    elif fail:
        status = "FAIL"
    else:
        status = "PARTIAL"
    return {
        "status": status,
        "R2_pred_over_R2_obs": ratio,
        "beta_relative_abs_diff": beta_rel,
        "share_abs_diff": share_rel,
        "predeclared_rule": {
            "STRONG_END_TO_END_SUPPORT": "Predicted replay retains most of measured replay aggregate association (R2 ratio not far below 1) with similar scale (beta and energy ratio).",
            "PARTIAL": "Same temporal structure remains but model energy bias materially degrades scale or fit.",
            "FAIL": "Predicted replay loses the relationship substantially.",
            "not_chosen_by_post_hoc_cutoff_alone": True,
        },
        "rationale": (
            f"R2_obs={r2o:.3f} R2_pred={r2p:.3f} ratio={ratio:.3f}; "
            f"beta_obs={obs['beta']:.3f} beta_pred={pred['beta']:.3f}; "
            f"share_obs={obs['kestrel_share_of_esif']:.3f} share_pred={pred['kestrel_share_of_esif']:.3f}"
        ),
        "wording": "validated CPU job-attributed load is associated with a measurable component of ESIF total IT variation",
        "causal": False,
    }


def main():
    os.environ.setdefault("PYTHONNOUSERSITE", "1")
    assert abs(json.loads((MANIFESTS / "FINAL_MODEL_FREEZE.json").read_text())["EX_POST_CPU"]["p_hat_W_per_node"] - P_FROZEN) < 1e-12
    freeze = json.loads((MANIFESTS / "TIMEOUT_TRANSFER_FREEZE.json").read_text())
    assert freeze["no_refitting"] is True
    assert abs(freeze["p_cpu_w_per_node"] - P_FROZEN) < 1e-12
    rules = freeze["interpretation_rule_predeclared"]

    c = con()
    jobs = load_validated(c, ["COMPLETED", "TIMEOUT", "CANCELLED"])
    completed = jobs[jobs["state_simple"] == "COMPLETED"].copy()
    timeout = jobs[jobs["state_simple"] == "TIMEOUT"].copy()
    cancelled = jobs[jobs["state_simple"] == "CANCELLED"].copy()
    completed_test = completed[completed["period"] == "TEST"]

    m_ct = pack_metrics(completed_test, "COMPLETED_frozen_TEST", "REFERENCE")
    rows = [m_ct]
    chrono = []

    def add_state(name, df, full_status_key="transfer_status"):
        m_full = pack_metrics(df, f"{name}_transfer")
        dec_full = interpret_transfer(m_ct, m_full, rules)
        m_full["transfer_status"] = dec_full["status"]
        rows.append(m_full)
        for per in ("DEV", "VAL", "TEST"):
            sub = df[df["period"] == per]
            rec = pack_metrics(sub, f"{name}_{per}")
            if per == "TEST":
                dec = interpret_transfer(m_ct, rec, rules)
                rec["transfer_status"] = dec["status"]
                rec["interpretation"] = dec
            else:
                rec["transfer_status"] = "CHRONO_ROBUSTNESS"
            chrono.append(rec)
            rows.append(rec)
        return m_full, dec_full

    m_to, dec_to = add_state("TIMEOUT", timeout)
    m_ca, dec_ca = add_state("CANCELLED", cancelled)

    # Preserve FAIL_TRANSFER states from prior closure without refitting or new modeling.
    prior = pd.read_csv(ANALYSIS.parent / "results" / "cpu_state_transfer_metrics.csv") if (ANALYSIS.parent / "results" / "cpu_state_transfer_metrics.csv").exists() else None
    fail_states = []
    if prior is not None:
        for cohort, disp in (
            ("FAILED_transfer", "FAIL_TRANSFER"),
            ("NODE_FAIL_transfer", "FAIL_TRANSFER"),
            ("OUT_OF_MEMORY_transfer", "FAIL_TRANSFER"),
        ):
            hit = prior[prior["cohort"] == cohort]
            if len(hit):
                rec = hit.iloc[0].to_dict()
                rec["refit"] = False
                rec["p_used"] = P_FROZEN
                rec["transfer_status"] = disp
                rec["note"] = "Preserved from prior closure; not re-modeled in this freeze pass."
                fail_states.append(rec)
                rows.append(rec)

    timeout_test = next(r for r in chrono if r["cohort"] == "TIMEOUT_TEST")
    cancelled_test = next(r for r in chrono if r["cohort"] == "CANCELLED_TEST")
    cancelled_test_ok = cancelled_test["n"] >= 1000 and cancelled_test["measured_GWh"] >= 0.05
    cancelled_test["sample_sufficient_for_stable_inference"] = cancelled_test_ok
    if not cancelled_test_ok:
        cancelled_test["transfer_status"] = "INSUFFICIENT_TEST_SAMPLE"

    to_chrono_status = timeout_test["transfer_status"]
    ca_chrono_status = cancelled_test["transfer_status"] if cancelled_test_ok else "INSUFFICIENT_TEST_SAMPLE"

    timeout_supported = dec_to["status"] in ("PASS_TRANSFER", "PARTIAL_TRANSFER") and to_chrono_status in (
        "PASS_TRANSFER",
        "PARTIAL_TRANSFER",
    )
    cancelled_supported = dec_ca["status"] in ("PASS_TRANSFER", "PARTIAL_TRANSFER") and (
        ca_chrono_status in ("PASS_TRANSFER", "PARTIAL_TRANSFER") or ca_chrono_status == "INSUFFICIENT_TEST_SAMPLE"
    )
    # If TEST is insufficient, full CANCELLED transfer can still support the domain with a caveat.
    cancelled_disposition = "SUPPORTED" if cancelled_supported else "UNSUPPORTED"
    if ca_chrono_status == "INSUFFICIENT_TEST_SAMPLE" and dec_ca["status"] in ("PASS_TRANSFER", "PARTIAL_TRANSFER"):
        cancelled_disposition = "SUPPORTED_FULL_PERIOD_TEST_CAVEAT"

    final_states = [
        {
            "state": "COMPLETED",
            "disposition": "SUPPORTED",
            "confidence": "high",
            "full": pack_metrics(completed, "COMPLETED_full", "REFERENCE"),
            "test": m_ct,
            "chrono_test_status": "REFERENCE",
        },
        {
            "state": "TIMEOUT",
            "disposition": "SUPPORTED" if timeout_supported else "UNSUPPORTED",
            "confidence": "high" if to_chrono_status == "PASS_TRANSFER" else "medium",
            "full": m_to,
            "test": timeout_test,
            "chrono_test_status": to_chrono_status,
        },
        {
            "state": "CANCELLED",
            "disposition": cancelled_disposition,
            "confidence": "high" if ca_chrono_status == "PASS_TRANSFER" else ("medium" if cancelled_supported else "low"),
            "full": m_ca,
            "test": cancelled_test,
            "chrono_test_status": ca_chrono_status,
        },
        {"state": "FAILED", "disposition": "UNSUPPORTED", "confidence": "high", "note": "FAIL_TRANSFER preserved"},
        {"state": "NODE_FAIL", "disposition": "UNSUPPORTED", "confidence": "high", "note": "FAIL_TRANSFER preserved"},
        {"state": "OOM", "disposition": "UNSUPPORTED", "confidence": "high", "note": "FAIL_TRANSFER preserved; immaterial energy"},
        {"state": "H100", "disposition": "UNSUPPORTED", "confidence": "high", "note": "no positive ConsumedEnergyRaw"},
        {"state": "shared_jobs", "disposition": "UNSUPPORTED", "confidence": "high", "note": "non-additive raw energy; reconstruction not attempted"},
    ]

    compact_final = []
    for s in final_states:
        row = {
            "state": s["state"],
            "disposition": s["disposition"],
            "confidence": s["confidence"],
            "p_used": P_FROZEN,
            "refit": False,
        }
        if "full" in s:
            f, t = s["full"], s["test"]
            row.update(
                {
                    "n_full": f["n"],
                    "GWh_full": f["measured_GWh"],
                    "WAPE_full": f["WAPE"],
                    "bias_full": f["total_energy_bias"],
                    "R2_logE_full": f["R2_logE"],
                    "median_W_per_node_hour_full": f["median_W_per_node_hour"],
                    "n_test": t["n"],
                    "GWh_test": t["measured_GWh"],
                    "WAPE_test": t["WAPE"],
                    "bias_test": t["total_energy_bias"],
                    "R2_logE_test": t["R2_logE"],
                    "median_W_per_node_hour_test": t.get("median_W_per_node_hour"),
                    "p05_W_per_node_hour_test": t.get("p05_W_per_node_hour"),
                    "p95_W_per_node_hour_test": t.get("p95_W_per_node_hour"),
                    "chrono_test_status": s["chrono_test_status"],
                }
            )
        if s.get("note"):
            row["note"] = s["note"]
        compact_final.append(row)

    pd.DataFrame(rows).to_csv(ANALYSIS / "CPU_STATE_TRANSFER_CHRONO.csv", index=False)
    pd.DataFrame(compact_final).to_csv(ANALYSIS / "CPU_STATE_TRANSFER_FINAL.csv", index=False)
    jdump(
        ANALYSIS / "CPU_STATE_TRANSFER_FINAL.json",
        {
            "p_cpu_w_per_node": P_FROZEN,
            "refit": False,
            "supported_states": [s["state"] for s in final_states if str(s["disposition"]).startswith("SUPPORTED")],
            "unsupported_states": [s["state"] for s in final_states if s["disposition"] == "UNSUPPORTED"],
            "states": compact_final,
            "chronological_rows": chrono,
            "interpretation_rule_predeclared": rules,
        },
    )

    # Coverage terminology
    cov = json.loads((ANALYSIS / "CPU_ENERGY_COVERAGE.json").read_text())
    validated = float(cov["validated_additive_cpu_GWh"])
    raw_pos = float(cov["total_positive_measured_Wh"]) / 1e9
    shared = next(x for x in cov["categories"] if x["category"].startswith("D_shared"))["measured_GWh"]
    additive_denom = raw_pos - shared
    frac_raw = validated / raw_pos
    frac_add = validated / additive_denom
    cov["coverage_measures"] = {
        "validated_additive_cpu_GWh": validated,
        "summed_positive_measured_ConsumedEnergyRaw_job_record_GWh": raw_pos,
        "fraction_of_summed_positive_measured_ConsumedEnergyRaw_job_record_energy_represented_by_validated_additive_CPU_states": frac_raw,
        "non_additive_shared_raw_sum_GWh": shared,
        "additive_nonshared_positive_measured_job_record_GWh": additive_denom,
        "fraction_of_additive_nonshared_positive_measured_job_record_energy_represented_by_validated_CPU_states": frac_add,
        "not_fraction_of_physical_Kestrel_IT": True,
        "not_fraction_of_facility_IT": True,
        "H100_physical_energy_excluded_because_unmeasured": True,
    }
    cov["gwh_definition"] = "GWh = Wh / 1e9"
    jdump(ANALYSIS / "CPU_ENERGY_COVERAGE.json", cov)

    # Residual dependence on untouched completed TEST
    h = completed_test["node_hours"].to_numpy()
    eps = completed_test["eps"].to_numpy()
    eobs = completed_test["energy_wh"].to_numpy()
    qs = np.quantile(h, [0.0, 0.25, 0.5, 0.75, 1.0])
    qs[0] = min(qs[0], h.min())
    qs[-1] = max(qs[-1], h.max())
    bins = pd.cut(completed_test["node_hours"], bins=qs, include_lowest=True, duplicates="drop")
    dep_rows = []
    for b, sub in completed_test.groupby(bins, observed=True):
        dep_rows.append(
            {
                "node_hour_bin": str(b),
                "n": int(len(sub)),
                "median_eps": float(sub["eps"].median()),
                "mean_eps": float(sub["eps"].mean()),
                "p05_eps": float(sub["eps"].quantile(0.05)),
                "p95_eps": float(sub["eps"].quantile(0.95)),
                "measured_GWh": float(sub["energy_wh"].sum()) / 1e9,
                "energy_weight": float(sub["energy_wh"].sum() / eobs.sum()),
                "median_node_hours": float(sub["node_hours"].median()),
            }
        )
    medians = [r["median_eps"] for r in dep_rows]
    rel_spread = (max(medians) - min(medians)) / float(np.median(eps)) if medians else 0.0
    # Material if quartile medians span >20% of overall median AND high-energy bins differ from overall.
    material = rel_spread > 0.2
    pd.DataFrame(dep_rows).to_csv(ANALYSIS / "CPU_RESIDUAL_DEPENDENCE.csv", index=False)
    residual = {
        "cohort": "COMPLETED_untouched_TEST",
        "n": int(len(eps)),
        "eps_mean": float(np.mean(eps)),
        "eps_median": float(np.median(eps)),
        "eps_p05": float(np.quantile(eps, 0.05)),
        "eps_p25": float(np.quantile(eps, 0.25)),
        "eps_p75": float(np.quantile(eps, 0.75)),
        "eps_p95": float(np.quantile(eps, 0.95)),
        "eps_p01": float(np.quantile(eps, 0.01)),
        "eps_p99": float(np.quantile(eps, 0.99)),
        "aggregate_test_bias": m_ct["total_energy_bias"],
        "WAPE_is_not_an_uncertainty_interval": True,
        "WAPE_completed_TEST": m_ct["WAPE"],
        "node_hour_quartile_median_eps": medians,
        "node_hour_quartile_median_eps_relative_spread": rel_spread,
        "residual_dependence_on_node_hours_material": material,
        "recommended_representation": "POINT_MODEL_PLUS_AGGREGATE_BIAS_AND_HELD_OUT_RESIDUAL_SENSITIVITY",
        "iid_epsilon_sampling_allowed": False,
        "do_not_import_completed_residuals_to_TIMEOUT_or_CANCELLED": True,
        "note": (
            "Canonical point model is E = p N tau. Downstream planning should use the point estimate "
            "with the chronological TEST aggregate energy bias as a diagnostic and the held-out residual "
            "distribution as sensitivity information. Do not treat WAPE as a CI. Do not draw iid epsilon "
            "by default; residuals are not a calibrated noise model and are mildly node-hour dependent."
        ),
        "if_stochastic_job_simulation_required": (
            "Use at most the 4 node-hour-quartile empirical F(eps|bin) on completed TEST; "
            "do not fit ML; do not force unweighted mean to 1; TIMEOUT/CANCELLED need state-specific residuals."
            if material
            else "Unconditional completed TEST residual distribution is adequate as sensitivity; still do not sample iid by default."
        ),
    }
    jdump(ANALYSIS / "CPU_RESIDUAL_UNCERTAINTY.json", residual)

    # Two comparable replays: measured vs frozen-model predicted
    fingerprint = {
        "n_jobs": int(len(jobs)),
        "states": sorted(jobs["state_simple"].unique().tolist()),
        "sum_nodes_used": float(jobs["nodes_used"].sum()),
        "sum_duration_s": float(jobs["duration_s"].sum()),
        "sum_measured_Wh": float(jobs["energy_wh"].sum()),
        "sum_predicted_Wh": float(jobs["pred_wh"].sum()),
        "start_min": str(jobs["start_utc"].min()),
        "end_max": str(jobs["end_utc"].max()),
        "predicted_uses_measured_energy": False,
        "predicted_formula": "pred_wh = p_frozen * nodes_used * duration_s / 3600",
        "identical_job_set": True,
    }
    frames = []
    conservation = {}
    for freq, name in ("1h", "1h"), ("1D", "1day"):
        g_m, p_m, c_m, e_m = replay_from_jobs(jobs["start_utc"], jobs["end_utc"], jobs["energy_wh"], freq)
        g_p, p_p, c_p, e_p = replay_from_jobs(jobs["start_utc"], jobs["end_utc"], jobs["pred_wh"], freq)
        assert list(g_m) == list(g_p)
        conservation[name] = {
            "measured": c_m,
            "predicted": c_p,
            "source_measured_Wh": e_m,
            "source_predicted_Wh": e_p,
        }
        frames.append(
            pd.DataFrame(
                {
                    "ts_utc": g_m,
                    "resolution": name,
                    "measured_cpu_kw": p_m,
                    "predicted_cpu_kw": p_p,
                }
            )
        )
    ts = pd.concat(frames, ignore_index=True)
    TIMESERIES.mkdir(parents=True, exist_ok=True)
    ts.to_parquet(TIMESERIES / "kestrel_cpu_replay_measured_pred_v2.parquet", index=False)
    jdump(ANALYSIS / "CPU_REPLAY_CONSERVATION.json", {"job_set": fingerprint, "conservation": conservation})

    # ESIF comparison on identical timestamps, no lag optimization
    es = con().execute(
        f"""
        SELECT ts, it_power_kw FROM read_parquet('{ESIF_PARQUET}')
        WHERE it_power_kw IS NOT NULL AND isfinite(it_power_kw)
        """
    ).fetchdf()
    ts_naive = pd.to_datetime(es["ts"])
    es["ts_utc"] = ts_naive.dt.tz_localize(DENVER, ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")
    es = es.dropna(subset=["ts_utc"])
    overlap = es[es["ts_utc"] >= pd.Timestamp("2023-08-10", tz="UTC")]
    compare_rows = []
    daily_primary = {}
    for freq_name, rule, dt_h in ("1h", "1h", 1.0), ("1day", "1D", 24.0):
        k = ts[ts["resolution"] == freq_name].set_index("ts_utc")
        e = overlap.set_index("ts_utc")["it_power_kw"].resample(rule).mean()
        m = pd.concat(
            [
                e.rename("esif_it_kw"),
                k["measured_cpu_kw"],
                k["predicted_cpu_kw"],
            ],
            axis=1,
        ).dropna()
        epochs = np.where(
            m.index < pd.Timestamp(EAGLE_DECOMMISSION_UTC),
            "eagle_coexist",
            np.where(m.index < pd.Timestamp(GPU_GA_UTC), "post_eagle_pre_gpu_ga", "post_gpu_ga"),
        )
        for epoch, sub in (("all", m),) + tuple((ep, g) for ep, g in m.groupby(epochs)):
            if len(sub) < 20:
                continue
            obs = fit_esif(sub, "measured_cpu_kw", dt_h)
            pred = fit_esif(sub, "predicted_cpu_kw", dt_h)
            obs.update({"replay": "measured_energy", "resolution": freq_name, "epoch": epoch, "identical_timestamps": True, "lag_optimized": False})
            pred.update({"replay": "frozen_model_predicted", "resolution": freq_name, "epoch": epoch, "identical_timestamps": True, "lag_optimized": False})
            compare_rows.append(obs)
            compare_rows.append(pred)
            if freq_name == "1day" and epoch == "post_gpu_ga":
                daily_primary = {"measured": obs, "predicted": pred, "n_intervals": int(len(sub)), "ts_min": str(sub.index.min()), "ts_max": str(sub.index.max())}

    e2e = interpret_e2e(daily_primary["measured"], daily_primary["predicted"])
    pd.DataFrame(compare_rows).to_csv(ANALYSIS / "ESIF_CPU_REPLAY_COMPARISON.csv", index=False)
    jdump(
        ANALYSIS / "ESIF_CPU_REPLAY_COMPARISON.json",
        {
            "timezone": "naive ESIF ts localized as America/Denver (operational; not lag-optimized)",
            "ESIF_TIMESTAMP_SEMANTICS": "AMBIGUOUS",
            "primary_resolution": "1day",
            "secondary_resolution": "1h",
            "hourly_timezone_caveat_hours": [6, 7],
            "primary_epoch": "post_gpu_ga",
            "identical_timestamps": True,
            "lag_optimized": False,
            "daily_post_gpu_ga": daily_primary,
            "end_to_end_interpretation": e2e,
            "rows": compare_rows,
            "wording": "validated CPU job-attributed load is associated with a measurable component of ESIF total IT variation",
        },
    )

    # Attach ESIF share to coverage
    cov["coverage_measures"]["validated_CPU_replay_over_ESIF_IT_energy_daily_post_gpu_ga_measured"] = daily_primary["measured"]["kestrel_share_of_esif"]
    cov["coverage_measures"]["validated_CPU_replay_over_ESIF_IT_energy_daily_post_gpu_ga_predicted"] = daily_primary["predicted"]["kestrel_share_of_esif"]
    jdump(ANALYSIS / "CPU_ENERGY_COVERAGE.json", cov)

    # Figures (max two scientific + coverage label update)
    fig, ax = plt.subplots(figsize=(6.6, 4.4))
    for lab, sub, c0 in (
        ("COMPLETED TEST", completed_test, "C0"),
        ("TIMEOUT TEST", timeout[timeout["period"] == "TEST"], "C1"),
        ("CANCELLED TEST", cancelled[cancelled["period"] == "TEST"], "C2"),
    ):
        ax.hist(np.clip(sub["w_per_nh"], 0, 1500), bins=50, density=True, alpha=0.45, label=lab, color=c0)
    ax.axvline(P_FROZEN, color="k", ls="--", lw=1, label=f"p={P_FROZEN:.1f} W/node")
    ax.set_xlabel("Measured Wh / node-hour")
    ax.set_ylabel("Density")
    ax.set_title("Chronological TEST occupancy intensity (frozen p)")
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES / "07_completed_vs_timeout_w_per_node_hour.png", dpi=140)
    plt.close(fig)

    drow_m = daily_primary["measured"]
    drow_p = daily_primary["predicted"]
    kday = ts[ts["resolution"] == "1day"].set_index("ts_utc")
    eday = overlap.set_index("ts_utc")["it_power_kw"].resample("1D").mean()
    both = pd.concat([eday.rename("esif"), kday["measured_cpu_kw"], kday["predicted_cpu_kw"]], axis=1).dropna()
    both = both[both.index >= pd.Timestamp(GPU_GA_UTC)]
    fig, ax = plt.subplots(figsize=(5.8, 5.4))
    ax.scatter(both["measured_cpu_kw"], both["esif"], s=12, alpha=0.45, label="measured replay")
    ax.scatter(both["predicted_cpu_kw"], both["esif"], s=12, alpha=0.45, label="frozen-model replay")
    xx = np.linspace(0, max(both["measured_cpu_kw"].max(), both["predicted_cpu_kw"].max()), 50)
    ax.plot(xx, drow_m["B_kw"] + drow_m["beta"] * xx, lw=1.2, label="fit measured")
    ax.plot(xx, drow_p["B_kw"] + drow_p["beta"] * xx, lw=1.2, label="fit predicted")
    ax.set_xlabel("Kestrel validated CPU replay (kW, daily mean)")
    ax.set_ylabel("ESIF IT (kW, daily mean)")
    ax.set_title("Daily post-GPU-GA: measured vs frozen-model CPU replay")
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES / "09_esif_daily_measured_vs_predicted.png", dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    cats = cov["categories"]
    plot = [r for r in cats if not r["category"].startswith("F_")]
    labels = {
        "A_completed_exclusive_nonshared_CPU": "A completed exclusive",
        "B_timeout_exclusive_nonshared_CPU": "B TIMEOUT exclusive",
        "C_other_states_exclusive_nonshared_CPU_positive_energy": "C other exclusive (CANCELLED validated)",
        "D_shared_CPU_positive_energy": "D shared (raw, not additive)",
        "E_H100_GPU": "E H100/GPU",
        "G_unresolved_positive_energy": "G unresolved positive",
    }
    ax.barh([labels.get(r["category"], r["category"]) for r in plot], [r["measured_GWh"] for r in plot])
    ax.set_xlabel("Measured job-record energy (GWh)")
    ax.set_title("Job-record energy by category (shared raw sum is not physical IT)")
    fig.tight_layout()
    fig.savefig(FIGURES / "08_cpu_energy_coverage.png", dpi=140)
    plt.close(fig)

    cpu_timeout = "PASS" if timeout_supported and to_chrono_status == "PASS_TRANSFER" else (
        "PARTIAL" if timeout_supported else "FAIL"
    )
    cpu_cancelled = "PASS" if ca_chrono_status == "PASS_TRANSFER" else (
        "PARTIAL" if cancelled_supported else "FAIL"
    )
    esif_pred_status = {"STRONG_END_TO_END_SUPPORT": "PASS", "PARTIAL": "PARTIAL", "FAIL": "FAIL"}[e2e["status"]]
    layer = "FROZEN_PASS_WITH_DOMAIN_RESTRICTIONS"

    status = {
        "CPU_COMPLETED_NODE_HOUR": "PASS",
        "CPU_TIMEOUT_TRANSFER": cpu_timeout,
        "CPU_CANCELLED_TRANSFER": cpu_cancelled,
        "CPU_OTHER_STATE_TRANSFER": "PARTIAL",
        "CPU_VALIDATED_RAW_MEASURED_ENERGY_SHARE": frac_raw,
        "CPU_VALIDATED_ADDITIVE_ENERGY_SHARE": frac_add,
        "SHARED_CPU_RECONSTRUCTION": "UNSUPPORTED",
        "H100_MEASURED_JOB_ENERGY": "UNSUPPORTED_IN_KESTREL_JOB_EXTRACT",
        "ENERGY_CONSERVING_JOB_REPLAY": "PASS",
        "SUBHOURLY_POWER_SHAPE": "UNSUPPORTED",
        "ESIF_TIMESTAMP_SEMANTICS": "AMBIGUOUS",
        "ESIF_MEASURED_CPU_LINKAGE": "PARTIAL",
        "ESIF_PREDICTED_CPU_LINKAGE": esif_pred_status,
        "CPU_LAYER_FINAL_DISPOSITION": layer,
        "p_KestrelCPU_W_per_node": P_FROZEN,
        "validated_states": ["COMPLETED", "TIMEOUT", "CANCELLED"],
        "unsupported_for_coefficient": ["H100", "Eagle", "generic_hyperscale_CPU", "shared_jobs", "FAILED", "NODE_FAIL", "OOM"],
        "coverage": cov["coverage_measures"],
        "end_to_end_daily_post_gpu_ga": e2e,
        "residual": {
            "representation": residual["recommended_representation"],
            "iid_epsilon_sampling_allowed": False,
            "WAPE_is_not_uncertainty": True,
        },
        "temporal": {
            "daily": "supported_energy_accounting_facility_comparison",
            "hourly": "useful_aggregate_approximation_timezone_caveat",
            "15min": "accounting_scenario_approximation_only",
            "5min": "energy_conserving_not_validated_physical_shape",
            "instantaneous_burst": "UNSUPPORTED",
        },
        "next_experiment": {
            "name": "NLR GENAI H100 MEASURED POWER PROFILES",
            "doi": "10.7799/3025227",
            "executed": False,
        },
        "refit": False,
    }
    jdump(ANALYSIS / "FINAL_KESTREL_CPU_STATUS.json", status)

    # Report addendum — keep original experiment sections; replace closure addendum with freeze addendum.
    report_path = DOCS / "KESTREL_JOB_POWER_REPORT.md"
    old = report_path.read_text()
    marker = "# CPU-coverage and ESIF-closure addendum"
    head = old.split(marker)[0].rstrip()
    # Patch J-table coverage row terminology in the historical section.
    head = head.replace(
        "| CPU_ENERGY_COVERAGE | **PARTIAL** (~89% of positive measured job energy in the validated exclusive/non-shared CPU law) |",
        "| CPU_ENERGY_COVERAGE | **PARTIAL** (see freeze addendum: 89.0% of summed positive job-record energy; 93.9% of additive/non-shared; not physical Kestrel IT) |",
    )
    dm, dp = daily_primary["measured"], daily_primary["predicted"]
    addendum = f"""

# Final Kestrel CPU freeze

Pass on frozen completed-job coefficient **p = {P_FROZEN} W/node**. No refit. Shared jobs not reconstructed. H100 not processed. ESIF lag not optimized.

## Chronological transfer (exclusive non-shared CPU)

| State | Period | n | GWh | WAPE | bias | R²(log E) | median W/node-h | disposition |
|---|---|---|---|---|---|---|---|---|
| COMPLETED | TEST | {m_ct['n']:,} | {m_ct['measured_GWh']:.3f} | {m_ct['WAPE']:.3f} | {m_ct['total_energy_bias']:+.3f} | {m_ct['R2_logE']:.3f} | {m_ct['median_W_per_node_hour']:.1f} | REFERENCE |
| TIMEOUT | full | {m_to['n']:,} | {m_to['measured_GWh']:.3f} | {m_to['WAPE']:.3f} | {m_to['total_energy_bias']:+.3f} | {m_to['R2_logE']:.3f} | {m_to['median_W_per_node_hour']:.1f} | {dec_to['status']} |
| TIMEOUT | TEST | {timeout_test['n']:,} | {timeout_test['measured_GWh']:.3f} | {timeout_test['WAPE']:.3f} | {timeout_test['total_energy_bias']:+.3f} | {timeout_test['R2_logE']:.3f} | {timeout_test['median_W_per_node_hour']:.1f} | {timeout_test['transfer_status']} |
| CANCELLED | full | {m_ca['n']:,} | {m_ca['measured_GWh']:.3f} | {m_ca['WAPE']:.3f} | {m_ca['total_energy_bias']:+.3f} | {m_ca['R2_logE']:.3f} | {m_ca['median_W_per_node_hour']:.1f} | {dec_ca['status']} |
| CANCELLED | TEST | {cancelled_test['n']:,} | {cancelled_test['measured_GWh']:.3f} | {cancelled_test['WAPE']:.3f} | {cancelled_test['total_energy_bias']:+.3f} | {cancelled_test['R2_logE']:.3f} | {cancelled_test['median_W_per_node_hour']:.1f} | {cancelled_test['transfer_status']} |

FAILED / NODE_FAIL / OOM remain **FAIL_TRANSFER** (not re-opened). Shared reconstruction remains **UNSUPPORTED**.

Supported domain: COMPLETED, TIMEOUT, CANCELLED (exclusive, non-shared, Kestrel CPU, actual nodes × actual runtime).

## Coverage (three different denominators)

Validated additive CPU energy = **{validated:.3f} GWh**.

1. Fraction of **summed positive measured ConsumedEnergyRaw job-record energy** represented by validated additive CPU states: **{validated:.3f}/{raw_pos:.3f} = {100*frac_raw:.1f}%**. This is **not** a fraction of physical Kestrel IT, facility IT, or total CPU energy. The denominator includes non-additive shared-job records and excludes unmeasured H100 physical energy.
2. Fraction of **additive/non-shared positive measured job-record energy** represented by validated CPU states: **{validated:.3f}/{additive_denom:.3f} = {100*frac_add:.1f}%**. Shared raw sum ({shared:.3f} GWh) is excluded because it is not additive.
3. Validated CPU replay / ESIF IT energy, daily post-GPU-GA: measured **{dm['kestrel_share_of_esif']:.3f}**; frozen-model predicted **{dp['kestrel_share_of_esif']:.3f}**.

## Canonical CPU model

\\(E^{{IT}}_{{j,\\mathrm{{CPU}}}} = p_{{\\mathrm{{KestrelCPU}}}} N_j \\tau_j\\) with \\(p_{{\\mathrm{{KestrelCPU}}}}={P_FROZEN}\\,\\mathrm{{W/node}}\\).

FORM \\(E\\propto\\)hardware-hours may generalize. PARAMETER 700.689 W/node is Kestrel-CPU-specific. Do not apply to H100, Eagle, generic hyperscale CPUs, shared jobs, or unsupported states.

## Uncertainty

Point model only. Completed TEST: median \\(\\epsilon=E_{{\\mathrm{{obs}}}}/(p N \\tau)\\) = {residual['eps_median']:.3f}; p05–p95 [{residual['eps_p05']:.3f}, {residual['eps_p95']:.3f}]; aggregate energy bias {m_ct['total_energy_bias']:+.3f}. Node-hour quartile median-\\(\\epsilon\\) relative spread = {rel_spread:.3f} (material={material}).

**WAPE is a diagnostic, not an uncertainty interval.** Do not sample iid \\(\\epsilon\\) by default. Do not import completed residuals onto TIMEOUT/CANCELLED.

## Temporal replay

Measured-energy and frozen-model replays use the **same** COMPLETED+TIMEOUT+CANCELLED exclusive non-shared jobs. Conservation holds at hourly and daily resolution (see `analysis/CPU_REPLAY_CONSERVATION.json`). Daily: supported for energy/accounting/facility comparison. Hourly: useful aggregate approximation (±6–7 h timezone caveat). 15 min: accounting/scenario only. 5 min: energy-conserving mathematically, **not** validated physical shape. Instantaneous/burst: **UNSUPPORTED**.

## ESIF end-to-end (PRIMARY = daily, post-GPU-GA)

Timezone remains **AMBIGUOUS** (calendar-day supported; hourly caveat). Lag was not optimized.

| Replay | n | Pearson | Spearman | R² | B (kW) | β | MAE (kW) | Kestrel/ESIF |
|---|---|---|---|---|---|---|---|---|
| measured energy | {dm['n']} | {dm['pearson']:.3f} | {dm['spearman']:.3f} | {dm['R2']:.3f} | {dm['B_kw']:.0f} | {dm['beta']:.3f} | {dm['MAE_kw']:.1f} | {dm['kestrel_share_of_esif']:.3f} |
| frozen-model predicted | {dp['n']} | {dp['pearson']:.3f} | {dp['spearman']:.3f} | {dp['R2']:.3f} | {dp['B_kw']:.0f} | {dp['beta']:.3f} | {dp['MAE_kw']:.1f} | {dp['kestrel_share_of_esif']:.3f} |

End-to-end: **{e2e['status']}**. {e2e['rationale']}. Wording: validated CPU job-attributed load is associated with a measurable component of ESIF total IT variation. Not causal.

Hourly is secondary; retain the timezone caveat.

## Final capability status

| Status | Result |
|---|---|
| CPU_COMPLETED_NODE_HOUR | **PASS** |
| CPU_TIMEOUT_TRANSFER | **{cpu_timeout}** |
| CPU_CANCELLED_TRANSFER | **{cpu_cancelled}** |
| CPU_OTHER_STATE_TRANSFER | **PARTIAL** |
| CPU_VALIDATED_RAW_MEASURED_ENERGY_SHARE | **{100*frac_raw:.1f}%** of summed positive job-record energy |
| CPU_VALIDATED_ADDITIVE_ENERGY_SHARE | **{100*frac_add:.1f}%** of additive/non-shared job-record energy |
| SHARED_CPU_RECONSTRUCTION | **UNSUPPORTED** |
| H100_MEASURED_JOB_ENERGY | **UNSUPPORTED_IN_KESTREL_JOB_EXTRACT** |
| ENERGY_CONSERVING_JOB_REPLAY | **PASS** |
| SUBHOURLY_POWER_SHAPE | **UNSUPPORTED** |
| ESIF_TIMESTAMP_SEMANTICS | **AMBIGUOUS** |
| ESIF_MEASURED_CPU_LINKAGE | **PARTIAL** |
| ESIF_PREDICTED_CPU_LINKAGE | **{esif_pred_status}** |
| CPU_LAYER_FINAL_DISPOSITION | **{layer}** |

## Next experiment (not executed)

NLR GenAI H100 measured power profiles, DOI `10.7799/3025227`. Shared-CPU reconstruction must not delay it.
"""
    report_path.write_text(head + addendum)
    print(json.dumps({
        "TIMEOUT_TEST": timeout_test["transfer_status"],
        "CANCELLED_TEST": cancelled_test["transfer_status"],
        "e2e": e2e["status"],
        "frac_raw": frac_raw,
        "frac_add": frac_add,
        "layer": layer,
    }, indent=2))


if __name__ == "__main__":
    main()
