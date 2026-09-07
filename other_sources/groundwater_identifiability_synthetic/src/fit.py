"""Estimation layer.

Receives `ObservationBundle` objects only. Train-only scaling; validation-only selection of
the network penalty and the spatial kernel bandwidth; the protected test set is never used
for any choice.

Nonnegative-L1 note (this is the part scipy does not give for free): `lsq_linear` has no L1
path. Because the network coefficients are constrained nonnegative, the L1 penalty is the
LINEAR term lambda * 1'kappa, so

    min_{beta free, kappa >= 0}  ||y - X beta - Z kappa||^2 + lambda * 1'kappa

is a smooth convex QP with simple bounds. The unpenalized block is profiled out
analytically and the bounded problem in kappa is solved with L-BFGS-B and an analytic
gradient. Only the nonnegative network coefficients are penalized; pumping and recharge
coefficients are neither penalized nor sign-constrained, which is what keeps the
sign-recovery gate metric non-vacuous.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize

from .models import NodeDesign, build_design, split_masks
from .observations import ObservationBundle, TEST, TRAIN, VALIDATION

_SCALE_FLOOR = 1e-12


@dataclass(frozen=True)
class NodeFit:
    node: int
    model: str
    names: tuple[str, ...]
    coef: np.ndarray                 # ORIGINAL feature units, aligned with names
    intercept: float
    kappa_neighbors: tuple[int, ...]
    lam: float | None
    bandwidth: float | None
    n_train_rows: int
    diagnostics: dict = field(default_factory=dict)

    def coef_of(self, name: str, default: float = np.nan) -> float:
        if name not in self.names:
            return default
        return float(self.coef[self.names.index(name)])

    def kappa_vector(self, n_nodes: int) -> np.ndarray:
        out = np.zeros(n_nodes)
        for j in self.kappa_neighbors:
            out[j] = self.coef_of(f"kappa_{j}", 0.0)
        return out

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.intercept + X @ self.coef


# -------------------------------------------------------------------------------------
# Solvers
# -------------------------------------------------------------------------------------


def _projector_apply(U: np.ndarray, V: np.ndarray) -> np.ndarray:
    """Apply the residual maker M = I - U U' for an orthonormal basis U of col(X)."""
    if U.size == 0:
        return V
    return V - U @ (U.T @ V)


def _orthonormal_basis(X: np.ndarray, tol_scale: float = 1e-10) -> np.ndarray:
    """SVD-based orthonormal basis of col(X); robust to rank deficiency."""
    if X.shape[1] == 0:
        return np.zeros((X.shape[0], 0))
    U, s, _ = np.linalg.svd(X, full_matrices=False)
    if s.size == 0:
        return np.zeros((X.shape[0], 0))
    keep = s > (tol_scale * max(s[0], 1.0))
    return U[:, keep]


def solve_nonneg_l1(
    X_free: np.ndarray,
    Z_pen: np.ndarray,
    y: np.ndarray,
    lam: float,
    tol: float = 1e-12,
) -> tuple[np.ndarray, np.ndarray]:
    """min_{beta free, kappa >= 0} ||y - X beta - Z kappa||^2 + lam * sum(kappa).

    Returns (beta, kappa). Validated in tests against lsq_linear (lam = 0), SLSQP,
    coordinate descent, and the KKT conditions.
    """
    n_pen = Z_pen.shape[1]
    if n_pen == 0:
        beta, *_ = np.linalg.lstsq(X_free, y, rcond=None)
        return beta, np.zeros(0)

    U = _orthonormal_basis(X_free)
    Zt = _projector_apply(U, Z_pen)
    yt = _projector_apply(U, y)

    G = Zt.T @ Zt
    c = Zt.T @ yt

    def objective(kappa: np.ndarray) -> float:
        return float(kappa @ G @ kappa - 2.0 * c @ kappa + lam * kappa.sum())

    def gradient(kappa: np.ndarray) -> np.ndarray:
        return 2.0 * (G @ kappa) - 2.0 * c + lam

    start = np.zeros(n_pen)
    result = minimize(
        objective,
        start,
        jac=gradient,
        method="L-BFGS-B",
        bounds=[(0.0, None)] * n_pen,
        options={"maxiter": 20000, "ftol": tol, "gtol": 1e-12},
    )
    kappa = np.maximum(result.x, 0.0)

    if X_free.shape[1] > 0:
        beta, *_ = np.linalg.lstsq(X_free, y - Z_pen @ kappa, rcond=None)
    else:
        beta = np.zeros(0)
    return beta, kappa


def kkt_residual(Zt: np.ndarray, yt: np.ndarray, kappa: np.ndarray, lam: float) -> float:
    """Max KKT violation for the profiled nonnegative-L1 problem. Used by tests."""
    grad = 2.0 * (Zt.T @ (Zt @ kappa - yt)) + lam
    active = kappa <= 1e-10
    violation = np.maximum(-grad[active], 0.0) if active.any() else np.zeros(1)
    stationary = np.abs(grad[~active]) if (~active).any() else np.zeros(1)
    return float(max(violation.max(), stationary.max()))


def _fit_scaled(
    X: np.ndarray,
    y: np.ndarray,
    penalized: np.ndarray,
    lam: float,
) -> tuple[float, np.ndarray, dict]:
    """Train-only z-scaling, then solve, then return coefficients in ORIGINAL units."""
    mean = X.mean(axis=0)
    scale = X.std(axis=0, ddof=0)
    scale = np.where(scale > _SCALE_FLOOR, scale, 1.0)
    Xs = (X - mean) / scale

    y_mean = float(y.mean())
    yc = y - y_mean

    free_idx = np.flatnonzero(~penalized)
    pen_idx = np.flatnonzero(penalized)
    X_free = np.column_stack([np.ones(len(yc)), Xs[:, free_idx]])
    Z_pen = Xs[:, pen_idx]

    beta, kappa = solve_nonneg_l1(X_free, Z_pen, yc, lam)

    scaled_coef = np.zeros(X.shape[1])
    scaled_coef[free_idx] = beta[1:]
    scaled_coef[pen_idx] = kappa
    scaled_intercept = float(beta[0]) + y_mean

    # Positive scaling preserves nonnegativity, so the kappa block stays >= 0 after unscaling.
    coef = scaled_coef / scale
    intercept = scaled_intercept - float(np.sum(scaled_coef * mean / scale))

    diagnostics = {
        "scaled_intercept": scaled_intercept,
        "feature_scale": scale,
        "feature_mean": mean,
    }
    return intercept, coef, diagnostics


def fit_node(design: NodeDesign, lam: float = 0.0, min_rows: int = 12) -> NodeFit | None:
    masks = split_masks(design)
    train = masks[TRAIN]
    n_train = int(train.sum())
    if n_train < max(min_rows, design.X.shape[1] + 2):
        return None

    intercept, coef, diagnostics = _fit_scaled(
        design.X[train], design.y[train], design.penalized, lam
    )
    return NodeFit(
        node=design.node,
        model=design.model,
        names=design.names,
        coef=coef,
        intercept=intercept,
        kappa_neighbors=design.kappa_neighbors,
        lam=lam if design.penalized.any() else None,
        bandwidth=design.bandwidth,
        n_train_rows=n_train,
        diagnostics=diagnostics,
    )


def _split_rmse(fit: NodeFit, design: NodeDesign, split_label: str) -> float:
    mask = split_masks(design)[split_label]
    if not mask.any():
        return float("nan")
    residual = design.y[mask] - fit.predict(design.X[mask])
    return float(np.sqrt(np.mean(residual**2)))


# -------------------------------------------------------------------------------------
# Ladder fitting with validation-only selection
# -------------------------------------------------------------------------------------


@dataclass
class LadderFit:
    fits: dict[str, dict[int, NodeFit]]
    designs: dict[str, dict[int, NodeDesign]]
    selection: dict[str, dict]

    def has(self, model: str, node: int) -> bool:
        return self.fits.get(model, {}).get(node) is not None


def fit_ladder(
    bundle: ObservationBundle,
    design_cfg: dict,
    models: tuple[str, ...] = ("B0", "L", "S", "N"),
) -> LadderFit:
    """Fit every rung. Selection uses VALIDATION only; TEST is never touched here."""
    n = bundle.n_nodes
    nodes = [int(i) for i in np.flatnonzero(bundle.observed_nodes)]

    fits: dict[str, dict[int, NodeFit]] = {}
    designs: dict[str, dict[int, NodeDesign]] = {}
    selection: dict[str, dict] = {}

    for model in models:
        if model == "S" and n == 1:
            continue
        if model == "N" and n == 1:
            continue

        if model == "S":
            grid = [float(v) for v in design_cfg["models"]["S"]["kernel_bandwidth_grid"]]
            best, best_score = None, np.inf
            for bandwidth in grid:
                score, count = 0.0, 0
                for node in nodes:
                    d = build_design(bundle, node, model, bandwidth=bandwidth)
                    f = fit_node(d)
                    if f is None:
                        continue
                    rmse = _split_rmse(f, d, VALIDATION)
                    if np.isfinite(rmse):
                        score += rmse
                        count += 1
                if count and (score / count) < best_score:
                    best_score, best = score / count, bandwidth
            if best is None:
                continue
            selection["S"] = {"bandwidth": best, "validation_rmse": best_score}
            designs[model] = {node: build_design(bundle, node, model, bandwidth=best) for node in nodes}
            fits[model] = {node: fit_node(d) for node, d in designs[model].items()}

        elif model == "N":
            grid = [float(v) for v in design_cfg["models"]["N"]["penalty_grid_lambda"]]
            node_designs = {node: build_design(bundle, node, model) for node in nodes}
            best, best_score = None, np.inf
            for lam in grid:
                score, count = 0.0, 0
                for node in nodes:
                    f = fit_node(node_designs[node], lam=lam)
                    if f is None:
                        continue
                    rmse = _split_rmse(f, node_designs[node], VALIDATION)
                    if np.isfinite(rmse):
                        score += rmse
                        count += 1
                if count and (score / count) < best_score:
                    best_score, best = score / count, lam
            if best is None:
                continue
            selection["N"] = {"lambda": best, "validation_rmse": best_score}
            designs[model] = node_designs
            fits[model] = {node: fit_node(node_designs[node], lam=best) for node in nodes}

        else:
            designs[model] = {node: build_design(bundle, node, model) for node in nodes}
            fits[model] = {node: fit_node(d) for node, d in designs[model].items()}

    return LadderFit(fits=fits, designs=designs, selection=selection)


# -------------------------------------------------------------------------------------
# Assembling the implied transition matrix
# -------------------------------------------------------------------------------------


def implied_transition_matrix(ladder: LadderFit, model: str, n_nodes: int) -> np.ndarray:
    """A_hat from a fitted rung.

    For N:  A_ii = a_i - sum_j kappa_ij  and  A_ij = kappa_ij, because the regressor is the
    head DIFFERENCE (y_j - y_i), not y_j. For the other rungs A is diagonal.
    """
    A_hat = np.full((n_nodes, n_nodes), np.nan)
    fits = ladder.fits.get(model, {})
    for i in range(n_nodes):
        fit = fits.get(i)
        if fit is None:
            continue
        own = fit.coef_of("own_level", np.nan)
        if model == "N":
            kappa = fit.kappa_vector(n_nodes)
            A_hat[i, :] = kappa
            A_hat[i, i] = own - kappa.sum()
        else:
            A_hat[i, :] = 0.0
            A_hat[i, i] = own
    return A_hat


def protected_test_rmse(ladder: LadderFit, model: str) -> float:
    """Mean over nodes of protected-test RMSE. Reported, never used for selection."""
    values = []
    for node, fit in ladder.fits.get(model, {}).items():
        if fit is None:
            continue
        d = ladder.designs[model][node]
        rmse = _split_rmse(fit, d, TEST)
        if np.isfinite(rmse):
            values.append(rmse)
    return float(np.mean(values)) if values else float("nan")


def max_abs_protected_prediction(ladder: LadderFit, model: str) -> float:
    worst = 0.0
    for node, fit in ladder.fits.get(model, {}).items():
        if fit is None:
            continue
        d = ladder.designs[model][node]
        mask = split_masks(d)[TEST]
        if not mask.any():
            continue
        worst = max(worst, float(np.max(np.abs(fit.predict(d.X[mask])))))
    return worst
