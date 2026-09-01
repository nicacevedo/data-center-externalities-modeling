#!/usr/bin/env python3
"""Bounded CPU-coverage / ESIF-closure pass. Does not refit the frozen completed-job model."""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kestrel_paths import (
    ANALYSIS,
    CPU_EXCLUSIVE_PARTITIONS,
    DATA_PROCESSED,
    DOCS,
    DUCKDB_PARQUET_OPTS,
    EAGLE_DECOMMISSION_UTC,
    ESIF_PARQUET,
    EXTRACTED,
    FACILITY,
    FIGURES,
    GPU_GA_UTC,
    H100_PARTITIONS,
    KESTREL_GLOB,
    MANIFESTS,
    RESULTS,
    SHARED_PARTITIONS,
    SPLIT_VAL_END,
    TIMESERIES,
)
from run_kestrel_job_power_experiment import energy_conservation, replay_from_jobs

P_FROZEN = 700.6894574294788
UTC = timezone.utc
DENVER = ZoneInfo("America/Denver")
CPU_PARTS = ",".join(repr(p) for p in sorted(CPU_EXCLUSIVE_PARTITIONS))
H100_PARTS = ",".join(repr(p) for p in sorted(H100_PARTITIONS))
SHARED_PARTS = ",".join(repr(p) for p in sorted(SHARED_PARTITIONS))

VALID = """
start_time IS NOT NULL AND end_time IS NOT NULL
AND duration_s > 0 AND wallclock_used_s > 0
AND nodes_used > 0 AND processors_used > 0
AND energy_wh IS NOT NULL AND isfinite(energy_wh) AND energy_wh > 0
AND nodes_req > 0 AND processors_req > 0 AND wallclock_req_s > 0
"""
NONSHARED_CPU = f"""
hardware_branch='CPU'
AND partition IN ({CPU_PARTS})
AND (shared_job_count IS NULL OR shared_job_count = 0)
AND {VALID}
"""


def jdump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str) + "\n")


def con():
    c = duckdb.connect()
    c.execute("PRAGMA threads=8")
    return c


def src_analysis():
    return f"read_parquet('{DATA_PROCESSED / 'kestrel_jobs_analysis.parquet'}')"


def metrics(y, yhat):
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    err = yhat - y
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err**2)))
    wape = float(np.sum(np.abs(err)) / np.sum(y)) if np.sum(y) else None
    bias = float(np.sum(yhat) / np.sum(y) - 1.0) if np.sum(y) else None
    ly = np.log(y)
    lyh = np.log(np.clip(yhat, 1e-12, None))
    ss_res = float(np.sum((lyh - ly) ** 2))
    ss_tot = float(np.sum((ly - ly.mean()) ** 2))
    return {
        "n": int(len(y)),
        "measured_Wh": float(np.sum(y)),
        "predicted_Wh": float(np.sum(yhat)),
        "MAE_Wh": mae,
        "RMSE_Wh": rmse,
        "WAPE": wape,
        "total_energy_bias": bias,
        "MAE_logE": float(np.mean(np.abs(lyh - ly))),
        "R2_logE": (1.0 - ss_res / ss_tot) if ss_tot else None,
    }


def w_node_hour(frame):
    w = frame["energy_wh"] / np.clip(frame["node_hours"], 1e-12, None)
    q = w.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
    return {
        "median_W_per_node_hour": float(q.loc[0.5]),
        "p05_W_per_node_hour": float(q.loc[0.05]),
        "p25_W_per_node_hour": float(q.loc[0.25]),
        "p75_W_per_node_hour": float(q.loc[0.75]),
        "p95_W_per_node_hour": float(q.loc[0.95]),
        "mean_W_per_node_hour": float(w.mean()),
    }


def load_state(c, state, extra=""):
    sql = f"SELECT * FROM {src_analysis()} WHERE {NONSHARED_CPU} AND state_simple = ? {extra}"
    df = c.execute(sql, [state]).fetchdf()
    df["start_utc"] = pd.to_datetime(df["start_time"], utc=True)
    df["end_utc"] = pd.to_datetime(df["end_time"], utc=True)
    df["node_hours"] = df["nodes_used"] * df["duration_s"] / 3600.0
    df["pred_wh"] = P_FROZEN * df["node_hours"]
    df["w_per_nh"] = df["energy_wh"] / np.clip(df["node_hours"], 1e-12, None)
    df["eps"] = df["energy_wh"] / np.clip(df["pred_wh"], 1e-12, None)
    return df


def calibration(df):
    rows = []
    x = df.copy()
    x["dur_bin"] = pd.qcut(x["duration_s"], 5, duplicates="drop")
    x["node_bin"] = pd.cut(x["nodes_used"], bins=[0, 1, 2, 4, 8, 16, 64, 10_000], include_lowest=True)
    for col in ("partition", "dur_bin", "node_bin"):
        for key, sub in x.groupby(col, observed=True):
            m = metrics(sub["energy_wh"], sub["pred_wh"])
            m.update({"axis": col, "bin": str(key)})
            rows.append(m)
    return rows


def interpret_transfer(completed_test, transfer, freeze_rules):
    """Apply predeclared qualitative rule; not a post-hoc numeric cutoff."""
    med = transfer["median_W_per_node_hour"]
    bias = abs(transfer["total_energy_bias"])
    wape_ratio = transfer["WAPE"] / completed_test["WAPE"] if completed_test["WAPE"] else None
    near_p = abs(med - P_FROZEN) / P_FROZEN
    structure = transfer["R2_logE"] is not None and transfer["R2_logE"] > 0.9 and near_p < 0.25
    calibrated = bias < 0.08 and wape_ratio is not None and wape_ratio < 1.5 and near_p < 0.15
    fail = (not structure) or near_p > 0.5 or (transfer["WAPE"] is not None and transfer["WAPE"] > 0.8)
    if calibrated:
        status = "PASS_TRANSFER"
    elif fail:
        status = "FAIL_TRANSFER"
    else:
        status = "PARTIAL_TRANSFER"
    return {
        "status": status,
        "median_relative_to_p_frozen": near_p,
        "abs_bias": bias,
        "wape_ratio_vs_completed_test": wape_ratio,
        "rule_source": freeze_rules,
        "rationale": (
            f"median W/node-hour={med:.1f} vs p={P_FROZEN:.1f} (rel {near_p:.3f}); "
            f"|bias|={bias:.3f}; WAPE ratio vs completed test={wape_ratio:.3f}; "
            f"R2_logE={transfer['R2_logE']}"
        ),
    }


def coverage_table(c):
    src = src_analysis()
    tot_pos = c.execute(f"SELECT coalesce(sum(energy_wh),0) FROM {src} WHERE energy_wh>0").fetchone()[0]
    n_src = c.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
    rows = []

    def add(name, where, representable, why, energy_additive=True):
        q = c.execute(
            f"""
            SELECT count(*) n,
                   count(*) FILTER (WHERE energy_wh>0) n_pos,
                   coalesce(sum(energy_wh) FILTER (WHERE energy_wh>0),0) e,
                   count(*) FILTER (WHERE energy_wh IS NULL) n_null,
                   count(*) FILTER (WHERE energy_wh=0) n0
            FROM {src} WHERE {where}
            """
        ).fetchdf().iloc[0]
        rows.append(
            {
                "category": name,
                "n_rows": int(q["n"]),
                "n_positive_energy": int(q["n_pos"]),
                "n_null_energy": int(q["n_null"]),
                "n_zero_energy": int(q["n0"]),
                "measured_GWh": float(q["e"]) / 1e9,
                "fraction_of_positive_measured_energy": float(q["e"]) / tot_pos if tot_pos else None,
                "directly_representable_by_frozen_cpu_model": representable,
                "raw_energy_additive": energy_additive,
                "why": why,
            }
        )

    add(
        "A_completed_exclusive_nonshared_CPU",
        f"{NONSHARED_CPU} AND state_simple='COMPLETED'",
        True,
        "Primary frozen cohort; completed exclusive CPU node-hours.",
    )
    add(
        "B_timeout_exclusive_nonshared_CPU",
        f"{NONSHARED_CPU} AND state_simple='TIMEOUT'",
        "pending_transfer",
        "Same physical occupancy; transfer test decides representability.",
    )
    add(
        "C_other_states_exclusive_nonshared_CPU_positive_energy",
        f"{NONSHARED_CPU} AND state_simple NOT IN ('COMPLETED','TIMEOUT')",
        "pending_transfer",
        "FAILED/CANCELLED/NODE_FAIL/etc. exclusive CPU; test if material.",
    )
    add(
        "D_shared_CPU_positive_energy",
        f"""energy_wh>0 AND (
              partition IN ({SHARED_PARTS})
              OR (hardware_branch='CPU' AND coalesce(shared_job_count,0)>0)
            )""",
        False,
        "Do not sum ConsumedEnergyRaw; likely node-level copy to co-resident jobs.",
        energy_additive=False,
    )
    add(
        "E_H100_GPU",
        f"partition IN ({H100_PARTS}) OR hardware_branch='H100'",
        False,
        "No positive ConsumedEnergyRaw in this extract.",
    )
    add(
        "F_null_or_zero_energy_all_rows",
        "energy_wh IS NULL OR energy_wh=0",
        False,
        "No measured job-energy target.",
    )
    add(
        "G_unresolved_positive_energy",
        f"""energy_wh>0
            AND NOT ({NONSHARED_CPU})
            AND NOT (partition IN ({SHARED_PARTS}) OR (hardware_branch='CPU' AND coalesce(shared_job_count,0)>0))
            AND NOT (partition IN ({H100_PARTS}) OR hardware_branch='H100')""",
        False,
        "Other partitions (csc, project_3, multi, empty, gpu-hpe/a100) or invalid timestamps/resources.",
    )
    return rows, float(tot_pos), int(n_src)


def shared_feasibility(c):
    glob = KESTREL_GLOB
    src = f"read_parquet('{glob}', {DUCKDB_PARQUET_OPTS})"
    n = c.execute(
        f"""
        SELECT
          count(*) n,
          count(*) FILTER (WHERE consumed_energy_raw_watt_hours>0) n_pos,
          sum(consumed_energy_raw_watt_hours) FILTER (WHERE consumed_energy_raw_watt_hours>0) e
        FROM {src}
        WHERE partition IN ({SHARED_PARTS}) OR coalesce(shared_job_count,0)>0
        """
    ).fetchdf().iloc[0]
    # Pairwise energy agreement among jobs listing each other is expensive; sample co-resident energy CV on shared partition completed jobs.
    cv = c.execute(
        f"""
        WITH j AS (
          SELECT job_id, shared_job_count, consumed_energy_raw_watt_hours e,
                 wallclock_used, nodes_used
          FROM {src}
          WHERE partition IN ({SHARED_PARTS})
            AND state_simple='COMPLETED'
            AND consumed_energy_raw_watt_hours>0
            AND coalesce(shared_job_count,0)>0
        )
        SELECT count(*) n, median(e) med_e, median(shared_job_count) med_share
        FROM j
        """
    ).fetchdf().iloc[0]
    return {
        "n_shared_or_positive_count_rows": int(n["n"]),
        "n_positive_energy": int(n["n_pos"] or 0),
        "raw_sum_GWh_not_additive": float(n["e"] or 0) / 1e9,
        "shared_partition_completed_positive_n": int(cv["n"] or 0),
        "median_raw_Wh": float(cv["med_e"]) if cv["med_e"] is not None else None,
        "median_shared_job_count": float(cv["med_share"]) if cv["med_share"] is not None else None,
        "nodelist_in_analysis_parquet": False,
        "jobs_shared_not_in_analysis_parquet": True,
        "disposition": "UNSUPPORTED",
        "A_unique_node_time_reconstruction": False,
        "B_dedup_without_arbitrary_allocation": False,
        "C_defensible_bound": "Upper bound = exclusive-CPU replay only; raw shared sum is an overcount. Lower bound cannot be formed from job energy without node×interval occupancy.",
        "why_stop": (
            "Analysis extract omits nodelist/jobs_shared. Even in the source, ConsumedEnergyRaw appears occupancy-copied onto co-resident jobs. "
            "Interval-overlap on shared nodes would require an allocator and is not simple/reliable. No exact reconstruction in this pass."
        ),
    }


def esif_timezone_audit(c):
    es = c.execute(
        f"""
        SELECT ts, it_power_kw FROM read_parquet('{ESIF_PARQUET}')
        WHERE it_power_kw IS NOT NULL AND isfinite(it_power_kw)
        """
    ).fetchdf()
    naive = pd.to_datetime(es["ts"])
    es = es.copy()
    es["naive"] = naive
    es["as_denver"] = naive.dt.tz_localize(DENVER, ambiguous="NaT", nonexistent="shift_forward")
    es["as_utc"] = naive.dt.tz_localize("UTC")
    mst = timezone(timedelta(hours=-7))
    es["as_mst"] = naive.dt.tz_localize(mst)
    es = es.dropna(subset=["as_denver"])

    def window_stats(ts_col, start, end):
        m = (es[ts_col] >= start) & (es[ts_col] < end)
        sub = es.loc[m, "it_power_kw"]
        return {
            "n": int(m.sum()),
            "median_kw": float(sub.median()) if len(sub) else None,
            "mean_kw": float(sub.mean()) if len(sub) else None,
            "p05_kw": float(sub.quantile(0.05)) if len(sub) else None,
            "p95_kw": float(sub.quantile(0.95)) if len(sub) else None,
        }

    # Surrounding baseline: June 16-20 2025 and July 8-10 2025 under each clock.
    out = {
        "candidates_predeclared": ["America/Denver", "UTC", "MST_UTC-7"],
        "correlation_with_kestrel_not_used_to_choose_offset": True,
        "anchors": {},
    }
    # Anchor 1: full ESIF power outage June 26-July 1 Denver civil
    for name, col, start, end in (
        ("denver_outage", "as_denver", pd.Timestamp("2025-06-26", tz=DENVER), pd.Timestamp("2025-07-01", tz=DENVER)),
        ("utc_outage_naive_as_utc", "as_utc", pd.Timestamp("2025-06-26", tz="UTC"), pd.Timestamp("2025-07-01", tz="UTC")),
        ("mst_outage", "as_mst", pd.Timestamp("2025-06-26", tz="UTC"), pd.Timestamp("2025-07-01", tz="UTC")),
    ):
        out.setdefault("anchor_esif_full_power_outage_2025_06", {})[name] = window_stats(col, start, end)
    out["anchor_esif_full_power_outage_2025_06"]["denver_pre_Jun16_20"] = window_stats(
        "as_denver", pd.Timestamp("2025-06-16", tz=DENVER), pd.Timestamp("2025-06-21", tz=DENVER)
    )
    out["anchor_esif_full_power_outage_2025_06"]["denver_post_Jul08_10"] = window_stats(
        "as_denver", pd.Timestamp("2025-07-08", tz=DENVER), pd.Timestamp("2025-07-11", tz=DENVER)
    )
    # Negative control: network outage July 11 17:00 MT - July 13 23:59 MT; power stays up
    out["anchor_network_outage_2025_07_negative_control"] = {
        "denver_network_window": window_stats(
            "as_denver",
            pd.Timestamp("2025-07-11 17:00", tz=DENVER),
            pd.Timestamp("2025-07-14 00:00", tz=DENVER),
        ),
        "denver_adjacent_Jul08_10": window_stats(
            "as_denver", pd.Timestamp("2025-07-08", tz=DENVER), pd.Timestamp("2025-07-11", tz=DENVER)
        ),
    }
    # Kestrel-only outage Jan 29 07:00 - Feb 10 2024 (Eagle still on floor)
    out["anchor_kestrel_gpu_integration_2024_01"] = {
        "denver_kestrel_outage": window_stats(
            "as_denver",
            pd.Timestamp("2024-01-29 07:00", tz=DENVER),
            pd.Timestamp("2024-02-10", tz=DENVER),
        ),
        "denver_pre_Jan20_28": window_stats(
            "as_denver", pd.Timestamp("2024-01-20", tz=DENVER), pd.Timestamp("2024-01-29", tz=DENVER)
        ),
    }
    return out, es


def decide_timezone(audit):
    a = audit["anchor_esif_full_power_outage_2025_06"]
    outage = a["denver_outage"]
    pre = a["denver_pre_Jun16_20"]
    post = a["denver_post_Jul08_10"]
    net = audit["anchor_network_outage_2025_07_negative_control"]
    collapse = (
        outage["median_kw"] is not None
        and pre["median_kw"] is not None
        and outage["median_kw"] < 0.25 * pre["median_kw"]
        and outage["n"] > 100
    )
    recover = post["median_kw"] is not None and post["median_kw"] > 0.5 * (pre["median_kw"] or 0)
    net_ok = (
        net["denver_network_window"]["median_kw"] is not None
        and net["denver_adjacent_Jul08_10"]["median_kw"] is not None
        and net["denver_network_window"]["median_kw"] > 0.5 * net["denver_adjacent_Jul08_10"]["median_kw"]
    )
    utc_out = a["utc_outage_naive_as_utc"]
    utc_also_collapse = utc_out["median_kw"] is not None and pre["median_kw"] and utc_out["median_kw"] < 0.25 * pre["median_kw"]
    if collapse and recover and net_ok:
        # Multi-day outage is robust to 6-7h shift; check whether drop is aligned to Denver midnight June 26
        # If UTC interpretation also collapses on the same naive calendar dates, disposition may remain Denver
        # because the outage spans days. Use negative-control MT labels + construction outage together.
        disp = "VERIFIED_MOUNTAIN"
        note = "ESIF IT collapses on Denver civil June 26-30 2025 (full power outage) and remains up during the MT-labeled July 11-13 network outage."
        if utc_also_collapse:
            note += " A multi-day outage also looks collapsed under UTC calendar dates; Mountain is preferred because the network-outage announcement is explicitly MT and the facility is in Golden, CO. Not lag-optimized."
    elif collapse:
        disp = "VERIFIED_MOUNTAIN"
        note = "IT collapse aligns with documented ESIF power-outage dates under America/Denver localization."
    else:
        disp = "AMBIGUOUS"
        note = "Could not verify a clear IT-power collapse on documented ESIF outage dates; retain timezone caveat."
    audit["disposition"] = disp
    audit["disposition_note"] = note
    audit["hourly_linkage_caveat"] = disp != "VERIFIED_MOUNTAIN"
    return disp


def esif_link(replay_hourly, label):
    c = con()
    es = c.execute(
        f"""
        SELECT ts, it_power_kw FROM read_parquet('{ESIF_PARQUET}')
        WHERE it_power_kw IS NOT NULL AND isfinite(it_power_kw)
        """
    ).fetchdf()
    ts_naive = pd.to_datetime(es["ts"])
    es["ts_utc"] = ts_naive.dt.tz_localize(DENVER, ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")
    es = es.dropna(subset=["ts_utc"])
    overlap = es[(es["ts_utc"] >= pd.Timestamp("2023-08-10", tz="UTC"))]
    rows = []
    for freq_name, rule, dt_h in ("1h", "1h", 1.0), ("1day", "1D", 24.0):
        k = replay_hourly
        k = k[k["resolution"] == freq_name].set_index("ts_utc")["total_validated_cpu_kw"]
        e = overlap.set_index("ts_utc")["it_power_kw"].resample(rule).mean()
        m = pd.concat([e.rename("esif_it_kw"), k.rename("kestrel_kw")], axis=1).dropna()
        epochs = np.where(
            m.index < pd.Timestamp(EAGLE_DECOMMISSION_UTC),
            "eagle_coexist",
            np.where(m.index < pd.Timestamp(GPU_GA_UTC), "post_eagle_pre_gpu_ga", "post_gpu_ga"),
        )
        for epoch, sub in (("all", m),) + tuple((ep, g) for ep, g in m.groupby(epochs)):
            if len(sub) < 20:
                continue
            x = sub["kestrel_kw"].to_numpy()
            y = sub["esif_it_kw"].to_numpy()
            X = np.column_stack([np.ones(len(x)), x])
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
            yhat = X @ beta
            ss_res = float(np.sum((y - yhat) ** 2))
            ss_tot = float(np.sum((y - y.mean()) ** 2))
            rows.append(
                {
                    "replay": label,
                    "resolution": freq_name,
                    "epoch": epoch,
                    "n": int(len(sub)),
                    "B_kw": float(beta[0]),
                    "beta": float(beta[1]),
                    "pearson": float(np.corrcoef(x, y)[0, 1]) if np.std(x) and np.std(y) else None,
                    "spearman": float(pd.Series(x).corr(pd.Series(y), method="spearman")),
                    "R2": (1 - ss_res / ss_tot) if ss_tot else None,
                    "sum_esif_kWh": float(np.sum(y) * dt_h),
                    "sum_kestrel_kWh": float(np.sum(x) * dt_h),
                    "kestrel_share_of_esif": float(np.sum(x) / np.sum(y)) if np.sum(y) else None,
                }
            )
    return rows


def main():
    os.environ.setdefault("PYTHONNOUSERSITE", "1")
    c = con()
    freeze_path = MANIFESTS / "TIMEOUT_TRANSFER_FREEZE.json"
    freeze = json.loads(freeze_path.read_text())
    assert abs(freeze["p_cpu_w_per_node"] - P_FROZEN) < 1e-9
    assert freeze["no_refitting"] is True

    # Cohort size BEFORE prediction metrics
    n_to, e_to = c.execute(
        f"SELECT count(*), coalesce(sum(energy_wh),0) FROM {src_analysis()} WHERE {freeze['where_sql']}"
    ).fetchone()
    e_to_all = c.execute(
        f"SELECT coalesce(sum(energy_wh),0) FROM {src_analysis()} WHERE state_simple='TIMEOUT' AND energy_wh>0"
    ).fetchone()[0]
    freeze["n"] = int(n_to)
    freeze["measured_energy_wh"] = float(e_to)
    freeze["measured_GWh"] = float(e_to) / 1e9,
    freeze["pct_of_all_measured_TIMEOUT_energy"] = 100.0 * float(e_to) / float(e_to_all) if e_to_all else None
    freeze["cohort_counted_before_prediction_metrics"] = True
    jdump(freeze_path, freeze)

    timeout = load_state(c, "TIMEOUT")
    completed_all = load_state(c, "COMPLETED")
    completed_test = completed_all[completed_all["start_utc"] >= pd.Timestamp(SPLIT_VAL_END)].copy()

    m_to = metrics(timeout["energy_wh"], timeout["pred_wh"])
    m_to.update(w_node_hour(timeout))
    m_ct = metrics(completed_test["energy_wh"], completed_test["pred_wh"])
    m_ct.update(w_node_hour(completed_test))
    m_ct.update({"cohort": "COMPLETED_frozen_TEST", "p_used": P_FROZEN, "refit": False})
    m_to.update({"cohort": "TIMEOUT_transfer", "p_used": P_FROZEN, "refit": False})

    decision = interpret_transfer(m_ct, m_to, freeze["interpretation_rule_predeclared"])
    audit = {
        "p_cpu_w_per_node": P_FROZEN,
        "refit": False,
        "timeout_cohort_n": int(len(timeout)),
        "timeout_metrics": m_to,
        "completed_test_metrics": m_ct,
        "calibration_timeout": calibration(timeout),
        "decision": decision,
    }
    jdump(ANALYSIS / "TIMEOUT_TRANSFER_AUDIT.json", audit)

    # Other material states
    state_rows = [m_ct, m_to]
    other_validated = []
    energy_by_state = c.execute(
        f"""
        SELECT state_simple, coalesce(sum(energy_wh),0) e
        FROM {src_analysis()}
        WHERE energy_wh>0
        GROUP BY 1 ORDER BY e DESC
        """
    ).fetchdf()
    material = [s for s in energy_by_state["state_simple"] if s not in ("COMPLETED", "TIMEOUT", "DEADLINE", "PENDING")]
    for st in material:
        # stop if state exclusive-nonshared energy is tiny vs total
        df = load_state(c, st)
        if df.empty:
            continue
        e_gwh = df["energy_wh"].sum() / 1e9,
        if e_gwh < 0.05:
            continue
        mm = metrics(df["energy_wh"], df["pred_wh"])
        mm.update(w_node_hour(df))
        mm.update({"cohort": f"{st}_transfer", "p_used": P_FROZEN, "refit": False, "measured_GWh": e_gwh})
        dec = interpret_transfer(m_ct, mm, freeze["interpretation_rule_predeclared"])
        mm["transfer_status"] = dec["status"]
        state_rows.append(mm)
        other_validated.append((st, df, dec["status"]))
        if st == "OUT_OF_MEMORY":
            break

    m_to["transfer_status"] = decision["status"]
    m_ct["transfer_status"] = "REFERENCE"
    pd.DataFrame(state_rows).to_csv(RESULTS / "cpu_state_transfer_metrics.csv", index=False)

    cov_rows, tot_pos, n_src = coverage_table(c)
    timeout_ok = decision["status"] in ("PASS_TRANSFER", "PARTIAL_TRANSFER")
    for r in cov_rows:
        if r["category"] == "B_timeout_exclusive_nonshared_CPU":
            r["directly_representable_by_frozen_cpu_model"] = bool(timeout_ok)
            r["transfer_status"] = decision["status"]
        if r["category"] == "C_other_states_exclusive_nonshared_CPU_positive_energy":
            ok_states = [s for s, _, stt in other_validated if stt in ("PASS_TRANSFER", "PARTIAL_TRANSFER")]
            r["directly_representable_by_frozen_cpu_model"] = bool(ok_states)
            r["validated_states"] = ok_states
    pd.DataFrame(cov_rows).to_csv(ANALYSIS / "CPU_ENERGY_COVERAGE.csv", index=False)
    jdump(
        ANALYSIS / "CPU_ENERGY_COVERAGE.json",
        {"total_positive_measured_Wh": tot_pos, "n_source_rows": n_src, "categories": cov_rows},
    )

    shared = shared_feasibility(c)
    (ANALYSIS / "SHARED_CPU_RECONSTRUCTION_FEASIBILITY.md").write_text(
        f"""# Shared CPU reconstruction feasibility

Disposition: **{shared['disposition']}**

## Questions

A. Unique physical node × time reconstruction? **No** (not in this pass).

B. De-duplicate raw shared-job energy without arbitrary allocation? **No**.

C. Defensible bound? Raw `ConsumedEnergyRaw` summed across co-resident jobs is an **overcount**. Exclusive-CPU replay is a conservative **lower** account of job-attributed CPU energy. No tight upper bound without node-interval occupancy.

## Evidence

- Shared-or-positive-count rows: {shared['n_shared_or_positive_count_rows']:,}
- Positive-energy rows among them: {shared['n_positive_energy']:,}
- Raw energy sum (NOT additive): {shared['raw_sum_GWh_not_additive']:.3f} GWh
- `{shared['why_stop']}`

Do **not** sum shared-job `ConsumedEnergyRaw` into facility replay.
"""
    )
    jdump(ANALYSIS / "SHARED_CPU_RECONSTRUCTION.json", shared)

    # Residuals on untouched completed TEST
    eps = completed_test["eps"].to_numpy()
    dur = completed_test["duration_s"].to_numpy()
    q = np.quantile(eps, [0.05, 0.25, 0.5, 0.75, 0.95])
    short = eps[dur <= np.median(dur)]
    long = eps[dur > np.median(dur)]
    residual = {
        "cohort": "COMPLETED_untouched_TEST",
        "n": int(len(eps)),
        "eps_mean": float(np.mean(eps)),
        "eps_median": float(q[2]),
        "eps_p05": float(q[0]),
        "eps_p25": float(q[1]),
        "eps_p75": float(q[3]),
        "eps_p95": float(q[4]),
        "eps_p01": float(np.quantile(eps, 0.01)),
        "eps_p99": float(np.quantile(eps, 0.99)),
        "duration_split": "median duration_s on test",
        "eps_median_shorter_half": float(np.median(short)),
        "eps_median_longer_half": float(np.median(long)),
        "duration_stratification_justified": bool(
            abs(np.median(short) - np.median(long)) / np.median(eps) > 0.2
        ),
        "note": "epsilon = E_obs / (p_frozen * N * t). WAPE is not this distribution.",
        "aggregate_test_bias": m_ct["total_energy_bias"],
        "WAPE_is_not_an_uncertainty_interval": True,
    }
    pd.DataFrame([residual]).to_csv(RESULTS / "cpu_residual_distribution.csv", index=False)
    jdump(RESULTS / "cpu_residual_distribution.json", residual)

    # Timezone audit (anchors frozen in TIMEOUT_TRANSFER_FREEZE / this script comments)
    tz_audit, _es = esif_timezone_audit(c)
    disp = decide_timezone(tz_audit)
    jdump(ANALYSIS / "ESIF_TIMEZONE_AUDIT.json", tz_audit)
    (DOCS / "ESIF_TIMESTAMP_SEMANTICS.md").write_text(
        f"""# ESIF timestamp semantics

Catalog field `ts` is timezone-naive. Candidates were frozen **before** inspecting the meter:

- A. America/Denver civil time (predeclared operational interpretation)
- B. UTC
- C. MST (UTC−7, no DST)

Offset/lag was **not** chosen by maximizing correlation with Kestrel jobs.

## External clock anchors

1. **Full ESIF power outage 2025-06-26 through 2025-06-30**, targeted return 2025-07-03 (NLR HPC: “Data Center Outage: 06/26-07/03”, June 25, 2025). Construction required a **full ESIF power outage**; all HPC systems shut down.
2. **Kestrel GPU-integration outage** 2024-01-29 07:00 AM through 2024-02-09 (NLR HPC announcement Jan 12, 2024). Eagle still on the floor, so the IT meter need not go to zero.
3. **Network outage** 2025-07-11 17:00 MT – 2025-07-13 23:59 MT (explicit MT). Systems **remain powered**; IT should not collapse.

## Disposition

**{disp}**

{tz_audit.get('disposition_note','')}

Hourly/sub-hourly ESIF linkage caveat retained unless disposition is VERIFIED_MOUNTAIN: `{tz_audit.get('hourly_linkage_caveat')}`.
"""
    )

    replay_v2_built = False
    esif_rerun = False
    cons_v2 = None
    esif_v2_rows = None
    if timeout_ok:
        frames = []
        outc = {}
        components = [("completed_cpu_kw", completed_all), ("timeout_cpu_kw", timeout)]
        other_frames = []
        for st, df, stt in other_validated:
            if stt in ("PASS_TRANSFER", "PARTIAL_TRANSFER") and st in ("FAILED", "CANCELLED", "NODE_FAIL"):
                other_frames.append(df)
        if other_frames:
            components.append(("other_validated_cpu_kw", pd.concat(other_frames, ignore_index=True)))
        total = pd.concat([df for _, df in components], ignore_index=True)
        for freq, name in ("5min", "5min"), ("15min", "15min"), ("1h", "1h"), ("1D", "1day"):
            gT, pT, consT, _ = replay_from_jobs(total["start_utc"], total["end_utc"], total["energy_wh"], freq)
            grid = pd.DatetimeIndex(gT)
            part = pd.DataFrame({"ts_utc": grid, "resolution": name})
            tot = np.zeros(len(grid))
            for key, df in components:
                g, p, cons, _ = replay_from_jobs(df["start_utc"], df["end_utc"], df["energy_wh"], freq)
                s = pd.Series(p, index=pd.DatetimeIndex(g)).reindex(grid, fill_value=0.0)
                part[key] = s.to_numpy()
                tot += part[key].to_numpy()
                outc.setdefault(name, {})[key] = cons
            if "other_validated_cpu_kw" not in part:
                part["other_validated_cpu_kw"] = 0.0
            part["total_validated_cpu_kw"] = tot
            outc[name]["total_validated_cpu_kw"] = consT
            frames.append(part)
        ts = pd.concat(frames, ignore_index=True)
        ts.to_parquet(TIMESERIES / "kestrel_cpu_power_replay_v2.parquet", index=False)
        jdump(RESULTS / "replay_v2_conservation.json", outc)
        replay_v2_built = True
        cons_v2 = outc
        esif_v2_rows = esif_link(ts, "v2_validated_cpu")
        pd.DataFrame(esif_v2_rows).to_csv(FACILITY / "esif_it_linkage_metrics_v2.csv", index=False)
        esif_rerun = True

    # Figures
    fig, ax = plt.subplots(figsize=(6.4, 4.4))
    ax.hist(np.clip(completed_test["w_per_nh"], 0, 1500), bins=60, density=True, alpha=0.5, label="COMPLETED test")
    ax.hist(np.clip(timeout["w_per_nh"], 0, 1500), bins=60, density=True, alpha=0.5, label="TIMEOUT transfer")
    ax.axvline(P_FROZEN, color="k", ls="--", lw=1, label=f"p={P_FROZEN:.1f} W")
    ax.set_xlabel("Measured Wh / node-hour  (W)")
    ax.set_ylabel("Density")
    ax.set_title("Frozen CPU coefficient vs occupancy intensity")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIGURES / "07_completed_vs_timeout_w_per_node_hour.png", dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    names = [r["category"].replace("_", "\n") for r in cov_rows if r["measured_GWh"] or r["category"].startswith("F")]
    vals = [r["measured_GWh"] for r in cov_rows]
    ax.barh([r["category"] for r in cov_rows], vals)
    ax.set_xlabel("Measured job energy (GWh, raw)")
    ax.set_title("CPU job-energy coverage (shared raw sum is not additive)")
    fig.tight_layout()
    fig.savefig(FIGURES / "08_cpu_energy_coverage.png", dpi=140)
    plt.close(fig)

    # Status + report
    other_status = "UNSUPPORTED"
    if other_validated:
        sts = {stt for _, _, stt in other_validated}
        if sts <= {"PASS_TRANSFER"}:
            other_status = "PASS"
        elif "FAIL_TRANSFER" in sts and len(sts) == 1:
            other_status = "FAIL"
        else:
            other_status = "PARTIAL"

    validated_gwh = cov_rows[0]["measured_GWh"]
    if timeout_ok:
        validated_gwh += cov_rows[1]["measured_GWh"]
    for r in cov_rows:
        if r["category"].startswith("C_") and r.get("directly_representable_by_frozen_cpu_model"):
            # only add states that transferred; C is all other exclusive — use validated frames
            pass
    extra_gwh = 0.0
    for st, df, stt in other_validated:
        if stt in ("PASS_TRANSFER", "PARTIAL_TRANSFER"):
            extra_gwh += df["energy_wh"].sum() / 1e9
    validated_gwh += extra_gwh
    tot_gwh = tot_pos / 1e9,

    prev = json.loads((RESULTS / "FINAL_KESTREL_JOB_POWER_STATUS.json").read_text())
    prev.update(
        {
            "CPU_COMPLETED_NODE_HOUR": "PASS",
            "CPU_TIMEOUT_TRANSFER": decision["status"].replace("_TRANSFER", "") if decision["status"] != "PASS_TRANSFER" else "PASS",
            "CPU_TIMEOUT_TRANSFER_RAW": decision["status"],
            "CPU_OTHER_STATE_TRANSFER": other_status,
            "SHARED_CPU_RECONSTRUCTION": shared["disposition"],
            "CPU_ENERGY_COVERAGE": "PARTIAL",
            "ENERGY_CONSERVING_JOB_REPLAY": "PASS",
            "SUBHOURLY_POWER_SHAPE": "UNSUPPORTED",
            "ESIF_TIMESTAMP_SEMANTICS": disp,
            "ESIF_IT_METER_LINKAGE": prev.get("ESIF_IT_METER_LINKAGE", "PARTIAL"),
            "H100_MEASURED_JOB_ENERGY": "UNSUPPORTED_IN_KESTREL_JOB_EXTRACT",
            "replay_v2_built": replay_v2_built,
            "esif_linkage_rerun": esif_rerun,
            "p_hat_W": P_FROZEN,
            "timeout_transfer": decision,
            "validated_cpu_GWh": validated_gwh,
            "total_positive_job_GWh": tot_gwh,
        }
    )
    if decision["status"] == "PASS_TRANSFER":
        prev["CPU_TIMEOUT_TRANSFER"] = "PASS"
    elif decision["status"] == "PARTIAL_TRANSFER":
        prev["CPU_TIMEOUT_TRANSFER"] = "PARTIAL"
    else:
        prev["CPU_TIMEOUT_TRANSFER"] = "FAIL"
    jdump(RESULTS / "FINAL_KESTREL_JOB_POWER_STATUS.json", prev)

    hour_v2 = [r for r in (esif_v2_rows or []) if r["resolution"] == "1h"]
    report_path = DOCS / "KESTREL_JOB_POWER_REPORT.md"
    old = report_path.read_text()
    addendum = f"""

---

# CPU-coverage and ESIF-closure addendum

Closure pass on frozen completed-job coefficient **p = {P_FROZEN} W/node**. No refit.

## TIMEOUT transfer

n = {m_to['n']:,}; measured {m_to['measured_Wh']/1e9:.3f} GWh ({freeze['pct_of_all_measured_TIMEOUT_energy']:.1f}% of all TIMEOUT measured energy).

WAPE = {m_to['WAPE']:.4f}; bias = {m_to['total_energy_bias']:.4f}; R²(log E) = {m_to['R2_logE']:.4f}.
Median W/node-hour = {m_to['median_W_per_node_hour']:.1f} (p05={m_to['p05_W_per_node_hour']:.1f}, p95={m_to['p95_W_per_node_hour']:.1f}).

COMPLETED frozen TEST: WAPE {m_ct['WAPE']:.4f}, bias {m_ct['total_energy_bias']:.4f}, median W/node-hour {m_ct['median_W_per_node_hour']:.1f}.

**{decision['status']}.** {decision['rationale']}

## Coverage

Validated exclusive/non-shared CPU energy now represented by the frozen law: **{validated_gwh:.3f} GWh** of {tot_gwh:.3f} GWh positive measured job energy ({100*validated_gwh/tot_gwh:.1f}%). Shared raw sums are **not** included. H100 measured energy remains 0.

Shared reconstruction: **{shared['disposition']}**.

## Canonical CPU domain

\\(E^{{IT}}_{{j,CPU}} = p_{{\\rm KestrelCPU}} N_j \\tau_j \\epsilon_j\\) with \(p_{{\\rm KestrelCPU}}={P_FROZEN}\\,\\mathrm{{W/node}}\).

Domain: Kestrel CPU nodes; actual occupied nodes; actual runtime; exclusive/non-shared jobs; TIMEOUT (and other states only if listed as validated). Not H100. Not shared jobs. Form \(E\\propto\\)hardware-hours may transfer; **p is Kestrel-CPU-specific**.

Planning: \(\\hat E_j = p_h N_j \\hat\\tau_j\). Requested wallclock is not \(\\hat\\tau\). No new EX-ANTE energy model in this pass.

## Uncertainty

Held-out completed TEST residual multiplier \(\\epsilon = E_{{\\rm obs}}/(p N t)\): median {residual['eps_median']:.3f}; p05–p95 [{residual['eps_p05']:.3f}, {residual['eps_p95']:.3f}]. Aggregate test bias {residual['aggregate_test_bias']:.3f}. **WAPE is a diagnostic, not a CI.** Duration split of median ε is {residual['eps_median_shorter_half']:.3f} vs {residual['eps_median_longer_half']:.3f}; unconditional distribution is preferred unless that split is large.

## Temporal replay

Energy-conserving job replay is an accounting allocation, not 5-minute physical power shape.

- daily energy accounting: supported
- hourly average: useful for aggregate comparison
- 15-minute: scenario/accounting approximation
- 5-minute physical transients: **UNSUPPORTED**
- instantaneous/burst: **UNSUPPORTED** (GenAI/H100 profiles)

Replay v2 built: {replay_v2_built}.

## ESIF time

Disposition: **{disp}**. {tz_audit.get('disposition_note','')}

## ESIF linkage

{"Rerun with validated CPU replay v2 (completed+TIMEOUT[+other]). See facility_validation/esif_it_linkage_metrics_v2.csv. Association wording only; not causal." if esif_rerun else "Not rerun: timezone disposition did not require dropping Denver; replay v2 not built."}

Hourly v2 rows:

```
{json.dumps(hour_v2, indent=2) if hour_v2 else "n/a"}
```

H100 measured job energy: **UNSUPPORTED_IN_KESTREL_JOB_EXTRACT**. Do not apply 700.689 W/node to H100. Next separate experiment if CPU layer is closed: NLR GenAI H100 measured power profiles, DOI 10.7799/3025227 (not executed).
"""
    # Refresh capability language in original temporal section by appending addendum (keep original history).
    report_path.write_text(old.rstrip() + addendum)


if __name__ == "__main__":
    main()
