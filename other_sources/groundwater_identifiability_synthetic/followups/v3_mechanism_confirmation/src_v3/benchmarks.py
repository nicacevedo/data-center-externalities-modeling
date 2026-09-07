"""Seed-independent / Monte-Carlo pseudo-true benchmarks F_train and F_intervention.

F_train uses only the V3_BENCHMARK pool. F_intervention is a deterministic optimization
over the actual frozen model-L algebraic response family (diagonal A, own-node Q only).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from . import dgp, interventions
from .design import rng_for, seed_list
from .diagnostics import (
    inclusion_mask,
    l_family_paired_response,
    neighbour_flux_share,
    persistent_nire,
)
from .fit import _fit_scaled
from .modes import RNG_NAMED, require_legal
from .observations import TRAIN, make_observations
from .rng import StreamBank


def _true_step_bundle(design, system, trajectory, bundle):
    k = int(bundle.cadence)
    cfg = design["interventions"]
    primary = int(cfg["primary_horizon_fine_steps"])
    horizon_fine = int(cfg["cumulative_drawdown_horizon_fine_steps"])
    inclusion = float(design["metrics"].get("nire_node_inclusion_threshold", 0.01))
    onset_transition = bundle.test_onset()
    onset_fine = trajectory.analysis_start + int(bundle.t_fine[onset_transition])
    available = trajectory.h.shape[0] - onset_fine - 1
    horizon_fine = int(min(horizon_fine, available))
    n_steps = max(1, horizon_fine // k)
    specs = interventions.build_intervention_specs(design, system, trajectory, horizon_fine)
    spec = next(s for s in specs if s.name == "persistent_step")
    delta_true_fine = interventions.true_paired_response(system, trajectory, onset_fine, spec, k)
    delta_true = interventions.sample_true_at_cadence(delta_true_fine, k, n_steps)
    include = inclusion_mask(delta_true, inclusion)
    delta_q_fine = interventions._delta_q_fine(spec, system.n_nodes, k)
    delta_q_interval = np.stack(
        [delta_q_fine[t * k : (t + 1) * k].sum(axis=0) for t in range(n_steps)],
        axis=0,
    )
    steps = int(np.ceil(primary / k))
    return spec, delta_true, include, delta_q_interval, steps, n_steps, k


def f_intervention_for_system(design, system, trajectory, bundle) -> dict[str, Any]:
    """Minimum frozen persistent-step NIRE in the actual L family.

    Search: dense grid over a_0 (unconstrained except finite recursion), closed-form
    kappa_0 | a_0. Other nodes keep kappa=0 (own-pumping only). Independently verified
    on a denser grid.
    """
    _, delta_true, include, dQ, steps, n_steps, _k = _true_step_bundle(
        design, system, trajectory, bundle
    )
    n = system.n_nodes
    pumped = 0
    true0 = delta_true[: steps + 1, pumped]

    def nire_of(a0: float, kappa0: float) -> float:
        a_diag = np.zeros(n)
        a_diag[pumped] = a0
        beta = np.zeros(n)
        beta[pumped] = kappa0
        hat = l_family_paired_response(a_diag, beta, dQ)
        if not np.all(np.isfinite(hat[: steps + 1])):
            return float("inf")
        return persistent_nire(delta_true, hat, include, steps)

    def objective_a(a0: float) -> tuple[float, float]:
        a_diag = np.zeros(n)
        a_diag[pumped] = float(a0)
        g = l_family_paired_response(a_diag, np.eye(n)[pumped], dQ)[: steps + 1, pumped]
        if not np.all(np.isfinite(g)) or float(g @ g) <= 1e-18:
            return 0.0, nire_of(float(a0), 0.0)
        kappa = float(g @ true0 / (g @ g))
        return kappa, nire_of(float(a0), kappa)

    from scipy.optimize import minimize_scalar

    def obj(a0: float) -> float:
        return objective_a(a0)[1]

    opt = minimize_scalar(obj, bounds=(-2.5, 2.5), method="bounded", options={"xatol": 1e-14})
    best_a = float(opt.x)
    best_k, best_nire = objective_a(best_a)

    coarse = np.linspace(-2.5, 2.5, 2001)
    verify_nire, verify_a, verify_k = best_nire, best_a, best_k
    for a0 in coarse:
        kappa, val = objective_a(float(a0))
        if val + 1e-15 < verify_nire:
            verify_a, verify_k, verify_nire = float(a0), float(kappa), float(val)
    if verify_nire < best_nire:
        best_a, best_k, best_nire = verify_a, verify_k, verify_nire

    certified = abs(verify_nire - best_nire) <= 1e-8 + 1e-6 * max(1.0, abs(best_nire))
    neighbor_true = {
        i: float(np.linalg.norm(delta_true[:, i]))
        for i in range(n)
        if i != pumped
    }
    return {
        "F_intervention": float(best_nire) if np.isfinite(best_nire) else float("nan"),
        "F_intervention_a0": best_a,
        "F_intervention_kappa0": best_k,
        "F_intervention_certified": bool(certified),
        "F_intervention_verify_nire": float(verify_nire),
        "F_intervention_verify_a0": verify_a,
        "neighbor_true_response_norm_max": (
            max(neighbor_true.values()) if neighbor_true else 0.0
        ),
        "n_included_nodes": int(np.sum(include)),
        "include_node0": bool(include[0]) if include.size else False,
    }


def _pooled_train_ols(designs_and_y: list[tuple[np.ndarray, np.ndarray, tuple[str, ...]]]):
    """Pool TRAIN rows across Monte Carlo draws and fit unpenalized OLS (same as L)."""
    names = designs_and_y[0][2]
    X = np.concatenate([item[0] for item in designs_and_y], axis=0)
    y = np.concatenate([item[1] for item in designs_and_y], axis=0)
    intercept, coef, _diag = _fit_scaled(
        X, y, np.zeros(X.shape[1], dtype=bool), 0.0
    )
    return intercept, coef, names, int(X.shape[0])


def f_train_for_cell(
    design: dict[str, Any],
    regime,
    rng_mode: str,
    system_seed_mode: str,
) -> dict[str, Any]:
    """Monte Carlo approximation of the TRAIN-distribution one-step L projection."""
    require_legal(rng_mode, system_seed_mode)
    seeds = seed_list(design, "V3_BENCHMARK")
    options = {}
    from .evaluation import scenario_options

    options = scenario_options(design, regime)
    collected: dict[int, list] = {}
    systems = []
    last_bundle = None
    last_traj = None
    last_system = None
    coef_draws: dict[int, list[np.ndarray]] = {}

    for seed in seeds:
        rng = rng_for(int(seed))
        streams = StreamBank(int(seed)) if rng_mode == RNG_NAMED else None
        system = dgp.build_system(
            design,
            topology=regime.topology,
            memory=regime.memory,
            gamma_label=regime.gamma,
            recharge_efficiency=float(options.get("recharge_efficiency", 1.0)),
            system_seed_mode=system_seed_mode,
        )
        if options.get("null_mode") == "matched_local_dynamics":
            system = dgp.as_matched_local_dynamics_null(system)
        traj = dgp.simulate(design, system, regime, rng, options, streams=streams)
        bundle = make_observations(design, system, traj, regime, rng, streams=streams)
        from .models import build_design

        for node in np.flatnonzero(bundle.observed_nodes):
            d = build_design(bundle, int(node), "L")
            mask = d.split == TRAIN
            if int(np.sum(mask)) < d.X.shape[1] + 2:
                continue
            collected.setdefault(int(node), []).append((d.X[mask], d.y[mask], d.names))
            intercept, coef, _ = _fit_scaled(
                d.X[mask], d.y[mask], np.zeros(d.X.shape[1], dtype=bool), 0.0
            )
            coef_draws.setdefault(int(node), []).append(np.concatenate([[intercept], coef]))
        systems.append(system)
        last_bundle, last_traj, last_system = bundle, traj, system

    if last_system is None or not collected:
        return {"F_train": float("nan"), "F_train_n_mc": 0}

    a_diag = np.full(last_system.n_nodes, np.nan)
    beta_q = np.zeros(last_system.n_nodes)
    pooled_rows = 0
    coef_se = {}
    for node, items in collected.items():
        intercept, coef, names, n_rows = _pooled_train_ols(items)
        pooled_rows += n_rows
        a_diag[node] = float(coef[list(names).index("own_level")])
        if "pumping" in names:
            beta_q[node] = float(coef[list(names).index("pumping")])
        draws = np.stack(coef_draws[node], axis=0)
        coef_se[node] = float(np.std(draws[:, 1 + list(names).index("own_level")], ddof=1) / np.sqrt(len(draws)))

    spec, delta_true, include, dQ, steps, _n_steps, _k = _true_step_bundle(
        design, last_system, last_traj, last_bundle
    )
    hat = l_family_paired_response(np.nan_to_num(a_diag, nan=0.0), beta_q, dQ)
    f_train = persistent_nire(delta_true, hat, include, steps)

    half = max(1, len(seeds) // 2)
    # Split-half NIRE diagnostic using the first vs second half of the MC pool.
    def _half_nire(slice_items):
        a_h = np.zeros(last_system.n_nodes)
        b_h = np.zeros(last_system.n_nodes)
        for node, items in collected.items():
            subset = items[:slice_items] if slice_items > 0 else items
            intercept, coef, names, _ = _pooled_train_ols(subset)
            a_h[node] = float(coef[list(names).index("own_level")])
            if "pumping" in names:
                b_h[node] = float(coef[list(names).index("pumping")])
        hat_h = l_family_paired_response(a_h, b_h, dQ)
        return persistent_nire(delta_true, hat_h, include, steps)

    nire_first = _half_nire(max(1, len(next(iter(collected.values()))) // 2))
    return {
        "F_train": float(f_train) if np.isfinite(f_train) else float("nan"),
        "F_train_kind": "monte_carlo_pooled_train_ols",
        "F_train_n_mc": len(seeds),
        "F_train_pooled_train_rows": pooled_rows,
        "F_train_a0": float(a_diag[0]) if a_diag.size else float("nan"),
        "F_train_beta_q0": float(beta_q[0]) if beta_q.size else float("nan"),
        "F_train_own_level_mc_se_mean": float(np.mean(list(coef_se.values()))) if coef_se else float("nan"),
        "F_train_split_half_nire": float(nire_first) if np.isfinite(nire_first) else float("nan"),
        "F_train_split_half_abs_delta": (
            abs(float(nire_first) - float(f_train)) if np.isfinite(nire_first) and np.isfinite(f_train) else float("nan")
        ),
    }


def cell_structural_diagnostics(design, regime, system, trajectory) -> dict[str, Any]:
    A = np.asarray(system.A, float)
    return {
        "neighbour_flux_share": neighbour_flux_share(system, trajectory),
        "tau_relax": float(system.tau_relax_realized),
        "spectral_radius": float(system.rho_A),
        "mean_diagonal_transition": float(np.mean(np.diag(A))),
        "gamma_label": regime.gamma,
        "kind_neighbour_flux_share": "synthetic_dimensionless_coupling_materiality",
    }
