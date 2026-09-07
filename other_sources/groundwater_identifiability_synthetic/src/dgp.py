"""Synthetic truth generator.

RESTRICTED PHYSICALLY INTERPRETABLE SPECIAL CASE of the repository model
    h_{m+1} = A h_m + B_R R_m - B_Q q_m + eps_m
obtained by imposing a Laplacian-plus-leakage A and B_R = B_Q = dt * diag(1/S).
This is NOT a reparameterization of the general model. See REPOSITORY_PREMISE_CONFLICTS C4.

Everything in this module is TRUTH. `SystemTruth` and `Trajectory` must never be passed to
`models` or `fit`; the no-leakage tests enforce that.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .design import rng_for, structural_seed


class TruthAccessViolation(RuntimeError):
    """Raised by the test tripwire when estimation code touches a truth object."""


@dataclass(frozen=True)
class SystemTruth:
    """Frozen synthetic system. TRUTH -- never visible to estimation code."""

    topology: str
    coordinates: np.ndarray          # (n, 2)
    S: np.ndarray                    # (n,)  storage, strictly positive
    C: np.ndarray                    # (n, n) symmetric conductance, zero diagonal
    C0: np.ndarray                   # (n,)  boundary leakage, strictly positive
    h_b: np.ndarray                  # (n,)  boundary head
    A: np.ndarray                    # (n, n)
    b: np.ndarray                    # (n,)  boundary intercept
    B_Q: np.ndarray                  # (n,)  dt / S
    B_R: np.ndarray                  # (n,)  recharge_efficiency * dt / S
    kappa: np.ndarray                # (n, n) effective directed coupling dt*C_ij/S_i
    true_edges: frozenset            # undirected pairs (i, j) with i < j
    dt: float
    rho_A: float
    tau_relax_realized: float
    recharge_efficiency: float

    @property
    def n_nodes(self) -> int:
        return int(self.S.shape[0])


@dataclass(frozen=True)
class Trajectory:
    """Simulated fine-step truth. TRUTH -- never visible to estimation code."""

    h: np.ndarray                    # (T, n) fine-step heads, includes burn-in
    R_true: np.ndarray               # (T, n) latent true recharge
    Q_true: np.ndarray               # (T, n) true pumping
    Q_placebo: np.ndarray | None     # (T, n) zero-effect pumping-like variable (S8)
    eps: np.ndarray                  # (T, n) flux disturbance
    burn_in: int
    analysis_start: int              # fine index where the analysis horizon begins
    analysis_length: int
    burn_in_head_sd: float
    clip_fraction: float


# -------------------------------------------------------------------------------------
# System construction
# -------------------------------------------------------------------------------------


def _topology_arrays(design: dict[str, Any], topology: str) -> tuple[np.ndarray, list[tuple[int, int]]]:
    spec = design["topologies"][topology]
    coords = np.asarray(spec["coordinates"], dtype=float)
    edges = [tuple(sorted(e)) for e in (spec["true_edges"] or [])]
    return coords, edges


def build_system(
    design: dict[str, Any],
    topology: str,
    memory: str,
    gamma_label: str,
    recharge_efficiency: float = 1.0,
    process_noise_scale: float = 1.0,
) -> SystemTruth:
    """Construct the truth system.

    Memory and coupling are controlled independently: physical conductance is uniform and
    symmetric across true edges, boundary leakage is set to hit the target coupling share
    gamma, and the overall conductance scale is set analytically so the REALIZED relaxation
    time hits its target. The realized value is then recomputed from the eigensystem and is
    what downstream code reports.
    """
    dt = float(design["time"]["dt_fine"])
    coords, edges = _topology_arrays(design, topology)
    n = coords.shape[0]

    gamma = float(design["coupling"]["gamma_levels"][gamma_label])
    tau_target = float(design["memory_regimes"]["targets_fine_steps"][memory])

    # Storage heterogeneity is structural: fixed within a cell, so across-seed variability
    # is purely stochastic rather than a different aquifer each replicate.
    het = float(design["dgp"]["storage_S_heterogeneity"])
    s_base = float(design["dgp"]["storage_S_base"])
    struct_rng = rng_for(structural_seed("system", topology, memory, gamma_label, recharge_efficiency))
    S = s_base * (1.0 + struct_rng.uniform(-het, het, size=n))

    adjacency = np.zeros((n, n), dtype=float)
    for i, j in edges:
        adjacency[i, j] = 1.0
        adjacency[j, i] = 1.0
    degree = adjacency.sum(axis=1)

    has_coupling = gamma > 0.0 and len(edges) > 0
    if has_coupling:
        # C_ij = c for every true edge; boundary leakage carries share (1 - gamma).
        unit_C = adjacency.copy()
        unit_C0 = degree * (1.0 - gamma) / gamma
    else:
        unit_C = np.zeros((n, n), dtype=float)
        unit_C0 = np.ones(n, dtype=float)

    unit_L = np.diag(unit_C.sum(axis=1) + unit_C0) - unit_C
    # dt * diag(1/S) * L scales linearly in the conductance scale c, so the required c is
    # analytic rather than iterative.
    unit_M = dt * (unit_L / S[:, None])
    unit_eigs = np.linalg.eigvals(unit_M)
    lambda_min = float(np.min(np.real(unit_eigs)))
    if lambda_min <= 0.0:
        raise ValueError(f"non-positive smallest relaxation eigenvalue for {topology}/{gamma_label}")

    target_rho = float(np.exp(-1.0 / tau_target))
    c_scale = (1.0 - target_rho) / lambda_min

    C = c_scale * unit_C
    C0 = c_scale * unit_C0
    L = np.diag(C.sum(axis=1) + C0) - C
    A = np.eye(n) - dt * (L / S[:, None])

    h_b = np.full(n, float(design["dgp"]["boundary_head_h_b"]))
    b = dt * C0 * h_b / S
    B_Q = dt / S
    B_R = recharge_efficiency * dt / S
    kappa = dt * C / S[:, None]

    rho_A = float(np.max(np.abs(np.linalg.eigvals(A))))
    tau_realized = float(-1.0 / np.log(rho_A)) if 0.0 < rho_A < 1.0 else float("inf")

    return SystemTruth(
        topology=topology,
        coordinates=coords,
        S=S,
        C=C,
        C0=C0,
        h_b=h_b,
        A=A,
        b=b,
        B_Q=B_Q,
        B_R=B_R,
        kappa=kappa,
        true_edges=frozenset(edges),
        dt=dt,
        rho_A=rho_A,
        tau_relax_realized=tau_realized,
        recharge_efficiency=recharge_efficiency,
    )


def check_stability(design: dict[str, Any], system: SystemTruth) -> dict[str, Any]:
    """Assert both stability conditions. Returns the realized diagnostics."""
    stab = design["stability"]
    delta_diag = float(stab["diagonal_margin_delta_diag"])
    delta = float(stab["contraction_margin_delta"])

    diag_load = system.dt * (system.C.sum(axis=1) + system.C0) / system.S
    max_diag_load = float(np.max(diag_load))
    if max_diag_load > 1.0 - delta_diag:
        raise ValueError(
            f"discretization condition violated for {system.topology}: "
            f"max dt*(sum_j C_ij + C_i0)/S_i = {max_diag_load:.6f} > {1.0 - delta_diag}"
        )
    if system.rho_A > 1.0 - delta:
        raise ValueError(
            f"contraction condition violated for {system.topology}: "
            f"rho(A) = {system.rho_A:.6f} > {1.0 - delta}"
        )
    if np.any(system.S <= 0.0):
        raise ValueError("storage must be strictly positive")
    if np.any(system.C < 0.0):
        raise ValueError("conductance must be nonnegative")
    if np.any(system.C0 <= 0.0):
        raise ValueError("boundary leakage must be strictly positive for contraction")
    if np.any(system.A < 0.0):
        raise ValueError("A must be entrywise nonnegative")

    return {
        "max_diagonal_load": max_diag_load,
        "min_diagonal_A": float(np.min(np.diag(system.A))),
        "rho_A": system.rho_A,
        "tau_relax_realized": system.tau_relax_realized,
    }


def burn_in_length(design: dict[str, Any], system: SystemTruth) -> int:
    """Adaptive burn-in. The analysis horizon begins strictly AFTER this."""
    floor_steps = int(design["time"]["burn_in_floor_fine_steps"])
    multiple = float(design["time"]["burn_in_tau_multiple"])
    return int(max(floor_steps, np.ceil(multiple * system.tau_relax_realized)))


# -------------------------------------------------------------------------------------
# Forcing
# -------------------------------------------------------------------------------------


def _ar1(rng: np.random.Generator, phi: float, sd: float, length: int, n: int) -> np.ndarray:
    out = np.zeros((length, n))
    innovations = rng.normal(0.0, sd, size=(length, n))
    stationary_sd = sd / np.sqrt(max(1.0 - phi * phi, 1e-12))
    out[0] = rng.normal(0.0, stationary_sd, size=n)
    for t in range(1, length):
        out[t] = phi * out[t - 1] + innovations[t]
    return out


def _seasonal_phases(design: dict[str, Any], n: int, topology: str) -> np.ndarray:
    rng = rng_for(structural_seed("phases", topology, n))
    return rng.uniform(0.0, 2.0 * np.pi, size=n)


def generate_forcing(
    design: dict[str, Any],
    system: SystemTruth,
    rho: float,
    length: int,
    rng: np.random.Generator,
    latent_common_climate_sd: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Recharge and pumping over `length` fine steps.

    Confounding is imposed on the SEASONAL SHAPES: s_R uses sin and s_Q uses
    rho*sin + sqrt(1-rho^2)*cos, which are exactly orthogonal over a period, so the realized
    seasonal correlation equals rho by construction.
    """
    n = system.n_nodes
    period = float(design["time"]["seasonal_period_fine_steps"])
    rspec = design["forcing"]["recharge"]
    qspec = design["forcing"]["pumping"]

    t = np.arange(length, dtype=float)[:, None]
    phases = _seasonal_phases(design, n, system.topology)[None, :]
    angle = 2.0 * np.pi * t / period + phases

    s_R = np.sin(angle)
    s_Q = rho * np.sin(angle) + np.sqrt(max(1.0 - rho * rho, 0.0)) * np.cos(angle)

    R_base = float(rspec["mean"]) * (1.0 + float(rspec["seasonal_amplitude"]) * s_R) + _ar1(
        rng, float(rspec["ar1_phi"]), float(rspec["ar1_innovation_sd"]), length, n
    )

    if latent_common_climate_sd > 0.0:
        # The latent climate factor is MULTIPLICATIVE, for two reasons. (a) design_v1 gives
        # the factor's STATIONARY sd, while `_ar1` takes an INNOVATION sd, so the conversion
        # below is required; passing the value straight through inflates the factor by
        # 1/sqrt(1-phi^2) = 2.3x. (b) Even correctly scaled, an ADDITIVE factor leaves only
        # ~2.5 sd of headroom above zero at the seasonal trough and drives this scenario into
        # the clipping limit, which would put an undocumented nonlinearity into the one
        # scenario whose misspecification is supposed to be exactly characterized. A
        # climate anomaly scales recharge rather than adding a fixed volume, so the
        # multiplicative form is also the more physical one, and it keeps R > 0 by
        # construction.
        common_phi = 0.9
        # log-scale chosen so the induced absolute sd AT MEAN RECHARGE equals the frozen
        # latent_common_climate_sd, keeping confounder strength as designed.
        log_sd = latent_common_climate_sd / float(rspec["mean"])
        innovation_sd = log_sd * np.sqrt(1.0 - common_phi**2)
        common = _ar1(rng, common_phi, innovation_sd, length, 1)
        R = R_base * np.exp(common - 0.5 * log_sd**2)
    else:
        R = R_base
    Q = (
        float(qspec["mean"]) * (1.0 + float(qspec["seasonal_amplitude"]) * s_Q)
        + _ar1(rng, float(qspec["ar1_phi"]), float(qspec["ar1_innovation_sd"]), length, n)
        + rng.normal(0.0, float(qspec["independent_excitation_sd"]), size=(length, n))
    )

    n_clipped = int(np.sum(R < 0.0) + np.sum(Q < 0.0))
    clip_fraction = n_clipped / float(R.size + Q.size)
    return np.maximum(R, 0.0), np.maximum(Q, 0.0), clip_fraction


def _steady_state(system: SystemTruth, R_mean: np.ndarray, Q_mean: np.ndarray) -> np.ndarray:
    n = system.n_nodes
    drive = system.b + system.B_R * R_mean - system.B_Q * Q_mean
    return np.linalg.solve(np.eye(n) - system.A, drive)


def simulate(
    design: dict[str, Any],
    system: SystemTruth,
    regime,
    rng: np.random.Generator,
    scenario_options: dict[str, Any] | None = None,
) -> Trajectory:
    """Simulate fine-step truth: burn-in followed by the frozen analysis horizon."""
    options = scenario_options or {}
    burn_in = burn_in_length(design, system)
    horizon = int(design["time"]["analysis_horizon_fine_steps"])
    total = burn_in + horizon              # number of states; transitions use indices < total-1

    R, Q, clip_fraction = generate_forcing(
        design,
        system,
        rho=float(regime.confounding_rho),
        length=total,
        rng=rng,
        latent_common_climate_sd=float(options.get("latent_common_climate_sd", 0.0)),
    )

    # S7 variants that change the TRUTH's recharge channel.
    R_effective = R
    lag_weights = options.get("recharge_lag_weights")
    if lag_weights:
        weights = np.asarray(lag_weights, dtype=float)
        padded = np.vstack([np.repeat(R[:1], len(weights) - 1, axis=0), R])
        R_effective = sum(
            weights[w] * padded[len(weights) - 1 - w : len(weights) - 1 - w + total]
            for w in range(len(weights))
        )
    nonlinear_kappa = float(options.get("nonlinear_recharge_kappa", 0.0))
    if nonlinear_kappa > 0.0:
        R_effective = R_effective * (1.0 - nonlinear_kappa * R_effective / (1.0 + R_effective))

    # S8: an observed pumping-like variable strongly correlated with recharge but with
    # exactly zero causal effect on head.
    Q_placebo = None
    placebo_corr = float(options.get("placebo_correlation", 0.0))
    if placebo_corr > 0.0:
        r_z = (R - R.mean(axis=0)) / np.maximum(R.std(axis=0), 1e-12)
        independent = rng.normal(0.0, 1.0, size=R.shape)
        mixed = placebo_corr * r_z + np.sqrt(max(1.0 - placebo_corr**2, 0.0)) * independent
        qspec = design["forcing"]["pumping"]
        Q_placebo = np.maximum(float(qspec["mean"]) * (1.0 + 0.4 * mixed), 0.0)

    eps = rng.normal(0.0, float(regime.process_noise_sd), size=(total, system.n_nodes))
    if float(regime.process_noise_sd) == 0.0:
        eps = np.zeros((total, system.n_nodes))

    h = np.zeros((total, system.n_nodes))
    h[0] = _steady_state(system, R_effective.mean(axis=0), Q.mean(axis=0))
    for t in range(total - 1):
        h[t + 1] = (
            system.A @ h[t]
            + system.b
            + system.B_R * R_effective[t]
            - system.B_Q * Q[t]
            + system.B_Q * eps[t]
        )

    burn_in_head_sd = float(np.mean(np.std(h[:burn_in], axis=0)))

    return Trajectory(
        h=h,
        R_true=R_effective,
        Q_true=Q,
        Q_placebo=Q_placebo,
        eps=eps,
        burn_in=burn_in,
        analysis_start=burn_in,
        analysis_length=horizon,
        burn_in_head_sd=burn_in_head_sd,
        clip_fraction=clip_fraction,
    )


def rollout(
    system: SystemTruth,
    h0: np.ndarray,
    R: np.ndarray,
    Q: np.ndarray,
    eps: np.ndarray,
) -> np.ndarray:
    """Deterministic fine-step rollout given explicit forcing and noise.

    Used by the paired intervention evaluator, where baseline and intervention runs share
    h0, R and eps exactly so common disturbances cancel.
    """
    steps = Q.shape[0]
    out = np.zeros((steps + 1, system.n_nodes))
    out[0] = h0
    for t in range(steps):
        out[t + 1] = (
            system.A @ out[t]
            + system.b
            + system.B_R * R[t]
            - system.B_Q * Q[t]
            + system.B_Q * eps[t]
        )
    return out
