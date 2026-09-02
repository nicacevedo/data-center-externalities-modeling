"""Focused tests for ESIF facility-overhead. Does not refit CPU/H100."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

FO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FO / "scripts"))
from facility_paths import (  # noqa: E402
    ALIGN_TOLERANCE_S,
    ANALYSIS,
    CADENCE_S,
    COVERAGE_MIN,
    CPU_FREEZE,
    CPU_FREEZE_SHA256,
    CPU_STATUS,
    CPU_STATUS_SHA256,
    DATA_PROCESSED,
    DOCS,
    H100_FREEZE,
    H100_FREEZE_SHA256,
    MANIFESTS,
    MAX_INTEGRATION_GAP_S,
    POWER_PARQUET,
    POWER_SHA256,
    README_SHA256,
    RESULTS,
    SIMPLEST_ORDER,
    WEATHER_PARQUET,
    WEATHER_SHA256,
    ESIF_README,
)
from run_esif_facility_overhead import (  # noqa: E402
    hourly_aggregate,
    stull_wetbulb_c,
)


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def test_raw_hashes_unchanged():
    assert _sha(POWER_PARQUET) == POWER_SHA256
    assert _sha(WEATHER_PARQUET) == WEATHER_SHA256
    assert _sha(ESIF_README) == README_SHA256


def test_cpu_h100_frozen_manifests_unchanged():
    assert _sha(CPU_STATUS) == CPU_STATUS_SHA256
    assert _sha(CPU_FREEZE) == CPU_FREEZE_SHA256
    assert _sha(H100_FREEZE) == H100_FREEZE_SHA256
    init = json.loads((MANIFESTS / "FACILITY_OVERHEAD_INITIAL_STATE.json").read_text())
    assert init["cpu"]["refit"] is False
    assert init["h100"]["refit"] is False
    st = json.loads((RESULTS / "FINAL_ESIF_FACILITY_OVERHEAD_STATUS.json").read_text())
    assert st["cpu_untouched"] is True
    assert st["h100_untouched"] is True


def test_official_field_units():
    sem = pd.read_csv(ANALYSIS / "FACILITY_FIELD_SEMANTICS.csv")
    units = dict(zip(sem.field, sem.unit))
    assert "kW" in units["it_power_kw"]
    assert "kW" in units["cooling_kw"]
    assert "Fahrenheit" in units["outside_air_temp"]
    assert "percent" in units["outside_air_humidity"].lower()


def test_component_arithmetic_and_pue_reconstruction():
    cl = json.loads((ANALYSIS / "PUE_COMPONENT_CLOSURE_AUDIT.json").read_text())
    assert cl["PUE_COMPONENT_CLOSURE"] in {"PASS", "PARTIAL", "FAIL"}
    assert cl["n_compared"] > 1000
    # recon = (IT+aux)/IT compared to source pue; do not force closure
    h = pd.read_parquet(DATA_PROCESSED / "esif_facility_hourly.parquet", columns=["it_power_kw", "cooling_kw", "hvac_kw", "pump_kw", "plug_and_light_kw", "aux_source_kw", "valid_all"])
    v = h[h.valid_all].head(500)
    np.testing.assert_allclose(
        v.aux_source_kw,
        v.cooling_kw + v.hvac_kw + v.pump_kw + v.plug_and_light_kw,
        rtol=1e-10,
        atol=1e-8,
    )


def test_timestamp_uniqueness_and_alignment_tolerance_frozen():
    clock = json.loads((ANALYSIS / "POWER_WEATHER_CLOCK_AUDIT.json").read_text())
    assert clock["alignment_tolerance_s_frozen_from_cadence"] == ALIGN_TOLERANCE_S
    assert clock["timezone_optimization"] == "NOT_PERFORMED"
    assert "UTC or America/Denver" in clock["not_the_question"]
    qc = json.loads((ANALYSIS / "FACILITY_DATA_QC.json").read_text())
    assert qc["power"]["n_duplicate_ts"] == 0
    assert qc["weather"]["n_duplicate_ts"] == 0


def test_energy_preserving_hourly_and_gap_treatment():
    ts = pd.date_range("2020-01-01", periods=60, freq="60s")
    df = pd.DataFrame({"ts": ts, "x": 10.0})
    # insert a 1-hour hole
    df.loc[30:, "ts"] = df.loc[30:, "ts"] + pd.Timedelta(hours=1)
    out = hourly_aggregate(df, ["x"])
    # the gapped hour must not reach 90% coverage
    low = out[out.coverage < COVERAGE_MIN]
    assert len(low) >= 1
    assert MAX_INTEGRATION_GAP_S == 180.0
    assert CADENCE_S == 60.0


def test_temporal_split_chronology_no_random_no_test_in_selection():
    sp = json.loads((MANIFESTS / "FACILITY_TEMPORAL_SPLIT_FREEZE.json").read_text())
    assert sp["no_random_split"] is True
    assert sp["test_not_used_for_selection"] is True
    assert pd.Timestamp(sp["DEV"]["end_exclusive"]) == pd.Timestamp(sp["TEST"]["start"])
    assert pd.Timestamp(sp["DEV"]["start"]) < pd.Timestamp(sp["TEST"]["start"])
    proto = json.loads((MANIFESTS / "FACILITY_MODEL_PROTOCOL_FREEZE.json").read_text())
    assert proto["test_not_used_for_selection"] if "test_not_used_for_selection" in proto else True
    assert "direct PUE fit" in proto["forbidden"]


def test_no_target_leakage_or_direct_pue_fit():
    proto = json.loads((MANIFESTS / "FACILITY_MODEL_PROTOCOL_FREEZE.json").read_text())
    assert "target autoregression" in proto["forbidden"]
    pue = json.loads((ANALYSIS / "PUE_PREDICTION_METRICS.json").read_text())
    assert "not fitted" in pue["note"].lower() or "was not fitted" in pue["note"]
    sel = json.loads((ANALYSIS / "COMPONENT_SELECTED_MODELS.json").read_text())
    for t, rec in sel.items():
        assert rec["selected_spec"] in SIMPLEST_ORDER


def test_no_reconstructed_kestrel_or_meta_or_water_or_prineville_transfer():
    init = json.loads((MANIFESTS / "FACILITY_OVERHEAD_INITIAL_STATE.json").read_text())
    c = init["constraints"]
    assert c["do_not_use_kestrel_cpu_replay"]
    assert c["do_not_use_meta"]
    assert c["do_not_fit_water"]
    assert c["do_not_transfer_coefficients_to_prineville"]
    st = json.loads((RESULTS / "FINAL_ESIF_FACILITY_OVERHEAD_STATUS.json").read_text())
    assert st["PRINEVILLE_COEFFICIENT_TRANSFER"] == "NOT_ALLOWED"
    assert st["input"] == "measured it_power_kw + weather"
    text = (FO / "scripts" / "run_esif_facility_overhead.py").read_text()
    assert "kestrel_jobs" not in text
    assert "ConsumedEnergyRaw" not in text
    assert "Meta_Prineville" not in text
    assert "wue" not in text.lower() or "not_executed" in json.dumps(st).lower()


def test_parsimony_rule_executed():
    sel = json.loads((ANALYSIS / "COMPONENT_SELECTED_MODELS.json").read_text())
    cv = pd.read_csv(ANALYSIS / "COMPONENT_CV_METRICS.csv")
    for target in ["cooling_kw", "hvac_kw", "pump_kw", "plug_and_light_kw"]:
        sub = cv[cv.target == target]
        assert not sub.empty
        best = sub["cv_daily_energy_WAPE"].min()
        chosen = sel[target]["selected_spec"]
        chosen_w = float(sub.loc[sub.spec == chosen, "cv_daily_energy_WAPE"].iloc[0])
        assert chosen_w <= best * 1.01 + 1e-12
        assert chosen in SIMPLEST_ORDER


def test_stull_wetbulb_room_temp():
    twb = float(stull_wetbulb_c(np.array([20.0]), np.array([50.0]))[0])
    assert 12.0 < twb < 16.0


def test_descriptive_pump_reclass_not_canonical():
    sem = pd.read_csv(ANALYSIS / "FACILITY_FIELD_SEMANTICS.csv")
    pump_phys = sem[sem.field == "pump_physical_kw"].iloc[0]
    assert "not a canonical" in pump_phys.modeling_role or "do not replace" in pump_phys.modeling_role
    md = (DOCS / "ESIF_FACILITY_BOUNDARY.md").read_text()
    assert "2.67" in md
    assert "not" in md.lower() and "substitutes" in md.lower() or "do not replace" in md.lower() or "not canonical" in md.lower()


def _closure_init():
    return json.loads((MANIFESTS / "FACILITY_OVERHEAD_POSTTEST_CLOSURE_INITIAL_STATE.json").read_text())


def test_original_numerical_artifacts_unchanged():
    init = _closure_init()
    for rel, meta in init["frozen_numerical_artifacts"].items():
        if rel.endswith("run_esif_facility_overhead.py"):
            continue  # generating-code corrections allowed; numerical files are not
        assert _sha(FO / rel) == meta["sha256"]
    sel = json.loads((ANALYSIS / "COMPONENT_SELECTED_MODELS.json").read_text())
    assert sel["cooling_kw"]["selected_spec"] == "F4"
    assert sel["hvac_kw"]["selected_spec"] == "F0"
    assert sel["pump_kw"]["selected_spec"] == "F4"
    assert sel["plug_and_light_kw"]["selected_spec"] == "F2_PHYS"
    assert sel["hvac_kw"]["coef"] == [19.48945560740139]


def test_cpu_h100_raw_hashes_match_closure_freeze():
    init = _closure_init()
    assert _sha(CPU_STATUS) == init["cpu"]["FINAL_KESTREL_CPU_STATUS.json"]
    assert _sha(CPU_FREEZE) == init["cpu"]["FINAL_MODEL_FREEZE.json"]
    assert _sha(H100_FREEZE) == init["h100"]["H100_COMPUTE_FINAL_FREEZE.json"]
    assert _sha(POWER_PARQUET) == init["raw_esif"]["power_parquet"]
    assert _sha(WEATHER_PARQUET) == init["raw_esif"]["weather_parquet"]


def test_thermosyphon_in_sample_august_2016_transition():
    ep = json.loads((ANALYSIS / "EPOCH_STABILITY.json").read_text())
    assert ep["epochs"]["thermosyphon_commissioning"] == "IN_SAMPLE"
    assert "NOT_IN_SAMPLE" not in ep["epochs"]["thermosyphon_commissioning"]
    tsc = json.loads((ANALYSIS / "THERMOSYPHON_COMMISSIONING_AUDIT.json").read_text())
    assert tsc["thermosyphon_in_sample"] is True
    assert tsc["NOT_IN_SAMPLE"] is False
    assert tsc["commissioning_transition"]["start"] == "2016-08-01"
    assert tsc["commissioning_transition"]["month_treated_as"] == "transitional"
    assert tsc["first_full_tsc_year"]["start"] == "2016-09-01"
    assert tsc["first_full_tsc_year"]["end_inclusive"] == "2017-08-31"
    months = pd.read_csv(ANALYSIS / "THERMOSYPHON_COMMISSIONING_AUDIT.csv")
    assert (months.loc[months.month == "2016-08", "regime"] == "commissioning_transition").all()
    assert (months.loc[months.month == "2016-09", "regime"] == "first_full_tsc_year").all()
    runner = (FO / "scripts" / "run_esif_facility_overhead.py").read_text()
    assert "NOT_IN_SAMPLE (ESIF thermosyphon predates 2015 start)" not in runner


def test_residual_protocol_deviation_not_falsely_asserted():
    resid = json.loads((ANALYSIS / "RESIDUAL_DIAGNOSTICS.json").read_text())
    assert resid["protocol_deviation"] is False
    assert resid["lagged_input_extension_tested"] is False
    assert resid["target_lag_used"] is False
    assert resid["fallback_trigger_condition_met"] is True
    assert resid["dev_cooling_acf"]["lag_1h"] == pytest.approx(0.8288581320055117)
    assert resid["dev_cooling_acf"]["lag_24h"] == pytest.approx(0.5458957558201557)


def test_posthoc_hvac_audit_cannot_modify_model_artifacts():
    proto = json.loads((MANIFESTS / "HVAC_REGIME_AUDIT_PROTOCOL.json").read_text())
    assert proto["status"] == "POST_HOC_INTERPRETATION_ONLY"
    assert proto["numerical_experiment_frozen"] is True
    hvac = json.loads((ANALYSIS / "HVAC_2024_REGIME_ATTRIBUTION.json").read_text())
    assert hvac["used_for_model_fitting"] is False
    assert hvac["used_to_revise_TEST"] is False
    closed = json.loads((ANALYSIS / "CLOSED_POSTTEST_HYPOTHESES.json").read_text())
    assert closed["epoch_aware_HVAC_model"] == "NOT_FITTED"
    assert closed["lagged_target_model"] == "FORBIDDEN_AND_NOT_USED"
    assert closed["post_TEST_feature_selection"] == "NOT_PERFORMED"


def test_tracked_canonical_status_taxonomy():
    st = json.loads((ANALYSIS / "FINAL_ESIF_FACILITY_OVERHEAD_STATUS.json").read_text())
    rst = json.loads((RESULTS / "FINAL_ESIF_FACILITY_OVERHEAD_STATUS.json").read_text())
    assert st["HOURLY_STRUCTURE"] != "PASS"
    assert st["HOURLY_STRUCTURE"] == "PARTIAL"
    assert st["PUE_ACCOUNTING_CLOSURE"] == "PASS"
    assert st["HVAC_STATIONARY_IT_WEATHER_MODEL"] == "FAIL"
    assert st["HVAC_REGIME_SHIFT"] == "PASS"
    assert st["PUMP_POWER_MODEL"] == "PARTIAL"
    assert st["PUMP_HOURLY_DYNAMICS"] == "FAIL"
    assert st["STATIONARY_IT_WEATHER_TOTAL_AUX_HYPOTHESIS"] == "FAIL"
    assert st["FACILITY_ARCHITECTURE_OPERATIONAL_STATE_DEPENDENCE"] == "STRONGLY_INDICATED"
    assert st["HEAT_REUSE_RESIDUAL_EFFECT"] == "LOW_FOR_TESTED_DIAGNOSTIC"
    assert st["PRINEVILLE_COEFFICIENT_TRANSFER"] == "NOT_ALLOWED"
    assert st["FACILITY_OVERHEAD_FINAL_DISPOSITION"] == "PARTIAL"
    assert st["READY_FOR_HEAT_REJECTION_WATER_WUE"] == "PASS_WITH_BOUNDARY_RESTRICTIONS"
    assert st["water_WUE_modeling_executed"] is False
    assert st["prineville_modified"] is False
    assert st["TEST_driven_model_change"] is False
    assert rst["HOURLY_STRUCTURE"] == "PARTIAL"


def test_original_runner_refuses_refit_after_freeze():
    import run_esif_facility_overhead as runner

    with pytest.raises(SystemExit, match="frozen after post-test closure"):
        runner.main()


def test_no_prineville_or_water_model_execution():
    closure = (FO / "scripts" / "run_facility_overhead_posttest_closure.py").read_text()
    assert "Meta_Prineville" not in closure
    assert "lstsq" not in closure
    assert "def fit_spec" not in closure
    handoff = (DOCS / "HEAT_REJECTION_WATER_HANDOFF.md").read_text()
    assert "hvac_kw" in handoff
    assert "thermal heat rejected" in handoff.lower()
    assert "cooling_kw" in handoff
    for p in FO.rglob("*"):
        assert "prineville" not in p.name.lower()
        assert "wue_model" not in p.name.lower()
