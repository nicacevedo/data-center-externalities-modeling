"""Partial/residualized pumping reliability and signed attenuation diagnostics."""

from __future__ import annotations

import numpy as np

from .models import TRAIN, split_masks


def residual_maker(Z: np.ndarray) -> np.ndarray:
    """M = I - Z (Z'Z)^+ Z'. Includes intercept column already in Z."""
    if Z.size == 0:
        raise ValueError("empty residualizer")
    gram = Z.T @ Z
    pinv = np.linalg.pinv(gram, rcond=1e-12)
    return np.eye(Z.shape[0]) - Z @ pinv @ Z.T


def reliability_from_columns(
    q_obs: np.ndarray,
    q_true: np.ndarray,
    Z: np.ndarray,
) -> dict[str, float]:
    """TRAIN-row residualized reliability of the pumping regressor.

    Z is the model-L design *without* the pumping column, intercept included.
    """
    q_obs = np.asarray(q_obs, float).ravel()
    q_true = np.asarray(q_true, float).ravel()
    u = q_obs - q_true
    M = residual_maker(np.asarray(Z, float))
    Mqt = M @ q_true
    Mqo = M @ q_obs
    Mu = M @ u
    ss_true = float(Mqt @ Mqt)
    ss_obs = float(Mqo @ Mqo)
    ss_u = float(Mu @ Mu)
    cp = float(Mqt @ Mqo)
    partial = cp / ss_obs if ss_obs > 1e-18 else float("nan")
    var_form = ss_true / (ss_true + ss_u) if (ss_true + ss_u) > 1e-18 else float("nan")
    v_true = float(np.var(q_true))
    v_obs = float(np.var(q_obs))
    uncond = v_true / v_obs if v_obs > 1e-18 else float("nan")
    m_diag = np.diag(M)
    theory_den = ss_true  # filled by caller with sigma if needed
    return {
        "partial_reliability_q": partial,
        "variance_form_reliability_q": var_form,
        "unconditional_reliability_q": uncond,
        "SS_true": ss_true,
        "SS_obs": ss_obs,
        "SS_error": ss_u,
        "cross_product": cp,
        "sum_qtrue2_Mtt": float(np.sum(q_true**2 * m_diag)),
    }


def theory_reliability(ss_true: float, sum_qtrue2_Mtt: float, sigma: float) -> float:
    extra = (np.exp(sigma * sigma) - 1.0) * sum_qtrue2_Mtt
    den = ss_true + extra
    return float(ss_true / den) if den > 1e-18 else float("nan")


def node_reliability(design, q_true_aligned: np.ndarray, sigma: float | None = None) -> dict[str, float]:
    """Reliability on admissible TRAIN rows of one NodeDesign.

    `q_true_aligned` is true interval pumping on the *unfiltered* transition index
    matching bundle.Q_obs rows; it is then subset to design.rows.
    """
    masks = split_masks(design)
    train = masks[TRAIN]
    names = list(design.names)
    if "pumping" not in names:
        return {k: float("nan") for k in (
            "partial_reliability_q", "variance_form_reliability_q",
            "unconditional_reliability_q", "SS_true", "SS_obs", "SS_error", "cross_product",
            "sum_qtrue2_Mtt", "theory_reliability_q",
        )}
    j = names.index("pumping")
    X = design.X[train]
    rows = design.rows[train]
    q_obs = X[:, j]
    q_true = np.asarray(q_true_aligned, float)[rows]
    intercept = np.ones((X.shape[0], 1))
    Z_rest = np.delete(X, j, axis=1)
    Z = np.concatenate([intercept, Z_rest], axis=1)
    out = reliability_from_columns(q_obs, q_true, Z)
    if sigma is None or float(sigma) <= 0:
        out["theory_reliability_q"] = 1.0 if np.isfinite(out["partial_reliability_q"]) else float("nan")
    else:
        out["theory_reliability_q"] = theory_reliability(
            out["SS_true"], out["sum_qtrue2_Mtt"], float(sigma)
        )
    return out
