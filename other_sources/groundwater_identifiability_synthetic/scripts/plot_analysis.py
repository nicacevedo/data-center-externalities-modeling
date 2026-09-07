#!/usr/bin/env python3
"""Deterministic confirmatory figures from frozen ANALYSIS tables only.

Transformations are frozen here before results are inspected:
  1. intervention NIRE vs pumping quality / missingness (cell medians)
  2. prediction RMSE vs intervention NIRE (L and N)
  3. network F1 vs missingness and confounding
  4. data-adequacy supported-complexity map (categorical)
  5. representative impulse: uses nire medians as the frozen proxy when
     full impulse arrays are not persisted (design: scalar replicate records only).
"""

from __future__ import annotations

import csv
from pathlib import Path

import _bootstrap_path  # noqa: F401
import numpy as np

from groundwater_identifiability_synthetic.src.design import MODULE_ROOT

ANALYSIS = MODULE_ROOT / "outputs" / "analysis"
FIGDIR = ANALYSIS / "figures"


def _load(name: str) -> list[dict]:
    path = ANALYSIS / name
    if not path.exists():
        raise SystemExit(f"missing {path}; run summarize_results.py --analysis first")
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _f(row: dict, key: str) -> float:
    try:
        return float(row.get(key, ""))
    except (TypeError, ValueError):
        return float("nan")


def main() -> int:
    import importlib

    FIGDIR.mkdir(parents=True, exist_ok=True)
    adequacy = _load("data_adequacy_map.csv")
    pred = _load("prediction_vs_intervention.csv")
    interv = _load("intervention_recovery.csv")

    plt = None
    try:
        matplotlib = importlib.import_module("matplotlib")
        matplotlib.use("Agg")
        plt = importlib.import_module("matplotlib.pyplot")
    except ImportError:
        print("matplotlib not available; writing figure-data CSVs only")

    def scatter(path, xs, ys, xlabel, ylabel, title):
        data_path = path.with_suffix(".csv")
        with open(data_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["x", "y"])
            for x, y in zip(xs, ys):
                writer.writerow([x, y])
        if plt is None:
            return
        fig, ax = plt.subplots(figsize=(6, 4.5))
        ax.scatter(xs, ys, s=18, alpha=0.7, c="#1f4e79")
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        fig.tight_layout()
        fig.savefig(path, dpi=140)
        plt.close(fig)

    xs = [_f(r, "head_missing_fraction") for r in adequacy]
    ys = [_f(r, "conditional_intervention_error_L") for r in adequacy]
    scatter(
        FIGDIR / "intervention_error_vs_missingness.png",
        xs, ys,
        "head missing fraction",
        "conditional NIRE h26 (L)",
        "Intervention error vs missingness (frozen table)",
    )

    xs = [_f(r, "rmse_test_N_median") for r in pred]
    ys = [_f(r, "nire_persistent_step_h26_N_median") for r in pred]
    scatter(
        FIGDIR / "prediction_vs_intervention_N.png",
        xs, ys,
        "protected RMSE (N)",
        "NIRE h26 (N)",
        "Prediction vs intervention (N; frozen G3 inversion uses these axes)",
    )

    xs = [_f(r, "head_missing_fraction") for r in adequacy]
    ys = [_f(r, "strong_edge_undirected_f1") for r in adequacy]
    scatter(
        FIGDIR / "network_f1_vs_missingness.png",
        xs, ys,
        "head missing fraction",
        "strong_edge_undirected_f1",
        "Network recovery vs missingness",
    )

    xs = [_f(r, "forcing_confounding") for r in adequacy]
    ys = [_f(r, "strong_edge_undirected_f1") for r in adequacy]
    scatter(
        FIGDIR / "network_f1_vs_confounding.png",
        xs, ys,
        "confounding rho",
        "strong_edge_undirected_f1",
        "Network recovery vs confounding",
    )

    # Data-adequacy categorical map: scenario x cadence, status code.
    map_rows = [
        {
            "scenario": r.get("scenario", ""),
            "cadence_k": r.get("cadence_k", ""),
            "local_response_status": r.get("local_response_status", ""),
            "network_dynamics_status": r.get("network_dynamics_status", ""),
            "supported_complexity_status": r.get("supported_complexity_status", ""),
        }
        for r in adequacy
    ]
    with open(FIGDIR / "data_adequacy_map_figure_data.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(map_rows[0]))
        writer.writeheader()
        writer.writerows(map_rows)
    if plt is not None:
        statuses = sorted({r["supported_complexity_status"] for r in map_rows})
        colors = {s: i for i, s in enumerate(statuses)}
        fig, ax = plt.subplots(figsize=(8, 5))
        xs = np.arange(len(map_rows))
        ys = [colors[r["supported_complexity_status"]] for r in map_rows]
        ax.scatter(xs, ys, s=12, c=ys, cmap="tab10")
        ax.set_yticks(list(colors.values()))
        ax.set_yticklabels(list(colors.keys()), fontsize=7)
        ax.set_xlabel("cell index (frozen adequacy table order)")
        ax.set_title("Supported-complexity map (deterministic from frozen table)")
        fig.tight_layout()
        fig.savefig(FIGDIR / "data_adequacy_supported_complexity.png", dpi=140)
        plt.close(fig)

    # Impulse-response proxy: NIRE by model from frozen intervention table (no trajectory arrays).
    with open(FIGDIR / "impulse_response_proxy_nire.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["cell_id", "scenario", "nire_B0", "nire_L", "nire_S", "nire_N"])
        for r in interv:
            writer.writerow([
                r.get("cell_id", ""),
                r.get("scenario", ""),
                r.get("nire_persistent_step_h26_B0", ""),
                r.get("nire_persistent_step_h26_L", ""),
                r.get("nire_persistent_step_h26_S", ""),
                r.get("nire_persistent_step_h26_N", ""),
            ])
    print(f"figures written under {FIGDIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
