"""V3-only diagnostics: coupling materiality, signed persistence error, recombinations.

These operate in the evaluation layer. They never feed coefficients back into fitting.
"""

from __future__ import annotations

import numpy as np

from . import metrics


def neighbour_flux_share(system, trajectory) -> float:
    """Synthetic dimensionless coupling-materiality diagnostic.

    Share of the true one-step head increment carried by cross-node (off-diagonal)
    transition terms, averaged over the analysis window. Internal to this known-truth
    system; not a field-observable Andhra Pradesh quantity.
    """
    start = int(trajectory.analysis_start)
    stop = start + int(trajectory.analysis_length) - 1
    if stop <= start:
        return float("nan")
    A_off = np.array(system.A, dtype=float, copy=True)
    np.fill_diagonal(A_off, 0.0)
    if np.allclose(A_off, 0.0):
        return 0.0
    h = trajectory.h[start:stop]
    h_next = trajectory.h[start + 1 : stop + 1]
    coupling = h @ A_off.T
    increment = h_next - h
    num = float(np.mean(np.abs(coupling)))
    den = float(np.mean(np.abs(increment)))
    if den <= 1e-18:
        return 0.0 if num <= 1e-18 else float("nan")
    return num / den


def signed_A_diag_relative_error(A_hat: np.ndarray, A_true_k: np.ndarray) -> float:
    """Median signed relative error of the diagonal of A_hat vs cadence-power A^k."""
    diag_hat = np.diag(np.asarray(A_hat, float))
    diag_true = np.diag(np.asarray(A_true_k, float))
    denom = np.maximum(np.abs(diag_true), 1e-12)
    rel = (diag_hat - diag_true) / denom
    good = np.isfinite(rel)
    return float(np.median(rel[good])) if good.any() else float("nan")


def l_family_paired_response(
    a_diag: np.ndarray,
    beta_q: np.ndarray,
    delta_q_interval: np.ndarray,
) -> np.ndarray:
    """Own-pumping-only diagonal-A response used by frozen model L.

    Recursion matches interventions.model_paired_response for L:
        out[t+1] = A @ out[t] + beta_q * delta_Q_interval[t]
    with A diagonal. Non-pumped nodes cannot be given a neighbour-Q coefficient.
    """
    n_steps, n = delta_q_interval.shape
    a_diag = np.asarray(a_diag, float).ravel()
    beta_q = np.asarray(beta_q, float).ravel()
    out = np.zeros((n_steps + 1, n))
    for t in range(n_steps):
        drive = beta_q * delta_q_interval[t]
        out[t + 1] = a_diag * out[t] + drive
        if not np.all(np.isfinite(out[t + 1])):
            out[t + 1] = np.nan
    return out


def persistent_nire(
    delta_true: np.ndarray,
    delta_hat: np.ndarray,
    include: np.ndarray,
    steps: int,
) -> float:
    per_node = [
        metrics.normalized_error(delta_true[: steps + 1, i], delta_hat[: steps + 1, i])
        for i in np.flatnonzero(include)
    ]
    array = np.asarray(per_node, dtype=float)
    good = np.isfinite(array)
    return float(array[good].mean()) if good.any() else float("nan")


def inclusion_mask(delta_true: np.ndarray, threshold: float) -> np.ndarray:
    norms = np.linalg.norm(delta_true, axis=0)
    if not np.isfinite(norms).any() or float(np.nanmax(norms)) <= 0:
        return np.zeros(delta_true.shape[1], dtype=bool)
    return norms >= threshold * float(np.nanmax(norms))
