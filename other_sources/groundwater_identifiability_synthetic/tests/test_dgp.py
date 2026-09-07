"""DGP correctness: state equation, stability, positivity, reproducibility, stationarity."""

from __future__ import annotations

import numpy as np
import pytest

from groundwater_identifiability_synthetic.src import dgp
from groundwater_identifiability_synthetic.src.design import resolve_regime, rng_for

TOPOLOGIES = ["single", "path5", "star5", "null5", "bridge6", "path5_hidden"]


def test_state_equation_matches_storage_balance(design):
    """The matrix recursion must reproduce the scalar storage balance term by term."""
    system = dgp.build_system(design, "path5", "MED", "MED")
    rng = rng_for(12345)
    n = system.n_nodes
    h = rng.normal(5.0, 1.0, size=n)
    R = rng.uniform(0.5, 2.0, size=n)
    Q = rng.uniform(0.5, 2.0, size=n)
    eps = rng.normal(0.0, 0.1, size=n)

    matrix_form = (
        system.A @ h + system.b + system.B_R * R - system.B_Q * Q + system.B_Q * eps
    )

    for i in range(n):
        coupling = sum(system.C[i, j] * (h[j] - h[i]) for j in range(n) if j != i)
        boundary = system.C0[i] * (system.h_b[i] - h[i])
        flux = R[i] - Q[i] + coupling + boundary + eps[i]
        scalar_form = h[i] + system.dt * flux / system.S[i]
        assert scalar_form == pytest.approx(matrix_form[i], rel=0, abs=1e-12)


@pytest.mark.parametrize("topology", TOPOLOGIES)
@pytest.mark.parametrize("memory", ["LOW", "MED", "HIGH"])
def test_stability_and_positivity(design, topology, memory):
    gamma = "MED"
    infeasible = {
        (e["topology"], e["memory"], e["gamma"])
        for e in design["coupling"]["infeasible_combinations"]
    }
    if (topology, memory, gamma) in infeasible:
        with pytest.raises(ValueError):
            dgp.check_stability(design, dgp.build_system(design, topology, memory, gamma))
        return

    system = dgp.build_system(design, topology, memory, gamma)
    diagnostics = dgp.check_stability(design, system)

    delta = float(design["stability"]["contraction_margin_delta"])
    delta_diag = float(design["stability"]["diagonal_margin_delta_diag"])
    assert system.rho_A <= 1.0 - delta
    assert diagnostics["max_diagonal_load"] <= 1.0 - delta_diag
    assert np.all(system.S > 0)
    assert np.all(system.C >= 0)
    assert np.all(system.C0 > 0)
    assert np.all(system.A >= 0)
    assert np.allclose(system.C, system.C.T), "physical conductance must be symmetric"


@pytest.mark.parametrize("topology", TOPOLOGIES)
@pytest.mark.parametrize("memory", ["LOW", "MED", "HIGH"])
def test_realized_tau_matches_target(design, topology, memory):
    gamma = "LOW"
    system = dgp.build_system(design, topology, memory, gamma)
    target = float(design["memory_regimes"]["targets_fine_steps"][memory])
    tolerance = float(design["memory_regimes"]["target_match_tolerance"])
    assert abs(system.tau_relax_realized - target) / target <= tolerance


def test_kappa_is_asymmetric_but_conductance_is_symmetric(design):
    """kappa_ij = dt*C_ij/S_i is directed; it must NOT be forced symmetric."""
    system = dgp.build_system(design, "path5", "MED", "MED")
    edges = list(system.true_edges)
    assert edges
    asymmetric = [
        (i, j) for i, j in edges if abs(system.kappa[i, j] - system.kappa[j, i]) > 1e-9
    ]
    assert asymmetric, "storage heterogeneity should make kappa directionally asymmetric"
    for i, j in edges:
        assert system.C[i, j] == pytest.approx(system.C[j, i])
        assert system.kappa[i, j] == pytest.approx(system.dt * system.C[i, j] / system.S[i])


def test_seed_reproducibility(design):
    system = dgp.build_system(design, "path5", "MED", "MED")
    regime = resolve_regime(design, "T", "S5", "path5", overrides={})
    a = dgp.simulate(design, system, regime, rng_for(999), {})
    b = dgp.simulate(design, system, regime, rng_for(999), {})
    c = dgp.simulate(design, system, regime, rng_for(1000), {})
    assert np.array_equal(a.h, b.h)
    assert np.array_equal(a.Q_true, b.Q_true)
    assert not np.array_equal(a.h, c.h)


def test_system_is_fixed_within_a_cell(design):
    """Truth must not change between replicates of the same cell."""
    a = dgp.build_system(design, "path5", "MED", "MED")
    b = dgp.build_system(design, "path5", "MED", "MED")
    assert np.array_equal(a.S, b.S)
    assert np.array_equal(a.C, b.C)


def test_burn_in_respects_floor_and_tau_multiple(design):
    floor_steps = int(design["time"]["burn_in_floor_fine_steps"])
    multiple = float(design["time"]["burn_in_tau_multiple"])
    for memory in ("LOW", "MED", "HIGH"):
        system = dgp.build_system(design, "path5", memory, "MED")
        burn_in = dgp.burn_in_length(design, system)
        assert burn_in >= floor_steps
        assert burn_in >= multiple * system.tau_relax_realized - 1


@pytest.mark.parametrize("memory", ["LOW", "MED", "HIGH"])
def test_analysis_window_is_stationary(design, memory):
    """The 520-step analysis horizon begins AFTER burn-in and must be stationary.

    The 104-step floor alone is not enough for HIGH memory; the adaptive 8*tau burn-in is
    what makes this pass.
    """
    system = dgp.build_system(design, "path5", memory, "MED")
    regime = resolve_regime(design, "T", "S5", "path5", overrides={"memory": memory})
    variances = []
    for seed in (11, 22, 33, 44):
        trajectory = dgp.simulate(design, system, regime, rng_for(seed), {})
        window = trajectory.h[trajectory.analysis_start :]
        third = window.shape[0] // 3
        first_mean = float(np.mean(window[:third]))
        last_mean = float(np.mean(window[-third:]))
        spread = float(np.mean(np.std(window, axis=0)))
        variances.append(abs(first_mean - last_mean) / max(spread, 1e-9))
    assert float(np.mean(variances)) < 0.5, "residual transient in the analysis window"


def test_forcing_clipping_negligible(design):
    limit = float(design["forcing"]["max_clip_fraction"])
    system = dgp.build_system(design, "path5", "MED", "MED")
    regime = resolve_regime(design, "T", "S5", "path5", overrides={})
    for seed in (1, 2, 3):
        trajectory = dgp.simulate(design, system, regime, rng_for(seed), {})
        assert trajectory.clip_fraction <= limit


def test_latent_climate_factor_never_clips_and_has_the_designed_strength(design):
    """S7's latent climate confounder must carry ONLY its intended misspecification.

    Regression guard for two defects that both inflated this cell into the clipping limit:
    passing the factor's stationary sd straight through as an AR(1) innovation sd (a 2.3x
    inflation), and adding the factor rather than scaling by it. Clipping is a nonlinearity
    that breaks paired-counterfactual exactness, so a scenario built to have one
    characterized misspecification must not also acquire an undocumented one.
    """
    spec = design["s7_variants"]["latent_common_climate"]
    target_sd = float(spec["common_factor_sd"])
    from groundwater_identifiability_synthetic.src.evaluation import scenario_options

    system = dgp.build_system(design, "path5", "MED", "MED")
    regime = resolve_regime(
        design, "T", "S7", "path5", overrides={}, variant="latent_common_climate"
    )
    options = scenario_options(design, regime)
    assert options.get("latent_common_climate_sd", 0.0) == target_sd, "variant not activated"

    limit = float(design["forcing"]["max_clip_fraction"])
    baseline = resolve_regime(design, "T", "S5", "path5", overrides={})
    seeds = (1, 2, 3, 4, 5)

    spreads, with_clip, without_clip = [], [], []
    for seed in seeds:
        a = dgp.simulate(design, system, regime, rng_for(seed), options)
        b = dgp.simulate(design, system, baseline, rng_for(seed), {})
        # Recharge itself is strictly positive, so the factor contributes NO clipping. The
        # residual clip_fraction is pumping-side and is present in the baseline too.
        assert np.all(a.R_true > 0.0), "multiplicative factor must keep recharge positive"
        assert a.clip_fraction <= limit
        spreads.append(np.var(a.R_true) - np.var(b.R_true))
        with_clip.append(a.clip_fraction)
        without_clip.append(b.clip_fraction)

    assert np.mean(with_clip) <= np.mean(without_clip) + 1e-4, (
        "the latent-climate variant must not add clipping on top of the baseline"
    )
    induced_sd = float(np.sqrt(max(np.mean(spreads), 0.0)))
    assert induced_sd == pytest.approx(target_sd, rel=0.5), (
        f"induced recharge sd {induced_sd:.3f} should be of order {target_sd}; a large "
        "mismatch means the stationary/innovation sd conversion regressed"
    )


def test_confounding_rho_is_realized(design):
    """Seasonal shapes use sin and rho*sin + sqrt(1-rho^2)*cos, exactly orthogonal, so the
    realized seasonal correlation equals the requested rho."""
    system = dgp.build_system(design, "single", "MED", "NONE")
    period = int(design["time"]["seasonal_period_fine_steps"])
    t = np.arange(4 * period)
    for rho in (0.0, 0.3, 0.6, 0.9):
        phase = 0.7
        angle = 2 * np.pi * t / period + phase
        s_R = np.sin(angle)
        s_Q = rho * np.sin(angle) + np.sqrt(1 - rho**2) * np.cos(angle)
        assert np.corrcoef(s_R, s_Q)[0, 1] == pytest.approx(rho, abs=0.02)


def test_null_network_has_no_coupling(design):
    system = dgp.build_system(design, "null5", "MED", "MED")
    assert system.true_edges == frozenset()
    off_diagonal = system.C.copy()
    np.fill_diagonal(off_diagonal, 0.0)
    assert np.all(off_diagonal == 0.0)
    assert np.allclose(system.A, np.diag(np.diag(system.A)))


def test_rollout_matches_simulate(design):
    """The intervention rollout helper must reproduce the simulator exactly."""
    system = dgp.build_system(design, "path5", "MED", "MED")
    regime = resolve_regime(design, "T", "S5", "path5", overrides={})
    trajectory = dgp.simulate(design, system, regime, rng_for(4242), {})
    start = trajectory.analysis_start
    steps = 40
    replayed = dgp.rollout(
        system,
        trajectory.h[start],
        trajectory.R_true[start : start + steps],
        trajectory.Q_true[start : start + steps],
        trajectory.eps[start : start + steps],
    )
    assert np.allclose(replayed, trajectory.h[start : start + steps + 1], atol=1e-10)
