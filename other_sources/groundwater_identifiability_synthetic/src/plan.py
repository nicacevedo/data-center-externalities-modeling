"""Enumeration of every cell in the frozen experiment plan.

Kept separate from `design.py` so that the sweep plan is one auditable list: gate cells,
reporting cells, targeted stress curves, and the five named two-factor grids. There is no
generic fractional factorial.
"""

from __future__ import annotations

from typing import Any

from .design import RegimeSpec, gate_cells, reporting_cells, resolve_regime


def _slug(value: Any) -> str:
    return str(value).replace(".", "p").replace("-", "").replace(" ", "")


def stress_curve_cells(design: dict[str, Any]) -> dict[str, RegimeSpec]:
    cells: dict[str, RegimeSpec] = {}
    for name, curve in design["experiment_grid"]["stress_curves"].items():
        factor = curve["vary"]
        for value in curve["values"]:
            cell_id = f"CURVE_{name}_{_slug(value)}"
            cells[cell_id] = resolve_regime(
                design,
                cell_id=cell_id,
                scenario=curve["scenario"],
                topology=curve["topology"],
                overrides={factor: value},
            )
    return cells


def two_factor_grid_cells(design: dict[str, Any]) -> dict[str, RegimeSpec]:
    cells: dict[str, RegimeSpec] = {}
    for name, spec in design["experiment_grid"]["two_factor_grids"].items():
        factors = spec["factors"]
        keys = list(factors)

        if "topology_by_level" in spec:
            # candidate-support level selects the topology; the other factor is ordinary.
            topology_factor = next(k for k in keys if k in spec["topology_by_level"] or k == "candidate_support")
            other = next(k for k in keys if k != topology_factor)
            for level in factors[topology_factor]:
                topology = spec["topology_by_level"][level]
                for value in factors[other]:
                    cell_id = f"GRID_{name}_{_slug(level)}_{_slug(value)}"
                    cells[cell_id] = resolve_regime(
                        design,
                        cell_id=cell_id,
                        scenario=spec["scenario"],
                        topology=topology,
                        overrides={other: value},
                    )
            continue

        first, second = keys
        for a in factors[first]:
            for b in factors[second]:
                cell_id = f"GRID_{name}_{_slug(a)}_{_slug(b)}"
                cells[cell_id] = resolve_regime(
                    design,
                    cell_id=cell_id,
                    scenario=spec["scenario"],
                    topology=spec["topology"],
                    overrides={first: a, second: b},
                )
    return cells


def all_cells(design: dict[str, Any]) -> dict[str, RegimeSpec]:
    """Full frozen plan: gates, reporting, curves, grids."""
    cells: dict[str, RegimeSpec] = {}
    cells.update(gate_cells(design))
    cells.update(reporting_cells(design))
    cells.update(stress_curve_cells(design))
    cells.update(two_factor_grid_cells(design))
    return cells


def plan_summary(design: dict[str, Any]) -> dict[str, int]:
    return {
        "gate_cells": len(gate_cells(design)),
        "reporting_cells": len(reporting_cells(design)),
        "stress_curve_cells": len(stress_curve_cells(design)),
        "two_factor_grid_cells": len(two_factor_grid_cells(design)),
        "total_unique_cells": len(all_cells(design)),
    }
