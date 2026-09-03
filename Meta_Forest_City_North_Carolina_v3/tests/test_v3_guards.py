#!/usr/bin/env python3
"""Forest City v3 guards. No calibration. Frozen packages must remain unchanged."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

FC3 = Path(__file__).resolve().parents[1]
REPO = FC3.parent
V1 = REPO / "Meta_Forest_City_North_Carolina_v1"
PRN = REPO / "Meta_Prineville_Oregon_v3"
NLR = REPO / "other_sources" / "nlr_esif_fullstack"
MASANET = REPO / "other_sources" / "masanet"

sys.path.insert(0, str(FC3 / "src"))
from taxonomy import CATEGORIES, assert_exactly_one, classify_hour  # noqa: E402

EXPECTED = {
    "fc_controller": "99ecc213fa181ab1fe7144087da5874b0a8f3f79478a6a8b5aed83fe0ea77c78",
    "fc_structural": "085a893cd63665b37d027877e9d80efbc99489a6c813a9f8da150e41a529568d",
    "fc_control_contract": "56d3ef12b0ab3584886892a3283f068ebe7bcfc0adc827543dc6b8910da450c2",
    "fc_airflow_contract": "f1cdc03bea8f5103e8951c6fbef7e965d16248e511fd4ad4874e19d5054ddc37",
    "kfqd_parquet": "f87a2e61120cf2d8e3117ff20e838567d0f8525a650a7fdaad221f9b3044e1d9",
    "prn_structural": "f9649c489196cdc3e617f5b28574334aaaace5a94e7ade5ce461f6da22809a6a",
    "prn_psych": "c10e1487a00ce32023bf3b630f915b2fe9ba303917951ff5f5bcbec3a3aafd30",
    "prn_graybox": "8275ca5bfc23042e3af19b72f2adb260304ac95d692d0b3ecbcb526b020f0609",
    "prn_arch": "1f87a1846aa8254c758ab11e3bd9b6f639e6c64bc551c36bcf8201bd65e78604",
    "q2_krdm": "87c0beaf1f8223ebb9f4d02ff13b9efd9d2286aaddfec0a3cce9af4c4279d925",
    "cpu": "1f57b210a63d375ce8eff7d5043756ffe6efe04e8a408bf9429bfd10096528d9",
    "h100": "a620d649a932f2388aa2f35bac2730eb75fe1dc74529668de4f30ee814600076",
    "esif": "4e01139dd9365f62824ac00ff944468839e7873e47a5cea3df4714854af1b02c",
    "esif_selected": "fc15039e713578316877f5df9e1009e2a719128bd2458cde74a822ff1aa877dd",
    "masanet_first": "70782ac8597d81d8d970fdbffb427969cc5618526df0191146b382e7cb1d1d8a",
}


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def test_v1_unchanged():
    assert _sha(V1 / "src/forest_city_controller.py") == EXPECTED["fc_controller"]
    assert _sha(V1 / "src/forest_city_structural_reference_v1.py") == EXPECTED["fc_structural"]
    assert _sha(V1 / "config/FOREST_CITY_REFERENCE_CONTROL_CONTRACT.json") == EXPECTED["fc_control_contract"]
    assert _sha(V1 / "config/FOREST_CITY_AIRFLOW_BOUNDARY_CONTRACT.json") == EXPECTED["fc_airflow_contract"]


def test_prineville_unchanged():
    assert _sha(PRN / "src/prineville_structural_v1.py") == EXPECTED["prn_structural"]
    assert _sha(PRN / "src/prineville_psychrometrics.py") == EXPECTED["prn_psych"]
    assert _sha(PRN / "src/prineville_graybox.py") == EXPECTED["prn_graybox"]
    assert _sha(PRN / "config/prineville_architecture_states.yaml") == EXPECTED["prn_arch"]
    assert _sha(PRN / "outputs/prn1_q2_2012_public_validation_v1/weather/Q2_2012_KRDM_hourly.parquet") == EXPECTED["q2_krdm"]


def test_cpu_h100_esif_masanet_unchanged():
    assert _sha(NLR / "analysis/FINAL_KESTREL_CPU_STATUS.json") == EXPECTED["cpu"]
    assert _sha(NLR / "genai_h100/manifests/H100_COMPUTE_FINAL_FREEZE.json") == EXPECTED["h100"]
    assert _sha(NLR / "heat_rejection_water/manifests/ESIF_HEAT_WATER_RESULT_FREEZE.json") == EXPECTED["esif"]
    assert _sha(NLR / "facility_overhead/analysis/COMPONENT_SELECTED_MODELS.json") == EXPECTED["esif_selected"]


def test_v3_src_has_no_fitting():
    banned = ("curve_fit", "least_squares", "GradientBoost", "sklearn")
    for p in (FC3 / "src").glob("*.py"):
        t = p.read_text()
        for b in banned:
            assert b not in t, f"{p} contains {b}"


def test_v3_scripts_write_only_under_v3():
    for script in (FC3 / "scripts").glob("*.py"):
        if script.name == "run_cleanroom_replay.py":
            # This audit intentionally writes only inside a disposable /tmp Git worktree.
            continue
        t = script.read_text()
        assert "Meta_Forest_City_North_Carolina_v1" not in t or "V1" in t
        assert "mkdir" not in t or "OUTPUTS" in t or "OUT" in t or "FC3" in t
        assert "to_csv(" in t or "write_text" in t or script.name.startswith("run_")
        assert "Path(\"/home" not in t or "conda/envs" in t


def test_35f_is_not_facility_delta_t():
    src = (V1 / "src/forest_city_structural_reference_v1.py").read_text()
    assert 'FACILITY_EFFECTIVE_DELTA_T_STATUS = "UNIDENTIFIED"' in src
    assert "IT_EQUIPMENT_DELTA_T_DESIGN_F = 35.0" in src
    contract = (FC3 / "config/claims_contract.yaml").read_text()
    assert "FACILITY_EFFECTIVE_DELTA_T" in contract
    assert "35 F" in contract


def test_facility_effective_delta_t_unidentified_absent_new_evidence():
    ledger = FC3 / "outputs/FINAL_CLAIMS_LEDGER.json"
    if not ledger.exists():
        pytest.skip("pipeline not yet run")
    rec = json.loads(ledger.read_text())
    assert rec["FACILITY_EFFECTIVE_DELTA_T"] == "UNIDENTIFIED"
    ident = pd.read_csv(FC3 / "outputs/identification/IDENTIFICATION_LEDGER.csv")
    row = ident.loc[ident.quantity == "FACILITY_EFFECTIVE_DELTA_T"].iloc[0]
    assert row.identification == "UNIDENTIFIED"


def test_2024_campus_cannot_become_2012_frc1():
    p = FC3 / "outputs/annual/CAMPUS_ANNUAL_COMPARISON.json"
    if not p.exists():
        pytest.skip("pipeline not yet run")
    rec = json.loads(p.read_text())
    assert rec["not_FRC1"] is True
    csv = pd.read_csv(FC3 / "outputs/annual/CAMPUS_ANNUAL_COMPARISON.csv")
    assert (~csv["comparable_to_2012_FRC1"].astype(bool)).all()
    assert csv["not_FRC1_cooling_WUE"].astype(bool).all()


def test_cooling_regimes_mutually_exclusive():
    for cat in CATEGORIES:
        ind = assert_exactly_one(cat)
        assert sum(ind.values()) == 1
        assert ind[cat] == 1


def test_cooling_regimes_exhaustive_on_usable_hours():
    hours = FC3 / "outputs/regimes/KFQD_JJA_HOURS.csv"
    if not hours.exists():
        pytest.skip("pipeline not yet run")
    df = pd.read_csv(hours)
    missing = df["control_mode"].astype(str) == "WEATHER_MISSING"
    usable = df.loc[~missing]
    assert int(missing.sum()) == 955
    assert len(usable) == 1253
    assert set(usable["common_category"]).issubset(set(CATEGORIES))
    assert usable["common_category"].notna().all()
    for cat in usable["common_category"]:
        assert_exactly_one(cat)


def test_station_choice_independent_of_dx():
    sel_path = FC3 / "outputs/weather/STATION_SELECTION.json"
    if not sel_path.exists():
        pytest.skip("pipeline not yet run")
    sel = json.loads(sel_path.read_text())
    assert sel["selected_using_dx_outcome"] is False
    assert sel["a_priori"] is True
    src = (FC3 / "scripts/run_v3_pipeline.py").read_text()
    assert "not selected because of a DX outcome" in src


def test_missing_hours_not_labeled_observed():
    p = FC3 / "outputs/weather/WEATHER_MISSINGNESS.csv"
    if not p.exists():
        pytest.skip("pipeline not yet run")
    m = pd.read_csv(p)
    assert (~m["jja_missing_labeled_observed"].astype(bool)).all()
    assert (m["evidence_class_for_missing"] == "UNIDENTIFIED").all()


def test_quantitative_transfer_cannot_pass_from_annual_match():
    src = (FC3 / "scripts/run_v3_pipeline.py").read_text()
    assert "QUANTITATIVE_PHYSICS_TRANSFER" in src
    assert "NOT_VALIDATED" in src
    ledger = FC3 / "outputs/FINAL_CLAIMS_LEDGER.json"
    if ledger.exists():
        rec = json.loads(ledger.read_text())
        assert rec["QUANTITATIVE_PHYSICS_TRANSFER"] == "NOT_VALIDATED"
        assert rec["MODEL_CALIBRATED"] == "NO"


def test_scenario_outputs_carry_provenance():
    mas = FC3 / "outputs/masanet/MASANET_TRANSFER.json"
    if mas.exists():
        rec = json.loads(mas.read_text())
        assert "SCENARIO" in rec.get("theta_provenance", "")
        assert rec["QUANTITATIVE_PHYSICS_TRANSFER"] == "NOT_VALIDATED"
        assert rec["refit"] is False
    esif = FC3 / "outputs/esif/ESIF_TRANSFER.json"
    if esif.exists():
        rec = json.loads(esif.read_text())
        assert rec["refit"] is False
        assert rec["evidence_class"] == "SCENARIO_INPUT + TRANSFERRED_MODEL_OUTPUT"
        assert rec["QUANTITATIVE_PHYSICS_TRANSFER"] == "NOT_VALIDATED"


def test_taxonomy_prn_b_split():
    assert classify_hour("PRN1", "B_100PCT_OA_HUMIDIFICATION_OR_COOLING", primary_control_objective="COOLING") == "EVAP_COOLING"
    assert classify_hour("PRN1", "B_100PCT_OA_HUMIDIFICATION_OR_COOLING", primary_control_objective="HUMIDIFICATION") == "HUMIDIFICATION"
    assert classify_hour("FC", "OA_FREE_COOLING") == "OA_FREE"
    assert classify_hour("FC", "DX_REQUIRED") == "MECHANICAL_COOLING"
    assert classify_hour("FC", "WEATHER_MISSING") == "UNRESOLVED"


def test_v2_reproduction_if_present():
    p = FC3 / "outputs/regimes/V2_REPRODUCTION.json"
    if not p.exists():
        pytest.skip("pipeline not yet run")
    rec = json.loads(p.read_text())
    assert rec["V2_REPRODUCTION"] == "PASS"
    d = rec["reproduced"]
    assert d["OA_FREE"] == 677
    assert d["HIGH_RH_MIXING"] == 443
    assert d["EVAP_COOLING"] == 133
    assert d["DX_required_hours"] == 0
    assert d["valid_hours"] == 1253


def test_v3_does_not_assign_v2_output_paths():
    pipe = (FC3 / "scripts/run_v3_pipeline.py").read_text()
    assert "OUTPUTS = FC3 / \"outputs\"" in (FC3 / "src/fc3_paths.py").read_text()
    assert "V2 / \"outputs\"" not in pipe


def test_material_dependencies_equal_intended_frozen_content():
    manifest = json.loads((FC3 / "outputs/provenance/V3_DEPENDENCY_MANIFEST.json").read_text())
    assert manifest["status"] == "PASS"
    assert manifest["v2_worktree_never_used"] is True
    for row in manifest["rows"]:
        if not row["material"]:
            continue
        if row["access_mode"] == "GIT_BLOB_ONLY":
            assert row["frozen_blob_available"] is True
        else:
            assert row["worktree_matches_intended"] is True, row["logical_input"]


def test_dirty_v2_replacements_cannot_enter_v3():
    manifest = pd.read_csv(FC3 / "outputs/provenance/V3_DEPENDENCY_MANIFEST.csv")
    v2 = manifest[manifest["package"] == "Forest City v2"]
    assert set(v2["logical_input"]) == {
        "v2_factorial_frozen_blob",
        "v2_station_frozen_blob",
        "v2_committed_pipeline",
        "v2_guard_suite",
    }
    assert v2["access_mode"].eq("GIT_BLOB_ONLY").all()
    pipe = (FC3 / "scripts/run_v3_pipeline.py").read_text()
    assert "read_frozen_blob" in pipe
    assert "pd.read_csv(V2" not in pipe


def test_clean_preprocessing_recreates_required_weather_intermediate():
    p = FC3 / "outputs/intermediates/weather_KRDM_2012.csv"
    assert p.exists()
    df = pd.read_csv(p, parse_dates=["timestamp_utc"])
    assert len(df) == 8784
    common = df[(df.timestamp_utc >= "2012-06-21T00:00:00Z") & (df.timestamp_utc < "2012-09-01T00:00:00Z")]
    assert len(common) == 1728


def test_2x2_contrasts_exact_and_labeled():
    source = pd.read_csv(FC3 / "outputs/cross_site/WEATHER_CONTROLLER_2x2.csv").set_index("combination")
    contrasts = pd.read_csv(FC3 / "outputs/cross_site/WEATHER_CONTROLLER_2x2_CONTRASTS.csv").set_index("regime")
    names = {"A": "PRN_weather+PRN_controller", "B": "PRN_weather+FC_controller", "C": "FC_weather+PRN_controller", "D": "FC_weather+FC_controller"}
    for regime, row in contrasts.iterrows():
        vals = {key: source.loc[name, f"P({regime})"] for key, name in names.items()}
        assert row["weather_effect_under_PRN_controller_pp"] == pytest.approx(100 * (vals["C"] - vals["A"]), abs=1e-12)
        assert row["weather_effect_under_FC_controller_pp"] == pytest.approx(100 * (vals["D"] - vals["B"]), abs=1e-12)
        assert row["controller_effect_under_PRN_weather_pp"] == pytest.approx(100 * (vals["B"] - vals["A"]), abs=1e-12)
        assert row["controller_effect_under_FC_weather_pp"] == pytest.approx(100 * (vals["D"] - vals["C"]), abs=1e-12)
        assert row["replay_interaction_pp"] == pytest.approx(100 * (vals["D"] - vals["C"] - vals["B"] + vals["A"]), abs=1e-12)
    payload = json.loads((FC3 / "outputs/cross_site/WEATHER_CONTROLLER_2x2_CONTRASTS.json").read_text())
    assert payload["evidence_class"] == "MODEL_REPLAY"
    assert payload["NOT_CAUSAL_IDENTIFICATION"] is True
    assert payload["NOT_WATER_USE"] is True


def test_zero_dx_and_detailed_station_robustness_are_separate():
    rec = json.loads((FC3 / "outputs/regimes/STATION_ROBUSTNESS.json").read_text())
    assert rec["SUMMER_DX_STATION_ROBUSTNESS"] == "STRONG_SUPPORT"
    assert rec["DETAILED_REGIME_SHARE_STATION_ROBUSTNESS"] == "PARTIAL"
    assert rec["ranges_are_not_confidence_intervals"] is True
    assert rec["true_full_period_regime_shares"] == "UNIDENTIFIED"


def test_masanet_main_support_is_matched_and_scenario_only():
    rec = json.loads((FC3 / "outputs/masanet/MASANET_TRANSFER.json").read_text())
    rows = {row["weather"]: row for row in rec["summaries"]}
    assert rows["KFQD"]["n"] == rows["KRDM"]["n"] == 1251
    assert rows["KFQD"]["timestamp_set_sha256"] == rows["KRDM"]["timestamp_set_sha256"]
    assert rec["main_fc_prn_identical_timestamp_support"] is True
    assert "NOT Forest City estimates" in rec["scenario_output_notice"]


def test_esif_main_support_and_synthetic_it_provenance():
    rec = json.loads((FC3 / "outputs/esif/ESIF_TRANSFER.json").read_text())
    rows = {row["weather"]: row for row in rec["rows"]}
    assert rows["KFQD"]["n"] == rows["KRDM"]["n"] == 1251
    assert rows["KFQD"]["timestamp_set_sha256"] == rows["KRDM"]["timestamp_set_sha256"]
    assert rec["main_fc_prn_identical_timestamp_support"] is True
    assert rows["KFQD"]["synthetic_IT_kw"] == pytest.approx(1406.2885351154928)
    assert "training-window mean IT load" in rows["KFQD"]["IT_provenance"]


def test_campus_withdrawal_is_not_consumption_or_frc1_cooling_water():
    annual = pd.read_csv(FC3 / "outputs/annual/CAMPUS_ANNUAL_COMPARISON.csv")
    assert annual["withdrawal_not_consumption"].astype(bool).all()
    assert annual["not_FRC1_cooling_WUE"].astype(bool).all()
    ident = pd.read_csv(FC3 / "outputs/identification/IDENTIFICATION_LEDGER.csv").set_index("quantity")
    assert ident.loc["CAMPUS_WATER_CONSUMPTION", "identification"] == "UNIDENTIFIED"
    assert ident.loc["FRC1_COOLING_ONLY_WATER_MAGNITUDE", "identification"] == "UNIDENTIFIED"


def test_cfm_alone_cannot_identify_delta_t_and_no_inverse_fit():
    ident = (FC3 / "outputs/identification/IDENTIFICATION_LEDGER.md").read_text()
    assert "CFM alone" in ident
    assert "Q = m_dot cp DeltaT" in ident
    scripts = "\n".join(p.read_text() for p in (FC3 / "scripts").glob("*.py"))
    assert "choose facility Delta-T to match annual water" not in scripts.lower()
    assert "inverse_fit" not in scripts.lower()


def test_no_arbitrary_numerical_voi_score():
    df = pd.read_csv(FC3 / "outputs/acquisition/DATA_VALUE_MATRIX.csv")
    assert "priority" not in df.columns
    assert "score" not in df.columns
    assert set(df["priority_tier"]) == {"VERY HIGH", "HIGH"}


def test_masanet_instrumentation_writes_only_under_v3():
    src = (FC3 / "scripts/run_masanet_transfer.py").read_text()
    assert "load_instrumented" not in src
    assert 'OUT / "_instrumented"' in src


def test_claims_contract_blocks_transferred_as_observed():
    t = (FC3 / "config/claims_contract.yaml").read_text()
    assert "TRANSFERRED_MODEL" in t
    assert "SCENARIO" in t
    assert "MUST NOT" in t
    assert "OBSERVED" in t
