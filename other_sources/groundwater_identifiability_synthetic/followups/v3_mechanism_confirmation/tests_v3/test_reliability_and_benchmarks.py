"""Reliability fixtures, recombination, F_train/F_intervention, own-pumping, no leakage."""

from __future__ import annotations

import inspect

import numpy as np

from src_v3 import dgp, interventions, metrics, models, fit as fit_module
from src_v3.benchmarks import f_intervention_for_system
from src_v3.design import resolve_v3_cell, rng_for, seed_list
from src_v3.diagnostics import l_family_paired_response, neighbour_flux_share
from src_v3.modes import RNG_NAMED, SEED_ORTHOGONAL
from src_v3.observations import make_observations
from src_v3.reliability import reliability_from_columns, theory_reliability
from src_v3.rng import StreamBank


def test_partial_reliability_analytic_fixture():
    q_true = np.array([1.0, 2.0, 3.0, 4.0])
    Z = np.ones((4, 1))
    out = reliability_from_columns(q_true, q_true, Z)
    assert abs(out["partial_reliability_q"] - 1.0) < 1e-12
    q_obs = 2.0 * q_true
    out2 = reliability_from_columns(q_obs, q_true, Z)
    assert abs(out2["partial_reliability_q"] - 0.5) < 1e-12
    assert abs(out2["variance_form_reliability_q"] - 0.5) < 1e-12


def test_attenuation_identity_fixture():
    """Classical identity: if y independent of u after residualizing, beta ratio = SS_true/SS_obs * (q_obs' y / q_true' y) -> reliability when q_obs=q_true+u with u orthogonal to y.

    Hand construction: M = I (Z empty intercept-only with demeaned series already).
    """
    rng = np.random.default_rng(0)
    q_true = rng.normal(size=200)
    y = 3.0 * q_true
    sigma = 0.2
    z = rng.normal(size=200)
    u = q_true * (np.exp(sigma * z - 0.5 * sigma * sigma) - 1.0)
    q_obs = q_true + u
    Z = np.ones((200, 1))
    rel = reliability_from_columns(q_obs, q_true, Z)
    # residualize
    Mqt = q_true - q_true.mean()
    My = y - y.mean()
    Mqo = q_obs - q_obs.mean()
    beta_exact = float(Mqt @ My / (Mqt @ Mqt))
    beta_obs = float(Mqo @ My / (Mqo @ Mqo))
    ratio = beta_obs / beta_exact
    # identity: ratio = (q_obs' y / q_true' y) * (SS_true / SS_obs)
    identity = (Mqo @ My) / (Mqt @ My) * (rel["SS_true"] / rel["SS_obs"])
    assert abs(ratio - identity) < 1e-12
    assert abs(ratio - rel["partial_reliability_q"]) < 0.05


def test_theory_reliability_matches_formula():
    ss_true = 10.0
    sum_mtt = 4.0
    sigma = 0.1
    expected = ss_true / (ss_true + (np.exp(sigma**2) - 1.0) * sum_mtt)
    assert abs(theory_reliability(ss_true, sum_mtt, sigma) - expected) < 1e-15


def test_recombination_recovers_true_when_hat_equals_truth():
    a = np.array([0.8, 0.8])
    beta = np.array([-0.1, 0.0])
    dQ = np.ones((10, 2))
    dQ[:, 1] = 0.0
    hat = l_family_paired_response(a, beta, dQ)
    include = np.array([True, False])
    from src_v3.diagnostics import persistent_nire
    nire = persistent_nire(hat, hat, include, 8)
    assert nire == 0.0


def test_own_pumping_cannot_assign_neighbor_q():
    a = np.array([0.9, 0.9, 0.9])
    beta = np.array([-0.2, 0.0, 0.0])  # L family: only node 0
    dQ = np.zeros((5, 3))
    dQ[:, 0] = 1.0
    hat = l_family_paired_response(a, beta, dQ)
    assert np.allclose(hat[:, 1], 0.0)
    assert np.allclose(hat[:, 2], 0.0)
    assert not np.allclose(hat[:, 0], 0.0)


def test_uncoupled_truth_nonpumped_nodes_zero_induced(design):
    regime = resolve_v3_cell(design, "B_GNONE")
    system = dgp.build_system(
        design, regime.topology, regime.memory, regime.gamma, system_seed_mode="orthogonal_v3"
    )
    rng = rng_for(seed_list(design, "V3_DETERMINISM")[0])
    streams = StreamBank(seed_list(design, "V3_DETERMINISM")[0])
    traj = dgp.simulate(design, system, regime, rng, {}, streams=streams)
    bundle = make_observations(design, system, traj, regime, rng, streams=streams)
    k = bundle.cadence
    onset = bundle.test_onset()
    onset_fine = traj.analysis_start + int(bundle.t_fine[onset])
    specs = interventions.build_intervention_specs(design, system, traj, 52)
    spec = next(s for s in specs if s.name == "persistent_step")
    delta = interventions.true_paired_response(system, traj, onset_fine, spec, k)
    assert np.allclose(delta[:, 1:], 0.0, atol=1e-10)
    assert neighbour_flux_share(system, traj) == 0.0


def test_coupled_truth_nonpumped_nodes_may_be_nonzero(design):
    regime = resolve_v3_cell(design, "B_GHIGH")
    system = dgp.build_system(
        design, regime.topology, regime.memory, regime.gamma, system_seed_mode="orthogonal_v3"
    )
    rng = rng_for(seed_list(design, "V3_DETERMINISM")[0])
    streams = StreamBank(seed_list(design, "V3_DETERMINISM")[0])
    traj = dgp.simulate(design, system, regime, rng, {}, streams=streams)
    bundle = make_observations(design, system, traj, regime, rng, streams=streams)
    k = bundle.cadence
    onset = bundle.test_onset()
    onset_fine = traj.analysis_start + int(bundle.t_fine[onset])
    specs = interventions.build_intervention_specs(design, system, traj, 52)
    spec = next(s for s in specs if s.name == "persistent_step")
    delta = interventions.true_paired_response(system, traj, onset_fine, spec, k)
    assert np.max(np.abs(delta[:, 1:])) > 1e-8


def test_f_intervention_zero_on_uncoupled_single_node(design):
    regime = resolve_v3_cell(design, "A1_PEXACT_K1")
    # single-node, gamma NONE: L family can represent the local response.
    system = dgp.build_system(
        design, regime.topology, regime.memory, regime.gamma, system_seed_mode="orthogonal_v3"
    )
    rng = rng_for(seed_list(design, "V3_DETERMINISM")[0])
    streams = StreamBank(seed_list(design, "V3_DETERMINISM")[0])
    traj = dgp.simulate(design, system, regime, rng, {}, streams=streams)
    bundle = make_observations(design, system, traj, regime, rng, streams=streams)
    result = f_intervention_for_system(design, system, traj, bundle)
    assert result["F_intervention_all"] < 1e-3
    assert result["F_intervention_pumped"] < 1e-3
    assert result["F_intervention_global_certified"]


def test_no_truth_leakage_into_fitting():
    for module in (models, fit_module):
        source = inspect.getsource(module)
        assert "from .dgp import" not in source
        assert "SystemTruth" not in source
        assert "Q_true" not in source
        assert "true_edges" not in source
