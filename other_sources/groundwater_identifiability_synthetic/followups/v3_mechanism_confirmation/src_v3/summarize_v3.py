"""V3 summarizer: continuous reporting, no gates, pointwise intervals, Block D factorial.

Reported 95% bootstrap and Wilson intervals are pointwise Monte Carlo uncertainty
intervals for their individual estimands. They are not simultaneous family-wise
confidence bands over all V3 contrasts.

No p-values. No significance declarations. No SESOI-derived pass/fail/gate/support.
"""

from __future__ import annotations

from typing import Any

import numpy as np

INTERVAL_SEMANTICS = (
    "Reported 95% bootstrap and Wilson intervals are pointwise Monte Carlo "
    "uncertainty intervals for their individual estimands. They are not "
    "simultaneous family-wise confidence bands over all V3 contrasts."
)

FORBIDDEN_INFERENTIAL_FIELDS = ("pass", "fail", "gate_status", "support_status")

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

SESOI = {"nire": 0.05, "rate_difference": 0.10, "reliability_discrepancy": 0.05}
SESOI_ROLE = "preregistered SESOI / decision-relevance reference magnitudes, NOT gates"


def wilson_interval(successes: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return float("nan"), float("nan")
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / denom
    half = z * np.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / denom
    return float(centre - half), float(centre + half)


def assert_no_gates(payload: dict[str, Any]) -> None:
    flat_keys = set(payload)
    if any(k in FORBIDDEN_INFERENTIAL_FIELDS for k in flat_keys):
        raise ValueError(f"V3 summarizer emitted forbidden inferential fields: {sorted(flat_keys & set(FORBIDDEN_INFERENTIAL_FIELDS))}")


def _by_cell_seed(records: list[dict], cell_id: str, metric: str) -> dict[int, float]:
    out = {}
    for row in records:
        if row.get("cell_id") != cell_id:
            continue
        seed = int(row["seed"])
        out[seed] = float(row.get(metric, np.nan))
    return out


def block_d_factorial(records: list[dict], metrics: tuple[str, ...] | None = None) -> dict[str, Any]:
    """3 main effects, 3 two-way, 1 three-way (secondary) using same-seed pairing."""
    metrics = metrics or ("placebo_false_effect_L", "placebo_relative_to_true_L")
    pumping_levels = ("P-EXACT", "P-MULTNOISE")
    recharge_levels = ("R-EXACT", "R-NOISE")
    rho_levels = (0.0, 0.3)

    def coded(p, r, c):
        return (
            1.0 if p == "P-MULTNOISE" else -1.0,
            1.0 if r == "R-NOISE" else -1.0,
            1.0 if c == 0.3 else -1.0,
        )

    result: dict[str, Any] = {
        "interval_semantics": INTERVAL_SEMANTICS,
        "three_way_role": "preregistered secondary/descriptive",
        "sesoi_role": SESOI_ROLE,
        "sesoi": SESOI,
        "outcomes": {},
    }
    for metric in metrics:
        cells = {
            key: _by_cell_seed(records, cid, metric) for key, cid in BLOCK_D_CELLS.items()
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
                "pointwise_interval": (
                    float(np.quantile(arr, 0.025)),
                    float(np.quantile(arr, 0.975)),
                )
                if arr.size >= 8
                else (float("nan"), float("nan")),
                "primary": name != "int_three_way",
            }
        result["outcomes"][metric] = summary
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


def summarize_records(records: list[dict], benchmarks: dict | None = None) -> dict[str, Any]:
    cells = sorted({r["cell_id"] for r in records})
    payload = {
        "n_records": len(records),
        "n_cells": len(cells),
        "interval_semantics": INTERVAL_SEMANTICS,
        "sesoi_role": SESOI_ROLE,
        "sesoi": SESOI,
        "legacy_v2_orientation_only": {"nire": 0.20, "edge_f1": 0.80, "placebo_ratio": 0.20},
        "gates": {},
        "block_d_factorial": block_d_factorial(records),
        "benchmarks_merged": bool(benchmarks),
        "non_inferential": True,
    }
    assert_no_gates(payload)
    return payload
