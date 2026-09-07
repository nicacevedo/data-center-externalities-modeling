"""S8 placebo mechanism, S6a/S6b false-edge mechanism, oracle-vs-realistic network
boundary, and the prediction-vs-intervention relationship. Read-only, post-hoc.
"""
from __future__ import annotations

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


def status(df, model):
    s = df.get(f"estimability_status_{model}").astype("string").fillna("")
    o = pd.Series("NOT_ESTIMABLE", index=df.index, dtype=object)
    o[s.isin(["ESTIMATED", "ESTIMABLE"])] = "ESTIMATED"
    o[s == "FIT_FAILED"] = "FIT_FAILED"
    return o


print("#" * 100)
print("# S8 PLACEBO MECHANISM")
print("#" * 100)
s8 = SW[SW.scenario == "S8"]
print(f"\nS8 cells present in the ENTIRE frozen sweep: {sorted(s8.cell_id.unique())}")
print(f"S8 cell count = {s8.cell_id.nunique()}   (design defines only G3R3 and G3R4)")
print("\nFrozen S8 observation configuration (both cells use overrides {} = reference regime):")
print(C.loc[["G3R3", "G3R4"], ["scenario", "topology", "cadence", "pumping_quality",
                               "recharge_quality", "recharge_sigma", "confounding_rho",
                               "mcar_fraction", "snr_head", "process_noise_sd", "n_nodes"]].T.to_string())
print("\n*** The frozen sweep contains NO S8 cell with R-EXACT recharge, and NO S8 cell with")
print("    confounding_rho != 0.3, and no S8 SNR/cadence/process-noise variation.")
print("    Section-10 question ('does placebo failure decline when recharge is exact and")
print("    confounding weak?') is therefore NOT IDENTIFIABLE FROM STORED FROZEN OUTPUTS. ***")

print("\nReplicate-level S8 diagnostics:")
for cell, d in s8.groupby("cell_id"):
    est = d[status(d, "L") == "ESTIMATED"]
    pc = pd.to_numeric(est["placebo_coef_L"], errors="coerce")
    pr = pd.to_numeric(est["placebo_relative_to_true_L"], errors="coerce")
    ps = pd.to_numeric(est["placebo_step_response_L"], errors="coerce")
    tr = pd.to_numeric(est["true_real_pumping_step_response"], errors="coerce")
    ff = pd.to_numeric(est["placebo_false_effect_L"], errors="coerce")
    rp = pd.to_numeric(est["s8_real_pumping_present_L"], errors="coerce")
    print(f"\n  --- {cell} (n_estimated={len(est)}) ---")
    print(f"    real pumping retained in every fit          : {bool((rp == 1).all())}")
    print(f"    placebo_false_effect rate (frozen threshold 0.20 of true) : {(ff == 1).mean():.4f}")
    print(f"    placebo_coef_L        median={pc.median():+.5f}  q10={pc.quantile(.1):+.5f}  q90={pc.quantile(.9):+.5f}")
    print(f"    frac placebo_coef < 0 (drawdown-like sign)  : {(pc < 0).mean():.3f}")
    print(f"    placebo_step_response median={ps.median():.5f}   true_real_step_response median={tr.median():.5f}")
    print(f"    placebo_relative_to_true  median={pr.median():.4f}  q10={pr.quantile(.1):.4f}  q90={pr.quantile(.9):.4f}")
    print(f"    frac with ratio in (0.20, 0.50]            : {((pr > 0.20) & (pr <= 0.50)).mean():.3f}")
    print(f"    frac with ratio > 1.0                      : {(pr > 1.0).mean():.3f}")
    # within-cell association with realized replicate conditions
    sub = est[["placebo_relative_to_true_L", "realized_snr_head", "realized_snr_head_detrended",
               "seasonal_variance_share", "pumping_excitation_fraction_L",
               "condition_number_L", "max_vif_L", "A_diag_relative_error_L",
               "B_Q_pseudo_true_relative_error_median"]].apply(pd.to_numeric, errors="coerce")
    sp = sub.corr(method="spearman")["placebo_relative_to_true_L"].drop("placebo_relative_to_true_L")
    print("    within-cell spearman(placebo_relative_to_true, X) across 60 seeds:")
    for kk, vv in sp.sort_values(key=lambda s: -s.abs()).items():
        print(f"       {vv:+.3f}  {kk}")

print("\nComparator: placebo channel is only constructed in S8, so no non-S8 baseline exists.")
print("Design fact: placebo correlation with recharge/climate = 0.85, true causal effect = 0.")

print("\n\n" + "#" * 100)
print("# S6a / S6b FALSE-EDGE MECHANISM")
print("#" * 100)
cells6 = ["G3R1", "G3R2", "G3R1b", "G3R2b"]
print("\nFrozen configurations:")
print(C.loc[cells6, ["scenario", "topology", "cadence", "gamma", "pumping_quality",
                     "recharge_quality", "confounding_rho", "mcar_fraction",
                     "observed_node_fraction", "snr_head", "process_noise_sd",
                     "n_nodes", "n_true_strong_edges", "realized_snr_head",
                     "realized_local_persistence_mean_A_ii", "rho_A", "tau_relax_realized"]].T.to_string())
print("\nFalse-edge outcomes (N model, ESTIMATED replicates only):")
rows = []
for cell in cells6:
    d = SW[SW.cell_id == cell]
    est = d[status(d, "N") == "ESTIMATED"]
    fe = pd.to_numeric(est["false_edge_count"], errors="coerce")
    rows.append({
        "cell": cell,
        "regime": "ORACLE" if cell in ("G3R2", "G3R2b") else "REALISTIC",
        "null": "S6a" if "b" not in cell else "S6b",
        "n_replicates": len(d), "n_estimated_N": len(est),
        "estimability_rate_N": len(est) / len(d),
        "median_false_edge_count": fe.median(),
        "mean_false_edge_count": fe.mean(),
        "frac_any_false_edge": float((fe >= 1).mean()),
        "q90_false_edge": fe.quantile(0.9),
        "max_false_edge": fe.max(),
        "n_candidate_pairs_proxy": pd.to_numeric(est["n_cols_N"], errors="coerce").median(),
        "median_selected_lambda": pd.to_numeric(est["selected_lambda"], errors="coerce").median(),
        "median_realized_snr": pd.to_numeric(est["realized_snr_head"], errors="coerce").median(),
        "median_condition_number_N": pd.to_numeric(est["condition_number_N"], errors="coerce").median(),
    })
t6 = pd.DataFrame(rows).set_index("cell")
print(t6.to_string())
print("\nORACLE vs REALISTIC contrast, per null family:")
for fam in ("S6a", "S6b"):
    sub = t6[t6.null == fam]
    r = sub[sub.regime == "REALISTIC"].iloc[0]
    o = sub[sub.regime == "ORACLE"].iloc[0]
    print(f"  {fam}: median false edges  realistic={r.median_false_edge_count:.1f} -> oracle={o.median_false_edge_count:.1f}")
    print(f"       any-false-edge rate  realistic={r.frac_any_false_edge:.3f} -> oracle={o.frac_any_false_edge:.3f}")
print("\nFrozen thresholds: median > 0.5 and any-rate > 0.2 (both trigger).")
print("Oracle any-rate S6a = %.3f (> 0.2 => triggers even under favourable known truth)" % t6.loc["G3R2", "frac_any_false_edge"])
print("Oracle any-rate S6b = %.3f (> 0.2 => triggers even under favourable known truth)" % t6.loc["G3R2b", "frac_any_false_edge"])

print("\n\n" + "#" * 100)
print("# ORACLE vs REALISTIC NETWORK BOUNDARY")
print("#" * 100)
net = ["G2R1", "G2R2", "G2R3", "G2R4", "R_S4_bridge", "R_S5_bridge"]
cols = ["scenario", "topology", "regime_lbl", "cadence", "gamma", "pumping_quality",
        "recharge_quality", "confounding_rho", "mcar_fraction", "observed_node_fraction",
        "snr_head", "process_noise_sd", "n_true_strong_edges",
        "strong_edge_undirected_f1", "edge_precision", "edge_recall",
        "false_edge_count", "false_edge_any_rate",
        "nire_persistent_step_h26_N", "nire_persistent_step_h26_L",
        "nire_persistent_step_h26_B0", "nire_persistent_step_h26_S",
        "rmse_test_N", "rmse_test_L", "estimability_rate_N", "selected_lambda",
        "A_diag_relative_error_N", "strong_coupling_weight_error"]
tmp = C.loc[net].copy()
tmp["regime_lbl"] = ["ORACLE", "ORACLE", "REALISTIC", "REALISTIC", "ORACLE", "REALISTIC"]
print(tmp[[c for c in cols if c in tmp.columns]].T.to_string())
print("""
Both regimes differ in EXACTLY the ORACLE_FAVOURABLE bundle:
  cadence 4->1, P-MULTNOISE->P-EXACT, R-NOISE->R-EXACT, rho 0.3->0.0,
  MCAR 0.1->0.0, snr_head 10->20, process_noise 0.05->0.02, gamma MED->HIGH.
gamma MED->HIGH also RAISES true coupling strength, which makes edges easier to detect.
""")
print("Isolating observation quality at fixed realistic scenario (S5 path5) via the frozen curves:")
for nm, ids in {
    "snr": ["CURVE_curve_snr_2", "CURVE_curve_snr_5", "CURVE_curve_snr_10", "CURVE_curve_snr_20"],
    "missing": ["CURVE_curve_missing_0p0", "CURVE_curve_missing_0p1", "CURVE_curve_missing_0p3", "CURVE_curve_missing_0p5"],
    "observed_nodes": ["CURVE_curve_observed_nodes_0p4", "CURVE_curve_observed_nodes_0p6",
                       "CURVE_curve_observed_nodes_0p8", "CURVE_curve_observed_nodes_1p0"],
    "cadence": ["CURVE_curve_cadence_1", "CURVE_curve_cadence_2", "CURVE_curve_cadence_4", "CURVE_curve_cadence_13"],
    "coupling": ["CURVE_curve_coupling_strength_NONE", "CURVE_curve_coupling_strength_LOW",
                 "CURVE_curve_coupling_strength_MED", "CURVE_curve_coupling_strength_HIGH"],
    "confounding": ["CURVE_curve_confounding_0p0", "CURVE_curve_confounding_0p3",
                    "CURVE_curve_confounding_0p6", "CURVE_curve_confounding_0p9"],
    "process_noise": ["CURVE_curve_process_noise_0p05", "CURVE_curve_process_noise_0p25", "CURVE_curve_process_noise_1p0"],
}.items():
    print(f"\n  [{nm}]")
    print(C.loc[ids, ["strong_edge_undirected_f1", "edge_precision", "edge_recall",
                      "false_edge_count", "false_edge_any_rate", "nire_persistent_step_h26_N",
                      "estimability_rate_N"]].to_string())

print("\n\n" + "#" * 100)
print("# PREDICTION vs INTERVENTION")
print("#" * 100)
nonG0 = C[C.scenario != "S0"]
pv = nonG0[["rmse_test_L", "nire_persistent_step_h26_L", "rmse_test_N",
            "nire_persistent_step_h26_N", "rmse_test_B0", "nire_persistent_step_h26_B0",
            "rmse_improvement_vs_B0_L"]].apply(pd.to_numeric, errors="coerce")
print("\nSpearman association over 128 non-G0 cells:")
print(f"  rmse_test_L  vs nire_h26_L : {pv[['rmse_test_L','nire_persistent_step_h26_L']].dropna().corr(method='spearman').iloc[0,1]:+.3f}")
print(f"  rmse_test_N  vs nire_h26_N : {pv[['rmse_test_N','nire_persistent_step_h26_N']].dropna().corr(method='spearman').iloc[0,1]:+.3f}")
print("\nNormalized comparison (rmse relative to B0 baseline rmse, i.e. does L predict better than the naive baseline?):")
rel = (pv["rmse_test_L"] / pv["rmse_test_B0"]).dropna()
print(f"  rmse_test_L / rmse_test_B0 : median={rel.median():.3f}  q10={rel.quantile(.1):.3f}  q90={rel.quantile(.9):.3f}")
print(f"  cells where L predicts BETTER than B0 : {(rel < 1).sum()} / {len(rel)}")
print(f"  of those, cells where nire_h26_L > 0.5: {((rel < 1) & (pv['nire_persistent_step_h26_L'] > 0.5)).sum()}")
print(f"  cells where L predicts better than B0 AND nire_h26_L > 0.20 : {((rel < 1) & (pv['nire_persistent_step_h26_L'] > 0.20)).sum()}")

print("\nStrongest-prediction cells (lowest rmse_test_L/rmse_test_B0) and their intervention error:")
z = nonG0.assign(rmse_ratio=rel).nsmallest(12, "rmse_ratio")
print(z[["rmse_ratio", "rmse_test_L", "rmse_test_B0", "nire_persistent_step_h26_L",
         "relative_shape_error_persistent_step_L", "scenario", "topology", "gamma"]].to_string())

print("\nN-vs-L prediction gain compared with N-vs-L intervention gain (frozen table):")
pvt = pd.read_csv(ROOT / "outputs/analysis/prediction_vs_intervention.csv")
pvt = pvt[pvt.cell_id != "C_G0"]
print(f"  cells with prediction_gain_N_vs_L > 0 : {(pvt.prediction_gain_N_vs_L > 0).sum()} / {len(pvt)}")
print(f"  cells with intervention_gain_N_vs_L < 0 : {(pvt.intervention_gain_N_vs_L < 0).sum()} / {len(pvt)}")
print(f"  cells flagged prediction_vs_intervention_inversion : {pvt.prediction_vs_intervention_inversion.astype(str).eq('True').sum()}")
print(f"  cells flagged frozen g3_prediction_intervention_inversion : {pvt.g3_prediction_intervention_inversion.astype(str).eq('True').sum()}")
inv = pvt[pvt.prediction_vs_intervention_inversion.astype(str).eq("True")]
print("\n  Inversion cells (N predicts better than L but intervenes worse):")
print(inv[["cell_id", "scenario", "prediction_gain_N_vs_L", "intervention_gain_N_vs_L",
           "rmse_test_N_median", "rmse_test_L_median",
           "nire_persistent_step_h26_N_median", "nire_persistent_step_h26_L_median"]].to_string(index=False))

print("\nS7 controlled-misspecification reporting cells (designed for this divergence):")
print(C.loc[["R_S7_delayed", "R_S7_effmismatch", "R_S7_nonlin", "R_S7_latentclimate"],
            ["variant", "rmse_test_L", "rmse_test_B0", "nire_persistent_step_h26_L",
             "rmse_test_N", "nire_persistent_step_h26_N", "strong_edge_undirected_f1",
             "false_edge_count", "false_edge_any_rate"]].to_string())

print("\nS9 candidate-support misspecification:")
s9 = C[C.scenario == "S9"]
print(s9[["topology", "gamma", "strong_edge_undirected_f1", "edge_recall", "edge_precision",
          "false_edge_count", "false_edge_any_rate", "nire_persistent_step_h26_N",
          "nire_persistent_step_h26_L", "estimability_rate_N"]].to_string())
