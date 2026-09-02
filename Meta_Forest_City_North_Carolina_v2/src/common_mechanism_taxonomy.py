"""Mutually exclusive hourly mechanism taxonomy for Prineville and Forest City.

Every classified hour maps to EXACTLY one of:
  HUMIDIFICATION, OA_FREE, HIGH_RH_MIXING, EVAP_COOLING,
  MECHANICAL_COOLING, UNRESOLVED.

Classification uses the native controller's documented objective / actuators,
not overlapping substring searches on mode labels.
"""
from __future__ import annotations

from typing import Iterable

CATEGORIES: tuple[str, ...] = (
    "HUMIDIFICATION",
    "OA_FREE",
    "HIGH_RH_MIXING",
    "EVAP_COOLING",
    "MECHANICAL_COOLING",
    "UNRESOLVED",
)

# Native-site mode -> common category when the mapping is 1:1.
# B is split by primary_control_objective (see classify_hour).
NATIVE_TO_COMMON: dict[tuple[str, str], str] = {
    # Prineville OCP Appendix A (structural-reference-v1)
    ("PRN1", "A_MIXED_AIR_HUMIDIFICATION"): "HUMIDIFICATION",
    ("PRN1", "C_DRY_FREE_OUTSIDE_AIR"): "OA_FREE",
    ("PRN1", "D_EVAPORATIVE_COOLING"): "EVAP_COOLING",
    ("PRN1", "E_EVAPORATIVE_COOLING_HIGH_WB"): "EVAP_COOLING",
    ("PRN1", "F_HIGH_HUMIDITY_MIX_SPRAY_BYPASS"): "HIGH_RH_MIXING",
    ("PRN1", "G_RH_OR_TEMP_MIX_SPRAY_BYPASS"): "HIGH_RH_MIXING",
    ("PRN1", "H_UNACCEPTABLE_OA_MIN_OA_RECIRC"): "UNRESOLVED",
    # Forest City local controller
    ("FC", "OA_FREE_COOLING"): "OA_FREE",
    ("FC", "HIGH_RH_RETURN_AIR_MIXING"): "HIGH_RH_MIXING",
    ("FC", "EVAPORATIVE_COOLING"): "EVAP_COOLING",
    ("FC", "DX_REQUIRED"): "MECHANICAL_COOLING",
    ("FC", "DX_REQUIRED_DEHUMIDIFY"): "MECHANICAL_COOLING",
    ("FC", "WEATHER_MISSING"): "UNRESOLVED",
}

MAPPING_NOTES = {
    ("PRN1", "A_MIXED_AIR_HUMIDIFICATION"): (
        "Humidity-target mixed-air ECH. Primary objective HUMIDIFICATION."
    ),
    ("PRN1", "B_100PCT_OA_HUMIDIFICATION_OR_COOLING"): (
        "Split: primary_control_objective HUMIDIFICATION -> HUMIDIFICATION; "
        "COOLING (OA above SAT max, temperature-driven direct evap) -> EVAP_COOLING. "
        "Not both; not substring search."
    ),
    ("PRN1", "C_DRY_FREE_OUTSIDE_AIR"): "100% OA; spray off; envelope already satisfied.",
    ("PRN1", "D_EVAPORATIVE_COOLING"): "Temperature-driven 100% OA direct evap toward SAT max.",
    ("PRN1", "E_EVAPORATIVE_COOLING_HIGH_WB"): "Same actuator purpose as D at higher wet-bulb.",
    ("PRN1", "F_HIGH_HUMIDITY_MIX_SPRAY_BYPASS"): "OA/RA mix to cap RH; spray bypassed.",
    ("PRN1", "G_RH_OR_TEMP_MIX_SPRAY_BYPASS"): "OA/RA mix to cap RH or SAT; spray bypassed.",
    ("PRN1", "H_UNACCEPTABLE_OA_MIN_OA_RECIRC"): (
        "Smoke/dust recirculation; IEC not installed. Not a weather-driven cooling mode."
    ),
    ("FC", "OA_FREE_COOLING"): "OA already inside 85 F / 90% RH; evaporative and DX off.",
    ("FC", "HIGH_RH_RETURN_AIR_MIXING"): "Hot-RA mix to meet 90% RH cap; evaporative off.",
    ("FC", "EVAPORATIVE_COOLING"): "100% OA evaporative cooling toward 85 F.",
    ("FC", "DX_REQUIRED"): "Documented DX backup when evaporative/mix cannot meet envelope.",
    ("FC", "DX_REQUIRED_DEHUMIDIFY"): "DX backup when mix cannot meet RH and T caps.",
    ("FC", "WEATHER_MISSING"): "No outdoor state; not a physical mode.",
}


class TaxonomyError(ValueError):
    pass


def category_indicators(category: str) -> dict[str, int]:
    if category not in CATEGORIES:
        raise TaxonomyError(f"Unknown category {category!r}")
    return {c: int(c == category) for c in CATEGORIES}


def assert_exactly_one(category: str) -> dict[str, int]:
    ind = category_indicators(category)
    if sum(ind.values()) != 1:
        raise TaxonomyError(f"sum(category_indicators) != 1 for {category!r}")
    return ind


def classify_hour(
    site: str,
    native_mode: str,
    *,
    primary_control_objective: str | None = None,
    weather_missing: bool = False,
) -> str:
    """Map one native controller hour to exactly one common category."""
    if weather_missing or native_mode in {"WEATHER_MISSING", "", None}:
        cat = "UNRESOLVED"
        assert_exactly_one(cat)
        return cat

    site_key = str(site).upper()
    if site_key in {"FOREST_CITY", "FOREST CITY", "FC1", "FRC"}:
        site_key = "FC"
    if site_key in {"PRN", "PRINEVILLE", "PRN1_OCP"}:
        site_key = "PRN1"

    mode = str(native_mode)

    if site_key == "PRN1" and mode == "B_100PCT_OA_HUMIDIFICATION_OR_COOLING":
        obj = (primary_control_objective or "").upper()
        if obj == "COOLING":
            cat = "EVAP_COOLING"
        elif obj == "HUMIDIFICATION":
            cat = "HUMIDIFICATION"
        else:
            cat = "UNRESOLVED"
        assert_exactly_one(cat)
        return cat

    key = (site_key, mode)
    if key in NATIVE_TO_COMMON:
        cat = NATIVE_TO_COMMON[key]
        assert_exactly_one(cat)
        return cat

    # DX family fallback for Forest City without promoting unknown modes.
    if site_key == "FC" and "DX" in mode.upper():
        cat = "MECHANICAL_COOLING"
        assert_exactly_one(cat)
        return cat

    cat = "UNRESOLVED"
    assert_exactly_one(cat)
    return cat


def mapping_table_rows() -> list[dict]:
    rows = []
    seen = set(NATIVE_TO_COMMON)
    rows.append(
        {
            "site": "PRN1",
            "native_mode": "B_100PCT_OA_HUMIDIFICATION_OR_COOLING",
            "split_key": "primary_control_objective",
            "common_category_if_HUMIDIFICATION": "HUMIDIFICATION",
            "common_category_if_COOLING": "EVAP_COOLING",
            "notes": MAPPING_NOTES[("PRN1", "B_100PCT_OA_HUMIDIFICATION_OR_COOLING")],
        }
    )
    for (site, mode), cat in NATIVE_TO_COMMON.items():
        rows.append(
            {
                "site": site,
                "native_mode": mode,
                "split_key": "",
                "common_category": cat,
                "notes": MAPPING_NOTES.get(key := (site, mode), ""),
            }
        )
        seen.add((site, mode))
    return rows


def assert_frame_exclusive(categories: Iterable[str]) -> None:
    for i, c in enumerate(categories):
        ind = assert_exactly_one(c)
        if sum(ind.values()) != 1:
            raise TaxonomyError(f"row {i}: not exclusive")
