"""Frozen GW-1B v2 ingestion, QA, allocation, and feature-readiness tools.

This module intentionally contains no groundwater-model fitting. Its role is
to accept an eventual OCWD WRMS delivery without changing the pre-registered
scientific protocol, validate its evidence and identities, and construct
monthly-volume and spatial exposure features on a single common support.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
import yaml


MODULE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MODULE_ROOT.parents[1]
FEASIBILITY_ROOT = REPO_ROOT / "other_sources" / "ocwd_groundwater_feasibility"
GW1A_ROOT = REPO_ROOT / "other_sources" / "ocwd_groundwater_gw1_preflight"
GW1C_ROOT = REPO_ROOT / "other_sources" / "ocwd_groundwater_gw1_climate"
BASELINE_COMMIT = "131657d62712f76acd12dcff461524937ca9fe44"

CONFIG = MODULE_ROOT / "config"
OUTPUTS = MODULE_ROOT / "outputs"
V2_OUTPUTS = OUTPUTS / "v2"
PROVENANCE = OUTPUTS / "provenance"
READINESS = OUTPUTS / "readiness"

PRIMARY_SEED = 20260904
TEMPORAL_PLACEBO_SEED_BASE = 2026090400
SPATIAL_PLACEBO_SEED_BASE = 2026090500
PLACEBO_REPLICATES = 100
SPATIAL_LENGTHS_KM = (2, 5, 10)

MEASUREMENT_CLASSES = {
    "MEASURED_REPORTED", "ALLOCATED", "ESTIMATED", "CALCULATED",
}
CROSSWALK_CLASSES = {"EXACT", "HIGH_CONFIDENCE", "AMBIGUOUS", "NO_MATCH"}
PRIMARY_CROSSWALK_CLASSES = {"EXACT", "HIGH_CONFIDENCE"}
TRANSITION_EXPOSURE_CLASS = "DERIVED_FROM_MONTHLY_VOLUME"
CANONICAL_VOLUME_UNIT = "acre_feet"

BC_FEATURES = [
    "delta_days", "season_sin", "season_cos", "time_trend_years",
    "P_interval_mm", "ET0_interval_mm", "P_pre30_mm", "P_pre90_mm",
    "ET0_pre30_mm", "ET0_pre90_mm",
]
PHI_SUFFIXES = ["interval_af", "pre30_af", "pre90_af"]
B4_TOTAL_FEATURES = [f"total_managed_recharge_{x}" for x in PHI_SUFFIXES] + [f"total_injection_{x}" for x in PHI_SUFFIXES]
B5_PUMPING_FEATURES = [f"total_pumping_{x}" for x in PHI_SUFFIXES]
B6_SPATIAL_FEATURES = [
    f"spatial_{family}_{x}_l{length}km"
    for family in ["pumping", "managed_recharge", "injection"]
    for x in PHI_SUFFIXES
    for length in SPATIAL_LENGTHS_KM
]
MODEL_FEATURES = {
    "BC": list(BC_FEATURES),
    "B4": [*BC_FEATURES, *B4_TOTAL_FEATURES],
    "B5": [*BC_FEATURES, *B4_TOTAL_FEATURES, *B5_PUMPING_FEATURES],
}
B6_MODEL_FEATURES_BY_LENGTH = {
    length: [
        *MODEL_FEATURES["B5"],
        *[
            f"spatial_{family}_{suffix}_l{length}km"
            for family in ["pumping", "managed_recharge", "injection"]
            for suffix in PHI_SUFFIXES
        ],
    ]
    for length in SPATIAL_LENGTHS_KM
}
S_STAR_REQUIRED_FEATURES = [*MODEL_FEATURES["B5"], *B6_SPATIAL_FEATURES]

PARENT_MANIFESTS = {
    FEASIBILITY_ROOT: "outputs/provenance/PACKAGE_FILE_HASHES.csv",
    GW1A_ROOT: "outputs/provenance/GW1A_OUTPUT_HASHES.csv",
    GW1C_ROOT: "outputs/provenance/GW1C_OUTPUT_HASHES.csv",
}

MATERIAL_DEPENDENCIES = [
    ("feasibility_package_hashes", FEASIBILITY_ROOT, "outputs/provenance/PACKAGE_FILE_HASHES.csv", "parent integrity"),
    ("feasibility_source_registry", FEASIBILITY_ROOT, "sources/source_registry.csv", "WRMS source/evidence semantics"),
    ("feasibility_WRMS_request", FEASIBILITY_ROOT, "requests/OCWD_WRMS_DATA_REQUEST.md", "delivery expectations"),
    ("feasibility_event_registry", FEASIBILITY_ROOT, "outputs/tables/EVENT_REGISTRY.csv", "reserved MBI evidence only"),
    ("feasibility_tracer_registry", FEASIBILITY_ROOT, "outputs/tables/TRACER_VALIDATION_REGISTRY.csv", "reserved tracer evidence only"),
    ("gw1a_transitions", GW1A_ROOT, "data/derived/HEAD_TRANSITIONS.parquet", "frozen outcomes and splits"),
    ("gw1a_spatial_folds", GW1A_ROOT, "config/SPATIAL_FOLDS.csv", "immutable folds"),
    ("gw1a_holdouts", GW1A_ROOT, "config/holdouts.yaml", "immutable temporal split"),
    ("gw1a_output_hashes", GW1A_ROOT, "outputs/provenance/GW1A_OUTPUT_HASHES.csv", "parent integrity"),
    ("gw1c_transitions", GW1C_ROOT, "data/derived/GW1C_TRANSITIONS.parquet", "BC population and climate features"),
    ("gw1c_status", GW1C_ROOT, "outputs/FINAL_GW1C_STATUS.json", "BC and Prado decision"),
    ("gw1c_protocol", GW1C_ROOT, "config/analysis_protocol.yaml", "fixed climate specification"),
    ("gw1c_feature_freeze", GW1C_ROOT, "outputs/protocol/CLIMATE_FEATURE_FREEZE.json", "fixed climate windows"),
    ("gw1c_output_hashes", GW1C_ROOT, "outputs/provenance/GW1C_OUTPUT_HASHES.csv", "parent integrity"),
    ("prior_GW1B_protocol_yaml", MODULE_ROOT, "config/GW1B_PROTOCOL_AMENDMENT_20260904.yaml", "preserved superseded protocol"),
    ("prior_GW1B_protocol_md", MODULE_ROOT, "outputs/protocol/GW1B_PROTOCOL_AMENDMENT_20260904.md", "preserved superseded protocol"),
]


class WRMSValidationError(ValueError):
    """Raised when a delivery violates the frozen ingestion contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def run_git(arguments: Sequence[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments], cwd=REPO_ROOT, check=check, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def tree_snapshot(root: Path) -> tuple[str, list[dict[str, object]]]:
    rows = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        rows.append({
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    digest = hashlib.sha256()
    for row in rows:
        digest.update(str(row["path"]).encode())
        digest.update(b"\0")
        digest.update(str(row["sha256"]).encode())
        digest.update(b"\n")
    return digest.hexdigest(), rows


def frozen_blob(repo_relative: str) -> tuple[bool, str, bytes | None]:
    spec = f"{BASELINE_COMMIT}:{repo_relative}"
    check = subprocess.run(
        ["git", "cat-file", "-e", spec], cwd=REPO_ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if check.returncode != 0:
        return False, "", None
    blob = run_git(["rev-parse", spec]).stdout.strip()
    raw = subprocess.run(
        ["git", "show", spec], cwd=REPO_ROOT, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout
    return True, blob, raw


def _committed_manifest(parent: Path) -> tuple[str, dict[str, tuple[int, str]]]:
    rel = PARENT_MANIFESTS[parent]
    repo_rel = (parent.relative_to(REPO_ROOT) / rel).as_posix()
    tracked, blob, raw = frozen_blob(repo_rel)
    if not tracked or raw is None:
        raise RuntimeError(f"Missing parent manifest at baseline: {repo_rel}")
    current = parent / rel
    if not current.exists() or sha256_file(current) != sha256_bytes(raw):
        raise RuntimeError(f"Parent manifest does not match baseline blob: {repo_rel}")
    frame = pd.read_csv(io.BytesIO(raw))
    return blob, {str(row.path): (int(row.bytes), str(row.sha256)) for row in frame.itertuples(index=False)}


def verify_frozen_parents() -> dict[str, object]:
    result: dict[str, object] = {"status": "PASS", "baseline_commit": BASELINE_COMMIT, "parents": {}}
    for label, parent in [("feasibility", FEASIBILITY_ROOT), ("gw1a", GW1A_ROOT), ("gw1c", GW1C_ROOT)]:
        diff = run_git(["diff", "--quiet", BASELINE_COMMIT, "--", parent.relative_to(REPO_ROOT).as_posix()], check=False)
        if diff.returncode != 0:
            raise RuntimeError(f"Tracked frozen-parent drift: {parent}")
        manifest_blob, expected = _committed_manifest(parent)
        failures = []
        for rel, (size, expected_sha) in expected.items():
            path = parent / rel
            if not path.exists() or path.stat().st_size != size or sha256_file(path) != expected_sha:
                failures.append(rel)
        if failures:
            raise RuntimeError(f"Frozen-parent manifest mismatch ({label}): {failures[:10]}")
        tracked = run_git([
            "ls-tree", "-r", "--name-only", BASELINE_COMMIT, "--",
            parent.relative_to(REPO_ROOT).as_posix(),
        ]).stdout.splitlines()
        tracked_failures = []
        for repo_rel in tracked:
            present, _, raw = frozen_blob(repo_rel)
            path = REPO_ROOT / repo_rel
            if not present or raw is None or not path.exists() or sha256_file(path) != sha256_bytes(raw):
                tracked_failures.append(repo_rel)
        if tracked_failures:
            raise RuntimeError(f"Frozen tracked-file mismatch ({label}): {tracked_failures[:10]}")
        tree_sha, files = tree_snapshot(parent)
        result["parents"][label] = {
            "path": parent.relative_to(REPO_ROOT).as_posix(),
            "git_diff_from_baseline": "CLEAN",
            "manifest_git_blob_sha1": manifest_blob,
            "manifest_entries_verified": len(expected),
            "tracked_files_verified": len(tracked),
            "current_tree_sha256": tree_sha,
            "current_total_files_excluding_pycache": len(files),
            "files": files,
        }
    return result


def verify_previous_protocol() -> dict[str, object]:
    baseline = json.loads((PROVENANCE / "GW1B_V2_PREVIOUS_PROTOCOL_BASELINE.json").read_text())
    failures = []
    for row in baseline["files"]:
        path = MODULE_ROOT / row["path"]
        if not path.exists() or sha256_file(path) != row["sha256"]:
            failures.append(row["path"])
        tracked, _, raw = frozen_blob((MODULE_ROOT.relative_to(REPO_ROOT) / row["path"]).as_posix())
        if not tracked or raw is None or sha256_bytes(raw) != row["sha256"]:
            failures.append(f"baseline_blob:{row['path']}")
    if failures:
        raise RuntimeError("Previous GW-1B protocol/report changed: " + ", ".join(failures))
    return {"status": "PASS", "files_verified": len(baseline["files"]), "failures": []}


def create_dependency_manifest() -> pd.DataFrame:
    parent_maps = {parent: _committed_manifest(parent)[1] for parent in PARENT_MANIFESTS}
    rows = []
    for logical, root, rel, role in MATERIAL_DEPENDENCIES:
        path = root / rel
        repo_rel = path.relative_to(REPO_ROOT).as_posix()
        tracked, blob, raw = frozen_blob(repo_rel)
        current_sha = sha256_file(path) if path.exists() else ""
        frozen_sha = sha256_bytes(raw) if raw is not None else ""
        recorded_sha = parent_maps.get(root, {}).get(rel, (0, ""))[1]
        expected = frozen_sha if tracked else recorded_sha
        matches = bool(path.exists() and expected and current_sha == expected)
        if not matches:
            raise RuntimeError(f"Material dependency mismatch: {repo_rel}")
        rows.append({
            "logical_input": logical, "path": repo_rel, "package": root.name,
            "used_by": role, "exists": path.exists(), "bytes": path.stat().st_size,
            "worktree_sha256": current_sha, "tracked_at_baseline": tracked,
            "baseline_git_blob_sha1": blob, "baseline_blob_sha256": frozen_sha,
            "parent_manifest_sha256": recorded_sha,
            "worktree_matches_frozen": matches, "baseline_commit": BASELINE_COMMIT,
        })
    frame = pd.DataFrame(rows)
    frame.to_csv(PROVENANCE / "GW1B_V2_DEPENDENCY_MANIFEST.csv", index=False)
    write_json(PROVENANCE / "GW1B_V2_DEPENDENCY_MANIFEST.json", frame.to_dict(orient="records"))
    return frame


def load_contract() -> dict[str, object]:
    return yaml.safe_load((CONFIG / "WRMS_INGESTION_CONTRACT_v2.yaml").read_text())


def _read_table(path: Path, sheet: str | None = None) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, sheet_name=sheet or 0)
    raise WRMSValidationError(f"Unsupported delivery table format: {path}")


def load_delivery(delivery_root: Path) -> tuple[dict[str, pd.DataFrame], dict[str, object]]:
    """Load only files explicitly named in a delivery manifest."""
    manifest_path = delivery_root / "delivery_manifest.yaml"
    if not manifest_path.exists():
        raise WRMSValidationError("Missing delivery_manifest.yaml")
    manifest = yaml.safe_load(manifest_path.read_text())
    if not isinstance(manifest.get("tables"), dict):
        raise WRMSValidationError("delivery_manifest.yaml must define a tables mapping")
    contract = load_contract()
    required_tables = set(contract["tables"])
    missing = required_tables - set(manifest["tables"])
    if missing:
        raise WRMSValidationError(f"Missing required tables in delivery manifest: {sorted(missing)}")
    tables = {}
    file_rows = []
    for name in sorted(required_tables):
        spec = manifest["tables"][name]
        if isinstance(spec, str):
            relative, sheet = spec, None
        else:
            relative, sheet = spec["path"], spec.get("sheet")
        path = (delivery_root / relative).resolve()
        if delivery_root.resolve() not in path.parents:
            raise WRMSValidationError(f"Delivery path escapes root: {relative}")
        if not path.exists():
            raise WRMSValidationError(f"Missing delivery file: {relative}")
        tables[name] = _read_table(path, sheet)
        file_rows.append({"table": name, "path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path), "sheet": sheet or ""})
    provenance = {"delivery_manifest": manifest, "files": file_rows}
    return tables, provenance


VOLUME_FACTORS_TO_AF = {
    "acre_feet": 1.0, "acre_ft": 1.0, "acre-feet": 1.0, "af": 1.0,
    "gallon": 1.0 / 325851.429, "gallons": 1.0 / 325851.429, "gal": 1.0 / 325851.429,
    "million_gallons": 1_000_000.0 / 325851.429, "mg": 1_000_000.0 / 325851.429, "mgal": 1_000_000.0 / 325851.429,
    "cubic_meter": 1.0 / 1233.48183754752, "cubic_meters": 1.0 / 1233.48183754752, "m3": 1.0 / 1233.48183754752,
}


def normalize_volume(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["volume_unit_original"] = result["volume_unit"].astype(str)
    normalized_unit = result["volume_unit"].astype(str).str.strip().str.lower()
    unknown = sorted(set(normalized_unit) - set(VOLUME_FACTORS_TO_AF))
    if unknown:
        raise WRMSValidationError(f"Unsupported volume units: {unknown}")
    factor = normalized_unit.map(VOLUME_FACTORS_TO_AF).astype(float)
    result["volume_original"] = pd.to_numeric(result["volume"], errors="raise")
    result["volume_af"] = result["volume_original"] * factor
    result["canonical_volume_unit"] = CANONICAL_VOLUME_UNIT
    return result


def _require_columns(name: str, frame: pd.DataFrame, required: Iterable[str]) -> None:
    missing = set(required) - set(frame.columns)
    if missing:
        raise WRMSValidationError(f"{name} missing required columns: {sorted(missing)}")


def _validate_coordinates(frame: pd.DataFrame, id_column: str, name: str) -> None:
    if frame[id_column].isna().any() or frame[id_column].astype(str).str.strip().eq("").any():
        raise WRMSValidationError(f"{name} contains missing identifiers")
    for identifier, group in frame.groupby(id_column, dropna=False):
        coordinates = group[["easting_m", "northing_m", "coordinate_crs"]].drop_duplicates()
        if len(coordinates) > 1:
            raise WRMSValidationError(f"{name} has conflicting coordinates for {identifier}")
    numeric = frame[["easting_m", "northing_m"]].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        raise WRMSValidationError(f"{name} has missing or nonnumeric projected coordinates")


def _validate_volume_table(name: str, frame: pd.DataFrame, id_column: str) -> pd.DataFrame:
    if frame[id_column].isna().any() or frame[id_column].astype(str).str.strip().eq("").any():
        raise WRMSValidationError(f"{name} contains missing identifiers")
    result = normalize_volume(frame)
    result["month"] = pd.to_datetime(result["month"], errors="raise").dt.to_period("M").dt.to_timestamp()
    if result.duplicated([id_column, "month"]).any():
        raise WRMSValidationError(f"{name} contains duplicate identifier-month rows")
    if (result["volume_af"] < 0).any():
        raise WRMSValidationError(f"{name} contains physically invalid negative volume")
    classes = set(result["measurement_class"].astype(str))
    if not classes.issubset(MEASUREMENT_CLASSES):
        raise WRMSValidationError(f"{name} contains unsupported measurement classes: {sorted(classes - MEASUREMENT_CLASSES)}")
    result["measurement_class_original"] = result["measurement_class"].astype(str)
    return result


def _validate_location_activity(frame: pd.DataFrame, id_column: str, name: str) -> pd.DataFrame:
    result = frame.copy()
    result["active_start"] = pd.to_datetime(result["active_start"], errors="raise")
    result["active_end"] = pd.to_datetime(result["active_end"], errors="coerce")
    for identifier, group in result.groupby(id_column, sort=True):
        intervals = group[["active_start", "active_end"]].drop_duplicates()
        if len(intervals) != 1:
            raise WRMSValidationError(f"{name} has conflicting/overlapping activity intervals for {identifier}")
    if (result["active_end"].notna() & (result["active_end"] < result["active_start"])).any():
        raise WRMSValidationError(f"{name} contains active_end before active_start")
    month_end = result["month"] + pd.offsets.MonthEnd(0)
    outside = (month_end < result["active_start"]) | (result["active_end"].notna() & (result["month"] > result["active_end"]))
    if outside.any():
        raise WRMSValidationError(f"{name} contains volume outside active dates")
    return result


def validate_delivery_tables(tables: Mapping[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], dict[str, object]]:
    contract = load_contract()
    required_tables = set(contract["tables"])
    missing_tables = required_tables - set(tables)
    if missing_tables:
        raise WRMSValidationError(f"Missing required delivery tables: {sorted(missing_tables)}")
    for name in required_tables:
        _require_columns(name, tables[name], contract["tables"][name]["required_columns"])

    well = tables["well_master"].copy()
    _validate_coordinates(well, "well_id", "well_master")
    if well["well_id"].duplicated().any():
        raise WRMSValidationError("well_master contains duplicate well IDs")
    well["active_start"] = pd.to_datetime(well["active_start"], errors="raise")
    well["active_end"] = pd.to_datetime(well["active_end"], errors="coerce")
    if (well["active_end"].notna() & (well["active_end"] < well["active_start"])).any():
        raise WRMSValidationError("well_master contains active_end before active_start")

    pumping = _validate_volume_table("monthly_pumping", tables["monthly_pumping"], "well_id")
    recharge = _validate_volume_table("managed_recharge", tables["managed_recharge"], "facility_id")
    injection = _validate_volume_table("injection", tables["injection"], "well_id")
    recharge = _validate_location_activity(recharge, "facility_id", "managed_recharge")
    injection = _validate_location_activity(injection, "well_id", "injection")
    _validate_coordinates(recharge, "facility_id", "managed_recharge")
    _validate_coordinates(injection, "well_id", "injection")

    well_dates = well.set_index("well_id")[["active_start", "active_end"]]
    joined = pumping.join(well_dates, on="well_id", validate="many_to_one")
    if joined[["active_start"]].isna().any().any():
        missing_ids = sorted(set(joined.loc[joined["active_start"].isna(), "well_id"]))
        raise WRMSValidationError(f"Pumping IDs absent from well master: {missing_ids[:10]}")
    month_end = joined["month"] + pd.offsets.MonthEnd(0)
    if ((month_end < joined["active_start"]) | (joined["active_end"].notna() & (joined["month"] > joined["active_end"]))).any():
        raise WRMSValidationError("Pumping contains months outside well active dates")

    crosswalk = tables["id_crosswalk"].copy()
    if crosswalk[["source_table", "source_id", "canonical_id", "match_status"]].isna().any().any():
        raise WRMSValidationError("id_crosswalk contains missing IDs/status")
    unknown_status = set(crosswalk["match_status"].astype(str)) - CROSSWALK_CLASSES
    if unknown_status:
        raise WRMSValidationError(f"Unknown crosswalk status: {sorted(unknown_status)}")
    if crosswalk.duplicated(["source_table", "source_id"]).any():
        raise WRMSValidationError("id_crosswalk contains duplicate source-table/source-ID rows")
    primary_crosswalk = crosswalk.loc[crosswalk["match_status"].isin(PRIMARY_CROSSWALK_CLASSES)].copy()
    if primary_crosswalk["match_status"].isin({"AMBIGUOUS", "NO_MATCH"}).any():  # defensive
        raise WRMSValidationError("Ambiguous crosswalk entered primary set")

    validated = {
        "well_master": well,
        "monthly_pumping": pumping,
        "managed_recharge": recharge,
        "injection": injection,
        "id_crosswalk": crosswalk,
        "primary_id_crosswalk": primary_crosswalk,
    }
    audit = {
        "status": "PASS",
        "rows": {name: len(frame) for name, frame in validated.items()},
        "measurement_classes_preserved": {
            name: sorted(set(validated[name]["measurement_class_original"]))
            for name in ["monthly_pumping", "managed_recharge", "injection"]
        },
        "ambiguous_crosswalk_rows_excluded": int(crosswalk["match_status"].eq("AMBIGUOUS").sum()),
        "silent_fuzzy_matching": False,
        "guessed_layers": False,
    }
    return validated, audit


def _month_starts(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    if start > end:
        return pd.DatetimeIndex([])
    return pd.date_range(start.to_period("M").start_time, end.to_period("M").start_time, freq="MS")


def proportional_month_exposure(
    monthly: pd.DataFrame,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
) -> tuple[float, bool, list[str]]:
    """Allocate monthly totals over an inclusive daily window.

    Missing months are never interpreted as zero; callers must provide explicit
    zero-volume rows for complete active panels.
    """
    start, end = pd.Timestamp(window_start).normalize(), pd.Timestamp(window_end).normalize()
    if start > end:
        return np.nan, False, []
    table = monthly.copy()
    table["month"] = pd.to_datetime(table["month"]).dt.to_period("M").dt.to_timestamp()
    expected_months = _month_starts(start, end)
    if table["month"].duplicated().any():
        raise WRMSValidationError("Duplicate month in location exposure input")
    indexed = table.set_index("month")
    if not set(expected_months).issubset(set(indexed.index)):
        return np.nan, False, []
    total = 0.0
    classes = set()
    for month in expected_months:
        row = indexed.loc[month]
        month_end = month + pd.offsets.MonthEnd(0)
        overlap_start, overlap_end = max(start, month), min(end, month_end)
        days = int((overlap_end - overlap_start).days) + 1
        total += float(row["volume_af"]) * days / int(month.days_in_month)
        classes.add(str(row["measurement_class_original"] if "measurement_class_original" in row else row["measurement_class"]))
    return total, True, sorted(classes)


def allocate_monthly_forcing_to_transitions(
    monthly: pd.DataFrame,
    transitions: pd.DataFrame,
    location_id_column: str,
    forcing_family: str,
) -> pd.DataFrame:
    required = {location_id_column, "month", "volume_af", "measurement_class"}
    _require_columns(forcing_family, monthly, required)
    table = monthly.copy()
    if "measurement_class_original" not in table:
        table["measurement_class_original"] = table["measurement_class"].astype(str)
    rows = []
    for location_id, location in table.groupby(location_id_column, sort=True):
        for transition in transitions.itertuples(index=False):
            origin = pd.Timestamp(transition.t_prev).normalize()
            target = pd.Timestamp(transition.t_target).normalize()
            interval, ok_interval, class_interval = proportional_month_exposure(location, origin + pd.Timedelta(days=1), target)
            pre30, ok30, class30 = proportional_month_exposure(location, origin - pd.Timedelta(days=30), origin - pd.Timedelta(days=1))
            pre90, ok90, class90 = proportional_month_exposure(location, origin - pd.Timedelta(days=90), origin - pd.Timedelta(days=1))
            rows.append({
                "transition_id": transition.transition_id,
                "location_id": location_id,
                "forcing_family": forcing_family,
                "interval_af": interval,
                "pre30_af": pre30,
                "pre90_af": pre90,
                "interval_complete": ok_interval,
                "pre30_complete": ok30,
                "pre90_complete": ok90,
                "source_measurement_classes": "|".join(sorted(set(class_interval + class30 + class90))),
                "source_measurement_classes_preserved": True,
                "source_temporal_resolution": "MONTHLY",
                "daily_measured": False,
                "allocation_assumption": "UNIFORM_WITHIN_MONTH",
                "transition_exposure_class": TRANSITION_EXPOSURE_CLASS,
                "calendar_month_compatible": bool(origin.is_month_end and target.is_month_end),
            })
    return pd.DataFrame(rows)


def verify_monthly_conservation(monthly: pd.DataFrame) -> dict[str, object]:
    """Verify a full-month proportional allocation reproduces each total."""
    failures = []
    maximum_error = 0.0
    for row in monthly.itertuples(index=False):
        month = pd.Timestamp(row.month).to_period("M").start_time
        end = month + pd.offsets.MonthEnd(0)
        one = pd.DataFrame({
            "month": [month], "volume_af": [float(row.volume_af)],
            "measurement_class": [str(row.measurement_class)],
        })
        allocated, complete, _ = proportional_month_exposure(one, month, end)
        error = abs(float(row.volume_af) - allocated) if complete else math.inf
        maximum_error = max(maximum_error, error)
        if not complete or error > 1e-12:
            failures.append(str(month.date()))
    return {"status": "PASS" if not failures else "FAIL", "rows_checked": len(monthly), "maximum_absolute_error_af": maximum_error, "failures": failures}


def basin_total_features(exposures: pd.DataFrame, family: str) -> pd.DataFrame:
    subset = exposures.loc[exposures["forcing_family"].eq(family)].copy()
    if subset.empty:
        raise WRMSValidationError(f"No exposure rows for {family}")
    complete = subset[["interval_complete", "pre30_complete", "pre90_complete"]].all(axis=1)
    subset = subset.loc[complete]
    grouped = subset.groupby("transition_id", as_index=False)[["interval_af", "pre30_af", "pre90_af"]].sum()
    return grouped.rename(columns={column: f"total_{family}_{column}" for column in PHI_SUFFIXES})


def spatial_features(
    exposures: pd.DataFrame,
    forcing_locations: pd.DataFrame,
    monitoring_transitions: pd.DataFrame,
    family: str,
) -> pd.DataFrame:
    _require_columns("forcing_locations", forcing_locations, ["location_id", "easting_m", "northing_m"])
    _require_columns("monitoring_transitions", monitoring_transitions, ["transition_id", "easting_m", "northing_m"])
    if forcing_locations["location_id"].duplicated().any():
        raise WRMSValidationError("Forcing locations contain duplicate IDs")
    exposure = exposures.loc[exposures["forcing_family"].eq(family)].merge(
        forcing_locations[["location_id", "easting_m", "northing_m"]], on="location_id", validate="many_to_one",
    )
    base = monitoring_transitions[["transition_id", "easting_m", "northing_m"]].rename(
        columns={"easting_m": "monitor_easting_m", "northing_m": "monitor_northing_m"}
    )
    joined = exposure.merge(base, on="transition_id", validate="many_to_one")
    distance_m = np.sqrt(
        (joined["easting_m"] - joined["monitor_easting_m"]) ** 2
        + (joined["northing_m"] - joined["monitor_northing_m"]) ** 2
    )
    rows = []
    for length in SPATIAL_LENGTHS_KM:
        weight = np.exp(-distance_m / (length * 1000.0))
        weighted = joined[["transition_id", *PHI_SUFFIXES]].copy()
        for suffix in PHI_SUFFIXES:
            weighted[suffix] = weighted[suffix] * weight
        aggregate = weighted.groupby("transition_id", as_index=False)[PHI_SUFFIXES].sum()
        aggregate = aggregate.rename(columns={suffix: f"spatial_{family}_{suffix}_l{length}km" for suffix in PHI_SUFFIXES})
        rows.append(aggregate.set_index("transition_id"))
    return pd.concat(rows, axis=1).reset_index()


def validate_nested_hierarchy() -> dict[str, object]:
    sets = {name: set(features) for name, features in MODEL_FEATURES.items()}
    relations = {
        "BC_subset_B4": sets["BC"] < sets["B4"],
        "B4_subset_B5": sets["B4"] < sets["B5"],
    }
    for length, features in B6_MODEL_FEATURES_BY_LENGTH.items():
        relations[f"B5_subset_B6_l{length}km"] = sets["B5"] < set(features)
        relations[f"B6_l{length}km_retains_every_B5_feature"] = sets["B5"].issubset(features)
    if not all(relations.values()):
        raise RuntimeError(f"Nested hierarchy failure: {relations}")
    return {
        "status": "PASS", "relations": relations,
        "feature_counts": {
            **{key: len(value) for key, value in MODEL_FEATURES.items()},
            **{f"B6_l{length}km": len(value) for length, value in B6_MODEL_FEATURES_BY_LENGTH.items()},
            "S_star_candidate_universe": len(S_STAR_REQUIRED_FEATURES),
        },
        "B6_scale_rule": "one validation-selected length only; candidate lengths are not simultaneous fitted features",
    }


def build_common_support(features: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    """Build S* once using every feature required through all B6 candidates."""
    required = [*S_STAR_REQUIRED_FEATURES, "transition_id", "site_code", "temporal_split", "spatial_fold", "crosswalk_status"]
    _require_columns("S_star_input", features, required)
    eligible = features["crosswalk_status"].isin(PRIMARY_CROSSWALK_CLASSES)
    complete = features[S_STAR_REQUIRED_FEATURES].notna().all(axis=1)
    s_star = features.loc[eligible & complete].copy()
    if s_star["transition_id"].duplicated().any():
        raise WRMSValidationError("S* contains duplicate transitions")
    original = len(features)
    split_counts = s_star.groupby("temporal_split").size().to_dict()
    fold_counts = s_star.groupby(["temporal_split", "spatial_fold"]).size().rename("n").reset_index().to_dict(orient="records")
    summary = {
        "status": "CONSTRUCTED",
        "original_transition_count": original,
        "retained_transition_count": len(s_star),
        "retained_wells": s_star["site_code"].nunique(),
        "retention_percentage": 100.0 * len(s_star) / original if original else 0.0,
        "counts_by_temporal_split": split_counts,
        "counts_by_temporal_split_and_spatial_fold": fold_counts,
        "applies_identically_to": ["BC", "B4", "B5", "B6"],
        "required_feature_count": len(S_STAR_REQUIRED_FEATURES),
        "S_star_requires_all_scale_candidates": True,
        "fitted_B6_uses_one_validation_selected_scale": True,
        "model_specific_sample_selection": False,
    }
    return s_star, summary


def temporal_pumping_placebo(monthly: pd.DataFrame, replicate: int) -> pd.DataFrame:
    """Permute across years within well, calendar month, and frozen split."""
    required = ["well_id", "month", "volume_af", "temporal_split"]
    _require_columns("temporal_placebo", monthly, required)
    if not 0 <= replicate < PLACEBO_REPLICATES:
        raise ValueError("replicate must be 0..99")
    result = monthly.copy()
    result["month"] = pd.to_datetime(result["month"])
    result["calendar_month"] = result["month"].dt.month
    rng = np.random.default_rng(TEMPORAL_PLACEBO_SEED_BASE + replicate)
    result["volume_af_real"] = result["volume_af"].to_numpy()
    result["volume_af"] = result.groupby(
        ["well_id", "calendar_month", "temporal_split"], sort=True
    )["volume_af"].transform(lambda values: rng.permutation(values.to_numpy()))
    result["placebo_replicate"] = replicate
    result["placebo_seed"] = TEMPORAL_PLACEBO_SEED_BASE + replicate
    result["split_crossing"] = False
    return result.drop(columns="calendar_month")


def spatial_identity_placebo(locations: pd.DataFrame, replicate: int, stratum_column: str) -> pd.DataFrame:
    """Permute authoritative coordinate identities only within strata."""
    _require_columns("spatial_placebo", locations, ["location_id", "easting_m", "northing_m", stratum_column])
    if locations[stratum_column].isna().any():
        raise WRMSValidationError("Spatial placebo requires complete authoritative strata")
    if not 0 <= replicate < PLACEBO_REPLICATES:
        raise ValueError("replicate must be 0..99")
    result = locations.copy()
    rng = np.random.default_rng(SPATIAL_PLACEBO_SEED_BASE + replicate)
    result["easting_m_real"] = result["easting_m"]
    result["northing_m_real"] = result["northing_m"]
    for _, index in result.groupby(stratum_column, sort=True).groups.items():
        index = np.asarray(list(index))
        permuted = rng.permutation(index)
        result.loc[index, ["easting_m", "northing_m"]] = result.loc[permuted, ["easting_m", "northing_m"]].to_numpy()
    result["placebo_replicate"] = replicate
    result["placebo_seed"] = SPATIAL_PLACEBO_SEED_BASE + replicate
    result["permuted_within_stratum"] = True
    return result
