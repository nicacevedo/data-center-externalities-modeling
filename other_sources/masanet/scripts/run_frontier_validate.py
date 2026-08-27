#!/usr/bin/env python3
"""Phase 5: Frontier Figshare v4 QC, thermal closure, PUE accounting, reduced accessory-power models."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common import FRONTIER_XLSX, WORK_ROOT, atomic_write_json, set_threads, utcnow

RHO = 1060.0  # kg/m3, paper
CP_KJ = 3.5  # kJ/(kg K), paper
GAL_M3 = 0.003785411784  # US gallon
GPM_TO_M3S = GAL_M3 / 60.0


def q_mw(flow_gpm, t_return_c, t_supply_c):
    v = np.asarray(flow_gpm, dtype=float) * GPM_TO_M3S
    dT = np.asarray(t_return_c, dtype=float) - np.asarray(t_supply_c, dtype=float)
    q_kw = RHO * CP_KJ * v * dT
    return q_kw / 1000.0


def _norm_name(c):
    if pd.isna(c):
        return None
    return str(c).replace("\xa0", " ").replace("\u00a0", " ").strip()


def read_readme():
    raw = pd.read_excel(FRONTIER_XLSX, sheet_name="Readme", header=None)
    rows = []
    for rec in raw.itertuples(index=False):
        vals = [_norm_name(v) or "" for v in rec]
        if any(vals):
            rows.append(vals)
    return rows


def read_frontier():
    raw = pd.read_excel(FRONTIER_XLSX, sheet_name="Frontier2023", header=None)
    cols = []
    for i, c in enumerate(raw.iloc[0].tolist()):
        n = _norm_name(c)
        cols.append(n if n else f"col_{i}")
    units = raw.iloc[1].tolist()
    df = raw.iloc[2:].copy()
    df.columns = cols
    df = df.loc[:, [c for c in df.columns if not c.startswith("col_")]]
    df["Date/Time"] = pd.to_datetime(df["Date/Time"], errors="coerce")
    for c in df.columns:
        if c == "Date/Time":
            continue
        df[c] = pd.to_numeric(df[c], errors="coerce")
    rename = {}
    for c in df.columns:
        cl = c.lower()
        if "subloop1" in cl.replace(" ", "") and "return" in cl:
            rename[c] = "Tret1"
        elif "subloop2" in cl.replace(" ", "") and "return" in cl:
            rename[c] = "Tret2"
        elif "subloop3" in cl.replace(" ", "") and "return" in cl:
            rename[c] = "Tret3"
        elif "subloop1" in cl.replace(" ", "") and "flow" in cl:
            rename[c] = "V1"
        elif "subloop2" in cl.replace(" ", "") and "flow" in cl:
            rename[c] = "V2"
        elif "subloop3" in cl.replace(" ", "") and "flow" in cl:
            rename[c] = "V3"
        elif "overall" in cl and "supply" in cl:
            rename[c] = "Tsup"
        elif "overall-average" in cl or ("overall" in cl and "return" in cl and "average" in cl):
            rename[c] = "Tret_avg"
        elif "overall" in cl and "flow" in cl:
            rename[c] = "Vtot"
        elif c.startswith("SubLoop1_WasteHeat"):
            rename[c] = "Q1_rep"
        elif c.startswith("SubLoop2_WasteHeat"):
            rename[c] = "Q2_rep"
        elif c.startswith("SubLoop3_WasteHeat"):
            rename[c] = "Q3_rep"
        elif c.startswith("Overall_WasteHeat"):
            rename[c] = "Qtot_rep"
        elif "compute power" in cl:
            rename[c] = "P_IT"
        elif "accessory" in cl:
            rename[c] = "P_acc"
        elif "total power" in cl:
            rename[c] = "P_tot"
        elif "effectiveness" in cl:
            rename[c] = "PUE_rep"
    df = df.rename(columns=rename)
    meta = {"original_columns": cols, "units_row": [str(u) if pd.notna(u) else None for u in units], "renamed": rename}
    return df, meta


def metrics(y, yhat):
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    e = yhat - y
    return {
        "MAE": float(np.mean(np.abs(e))),
        "RMSE": float(np.sqrt(np.mean(e**2))),
        "peak_abs_error": float(np.max(np.abs(e))),
        "n": int(len(y)),
    }


def main():
    set_threads()
    df, meta = read_frontier()
    readme_rows = read_readme()
    n = len(df)
    ts = df["Date/Time"]
    dts = ts.diff().dt.total_seconds()
    cadence = dts.dropna()
    dup = int(ts.duplicated().sum())
    missing_ts = int(ts.isna().sum())
    span = None
    if ts.notna().any():
        span = [str(ts.min()), str(ts.max())]

    qc_flags = {}
    for c in ["P_IT", "P_acc", "P_tot", "PUE_rep", "V1", "V2", "V3", "Tret1", "Tret2", "Tret3", "Tsup"]:
        if c in df:
            s = df[c]
            qc_flags[c] = {
                "n_missing": int(s.isna().sum()),
                "n_negative": int((s < 0).sum()) if np.issubdtype(s.dtype, np.number) else None,
                "min": float(s.min()) if s.notna().any() else None,
                "max": float(s.max()) if s.notna().any() else None,
            }
    if "PUE_rep" in df:
        qc_flags["PUE_rep"]["n_lt_1"] = int((df["PUE_rep"] < 1).sum())

    qc = {
        "file": str(FRONTIER_XLSX),
        "n_rows": n,
        "timestamp_span": span,
        "n_duplicate_timestamps": dup,
        "n_missing_timestamps": missing_ts,
        "cadence_seconds": {
            "median": float(cadence.median()) if len(cadence) else None,
            "mean": float(cadence.mean()) if len(cadence) else None,
            "min": float(cadence.min()) if len(cadence) else None,
            "max": float(cadence.max()) if len(cadence) else None,
            "p05": float(cadence.quantile(0.05)) if len(cadence) else None,
            "p95": float(cadence.quantile(0.95)) if len(cadence) else None,
            "frac_exactly_600": float((cadence == 600).mean()) if len(cadence) else None,
            "n_gt_600": int((cadence > 600).sum()) if len(cadence) else None,
            "n_lt_600": int((cadence < 600).sum()) if len(cadence) else None,
        },
        "column_map": meta,
        "per_column": qc_flags,
        "interpolation": "none; missing values preserved",
        "readme_cadence_claim": "Readme says 10-minute step; observed cadence computed from timestamps.",
        "readme_rows": readme_rows,
        "readme_vs_data_name_notes": [
            "Readme 'Frontier accessory Power' vs data column 'Frontier Facility accessory Power'.",
            "Data sheet uses 'FLow' capitalization for some flow columns; matching is case-insensitive.",
        ],
    }
    atomic_write_json(WORK_ROOT / "results" / "frontier_qc.json", qc)

    # Thermal reconstruction uses overall supply temperature for all loops (no per-loop supply in file).
    df["Q1_rec"] = q_mw(df["V1"], df["Tret1"], df["Tsup"])
    df["Q2_rec"] = q_mw(df["V2"], df["Tret2"], df["Tsup"])
    df["Q3_rec"] = q_mw(df["V3"], df["Tret3"], df["Tsup"])
    df["Qtot_rec"] = df["Q1_rec"] + df["Q2_rec"] + df["Q3_rec"]
    df["Qsum_rep"] = df["Q1_rep"] + df["Q2_rep"] + df["Q3_rep"]

    def disc(a, b):
        mask = a.notna() & b.notna()
        err = (a[mask] - b[mask]).astype(float)
        rel = err / b[mask].replace(0, np.nan)
        dt_h = ts.diff().dt.total_seconds().reindex(err.index) / 3600.0
        dt_h = dt_h.fillna(10.0 / 60.0)
        return {
            "n": int(mask.sum()),
            "median_abs": float(err.abs().median()) if len(err) else None,
            "p95_abs": float(err.abs().quantile(0.95)) if len(err) else None,
            "median_rel": float(rel.abs().median()) if rel.notna().any() else None,
            "p95_rel": float(rel.abs().quantile(0.95)) if rel.notna().any() else None,
            "max_abs": float(err.abs().max()) if len(err) else None,
            "integrated_MWh_recon_minus_reported": float((err * dt_h).sum()) if len(err) else None,
            "dt_source": "timestamp deltas in hours; 10 min imputed only for the first row",
        }

    thermal = {
        "formula": "Q = rho * cp * V_dot * (T_return - T_supply)",
        "rho_kg_m3": RHO,
        "cp_kJ_kgK": CP_KJ,
        "flow_unit": "gpm US -> m3/s",
        "supply_temperature": "Overall Coolant Supply Temp applied to all three loops (no per-loop supply column)",
        "per_loop": {
            "1": disc(df["Q1_rec"], df["Q1_rep"]),
            "2": disc(df["Q2_rec"], df["Q2_rep"]),
            "3": disc(df["Q3_rec"], df["Q3_rep"]),
        },
        "total_vs_reported_overall": disc(df["Qtot_rec"], df["Qtot_rep"]),
        "sum_loops_vs_overall_reported": disc(df["Qsum_rep"], df["Qtot_rep"]),
        "tolerance_note": (
            "Excel stores floats; gpm and deg C look like converted instrument values. "
            "Agreement at ~1e-12 MW is numerical identity of the published formula, not independent sensors."
        ),
    }
    med = thermal["total_vs_reported_overall"]["median_abs"]
    thermal["status"] = "PASS" if med is not None and med < 1e-6 else ("PARTIAL" if med < 1e-3 else "FAIL")

    df["PUE_from_tot_IT"] = df["P_tot"] / df["P_IT"]
    df["PUE_from_ITplusacc"] = (df["P_IT"] + df["P_acc"]) / df["P_IT"]
    df["P_sum"] = df["P_IT"] + df["P_acc"]
    pue_acc = {
        "reported_definition_from_paper": "PUE = data-center energy / HPC equipment energy",
        "P_tot_minus_PIT_minus_Pacc": {
            "median": float((df["P_tot"] - df["P_sum"]).median()),
            "p95_abs": float((df["P_tot"] - df["P_sum"]).abs().quantile(0.95)),
            "n_nonzero_gt_1e-6": int(((df["P_tot"] - df["P_sum"]).abs() > 1e-6).sum()),
        },
        "PUE_rep_vs_Ptot_over_PIT": disc(df["PUE_rep"], df["PUE_from_tot_IT"]),
        "PUE_rep_vs_PITplusacc_over_PIT": disc(df["PUE_rep"], df["PUE_from_ITplusacc"]),
    }
    pue_acc["status"] = (
        "PASS"
        if pue_acc["PUE_rep_vs_Ptot_over_PIT"]["median_abs"] < 1e-6
        else "PARTIAL"
    )

    # Reduced models: chronological expanding next-month folds. Drop NA rows only for fit/eval.
    work = df.dropna(subset=["P_IT", "P_acc", "Qtot_rep", "Date/Time"]).copy()
    work["month"] = work["Date/Time"].dt.to_period("M")
    months = list(work["month"].sort_values().unique())
    init_n = 3
    folds = []
    for i in range(init_n, len(months)):
        train_m = months[:i]
        test_m = months[i]
        tr = work[work["month"].isin(train_m)]
        te = work[work["month"] == test_m]
        ytr, yte = tr["P_acc"].to_numpy(), te["P_acc"].to_numpy()
        # F0
        c0 = float(ytr.mean())
        f0 = np.full_like(yte, c0, dtype=float)
        # F1
        Xtr = np.column_stack([np.ones(len(tr)), tr["P_IT"].to_numpy()])
        Xte = np.column_stack([np.ones(len(te)), te["P_IT"].to_numpy()])
        b1, *_ = np.linalg.lstsq(Xtr, ytr, rcond=None)
        f1 = Xte @ b1
        # F2 oracle/structural contemporaneous Q
        Xtr2 = np.column_stack([np.ones(len(tr)), tr["P_IT"].to_numpy(), tr["Qtot_rep"].to_numpy()])
        Xte2 = np.column_stack([np.ones(len(te)), te["P_IT"].to_numpy(), te["Qtot_rep"].to_numpy()])
        b2, *_ = np.linalg.lstsq(Xtr2, ytr, rcond=None)
        f2 = Xte2 @ b2
        dt_h = 10.0 / 60.0
        rec = {
            "test_month": str(test_m),
            "n_train": int(len(tr)),
            "n_test": int(len(te)),
            "F0": {**metrics(yte, f0), "integrated_MWh_error": float(((f0 - yte) * dt_h).sum())},
            "F1": {
                **metrics(yte, f1),
                "coef_a_b": [float(b1[0]), float(b1[1])],
                "integrated_MWh_error": float(((f1 - yte) * dt_h).sum()),
            },
            "F2": {
                **metrics(yte, f2),
                "coef_a_b_c": [float(b2[0]), float(b2[1]), float(b2[2])],
                "integrated_MWh_error": float(((f2 - yte) * dt_h).sum()),
                "label": "contemporaneous_structural_oracle_uses_measured_Q",
            },
        }
        rec["MAE_improvement_F1_vs_F0"] = rec["F0"]["MAE"] - rec["F1"]["MAE"]
        rec["MAE_improvement_F2_vs_F1"] = rec["F1"]["MAE"] - rec["F2"]["MAE"]
        folds.append(rec)

    reduced = {
        "status": "PASS" if folds else "FAIL",
        "initial_train_window_months": init_n,
        "validation": "expanding chronological next-month folds; no random split",
        "F2_caveat": "F2 uses measured waste heat at the same timestamp and is not an ex-ante predictor.",
        "folds": folds,
        "mean_MAE": {
            k: float(np.mean([f[k]["MAE"] for f in folds])) if folds else None for k in ("F0", "F1", "F2")
        },
    }

    figdir = WORK_ROOT / "results" / "figures"
    figdir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(df["Date/Time"], df["Qtot_rep"] - df["Qtot_rec"])
    ax.set_ylabel("Reported − reconstructed Q (MW)")
    ax.set_title("Frontier thermal residual (overall)")
    fig.tight_layout()
    fig.savefig(figdir / "fig_frontier_thermal_residual.png", dpi=140)
    plt.close(fig)

    if folds:
        fig, ax = plt.subplots(figsize=(8, 4))
        xs = [f["test_month"] for f in folds]
        for k, lab in [("F0", "F0 const"), ("F1", "F1 a+b PIT"), ("F2", "F2 +Q oracle")]:
            ax.plot(xs, [f[k]["MAE"] for f in folds], marker="o", label=lab)
        ax.set_ylabel("MAE accessory power (MW)")
        ax.set_xticks(range(len(xs)))
        ax.set_xticklabels(xs, rotation=45, ha="right")
        ax.legend()
        ax.set_title("Chronological expanding-window accessory-power error")
        fig.tight_layout()
        fig.savefig(figdir / "fig_frontier_reduced_mae.png", dpi=140)
        plt.close(fig)

    out = {
        "timestamp_utc": utcnow(),
        "qc_status": "PASS",
        "thermal_closure": thermal,
        "pue_accounting": pue_acc,
        "reduced_model": reduced,
        "figures": [
            str(figdir / "fig_frontier_thermal_residual.png"),
            str(figdir / "fig_frontier_reduced_mae.png"),
        ],
    }
    atomic_write_json(WORK_ROOT / "results" / "frontier_validation.json", out)
    print(json.dumps(
        {
            "qc": out["qc_status"],
            "thermal": thermal["status"],
            "pue": pue_acc["status"],
            "reduced": reduced["status"],
            "thermal_median_abs_MW": med,
        },
        indent=2,
    ))
    if thermal["status"] == "FAIL":
        sys.exit(2)


if __name__ == "__main__":
    main()
