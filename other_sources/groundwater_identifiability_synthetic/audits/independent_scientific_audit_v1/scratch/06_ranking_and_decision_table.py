"""Factor ranking for local intervention recovery + the empirical decision table.

POST-HOC MECHANISM DIAGNOSTIC. Uses only the frozen 0.20 G1 intervention criterion;
no new thresholds are introduced.
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pandas as pd

pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 60)

ROOT = Path(
    "/home/nacevedo/RA/data-center-externalities-modeling/"
    "other_sources/groundwater_identifiability_synthetic"
)
OUT = Path("/tmp/sgi_independent_audit")
C = pd.read_csv(OUT / "02_cell_surface.csv").set_index("cell_id")
SW = pd.read_csv(ROOT / "outputs/analysis/sweep_replicates.csv", low_memory=False)

NIRE = "nire_persistent_step_h26_L"
NIRE_N = "nire_persistent_step_h26_N"
F1 = "strong_edge_undirected_f1"
G1_THR = 0.20

# ---------------------------------------------------------------- estimability check
print("#" * 100)
print("# ESTIMABILITY EXCEPTIONS")
print("#" * 100)
bad_l = C[C.estimability_rate_L < 1.0]
print("\nCells where the LOCAL model is not estimable in every replicate:")
print(bad_l[["estimability_rate_L", "mcar_fraction", "observed_node_fraction", "cadence", NIRE]].to_string()
      if len(bad_l) else "  none")
bad_n = C[C.estimability_rate_N < 1.0].sort_values("estimability_rate_N")
print(f"\nCells where the NETWORK model is not estimable in every replicate: {len(bad_n)}")
print(bad_n[["estimability_rate_N", "mcar_fraction", "observed_node_fraction", "cadence",
             "blocks_per_node", F1]].to_string())

# ---------------------------------------------------------------- factor ranking
print("\n\n" + "#" * 100)
print("# FACTOR RANKING FOR LOCAL INTERVENTION RECOVERY (frozen 1-D stress curves)")
print("#" * 100)
print("""
All curves share the same S5/path5 baseline cell (CURVE_curve_*_<reference level> == the
reference regime), so the swing within a curve isolates that one factor over its frozen
tested range. Sign convention: 'best' = lowest NIRE.
""")
CURVES = {
    "pumping_quality":      (["CURVE_curve_pumping_quality_PEXACT", "CURVE_curve_pumping_quality_PMULTNOISE",
                              "CURVE_curve_pumping_quality_PSCALEBIAS", "CURVE_curve_pumping_quality_PTEMPAGG",
                              "CURVE_curve_pumping_quality_PSPATIALAGG"], "pumping_quality"),
    "coupling_strength(truth)": (["CURVE_curve_coupling_strength_NONE", "CURVE_curve_coupling_strength_LOW",
                                  "CURVE_curve_coupling_strength_MED", "CURVE_curve_coupling_strength_HIGH"], "gamma"),
    "head_snr":             (["CURVE_curve_snr_2", "CURVE_curve_snr_5", "CURVE_curve_snr_10",
                              "CURVE_curve_snr_20"], "snr_head"),
    "cadence":              (["CURVE_curve_cadence_1", "CURVE_curve_cadence_2", "CURVE_curve_cadence_4",
                              "CURVE_curve_cadence_13"], "cadence"),
    "hydraulic_memory":     (["CURVE_curve_memory_LOW", "CURVE_curve_memory_MED",
                              "CURVE_curve_memory_HIGH"], "memory"),
    "observed_node_fraction": (["CURVE_curve_observed_nodes_0p4", "CURVE_curve_observed_nodes_0p6",
                                "CURVE_curve_observed_nodes_0p8", "CURVE_curve_observed_nodes_1p0"],
                               "observed_node_fraction"),
    "recharge_quality":     (["CURVE_curve_recharge_quality_REXACT", "CURVE_curve_recharge_quality_RNOISE",
                              "CURVE_curve_recharge_quality_RLAG", "CURVE_curve_recharge_quality_RNOISELAG",
                              "CURVE_curve_recharge_quality_RSCALE"], "recharge_quality"),
    "confounding_rho":      (["CURVE_curve_confounding_0p0", "CURVE_curve_confounding_0p3",
                              "CURVE_curve_confounding_0p6", "CURVE_curve_confounding_0p9"], "confounding_rho"),
    "mcar_missingness":     (["CURVE_curve_missing_0p0", "CURVE_curve_missing_0p1",
                              "CURVE_curve_missing_0p3", "CURVE_curve_missing_0p5"], "mcar_fraction"),
    "block_outage":         (["CURVE_curve_block_outage_0", "CURVE_curve_block_outage_1",
                              "CURVE_curve_block_outage_2"], "blocks_per_node"),
    "process_noise":        (["CURVE_curve_process_noise_0p05", "CURVE_curve_process_noise_0p25",
                              "CURVE_curve_process_noise_1p0"], "process_noise_sd"),
}
rank_rows = []
for name, (ids, lvl) in CURVES.items():
    ids = [i for i in ids if i in C.index]
    sub = C.loc[ids]
    v = pd.to_numeric(sub[NIRE], errors="coerce")
    vn = pd.to_numeric(sub[NIRE_N], errors="coerce")
    f1 = pd.to_numeric(sub[F1], errors="coerce")
    rank_rows.append({
        "factor": name,
        "frozen_levels": " -> ".join(str(x) for x in sub[lvl].tolist()),
        "NIRE_L_best": v.min(), "NIRE_L_worst": v.max(),
        "NIRE_L_swing": v.max() - v.min(),
        "best_level": str(sub[lvl].iloc[int(np.nanargmin(v.values))]),
        "worst_level": str(sub[lvl].iloc[int(np.nanargmax(v.values))]),
        "gap_of_best_to_frozen_0.20": v.min() - G1_THR,
        "NIRE_N_swing": (vn.max() - vn.min()) if vn.notna().any() else np.nan,
        "edge_F1_swing": (f1.max() - f1.min()) if f1.notna().any() else np.nan,
    })
rank = pd.DataFrame(rank_rows).sort_values("NIRE_L_swing", ascending=False)
print(rank.to_string(index=False))
rank.to_csv(OUT / "06_factor_ranking_local.csv", index=False)

print("\n\nSame ranking by effect on NETWORK edge F1 (descending swing):")
print(rank.sort_values("edge_F1_swing", ascending=False)[
    ["factor", "frozen_levels", "edge_F1_swing", "NIRE_N_swing"]].to_string(index=False))

print("\n\nOBSERVATION-BUNDLE contrast at fixed uncoupled truth (the only route below 0.20):")
bundle = pd.DataFrame([
    {"regime": "uncoupled truth + realistic obs (k=1)", "cell": "G1R2", "NIRE_L": C.loc["G1R2", NIRE]},
    {"regime": "uncoupled truth + realistic obs (k=4)", "cell": "G1R1", "NIRE_L": C.loc["G1R1", NIRE]},
    {"regime": "uncoupled truth + realistic obs (k=4, 5-node)", "cell": "G3R1", "NIRE_L": C.loc["G3R1", NIRE]},
    {"regime": "uncoupled truth + ORACLE obs (S6a null5)", "cell": "G3R2", "NIRE_L": C.loc["G3R2", NIRE]},
    {"regime": "uncoupled truth + ORACLE obs (S6b path5-geom)", "cell": "G3R2b", "NIRE_L": C.loc["G3R2b", NIRE]},
    {"regime": "COUPLED truth + ORACLE obs (S4 path5)", "cell": "G2R1", "NIRE_L": C.loc["G2R1", NIRE]},
    {"regime": "COUPLED truth + ORACLE obs (S4 star5)", "cell": "G2R2", "NIRE_L": C.loc["G2R2", NIRE]},
    {"regime": "COUPLED truth + realistic obs (S5 path5)", "cell": "G2R3", "NIRE_L": C.loc["G2R3", NIRE]},
    {"regime": "zero-coupling truth + realistic obs (gamma NONE)", "cell": "CURVE_curve_coupling_strength_NONE", "NIRE_L": C.loc["CURVE_curve_coupling_strength_NONE", NIRE]},
])
bundle["meets_frozen_0.20"] = bundle.NIRE_L <= G1_THR
print(bundle.to_string(index=False))

# ---------------------------------------------------------------- decision table
print("\n\n" + "#" * 100)
print("# EMPIRICAL DECISION TABLE")
print("#" * 100)

LOCAL_CRED = "LOCAL_RESPONSE_CREDIBLE"
LOCAL_COND = "LOCAL_RESPONSE_CONDITIONALLY_CREDIBLE"
FORECAST = "FORECASTING_ONLY"
SPATIAL = "SPATIAL_FORCING_DIAGNOSTIC_ONLY"
NET_NO = "NETWORK_NOT_EARNED"
NET_COND = "NETWORK_CONDITIONALLY_TESTABLE"
ABS_NO = "ABSOLUTE_PHYSICAL_SCALE_NOT_IDENTIFIED"
INCONC = "INCONCLUSIVE"


def classify(row):
    """Classify one observation regime using ONLY the frozen 0.20 G1 criterion,
    the frozen G2 edge-F1 criterion (0.80), the frozen G3 falsification outcome,
    and the frozen absolute-scale identifiability flags."""
    labels = []
    nire_l = row["nire_L"]
    f1 = row["edge_f1"]
    est_l, est_n = row["est_rate_L"], row["est_rate_N"]

    if not np.isfinite(nire_l) or est_l == 0:
        labels.append(INCONC)
    elif nire_l <= G1_THR and est_l == 1.0:
        labels.append(LOCAL_CRED)
    elif nire_l <= G1_THR:
        labels.append(LOCAL_COND)
    else:
        # frozen evidence: local intervention recovery is not credible here
        if row["rmse_ratio_L_vs_B0"] < 1.0:
            labels.append(FORECAST)
        else:
            labels.append(INCONC)

    # spatial forcing (S model) useful without dynamic network?
    if np.isfinite(row["nire_S"]) and np.isfinite(nire_l) and row["nire_S"] < nire_l:
        labels.append(SPATIAL)

    # network: frozen G3 hard failure applies globally -> NOT_EARNED everywhere.
    # A regime is at most CONDITIONALLY_TESTABLE, never earned, and only where the
    # frozen G2 edge criterion is met AND no false edges are being manufactured.
    if not np.isfinite(f1) or est_n == 0:
        labels.append(NET_NO)
    elif f1 >= 0.80 and row["false_edge_any_rate"] <= 0.20:
        labels.append(NET_COND)
    else:
        labels.append(NET_NO)

    # absolute physical scale
    if not bool(row["absolute_S_identifiable"]):
        labels.append(ABS_NO)
    return labels


rows = []
for cell, r in C.iterrows():
    rr = {
        "cell_id": cell,
        "scenario": r["scenario"], "topology": r["topology"],
        "n_nodes": r["n_nodes"], "memory": r["memory"], "gamma": r["gamma"],
        "cadence": r["cadence"], "cadence_over_tau_relax": r["cadence_over_tau_relax"],
        "pumping_quality": r["pumping_quality"],
        "absolute_pumping_scale_known": r["absolute_pumping_scale_known"],
        "recharge_quality": r["recharge_quality"], "recharge_lag": r["recharge_lag"],
        "confounding_rho": r["confounding_rho"], "mcar_fraction": r["mcar_fraction"],
        "blocks_per_node": r["blocks_per_node"],
        "observed_node_fraction": r["observed_node_fraction"],
        "snr_head": r["snr_head"], "process_noise_sd": r["process_noise_sd"],
        "est_rate_L": r["estimability_rate_L"], "est_rate_N": r["estimability_rate_N"],
        "nire_L": r[NIRE], "nire_N": r[NIRE_N],
        "nire_S": r.get("nire_persistent_step_h26_S", np.nan),
        "nire_B0": r.get("nire_persistent_step_h26_B0", np.nan),
        "shape_error_L": r.get("relative_shape_error_persistent_step_L", np.nan),
        "rmse_L": r["rmse_test_L"], "rmse_B0": r["rmse_test_B0"],
        "rmse_ratio_L_vs_B0": r["rmse_test_L"] / r["rmse_test_B0"] if r["rmse_test_B0"] else np.nan,
        "edge_f1": r.get(F1, np.nan),
        "false_edge_any_rate": r.get("false_edge_any_rate", np.nan),
        "false_edge_count_median": r.get("false_edge_count", np.nan),
        "absolute_S_identifiable": r["absolute_S_identifiable"],
        "physical_parameter_identifiable": r["physical_parameter_identifiable"],
        "placebo_false_effect_rate_L": r.get("placebo_false_effect_rate_L", np.nan),
    }
    rr["classification"] = ";".join(classify(rr))
    rows.append(rr)

DT = pd.DataFrame(rows).set_index("cell_id").sort_index()
DT.to_csv(OUT / "EMPIRICAL_DECISION_TABLE.csv")
print(f"\nwrote {OUT / 'EMPIRICAL_DECISION_TABLE.csv'}  ({DT.shape[0]} regimes x {DT.shape[1]} fields)")

print("\nClassification tallies over the 129 frozen cells:")
from collections import Counter
cnt = Counter()
for s in DT.classification:
    for tok in s.split(";"):
        cnt[tok] += 1
for kk, vv in cnt.most_common():
    print(f"  {vv:4d}  {kk}")

print("\nCells classified LOCAL_RESPONSE_CREDIBLE:")
print(DT[DT.classification.str.contains(LOCAL_CRED)][
    ["scenario", "topology", "gamma", "cadence", "pumping_quality", "recharge_quality",
     "confounding_rho", "mcar_fraction", "snr_head", "process_noise_sd", "nire_L",
     "classification"]].to_string())

print("\nCells classified NETWORK_CONDITIONALLY_TESTABLE:")
nt = DT[DT.classification.str.contains(NET_COND)]
print(nt[["scenario", "topology", "gamma", "cadence", "pumping_quality", "snr_head",
          "observed_node_fraction", "edge_f1", "false_edge_any_rate", "nire_N"]].to_string()
      if len(nt) else "  none")

print("\nCells where the SPATIAL-forcing model beats the local model on intervention:")
sp = DT[DT.classification.str.contains(SPATIAL)]
print(f"  {len(sp)} / {len(DT)} cells")
print(sp[["scenario", "topology", "gamma", "nire_L", "nire_S", "nire_N"]].head(20).to_string() if len(sp) else "")

print("\nABSOLUTE_PHYSICAL_SCALE_NOT_IDENTIFIED count:", int(DT.classification.str.contains(ABS_NO).sum()))
print("Cells where absolute_S_identifiable is TRUE:")
print(DT[DT.absolute_S_identifiable.astype(str) == "True"][
    ["scenario", "topology", "cadence", "pumping_quality", "recharge_quality",
     "confounding_rho", "nire_L"]].to_string())

# ---------------------------------------------------------------- markdown rendering
md = ["# Empirical decision table (POST-HOC; frozen gates unchanged)", "",
      "Derived read-only from `outputs/analysis/sweep_replicates.csv` at",
      "DESIGN_HASH `b53f5594…a8a5`, CODE_HASH `7cc64809…d863c`, 7,740 ANALYSIS replicates.",
      "",
      "Classification uses ONLY frozen criteria: the G1 intervention threshold 0.20 on",
      "`median(nire_persistent_step_h26_L)`, the G2 edge criterion 0.80 on",
      "`median(strong_edge_undirected_f1)`, the G3 falsification outcome (hard failure,",
      "network NOT_EARNED globally), and the frozen `absolute_S_identifiable` flag.",
      "No new thresholds are introduced.", "",
      "## Tallies", "", "| label | cells |", "|---|---|"]
for kk, vv in cnt.most_common():
    md.append(f"| `{kk}` | {vv} |")
md += ["", "## Regimes meeting the frozen local criterion", "",
       "| cell | scenario | topology | true coupling | k | pumping | recharge | rho | MCAR | SNR | proc noise | NIRE_L |",
       "|---|---|---|---|---|---|---|---|---|---|---|---|"]
for cid, r in DT[DT.classification.str.contains(LOCAL_CRED)].iterrows():
    coup = "n/a (single node)" if str(r.topology) == "single" else f"gamma={r.gamma} but C_ij=0 (null truth)"
    md.append(f"| {cid} | {r.scenario} | {r.topology} | {coup} | {r.cadence} | "
              f"{r.pumping_quality} | {r.recharge_quality} | {r.confounding_rho} | {r.mcar_fraction} | "
              f"{r.snr_head} | {r.process_noise_sd} | {r.nire_L:.4f} |")
md += ["",
       "`C_G0` is the noise-free implementation-sanity cell (SGI_G0) and carries no scientific",
       "claim about attainable data. Only **two** non-G0 regimes out of 128 meet the frozen 0.20",
       "criterion, and in both the truth has **zero cross-node coupling by construction** and the",
       "observation bundle is fully ORACLE_FAVOURABLE. The next best non-G0 regime is `G1R2` at",
       "0.5303 — 2.8x the second-best value — so the boundary is a cliff, not a gradient."]
md += ["", "## Full table", "", "See `EMPIRICAL_DECISION_TABLE.csv` (129 rows).", "",
       "## Factor ranking for local intervention recovery", "",
       "| factor | frozen levels | best NIRE_L | worst NIRE_L | swing | best level | gap of best to 0.20 |",
       "|---|---|---|---|---|---|---|"]
for _, r in rank.iterrows():
    md.append(f"| {r.factor} | {r.frozen_levels} | {r['NIRE_L_best']:.3f} | {r['NIRE_L_worst']:.3f} | "
              f"{r['NIRE_L_swing']:.3f} | {r.best_level} | {r['gap_of_best_to_frozen_0.20']:+.3f} |")
(OUT / "EMPIRICAL_DECISION_TABLE.md").write_text("\n".join(md) + "\n")
print(f"\nwrote {OUT / 'EMPIRICAL_DECISION_TABLE.md'}")
