from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from pathlib import Path

import pandas as pd
import yaml


MODULE = Path(__file__).resolve().parents[1]
REPO = MODULE.parents[1]
BASELINE = "975821ae679713cc6b2bcd984f2d16d4328289a8"
PARENTS = (
    "other_sources/ocwd_groundwater_feasibility",
    "other_sources/ocwd_groundwater_gw1_preflight",
    "other_sources/ocwd_groundwater_gw1_climate",
    "other_sources/ocwd_groundwater_gw1b",
)
ALLOWED = {
    "OBSERVED",
    "REPORTED_MEASURED",
    "DERIVED_FROM_MEASUREMENTS",
    "ESTIMATED",
    "MODELED",
    "REFERENCE_MODEL",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def test_frozen_parent_modules_match_baseline() -> None:
    manifest = json.loads(
        (MODULE / "outputs/provenance/FROZEN_PARENT_DEPENDENCY_MANIFEST.json").read_text()
    )
    assert manifest["baseline_commit"] == BASELINE
    assert manifest["parent_modules_byte_integrity"] == "PASS"
    assert manifest["parent_status_lines"] == []
    for parent in PARENTS:
        status = subprocess.run(
            ["git", "status", "--short", "--untracked-files=all", "--", parent],
            cwd=REPO,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert status == ""


def test_downloaded_raw_hashes_are_pinned() -> None:
    rows = list(
        csv.DictReader((MODULE / "outputs/provenance/RAW_DOWNLOAD_MANIFEST.csv").open())
    )
    assert len(rows) == 5
    for row in rows:
        assert row["official_url"].startswith("https://")
        assert row["accessed_at"]
        assert len(row["sha256"]) == 64
        assert row["sha256"] == row["expected_sha256"]
        assert sha256(MODULE / row["local_path"]) == row["sha256"]


def test_evidence_classes_are_preserved() -> None:
    contract = yaml.safe_load((MODULE / "config/EVIDENCE_CLASSES.yaml").read_text())
    assert set(contract["allowed_classes"]) == ALLOWED
    rows = list(csv.DictReader((MODULE / "sources/AP_AUTHORITATIVE_SOURCE_REGISTRY.csv").open()))
    assert len(rows) == 19
    assert {row["evidence_class"] for row in rows} <= ALLOWED
    assert all(row["agency"] and row["official_url"] and row["limitations"] for row in rows)


def test_data_contract_resolves_required_metadata_for_every_field() -> None:
    contract = yaml.safe_load((MODULE / "config/AP_PLANNING_DATA_CONTRACT.yaml").read_text())
    assert set(contract["tables"]) == {
        "candidate_regions", "power_regions", "groundwater_nodes", "groundwater_heads",
        "groundwater_recharge", "groundwater_extraction", "agriculture_demand",
        "municipal_demand", "water_sources", "wastewater_reuse", "desalination",
        "dc_source_options", "site_groundwater_crosswalk",
    }
    required_meta = {
        "temporal_resolution", "spatial_resolution", "evidence_class",
        "authoritative_source", "period", "qa", "uncertainty",
    }
    for table in contract["tables"].values():
        assert required_meta <= set(table["metadata"])
        assert table["metadata"]["evidence_class"] in ALLOWED
        for field in table["fields"].values():
            assert field["dtype"] and field["units"] and field["intended_model_role"]


def test_groundwater_heads_are_not_interpolated() -> None:
    status = json.loads((MODULE / "outputs/readiness/AP_GROUNDWATER_COVERAGE_STATUS.json").read_text())
    assert status["no_interpolation"] is True
    observations = pd.read_parquet(
        MODULE / "data/derived/AP_CGWB_GROUNDWATER_HEAD_OBSERVATIONS.parquet",
        columns=["head_depth_m_bgl", "numeric_observation", "measurement_class"],
    )
    assert len(observations) == status["raw_rows"]
    assert observations.loc[~observations["numeric_observation"], "head_depth_m_bgl"].isna().all()
    assert set(observations["measurement_class"]) == {"OBSERVED"}


def test_grace_is_not_well_level_ground_truth() -> None:
    rows = list(csv.DictReader((MODULE / "sources/AP_AUTHORITATIVE_SOURCE_REGISTRY.csv").open()))
    grace = next(row for row in rows if row["source_id"] == "NASA_GRACE_JPL")
    assert grace["evidence_class"] == "DERIVED_FROM_MEASUREMENTS"
    assert "cannot be labeled or used as local well-scale groundwater head" in grace["limitations"]


def test_no_unresolved_crosswalk_enters_primary_mapping() -> None:
    crosswalk = pd.read_csv(MODULE / "outputs/tables/AP_CANDIDATE_REGION_CROSSWALK.csv")
    invalid = crosswalk["crosswalk_confidence"].isin(["APPROXIMATE", "UNRESOLVED"])
    assert not crosswalk.loc[invalid, "primary_eligible"].astype(bool).any()
    for filename in ("M_GW.csv", "M_AG.csv", "M_MUN.csv"):
        frame = pd.read_csv(MODULE / "outputs/tables" / filename)
        assert frame.empty


def test_source_feasibility_is_not_assumed() -> None:
    frame = pd.read_csv(MODULE / "outputs/tables/AP_WATER_SOURCE_FEASIBILITY.csv")
    assert set(frame["source_type"]) == {
        "groundwater", "reclaimed wastewater", "desalinated seawater",
        "other surface/municipal source",
    }
    assert set(frame["feasibility"]) == {"UNCERTAIN"}
    assert not frame["primary_eligible"].astype(bool).any()
    assert frame["capacity_m3_per_day"].isna().all()


def test_ablation_has_one_shared_input_bundle() -> None:
    protocol = yaml.safe_load((MODULE / "config/PLANNING_ABLATION_PROTOCOL.yaml").read_text())
    assert set(protocol["models"]) == {"M0", "M0S", "M1L", "M1N"}
    assert protocol["controlled_mechanism"] == "water representation only"
    assert len(protocol["shared_inputs"]) == 6
    assert all(str(value).endswith("PENDING") for value in protocol["shared_inputs"].values())


def test_no_ocwd_physical_coefficients_or_model_solution_enter_india_code() -> None:
    executable_text = "\n".join(
        path.read_text(errors="ignore")
        for folder in (MODULE / "src", MODULE / "scripts")
        for path in folder.glob("*.py")
    ).lower()
    forbidden = (
        "a_matrix", "b_matrix", "storage_coefficient", "hydraulic_conductance",
        "ocwd_pumping_response", "solve_m1", "optimize_siting",
    )
    assert not any(token in executable_text for token in forbidden)
    status = json.loads((MODULE / "outputs/readiness/AP_PLANNING_READINESS.json").read_text())
    assert status["AP9"]["status"] == "FAIL"
    assert status["optimization_run"] is False


def test_track_a_stopped_after_absence_check() -> None:
    status = json.loads((MODULE / "outputs/readiness/TRACK_A_WRMS_STATUS.json").read_text())
    assert status["TRACK_A_STATUS"] == "WAITING_FOR_WRMS"
    assert status["WRMS_PRESENT"] is False
    assert status["B4_B5_B6_B7"] == "NOT_RUN"
    assert status["placebos"] == "NOT_RUN"
    assert status["tracer_mbi_validation"] == "NOT_TOUCHED"


def test_static_dynamic_ranking_is_only_preregistered() -> None:
    protocol = yaml.safe_load((MODULE / "config/STATIC_DYNAMIC_RANKING_PROTOCOL.yaml").read_text())
    assert protocol["status"] == "PREREGISTERED_NOT_RUN"
    assert "No OCWD physical coefficient" in protocol["local_model_requirement"]
    assert len(protocol["rank_metrics"]) == 6
    assert not list(MODULE.glob("**/*M1*_solution*"))


def test_m0_reproduction_is_not_fabricated() -> None:
    status = json.loads((MODULE / "outputs/readiness/M0_REPRODUCTION_STATUS.json").read_text())
    assert status["status"] == "PARTIAL"
    assert status["frozen_numerical_result_reproduced"] is False
    assert status["code_path"] is None


def test_public_groundwater_status_preserves_identity_uncertainty() -> None:
    status = json.loads((MODULE / "outputs/readiness/AP_GROUNDWATER_COVERAGE_STATUS.json").read_text())
    assert status["raw_stable_station_id_present"] is False
    assert status["raw_qa_flags_present"] is False
    assert status["raw_screen_layer_fields_present"] is False
    assert status["candidate_rows_outside_published_ap_coordinate_envelope"] > 0
    assert status["station_location_series_upper_bound"] >= status["distinct_name_keys_lower_bound"]


def test_parent_paths_are_not_modified_by_this_module() -> None:
    status = subprocess.run(
        ["git", "status", "--short", "--untracked-files=all", "--", *PARENTS],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert status == ""
