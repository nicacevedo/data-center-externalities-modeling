"""Counterfactual intervention evaluator and masked-node protocol.

PAIRING is mandatory. The true baseline and true intervention trajectories share the same
initial state, the same recharge/background forcing and the same process-noise realization,
so common disturbances cancel exactly and the estimand is the paired difference

    delta_h = h_intervention - h_baseline.

Because both the DGP and the estimators are linear, that paired difference is the
deterministic structural response: it does not depend on the noise realization at all, which
`test_paired_intervention_noise_cancels` asserts.

Model side, for every rung:

    delta_yhat_{tau+1} = A_hat delta_yhat_tau + beta_Q_hat * delta_Q_tau  ( + spatial term )

with delta_yhat_0 = 0. Intercepts, harmonics and recharge cancel in the paired difference.
B0 has no pumping coefficient, so its predicted intervention response is identically zero,
which is the correct statement that a background model cannot represent an intervention.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .dgp import SystemTruth, Trajectory, rollout
from .fit import LadderFit, implied_transition_matrix
from .models import build_design
from .observations import ObservationBundle

INTERVENTION_TYPES = ("pulse", "persistent_step", "new_node_pumping", "multi_node_withdrawal")


@dataclass(frozen=True)
class InterventionSpec:
    name: str
    nodes: tuple[int, ...]
    magnitude: float
    duration_fine: int
    horizon_fine: int


def build_intervention_specs(
    design: dict,
    system: SystemTruth,
    trajectory: Trajectory,
    horizon_fine: int,
) -> list[InterventionSpec]:
    cfg = design["interventions"]
    magnitude = float(cfg["magnitude_fraction_of_mean_pumping"]) * float(
        design["forcing"]["pumping"]["mean"]
    )
    n = system.n_nodes
    specs: list[InterventionSpec] = []

    # Pulse duration equals one cadence interval; filled in by the caller via duration_fine.
    specs.append(InterventionSpec("pulse", (0,), magnitude, -1, horizon_fine))
    specs.append(
        InterventionSpec(
            "persistent_step",
            (0,),
            magnitude,
            int(cfg["types"]["persistent_step"]["duration_fine_steps"]),
            horizon_fine,
        )
    )

    if n > 1:
        mean_pumping = trajectory.Q_true.mean(axis=0)
        low_node = int(np.argmin(mean_pumping))
        specs.append(
            InterventionSpec(
                "new_node_pumping",
                (low_node,),
                magnitude,
                int(cfg["types"]["new_node_pumping"]["duration_fine_steps"]),
                horizon_fine,
            )
        )
        n_multi = int(cfg["types"]["multi_node_withdrawal"]["n_nodes"])
        specs.append(
            InterventionSpec(
                "multi_node_withdrawal",
                tuple(range(min(n_multi, n))),
                magnitude,
                int(cfg["types"]["multi_node_withdrawal"]["duration_fine_steps"]),
                horizon_fine,
            )
        )
    return specs


def _delta_q_fine(spec: InterventionSpec, n_nodes: int, cadence: int) -> np.ndarray:
    duration = cadence if spec.duration_fine < 0 else spec.duration_fine
    out = np.zeros((spec.horizon_fine, n_nodes))
    stop = min(duration, spec.horizon_fine)
    for node in spec.nodes:
        out[:stop, node] = spec.magnitude
    return out


def true_paired_response(
    system: SystemTruth,
    trajectory: Trajectory,
    onset_fine: int,
    spec: InterventionSpec,
    cadence: int,
    force_noise_free: bool = False,
) -> np.ndarray:
    """delta_h over the horizon, at FINE resolution, from the paired truth rollouts."""
    steps = spec.horizon_fine
    R = trajectory.R_true[onset_fine : onset_fine + steps]
    Q = trajectory.Q_true[onset_fine : onset_fine + steps]
    eps = trajectory.eps[onset_fine : onset_fine + steps]
    if force_noise_free:
        eps = np.zeros_like(eps)
    h0 = trajectory.h[onset_fine]

    delta_q = _delta_q_fine(spec, system.n_nodes, cadence)
    baseline = rollout(system, h0, R, Q, eps)
    intervention = rollout(system, h0, R, Q + delta_q, eps)
    return intervention - baseline


def model_paired_response(
    bundle: ObservationBundle,
    ladder: LadderFit,
    model: str,
    spec: InterventionSpec,
    n_cadence_steps: int,
    channel: str = "pumping",
) -> np.ndarray:
    """delta_yhat at cadence resolution for a fitted rung.

    The paired difference removes the intercept, calendar terms and recharge, leaving the
    transition matrix and the pumping channel. The additional withdrawal is entered in
    ABSOLUTE units, exactly as a planner would specify it, so a regime with an unknown
    pumping scale produces a correspondingly wrong ABSOLUTE response. That is the intended
    behaviour, not a defect.
    """
    n = bundle.n_nodes
    A_hat = implied_transition_matrix(ladder, model, n)
    A_hat = np.where(np.isfinite(A_hat), A_hat, 0.0)

    beta_q = np.zeros(n)
    beta_qn = np.zeros(n)
    bandwidth = ladder.selection.get("S", {}).get("bandwidth")
    for node, fit in ladder.fits.get(model, {}).items():
        if fit is None:
            continue
        beta_q[node] = fit.coef_of(channel, 0.0)
        beta_qn[node] = fit.coef_of("neighbour_pumping", 0.0) if channel == "pumping" else 0.0

    cadence = bundle.cadence
    delta_q_fine = _delta_q_fine(spec, n, cadence)
    # Aggregate the increment over cadence intervals, matching how forcing was observed.
    delta_q_interval = np.stack(
        [
            delta_q_fine[t * cadence : (t + 1) * cadence].sum(axis=0)
            for t in range(n_cadence_steps)
        ],
        axis=0,
    )

    weights = None
    if model == "S" and bandwidth is not None:
        weights = np.exp(-bundle.distances / float(bandwidth))
        np.fill_diagonal(weights, 0.0)
        weights[:, ~bundle.observed_nodes] = 0.0

    out = np.zeros((n_cadence_steps + 1, n))
    for t in range(n_cadence_steps):
        drive = beta_q * delta_q_interval[t]
        if weights is not None:
            drive = drive + beta_qn * (weights @ delta_q_interval[t])
        out[t + 1] = A_hat @ out[t] + drive
    return out


def sample_true_at_cadence(delta_h_fine: np.ndarray, cadence: int, n_steps: int) -> np.ndarray:
    idx = np.arange(0, n_steps + 1) * cadence
    idx = idx[idx < delta_h_fine.shape[0]]
    return delta_h_fine[idx]


# -------------------------------------------------------------------------------------
# Masked-node protocol: propagation through monitoring loss, NOT zero-shot prediction
# -------------------------------------------------------------------------------------


def _last_observed_at_or_before(y: np.ndarray, tau: int, node: int) -> float:
    """Most recent observed head of `node` at or before instant `tau`.

    Applied ONLY to non-masked neighbour stations. Using a neighbour's own most recent
    observation is an operational nowcast of a station that is still being monitored; it is
    not interpolation of the masked node's withheld series, and the masked node is never
    carried forward this way. Without it the recursion aborts on the first missing neighbour
    and the masked-node criterion is unevaluable at any realistic missingness.
    """
    for t in range(tau, -1, -1):
        value = y[t, node]
        if np.isfinite(value):
            return float(value)
    return float("nan")


def frozen_masked_node_index(design: dict, topology: str) -> int:
    """Topology table lookup. Independent of realized missingness."""
    table = design["spatial_evaluation"]["masked_node_protocol"]["masked_node_selection"]["by_topology"]
    if topology not in table:
        raise KeyError(f"no frozen masked-node index for topology {topology}")
    return int(table[topology])


def _one_forecast_step(
    bundle: ObservationBundle,
    fit,
    model: str,
    node: int,
    tau: int,
    state: float,
    bandwidth: float | None,
) -> tuple[float | None, int]:
    """Advance one cadence step. Returns (next_state, neighbour_carry_forwards) or (None, _)."""
    values: list[float] = [state, bundle.season_sin[tau], bundle.season_cos[tau], bundle.time_trend[tau]]
    if model in ("L", "S", "N"):
        values.append(bundle.Q_obs[tau, node])
        values.append(bundle.R_proxy[tau, node])
        if bundle.P_placebo is not None:
            values.append(bundle.P_placebo[tau, node])
    if model == "S" and bandwidth is not None:
        weights = np.exp(-bundle.distances[node] / float(bandwidth))
        weights[node] = 0.0
        weights[~bundle.observed_nodes] = 0.0
        values.append(float(bundle.Q_obs[tau] @ weights))
        values.append(float(bundle.R_proxy[tau] @ weights))
    carry = 0
    if model == "N":
        for j in fit.kappa_neighbors:
            neighbour = bundle.y[tau, j]
            if not np.isfinite(neighbour):
                neighbour = _last_observed_at_or_before(bundle.y, tau, j)
                carry += 1
            if not np.isfinite(neighbour):
                return None, carry
            values.append(float(neighbour) - state)
    row = np.asarray(values, dtype=float)
    if row.shape[0] != fit.coef.shape[0] or not np.all(np.isfinite(row)):
        return None, carry
    return float(fit.intercept + row @ fit.coef), carry


def masked_node_forecast(
    bundle: ObservationBundle,
    ladder: LadderFit,
    model: str,
    node: int,
    onset_transition: int,
    horizon: int,
) -> tuple[np.ndarray, dict[str, int | str]]:
    """Recursive forecast aligned to TEST onset.

    Protocol, frozen in design_v2:
      - start from the last admissible PRE-MASK head (instant t_anchor < onset);
      - if t_anchor < onset - 1, warm-forward internally to onset (NOT scored);
      - score only heads at instants onset, ..., onset+horizon-1;
      - no withheld TEST head of the masked node may enter.

    Returns (predictions of length `horizon`, diagnostics).
    """
    empty = np.full(horizon, np.nan)
    info: dict[str, int | str] = {
        "warm_forward_steps": 0,
        "carry_forward_steps": 0,
        "anchor_instant": -1,
        "status": "NOT_ESTIMABLE",
    }
    fit = ladder.fits.get(model, {}).get(node)
    if fit is None:
        info["status"] = "NOT_ESTIMABLE"
        return empty, info

    start = -1
    for tau in range(onset_transition - 1, -1, -1):
        if np.isfinite(bundle.y[tau, node]):
            start = tau
            break
    if start < 0:
        info["status"] = "NO_START_OBSERVATION"
        return empty, info
    info["anchor_instant"] = start
    state = float(bundle.y[start, node])
    bandwidth = ladder.selection.get("S", {}).get("bandwidth")
    carry_forward = 0

    # Warm-forward from start to onset-1. Predictions in this loop are NOT scored.
    for tau in range(start, onset_transition - 1):
        if tau >= bundle.n_transitions:
            info["status"] = "RECURSION_STOPPED_EARLY"
            info["carry_forward_steps"] = carry_forward
            info["warm_forward_steps"] = tau - start
            return empty, info
        nxt, carry = _one_forecast_step(bundle, fit, model, node, tau, state, bandwidth)
        carry_forward += carry
        if nxt is None:
            info["status"] = "RECURSION_STOPPED_EARLY"
            info["carry_forward_steps"] = carry_forward
            info["warm_forward_steps"] = tau - start
            return empty, info
        state = nxt
    info["warm_forward_steps"] = max(0, (onset_transition - 1) - start)

    predictions = np.full(horizon, np.nan)
    for step in range(horizon):
        tau = onset_transition - 1 + step
        if tau >= bundle.n_transitions:
            break
        nxt, carry = _one_forecast_step(bundle, fit, model, node, tau, state, bandwidth)
        carry_forward += carry
        if nxt is None:
            break
        state = nxt
        predictions[step] = state

    info["carry_forward_steps"] = carry_forward
    completed = int(np.sum(np.isfinite(predictions)))
    info["status"] = "OK" if completed else "RECURSION_STOPPED_EARLY"
    return predictions, info


def observed_node_chained_forecast(
    bundle: ObservationBundle,
    ladder: LadderFit,
    model: str,
    node: int,
    onset_transition: int,
    horizon: int,
) -> np.ndarray:
    """Monitoring-intact counterpart: identical horizon, but re-initialized each step from
    the node's own observed head. The ratio of the two errors is what the masked-node gate
    criterion uses."""
    fit = ladder.fits.get(model, {}).get(node)
    if fit is None:
        return np.full(horizon, np.nan)
    design = ladder.designs[model][node]
    lookup = {int(r): idx for idx, r in enumerate(design.rows)}

    predictions = np.full(horizon, np.nan)
    for step in range(horizon):
        tau = onset_transition - 1 + step
        if tau in lookup:
            predictions[step] = float(fit.predict(design.X[lookup[tau] : lookup[tau] + 1])[0])
    return predictions
