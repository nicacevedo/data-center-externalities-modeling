#!/usr/bin/env python3
"""Reproduce frozen v2 guards and final v3 in a temporary da7fd6f worktree."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


FC3 = Path(__file__).resolve().parents[1]
REPO = FC3.parent
OUT = FC3 / "outputs" / "reproducibility"
FROZEN = "da7fd6f55e1aef5216ceabe80bfc3e31265f7927"
DC_PYTHON = os.environ.get("FC3_PYTHON", "/home/nacevedo/.conda/envs/dc_externalities/bin/python")
MASANET_PYTHON = os.environ.get("FC3_MASANET_PYTHON", "/home/nacevedo/.conda/envs/masanet_lei/bin/python")
UPSTREAM_URL = "https://github.com/nuoaleon/Data-Center-Water-footprint.git"
UPSTREAM_COMMIT = "2cc53bee89b0a61bdad10c02b4d170d7f673e2dc"

DOWNLOADS = [
    ("Meta_Forest_City_North_Carolina_v1/data/raw/weather/isd-history.csv", "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv", "1994747ab4af1b97e63adb434b4d0d022f2daee76f0c144ea9ab46be2d906604"),
    ("Meta_Forest_City_North_Carolina_v1/data/raw/weather/72314453890_2012.csv", "https://www.ncei.noaa.gov/data/global-hourly/access/2012/72314453890.csv", "e4cbfbbfc133cccc1c595b10859546880d169013aec80939bf3728d1bf62ad7f"),
    ("Meta_Forest_City_North_Carolina_v1/data/raw/weather/72027763843_2012.csv", "https://www.ncei.noaa.gov/data/global-hourly/access/2012/72027763843.csv", "adc544dfbb31869ffe11ef3788b1763756d559f021966ec22363c60a4c944903"),
    ("Meta_Forest_City_North_Carolina_v1/data/raw/weather/72312003870_2012.csv", "https://www.ncei.noaa.gov/data/global-hourly/access/2012/72312003870.csv", "d4305277f146bfd81096950fd54f783e43a14767e9e1deec4533e4b7d0907b3a"),
    ("Meta_Prineville_Oregon_v3/data/raw/noaa/72692024230_2012.csv", "https://www.ncei.noaa.gov/data/global-hourly/access/2012/72692024230.csv", "29853f7afa500a5dc8a946cfdc88df9e9f93a459af41c22a27fa91aefafa6fa2"),
]

MATERIAL_OUTPUTS = [
    "outputs/regimes/V2_REPRODUCTION.json",
    "outputs/regimes/JJA_STATION_REGIME_SHARES.csv",
    "outputs/regimes/STATION_ROBUSTNESS_RANGES.csv",
    "outputs/regimes/STATION_ROBUSTNESS.json",
    "outputs/cross_site/COMMON_PERIOD_CLIMATE.csv",
    "outputs/cross_site/WEATHER_CONTROLLER_2x2.csv",
    "outputs/cross_site/WEATHER_CONTROLLER_2x2.json",
    "outputs/cross_site/WEATHER_CONTROLLER_2x2_CONTRASTS.csv",
    "outputs/cross_site/WEATHER_CONTROLLER_2x2_CONTRASTS.json",
    "outputs/annual/CAMPUS_ANNUAL_COMPARISON.csv",
    "outputs/annual/CAMPUS_ANNUAL_COMPARISON.json",
    "outputs/masanet/MASANET_TRANSFER.json",
    "outputs/masanet/MASANET_CLIMATE_BINS.csv",
    "outputs/masanet/MASANET_HOURLY_KFQD.csv",
    "outputs/masanet/MASANET_HOURLY_KRDM.csv",
    "outputs/masanet/MASANET_HOURLY_KEHO.csv",
    "outputs/masanet/MASANET_HOURLY_KGSP.csv",
    "outputs/esif/ESIF_TRANSFER.json",
    "outputs/esif/ESIF_TRANSFER_SUMMARY.csv",
    "outputs/esif/ESIF_TRANSFER_KFQD.csv",
    "outputs/esif/ESIF_TRANSFER_KRDM.csv",
    "outputs/esif/ESIF_TRANSFER_KEHO.csv",
    "outputs/esif/ESIF_TRANSFER_KGSP.csv",
    "outputs/identification/IDENTIFICATION_LEDGER.csv",
    "outputs/acquisition/DATA_VALUE_MATRIX.csv",
    "outputs/FINAL_CLAIMS_LEDGER.json",
    "outputs/figures/fig01_same_period_climate_regime.png",
    "outputs/figures/fig02_weather_controller_2x2.png",
    "outputs/figures/fig03_masanet_transfer.png",
    "outputs/figures/fig04_esif_overhead_transfer.png",
    "outputs/figures/fig05_identification.png",
    "outputs/figures/fig06_data_value_matrix.png",
]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def run(args: list[str], cwd: Path, env: dict | None = None, timeout: int = 1800) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout)


def csv_numerically_equal(a: Path, b: Path) -> tuple[bool, float]:
    try:
        left, right = pd.read_csv(a), pd.read_csv(b)
    except Exception:
        return False, float("nan")
    if left.shape != right.shape or list(left.columns) != list(right.columns):
        return False, float("inf")
    max_diff = 0.0
    for col in left.columns:
        if pd.api.types.is_numeric_dtype(left[col]) and pd.api.types.is_numeric_dtype(right[col]):
            x, y = left[col].to_numpy(float), right[col].to_numpy(float)
            finite = np.isfinite(x) & np.isfinite(y)
            if finite.any():
                max_diff = max(max_diff, float(np.max(np.abs(x[finite] - y[finite]))))
            if not np.allclose(x, y, rtol=0, atol=1e-12, equal_nan=True):
                return False, max_diff
        elif not left[col].fillna("<NA>").astype(str).equals(right[col].fillna("<NA>").astype(str)):
            return False, max_diff
    return True, max_diff


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    temp_parent = Path(tempfile.mkdtemp(prefix="forest_city_v3_cleanroom_", dir="/tmp"))
    worktree = temp_parent / "checkout"
    commands: list[dict] = []
    raw_hashes: list[dict] = []
    v2_result = None
    v3_result = None
    compare_rows: list[dict] = []
    cleanup_result = "NOT_RUN"
    try:
        cmd = ["git", "worktree", "add", "--detach", str(worktree), FROZEN]
        proc = run(cmd, REPO)
        commands.append({"command": cmd, "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
        if proc.returncode:
            raise RuntimeError(proc.stderr)

        shutil.copytree(FC3, worktree / FC3.name, dirs_exist_ok=True)
        for rel, url, expected in DOWNLOADS:
            dest = worktree / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            request = urllib.request.Request(url, headers={"User-Agent": "Forest-City-v3-cleanroom/1.0"})
            with urllib.request.urlopen(request, timeout=180) as response:
                dest.write_bytes(response.read())
            actual = sha(dest)
            raw_hashes.append({"path": rel, "url": url, "sha256": actual, "expected_sha256": expected, "match": actual == expected})
            if actual != expected:
                raise RuntimeError(f"download hash mismatch for {rel}: {actual}")

        upstream_parent = worktree / "other_sources/masanet/external"
        upstream_parent.mkdir(parents=True, exist_ok=True)
        upstream = upstream_parent / "Data-Center-Water-footprint"
        clone = run(["git", "clone", "--quiet", UPSTREAM_URL, str(upstream)], worktree, timeout=600)
        commands.append({"command": ["git", "clone", "--quiet", UPSTREAM_URL, str(upstream)], "returncode": clone.returncode, "stderr": clone.stderr})
        if clone.returncode:
            raise RuntimeError(clone.stderr)
        checkout = run(["git", "checkout", "--detach", UPSTREAM_COMMIT], upstream)
        commands.append({"command": ["git", "checkout", "--detach", UPSTREAM_COMMIT], "returncode": checkout.returncode, "stderr": checkout.stderr})
        if checkout.returncode:
            raise RuntimeError(checkout.stderr)

        env = os.environ.copy()
        env.update({"PYTHONDONTWRITEBYTECODE": "1", "MPLCONFIGDIR": str(temp_parent / "mpl"), "FC3_PYTHON": DC_PYTHON, "FC3_MASANET_PYTHON": MASANET_PYTHON})
        # Recreate the ignored KRDM product from the one hash-pinned 2012 raw
        # file before running the committed v2 pipeline.  With only that year
        # present, the frozen preprocessor cannot silently consume cached years.
        prn = worktree / "Meta_Prineville_Oregon_v3"
        prn_preprocess_cmd = [DC_PYTHON, "src/prepare_weather.py"]
        prn_preprocess = run(prn_preprocess_cmd, prn, env=env, timeout=900)
        commands.append({"command": prn_preprocess_cmd, "cwd": str(prn.relative_to(worktree)), "returncode": prn_preprocess.returncode, "stdout": prn_preprocess.stdout, "stderr": prn_preprocess.stderr})
        if prn_preprocess.returncode:
            raise RuntimeError("frozen KRDM preprocessing failed: " + prn_preprocess.stderr[-4000:])

        # Run the committed v2 pipeline itself.  This deterministically creates
        # both ignored files exercised by its guards, rather than copying stale
        # development artifacts into the clean checkout.  Its unrelated
        # municipal_update is context-only and consumes a mutable, ignored v1
        # web scrape; it has no downstream return value and is skipped explicitly.
        v2 = worktree / "Meta_Forest_City_North_Carolina_v2"
        v2_pipeline_code = (
            "import importlib.util; from pathlib import Path; "
            "p=Path('scripts/run_pipeline.py'); "
            "s=importlib.util.spec_from_file_location('fc2_pipeline', p); "
            "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
            "m.municipal_update=lambda canon: None; m.main()"
        )
        v2_pipeline_cmd = [DC_PYTHON, "-c", v2_pipeline_code]
        v2_pipeline = run(v2_pipeline_cmd, v2, env=env, timeout=1800)
        commands.append({"command": v2_pipeline_cmd, "cwd": str(v2.relative_to(worktree)), "returncode": v2_pipeline.returncode, "stdout": v2_pipeline.stdout, "stderr": v2_pipeline.stderr})
        if v2_pipeline.returncode:
            raise RuntimeError("committed v2 preprocessing/replay failed: " + v2_pipeline.stderr[-4000:])

        canonical_dst = v2 / "data/processed/FOREST_CITY_META_ANNUAL_CANONICAL.csv"
        hours_dst = v2 / "outputs/weather_robustness/FULL_JJA_KFQD_HOURS.csv"
        v2_cmd = [DC_PYTHON, "-m", "pytest", "tests/test_v2_guards.py", "-q"]
        v2_result = run(v2_cmd, v2, env=env, timeout=900)
        commands.append({"command": v2_cmd, "cwd": str(v2.relative_to(worktree)), "returncode": v2_result.returncode, "stdout": v2_result.stdout, "stderr": v2_result.stderr})

        clean_fc3 = worktree / FC3.name
        v3_cmd = [DC_PYTHON, "scripts/run_v3_pipeline.py"]
        v3_result = run(v3_cmd, clean_fc3, env=env, timeout=1800)
        commands.append({"command": v3_cmd, "cwd": FC3.name, "returncode": v3_result.returncode, "stdout": v3_result.stdout, "stderr": v3_result.stderr})
        if v3_result.returncode:
            raise RuntimeError("clean v3 replay failed: " + v3_result.stderr[-4000:])
        test_cmd = [DC_PYTHON, "-m", "pytest", "tests/test_v3_guards.py", "-q"]
        v3_tests = run(test_cmd, clean_fc3, env=env, timeout=900)
        commands.append({"command": test_cmd, "cwd": FC3.name, "returncode": v3_tests.returncode, "stdout": v3_tests.stdout, "stderr": v3_tests.stderr})

        for rel in MATERIAL_OUTPUTS:
            dev = FC3 / rel
            clean = clean_fc3 / rel
            exact = dev.exists() and clean.exists() and sha(dev) == sha(clean)
            numerical = exact
            max_abs_diff = 0.0 if exact else float("nan")
            if not exact and dev.suffix == ".csv" and dev.exists() and clean.exists():
                numerical, max_abs_diff = csv_numerically_equal(dev, clean)
            compare_rows.append({
                "relative_path": rel,
                "development_sha256": sha(dev) if dev.exists() else "",
                "cleanroom_sha256": sha(clean) if clean.exists() else "",
                "exact_hash_match": exact,
                "numerical_tolerance_pass": numerical,
                "max_abs_numeric_difference": max_abs_diff,
                "tolerance": "exact bytes; CSV fallback atol=1e-12",
            })

        v2_pass = bool(v2_result.returncode == 0 and "passed" in v2_result.stdout)
        v3_tests_pass = bool(v3_tests.returncode == 0)
        outputs_pass = all(row["exact_hash_match"] or row["numerical_tolerance_pass"] for row in compare_rows)
        status = "PASS" if v2_pass and v3_tests_pass and outputs_pass else "FAIL"
        with (OUT / "CLEANROOM_OUTPUT_HASHES.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(compare_rows[0]))
            writer.writeheader(); writer.writerows(compare_rows)
        payload = {
            "CLEANROOM_FINAL_STATUS": status,
            "CLEAN_V2_REPRODUCIBILITY": "PASS" if v2_pass else "FAIL",
            "frozen_dependency_commit": FROZEN,
            "clean_checkout_HEAD": FROZEN,
            "generated_inputs": raw_hashes + [
                {"path": str((prn / "data/processed/weather_krdm_hourly.csv").relative_to(worktree)), "sha256": sha(prn / "data/processed/weather_krdm_hourly.csv"), "source": "frozen src/prepare_weather.py + hash-pinned 2012 KRDM raw"},
                {"path": str(canonical_dst.relative_to(worktree)), "sha256": sha(canonical_dst), "source": "committed v2 scripts/run_pipeline.py"},
                {"path": str(hours_dst.relative_to(worktree)), "sha256": sha(hours_dst), "source": "committed v2 scripts/run_pipeline.py"},
            ],
            "environment": {"dc_python": DC_PYTHON, "masanet_python": MASANET_PYTHON, "utc": datetime.now(timezone.utc).isoformat()},
            "commands": commands,
            "v2_test_summary": v2_result.stdout.strip(),
            "v3_test_summary": v3_tests.stdout.strip(),
            "material_outputs_match": outputs_pass,
            "v2_pipeline_scope": "committed pipeline with context-only municipal_update explicitly skipped because its ignored mutable web scrape is not a v3 scientific input",
            "n_material_outputs": len(compare_rows),
            "n_exact_hash_matches": sum(row["exact_hash_match"] for row in compare_rows),
            "comparison_csv": "CLEANROOM_OUTPUT_HASHES.csv",
            "temporary_worktree_removed_after_audit": True,
            "prior_attempt": "One earlier clean-room replay was manually interrupted after anomalous sequential Masanet stalling; no result was accepted.",
        }
        (OUT / "CLEANROOM_FINAL_STATUS.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        (OUT / "CLEAN_V2_REPRODUCIBILITY.json").write_text(json.dumps({
            "CLEAN_V2_REPRODUCIBILITY": "PASS" if v2_pass else "FAIL",
            "frozen_commit": FROZEN,
            "deterministic_preprocessing": "hash-pinned NOAA inputs -> frozen KRDM preprocessor -> committed v2 pipeline (context-only municipal_update skipped) -> ignored intermediates -> guards",
            "generated_files": [
                {"path": str(canonical_dst.relative_to(worktree)), "sha256": sha(canonical_dst)},
                {"path": str(hours_dst.relative_to(worktree)), "sha256": sha(hours_dst)},
            ],
            "test_summary": v2_result.stdout.strip(),
        }, indent=2, sort_keys=True) + "\n")
    except Exception as exc:
        payload = {
            "CLEANROOM_FINAL_STATUS": "FAIL",
            "CLEAN_V2_REPRODUCIBILITY": "PASS" if v2_result is not None and v2_result.returncode == 0 else "FAIL",
            "frozen_dependency_commit": FROZEN,
            "error": f"{type(exc).__name__}: {exc}",
            "generated_inputs": raw_hashes,
            "commands": commands,
            "temporary_worktree_removed_after_audit": True,
        }
        (OUT / "CLEANROOM_FINAL_STATUS.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        raise
    finally:
        if worktree.exists():
            cleanup = run(["git", "worktree", "remove", "--force", str(worktree)], REPO, timeout=300)
            cleanup_result = f"returncode={cleanup.returncode}"
        shutil.rmtree(temp_parent, ignore_errors=True)
        status_path = OUT / "CLEANROOM_FINAL_STATUS.json"
        if status_path.exists():
            data = json.loads(status_path.read_text())
            data["cleanup_result"] = cleanup_result
            status_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
