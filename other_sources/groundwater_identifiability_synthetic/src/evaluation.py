"""Replicate runner and gate evaluation.

This is the ONLY layer permitted to hold truth and estimates at the same time. It receives
`SystemTruth`/`Trajectory` from the DGP and `NodeFit`s from the estimation layer, and it is
where every comparison happens.

One call to `run_replicate` produces a flat dict of SCALARS. No trajectory arrays are
persisted, which is what keeps the Monte Carlo output compact.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from . import dgp, identifiability, interventions, metrics
from .design import MODULE_ROOT, RegimeSpec, rng_for
from .fit import (
    LadderFit,
    fit_ladder,
    implied_transition_matrix,
    max_abs_protected_prediction,
    protected_test_rmse,
)
from .observations import TEST, TRAIN, make_observations, mask_node_for_test

S6_CHARACTERIZATION_PATH = (
    MODULE_ROOT / "outputs" / "provenance" / "S6_VARIANCE_CHARACTERIZATION.json"
)


def _nanmean(values) -> float:
    """np.nanmean without the all-NaN RuntimeWarning. An all-NaN input means 'not measured'."""
    array = np.asarray(list(values), dtype=float)
    good = np.isfinite(array)
    return float(array[good].mean()) if good.any() else float("nan")


def _nanmax(values) -> float:
    array = np.asarray(list(values), dtype=float)
    good = np.isfinite(array)
    return float(array[good].max()) if good.any() else float("nan")


def _nanmedian(values) -> float:
    array = np.asarray(list(values), dtype=float)
    good = np.isfinite(array)
    return float(np.median(array[good])) if good.any() else float("nan")


# -------------------------------------------------------------------------------------
# Scenario wiring
# -------------------------------------------------------------------------------------


def scenario_options(design: dict[str, Any], regime: RegimeSpec) -> dict[str, Any]:
    """Translate a scenario label (and S7 variant) into DGP options."""
    options: dict[str, Any] = {}
    if regime.scenario == "S7":
        variants = design["s7_variants"]
        variant = regime.variant
        if variant == "delayed_recharge":
            options["recharge_lag_weights"] = list(variants["delayed_recharge"]["lag_weights"])
        elif variant == "weak_nonlinear_recharge":
            options["nonlinear_recharge_kappa"] = 0.25
        elif variant == "latent_common_climate":
            options["latent_common_climate_sd"] = float(
                variants["latent_common_climate"]["common_factor_sd"]
            )
        elif variant == "recharge_efficiency_mismatch":
            options["recharge_efficiency"] = float(
                variants["recharge_efficiency_mismatch"]["recharge_efficiency"]
            )
    if regime.scenario == "S8":
        options["placebo_correlation"] = float(
            design["s8_placebo_construction"]["placebo_correlation_with_recharge"]
        )
    return options


def _forcing_sampler(design: dict[str, Any]):
    """Within-interval draws of the PUMPING deviation from the frozen forcing process.

    The pseudo-true coarse coefficient depends on the forcing process, so this must be the
    actual frozen process, not a convenient iid stand-in: the AR(1) serial correlation inside
    a cadence interval changes the projection. Deviations are taken about the process mean
    because the seasonal and mean components are absorbed by the estimator's calendar terms.

    Single-channel by construction: this projects the PUMPING channel only. Since the DGP
    imposes B_R = B_Q, the recharge channel has the same algebra, and the two channels are
    close to orthogonal within an interval once seasonality is removed. This quantity is a
    REPORTED DIAGNOSTIC, never a gate input.
    """
    qspec = design["forcing"]["pumping"]
    phi = float(qspec["ar1_phi"])
    innovation_sd = float(qspec["ar1_innovation_sd"])
    excitation_sd = float(qspec["independent_excitation_sd"])
    stationary_sd = innovation_sd / np.sqrt(max(1.0 - phi * phi, 1e-12))

    def sampler(rng: np.random.Generator, k: int, n: int) -> np.ndarray:
        ar = np.zeros((k, n))
        ar[0] = rng.normal(0.0, stationary_sd, size=n)
        for r in range(1, k):
            ar[r] = phi * ar[r - 1] + rng.normal(0.0, innovation_sd, size=n)
        return ar + rng.normal(0.0, excitation_sd, size=(k, n))

    return sampler


# -------------------------------------------------------------------------------------
# Replicate
# -------------------------------------------------------------------------------------


def run_replicate(
    design: dict[str, Any],
    regime: RegimeSpec,
    seed: int,
    with_bootstrap: bool = False,
    n_bootstrap: int = 0,
) -> dict[str, Any]:
    rng = rng_for(seed)
    options = scenario_options(design, regime)

    system = dgp.build_system(
        design,
        topology=regime.topology,
        memory=regime.memory,
        gamma_label=regime.gamma,
        recharge_efficiency=float(options.get("recharge_efficiency", 1.0)),
    )
    stability = dgp.check_stability(design, system)

    effective_regime = regime
    trajectory = dgp.simulate(design, system, effective_regime, rng, options)
    bundle = make_observations(
        design,
        system,
        trajectory,
        effective_regime,
        rng,
        use_placebo_as_pumping=(regime.scenario == "S8"),
    )
    ladder = fit_ladder(bundle, design)

    record: dict[str, Any] = {
        "cell_id": regime.cell_id,
        "scenario": regime.scenario,
        "topology": regime.topology,
        "variant": regime.variant or "",
        "memory": regime.memory,
        "gamma": regime.gamma,
        "cadence": regime.cadence,
        "pumping_quality": regime.pumping_quality,
        "recharge_quality": regime.recharge_quality,
        "confounding_rho": regime.confounding_rho,
        "mcar_fraction": regime.mcar_fraction,
        "blocks_per_node": regime.blocks_per_node,
        "observed_node_fraction": regime.observed_node_fraction,
        "snr_head": regime.snr_head,
        "process_noise_sd": effective_regime.process_noise_sd,
        "seed": int(seed),
        "n_nodes": system.n_nodes,
        "rho_A": stability["rho_A"],
        "tau_relax_realized": stability["tau_relax_realized"],
        "cadence_over_tau_relax": regime.cadence / stability["tau_relax_realized"],
        "min_diagonal_A": stability["min_diagonal_A"],
        "burn_in_fine_steps": trajectory.burn_in,
        "n_transitions": bundle.n_transitions,
        "clip_fraction": trajectory.clip_fraction,
        "absolute_pumping_scale_known": bool(bundle.absolute_pumping_scale_known),
        "selected_bandwidth": ladder.selection.get("S", {}).get("bandwidth", np.nan),
        "selected_lambda": ladder.selection.get("N", {}).get("lambda", np.nan),
    }
    record.update(_realized_signal_diagnostics(design, trajectory, bundle))

    # ---- predictive diagnostics (SECONDARY) ----
    for model in ("B0", "L", "S", "N"):
        record[f"rmse_test_{model}"] = protected_test_rmse(ladder, model)
        record[f"max_abs_protected_prediction_{model}"] = (
            max_abs_protected_prediction(ladder, model) if model in ladder.fits else np.nan
        )
    if np.isfinite(record["rmse_test_B0"]) and record["rmse_test_B0"] > 0:
        for model in ("L", "S", "N"):
            record[f"rmse_improvement_vs_B0_{model}"] = 1.0 - (
                record[f"rmse_test_{model}"] / record["rmse_test_B0"]
            )

    # ---- identifiability diagnostics ----
    diag_nodes = [int(i) for i in np.flatnonzero(bundle.observed_nodes)]
    for model in ("L", "N"):
        if model not in ladder.designs:
            continue
        collected = [
            identifiability.design_diagnostics(ladder.designs[model][node], TRAIN)
            for node in diag_nodes
            if node in ladder.designs[model]
        ]
        if not collected:
            continue
        for key in collected[0]:
            values = np.array([c[key] for c in collected], dtype=float)
            record[f"{key}_{model}"] = _nanmean(values)
        record[f"rank_deficiency_max_{model}"] = _nanmax(
            [c["rank_deficiency"] for c in collected]
        )

    # ---- parameter recovery, subject to the cadence rule ----
    k = bundle.cadence
    A_true_k = np.linalg.matrix_power(system.A, k)
    record["direct_parameter_recovery_is_primary"] = bool(k == 1)

    beta_q_hat = np.full(system.n_nodes, np.nan)
    for node, fit in ladder.fits.get("L", {}).items():
        if fit is not None:
            beta_q_hat[node] = fit.coef_of("pumping", np.nan)
    record["sign_correct_fraction_L"] = float(np.mean(beta_q_hat < 0))
    record["beta_q_hat_mean_L"] = _nanmean(beta_q_hat)

    absolute_S_identifiable = bool(
        bundle.absolute_pumping_scale_known
        and k == 1
        and regime.scenario not in ("S7",)
    )
    record["absolute_S_identifiable"] = absolute_S_identifiable

    S_hat = np.full(system.n_nodes, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        negative = beta_q_hat < 0
        S_hat[negative] = -system.dt / beta_q_hat[negative]
    if absolute_S_identifiable:
        rel = np.abs(S_hat - system.S) / system.S
        record["storage_relative_error_median"] = _nanmedian(rel)
    else:
        record["storage_relative_error_median"] = np.nan

    if k == 1:
        record["B_Q_relative_error_median"] = _nanmedian(
            np.abs(-beta_q_hat - system.B_Q) / system.B_Q
        )
    else:
        record["B_Q_relative_error_median"] = np.nan
        try:
            B_pseudo = metrics.pseudo_true_coarse_B(
                system.A,
                system.B_Q,
                k,
                _forcing_sampler(design),
                int(design["estimands"]["pseudo_true_coarse_coefficient"]["monte_carlo_draws"]),
                rng_for(seed + 991),
            )
            record["B_Q_pseudo_true_diag_mean"] = float(np.mean(np.diag(B_pseudo)))
            record["B_Q_pseudo_true_relative_error_median"] = _nanmedian(
                np.abs(-beta_q_hat - np.diag(B_pseudo)) / np.abs(np.diag(B_pseudo))
            )
        except Exception:  # numerical failure must not kill a replicate
            record["B_Q_pseudo_true_diag_mean"] = np.nan
            record["B_Q_pseudo_true_relative_error_median"] = np.nan

    for model in ("L", "N"):
        if model not in ladder.fits:
            continue
        A_hat = implied_transition_matrix(ladder, model, system.n_nodes)
        good = np.isfinite(A_hat)
        if good.any():
            record[f"A_vs_Ak_max_abs_error_{model}"] = _nanmax(
                np.abs(A_hat[good] - A_true_k[good])
            )
            record[f"A_diag_relative_error_{model}"] = _nanmedian(
                np.abs(np.diag(A_hat) - np.diag(A_true_k))
                / np.maximum(np.abs(np.diag(A_true_k)), 1e-12)
            )

    # ---- network recovery ----
    threshold = float(design["network_semantics"]["strong_edge_threshold"])
    all_pairs = {(i, j) for i in range(system.n_nodes) for j in range(i + 1, system.n_nodes)}
    if "N" in ladder.fits and system.n_nodes > 1:
        kappa_hat = np.zeros((system.n_nodes, system.n_nodes))
        for node, fit in ladder.fits["N"].items():
            if fit is not None:
                kappa_hat[node] = fit.kappa_vector(system.n_nodes)
        true_strong = metrics.strong_true_edges(A_true_k, threshold)
        predicted = metrics.detected_edges(kappa_hat, threshold)
        record.update(metrics.edge_metrics(true_strong, predicted, all_pairs))
        record["n_true_strong_edges"] = float(len(true_strong))
        record["false_edge_count"] = float(len(predicted - true_strong))
        record["false_edge_any"] = float(len(predicted - true_strong) >= 1)
        record["true_edges_outside_candidate_set"] = float(
            len(true_strong - set(bundle.candidate_pairs))
        )
        record.update(
            metrics.d_phys(
                kappa_hat,
                S_hat,
                set(bundle.candidate_pairs),
                threshold,
                float(design["network_semantics"]["physics_consistency_diagnostic"]["epsilon_stab"]),
                absolute_S_identifiable,
            )
        )
        strong_weight_errors = [
            abs(kappa_hat[i, j] - A_true_k[i, j]) for (i, j) in true_strong
        ]
        record["strong_coupling_weight_error"] = (
            float(np.mean(strong_weight_errors)) if strong_weight_errors else np.nan
        )

    # ---- estimability (ALWAYS populated) ----
    record.update(_estimability_block(bundle, ladder))

    # ---- interventions (paired, protected) ----
    record.update(_intervention_block(design, system, trajectory, bundle, ladder, regime))

    # ---- masked node ----
    record.update(_masked_node_block(design, system, trajectory, bundle, ladder))

    # ---- uncertainty (diagnostic only) ----
    if with_bootstrap and n_bootstrap > 0:
        record.update(
            _bootstrap_block(design, system, bundle, ladder, n_bootstrap, stability, seed)
        )

    # ---- SGI_G0 exact-recovery quantities ----
    if regime.scenario == "S0":
        record.update(_g0_block(system, bundle, ladder))

    return record


def _g0_block(system, bundle, ladder: LadderFit) -> dict[str, Any]:
    """Exact-recovery quantities for the deterministic sanity gate.

    Under S0 the data are noise-free with exact forcing at cadence 1, so an identifiable
    design must reproduce the truth to numerical tolerance. Anything else is an
    implementation defect, not a scientific finding.
    """
    out: dict[str, Any] = {}
    fit = ladder.fits.get("L", {}).get(0)
    design_obj = ladder.designs.get("L", {}).get(0)
    if fit is None or design_obj is None:
        out["g0_max_abs_transition_residual"] = np.nan
        out["g0_max_abs_relative_coef_error"] = np.nan
        out["g0_storage_relative_error"] = np.nan
        return out

    residual = design_obj.y - fit.predict(design_obj.X)
    out["g0_max_abs_transition_residual"] = _nanmax(np.abs(residual))

    truth = {
        "own_level": float(system.A[0, 0]),
        "pumping": float(-system.B_Q[0]),
        "recharge_proxy": float(system.B_R[0]),
    }
    errors = []
    for name, true_value in truth.items():
        estimate = fit.coef_of(name, np.nan)
        errors.append(abs(estimate - true_value) / max(abs(true_value), 1e-12))
        out[f"g0_coef_{name}"] = float(estimate)
        out[f"g0_true_{name}"] = true_value
    intercept_true = float(system.b[0])
    errors.append(abs(fit.intercept - intercept_true) / max(abs(intercept_true), 1e-12))
    out["g0_intercept"] = float(fit.intercept)
    out["g0_true_intercept"] = intercept_true
    out["g0_max_abs_relative_coef_error"] = _nanmax(errors)

    beta_q = fit.coef_of("pumping", np.nan)
    if np.isfinite(beta_q) and beta_q < 0:
        S_hat = -system.dt / beta_q
        out["g0_storage_relative_error"] = float(abs(S_hat - system.S[0]) / system.S[0])
        out["g0_S_hat"] = float(S_hat)
        out["g0_S_true"] = float(system.S[0])
    else:
        out["g0_storage_relative_error"] = np.nan
    return out


def _estimability_block(bundle, ladder: LadderFit) -> dict[str, Any]:
    """Whether each rung could be fitted at all, recorded for EVERY replicate.

    A rung that cannot be estimated and a rung that was estimated and performed badly both
    leave NaN metrics, but they are opposite findings, and the deliverable is a data-adequacy
    map on which "the network model is not estimable at this observation quality" is one of
    the most informative cells. So estimability is recorded as a first-class result rather
    than inferred from absent columns.

    A rung is UNDERDETERMINED when admissible rows are too few for its column count: the N
    rung requires a node and all its candidate neighbours to be observed in the same
    interval, so admissible rows fall off far faster than the raw missingness rate.
    """
    out: dict[str, Any] = {}
    for model in ("B0", "L", "S", "N"):
        designs = ladder.designs.get(model, {})
        fits = ladder.fits.get(model, {})
        n_nodes = len(designs)
        if n_nodes == 0:
            # Distinguish a rung that does not exist for this topology (N on a single node)
            # from one that exists but had no admissible row anywhere. The first is a
            # definitional absence; the second is the data-adequacy result itself.
            applicable = not (model in ("S", "N") and int(bundle.observed_nodes.size) < 2)
            out[f"estimable_{model}"] = 0.0
            out[f"estimability_status_{model}"] = (
                "NO_ADMISSIBLE_ROWS" if applicable else "MODEL_NOT_APPLICABLE"
            )
            out[f"n_nodes_fitted_{model}"] = 0.0
            out[f"frac_nodes_fitted_{model}"] = np.nan
            out[f"median_admissible_train_rows_{model}"] = 0.0
            continue

        fitted = sum(1 for node in designs if fits.get(node) is not None)
        train_rows = [int(np.sum(d.split == "TRAIN")) for d in designs.values()]
        n_cols = int(np.median([d.X.shape[1] for d in designs.values()]))
        out[f"n_nodes_fitted_{model}"] = float(fitted)
        out[f"frac_nodes_fitted_{model}"] = float(fitted) / float(n_nodes)
        out[f"median_admissible_train_rows_{model}"] = float(np.median(train_rows))
        out[f"n_cols_design_{model}"] = float(n_cols)
        out[f"estimable_{model}"] = float(fitted == n_nodes)
        out[f"estimability_status_{model}"] = (
            "ESTIMABLE" if fitted == n_nodes
            else ("UNDERDETERMINED" if fitted == 0 else "PARTIAL")
        )
    return out


def _realized_signal_diagnostics(design, trajectory, bundle) -> dict[str, Any]:
    """Realized head variability and observation noise.

    Required reporting: S6 marginal head variance is deliberately NOT force-matched to the
    coupled reference, so every cross-scenario comparison must be readable against the
    realized values. `snr_head` is defined against TOTAL head sd, which the seasonal swing
    dominates; the detrended companion removes the annual harmonics so the regime can also be
    read against the variability that actually identifies the forcing response.
    """
    window = trajectory.h[trajectory.analysis_start :]
    head_sd = float(np.mean(np.std(window, axis=0)))
    nu_sd = float(bundle.meta.get("nu_sd", 0.0))

    period = float(design["time"]["seasonal_period_fine_steps"])
    t = np.arange(window.shape[0], dtype=float)
    basis = np.column_stack(
        [
            np.ones_like(t),
            t / period,
            np.sin(2 * np.pi * t / period),
            np.cos(2 * np.pi * t / period),
        ]
    )
    coefficients, *_ = np.linalg.lstsq(basis, window, rcond=None)
    detrended_sd = float(np.mean(np.std(window - basis @ coefficients, axis=0)))

    return {
        "realized_head_sd": head_sd,
        "realized_head_sd_detrended": detrended_sd,
        "realized_observation_noise_sd": nu_sd,
        "realized_snr_head": head_sd / nu_sd if nu_sd > 0 else float("inf"),
        "realized_snr_head_detrended": detrended_sd / nu_sd if nu_sd > 0 else float("inf"),
        "seasonal_variance_share": 1.0 - (detrended_sd / head_sd) ** 2 if head_sd > 0 else np.nan,
    }


def _intervention_block(
    design: dict[str, Any],
    system,
    trajectory,
    bundle,
    ladder: LadderFit,
    regime: RegimeSpec,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    k = bundle.cadence
    cfg = design["interventions"]
    horizons = [int(h) for h in cfg["horizons_fine_steps"]]
    primary = int(cfg["primary_horizon_fine_steps"])
    horizon_fine = int(cfg["cumulative_drawdown_horizon_fine_steps"])
    inclusion = float(design["metrics"].get("nire_node_inclusion_threshold", 0.01))

    onset_transition = bundle.test_onset()
    onset_fine = trajectory.analysis_start + int(bundle.t_fine[onset_transition])
    available = trajectory.h.shape[0] - onset_fine - 1
    horizon_fine = int(min(horizon_fine, available))
    n_steps = max(1, horizon_fine // k)

    specs = interventions.build_intervention_specs(design, system, trajectory, horizon_fine)
    for spec in specs:
        delta_true_fine = interventions.true_paired_response(
            system, trajectory, onset_fine, spec, k
        )
        delta_true = interventions.sample_true_at_cadence(delta_true_fine, k, n_steps)
        norms = np.linalg.norm(delta_true, axis=0)
        if norms.max() <= 0:
            continue
        include = norms >= inclusion * norms.max()

        for model in ("B0", "L", "S", "N"):
            if model not in ladder.fits:
                continue
            delta_hat = interventions.model_paired_response(bundle, ladder, model, spec, n_steps)
            for horizon in horizons:
                steps = int(np.ceil(horizon / k))
                if steps < 1 or steps + 1 > delta_true.shape[0]:
                    continue
                per_node = [
                    metrics.normalized_error(delta_true[: steps + 1, i], delta_hat[: steps + 1, i])
                    for i in np.flatnonzero(include)
                ]
                key = f"nire_{spec.name}_h{horizon}_{model}"
                out[key] = _nanmean(per_node) if per_node else np.nan
                if horizon == primary:
                    rel = [
                        metrics.relative_shape_error(
                            delta_true[: steps + 1, i], delta_hat[: steps + 1, i]
                        )
                        for i in np.flatnonzero(include)
                    ]
                    out[f"relative_shape_error_{spec.name}_{model}"] = (
                        _nanmean(rel) if rel else np.nan
                    )
            cum_true = np.array([metrics.cumulative_drawdown(delta_true[:, i]) for i in range(system.n_nodes)])
            cum_hat = np.array([metrics.cumulative_drawdown(delta_hat[:, i]) for i in range(system.n_nodes)])
            denominator = np.abs(cum_true[include]).sum()
            out[f"cumulative_drawdown_error_{spec.name}_{model}"] = (
                float(np.abs(cum_hat[include] - cum_true[include]).sum() / denominator)
                if denominator > 0
                else np.nan
            )

    # S8: how large is the apparent response to a variable with zero causal effect?
    if regime.scenario == "S8":
        step_spec = next((s for s in specs if s.name == "persistent_step"), None)
        if step_spec is not None:
            delta_true_fine = interventions.true_paired_response(
                system, trajectory, onset_fine, step_spec, k
            )
            delta_true = interventions.sample_true_at_cadence(delta_true_fine, k, n_steps)
            true_magnitude = float(np.abs(delta_true).max())
            for model in ("L", "N"):
                if model not in ladder.fits:
                    continue
                delta_hat = interventions.model_paired_response(
                    bundle, ladder, model, step_spec, n_steps
                )
                placebo_magnitude = float(np.abs(delta_hat).max())
                out[f"placebo_step_response_{model}"] = placebo_magnitude
                out[f"placebo_relative_to_true_{model}"] = (
                    placebo_magnitude / true_magnitude if true_magnitude > 0 else np.nan
                )

    # Vulnerability ranking: step at each node in turn, rank by that node's own drawdown.
    if system.n_nodes > 2:
        magnitude = float(cfg["magnitude_fraction_of_mean_pumping"]) * float(
            design["forcing"]["pumping"]["mean"]
        )
        duration = int(cfg["types"]["persistent_step"]["duration_fine_steps"])
        true_scores, hat_scores = [], {m: [] for m in ("L", "S", "N")}
        for node in range(system.n_nodes):
            spec = interventions.InterventionSpec(
                f"vuln_{node}", (node,), magnitude, duration, horizon_fine
            )
            dt_fine = interventions.true_paired_response(system, trajectory, onset_fine, spec, k)
            dt_c = interventions.sample_true_at_cadence(dt_fine, k, n_steps)
            true_scores.append(metrics.cumulative_drawdown(dt_c[:, node]))
            for model in hat_scores:
                if model not in ladder.fits:
                    continue
                dh = interventions.model_paired_response(bundle, ladder, model, spec, n_steps)
                hat_scores[model].append(metrics.cumulative_drawdown(dh[:, node]))
        for model, scores in hat_scores.items():
            if len(scores) == system.n_nodes:
                ranking = metrics.vulnerability_ranking(
                    np.array(true_scores), np.array(scores), int(design["metrics"]["topk_k"])
                )
                out[f"vulnerability_spearman_{model}"] = ranking["spearman"]
                out[f"vulnerability_topk_overlap_{model}"] = ranking["topk_overlap"]

    return out


def _masked_node_block(design, system, trajectory, bundle, ladder: LadderFit) -> dict[str, Any]:
    out: dict[str, Any] = {}
    cfg = design["spatial_evaluation"]["masked_node_protocol"]
    if system.n_nodes < 2:
        return out

    # Frozen preferred index, with a deterministic fallback to the nearest observed node.
    # Under partial monitoring the preferred node is often not instrumented at all, and a
    # rigid index would silently delete the entire masked-node criterion in exactly the
    # sparse-network cells it is most informative about.
    preferred = 0 if system.topology in ("single", "star5") else 2
    observed = np.flatnonzero(bundle.observed_nodes)
    if observed.size == 0:
        out["masked_node_status"] = "NO_OBSERVED_NODES"
        return out
    node = int(observed[np.lexsort((observed, np.abs(observed - preferred)))[0]])
    out["masked_node_index"] = float(node)
    out["masked_node_used_fallback_index"] = float(node != preferred)

    onset = bundle.test_onset()
    horizon = int(min(int(cfg["mask_horizon_cadence_steps"]), bundle.n_transitions - onset))
    if horizon < 3 or onset < 1:
        out["masked_node_status"] = "HORIZON_TOO_SHORT"
        return out

    masked_bundle = mask_node_for_test(bundle, node, onset, horizon)
    truth_instants = trajectory.analysis_start + bundle.t_fine[onset : onset + horizon].astype(int)
    truth_instants = truth_instants[truth_instants < trajectory.h.shape[0]]
    true_heads = trajectory.h[truth_instants, node]

    min_steps = int(
        design["spatial_evaluation"]["masked_node_protocol"].get("min_completed_steps", 4)
    )
    for model in ("L", "S", "N"):
        if model not in ladder.fits:
            continue
        masked, carry_forward = interventions.masked_node_forecast(
            masked_bundle, ladder, model, node, onset, horizon
        )
        intact = interventions.observed_node_chained_forecast(
            bundle, ladder, model, node, onset, horizon
        )
        completed = int(np.sum(np.isfinite(masked)))
        out[f"masked_node_steps_completed_{model}"] = float(completed)
        out[f"masked_node_carry_forward_steps_{model}"] = float(carry_forward)
        out[f"masked_node_nmpe_{model}"] = (
            metrics.normalized_forecast_error(true_heads, masked)
            if completed >= min_steps
            else np.nan
        )
        out[f"observed_node_nmpe_{model}"] = metrics.normalized_forecast_error(true_heads, intact)
        # Record WHY a replicate is missing, so a NaN rate is diagnosable rather than mute.
        out[f"masked_node_status_{model}"] = (
            "OK" if completed >= min_steps
            else ("NO_START_OBSERVATION" if completed == 0 else "RECURSION_STOPPED_EARLY")
        )
    out["masked_node_status"] = "EVALUATED"
    out["masked_node_horizon"] = float(horizon)
    return out


def _bootstrap_block(design, system, bundle, ladder, n_bootstrap, stability, seed) -> dict[str, Any]:
    """Moving-block bootstrap over contiguous TRAIN blocks. DIAGNOSTIC ONLY.

    The iid bootstrap is invalid for these dependent series and is not used. Coverage is
    reported, never gated, in v1.
    """
    from .fit import _fit_scaled

    out: dict[str, Any] = {}
    if "L" not in ladder.designs:
        return out

    block = max(2, int(np.ceil(2.0 * stability["tau_relax_realized"] / bundle.cadence)))
    nominal = float(design["uncertainty"]["nominal_interval"])
    rng = rng_for(seed + 7717)
    covered, total = 0, 0

    for node, design_obj in ladder.designs["L"].items():
        mask = design_obj.split == TRAIN
        X, y = design_obj.X[mask], design_obj.y[mask]
        if X.shape[0] < 3 * block:
            continue
        try:
            idx = design_obj.names.index("pumping")
        except ValueError:
            continue

        estimates = []
        n_blocks = int(np.ceil(X.shape[0] / block))
        for _ in range(n_bootstrap):
            starts = rng.integers(0, X.shape[0] - block + 1, size=n_blocks)
            rows = np.concatenate([np.arange(s, s + block) for s in starts])[: X.shape[0]]
            try:
                _, coef, _ = _fit_scaled(X[rows], y[rows], design_obj.penalized, 0.0)
                estimates.append(coef[idx])
            except np.linalg.LinAlgError:
                continue
        if len(estimates) < max(5, n_bootstrap // 2):
            continue
        alpha = (1.0 - nominal) / 2.0
        lower, upper = np.quantile(estimates, [alpha, 1.0 - alpha])
        true_beta = -system.B_Q[node]
        total += 1
        covered += int(lower <= true_beta <= upper)
        out.setdefault("bootstrap_interval_width_mean", []).append(float(upper - lower))

    if total:
        out["bootstrap_coverage_beta_q"] = covered / total
        out["bootstrap_n_nodes"] = float(total)
        widths = out.pop("bootstrap_interval_width_mean", [])
        out["bootstrap_interval_width_mean"] = float(np.mean(widths)) if widths else np.nan
    else:
        out.pop("bootstrap_interval_width_mean", None)
    return out


# -------------------------------------------------------------------------------------
# Gate evaluation
# -------------------------------------------------------------------------------------


def evaluate_g0(design: dict[str, Any], records: list[dict]) -> dict[str, Any]:
    """SGI_G0: deterministic implementation sanity. Every seed must pass."""
    criteria = {c["id"]: c for c in design["gates"]["SGI_G0"]["criteria"]}
    results = {}

    results["G0_transition_exact"] = {
        "value": _nanmax(r.get("g0_max_abs_transition_residual", np.nan) for r in records),
        "threshold": float(criteria["G0_transition_exact"]["threshold"]),
    }
    results["G0_coefficient_exact"] = {
        "value": _nanmax(r.get("g0_max_abs_relative_coef_error", np.nan) for r in records),
        "threshold": float(criteria["G0_coefficient_exact"]["threshold"]),
    }
    results["G0_storage_exact"] = {
        "value": _nanmax(r.get("g0_storage_relative_error", np.nan) for r in records),
        "threshold": float(criteria["G0_storage_exact"]["threshold"]),
    }
    results["G0_design_full_rank"] = {
        "value": _nanmax(r.get("rank_deficiency_max_L", np.nan) for r in records),
        "threshold": 0.0,
    }

    for name, payload in results.items():
        payload["pass"] = bool(
            np.isfinite(payload["value"]) and payload["value"] <= payload["threshold"] + 1e-15
        )
    return {
        "gate": "SGI_G0",
        "criteria": results,
        "pass": all(p["pass"] for p in results.values()),
        "n_seeds": len(records),
    }
