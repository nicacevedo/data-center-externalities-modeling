"""Frozen ANALYSIS summarizer: every preregistered output, no gates, no V2 override.

Pass 2 must not require a summarizer-code patch. This suite feeds synthetic records that
cover all five blocks and asserts the frozen payload schema, including benchmark merge
and nested-prefix convergence, without reading any V3 ANALYSIS outcome.
"""

from __future__ import annotations

import pytest

from src_v3.diagnostics import RECOMBINATION_SEMANTICS
from src_v3.summarize_v3 import (
    BLOCK_A_LADDER,
    FORBIDDEN_INFERENTIAL_FIELDS,
    INTERVAL_SEMANTICS,
    V2_AUTHORITATIVE_STATUS,
    summarize_analysis,
    summarize_records,
)


def _row(cell_id: str, seed: int, **fields):
    rec = {
        "cell_id": cell_id,
        "seed": seed,
        "rng_mode": "named_substreams",
        "system_seed_mode": "orthogonal_v3",
        "nire_persistent_step_h26_L": 0.40,
        "nire_persistent_step_h4_L": 0.20,
        "nire_persistent_step_h13_L": 0.30,
        "nire_persistent_step_h52_L": 0.50,
        "relative_shape_error_persistent_step_L": 0.04,
        "cumulative_drawdown_error_persistent_step_L": 0.10,
        "beta_q_hat_mean_L": -0.08,
        "partial_reliability_q": 0.90,
        "variance_form_reliability_q": 0.90,
        "unconditional_reliability_q": 0.80,
        "theory_reliability_q": 0.91,
        "A_diag_relative_error_L": 0.01,
        "A_diag_signed_relative_error_L": -0.01,
        "nire_recomb_trueA_hatB": 0.12,
        "nire_recomb_hatA_trueB": 0.08,
        "condition_number_L": 10.0,
        "max_vif_L": 2.0,
        "pumping_excitation_fraction_L": 0.20,
        "median_admissible_train_rows_L": 80.0,
        "rmse_test_L": 0.05,
        "rmse_improvement_vs_B0_L": 0.30,
        "nire_persistent_step_h26_N": 0.35,
        "strong_edge_undirected_f1": 0.70,
        "edge_precision": 0.80,
        "false_edge_count": 1.0,
        "false_edge_any": 1.0,
        "neighbour_flux_share": 0.25,
        "mean_diagonal_transition": 0.90,
        "spectral_radius": 0.95,
        "placebo_false_effect_L": 0.0,
        "placebo_relative_to_true_L": 0.05,
        "estimability_status_L": "ESTIMATED",
        "estimability_status_N": "ESTIMATED",
        "estimable_L": 1.0,
        "estimable_N": 1.0,
        "sign_correct_fraction_L": 1.0,
        "rmse_test_B0": 0.08,
        "max_abs_protected_prediction_L": 0.02,
    }
    rec.update(fields)
    return rec


CELLS = [
    "A_PEXACT", "A_S025", "A_S050", "A_S100", "A_S200",
    "A1_PEXACT_K1", "A1_S100_K1",
    "B_GNONE", "B_GLOW", "B_GMED", "B_GHIGH",
    "C_REAL_GMED", "C_REAL_GHIGH",
    "D_PE_RE_R0", "D_PE_RE_R3", "D_PE_RN_R0", "D_PE_RN_R3",
    "D_PM_RE_R0", "D_PM_RE_R3", "D_PM_RN_R0", "D_PM_RN_R3",
]


def _records():
    rows = []
    for seed in (11, 12, 13):
        for cell in CELLS:
            extra = {}
            if cell.startswith("A_S") or cell == "A1_S100_K1":
                extra["beta_q_hat_mean_L"] = -0.04
                extra["partial_reliability_q"] = 0.50
            if cell.startswith("D_"):
                extra["placebo_false_effect_L"] = 1.0 if "PM" in cell and "RN" in cell else 0.0
                extra["placebo_relative_to_true_L"] = 0.40 if extra["placebo_false_effect_L"] else 0.05
            if cell.startswith("C_") or cell.startswith("B_"):
                extra["strong_edge_undirected_f1"] = 0.90 if cell.startswith("B_") else 0.55
            rows.append(_row(cell, seed, **extra))
    return rows


def _benchmarks():
    return {
        cell: {
            "F_intervention_all": 0.10 if cell.startswith("A_") or cell.startswith("D_") else 0.60,
            "F_intervention_pumped": 0.01,
            "neighbor_unmodeled_floor": 0.0 if cell.startswith(("A_", "D_")) else 0.50,
            "F_train_true": 0.15 if cell.startswith(("A_", "D_")) else 0.70,
            "F_train_obs": 0.25 if cell.startswith(("A_", "D_")) else 0.75,
            "F_intervention_global_certified": True,
            "F_intervention_domain": "extended_real_line_a_in_R_union_pm_inf__kappa_in_R",
            "n_included_nodes": 1 if cell.startswith(("A_", "D_")) else 4,
            "n_included_nonpumped_nodes": 0 if cell.startswith(("A_", "D_")) else 3,
        }
        for cell in CELLS
    }


def _convergence():
    rows = []
    for cell in CELLS:
        prev_true, prev_obs = 0.20, 0.30
        for n, true, obs in ((16, 0.18, 0.28), (32, 0.16, 0.26), (64, 0.155, 0.255), (128, 0.15, 0.25)):
            rows.append(
                {
                    "cell_id": cell,
                    "prefix_n": n,
                    "F_train_true_nire": true,
                    "F_train_obs_nire": obs,
                    "F_train_true_a_pumped": 0.85,
                    "F_train_obs_a_pumped": 0.80,
                    "F_train_true_beta_q_pumped": -0.10,
                    "F_train_obs_beta_q_pumped": -0.07,
                    "F_train_true_beta_recharge_pumped": 0.05,
                    "F_train_obs_beta_recharge_pumped": 0.04,
                }
            )
            prev_true, prev_obs = true, obs
    return rows


def test_summarize_analysis_emits_every_preregistered_block_and_no_gates():
    payload = summarize_analysis(
        _records(),
        benchmarks=_benchmarks(),
        convergence=_convergence(),
        n_bootstrap=50,
    )
    for key in FORBIDDEN_INFERENTIAL_FIELDS:
        assert key not in payload
    assert payload["gates"] == {}
    assert payload["no_p_values"] is True
    assert payload["no_significance_declarations"] is True
    assert payload["no_support_status_override"] is True
    assert payload["reinterprets_v2"] is False
    assert payload["v2_authoritative_status"]["LOCAL_RESPONSE_STATUS"] == (
        V2_AUTHORITATIVE_STATUS["LOCAL_RESPONSE_STATUS"]
    )
    assert payload["v2_authoritative_status"]["NETWORK_SUPPORT_FINAL"] == "NOT_EARNED"
    assert payload["interval_semantics"] == INTERVAL_SEMANTICS
    assert payload["recombination_diagnostics"]["semantics"] == RECOMBINATION_SEMANTICS

    for key in (
        "block_A_pumping_attenuation",
        "block_A_prime_cadence_anchor",
        "block_B_coupling",
        "block_C_identification",
        "block_D_factorial",
        "benchmark_layers",
        "benchmark_convergence",
        "estimability",
        "prediction_vs_intervention",
    ):
        assert key in payload, key

    a = payload["block_A_pumping_attenuation"]
    assert list(a["per_cell"]) == list(BLOCK_A_LADDER)
    assert "A_S100" in a["attenuation_diagnostic"]
    assert "mean-corrected" in a["pumping_error_model"]
    d = payload["block_D_factorial"]
    assert d["main_effects"] == ["pumping_quality", "recharge_quality", "confounding_rho"]
    assert len(d["two_way_interactions"]) == 3
    assert d["three_way_interaction"] == [
        "pumping_quality",
        "recharge_quality",
        "confounding_rho",
    ]
    fam = d["outcomes"]["placebo_false_effect_L"]
    assert "int_three_way" in fam
    assert fam["int_three_way"]["primary"] is False
    assert d["v2_like_corner"]["cell_id"] == "D_PM_RN_R3"
    assert "numeric replication gate" in d["v2_like_corner"]["role"].lower() or (
        "NOT a numeric" in d["v2_like_corner"]["role"]
    )

    layers = payload["benchmark_layers"]
    assert layers["ordering"] == [
        "F_intervention_all",
        "F_train_true",
        "F_train_obs",
        "fitted_nire_L",
    ]
    assert layers["decomposition_is_additive"] is False
    one = layers["per_cell"]["B_GHIGH"]
    assert one["layer_1_F_intervention_all"] == 0.60
    assert one["layer_2_F_train_true"] == 0.70
    assert one["layer_3_F_train_obs"] == 0.75
    assert one["companion_neighbor_unmodeled_floor"] == 0.50
    assert one["floor_invariant_holds"] is True

    conv = payload["benchmark_convergence"]
    assert conv["available"] is True
    assert conv["prefixes"] == [16, 32, 64, 128]
    assert "A_PEXACT" in conv["per_cell"]
    assert 128 in conv["per_cell"]["A_PEXACT"]["prefixes"]


def test_summarizer_refuses_non_substantive_modes():
    rows = _records()
    rows[0]["rng_mode"] = "legacy_sequential"
    rows[0]["system_seed_mode"] = "legacy_v2"
    with pytest.raises(ValueError, match="refuses non-uniform"):
        summarize_analysis(rows, n_bootstrap=20)


def test_smoke_wrapper_is_non_inferential_and_tolerates_mixed_absence():
    payload = summarize_records(_records()[:6], n_bootstrap=20)
    assert payload["non_inferential"] is True
    assert payload["gates"] == {}
    for key in FORBIDDEN_INFERENTIAL_FIELDS:
        assert key not in payload
