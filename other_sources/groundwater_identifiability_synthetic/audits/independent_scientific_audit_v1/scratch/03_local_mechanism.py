"""Local-response mechanism analysis over the frozen 129-cell surface. Read-only.

POST-HOC MECHANISM DIAGNOSTIC. Does not recompute or alter any preregistered gate.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 80)

OUT = Path("/tmp/sgi_independent_audit")
C = pd.read_csv(OUT / "02_cell_surface.csv").set_index("cell_id")

NIRE = "nire_persistent_step_h26_L"
CFG = ["scenario", "topology", "memory", "gamma", "cadence", "cadence_over_tau_relax",
       "tau_relax_realized", "pumping_quality", "recharge_quality", "recharge_sigma",
       "recharge_lag", "confounding_rho", "mcar_fraction", "blocks_per_node",
       "observed_node_fraction", "snr_head", "process_noise_sd", "n_nodes",
       "absolute_pumping_scale_known", "absolute_S_identifiable",
       "physical_parameter_identifiable"]

print("#" * 100)
print("# 1. FULL FROZEN CONFIGURATION OF EVERY G1 CELL (corrects the G1R2 interpretation error)")
print("#" * 100)
g1 = C.loc[["G1R1", "G1R2", "G1R3", "G1R4", "G1R5", "G1R6"]]
extra = ["realized_snr_head", "realized_snr_head_detrended", "realized_head_sd",
         "realized_observation_noise_sd", "realized_local_persistence_mean_A_ii",
         "pumping_excitation_fraction_L", "condition_number_L", "max_vif_L",
         "n_transitions", "n_rows_L", "seasonal_variance_share", NIRE]
print(g1[CFG + extra].T.to_string())

print("\n\n" + "#" * 100)
print("# 2. AUDIT QUESTION A — distribution of local persistent-step NIRE (h26) over all cells")
print("#" * 100)
nonG0 = C[C.scenario != "S0"]
print(f"n cells total = {len(C)}, non-G0 = {len(nonG0)}")
print(f"\nC_G0 (implementation-sanity oracle) {NIRE} = {C.loc['C_G0', NIRE]!r}")
d = nonG0[NIRE].dropna()
print(f"\nnon-G0 cells with finite {NIRE}: {len(d)}")
print(f"  min    = {d.min():.4f}   ({d.idxmin()})")
print(f"  q05    = {d.quantile(0.05):.4f}")
print(f"  q25    = {d.quantile(0.25):.4f}")
print(f"  median = {d.median():.4f}")
print(f"  q75    = {d.quantile(0.75):.4f}")
print(f"  max    = {d.max():.4f}   ({d.idxmax()})")
print(f"  cells <= 0.20 frozen G1 criterion : {(d <= 0.20).sum()}")
print(f"  cells <= 0.40                     : {(d <= 0.40).sum()}")
print(f"  cells <= 0.50                     : {(d <= 0.50).sum()}")

print("\n--- 12 BEST local-response cells (lowest median NIRE h26 L) ---")
best = nonG0.nsmallest(12, NIRE)
print(best[[NIRE] + CFG].to_string())
print("\n--- 10 WORST local-response cells ---")
worst = nonG0.nlargest(10, NIRE)
print(worst[[NIRE] + CFG].to_string())

print("\n--- FULL config of the single best non-G0 cell + comparison to C_G0 ---")
print(C.loc[[d.idxmin(), "C_G0"], CFG + extra].T.to_string())

print("\n\n" + "#" * 100)
print("# 3. AUDIT QUESTION B — what drives local intervention error (rank correlations)")
print("#" * 100)
drivers = ["A_diag_relative_error_L", "A_vs_Ak_max_abs_error_L",
           "B_Q_relative_error_median", "B_Q_pseudo_true_relative_error_median",
           "rmse_test_L", "rmse_improvement_vs_B0_L",
           "realized_snr_head", "realized_snr_head_detrended", "snr_head",
           "process_noise_sd", "mcar_fraction", "confounding_rho", "cadence",
           "cadence_over_tau_relax", "tau_relax_realized", "recharge_sigma",
           "recharge_lag", "observed_node_fraction", "blocks_per_node",
           "condition_number_L", "max_vif_L", "smallest_singular_value_L",
           "pumping_excitation_fraction_L", "n_transitions", "n_rows_L",
           "realized_local_persistence_mean_A_ii", "seasonal_variance_share",
           "relative_shape_error_persistent_step_L",
           "cumulative_drawdown_error_persistent_step_L"]
sub = nonG0[[NIRE] + [c for c in drivers if c in nonG0.columns]].apply(pd.to_numeric, errors="coerce")
sp = sub.corr(method="spearman")[NIRE].drop(NIRE).sort_values(key=lambda s: -s.abs())
print(f"\nSpearman rank correlation with {NIRE} across {len(nonG0)} non-G0 cells:")
for k, v in sp.items():
    n = int(sub[[NIRE, k]].dropna().shape[0])
    print(f"  {v:+.3f}   n={n:3d}   {k}")

print("\n\n" + "#" * 100)
print("# 4. HORIZON GROWTH — is intervention error a long-horizon compounding phenomenon?")
print("#" * 100)
hz = ["nire_persistent_step_h4_L", "nire_persistent_step_h13_L",
      "nire_persistent_step_h26_L", "nire_persistent_step_h52_L"]
print("\nMedian over non-G0 cells of the per-cell median NIRE, by horizon:")
for h in hz:
    v = pd.to_numeric(nonG0[h], errors="coerce").dropna()
    print(f"  {h:32s} n_cells={len(v):3d}  median={v.median():.4f}  q25={v.quantile(.25):.4f}  q75={v.quantile(.75):.4f}")
print("\nSame for C_G0 (exact-implementation oracle):")
for h in hz:
    print(f"  {h:32s} {C.loc['C_G0', h]!r}")
print("\nG1 cells across horizons:")
print(g1[hz].to_string())

print("\n\n" + "#" * 100)
print("# 5. PERSISTENCE vs PUMPING-RESPONSE recovery (EIV hypothesis, part 1)")
print("#" * 100)
k1 = nonG0[pd.to_numeric(nonG0.cadence, errors="coerce") == 1]
print(f"\nk=1 cells: {len(k1)}  (B_Q_relative_error_median is defined only here)")
cols = ["A_diag_relative_error_L", "B_Q_relative_error_median", NIRE,
        "rmse_test_L", "realized_snr_head", "process_noise_sd", "snr_head",
        "storage_relative_error_median", "scenario", "topology", "memory"]
print(k1[[c for c in cols if c in k1.columns]].to_string())

kgt1 = nonG0[pd.to_numeric(nonG0.cadence, errors="coerce") > 1]
print(f"\n\nk>1 cells: {len(kgt1)}  (pseudo-true coarse B_Q comparison)")
sub2 = kgt1[["A_diag_relative_error_L", "B_Q_pseudo_true_relative_error_median", NIRE]].apply(pd.to_numeric, errors="coerce").dropna()
print(f"  median A_diag_relative_error_L                 = {sub2['A_diag_relative_error_L'].median():.4f}")
print(f"  median B_Q_pseudo_true_relative_error_median   = {sub2['B_Q_pseudo_true_relative_error_median'].median():.4f}")
print(f"  spearman(A_diag_err , NIRE)  = {sub2.corr(method='spearman').loc['A_diag_relative_error_L', NIRE]:+.3f}")
print(f"  spearman(B_Q_ps_err , NIRE)  = {sub2.corr(method='spearman').loc['B_Q_pseudo_true_relative_error_median', NIRE]:+.3f}")
print(f"  spearman(A_diag_err , B_Q_ps_err) = {sub2.corr(method='spearman').loc['A_diag_relative_error_L','B_Q_pseudo_true_relative_error_median']:+.3f}")

print("\n\n" + "#" * 100)
print("# 6. 1-D STRESS CURVES (frozen), local model")
print("#" * 100)
show = [NIRE, "nire_persistent_step_h4_L", "nire_persistent_step_h52_L",
        "A_diag_relative_error_L", "B_Q_relative_error_median",
        "B_Q_pseudo_true_relative_error_median", "rmse_test_L",
        "realized_snr_head", "condition_number_L", "pumping_excitation_fraction_L",
        "estimability_rate_L"]
order = {
    "curve_snr": ["CURVE_curve_snr_2", "CURVE_curve_snr_5", "CURVE_curve_snr_10", "CURVE_curve_snr_20"],
    "curve_process_noise": ["CURVE_curve_process_noise_0p05", "CURVE_curve_process_noise_0p25", "CURVE_curve_process_noise_1p0"],
    "curve_cadence": ["CURVE_curve_cadence_1", "CURVE_curve_cadence_2", "CURVE_curve_cadence_4", "CURVE_curve_cadence_13"],
    "curve_missing": ["CURVE_curve_missing_0p0", "CURVE_curve_missing_0p1", "CURVE_curve_missing_0p3", "CURVE_curve_missing_0p5"],
    "curve_pumping_quality": ["CURVE_curve_pumping_quality_PEXACT", "CURVE_curve_pumping_quality_PMULTNOISE",
                              "CURVE_curve_pumping_quality_PSCALEBIAS", "CURVE_curve_pumping_quality_PTEMPAGG",
                              "CURVE_curve_pumping_quality_PSPATIALAGG"],
    "curve_recharge_quality": ["CURVE_curve_recharge_quality_REXACT", "CURVE_curve_recharge_quality_RNOISE",
                               "CURVE_curve_recharge_quality_RLAG", "CURVE_curve_recharge_quality_RNOISELAG",
                               "CURVE_curve_recharge_quality_RSCALE"],
    "curve_confounding": ["CURVE_curve_confounding_0p0", "CURVE_curve_confounding_0p3",
                          "CURVE_curve_confounding_0p6", "CURVE_curve_confounding_0p9"],
    "curve_memory": ["CURVE_curve_memory_LOW", "CURVE_curve_memory_MED", "CURVE_curve_memory_HIGH"],
    "curve_coupling_strength": ["CURVE_curve_coupling_strength_NONE", "CURVE_curve_coupling_strength_LOW",
                                "CURVE_curve_coupling_strength_MED", "CURVE_curve_coupling_strength_HIGH"],
    "curve_observed_nodes": ["CURVE_curve_observed_nodes_0p4", "CURVE_curve_observed_nodes_0p6",
                             "CURVE_curve_observed_nodes_0p8", "CURVE_curve_observed_nodes_1p0"],
    "curve_block_outage": ["CURVE_curve_block_outage_0", "CURVE_curve_block_outage_1", "CURVE_curve_block_outage_2"],
}
for name, ids in order.items():
    ids = [i for i in ids if i in C.index]
    print(f"\n--- {name} ---")
    print(C.loc[ids, [c for c in show if c in C.columns]].to_string())

print("\n\n" + "#" * 100)
print("# 7. TWO-FACTOR GRIDS, local model NIRE h26")
print("#" * 100)
gm = C[C.index.str.startswith("GRID_grid_cadence_x_memory")]
piv = gm.assign(cad=pd.to_numeric(gm.cadence)).pivot_table(index="cad", columns="memory", values=NIRE)
print("\n--- cadence x memory : NIRE h26 L ---")
print(piv.to_string())
piv2 = gm.assign(cad=pd.to_numeric(gm.cadence)).pivot_table(index="cad", columns="memory", values="cadence_over_tau_relax")
print("\n  (cadence / tau_relax_realized)")
print(piv2.to_string())
piv3 = gm.assign(cad=pd.to_numeric(gm.cadence)).pivot_table(index="cad", columns="memory", values="A_diag_relative_error_L")
print("\n  A_diag_relative_error_L")
print(piv3.to_string())

rc = C[C.index.str.startswith("GRID_grid_recharge_x_confounding")]
print("\n--- recharge_quality x confounding_rho : NIRE h26 L ---")
print(rc.pivot_table(index="recharge_quality", columns="confounding_rho", values=NIRE).to_string())
print("\n  placebo-free local: A_diag_relative_error_L")
print(rc.pivot_table(index="recharge_quality", columns="confounding_rho", values="A_diag_relative_error_L").to_string())
print("\n  B_Q_pseudo_true_relative_error_median")
print(rc.pivot_table(index="recharge_quality", columns="confounding_rho", values="B_Q_pseudo_true_relative_error_median").to_string())

mo = C[C.index.str.startswith("GRID_grid_missing_x_obsnodes")]
print("\n--- mcar_fraction x observed_node_fraction : NIRE h26 L ---")
print(mo.pivot_table(index="mcar_fraction", columns="observed_node_fraction", values=NIRE).to_string())

cs = C[C.index.str.startswith("GRID_grid_coupling_x_snr")]
print("\n--- gamma x snr_head : NIRE h26 L ---")
print(cs.pivot_table(index="gamma", columns="snr_head", values=NIRE).to_string())
print("\n  A_diag_relative_error_L")
print(cs.pivot_table(index="gamma", columns="snr_head", values="A_diag_relative_error_L").to_string())
print("\n  realized_snr_head")
print(cs.pivot_table(index="gamma", columns="snr_head", values="realized_snr_head").to_string())
