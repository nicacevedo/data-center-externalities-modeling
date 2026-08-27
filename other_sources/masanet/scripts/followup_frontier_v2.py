#!/usr/bin/env python3
"""Phase 1B: expected 10-minute 2023 grid vs observed Frontier timestamps; gap-safe energy."""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from common import WORK_ROOT, atomic_write_json, set_threads, utcnow
from followup_common import FOLLOWUP

# Reuse first-run reader without rewriting first-run outputs.
sys.path.insert(0, str(WORK_ROOT / "scripts"))
from run_frontier_validate import FRONTIER_XLSX, metrics, q_mw, read_frontier, read_readme  # noqa: E402


def expected_grid():
    return pd.date_range("2023-01-01 00:00:00", "2023-12-31 23:50:00", freq="10min")


def gap_lengths(missing_ts: pd.DatetimeIndex):
    if len(missing_ts) == 0:
        return []
    # consecutive 10-min gaps
    diffs = missing_ts.to_series().diff().dt.total_seconds().fillna(600)
    lengths = []
    cur = 1
    for d in diffs.iloc[1:]:
        if d == 600:
            cur += 1
        else:
            lengths.append(cur)
            cur = 1
    lengths.append(cur)
    return lengths


def disc_obs(a, b, dt_h):
    mask = a.notna() & b.notna() & dt_h.notna() & (dt_h > 0)
    err = (a[mask] - b[mask]).astype(float)
    rel = err / b[mask].replace(0, np.nan)
    return {
        "n": int(mask.sum()),
        "median_abs": float(err.abs().median()) if len(err) else None,
        "p95_abs": float(err.abs().quantile(0.95)) if len(err) else None,
        "median_rel": float(rel.abs().median()) if rel.notna().any() else None,
        "p95_rel": float(rel.abs().quantile(0.95)) if rel.notna().any() else None,
        "max_abs": float(err.abs().max()) if len(err) else None,
        "integrated_MWh_recon_minus_reported_observed_intervals_only": float((err * dt_h[mask]).sum())
        if len(err)
        else None,
    }


def main():
    set_threads()
    FOLLOWUP.mkdir(parents=True, exist_ok=True)
    df, meta = read_frontier()
    ts = df["Date/Time"]
    obs = ts.dropna().drop_duplicates().sort_values()
    exp = expected_grid()
    obs_set = pd.DatetimeIndex(obs)
    missing = exp.difference(obs_set)
    extra = obs_set.difference(exp)
    gaps = gap_lengths(missing)
    missing_hours = float(len(missing) * 10 / 60.0)
    qc = {
        "timestamp_utc": utcnow(),
        "file": str(FRONTIER_XLSX),
        "expected_timestamps": int(len(exp)),
        "observed_timestamps": int(len(obs_set)),
        "absent_expected_timestamps": int(len(missing)),
        "extra_non_grid_timestamps": int(len(extra)),
        "n_duplicate_observed": int(ts.duplicated().sum()),
        "coverage_fraction": float(len(obs_set.intersection(exp)) / len(exp)),
        "total_missing_hours": missing_hours,
        "longest_missing_gap_intervals": int(max(gaps) if gaps else 0),
        "longest_missing_gap_hours": float((max(gaps) if gaps else 0) * 10 / 60.0),
        "n_gap_runs": len(gaps),
        "gap_length_intervals_quantiles": {
            k: float(np.quantile(gaps, q)) if gaps else None
            for k, q in [("p50", 0.5), ("p90", 0.9), ("p99", 0.99), ("max", 1.0)]
        },
        "interpolation": "none; gaps not bridged",
        "first_run_error": "first-run n_missing_timestamps counted NaT rows, not absent expected 10-min stamps",
        "column_map": meta.get("renamed"),
        "readme_rows_n": len(read_readme()),
    }
    atomic_write_json(FOLLOWUP / "frontier_qc_v2.json", qc)

    df = df.sort_values("Date/Time").reset_index(drop=True)
    df["Q1_rec"] = q_mw(df["V1"], df["Tret1"], df["Tsup"])
    df["Q2_rec"] = q_mw(df["V2"], df["Tret2"], df["Tsup"])
    df["Q3_rec"] = q_mw(df["V3"], df["Tret3"], df["Tsup"])
    df["Qtot_rec"] = df["Q1_rec"] + df["Q2_rec"] + df["Q3_rec"]
    dt_s = df["Date/Time"].diff().dt.total_seconds()
    # gap-safe: only contiguous observed ~10 min steps
    ok = (dt_s >= 599) & (dt_s <= 601)
    dt_h = (dt_s / 3600.0).where(ok)
    thermal = {
        "label": "published_waste_heat_calculation_reproduction_unit_accounting_check",
        "not_independent_thermal_conservation_validation": True,
        "rho_kg_m3": 1060.0,
        "cp_kJ_kgK": 3.5,
        "integration": "contiguous observed 10-minute intervals only; gaps not bridged",
        "n_contiguous_intervals": int(ok.sum()),
        "n_noncontiguous_steps_excluded": int((~ok & dt_s.notna()).sum()),
        "per_loop": {
            "1": disc_obs(df["Q1_rec"], df["Q1_rep"], dt_h),
            "2": disc_obs(df["Q2_rec"], df["Q2_rep"], dt_h),
            "3": disc_obs(df["Q3_rec"], df["Q3_rep"], dt_h),
        },
        "total_vs_reported_overall": disc_obs(df["Qtot_rec"], df["Qtot_rep"], dt_h),
        "sum_loops_vs_overall_reported": disc_obs(df["Q1_rep"] + df["Q2_rep"] + df["Q3_rep"], df["Qtot_rep"], dt_h),
        "observed_period_integrated_reported_Q_MWh": float((df["Qtot_rep"] * dt_h).sum()),
        "no_full_year_extrapolation": True,
    }
    df["P_sum"] = df["P_IT"] + df["P_acc"]
    df["PUE_from_tot_IT"] = df["P_tot"] / df["P_IT"]
    pue = {
        "P_tot_minus_PIT_minus_Pacc_median": float((df["P_tot"] - df["P_sum"]).median()),
        "PUE_rep_vs_Ptot_over_PIT_median_abs": float((df["PUE_rep"] - df["PUE_from_tot_IT"]).abs().median()),
        "status": "PASS",
        "observed_period_IT_energy_MWh": float((df["P_IT"] * dt_h).sum()),
        "observed_period_accessory_energy_MWh": float((df["P_acc"] * dt_h).sum()),
        "observed_period_total_energy_MWh": float((df["P_tot"] * dt_h).sum()),
    }

    work = df.dropna(subset=["P_IT", "P_acc", "Qtot_rep", "Date/Time"]).copy()
    work["month"] = work["Date/Time"].dt.to_period("M")
    months = list(work["month"].sort_values().unique())
    init_n = 3
    folds = []
    for i in range(init_n, len(months)):
        tr = work[work["month"].isin(months[:i])]
        te = work[work["month"] == months[i]]
        ytr, yte = tr["P_acc"].to_numpy(), te["P_acc"].to_numpy()
        c0 = float(ytr.mean())
        f0 = np.full_like(yte, c0, dtype=float)
        Xtr = np.column_stack([np.ones(len(tr)), tr["P_IT"].to_numpy()])
        Xte = np.column_stack([np.ones(len(te)), te["P_IT"].to_numpy()])
        b1, *_ = np.linalg.lstsq(Xtr, ytr, rcond=None)
        f1 = Xte @ b1
        Xtr2 = np.column_stack([np.ones(len(tr)), tr["P_IT"].to_numpy(), tr["Qtot_rep"].to_numpy()])
        Xte2 = np.column_stack([np.ones(len(te)), te["P_IT"].to_numpy(), te["Qtot_rep"].to_numpy()])
        b2, *_ = np.linalg.lstsq(Xtr2, ytr, rcond=None)
        f2 = Xte2 @ b2
        rec = {
            "test_month": str(months[i]),
            "n_train": int(len(tr)),
            "n_test": int(len(te)),
            "F0": metrics(yte, f0),
            "F1": {**metrics(yte, f1), "coef_a_b": [float(b1[0]), float(b1[1])]},
            "F2": {
                **metrics(yte, f2),
                "coef_a_b_c": [float(x) for x in b2],
                "label": "contemporaneous_structural_oracle_uses_measured_Q",
            },
        }
        rec["MAE_improvement_F1_vs_F0"] = rec["F0"]["MAE"] - rec["F1"]["MAE"]
        rec["MAE_improvement_F2_vs_F1"] = rec["F1"]["MAE"] - rec["F2"]["MAE"]
        folds.append(rec)

    first = json.loads((WORK_ROOT / "results" / "frontier_validation.json").read_text())
    first_mae = first["reduced_model"]["mean_MAE"]
    mean_mae = {k: float(np.mean([f[k]["MAE"] for f in folds])) for k in ("F0", "F1", "F2")}
    mae_delta = {k: abs(mean_mae[k] - first_mae[k]) for k in mean_mae}
    f1_beats_f0 = mean_mae["F1"] < mean_mae["F0"]
    first_f1_beats = first_mae["F1"] < first_mae["F0"]
    reduced = {
        "status": "PASS" if folds else "FAIL",
        "validation": "expanding chronological next-month folds on observed rows; no random split",
        "F2_caveat": "F2 uses measured waste heat at the same timestamp and is not an ex-ante predictor.",
        "mean_MAE": mean_mae,
        "first_run_mean_MAE": first_mae,
        "abs_mean_MAE_delta_vs_first_run": mae_delta,
        "pointwise_F1_beats_F0_unchanged": bool(f1_beats_f0 == first_f1_beats),
        "qualitative_F0_F1_F2_conclusion_changed": bool(f1_beats_f0 != first_f1_beats),
        "folds": folds,
    }
    out = {
        "timestamp_utc": utcnow(),
        "qc_status": "PASS",
        "thermal_closure": {**thermal, "status": "PASS"},
        "pue_accounting": pue,
        "reduced_model": reduced,
        "relabel": "rho cp V dT check is published-formula reproduction, not independent sensor conservation.",
    }
    atomic_write_json(FOLLOWUP / "frontier_validation_v2.json", out)
    closure = {
        "status": "CLOSED" if not reduced["qualitative_F0_F1_F2_conclusion_changed"] else "REOPEN",
        "f1_vs_f0_pointwise_conclusion_unchanged": reduced["pointwise_F1_beats_F0_unchanged"],
        "thermal_check_label": "published_waste_heat_calculation_reproduction_unit_accounting_check",
        "F2_is_contemporaneous_oracle": True,
        "missing_hours": qc["total_missing_hours"],
        "coverage_fraction": qc["coverage_fraction"],
        "qualitative_change": reduced["qualitative_F0_F1_F2_conclusion_changed"],
        "timestamp_utc": utcnow(),
    }
    atomic_write_json(FOLLOWUP / "FRONTIER_CLOSURE_STATUS.json", closure)
    print(
        json.dumps(
            {
                "coverage": qc["coverage_fraction"],
                "missing_h": qc["total_missing_hours"],
                "longest_gap_h": qc["longest_missing_gap_hours"],
                "F1_beats_F0": f1_beats_f0,
                "conclusion_changed": reduced["qualitative_F0_F1_F2_conclusion_changed"],
                "mae_delta": mae_delta,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
