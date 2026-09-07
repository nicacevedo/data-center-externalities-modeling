"""Fixture-based tests for the preregistered summarizer. No ANALYSIS seeds."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest

from groundwater_identifiability_synthetic.src import summarize as sr

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def _row(**kwargs):
    base = {
        "cell_id": "G1R1",
        "scenario": "S1",
        "cadence": 4,
        "mcar_fraction": 0.1,
        "estimability_status_L": sr.ESTIMATED,
        "estimability_status_N": sr.ESTIMATED,
        "estimability_reason_L": "ESTIMATED",
        "estimability_reason_N": "ESTIMATED",
        "estimable_L": 1.0,
        "estimable_N": 1.0,
        "rmse_test_L": 0.1,
        "rmse_test_N": 0.08,
        "rmse_test_B0": 0.4,
        "nire_persistent_step_h26_B0": 0.50,
        "nire_persistent_step_h26_L": 0.10,
        "nire_persistent_step_h26_S": 0.12,
        "nire_persistent_step_h26_N": 0.08,
        "rmse_test_S": 0.12,
        "beta_q_hat_mean_L": -0.20,
        "edge_f1": 0.90,
        "masked_node_nmpe_N": 0.20,
        "observed_node_nmpe_N": 0.20,
        "false_edge_count": 0.0,
        "false_edge_any": 0.0,
        "placebo_false_effect_L": 0.0,
        "sign_correct_fraction_L": 1.0,
        "max_abs_protected_prediction_L": 1.0,
    }
    base.update(kwargs)
    return base


def test_all_models_estimable_and_passing():
    records = [_row(cell_id="G1R1") for _ in range(5)]
    result = sr.classify_gate_cell(
        records,
        "L",
        [{"id": "G1_intervention", "metric_column": "nire_persistent_step_h26_L",
          "comparator": "<=", "threshold": 0.20}],
    )
    assert result["state"] == sr.ESTIMATED_PASSED_GATE
    assert result["pass"] is True


def test_required_cell_not_estimable_fails_and_is_retained():
    records = [
        _row(
            cell_id="G2R3",
            estimability_status_N=sr.NOT_ESTIMABLE,
            estimability_reason_N="insufficient_training_rows",
            estimable_N=0.0,
            nire_persistent_step_h26_N=np.nan,
        )
        for _ in range(5)
    ]
    result = sr.classify_gate_cell(
        records,
        "N",
        [{"id": "G2_strong_edge_f1", "metric_column": "edge_f1", "comparator": ">=", "threshold": 0.80}],
    )
    assert result["state"] == sr.NOT_ESTIMABLE
    assert result["pass"] is False
    assert result["complexity_unsupported"] is True
    agg = sr.aggregate_cell(records, "N", "nire_persistent_step_h26_N")
    assert agg["not_estimable_rate"] == 1.0
    assert agg["n_not_estimable"] == 5


def test_solver_failure_is_distinct_from_not_estimable():
    records = [
        _row(estimability_status_L=sr.FIT_FAILED, estimability_reason_L="solver_failure", estimable_L=0.0)
        for _ in range(3)
    ]
    result = sr.classify_gate_cell(records, "L", [])
    assert result["state"] == sr.FIT_FAILED
    assert result["pass"] is False


def test_good_prediction_poor_intervention_is_classified():
    records = [
        _row(
            cell_id="INV1",
            rmse_test_N=0.05,
            rmse_test_L=0.20,
            nire_persistent_step_h26_N=0.50,
            nire_persistent_step_h26_L=0.10,
        )
        for _ in range(4)
    ]
    rows = sr.prediction_vs_intervention(records)
    assert len(rows) == 1
    assert rows[0]["prediction_vs_intervention_inversion"] is True
    assert rows[0]["prediction_gain_N_vs_L"] > 0
    assert rows[0]["intervention_gain_N_vs_L"] < 0


def test_s6_false_edges_trigger_g3_hard_failure(design):
    records = [
        _row(cell_id="G3R1", scenario="S6a", false_edge_count=2.0, false_edge_any=1.0)
        for _ in range(8)
    ]
    trig = sr._g3_triggers(design["gates"]["SGI_G3"], {"G3R1": records})
    assert trig["G3_null_s6a_false_edges_median"]["triggered"] is True
    assert trig["_hard_failure"] is True


def test_s8_false_placebo_effect_triggers_g3(design):
    records = [
        _row(cell_id="G3R3", scenario="S8", placebo_false_effect_L=1.0)
        for _ in range(8)
    ]
    trig = sr._g3_triggers(design["gates"]["SGI_G3"], {"G3R3": records})
    assert trig["G3_placebo_effect"]["triggered"] is True


def test_g3_prediction_intervention_inversion_trigger(design):
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
        for _ in range(4)
    ]
    trig = sr._g3_triggers(design["gates"]["SGI_G3"], {"G2R3": records})
    assert trig["G3_prediction_intervention_inversion"]["triggered"] is True
    assert trig["_hard_failure"] is True


def test_s9_support_misspecification_is_visible_in_adequacy():
    records = [
        _row(
            cell_id="R_S9_hidden",
            scenario="S9",
            true_edges_outside_candidate_set=1.0,
            estimability_status_N=sr.ESTIMATED,
        )
        for _ in range(3)
    ]
    adequacy = sr.data_adequacy_rows(records)
    assert adequacy[0]["cell_id"] == "R_S9_hidden"
    assert adequacy[0]["complexity_unsupported"] is False


def test_oracle_cannot_compensate_for_realistic_not_estimable(design):
    oracle = [_row(cell_id="G2R1", nire_persistent_step_h26_N=0.05) for _ in range(4)]
    realistic = [
        _row(
            cell_id="G2R3",
            estimability_status_N=sr.NOT_ESTIMABLE,
            estimable_N=0.0,
            nire_persistent_step_h26_N=np.nan,
        )
        for _ in range(4)
    ]
    payload = sr.summarize(design, oracle + realistic, source="FIXTURE")
    g2 = payload["gates"]["SGI_G2"]
    assert g2["oracle_compensated"] or not g2["all_required_cells_pass"]
    assert "G2R3" in g2["realistic_failures"]


def test_fixture_csvs_exist_and_round_trip():
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    cases = {
        "all_passing": [_row(cell_id="G1R1") for _ in range(3)],
        "n_not_estimable": [
            _row(cell_id="G2R3", estimability_status_N=sr.NOT_ESTIMABLE, estimable_N=0.0)
            for _ in range(3)
        ],
        "solver_failure": [
            _row(cell_id="G1R1", estimability_status_L=sr.FIT_FAILED, estimable_L=0.0)
            for _ in range(3)
        ],
        "pred_vs_interv": [
            _row(cell_id="INV1", rmse_test_N=0.05, rmse_test_L=0.2,
                 nire_persistent_step_h26_N=0.5, nire_persistent_step_h26_L=0.1)
        ],
        "s6_false_edges": [_row(cell_id="G3R1", scenario="S6a", false_edge_count=3, false_edge_any=1)],
        "s8_placebo": [_row(cell_id="G3R3", scenario="S8", placebo_false_effect_L=1)],
        "s9_support": [_row(cell_id="R_S9_hidden", scenario="S9")],
    }
    for name, rows in cases.items():
        path = FIXTURE_DIR / f"{name}.csv"
        fields = sorted({k for r in rows for k in r})
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        loaded = sr.load_records(path)
        assert len(loaded) == len(rows)
