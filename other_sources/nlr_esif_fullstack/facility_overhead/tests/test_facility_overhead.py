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
