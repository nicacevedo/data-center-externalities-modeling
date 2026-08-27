"""Follow-up v1 tests: crosswalk, UE.xlsx shape, Table 3 coverage. No Meta water."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path("/home/nacevedo/RA/data-center-externalities-modeling/other_sources/masanet")
sys.path.insert(0, str(ROOT / "scripts"))

from common import ARCHETYPE_PARAMS, UPSTREAM  # noqa: E402
from followup_common import (  # noqa: E402
    PAPER_CASES,
    UE_CLIMATE_ZONES,
    active_params_for_function,
    table3_ranges,
)


def test_ten_cases_map_exactly_once():
    assert set(PAPER_CASES) == set(range(1, 11))
    fns = [PAPER_CASES[c]["top_level_code_function"] for c in range(1, 11)]
    assert all(f in ARCHETYPE_PARAMS for f in fns)
    # unique mapping of (function, size_class)
    pairs = [(PAPER_CASES[c]["top_level_code_function"], PAPER_CASES[c]["size_class"]) for c in range(1, 11)]
    assert len(pairs) == len(set(pairs))


def test_every_required_code_input_has_active_range():
    for c in range(1, 11):
        active = active_params_for_function(c)
        fn = PAPER_CASES[c]["top_level_code_function"]
        required = [n for n in ARCHETYPE_PARAMS[fn] if n not in ("T_oa", "RH_oa", "P_oa")]
        assert set(active) == set(required)
        for n, sp in active.items():
            assert not sp["inactive"]
            assert sp["lo"] is not None and sp["hi"] is not None
            assert sp["lo"] <= sp["hi"]


def test_inactive_equipment_is_na_not_defaulted():
    spec = table3_ranges(10)
    assert spec["Windage_p"]["inactive"]
    assert spec["CC"]["inactive"]
    assert spec["Chiller_load"]["inactive"]
    spec1 = table3_ranges(1)
    assert spec1["Pump_Pressure_WE"]["inactive"]
    assert spec1["HTE"]["inactive"]
    spec2 = table3_ranges(2)
    assert not spec2["Pump_Pressure_WE"]["inactive"]


def test_ue_xlsx_10x15x2():
    ue = pd.read_excel(UPSTREAM / "Simulation Results" / "UE.xlsx")
    assert len(ue) == 300
    assert sorted(ue["Case"].unique().tolist()) == list(range(1, 11))
    zones = sorted(ue["Climate Zone"].unique().tolist())
    assert zones == UE_CLIMATE_ZONES
    assert len(zones) == 15
    assert set(ue["Quantile"].unique()) == {"5th", "95th"}


def test_rh_bounds_not_physically_reversed_in_code_mapping():
    for c in range(1, 11):
        sp = table3_ranges(c)
        assert sp["RH_up"]["lo"] > sp["RH_lw"]["hi"] or sp["RH_up"]["lo"] >= 50
        assert sp["T_up"]["lo"] >= sp["T_lw"]["hi"] or sp["T_up"]["lo"] > sp["T_lw"]["lo"]
        assert sp["dp_up"]["lo"] > sp["dp_lw"]["hi"]


def test_lighting_large_scale_is_fraction_not_percent():
    sp = table3_ranges(1)["L_percentage"]
    assert sp["hi"] == pytest.approx(0.002)
    sp5 = table3_ranges(5)["L_percentage"]
    assert sp5["lo"] == pytest.approx(0.02)
    assert sp5["hi"] == pytest.approx(0.05)


def test_case_vector_has_no_silent_defaults():
    from followup_common import case_vector

    with pytest.raises(KeyError, match="no silent defaults"):
        case_vector(1, {"T_oa": 20.0, "RH_oa": 50.0, "P_oa": 101325.0}, {})
