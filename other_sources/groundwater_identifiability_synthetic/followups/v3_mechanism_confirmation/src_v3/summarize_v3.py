"""V3 summarizer: continuous reporting, no gates, pointwise intervals, all five blocks.

This module is the FROZEN Pass-2 analysis summarizer. It must be able to produce every
preregistered V3 output from a replicate table without any post-result code edit:

    Block A   pumping attenuation (sigma ladder, Tier-1)
    Block A'  cadence anchor (k=1, Tier-1)
    Block B   coupling profile across gamma (Tier-3)
    Block C   identification-regime x gamma bundle (Tier-3)
    Block D   placebo 2x2x2 factorial (Tier-1 within factor)

    benchmark layers   F_intervention_all, F_intervention_pumped,
                       neighbor_unmodeled_floor, F_train_true, F_train_obs
    benchmark convergence  nested-prefix 16/32/64/128 diagnostics
    paired contrasts       per-seed differences, medians, means, bootstrap intervals,
                           improvement fractions, sigma_d and paired correlation
    pointwise intervals    percentile bootstrap over seeds; Wilson for rates
    estimability           first-class, never dropped
    prediction-vs-intervention diagnostics

Reported 95% bootstrap and Wilson intervals are pointwise Monte Carlo uncertainty
intervals for their individual estimands. They are not simultaneous family-wise
confidence bands over all V3 contrasts.

No p-values. No significance declarations. No SESOI-derived pass/fail/gate/support field.
No V2 status is recomputed, overridden or reinterpreted here: V2's
`LOCAL_RESPONSE_STATUS = LOCAL_RESPONSE_NOT_IDENTIFIED` and
`NETWORK_SUPPORT_FINAL = NOT_EARNED` remain authoritative under every V3 outcome.
"""

from __future__ import annotations

import hashlib
from typing import Any, Iterable, Sequence

import numpy as np

from .diagnostics import RECOMBINATION_SEMANTICS
from .records import parse_record, parse_seed

INTERVAL_SEMANTICS = (
    "Reported 95% bootstrap and Wilson intervals are pointwise Monte Carlo "
    "uncertainty intervals for their individual estimands. They are not "
    "simultaneous family-wise confidence bands over all V3 contrasts."
)

FORBIDDEN_INFERENTIAL_FIELDS = ("pass", "fail", "gate_status", "support_status")

V2_AUTHORITATIVE_STATUS = {
    "LOCAL_RESPONSE_STATUS": "LOCAL_RESPONSE_NOT_IDENTIFIED",
    "NETWORK_SUPPORT_FINAL": "NOT_EARNED",
    "role": (
        "Frozen V2 statuses, reproduced verbatim for provenance. V3 may explain V2; V3 may "
        "not overturn V2. This summarizer never recomputes or overrides them."
    ),
}

SESOI = {"nire": 0.05, "rate_difference": 0.10, "reliability_discrepancy": 0.05}
SESOI_ROLE = "preregistered SESOI / decision-relevance reference magnitudes, NOT gates"
LEGACY_V2_ORIENTATION_ONLY = {"nire": 0.20, "edge_f1": 0.80, "placebo_ratio": 0.20}

DEFAULT_N_BOOTSTRAP = 10000
SUBSTANTIVE_MODES = ("named_substreams", "orthogonal_v3")

# -------------------------------------------------------------------------------------
# Frozen cell groupings
# -------------------------------------------------------------------------------------

BLOCK_A_LADDER = ("A_PEXACT", "A_S025", "A_S050", "A_S100", "A_S200")
BLOCK_A_SIGMA = {
    "A_PEXACT": 0.0,
    "A_S025": 0.025,
    "A_S050": 0.05,
    "A_S100": 0.10,
    "A_S200": 0.20,
}
BLOCK_A_REFERENCE = "A_PEXACT"

BLOCK_A_PRIME = ("A1_PEXACT_K1", "A1_S100_K1")
BLOCK_A_PRIME_REFERENCE = "A1_PEXACT_K1"

BLOCK_B_GAMMA = ("B_GNONE", "B_GLOW", "B_GMED", "B_GHIGH")
BLOCK_B_REFERENCE = "B_GNONE"

# Identification regime x gamma. FAVOURABLE arm is Block B; REALISTIC arm is Block C.
BLOCK_C_GRID = {
    "MED": {"FAVOURABLE": "B_GMED", "REALISTIC": "C_REAL_GMED"},
    "HIGH": {"FAVOURABLE": "B_GHIGH", "REALISTIC": "C_REAL_GHIGH"},
}

BLOCK_D_CELLS = {
    ("P-EXACT", "R-EXACT", 0.0): "D_PE_RE_R0",
    ("P-EXACT", "R-EXACT", 0.3): "D_PE_RE_R3",
    ("P-EXACT", "R-NOISE", 0.0): "D_PE_RN_R0",
    ("P-EXACT", "R-NOISE", 0.3): "D_PE_RN_R3",
    ("P-MULTNOISE", "R-EXACT", 0.0): "D_PM_RE_R0",
    ("P-MULTNOISE", "R-EXACT", 0.3): "D_PM_RE_R3",
    ("P-MULTNOISE", "R-NOISE", 0.0): "D_PM_RN_R0",
    ("P-MULTNOISE", "R-NOISE", 0.3): "D_PM_RN_R3",
}

PAIRING_TIERS = {
    "block_A_sigma_ladder": 1,
    "block_A_prime_cadence_anchor": 1,
    "block_B_gamma_profile": 3,
    "block_C_identification_bundle": 3,
    "block_C_gamma_within_regime": 3,
    "block_D_factorial": 1,
}

TIER_SEMANTICS = {
    1: "same-truth, same estimand; only the observation map changes",
    2: "same-truth, different estimand and sample size",
    3: (
        "shared-base-innovation, different realized truth; pairing is a variance-reduction "
        "device, not a same-truth counterfactual"
    ),
}

BLOCK_C_DISCLOSURES = (
    "IDENTIFICATION_REGIME is a bundle of seven factor changes (cadence, pumping quality, "
    "recharge quality, confounding, missingness, head SNR, process noise) and is NOT a "
    "measurement-quality factor. The bundle effect is reported as a bundle effect and is not "
    "decomposable by this design.",
    "The gamma contrast holds realized tau_relax fixed by re-solving the conductance scale, so "
    "more coupling also means less boundary leakage and A_ii differs across gamma.",
    "NETWORK_SUPPORT_FINAL = NOT_EARNED stands regardless; V3 may not be cited as support for "
    "empirical M1N.",
)

# -------------------------------------------------------------------------------------
# Outcome families
# -------------------------------------------------------------------------------------

PRIMARY_FAMILIES = {
    "P1": {
        "outcome": ["nire_persistent_step_h26_L"],
        "cells": ["A_PEXACT", "A_S100"],
        "statistic": "paired median difference + 95% percentile-bootstrap interval",
        "tier": 1,
    },
    "P2": {
        "outcome": ["beta_q_ratio_vs_exact", "partial_reliability_q"],
        "cells": list(BLOCK_A_LADDER),
        "statistic": "paired median of the ratio, and of ratio minus partial reliability",
        "tier": 1,
    },
    "P3": {
        "outcome": ["nire_persistent_step_h26_L", "benchmark_layers"],
        "cells": list(BLOCK_B_GAMMA),
        "statistic": "paired median differences; deterministic benchmark profiles",
        "tier": 3,
    },
    "P4": {
        "outcome": ["strong_edge_undirected_f1", "edge_precision", "false_edge_count"],
        "cells": ["B_GMED", "B_GHIGH", "C_REAL_GMED", "C_REAL_GHIGH"],
        "statistic": "paired median differences",
        "tier": 3,
    },
    "P5": {
        "outcome": ["placebo_false_effect_L", "placebo_relative_to_true_L"],
        "cells": sorted(BLOCK_D_CELLS.values()),
        "statistic": "Wilson intervals; three marginal contrasts; paired continuous medians",
        "tier": 1,
    },
}

BLOCK_A_METRICS = (
    "nire_persistent_step_h26_L",
    "nire_persistent_step_h4_L",
    "nire_persistent_step_h13_L",
    "nire_persistent_step_h52_L",
    "relative_shape_error_persistent_step_L",
    "cumulative_drawdown_error_persistent_step_L",
    "beta_q_hat_mean_L",
    "partial_reliability_q",
    "variance_form_reliability_q",
    "unconditional_reliability_q",
    "theory_reliability_q",
    "A_diag_relative_error_L",
    "A_diag_signed_relative_error_L",
    "nire_recomb_trueA_hatB",
    "nire_recomb_hatA_trueB",
    "condition_number_L",
    "max_vif_L",
    "pumping_excitation_fraction_L",
    "median_admissible_train_rows_L",
    "rmse_test_L",
    "rmse_improvement_vs_B0_L",
)

BLOCK_B_METRICS = (
    "nire_persistent_step_h26_L",
    "nire_persistent_step_h26_N",
    "relative_shape_error_persistent_step_L",
    "beta_q_hat_mean_L",
    "partial_reliability_q",
    "A_diag_signed_relative_error_L",
    "nire_recomb_trueA_hatB",
    "nire_recomb_hatA_trueB",
    "neighbour_flux_share",
    "mean_diagonal_transition",
    "spectral_radius",
    "tau_relax_realized",
    "strong_edge_undirected_f1",
    "edge_precision",
    "edge_recall",
    "false_edge_count",
    "predicted_edge_count",
    "strong_coupling_weight_error",
)

BLOCK_C_METRICS = (
    "strong_edge_undirected_f1",
    "edge_precision",
    "edge_recall",
    "false_edge_count",
    "nire_persistent_step_h26_N",
    "nire_persistent_step_h26_L",
    "partial_reliability_q",
    "neighbour_flux_share",
)

BLOCK_C_RATE_METRICS = ("false_edge_any", "estimable_N", "estimable_L")

BLOCK_D_METRICS = ("placebo_false_effect_L", "placebo_relative_to_true_L")

BLOCK_D_SECONDARY_METRICS = (
    "placebo_coef_L",
    "placebo_coef_abs_L",
    "placebo_step_response_L",
    "corr_placebo_qobs",
    "corr_placebo_rproxy",
    "vif_placebo",
    "s8_real_pumping_present_L",
)

PREDICTION_VS_INTERVENTION_METRICS = (
    "rmse_test_B0",
    "rmse_test_L",
    "rmse_improvement_vs_B0_L",
    "nire_persistent_step_h26_L",
    "relative_shape_error_persistent_step_L",
    "max_abs_protected_prediction_L",
)

RATE_METRICS = (
    "estimable_L",
    "estimable_N",
    "sign_correct_fraction_L",
    "false_edge_any",
    "placebo_false_effect_L",
    "direct_parameter_recovery_is_primary",
    "absolute_S_identifiable",
)

BENCHMARK_FIELDS = (
    "F_intervention_all",
    "F_intervention_pumped",
    "neighbor_unmodeled_floor",
    "F_train_true",
    "F_train_obs",
)

ESTIMABILITY_MODELS = ("B0", "L", "S", "N")


# -------------------------------------------------------------------------------------
# Primitives
# -------------------------------------------------------------------------------------


def _rng_for_label(label: str) -> np.random.Generator:
    """Deterministic bootstrap stream derived from the contrast label, never from seeds."""
    digest = hashlib.sha256(f"v3-summarizer-bootstrap:{label}".encode("utf-8")).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "big"))


def _num(value: Any) -> float:
    if value is None or value == "":
        return float("nan")
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def wilson_interval(successes: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return float("nan"), float("nan")
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / denom
    half = z * np.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / denom
    return float(centre - half), float(centre + half)


def bootstrap_interval(
    values: Sequence[float],
    label: str,
    statistic: str = "median",
    n_bootstrap: int = DEFAULT_N_BOOTSTRAP,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile bootstrap over the resampling unit already encoded in `values`."""
    arr = np.asarray([v for v in values if np.isfinite(v)], dtype=float)
    if arr.size == 0 or n_bootstrap <= 0:
        return float("nan"), float("nan")
    if arr.size == 1:
        return float(arr[0]), float(arr[0])
    rng = _rng_for_label(f"{label}|{statistic}|{arr.size}")
    idx = rng.integers(0, arr.size, size=(int(n_bootstrap), arr.size))
    draws = arr[idx]
    stat = np.median(draws, axis=1) if statistic == "median" else np.mean(draws, axis=1)
    return (
        float(np.quantile(stat, alpha / 2.0)),
        float(np.quantile(stat, 1.0 - alpha / 2.0)),
    )


def describe(
    values: Iterable[float],
    label: str,
    n_bootstrap: int = DEFAULT_N_BOOTSTRAP,
) -> dict[str, Any]:
    arr = np.asarray([_num(v) for v in values], dtype=float)
    good = arr[np.isfinite(arr)]
    if good.size == 0:
        return {
            "n": 0,
            "n_finite": 0,
            "mean": float("nan"),
            "median": float("nan"),
            "sd": float("nan"),
            "quantiles": {},
            "median_pointwise_interval": (float("nan"), float("nan")),
            "mean_pointwise_interval": (float("nan"), float("nan")),
        }
    qs = [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95]
    return {
        "n": int(arr.size),
        "n_finite": int(good.size),
        "mean": float(good.mean()),
        "median": float(np.median(good)),
        "sd": float(good.std(ddof=1)) if good.size > 1 else float("nan"),
        "min": float(good.min()),
        "max": float(good.max()),
        "quantiles": {f"q{int(q * 100):02d}": float(np.quantile(good, q)) for q in qs},
        "median_pointwise_interval": bootstrap_interval(
            good, label, "median", n_bootstrap
        ),
        "mean_pointwise_interval": bootstrap_interval(good, label, "mean", n_bootstrap),
    }


def _by_seed(records: Sequence[dict], cell_id: str, metric: str) -> dict[int, float]:
    out: dict[int, float] = {}
    for row in records:
        if str(row.get("cell_id")) != cell_id:
            continue
        seed = parse_seed(row["seed"])
        out[seed] = _num(row.get(metric))
    return out


def _cell_seeds(records: Sequence[dict], cell_id: str) -> set[int]:
    seeds = set()
    for row in records:
        if str(row.get("cell_id")) != cell_id:
            continue
        seeds.add(parse_seed(row["seed"]))
    return seeds


def paired_contrast(
    records: Sequence[dict],
    cell_a: str,
    cell_b: str,
    metric: str,
    tier: int,
    contrast_family: str,
    n_bootstrap: int = DEFAULT_N_BOOTSTRAP,
) -> dict[str, Any]:
    """Same-seed paired difference `cell_a - cell_b` for one metric.

    Resamples SEEDS as the unit so pairing is preserved. Reports the realized paired sd and
    the paired correlation so the pairing's efficiency is measured rather than assumed.
    """
    a = _by_seed(records, cell_a, metric)
    b = _by_seed(records, cell_b, metric)
    common = sorted(set(a) & set(b))
    pairs = [(a[s], b[s]) for s in common if np.isfinite(a[s]) and np.isfinite(b[s])]
    label = f"{contrast_family}|{cell_a}-{cell_b}|{metric}"
    if not pairs:
        return {
            "contrast": f"{cell_a} - {cell_b}",
            "metric": metric,
            "pairing_tier": tier,
            "pairing_tier_semantics": TIER_SEMANTICS[tier],
            "n_paired_seeds": 0,
            "paired_median": float("nan"),
            "paired_mean": float("nan"),
            "paired_sd": float("nan"),
            "paired_correlation": float("nan"),
            "fraction_a_lower": float("nan"),
            "median_pointwise_interval": (float("nan"), float("nan")),
            "mean_pointwise_interval": (float("nan"), float("nan")),
            "quantiles": {},
        }
    va = np.asarray([p[0] for p in pairs], float)
    vb = np.asarray([p[1] for p in pairs], float)
    diff = va - vb
    qs = [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95]
    correlation = (
        float(np.corrcoef(va, vb)[0, 1])
        if diff.size > 1 and va.std() > 0 and vb.std() > 0
        else float("nan")
    )
    return {
        "contrast": f"{cell_a} - {cell_b}",
        "metric": metric,
        "pairing_tier": tier,
        "pairing_tier_semantics": TIER_SEMANTICS[tier],
        "n_paired_seeds": int(diff.size),
        "paired_median": float(np.median(diff)),
        "paired_mean": float(diff.mean()),
        "paired_sd": float(diff.std(ddof=1)) if diff.size > 1 else float("nan"),
        "paired_correlation": correlation,
        "fraction_a_lower": float(np.mean(diff < 0.0)),
        "median_pointwise_interval": bootstrap_interval(diff, label, "median", n_bootstrap),
        "mean_pointwise_interval": bootstrap_interval(diff, label, "mean", n_bootstrap),
        "quantiles": {f"q{int(q * 100):02d}": float(np.quantile(diff, q)) for q in qs},
        "level_a": float(np.median(va)),
        "level_b": float(np.median(vb)),
    }


def rate_summary(
    records: Sequence[dict], cell_id: str, metric: str
) -> dict[str, Any]:
    values = np.asarray(
        [v for v in _by_seed(records, cell_id, metric).values() if np.isfinite(v)], float
    )
    if values.size == 0:
        return {"n": 0, "rate": float("nan"), "wilson_interval": (float("nan"), float("nan"))}
    successes = float(np.sum(values > 0.5))
    return {
        "n": int(values.size),
        "successes": successes,
        "rate": float(successes / values.size),
        "wilson_interval": wilson_interval(successes, int(values.size)),
        "mean_value": float(values.mean()),
    }


def paired_rate_difference(
    records: Sequence[dict],
    cell_a: str,
    cell_b: str,
    metric: str,
    tier: int,
    contrast_family: str,
    n_bootstrap: int = DEFAULT_N_BOOTSTRAP,
) -> dict[str, Any]:
    out = paired_contrast(
        records, cell_a, cell_b, metric, tier, contrast_family, n_bootstrap
    )
    out["metric_kind"] = "rate_difference"
    out["sesoi_reference_magnitude"] = SESOI["rate_difference"]
    out["sesoi_role"] = SESOI_ROLE
    return out


def assert_no_gates(payload: dict[str, Any]) -> None:
    flat_keys = set(payload)
    offending = flat_keys & set(FORBIDDEN_INFERENTIAL_FIELDS)
    if offending:
        raise ValueError(
            f"V3 summarizer emitted forbidden inferential fields: {sorted(offending)}"
        )


def check_uniform_substantive_modes(records: Sequence[dict]) -> dict[str, Any]:
    """The ANALYSIS summarizer refuses input whose rows are not uniformly substantive."""
    modes = {(str(r.get("rng_mode", "")), str(r.get("system_seed_mode", ""))) for r in records}
    modes.discard(("", ""))
    uniform = modes == {SUBSTANTIVE_MODES} or modes == {tuple(SUBSTANTIVE_MODES)}
    return {
        "observed_mode_pairs": sorted(list(m) for m in modes),
        "uniform_substantive": bool(uniform),
        "required": list(SUBSTANTIVE_MODES),
    }


def require_uniform_substantive_modes(records: Sequence[dict]) -> None:
    report = check_uniform_substantive_modes(records)
    if not report["uniform_substantive"]:
        raise ValueError(
            "V3 ANALYSIS summarizer refuses non-uniform or non-substantive mode rows: "
            f"{report['observed_mode_pairs']}"
        )


# -------------------------------------------------------------------------------------
# Block A: pumping attenuation
# -------------------------------------------------------------------------------------


def _beta_q_ratio_records(
    records: Sequence[dict], cell: str, reference: str, guard: float = 1e-6
) -> dict[str, Any]:
    """Paired beta_Q ratio versus the exact-metering arm, with the preregistered guard.

    The ratio is undefined when the reference coefficient is ~0. Those seeds are excluded
    from the ratio statistic only; the guard-free paired difference is reported alongside.
    """
    sigma_values = _by_seed(records, cell, "beta_q_hat_mean_L")
    exact_values = _by_seed(records, reference, "beta_q_hat_mean_L")
    common = sorted(set(sigma_values) & set(exact_values))
    ratios: list[float] = []
    diffs: list[float] = []
    excluded = 0
    for seed in common:
        num, den = sigma_values[seed], exact_values[seed]
        if not (np.isfinite(num) and np.isfinite(den)):
            continue
        diffs.append(float(num - den))
        if abs(den) < guard:
            excluded += 1
            continue
        ratios.append(float(num / den))
    return {"ratios": ratios, "differences": diffs, "n_excluded_by_guard": excluded, "guard": guard}


def block_a_attenuation(
    records: Sequence[dict],
    n_bootstrap: int = DEFAULT_N_BOOTSTRAP,
    ladder: Sequence[str] = BLOCK_A_LADDER,
    reference: str = BLOCK_A_REFERENCE,
    sigma_map: dict[str, float] | None = None,
    family: str = "block_A_sigma_ladder",
) -> dict[str, Any]:
    """Tier-1 sigma ladder: reliability curves, beta_Q attenuation, NIRE, shape error."""
    sigma_map = sigma_map or BLOCK_A_SIGMA
    tier = PAIRING_TIERS[family]
    per_cell: dict[str, Any] = {}
    for cell in ladder:
        entry: dict[str, Any] = {
            "sigma": sigma_map.get(cell, float("nan")),
            "n_seeds": len(_cell_seeds(records, cell)),
            "metrics": {},
            "rates": {},
        }
        for metric in BLOCK_A_METRICS:
            entry["metrics"][metric] = describe(
                _by_seed(records, cell, metric).values(), f"{family}|{cell}|{metric}", n_bootstrap
            )
        for metric in ("estimable_L", "sign_correct_fraction_L"):
            entry["rates"][metric] = rate_summary(records, cell, metric)
        per_cell[cell] = entry

    contrasts: dict[str, Any] = {}
    attenuation: dict[str, Any] = {}
    for cell in ladder:
        if cell == reference:
            continue
        contrasts[cell] = {
            metric: paired_contrast(
                records, cell, reference, metric, tier, family, n_bootstrap
            )
            for metric in BLOCK_A_METRICS
        }
        ratio_block = _beta_q_ratio_records(records, cell, reference)
        ratios = ratio_block["ratios"]
        reliability = [
            v for v in _by_seed(records, cell, "partial_reliability_q").values() if np.isfinite(v)
        ]
        theory = [
            v for v in _by_seed(records, cell, "theory_reliability_q").values() if np.isfinite(v)
        ]
        # Paired, same-seed discrepancy between the realized ratio and the reliability.
        rel_by_seed = _by_seed(records, cell, "partial_reliability_q")
        theory_by_seed = _by_seed(records, cell, "theory_reliability_q")
        sigma_beta = _by_seed(records, cell, "beta_q_hat_mean_L")
        exact_beta = _by_seed(records, reference, "beta_q_hat_mean_L")
        disc_partial: list[float] = []
        disc_theory: list[float] = []
        for seed in sorted(set(sigma_beta) & set(exact_beta)):
            num, den = sigma_beta[seed], exact_beta[seed]
            if not (np.isfinite(num) and np.isfinite(den)) or abs(den) < 1e-6:
                continue
            ratio = num / den
            if np.isfinite(rel_by_seed.get(seed, np.nan)):
                disc_partial.append(float(ratio - rel_by_seed[seed]))
            if np.isfinite(theory_by_seed.get(seed, np.nan)):
                disc_theory.append(float(ratio - theory_by_seed[seed]))
        attenuation[cell] = {
            "sigma": sigma_map.get(cell, float("nan")),
            "pairing_tier": tier,
            "beta_q_ratio_vs_exact": describe(
                ratios, f"{family}|{cell}|beta_q_ratio", n_bootstrap
            ),
            "beta_q_paired_difference_guard_free": describe(
                ratio_block["differences"], f"{family}|{cell}|beta_q_diff", n_bootstrap
            ),
            "n_excluded_by_guard": ratio_block["n_excluded_by_guard"],
            "guard_threshold_abs_beta_q_exact": ratio_block["guard"],
            "partial_reliability_q": describe(
                reliability, f"{family}|{cell}|partial_rel", n_bootstrap
            ),
            "theory_reliability_q": describe(
                theory, f"{family}|{cell}|theory_rel", n_bootstrap
            ),
            "ratio_minus_partial_reliability": describe(
                disc_partial, f"{family}|{cell}|ratio_minus_partial", n_bootstrap
            ),
            "ratio_minus_theory_reliability": describe(
                disc_theory, f"{family}|{cell}|ratio_minus_theory", n_bootstrap
            ),
            "reliability_discrepancy_reference_magnitude": SESOI["reliability_discrepancy"],
            "sesoi_role": SESOI_ROLE,
        }

    return {
        "family": family,
        "pairing_tier": tier,
        "pairing_tier_semantics": TIER_SEMANTICS[tier],
        "reference_cell": reference,
        "sigma_levels": {c: sigma_map.get(c, float("nan")) for c in ladder},
        "per_cell": per_cell,
        "paired_contrasts_vs_reference": contrasts,
        "attenuation_diagnostic": attenuation,
        "pumping_error_model": (
            "mean-corrected / unit-mean multiplicative lognormal pumping error "
            "(E[m] = 1; median exp(-sigma^2/2))"
        ),
        "interval_semantics": INTERVAL_SEMANTICS,
        "sesoi": SESOI,
        "sesoi_role": SESOI_ROLE,
    }


def block_a_prime_cadence(
    records: Sequence[dict], n_bootstrap: int = DEFAULT_N_BOOTSTRAP
) -> dict[str, Any]:
    """Tier-1 k=1 anchor pair, plus the k=4 counterpart for the cadence comparison."""
    family = "block_A_prime_cadence_anchor"
    payload = block_a_attenuation(
        records,
        n_bootstrap=n_bootstrap,
        ladder=BLOCK_A_PRIME,
        reference=BLOCK_A_PRIME_REFERENCE,
        sigma_map={"A1_PEXACT_K1": 0.0, "A1_S100_K1": 0.10},
        family=family,
    )
    payload["cadence"] = 1
    payload["cadence_comparison"] = {
        "role": (
            "The k=1 anchor pair is compared to the matched k=4 pair (A_PEXACT vs A_S100) as a "
            "cadence comparison. Cadence changes the estimand and the TRAIN sample size, so the "
            "cross-cadence comparison is descriptive and is NOT a same-estimand contrast."
        ),
        "k1_pair": ["A1_PEXACT_K1", "A1_S100_K1"],
        "k4_pair": ["A_PEXACT", "A_S100"],
        "cross_cadence_tier": 2,
        "cross_cadence_tier_semantics": TIER_SEMANTICS[2],
        "k1_paired_contrast": {
            metric: paired_contrast(
                records, "A1_S100_K1", "A1_PEXACT_K1", metric, 1, family, n_bootstrap
            )
            for metric in BLOCK_A_METRICS
        },
        "k4_paired_contrast": {
            metric: paired_contrast(
                records, "A_S100", "A_PEXACT", metric, 1, "block_A_sigma_ladder", n_bootstrap
            )
            for metric in BLOCK_A_METRICS
        },
        "note_k1_gamma": (
            "The A' cells run at gamma=MED on a single-node topology, so the coupling label has "
            "no cross-node effect there; the anchor isolates cadence, not coupling."
        ),
    }
    payload["direct_parameter_recovery_is_primary_at_k1"] = {
        cell: rate_summary(records, cell, "direct_parameter_recovery_is_primary")
        for cell in BLOCK_A_PRIME
    }
    payload["B_Q_relative_error_median"] = {
        cell: describe(
            _by_seed(records, cell, "B_Q_relative_error_median").values(),
            f"{family}|{cell}|B_Q_rel_err",
            n_bootstrap,
        )
        for cell in BLOCK_A_PRIME
    }
    return payload


# -------------------------------------------------------------------------------------
# Block B: coupling profile
# -------------------------------------------------------------------------------------


def block_b_coupling(
    records: Sequence[dict],
    benchmarks: dict[str, dict] | None = None,
    n_bootstrap: int = DEFAULT_N_BOOTSTRAP,
) -> dict[str, Any]:
    family = "block_B_gamma_profile"
    tier = PAIRING_TIERS[family]
    per_cell: dict[str, Any] = {}
    for cell in BLOCK_B_GAMMA:
        entry: dict[str, Any] = {
            "n_seeds": len(_cell_seeds(records, cell)),
            "metrics": {
                metric: describe(
                    _by_seed(records, cell, metric).values(),
                    f"{family}|{cell}|{metric}",
                    n_bootstrap,
                )
                for metric in BLOCK_B_METRICS
            },
            "rates": {
                metric: rate_summary(records, cell, metric)
                for metric in ("estimable_L", "estimable_N", "false_edge_any")
            },
        }
        if benchmarks and cell in benchmarks:
            entry["benchmark_layers"] = {
                key: _num(benchmarks[cell].get(key)) for key in BENCHMARK_FIELDS
            }
        per_cell[cell] = entry

    contrasts = {
        cell: {
            metric: paired_contrast(
                records, cell, BLOCK_B_REFERENCE, metric, tier, family, n_bootstrap
            )
            for metric in BLOCK_B_METRICS
        }
        for cell in BLOCK_B_GAMMA
        if cell != BLOCK_B_REFERENCE
    }
    adjacent = {}
    for lo, hi in zip(BLOCK_B_GAMMA[:-1], BLOCK_B_GAMMA[1:]):
        adjacent[f"{hi}-{lo}"] = {
            metric: paired_contrast(records, hi, lo, metric, tier, family, n_bootstrap)
            for metric in BLOCK_B_METRICS
        }
    return {
        "family": family,
        "pairing_tier": tier,
        "pairing_tier_semantics": TIER_SEMANTICS[tier],
        "reference_cell": BLOCK_B_REFERENCE,
        "gamma_ordering": list(BLOCK_B_GAMMA),
        "per_cell": per_cell,
        "paired_contrasts_vs_reference": contrasts,
        "paired_contrasts_adjacent_gamma": adjacent,
        "disclosures": (
            "The gamma contrast holds realized tau_relax fixed by re-solving the conductance "
            "scale, so more coupling also means less boundary leakage and A_ii differs across "
            "gamma.",
            "neighbour_flux_share is a synthetic dimensionless coupling-materiality diagnostic "
            "internal to this known-truth system, not a field-observable Andhra Pradesh quantity.",
        ),
        "interval_semantics": INTERVAL_SEMANTICS,
        "sesoi": SESOI,
        "sesoi_role": SESOI_ROLE,
    }


# -------------------------------------------------------------------------------------
# Block C: identification regime x gamma
# -------------------------------------------------------------------------------------


def block_c_identification(
    records: Sequence[dict], n_bootstrap: int = DEFAULT_N_BOOTSTRAP
) -> dict[str, Any]:
    family = "block_C_identification_bundle"
    tier = PAIRING_TIERS[family]
    per_cell: dict[str, Any] = {}
    for gamma, arms in BLOCK_C_GRID.items():
        for regime, cell in arms.items():
            per_cell[cell] = {
                "gamma": gamma,
                "identification_regime": regime,
                "n_seeds": len(_cell_seeds(records, cell)),
                "metrics": {
                    metric: describe(
                        _by_seed(records, cell, metric).values(),
                        f"{family}|{cell}|{metric}",
                        n_bootstrap,
                    )
                    for metric in BLOCK_C_METRICS
                },
                "rates": {
                    metric: rate_summary(records, cell, metric)
                    for metric in BLOCK_C_RATE_METRICS
                },
            }

    bundle = {
        gamma: {
            metric: paired_contrast(
                records,
                arms["FAVOURABLE"],
                arms["REALISTIC"],
                metric,
                tier,
                family,
                n_bootstrap,
            )
            for metric in BLOCK_C_METRICS
        }
        for gamma, arms in BLOCK_C_GRID.items()
    }
    bundle_rates = {
        gamma: {
            metric: paired_rate_difference(
                records,
                arms["FAVOURABLE"],
                arms["REALISTIC"],
                metric,
                tier,
                family,
                n_bootstrap,
            )
            for metric in BLOCK_C_RATE_METRICS
        }
        for gamma, arms in BLOCK_C_GRID.items()
    }
    gamma_within = {
        regime: {
            metric: paired_contrast(
                records,
                BLOCK_C_GRID["HIGH"][regime],
                BLOCK_C_GRID["MED"][regime],
                metric,
                PAIRING_TIERS["block_C_gamma_within_regime"],
                "block_C_gamma_within_regime",
                n_bootstrap,
            )
            for metric in BLOCK_C_METRICS
        }
        for regime in ("FAVOURABLE", "REALISTIC")
    }
    return {
        "family": family,
        "pairing_tier": tier,
        "pairing_tier_semantics": TIER_SEMANTICS[tier],
        "grid": BLOCK_C_GRID,
        "per_cell": per_cell,
        "bundle_effect_favourable_minus_realistic": bundle,
        "bundle_effect_rate_outcomes": bundle_rates,
        "gamma_effect_within_regime_high_minus_med": gamma_within,
        "co_primary_outcomes": ["strong_edge_undirected_f1", "edge_precision", "false_edge_count"],
        "disclosures": BLOCK_C_DISCLOSURES,
        "interval_semantics": INTERVAL_SEMANTICS,
        "sesoi": SESOI,
        "sesoi_role": SESOI_ROLE,
    }


# -------------------------------------------------------------------------------------
# Block D: placebo factorial
# -------------------------------------------------------------------------------------


def block_d_factorial(
    records: Sequence[dict],
    metrics: tuple[str, ...] | None = None,
    n_bootstrap: int = DEFAULT_N_BOOTSTRAP,
) -> dict[str, Any]:
    """3 main effects, 3 two-way, 1 three-way (secondary) using same-seed pairing."""
    metrics = metrics or BLOCK_D_METRICS
    pumping_levels = ("P-EXACT", "P-MULTNOISE")
    recharge_levels = ("R-EXACT", "R-NOISE")
    rho_levels = (0.0, 0.3)
    family = "block_D_factorial"
    tier = PAIRING_TIERS[family]

    def coded(p, r, c):
        return (
            1.0 if p == "P-MULTNOISE" else -1.0,
            1.0 if r == "R-NOISE" else -1.0,
            1.0 if c == 0.3 else -1.0,
        )

    result: dict[str, Any] = {
        "family": family,
        "pairing_tier": tier,
        "pairing_tier_semantics": TIER_SEMANTICS[tier],
        "interval_semantics": INTERVAL_SEMANTICS,
        "three_way_role": "preregistered secondary/descriptive",
        "sesoi_role": SESOI_ROLE,
        "sesoi": SESOI,
        "outcomes": {},
    }
    for metric in metrics:
        cells = {
            key: _by_seed(records, cid, metric) for key, cid in BLOCK_D_CELLS.items()
        }
        seed_sets = [set(v) for v in cells.values() if v]
        common = set.intersection(*seed_sets) if seed_sets else set()
        contrasts = {
            "main_pumping": [],
            "main_recharge": [],
            "main_confounding": [],
            "int_pumping_recharge": [],
            "int_pumping_confounding": [],
            "int_recharge_confounding": [],
            "int_three_way": [],
        }
        for seed in sorted(common):
            acc = {k: 0.0 for k in contrasts}
            n_ok = 0
            for p in pumping_levels:
                for r in recharge_levels:
                    for c in rho_levels:
                        y = cells[(p, r, c)].get(seed, float("nan"))
                        if not np.isfinite(y):
                            continue
                        P, R, C = coded(p, r, c)
                        acc["main_pumping"] += y * P
                        acc["main_recharge"] += y * R
                        acc["main_confounding"] += y * C
                        acc["int_pumping_recharge"] += y * P * R
                        acc["int_pumping_confounding"] += y * P * C
                        acc["int_recharge_confounding"] += y * R * C
                        acc["int_three_way"] += y * P * R * C
                        n_ok += 1
            if n_ok != 8:
                continue
            scale = 1.0 / 8.0
            for k, v in acc.items():
                contrasts[k].append(v * scale)
        summary = {}
        for name, values in contrasts.items():
            arr = np.asarray(values, float)
            summary[name] = {
                "n_paired_seeds": int(arr.size),
                "mean": float(arr.mean()) if arr.size else float("nan"),
                "median": float(np.median(arr)) if arr.size else float("nan"),
                "sd": float(arr.std(ddof=1)) if arr.size > 1 else float("nan"),
                "pointwise_interval": (
                    float(np.quantile(arr, 0.025)),
                    float(np.quantile(arr, 0.975)),
                )
                if arr.size >= 8
                else (float("nan"), float("nan")),
                "median_pointwise_interval": bootstrap_interval(
                    arr, f"{family}|{metric}|{name}", "median", n_bootstrap
                ),
                "mean_pointwise_interval": bootstrap_interval(
                    arr, f"{family}|{metric}|{name}", "mean", n_bootstrap
                ),
                "primary": name != "int_three_way",
            }
        result["outcomes"][metric] = summary

    result["per_cell"] = {
        cid: {
            "factors": dict(zip(("pumping_quality", "recharge_quality", "confounding_rho"), key)),
            "n_seeds": len(_cell_seeds(records, cid)),
            "rates": {
                metric: rate_summary(records, cid, metric)
                for metric in ("placebo_false_effect_L", "s8_real_pumping_present_L")
            },
            "metrics": {
                metric: describe(
                    _by_seed(records, cid, metric).values(),
                    f"{family}|{cid}|{metric}",
                    n_bootstrap,
                )
                for metric in tuple(metrics) + BLOCK_D_SECONDARY_METRICS
            },
        }
        for key, cid in BLOCK_D_CELLS.items()
    }
    result["v2_like_corner"] = {
        "cell_id": "D_PM_RN_R3",
        "role": (
            "External-consistency diagnostic only. NOT a numeric replication gate. Hard "
            "implementation validation comes from legacy-mode G1R1/G2R3/G3R3 bit-for-bit parity."
        ),
        "legacy_v2_orientation_only": LEGACY_V2_ORIENTATION_ONLY,
    }
    result["main_effects"] = ["pumping_quality", "recharge_quality", "confounding_rho"]
    result["two_way_interactions"] = [
        ["pumping_quality", "recharge_quality"],
        ["pumping_quality", "confounding_rho"],
        ["recharge_quality", "confounding_rho"],
    ]
    result["three_way_interaction"] = [
        "pumping_quality",
        "recharge_quality",
        "confounding_rho",
    ]
    assert_no_gates(result)
    return result


# -------------------------------------------------------------------------------------
# Benchmarks, estimability, prediction-vs-intervention
# -------------------------------------------------------------------------------------


def benchmark_merge(
    records: Sequence[dict],
    benchmarks: dict[str, dict] | None,
    n_bootstrap: int = DEFAULT_N_BOOTSTRAP,
) -> dict[str, Any]:
    """Merge the deterministic / pseudo-true benchmark layers with the fitted layer-4 NIRE."""
    cells = sorted({str(r.get("cell_id")) for r in records if r.get("cell_id")})
    if benchmarks:
        cells = sorted(set(cells) | set(benchmarks))
    per_cell: dict[str, Any] = {}
    for cell in cells:
        bench = (benchmarks or {}).get(cell, {})
        fitted = describe(
            _by_seed(records, cell, "nire_persistent_step_h26_L").values(),
            f"benchmark_merge|{cell}|fitted_nire",
            n_bootstrap,
        )
        layers = {key: _num(bench.get(key)) for key in BENCHMARK_FIELDS}
        entry = {
            "layer_1_F_intervention_all": layers["F_intervention_all"],
            "layer_2_F_train_true": layers["F_train_true"],
            "layer_3_F_train_obs": layers["F_train_obs"],
            "layer_4_fitted_nire_L": fitted,
            "companion_F_intervention_pumped": layers["F_intervention_pumped"],
            "companion_neighbor_unmodeled_floor": layers["neighbor_unmodeled_floor"],
            "gap_representation_to_train_true": float(
                layers["F_train_true"] - layers["F_intervention_all"]
            ),
            "gap_train_true_to_train_obs": float(
                layers["F_train_obs"] - layers["F_train_true"]
            ),
            "gap_train_obs_to_fitted_median": float(
                fitted["median"] - layers["F_train_obs"]
            ),
            "F_intervention_global_certified": bench.get("F_intervention_global_certified"),
            "F_intervention_domain": bench.get("F_intervention_domain"),
            "n_included_nodes": _num(bench.get("n_included_nodes")),
            "n_included_nonpumped_nodes": _num(bench.get("n_included_nonpumped_nodes")),
            "floor_invariant_holds": bool(
                not np.isfinite(layers["F_intervention_all"])
                or not np.isfinite(layers["neighbor_unmodeled_floor"])
                or layers["F_intervention_all"] >= layers["neighbor_unmodeled_floor"] - 1e-9
            ),
        }
        per_cell[cell] = entry
    return {
        "ordering": ["F_intervention_all", "F_train_true", "F_train_obs", "fitted_nire_L"],
        "decomposition_is_additive": False,
        "decomposition_note": (
            "Nested benchmark comparisons only. Frozen NIRE is a mean over included nodes of "
            "per-node ratios of L2 norms; that algebra does not license an additive error "
            "decomposition."
        ),
        "gap_semantics": {
            "F_intervention_all__to__F_train_true": "training-target / functional-approximation cost",
            "F_train_true__to__F_train_obs": "asymptotic observation / proxy / forcing-data bias",
            "F_train_obs__to__fitted_nire_L": "finite-sample estimation cost",
        },
        "per_cell": per_cell,
        "benchmarks_merged": bool(benchmarks),
    }


def benchmark_convergence_report(convergence: Sequence[dict] | None) -> dict[str, Any]:
    """Nested-prefix benchmark convergence, reported as a pre-defined diagnostic only."""
    rows = list(convergence or [])
    if not rows:
        return {"available": False, "prefixes": [], "per_cell": {}}
    prefixes = sorted({int(_num(r.get("prefix_n"))) for r in rows if np.isfinite(_num(r.get("prefix_n")))})
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
    per_cell: dict[str, Any] = {}
    for row in rows:
        cell = str(row.get("cell_id"))
        per_cell.setdefault(cell, {"prefixes": {}})
        per_cell[cell]["prefixes"][int(_num(row.get("prefix_n")))] = {
            key: _num(row.get(key)) for key in tracked
        }
    worst: dict[str, Any] = {}
    for key in tracked:
        entries = []
        for cell, block in per_cell.items():
            ordered = sorted(block["prefixes"])
            for lo, hi in zip(ordered[:-1], ordered[1:]):
                a = block["prefixes"][lo][key]
                b = block["prefixes"][hi][key]
                if np.isfinite(a) and np.isfinite(b):
                    entries.append((abs(b - a), f"{lo}->{hi}", cell, float(b - a)))
        if entries:
            magnitude, step, cell, signed = max(entries)
            worst[key] = {
                "worst_abs_delta": magnitude,
                "worst_step": step,
                "worst_cell": cell,
                "worst_signed_delta": signed,
            }
    return {
        "available": True,
        "prefixes": prefixes,
        "per_cell": per_cell,
        "worst_prefix_step_changes": worst,
        "use": (
            "Pre-defined benchmark diagnostic only. May not be used to select the benchmark n, "
            "or to alter cells, sigma, gamma, n_ANALYSIS, hypotheses or SESOI."
        ),
        "nesting": "SeedSequence(entropy).spawn(n)[:m] == spawn(m); prefixes are strictly nested.",
    }


def estimability_summary(records: Sequence[dict]) -> dict[str, Any]:
    """First-class estimability, never dropped by aggregation."""
    cells = sorted({str(r.get("cell_id")) for r in records if r.get("cell_id")})
    per_cell: dict[str, Any] = {}
    totals: dict[str, dict[str, int]] = {m: {} for m in ESTIMABILITY_MODELS}
    for cell in cells:
        entry: dict[str, Any] = {}
        for model in ESTIMABILITY_MODELS:
            statuses: dict[str, int] = {}
            reasons: dict[str, int] = {}
            for row in records:
                if str(row.get("cell_id")) != cell:
                    continue
                status = str(row.get(f"estimability_status_{model}", ""))
                reason = str(row.get(f"estimability_reason_{model}", ""))
                if status:
                    statuses[status] = statuses.get(status, 0) + 1
                    totals[model][status] = totals[model].get(status, 0) + 1
                if reason:
                    reasons[reason] = reasons.get(reason, 0) + 1
            n = sum(statuses.values())
            estimated = statuses.get("ESTIMATED", 0)
            entry[model] = {
                "n": n,
                "status_counts": statuses,
                "reason_counts": reasons,
                "estimated_rate": float(estimated / n) if n else float("nan"),
                "estimated_wilson_interval": wilson_interval(float(estimated), n),
                "frac_nodes_fitted": describe(
                    _by_seed(records, cell, f"frac_nodes_fitted_{model}").values(),
                    f"estimability|{cell}|{model}|frac_nodes",
                    0,
                ),
                "median_admissible_train_rows": describe(
                    _by_seed(records, cell, f"median_admissible_train_rows_{model}").values(),
                    f"estimability|{cell}|{model}|train_rows",
                    0,
                ),
            }
        per_cell[cell] = entry
    return {
        "per_cell": per_cell,
        "overall_status_counts": totals,
        "policy": "estimability is a first-class outcome and is never dropped by aggregation",
    }


def prediction_vs_intervention(
    records: Sequence[dict], n_bootstrap: int = DEFAULT_N_BOOTSTRAP
) -> dict[str, Any]:
    """Prediction-versus-intervention divergence, carried forward from V2's headline."""
    cells = sorted({str(r.get("cell_id")) for r in records if r.get("cell_id")})
    per_cell: dict[str, Any] = {}
    for cell in cells:
        block = {
            metric: describe(
                _by_seed(records, cell, metric).values(),
                f"pred_vs_interv|{cell}|{metric}",
                n_bootstrap,
            )
            for metric in PREDICTION_VS_INTERVENTION_METRICS
        }
        improvement = block["rmse_improvement_vs_B0_L"]["median"]
        nire = block["nire_persistent_step_h26_L"]["median"]
        block["divergence_median_pair"] = {
            "rmse_improvement_vs_B0_L_median": improvement,
            "nire_persistent_step_h26_L_median": nire,
            "reading": (
                "Reported as a pair. A high predictive improvement alongside a high intervention "
                "NIRE is the prediction-versus-intervention divergence; no threshold is applied."
            ),
        }
        per_cell[cell] = block
    return {
        "per_cell": per_cell,
        "role": "secondary/diagnostic; predictive metrics are secondary in this design",
        "interval_semantics": INTERVAL_SEMANTICS,
    }


def rate_outcome_summary(records: Sequence[dict]) -> dict[str, Any]:
    cells = sorted({str(r.get("cell_id")) for r in records if r.get("cell_id")})
    return {
        "per_cell": {
            cell: {metric: rate_summary(records, cell, metric) for metric in RATE_METRICS}
            for cell in cells
        },
        "interval_kind": "wilson_pointwise",
    }


# -------------------------------------------------------------------------------------
# Top-level payloads
# -------------------------------------------------------------------------------------


def summarize_analysis(
    records: Sequence[dict],
    benchmarks: dict[str, dict] | None = None,
    convergence: Sequence[dict] | None = None,
    n_bootstrap: int = DEFAULT_N_BOOTSTRAP,
    require_substantive_modes: bool = True,
    non_inferential: bool = False,
) -> dict[str, Any]:
    """Full preregistered V3 summary. No gates, no support status, no V2 reinterpretation."""
    records = [parse_record(row) for row in records]
    mode_report = check_uniform_substantive_modes(records)
    if require_substantive_modes:
        require_uniform_substantive_modes(records)
    cells = sorted({str(r.get("cell_id")) for r in records if r.get("cell_id")})
    seeds = sorted({parse_seed(r["seed"]) for r in records if r.get("seed", "") != "" and r.get("seed") is not None})
    payload: dict[str, Any] = {
        "n_records": len(records),
        "n_cells": len(cells),
        "cells": cells,
        "n_unique_seeds": len(seeds),
        "mode_report": mode_report,
        "interval_semantics": INTERVAL_SEMANTICS,
        "n_bootstrap_across_seeds": int(n_bootstrap),
        "bootstrap_resampling_unit": "seed",
        "sesoi_role": SESOI_ROLE,
        "sesoi": SESOI,
        "legacy_v2_orientation_only": LEGACY_V2_ORIENTATION_ONLY,
        "gates": {},
        "primary_families": PRIMARY_FAMILIES,
        "pairing_tiers": PAIRING_TIERS,
        "pairing_tier_semantics": TIER_SEMANTICS,
        "v2_authoritative_status": V2_AUTHORITATIVE_STATUS,
        "block_A_pumping_attenuation": block_a_attenuation(records, n_bootstrap),
        "block_A_prime_cadence_anchor": block_a_prime_cadence(records, n_bootstrap),
        "block_B_coupling": block_b_coupling(records, benchmarks, n_bootstrap),
        "block_C_identification": block_c_identification(records, n_bootstrap),
        "block_D_factorial": block_d_factorial(records, None, n_bootstrap),
        "benchmark_layers": benchmark_merge(records, benchmarks, n_bootstrap),
        "benchmark_convergence": benchmark_convergence_report(convergence),
        "estimability": estimability_summary(records),
        "prediction_vs_intervention": prediction_vs_intervention(records, n_bootstrap),
        "rate_outcomes": rate_outcome_summary(records),
        "recombination_diagnostics": {
            "quantities": ["nire_recomb_trueA_hatB", "nire_recomb_hatA_trueB"],
            "semantics": RECOMBINATION_SEMANTICS,
        },
        "paper_claim_boundaries": {
            "structural_statement_restricted_to": (
                "the frozen own-pumping, one-mode local response family under the known-truth "
                "intervention"
            ),
            "not_licensed_from_v3_alone": [
                "Andhra Pradesh groundwater parameters are identified",
                "actual AP pumping-error magnitude follows the synthetic model",
                "M1L is empirically validated",
                "M1N is validated",
                "a calibrated real groundwater network exists",
                "no local groundwater model can represent cross-node dynamics",
            ],
        },
        "no_p_values": True,
        "no_significance_declarations": True,
        "no_support_status_override": True,
        "reinterprets_v2": False,
        "non_inferential": bool(non_inferential),
    }
    assert_no_gates(payload)
    return payload


def summarize_records(
    records: Sequence[dict],
    benchmarks: dict | None = None,
    convergence: Sequence[dict] | None = None,
    n_bootstrap: int = 200,
) -> dict[str, Any]:
    """Lightweight non-inferential wrapper used by the engineering smoke.

    Same code path as the frozen ANALYSIS summarizer, with a reduced bootstrap count and
    without the substantive-mode requirement, so the smoke can exercise every branch
    without pretending to be an inferential result.
    """
    payload = summarize_analysis(
        records,
        benchmarks=benchmarks if isinstance(benchmarks, dict) else None,
        convergence=convergence,
        n_bootstrap=n_bootstrap,
        require_substantive_modes=False,
        non_inferential=True,
    )
    payload["block_d_factorial"] = payload["block_D_factorial"]
    payload["benchmarks_merged"] = bool(benchmarks)
    assert_no_gates(payload)
    return payload
