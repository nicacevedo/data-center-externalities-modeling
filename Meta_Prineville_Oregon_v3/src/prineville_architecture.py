"""Building-level architecture registry, campus aggregation, and fail-closed CHW.

ARCHITECTURE and CAMPUS AGGREGATION layers. No water fitting.
Quantitative chilled-water conditioning water is UNIDENTIFIED without condenser evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "config" / "prineville_architecture_states.yaml"


class UnidentifiedChilledWaterConditioning(ValueError):
    """Quantitative CHW water is not identified (no condenser / load-share evidence)."""


class UnidentifiedBuildingLoadShares(ValueError):
    """Campus totals cannot be formed when λ_b is UNKNOWN."""


class UnidentifiedArchitectureWater(ValueError):
    """Asked for quantitative water from an unidentified architecture class."""


@dataclass(frozen=True)
class ArchitectureState:
    building_id: str
    phase: str
    architecture_class: str
    earliest_possible_start: str | None
    confirmed_operational_by: str | None
    end_date: str | None
    date_precision: str
    air_side_mechanism: str
    liquid_side_mechanism: str
    heat_rejection_mechanism: str
    water_consuming_mechanism: str
    controller_evidence_class: str
    served_load_share: str | float
    condenser_type: str
    source_ids: str
    confidence: str
    unresolved_fields: str
    notes: str = ""

    def load_share_numeric(self) -> float | None:
        if self.served_load_share in (None, "UNKNOWN", "UNIDENTIFIED"):
            return None
        return float(self.served_load_share)


def _load_yaml(path: Path) -> dict:
    text = path.read_text()
    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("PyYAML is required to load the architecture registry.") from exc
    return yaml.safe_load(text)


def load_architecture_registry(path: Path | None = None) -> list[ArchitectureState]:
    data = _load_yaml(path or DEFAULT_REGISTRY)
    rows = data.get("buildings") or data.get("states") or []
    out: list[ArchitectureState] = []
    for row in rows:
        out.append(
            ArchitectureState(
                building_id=str(row["building_id"]),
                phase=str(row["phase"]),
                architecture_class=str(row["architecture_class"]),
                earliest_possible_start=row.get("earliest_possible_start"),
                confirmed_operational_by=row.get("confirmed_operational_by"),
                end_date=row.get("end_date"),
                date_precision=str(row.get("date_precision", "UNKNOWN")),
                air_side_mechanism=str(row.get("air_side_mechanism", "UNKNOWN")),
                liquid_side_mechanism=str(row.get("liquid_side_mechanism", "UNKNOWN")),
                heat_rejection_mechanism=str(row.get("heat_rejection_mechanism", "UNKNOWN")),
                water_consuming_mechanism=str(row.get("water_consuming_mechanism", "UNKNOWN")),
                controller_evidence_class=str(row.get("controller_evidence_class", "UNIDENTIFIED")),
                served_load_share=row.get("served_load_share", "UNKNOWN"),
                condenser_type=str(row.get("condenser_type", "UNKNOWN")),
                source_ids=str(row.get("source_ids", "")),
                confidence=str(row.get("confidence", "UNKNOWN")),
                unresolved_fields=str(row.get("unresolved_fields", "")),
                notes=str(row.get("notes", "")),
            )
        )
    return out


def architecture_at(states: list[ArchitectureState], building_id: str, date_iso: str) -> list[ArchitectureState]:
    """Return A_{b,t} records whose interval covers date_iso (inclusive start; exclusive end if set)."""
    hits = []
    for s in states:
        if s.building_id != building_id:
            continue
        if s.earliest_possible_start and date_iso < str(s.earliest_possible_start):
            continue
        if s.end_date and date_iso >= str(s.end_date):
            continue
        hits.append(s)
    return hits


def chilled_water_conditioning_water(*_args, **_kwargs) -> float:
    """Fail closed: no tower, dry-cooler, or WUE coefficient without condenser evidence."""
    raise UnidentifiedChilledWaterConditioning(
        "CHILLED_WATER_AIR_COOLING_PRESENT is architecture metadata only. "
        "heat_rejection_type=UNKNOWN, condenser_type=UNKNOWN, served_load_share=UNKNOWN, "
        "conditioning_water_model=UNIDENTIFIED. No quantitative chiller-water prediction."
    )


def building_conditioning_water_allowed(state: ArchitectureState) -> str:
    if state.architecture_class == "DIRECT_OUTSIDE_AIR_EVAP":
        return "QUANTITATIVE_CONDITIONING_WATER_DEFINED"
    if state.architecture_class == "CHILLED_WATER_AIR_COOLING":
        return "UNIDENTIFIED"
    return "UNIDENTIFIED"


def validate_load_shares(lambdas: dict[str, float]) -> dict[str, float]:
    vals = {k: float(v) for k, v in lambdas.items()}
    arr = np.array(list(vals.values()), dtype=float)
    if np.any(~np.isfinite(arr)):
        raise ValueError("Load shares must be finite.")
    if np.any(arr < -1e-15):
        raise ValueError("Load shares must be nonnegative (lambda >= 0).")
    s = float(arr.sum())
    if abs(s - 1.0) > 1e-8:
        raise ValueError(f"Load shares must sum to 1 when supplied; sum={s}.")
    return vals


def aggregate_campus(
    building_outputs: dict[str, dict[str, Any]],
    lambdas: dict[str, float] | None,
) -> dict[str, Any]:
    """P_IT,campus = sum_b P_IT,b and W_conditioning,campus = sum_b W_b when λ known.

    If any share is UNKNOWN, do not silently equal-weight.
    """
    if lambdas is None or any(
        v in (None, "UNKNOWN", "UNIDENTIFIED") for v in (lambdas or {}).values()
    ):
        raise UnidentifiedBuildingLoadShares(
            "Building load shares lambda_b,t are UNKNOWN. "
            "The system will not fabricate a campus-total prediction by equal weighting."
        )
    shares = validate_load_shares(lambdas)
    missing = [b for b in shares if b not in building_outputs]
    if missing:
        raise KeyError(f"Missing building outputs for load shares: {missing}")
    p_it = 0.0
    w_cond = 0.0
    for b, lam in shares.items():
        out = building_outputs[b]
        if out.get("conditioning_water_status") == "UNIDENTIFIED":
            raise UnidentifiedArchitectureWater(
                f"Building {b} conditioning water is UNIDENTIFIED; campus total is not identified."
            )
        p_it += lam * float(out["p_it_mw"])
        w_cond += float(out["water_conditioning_total_m3_h"])
    return {
        "p_it_campus_mw": p_it,
        "water_conditioning_campus_m3_h": w_cond,
        "water_boundary": "CONDITIONING_SITE_WATER",
        "load_shares": shares,
        "campus_total_scientifically_identified": True,
        "aggregation_status": "IDENTIFIED_FROM_SUPPLIED_SHARES",
    }
