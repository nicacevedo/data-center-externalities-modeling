"""Metric definitions.

Predictive metrics are SECONDARY. The primary metrics are intervention recovery,
vulnerability ranking, and network/falsification behaviour.

Cadence rule, applied throughout: direct fine-parameter recovery is primary only at k = 1.
At k > 1 the estimated transition matrix is compared to A^k and labelled state-transition
recovery, and any coarse forcing coefficient reported is the PSEUDO-TRUE projection defined
in DESIGN_FREEZE.md section 2.7, never "the" coarse parameter.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import spearmanr


def rmse(actual: np.ndarray, predicted: np.ndarray) -> float:
    diff = np.asarray(actual, float) - np.asarray(predicted, float)
    diff = diff[np.isfinite(diff)]
    return float(np.sqrt(np.mean(diff**2))) if diff.size else float("nan")


def mae(actual: np.ndarray, predicted: np.ndarray) -> float:
    diff = np.asarray(actual, float) - np.asarray(predicted, float)
    diff = diff[np.isfinite(diff)]
    return float(np.mean(np.abs(diff))) if diff.size else float("nan")


def normalized_error(truth: np.ndarray, estimate: np.ndarray) -> float:
    """||estimate - truth|| / ||truth||, the normalized intervention-response error."""
    truth = np.asarray(truth, float).ravel()
    estimate = np.asarray(estimate, float).ravel()
    n = min(truth.size, estimate.size)
    truth, estimate = truth[:n], estimate[:n]
    good = np.isfinite(truth) & np.isfinite(estimate)
    if not good.any():
        return float("nan")
    denominator = float(np.linalg.norm(truth[good]))
    if denominator <= 1e-15:
        return float("nan")
    return float(np.linalg.norm(estimate[good] - truth[good]) / denominator)


def relative_shape_error(truth: np.ndarray, estimate: np.ndarray) -> float:
    """Scale-invariant counterpart of `normalized_error`.

    Each response curve is normalized by its own L2 norm before comparison, so an unknown
    multiplicative pumping scale cannot affect the result. This is the RELATIVE recovery
    metric; it must never be reported as ABSOLUTE intervention recovery.
    """
    truth = np.asarray(truth, float).ravel()
    estimate = np.asarray(estimate, float).ravel()
    n = min(truth.size, estimate.size)
    truth, estimate = truth[:n], estimate[:n]
    good = np.isfinite(truth) & np.isfinite(estimate)
    if not good.any():
        return float("nan")
    tn = np.linalg.norm(truth[good])
    en = np.linalg.norm(estimate[good])
    if tn <= 1e-15 or en <= 1e-15:
        return float("nan")
    return float(np.linalg.norm(estimate[good] / en - truth[good] / tn))


def cumulative_drawdown(delta_h: np.ndarray) -> float:
    values = np.asarray(delta_h, float)
    values = values[np.isfinite(values)]
    return float(np.sum(values))


def normalized_forecast_error(truth: np.ndarray, predicted: np.ndarray) -> float:
    """Recursive-forecast error normalized by the sd of the truth over the horizon."""
    truth = np.asarray(truth, float).ravel()
    predicted = np.asarray(predicted, float).ravel()
    n = min(truth.size, predicted.size)
    truth, predicted = truth[:n], predicted[:n]
    good = np.isfinite(truth) & np.isfinite(predicted)
    if good.sum() < 2:
        return float("nan")
    denominator = float(np.std(truth[good]))
    if denominator <= 1e-12:
        return float("nan")
    return float(np.sqrt(np.mean((predicted[good] - truth[good]) ** 2)) / denominator)


# -------------------------------------------------------------------------------------
# Vulnerability ranking
# -------------------------------------------------------------------------------------


def vulnerability_ranking(true_response: np.ndarray, est_response: np.ndarray, k: int = 2) -> dict:
    """Rank nodes by adverse response to additional pumping (most negative = most vulnerable)."""
    true_response = np.asarray(true_response, float)
    est_response = np.asarray(est_response, float)
    good = np.isfinite(true_response) & np.isfinite(est_response)
    if good.sum() < 3:
        return {"spearman": float("nan"), "topk_overlap": float("nan")}

    rho, _ = spearmanr(true_response[good], est_response[good])
    order_true = np.argsort(true_response[good])
    order_est = np.argsort(est_response[good])
    kk = min(k, good.sum())
    overlap = len(set(order_true[:kk].tolist()) & set(order_est[:kk].tolist())) / kk
    return {"spearman": float(rho), "topk_overlap": float(overlap)}


# -------------------------------------------------------------------------------------
# Network recovery
# -------------------------------------------------------------------------------------


def strong_true_edges(A_true_k: np.ndarray, threshold: float) -> set[tuple[int, int]]:
    """Undirected true strong edges at the OBSERVATION cadence, from A^k."""
    n = A_true_k.shape[0]
    edges = set()
    for i in range(n):
        for j in range(i + 1, n):
            if max(A_true_k[i, j], A_true_k[j, i]) >= threshold:
                edges.add((i, j))
    return edges


def detected_edges(kappa_hat: np.ndarray, threshold: float) -> set[tuple[int, int]]:
    n = kappa_hat.shape[0]
    edges = set()
    for i in range(n):
        for j in range(i + 1, n):
            a = kappa_hat[i, j] if np.isfinite(kappa_hat[i, j]) else 0.0
            b = kappa_hat[j, i] if np.isfinite(kappa_hat[j, i]) else 0.0
            if max(a, b) >= threshold:
                edges.add((i, j))
    return edges


def edge_metrics(
    true_edges: set[tuple[int, int]],
    predicted_edges: set[tuple[int, int]],
    all_pairs: set[tuple[int, int]],
) -> dict[str, float]:
    """Undirected edge recovery.

    True strong edges lying OUTSIDE the candidate set are still counted, as false negatives:
    an unavailable connection is a missed connection, not an excused one.
    """
    tp = len(true_edges & predicted_edges)
    fp = len(predicted_edges - true_edges)
    fn = len(true_edges - predicted_edges)
    negatives = all_pairs - true_edges
    tn = len(negatives - predicted_edges)

    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    if np.isfinite(precision) and np.isfinite(recall) and (precision + recall) > 0:
        f1 = 2 * precision * recall / (precision + recall)
    elif not true_edges and not predicted_edges:
        f1 = float("nan")          # undefined for the null case; use false_edge_count there
    else:
        f1 = 0.0
    return {
        "edge_true_positive": float(tp),
        "edge_false_positive": float(fp),
        "edge_false_negative": float(fn),
        "edge_precision": float(precision),
        "edge_recall": float(recall),
        "edge_f1": float(f1),
        "edge_false_positive_rate": float(fp / (fp + tn)) if (fp + tn) else float("nan"),
        "edge_false_negative_rate": float(fn / (fn + tp)) if (fn + tp) else float("nan"),
    }


def d_phys(
    kappa_hat: np.ndarray,
    S_hat: np.ndarray,
    pairs: set[tuple[int, int]],
    strong_threshold: float,
    epsilon_stab: float,
    absolute_S_identifiable: bool,
) -> dict[str, float]:
    """Bounded symmetric physics-consistency discrepancy.

    D_phys_ij = |k_ij S_i - k_ji S_j| / (|k_ij S_i| + |k_ji S_j| + eps)  in [0, 1].

    The raw ratio (k_ij S_i)/(k_ji S_j) is deliberately NOT used: it is unstable near zero.
    Reported only where absolute S is identifiable AND both directional estimates are
    nondegenerate; otherwise null, never a number.
    """
    if not absolute_S_identifiable:
        return {"d_phys_median": float("nan"), "d_phys_n_pairs": 0.0}

    values = []
    for i, j in pairs:
        kij = kappa_hat[i, j]
        kji = kappa_hat[j, i]
        if not (np.isfinite(kij) and np.isfinite(kji)):
            continue
        if kij < strong_threshold or kji < strong_threshold:
            continue
        si, sj = S_hat[i], S_hat[j]
        if not (np.isfinite(si) and np.isfinite(sj) and si > 0 and sj > 0):
            continue
        a, b = kij * si, kji * sj
        values.append(abs(a - b) / (abs(a) + abs(b) + epsilon_stab))

    if not values:
        return {"d_phys_median": float("nan"), "d_phys_n_pairs": 0.0}
    return {"d_phys_median": float(np.median(values)), "d_phys_n_pairs": float(len(values))}


# -------------------------------------------------------------------------------------
# Pseudo-true coarse coefficient
# -------------------------------------------------------------------------------------


def pseudo_true_coarse_B(
    A: np.ndarray,
    B_diag: np.ndarray,
    cadence: int,
    forcing_sampler,
    n_draws: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """B_k_pseudo := argmin_B E || sum_r A^{k-1-r} B u_{t+r} - B_k U ||^2.

    The population L2 projection of the exact coarse forcing response onto the
    aggregate-forcing linear family, under the frozen forcing process. Depends on that
    forcing process, is computed here in the evaluation layer from truth, and is always
    labelled pseudo-true.
    """
    n = A.shape[0]
    powers = [np.linalg.matrix_power(A, cadence - 1 - r) for r in range(cadence)]

    targets = []
    aggregates = []
    for _ in range(n_draws):
        u = forcing_sampler(rng, cadence, n)               # (k, n)
        exact = sum(powers[r] @ (B_diag * u[r]) for r in range(cadence))
        targets.append(exact)
        aggregates.append(u.sum(axis=0))

    Y = np.asarray(targets)          # (draws, n)
    U = np.asarray(aggregates)       # (draws, n)

    # Solve per output node: Y[:, i] ~ U @ row_i
    B_pseudo = np.zeros((n, n))
    for i in range(n):
        coef, *_ = np.linalg.lstsq(U, Y[:, i], rcond=None)
        B_pseudo[i] = coef
    return B_pseudo
