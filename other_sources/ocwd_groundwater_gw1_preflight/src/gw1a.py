"""Deterministic protocol and benchmark implementation for OCWD GW-1A.

The code intentionally contains only pooled linear no-pumping baselines. It
does not interpolate heads or estimate spatial/network coefficients.
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
import numpy as np
import pandas as pd
import yaml
from sklearn.cluster import KMeans


MODULE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MODULE_ROOT.parents[1]
FEASIBILITY_ROOT = REPO_ROOT / "other_sources" / "ocwd_groundwater_feasibility"
FROZEN_COMMIT = "f5d2cedb3c5ba8f75aabe06801a42d274eafe692"

CONFIG = MODULE_ROOT / "config"
DATA_DERIVED = MODULE_ROOT / "data" / "derived"
OUTPUTS = MODULE_ROOT / "outputs"
COHORTS = OUTPUTS / "cohorts"
PROTOCOL = OUTPUTS / "protocol"
TABLES = OUTPUTS / "tables"
FIGURES = OUTPUTS / "figures"
PROVENANCE = OUTPUTS / "provenance"

SEED = 20260904
SEARCH_START = pd.Timestamp("1990-11-01")
SEARCH_END = pd.Timestamp("1999-11-30 23:59:59.999999")
EXPECTED_PRIMARY_START = pd.Timestamp("1991-10-01")
EXPECTED_PRIMARY_END_MONTH = pd.Timestamp("1998-11-01")
EXPECTED_PRIMARY_MONTHS = 86

OCWD_ORIGIN = "OCWD_ORIGIN_REPUBLISHED_BY_DWR"
INDEPENDENT_ORIGIN = "INDEPENDENT_AGENCY_OBSERVATION"


DEPENDENCIES = [
    ("well_master", "data/derived/DWR_OCWD_WELL_MASTER.parquet", "cohort, coordinates, folds"),
    ("head_observations", "data/derived/DWR_OCWD_HEAD_OBSERVATIONS.parquet", "cohort, panel, transitions, outcomes"),
    ("perforations", "data/derived/DWR_OCWD_PERFORATIONS.parquet", "provenance only; prohibited from fold/model inputs"),
    ("observation_independence", "outputs/tables/OBSERVATION_INDEPENDENCE_LEDGER.csv", "development/independent population separation"),
    ("basin_8_001_geometry", "data/derived/DWR_BASIN_8_001.geojson", "figure boundary only"),
    ("official_bulletin_118_geometry", "data/raw/dwr/bulletin118_groundwater_basins.geojson", "official geometry provenance"),
    ("usgs_11074000_daily_derived", "data/derived/USGS_11074000_SANTA_ANA_RIVER_DAILY.parquet", "B3 public background hydrology"),
    ("usgs_11074000_daily_raw", "data/raw/usgs/USGS_11074000_discharge_daily.rdb", "B3 source provenance"),
    ("event_registry", "outputs/tables/EVENT_REGISTRY.csv", "reserved external validation registry only"),
    ("tracer_registry", "outputs/tables/TRACER_VALIDATION_REGISTRY.csv", "reserved external validation registry only"),
    ("source_registry_csv", "sources/source_registry.csv", "source provenance"),
    ("source_registry_yaml", "sources/source_registry.yaml", "source provenance"),
    ("feasibility_package_hashes", "outputs/provenance/PACKAGE_FILE_HASHES.csv", "frozen package integrity"),
    ("raw_download_hashes_csv", "outputs/provenance/RAW_DOWNLOAD_HASH_MANIFEST.csv", "raw provenance"),
    ("raw_download_hashes_json", "outputs/provenance/RAW_DOWNLOAD_HASH_MANIFEST.json", "raw provenance"),
    ("feasibility_output_hashes", "outputs/provenance/OUTPUT_HASHES.csv", "output provenance"),
    ("basin_geometry_provenance", "outputs/provenance/BASIN_GEOMETRY_PROVENANCE.json", "CRS and boundary provenance"),
    ("usgs_coverage", "outputs/tables/USGS_11074000_COVERAGE.json", "forcing coverage provenance"),
    ("final_feasibility_status", "outputs/feasibility/FINAL_FEASIBILITY_STATUS.json", "feasibility status provenance"),
]


MODEL_FEATURES = {
    "B1": ["delta_days", "season_sin", "season_cos", "time_trend_years"],
    "B2": ["h_prev", "delta_days", "season_sin", "season_cos", "time_trend_years"],
    "B3": [
        "h_prev",
        "delta_days",
        "season_sin",
        "season_cos",
        "time_trend_years",
        "log1p_interval_mean_discharge_cfs",
        "log1p_antecedent_30d_mean_discharge_cfs",
    ],
}


def ensure_directories() -> None:
    for path in [CONFIG, DATA_DERIVED, COHORTS, PROTOCOL, TABLES, FIGURES, PROVENANCE, MODULE_ROOT / "tests", MODULE_ROOT / "scripts"]:
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


def frozen_blob(relative_to_repo: str) -> tuple[bool, str, bytes | None]:
    spec = f"{FROZEN_COMMIT}:{relative_to_repo}"
    check = subprocess.run(
        ["git", "cat-file", "-e", spec], cwd=REPO_ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if check.returncode != 0:
        return False, "", None
    blob_sha = run_git(["rev-parse", spec]).stdout.strip()
    raw = subprocess.run(
        ["git", "show", spec], cwd=REPO_ROOT, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout
    return True, blob_sha, raw


def deterministic_tree_snapshot(root: Path) -> tuple[str, list[dict[str, object]]]:
    records: list[dict[str, object]] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix()
        records.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    digest = hashlib.sha256()
    for row in records:
        digest.update(str(row["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(row["sha256"]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest(), records


def verify_frozen_feasibility() -> dict[str, object]:
    """Verify both the committed package and hash-pinned ignored artifacts."""
    manifest_rel = "other_sources/ocwd_groundwater_feasibility/outputs/provenance/PACKAGE_FILE_HASHES.csv"
    tracked, manifest_blob, manifest_bytes = frozen_blob(manifest_rel)
    if not tracked or manifest_bytes is None:
        raise RuntimeError("Frozen commit does not contain PACKAGE_FILE_HASHES.csv")
    manifest_path = FEASIBILITY_ROOT / "outputs/provenance/PACKAGE_FILE_HASHES.csv"
    if sha256_file(manifest_path) != sha256_bytes(manifest_bytes):
        raise RuntimeError("Current feasibility hash manifest differs from frozen Git blob")
    expected = pd.read_csv(io.BytesIO(manifest_bytes))
    failures: list[str] = []
    for row in expected.itertuples(index=False):
        path = FEASIBILITY_ROOT / str(row.path)
        if not path.exists():
            failures.append(f"missing:{row.path}")
        elif path.stat().st_size != int(row.bytes) or sha256_file(path) != str(row.sha256):
            failures.append(f"hash_or_size:{row.path}")

    tracked_files = run_git(["ls-tree", "-r", "--name-only", FROZEN_COMMIT, "--", "other_sources/ocwd_groundwater_feasibility"]).stdout.splitlines()
    for relative in tracked_files:
        path = REPO_ROOT / relative
        is_tracked, _, raw = frozen_blob(relative)
        if not is_tracked or raw is None or not path.exists() or sha256_file(path) != sha256_bytes(raw):
            failures.append(f"tracked_blob:{relative}")
    if failures:
        raise RuntimeError("Frozen feasibility integrity failure: " + "; ".join(failures[:20]))

    tree_sha, tree_records = deterministic_tree_snapshot(FEASIBILITY_ROOT)
    return {
        "status": "PASS",
        "frozen_commit": FROZEN_COMMIT,
        "package_manifest_git_blob": manifest_blob,
        "package_manifest_sha256": sha256_bytes(manifest_bytes),
        "manifest_entries_verified": int(len(expected)),
        "tracked_files_verified": int(len(tracked_files)),
        "current_total_files": int(len(tree_records)),
        "current_tree_sha256": tree_sha,
        "files": tree_records,
        "note": "Gitignored raw/derived artifacts are pinned by the committed PACKAGE_FILE_HASHES.csv; tracked files are additionally matched to frozen Git blobs.",
    }


def create_dependency_manifest() -> pd.DataFrame:
    manifest_rel = "other_sources/ocwd_groundwater_feasibility/outputs/provenance/PACKAGE_FILE_HASHES.csv"
    _, _, manifest_bytes = frozen_blob(manifest_rel)
    if manifest_bytes is None:
        raise RuntimeError("Cannot read committed package manifest")
    expected_df = pd.read_csv(io.BytesIO(manifest_bytes))
    expected_map = dict(zip(expected_df["path"], expected_df["sha256"]))
    rows: list[dict[str, object]] = []
    for logical, rel, used_by in DEPENDENCIES:
        repo_rel = f"other_sources/ocwd_groundwater_feasibility/{rel}"
        path = FEASIBILITY_ROOT / rel
        tracked, blob_sha, blob_bytes = frozen_blob(repo_rel)
        current_sha = sha256_file(path) if path.exists() else ""
        frozen_sha = sha256_bytes(blob_bytes) if blob_bytes is not None else ""
        recorded_sha = expected_map.get(rel, "")
        expected_sha = frozen_sha if tracked else recorded_sha
        matches = bool(path.exists() and expected_sha and current_sha == expected_sha)
        if not matches:
            raise RuntimeError(f"Material dependency does not match frozen baseline: {rel}")
        rows.append({
            "logical_input": logical,
            "path": repo_rel,
            "package": "other_sources/ocwd_groundwater_feasibility",
            "used_by_step": used_by,
            "exists_worktree": path.exists(),
            "bytes": path.stat().st_size if path.exists() else 0,
            "worktree_sha256": current_sha,
            "tracked_at_frozen_commit": tracked,
            "frozen_git_blob_sha1": blob_sha,
            "frozen_blob_sha256": frozen_sha,
            "recorded_package_sha256": recorded_sha,
            "worktree_matches_frozen": matches,
            "frozen_commit": FROZEN_COMMIT,
            "resolution": "verified_worktree_bytes" if tracked else "verified_against_committed_package_hash_manifest",
            "notes": "No dependency copied; source package read-only.",
        })
    frame = pd.DataFrame(rows)
    frame.to_csv(PROVENANCE / "GW1A_DEPENDENCY_MANIFEST.csv", index=False)
    write_json(PROVENANCE / "GW1A_DEPENDENCY_MANIFEST.json", frame.to_dict(orient="records"))
    return frame


def record_preflight(source_integrity: dict[str, object]) -> None:
    submodule = run_git(["submodule", "status"], check=False)
    status = run_git(["status", "--short"]).stdout.splitlines()
    try:
        import sklearn
        import pyarrow
        versions = {"numpy": np.__version__, "pandas": pd.__version__, "sklearn": sklearn.__version__, "pyarrow": pyarrow.__version__, "matplotlib": plt.matplotlib.__version__}
    except Exception as exc:  # pragma: no cover - diagnostic only
        versions = {"environment_error": repr(exc)}
    value = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(REPO_ROOT),
        "branch": run_git(["branch", "--show-current"]).stdout.strip(),
        "HEAD": run_git(["rev-parse", "HEAD"]).stdout.strip(),
        "task_start_status_before_new_module": [" m Data-center-PUE-prediction-tool"],
        "current_status_short": status,
        "submodule_status_exit_code": submodule.returncode,
        "submodule_status_stdout": submodule.stdout.splitlines(),
        "submodule_status_stderr": submodule.stderr.strip(),
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "package_versions": versions,
        "frozen_feasibility_integrity": {k: v for k, v in source_integrity.items() if k != "files"},
    }
    write_json(PROVENANCE / "REPOSITORY_PREFLIGHT.json", value)


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    wells = pd.read_parquet(FEASIBILITY_ROOT / "data/derived/DWR_OCWD_WELL_MASTER.parquet")
    heads = pd.read_parquet(FEASIBILITY_ROOT / "data/derived/DWR_OCWD_HEAD_OBSERVATIONS.parquet")
    independence = pd.read_csv(FEASIBILITY_ROOT / "outputs/tables/OBSERVATION_INDEPENDENCE_LEDGER.csv")
    river = pd.read_parquet(FEASIBILITY_ROOT / "data/derived/USGS_11074000_SANTA_ANA_RIVER_DAILY.parquet")
    if len(heads) != len(independence):
        raise RuntimeError("Independence ledger is not row-aligned with head observations")
    htime = pd.to_datetime(heads["measurement_datetime_pst"])
    ltime = pd.to_datetime(independence["measurement_datetime"])
    if not np.array_equal(heads["site_code"].astype(str).to_numpy(), independence["site_code"].astype(str).to_numpy()):
        raise RuntimeError("Independence site identifiers are not row-aligned")
    if not np.array_equal(htime.to_numpy(), ltime.to_numpy()):
        raise RuntimeError("Independence timestamps are not row-aligned")
    if not np.array_equal(heads["usable_head"].astype(bool).to_numpy(), independence["usable_head"].astype(bool).to_numpy()):
        raise RuntimeError("Independence usable-head flags are not row-aligned")
    heads = heads.copy()
    heads["measurement_datetime"] = htime
    heads["independence_class"] = independence["independence_class"].to_numpy()
    heads["collecting_organization"] = independence["collecting_organization"].fillna("").to_numpy()
    heads["reporting_organization"] = independence["reporting_organization"].fillna("").to_numpy()
    river = river.copy()
    river["timestamp"] = pd.to_datetime(river["timestamp"]).dt.normalize()
    return wells, heads, independence, river


def find_primary_window(heads: pd.DataFrame) -> tuple[pd.DataFrame, pd.Timestamp, pd.Timestamp]:
    usable = heads.loc[heads["usable_head"].astype(bool)].copy()
    usable = usable.loc[usable["measurement_datetime"].between(SEARCH_START, SEARCH_END)]
    usable["month"] = usable["measurement_datetime"].dt.to_period("M").dt.to_timestamp()
    months = pd.date_range(SEARCH_START.normalize(), pd.Timestamp("1999-11-01"), freq="MS")
    counts = usable.groupby("month")["site_code"].nunique().reindex(months, fill_value=0)
    eligible = counts.ge(50)
    run_ids = eligible.ne(eligible.shift(fill_value=eligible.iloc[0])).cumsum()
    candidates: list[tuple[int, pd.Timestamp, pd.Timestamp]] = []
    for _, group in counts.groupby(run_ids):
        if group.iloc[0] >= 50:
            candidates.append((len(group), group.index.min(), group.index.max()))
    if not candidates:
        raise RuntimeError("No interval meets the pre-registered 50-well threshold")
    n_months, start, end_month = sorted(candidates, key=lambda x: (-x[0], x[1]))[0]
    coverage = pd.DataFrame({
        "month": months,
        "n_distinct_wells_with_usable_observation": counts.to_numpy(),
        "meets_50_well_gate": eligible.to_numpy(),
        "run_id": run_ids.to_numpy(),
        "selected_primary_window": (months >= start) & (months <= end_month),
    })
    coverage.to_csv(COHORTS / "MONTHLY_COVERAGE.csv", index=False, date_format="%Y-%m-%d")
    status = {
        "selection_basis": "HEAD_OBSERVATION_AVAILABILITY_ONLY",
        "search_start": SEARCH_START.date().isoformat(),
        "search_end": "1999-11-30",
        "threshold_distinct_wells_each_calendar_month": 50,
        "primary_start_month": start.date().isoformat(),
        "primary_end_month": end_month.date().isoformat(),
        "n_consecutive_months": n_months,
        "minimum_monthly_wells": int(counts.loc[start:end_month].min()),
        "median_monthly_wells": float(counts.loc[start:end_month].median()),
        "date_selection_used_prediction_accuracy": False,
    }
    write_json(COHORTS / "PRIMARY_WINDOW.json", status)
    if start != EXPECTED_PRIMARY_START or end_month != EXPECTED_PRIMARY_END_MONTH or n_months != EXPECTED_PRIMARY_MONTHS:
        raise RuntimeError(f"Dense-window discrepancy: reproduced {start:%Y-%m} to {end_month:%Y-%m}, {n_months} months")
    return coverage, start, end_month


def utm11n_from_nad83(longitude: np.ndarray, latitude: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Forward Transverse Mercator for EPSG:26911 using the GRS80 ellipsoid."""
    a = 6378137.0
    inv_f = 298.257222101
    f = 1.0 / inv_f
    e2 = f * (2.0 - f)
    ep2 = e2 / (1.0 - e2)
    k0 = 0.9996
    lon0 = math.radians(-117.0)
    lat = np.radians(np.asarray(latitude, dtype=float))
    lon = np.radians(np.asarray(longitude, dtype=float))
    n = a / np.sqrt(1.0 - e2 * np.sin(lat) ** 2)
    t = np.tan(lat) ** 2
    c = ep2 * np.cos(lat) ** 2
    aa = np.cos(lat) * (lon - lon0)
    m = a * (
        (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256) * lat
        - (3 * e2 / 8 + 3 * e2**2 / 32 + 45 * e2**3 / 1024) * np.sin(2 * lat)
        + (15 * e2**2 / 256 + 45 * e2**3 / 1024) * np.sin(4 * lat)
        - (35 * e2**3 / 3072) * np.sin(6 * lat)
    )
    east = 500000.0 + k0 * n * (aa + (1 - t + c) * aa**3 / 6 + (5 - 18*t + t**2 + 72*c - 58*ep2) * aa**5 / 120)
    north = k0 * (m + n * np.tan(lat) * (aa**2 / 2 + (5 - t + 9*c + 4*c**2) * aa**4 / 24 + (61 - 58*t + t**2 + 600*c - 330*ep2) * aa**6 / 720))
    return east, north


def make_temporal_splits(start: pd.Timestamp, end_month: pd.Timestamp) -> pd.DataFrame:
    months = pd.date_range(start, end_month, freq="MS")
    n = len(months)
    train_cut = math.floor(0.70 * n)
    validation_cut = math.floor(0.85 * n)
    labels = np.where(np.arange(n) < train_cut, "TRAIN", np.where(np.arange(n) < validation_cut, "VALIDATION", "TEST"))
    assignments = pd.DataFrame({"month": months, "temporal_split": labels})
    assignments.to_csv(PROTOCOL / "TEMPORAL_MONTH_ASSIGNMENTS.csv", index=False, date_format="%Y-%m-%d")
    split = {
        "rule": "chronological months; [0,floor(0.70*n)) TRAIN, [floor(0.70*n),floor(0.85*n)) VALIDATION, remainder TEST",
        "n_months": n,
        "TRAIN": {"start": months[0].date().isoformat(), "end": months[train_cut-1].date().isoformat(), "n_months": train_cut},
        "VALIDATION": {"start": months[train_cut].date().isoformat(), "end": months[validation_cut-1].date().isoformat(), "n_months": validation_cut-train_cut},
        "TEST": {"start": months[validation_cut].date().isoformat(), "end": months[-1].date().isoformat(), "n_months": n-validation_cut},
        "random_row_split": False,
        "immutable_for_GW1B": True,
    }
    write_json(PROTOCOL / "TEMPORAL_SPLIT.json", split)
    holdouts = {
        "protocol_id": "OCWD_GW1A_20260904",
        "primary_window": {"start_month": months[0].strftime("%Y-%m"), "end_month": months[-1].strftime("%Y-%m"), "n_months": n},
        "temporal": split,
        "spatial": {"membership_file": "config/SPATIAL_FOLDS.csv", "k": 5, "random_state": SEED, "inputs": ["NAD83 longitude", "NAD83 latitude projected to EPSG:26911"]},
        "independent_agency": {"role": "evaluation_only", "class": INDEPENDENT_ORIGIN},
    }
    (CONFIG / "holdouts.yaml").write_text(yaml.safe_dump(holdouts, sort_keys=False), encoding="utf-8")
    return assignments


def make_spatial_folds(wells: pd.DataFrame, primary_site_codes: Iterable[str]) -> pd.DataFrame:
    site_set = set(primary_site_codes)
    frame = wells.loc[wells["site_code"].isin(site_set), ["site_code", "latitude_numeric", "longitude_numeric"]].copy()
    frame = frame.drop_duplicates("site_code").sort_values("site_code").reset_index(drop=True)
    if len(frame) != len(site_set) or frame[["latitude_numeric", "longitude_numeric"]].isna().any().any():
        raise RuntimeError("Primary wells lack unique authoritative coordinates")
    east, north = utm11n_from_nad83(frame["longitude_numeric"].to_numpy(), frame["latitude_numeric"].to_numpy())
    frame["easting_m"] = east
    frame["northing_m"] = north
    km = KMeans(n_clusters=5, random_state=SEED, n_init=50, algorithm="lloyd")
    raw_label = km.fit_predict(frame[["easting_m", "northing_m"]].to_numpy())
    centers = pd.DataFrame(km.cluster_centers_, columns=["easting_m", "northing_m"])
    order = centers.sort_values(["easting_m", "northing_m"]).index.tolist()
    label_map = {old: i + 1 for i, old in enumerate(order)}
    frame["spatial_fold"] = [label_map[int(x)] for x in raw_label]
    frame["coordinate_source"] = "DWR_OCWD_WELL_MASTER authoritative DWR periodic coordinates"
    frame["input_crs"] = "EPSG:4269 NAD83"
    frame["projected_crs"] = "EPSG:26911 NAD83 / UTM zone 11N"
    frame["fold_inputs"] = "easting_m|northing_m"
    frame["k"] = 5
    frame["random_state"] = SEED
    frame["n_init"] = 50
    frame.to_csv(CONFIG / "SPATIAL_FOLDS.csv", index=False, float_format="%.6f")
    return frame


def join_values(values: pd.Series) -> str:
    return " | ".join(sorted(set(str(x) for x in values if pd.notna(x) and str(x))))


def add_hydrology_features(transitions: pd.DataFrame, river: pd.DataFrame) -> pd.DataFrame:
    r = river.set_index("timestamp")["discharge_cfs"].sort_index()
    if r.index.duplicated().any():
        raise RuntimeError("USGS daily discharge contains duplicate dates")
    result = transitions.copy()
    columns: dict[str, list[object]] = {
        "interval_mean_discharge_cfs": [], "interval_expected_days": [], "interval_observed_days": [], "interval_max_source_date": [],
        "antecedent_30d_mean_discharge_cfs": [], "antecedent_30d_expected_days": [], "antecedent_30d_observed_days": [], "antecedent_30d_max_source_date": [],
    }
    for row in result[["t_prev", "t_target"]].itertuples(index=False):
        origin_date = pd.Timestamp(row.t_prev).normalize()
        target_date = pd.Timestamp(row.t_target).normalize()
        interval_dates = pd.date_range(origin_date, target_date - pd.Timedelta(days=1), freq="D") if target_date > origin_date else pd.DatetimeIndex([])
        antecedent_dates = pd.date_range(target_date - pd.Timedelta(days=30), target_date - pd.Timedelta(days=1), freq="D")
        iv = r.reindex(interval_dates)
        av = r.reindex(antecedent_dates)
        iv_complete = len(interval_dates) > 0 and iv.notna().all()
        av_complete = len(antecedent_dates) == 30 and av.notna().all()
        columns["interval_mean_discharge_cfs"].append(float(iv.mean()) if iv_complete else np.nan)
        columns["interval_expected_days"].append(len(interval_dates))
        columns["interval_observed_days"].append(int(iv.notna().sum()))
        columns["interval_max_source_date"].append(interval_dates.max() if len(interval_dates) else pd.NaT)
        columns["antecedent_30d_mean_discharge_cfs"].append(float(av.mean()) if av_complete else np.nan)
        columns["antecedent_30d_expected_days"].append(len(antecedent_dates))
        columns["antecedent_30d_observed_days"].append(int(av.notna().sum()))
        columns["antecedent_30d_max_source_date"].append(antecedent_dates.max() if len(antecedent_dates) else pd.NaT)
    for name, values in columns.items():
        result[name] = values
    result["log1p_interval_mean_discharge_cfs"] = np.log1p(result["interval_mean_discharge_cfs"])
    result["log1p_antecedent_30d_mean_discharge_cfs"] = np.log1p(result["antecedent_30d_mean_discharge_cfs"])
    result["hydrologic_feature_complete"] = result[["log1p_interval_mean_discharge_cfs", "log1p_antecedent_30d_mean_discharge_cfs"]].notna().all(axis=1)
    result["hydrologic_forcing_role"] = "PUBLIC_BACKGROUND_HYDROLOGY_NOT_MANAGED_RECHARGE"
    return result


def build_representations(
    wells: pd.DataFrame,
    heads: pd.DataFrame,
    river: pd.DataFrame,
    start: pd.Timestamp,
    end_month: pd.Timestamp,
    month_assignments: pd.DataFrame,
    folds: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, object]]:
    end = end_month + pd.offsets.MonthEnd(1) + pd.Timedelta(hours=23, minutes=59, seconds=59)
    obs = heads.loc[heads["usable_head"].astype(bool) & heads["measurement_datetime"].between(start, end)].copy()
    obs["month"] = obs["measurement_datetime"].dt.to_period("M").dt.to_timestamp()
    months = pd.date_range(start, end_month, freq="MS")
    sites = sorted(obs["site_code"].unique())
    monthly = obs.groupby(["site_code", "month"], as_index=False)["groundwater_elevation_ft_navd88"].median()
    wide = monthly.pivot(index="site_code", columns="month", values="groundwater_elevation_ft_navd88").reindex(index=sites, columns=months)
    wide.columns = [pd.Timestamp(c).strftime("%Y-%m") for c in wide.columns]
    wide_out = wide.reset_index()
    mask_out = wide.notna().reset_index()
    wide_out.to_parquet(DATA_DERIVED / "MONTHLY_HEAD_MATRIX.parquet", index=False)
    mask_out.to_parquet(DATA_DERIVED / "MONTHLY_OBSERVATION_MASK.parquet", index=False)

    aggregated = (
        obs.groupby(["site_code", "measurement_datetime"], as_index=False)
        .agg(
            head=("groundwater_elevation_ft_navd88", "median"),
            n_same_timestamp_observations=("groundwater_elevation_ft_navd88", "size"),
            independence_class=("independence_class", join_values),
            collecting_organization=("collecting_organization", join_values),
            reporting_organization=("reporting_organization", join_values),
            dwr_source=("source", join_values),
        )
        .sort_values(["site_code", "measurement_datetime"])
    )
    grouped = aggregated.groupby("site_code", sort=False)
    aggregated["t_prev"] = grouped["measurement_datetime"].shift(1)
    aggregated["h_prev"] = grouped["head"].shift(1)
    aggregated["prev_independence_class"] = grouped["independence_class"].shift(1)
    aggregated["prev_collecting_organization"] = grouped["collecting_organization"].shift(1)
    transitions = aggregated.dropna(subset=["t_prev", "h_prev"]).copy()
    transitions = transitions.rename(columns={
        "measurement_datetime": "t_target", "head": "h_target",
        "independence_class": "target_independence_class",
        "collecting_organization": "target_collecting_organization",
        "reporting_organization": "target_reporting_organization",
    })
    transitions["delta_h"] = transitions["h_target"] - transitions["h_prev"]
    transitions["delta_days"] = (transitions["t_target"] - transitions["t_prev"]).dt.total_seconds() / 86400.0
    if (transitions["delta_days"] <= 0).any():
        raise RuntimeError("Transition construction produced a non-positive gap")
    transitions["target_month"] = transitions["t_target"].dt.to_period("M").dt.to_timestamp()
    transitions = transitions.merge(month_assignments, left_on="target_month", right_on="month", how="left").drop(columns="month")
    transitions = transitions.merge(
        folds[["site_code", "latitude_numeric", "longitude_numeric", "easting_m", "northing_m", "spatial_fold"]],
        on="site_code", how="left", validate="many_to_one",
    )
    both_ocwd = transitions["target_independence_class"].eq(OCWD_ORIGIN) & transitions["prev_independence_class"].eq(OCWD_ORIGIN)
    both_ind = transitions["target_independence_class"].eq(INDEPENDENT_ORIGIN) & transitions["prev_independence_class"].eq(INDEPENDENT_ORIGIN)
    transitions["transition_independence_class"] = np.where(both_ocwd, OCWD_ORIGIN, np.where(both_ind, INDEPENDENT_ORIGIN, "MIXED_ORIGIN"))
    doy = transitions["t_target"].dt.dayofyear
    transitions["target_day_of_year"] = doy
    transitions["season_sin"] = np.sin(2 * np.pi * doy / 365.25)
    transitions["season_cos"] = np.cos(2 * np.pi * doy / 365.25)
    transitions["time_trend_years"] = (transitions["t_target"] - EXPECTED_PRIMARY_START).dt.total_seconds() / (365.25 * 86400.0)
    for gap in [45, 90, 120, 180]:
        transitions[f"gap_le_{gap}_days"] = transitions["delta_days"].le(gap)
    transitions["gap_group_primary"] = pd.cut(
        transitions["delta_days"], bins=[0, 45, 90, 120, np.inf],
        labels=["LE_45", "GT_45_LE_90", "GT_90_LE_120", "GT_120"], right=True,
    ).astype(str)
    transitions = add_hydrology_features(transitions, river)
    transitions = transitions.sort_values(["site_code", "t_target"]).reset_index(drop=True)
    transitions.insert(0, "transition_id", [f"TR{i:06d}" for i in range(1, len(transitions) + 1)])
    transitions.to_parquet(DATA_DERIVED / "HEAD_TRANSITIONS.parquet", index=False)

    summary = {
        "primary_window": {"start": start.strftime("%Y-%m-%d"), "end_month": end_month.strftime("%Y-%m-%d"), "n_months": len(months)},
        "monthly_matrix": {
            "n_wells": len(sites), "n_months": len(months), "n_cells": int(len(sites) * len(months)),
            "n_observed_cells": int(wide.notna().sum().sum()), "n_missing_cells_retained": int(wide.isna().sum().sum()),
            "n_input_usable_observations": int(len(obs)), "aggregation": "median within well-month", "interpolated_cells": 0,
        },
        "same_timestamp_handling": {
            "n_unique_well_timestamps": int(len(aggregated)),
            "n_groups_with_multiple_records": int((aggregated["n_same_timestamp_observations"] > 1).sum()),
            "aggregation": "median; no within-time order inferred",
        },
        "transitions": {
            "n_all_consecutive_unique_timestamp_transitions": int(len(transitions)),
            "n_wells": int(transitions["site_code"].nunique()),
            "n_le_45": int(transitions["gap_le_45_days"].sum()),
            "n_le_90": int(transitions["gap_le_90_days"].sum()),
            "n_le_120": int(transitions["gap_le_120_days"].sum()),
            "n_le_180": int(transitions["gap_le_180_days"].sum()),
            "n_primary_ocwd_le_120": int((transitions["gap_le_120_days"] & transitions["transition_independence_class"].eq(OCWD_ORIGIN)).sum()),
            "n_independent_le_120": int((transitions["gap_le_120_days"] & transitions["transition_independence_class"].eq(INDEPENDENT_ORIGIN)).sum()),
            "n_hydrologic_feature_complete_le_120": int((transitions["gap_le_120_days"] & transitions["hydrologic_feature_complete"]).sum()),
            "target_interpolation": "NONE",
        },
    }
    write_json(COHORTS / "REPRESENTATION_SUMMARY.json", summary)
    return transitions, summary


def make_protocol_summaries(transitions: pd.DataFrame, folds: pd.DataFrame) -> None:
    primary = transitions.loc[transitions["gap_le_120_days"] & transitions["transition_independence_class"].eq(OCWD_ORIGIN)].copy()
    rows = []
    for fold, fg in folds.groupby("spatial_fold"):
        sites = set(fg["site_code"])
        tg = primary.loc[primary["site_code"].isin(sites)]
        rows.append({
            "spatial_fold": int(fold), "n_wells": len(sites),
            "easting_min_m": fg["easting_m"].min(), "easting_max_m": fg["easting_m"].max(),
            "northing_min_m": fg["northing_m"].min(), "northing_max_m": fg["northing_m"].max(),
            "n_transitions_total_le_120": len(tg),
            "n_train_transitions": int(tg["temporal_split"].eq("TRAIN").sum()),
            "n_validation_transitions": int(tg["temporal_split"].eq("VALIDATION").sum()),
            "n_test_transitions": int(tg["temporal_split"].eq("TEST").sum()),
            "fold_construction_inputs": "coordinates_only_EPSG26911",
        })
    pd.DataFrame(rows).to_csv(PROTOCOL / "SPATIAL_FOLD_SUMMARY.csv", index=False, float_format="%.6f")
    ind = transitions.loc[transitions["transition_independence_class"].eq(INDEPENDENT_ORIGIN)]
    write_json(PROTOCOL / "INDEPENDENT_AGENCY_HOLDOUT.json", {
        "class": INDEPENDENT_ORIGIN,
        "role": "EVALUATION_ONLY_NEVER_TUNING",
        "primary_window_transition_count": int(len(ind)),
        "primary_window_well_count": int(ind["site_code"].nunique()),
        "primary_le_120_transition_count": int(ind["gap_le_120_days"].sum()) if len(ind) else 0,
        "T3_feasible_within_frozen_primary_window": bool((ind["gap_le_120_days"] & ind["temporal_split"].eq("TEST")).any()) if len(ind) else False,
        "decision": "Report unavailable rather than expand the coverage-selected cohort or mix provenance classes." if len(ind) == 0 else "Evaluate only if leakage guards pass.",
    })
    event_path = FEASIBILITY_ROOT / "outputs/tables/EVENT_REGISTRY.csv"
    tracer_path = FEASIBILITY_ROOT / "outputs/tables/TRACER_VALIDATION_REGISTRY.csv"
    events = pd.read_csv(event_path)
    tracers = pd.read_csv(tracer_path)
    write_json(PROTOCOL / "RESERVED_EXTERNAL_VALIDATION.json", {
        "status": "RESERVED_UNTOUCHED_OUTSIDE_FITTING_TUNING_AND_STRUCTURE_SELECTION",
        "assets": [
            {"name": "LLNL_KRAEMER_TRACER_RESULTS", "path": str(tracer_path.relative_to(REPO_ROOT)), "sha256": sha256_file(tracer_path), "records": len(tracers)},
            {"name": "MBI_1_2015_RESPONSE_EVENT", "path": str(event_path.relative_to(REPO_ROOT)), "sha256": sha256_file(event_path), "records": int(events["event_id"].astype(str).str.contains("MBI-1").sum())},
            {"name": "MBI_2_THROUGH_MBI_5_2020_RESPONSE_EVENTS", "path": str(event_path.relative_to(REPO_ROOT)), "sha256": sha256_file(event_path), "records": int(events["event_id"].astype(str).str.contains("MBI-[2345]").sum())},
        ],
        "used_for_features": False, "used_for_fitting": False, "used_for_tuning": False, "used_for_model_selection": False,
        "future_role": "validation only after groundwater model is frozen",
    })
    write_json(PROTOCOL / "B0_B3_MODEL_SPECIFICATIONS.json", {
        "scope": "NO_PUMPING_NO_WRMS",
        "B0": {"formula": "h_hat_target = h_prev", "fitted": False},
        "B1": {"target": "delta_h", "features": MODEL_FEATURES["B1"], "fitting": "pooled OLS; training only"},
        "B2": {"target": "h_target", "features": MODEL_FEATURES["B2"], "fitting": "pooled OLS; training only"},
        "B3": {"target": "h_target", "features": MODEL_FEATURES["B3"], "fitting": "pooled OLS; training only", "forcing_role": "PUBLIC_BACKGROUND_HYDROLOGY_NOT_MANAGED_RECHARGE"},
        "prediction_task": "one-step groundwater-response prediction conditional on observed origin state and realized public hydrologic forcing over/preceding the interval; not an operational forecast",
        "outcomes": ["h_target", "delta_h"],
        "forbidden_features": ["pumping", "WRMS managed recharge", "tracer", "MBI response", "future-after-target discharge", "network connectivity"],
    })


def save_figure(fig: plt.Figure, stem: str) -> None:
    fig.savefig(FIGURES / f"{stem}.png", dpi=220, bbox_inches="tight")
    fig.savefig(FIGURES / f"{stem}.pdf", bbox_inches="tight", metadata={"Creator": "OCWD GW-1A", "CreationDate": None, "ModDate": None})
    plt.close(fig)


def iter_geojson_rings(geometry: dict) -> Iterable[list[list[float]]]:
    if geometry.get("type") == "Polygon":
        yield from geometry.get("coordinates", [])
    elif geometry.get("type") == "MultiPolygon":
        for polygon in geometry.get("coordinates", []):
            yield from polygon


def plot_protocol_figures(wide: pd.DataFrame, folds: pd.DataFrame, assignments: pd.DataFrame) -> None:
    month_cols = [c for c in wide.columns if c != "site_code"]
    matrix = wide[month_cols].notna().to_numpy()
    order = np.lexsort((wide["site_code"].to_numpy(), -matrix.sum(axis=1)))
    fig, ax = plt.subplots(figsize=(10.5, 6.2))
    ax.imshow(matrix[order], aspect="auto", interpolation="nearest", cmap=plt.matplotlib.colors.ListedColormap(["#eeeeee", "#176b87"]), vmin=0, vmax=1)
    tick_idx = np.arange(0, len(month_cols), 12)
    ax.set_xticks(tick_idx, [month_cols[i] for i in tick_idx], rotation=35, ha="right")
    ax.set_xlabel("Calendar month")
    ax.set_ylabel(f"Wells (n={len(wide)}; ordered by observed-month count)")
    ax.set_title("GW-1A primary-window observation mask (no interpolation)")
    ax.text(0.01, -0.19, "Evidence: OBSERVED DWR periodic heads; teal = ≥1 QA-usable measurement aggregated by monthly median; gray = missing retained.", transform=ax.transAxes, fontsize=8.5)
    save_figure(fig, "fig01_primary_observation_mask")

    fig = plt.figure(figsize=(10.8, 7.4))
    gs = fig.add_gridspec(2, 1, height_ratios=[0.7, 3.2], hspace=0.30)
    ax0 = fig.add_subplot(gs[0])
    colors = {"TRAIN": "#4472C4", "VALIDATION": "#ED7D31", "TEST": "#A5A5A5"}
    for split, group in assignments.groupby("temporal_split", sort=False):
        ax0.barh([0], [len(group)], left=[group.index.min()], color=colors[split], label=f"{split} ({len(group)} months)", height=0.5)
    ax0.set_xlim(-0.5, len(assignments)-0.5)
    idx = np.arange(0, len(assignments), 12)
    ax0.set_xticks(idx, [assignments.iloc[i]["month"].strftime("%Y-%m") for i in idx], rotation=30, ha="right")
    ax0.set_yticks([])
    ax0.legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.45), frameon=False)
    ax0.set_title("Frozen chronological split", loc="left", fontsize=11)

    ax1 = fig.add_subplot(gs[1])
    basin = json.loads((FEASIBILITY_ROOT / "data/derived/DWR_BASIN_8_001.geojson").read_text(encoding="utf-8"))
    features = basin.get("features", []) if basin.get("type") == "FeatureCollection" else [{"geometry": basin}]
    for feature in features:
        for ring in iter_geojson_rings(feature["geometry"]):
            coords = np.asarray(ring)
            ex, ny = utm11n_from_nad83(coords[:, 0], coords[:, 1])
            ax1.plot(ex / 1000, ny / 1000, color="#555555", linewidth=1.0)
    palette = ["#4472C4", "#ED7D31", "#70AD47", "#C55A11", "#8064A2"]
    for fold, group in folds.groupby("spatial_fold"):
        ax1.scatter(group["easting_m"] / 1000, group["northing_m"] / 1000, s=18, alpha=0.78, color=palette[int(fold)-1], label=f"Fold {fold} (n={len(group)})")
    ax1.set_aspect("equal", adjustable="box")
    ax1.set_xlabel("Easting (km; EPSG:26911)")
    ax1.set_ylabel("Northing (km; EPSG:26911)")
    ax1.set_title("Coordinate-only spatial folds", loc="left", fontsize=11)
    ax1.legend(loc="best", frameon=False, fontsize=8)
    fig.suptitle("GW-1A frozen temporal and spatial holdouts", y=0.995, fontsize=13)
    fig.text(0.01, 0.005, "Fold construction used only authoritative well coordinates; heads, screens, forcing, residuals, and model skill were excluded.", fontsize=8.5)
    save_figure(fig, "fig02_frozen_temporal_spatial_holdouts")


def freeze_protocol() -> dict[str, object]:
    ensure_directories()
    integrity = verify_frozen_feasibility()
    write_json(PROVENANCE / "SOURCE_FEASIBILITY_PACKAGE_INTEGRITY.json", integrity)
    dependencies = create_dependency_manifest()
    record_preflight(integrity)
    wells, heads, _, river = load_inputs()
    coverage, start, end_month = find_primary_window(heads)
    assignments = make_temporal_splits(start, end_month)
    usable_primary = heads.loc[
        heads["usable_head"].astype(bool)
        & heads["measurement_datetime"].between(start, end_month + pd.offsets.MonthEnd(1) + pd.Timedelta(hours=23, minutes=59, seconds=59))
    ]
    folds = make_spatial_folds(wells, usable_primary["site_code"].unique())
    transitions, representation = build_representations(wells, heads, river, start, end_month, assignments, folds)
    make_protocol_summaries(transitions, folds)
    wide = pd.read_parquet(DATA_DERIVED / "MONTHLY_HEAD_MATRIX.parquet")
    plot_protocol_figures(wide, folds, assignments)

    frozen_paths = [
        CONFIG / "analysis_protocol.yaml", CONFIG / "holdouts.yaml", CONFIG / "SPATIAL_FOLDS.csv",
        MODULE_ROOT / "GW1B_PREREGISTRATION.md", MODULE_ROOT / "GW1B_PREREGISTRATION.yaml",
        PROVENANCE / "GW1A_DEPENDENCY_MANIFEST.csv", PROVENANCE / "GW1A_DEPENDENCY_MANIFEST.json",
        PROVENANCE / "SOURCE_FEASIBILITY_PACKAGE_INTEGRITY.json",
        COHORTS / "PRIMARY_WINDOW.json", COHORTS / "MONTHLY_COVERAGE.csv", COHORTS / "REPRESENTATION_SUMMARY.json",
        DATA_DERIVED / "MONTHLY_HEAD_MATRIX.parquet", DATA_DERIVED / "MONTHLY_OBSERVATION_MASK.parquet", DATA_DERIVED / "HEAD_TRANSITIONS.parquet",
        PROTOCOL / "TEMPORAL_SPLIT.json", PROTOCOL / "TEMPORAL_MONTH_ASSIGNMENTS.csv", PROTOCOL / "SPATIAL_FOLD_SUMMARY.csv",
        PROTOCOL / "INDEPENDENT_AGENCY_HOLDOUT.json", PROTOCOL / "RESERVED_EXTERNAL_VALIDATION.json", PROTOCOL / "B0_B3_MODEL_SPECIFICATIONS.json",
    ]
    protocol_freeze = {
        "status": "FROZEN_BEFORE_MODEL_COMPARISON",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "frozen_feasibility_commit": FROZEN_COMMIT,
        "files": [{"path": p.relative_to(MODULE_ROOT).as_posix(), "bytes": p.stat().st_size, "sha256": sha256_file(p)} for p in frozen_paths],
        "dependency_count": len(dependencies),
        "primary_window": {"start": start.strftime("%Y-%m"), "end": end_month.strftime("%Y-%m"), "months": len(assignments)},
        "no_model_was_fit_in_this_stage": True,
    }
    write_json(PROTOCOL / "PROTOCOL_FREEZE.json", protocol_freeze)
    return {"integrity": integrity, "representation": representation, "protocol_freeze": protocol_freeze, "coverage_rows": len(coverage)}


def verify_protocol_freeze() -> dict[str, object]:
    freeze = json.loads((PROTOCOL / "PROTOCOL_FREEZE.json").read_text(encoding="utf-8"))
    failures = []
    for row in freeze["files"]:
        path = MODULE_ROOT / row["path"]
        if not path.exists() or path.stat().st_size != int(row["bytes"]) or sha256_file(path) != row["sha256"]:
            failures.append(row["path"])
    if failures:
        raise RuntimeError("Protocol freeze mismatch before model fitting: " + ", ".join(failures))
    verify_frozen_feasibility()
    return freeze


@dataclass
class OLSFit:
    model: str
    target: str
    features: list[str]
    mean: np.ndarray
    scale: np.ndarray
    coefficients: np.ndarray


def fit_ols(model: str, train: pd.DataFrame) -> OLSFit:
    features = MODEL_FEATURES[model]
    target = "delta_h" if model == "B1" else "h_target"
    x = train[features].to_numpy(dtype=float)
    y = train[target].to_numpy(dtype=float)
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise RuntimeError(f"Non-finite training data for {model}")
    mean = x.mean(axis=0)
    scale = x.std(axis=0, ddof=0)
    scale = np.where(scale > 1e-12, scale, 1.0)
    xs = (x - mean) / scale
    design = np.column_stack([np.ones(len(xs)), xs])
    coef, _, _, _ = np.linalg.lstsq(design, y, rcond=None)
    return OLSFit(model=model, target=target, features=list(features), mean=mean, scale=scale, coefficients=coef)


def predict(fit: OLSFit, frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    x = frame[fit.features].to_numpy(dtype=float)
    xs = (x - fit.mean) / fit.scale
    raw = np.column_stack([np.ones(len(xs)), xs]) @ fit.coefficients
    if fit.target == "delta_h":
        delta = raw
        head = frame["h_prev"].to_numpy(dtype=float) + delta
    else:
        head = raw
        delta = head - frame["h_prev"].to_numpy(dtype=float)
    return head, delta


def fit_audit_rows(fit_id: str, regime: str, threshold: int, fold: int | None, fit: OLSFit, train: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    names = ["INTERCEPT", *fit.features]
    means = [0.0, *fit.mean.tolist()]
    scales = [1.0, *fit.scale.tolist()]
    for name, coefficient, mean, scale in zip(names, fit.coefficients, means, scales):
        rows.append({
            "fit_id": fit_id, "regime": regime, "gap_threshold_days": threshold,
            "held_out_spatial_fold": fold if fold is not None else "",
            "model": fit.model, "target": fit.target, "feature": name,
            "coefficient_standardized_scale": coefficient, "training_feature_mean": mean, "training_feature_scale": scale,
            "n_training_transitions": len(train), "n_training_wells": train["site_code"].nunique(),
            "fit_split": "TRAIN", "training_target_month_min": train["target_month"].min(), "training_target_month_max": train["target_month"].max(),
            "training_independence_classes": join_values(train["transition_independence_class"]),
            "validation_used": False, "test_used": False, "hyperparameter_search": "NONE",
        })
    return rows


def predictions_for_split(
    transitions: pd.DataFrame,
    regime: str,
    threshold: int,
    held_out_fold: int | None,
) -> tuple[pd.DataFrame, list[dict[str, object]], pd.DataFrame]:
    eligible = transitions.loc[
        transitions[f"gap_le_{threshold}_days"]
        & transitions["hydrologic_feature_complete"]
        & transitions["transition_independence_class"].eq(OCWD_ORIGIN)
    ].copy()
    if held_out_fold is None:
        train = eligible.loc[eligible["temporal_split"].eq("TRAIN")]
        train_wells = set(train["site_code"])
        test = eligible.loc[eligible["temporal_split"].eq("TEST") & eligible["site_code"].isin(train_wells)]
        fold_label = "NONE"
    else:
        train = eligible.loc[eligible["temporal_split"].eq("TRAIN") & eligible["spatial_fold"].ne(held_out_fold)]
        test = eligible.loc[eligible["temporal_split"].eq("TEST") & eligible["spatial_fold"].eq(held_out_fold)]
        fold_label = str(held_out_fold)
    if train.empty or test.empty:
        raise RuntimeError(f"Empty train/test sample for {regime}, fold={held_out_fold}, threshold={threshold}")
    base_cols = ["transition_id", "site_code", "t_prev", "t_target", "target_month", "delta_days", "gap_group_primary", "spatial_fold", "h_prev", "h_target", "delta_h"]
    predictions: list[pd.DataFrame] = []
    fit_rows: list[dict[str, object]] = []
    fit_samples: list[pd.DataFrame] = []
    b0 = test[base_cols].copy()
    b0["model"] = "B0"
    b0["regime"] = regime
    b0["held_out_spatial_fold"] = fold_label
    b0["gap_threshold_days"] = threshold
    b0["h_pred"] = b0["h_prev"]
    b0["delta_pred"] = 0.0
    predictions.append(b0)
    for model in ["B1", "B2", "B3"]:
        fit_id = f"{regime}_G{threshold}_F{held_out_fold if held_out_fold is not None else 'ALL'}_{model}"
        fitted = fit_ols(model, train)
        h_pred, delta_pred = predict(fitted, test)
        pred = test[base_cols].copy()
        pred["model"] = model
        pred["regime"] = regime
        pred["held_out_spatial_fold"] = fold_label
        pred["gap_threshold_days"] = threshold
        pred["h_pred"] = h_pred
        pred["delta_pred"] = delta_pred
        predictions.append(pred)
        fit_rows.extend(fit_audit_rows(fit_id, regime, threshold, held_out_fold, fitted, train))
        sample = train[["transition_id", "site_code", "target_month", "temporal_split", "spatial_fold", "transition_independence_class"]].copy()
        sample["fit_id"] = fit_id
        sample["model"] = model
        sample["regime"] = regime
        sample["held_out_spatial_fold"] = fold_label
        sample["gap_threshold_days"] = threshold
        fit_samples.append(sample)
    return pd.concat(predictions, ignore_index=True), fit_rows, pd.concat(fit_samples, ignore_index=True)


def run_prediction_set(transitions: pd.DataFrame, threshold: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    predictions = []
    audit_rows: list[dict[str, object]] = []
    samples = []
    p, a, s = predictions_for_split(transitions, "T1_TEMPORAL_OOS", threshold, None)
    predictions.append(p); audit_rows.extend(a); samples.append(s)
    for fold in range(1, 6):
        p, a, s = predictions_for_split(transitions, "T2_SPATIOTEMPORAL_OOS", threshold, fold)
        predictions.append(p); audit_rows.extend(a); samples.append(s)
    return pd.concat(predictions, ignore_index=True), pd.DataFrame(audit_rows), pd.concat(samples, ignore_index=True)


def metric_row(group: pd.DataFrame) -> dict[str, object]:
    err_h = group["h_pred"].to_numpy() - group["h_target"].to_numpy()
    err_d = group["delta_pred"].to_numpy() - group["delta_h"].to_numpy()
    actual_delta = group["delta_h"].to_numpy()
    pred_delta = group["delta_pred"].to_numpy()
    meaningful = actual_delta != 0
    directional = meaningful & (pred_delta != 0)
    sign_accuracy = float(np.mean(np.sign(pred_delta[meaningful]) == np.sign(actual_delta[meaningful]))) if meaningful.any() and directional.any() else np.nan
    ss_h = float(np.sum((group["h_target"] - group["h_target"].mean()) ** 2))
    ss_d = float(np.sum((group["delta_h"] - group["delta_h"].mean()) ** 2))
    return {
        "n_transitions": len(group), "n_wells": group["site_code"].nunique(),
        "MAE_h_ft": float(np.mean(np.abs(err_h))), "RMSE_h_ft": float(np.sqrt(np.mean(err_h**2))), "bias_h_ft": float(np.mean(err_h)),
        "MAE_delta_h_ft": float(np.mean(np.abs(err_d))), "RMSE_delta_h_ft": float(np.sqrt(np.mean(err_d**2))), "bias_delta_h_ft": float(np.mean(err_d)),
        "sign_accuracy_delta_h": sign_accuracy,
        "R2_h_secondary": 1.0 - float(np.sum(err_h**2)) / ss_h if ss_h > 0 else np.nan,
        "R2_delta_h_secondary": 1.0 - float(np.sum(err_d**2)) / ss_d if ss_d > 0 else np.nan,
        "delta_h_IQR_ft": float(np.subtract(*np.percentile(group["delta_h"], [75, 25]))),
    }


def aggregate_metrics(predictions: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    rows = []
    for keys, group in predictions.groupby(group_columns, dropna=False, sort=True):
        keys = keys if isinstance(keys, tuple) else (keys,)
        row = dict(zip(group_columns, keys))
        row.update(metric_row(group))
        rows.append(row)
    result = pd.DataFrame(rows)
    skill_keys = [c for c in group_columns if c != "model"]
    base = result.loc[result["model"].eq("B0"), skill_keys + ["RMSE_h_ft", "MAE_h_ft", "RMSE_delta_h_ft", "MAE_delta_h_ft"]].copy()
    base = base.rename(columns={c: f"B0_{c}" for c in ["RMSE_h_ft", "MAE_h_ft", "RMSE_delta_h_ft", "MAE_delta_h_ft"]})
    result = result.merge(base, on=skill_keys, how="left", validate="many_to_one")
    result["RMSE_skill_vs_persistence"] = 1.0 - result["RMSE_delta_h_ft"] / result["B0_RMSE_delta_h_ft"]
    result["MAE_skill_vs_persistence"] = 1.0 - result["MAE_delta_h_ft"] / result["B0_MAE_delta_h_ft"]
    return result


def well_level_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (regime, model, site), group in predictions.groupby(["regime", "model", "site_code"], sort=True):
        row = {"regime": regime, "model": model, "site_code": site}
        row.update(metric_row(group))
        rows.append(row)
    result = pd.DataFrame(rows)
    base = result.loc[result["model"].eq("B0"), ["regime", "site_code", "RMSE_delta_h_ft", "MAE_delta_h_ft"]].rename(columns={"RMSE_delta_h_ft": "B0_RMSE_delta_h_ft", "MAE_delta_h_ft": "B0_MAE_delta_h_ft"})
    result = result.merge(base, on=["regime", "site_code"], how="left", validate="many_to_one")
    result["well_RMSE_improvement_ft_vs_B0"] = result["B0_RMSE_delta_h_ft"] - result["RMSE_delta_h_ft"]
    result["well_MAE_improvement_ft_vs_B0"] = result["B0_MAE_delta_h_ft"] - result["MAE_delta_h_ft"]
    result["well_RMSE_skill_vs_B0"] = 1.0 - result["RMSE_delta_h_ft"] / result["B0_RMSE_delta_h_ft"]
    result["well_MAE_skill_vs_B0"] = 1.0 - result["MAE_delta_h_ft"] / result["B0_MAE_delta_h_ft"]
    return result


def bootstrap_difference(predictions: pd.DataFrame, comparison_model: str, reference_model: str, regime: str, seed_offset: int) -> dict[str, object]:
    a = predictions.loc[(predictions["regime"] == regime) & (predictions["model"] == comparison_model)].copy()
    b = predictions.loc[(predictions["regime"] == regime) & (predictions["model"] == reference_model)].copy()
    merged = a[["transition_id", "site_code", "h_target", "h_pred"]].merge(
        b[["transition_id", "h_pred"]], on="transition_id", suffixes=("_model", "_reference"), validate="one_to_one"
    )
    grouped = []
    for site, group in merged.groupby("site_code"):
        err_model = group["h_pred_model"] - group["h_target"]
        err_ref = group["h_pred_reference"] - group["h_target"]
        grouped.append((site, len(group), float(np.abs(err_model).sum()), float((err_model**2).sum()), float(np.abs(err_ref).sum()), float((err_ref**2).sum())))
    arr = np.asarray([x[1:] for x in grouped], dtype=float)
    rng = np.random.default_rng(SEED + seed_offset)
    mae_diff = np.empty(1000)
    rmse_diff = np.empty(1000)
    mae_skill = np.empty(1000)
    rmse_skill = np.empty(1000)
    n_wells = len(grouped)
    for i in range(1000):
        idx = rng.integers(0, n_wells, size=n_wells)
        sample = arr[idx]
        n = sample[:, 0].sum()
        mae_model = sample[:, 1].sum() / n
        rmse_model = math.sqrt(sample[:, 2].sum() / n)
        mae_ref = sample[:, 3].sum() / n
        rmse_ref = math.sqrt(sample[:, 4].sum() / n)
        mae_diff[i] = mae_ref - mae_model
        rmse_diff[i] = rmse_ref - rmse_model
        mae_skill[i] = 1.0 - mae_model / mae_ref
        rmse_skill[i] = 1.0 - rmse_model / rmse_ref
    point_model = metric_row(a)
    point_ref = metric_row(b)
    return {
        "regime": regime, "comparison_model": comparison_model, "reference_model": reference_model,
        "difference_direction": "positive_means_comparison_model_has_lower_error",
        "n_wells": n_wells, "n_transitions": len(merged), "bootstrap_resamples": 1000, "resampling_unit": "well", "seed": SEED + seed_offset,
        "MAE_improvement_ft": point_ref["MAE_delta_h_ft"] - point_model["MAE_delta_h_ft"],
        "MAE_improvement_ci95_low_ft": float(np.percentile(mae_diff, 2.5)), "MAE_improvement_ci95_high_ft": float(np.percentile(mae_diff, 97.5)),
        "RMSE_improvement_ft": point_ref["RMSE_delta_h_ft"] - point_model["RMSE_delta_h_ft"],
        "RMSE_improvement_ci95_low_ft": float(np.percentile(rmse_diff, 2.5)), "RMSE_improvement_ci95_high_ft": float(np.percentile(rmse_diff, 97.5)),
        "MAE_skill_vs_reference": 1.0 - point_model["MAE_delta_h_ft"] / point_ref["MAE_delta_h_ft"],
        "MAE_skill_ci95_low": float(np.percentile(mae_skill, 2.5)), "MAE_skill_ci95_high": float(np.percentile(mae_skill, 97.5)),
        "RMSE_skill_vs_reference": 1.0 - point_model["RMSE_delta_h_ft"] / point_ref["RMSE_delta_h_ft"],
        "RMSE_skill_ci95_low": float(np.percentile(rmse_skill, 2.5)), "RMSE_skill_ci95_high": float(np.percentile(rmse_skill, 97.5)),
    }


def summarize_well_distribution(primary_metrics: pd.DataFrame, wells: pd.DataFrame) -> pd.DataFrame:
    summaries = []
    for (regime, model), group in wells.groupby(["regime", "model"]):
        summaries.append({
            "regime": regime, "model": model,
            "median_well_RMSE_ft": group["RMSE_delta_h_ft"].median(),
            "well_RMSE_IQR_ft": group["RMSE_delta_h_ft"].quantile(.75) - group["RMSE_delta_h_ft"].quantile(.25),
            "median_well_MAE_ft": group["MAE_delta_h_ft"].median(),
            "well_MAE_IQR_ft": group["MAE_delta_h_ft"].quantile(.75) - group["MAE_delta_h_ft"].quantile(.25),
            "median_well_RMSE_improvement_ft_vs_B0": group["well_RMSE_improvement_ft_vs_B0"].median(),
            "fraction_wells_RMSE_improved_vs_B0": float((group["well_RMSE_improvement_ft_vs_B0"] > 0).mean()),
            "n_eligible_wells": len(group),
        })
    summary = pd.DataFrame(summaries)
    return primary_metrics.merge(summary, on=["regime", "model"], how="left", validate="one_to_one")


def plot_model_figures(metrics: pd.DataFrame, well_metrics: pd.DataFrame, cadence: pd.DataFrame) -> None:
    models = ["B0", "B1", "B2", "B3"]
    regimes = ["T1_TEMPORAL_OOS", "T2_SPATIOTEMPORAL_OOS"]
    pretty_regime = {"T1_TEMPORAL_OOS": "T1 temporal OOS", "T2_SPATIOTEMPORAL_OOS": "T2 spatiotemporal OOS"}
    palette = ["#7F7F7F", "#4472C4", "#70AD47", "#ED7D31"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), sharex=True)
    width = 0.18
    x = np.arange(len(regimes))
    for j, model in enumerate(models):
        subset = metrics.loc[metrics["model"].eq(model)].set_index("regime").loc[regimes]
        axes[0].bar(x + (j-1.5)*width, subset["RMSE_delta_h_ft"], width, label=model, color=palette[j])
        axes[1].bar(x + (j-1.5)*width, subset["MAE_delta_h_ft"], width, label=model, color=palette[j])
    for ax, title, unit in [(axes[0], "RMSE", "RMSE (ft)"), (axes[1], "MAE", "MAE (ft)")]:
        ax.set_xticks(x, [pretty_regime[r] for r in regimes])
        ax.set_ylabel(unit)
        ax.set_title(title)
        ax.grid(axis="y", alpha=.25)
    axes[0].legend(ncol=4, frameon=False, loc="upper left")
    fig.suptitle("GW-1A test-only no-pumping baseline error (primary ≤120-day transitions)")
    fig.text(.01, .01, "Head-level and head-change residual errors are algebraically equal conditional on observed h_prev; all metrics use TEST targets only.", fontsize=8.5)
    fig.tight_layout(rect=[0, .05, 1, .94])
    save_figure(fig, "fig03_oos_baseline_comparison")

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.7), sharey=True)
    for ax, regime in zip(axes, regimes):
        data = [well_metrics.loc[(well_metrics["regime"] == regime) & (well_metrics["model"] == model), "well_RMSE_improvement_ft_vs_B0"].dropna().to_numpy() for model in models[1:]]
        bp = ax.boxplot(data, tick_labels=models[1:], showfliers=False, patch_artist=True)
        for patch, color in zip(bp["boxes"], palette[1:]): patch.set_facecolor(color); patch.set_alpha(.75)
        ax.axhline(0, color="black", linewidth=.9)
        ax.set_title(pretty_regime[regime])
        ax.set_xlabel("Model")
        ax.grid(axis="y", alpha=.22)
    axes[0].set_ylabel("Per-well RMSE improvement vs B0 (ft; positive is better)")
    fig.suptitle("Distribution of held-out well-level skill relative to persistence")
    fig.text(.01, .01, "Boxes show median and IQR across eligible wells; whiskers use 1.5×IQR. No individual transition is treated as an independent replicate.", fontsize=8.5)
    fig.tight_layout(rect=[0, .05, 1, .94])
    save_figure(fig, "fig04_per_well_skill_distribution")

    gap_order = ["LE_45", "GT_45_LE_90", "GT_90_LE_120"]
    gap_labels = ["≤45", "46–90", "91–120"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.7), sharey=True)
    for ax, regime in zip(axes, regimes):
        for model, color in zip(models[1:], palette[1:]):
            sub = cadence.loc[(cadence["regime"] == regime) & (cadence["model"] == model)].set_index("cadence_group").reindex(gap_order)
            ax.plot(gap_labels, sub["RMSE_skill_vs_persistence"], marker="o", linewidth=1.8, color=color, label=model)
        ax.axhline(0, color="black", linewidth=.9)
        ax.set_title(pretty_regime[regime])
        ax.set_xlabel("Observation gap (days)")
        ax.grid(axis="y", alpha=.22)
    axes[0].set_ylabel("RMSE skill vs persistence (positive is better)")
    axes[0].legend(frameon=False)
    fig.suptitle("Cadence sensitivity of no-pumping predictive skill")
    fig.text(.01, .01, "Models are fit under the pre-registered ≤120-day protocol; points are TEST-only subsets by transition gap.", fontsize=8.5)
    fig.tight_layout(rect=[0, .05, 1, .94])
    save_figure(fig, "fig05_skill_by_observation_gap")


def classify_difficulty(ratio: float) -> str:
    if ratio <= 0.5:
        return "LOW"
    if ratio <= 1.0:
        return "MODERATE"
    return "HIGH"


def markdown_table(frame: pd.DataFrame) -> str:
    """Render a compact Markdown table without an optional tabulate dependency."""
    def cell(value: object) -> str:
        if pd.isna(value):
            return ""
        if isinstance(value, (float, np.floating)):
            rendered = f"{float(value):g}"
        else:
            rendered = str(value)
        return rendered.replace("|", "\\|").replace("\n", " ")

    headers = [cell(x) for x in frame.columns]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in frame.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(cell(x) for x in row) + " |")
    return "\n".join(lines)


def build_final_report(status: dict[str, object], metrics: pd.DataFrame, cadence: pd.DataFrame, bootstrap: pd.DataFrame) -> None:
    fmt = metrics.copy()
    numeric = [c for c in fmt.columns if pd.api.types.is_numeric_dtype(fmt[c])]
    fmt[numeric] = fmt[numeric].round(4)
    primary_table = markdown_table(fmt[["regime", "model", "n_transitions", "n_wells", "MAE_h_ft", "RMSE_h_ft", "bias_h_ft", "MAE_delta_h_ft", "RMSE_delta_h_ft", "sign_accuracy_delta_h", "RMSE_skill_vs_persistence", "MAE_skill_vs_persistence", "median_well_RMSE_ft", "well_RMSE_IQR_ft", "fraction_wells_RMSE_improved_vs_B0"]])
    bootstrap_display = markdown_table(bootstrap.round(4))
    cadence_display = markdown_table(cadence[["regime", "cadence_group", "model", "n_transitions", "n_wells", "RMSE_delta_h_ft", "MAE_delta_h_ft", "RMSE_skill_vs_persistence", "MAE_skill_vs_persistence"]].round(4))
    split = status["temporal_split"]
    folds = markdown_table(pd.read_csv(PROTOCOL / "SPATIAL_FOLD_SUMMARY.csv").round(3))
    deps = pd.read_csv(PROVENANCE / "GW1A_DEPENDENCY_MANIFEST.csv")
    dep_table = markdown_table(deps[["logical_input", "path", "worktree_sha256", "tracked_at_frozen_commit", "worktree_matches_frozen"]])
    report = f"""# Final OCWD GW-1A report

## A. Repository/preflight state

- Repository: `{REPO_ROOT}`
- Branch / HEAD: `{status['repository']['branch']}` / `{status['repository']['HEAD']}`
- Frozen feasibility baseline: `{FROZEN_COMMIT}`; package-integrity check **PASS**.
- Task-start status: ` m Data-center-PUE-prediction-tool`; no pre-existing path was modified.
- Python: `{status['repository']['python_executable']}` ({status['repository']['python_version_short']}).
- Submodule inspection remains unavailable because Git reports no `.gitmodules` mapping for the existing PUE path.

## B. Dependency hashes

{dep_table}

Ignored raw/derived feasibility artifacts are pinned by the committed package hash manifest; tracked artifacts additionally match their exact frozen Git blobs. The source package tree was rechecked after GW-1A and remained byte-identical.

## C. Primary dense window

Coverage selection independently reproduced **{status['primary_window']['start']} through {status['primary_window']['end']} ({status['primary_window']['n_months']} consecutive months)** with at least {status['primary_window']['minimum_monthly_wells']} wells observed in every month. Dates used observation availability only, never predictive performance.

## D. Data representations

- Monthly matrix: {status['samples']['monthly_wells']} wells × {status['samples']['monthly_months']} months; {status['samples']['monthly_observed_cells']} observed cells and {status['samples']['monthly_missing_cells']} missing cells retained.
- Usable source observations in window: {status['samples']['usable_head_observations']}.
- Consecutive unique-time transitions: {status['samples']['all_transitions']}; ≤45: {status['samples']['transitions_le_45']}, ≤90: {status['samples']['transitions_le_90']}, ≤120: {status['samples']['transitions_le_120']}, ≤180: {status['samples']['transitions_le_180']}.
- Exact well/timestamp duplicates were collapsed by median solely to avoid fabricating an order at zero elapsed time. No target or missing head was interpolated.
- USGS daily discharge is complete for all required calendar days. Fifty-eight ≤120-day transitions contained no complete calendar day between a same-day origin and target (55 TRAIN, 3 VALIDATION, 0 TEST); the common B0–B3 fitting support excludes them rather than imputing an interval-flow value.

## E. Temporal split

- TRAIN: {split['TRAIN']['start']} through {split['TRAIN']['end']} ({split['TRAIN']['n_months']} months)
- VALIDATION: {split['VALIDATION']['start']} through {split['VALIDATION']['end']} ({split['VALIDATION']['n_months']} months)
- TEST: {split['TEST']['start']} through {split['TEST']['end']} ({split['TEST']['n_months']} months)

Validation was not used because ordinary least squares required no tuning. TEST data never entered fitting or scaling.

## F. Spatial folds

{folds}

Folds are deterministic KMeans clusters in EPSG:26911 from coordinates only (`k=5`, `random_state=20260904`, `n_init=50`), relabeled west-to-east. Heads, screens, forcing, residuals, and skill were excluded.

## G. Independent-agency holdout

Every one of the {status['samples']['usable_head_observations']} usable source observations in the frozen primary window is classified `OCWD_ORIGIN_REPUBLISHED_BY_DWR`. There are zero within-window independent-agency transitions, so T3 is **NOT FEASIBLE IN THE FROZEN COHORT** and is not forced through temporal extrapolation or provenance mixing.

## H. Exact B0–B3 specifications

- **B0:** `h_hat_target = h_prev`; no fitting.
- **B1:** pooled OLS for `delta_h` from gap days, target-day seasonal sine/cosine, and linear target-time trend.
- **B2:** pooled OLS for `h_target` from `h_prev` plus the B1 inputs.
- **B3:** B2 plus `log1p` mean USGS 11074000 discharge on origin-date through day-before-target and `log1p` mean discharge over the 30 complete days before target. No target-day or later flow enters a feature.

B3 is public background/boundary hydrology, **not managed recharge**. A hydrologic feature is missing if any required daily discharge is missing; no discharge is imputed. All feature centering/scaling is learned from TRAIN only. No hyperparameter search or regularization was used.

## I–J. T1 temporal and T2 spatiotemporal TEST results

Errors are feet. Bias is prediction minus observation. Positive skill means lower error than persistence. Head and change residual errors are algebraically identical conditional on the observed origin head; change metrics prevent a misleading interpretation based on between-well level heterogeneity. R² is retained only in machine-readable output as secondary.

{primary_table}

## K. T3 independent-source result

T3 is unavailable within the frozen interval (zero eligible independent-agency transitions). Independent observations outside the interval remain preserved and were not repurposed.

## L. Cadence robustness

{cadence_display}

Threshold sensitivities at ≤90, ≤120, and ≤180 days are in `outputs/tables/SENSITIVITY_METRICS.csv`; each threshold refits the same declared OLS ladder on TRAIN only. Gap-band results above subset the primary ≤120-day TEST predictions.

## M–N. Strongest baseline and public hydrologic increment

- `STRONGEST_NO_PUMPING_BASELINE = {status['STRONGEST_NO_PUMPING_BASELINE']}` under the predeclared mean T1/T2 RMSE-skill ranking.
- `PUBLIC_HYDROLOGIC_INCREMENTAL_SKILL = {status['PUBLIC_HYDROLOGIC_INCREMENTAL_SKILL']}` for B3 relative to B2.
- `TEMPORAL_PREDICTION_DIFFICULTY = {status['TEMPORAL_PREDICTION_DIFFICULTY']}` and `SPATIAL_GENERALIZATION_DIFFICULTY = {status['SPATIAL_GENERALIZATION_DIFFICULTY']}` under the frozen RMSE-to-test-change-IQR rule.

Well-bootstrap differences (positive means the comparison model lowers error):

{bootstrap_display}

## O–P. Frozen GW-1B and placebo protocol

GW-1B retains B0–B3, then adds B4 observed managed recharge/injection, B5 observed pumping, B6 spatially structured forcing, and B7 the smallest physically constrained groundwater network. `B5-B4` tests incremental pumping information; `B7-B5` separately tests network structure. The temporal placebo permutes pumping across years within calendar month. The spatial placebo permutes pumping-well identities only within authoritative future aquifer/layer strata. Neither is run now.

## Q. Reserved external validation

The 35-row tracer registry and five MBI start events remain outside features, fitting, tuning, fold construction, and ranking. They are reserved for post-freeze physical validation.

## R. Tests

The guard suite checks frozen source integrity, input hashes, non-imputation, split isolation, coordinate-only folds, independent-source exclusion, hydrologic time direction, forcing labels, reserved-validation isolation, absence of pumping/network/GNN/MODFLOW fitting, and OOS-only ranking. Exact execution result is recorded after the final test run in the handoff.

## S. Scientific conclusion

Without pumping, `{status['STRONGEST_NO_PUMPING_BASELINE']}` is the strongest transparent held-out baseline under the frozen joint T1/T2 ranking. Public Prado discharge contributes `{status['PUBLIC_HYDROLOGIC_INCREMENTAL_SKILL'].lower()}` incremental support relative to head history under the preregistered rule. These results quantify conditional one-step response predictability, not an operational forecast and not pumping causality. Because observed WRMS pumping and managed-recharge panels are absent, pumping-response coefficients, source attribution, and spatial/network added value remain unidentified.

Future evidence that pumping matters requires robust B5-over-B4 held-out improvement, a well-bootstrap interval excluding zero, positive median well-level improvement, broad well support, and superiority to the season-preserving temporal placebo. Future evidence that network structure matters separately requires B7 to outperform B5 and the spatial pumping placebo after authoritative well/layer crosswalks exist.

## T. Exact next action

`READY_FOR_GW1B = NO_UNTIL_WRMS`. When the requested WRMS export arrives, hash and schema-audit it first; map well/facility/layer identities only from authoritative crosswalks; then reuse the immutable GW-1A months and spatial folds and run the frozen B4→B7 ladder and placebos without consulting tracer or MBI responses until the groundwater model is frozen.
"""
    (OUTPUTS / "FINAL_GW1A_REPORT.md").write_text(report, encoding="utf-8")


def write_output_hashes() -> pd.DataFrame:
    destination_csv = PROVENANCE / "GW1A_OUTPUT_HASHES.csv"
    destination_json = PROVENANCE / "GW1A_OUTPUT_HASHES.json"
    excluded = {destination_csv.resolve(), destination_json.resolve()}
    rows = []
    for path in sorted(p for p in MODULE_ROOT.rglob("*") if p.is_file() and p.resolve() not in excluded and "__pycache__" not in p.parts):
        rows.append({"path": path.relative_to(MODULE_ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    frame = pd.DataFrame(rows)
    frame.to_csv(destination_csv, index=False)
    write_json(destination_json, frame.to_dict(orient="records"))
    return frame


def run_benchmarks() -> dict[str, object]:
    ensure_directories()
    freeze = verify_protocol_freeze()
    transitions = pd.read_parquet(DATA_DERIVED / "HEAD_TRANSITIONS.parquet")
    for col in ["t_prev", "t_target", "target_month", "interval_max_source_date", "antecedent_30d_max_source_date"]:
        transitions[col] = pd.to_datetime(transitions[col])

    all_predictions = []
    all_audits = []
    all_fit_samples = []
    sensitivity_metrics = []
    primary_predictions = None
    for threshold in [90, 120, 180]:
        pred, audit, fit_samples = run_prediction_set(transitions, threshold)
        all_predictions.append(pred)
        all_audits.append(audit)
        all_fit_samples.append(fit_samples)
        aggregated = aggregate_metrics(pred, ["regime", "model"])
        aggregated.insert(2, "gap_threshold_days", threshold)
        sensitivity_metrics.append(aggregated)
        if threshold == 120:
            primary_predictions = pred
    assert primary_predictions is not None
    primary_predictions.to_parquet(DATA_DERIVED / "PRIMARY_TEST_PREDICTIONS.parquet", index=False)
    pd.concat(all_predictions, ignore_index=True).to_parquet(DATA_DERIVED / "ALL_SENSITIVITY_TEST_PREDICTIONS.parquet", index=False)
    pd.concat(all_audits, ignore_index=True).to_csv(TABLES / "FITTED_MODEL_AUDIT.csv", index=False)
    pd.concat(all_fit_samples, ignore_index=True).to_parquet(DATA_DERIVED / "FIT_SAMPLE_LEDGER.parquet", index=False)
    sensitivity = pd.concat(sensitivity_metrics, ignore_index=True)
    sensitivity.to_csv(TABLES / "SENSITIVITY_METRICS.csv", index=False, float_format="%.10g")

    primary_metrics = aggregate_metrics(primary_predictions, ["regime", "model"])
    well_metrics = well_level_metrics(primary_predictions)
    primary_metrics = summarize_well_distribution(primary_metrics, well_metrics)
    primary_metrics.to_csv(TABLES / "PRIMARY_METRICS.csv", index=False, float_format="%.10g")
    well_metrics.to_csv(TABLES / "WELL_LEVEL_METRICS.csv", index=False, float_format="%.10g")
    fold_metrics = aggregate_metrics(primary_predictions.loc[primary_predictions["regime"].eq("T2_SPATIOTEMPORAL_OOS")], ["regime", "held_out_spatial_fold", "model"])
    fold_metrics.to_csv(TABLES / "SPATIAL_FOLD_METRICS.csv", index=False, float_format="%.10g")

    cadence_rows = []
    for gap_group in ["LE_45", "GT_45_LE_90", "GT_90_LE_120"]:
        subset = primary_predictions.loc[primary_predictions["gap_group_primary"].eq(gap_group)]
        m = aggregate_metrics(subset, ["regime", "model"])
        m.insert(1, "cadence_group", gap_group)
        cadence_rows.append(m)
    cadence = pd.concat(cadence_rows, ignore_index=True)
    cadence.to_csv(TABLES / "CADENCE_ROBUSTNESS_METRICS.csv", index=False, float_format="%.10g")

    boot_rows = []
    offset = 0
    for regime in ["T1_TEMPORAL_OOS", "T2_SPATIOTEMPORAL_OOS"]:
        for model in ["B1", "B2", "B3"]:
            offset += 1
            boot_rows.append(bootstrap_difference(primary_predictions, model, "B0", regime, offset))
    bootstrap = pd.DataFrame(boot_rows)
    bootstrap.to_csv(TABLES / "BOOTSTRAP_DIFFERENCES_VS_PERSISTENCE.csv", index=False, float_format="%.10g")
    b3_b2 = pd.DataFrame([
        bootstrap_difference(primary_predictions, "B3", "B2", "T1_TEMPORAL_OOS", 101),
        bootstrap_difference(primary_predictions, "B3", "B2", "T2_SPATIOTEMPORAL_OOS", 102),
    ])
    b3_b2.to_csv(TABLES / "BOOTSTRAP_B3_VS_B2.csv", index=False, float_format="%.10g")

    ranking = primary_metrics.pivot(index="model", columns="regime", values=["RMSE_skill_vs_persistence", "MAE_skill_vs_persistence"])
    rank_rows = []
    for model in ["B0", "B1", "B2", "B3"]:
        rank_rows.append({
            "model": model,
            "mean_T1_T2_RMSE_skill": float(ranking.loc[model, "RMSE_skill_vs_persistence"].mean()),
            "mean_T1_T2_MAE_skill": float(ranking.loc[model, "MAE_skill_vs_persistence"].mean()),
            "ranking_data_split": "TEST_ONLY",
        })
    ranking_frame = pd.DataFrame(rank_rows).sort_values(["mean_T1_T2_RMSE_skill", "mean_T1_T2_MAE_skill"], ascending=False).reset_index(drop=True)
    ranking_frame.to_csv(TABLES / "OOS_MODEL_RANKING.csv", index=False, float_format="%.10g")
    strongest = str(ranking_frame.iloc[0]["model"])

    well_b3 = well_metrics.loc[well_metrics["model"].eq("B3"), ["regime", "site_code", "RMSE_delta_h_ft", "MAE_delta_h_ft"]]
    well_b2 = well_metrics.loc[well_metrics["model"].eq("B2"), ["regime", "site_code", "RMSE_delta_h_ft", "MAE_delta_h_ft"]]
    wb = well_b3.merge(well_b2, on=["regime", "site_code"], suffixes=("_B3", "_B2"), validate="one_to_one")
    wb["RMSE_improvement_B3_vs_B2"] = wb["RMSE_delta_h_ft_B2"] - wb["RMSE_delta_h_ft_B3"]
    wb["MAE_improvement_B3_vs_B2"] = wb["MAE_delta_h_ft_B2"] - wb["MAE_delta_h_ft_B3"]
    hydrology_support = []
    strong = True
    any_supported = False
    for regime in ["T1_TEMPORAL_OOS", "T2_SPATIOTEMPORAL_OOS"]:
        brow = b3_b2.loc[b3_b2["regime"].eq(regime)].iloc[0]
        wg = wb.loc[wb["regime"].eq(regime)]
        median_imp = float(wg["RMSE_improvement_B3_vs_B2"].median())
        frac_imp = float((wg["RMSE_improvement_B3_vs_B2"] > 0).mean())
        this_strong = brow["MAE_improvement_ci95_low_ft"] > 0 and brow["RMSE_improvement_ci95_low_ft"] > 0 and median_imp > 0 and frac_imp > .5
        strong = strong and bool(this_strong)
        aggregate_positive = brow["MAE_improvement_ft"] > 0 and brow["RMSE_improvement_ft"] > 0
        any_supported = any_supported or bool(aggregate_positive and (median_imp > 0 or frac_imp > .5))
        hydrology_support.append({"regime": regime, "median_well_RMSE_improvement_ft": median_imp, "fraction_wells_RMSE_improved": frac_imp, "strong_rule_met": bool(this_strong)})
    if strong:
        hydro_status = "STRONG"
    elif any_supported:
        hydro_status = "PARTIAL"
    else:
        hydro_status = "NONE"
    pd.DataFrame(hydrology_support).to_csv(TABLES / "PUBLIC_HYDROLOGY_INCREMENT_SUMMARY.csv", index=False, float_format="%.10g")

    difficulty = {}
    for regime, label in [("T1_TEMPORAL_OOS", "TEMPORAL_PREDICTION_DIFFICULTY"), ("T2_SPATIOTEMPORAL_OOS", "SPATIAL_GENERALIZATION_DIFFICULTY")]:
        row = primary_metrics.loc[(primary_metrics["regime"].eq(regime)) & (primary_metrics["model"].eq(strongest))].iloc[0]
        ratio = float(row["RMSE_delta_h_ft"] / row["delta_h_IQR_ft"]) if row["delta_h_IQR_ft"] > 0 else math.inf
        difficulty[label] = {"classification": classify_difficulty(ratio), "RMSE_to_delta_IQR_ratio": ratio, "model": strongest}

    representation = json.loads((COHORTS / "REPRESENTATION_SUMMARY.json").read_text())
    primary_window = json.loads((COHORTS / "PRIMARY_WINDOW.json").read_text())
    split = json.loads((PROTOCOL / "TEMPORAL_SPLIT.json").read_text())
    preflight = json.loads((PROVENANCE / "REPOSITORY_PREFLIGHT.json").read_text())
    source_after = verify_frozen_feasibility()
    source_before = json.loads((PROVENANCE / "SOURCE_FEASIBILITY_PACKAGE_INTEGRITY.json").read_text())
    source_unchanged = source_before["current_tree_sha256"] == source_after["current_tree_sha256"] and source_before["files"] == source_after["files"]
    if not source_unchanged:
        raise RuntimeError("Frozen feasibility package changed during GW-1A")
    primary_ocwd = transitions.loc[transitions["gap_le_120_days"] & transitions["transition_independence_class"].eq(OCWD_ORIGIN)]
    hydro_incomplete_by_split = primary_ocwd.loc[~primary_ocwd["hydrologic_feature_complete"], "temporal_split"].value_counts().to_dict()
    status = {
        "GW1A_STATUS": "PASS",
        "STRONGEST_NO_PUMPING_BASELINE": strongest,
        "PUBLIC_HYDROLOGIC_INCREMENTAL_SKILL": hydro_status,
        "TEMPORAL_PREDICTION_DIFFICULTY": difficulty["TEMPORAL_PREDICTION_DIFFICULTY"]["classification"],
        "SPATIAL_GENERALIZATION_DIFFICULTY": difficulty["SPATIAL_GENERALIZATION_DIFFICULTY"]["classification"],
        "READY_FOR_GW1B": "NO_UNTIL_WRMS",
        "scope": "PRE_REGISTERED_NO_PUMPING_NULL_PREDICTIVE_BENCHMARK",
        "repository": {"branch": preflight["branch"], "HEAD": preflight["HEAD"], "python_executable": preflight["python_executable"], "python_version_short": preflight["python_version"].split(" |")[0]},
        "frozen_feasibility": {"commit": FROZEN_COMMIT, "source_package_byte_identical_before_after": source_unchanged, "tree_sha256": source_after["current_tree_sha256"], "package_manifest_sha256": source_after["package_manifest_sha256"]},
        "protocol_freeze_sha256": sha256_file(PROTOCOL / "PROTOCOL_FREEZE.json"),
        "primary_window": {"start": primary_window["primary_start_month"][:7], "end": primary_window["primary_end_month"][:7], "n_months": primary_window["n_consecutive_months"], "minimum_monthly_wells": primary_window["minimum_monthly_wells"]},
        "temporal_split": split,
        "samples": {
            "monthly_wells": representation["monthly_matrix"]["n_wells"], "monthly_months": representation["monthly_matrix"]["n_months"],
            "monthly_observed_cells": representation["monthly_matrix"]["n_observed_cells"], "monthly_missing_cells": representation["monthly_matrix"]["n_missing_cells_retained"],
            "usable_head_observations": representation["monthly_matrix"]["n_input_usable_observations"],
            "all_transitions": representation["transitions"]["n_all_consecutive_unique_timestamp_transitions"],
            "transitions_le_45": representation["transitions"]["n_le_45"], "transitions_le_90": representation["transitions"]["n_le_90"],
            "transitions_le_120": representation["transitions"]["n_le_120"], "transitions_le_180": representation["transitions"]["n_le_180"],
            "hydrologic_feature_complete_le_120": int(primary_ocwd["hydrologic_feature_complete"].sum()),
            "hydrologic_feature_incomplete_le_120": int((~primary_ocwd["hydrologic_feature_complete"]).sum()),
            "hydrologic_feature_incomplete_by_split": {str(k): int(v) for k, v in hydro_incomplete_by_split.items()},
            "primary_test_T1": int(primary_predictions.loc[(primary_predictions["regime"].eq("T1_TEMPORAL_OOS")) & (primary_predictions["model"].eq("B0"))].shape[0]),
            "primary_test_T2": int(primary_predictions.loc[(primary_predictions["regime"].eq("T2_SPATIOTEMPORAL_OOS")) & (primary_predictions["model"].eq("B0"))].shape[0]),
            "independent_agency_primary_transitions": representation["transitions"]["n_independent_le_120"],
        },
        "evaluation": {"all_main_metrics_split": "TEST", "T1": "TEMPORAL_OOS", "T2": "SPATIOTEMPORAL_OOS", "T3": "NOT_FEASIBLE_ZERO_WITHIN_WINDOW_INDEPENDENT_TRANSITIONS", "bootstrap_unit": "well", "bootstrap_resamples": 1000, "bootstrap_seed_base": SEED},
        "difficulty_details": difficulty,
        "public_hydrology_details": hydrology_support,
        "scientific_identification": {
            "predictable_without_pumping": f"Measured by OOS B0-B3; strongest is {strongest}.",
            "pumping_response": "UNIDENTIFIED_WRMS_PUMPING_ABSENT",
            "managed_recharge_increment": "UNIDENTIFIED_WRMS_RECHARGE_ABSENT",
            "network_added_value": "UNIDENTIFIED_NO_NETWORK_ESTIMATED",
            "B3_role": "PUBLIC_BACKGROUND_HYDROLOGY_NOT_MANAGED_RECHARGE",
            "operational_forecast": False,
        },
        "GW1B_evidence_rules": {
            "pumping_matters": "B5 beats B4 robustly OOS; uncertainty excludes zero; median well improvement positive; broad support; real pumping beats season-preserving temporal placebo.",
            "network_structure_matters": "B7 separately beats B5 and spatial pumping placebo after authoritative well/layer crosswalks; pumping value alone is insufficient.",
        },
        "next_action": "When WRMS arrives, hash/schema-audit it, build only authoritative well/facility/layer crosswalks, reuse frozen GW1A holdouts, and execute preregistered B4-B7 and placebo comparisons while tracer/MBI remain reserved.",
    }
    write_json(OUTPUTS / "FINAL_GW1A_STATUS.json", status)
    plot_model_figures(primary_metrics, well_metrics, cadence)
    build_final_report(status, primary_metrics, cadence, pd.concat([bootstrap, b3_b2], ignore_index=True))
    write_json(PROTOCOL / "VALIDATION_AND_TEST_NONUSE_AUDIT.json", {
        "hyperparameter_search": "NONE", "regularization": "NONE", "validation_used_for_fitting_scaling_or_ranking": False,
        "test_used_for_fitting_scaling_or_tuning": False, "test_used_for_final_OOS_metrics_and_reporting_only": True,
        "model_ranking_source": "T1 and T2 TEST RMSE skill, tie-broken by TEST MAE skill; never in-sample",
    })
    write_output_hashes()
    return status
