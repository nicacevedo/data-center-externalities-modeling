"""Deterministic OCWD GW-1C climate/background null benchmark.

This module deliberately fits only pooled linear response baselines. It reads
the frozen GW-1A transitions and folds, never interpolates heads, and contains
no pumping, managed-recharge, groundwater-network, GNN, or MODFLOW model.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

import matplotlib.pyplot as plt
import netCDF4
import numpy as np
import pandas as pd
import yaml


MODULE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MODULE_ROOT.parents[1]
FEASIBILITY_ROOT = REPO_ROOT / "other_sources" / "ocwd_groundwater_feasibility"
GW1A_ROOT = REPO_ROOT / "other_sources" / "ocwd_groundwater_gw1_preflight"
GW1B_ROOT = REPO_ROOT / "other_sources" / "ocwd_groundwater_gw1b"
BASELINE_COMMIT = "9e7ff6c43f28fcc66760681695459445283f6396"

RAW = MODULE_ROOT / "data" / "raw" / "gridmet"
DERIVED = MODULE_ROOT / "data" / "derived"
OUTPUTS = MODULE_ROOT / "outputs"
FIGURES = OUTPUTS / "figures"
TABLES = OUTPUTS / "tables"
METRICS = OUTPUTS / "metrics"
PROVENANCE = OUTPUTS / "provenance"
PROTOCOL = OUTPUTS / "protocol"

SEED = 20260904
OCWD_ORIGIN = "OCWD_ORIGIN_REPUBLISHED_BY_DWR"
INDEPENDENT_ORIGIN = "INDEPENDENT_AGENCY_OBSERVATION"
PRIMARY_GAP = 120
SENSITIVITY_GAPS = [90, 180]
BOOTSTRAPS = 1000
# Frozen prediction Parquet values reproduce exactly. The canonical metrics CSV
# is decimal-serialized, so its round-trip comparison needs a 1e-8 ft tolerance.
TOLERANCE = 1e-8

B1_FEATURES = ["delta_days", "season_sin", "season_cos", "time_trend_years"]
CLIMATE_FEATURES = [
    "P_interval_mm", "ET0_interval_mm", "P_pre30_mm", "P_pre90_mm",
    "ET0_pre30_mm", "ET0_pre90_mm",
]
PRADO_FEATURES = [
    "log1p_interval_mean_discharge_cfs",
    "log1p_antecedent_30d_mean_discharge_cfs",
]
MODEL_FEATURES = {
    "B1": B1_FEATURES,
    "B1C": [*B1_FEATURES, *CLIMATE_FEATURES],
    "B1CH": [*B1_FEATURES, *CLIMATE_FEATURES, *PRADO_FEATURES],
}

GRIDMET = {
    "pr": {
        "variable": "precipitation_amount",
        "units": "mm",
        "description": "Daily accumulated precipitation",
    },
    "pet": {
        "variable": "potential_evapotranspiration",
        "units": "mm",
        "description": "Daily reference evapotranspiration (short grass)",
    },
}
GRIDMET_BASE = "https://tds-proxy.nkn.uidaho.edu/thredds/dodsC/MET"
GRIDMET_START = pd.Timestamp("1991-07-01")
GRIDMET_END = pd.Timestamp("1998-11-30")
LAT_SLICE = (369, 381)  # inclusive DAP indices
LON_SLICE = (158, 173)  # inclusive DAP indices
BASIN_BUFFER_DEGREES = 0.1

MATERIAL_DEPENDENCIES = [
    ("gw1a_head_transitions", GW1A_ROOT, "data/derived/HEAD_TRANSITIONS.parquet", "response population, features, splits"),
    ("gw1a_spatial_folds", GW1A_ROOT, "config/SPATIAL_FOLDS.csv", "immutable spatial folds"),
    ("gw1a_holdouts", GW1A_ROOT, "config/holdouts.yaml", "temporal split"),
    ("gw1a_analysis_protocol", GW1A_ROOT, "config/analysis_protocol.yaml", "B1 and Prado definitions"),
    ("gw1a_primary_metrics", GW1A_ROOT, "outputs/tables/PRIMARY_METRICS.csv", "B1 reproduction target"),
    ("gw1a_primary_predictions", GW1A_ROOT, "data/derived/PRIMARY_TEST_PREDICTIONS.parquet", "B1 prediction reproduction target"),
    ("gw1a_sensitivity_metrics", GW1A_ROOT, "outputs/tables/SENSITIVITY_METRICS.csv", "cadence protocol"),
    ("gw1a_protocol_freeze", GW1A_ROOT, "outputs/protocol/PROTOCOL_FREEZE.json", "frozen protocol"),
    ("gw1a_reserved_validation", GW1A_ROOT, "outputs/protocol/RESERVED_EXTERNAL_VALIDATION.json", "reserved tracer/MBI assets"),
    ("gw1a_dependency_manifest", GW1A_ROOT, "outputs/provenance/GW1A_DEPENDENCY_MANIFEST.csv", "upstream provenance"),
    ("gw1a_output_hash_manifest", GW1A_ROOT, "outputs/provenance/GW1A_OUTPUT_HASHES.csv", "ignored output integrity"),
    ("gw1a_final_status", GW1A_ROOT, "outputs/FINAL_GW1A_STATUS.json", "frozen result interpretation"),
    ("basin_geometry", FEASIBILITY_ROOT, "data/derived/DWR_BASIN_8_001.geojson", "climate subset and coverage context"),
    ("well_master", FEASIBILITY_ROOT, "data/derived/DWR_OCWD_WELL_MASTER.parquet", "authoritative coordinate provenance"),
    ("event_registry", FEASIBILITY_ROOT, "outputs/tables/EVENT_REGISTRY.csv", "reserved MBI validation registry only"),
    ("tracer_registry", FEASIBILITY_ROOT, "outputs/tables/TRACER_VALIDATION_REGISTRY.csv", "reserved tracer registry only"),
    ("feasibility_source_registry", FEASIBILITY_ROOT, "sources/source_registry.csv", "source provenance"),
    ("feasibility_package_hashes", FEASIBILITY_ROOT, "outputs/provenance/PACKAGE_FILE_HASHES.csv", "ignored artifact integrity"),
]


def ensure_directories() -> None:
    for path in [RAW, DERIVED, FIGURES, TABLES, METRICS, PROVENANCE, PROTOCOL]:
        path.mkdir(parents=True, exist_ok=True)


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


def run_git(args: Sequence[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, check=check, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def tree_snapshot(root: Path) -> tuple[str, list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
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


def _frozen_blob(repo_relative: str) -> tuple[bool, str, bytes | None]:
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


def _committed_manifest(package_root: Path) -> tuple[str, dict[str, tuple[int, str]]]:
    if package_root == GW1A_ROOT:
        rel = "outputs/provenance/GW1A_OUTPUT_HASHES.csv"
    elif package_root == FEASIBILITY_ROOT:
        rel = "outputs/provenance/PACKAGE_FILE_HASHES.csv"
    else:  # pragma: no cover
        raise ValueError(package_root)
    repo_rel = (package_root.relative_to(REPO_ROOT) / rel).as_posix()
    tracked, blob, raw = _frozen_blob(repo_rel)
    if not tracked or raw is None:
        raise RuntimeError(f"Missing committed parent hash manifest: {repo_rel}")
    current = package_root / rel
    if not current.exists() or sha256_file(current) != sha256_bytes(raw):
        raise RuntimeError(f"Parent hash manifest differs from baseline blob: {repo_rel}")
    frame = pd.read_csv(io.BytesIO(raw))
    return blob, {str(r.path): (int(r.bytes), str(r.sha256)) for r in frame.itertuples(index=False)}


def verify_frozen_parents(write_start: bool = False) -> dict[str, object]:
    ensure_directories()
    result: dict[str, object] = {
        "status": "PASS",
        "baseline_commit": BASELINE_COMMIT,
        "parents": {},
    }
    for label, root in [("feasibility", FEASIBILITY_ROOT), ("gw1a", GW1A_ROOT)]:
        diff = run_git(["diff", "--quiet", BASELINE_COMMIT, "--", root.relative_to(REPO_ROOT).as_posix()], check=False)
        if diff.returncode != 0:
            raise RuntimeError(f"Frozen parent has tracked differences from baseline: {root}")
        manifest_blob, expected = _committed_manifest(root)
        failures = []
        for rel, (size, expected_sha) in expected.items():
            path = root / rel
            if not path.exists() or path.stat().st_size != size or sha256_file(path) != expected_sha:
                failures.append(rel)
        if failures:
            raise RuntimeError(f"Frozen parent manifest mismatch ({label}): {failures[:10]}")
        tracked_files = run_git([
            "ls-tree", "-r", "--name-only", BASELINE_COMMIT, "--",
            root.relative_to(REPO_ROOT).as_posix(),
        ]).stdout.splitlines()
        tracked_failures = []
        for rel in tracked_files:
            path = REPO_ROOT / rel
            ok, _, raw = _frozen_blob(rel)
            if not ok or raw is None or not path.exists() or sha256_file(path) != sha256_bytes(raw):
                tracked_failures.append(rel)
        if tracked_failures:
            raise RuntimeError(f"Frozen tracked blob mismatch ({label}): {tracked_failures[:10]}")
        tree_sha, files = tree_snapshot(root)
        result["parents"][label] = {
            "path": root.relative_to(REPO_ROOT).as_posix(),
            "git_diff_from_baseline": "CLEAN",
            "tracked_files_verified": len(tracked_files),
            "manifest_entries_verified": len(expected),
            "manifest_git_blob_sha1": manifest_blob,
            "current_total_files": len(files),
            "current_tree_sha256": tree_sha,
            "files": files,
        }
    if write_start:
        write_json(PROVENANCE / "FROZEN_PARENT_INTEGRITY_START.json", result)
    return result


def create_dependency_manifest() -> pd.DataFrame:
    manifests = {
        GW1A_ROOT: _committed_manifest(GW1A_ROOT)[1],
        FEASIBILITY_ROOT: _committed_manifest(FEASIBILITY_ROOT)[1],
    }
    rows = []
    for logical, root, rel, role in MATERIAL_DEPENDENCIES:
        path = root / rel
        repo_rel = path.relative_to(REPO_ROOT).as_posix()
        tracked, blob, raw = _frozen_blob(repo_rel)
        current_sha = sha256_file(path) if path.exists() else ""
        blob_sha256 = sha256_bytes(raw) if raw is not None else ""
        recorded = manifests[root].get(rel, (0, ""))[1]
        expected = blob_sha256 if tracked else recorded
        matches = bool(path.exists() and expected and current_sha == expected)
        if not matches:
            raise RuntimeError(f"Material input does not match baseline: {repo_rel}")
        rows.append({
            "logical_input": logical,
            "path": repo_rel,
            "parent_module": root.name,
            "used_by": role,
            "exists": path.exists(),
            "bytes": path.stat().st_size,
            "worktree_sha256": current_sha,
            "tracked_at_baseline": tracked,
            "baseline_git_blob_sha1": blob,
            "baseline_blob_sha256": blob_sha256,
            "parent_manifest_sha256": recorded,
            "worktree_matches_frozen": matches,
            "baseline_commit": BASELINE_COMMIT,
            "resolution": "verified exact working-tree bytes; no parent copy modified",
        })
    frame = pd.DataFrame(rows)
    frame.to_csv(PROVENANCE / "GW1C_DEPENDENCY_MANIFEST.csv", index=False)
    write_json(PROVENANCE / "GW1C_DEPENDENCY_MANIFEST.json", frame.to_dict(orient="records"))
    return frame


def record_preflight(parent_integrity: dict[str, object]) -> None:
    # This is a task-start record, not a live-status record. Preserve the first
    # capture so deterministic scientific replays do not rewrite provenance.
    if (PROVENANCE / "REPOSITORY_PREFLIGHT.json").exists():
        return
    submodule = run_git(["submodule", "status"], check=False)
    status = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(REPO_ROOT),
        "branch": run_git(["branch", "--show-current"]).stdout.strip(),
        "HEAD": run_git(["rev-parse", "HEAD"]).stdout.strip(),
        "scientific_baseline_commit": BASELINE_COMMIT,
        "HEAD_matches_scientific_baseline": run_git(["rev-parse", "HEAD"]).stdout.strip() == BASELINE_COMMIT,
        "task_start_status_short": [" m Data-center-PUE-prediction-tool"],
        "current_status_short": run_git(["status", "--short"]).stdout.splitlines(),
        "existing_unrelated_dirty_paths": ["Data-center-PUE-prediction-tool"],
        "submodule_status_exit_code": submodule.returncode,
        "submodule_status_stdout": submodule.stdout.splitlines(),
        "submodule_status_stderr": submodule.stderr.strip(),
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "frozen_parent_summary": {
            key: {k: v for k, v in value.items() if k != "files"}
            for key, value in parent_integrity["parents"].items()
        },
    }
    write_json(PROVENANCE / "REPOSITORY_PREFLIGHT.json", status)


@dataclass
class OLSFit:
    model: str
    features: list[str]
    mean: np.ndarray
    scale: np.ndarray
    coefficients: np.ndarray
    condition_number: float


def fit_ols(model: str, train: pd.DataFrame) -> OLSFit:
    features = MODEL_FEATURES[model]
    x = train[features].to_numpy(float)
    y = train["delta_h"].to_numpy(float)
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise RuntimeError(f"Non-finite training input for {model}")
    mean = x.mean(axis=0)
    scale = x.std(axis=0, ddof=0)
    scale = np.where(scale > 1e-12, scale, 1.0)
    design = np.column_stack([np.ones(len(x)), (x - mean) / scale])
    condition = float(np.linalg.cond(design))
    if condition > 1e8:
        raise RuntimeError(f"Severe standardized design conditioning for {model}: {condition:g}")
    coefficients = np.linalg.lstsq(design, y, rcond=None)[0]
    return OLSFit(model, list(features), mean, scale, coefficients, condition)


def predict(fit: OLSFit, frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    x = frame[fit.features].to_numpy(float)
    delta = np.column_stack([np.ones(len(x)), (x - fit.mean) / fit.scale]) @ fit.coefficients
    head = frame["h_prev"].to_numpy(float) + delta
    return head, delta


def _eligible(transitions: pd.DataFrame, threshold: int, require_climate: bool) -> pd.DataFrame:
    mask = (
        transitions[f"gap_le_{threshold}_days"].astype(bool)
        & transitions["hydrologic_feature_complete"].astype(bool)
        & transitions["transition_independence_class"].eq(OCWD_ORIGIN)
    )
    if require_climate:
        mask &= transitions["climate_feature_complete"].astype(bool)
    return transitions.loc[mask].copy()


def _prediction_set(
    transitions: pd.DataFrame,
    threshold: int,
    models: Iterable[str],
    require_climate: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    eligible = _eligible(transitions, threshold, require_climate)
    predictions = []
    fits = []
    samples = []
    base_columns = [
        "transition_id", "site_code", "t_prev", "t_target", "target_month",
        "delta_days", "gap_group_primary", "spatial_fold", "h_prev",
        "h_target", "delta_h",
    ]
    regimes: list[tuple[str, int | None]] = [("T1_TEMPORAL_OOS", None)] + [
        ("T2_SPATIOTEMPORAL_OOS", fold) for fold in range(1, 6)
    ]
    for regime, fold in regimes:
        if fold is None:
            train = eligible.loc[eligible["temporal_split"].eq("TRAIN")]
            train_wells = set(train["site_code"])
            test = eligible.loc[
                eligible["temporal_split"].eq("TEST") & eligible["site_code"].isin(train_wells)
            ]
        else:
            train = eligible.loc[
                eligible["temporal_split"].eq("TRAIN") & eligible["spatial_fold"].ne(fold)
            ]
            test = eligible.loc[
                eligible["temporal_split"].eq("TEST") & eligible["spatial_fold"].eq(fold)
            ]
        if train.empty or test.empty:
            raise RuntimeError(f"Empty OOS sample: {regime}, fold={fold}, gap={threshold}")
        for model in models:
            fitted = fit_ols(model, train)
            h_pred, delta_pred = predict(fitted, test)
            pred = test[base_columns].copy()
            pred["model"] = model
            pred["regime"] = regime
            pred["held_out_spatial_fold"] = "NONE" if fold is None else str(fold)
            pred["gap_threshold_days"] = threshold
            pred["h_pred"] = h_pred
            pred["delta_pred"] = delta_pred
            predictions.append(pred)
            fit_id = f"{regime}_G{threshold}_F{fold if fold is not None else 'ALL'}_{model}"
            for index, feature in enumerate(["INTERCEPT", *fitted.features]):
                fits.append({
                    "fit_id": fit_id,
                    "regime": regime,
                    "held_out_spatial_fold": "NONE" if fold is None else str(fold),
                    "gap_threshold_days": threshold,
                    "model": model,
                    "target": "delta_h",
                    "feature": feature,
                    "coefficient_standardized_scale": fitted.coefficients[index],
                    "training_feature_mean": 0.0 if index == 0 else fitted.mean[index - 1],
                    "training_feature_scale": 1.0 if index == 0 else fitted.scale[index - 1],
                    "standardized_design_condition_number": fitted.condition_number,
                    "n_training_transitions": len(train),
                    "n_training_wells": train["site_code"].nunique(),
                    "fit_split": "TRAIN",
                    "training_target_month_min": train["target_month"].min(),
                    "training_target_month_max": train["target_month"].max(),
                    "validation_used": False,
                    "test_used": False,
                    "hyperparameter_search": "NONE",
                })
            sample = train[[
                "transition_id", "site_code", "target_month", "temporal_split",
                "spatial_fold", "transition_independence_class",
            ]].copy()
            sample["fit_id"] = fit_id
            sample["model"] = model
            sample["regime"] = regime
            sample["held_out_spatial_fold"] = "NONE" if fold is None else str(fold)
            sample["gap_threshold_days"] = threshold
            samples.append(sample)
    return pd.concat(predictions, ignore_index=True), pd.DataFrame(fits), pd.concat(samples, ignore_index=True)


def _metric(group: pd.DataFrame) -> dict[str, object]:
    error = group["delta_pred"].to_numpy() - group["delta_h"].to_numpy()
    actual = group["delta_h"].to_numpy()
    predicted = group["delta_pred"].to_numpy()
    meaningful = actual != 0
    sign = float(np.mean(np.sign(predicted[meaningful]) == np.sign(actual[meaningful]))) if meaningful.any() else np.nan
    return {
        "n_transitions": len(group),
        "n_wells": group["site_code"].nunique(),
        "MAE_delta_h_ft": float(np.mean(np.abs(error))),
        "RMSE_delta_h_ft": float(np.sqrt(np.mean(error ** 2))),
        "bias_delta_h_ft": float(np.mean(error)),
        "sign_accuracy_delta_h": sign,
        "delta_h_IQR_ft": float(np.subtract(*np.percentile(actual, [75, 25]))),
        "note": "head-level residual equals delta-h residual conditional on observed h_prev",
    }


def aggregate_metrics(predictions: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    rows = []
    for keys, group in predictions.groupby(group_columns, sort=True, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = dict(zip(group_columns, keys))
        row.update(_metric(group))
        rows.append(row)
    return pd.DataFrame(rows)


def add_b1_skill(metrics: pd.DataFrame, key_columns: list[str]) -> pd.DataFrame:
    base = metrics.loc[metrics["model"].eq("B1"), key_columns + ["RMSE_delta_h_ft", "MAE_delta_h_ft"]].rename(
        columns={"RMSE_delta_h_ft": "B1_RMSE_delta_h_ft", "MAE_delta_h_ft": "B1_MAE_delta_h_ft"}
    )
    result = metrics.merge(base, on=key_columns, how="left", validate="many_to_one")
    result["RMSE_skill_vs_B1"] = 1.0 - result["RMSE_delta_h_ft"] / result["B1_RMSE_delta_h_ft"]
    result["MAE_skill_vs_B1"] = 1.0 - result["MAE_delta_h_ft"] / result["B1_MAE_delta_h_ft"]
    return result


def _well_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (regime, model, site), group in predictions.groupby(["regime", "model", "site_code"], sort=True):
        row = {"regime": regime, "model": model, "site_code": site}
        row.update(_metric(group))
        rows.append(row)
    return pd.DataFrame(rows)


def _comparison_summary(predictions: pd.DataFrame, comparison: str, reference: str, regime: str) -> dict[str, object]:
    model = predictions.loc[(predictions["model"] == comparison) & (predictions["regime"] == regime)]
    ref = predictions.loc[(predictions["model"] == reference) & (predictions["regime"] == regime)]
    joined = model[["transition_id", "site_code", "delta_h", "delta_pred"]].merge(
        ref[["transition_id", "delta_pred"]], on="transition_id",
        suffixes=("_model", "_reference"), validate="one_to_one",
    )
    err_m = joined["delta_pred_model"] - joined["delta_h"]
    err_r = joined["delta_pred_reference"] - joined["delta_h"]
    rmse_m, rmse_r = float(np.sqrt(np.mean(err_m ** 2))), float(np.sqrt(np.mean(err_r ** 2)))
    mae_m, mae_r = float(np.mean(np.abs(err_m))), float(np.mean(np.abs(err_r)))
    well_rows = []
    for site, group in joined.groupby("site_code"):
        em = group["delta_pred_model"] - group["delta_h"]
        er = group["delta_pred_reference"] - group["delta_h"]
        well_rows.append({
            "site_code": site,
            "RMSE_improvement_ft": float(np.sqrt(np.mean(er ** 2)) - np.sqrt(np.mean(em ** 2))),
            "MAE_improvement_ft": float(np.mean(np.abs(er)) - np.mean(np.abs(em))),
        })
    wells = pd.DataFrame(well_rows)
    return {
        "regime": regime,
        "comparison": f"{comparison}_minus_{reference}",
        "comparison_model": comparison,
        "reference_model": reference,
        "positive_means_comparison_has_lower_error": True,
        "n_transitions": len(joined),
        "n_wells": joined["site_code"].nunique(),
        "RMSE_reference_ft": rmse_r,
        "RMSE_comparison_ft": rmse_m,
        "RMSE_improvement_ft": rmse_r - rmse_m,
        "RMSE_skill_fraction": 1.0 - rmse_m / rmse_r,
        "MAE_reference_ft": mae_r,
        "MAE_comparison_ft": mae_m,
        "MAE_improvement_ft": mae_r - mae_m,
        "MAE_skill_fraction": 1.0 - mae_m / mae_r,
        "median_well_RMSE_improvement_ft": float(wells["RMSE_improvement_ft"].median()),
        "well_RMSE_improvement_IQR_ft": float(wells["RMSE_improvement_ft"].quantile(.75) - wells["RMSE_improvement_ft"].quantile(.25)),
        "fraction_wells_RMSE_improved": float((wells["RMSE_improvement_ft"] > 0).mean()),
    }


def _bootstrap_comparison(predictions: pd.DataFrame, comparison: str, reference: str, regime: str, offset: int) -> dict[str, object]:
    model = predictions.loc[(predictions["model"] == comparison) & (predictions["regime"] == regime)]
    ref = predictions.loc[(predictions["model"] == reference) & (predictions["regime"] == regime)]
    joined = model[["transition_id", "site_code", "delta_h", "delta_pred"]].merge(
        ref[["transition_id", "delta_pred"]], on="transition_id",
        suffixes=("_model", "_reference"), validate="one_to_one",
    )
    groups = []
    for _, group in joined.groupby("site_code", sort=True):
        em = group["delta_pred_model"] - group["delta_h"]
        er = group["delta_pred_reference"] - group["delta_h"]
        groups.append((len(group), float(np.abs(em).sum()), float((em ** 2).sum()), float(np.abs(er).sum()), float((er ** 2).sum())))
    arr = np.asarray(groups, float)
    rng = np.random.default_rng(SEED + offset)
    mae_diff = np.empty(BOOTSTRAPS)
    rmse_diff = np.empty(BOOTSTRAPS)
    for index in range(BOOTSTRAPS):
        sampled = arr[rng.integers(0, len(arr), size=len(arr))]
        n = sampled[:, 0].sum()
        mae_diff[index] = sampled[:, 3].sum() / n - sampled[:, 1].sum() / n
        rmse_diff[index] = math.sqrt(sampled[:, 4].sum() / n) - math.sqrt(sampled[:, 2].sum() / n)
    point = _comparison_summary(predictions, comparison, reference, regime)
    point.update({
        "bootstrap_resamples": BOOTSTRAPS,
        "resampling_unit": "well",
        "seed": SEED + offset,
        "MAE_improvement_ci95_low_ft": float(np.percentile(mae_diff, 2.5)),
        "MAE_improvement_ci95_high_ft": float(np.percentile(mae_diff, 97.5)),
        "RMSE_improvement_ci95_low_ft": float(np.percentile(rmse_diff, 2.5)),
        "RMSE_improvement_ci95_high_ft": float(np.percentile(rmse_diff, 97.5)),
    })
    return point


def _parse_transition_dates(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    for column in ["t_prev", "t_target", "target_month"]:
        frame[column] = pd.to_datetime(frame[column])
    return frame


def reproduce_b1_gate(write_output: bool = True) -> dict[str, object]:
    ensure_directories()
    verify_frozen_parents()
    transitions = _parse_transition_dates(pd.read_parquet(GW1A_ROOT / "data/derived/HEAD_TRANSITIONS.parquet"))
    predictions, _, _ = _prediction_set(transitions, PRIMARY_GAP, ["B1"], require_climate=False)
    metrics = aggregate_metrics(predictions, ["regime", "model"])
    expected_metrics = pd.read_csv(GW1A_ROOT / "outputs/tables/PRIMARY_METRICS.csv")
    expected_predictions = pd.read_parquet(GW1A_ROOT / "data/derived/PRIMARY_TEST_PREDICTIONS.parquet")
    comparisons = []
    failures = []
    for regime in ["T1_TEMPORAL_OOS", "T2_SPATIOTEMPORAL_OOS"]:
        actual = metrics.loc[metrics["regime"].eq(regime)].iloc[0]
        expected = expected_metrics.loc[
            expected_metrics["regime"].eq(regime) & expected_metrics["model"].eq("B1")
        ].iloc[0]
        for metric in ["n_transitions", "n_wells", "MAE_delta_h_ft", "RMSE_delta_h_ft", "bias_delta_h_ft", "sign_accuracy_delta_h"]:
            difference = float(actual[metric]) - float(expected[metric])
            comparisons.append({"regime": regime, "metric": metric, "actual": float(actual[metric]), "frozen": float(expected[metric]), "difference": difference})
            if abs(difference) > TOLERANCE:
                failures.append(f"{regime}:{metric}:{difference}")
        actual_pred = predictions.loc[predictions["regime"].eq(regime), ["transition_id", "delta_pred"]]
        frozen_pred = expected_predictions.loc[
            expected_predictions["regime"].eq(regime) & expected_predictions["model"].eq("B1"),
            ["transition_id", "delta_pred"],
        ]
        joined = actual_pred.merge(frozen_pred, on="transition_id", suffixes=("_actual", "_frozen"), validate="one_to_one")
        if len(joined) != len(actual_pred) or len(joined) != len(frozen_pred):
            failures.append(f"{regime}:prediction_population")
            max_abs = math.inf
        else:
            max_abs = float(np.max(np.abs(joined["delta_pred_actual"] - joined["delta_pred_frozen"])))
            if max_abs > TOLERANCE:
                failures.append(f"{regime}:prediction_max_abs:{max_abs}")
        comparisons.append({"regime": regime, "metric": "prediction_max_abs_difference_ft", "actual": max_abs, "frozen": 0.0, "difference": max_abs})
    result = {
        "status": "PASS" if not failures else "FAIL",
        "baseline_commit": BASELINE_COMMIT,
        "tolerance": TOLERANCE,
        "model": "B1",
        "model_features": B1_FEATURES,
        "target": "delta_h",
        "primary_gap_days": PRIMARY_GAP,
        "comparisons": comparisons,
        "failures": failures,
        "must_pass_before_climate_modeling": True,
    }
    if write_output:
        write_json(PROVENANCE / "B1_REPRODUCTION.json", result)
        pd.DataFrame(comparisons).to_csv(TABLES / "B1_REPRODUCTION_COMPARISON.csv", index=False)
    if failures:
        raise RuntimeError("Frozen B1 reproduction failed: " + "; ".join(failures[:10]))
    return result


def _all_coordinates(value: object) -> Iterable[tuple[float, float]]:
    if isinstance(value, list) and len(value) >= 2 and all(isinstance(x, (int, float)) for x in value[:2]):
        yield float(value[0]), float(value[1])
    elif isinstance(value, list):
        for child in value:
            yield from _all_coordinates(child)


def _basin_bbox() -> dict[str, float]:
    geometry = json.loads((FEASIBILITY_ROOT / "data/derived/DWR_BASIN_8_001.geojson").read_text())
    coordinates = []
    for feature in geometry.get("features", []):
        coordinates.extend(_all_coordinates(feature["geometry"]["coordinates"]))
    lon = [x for x, _ in coordinates]
    lat = [y for _, y in coordinates]
    return {"west": min(lon), "east": max(lon), "south": min(lat), "north": max(lat)}


def _download_with_curl(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["curl", "-L", "--fail", "--silent", "--show-error", url, "-o", str(destination)], check=True)


def acquire_gridmet() -> dict[str, object]:
    """Acquire only the fixed 13 x 16 grid and fixed daily period."""
    ensure_directories()
    if reproduce_b1_gate(write_output=True)["status"] != "PASS":  # hard gate
        raise RuntimeError("B1 gate did not pass")
    basin = _basin_bbox()
    buffered = {key: value + (-BASIN_BUFFER_DEGREES if key in {"west", "south"} else BASIN_BUFFER_DEGREES) for key, value in basin.items()}
    raw_rows = []
    decoded_frames: dict[str, list[pd.DataFrame]] = {"pr": [], "pet": []}
    accessed = datetime.now(timezone.utc).isoformat()
    for shorthand, metadata in GRIDMET.items():
        variable = metadata["variable"]
        for suffix in ["dds", "das"]:
            url = f"{GRIDMET_BASE}/{shorthand}/{shorthand}_1991.nc.{suffix}"
            destination = RAW / f"{shorthand}_1991.nc.{suffix}"
            _download_with_curl(url, destination)
            raw_rows.append({
                "source": "official gridMET THREDDS", "variable": variable,
                "year": 1991, "artifact_type": suffix.upper(), "url": url,
                "accessed_at_utc": accessed, "path": destination.relative_to(MODULE_ROOT).as_posix(),
                "bytes": destination.stat().st_size, "sha256": sha256_file(destination),
                "extraction_command": f"curl -L --fail '{url}' -o '{destination.relative_to(MODULE_ROOT).as_posix()}'",
            })
        for year in range(1991, 1999):
            remote = f"{GRIDMET_BASE}/{shorthand}/{shorthand}_{year}.nc"
            with netCDF4.Dataset(remote) as dataset:
                time_var = dataset.variables["day"]
                dates = pd.to_datetime([
                    str(x)[:10] for x in netCDF4.num2date(time_var[:], time_var.units, getattr(time_var, "calendar", "standard"))
                ])
                keep = np.flatnonzero((dates >= GRIDMET_START) & (dates <= GRIDMET_END))
                if not len(keep):
                    continue
                first, last = int(keep[0]), int(keep[-1])
                lat = np.asarray(dataset.variables["lat"][LAT_SLICE[0]:LAT_SLICE[1] + 1], float)
                lon = np.asarray(dataset.variables["lon"][LON_SLICE[0]:LON_SLICE[1] + 1], float)
                values = np.ma.filled(
                    dataset.variables[variable][first:last + 1, LAT_SLICE[0]:LAT_SLICE[1] + 1, LON_SLICE[0]:LON_SLICE[1] + 1],
                    np.nan,
                ).astype(float)
            subset_dates = dates[first:last + 1]
            if values.shape != (len(subset_dates), len(lat), len(lon)):
                raise RuntimeError(f"Unexpected gridMET subset shape for {shorthand} {year}: {values.shape}")
            time_index = np.repeat(np.arange(len(subset_dates)), len(lat) * len(lon))
            lat_local = np.tile(np.repeat(np.arange(len(lat)), len(lon)), len(subset_dates))
            lon_local = np.tile(np.arange(len(lon)), len(subset_dates) * len(lat))
            decoded_frames[shorthand].append(pd.DataFrame({
                "date": subset_dates.to_numpy()[time_index],
                "lat_index": LAT_SLICE[0] + lat_local,
                "lon_index": LON_SLICE[0] + lon_local,
                "latitude": lat[lat_local],
                "longitude": lon[lon_local],
                f"{shorthand}_mm": values.reshape(-1),
            }))
            constraint = (
                f"{variable}[{first}:1:{last}]"
                f"[{LAT_SLICE[0]}:1:{LAT_SLICE[1]}]"
                f"[{LON_SLICE[0]}:1:{LON_SLICE[1]}]"
            )
            url = f"{remote}.dods?{constraint}"
            destination = RAW / f"{shorthand}_{year}_ocwd_subset.dods"
            _download_with_curl(url, destination)
            raw_rows.append({
                "source": "official gridMET THREDDS", "variable": variable,
                "year": year, "artifact_type": "bounded_OPeNDAP_DODS_response",
                "url": url, "accessed_at_utc": accessed,
                "path": destination.relative_to(MODULE_ROOT).as_posix(),
                "bytes": destination.stat().st_size, "sha256": sha256_file(destination),
                "extraction_command": f"curl -L --fail '{url}' -o '{destination.relative_to(MODULE_ROOT).as_posix()}'",
                "date_start": subset_dates.min().strftime("%Y-%m-%d"),
                "date_end": subset_dates.max().strftime("%Y-%m-%d"),
                "lat_index_range": f"{LAT_SLICE[0]}:{LAT_SLICE[1]}",
                "lon_index_range": f"{LON_SLICE[0]}:{LON_SLICE[1]}",
            })
    pr = pd.concat(decoded_frames["pr"], ignore_index=True)
    pet = pd.concat(decoded_frames["pet"], ignore_index=True)
    keys = ["date", "lat_index", "lon_index", "latitude", "longitude"]
    daily = pr.merge(pet, on=keys, validate="one_to_one")
    daily["cell_id"] = daily.apply(lambda r: f"GRIDMET_{int(r.lat_index):04d}_{int(r.lon_index):04d}", axis=1)
    daily["source"] = "official gridMET THREDDS bounded OPeNDAP subset"
    daily["evidence_class"] = "REFERENCE_MODEL"
    daily = daily[["date", "cell_id", "lat_index", "lon_index", "latitude", "longitude", "pr_mm", "pet_mm", "source", "evidence_class"]].sort_values(["date", "cell_id"]).reset_index(drop=True)
    daily.to_parquet(DERIVED / "GRIDMET_OCWD_DAILY.parquet", index=False)
    raw_manifest = pd.DataFrame(raw_rows).sort_values(["variable", "artifact_type", "year", "path"]).reset_index(drop=True)
    raw_manifest.to_csv(PROVENANCE / "GRIDMET_RAW_DOWNLOAD_MANIFEST.csv", index=False)
    write_json(PROVENANCE / "GRIDMET_RAW_DOWNLOAD_MANIFEST.json", raw_manifest.to_dict(orient="records"))
    source = {
        "status": "PASS",
        "authority": "University of Idaho / Northwest Knowledge Network",
        "product": "gridMET",
        "official_catalog": "https://tds-proxy.nkn.uidaho.edu/thredds/reacch_climate_MET_catalog.html",
        "service": "official THREDDS OPeNDAP",
        "accessed_at_utc": accessed,
        "variables": GRIDMET,
        "units": {"pr_mm": "millimetres daily precipitation", "pet_mm": "millimetres daily short-grass reference ET0"},
        "crs": "WGS84 geographic latitude/longitude (EPSG:4326)",
        "grid_resolution_degrees": 1 / 24,
        "temporal_resolution": "daily; source days approximately end at midnight Mountain Standard Time",
        "requested_period": [GRIDMET_START.strftime("%Y-%m-%d"), GRIDMET_END.strftime("%Y-%m-%d")],
        "actual_period": [daily["date"].min().strftime("%Y-%m-%d"), daily["date"].max().strftime("%Y-%m-%d")],
        "basin_bbox_degrees": basin,
        "buffer_degrees": BASIN_BUFFER_DEGREES,
        "requested_buffered_bbox_degrees": buffered,
        "fixed_grid_indices": {"lat_inclusive": list(LAT_SLICE), "lon_inclusive": list(LON_SLICE)},
        "actual_grid_bbox_degrees": {"west": daily.longitude.min(), "east": daily.longitude.max(), "south": daily.latitude.min(), "north": daily.latitude.max()},
        "n_grid_cells": int(daily["cell_id"].nunique()),
        "n_complete_land_grid_cells": int(daily.groupby("cell_id")[["pr_mm", "pet_mm"]].apply(lambda x: x.notna().all().all()).sum()),
        "n_fully_masked_or_incomplete_grid_cells": int((~daily.groupby("cell_id")[["pr_mm", "pet_mm"]].apply(lambda x: x.notna().all().all())).sum()),
        "n_days": int(daily["date"].nunique()),
        "n_rows": len(daily),
        "missing_pr_values": int(daily["pr_mm"].isna().sum()),
        "missing_pet_values": int(daily["pet_mm"].isna().sum()),
        "derived_daily_table": {
            "path": (DERIVED / "GRIDMET_OCWD_DAILY.parquet").relative_to(MODULE_ROOT).as_posix(),
            "bytes": (DERIVED / "GRIDMET_OCWD_DAILY.parquet").stat().st_size,
            "sha256": sha256_file(DERIVED / "GRIDMET_OCWD_DAILY.parquet"),
        },
        "raw_file_count": len(raw_manifest),
        "raw_total_bytes": int(raw_manifest["bytes"].sum()),
        "ncss_note": "Catalog NCSS links returned HTTP 404 at access; official OPeNDAP was used successfully instead.",
    }
    write_json(PROVENANCE / "GRIDMET_SOURCE_AND_SUBSET.json", source)
    return source


def _nearest_grid_crosswalk(daily: pd.DataFrame, transitions: pd.DataFrame) -> pd.DataFrame:
    complete = daily.groupby("cell_id")[["pr_mm", "pet_mm"]].apply(lambda x: x.notna().all().all())
    complete_ids = set(complete.index[complete])
    grid = daily.loc[daily["cell_id"].isin(complete_ids), ["cell_id", "lat_index", "lon_index", "latitude", "longitude"]].drop_duplicates().sort_values("cell_id")
    wells = transitions[["site_code", "latitude_numeric", "longitude_numeric"]].drop_duplicates("site_code").sort_values("site_code")
    grid_xy = grid[["longitude", "latitude"]].to_numpy(float)
    rows = []
    for well in wells.itertuples(index=False):
        # Coordinates only; squared geographic distance is sufficient for a fixed
        # regular grid over this small extent.
        distance2 = (grid_xy[:, 0] - well.longitude_numeric) ** 2 + (grid_xy[:, 1] - well.latitude_numeric) ** 2
        index = int(np.argmin(distance2))
        cell = grid.iloc[index]
        rows.append({
            "site_code": well.site_code,
            "well_latitude": well.latitude_numeric,
            "well_longitude": well.longitude_numeric,
            "cell_id": cell.cell_id,
            "grid_latitude": cell.latitude,
            "grid_longitude": cell.longitude,
            "lat_index": int(cell.lat_index),
            "lon_index": int(cell.lon_index),
            "mapping_inputs": "well_latitude|well_longitude|fixed_grid_coordinates",
            "groundwater_outcomes_used": False,
            "mapping_rule": "nearest temporally complete land grid-cell center by squared lon/lat distance",
        })
    return pd.DataFrame(rows)


def _window_sum(frame: pd.DataFrame, column: str, start: pd.Timestamp, end: pd.Timestamp, expected: int) -> tuple[float, int]:
    if expected <= 0 or start > end:
        return np.nan, 0
    values = frame.loc[(frame.index >= start) & (frame.index <= end), column]
    observed = int(values.notna().sum())
    if len(values) != expected or observed != expected:
        return np.nan, observed
    return float(values.sum()), observed


def build_climate_features() -> pd.DataFrame:
    daily = pd.read_parquet(DERIVED / "GRIDMET_OCWD_DAILY.parquet")
    daily["date"] = pd.to_datetime(daily["date"])
    transitions = _parse_transition_dates(pd.read_parquet(GW1A_ROOT / "data/derived/HEAD_TRANSITIONS.parquet"))
    crosswalk = _nearest_grid_crosswalk(daily, transitions)
    crosswalk.to_csv(DERIVED / "WELL_GRIDMET_CELL_CROSSWALK.csv", index=False)
    lookup = {cell: group.set_index("date").sort_index() for cell, group in daily.groupby("cell_id")}
    cell_by_well = dict(zip(crosswalk["site_code"], crosswalk["cell_id"]))
    rows = []
    for transition in transitions.itertuples(index=False):
        cell_id = cell_by_well[transition.site_code]
        climate = lookup[cell_id]
        origin = pd.Timestamp(transition.t_prev).normalize()
        target = pd.Timestamp(transition.t_target).normalize()
        interval_start, interval_end = origin + pd.Timedelta(days=1), target
        interval_expected = max(0, int((interval_end - interval_start).days) + 1)
        pre30_start, pre30_end = origin - pd.Timedelta(days=30), origin - pd.Timedelta(days=1)
        pre90_start, pre90_end = origin - pd.Timedelta(days=90), origin - pd.Timedelta(days=1)
        p_interval, n_p_interval = _window_sum(climate, "pr_mm", interval_start, interval_end, interval_expected)
        et_interval, n_et_interval = _window_sum(climate, "pet_mm", interval_start, interval_end, interval_expected)
        p30, n_p30 = _window_sum(climate, "pr_mm", pre30_start, pre30_end, 30)
        p90, n_p90 = _window_sum(climate, "pr_mm", pre90_start, pre90_end, 90)
        et30, n_et30 = _window_sum(climate, "pet_mm", pre30_start, pre30_end, 30)
        et90, n_et90 = _window_sum(climate, "pet_mm", pre90_start, pre90_end, 90)
        values = [p_interval, et_interval, p30, p90, et30, et90]
        rows.append({
            "transition_id": transition.transition_id,
            "site_code": transition.site_code,
            "cell_id": cell_id,
            "origin_date": origin,
            "target_date": target,
            "interval_start_date": interval_start,
            "interval_end_date": interval_end,
            "interval_expected_days": interval_expected,
            "interval_observed_pr_days": n_p_interval,
            "interval_observed_et0_days": n_et_interval,
            "pre30_start_date": pre30_start,
            "pre30_end_date": pre30_end,
            "pre30_observed_pr_days": n_p30,
            "pre30_observed_et0_days": n_et30,
            "pre90_start_date": pre90_start,
            "pre90_end_date": pre90_end,
            "pre90_observed_pr_days": n_p90,
            "pre90_observed_et0_days": n_et90,
            "P_interval_mm": p_interval,
            "ET0_interval_mm": et_interval,
            "P_pre30_mm": p30,
            "P_pre90_mm": p90,
            "ET0_pre30_mm": et30,
            "ET0_pre90_mm": et90,
            "climate_feature_complete": bool(np.isfinite(values).all()),
            "feature_date_rule": "interval=(origin_date,target_date]; pre30/pre90 use complete dates before origin",
            "groundwater_outcomes_used_for_cell_mapping": False,
        })
    features = pd.DataFrame(rows)
    features.to_parquet(DERIVED / "GW1C_CLIMATE_FEATURES.parquet", index=False)
    merged = transitions.merge(features.drop(columns="site_code"), on="transition_id", validate="one_to_one")
    merged.to_parquet(DERIVED / "GW1C_TRANSITIONS.parquet", index=False)
    summary = {
        "status": "PASS",
        "fixed_features": CLIMATE_FEATURES,
        "n_transitions": len(features),
        "n_wells": features["site_code"].nunique(),
        "n_complete": int(features["climate_feature_complete"].sum()),
        "n_incomplete": int((~features["climate_feature_complete"]).sum()),
        "n_grid_cells_used": crosswalk["cell_id"].nunique(),
        "n_complete_candidate_grid_cells": int(daily.groupby("cell_id")[["pr_mm", "pet_mm"]].apply(lambda x: x.notna().all().all()).sum()),
        "mapping_uses_coordinates_only": True,
        "head_interpolation": False,
        "alternative_lag_search": False,
        "interval_rule": "daily sum over calendar dates (date(t0), date(t1)]",
        "preorigin_rule": "daily sum over 30 and 90 complete calendar dates strictly before date(t0)",
        "evidence_role": "natural climate/background controls; not managed recharge",
    }
    write_json(PROTOCOL / "CLIMATE_FEATURE_FREEZE.json", summary)
    return merged


def _classify(rows: pd.DataFrame) -> str:
    strong = (
        (rows["RMSE_improvement_ft"] > 0).all()
        and (rows["MAE_improvement_ft"] > 0).all()
        and (rows["RMSE_improvement_ci95_low_ft"] > 0).all()
        and (rows["MAE_improvement_ci95_low_ft"] > 0).all()
        and (rows["median_well_RMSE_improvement_ft"] > 0).all()
        and (rows["fraction_wells_RMSE_improved"] > .5).all()
    )
    if strong:
        return "STRONG"
    positive = (rows["RMSE_improvement_ft"] > 0).all() and (rows["MAE_improvement_ft"] > 0).all()
    return "PARTIAL" if positive else "NONE"


def _save_figure(fig: plt.Figure, stem: str) -> None:
    fig.savefig(FIGURES / f"{stem}.png", dpi=220, bbox_inches="tight")
    fig.savefig(
        FIGURES / f"{stem}.pdf", bbox_inches="tight",
        metadata={"Creator": "OCWD GW-1C deterministic pipeline", "CreationDate": None, "ModDate": None},
    )
    plt.close(fig)


def _plot_results(metrics: pd.DataFrame, comparisons: pd.DataFrame, predictions: pd.DataFrame) -> None:
    models = ["B1", "B1C", "B1CH"]
    regimes = ["T1_TEMPORAL_OOS", "T2_SPATIOTEMPORAL_OOS"]
    labels = {"T1_TEMPORAL_OOS": "T1 temporal OOS", "T2_SPATIOTEMPORAL_OOS": "T2 spatiotemporal OOS"}
    colors = {"B1": "#6B7280", "B1C": "#2F6B9A", "B1CH": "#D97706"}
    fig, axes = plt.subplots(1, 2, figsize=(10.6, 4.6))
    x = np.arange(2)
    width = .23
    for index, model in enumerate(models):
        sub = metrics.loc[metrics["model"].eq(model)].set_index("regime").loc[regimes]
        axes[0].bar(x + (index - 1) * width, sub["RMSE_delta_h_ft"], width, color=colors[model], label=model)
        axes[1].bar(x + (index - 1) * width, sub["MAE_delta_h_ft"], width, color=colors[model], label=model)
    for axis, metric in zip(axes, ["RMSE", "MAE"]):
        axis.set_xticks(x, [labels[r] for r in regimes])
        axis.set_ylabel(f"{metric} of held-out $\\Delta h$ (ft)")
        axis.set_title(metric)
        axis.grid(axis="y", alpha=.22)
    axes[0].legend(frameon=False, ncol=3)
    fig.suptitle("GW-1C no-pumping background models (TEST only; transitions ≤120 days)")
    fig.text(.01, .01, "B1: season/trend; B1C: + fixed gridMET precipitation/ET0; B1CH: + frozen Prado features. Conditional head and Δh residuals coincide.", fontsize=8.2)
    fig.tight_layout(rect=[0, .06, 1, .94])
    _save_figure(fig, "fig01_gw1c_oos_skill")

    climate = predictions.loc[predictions["model"].isin(["B1", "B1C"])]
    rows = []
    for regime in regimes:
        a = climate.loc[(climate["regime"] == regime) & (climate["model"] == "B1C")]
        b = climate.loc[(climate["regime"] == regime) & (climate["model"] == "B1")]
        joined = a[["transition_id", "site_code", "delta_h", "delta_pred"]].merge(
            b[["transition_id", "delta_pred"]], on="transition_id", suffixes=("_B1C", "_B1"), validate="one_to_one",
        )
        for site, group in joined.groupby("site_code"):
            ec = group["delta_pred_B1C"] - group["delta_h"]
            eb = group["delta_pred_B1"] - group["delta_h"]
            rows.append({"regime": regime, "site_code": site, "RMSE_improvement_ft": np.sqrt(np.mean(eb ** 2)) - np.sqrt(np.mean(ec ** 2))})
    per_well = pd.DataFrame(rows)
    per_well.to_csv(TABLES / "PER_WELL_CLIMATE_INCREMENTAL_SKILL.csv", index=False)
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.6), sharey=True)
    for axis, regime in zip(axes, regimes):
        values = per_well.loc[per_well["regime"].eq(regime), "RMSE_improvement_ft"]
        axis.hist(values, bins=25, color="#2F6B9A", alpha=.85, edgecolor="white")
        axis.axvline(0, color="black", linewidth=1)
        axis.axvline(values.median(), color="#8B1E3F", linewidth=1.5, linestyle="--", label=f"median {values.median():.2f} ft")
        axis.set_title(labels[regime])
        axis.set_xlabel("Per-well RMSE improvement: B1C vs B1 (ft)")
        axis.grid(axis="y", alpha=.2)
        axis.legend(frameon=False, fontsize=8)
    axes[0].set_ylabel("Wells")
    fig.suptitle("Held-out well-level climate incremental skill")
    fig.text(.01, .01, "Positive values mean the fixed climate controls reduce TEST RMSE. Wells, not transitions, are the uncertainty unit.", fontsize=8.2)
    fig.tight_layout(rect=[0, .06, 1, .94])
    _save_figure(fig, "fig02_per_well_climate_incremental_skill")


def _markdown(frame: pd.DataFrame) -> str:
    def render(value: object) -> str:
        if pd.isna(value):
            return ""
        if isinstance(value, (float, np.floating)):
            return f"{float(value):.4f}"
        return str(value).replace("|", "\\|").replace("\n", " ")
    headers = [render(x) for x in frame.columns]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    lines.extend("| " + " | ".join(render(x) for x in row) + " |" for row in frame.itertuples(index=False, name=None))
    return "\n".join(lines)


def _write_final_report(status: dict[str, object], metrics: pd.DataFrame, comparisons: pd.DataFrame, sensitivity: pd.DataFrame, cadence: pd.DataFrame) -> None:
    display_metrics = metrics[["regime", "model", "n_transitions", "n_wells", "RMSE_delta_h_ft", "MAE_delta_h_ft", "bias_delta_h_ft", "sign_accuracy_delta_h", "RMSE_skill_vs_B1", "MAE_skill_vs_B1", "median_well_RMSE_ft", "well_RMSE_IQR_ft"]]
    display_comparisons = comparisons[["regime", "comparison", "RMSE_improvement_ft", "RMSE_improvement_ci95_low_ft", "RMSE_improvement_ci95_high_ft", "MAE_improvement_ft", "MAE_improvement_ci95_low_ft", "MAE_improvement_ci95_high_ft", "median_well_RMSE_improvement_ft", "well_RMSE_improvement_IQR_ft", "fraction_wells_RMSE_improved"]]
    report = f"""# Final OCWD GW-1C report

## A. Repository and frozen dependencies

- Repository: `{REPO_ROOT}`
- Branch / HEAD: `{status['repository']['branch']}` / `{status['repository']['HEAD']}`
- Scientific baseline: `{BASELINE_COMMIT}`; both frozen parent modules verified byte-for-byte against their committed blobs and committed hash manifests.
- Task-start dirty state: ` m Data-center-PUE-prediction-tool` only. No pre-existing path or frozen parent was modified.
- Python: `{status['repository']['python_executable']}` ({status['repository']['python_version']}).
- Submodule status could not be enumerated because Git reports no `.gitmodules` mapping for the existing PUE path; that path was not touched.

The dependency manifest in `outputs/provenance/GW1C_DEPENDENCY_MANIFEST.csv` pins every material input. Frozen B1 reproduction passed at tolerance {TOLERANCE:g}; maximum prediction difference was {status['B1_reproduction']['maximum_prediction_difference_ft']:.3g} ft.

## B. Climate source and fixed features

The climate source is the official University of Idaho / Northwest Knowledge Network **gridMET** THREDDS OPeNDAP service. Only a {status['climate']['n_grid_cells']}-cell (13 × 16) WGS84 subset covering Basin 8-001 plus a fixed 0.1° buffer was acquired for {status['climate']['date_start']} through {status['climate']['date_end']}. It contains daily precipitation and short-grass reference ET0 in millimetres. The rectangular source subset preserves {status['climate']['missing_values']} masked values in ocean/non-land cells; all selected well cells have complete required coverage. Raw bounded DODS responses and metadata are retained and SHA-256 hashed.

Each frozen well was mapped once to the nearest temporally complete land grid cell using only data availability and coordinates. For transition `(t0,t1)`, the six frozen features are daily sums: `P_interval_mm` and `ET0_interval_mm` over calendar dates `(date(t0), date(t1)]`; and precipitation/ET0 over exactly 30 and 90 complete days strictly before `date(t0)`. No alternative lag, climate variable, well outcome, or target interpolation entered feature construction.

## C. Models and OOS results

- **B1:** frozen season/trend response baseline.
- **B1C:** B1 plus the six fixed gridMET features.
- **B1CH:** B1C plus the two unchanged GW-1A Prado features.

All models predict `delta_h` with pooled OLS after TRAIN-only centering/scaling. Validation and TEST were not used for fitting, scaling, or selection. Results below are TEST only, in feet, on common support. Since `h_hat = h_prev + delta_hat`, head-level and delta-head residuals are algebraically identical and are not presented as independent findings.

{_markdown(display_metrics)}

## D. Pre-registered incremental comparisons and well bootstrap

Positive improvement means the more complex model has lower error. Intervals are 95% well-level bootstrap intervals (1,000 resamples; fixed seed family based on {SEED}).

{_markdown(display_comparisons)}

- `CLIMATE_INCREMENTAL_SKILL = {status['CLIMATE_INCREMENTAL_SKILL']}`
- `PRADO_AFTER_CLIMATE_SKILL = {status['PRADO_AFTER_CLIMATE_SKILL']}`
- Frozen GW-1B background model: **{status['GW1B_BACKGROUND_MODEL']}**.

These classifications concern held-out predictive information, not causal hydrologic coefficients. Climate remains mandatory background/confounding control in GW-1B regardless of its standalone increment. Prado is retained in the primary background model only when its post-climate support is positive under the frozen rule; otherwise it remains a sensitivity control.

## E. Cadence and gap-threshold robustness

The primary protocol remains ≤120 days. Cadence-group metrics subset the primary fits without refitting; ≤90 and ≤180 sensitivity results refit on their corresponding frozen gap thresholds.

{_markdown(cadence[["regime", "cadence_group", "model", "n_transitions", "n_wells", "RMSE_delta_h_ft", "MAE_delta_h_ft", "RMSE_skill_vs_B1", "MAE_skill_vs_B1"]])}

{_markdown(sensitivity[["regime", "gap_threshold_days", "model", "n_transitions", "n_wells", "RMSE_delta_h_ft", "MAE_delta_h_ft", "RMSE_skill_vs_B1", "MAE_skill_vs_B1"]])}

## F. GW-1B readiness and identification boundary

The single permitted local filename scan found no OCWD WRMS delivery. Therefore `GW1B_DATA_STATUS = WAITING_FOR_WRMS`; B4–B7, pumping and recharge features, placebos, spatial kernels, and groundwater coupling were not fitted. The dated protocol amendment was frozen from GW-1A/GW-1C findings before any WRMS response analysis.

What this pass identifies is how well frozen heads can be predicted from the observed origin state, season/trend, fixed natural climate, and (when supported) public Prado background hydrology. Managed-recharge value, pumping predictive value, spatial forcing value, and network added value remain **UNIDENTIFIED WITHOUT WRMS**.

Tracer and MBI records remain reserved outside training, feature selection, scale selection, and model selection. No external physical validation is run before a future B7 is frozen.

The frozen GW-1A primary window contains zero eligible independent-agency transitions, so an independent-source T3 climate comparison remains `NOT_FEASIBLE_IN_FROZEN_WINDOW`; it was not forced by mixing provenance or extrapolating dates.

## G. Exact next action

When the OCWD WRMS delivery arrives, preserve it byte-for-byte, hash it, audit schemas/units/QA/evidence classes and exact well/facility identities, and re-evaluate pumping, recharge, vertical-identity, and common-support gates. Only after those gates pass should the frozen amendment be executed: B4 managed recharge/injection, B5 basin pumping, B6 spatial forcing plus its placebos, and B7 only if its network gate is earned. The static-versus-dynamic planning comparison remains downstream and must not begin in this pass.
"""
    (OUTPUTS / "FINAL_GW1C_REPORT.md").write_text(report, encoding="utf-8")


def _write_hash_manifest() -> pd.DataFrame:
    excluded = {
        "outputs/provenance/GW1C_OUTPUT_HASHES.csv",
        "outputs/provenance/GW1C_OUTPUT_HASHES.json",
        "outputs/provenance/DETERMINISTIC_REPLAY_STATUS.json",
    }
    rows = []
    for path in sorted(p for p in MODULE_ROOT.rglob("*") if p.is_file()):
        rel = path.relative_to(MODULE_ROOT).as_posix()
        if rel in excluded or "__pycache__" in rel:
            continue
        rows.append({"path": rel, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    frame = pd.DataFrame(rows)
    frame.to_csv(PROVENANCE / "GW1C_OUTPUT_HASHES.csv", index=False)
    write_json(PROVENANCE / "GW1C_OUTPUT_HASHES.json", frame.to_dict(orient="records"))
    return frame


def _verify_parent_end(start: dict[str, object]) -> dict[str, object]:
    end = verify_frozen_parents()
    for label in ["feasibility", "gw1a"]:
        if start["parents"][label]["current_tree_sha256"] != end["parents"][label]["current_tree_sha256"]:
            raise RuntimeError(f"Frozen parent tree changed during GW-1C: {label}")
    end["matches_start_snapshot"] = True
    write_json(PROVENANCE / "FROZEN_PARENT_INTEGRITY_END.json", end)
    return end


def run_gw1c() -> dict[str, object]:
    ensure_directories()
    parent_start = verify_frozen_parents(write_start=True)
    create_dependency_manifest()
    record_preflight(parent_start)
    reproduction = reproduce_b1_gate(write_output=True)
    climate_source_path = PROVENANCE / "GRIDMET_SOURCE_AND_SUBSET.json"
    daily_path = DERIVED / "GRIDMET_OCWD_DAILY.parquet"
    if not climate_source_path.exists() or not daily_path.exists():
        raise RuntimeError("Official gridMET subset is absent; run scripts/acquire_gridmet.py with network access")
    climate_source = json.loads(climate_source_path.read_text())
    raw_manifest = pd.read_csv(PROVENANCE / "GRIDMET_RAW_DOWNLOAD_MANIFEST.csv")
    for row in raw_manifest.itertuples(index=False):
        path = MODULE_ROOT / row.path
        if not path.exists() or path.stat().st_size != int(row.bytes) or sha256_file(path) != row.sha256:
            raise RuntimeError(f"Raw gridMET hash mismatch: {row.path}")
    transitions = build_climate_features()
    primary_predictions, fit_audit, fit_samples = _prediction_set(
        transitions, PRIMARY_GAP, ["B1", "B1C", "B1CH"], require_climate=True,
    )
    primary_metrics = add_b1_skill(aggregate_metrics(primary_predictions, ["regime", "model"]), ["regime"])
    well_metrics = _well_metrics(primary_predictions)
    well_distribution = well_metrics.groupby(["regime", "model"], as_index=False).agg(
        median_well_RMSE_ft=("RMSE_delta_h_ft", "median"),
        well_RMSE_q25_ft=("RMSE_delta_h_ft", lambda x: x.quantile(.25)),
        well_RMSE_q75_ft=("RMSE_delta_h_ft", lambda x: x.quantile(.75)),
        median_well_MAE_ft=("MAE_delta_h_ft", "median"),
        well_MAE_q25_ft=("MAE_delta_h_ft", lambda x: x.quantile(.25)),
        well_MAE_q75_ft=("MAE_delta_h_ft", lambda x: x.quantile(.75)),
    )
    well_distribution["well_RMSE_IQR_ft"] = well_distribution["well_RMSE_q75_ft"] - well_distribution["well_RMSE_q25_ft"]
    well_distribution["well_MAE_IQR_ft"] = well_distribution["well_MAE_q75_ft"] - well_distribution["well_MAE_q25_ft"]
    primary_metrics = primary_metrics.merge(
        well_distribution[["regime", "model", "median_well_RMSE_ft", "well_RMSE_IQR_ft", "median_well_MAE_ft", "well_MAE_IQR_ft"]],
        on=["regime", "model"], how="left", validate="one_to_one",
    )
    comparisons = []
    for offset, (comparison, reference) in enumerate([("B1C", "B1"), ("B1CH", "B1C")]):
        for regime_offset, regime in enumerate(["T1_TEMPORAL_OOS", "T2_SPATIOTEMPORAL_OOS"]):
            comparisons.append(_bootstrap_comparison(primary_predictions, comparison, reference, regime, offset * 10 + regime_offset))
    comparisons_frame = pd.DataFrame(comparisons)
    climate_claim = _classify(comparisons_frame.loc[comparisons_frame["comparison"].eq("B1C_minus_B1")])
    prado_claim = _classify(comparisons_frame.loc[comparisons_frame["comparison"].eq("B1CH_minus_B1C")])
    prado_rows = comparisons_frame.loc[comparisons_frame["comparison"].eq("B1CH_minus_B1C")]
    prado_positive = bool(
        (prado_rows["RMSE_improvement_ft"] > 0).all()
        and (prado_rows["MAE_improvement_ft"] > 0).all()
        and prado_claim != "NONE"
    )
    background = "B1CH" if prado_positive else "B1C"

    sensitivity_predictions = []
    for threshold in SENSITIVITY_GAPS:
        p, _, _ = _prediction_set(transitions, threshold, ["B1", "B1C", "B1CH"], require_climate=True)
        sensitivity_predictions.append(p)
    sensitivity_all = pd.concat(sensitivity_predictions, ignore_index=True)
    sensitivity_metrics = add_b1_skill(
        aggregate_metrics(sensitivity_all, ["regime", "gap_threshold_days", "model"]),
        ["regime", "gap_threshold_days"],
    )
    cadence_rows = []
    for (regime, gap, model), group in primary_predictions.groupby(["regime", "gap_group_primary", "model"], sort=True):
        row = {"regime": regime, "cadence_group": gap, "model": model}
        row.update(_metric(group))
        cadence_rows.append(row)
    cadence_metrics = add_b1_skill(pd.DataFrame(cadence_rows), ["regime", "cadence_group"])

    primary_predictions.to_parquet(DERIVED / "GW1C_PRIMARY_TEST_PREDICTIONS.parquet", index=False)
    fit_samples.to_parquet(DERIVED / "GW1C_FIT_SAMPLE_LEDGER.parquet", index=False)
    fit_audit.to_csv(TABLES / "GW1C_FITTED_MODEL_AUDIT.csv", index=False)
    primary_metrics.to_csv(METRICS / "GW1C_PRIMARY_METRICS.csv", index=False)
    comparisons_frame.to_csv(METRICS / "GW1C_INCREMENTAL_COMPARISONS_BOOTSTRAP.csv", index=False)
    well_metrics.to_csv(METRICS / "GW1C_WELL_LEVEL_METRICS.csv", index=False)
    well_distribution.to_csv(METRICS / "GW1C_WELL_DISTRIBUTION_SUMMARY.csv", index=False)
    sensitivity_metrics.to_csv(METRICS / "GW1C_SENSITIVITY_METRICS.csv", index=False)
    cadence_metrics.to_csv(METRICS / "GW1C_CADENCE_METRICS.csv", index=False)
    _plot_results(primary_metrics, comparisons_frame, primary_predictions)

    preflight = json.loads((PROVENANCE / "REPOSITORY_PREFLIGHT.json").read_text())
    feature_freeze = json.loads((PROTOCOL / "CLIMATE_FEATURE_FREEZE.json").read_text())
    b1_max = max(float(row["difference"]) for row in reproduction["comparisons"] if row["metric"] == "prediction_max_abs_difference_ft")
    status = {
        "GW1C_STATUS": "PASS",
        "CLIMATE_INCREMENTAL_SKILL": climate_claim,
        "PRADO_AFTER_CLIMATE_SKILL": prado_claim,
        "GW1B_BACKGROUND_MODEL": background,
        "GW1B_BACKGROUND_DEFINITION": "B1 + fixed gridMET climate + frozen Prado features" if background == "B1CH" else "B1 + fixed gridMET climate; Prado retained only as sensitivity control",
        "GW1B_DATA_STATUS": "WAITING_FOR_WRMS",
        "repository": {
            "repo_root": str(REPO_ROOT), "branch": preflight["branch"], "HEAD": preflight["HEAD"],
            "python_executable": preflight["python_executable"], "python_version": platform.python_version(),
        },
        "frozen_dependencies": {"status": "PASS", "baseline_commit": BASELINE_COMMIT, "material_dependencies": len(MATERIAL_DEPENDENCIES)},
        "B1_reproduction": {"status": reproduction["status"], "tolerance": TOLERANCE, "maximum_prediction_difference_ft": b1_max},
        "protocol": {
            "primary_window": ["1991-10", "1998-11"],
            "temporal_split": {"TRAIN": ["1991-10", "1996-09"], "VALIDATION": ["1996-10", "1997-10"], "TEST": ["1997-11", "1998-11"]},
            "spatial_folds": "exact frozen GW1A SPATIAL_FOLDS.csv",
            "primary_gap_days": PRIMARY_GAP,
            "sensitivity_gap_days": SENSITIVITY_GAPS,
            "target": "delta_h",
            "head_interpolation": False,
        },
        "climate": {
            "source": "official University of Idaho / Northwest Knowledge Network gridMET THREDDS OPeNDAP",
            "date_start": climate_source["actual_period"][0], "date_end": climate_source["actual_period"][1],
            "n_days": climate_source["n_days"], "n_grid_cells": climate_source["n_grid_cells"],
            "n_grid_cells_used": feature_freeze["n_grid_cells_used"],
            "missing_values": climate_source["missing_pr_values"] + climate_source["missing_pet_values"],
            "features": CLIMATE_FEATURES,
            "mapping_uses_coordinates_only": True,
        },
        "samples": {
            "all_transitions": len(transitions),
            "climate_complete_transitions": int(transitions["climate_feature_complete"].sum()),
            "primary_eligible_transitions_all_splits": len(_eligible(transitions, PRIMARY_GAP, True)),
            "T1_test_transitions": int(primary_metrics.loc[primary_metrics["regime"].eq("T1_TEMPORAL_OOS"), "n_transitions"].iloc[0]),
            "T2_test_transitions": int(primary_metrics.loc[primary_metrics["regime"].eq("T2_SPATIOTEMPORAL_OOS"), "n_transitions"].iloc[0]),
        },
        "claims_rule": {
            "STRONG": "positive RMSE/MAE improvements with well-bootstrap 95% lower bounds above zero, positive median well improvement, and >50% wells improved in both T1/T2",
            "PARTIAL": "positive RMSE and MAE aggregate improvement in both T1/T2 with mixed uncertainty or well support",
            "NONE": "no consistent positive aggregate RMSE and MAE support across T1/T2",
        },
        "identification": {
            "natural_climate_predictive_value": climate_claim,
            "Prado_after_climate_predictive_value": prado_claim,
            "managed_recharge_value": "UNIDENTIFIED_WRMS_ABSENT",
            "pumping_predictive_value": "UNIDENTIFIED_WRMS_ABSENT",
            "spatial_forcing_value": "UNIDENTIFIED_WRMS_ABSENT",
            "network_added_value": "UNIDENTIFIED_NO_NETWORK_FIT",
            "causal_effects": "NOT_IDENTIFIED_BY_PREDICTIVE_BENCHMARK",
        },
        "reserved_external_validation": {
            "tracer": "RESERVED_NOT_USED",
            "MBI_1_2015": "RESERVED_NOT_USED",
            "MBI_2_TO_5_2020": "RESERVED_NOT_USED",
        },
        "independent_agency_check": "NOT_FEASIBLE_IN_FROZEN_WINDOW_ZERO_ELIGIBLE_TRANSITIONS",
        "modeling_not_run": ["WRMS audit", "B4", "B5", "B6", "placebos", "network gate", "B7", "tracer validation", "MBI validation", "MODFLOW calibration", "GNN", "data-center optimization"],
    }
    write_json(OUTPUTS / "FINAL_GW1C_STATUS.json", status)
    _write_final_report(status, primary_metrics, comparisons_frame, sensitivity_metrics, cadence_metrics)
    _verify_parent_end(parent_start)
    _write_hash_manifest()
    return status
