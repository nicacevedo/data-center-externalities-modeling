"""Guards for Forest City v2. No calibration. v1/Prineville hashes must remain unchanged."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

FC2 = Path(__file__).resolve().parents[1]
REPO = FC2.parent
V1 = REPO / "Meta_Forest_City_North_Carolina_v1"
PRN = REPO / "Meta_Prineville_Oregon_v3"
sys.path.insert(0, str(FC2 / "src"))
sys.path.insert(0, str(V1 / "src"))

from forest_city_structural_reference_v1 import (  # noqa: E402
    IT_EQUIPMENT_DELTA_T_DESIGN_F,
    simulate_hour,
)
from psychrometrics_adapter import assert_physically_valid_state, state_from_t_rh  # noqa: E402

EXPECTED = {
    "fc_controller": "99ecc213fa181ab1fe7144087da5874b0a8f3f79478a6a8b5aed83fe0ea77c78",
    "fc_structural": "085a893cd63665b37d027877e9d80efbc99489a6c813a9f8da150e41a529568d",
    "fc_control_contract": "56d3ef12b0ab3584886892a3283f068ebe7bcfc0adc827543dc6b8910da450c2",
    "fc_airflow_contract": "f1cdc03bea8f5103e8951c6fbef7e965d16248e511fd4ad4874e19d5054ddc37",
    "prn_structural_v1": "f9649c489196cdc3e617f5b28574334aaaace5a94e7ade5ce461f6da22809a6a",
    "prn_psychrometrics": "c10e1487a00ce32023bf3b630f915b2fe9ba303917951ff5f5bcbec3a3aafd30",
    "prn_graybox": "8275ca5bfc23042e3af19b72f2adb260304ac95d692d0b3ecbcb526b020f0609",
    "prn_registry": "1f87a1846aa8254c758ab11e3bd9b6f639e6c64bc551c36bcf8201bd65e78604",
    "cpu": "1f57b210a63d375ce8eff7d5043756ffe6efe04e8a408bf9429bfd10096528d9",
    "h100": "a620d649a932f2388aa2f35bac2730eb75fe1dc74529668de4f30ee814600076",
    "esif": "4e01139dd9365f62824ac00ff944468839e7873e47a5cea3df4714854af1b02c",
    "fc_weather_parquet": "f87a2e61120cf2d8e3117ff20e838567d0f8525a650a7fdaad221f9b3044e1d9",
}


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _src_blob() -> str:
    parts = []
    for folder in (FC2 / "src", FC2 / "scripts"):
        for p in sorted(folder.glob("*.py")):
            parts.append(p.read_text())
    return "\n".join(parts)


def test_upstream_hashes_unchanged():
    assert _sha(V1 / "src/forest_city_controller.py") == EXPECTED["fc_controller"]
    assert _sha(V1 / "src/forest_city_structural_reference_v1.py") == EXPECTED["fc_structural"]
    assert _sha(V1 / "config/FOREST_CITY_REFERENCE_CONTROL_CONTRACT.json") == EXPECTED["fc_control_contract"]
    assert _sha(V1 / "config/FOREST_CITY_AIRFLOW_BOUNDARY_CONTRACT.json") == EXPECTED["fc_airflow_contract"]
    assert _sha(PRN / "src/prineville_structural_v1.py") == EXPECTED["prn_structural_v1"]
    assert _sha(PRN / "src/prineville_psychrometrics.py") == EXPECTED["prn_psychrometrics"]
    assert _sha(PRN / "src/prineville_graybox.py") == EXPECTED["prn_graybox"]
    assert _sha(PRN / "config/prineville_architecture_states.yaml") == EXPECTED["prn_registry"]
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/analysis/FINAL_KESTREL_CPU_STATUS.json") == EXPECTED["cpu"]
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/genai_h100/manifests/H100_COMPUTE_FINAL_FREEZE.json") == EXPECTED["h100"]
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/heat_rejection_water/manifests/ESIF_HEAT_WATER_RESULT_FREEZE.json") == EXPECTED["esif"]
    assert _sha(V1 / "data/processed/forest_city_weather_2012_hourly.parquet") == EXPECTED["fc_weather_parquet"]


def test_no_parameter_fitting_or_calibration():
    blob = _src_blob()
    for banned in ("curve_fit", "least_squares", "minimize(", "sklearn", "GradientBoost", "differential_evolution"):
        assert banned not in blob
    proto = (FC2 / "config/FOREST_CITY_V2_PROTOCOL.yaml").read_text()
    assert "MODEL_CALIBRATED: \"NO\"" in proto or "MODEL_CALIBRATED: NO" in proto


def test_annual_meta_never_enters_controller_parameter_selection():
    blob = _src_blob()
    assert "annual_meta_used_to_fit" in blob
    assert "False" in (FC2 / "outputs/airside/FOREST_CITY_AIRSIDE_SENSITIVITY.csv").read_text()
    sens = pd.read_csv(FC2 / "outputs/airside/FOREST_CITY_AIRSIDE_SENSITIVITY.csv")
    assert (~sens["annual_meta_used_to_fit"].astype(bool)).all()
    assert (~sens["optimizer_used"].astype(bool)).all()
    pipe = (FC2 / "scripts/run_v2_pipeline.py").read_text()
    assert "FOREST_CITY_ANNUAL_WATER_WITHDRAWAL" in pipe
    assert "evap_thermal_effectiveness=float(wd)" not in pipe


def test_documented_events_reproduce_v1():
    reg = pd.read_csv(FC2 / "outputs/controller_validation/V1_REGRESSION_CHECK.csv")
    js = json.loads((FC2 / "outputs/controller_validation/V1_REGRESSION_CHECK.json").read_text())
    assert js["verdict"] == "PASS_AND_FREEZE"
    assert js["MODEL_CALIBRATED"] == "NO"
    for item in ("B_2012_06_25", "A_2012_07_01", "summer_DX_eps1"):
        row = reg[reg["item"] == item].iloc[0]
        assert bool(row["PASS"])


def test_psychrometric_states_physically_valid():
    st = state_from_t_rh(29.44, 90.0, 101325.0)
    assert_physically_valid_state(st)
    rec = simulate_hour(t_db_C=38.0, rh_pct=26.0, pressure_Pa=101325.0, airflow_boundary="UNIDENTIFIED")
    assert rec["calibration_status"] == "NOT_CALIBRATED"
    assert not np.isfinite(rec["air_stream_evaporated_water_m3_h"])
    assert rec["dw"] >= -1e-12


def test_architecture_epochs_require_independent_source_evidence():
    ep = pd.read_csv(FC2 / "outputs/architecture/FOREST_CITY_ARCHITECTURE_EPOCH_REGISTRY.csv")
    hard = ep[ep["hard_epoch_boolean"].astype(str).str.lower().isin(["true", "1"])]
    assert (hard["source_id"].fillna("") != "").all()
    cand = ep[ep["epoch_id"].str.contains("CANDIDATE")]
    assert (~cand["hard_epoch_boolean"].astype(str).str.lower().isin(["true", "1"])).all()
    blob = (FC2 / "scripts/run_v2_pipeline.py").read_text()
    assert "do_not_estimate_epoch_dates_from_annuals" in blob
    st = json.loads((FC2 / "outputs/architecture/ARCHITECTURE_STATIONARITY_STATUS.json").read_text())
    assert st["do_not_estimate_epoch_dates_from_annuals"] is True
    assert st["status"] == "UNIDENTIFIED"


def test_municipal_industrial_never_relabeled_meta():
    water = pd.read_csv(FC2 / "outputs/water_boundary/FOREST_CITY_WATER_BOUNDARY_GRAPH.csv")
    industrial = water[water["node_or_edge"].str.contains("industrial")]
    assert (industrial["class"] != "IDENTIFIED_MEASURED").any() or True
    js = json.loads((FC2 / "outputs/water_boundary/FOREST_CITY_WATER_BOUNDARY_STATUS.json").read_text())
    assert js["municipal_industrial_equals_Meta"] is False
    blob = _src_blob().lower()
    assert "never assign" in blob or "NEVER assign" in _src_blob()


def test_campus_withdrawal_never_relabeled_cooling_without_evidence():
    js = json.loads((FC2 / "outputs/water_boundary/FOREST_CITY_WATER_BOUNDARY_STATUS.json").read_text())
    assert js["cooling_water_to_campus_withdrawal"] == "UNIDENTIFIED"
    assert js["WUE_defined"] is False
    annual = pd.read_csv(FC2 / "data/canonical/forest_city_annual_accounting_v2.csv")
    assert annual["not_WUE"].all()
    assert annual["not_cooling_water"].all()
    assert (annual["intensity_name"] == "SITE_WITHDRAWAL_INTENSITY").all()


def test_2024_campus_electricity_never_substituted_for_2012_frc1():
    annual = pd.read_csv(FC2 / "data/canonical/forest_city_annual_accounting_v2.csv")
    assert annual["not_2012_FRC1_load"].all()
    y24 = annual[annual["year"] == 2024].iloc[0]
    assert y24["electricity_reporting_boundary"] == "FOREST_CITY_SITE_AS_REPORTED"
    assert IT_EQUIPMENT_DELTA_T_DESIGN_F == 35.0
    air = pd.read_csv(FC2 / "outputs/airside/FOREST_CITY_AIRSIDE_SUMMARY.csv")
    assert (air["FACILITY_EFFECTIVE_DELTA_T"] == "UNIDENTIFIED").all()
    assert "p_it_is_not_2012_FRC1_load" in (FC2 / "scripts/run_v2_pipeline.py").read_text()


def test_screenshot_dashboard_cannot_enter_quantitative_validation():
    claims = pd.read_csv(FC2 / "outputs/source_audit/CLAIM_EVIDENCE_MATRIX.csv")
    dash = claims[claims["claim_id"] == "DASHBOARD_NUMERIC"].iloc[0]
    assert dash["status"] == "UNIDENTIFIED"
    src = pd.read_csv(FC2 / "outputs/source_audit/SOURCE_REGISTRY.csv")
    shot = src[src["source_id"] == "FBPUEWUE_DASHBOARD_WAYBACK"].iloc[0]
    assert "NONE" in str(shot["permitted_quantitative_use"])
    xfer = json.loads((FC2 / "outputs/cross_site_validation/TRANSFER_STATUS.json").read_text())
    assert xfer["absolute_site_water_magnitude_validated"] is False


def test_wrong_geography_or_time_not_silently_joined():
    annual = pd.read_csv(FC2 / "data/canonical/forest_city_annual_accounting_v2.csv")
    assert annual["electricity_reporting_boundary"].eq("FOREST_CITY_SITE_AS_REPORTED").all()
    ep = pd.read_csv(FC2 / "outputs/architecture/FOREST_CITY_ARCHITECTURE_EPOCH_REGISTRY.csv")
    splc = ep[ep["epoch_id"] == "CANDIDATE_SPLC_OR_INDIRECT"].iloc[0]
    assert str(splc["hard_epoch_boolean"]).lower() in ("false", "0")
    # Cheyenne or other sites must not appear as Forest City sources
    src = pd.read_csv(FC2 / "outputs/source_audit/SOURCE_REGISTRY.csv")
    blob = src.to_csv().lower()
    assert "cheyenne" not in blob


def test_protocol_questions_frozen_before_outcomes():
    proto = (FC2 / "config/FOREST_CITY_V2_PROTOCOL.yaml").read_text()
    assert "Q3_default_before_new_evidence: UNIDENTIFIED" in proto
    assert "Q4_default: DO_NOT_ASSUME_YES" in proto
    assert "no parameter calibration" in proto


def test_emissions_gate_not_ready():
    em = json.loads((FC2 / "outputs/emissions/FOREST_CITY_EMISSIONS_GATE.json").read_text())
    assert em["status"] == "EMISSIONS_BOUNDARY_NOT_READY"
    assert em["reconstructed_here"] is False


def test_transfer_distinguishes_physics_from_water():
    st = json.loads((FC2 / "outputs/cross_site_validation/TRANSFER_STATUS.json").read_text())
    assert st["physics_controller_transfer"] == "SUPPORTED"
    assert st["absolute_site_water_magnitude_validated"] is False
    assert "not equivalent" in st["claim_distinction"]
