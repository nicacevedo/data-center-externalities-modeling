"""Structural identifiability diagnostics.

These distinguish STRUCTURAL non-identifiability (the design matrix cannot separate the
parameters at all) from PRACTICAL noise-driven difficulty (it can, but not at this
signal-to-noise ratio). Monte Carlo error alone cannot make that distinction, which is why
these are reported alongside it rather than replaced by it.

Operates on design matrices only; no truth is required or accepted.
"""

from __future__ import annotations

import numpy as np

from .models import NodeDesign, split_masks
from .observations import TRAIN


def design_diagnostics(design: NodeDesign, split_label: str = TRAIN) -> dict[str, float]:
    mask = split_masks(design)[split_label]
    X = design.X[mask]
    if X.shape[0] <= X.shape[1] or X.shape[1] == 0:
        return {
            "n_rows": float(X.shape[0]),
            "n_cols": float(X.shape[1]),
            "rank": float("nan"),
            "rank_deficiency": float("nan"),
            "condition_number": float("inf"),
            "smallest_singular_value": float("nan"),
            "max_vif": float("nan"),
            "pumping_excitation_fraction": float("nan"),
        }

    # Center and scale so the condition number reflects collinearity, not units.
    Xc = X - X.mean(axis=0)
    scale = np.where(Xc.std(axis=0, ddof=0) > 1e-12, Xc.std(axis=0, ddof=0), 1.0)
    Xs = Xc / scale

    singular = np.linalg.svd(Xs, compute_uv=False)
    rank = int(np.sum(singular > singular[0] * 1e-10)) if singular.size else 0
    condition = float(singular[0] / singular[-1]) if singular[-1] > 0 else float("inf")

    max_vif = float("nan")
    vifs = []
    for j in range(Xs.shape[1]):
        others = np.delete(Xs, j, axis=1)
        if others.shape[1] == 0:
            continue
        coef, *_ = np.linalg.lstsq(others, Xs[:, j], rcond=None)
        residual = Xs[:, j] - others @ coef
        ss_res = float(residual @ residual)
        ss_tot = float(Xs[:, j] @ Xs[:, j])
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
        vifs.append(1.0 / max(1.0 - r2, 1e-12))
    if vifs:
        max_vif = float(np.max(vifs))

    # Excitation: the share of pumping variance that survives projecting out every other
    # regressor. This is what actually identifies the pumping coefficient.
    excitation = float("nan")
    if "pumping" in design.names:
        j = design.names.index("pumping")
        others = np.delete(Xs, j, axis=1)
        if others.shape[1] > 0:
            coef, *_ = np.linalg.lstsq(others, Xs[:, j], rcond=None)
            residual = Xs[:, j] - others @ coef
            excitation = float((residual @ residual) / max(Xs[:, j] @ Xs[:, j], 1e-12))
        else:
            excitation = 1.0

    return {
        "n_rows": float(X.shape[0]),
        "n_cols": float(X.shape[1]),
        "rank": float(rank),
        "rank_deficiency": float(Xs.shape[1] - rank),
        "condition_number": condition,
        "smallest_singular_value": float(singular[-1]),
        "max_vif": max_vif,
        "pumping_excitation_fraction": excitation,
    }
