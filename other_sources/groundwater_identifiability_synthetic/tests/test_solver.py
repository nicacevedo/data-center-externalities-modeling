"""Validation of the nonnegative-L1 solver.

scipy.optimize.lsq_linear provides no L1 path, so the penalty is implemented directly. This
file is the evidence that the implementation is correct: it is checked against lsq_linear at
lambda = 0, against SLSQP and an independent coordinate-descent reference at lambda > 0, and
against the KKT conditions of the profiled problem.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.optimize import lsq_linear, minimize

from groundwater_identifiability_synthetic.src.fit import (
    _orthonormal_basis,
    _projector_apply,
    kkt_residual,
    solve_nonneg_l1,
)


def _problem(seed: int, n: int = 120, p_free: int = 3, p_pen: int = 5):
    rng = np.random.default_rng(seed)
    X = np.column_stack([np.ones(n), rng.normal(size=(n, p_free - 1))])
    Z = np.abs(rng.normal(size=(n, p_pen))) + 0.1
    beta = rng.normal(size=p_free)
    kappa = np.array([0.8, 0.0, 0.3, 0.0, 1.2])[:p_pen]
    y = X @ beta + Z @ kappa + rng.normal(0.0, 0.1, size=n)
    return X, Z, y


def _objective(X, Z, y, beta, kappa, lam):
    residual = y - X @ beta - Z @ kappa
    return float(residual @ residual + lam * kappa.sum())


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_matches_lsq_linear_at_zero_penalty(seed):
    """At lambda = 0 the problem is bounded least squares, which scipy solves directly."""
    X, Z, y = _problem(seed)
    beta, kappa = solve_nonneg_l1(X, Z, y, lam=0.0)

    joint = np.column_stack([X, Z])
    lower = np.concatenate([np.full(X.shape[1], -np.inf), np.zeros(Z.shape[1])])
    upper = np.full(joint.shape[1], np.inf)
    reference = lsq_linear(joint, y, bounds=(lower, upper), tol=1e-14)

    ours = _objective(X, Z, y, beta, kappa, 0.0)
    theirs = _objective(X, Z, y, reference.x[: X.shape[1]], reference.x[X.shape[1] :], 0.0)
    assert ours <= theirs + 1e-8
    assert np.allclose(kappa, reference.x[X.shape[1] :], atol=1e-6)


@pytest.mark.parametrize("lam", [0.01, 0.1, 1.0, 10.0])
def test_matches_slsqp_reference(lam):
    X, Z, y = _problem(7)
    beta, kappa = solve_nonneg_l1(X, Z, y, lam=lam)

    p_free, p_pen = X.shape[1], Z.shape[1]

    def packed_objective(v):
        return _objective(X, Z, y, v[:p_free], v[p_free:], lam)

    bounds = [(None, None)] * p_free + [(0.0, None)] * p_pen
    reference = minimize(
        packed_objective,
        np.zeros(p_free + p_pen),
        method="SLSQP",
        bounds=bounds,
        options={"maxiter": 2000, "ftol": 1e-14},
    )
    assert _objective(X, Z, y, beta, kappa, lam) <= reference.fun + 1e-6


@pytest.mark.parametrize("lam", [0.01, 0.1, 1.0, 10.0])
def test_matches_coordinate_descent_reference(lam):
    """Independent solver: coordinate descent on the profiled nonnegative problem."""
    X, Z, y = _problem(11)
    beta, kappa = solve_nonneg_l1(X, Z, y, lam=lam)

    U = _orthonormal_basis(X)
    Zt = _projector_apply(U, Z)
    yt = _projector_apply(U, y)

    k = np.zeros(Z.shape[1])
    norms = np.sum(Zt * Zt, axis=0)
    for _ in range(20000):
        previous = k.copy()
        for j in range(len(k)):
            partial = yt - Zt @ k + Zt[:, j] * k[j]
            k[j] = max(0.0, (Zt[:, j] @ partial - lam / 2.0) / max(norms[j], 1e-14))
        if np.max(np.abs(k - previous)) < 1e-12:
            break
    assert np.allclose(kappa, k, atol=1e-6), f"ours={kappa} cd={k}"


@pytest.mark.parametrize("lam", [0.0, 0.05, 0.5, 5.0])
def test_kkt_conditions_hold(lam):
    X, Z, y = _problem(13)
    _, kappa = solve_nonneg_l1(X, Z, y, lam=lam)
    U = _orthonormal_basis(X)
    Zt = _projector_apply(U, Z)
    yt = _projector_apply(U, y)
    assert kkt_residual(Zt, yt, kappa, lam) < 1e-5


def test_nonnegativity_is_enforced():
    rng = np.random.default_rng(3)
    n = 80
    X = np.ones((n, 1))
    Z = np.abs(rng.normal(size=(n, 4))) + 0.1
    y = X[:, 0] * 2.0 - Z @ np.array([1.0, 0.5, 0.2, 0.1]) + rng.normal(0, 0.05, n)
    _, kappa = solve_nonneg_l1(X, Z, y, lam=0.0)
    assert np.all(kappa >= -1e-12), "negative coupling must be impossible"


def test_penalty_shrinks_and_sparsifies():
    X, Z, y = _problem(17)
    previous_sum = np.inf
    for lam in (0.0, 1.0, 10.0, 100.0, 1000.0):
        _, kappa = solve_nonneg_l1(X, Z, y, lam=lam)
        assert kappa.sum() <= previous_sum + 1e-8
        previous_sum = kappa.sum()
    assert previous_sum == pytest.approx(0.0, abs=1e-6)


def test_free_block_is_unpenalized_and_unconstrained():
    """The pumping coefficient must be free to go negative and must not be shrunk."""
    rng = np.random.default_rng(23)
    n = 200
    pumping = rng.normal(size=n)
    X = np.column_stack([np.ones(n), pumping])
    Z = np.abs(rng.normal(size=(n, 3))) + 0.1
    true_beta_q = -0.75
    y = 1.0 + true_beta_q * pumping + Z @ np.array([0.4, 0.0, 0.9]) + rng.normal(0, 0.02, n)

    for lam in (0.0, 1.0, 50.0):
        beta, _ = solve_nonneg_l1(X, Z, y, lam=lam)
        assert beta[1] < 0.0, "the free pumping coefficient must be able to be negative"
    beta_zero, _ = solve_nonneg_l1(X, Z, y, lam=0.0)
    assert beta_zero[1] == pytest.approx(true_beta_q, abs=0.05)


def test_profiling_is_equivalent_to_joint_solution():
    """Profiling out the free block must not change the optimum."""
    X, Z, y = _problem(29)
    lam = 0.3
    beta, kappa = solve_nonneg_l1(X, Z, y, lam=lam)
    p_free, p_pen = X.shape[1], Z.shape[1]
    joint = minimize(
        lambda v: _objective(X, Z, y, v[:p_free], v[p_free:], lam),
        np.concatenate([beta, kappa]),
        method="L-BFGS-B",
        bounds=[(None, None)] * p_free + [(0.0, None)] * p_pen,
        options={"maxiter": 20000, "ftol": 1e-16},
    )
    assert _objective(X, Z, y, beta, kappa, lam) <= joint.fun + 1e-8


def test_rank_deficient_free_block_is_handled():
    """A duplicated free column must not break the projector."""
    X, Z, y = _problem(31)
    X_deficient = np.column_stack([X, X[:, 1]])
    beta, kappa = solve_nonneg_l1(X_deficient, Z, y, lam=0.1)
    assert np.all(np.isfinite(beta))
    assert np.all(np.isfinite(kappa))
    assert np.all(kappa >= -1e-12)
