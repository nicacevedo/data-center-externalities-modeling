"""Seed-independent and pseudo-true benchmarks for the V3 four-layer decomposition.

Four nested benchmark layers, all evaluated through the *same* frozen persistent-step
NIRE routine (`diagnostics.persistent_nire`) on the same scoring nodes and instants:

    L1  F_intervention_all   minimum planning-relevant NIRE attainable by the actual
                             frozen model-L response family (diagonal own-lag +
                             own-node pumping drive), scored on every materially
                             affected included node.
    L2  F_train_true         NIRE of the pseudo-true one-step L target fitted on the
                             LATENT TRUE variables over the same TRAIN support.
    L3  F_train_obs          NIRE of the pseudo-true one-step L target of the actual
                             observed-data estimator under the frozen observation
                             regime.
    L4  fitted NIRE          finite-sample V3 estimator performance (Pass 2).

These are NESTED BENCHMARK COMPARISONS, not an additive error decomposition. The
frozen NIRE is a mean over nodes of per-node ratios of L2 norms; that algebra does
not license writing L4 as a sum of L1 plus differences.

Two diagnostic companions to L1:

    F_intervention_pumped     the same minimisation scored only on the directly
                              pumped intervention node.
    neighbor_unmodeled_floor  the exact known-truth representational floor induced by
                              the own-pumping-only local structure: model L predicts
                              identically zero response at every non-pumped node, so
                              each such included node contributes exactly 1.0 to the
                              frozen node-averaged NIRE.

`F_train_true` / `F_train_obs` are Monte-Carlo pseudo-true quantities computed from the
disjoint `V3_BENCHMARK` pool only. `F_intervention_*` and `neighbor_unmodeled_floor` are
deterministic given the cell's structural construction, because `dgp.rollout` is linear
and the paired intervention difference therefore cancels forcing, initial state and noise
exactly.

No V3 ANALYSIS seed is read anywhere in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.polynomial import polynomial as P

from . import dgp, interventions, metrics
from .design import rng_for, seed_list
from .diagnostics import (
    inclusion_mask,
    l_family_paired_response,
    neighbor_unmodeled_floor,
    neighbour_flux_share,
    persistent_nire,
)
from .fit import _fit_scaled
from .modes import RNG_NAMED, require_legal
from .observations import TRAIN, _interval_sums, make_observations
from .rng import StreamBank

# The frozen persistent step is applied to node 0 (see interventions.build_intervention_specs).
PUMPED_NODE = 0

BENCHMARK_LAYER_NAMES = (
    "F_intervention_all",
    "F_train_true",
    "F_train_obs",
)

LAYER_SEMANTICS = {
    "F_intervention_all": (
        "Layer 1. Minimum planning-relevant persistent-step NIRE attainable by the actual "
        "frozen model-L response family on the frozen scoring set."
    ),
    "F_train_true": (
        "Layer 2. Intervention NIRE of the pseudo-true one-step L target fitted on the "
        "latent true head/pumping/recharge variables over the same cadence-specific TRAIN "
        "support and the same admissible rows as the observed-data estimator."
    ),
    "F_train_obs": (
        "Layer 3. Intervention NIRE of the pseudo-true one-step L target of the actual "
        "observed-data estimator under the frozen observation regime."
    ),
    "F_intervention_pumped": (
        "Diagnostic companion to Layer 1. Same minimisation scored only on the directly "
        "pumped node: can L represent the DIRECT local response?"
    ),
    "neighbor_unmodeled_floor": (
        "Exact known-truth representational floor induced by the own-pumping-only local "
        "structure. Not a hydraulic-coupling threshold."
    ),
}

GAP_SEMANTICS = {
    "gap_representation_to_train_true": (
        "F_intervention_all -> F_train_true: training-target / functional-approximation "
        "cost of the one-step objective relative to the intervention-optimal member of "
        "the same frozen family. Not pure 'objective mismatch': other unavoidable "
        "functional restrictions of the frozen family remain in force on both sides."
    ),
    "gap_train_true_to_train_obs": (
        "F_train_true -> F_train_obs: asymptotic cost of observation / proxy / forcing-data "
        "corruption under the frozen estimator, holding the admissible-row support and the "
        "confounded forcing distribution common. Does not isolate any single measurement "
        "channel."
    ),
    "gap_train_obs_to_fitted": (
        "F_train_obs -> fitted NIRE: finite-sample estimation cost. Evaluated in Pass 2."
    ),
}


# -------------------------------------------------------------------------------------
# Shared frozen intervention geometry
# -------------------------------------------------------------------------------------


def _true_step_bundle(design, system, trajectory, bundle):
    """Frozen persistent-step scoring geometry: (spec, delta_true, include, dQ, steps, ...)."""
    k = int(bundle.cadence)
    cfg = design["interventions"]
    primary = int(cfg["primary_horizon_fine_steps"])
    horizon_fine = int(cfg["cumulative_drawdown_horizon_fine_steps"])
    inclusion = float(design["metrics"].get("nire_node_inclusion_threshold", 0.01))
    onset_transition = bundle.test_onset()
    onset_fine = trajectory.analysis_start + int(bundle.t_fine[onset_transition])
    available = trajectory.h.shape[0] - onset_fine - 1
    horizon_fine = int(min(horizon_fine, available))
    n_steps = max(1, horizon_fine // k)
    specs = interventions.build_intervention_specs(design, system, trajectory, horizon_fine)
    spec = next(s for s in specs if s.name == "persistent_step")
    delta_true_fine = interventions.true_paired_response(system, trajectory, onset_fine, spec, k)
    delta_true = interventions.sample_true_at_cadence(delta_true_fine, k, n_steps)
    include = inclusion_mask(delta_true, inclusion)
    delta_q_fine = interventions._delta_q_fine(spec, system.n_nodes, k)
    delta_q_interval = np.stack(
        [delta_q_fine[t * k : (t + 1) * k].sum(axis=0) for t in range(n_steps)],
        axis=0,
    )
    steps = int(np.ceil(primary / k))
    return spec, delta_true, include, delta_q_interval, steps, n_steps, k


# -------------------------------------------------------------------------------------
# Layer 1: exact global optimisation over the whole frozen L response family
# -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PumpedProfile:
    """Amplitude-profiled objective for the pumped node, as an explicit rational function.

    For the pumped node the frozen L recursion gives, with own-lag `a` and own-pumping
    amplitude `kappa`,

        out[t] = kappa * g_t(a),      g_t(a) = sum_{s<t} a^{t-1-s} d_s,   g_0 = 0

    where `d_s` is the frozen cadence-aggregated intervention pumping increment. `g_t` is a
    polynomial in `a` of degree `t-1`. Profiling out the amplitude analytically
    (`kappa|a` is a one-dimensional least-squares problem) leaves

        NIRE_pumped(a)^2 = 1 - c(a)^2 / Q(a),
        c(a) = sum_t yhat_t g_t(a),   Q(a) = sum_t g_t(a)^2

    with `yhat` the unit-normalised true pumped-node response. Because `g_1(a) = d_0` is a
    nonzero constant, `Q(a) >= d_0^2 > 0` for every real `a`: the rational function has NO
    POLES on the real line, is continuous on the two-point compactification
    `R u {+-inf}`, and its limit there is exactly `yhat_last^2` (ratio of leading
    coefficients). A global optimum therefore exists and is attained either at a real
    stationary point or in that limit.
    """

    c: np.ndarray                 # ascending coefficients of c(a)
    q: np.ndarray                 # ascending coefficients of Q(a)
    y: np.ndarray                 # true pumped-node response at the scored instants
    d: np.ndarray                 # frozen cadence-aggregated intervention increments
    y_norm: float                 # ||y|| of the true pumped-node response
    y_hat_last: float             # last component of the unit-normalised true response
    n_scored: int                 # number of scored instants (including t=0)

    # -- evaluation ----------------------------------------------------------------

    def _padded(self) -> tuple[np.ndarray, np.ndarray]:
        num = P.polymul(self.c, self.c)
        size = max(num.size, self.q.size)
        num = np.concatenate([num, np.zeros(size - num.size)])
        den = np.concatenate([self.q, np.zeros(size - self.q.size)])
        return num, den

    def ratio(self, a: float) -> float:
        """rho^2(a) = c(a)^2 / Q(a), evaluated without overflow for any finite `a`."""
        a = float(a)
        num, den = self._padded()
        if abs(a) <= 1.0:
            n_val = float(P.polyval(a, num))
            d_val = float(P.polyval(a, den))
        else:
            b = 1.0 / a
            n_val = float(P.polyval(b, num[::-1]))
            d_val = float(P.polyval(b, den[::-1]))
        if not np.isfinite(n_val) or not np.isfinite(d_val) or abs(d_val) <= 0.0:
            return float("nan")
        return n_val / d_val

    def ratio_at_infinity(self) -> float:
        return float(self.y_hat_last * self.y_hat_last)

    def nire(self, a: float) -> float:
        r = self.ratio(a)
        if not np.isfinite(r):
            return float("nan")
        return float(np.sqrt(max(0.0, 1.0 - r)))

    def kappa(self, a: float) -> float:
        """Conditionally optimal own-pumping amplitude at `a`, from the rational form.

        `direct_kappa` is what the reported benchmark uses; this closed form exists for the
        analytic cross-check and for large |a|, where it is evaluated in the reciprocal
        coordinate so no power of `a` overflows.
        """
        a = float(a)
        if abs(a) <= 1.0:
            c_val = float(P.polyval(a, self.c))
            q_val = float(P.polyval(a, self.q))
        else:
            b = 1.0 / a
            # Pad c to Q's degree so the common power of `a` cancels exactly in the ratio.
            c_pad = np.concatenate([self.c, np.zeros(max(0, self.q.size - self.c.size))])
            c_val = float(P.polyval(b, c_pad[::-1]))
            q_val = float(P.polyval(b, self.q[::-1]))
        if not np.isfinite(c_val) or not np.isfinite(q_val) or abs(q_val) <= 0.0:
            return float("nan")
        return float(c_val * self.y_norm / q_val)

    def direct_nire(self, a: float) -> float:
        """Frozen normalized error at `a` with the conditionally optimal amplitude.

        Evaluated by explicitly forming the response and the residual, so there is no
        `sqrt(1 - rho^2)` cancellation. `ratio()` is used to LOCATE the global optimum
        (its rational-function form is what makes the global argument exact); this is used
        to REPORT the value there at full precision. Returns nan where the recursion is
        not finite, so the caller can fall back to the ratio form.
        """
        a = float(a)
        if not np.isfinite(a) or self.n_scored < 2 or self.y_norm <= 1e-15:
            return float("nan")
        g = np.zeros(self.n_scored)
        for t in range(self.n_scored - 1):
            g[t + 1] = a * g[t] + self.d[t]
        if not np.all(np.isfinite(g)):
            return float("nan")
        gg = float(g @ g)
        if gg <= 1e-300:
            return float(np.linalg.norm(self.y) / self.y_norm)
        kappa = float(g @ self.y / gg)
        hat = kappa * g
        if not np.all(np.isfinite(hat)):
            return float("nan")
        return float(metrics.normalized_error(self.y, hat))

    def direct_kappa(self, a: float) -> float:
        a = float(a)
        if not np.isfinite(a) or self.n_scored < 2:
            return float("nan")
        g = np.zeros(self.n_scored)
        for t in range(self.n_scored - 1):
            g[t + 1] = a * g[t] + self.d[t]
        gg = float(g @ g)
        if not np.all(np.isfinite(g)) or gg <= 1e-300:
            return float("nan")
        return float(g @ self.y / gg)

    # -- global optimisation -------------------------------------------------------

    def stationary_points(self) -> np.ndarray:
        """All real stationary points of rho^2 = c^2/Q.

        d/da (c^2/Q) = c * (2 c' Q - c Q') / Q^2, and Q > 0 everywhere, so the stationary
        set is exactly the real root set of the polynomial `c * (2 c' Q - c Q')`. Both
        factors are enumerated by companion-matrix eigenvalues.
        """
        c, q = self.c, self.q
        dc = P.polyder(c) if c.size > 1 else np.zeros(1)
        dq = P.polyder(q) if q.size > 1 else np.zeros(1)
        factors = [c, P.polysub(2.0 * P.polymul(dc, q), P.polymul(c, dq))]
        found: list[float] = []
        for poly in factors:
            poly = P.polytrim(np.asarray(poly, float), tol=0.0)
            if poly.size < 2 or not np.all(np.isfinite(poly)):
                continue
            scale = float(np.max(np.abs(poly)))
            if scale <= 0.0:
                continue
            try:
                roots = P.polyroots(poly / scale)
            except Exception:  # pragma: no cover - numerical failure path
                continue
            for root in np.atleast_1d(roots):
                if not np.isfinite(root):
                    continue
                if abs(np.imag(root)) <= 1e-8 * max(1.0, abs(np.real(root))):
                    found.append(float(np.real(root)))
        return np.asarray(sorted(found), dtype=float)

    def global_max_ratio(self) -> dict[str, Any]:
        """Certified global maximum of rho^2 over R u {+-inf}."""
        from scipy.optimize import minimize_scalar

        candidates: list[tuple[float, float]] = [(0.0, self.ratio(0.0))]
        stat = self.stationary_points()
        for a in stat:
            candidates.append((float(a), self.ratio(float(a))))
            # Deterministic local polish in a tight bracket around each stationary point.
            width = 1e-6 * max(1.0, abs(a))
            try:
                res = minimize_scalar(
                    lambda x: -self.ratio(x),
                    bracket=None,
                    bounds=(a - width, a + width),
                    method="bounded",
                    options={"xatol": 1e-15},
                )
                candidates.append((float(res.x), self.ratio(float(res.x))))
            except Exception:  # pragma: no cover
                pass
        finite = [(a, r) for a, r in candidates if np.isfinite(r)]
        if finite:
            best_a, best_r = max(finite, key=lambda item: item[1])
        else:
            best_a, best_r = float("nan"), float("-inf")
        limit_r = self.ratio_at_infinity()
        attained_at_infinity = bool(limit_r > best_r + 1e-15)
        if attained_at_infinity:
            best_a, best_r = float("inf"), limit_r
        return {
            "argmax_a": float(best_a),
            "max_ratio": float(best_r),
            "limit_ratio_at_infinity": float(limit_r),
            "attained_at_infinity": attained_at_infinity,
            "n_real_stationary_points": int(stat.size),
            "polynomial_degree_c": int(max(0, self.c.size - 1)),
            "polynomial_degree_Q": int(max(0, self.q.size - 1)),
        }

    def compactified_scan(self, n_grid: int = 40001) -> dict[str, Any]:
        """Independent global cross-check on the compactified line u = a/(1+|a|).

        `u -> a = u/(1-|u|)` is a bijection from (-1, 1) onto R; the endpoints `u = +-1`
        carry the analytic limit value. The scan therefore covers the COMPLETE extended
        parameter line, not a finite window.
        """
        from scipy.optimize import minimize_scalar

        u = np.linspace(-1.0, 1.0, int(n_grid))
        best_u, best_r = float("nan"), float("-inf")
        for value in u:
            if abs(value) >= 1.0:
                r = self.ratio_at_infinity()
                a = float(np.sign(value) * np.inf)
            else:
                a = float(value / (1.0 - abs(value)))
                r = self.ratio(a)
            if np.isfinite(r) and r > best_r:
                best_u, best_r = float(value), float(r)
        if np.isfinite(best_u) and abs(best_u) < 1.0:
            step = 2.0 / (int(n_grid) - 1)
            lo, hi = max(-0.999999, best_u - step), min(0.999999, best_u + step)
            try:
                res = minimize_scalar(
                    lambda v: -self.ratio(float(v / (1.0 - abs(v)))),
                    bounds=(lo, hi),
                    method="bounded",
                    options={"xatol": 1e-15},
                )
                r = self.ratio(float(res.x / (1.0 - abs(float(res.x)))))
                if np.isfinite(r) and r > best_r:
                    best_u, best_r = float(res.x), float(r)
            except Exception:  # pragma: no cover
                pass
        a_best = (
            float(best_u / (1.0 - abs(best_u)))
            if np.isfinite(best_u) and abs(best_u) < 1.0
            else float("inf")
        )
        return {"argmax_a": a_best, "max_ratio": float(best_r), "n_grid": int(n_grid)}


def build_pumped_profile(
    delta_true: np.ndarray,
    delta_q_interval: np.ndarray,
    steps: int,
    pumped: int = PUMPED_NODE,
) -> PumpedProfile:
    """Assemble the exact amplitude-profiled objective for the pumped node."""
    n_scored = int(min(steps + 1, delta_true.shape[0], delta_q_interval.shape[0] + 1))
    y = np.asarray(delta_true[:n_scored, pumped], float)
    d = np.asarray(delta_q_interval[: max(n_scored - 1, 0), pumped], float)
    y_norm = float(np.linalg.norm(y))
    if n_scored < 2 or y_norm <= 1e-15 or not np.all(np.isfinite(y)) or not np.all(np.isfinite(d)):
        return PumpedProfile(
            c=np.zeros(1),
            q=np.ones(1),
            y=y,
            d=d,
            y_norm=y_norm,
            y_hat_last=0.0,
            n_scored=n_scored,
        )
    y_hat = y / y_norm
    # g_t(a) = sum_{j=0}^{t-1} d_{t-1-j} a^j, for t = 1 .. n_scored-1.
    c = np.zeros(max(n_scored - 1, 1))
    q = np.zeros(max(2 * (n_scored - 2) + 1, 1))
    for t in range(1, n_scored):
        g = d[:t][::-1].copy()                      # ascending coefficients of g_t
        c = P.polyadd(c, y_hat[t] * g)
        q = P.polyadd(q, P.polymul(g, g))
    return PumpedProfile(
        c=np.asarray(c, float),
        q=np.asarray(q, float),
        y=y,
        d=d,
        y_norm=y_norm,
        y_hat_last=float(y_hat[n_scored - 1]),
        n_scored=n_scored,
    )


def f_intervention_for_system(design, system, trajectory, bundle) -> dict[str, Any]:
    """Layer-1 benchmarks plus the pumped-node and neighbour-floor companions.

    `F_intervention_all` is the planning-relevant metric: the frozen NIRE scoring set (all
    materially affected included nodes, all frozen scoring instants). `F_intervention_pumped`
    is the same minimisation restricted to the directly pumped node. `neighbor_unmodeled_floor`
    is the exact contribution of the structurally-zero prediction at non-pumped included
    nodes. Under the frozen node-averaged NIRE these satisfy, exactly,

        F_intervention_all = neighbor_unmodeled_floor
                             + (F_intervention_pumped / n_included)   if node 0 is included

    so `F_intervention_all >= neighbor_unmodeled_floor` always.
    """
    _, delta_true, include, dQ, steps, _n_steps, _k = _true_step_bundle(
        design, system, trajectory, bundle
    )
    n = system.n_nodes
    pumped = PUMPED_NODE

    profile = build_pumped_profile(delta_true, dQ, steps, pumped)
    exact = profile.global_max_ratio()
    scan = profile.compactified_scan()

    # The exact rational analysis LOCATES the global optimum over the whole extended
    # parameter line; the direct residual form REPORTS its value at that location without
    # the `sqrt(1 - rho^2)` cancellation, whose absolute resolution near zero is only
    # sqrt(machine eps) ~ 1.5e-8.
    ratio_pumped = float(np.sqrt(max(0.0, 1.0 - exact["max_ratio"])))
    ratio_pumped_scan = float(np.sqrt(max(0.0, 1.0 - scan["max_ratio"])))
    cross_check = abs(ratio_pumped - ratio_pumped_scan)

    candidates = [exact["argmax_a"], scan["argmax_a"]]
    candidates.extend(float(a) for a in profile.stationary_points())
    best_a, f_pumped = float("nan"), float("inf")
    for candidate in candidates:
        value = profile.direct_nire(candidate)
        if np.isfinite(value) and value < f_pumped:
            best_a, f_pumped = float(candidate), float(value)
    if not np.isfinite(f_pumped):
        best_a, f_pumped = float(exact["argmax_a"]), ratio_pumped

    # Global-validity flag: the rational profile has no real poles (Q >= d_0^2 > 0), is
    # continuous on R u {+-inf} with an explicit limit, all stationary points are
    # enumerated, and an independent full-extended-line compactified scan agrees.
    ratio_tol = 1e-6 + 1e-6 * max(1.0, ratio_pumped)
    global_certified = bool(
        np.isfinite(f_pumped)
        and np.isfinite(ratio_pumped)
        and np.isfinite(ratio_pumped_scan)
        and cross_check <= ratio_tol
        and abs(f_pumped - ratio_pumped) <= ratio_tol
        and not exact["attained_at_infinity"]
    )

    # Realised all-node NIRE at the certified optimum, through the frozen routine.
    if np.isfinite(best_a):
        best_kappa = profile.direct_kappa(best_a)
    else:
        best_kappa = float("nan")
    if np.isfinite(best_a) and np.isfinite(best_kappa):
        a_diag = np.zeros(n)
        a_diag[pumped] = best_a
        beta = np.zeros(n)
        beta[pumped] = best_kappa
        hat = l_family_paired_response(a_diag, beta, dQ)
        f_all_realised = persistent_nire(delta_true, hat, include, steps)
    else:
        f_all_realised = float("nan")

    floor = neighbor_unmodeled_floor(delta_true, include, steps, pumped)
    n_incl = int(np.sum(include))
    include_pumped = bool(include[pumped]) if include.size > pumped else False
    n_incl_nonpumped = int(n_incl - (1 if include_pumped else 0))

    # Closed-form all-node value implied by the frozen node-averaged NIRE algebra.
    if n_incl > 0:
        f_all_closed = (
            (f_pumped + n_incl_nonpumped) / n_incl if include_pumped else float(n_incl_nonpumped) / n_incl
        )
    else:
        f_all_closed = float("nan")
    identity_residual = (
        abs(f_all_realised - f_all_closed)
        if np.isfinite(f_all_realised) and np.isfinite(f_all_closed)
        else float("nan")
    )

    # Secondary descriptive reading of the floor as a global-norm share.
    n_scored = int(min(steps + 1, delta_true.shape[0]))
    scored = delta_true[:n_scored][:, np.flatnonzero(include)] if n_incl else np.zeros((n_scored, 0))
    nonpumped_cols = [i for i in np.flatnonzero(include) if i != pumped]
    num = float(np.linalg.norm(delta_true[:n_scored][:, nonpumped_cols])) if nonpumped_cols else 0.0
    den = float(np.linalg.norm(scored)) if scored.size else 0.0
    norm_share = num / den if den > 1e-15 else float("nan")

    neighbor_true = {
        i: float(np.linalg.norm(delta_true[:, i])) for i in range(n) if i != pumped
    }
    return {
        "F_intervention_all": float(f_all_closed),
        "F_intervention_all_realised_through_frozen_nire": float(f_all_realised),
        "F_intervention_all_identity_residual": float(identity_residual),
        "F_intervention_pumped": float(f_pumped),
        "neighbor_unmodeled_floor": float(floor),
        "neighbor_unmodeled_floor_norm_share_secondary": float(norm_share),
        "F_intervention_floor_gap": (
            float(f_all_closed - floor)
            if np.isfinite(f_all_closed) and np.isfinite(floor)
            else float("nan")
        ),
        "F_intervention_a0": float(best_a),
        "F_intervention_kappa0": float(best_kappa),
        "F_intervention_global_certified": global_certified,
        "F_intervention_domain": (
            "extended_real_line_a_in_R_union_pm_inf__kappa_in_R"
            if global_certified
            else "verified_domain_compactified_grid_only"
        ),
        "F_intervention_verification_strategy": (
            "exact rational-profile stationary-point enumeration (companion-matrix roots of "
            "c*(2c'Q - cQ')) plus explicit limit at |a|->inf, cross-checked against an "
            "independent compactified dense scan over u = a/(1+|a|) on [-1, 1]"
        ),
        "F_intervention_cross_check_abs_delta": float(cross_check),
        "F_intervention_ratio_form_pumped": float(ratio_pumped),
        "F_intervention_scan_ratio_form_pumped": float(ratio_pumped_scan),
        "F_intervention_attained_at_infinity": bool(exact["attained_at_infinity"]),
        "F_intervention_n_real_stationary_points": int(exact["n_real_stationary_points"]),
        "F_intervention_profile_degree_c": int(exact["polynomial_degree_c"]),
        "F_intervention_profile_degree_Q": int(exact["polynomial_degree_Q"]),
        "F_intervention_limit_ratio_at_infinity": float(exact["limit_ratio_at_infinity"]),
        "neighbor_true_response_norm_max": (
            max(neighbor_true.values()) if neighbor_true else 0.0
        ),
        "n_included_nodes": n_incl,
        "n_included_nonpumped_nodes": n_incl_nonpumped,
        "include_node0": include_pumped,
        "n_scored_instants": n_scored,
    }


# -------------------------------------------------------------------------------------
# Layers 2 and 3: latent-true and observed-data pseudo-true one-step targets
# -------------------------------------------------------------------------------------


def latent_true_columns(trajectory, bundle) -> dict[str, Any]:
    """Latent-true counterparts of the frozen L design columns.

    Uses the exact frozen cadence transformation of `make_observations`: heads sampled at
    the same observation instants and forcing summed over the same `[t, t+k)` intervals.
    No measurement noise, no missingness, no recharge lag, no recharge noise, no
    multiplicative pumping error.
    """
    k = int(bundle.cadence)
    start = int(trajectory.analysis_start)
    horizon = int(trajectory.analysis_length)
    offsets = np.arange(0, horizon, k)
    starts = offsets[:-1]
    h_window = trajectory.h[start : start + horizon]
    y_clean = h_window[offsets]
    q_true = _interval_sums(trajectory.Q_true[start : start + horizon], starts, k)
    r_true = _interval_sums(trajectory.R_true[start : start + horizon], starts, k)
    p_true = (
        _interval_sums(trajectory.Q_placebo[start : start + horizon], starts, k)
        if trajectory.Q_placebo is not None
        else None
    )
    return {
        "y_clean": y_clean,
        "pumping": q_true,
        "recharge_proxy": r_true,
        "placebo": p_true,
    }


def true_l_design_block(obs_design, columns, bundle, node: int):
    """Latent-true (X, y) on the SAME admissible rows and column order as `obs_design`.

    Holding the admissible-row support common between the true-variable and observed-variable
    targets is deliberate: it keeps `F_train_true -> F_train_obs` a statement about VALUE
    corruption (measurement / proxy / lag / forcing) rather than about row attrition.
    """
    names = tuple(obs_design.names)
    rows = np.asarray(obs_design.rows, int)
    y_clean = columns["y_clean"]
    built: list[np.ndarray] = []
    for name in names:
        if name == "own_level":
            built.append(y_clean[:-1, node])
        elif name == "season_sin":
            built.append(np.asarray(bundle.season_sin, float))
        elif name == "season_cos":
            built.append(np.asarray(bundle.season_cos, float))
        elif name == "time_trend":
            built.append(np.asarray(bundle.time_trend, float))
        elif name == "pumping":
            built.append(columns["pumping"][:, node])
        elif name == "recharge_proxy":
            built.append(columns["recharge_proxy"][:, node])
        elif name == "placebo":
            if columns["placebo"] is None:
                raise ValueError("observed L design has a placebo column but truth has none")
            built.append(columns["placebo"][:, node])
        else:
            raise ValueError(f"no latent-true counterpart for L design column {name!r}")
    X = np.column_stack(built)[rows]
    y = np.asarray(y_clean[1:, node], float)[rows]
    return X, y, names


def _pooled_ols(blocks: list[tuple[np.ndarray, np.ndarray]], names: tuple[str, ...]):
    """Pool rows across Monte-Carlo draws and fit the same unpenalized OLS model L uses."""
    X = np.concatenate([b[0] for b in blocks], axis=0)
    y = np.concatenate([b[1] for b in blocks], axis=0)
    intercept, coef, _diag = _fit_scaled(X, y, np.zeros(X.shape[1], dtype=bool), 0.0)
    return intercept, coef, names, int(X.shape[0])


def _coef_named(coef: np.ndarray, names: tuple[str, ...], key: str, default: float = 0.0) -> float:
    names_list = list(names)
    if key not in names_list:
        return default
    return float(coef[names_list.index(key)])


def benchmark_prefixes(design: dict[str, Any]) -> tuple[int, ...]:
    spec = design["seeds"]["pools"]["V3_BENCHMARK"]
    prefixes = spec.get("convergence_prefixes") or [int(spec["n_seeds"])]
    n = int(spec["n_seeds"])
    return tuple(int(m) for m in prefixes if 0 < int(m) <= n)


def pseudo_true_targets(
    design: dict[str, Any],
    regime,
    rng_mode: str,
    system_seed_mode: str,
) -> dict[str, Any]:
    """Monte-Carlo pseudo-true one-step L targets on latent-true and observed variables.

    Returns `F_train_true`, `F_train_obs`, their pseudo-true coefficients, and nested-prefix
    convergence diagnostics at the preregistered prefixes. Uses only the `V3_BENCHMARK` pool,
    whose `SeedSequence(entropy).spawn(n)` construction makes the prefixes strictly nested.
    """
    require_legal(rng_mode, system_seed_mode)
    seeds = seed_list(design, "V3_BENCHMARK")
    prefixes = benchmark_prefixes(design)
    from .evaluation import scenario_options
    from .models import build_design

    options = scenario_options(design, regime)

    obs_blocks: dict[int, list[tuple[np.ndarray, np.ndarray]]] = {}
    true_blocks: dict[int, list[tuple[np.ndarray, np.ndarray]]] = {}
    node_names: dict[int, tuple[str, ...]] = {}
    last = None

    for seed in seeds:
        rng = rng_for(int(seed))
        streams = StreamBank(int(seed)) if rng_mode == RNG_NAMED else None
        system = dgp.build_system(
            design,
            topology=regime.topology,
            memory=regime.memory,
            gamma_label=regime.gamma,
            recharge_efficiency=float(options.get("recharge_efficiency", 1.0)),
            system_seed_mode=system_seed_mode,
        )
        if options.get("null_mode") == "matched_local_dynamics":
            system = dgp.as_matched_local_dynamics_null(system)
        traj = dgp.simulate(design, system, regime, rng, options, streams=streams)
        bundle = make_observations(design, system, traj, regime, rng, streams=streams)
        columns = latent_true_columns(traj, bundle)
        for node in np.flatnonzero(bundle.observed_nodes):
            node = int(node)
            d = build_design(bundle, node, "L")
            train = d.split == TRAIN
            if int(np.sum(train)) < d.X.shape[1] + 2:
                continue
            X_true, y_true, names = true_l_design_block(d, columns, bundle, node)
            obs_blocks.setdefault(node, []).append((d.X[train], d.y[train]))
            true_blocks.setdefault(node, []).append((X_true[train], y_true[train]))
            node_names[node] = names
        last = (system, traj, bundle)

    if last is None or not obs_blocks:
        empty = {
            "F_train_true": float("nan"),
            "F_train_obs": float("nan"),
            "F_train_n_mc": 0,
            "F_train_convergence": [],
        }
        return empty

    system, traj, bundle = last
    _, delta_true, include, dQ, steps, _n_steps, _k = _true_step_bundle(
        design, system, traj, bundle
    )

    def _fit_prefix(blocks: dict[int, list], m: int) -> dict[str, Any]:
        a_diag = np.zeros(system.n_nodes)
        beta_q = np.zeros(system.n_nodes)
        beta_r = np.full(system.n_nodes, np.nan)
        rows_used = 0
        n_draws_used = 0
        for node, items in blocks.items():
            subset = items[:m]
            if not subset:
                continue
            n_draws_used = max(n_draws_used, len(subset))
            intercept, coef, names, n_rows = _pooled_ols(subset, node_names[node])
            rows_used += n_rows
            a_diag[node] = _coef_named(coef, names, "own_level", 0.0)
            beta_q[node] = _coef_named(coef, names, "pumping", 0.0)
            beta_r[node] = _coef_named(coef, names, "recharge_proxy", float("nan"))
        hat = l_family_paired_response(a_diag, beta_q, dQ)
        nire = persistent_nire(delta_true, hat, include, steps)
        return {
            "n_mc": int(n_draws_used),
            "nire": float(nire),
            "a_pumped": float(a_diag[PUMPED_NODE]),
            "beta_q_pumped": float(beta_q[PUMPED_NODE]),
            "beta_recharge_pumped": float(beta_r[PUMPED_NODE]),
            "a_mean_over_nodes": float(np.mean(a_diag)),
            "beta_q_mean_over_nodes": float(np.mean(beta_q)),
            "pooled_train_rows": int(rows_used),
        }

    convergence: list[dict[str, Any]] = []
    for m in prefixes:
        row = {"prefix_n": int(m)}
        for label, blocks in (("true", true_blocks), ("obs", obs_blocks)):
            fitted = _fit_prefix(blocks, m)
            row[f"F_train_{label}_nire"] = fitted["nire"]
            row[f"F_train_{label}_a_pumped"] = fitted["a_pumped"]
            row[f"F_train_{label}_beta_q_pumped"] = fitted["beta_q_pumped"]
            row[f"F_train_{label}_beta_recharge_pumped"] = fitted["beta_recharge_pumped"]
            row[f"F_train_{label}_a_mean"] = fitted["a_mean_over_nodes"]
            row[f"F_train_{label}_beta_q_mean"] = fitted["beta_q_mean_over_nodes"]
            row[f"F_train_{label}_pooled_train_rows"] = fitted["pooled_train_rows"]
            row[f"F_train_{label}_n_mc"] = fitted["n_mc"]
        convergence.append(row)

    deltas: dict[str, float] = {}
    tracked = (
        "F_train_true_nire",
        "F_train_obs_nire",
        "F_train_true_a_pumped",
        "F_train_obs_a_pumped",
        "F_train_true_beta_q_pumped",
        "F_train_obs_beta_q_pumped",
        "F_train_true_beta_recharge_pumped",
        "F_train_obs_beta_recharge_pumped",
    )
    for lo, hi in zip(convergence[:-1], convergence[1:]):
        tag = f"{lo['prefix_n']}_to_{hi['prefix_n']}"
        for key in tracked:
            deltas[f"delta_{key}_{tag}"] = float(hi[key] - lo[key])

    final = convergence[-1]
    out: dict[str, Any] = {
        "F_train_true": final["F_train_true_nire"],
        "F_train_obs": final["F_train_obs_nire"],
        "F_train_true_a_pumped": final["F_train_true_a_pumped"],
        "F_train_obs_a_pumped": final["F_train_obs_a_pumped"],
        "F_train_true_beta_q_pumped": final["F_train_true_beta_q_pumped"],
        "F_train_obs_beta_q_pumped": final["F_train_obs_beta_q_pumped"],
        "F_train_true_beta_recharge_pumped": final["F_train_true_beta_recharge_pumped"],
        "F_train_obs_beta_recharge_pumped": final["F_train_obs_beta_recharge_pumped"],
        "F_train_true_pooled_train_rows": final["F_train_true_pooled_train_rows"],
        "F_train_obs_pooled_train_rows": final["F_train_obs_pooled_train_rows"],
        "F_train_n_mc": int(len(seeds)),
        "F_train_prefixes": list(prefixes),
        "F_train_kind": "monte_carlo_pooled_train_ols_nested_prefix",
        "F_train_pool": "V3_BENCHMARK",
        "F_train_convergence": convergence,
        "F_train_max_abs_delta_last_step": float(
            max(
                (
                    abs(deltas.get(f"delta_{key}_{prefixes[-2]}_to_{prefixes[-1]}", 0.0))
                    for key in ("F_train_true_nire", "F_train_obs_nire")
                ),
                default=float("nan"),
            )
        )
        if len(prefixes) >= 2
        else float("nan"),
    }
    out.update(deltas)
    return out


# -------------------------------------------------------------------------------------
# Structural diagnostics
# -------------------------------------------------------------------------------------


def cell_structural_diagnostics(design, regime, system, trajectory) -> dict[str, Any]:
    A = np.asarray(system.A, float)
    return {
        "neighbour_flux_share": neighbour_flux_share(system, trajectory),
        "tau_relax": float(system.tau_relax_realized),
        "spectral_radius": float(system.rho_A),
        "mean_diagonal_transition": float(np.mean(np.diag(A))),
        "gamma_label": regime.gamma,
        "kind_neighbour_flux_share": "synthetic_dimensionless_coupling_materiality",
    }
