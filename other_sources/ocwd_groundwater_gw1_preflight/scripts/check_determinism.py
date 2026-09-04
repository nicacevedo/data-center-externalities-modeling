#!/usr/bin/env python3
"""Replay GW-1A once and certify byte-identical canonical numerical outputs."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.gw1a import run_benchmarks, sha256_file, write_json, write_output_hashes  # noqa: E402


KEY_PATHS = [
    "data/derived/PRIMARY_TEST_PREDICTIONS.parquet",
    "data/derived/ALL_SENSITIVITY_TEST_PREDICTIONS.parquet",
    "data/derived/FIT_SAMPLE_LEDGER.parquet",
    "outputs/tables/PRIMARY_METRICS.csv",
    "outputs/tables/SENSITIVITY_METRICS.csv",
    "outputs/tables/CADENCE_ROBUSTNESS_METRICS.csv",
    "outputs/tables/BOOTSTRAP_DIFFERENCES_VS_PERSISTENCE.csv",
    "outputs/tables/BOOTSTRAP_B3_VS_B2.csv",
    "outputs/tables/OOS_MODEL_RANKING.csv",
    "outputs/figures/fig03_oos_baseline_comparison.png",
    "outputs/figures/fig03_oos_baseline_comparison.pdf",
    "outputs/figures/fig04_per_well_skill_distribution.png",
    "outputs/figures/fig04_per_well_skill_distribution.pdf",
    "outputs/figures/fig05_skill_by_observation_gap.png",
    "outputs/figures/fig05_skill_by_observation_gap.pdf",
    "outputs/FINAL_GW1A_REPORT.md",
    "outputs/FINAL_GW1A_STATUS.json",
]


if __name__ == "__main__":
    before = {relative: sha256_file(ROOT / relative) for relative in KEY_PATHS}
    run_benchmarks()
    after = {relative: sha256_file(ROOT / relative) for relative in KEY_PATHS}
    records = [
        {"path": relative, "sha256_before": before[relative], "sha256_after": after[relative], "byte_identical": before[relative] == after[relative]}
        for relative in KEY_PATHS
    ]
    status = {
        "status": "PASS" if all(row["byte_identical"] for row in records) else "FAIL",
        "method": "rerun frozen B0-B3 pipeline and compare canonical file SHA-256 values",
        "files_compared": len(records),
        "records": records,
    }
    write_json(ROOT / "outputs/provenance/DETERMINISTIC_REPLAY_STATUS.json", status)
    write_output_hashes()
    print(f"DETERMINISTIC_REPLAY={status['status']} ({len(records)} files)")
    if status["status"] != "PASS":
        raise SystemExit(1)

