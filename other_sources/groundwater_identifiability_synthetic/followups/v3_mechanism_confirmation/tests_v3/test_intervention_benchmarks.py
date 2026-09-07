"""Layer-1 intervention benchmarks: global validity, all-node vs pumped, neighbour floor.

Includes the analytically controlled COUPLED fixture that exercises the exact structural
phenomenon Block B is meant to diagnose: an own-pumping-only local family cannot propagate a
withdrawal to a hydraulically affected non-pumped unit, so the all-node benchmark carries a
strictly positive irreducible component.
"""

from __future__ import annotations

import numpy as np
import pytest

from src_v3 import dgp
from src_v3.benchmarks import build_pumped_profile, f_intervention_for_system
from src_v3.design import load_design, resolve_v3_cell, rng_for, seed_list
from src_v3.diagnostics import (
    inclusion_mask,
    l_family_paired_response,
    neighbor_unmodeled_floor,
    persistent_nire,
)
from src_v3.evaluation import scenario_options
from src_v3.metrics import normalized_error
from src_v3.observations import make_observations
from src_v3.rng import StreamBank

CELLS_UNDER_TEST = ("A_PEXACT", "A1_PEXACT_K1", "B_GNONE", "B_GLOW", "B_GHIGH", "C_REAL_GHIGH")


def _realize(design, cell_id, seed):
    regime = resolve_v3_cell(design, cell_id)
    options = scenario_options(design, regime)
    system = dgp.build_system(
        design,
        regime.topology,
        regime.memory,
        regime.gamma,
        recharge_efficiency=float(options.get("recharge_efficiency", 1.0)),
        system_seed_mode="orthogonal_v3",
    )
    streams = StreamBank(int(seed))
    traj = dgp.simulate(design, system, regime, rng_for(int(seed)), options, streams=streams)
    bundle = make_observations(
        design, system, traj, regime, rng_for(int(seed)), streams=streams
    )
    return regime, system, traj, bundle


# -------------------------------------------------------------------------------------
# Profile algebra
# -------------------------------------------------------------------------------------


def test_pumped_profile_reproduces_the_frozen_recursion():
    """kappa * g_t(a) from the polynomial profile equals the frozen L recursion exactly."""
    rng = np.random.default_rng(7)
    n_steps = 9
    dQ = np.zeros((n_steps, 3))
    dQ[:6, 0] = 4.0
    dQ[6, 0] = 2.0
    y = np.zeros((n_steps + 1, 3))
    y[:, 0] = np.linspace(0.0, -1.0, n_steps + 1)
    profile = build_pumped_profile(y, dQ, n_steps, pumped=0)
    for a in rng.uniform(-3.0, 3.0, size=25):
        kappa = float(rng.normal())
        a_diag = np.zeros(3)
        a_diag[0] = a
        beta = np.zeros(3)
        beta[0] = kappa
        expected = l_family_paired_response(a_diag, beta, dQ)[:, 0]
        g = np.zeros(profile.n_scored)
        for t in range(profile.n_scored - 1):
            g[t + 1] = a * g[t] + profile.d[t]
        # |a|>1 on a random draw grows the recursion to O(1e4); relative 1e-12 is
        # still an algebraic-identity check (the failure above was 2e-16 relative).
        np.testing.assert_allclose(
            kappa * g, expected[: profile.n_scored], rtol=1e-12, atol=1e-12
        )


def test_profile_denominator_has_no_real_pole():
    """Q(a) >= d_0^2 > 0 for every real a, which is what makes the global argument work."""
    from numpy.polynomial import polynomial as P

    dQ = np.zeros((8, 2))
    dQ[:, 0] = 3.0
    y = np.zeros((9, 2))
    y[:, 0] = -np.arange(9, dtype=float)
    profile = build_pumped_profile(y, dQ, 8, pumped=0)
    grid = np.concatenate([np.linspace(-50.0, 50.0, 20001), [0.0]])
    values = np.array([float(P.polyval(a, profile.q)) for a in grid])
    assert np.all(values >= profile.d[0] ** 2 - 1e-9)
    assert np.all(np.isfinite(values))


def test_ratio_limit_at_infinity_is_the_analytic_leading_coefficient_ratio():
    dQ = np.zeros((6, 1))
    dQ[:, 0] = 2.0
    y = np.zeros((7, 1))
    y[:, 0] = np.array([0.0, -1.0, -1.5, -1.8, -1.9, -1.95, -2.0])
    profile = build_pumped_profile(y, dQ, 6, pumped=0)
    y_hat_last = y[6, 0] / np.linalg.norm(y[:, 0])
    assert profile.ratio_at_infinity() == pytest.approx(y_hat_last**2, rel=0, abs=1e-14)
    # Numerically approach the limit from both sides.
    for a in (1e6, 1e8, -1e6, -1e8):
        assert profile.ratio(a) == pytest.approx(profile.ratio_at_infinity(), abs=1e-4)


# -------------------------------------------------------------------------------------
# Global-domain verification
# -------------------------------------------------------------------------------------


@pytest.mark.parametrize("cell_id", CELLS_UNDER_TEST)
def test_f_intervention_global_certification_and_domain(design, cell_id):
    seed = seed_list(design, "V3_BENCHMARK")[0]
    _regime, system, traj, bundle = _realize(design, cell_id, seed)
    out = f_intervention_for_system(design, system, traj, bundle)
    assert out["F_intervention_global_certified"] is True
    assert out["F_intervention_domain"] == "extended_real_line_a_in_R_union_pm_inf__kappa_in_R"
    assert out["F_intervention_attained_at_infinity"] is False
    assert out["F_intervention_n_real_stationary_points"] >= 1
    assert out["F_intervention_cross_check_abs_delta"] < 1e-6


@pytest.mark.parametrize("cell_id", CELLS_UNDER_TEST)
def test_certified_optimum_beats_any_wider_finite_window(design, cell_id):
    """The certified value must be <= the best over a window far wider than the old [-2.5, 2.5]."""
    seed = seed_list(design, "V3_BENCHMARK")[0]
    _regime, system, traj, bundle = _realize(design, cell_id, seed)
    from src_v3.benchmarks import _true_step_bundle

    _, delta_true, _include, dQ, steps, _n, _k = _true_step_bundle(
        design, system, traj, bundle
    )
    profile = build_pumped_profile(delta_true, dQ, steps, pumped=0)
    out = f_intervention_for_system(design, system, traj, bundle)
    grid = np.concatenate(
        [
            np.linspace(-2.5, 2.5, 5001),
            np.linspace(-40.0, 40.0, 4001),
            np.linspace(-1.05, 1.05, 4001),
        ]
    )
    best = min(
        (v for v in (profile.direct_nire(float(a)) for a in grid) if np.isfinite(v)),
        default=float("inf"),
    )
    assert out["F_intervention_pumped"] <= best + 1e-9


def test_uncoupled_single_node_k1_recovers_the_analytic_optimum(design):
    """Single node, k=1: the truth IS in the L family, at a = A_00 and kappa = -B_Q."""
    seed = seed_list(design, "V3_DETERMINISM")[0]
    _regime, system, traj, bundle = _realize(design, "A1_PEXACT_K1", seed)
    assert system.n_nodes == 1
    out = f_intervention_for_system(design, system, traj, bundle)
    assert out["F_intervention_pumped"] < 1e-10
    assert out["F_intervention_all"] < 1e-10
    assert out["neighbor_unmodeled_floor"] == pytest.approx(0.0, abs=1e-15)
    assert out["F_intervention_a0"] == pytest.approx(float(system.A[0, 0]), rel=1e-6)
    assert out["F_intervention_kappa0"] == pytest.approx(-float(system.B_Q[0]), rel=1e-6)
    assert out["F_intervention_global_certified"] is True


def test_pumped_benchmark_never_exceeds_the_zero_prediction(design):
    """kappa = 0 gives normalized error exactly 1, so the minimum can never exceed 1."""
    seed = seed_list(design, "V3_BENCHMARK")[0]
    for cell_id in CELLS_UNDER_TEST:
        _regime, system, traj, bundle = _realize(design, cell_id, seed)
        out = f_intervention_for_system(design, system, traj, bundle)
        assert out["F_intervention_pumped"] <= 1.0 + 1e-12, cell_id
        assert out["F_intervention_all"] <= 1.0 + 1e-12, cell_id


# -------------------------------------------------------------------------------------
# All-node vs pumped-node, and the exact neighbour floor
# -------------------------------------------------------------------------------------


@pytest.mark.parametrize("cell_id", CELLS_UNDER_TEST)
def test_all_node_identity_and_floor_invariant(design, cell_id):
    seed = seed_list(design, "V3_BENCHMARK")[0]
    _regime, system, traj, bundle = _realize(design, cell_id, seed)
    out = f_intervention_for_system(design, system, traj, bundle)

    n_incl = out["n_included_nodes"]
    n_non = out["n_included_nonpumped_nodes"]
    assert out["include_node0"] is True
    assert n_non == n_incl - 1

    # Closed-form floor under the frozen node-averaged per-node-normalized NIRE.
    assert out["neighbor_unmodeled_floor"] == pytest.approx(n_non / n_incl, rel=0, abs=1e-12)
    # Exact identity between the realised frozen NIRE and the closed form.
    assert out["F_intervention_all_identity_residual"] < 1e-10
    # The hard invariant.
    assert out["F_intervention_all"] >= out["neighbor_unmodeled_floor"] - 1e-12
    assert out["F_intervention_all"] == pytest.approx(
        out["neighbor_unmodeled_floor"] + out["F_intervention_pumped"] / n_incl,
        rel=0,
        abs=1e-10,
    )


def test_pumped_and_all_node_views_separate_direct_from_propagated(design):
    """Coupled cells: the all-node value is dominated by the floor, the pumped value is not."""
    seed = seed_list(design, "V3_BENCHMARK")[0]
    _regime, system, traj, bundle = _realize(design, "B_GHIGH", seed)
    out = f_intervention_for_system(design, system, traj, bundle)
    assert out["n_included_nodes"] >= 2
    assert out["neighbor_unmodeled_floor"] > 0.4
    assert out["F_intervention_pumped"] < 0.1
    assert out["F_intervention_all"] > out["F_intervention_pumped"]


# -------------------------------------------------------------------------------------
# Analytically controlled COUPLED structural fixture (the Block-B failure mode)
# -------------------------------------------------------------------------------------


def _coupled_fixture(n_steps: int = 10, magnitude: float = 1.0):
    """Two-node coupled truth with an analytically known paired response.

    delta[t+1] = A delta[t] - B_Q * delta_Q[t], with the step at node 0 only. Node 1 is never
    pumped, so any response there is purely propagated through the off-diagonal of A.
    """
    A = np.array([[0.90, 0.06], [0.06, 0.90]])
    B_Q = np.array([1.0, 1.0])
    dQ = np.zeros((n_steps, 2))
    dQ[:, 0] = magnitude
    delta = np.zeros((n_steps + 1, 2))
    for t in range(n_steps):
        delta[t + 1] = A @ delta[t] - B_Q * dQ[t]
    return A, dQ, delta


def test_coupled_fixture_neighbour_receives_true_induced_drawdown():
    _A, _dQ, delta = _coupled_fixture()
    assert abs(delta[-1, 0]) > 1e-6
    assert abs(delta[-1, 1]) > 1e-6, "the coupled fixture must induce a real neighbour response"
    assert np.sign(delta[-1, 1]) == np.sign(delta[-1, 0])


def test_coupled_fixture_local_family_predicts_zero_at_the_non_pumped_neighbour():
    """For EVERY admissible (a_1, beta_q_1) the L state at the non-pumped node stays zero."""
    _A, dQ, _delta = _coupled_fixture()
    rng = np.random.default_rng(11)
    for _ in range(50):
        a_diag = rng.uniform(-3.0, 3.0, size=2)
        beta = rng.normal(size=2)
        hat = l_family_paired_response(a_diag, beta, dQ)
        np.testing.assert_allclose(hat[:, 1], 0.0, rtol=0, atol=0.0)
        assert not np.allclose(hat[:, 0], 0.0)


def test_coupled_fixture_all_node_benchmark_has_strictly_positive_irreducible_component():
    _A, dQ, delta = _coupled_fixture()
    steps = dQ.shape[0]
    include = inclusion_mask(delta, 0.01)
    assert include.tolist() == [True, True]

    floor = neighbor_unmodeled_floor(delta, include, steps, pumped=0)
    assert floor == pytest.approx(0.5, rel=0, abs=1e-12)

    profile = build_pumped_profile(delta, dQ, steps, pumped=0)
    exact = profile.global_max_ratio()
    best_a = exact["argmax_a"]
    f_pumped = profile.direct_nire(best_a)
    kappa = profile.direct_kappa(best_a)

    a_diag = np.zeros(2)
    a_diag[0] = best_a
    beta = np.zeros(2)
    beta[0] = kappa
    hat = l_family_paired_response(a_diag, beta, dQ)
    f_all = persistent_nire(delta, hat, include, steps)

    # Strictly positive irreducible component, entirely from the unmodelled neighbour.
    assert f_all >= floor - 1e-12
    assert f_all > 0.49
    assert f_all == pytest.approx(floor + f_pumped / 2.0, rel=0, abs=1e-10)
    # The non-pumped node contributes exactly 1.0 to the node-averaged NIRE.
    assert normalized_error(delta[: steps + 1, 1], hat[: steps + 1, 1]) == pytest.approx(
        1.0, rel=0, abs=1e-14
    )


def test_coupled_fixture_floor_grows_with_the_number_of_affected_neighbours():
    """1/2, 2/3, 4/5 arise from the frozen node weighting, not a coupling threshold."""
    for n_nodes, expected in ((2, 1 / 2), (3, 2 / 3), (5, 4 / 5)):
        n_steps = 8
        A = np.full((n_nodes, n_nodes), 0.05)
        np.fill_diagonal(A, 0.9)
        dQ = np.zeros((n_steps, n_nodes))
        dQ[:, 0] = 1.0
        delta = np.zeros((n_steps + 1, n_nodes))
        for t in range(n_steps):
            delta[t + 1] = A @ delta[t] - np.ones(n_nodes) * dQ[t]
        include = inclusion_mask(delta, 0.01)
        assert int(include.sum()) == n_nodes
        floor = neighbor_unmodeled_floor(delta, include, n_steps, pumped=0)
        assert floor == pytest.approx(expected, rel=0, abs=1e-12)


def test_neighbor_floor_is_nan_without_included_nodes():
    delta = np.zeros((4, 2))
    include = np.zeros(2, dtype=bool)
    assert np.isnan(neighbor_unmodeled_floor(delta, include, 3, pumped=0))


# -------------------------------------------------------------------------------------
# Frozen-artifact consistency (all 21 cells)
# -------------------------------------------------------------------------------------


def test_frozen_benchmark_artifact_is_certified_for_all_21_cells(v3_root):
    import json

    path = v3_root / "outputs" / "benchmarks" / "BENCHMARKS_V3.json"
    if not path.exists():
        pytest.skip("benchmarks not yet computed in this working tree")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload["rows"]
    if not rows or "F_intervention_all" not in rows[0]:
        pytest.skip("Pass-1.1 benchmark artifact not yet computed")
    assert len(rows) == 21
    assert payload["invariant_violations"] == []
    assert payload["decomposition_is_additive"] is False
    for row in rows:
        assert row["F_intervention_global_certified"] in (True, "True")
        assert float(row["F_intervention_all"]) >= float(row["neighbor_unmodeled_floor"]) - 1e-9
        assert float(row["F_intervention_all_identity_residual"]) < 1e-9
        assert 0.0 <= float(row["F_intervention_pumped"]) <= 1.0 + 1e-12
