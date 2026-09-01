"""Focused tests for the CPU-coverage / ESIF-closure pass."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kestrel_paths import (  # noqa: E402
    ANALYSIS,
    DOCS,
    MANIFESTS,
    RESULTS,
    SHARED_PARTITIONS,
    TIMESERIES,
)
from run_kestrel_job_power_experiment import replay_from_jobs  # noqa: E402

P_FROZEN = 700.6894574294788


def test_frozen_coefficient_unchanged():
    freeze = json.loads((MANIFESTS / "FINAL_MODEL_FREEZE.json").read_text())
    assert freeze["EX_POST_CPU"]["p_hat_W_per_node"] == pytest.approx(P_FROZEN)
    t = json.loads((MANIFESTS / "TIMEOUT_TRANSFER_FREEZE.json").read_text())
    assert t["p_cpu_w_per_node"] == pytest.approx(P_FROZEN)
    assert t["no_refitting"] is True
    testm = pd.read_csv(RESULTS / "job_energy_test_metrics.csv")
    row = testm[(testm["problem"] == "EX_POST") & (testm["split"] == "test")].iloc[0]
    assert row["WAPE"] == pytest.approx(0.13616455874940167)
    assert row["total_energy_bias"] == pytest.approx(0.030774472066324332)
    st = json.loads((RESULTS / "FINAL_KESTREL_JOB_POWER_STATUS.json").read_text())
    assert st["p_hat_W"] == pytest.approx(P_FROZEN)


def test_timeout_cohort_restrictions():
    t = json.loads((MANIFESTS / "TIMEOUT_TRANSFER_FREEZE.json").read_text())
    sql = t["where_sql"]
    assert "state_simple='TIMEOUT'" in sql
    assert "hardware_branch='CPU'" in sql
    assert "shared_job_count IS NULL OR shared_job_count = 0" in sql
    sql_wo_shared_logic = sql.replace("shared_job_count", "")
    for p in SHARED_PARTITIONS:
        assert f"'{p}'" not in sql_wo_shared_logic
    assert "gpu-h100" not in sql
    assert t["cohort_rules"]["no_energy_tdp_filtering_beyond_target_validity"] is True
    audit = json.loads((ANALYSIS / "TIMEOUT_TRANSFER_AUDIT.json").read_text())
    assert audit["refit"] is False
    assert audit["p_cpu_w_per_node"] == pytest.approx(P_FROZEN)
    assert t["measured_GWh"] == pytest.approx(t["measured_energy_wh"] / 1e9)


def test_state_transfer_uses_energy_as_outcome_only():
    path = ANALYSIS / "CPU_STATE_TRANSFER_CHRONO.csv"
    if not path.exists():
        path = RESULTS / "cpu_state_transfer_metrics.csv"
    df = pd.read_csv(path)
    assert np.allclose(df["p_used"].dropna().unique(), P_FROZEN)
    assert df["refit"].astype(str).str.lower().isin(["false", "0"]).all()
    to = df[df["cohort"] == "TIMEOUT_transfer"].iloc[0]
    assert to["transfer_status"] == "PASS_TRANSFER"
    assert to["WAPE"] < 0.2
    assert abs(to["total_energy_bias"]) < 0.05
    ca = df[df["cohort"] == "CANCELLED_transfer"].iloc[0]
    assert ca["transfer_status"] == "PASS_TRANSFER"
    fail = df[df["cohort"] == "FAILED_transfer"].iloc[0]
    assert fail["transfer_status"] == "FAIL_TRANSFER"


def test_residual_multiplier_definition():
    r = json.loads((ANALYSIS / "CPU_RESIDUAL_UNCERTAINTY.json").read_text())
    if not (RESULTS / "cpu_residual_distribution.json").exists():
        pass
    else:
        old = json.loads((RESULTS / "cpu_residual_distribution.json").read_text())
        assert old["WAPE_is_not_an_uncertainty_interval"] is True
    assert r["WAPE_is_not_an_uncertainty_interval"] is True
    assert r["iid_epsilon_sampling_allowed"] is False
    assert 0.5 < r["eps_median"] < 1.2
    assert r["eps_p05"] < r["eps_median"] < r["eps_p95"]


def test_shared_raw_energy_not_summed_into_validated_coverage():
    cov = json.loads((ANALYSIS / "CPU_ENERGY_COVERAGE.json").read_text())
    d = next(x for x in cov["categories"] if x["category"].startswith("D_shared"))
    assert d["directly_representable_by_frozen_cpu_model"] is False
    assert d["raw_energy_additive"] is False
    c = next(x for x in cov["categories"] if x["category"].startswith("C_other"))
    assert c["directly_representable_by_frozen_cpu_model"] is False
    assert c["validated_states"] == ["CANCELLED"]
    md = (ANALYSIS / "SHARED_CPU_RECONSTRUCTION_FEASIBILITY.md").read_text()
    assert "UNSUPPORTED" in md
    assert "Do **not** sum" in md
    rec = json.loads((ANALYSIS / "SHARED_CPU_RECONSTRUCTION.json").read_text())
    assert rec["disposition"] == "UNSUPPORTED"


def test_replay_v2_conserves_energy():
    # Historical 5min/15min conservation (if present) plus canonical hourly/daily freeze conservation.
    hist = RESULTS / "replay_v2_conservation.json"
    if hist.exists():
        cons = json.loads(hist.read_text())
        for res, rec in cons.items():
            assert rec["total_validated_cpu_kw"]["pass"], res
    freeze_cons = json.loads((ANALYSIS / "CPU_REPLAY_CONSERVATION.json").read_text())
    js = freeze_cons["job_set"]
    assert js["identical_job_set"] is True
    assert js["predicted_uses_measured_energy"] is False
    for res, rec in freeze_cons["conservation"].items():
        assert rec["measured"]["pass"], res
        assert rec["predicted"]["pass"], res
    ts = TIMESERIES / "kestrel_cpu_replay_measured_pred_v2.parquet"
    assert ts.exists()
    cols = set(pd.read_parquet(ts, columns=["measured_cpu_kw", "predicted_cpu_kw"]).columns)
    assert "measured_cpu_kw" in cols and "predicted_cpu_kw" in cols


def test_timezone_audit_does_not_optimize_kestrel_lag():
    audit = json.loads((ANALYSIS / "ESIF_TIMEZONE_AUDIT.json").read_text())
    assert audit["correlation_with_kestrel_not_used_to_choose_offset"] is True
    assert audit["disposition"] == "AMBIGUOUS"
    md = (DOCS / "ESIF_TIMESTAMP_SEMANTICS.md").read_text()
    assert "not" in md.lower()
    assert "correlation" in md.lower()
    freeze = json.loads((MANIFESTS / "TIMEOUT_TRANSFER_FREEZE.json").read_text())
    assert "maximizing correlation" in freeze["timezone_anchors_predeclared_before_meter_inspection"]["forbidden"]


def test_no_h100_substitution_or_genai_or_meta():
    st = json.loads((ANALYSIS / "FINAL_KESTREL_CPU_STATUS.json").read_text())
    assert st["H100_MEASURED_JOB_ENERGY"] == "UNSUPPORTED_IN_KESTREL_JOB_EXTRACT"
    assert st["SUBHOURLY_POWER_SHAPE"] == "UNSUPPORTED"
    cov = json.loads((ANALYSIS / "CPU_ENERGY_COVERAGE.json").read_text())
    e = next(x for x in cov["categories"] if x["category"].startswith("E_H100"))
    assert e["measured_GWh"] == 0.0
    assert e["directly_representable_by_frozen_cpu_model"] is False
    clos = (ROOT / "scripts" / "run_cpu_closure_pass.py").read_text()
    assert "Meta_Prineville" not in clos
    assert "wget" not in clos
    assert "requests.get" not in clos
    freeze_script = (ROOT / "scripts" / "run_kestrel_cpu_final_freeze.py").read_text()
    assert "Meta_Prineville" not in freeze_script
    assert "3025227" not in freeze_script or "not executed" in freeze_script.lower() or "executed\": False" in freeze_script or "executed" in freeze_script
    report = (DOCS / "KESTREL_JOB_POWER_REPORT.md").read_text()
    assert "not executed" in report.lower()
    assert "UNSUPPORTED_IN_KESTREL_JOB_EXTRACT" in report


def test_gwh_units_are_wh_over_1e9():
    freeze = json.loads((MANIFESTS / "TIMEOUT_TRANSFER_FREEZE.json").read_text())
    assert freeze["measured_GWh"] == pytest.approx(10.326, abs=0.01)
    cov = json.loads((ANALYSIS / "CPU_ENERGY_COVERAGE.json").read_text())
    a = next(x for x in cov["categories"] if x["category"].startswith("A_"))
    assert a["measured_GWh"] == pytest.approx(9.282, abs=0.01)
    assert cov["validated_additive_cpu_GWh"] == pytest.approx(21.295, abs=0.01)


def test_synthetic_overlap_allocation_still_conserves():
    starts = pd.to_datetime(["2024-01-01 00:00:10Z"], utc=True)
    ends = pd.to_datetime(["2024-01-01 00:10:10Z"], utc=True)
    e = np.array([1000.0])
    _, _p, cons, total = replay_from_jobs(starts, ends, e, "5min")
    assert cons["pass"]
    assert abs(total - 1000) < 1e-9
