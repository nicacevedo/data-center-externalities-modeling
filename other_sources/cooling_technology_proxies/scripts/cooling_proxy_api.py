"""Fail-closed annual cooling source-scenario proxy.

LEVEL 1 only. Does not construct hourly PUE/WUE.
Never independently samples PUE and WUE.
Never averages climates, facility classes, or liquid subtypes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "data_processed" / "cooling_proxy_scenarios.parquet"
DOMAIN = ROOT / "data_processed" / "SUPPORTED_DOMAIN_MATRIX.csv"

WATER_BOUNDARY_WARNING = (
    "Returned WUE_site_model is a source-model onsite conditioning-water intensity "
    "(Lei/Masanet WUE-site construction: humidification and/or adiabatic water plus, "
    "where towers exist, evaporation + windage/drift + draw-off/blowdown). "
    "It is not automatically municipal withdrawal, consumption, RO reject, sewer discharge, "
    "or groundwater pumping."
)

SCENARIO_SEMANTICS = (
    "Each row is one Lei et al. 2025 source-model annual scenario (LHS operational draw), "
    "not an empirical observation of a real facility. Source 5th/95th are source-scenario "
    "quantiles, not confidence intervals or population frequencies."
)


class CoolingProxyUnsupportedError(ValueError):
    """Raised when the requested combination is outside the supported domain."""


@dataclass
class CoolingScenarioResult:
    rows: pd.DataFrame
    n: int
    technology: str
    climate: str
    facility_class: str
    liquid_subtype: str
    source_scope_status: str
    source_case_original: list
    scenario_ids: list
    weighting: Optional[str]
    water_boundary_warning: str = WATER_BOUNDARY_WARNING
    scenario_semantics: str = SCENARIO_SEMANTICS
    model_tier: str = "LEVEL_1_ANNUAL_SOURCE_SCENARIO"
    paired_pue_wue: bool = True
    evidence_grade: dict = field(default_factory=dict)

    def sample_pairs(self, n=None, rng=None):
        if self.weighting != "DESIGN_PRIOR_UNIFORM":
            raise CoolingProxyUnsupportedError(
                "Sampling requires scenario_weighting='DESIGN_PRIOR_UNIFORM' "
                "(equal weights over the source ensemble, not an empirical frequency)."
            )
        df = self.rows
        if n is None:
            return df[["PUE", "WUE_site_model", "scenario_id"]].copy()
        return df.sample(n=n, replace=True, random_state=rng)[["PUE", "WUE_site_model", "scenario_id"]]


def _load():
    if not SCENARIOS.exists():
        raise FileNotFoundError(SCENARIOS)
    return pd.read_parquet(SCENARIOS)


def get_cooling_scenarios(
    technology,
    climate,
    facility_class,
    liquid_subtype=None,
    include_source_extra=False,
    scenario_weighting=None,
    df=None,
):
    """Return paired annual source-model scenarios for an exact supported cell.

    Parameters
    ----------
    technology : tech_id (e.g. AE_AD_ACC) or exact Lei cooling-system label
    climate : IECC/ASHRAE zone string (e.g. '5B')
    facility_class : Lei 'Data center size' (Large-scale / Midsize / Small)
    liquid_subtype : required for liquid technologies; NOT_APPLICABLE or None for air-IT
    include_source_extra : must be True to retrieve Cases 17/18
    scenario_weighting : None (return ensemble only) or 'DESIGN_PRIOR_UNIFORM'
    """
    if scenario_weighting not in (None, "DESIGN_PRIOR_UNIFORM"):
        raise CoolingProxyUnsupportedError(
            "scenario_weighting must be None or 'DESIGN_PRIOR_UNIFORM'"
        )
    data = df if df is not None else _load()

    tech = str(technology)
    if tech in set(data["tech_id"].astype(str)):
        mask = data["tech_id"].astype(str) == tech
    elif tech in set(data["Cooling system"].astype(str)):
        mask = data["Cooling system"].astype(str) == tech
    else:
        raise CoolingProxyUnsupportedError(f"Unknown technology: {technology}")

    sub = data.loc[mask]
    is_liquid = bool(sub["liquid_it"].iloc[0]) if len(sub) else False

    if is_liquid:
        if liquid_subtype in (None, "", "NOT_APPLICABLE"):
            raise CoolingProxyUnsupportedError(
                "Liquid technologies require liquid_subtype in "
                "{REAR_DOOR_HEAT_EXCHANGER, DIRECT_TO_CHIP_COLD_PLATE, IMMERSION}. "
                "Silent pooling is not allowed."
            )
        sub = sub[sub["liquid_cooling_type"] == liquid_subtype]
    else:
        if liquid_subtype not in (None, "", "NOT_APPLICABLE"):
            raise CoolingProxyUnsupportedError(
                "Air-IT technologies only accept liquid_subtype NOT_APPLICABLE or None"
            )
        sub = sub[sub["liquid_cooling_type"] == "NOT_APPLICABLE"]

    sub = sub[sub["Climate Zone"].astype(str) == str(climate)]
    sub = sub[sub["Data center size"].astype(str) == str(facility_class)]

    if sub.empty:
        raise CoolingProxyUnsupportedError(
            f"Unsupported combination: technology={technology!r}, climate={climate!r}, "
            f"facility_class={facility_class!r}, liquid_subtype={liquid_subtype!r}. "
            "No nearest-neighbor, climate average, or technology average is applied."
        )

    scopes = set(sub["source_scope_status"].astype(str))
    if "SOURCE_EXTRA_EXTENDED" in scopes and not include_source_extra:
        raise CoolingProxyUnsupportedError(
            "Cases 17/18 are SOURCE_EXTRA_EXTENDED and require include_source_extra=True"
        )

    liq = "NOT_APPLICABLE" if not is_liquid else str(liquid_subtype)
    evidence = {
        "source_semantics": "PASS",
        "source_reproduction": "PASS_estimator_on_csv",
        "model_lineage": "SAME_LEI_MASANET_LINEAGE",
        "independent_or_operator_validation": "PARTIAL_or_UNSUPPORTED_see_matrix",
        "temporal_resolution": "annual_source_scenario",
        "quantile_semantics": "SOURCE_SCENARIO_QUANTILE",
    }
    return CoolingScenarioResult(
        rows=sub.copy(),
        n=int(len(sub)),
        technology=str(sub["tech_id"].iloc[0]),
        climate=str(climate),
        facility_class=str(facility_class),
        liquid_subtype=liq,
        source_scope_status=str(sub["source_scope_status"].iloc[0]),
        source_case_original=sorted(sub["Case (Original)"].astype(str).unique().tolist()),
        scenario_ids=sub["scenario_id"].tolist(),
        weighting=scenario_weighting,
        evidence_grade=evidence,
    )
