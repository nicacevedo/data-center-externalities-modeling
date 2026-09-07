"""Independent reproduction of SGI_G1 / SGI_G2 / SGI_G3 from raw replicate records.

Deliberately does NOT import src/summarize.py. Aggregation rules are re-read from
config/design_v2.yaml and re-implemented here so that a summarizer bug would surface
as a disagreement.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(
    "/home/nacevedo/RA/data-center-externalities-modeling/"
    "other_sources/groundwater_identifiability_synthetic"
)
OUT = Path("/tmp/sgi_independent_audit")

DESIGN = yaml.safe_load(open(ROOT / "config/design_v2.yaml", encoding="utf-8"))
SW = pd.read_csv(ROOT / "outputs/analysis/sweep_replicates.csv", low_memory=False)

# Frozen G3 model assignment, re-stated from the design's own wording:
# S6 null-network falsification is a NETWORK test; S8 placebo is a LOCAL test.
G3_MODEL = {
    "G3R1": "N", "G3R2": "N", "G3R1b": "N", "G3R2b": "N",
    "G3R3": "L", "G3R4": "L",
    "G2R1": "N", "G2R2": "N", "G2R3": "N", "G2R4": "N",
}
ESTIMATED, NOT_ESTIMABLE, FIT_FAILED = "ESTIMATED", "NOT_ESTIMABLE", "FIT_FAILED"


def status(df: pd.DataFrame, model: str) -> pd.Series:
    raw = df.get(f"estimability_status_{model}")
    if raw is None:
        return pd.Series([NOT_ESTIMABLE] * len(df), index=df.index)
    s = raw.astype("string").fillna("")
    out = pd.Series(NOT_ESTIMABLE, index=df.index, dtype=object)
    out[s == ESTIMATED] = ESTIMATED
    out[s == "ESTIMABLE"] = ESTIMATED
    out[s == FIT_FAILED] = FIT_FAILED
    out[s == NOT_ESTIMABLE] = NOT_ESTIMABLE
    for tok in ("NO_ADMISSIBLE_ROWS", "MODEL_NOT_APPLICABLE", "UNDERDETERMINED", "PARTIAL"):
        out[s == tok] = NOT_ESTIMABLE
    unknown = ~s.isin([ESTIMATED, "ESTIMABLE", FIT_FAILED, NOT_ESTIMABLE,
                       "NO_ADMISSIBLE_ROWS", "MODEL_NOT_APPLICABLE",
                       "UNDERDETERMINED", "PARTIAL"])
    if unknown.any():
        est = pd.to_numeric(df.get(f"estimable_{model}"), errors="coerce")
        out[unknown & (est == 1.0)] = ESTIMATED
    return out


def agg(df: pd.DataFrame, model: str, metric: str) -> dict:
    st = status(df, model)
    est = st == ESTIMATED
    vals = pd.to_numeric(df.loc[est, metric], errors="coerce") if metric in df else pd.Series(dtype=float)
    n = len(df)
    return {
        "n_replicates": n,
        "n_estimated": int(est.sum()),
        "n_not_estimable": int((st == NOT_ESTIMABLE).sum()),
        "n_fit_failed": int((st == FIT_FAILED).sum()),
        "estimability_rate": float(est.sum()) / n if n else np.nan,
        "median": float(np.nanmedian(vals)) if len(vals.dropna()) else np.nan,
        "q10": float(np.nanquantile(vals, 0.10)) if len(vals.dropna()) else np.nan,
        "q90": float(np.nanquantile(vals, 0.90)) if len(vals.dropna()) else np.nan,
    }


def median_all(df: pd.DataFrame, col: str) -> float:
    v = pd.to_numeric(df[col], errors="coerce") if col in df else pd.Series(dtype=float)
    return float(np.nanmedian(v)) if len(v.dropna()) else np.nan


report: dict = {}

# ---------------------------------------------------------------- basic integrity
report["integrity"] = {
    "n_records": int(len(SW)),
    "n_cells": int(SW["cell_id"].nunique()),
    "n_unique_cell_seed": int(SW.groupby(["cell_id", "seed"]).ngroups),
    "duplicate_cell_seed": int(len(SW) - SW.groupby(["cell_id", "seed"]).ngroups),
    "n_unique_seeds": int(SW["seed"].nunique()),
    "source_pool_values": sorted(SW["source_pool"].dropna().unique().tolist()),
    "smoke_any_true": bool(SW["smoke"].astype(str).eq("True").any()),
    "replicates_per_cell": sorted(SW.groupby("cell_id").size().unique().tolist()),
    "n_not_estimable_N": int((status(SW, "N") == NOT_ESTIMABLE).sum()),
    "n_fit_failed_L": int((status(SW, "L") == FIT_FAILED).sum()),
    "n_not_estimable_L": int((status(SW, "L") == NOT_ESTIMABLE).sum()),
}

# ---------------------------------------------------------------- SGI_G1
g1 = DESIGN["gates"]["SGI_G1"]
g1_crit = {c["id"]: c for c in g1["criteria"]}
g1_rows = []
for cell in g1["required_cells"]:
    d = SW[SW.cell_id == cell]
    a = agg(d, "L", "nire_persistent_step_h26_L")
    est = d[status(d, "L") == ESTIMATED]
    sign_frac = float((pd.to_numeric(est["beta_q_hat_mean_L"], errors="coerce") < 0).mean())
    blowup = float((pd.to_numeric(d["max_abs_protected_prediction_L"], errors="coerce").fillna(0.0) > 1000.0).mean())
    rmse_l = agg(d, "L", "rmse_test_L")["median"]
    rmse_b0 = median_all(d, "rmse_test_B0")
    ratio = rmse_l / rmse_b0 if np.isfinite(rmse_b0) and rmse_b0 > 0 else np.nan
    checks = {
        "G1_sign": (sign_frac, ">=", g1_crit["G1_sign"]["threshold"], sign_frac >= g1_crit["G1_sign"]["threshold"]),
        "G1_intervention": (a["median"], "<=", g1_crit["G1_intervention"]["threshold"], a["median"] <= g1_crit["G1_intervention"]["threshold"]),
        "G1_stability_blowup": (blowup, "==", g1_crit["G1_stability_blowup"]["threshold"], blowup == g1_crit["G1_stability_blowup"]["threshold"]),
        "G1_stability_vs_B0": (ratio, "<=", g1_crit["G1_stability_vs_B0"]["threshold"], ratio <= g1_crit["G1_stability_vs_B0"]["threshold"]),
    }
    g1_rows.append({
        "cell_id": cell,
        "n_replicates": a["n_replicates"],
        "n_estimated": a["n_estimated"],
        "estimability_rate": a["estimability_rate"],
        "nire_h26_L_median": a["median"],
        "nire_h26_L_q10": a["q10"],
        "nire_h26_L_q90": a["q90"],
        "threshold": g1_crit["G1_intervention"]["threshold"],
        "G1_intervention_pass": bool(checks["G1_intervention"][3]),
        "G1_sign_value": sign_frac,
        "G1_sign_pass": bool(checks["G1_sign"][3]),
        "G1_blowup_value": blowup,
        "G1_blowup_pass": bool(checks["G1_stability_blowup"][3]),
        "G1_rmse_ratio_value": ratio,
        "G1_rmse_vs_B0_pass": bool(checks["G1_stability_vs_B0"][3]),
        "failed_criteria": [k for k, v in checks.items() if not v[3]],
        "cell_pass": bool(all(v[3] for v in checks.values())),
    })
report["SGI_G1"] = {
    "rows": g1_rows,
    "all_required_cells_pass": bool(all(r["cell_pass"] for r in g1_rows)),
}

# ---------------------------------------------------------------- SGI_G2
g2 = DESIGN["gates"]["SGI_G2"]
g2_crit = {c["id"]: c for c in g2["criteria"]}
g2_rows = []
for cell in g2["required_cells"]:
    d = SW[SW.cell_id == cell]
    st_n = status(d, "N")
    est_n = d[st_n == ESTIMATED]
    f1 = float(np.nanmedian(pd.to_numeric(est_n["strong_edge_undirected_f1"], errors="coerce"))) if len(est_n) else np.nan
    nire_n = agg(d, "N", "nire_persistent_step_h26_N")["median"]
    nire_l = agg(d, "L", "nire_persistent_step_h26_L")["median"]
    simple = {m: median_all(d, f"nire_persistent_step_h26_{m}") for m in ("B0", "L", "S")}
    best_simple = float(np.nanmin(list(simple.values())))
    gain = (best_simple - nire_n) / best_simple if np.isfinite(best_simple) and best_simple > 0 else np.nan
    mnn = agg(d, "N", "masked_node_nmpe_N")["median"]
    onn = agg(d, "N", "observed_node_nmpe_N")["median"]
    collapse = mnn / onn if np.isfinite(onn) and onn > 0 else np.nan
    checks = {
        "G2_intervention_gain": (gain, ">=", 0.1, bool(gain >= 0.1)),
        "G2_strong_edge_f1": (f1, ">=", 0.8, bool(f1 >= 0.8)),
        "G2_masked_node_no_collapse": (collapse, "<=", 1.5, bool(collapse <= 1.5)),
    }
    g2_rows.append({
        "cell_id": cell,
        "scenario": d["scenario"].iloc[0],
        "topology": d["topology"].iloc[0],
        "regime": "ORACLE" if cell in g2["oracle_cells"] else "REALISTIC",
        "n_replicates": int(len(d)),
        "n_estimated_N": int((st_n == ESTIMATED).sum()),
        "estimability_rate_N": float((st_n == ESTIMATED).mean()),
        "strong_edge_f1_median": f1,
        "f1_threshold": 0.8,
        "edge_precision_median": median_all(d, "edge_precision"),
        "edge_recall_median": median_all(d, "edge_recall"),
        "nire_h26_N_median": nire_n,
        "nire_h26_L_median": nire_l,
        "nire_h26_B0_median": simple["B0"],
        "nire_h26_S_median": simple["S"],
        "best_simple_nire": best_simple,
        "intervention_gain": gain,
        "gain_threshold": 0.1,
        "masked_over_observed_nmpe": collapse,
        "failed_criteria": [k for k, v in checks.items() if not v[3]],
        "cell_pass": bool(all(v[3] for v in checks.values())),
    })
report["SGI_G2_RAW"] = {
    "rows": g2_rows,
    "all_required_cells_pass": bool(all(r["cell_pass"] for r in g2_rows)),
}

# ---------------------------------------------------------------- SGI_G3
g3 = DESIGN["gates"]["SGI_G3"]
trig_out = {}
for trig in g3["triggers_any_of"]:
    tid = trig["id"]
    cells = trig["cells"]
    per_cell = {}
    if tid == "G3_prediction_intervention_inversion":
        for cell in cells:
            d = SW[SW.cell_id == cell]
            model = G3_MODEL[cell]
            rmse_n = agg(d, "N", "rmse_test_N")["median"]
            nire_n = agg(d, "N", "nire_persistent_step_h26_N")["median"]
            rmse_simple = float(np.nanmin([median_all(d, f"rmse_test_{m}") for m in ("B0", "L", "S")]))
            nire_simple = float(np.nanmin([median_all(d, f"nire_persistent_step_h26_{m}") for m in ("B0", "L", "S")]))
            fired = bool(rmse_n < rmse_simple and nire_n > nire_simple)
            per_cell[cell] = {
                "evaluated_model": model, "triggered": fired, "value": float(fired),
                "rmse_N": rmse_n, "rmse_best_simple": rmse_simple,
                "nire_N": nire_n, "nire_best_simple": nire_simple,
            }
        trig_out[tid] = {"cells": cells, "per_cell": per_cell,
                         "severity": trig["severity"],
                         "triggered": any(v["triggered"] for v in per_cell.values()),
                         "triggered_cells": [c for c, v in per_cell.items() if v["triggered"]]}
        continue

    stat = trig["statistic"]
    thr = trig["threshold"]
    for cell in cells:
        d = SW[SW.cell_id == cell]
        model = G3_MODEL[cell]
        st = status(d, model)
        est = d[st == ESTIMATED]
        if "false_edge_count" in stat and "median" in stat:
            v = float(np.nanmedian(pd.to_numeric(est["false_edge_count"], errors="coerce"))) if len(est) else np.nan
        elif "false_edge_count" in stat:
            v = float((pd.to_numeric(est["false_edge_count"], errors="coerce") >= 1).mean()) if len(est) else np.nan
        elif "placebo_false_effect_L" in stat:
            v = float((pd.to_numeric(est[f"placebo_false_effect_{model}"], errors="coerce") == 1).mean()) if len(est) else np.nan
        else:
            v = np.nan
        per_cell[cell] = {
            "evaluated_model": model,
            "n_estimated": int((st == ESTIMATED).sum()),
            "n_replicates": int(len(d)),
            "value": v,
            "triggered": bool(v > thr),
            "regime": "ORACLE" if cell in ("G3R2", "G3R2b") else "REALISTIC",
        }
    trig_out[tid] = {
        "cells": cells, "statistic": stat, "comparator": trig["comparator"], "threshold": thr,
        "severity": trig["severity"], "family": trig.get("family"),
        "per_cell": per_cell,
        "triggered": any(v["triggered"] for v in per_cell.values()),
        "triggered_cells": [c for c, v in per_cell.items() if v["triggered"]],
        "realistic_triggered_cells": [c for c, v in per_cell.items()
                                      if v["triggered"] and v.get("regime") == "REALISTIC"],
    }

hard_ids = set(g3["hard_failure_ids"])
hard_fail = any(v["triggered"] for k, v in trig_out.items() if k in hard_ids)
rob_only = (not hard_fail) and any(v["triggered"] for k, v in trig_out.items() if k in set(g3["robustness_ids"]))
report["SGI_G3"] = {
    "triggers": trig_out,
    "hard_failure": bool(hard_fail),
    "robustness_only": bool(rob_only),
    "evaluated_model_by_cell": {c: G3_MODEL[c] for c in g3["required_cells"]},
}

# ---------------------------------------------------------------- final statuses
report["derived_status"] = {
    "LOCAL_RESPONSE_STATUS": "LOCAL_RESPONSE_NOT_IDENTIFIED"
    if not report["SGI_G1"]["all_required_cells_pass"] else "LOCAL_RESPONSE_IDENTIFIED",
    "SGI_G2_RAW_pass": report["SGI_G2_RAW"]["all_required_cells_pass"],
    "SGI_G3_hard_fail": report["SGI_G3"]["hard_failure"],
    "NETWORK_SUPPORT_FINAL": "NOT_EARNED"
    if (report["SGI_G3"]["hard_failure"] or not report["SGI_G2_RAW"]["all_required_cells_pass"])
    else "EARNED",
}

# ---------------------------------------------------------------- diff vs canonical
canon = json.load(open(ROOT / "outputs/analysis/FINAL_SYNTHETIC_IDENTIFIABILITY_STATUS.json"))
diffs = []
for r in g1_rows:
    c = canon["SGI_G1"]["cells"][r["cell_id"]]
    if c["pass"] != r["cell_pass"]:
        diffs.append(("G1_pass", r["cell_id"], c["pass"], r["cell_pass"]))
    if abs(c["estimability_rate"] - r["estimability_rate"]) > 1e-12:
        diffs.append(("G1_estrate", r["cell_id"], c["estimability_rate"], r["estimability_rate"]))
    if sorted(c["failed_criteria"]) != sorted(r["failed_criteria"]):
        diffs.append(("G1_failedcrit", r["cell_id"], c["failed_criteria"], r["failed_criteria"]))
for r in g2_rows:
    c = canon["SGI_G2_RAW"]["cells"][r["cell_id"]]
    if c["pass"] != r["cell_pass"]:
        diffs.append(("G2_pass", r["cell_id"], c["pass"], r["cell_pass"]))
    if sorted(c["failed_criteria"]) != sorted(r["failed_criteria"]):
        diffs.append(("G2_failedcrit", r["cell_id"], c["failed_criteria"], r["failed_criteria"]))
for tid, tv in trig_out.items():
    ct = canon["SGI_G3"]["triggers"][tid]
    if ct["triggered"] != tv["triggered"]:
        diffs.append(("G3_trig", tid, ct["triggered"], tv["triggered"]))
    for cell, cv in tv["per_cell"].items():
        cc = ct["per_cell"][cell]
        if cc["evaluated_model"] != cv["evaluated_model"]:
            diffs.append(("G3_model", f"{tid}/{cell}", cc["evaluated_model"], cv["evaluated_model"]))
        if not (np.isnan(cc["value"]) and np.isnan(cv["value"])) and abs(cc["value"] - cv["value"]) > 1e-9:
            diffs.append(("G3_value", f"{tid}/{cell}", cc["value"], cv["value"]))
        if cc["triggered"] != cv["triggered"]:
            diffs.append(("G3_celltrig", f"{tid}/{cell}", cc["triggered"], cv["triggered"]))
if canon["SGI_G3"]["hard_failure"] != report["SGI_G3"]["hard_failure"]:
    diffs.append(("G3_hardfail", "-", canon["SGI_G3"]["hard_failure"], report["SGI_G3"]["hard_failure"]))
if canon["LOCAL_RESPONSE_STATUS"] != report["derived_status"]["LOCAL_RESPONSE_STATUS"]:
    diffs.append(("LOCAL_STATUS", "-", canon["LOCAL_RESPONSE_STATUS"], report["derived_status"]["LOCAL_RESPONSE_STATUS"]))
if canon["NETWORK_SUPPORT_FINAL"]["status"] != report["derived_status"]["NETWORK_SUPPORT_FINAL"]:
    diffs.append(("NETWORK_STATUS", "-", canon["NETWORK_SUPPORT_FINAL"]["status"], report["derived_status"]["NETWORK_SUPPORT_FINAL"]))

report["discrepancies_vs_canonical"] = diffs

json.dump(report, open(OUT / "01_gate_reproduction.json", "w"), indent=2, default=str)

print("=== INTEGRITY ===")
print(json.dumps(report["integrity"], indent=2))
print("\n=== SGI_G1 ===")
print(pd.DataFrame(g1_rows)[["cell_id", "n_replicates", "estimability_rate", "nire_h26_L_median",
                             "nire_h26_L_q10", "nire_h26_L_q90", "threshold", "G1_intervention_pass",
                             "G1_sign_value", "G1_rmse_ratio_value", "cell_pass"]].to_string(index=False))
print("\n=== SGI_G2 ===")
print(pd.DataFrame(g2_rows)[["cell_id", "scenario", "topology", "regime", "estimability_rate_N",
                             "strong_edge_f1_median", "edge_precision_median", "edge_recall_median",
                             "nire_h26_N_median", "nire_h26_L_median", "best_simple_nire",
                             "intervention_gain", "masked_over_observed_nmpe", "cell_pass"]].to_string(index=False))
print("\n=== SGI_G3 ===")
for tid, tv in trig_out.items():
    print(f"\n-- {tid}  [{tv.get('severity')}] thr={tv.get('threshold')} triggered={tv['triggered']}")
    for cell, cv in tv["per_cell"].items():
        print(f"   {cell:8s} model={cv['evaluated_model']} value={cv['value']!r} triggered={cv['triggered']} regime={cv.get('regime','-')}")
print("\n=== DERIVED STATUS ===")
print(json.dumps(report["derived_status"], indent=2))
print("\n=== DISCREPANCIES vs CANONICAL ===")
print(diffs if diffs else "NONE")
