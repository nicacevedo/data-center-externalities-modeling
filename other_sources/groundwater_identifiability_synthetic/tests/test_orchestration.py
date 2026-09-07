"""Orchestration freeze: G3 models, per-cell G3, G2 override, F1 alias, ANALYSIS guards."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from groundwater_identifiability_synthetic.src import summarize as sr
from groundwater_identifiability_synthetic.src.design import (
    code_hash,
    design_hash,
    load_design,
    seed_list,
    seed_pool_hash,
)
from groundwater_identifiability_synthetic.tests.test_summarizer import _row


def test_g3_evaluated_models_are_explicit():
    assert sr.g3_evaluated_model("G3R1") == "N"
    assert sr.g3_evaluated_model("G3R2") == "N"
    assert sr.g3_evaluated_model("G3R1b") == "N"
    assert sr.g3_evaluated_model("G3R2b") == "N"
    assert sr.g3_evaluated_model("G3R3") == "L"
    assert sr.g3_evaluated_model("G3R4") == "L"
    assert sr.g3_evaluated_model("G2R3") == "N"
    with pytest.raises(KeyError):
        sr.g3_evaluated_model("G1R1")


def test_g3_does_not_use_global_evaluated_model_fallback(design):
    spec = design["gates"]["SGI_G3"]
    assert "evaluated_model" not in spec
    payload = sr.summarize(design, [_row(cell_id="G3R1")], source="FIXTURE")
    by_cell = payload["gates"]["SGI_G3"]["evaluated_model_by_cell"]
    assert by_cell["G3R1"] == "N"
    assert by_cell["G3R3"] == "L"


def test_g3_per_cell_oracle_cannot_hide_realistic_false_edges(design):
    """Pooling 3 failing realistic reps with many oracle zeros would hide the failure."""
    realistic = [
        _row(cell_id="G3R1", scenario="S6a", false_edge_count=2.0, false_edge_any=1.0)
        for _ in range(3)
    ]
    oracle = [
        _row(cell_id="G3R2", scenario="S6a", false_edge_count=0.0, false_edge_any=0.0)
        for _ in range(20)
    ]
    trig = sr._g3_triggers(design["gates"]["SGI_G3"], {"G3R1": realistic, "G3R2": oracle})
    assert trig["G3_null_s6a_false_edges_median"]["per_cell"]["G3R1"]["triggered"] is True
    assert trig["G3_null_s6a_false_edges_median"]["per_cell"]["G3R2"]["triggered"] is False
    assert trig["G3_null_s6a_false_edges_median"]["triggered"] is True
    assert "G3R1" in trig["G3_null_s6a_false_edges_median"]["realistic_triggered_cells"]
    assert trig["_hard_failure"] is True
    pooled = np.median([2] * 3 + [0] * 20)
    assert pooled <= 0.5  # pooling would have hidden the realistic failure


def test_g2_strong_edge_f1_reads_canonical_column():
    records = [
        _row(cell_id="G2R3", strong_edge_undirected_f1=0.95, edge_f1=0.10)
        for _ in range(5)
    ]
    result = sr.classify_gate_cell(
        records,
        "N",
        [{"id": "G2_strong_edge_f1", "statistic": "median_over_replicates(strong_edge_undirected_f1)",
          "comparator": ">=", "threshold": 0.80}],
    )
    assert result["pass"] is True
    value, _ = sr._criterion_value(
        records, "N",
        {"id": "G2_strong_edge_f1", "statistic": "median_over_replicates(strong_edge_undirected_f1)"},
    )
    assert abs(value - 0.95) < 1e-12


def test_partial_estimability_is_conditional_not_full_support():
    records = [_row(cell_id="G1R1") for _ in range(4)]
    records.append(
        _row(
            cell_id="G1R1",
            estimability_status_L=sr.NOT_ESTIMABLE,
            estimable_L=0.0,
            nire_persistent_step_h26_L=np.nan,
        )
    )
    result = sr.classify_gate_cell(
        records,
        "L",
        [{"id": "G1_intervention", "metric_column": "nire_persistent_step_h26_L",
          "comparator": "<=", "threshold": 0.20}],
    )
    assert result["metrics_pass"] is True
    assert result["support_status"] == sr.CONDITIONALLY_SUPPORTED_BUT_NOT_ROBUSTLY_ESTIMABLE
    assert result["n_not_estimable"] == 1


def test_network_support_final_matrix():
    g2_fail_g3_pass = sr.network_support_final(False, False, False)
    assert g2_fail_g3_pass["status"] == "NOT_EARNED"
    g2_pass_g3_pass = sr.network_support_final(True, False, False)
    assert g2_pass_g3_pass["status"] == "EARNED_UNDER_SPECIFIED_DATA_REGIME"
    g2_pass_g3_fail = sr.network_support_final(True, True, False)
    assert g2_pass_g3_fail["status"] == "NOT_EARNED_DUE_TO_FALSIFICATION"
    g2_cond_g3_pass = sr.network_support_final(True, False, True)
    assert g2_cond_g3_pass["status"] == sr.CONDITIONALLY_SUPPORTED_BUT_NOT_ROBUSTLY_ESTIMABLE


def _g2_passing_records():
    cells = []
    for cid in ("G2R1", "G2R2", "G2R3", "G2R4"):
        cells.extend(
            [
                _row(
                    cell_id=cid,
                    scenario="S4" if cid in ("G2R1", "G2R2") else "S5",
                    nire_persistent_step_h26_N=0.05,
                    nire_persistent_step_h26_L=0.20,
                    nire_persistent_step_h26_S=0.18,
                    nire_persistent_step_h26_B0=0.40,
                    rmse_test_N=0.08,
                    rmse_test_L=0.12,
                    strong_edge_undirected_f1=0.95,
                    edge_f1=0.95,
                    masked_node_nmpe_N=0.10,
                    observed_node_nmpe_N=0.10,
                )
                for _ in range(4)
            ]
        )
    return cells


def test_g2_pass_g3_hard_fail_overrides_network_support(design):
    records = _g2_passing_records()
    records.extend(
        [
            _row(cell_id="G3R1", scenario="S6a", false_edge_count=4.0, false_edge_any=1.0)
            for _ in range(4)
        ]
    )
    payload = sr.summarize(design, records, source="FIXTURE")
    assert payload["SGI_G2_RAW"]["all_required_cells_pass"] is True
    assert payload["gates"]["SGI_G3"]["hard_failure"] is True
    assert payload["NETWORK_SUPPORT_FINAL"]["status"] == "NOT_EARNED_DUE_TO_FALSIFICATION"


def test_analysis_seeds_used_flag_depends_on_source(design):
    payload_f = sr.summarize(design, [_row()], source="FIXTURE")
    payload_a = sr.summarize(design, [_row()], source="ANALYSIS")
    assert payload_f["analysis_seeds_used"] is False
    assert payload_a["analysis_seeds_used"] is True


def test_analysis_summarizer_rejects_smoke_and_hash_mismatch(design, tmp_path, module_root):
    freeze = json.loads((module_root / "outputs/provenance/DESIGN_V2_FREEZE.json").read_text())
    records = [_row(cell_id="G1R1", seed=int(seed_list(design, "SMOKE")[0]), smoke=True)]
    manifest = {
        "source": "ANALYSIS",
        "full_sweep_launched": True,
        "design_hash": freeze["design_hash"],
        "code_hash": freeze["code_hash"],
        "analysis_seed_hash": freeze["seed_pool_hashes"]["ANALYSIS"],
        "n_cells": 1,
        "n_analysis_seeds": 1,
    }
    errors = sr.validate_analysis_inputs(design, records, manifest, freeze)
    assert any("SMOKE" in e for e in errors)

    bad_freeze = dict(freeze)
    bad_freeze["code_hash"] = "0" * 64
    errors2 = sr.validate_analysis_inputs(design, [], dict(manifest, n_cells=0, n_analysis_seeds=0), bad_freeze)
    assert any("CODE_HASH" in e for e in errors2)

    bad_design = dict(freeze)
    bad_design["design_hash"] = "1" * 64
    errors3 = sr.validate_analysis_inputs(design, [], dict(manifest, n_cells=0, n_analysis_seeds=0), bad_design)
    assert any("DESIGN_HASH" in e for e in errors3)


def test_run_experiment_refuses_code_hash_mismatch(module_root):
    import subprocess
    import sys

    freeze_path = module_root / "outputs/provenance/DESIGN_V2_FREEZE.json"
    original = freeze_path.read_text(encoding="utf-8")
    payload = json.loads(original)
    payload["code_hash"] = "0" * 64
    freeze_path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(module_root / "scripts" / "run_experiment.py"),
                "--authorize",
                "I_AUTHORIZE_THE_FULL_PREREGISTERED_SWEEP",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "CODE HASH MISMATCH" in (result.stdout + result.stderr)
    finally:
        freeze_path.write_text(original, encoding="utf-8")
    assert not (module_root / "outputs/analysis/sweep_replicates.csv").exists()


def test_run_experiment_refuses_seed_hash_mismatch(module_root):
    import subprocess
    import sys

    freeze_path = module_root / "outputs/provenance/DESIGN_V2_FREEZE.json"
    original = freeze_path.read_text(encoding="utf-8")
    payload = json.loads(original)
    payload["code_hash"] = code_hash()
    payload["seed_pool_hashes"] = dict(payload["seed_pool_hashes"])
    payload["seed_pool_hashes"]["ANALYSIS"] = "0" * 64
    freeze_path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(module_root / "scripts" / "run_experiment.py"),
                "--authorize",
                "I_AUTHORIZE_THE_FULL_PREREGISTERED_SWEEP",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "SEED POOL HASH MISMATCH" in (result.stdout + result.stderr)
    finally:
        freeze_path.write_text(original, encoding="utf-8")


def test_seed_pool_hash_matches_freeze(design, module_root):
    freeze = json.loads((module_root / "outputs/provenance/DESIGN_V2_FREEZE.json").read_text())
    assert seed_pool_hash(design, "ANALYSIS") == freeze["seed_pool_hashes"]["ANALYSIS"]
    assert seed_pool_hash(design, "SMOKE") == freeze["seed_pool_hashes"]["SMOKE"]


def test_design_hash_unchanged_by_orchestration_code():
    # Locked design_v2 hash from Phase 1.5 freeze.
    assert design_hash() == "b53f5594a444ae4826adfe2c47818080508a4c4b00a38fa25b4ffc483e20a8a5"
    assert code_hash() != "5429a6378005b4152130f6b9707cc1fc61abdf3a81a83e3849530d1ea8f856fd"


def test_prediction_vs_intervention_uses_frozen_g3_rule():
    records = [
        _row(
            cell_id="G2R3",
            rmse_test_N=0.05,
            rmse_test_L=0.20,
            rmse_test_B0=0.40,
            rmse_test_S=0.18,
            nire_persistent_step_h26_N=0.50,
            nire_persistent_step_h26_L=0.10,
            nire_persistent_step_h26_B0=0.60,
            nire_persistent_step_h26_S=0.12,
        )
        for _ in range(3)
    ]
    rows = sr.prediction_vs_intervention(records)
    assert rows[0]["g3_prediction_intervention_inversion"] is True
    assert rows[0]["good_prediction_poor_intervention"] is True
