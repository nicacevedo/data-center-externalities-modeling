"""Observation model: everything the estimator is allowed to see.

`ObservationBundle` is the ONLY object estimation code may receive. It deliberately carries
no storage, no conductance, no true edge set, and no latent recharge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

TRAIN, VALIDATION, TEST = "TRAIN", "VALIDATION", "TEST"


@dataclass(frozen=True)
class ObservationBundle:
    """Observable data. Contains NO truth parameters and NO true edges."""

    node_ids: np.ndarray             # (n,)
    coordinates: np.ndarray          # (n, 2)  geometry is observable
    y: np.ndarray                    # (M, n)  heads at cadence instants, NaN where missing
    Q_obs: np.ndarray                # (M-1, n) interval-aggregated observed pumping
    R_proxy: np.ndarray              # (M-1, n) interval-aggregated recharge proxy
    P_placebo: np.ndarray | None     # (M-1, n) placebo pumping-like channel (S8); None otherwise
    t_fine: np.ndarray               # (M,) fine index of each observation instant
    season_sin: np.ndarray           # (M-1,)
    season_cos: np.ndarray           # (M-1,)
    time_trend: np.ndarray           # (M-1,)
    split: np.ndarray                # (M-1,) TRAIN / VALIDATION / TEST
    cadence: int
    candidate_neighbors: dict[int, list[int]]
    candidate_pairs: frozenset       # undirected (i, j), i < j
    observed_nodes: np.ndarray       # (n,) bool
    absolute_pumping_scale_known: bool
    distances: np.ndarray            # (n, n)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def n_nodes(self) -> int:
        return int(self.y.shape[1])

    @property
    def n_transitions(self) -> int:
        return int(self.Q_obs.shape[0])

    def test_onset(self) -> int:
        idx = np.flatnonzero(self.split == TEST)
        if idx.size == 0:
            raise ValueError("no protected test transitions")
        return int(idx[0])


# -------------------------------------------------------------------------------------
# Geometry-only candidate graph
# -------------------------------------------------------------------------------------


def candidate_graph(
    design: dict[str, Any],
    coordinates: np.ndarray,
    observed_nodes: np.ndarray | None = None,
) -> tuple[dict[int, list[int]], frozenset, np.ndarray]:
    """Candidate neighbours from coordinates and a frozen radius rule ONLY.

    This function never sees the true edge set. `test_candidate_graph_independent_of_truth`
    builds two systems with identical geometry and different true edges and asserts the
    output is identical.
    """
    n = coordinates.shape[0]
    diff = coordinates[:, None, :] - coordinates[None, :, :]
    distances = np.sqrt(np.sum(diff * diff, axis=-1))

    radius = float(design["geometry"]["candidate_radius"])
    knn_k = int(design["geometry"]["candidate_knn_fallback_k"])

    if observed_nodes is None:
        observed_nodes = np.ones(n, dtype=bool)

    neighbors: dict[int, list[int]] = {}
    for i in range(n):
        within = [
            j
            for j in range(n)
            if j != i and distances[i, j] <= radius and observed_nodes[j]
        ]
        if not within:
            # Frozen fallback, also geometry-only.
            order = [j for j in np.argsort(distances[i]) if j != i and observed_nodes[j]]
            within = [int(j) for j in order[:knn_k]]
        neighbors[i] = sorted(int(j) for j in within)

    pairs = set()
    for i, js in neighbors.items():
        for j in js:
            pairs.add((min(i, j), max(i, j)))
    return neighbors, frozenset(pairs), distances


# -------------------------------------------------------------------------------------
# Aggregation and degradation
# -------------------------------------------------------------------------------------


def _interval_sums(series: np.ndarray, starts: np.ndarray, k: int) -> np.ndarray:
    """Sum a fine-step series over each cadence interval [t, t+k)."""
    return np.stack([series[s : s + k].sum(axis=0) for s in starts], axis=0)


def _degrade_pumping(
    design: dict[str, Any],
    regime,
    q_interval: np.ndarray,
    q_fine: np.ndarray,
    starts: np.ndarray,
    k: int,
    period: float,
    phases: np.ndarray,
    rng: np.random.Generator,
    streams=None,
) -> tuple[np.ndarray, bool, np.ndarray | None]:
    """Apply the frozen pumping-quality regime. Returns (observed, absolute_scale_known, z)."""
    regimes = design["observation"]["pumping_quality_regimes"]
    kind = regime.pumping_quality
    z_named = None
    if streams is not None:
        z_named = streams["pumping_degradation_z"].normal(0.0, 1.0, size=q_interval.shape)
        streams["pumping_scalebias"].normal(0.0, 0.30)
        n = q_interval.shape[1]
        streams["pumping_dirichlet"].dirichlet(np.ones(max(n, 2)))

    if kind == "P-EXACT":
        return q_interval.copy(), True, z_named

    if kind == "P-MULTNOISE":
        s = float(regime.pumping_noise_s)
        z = z_named if z_named is not None else rng.normal(0.0, 1.0, size=q_interval.shape)
        factor = np.exp(s * z - 0.5 * s * s)
        return q_interval * factor, True, z

    if kind == "P-SCALEBIAS":
        if streams is not None:
            # scalebias already consumed above; draw an independent factor from a copy is
            # illegal. Use a dedicated residual: named P-SCALEBIAS is unused in V3 cells.
            c = float(np.exp(float(z_named.ravel()[0]) * 0.30))
        else:
            c = float(np.exp(rng.normal(0.0, 0.30)))
        return q_interval * c, False, z_named

    if kind == "P-TEMPAGG":
        # Annual totals redistributed by a FIXED mean seasonal template: within-year
        # variation is destroyed, annual mass is preserved.
        qspec = design["forcing"]["pumping"]
        t = np.arange(q_fine.shape[0], dtype=float)[:, None]
        template = np.maximum(
            float(qspec["mean"])
            * (1.0 + float(qspec["seasonal_amplitude"]) * np.sin(2.0 * np.pi * t / period + phases[None, :])),
            1e-9,
        )
        year = 52
        rebuilt = np.zeros_like(q_fine)
        for start in range(0, q_fine.shape[0], year):
            stop = min(start + year, q_fine.shape[0])
            actual_total = q_fine[start:stop].sum(axis=0)
            tmpl = template[start:stop]
            tmpl_total = tmpl.sum(axis=0)
            rebuilt[start:stop] = tmpl * (actual_total / np.maximum(tmpl_total, 1e-12))[None, :]
        return _interval_sums(rebuilt, starts, k), True, z_named

    if kind == "P-SPATIALAGG":
        concentration = float(regimes["P-SPATIALAGG"]["dirichlet_concentration"])
        mean_shares = q_interval.mean(axis=0)
        total_mean = mean_shares.sum()
        if total_mean <= 0 or q_interval.shape[1] == 1:
            return q_interval.copy(), False, z_named
        mean_shares = mean_shares / total_mean
        if streams is None:
            shares = rng.dirichlet(np.maximum(concentration * mean_shares, 1e-6))
        else:
            shares = mean_shares  # Dirichlet already consumed on the named stream above
        basin_total = q_interval.sum(axis=1, keepdims=True)
        return basin_total * shares[None, :], False, z_named

    raise ValueError(f"unknown pumping-quality regime {kind}")


def _degrade_recharge(
    regime,
    r_fine: np.ndarray,
    starts: np.ndarray,
    k: int,
    rng: np.random.Generator,
    streams=None,
) -> np.ndarray:
    """Apply the frozen recharge-quality regime. The latent truth is never exposed."""
    kind = regime.recharge_quality
    series = r_fine

    lag = int(regime.recharge_lag)
    if lag > 0:
        series = np.vstack([np.repeat(series[:1], lag, axis=0), series[:-lag]])

    proxy = _interval_sums(series, starts, k)

    sigma = float(regime.recharge_sigma)
    z_named = None
    scale_named = None
    if streams is not None:
        z_named = streams["recharge_degradation_z"].normal(0.0, 1.0, size=proxy.shape)
        scale_named = float(np.exp(streams["recharge_scalebias"].normal(0.0, 0.30)))
    if sigma > 0.0:
        scale = np.maximum(proxy.std(axis=0), 1e-12)
        noise = z_named if z_named is not None else rng.normal(0.0, 1.0, size=proxy.shape)
        proxy = proxy + noise * (sigma * scale)[None, :]

    if kind == "R-SCALE":
        c = scale_named if scale_named is not None else float(np.exp(rng.normal(0.0, 0.30)))
        proxy = proxy * c

    return proxy


# -------------------------------------------------------------------------------------
# Missingness
# -------------------------------------------------------------------------------------


def _apply_missingness(
    design: dict[str, Any],
    regime,
    y: np.ndarray,
    rng: np.random.Generator,
    streams=None,
) -> tuple[np.ndarray, np.ndarray]:
    n_instants, n = y.shape
    observed_nodes = np.ones(n, dtype=bool)

    frac = float(regime.observed_node_fraction)
    if frac < 1.0 and n > 1:
        n_observed = max(1, int(np.floor(frac * n)))
        chooser = streams["node_subsample"] if streams is not None else rng
        keep = chooser.choice(n, size=n_observed, replace=False)
        observed_nodes = np.zeros(n, dtype=bool)
        observed_nodes[keep] = True
    elif streams is not None and n > 1:
        # consume a dummy choice of full set size so the stream position is defined
        streams["node_subsample"].choice(n, size=n, replace=False)

    out = y.copy()
    out[:, ~observed_nodes] = np.nan

    mcar = float(regime.mcar_fraction)
    uniforms = None
    if streams is not None:
        uniforms = streams["mcar_uniforms"].random(out.shape)
    if mcar > 0.0 or uniforms is not None:
        if uniforms is None:
            drop = rng.random(out.shape) < mcar
        else:
            drop = uniforms < mcar
        drop[:, ~observed_nodes] = False
        out[drop] = np.nan

    blocks = int(regime.blocks_per_node)
    length = int(design["observation"]["missingness"]["block_outage"]["block_length_cadence_steps"])
    max_blocks = 2
    if streams is not None:
        n_starts = n * max_blocks
        starts_draw = streams["block_outage_starts"].integers(
            0, max(n_instants - length, 1), size=n_starts
        )
        idx = 0
        if blocks > 0:
            for node in np.flatnonzero(observed_nodes):
                for _ in range(blocks):
                    start = int(starts_draw[idx]); idx += 1
                    if n_instants <= length:
                        out[:, node] = np.nan
                    else:
                        out[start : start + length, node] = np.nan
    elif blocks > 0:
        for node in np.flatnonzero(observed_nodes):
            for _ in range(blocks):
                if n_instants <= length:
                    out[:, node] = np.nan
                    continue
                start = int(rng.integers(0, n_instants - length))
                out[start : start + length, node] = np.nan

    return out, observed_nodes


# -------------------------------------------------------------------------------------
# Splits
# -------------------------------------------------------------------------------------


def chronological_split(design: dict[str, Any], n_transitions: int) -> np.ndarray:
    train_f = float(design["splits"]["train_fraction"])
    val_f = float(design["splits"]["validation_fraction"])
    train_cut = int(np.floor(train_f * n_transitions))
    val_cut = int(np.floor((train_f + val_f) * n_transitions))
    labels = np.full(n_transitions, TEST, dtype=object)
    labels[:train_cut] = TRAIN
    labels[train_cut:val_cut] = VALIDATION
    return labels


# -------------------------------------------------------------------------------------
# Assembly
# -------------------------------------------------------------------------------------


def make_observations(
    design: dict[str, Any],
    system,
    trajectory,
    regime,
    rng: np.random.Generator,
    use_placebo_as_pumping: bool = False,
    streams=None,
) -> ObservationBundle:
    """Build the observation bundle. This is the ONLY boundary truth may cross.

    Real pumping always occupies Q_obs. If a placebo series exists on the trajectory it is
    attached as P_placebo (S8). Replacing Q with the placebo is a v1 behaviour that v2
    refuses.
    """
    if use_placebo_as_pumping:
        raise ValueError("v2 S8 must not replace real pumping with the placebo")
    k = int(regime.cadence)
    period = float(design["time"]["seasonal_period_fine_steps"])
    start = trajectory.analysis_start
    horizon = trajectory.analysis_length

    # Observation instants at fine offsets 0, k, 2k, ... <= horizon - 1.
    offsets = np.arange(0, horizon, k)
    n_transitions = len(offsets) - 1
    if n_transitions < 8:
        raise ValueError(f"cadence {k} leaves only {n_transitions} transitions")

    h_window = trajectory.h[start : start + horizon]
    y_clean = h_window[offsets]

    # Observation noise from the BURN-IN head sd, never the analysed window.
    snr = float(regime.snr_head)
    if streams is not None:
        z_nu = streams["head_measurement_noise"].normal(0.0, 1.0, size=y_clean.shape)
        if np.isfinite(snr) and snr > 0:
            nu_sd = trajectory.burn_in_head_sd / snr
            y_noisy = y_clean + z_nu * nu_sd
        else:
            nu_sd = 0.0
            y_noisy = y_clean.copy()
    elif np.isfinite(snr) and snr > 0:
        nu_sd = trajectory.burn_in_head_sd / snr
        y_noisy = y_clean + rng.normal(0.0, nu_sd, size=y_clean.shape)
    else:
        nu_sd = 0.0
        y_noisy = y_clean.copy()

    y_obs, observed_nodes = _apply_missingness(design, regime, y_noisy, rng, streams=streams)

    # Forcing is interval-aggregated over [t_tau, t_tau + k).
    starts = offsets[:-1]
    q_fine = trajectory.Q_true[start : start + horizon]
    r_fine = trajectory.R_true[start : start + horizon]
    q_interval = _interval_sums(q_fine, starts, k)

    from .dgp import _seasonal_phases  # geometry-independent frozen phases

    phases = _seasonal_phases(design, system.n_nodes, system.topology)
    q_obs, absolute_known, z_pump = _degrade_pumping(
        design, regime, q_interval, q_fine, starts, k, period, phases, rng, streams=streams
    )
    r_proxy = _degrade_recharge(regime, r_fine, starts, k, rng, streams=streams)

    p_placebo = None
    if trajectory.Q_placebo is not None:
        p_fine = trajectory.Q_placebo[start : start + horizon]
        p_placebo = _interval_sums(p_fine, starts, k)

    t_fine = offsets.astype(float)
    angle = 2.0 * np.pi * t_fine[:-1] / period
    split = chronological_split(design, n_transitions)

    neighbors, pairs, distances = candidate_graph(design, system.coordinates, observed_nodes)

    return ObservationBundle(
        node_ids=np.arange(system.n_nodes),
        coordinates=system.coordinates.copy(),
        y=y_obs,
        Q_obs=q_obs,
        R_proxy=r_proxy,
        P_placebo=p_placebo,
        t_fine=t_fine,
        season_sin=np.sin(angle),
        season_cos=np.cos(angle),
        time_trend=t_fine[:-1] / period,
        split=split,
        cadence=k,
        candidate_neighbors=neighbors,
        candidate_pairs=pairs,
        observed_nodes=observed_nodes,
        absolute_pumping_scale_known=absolute_known,
        distances=distances,
        meta={
            "nu_sd": float(nu_sd),
            "analysis_start_fine": int(start),
            "offsets_fine": offsets,
            "pumping_quality": regime.pumping_quality,
            "recharge_quality": regime.recharge_quality,
            "has_placebo": p_placebo is not None,
            "pumping_degradation_z": z_pump,
        },
    )


def mask_node_for_test(
    bundle: ObservationBundle,
    node: int,
    onset_transition: int,
    horizon: int,
    sentinel: float = np.nan,
) -> ObservationBundle:
    """Withhold a node's head observations over a contiguous post-onset horizon.

    `sentinel` exists so the leak test can poison the withheld entries with a large finite
    value and assert the recursive forecast is unchanged.
    """
    y = bundle.y.copy()
    first = onset_transition
    last = min(onset_transition + horizon + 1, y.shape[0])
    y[first:last, node] = sentinel
    return ObservationBundle(
        node_ids=bundle.node_ids,
        coordinates=bundle.coordinates,
        y=y,
        Q_obs=bundle.Q_obs,
        R_proxy=bundle.R_proxy,
        P_placebo=bundle.P_placebo,
        t_fine=bundle.t_fine,
        season_sin=bundle.season_sin,
        season_cos=bundle.season_cos,
        time_trend=bundle.time_trend,
        split=bundle.split,
        cadence=bundle.cadence,
        candidate_neighbors=bundle.candidate_neighbors,
        candidate_pairs=bundle.candidate_pairs,
        observed_nodes=bundle.observed_nodes,
        absolute_pumping_scale_known=bundle.absolute_pumping_scale_known,
        distances=bundle.distances,
        meta={**bundle.meta, "masked_node": node, "mask_onset": first, "mask_last": last},
    )
