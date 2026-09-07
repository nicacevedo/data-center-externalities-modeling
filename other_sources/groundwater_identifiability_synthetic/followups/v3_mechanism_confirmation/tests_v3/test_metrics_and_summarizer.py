"""Zero-edge metrics, Block D factorial including three-way, no V3 gates, ANALYSIS guard."""

from __future__ import annotations

import numpy as np
import pytest

from src_v3.metrics import edge_metrics
from src_v3.summarize_v3 import (
    FORBIDDEN_INFERENTIAL_FIELDS,
    block_d_factorial,
    summarize_records,
)


def test_zero_truth_zero_predicted_nan_f1():
    out = edge_metrics(set(), set(), {(0, 1), (0, 2), (1, 2)})
    assert np.isnan(out["edge_f1"])
    assert np.isnan(out["edge_precision"])
    assert np.isnan(out["edge_recall"])


def test_zero_truth_false_predicted_precision_zero_recall_nan():
    predicted = {(0, 1)}
    out = edge_metrics(set(), predicted, {(0, 1), (0, 2), (1, 2)})
    assert out["edge_f1"] == 0.0
    assert out["edge_precision"] == 0.0
    assert np.isnan(out["edge_recall"])
    assert out["edge_false_positive"] == 1.0


def test_block_d_factorial_includes_three_way():
    records = []
    cells = {
        "D_PE_RE_R0": 0.10,
        "D_PE_RE_R3": 0.20,
        "D_PE_RN_R0": 0.30,
        "D_PE_RN_R3": 0.55,
        "D_PM_RE_R0": 0.15,
        "D_PM_RE_R3": 0.25,
        "D_PM_RN_R0": 0.40,
        "D_PM_RN_R3": 0.80,
    }
    for seed in (11, 12, 13):
        for cid, y in cells.items():
            records.append(
                {
                    "cell_id": cid,
                    "seed": seed,
                    "placebo_false_effect_L": y,
                    "placebo_relative_to_true_L": y,
                }
            )
    out = block_d_factorial(records)
    assert out["main_effects"] == ["pumping_quality", "recharge_quality", "confounding_rho"]
    assert len(out["two_way_interactions"]) == 3
    assert out["three_way_interaction"] == [
        "pumping_quality",
        "recharge_quality",
        "confounding_rho",
    ]
    fam = out["outcomes"]["placebo_false_effect_L"]
    assert "int_three_way" in fam
    assert fam["int_three_way"]["primary"] is False
    assert fam["main_pumping"]["primary"] is True
    # Hand-coded three-way for this table should be nonzero.
    assert abs(fam["int_three_way"]["mean"]) > 1e-12


def test_summarizer_emits_no_gates():
    payload = summarize_records([])
    for key in FORBIDDEN_INFERENTIAL_FIELDS:
        assert key not in payload
    assert payload["gates"] == {}


def test_analysis_launcher_authorization_guard():
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parent.parent / "scripts_v3" / "run_v3.py"
    proc = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        cwd=str(script.parent),
    )
    assert proc.returncode != 0
    assert "V3 ANALYSIS refused" in (proc.stderr + proc.stdout)
