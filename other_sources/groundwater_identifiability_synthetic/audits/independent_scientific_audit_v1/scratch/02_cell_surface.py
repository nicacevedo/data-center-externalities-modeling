"""Per-cell configuration + local/network recovery surface over the frozen 129 cells.

Read-only. Builds one row per cell with the full observation configuration and the
already-frozen intervention/prediction/estimation-diagnostic medians.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(
    "/home/nacevedo/RA/data-center-externalities-modeling/"
    "other_sources/groundwater_identifiability_synthetic"
)
OUT = Path("/tmp/sgi_independent_audit")
SW = pd.read_csv(ROOT / "outputs/analysis/sweep_replicates.csv", low_memory=False)

ESTIMATED = "ESTIMATED"


def status(df, model):
    s = df.get(f"estimability_status_{model}").astype("string").fillna("")
    out = pd.Series("NOT_ESTIMABLE", index=df.index, dtype=object)
    out[s.isin([ESTIMATED, "ESTIMABLE"])] = ESTIMATED
    out[s == "FIT_FAILED"] = "FIT_FAILED"
    return out


CONFIG_COLS = [
    "scenario", "topology", "memory", "gamma", "cadence", "cadence_over_tau_relax",
    "tau_relax_realized", "rho_A", "min_diagonal_A",
    "pumping_quality", "recharge_quality", "recharge_sigma", "recharge_lag",
    "confounding_rho", "mcar_fraction", "blocks_per_node", "observed_node_fraction",
    "snr_head", "process_noise_sd", "n_nodes", "variant", "null_mode",
    "absolute_pumping_scale_known", "absolute_S_identifiable",
    "physical_parameter_identifiable", "direct_parameter_recovery_is_primary",
    "n_transitions", "n_true_strong_edges", "has_placebo",
]

# Metrics medianed over ESTIMATED replicates of the relevant model
L_METRICS = [
    "nire_persistent_step_h4_L", "nire_persistent_step_h13_L",
    "nire_persistent_step_h26_L", "nire_persistent_step_h52_L",
    "nire_pulse_h26_L", "nire_new_node_pumping_h26_L", "nire_multi_node_withdrawal_h26_L",
    "relative_shape_error_persistent_step_L", "cumulative_drawdown_error_persistent_step_L",
    "A_diag_relative_error_L", "A_vs_Ak_max_abs_error_L",
    "B_Q_relative_error_median", "B_Q_pseudo_true_relative_error_median",
    "B_Q_pseudo_true_diag_mean", "beta_q_hat_mean_L",
    "storage_relative_error_median", "rmse_test_L", "rmse_improvement_vs_B0_L",
    "condition_number_L", "max_vif_L", "smallest_singular_value_L",
    "rank_deficiency_L", "pumping_excitation_fraction_L", "sign_correct_fraction_L",
    "realized_snr_head", "realized_snr_head_detrended", "realized_head_sd",
    "realized_observation_noise_sd", "realized_local_persistence_mean_A_ii",
    "n_rows_L", "n_cols_L", "median_admissible_train_rows_L", "seasonal_variance_share",
    "vulnerability_spearman_L", "vulnerability_topk_overlap_L",
    "placebo_coef_abs_L", "placebo_step_response_L", "placebo_relative_to_true_L",
    "true_real_pumping_step_response", "d_phys_median",
]
N_METRICS = [
    "nire_persistent_step_h26_N", "nire_persistent_step_h52_N", "rmse_test_N",
    "strong_edge_undirected_f1", "edge_f1", "edge_precision", "edge_recall",
    "edge_false_positive", "edge_false_negative", "false_edge_count", "false_edge_any",
    "A_diag_relative_error_N", "A_vs_Ak_max_abs_error_N", "condition_number_N",
    "max_vif_N", "smallest_singular_value_N", "rank_deficiency_N",
    "masked_node_nmpe_N", "observed_node_nmpe_N", "selected_lambda",
    "strong_coupling_weight_error", "pumping_excitation_fraction_N",
    "placebo_false_effect_N", "n_rows_N", "n_cols_N",
]
PLAIN = ["nire_persistent_step_h26_B0", "nire_persistent_step_h26_S", "rmse_test_B0",
         "rmse_test_S", "placebo_false_effect_L", "clip_fraction"]

rows = []
for cell, d in SW.groupby("cell_id"):
    r = {"cell_id": cell, "n_replicates": len(d)}
    for c in CONFIG_COLS:
        if c in d:
            u = d[c].dropna().unique()
            r[c] = u[0] if len(u) == 1 else ("|".join(map(str, sorted(map(str, u)))) if len(u) else np.nan)
    st_l, st_n = status(d, "L"), status(d, "N")
    r["estimability_rate_L"] = float((st_l == ESTIMATED).mean())
    r["estimability_rate_N"] = float((st_n == ESTIMATED).mean())
    dl, dn = d[st_l == ESTIMATED], d[st_n == ESTIMATED]
    for m in L_METRICS:
        if m in d:
            v = pd.to_numeric(dl[m], errors="coerce")
            r[m] = float(np.nanmedian(v)) if v.notna().any() else np.nan
    for m in N_METRICS:
        if m in d:
            v = pd.to_numeric(dn[m], errors="coerce")
            r[m] = float(np.nanmedian(v)) if v.notna().any() else np.nan
    for m in PLAIN:
        if m in d:
            v = pd.to_numeric(d[m], errors="coerce")
            r[m] = float(np.nanmedian(v)) if v.notna().any() else np.nan
    # extra rates
    if "false_edge_count" in d and len(dn):
        r["false_edge_any_rate"] = float((pd.to_numeric(dn["false_edge_count"], errors="coerce") >= 1).mean())
    if "placebo_false_effect_L" in d and len(dl):
        v = pd.to_numeric(dl["placebo_false_effect_L"], errors="coerce")
        r["placebo_false_effect_rate_L"] = float((v == 1).mean()) if v.notna().any() else np.nan
    rows.append(r)

cells = pd.DataFrame(rows).set_index("cell_id").sort_index()
cells.to_csv(OUT / "02_cell_surface.csv")
print("cells:", cells.shape)
print("\ncell_id families:", sorted({c.split("_")[0] for c in cells.index}))
print("\nscenarios:", cells.scenario.value_counts().to_dict())
print("\nAll cell ids:")
for c in cells.index:
    print("  ", c)
