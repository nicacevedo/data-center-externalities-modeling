"""Guards for PRN1 Q2-2012 public validation. No fitting, no proxy-freeze overwrite."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from holdout_guard import HoldoutAccessError, HoldoutGuard  # noqa: E402

OUT = ROOT / "outputs" / "prn1_q2_2012_public_validation_v1"
PROXY_FREEZE = ROOT / "outputs/public_proxy_reconstruction_v1/preoutcome/PUBLIC_PROXY_RECONSTRUCTION_FREEZE.json"

V1 = "f9649c489196cdc3e617f5b28574334aaaace5a94e7ade5ce461f6da22809a6a"
V1_FREEZE = "decd095f59cc2249eee66d5b94ad30d30a53555eadbec3358bbb9aa80caaa81d"
CPU = "1f57b210a63d375ce8eff7d5043756ffe6efe04e8a408bf9429bfd10096528d9"
H100 = "a620d649a932f2388aa2f35bac2730eb75fe1dc74529668de4f30ee814600076"
ESIF = "4e01139dd9365f62824ac00ff944468839e7873e47a5cea3df4714854af1b02c"


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def test_structural_v1_and_upstream_unchanged():
    assert _sha(ROOT / "src/prineville_structural_v1.py") == V1
    assert _sha(ROOT / "outputs/structural_revision_v1/PRINEVILLE_STRUCTURAL_REFERENCE_V1_FREEZE.json") == V1_FREEZE
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/analysis/FINAL_KESTREL_CPU_STATUS.json") == CPU
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/genai_h100/manifests/H100_COMPUTE_FINAL_FREEZE.json") == H100
    assert _sha(REPO / "other_sources/nlr_esif_fullstack/heat_rejection_water/manifests/ESIF_HEAT_WATER_RESULT_FREEZE.json") == ESIF


def test_public_proxy_freeze_unchanged():
    freeze = json.loads(PROXY_FREEZE.read_text())
    assert freeze["master_hash"] == "137c79fdc151503ab158663f0c5e5e10a98e6de5f03942b49f02cfade808b908"
    run = json.loads((OUT / "RUN_STATUS.json").read_text())
    assert run["public_proxy_freeze_unchanged"] is True


def test_no_annual_or_holdout_meta_water_in_this_pass():
    with HoldoutGuard(ROOT):
        with pytest.raises(HoldoutAccessError):
            (ROOT / "data/canonical/meta_prineville_annual.csv").open("r")
        with pytest.raises(HoldoutAccessError):
            (ROOT / "outputs/conditional_annual_compare.csv").open("r")
    init = json.loads((OUT / "INITIAL_STATE.json").read_text())
    assert "meta_prineville_annual.csv" in " ".join(init["protected_paths"])


def test_topology_B_removed_product_return_confirmed():
    bal = json.loads((OUT / "EARLY_PRN1_CONFIRMED_WATER_BALANCE.json").read_text())
    assert bal["RECIRCULATION_TOPOLOGY"] == "PRODUCT_STORAGE_RETURN_CONFIRMED"
    assert bal["steady_state"]["P = E"] is True
    assert bal["steady_state"]["not_1.392_topology"] is True
    assert bal["steady_state"]["not_E_over_0.85"] is True


def test_ro_discrepancy_preserved():
    bal = json.loads((OUT / "EARLY_PRN1_CONFIRMED_WATER_BALANCE.json").read_text())
    assert bal["RO_RECOVERY_SOURCE_STATE"] == "DISCREPANT_{0.67,0.75}"
    assert 0.67 in bal["r_values_evaluated"] and 0.75 in bal["r_values_evaluated"]


def test_wue_boundary_not_silently_assumed():
    b = json.loads((OUT / "Q2_2012_WUE_BOUNDARY_STATUS.json").read_text())
    assert b["status"] == "PARTIAL_UNRESOLVED"
    ids = {h["id"] for h in b["discrete_hypotheses"]}
    assert ids == {"RAW_COOLING_WATER_INPUT", "RO_PRODUCT_OR_ECH_MAKEUP"}


def test_q2_2012_prn1_only():
    c = json.loads((OUT / "PUBLIC_PROXY_V1_CORRECTIONS.json").read_text())
    assert any("PRN1_ONLY" in x["corrected_claim"] for x in c["corrections"])


def test_prn4_not_hard_operational_2014():
    text = (OUT / "OPERATING_STATUS_ONTOLOGY.md").read_text()
    assert "PRN4" in text and "2016" in text
    assert "NOT hard-activated" in text


def test_no_numeric_pseudo_voi_placeholders():
    voi = pd.read_csv(OUT / "REVISED_INFORMATION_PRIORITY.csv")
    assert "normalized_range_reduction" not in voi.columns
    allowed = {
        "VERY_HIGH",
        "HIGH",
        "MEDIUM",
        "LOW",
        "VERY_HIGH_for_campus_not_for_this_Q2_test",
    }
    assert set(voi["expected_information_value"]).issubset(allowed)
    assert not {1.0, 0.8, 0.7}.intersection(set(voi["expected_information_value"]))


def test_ro_discrepancy_not_interpolated():
    d = json.loads((OUT / "RO_RECOVERY_DISCREPANCY.json").read_text())
    assert d["RO_RECOVERY_SOURCE_STATE"] == "DISCREPANT_{0.67,0.75}"
    assert d["not_a_probability_distribution"] is True
    assert d["not_replaced_by_hard_75pct"] is True


def test_proxy_freeze_file_hash():
    assert _sha(PROXY_FREEZE) == "1d88ba5c3429d0978e64e9caea9b7b9d2cfe5287bf3fb3c2afbb5b81b0a699e2"


def test_intensity_invariant_to_it_mw():
    n = pd.read_csv(OUT / "NORMALIZATION_TEST_RESULTS.csv")
    assert (n["max_abs_diff_vs_1MW"] < 1e-9).all()


def test_benchmark_did_not_modify_prebenchmark_freeze():
    pre = json.loads((OUT / "PREBENCHMARK_OUTPUT_FREEZE.json").read_text())
    cons = json.loads((OUT / "Q2_2012_EXTERNAL_CONSISTENCY_RESULTS.json").read_text())
    assert cons["prebenchmark_output_freeze_hash"] == pre["master_hash"]
    assert cons["no_retune"] is True
    assert cons["no_winner_selected"] is True


def test_no_scenario_selected_by_wue_error():
    df = pd.read_csv(OUT / "Q2_2012_EXTERNAL_CONSISTENCY_RESULTS.csv")
    assert (~df["selected_as_winner"].astype(bool)).all()


def test_no_parameter_fit():
    run = json.loads((OUT / "RUN_STATUS.json").read_text())
    assert run["no_fit"] is True
    spec = json.loads((OUT / "PRN1_Q2_2012_PREBENCHMARK_FREEZE.json").read_text())
    assert "deltaT" in spec["not_chosen_using_0.22"]
