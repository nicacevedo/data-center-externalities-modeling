"""Design-matrix construction for the B0 / L / S / N estimator ladder.

Every function here accepts an `ObservationBundle` and nothing else. No truth object may
reach this module; `test_no_truth_leakage_signatures` and the runtime tripwire enforce it.

Network parameterization, stated once because the algebra matters downstream:

    y_{i,tau+1} = c + a_i * y_{i,tau}
                    + sum_{j in cand(i)} kappa_ij * (y_{j,tau} - y_{i,tau})
                    + beta_Q * Q_i + beta_R * R_i + harmonics

so a_i = 1 - kappa_i0 is the leakage-only own-level coefficient, and the implied transition
matrix is  A_ii = a_i - sum_j kappa_ij,  A_ij = kappa_ij.  Assembling A_hat naively from a_i
alone would be wrong.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .observations import ObservationBundle, TEST, TRAIN, VALIDATION

MODEL_RUNGS = ("B0", "L", "S", "N")
BASE_FEATURES = ("own_level", "season_sin", "season_cos", "time_trend")


@dataclass(frozen=True)
class NodeDesign:
    node: int
    model: str
    X: np.ndarray                # (rows, p) unscaled, no intercept column
    y: np.ndarray                # (rows,)
    names: tuple[str, ...]
    rows: np.ndarray             # transition indices retained
    split: np.ndarray            # (rows,) split label per retained row
    penalized: np.ndarray        # (p,) bool -- the nonnegative kappa block
    kappa_neighbors: tuple[int, ...]
    bandwidth: float | None


def _kernel_weights(bundle: ObservationBundle, node: int, bandwidth: float) -> np.ndarray:
    weights = np.exp(-bundle.distances[node] / bandwidth)
    weights[node] = 0.0
    weights[~bundle.observed_nodes] = 0.0
    return weights


def build_design(
    bundle: ObservationBundle,
    node: int,
    model: str,
    bandwidth: float | None = None,
) -> NodeDesign:
    """Build one node's design matrix for one rung.

    Row admissibility follows the frozen rule: a transition is usable only if every head it
    needs is actually observed. No head is interpolated to rescue a row.
    """
    if model not in MODEL_RUNGS:
        raise ValueError(f"unknown model rung {model}")

    n_tr = bundle.n_transitions
    y_prev = bundle.y[:-1, node]
    y_next = bundle.y[1:, node]

    columns: list[np.ndarray] = [y_prev, bundle.season_sin, bundle.season_cos, bundle.time_trend]
    names: list[str] = list(BASE_FEATURES)
    penalized: list[bool] = [False] * len(names)
    neighbors: tuple[int, ...] = ()

    if model in ("L", "S", "N"):
        columns.append(bundle.Q_obs[:, node])
        names.append("pumping")
        penalized.append(False)
        columns.append(bundle.R_proxy[:, node])
        names.append("recharge_proxy")
        penalized.append(False)

    if model == "S":
        if bandwidth is None:
            raise ValueError("model S requires a bandwidth")
        weights = _kernel_weights(bundle, node, bandwidth)
        columns.append(bundle.Q_obs @ weights)
        names.append("neighbour_pumping")
        penalized.append(False)
        columns.append(bundle.R_proxy @ weights)
        names.append("neighbour_recharge")
        penalized.append(False)

    if model == "N":
        neighbors = tuple(j for j in bundle.candidate_neighbors.get(node, []) if bundle.observed_nodes[j])
        for j in neighbors:
            columns.append(bundle.y[:-1, j] - y_prev)
            names.append(f"kappa_{j}")
            penalized.append(True)

    X = np.column_stack(columns) if columns else np.zeros((n_tr, 0))
    finite = np.isfinite(X).all(axis=1) & np.isfinite(y_next)
    rows = np.flatnonzero(finite)

    return NodeDesign(
        node=node,
        model=model,
        X=X[rows],
        y=y_next[rows],
        names=tuple(names),
        rows=rows,
        split=bundle.split[rows],
        penalized=np.asarray(penalized, dtype=bool),
        kappa_neighbors=neighbors,
        bandwidth=bandwidth,
    )


def split_masks(design: NodeDesign) -> dict[str, np.ndarray]:
    return {
        TRAIN: design.split == TRAIN,
        VALIDATION: design.split == VALIDATION,
        TEST: design.split == TEST,
    }
