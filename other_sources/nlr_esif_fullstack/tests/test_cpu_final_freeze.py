"""Tests for the final Kestrel CPU freeze / end-to-end ESIF correction pass."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from kestrel_paths import ANALYSIS, DOCS, MANIFESTS, SPLIT_DEV_END, SPLIT_VAL_END  # noqa: E402

P_FROZEN = 700.6894574294788
STATUS_KEYS = [
    "CPU_COMPLETED_NODE_HOUR",
    "CPU_TIMEOUT_TRANSFER",
    "CPU_CANCELLED_TRANSFER",
    "CPU_OTHER_STATE_TRANSFER",
    "CPU_VALIDATED_RAW_MEASURED_ENERGY_SHARE",
    "CPU_VALIDATED_ADDITIVE_ENERGY_SHARE",
    "SHARED_CPU_RECONSTRUCTION",
    "H100_MEASURED_JOB_ENERGY",
    "ENERGY_CONSERVING_JOB_REPLAY",
    "SUBHOURLY_POWER_SHAPE",
    "ESIF_TIMESTAMP_SEMANTICS",
    "ESIF_MEASURED_CPU_LINKAGE",
    "ESIF_PREDICTED_CPU_LINKAGE",
    "CPU_LAYER_FINAL_DISPOSITION",
]


def test_frozen_coefficient_not_refit():
    freeze = json.loads((MANIFESTS / "FINAL_MODEL_FREEZE.json").read_text())
    assert freeze["EX_POST_CPU"]["p_hat_W_per_node"] == pytest.approx(P_FROZEN)
    st = json.loads((ANALYSIS / "FINAL_KESTREL_CPU_STATUS.json").read_text())
    assert st["p_KestrelCPU_W_per_node"] == pytest.approx(P_FROZEN)
    assert st["refit"] is False
    trans = json.loads((ANALYSIS / "CPU_STATE_TRANSFER_FINAL.json").read_text())
    assert trans["refit"] is False
    assert trans["p_cpu_w_per_node"] == pytest.approx(P_FROZEN)


def test_chronological_splits_match_protocol():
    proto = json.loads((MANIFESTS / "MODEL_PROTOCOL_FREEZE.json").read_text())
    assert proto["development"]["start_time_utc <"] == SPLIT_DEV_END
    assert proto["untouched_final_test"]["start_time_utc >="] == SPLIT_VAL_END
    chrono = pd.read_csv(ANALYSIS / "CPU_STATE_TRANSFER_CHRONO.csv")
    for name in ("TIMEOUT_DEV", "TIMEOUT_VAL", "TIMEOUT_TEST", "CANCELLED_TEST"):
        assert name in set(chrono["cohort"])
    to_test = chrono[chrono["cohort"] == "TIMEOUT_TEST"].iloc[0]
    assert to_test["transfer_status"] == "PASS_TRANSFER"
    assert to_test["p_used"] == pytest.approx(P_FROZEN)


def test_predicted_replay_has_no_measured_energy_leakage():
    cons = json.loads((ANALYSIS / "CPU_REPLAY_CONSERVATION.json").read_text())
    js = cons["job_set"]
    assert js["predicted_uses_measured_energy"] is False
    assert "p_frozen" in js["predicted_formula"]
    assert js["identical_job_set"] is True
    assert js["states"] == ["CANCELLED", "COMPLETED", "TIMEOUT"]
    assert abs(js["sum_predicted_Wh"] - js["sum_measured_Wh"]) / js["sum_measured_Wh"] < 0.05
    for res, rec in cons["conservation"].items():
        assert rec["measured"]["pass"]
        assert rec["predicted"]["pass"]
        assert rec["measured"]["source_Wh"] == pytest.approx(js["sum_measured_Wh"], rel=1e-12)
        assert rec["predicted"]["source_Wh"] == pytest.approx(js["sum_predicted_Wh"], rel=1e-12)


def test_esif_daily_identical_timestamps_no_lag():
    cmpj = json.loads((ANALYSIS / "ESIF_CPU_REPLAY_COMPARISON.json").read_text())
    assert cmpj["lag_optimized"] is False
    assert cmpj["identical_timestamps"] is True
    assert cmpj["primary_resolution"] == "1day"
    assert cmpj["ESIF_TIMESTAMP_SEMANTICS"] == "AMBIGUOUS"
    dm = cmpj["daily_post_gpu_ga"]["measured"]
    dp = cmpj["daily_post_gpu_ga"]["predicted"]
    assert dm["n"] == dp["n"]
    assert dm["identical_timestamps"] is True
    assert dp["lag_optimized"] is False
    df = pd.read_csv(ANALYSIS / "ESIF_CPU_REPLAY_COMPARISON.csv")
    assert not df["lag_optimized"].astype(bool).any()
    pair = df[(df["resolution"] == "1day") & (df["epoch"] == "post_gpu_ga")]
    assert set(pair["n"]) == {int(dm["n"])}


def test_coverage_denominators_not_physical_it():
    cov = json.loads((ANALYSIS / "CPU_ENERGY_COVERAGE.json").read_text())
    m = cov["coverage_measures"]
    raw = m["summed_positive_measured_ConsumedEnergyRaw_job_record_GWh"]
    shared = m["non_additive_shared_raw_sum_GWh"]
    add = m["additive_nonshared_positive_measured_job_record_GWh"]
    val = m["validated_additive_cpu_GWh"]
    assert add == pytest.approx(raw - shared)
    assert m["fraction_of_summed_positive_measured_ConsumedEnergyRaw_job_record_energy_represented_by_validated_additive_CPU_states"] == pytest.approx(val / raw)
    assert m["fraction_of_additive_nonshared_positive_measured_job_record_energy_represented_by_validated_CPU_states"] == pytest.approx(val / add)
    assert m["not_fraction_of_physical_Kestrel_IT"] is True
    assert m["not_fraction_of_facility_IT"] is True
    st = json.loads((ANALYSIS / "FINAL_KESTREL_CPU_STATUS.json").read_text())
    assert st["CPU_VALIDATED_RAW_MEASURED_ENERGY_SHARE"] == pytest.approx(val / raw)
    assert st["CPU_VALIDATED_ADDITIVE_ENERGY_SHARE"] == pytest.approx(val / add)
    report = (DOCS / "KESTREL_JOB_POWER_REPORT.md").read_text()
    assert "summed positive measured ConsumedEnergyRaw job-record energy" in report
    assert "not** a fraction of physical Kestrel IT" in report or "not a fraction of physical Kestrel IT" in report.lower()
    freeze_script = (ROOT / "scripts" / "run_kestrel_cpu_final_freeze.py").read_text()
    assert "cooling" not in freeze_script.lower() or "Do not" in freeze_script


def test_shared_not_summed_and_no_h100():
    rec = json.loads((ANALYSIS / "SHARED_CPU_RECONSTRUCTION.json").read_text())
    assert rec["disposition"] == "UNSUPPORTED"
    st = json.loads((ANALYSIS / "FINAL_KESTREL_CPU_STATUS.json").read_text())
    assert st["SHARED_CPU_RECONSTRUCTION"] == "UNSUPPORTED"
    assert st["H100_MEASURED_JOB_ENERGY"] == "UNSUPPORTED_IN_KESTREL_JOB_EXTRACT"
    script = (ROOT / "scripts" / "run_kestrel_cpu_final_freeze.py").read_text()
    assert "Meta_Prineville" not in script
    assert "wget" not in script


def test_residual_not_called_wape_no_iid_default():
    r = json.loads((ANALYSIS / "CPU_RESIDUAL_UNCERTAINTY.json").read_text())
    assert r["WAPE_is_not_an_uncertainty_interval"] is True
    assert r["iid_epsilon_sampling_allowed"] is False
    assert "WAPE" in r["note"]
    dep = pd.read_csv(ANALYSIS / "CPU_RESIDUAL_DEPENDENCE.csv")
    assert len(dep) <= 4
    assert dep["energy_weight"].sum() == pytest.approx(1.0, abs=1e-6)


def test_markdown_statuses_match_canonical_json():
    st = json.loads((ANALYSIS / "FINAL_KESTREL_CPU_STATUS.json").read_text())
    report = (DOCS / "KESTREL_JOB_POWER_REPORT.md").read_text()
    section = report.split("## Final capability status")[-1]
    for key in STATUS_KEYS:
        val = st[key]
        if key in (
            "CPU_VALIDATED_RAW_MEASURED_ENERGY_SHARE",
            "CPU_VALIDATED_ADDITIVE_ENERGY_SHARE",
        ):
            pct = f"{100 * float(val):.1f}%"
            assert pct in section, key
        else:
            assert f"**{val}**" in section, f"{key}={val}"
    assert st["CPU_LAYER_FINAL_DISPOSITION"] == "FROZEN_PASS_WITH_DOMAIN_RESTRICTIONS"


def test_timeout_cohort_definition_unchanged():
    t = json.loads((MANIFESTS / "TIMEOUT_TRANSFER_FREEZE.json").read_text())
    assert t["no_refitting"] is True
    assert "state_simple='TIMEOUT'" in t["where_sql"]
    assert t["p_cpu_w_per_node"] == pytest.approx(P_FROZEN)
