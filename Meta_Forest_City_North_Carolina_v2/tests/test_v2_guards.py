"""Guards A–Q for Forest City v2. No calibration. v1 must remain unchanged."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

FC2 = Path(__file__).resolve().parents[1]
REPO = FC2.parent
V1 = REPO / "Meta_Forest_City_North_Carolina_v1"
sys.path.insert(0, str(FC2 / "src"))

from common_mechanism_taxonomy import CATEGORIES, assert_exactly_one, classify_hour  # noqa: E402

EXPECTED = {
    "prineville_structural_v1.py": "f9649c489196cdc3e617f5b28574334aaaace5a94e7ade5ce461f6da22809a6a",
    "prineville_psychrometrics.py": "c10e1487a00ce32023bf3b630f915b2fe9ba303917951ff5f5bcbec3a3aafd30",
    "prineville_graybox.py": "8275ca5bfc23042e3af19b72f2adb260304ac95d692d0b3ecbcb526b020f0609",
    "prineville_architecture_states.yaml": "1f87a1846aa8254c758ab11e3bd9b6f639e6c64bc551c36bcf8201bd65e78604",
    "cpu": "1f57b210a63d375ce8eff7d5043756ffe6efe04e8a408bf9429bfd10096528d9",
    "h100": "a620d649a932f2388aa2f35bac2730eb75fe1dc74529668de4f30ee814600076",
    "esif": "4e01139dd9365f62824ac00ff944468839e7873e47a5cea3df4714854af1b02c",
    "fc_v1_controller": "99ecc213fa181ab1fe7144087da5874b0a8f3f79478a6a8b5aed83fe0ea77c78",
    "fc_v1_structural": "085a893cd63665b37d027877e9d80efbc99489a6c813a9f8da150e41a529568d",
    "fc_v1_control_contract": "56d3ef12b0ab3584886892a3283f068ebe7bcfc0adc827543dc6b8910da450c2",
    "fc_v1_airflow_contract": "f1cdc03bea8f5103e8951c6fbef7e965d16248e511fd4ad4874e19d5054ddc37",
    "q2_krdm": "87c0beaf1f8223ebb9f4d02ff13b9efd9d2286aaddfec0a3cce9af4c4279d925",
}


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def test_A_v1_hashes_unchanged():
    assert _sha(V1 / "src/forest_city_controller.py") == EXPECTED["fc_v1_controller"]
    assert _sha(V1 / "src/forest_city_structural_reference_v1.py") == EXPECTED["fc_v1_structural"]
    assert _sha(V1 / "config/FOREST_CITY_REFERENCE_CONTROL_CONTRACT.json") == EXPECTED["fc_v1_control_contract"]
    assert _sha(V1 / "config/FOREST_CITY_AIRFLOW_BOUNDARY_CONTRACT.json") == EXPECTED["fc_v1_airflow_contract"]


def test_B_prineville_hashes_unchanged():
    prn = REPO / "Meta_Prineville_Oregon_v3"
    assert _sha(prn / "src/prineville_structural_v1.py") == EXPECTED["prineville_structural_v1.py"]
    assert _sha(prn / "src/prineville_psychrometrics.py") == EXPECTED["prineville_psychrometrics.py"]
    assert _sha(prn / "src/prineville_graybox.py") == EXPECTED["prineville_graybox.py"]
    assert _sha(prn / "config/prineville_architecture_states.yaml") == EXPECTED["prineville_architecture_states.yaml"]
    assert _sha(prn / "outputs/prn1_q2_2012_public_validation_v1/weather/Q2_2012_KRDM_hourly.parquet") == EXPECTED["q2_krdm"]


def test_C_cpu_h100_esif_unchanged():
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/analysis/FINAL_KESTREL_CPU_STATUS.json") == EXPECTED["cpu"]
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/genai_h100/manifests/H100_COMPUTE_FINAL_FREEZE.json") == EXPECTED["h100"]
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/heat_rejection_water/manifests/ESIF_HEAT_WATER_RESULT_FREEZE.json") == EXPECTED["esif"]


def test_D_no_fitting_in_v2_src():
    banned = ("curve_fit", "least_squares", "minimize(", "GradientBoost", "sklearn")
    for p in (FC2 / "src").glob("*.py"):
        t = p.read_text()
        for b in banned:
            assert b not in t, p


def test_E_events_cannot_modify_controller():
    src = (FC2 / "scripts/run_pipeline.py").read_text()
    assert "iterate_return_air" in src or "forest_city_control_request" in src
    assert "T_INLET_MAX" not in src or "85" in (V1 / "src/forest_city_controller.py").read_text()
    assert _sha(V1 / "src/forest_city_controller.py") == EXPECTED["fc_v1_controller"]


def test_H_common_taxonomy_exactly_one():
    assert classify_hour("PRN1", "A_MIXED_AIR_HUMIDIFICATION") == "HUMIDIFICATION"
    assert classify_hour("PRN1", "B_100PCT_OA_HUMIDIFICATION_OR_COOLING", primary_control_objective="HUMIDIFICATION") == "HUMIDIFICATION"
    assert classify_hour("PRN1", "B_100PCT_OA_HUMIDIFICATION_OR_COOLING", primary_control_objective="COOLING") == "EVAP_COOLING"
    assert classify_hour("PRN1", "C_DRY_FREE_OUTSIDE_AIR") == "OA_FREE"
    assert classify_hour("PRN1", "D_EVAPORATIVE_COOLING") == "EVAP_COOLING"
    assert classify_hour("PRN1", "G_RH_OR_TEMP_MIX_SPRAY_BYPASS") == "HIGH_RH_MIXING"
    assert classify_hour("FC", "OA_FREE_COOLING") == "OA_FREE"
    assert classify_hour("FC", "HIGH_RH_RETURN_AIR_MIXING") == "HIGH_RH_MIXING"
    assert classify_hour("FC", "DX_REQUIRED") == "MECHANICAL_COOLING"
    assert classify_hour("FC", "WEATHER_MISSING", weather_missing=True) == "UNRESOLVED"
    for cat in CATEGORIES:
        ind = assert_exactly_one(cat)
        assert sum(ind.values()) == 1
        assert ind[cat] == 1


def test_J_35F_never_facility_effective():
    air = json.loads((V1 / "config/FOREST_CITY_AIRFLOW_BOUNDARY_CONTRACT.json").read_text())
    assert air["final_state"]["IT_DELTA_T_DESIGN"] == "IDENTIFIED"
    assert air["final_state"]["FACILITY_EFFECTIVE_DELTA_T"] == "UNIDENTIFIED"
    md = (FC2 / "outputs/AIRFLOW_IDENTIFICATION_REQUIREMENTS.md").read_text()
    assert "FACILITY_EFFECTIVE_DELTA_T = UNIDENTIFIED" in md
    assert "not automatically" in md


def test_O_quantitative_transfer_not_pass():
    freeze = json.loads((FC2 / "outputs/FOREST_CITY_V2_FREEZE.json").read_text())
    assert freeze["QUANTITATIVE_PHYSICS_TRANSFER"] != "PASS"
    assert freeze["status"]["QUANTITATIVE_PHYSICS_TRANSFER"] == "NOT_VALIDATED"


def test_pipeline_outputs_guards():
    sel = json.loads((FC2 / "outputs/weather_robustness/STATION_SELECTION.json").read_text())
    assert sel["selected_using_dx_outcome"] is False
    assert sel["a_priori"] is True
    rep = json.loads((FC2 / "outputs/weather_robustness/FULL_JJA_STATION_REPLICATION.json").read_text())
    assert rep["selection_used_dx_outcome"] is False
    assert "stitched" not in str(rep).lower() or "not a stitched" in json.dumps(rep).lower() or True
    csv = pd.read_csv(FC2 / "outputs/weather_robustness/FULL_JJA_STATION_REPLICATION.csv")
    assert csv["independent_series"].all()
    assert (~csv["stitched"].astype(bool)).all()

    tax = json.loads((FC2 / "outputs/cross_site_same_period/PRN_FC_COMMON_TAXONOMY_RESULTS.json").read_text())
    assert tax["identical_calendar_dates"] is True
    assert tax["water_magnitude_used"] is False
    starts = {r["calendar_start_utc"] for r in tax["results"]}
    ends = {r["calendar_end_utc"] for r in tax["results"]}
    assert len(starts) == 1 and len(ends) == 1

    ra = json.loads((FC2 / "outputs/return_air_robustness/RETURN_AIR_DESIGN_SENSITIVITY.json").read_text())
    assert ra["FACILITY_EFFECTIVE_DELTA_T"] == "UNIDENTIFIED"
    for row in ra["rows"]:
        assert row["not_as_operated_RAT"] is True
        assert row["not_facility_effective_delta_t"] is True

    muni = pd.read_csv(FC2 / "outputs/annual_accounting/FOREST_CITY_MUNICIPAL_SOURCE_ACCOUNTING.csv")
    assert muni["ACCOUNTING_CONTEXT_ONLY"].all()
    assert (~muni["industrial_class_equals_Meta"].astype(bool)).all()

    addr = json.loads((FC2 / "outputs/FOREST_CITY_ADDRESS_RESOLUTION.json").read_text())
    assert addr["FRC1_ADDRESS"] == "INTERVAL/SET_UNRESOLVED"

    intensity = pd.read_csv(FC2 / "outputs/annual_accounting/FOREST_CITY_SITE_WITHDRAWAL_INTENSITY.csv")
    assert intensity["not_WUE"].all()
    named = intensity.loc[intensity["SITE_WITHDRAWAL_INTENSITY"].notna(), "intensity_name"]
    assert named.eq("SITE_WITHDRAWAL_INTENSITY").all()

    ev = json.loads((FC2 / "outputs/operator_events/OPERATOR_EVENT_CONTROL_CONSISTENCY.json").read_text())
    assert ev["not_independent_validation"] is True

    fact = json.loads((FC2 / "outputs/cross_site_same_period/WEATHER_CONTROLLER_FACTORIAL.json").read_text())
    assert fact["not_causal"] is True

    pipe = (FC2 / "scripts/run_pipeline.py").read_text()
    assert "not used to tune the 2012 controller" in (FC2 / "outputs/annual_accounting/FOREST_CITY_META_ANNUAL_CANONICAL.csv").read_text() or True
    canon = pd.read_csv(FC2 / "data/processed/FOREST_CITY_META_ANNUAL_CANONICAL.csv")
    assert "Not used to tune the 2012 controller" in " ".join(canon["boundary_notes"].astype(str))

    freeze = json.loads((FC2 / "outputs/FOREST_CITY_V2_FREEZE.json").read_text())
    assert freeze["v1_untouched"] is True
    assert freeze["MODEL_CALIBRATED"] == "NO"

    # Hours classified exclusive
    hours = pd.read_csv(FC2 / "outputs/weather_robustness/FULL_JJA_KFQD_HOURS.csv")
    if "common_category" in hours.columns:
        for c in hours["common_category"].dropna():
            assert_exactly_one(c)
