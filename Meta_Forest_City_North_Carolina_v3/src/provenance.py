"""Exact external-dependency inventory and frozen-content enforcement for v3."""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from fc3_paths import FC3, OUTPUTS, REPO


FROZEN_COMMIT = "da7fd6f55e1aef5216ceabe80bfc3e31265f7927"
MASANET_UPSTREAM_COMMIT = "2cc53bee89b0a61bdad10c02b4d170d7f673e2dc"


@dataclass(frozen=True)
class Dependency:
    logical_input: str
    path: str
    package: str
    used_by_step: str
    evidence_class: str
    notes: str
    access_mode: str = "WORKTREE"
    intended_commit: str = FROZEN_COMMIT
    expected_sha256: str = ""
    nested_repo: str = ""
    material: bool = True


DEPENDENCIES = [
    Dependency("fc_v1_paths", "Meta_Forest_City_North_Carolina_v1/src/paths.py", "Forest City v1", "imports", "FROZEN_CODE", "Transitive import used by psychrometrics adapter."),
    Dependency("fc_v1_psychrometrics_adapter", "Meta_Forest_City_North_Carolina_v1/src/psychrometrics_adapter.py", "Forest City v1", "weather preprocessing; FC replay", "FROZEN_CODE", "Pressure-aware wet-bulb adapter."),
    Dependency("fc_v1_controller", "Meta_Forest_City_North_Carolina_v1/src/forest_city_controller.py", "Forest City v1", "FC controller replay", "FROZEN_CODE", "Frozen controller; never fitted."),
    Dependency("fc_v1_structural", "Meta_Forest_City_North_Carolina_v1/src/forest_city_structural_reference_v1.py", "Forest City v1", "FC controller replay", "FROZEN_CODE", "Frozen structural reference; airflow boundary remains unidentified."),
    Dependency("fc_control_contract", "Meta_Forest_City_North_Carolina_v1/config/FOREST_CITY_REFERENCE_CONTROL_CONTRACT.json", "Forest City v1", "claims guard", "DOCUMENTARY_CONTRACT", "Frozen controller evidence contract."),
    Dependency("fc_airflow_contract", "Meta_Forest_City_North_Carolina_v1/config/FOREST_CITY_AIRFLOW_BOUNDARY_CONTRACT.json", "Forest City v1", "identification guard", "DOCUMENTARY_CONTRACT", "35 F is an IT design rise, not facility effective Delta-T."),
    Dependency("fc_source_register", "Meta_Forest_City_North_Carolina_v1/config/forest_city_source_register.csv", "Forest City v1", "evidence crosswalk", "DOCUMENTARY_EVIDENCE", "Committed source-level evidence registry."),
    Dependency("fc_annual_source_rows", "Meta_Forest_City_North_Carolina_v1/outputs/annual_accounting/FOREST_CITY_SITE_WITHDRAWAL_INTENSITY.csv", "Forest City v1", "2024 campus accounting", "OBSERVED_AND_DERIVED", "Committed actual source rows; replaces ignored processed CSV dependency."),
    Dependency("fc_dashboard_scope", "Meta_Forest_City_North_Carolina_v1/outputs/dashboard_recovery/DASHBOARD_RECOVERY_STATUS.json", "Forest City v1", "evidence crosswalk", "DOCUMENTARY_EVIDENCE", "Scope evidence only; not quantitative validation."),
    Dependency("fc_facility_registry", "Meta_Forest_City_North_Carolina_v1/config/forest_city_facility_registry.yaml", "Forest City v1", "evidence crosswalk", "DOCUMENTARY_EVIDENCE", "Facility identity remains unresolved."),
    Dependency("fc_permit_inventory", "Meta_Forest_City_North_Carolina_v1/outputs/permit_audit/FOREST_CITY_PUBLIC_PERMIT_INVENTORY.csv", "Forest City v1", "evidence crosswalk", "DOCUMENTARY_EVIDENCE", "Public acquisition inventory."),
    Dependency("prn_architecture", "Meta_Prineville_Oregon_v3/src/prineville_architecture.py", "Prineville v3", "PRN replay import", "FROZEN_CODE", "Transitive structural-model dependency."),
    Dependency("prn_controller", "Meta_Prineville_Oregon_v3/src/prineville_ocp_controller.py", "Prineville v3", "PRN replay import", "FROZEN_CODE", "Frozen controller."),
    Dependency("prn_psychrometrics", "Meta_Prineville_Oregon_v3/src/prineville_psychrometrics.py", "Prineville v3", "weather and PRN replay", "FROZEN_CODE", "Frozen psychrometrics implementation."),
    Dependency("prn_structural_helpers", "Meta_Prineville_Oregon_v3/src/prineville_structural.py", "Prineville v3", "PRN replay import", "FROZEN_CODE", "Airflow scaling helper; no parameter fit."),
    Dependency("prn_structural_v1", "Meta_Prineville_Oregon_v3/src/prineville_structural_v1.py", "Prineville v3", "PRN controller replay", "FROZEN_CODE", "Frozen structural reference."),
    Dependency("prn_weather_preprocessor", "Meta_Prineville_Oregon_v3/src/prepare_weather.py", "Prineville v3", "KRDM deterministic preprocessing", "FROZEN_CODE", "Invoked in memory with output redirected under v3."),
    Dependency("prn_architecture_registry", "Meta_Prineville_Oregon_v3/config/prineville_architecture_states.yaml", "Prineville v3", "claims guard", "DOCUMENTARY_CONTRACT", "Frozen architecture registry."),
    Dependency("prn_graybox", "Meta_Prineville_Oregon_v3/src/prineville_graybox.py", "Prineville v3", "frozen-package guard", "FROZEN_CODE", "Guard only; not fitted or invoked."),
    Dependency("prn_q2_weather_reference", "Meta_Prineville_Oregon_v3/outputs/prn1_q2_2012_public_validation_v1/weather/Q2_2012_KRDM_hourly.parquet", "Prineville v3", "frozen-package guard", "OBSERVED", "Guard/reference only; main replay is rebuilt from frozen raw KRDM."),
    Dependency("prn_annual_source_rows", "Meta_Prineville_Oregon_v3/outputs/annual_audit.csv", "Prineville v3", "2024 campus accounting", "OBSERVED_AND_DERIVED", "Committed campus annual audit."),
    Dependency("v2_factorial_frozen_blob", "Meta_Forest_City_North_Carolina_v2/outputs/cross_site_same_period/WEATHER_CONTROLLER_FACTORIAL.csv", "Forest City v2", "2x2 reproduction targets", "MODEL_REPLAY", "Read only with git show from intended commit; current replacement cannot enter.", access_mode="GIT_BLOB_ONLY"),
    Dependency("v2_station_frozen_blob", "Meta_Forest_City_North_Carolina_v2/outputs/weather_robustness/FULL_JJA_STATION_REPLICATION.csv", "Forest City v2", "station reproduction targets", "MODEL_REPLAY", "Read only with git show from intended commit; current replacement cannot enter.", access_mode="GIT_BLOB_ONLY"),
    Dependency("v2_committed_pipeline", "Meta_Forest_City_North_Carolina_v2/scripts/run_pipeline.py", "Forest City v2", "clean-room deterministic preprocessing/replay", "FROZEN_CODE", "Executed in the clean worktree with context-only municipal_update explicitly skipped.", access_mode="GIT_BLOB_ONLY"),
    Dependency("v2_guard_suite", "Meta_Forest_City_North_Carolina_v2/tests/test_v2_guards.py", "Forest City v2", "clean-room v2 guard suite", "FROZEN_TEST", "Executed only in clean worktree at intended commit.", access_mode="GIT_BLOB_ONLY"),
    Dependency("esif_selected_models", "other_sources/nlr_esif_fullstack/facility_overhead/analysis/COMPONENT_SELECTED_MODELS.json", "ESIF", "ESIF transfer", "TRANSFERRED_MODEL", "Frozen F4 cooling and F0 HVAC coefficients plus training-window scaler mean."),
    Dependency("esif_freeze", "other_sources/nlr_esif_fullstack/heat_rejection_water/manifests/ESIF_HEAT_WATER_RESULT_FREEZE.json", "ESIF", "frozen-package guard", "FROZEN_GUARD", "No ESIF refit."),
    Dependency("cpu_freeze", "other_sources/nlr_esif_fullstack/analysis/FINAL_KESTREL_CPU_STATUS.json", "CPU", "frozen-package guard", "FROZEN_GUARD", "Guard only; not a Forest City model input."),
    Dependency("h100_freeze", "other_sources/nlr_esif_fullstack/genai_h100/manifests/H100_COMPUTE_FINAL_FREEZE.json", "H100", "frozen-package guard", "FROZEN_GUARD", "Guard only; not a Forest City model input."),
    Dependency("masanet_common", "other_sources/masanet/scripts/common.py", "Masanet", "Masanet transfer import", "FROZEN_CODE", "Frozen adapter support."),
    Dependency("masanet_facility_adapter", "other_sources/masanet/scripts/facility_adapter.py", "Masanet", "Masanet transfer import", "FROZEN_CODE", "Frozen facility-intensity wrapper."),
    Dependency("masanet_case_table", "other_sources/masanet/scripts/followup_common.py", "Masanet", "Masanet Case 1 parameter ranges", "FROZEN_CODE", "Frozen Table 3 parameter mapping."),
    Dependency("masanet_upstream_source", "other_sources/masanet/external/Data-Center-Water-footprint/simulation_funs_DC.py", "Masanet upstream", "Masanet transfer", "FROZEN_CODE", "Ignored nested clone pinned to upstream commit.", intended_commit=MASANET_UPSTREAM_COMMIT, expected_sha256="74ea9da658482a29e1a298a544234cc43b654cf514d678482842ae30c2446c01", nested_repo="other_sources/masanet/external/Data-Center-Water-footprint"),
    Dependency("masanet_cop_2", "other_sources/masanet/external/Data-Center-Water-footprint/COP_2.pkl", "Masanet upstream", "Masanet transfer", "FROZEN_MODEL", "Frozen serialized COP model.", intended_commit=MASANET_UPSTREAM_COMMIT, expected_sha256="a17f740bf3a4c4f59a6e1aedce46bf0457913fc559da51320dd3518dfa6a790a", nested_repo="other_sources/masanet/external/Data-Center-Water-footprint"),
    Dependency("masanet_cop_dx", "other_sources/masanet/external/Data-Center-Water-footprint/COP_DX.pkl", "Masanet upstream", "Masanet transfer", "FROZEN_MODEL", "Frozen serialized COP model.", intended_commit=MASANET_UPSTREAM_COMMIT, expected_sha256="b17e58dc27f9227946f175ff0b1d8e93f8919c2af4a974b0fe256c18b0cacf8e", nested_repo="other_sources/masanet/external/Data-Center-Water-footprint"),
    Dependency("masanet_cop_ac", "other_sources/masanet/external/Data-Center-Water-footprint/COP_AC.pkl", "Masanet upstream", "Masanet transfer", "FROZEN_MODEL", "Frozen serialized COP model.", intended_commit=MASANET_UPSTREAM_COMMIT, expected_sha256="e8ac8e5cabb75013a3313cdafaf43e3137853197b8029554ae73599bbf18e9a4", nested_repo="other_sources/masanet/external/Data-Center-Water-footprint"),
    Dependency("weather_station_history", "Meta_Forest_City_North_Carolina_v1/data/raw/weather/isd-history.csv", "NOAA ISD station history", "clean-room v2 weather preprocessing", "OBSERVED_METADATA", "Ignored public metadata pinned by SHA256; used only by committed v2 station audit.", intended_commit="NO_GIT_BLOB_SHA256_PINNED", expected_sha256="1994747ab4af1b97e63adb434b4d0d022f2daee76f0c144ea9ab46be2d906604"),
    Dependency("weather_kfqd_2012", "Meta_Forest_City_North_Carolina_v1/data/raw/weather/72314453890_2012.csv", "NOAA Global Hourly", "KFQD weather preprocessing", "OBSERVED", "Ignored raw source pinned by SHA256; missing hours preserved.", intended_commit="NO_GIT_BLOB_SHA256_PINNED", expected_sha256="e4cbfbbfc133cccc1c595b10859546880d169013aec80939bf3728d1bf62ad7f"),
    Dependency("weather_keho_2012", "Meta_Forest_City_North_Carolina_v1/data/raw/weather/72027763843_2012.csv", "NOAA Global Hourly", "KEHO weather preprocessing", "OBSERVED", "Ignored raw source pinned by SHA256.", intended_commit="NO_GIT_BLOB_SHA256_PINNED", expected_sha256="adc544dfbb31869ffe11ef3788b1763756d559f021966ec22363c60a4c944903"),
    Dependency("weather_kgsp_2012", "Meta_Forest_City_North_Carolina_v1/data/raw/weather/72312003870_2012.csv", "NOAA Global Hourly", "KGSP weather preprocessing", "OBSERVED", "Ignored raw source pinned by SHA256.", intended_commit="NO_GIT_BLOB_SHA256_PINNED", expected_sha256="d4305277f146bfd81096950fd54f783e43a14767e9e1deec4533e4b7d0907b3a"),
    Dependency("weather_krdm_2012", "Meta_Prineville_Oregon_v3/data/raw/noaa/72692024230_2012.csv", "NOAA Global Hourly", "KRDM weather preprocessing", "OBSERVED", "Ignored raw source pinned by SHA256.", intended_commit="NO_GIT_BLOB_SHA256_PINNED", expected_sha256="29853f7afa500a5dc8a946cfdc88df9e9f93a459af41c22a27fa91aefafa6fa2"),
]


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    with path.open("rb") as handle:
        return _sha_bytes(handle.read())


def _git_bytes(repo: Path, commit: str, path: str) -> bytes | None:
    proc = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=repo, capture_output=True)
    return proc.stdout if proc.returncode == 0 else None


def read_frozen_blob(relative_path: str, commit: str = FROZEN_COMMIT) -> bytes:
    data = _git_bytes(REPO, commit, relative_path)
    if data is None:
        raise FileNotFoundError(f"missing frozen Git blob {commit}:{relative_path}")
    return data


def audit_dependencies(write: bool = True, enforce: bool = True) -> list[dict]:
    rows: list[dict] = []
    failures: list[str] = []
    for dep in DEPENDENCIES:
        path = REPO / dep.path
        exists = path.is_file()
        work_sha = sha256_file(path) if exists else ""
        head_data = _git_bytes(REPO, "HEAD", dep.path)
        head_sha = _sha_bytes(head_data) if head_data is not None else ""
        intended_data = None
        if dep.nested_repo:
            nested_root = REPO / dep.nested_repo
            nested_rel = path.relative_to(nested_root).as_posix()
            intended_data = _git_bytes(nested_root, dep.intended_commit, nested_rel)
        elif dep.intended_commit not in {"NO_GIT_BLOB_SHA256_PINNED", ""}:
            intended_data = _git_bytes(REPO, dep.intended_commit, dep.path)
        intended_sha = dep.expected_sha256 or (_sha_bytes(intended_data) if intended_data is not None else "")
        matches_intended = bool(exists and intended_sha and work_sha == intended_sha)
        frozen_blob_available = intended_data is not None or dep.intended_commit == "NO_GIT_BLOB_SHA256_PINNED"
        row = {
            "logical_input": dep.logical_input,
            "path": dep.path,
            "package": dep.package,
            "used_by_step": dep.used_by_step,
            "exists_worktree": exists,
            "worktree_sha256": work_sha,
            "tracked_at_HEAD": head_data is not None,
            "HEAD_blob_sha256": head_sha,
            "worktree_matches_HEAD": bool(exists and head_sha and work_sha == head_sha),
            "intended_frozen_commit": dep.intended_commit,
            "intended_blob_sha256": intended_sha,
            "worktree_matches_intended": matches_intended,
            "access_mode": dep.access_mode,
            "frozen_blob_available": frozen_blob_available,
            "material": dep.material,
            "evidence_class": dep.evidence_class,
            "notes": dep.notes,
        }
        rows.append(row)
        if not enforce or not dep.material:
            continue
        if dep.access_mode == "GIT_BLOB_ONLY":
            if intended_data is None:
                failures.append(f"{dep.logical_input}: intended Git blob unavailable")
        elif not exists:
            failures.append(f"{dep.logical_input}: worktree input missing")
        elif not intended_sha or work_sha != intended_sha:
            failures.append(f"{dep.logical_input}: worktree differs from intended frozen content")

    if write:
        out = OUTPUTS / "provenance"
        out.mkdir(parents=True, exist_ok=True)
        fields = list(rows[0])
        with (out / "V3_DEPENDENCY_MANIFEST.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        payload = {
            "frozen_dependency_commit": FROZEN_COMMIT,
            "policy": "worktree inputs must equal intended content; v2 targets are read from Git blobs only",
            "v2_worktree_never_used": True,
            "n_dependencies": len(rows),
            "failures": failures,
            "status": "PASS" if not failures else "FAIL",
            "rows": rows,
        }
        (out / "V3_DEPENDENCY_MANIFEST.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    if failures and enforce:
        raise RuntimeError("dependency audit failed: " + "; ".join(failures))
    return rows
