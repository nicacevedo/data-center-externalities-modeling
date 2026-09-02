"""Mutually exclusive cooling-regime taxonomy. Exhaustive on usable hours."""
from __future__ import annotations

CATEGORIES = (
    "HUMIDIFICATION",
    "OA_FREE",
    "HIGH_RH_MIXING",
    "EVAP_COOLING",
    "MECHANICAL_COOLING",
    "UNRESOLVED",
)

NATIVE_TO_COMMON = {
    ("PRN1", "A_MIXED_AIR_HUMIDIFICATION"): "HUMIDIFICATION",
    ("PRN1", "C_DRY_FREE_OUTSIDE_AIR"): "OA_FREE",
    ("PRN1", "D_EVAPORATIVE_COOLING"): "EVAP_COOLING",
    ("PRN1", "E_EVAPORATIVE_COOLING_HIGH_WB"): "EVAP_COOLING",
    ("PRN1", "F_HIGH_HUMIDITY_MIX_SPRAY_BYPASS"): "HIGH_RH_MIXING",
    ("PRN1", "G_RH_OR_TEMP_MIX_SPRAY_BYPASS"): "HIGH_RH_MIXING",
    ("PRN1", "H_UNACCEPTABLE_OA_MIN_OA_RECIRC"): "UNRESOLVED",
    ("FC", "OA_FREE_COOLING"): "OA_FREE",
    ("FC", "HIGH_RH_RETURN_AIR_MIXING"): "HIGH_RH_MIXING",
    ("FC", "EVAPORATIVE_COOLING"): "EVAP_COOLING",
    ("FC", "DX_REQUIRED"): "MECHANICAL_COOLING",
    ("FC", "DX_REQUIRED_DEHUMIDIFY"): "MECHANICAL_COOLING",
    ("FC", "WEATHER_MISSING"): "UNRESOLVED",
}


class TaxonomyError(ValueError):
    pass


def assert_exactly_one(category: str) -> dict[str, int]:
    if category not in CATEGORIES:
        raise TaxonomyError(category)
    ind = {c: int(c == category) for c in CATEGORIES}
    if sum(ind.values()) != 1:
        raise TaxonomyError(f"not exclusive: {category}")
    return ind


def mapping_table_rows() -> list[dict]:
    rows = [
        {
            "site": "PRN1",
            "native_mode": "B_100PCT_OA_HUMIDIFICATION_OR_COOLING",
            "split_key": "primary_control_objective",
            "common_category_if_HUMIDIFICATION": "HUMIDIFICATION",
            "common_category_if_COOLING": "EVAP_COOLING",
            "notes": "Split on primary_control_objective; not substring search.",
        }
    ]
    for (site, mode), cat in NATIVE_TO_COMMON.items():
        rows.append({"site": site, "native_mode": mode, "split_key": "", "common_category": cat})
    return rows


def classify_hour(site: str, native_mode: str, *, primary_control_objective=None, weather_missing: bool = False) -> str:
    if weather_missing or native_mode in {"WEATHER_MISSING", "", None}:
        return "UNRESOLVED"
    site_key = str(site).upper()
    if site_key in {"FOREST_CITY", "FC1", "FRC"}:
        site_key = "FC"
    if site_key in {"PRN", "PRINEVILLE"}:
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
    if site_key == "FC" and "DX" in mode.upper():
        assert_exactly_one("MECHANICAL_COOLING")
        return "MECHANICAL_COOLING"
    assert_exactly_one("UNRESOLVED")
    return "UNRESOLVED"
