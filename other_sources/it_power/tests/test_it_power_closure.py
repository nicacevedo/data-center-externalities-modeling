"""Focused tests for IT-power closure. Does not refit models."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

IT = Path(__file__).resolve().parents[1]
NLR = IT.parent / "nlr_esif_fullstack"
H100 = NLR / "genai_h100"
import sys

sys.path.insert(0, str(IT / "scripts"))
from it_power_paths import (  # noqa: E402
    ANALYSIS,
    CPU_DISPOSITION,
    CPU_FREEZE,
    CPU_STATUS,
    FIGSHARE_SHA256,
    FIGSHARE_ZIP,
    GENAI_SHA256,
    GENAI_ZIP,
    H100_RUNNER,
    MANIFESTS,
    NEWKIRK_ZIP,
    NEWKIRK_ZIP_SHA256,
)


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def test_cpu_frozen_unchanged():
    init = json.loads((MANIFESTS / "IT_POWER_CLOSURE_INITIAL_STATE.json").read_text())
    st = json.loads(CPU_STATUS.read_text())
    assert st["CPU_LAYER_FINAL_DISPOSITION"] == CPU_DISPOSITION
    assert st["p_KestrelCPU_W_per_node"] == pytest.approx(700.6894574294788)
    assert st["refit"] is False
    assert init["cpu"]["read_only"] is True
    freeze = json.loads(CPU_FREEZE.read_text())
    assert freeze["EX_POST_CPU"]["p_hat_W_per_node"] == pytest.approx(700.6894574294788)


def test_nlr_dataset_hash_unchanged():
    init = json.loads((MANIFESTS / "IT_POWER_CLOSURE_INITIAL_STATE.json").read_text())
    assert init["file_sha256"]["genai_zip"] == GENAI_SHA256
    assert _sha(GENAI_ZIP) == GENAI_SHA256


def test_sd_n1_provenance():
    df = pd.read_csv(H100 / "analysis" / "H100_SD_N1_RECONSTRUCTED.csv")
    assert df.provenance.eq("RAW_RECONSTRUCTED_SOURCE_RUN").all()
    assert df.not_author_supplied_aggregate.all()
    assert df.nodes.eq(1).all()
    assert len(df) >= 4
    freeze = json.loads((H100 / "manifests" / "H100_COMPUTE_FINAL_FREEZE.json").read_text())
    assert freeze["final_experiment_count"]["sd_n1_raw_reconstructed"] == len(df)


def test_rapl_package_vs_source_distinguished():
    rapl = json.loads((H100 / "analysis" / "H100_RAPL_PHYSICAL_ACCOUNTING.json").read_text())
    assert rapl["source_reproduction_cpu_definition"].startswith("package + core")
    assert rapl["preferred_physical_cpu"] == "package only"
    assert rapl["refit_because_of_this"] is False
    assert rapl["max_pct_of_cpu_gpu_compute_energy"] < 0.01


def test_no_time_sample_pseudoreplication():
    freeze = json.loads((H100 / "manifests" / "H100_COMPUTE_FINAL_FREEZE.json").read_text())
    assert freeze["final_experiment_count"]["experimental_unit"] == "independent_run_not_time_sample"
    ind = json.loads((ANALYSIS / "INDEPENDENT_H100_B200_REPLICATION.json").read_text())
    assert ind["experimental_unit"] == "independent_session"
    assert ind["n_sessions"] < 100
    assert ind["n_sessions"] == ind["n_H100"] + ind["n_B200"]


def test_h100_b200_holdout_and_no_silent_reuse():
    ind = json.loads((ANALYSIS / "INDEPENDENT_H100_B200_REPLICATION.json").read_text())
    assert ind["transfer"]["H100_to_B200"]["note"].startswith("H100 M1")
    assert ind["transfer"]["B200_to_H100"]["note"].startswith("B200 M1")
    assert ind["transfer"]["H100_M1"]["a"] != pytest.approx(ind["transfer"]["B200_M1"]["a"], rel=0.001)
    assert ind["rtx3060_processed"] is False


def test_latif_newkirk_not_independent():
    bank = pd.read_csv(ANALYSIS / "H100_FULL_NODE_EVIDENCE_BANK.csv")
    latif = bank[bank.source_id == "LATIF_2025_IEEE_ACCESS"].iloc[0]
    bnl = bank[bank.source_id == "NEWKIRK_BNL_OVERLAP"].iloc[0]
    assert latif.data_lineage_id == bnl.data_lineage_id
    nk = json.loads((ANALYSIS / "NEWKIRK_SOURCE_REPRODUCTION.json").read_text())
    assert nk["bnl_is_latif"] is True


def test_no_naive_8_to_4_calibration():
    env = json.loads((ANALYSIS / "H100_NODE_BOUNDARY_BRIDGE.json").read_text())
    assert env["label"] == "EXTERNAL_H100_NODE_BOUNDARY_ENVELOPE"
    assert env["not"] == "KESTREL_CALIBRATED"
    assert "halve_8gpu_node" in env["forbidden_operations_not_done"]
    assert env["KESTREL_H100_FULL_NODE"] == "PARTIAL_EXTERNAL_ENVELOPE"


def test_no_tdp_as_measured():
    bank = pd.read_csv(ANALYSIS / "H100_FULL_NODE_EVIDENCE_BANK.csv")
    nlr = bank[bank.source_id == "NLR_GENAI_H100_COMPUTE"].iloc[0]
    assert nlr.boundary == "CPU+GPU compute"
    assert str(nlr.notes).startswith("NOT full-node")
    freeze = json.loads((H100 / "manifests" / "H100_COMPUTE_FINAL_FREEZE.json").read_text())
    assert "not full-node" in freeze["measurement_boundary"]


def test_no_literature_fit_to_nlr():
    freeze = json.loads((H100 / "manifests" / "H100_COMPUTE_FINAL_FREEZE.json").read_text())
    assert freeze["nlr_coefficients_will_not_be_refit_to_external_node_data"] is True


def test_no_historical_h100_replay():
    init = json.loads((MANIFESTS / "IT_POWER_CLOSURE_INITIAL_STATE.json").read_text())
    assert init["constraints"]["do_not_populate_historical_h100_jobs"] is True
    st = json.loads((ANALYSIS / "FINAL_IT_POWER_STATUS.json").read_text())
    assert st["same_system_bridge_run"] is False


def test_no_cooling_weather_or_meta():
    init = json.loads((MANIFESTS / "IT_POWER_CLOSURE_INITIAL_STATE.json").read_text())
    assert init["constraints"]["do_not_fit_cooling_weather"] is True
    assert init["constraints"]["no_meta_access"] is True
    st = json.loads((ANALYSIS / "FINAL_IT_POWER_STATUS.json").read_text())
    assert "cooling" in st["next_layer_recommended_not_executed"]


def test_independent_provenance_file():
    prov = json.loads((MANIFESTS / "INDEPENDENT_GPU_SOURCE_PROVENANCE.json").read_text())
    assert prov["source_doi"] == "10.1038/s41597-026-07496-6"
    assert prov["figshare_doi"] == "10.6084/m9.figshare.31654879"
    assert prov["sha256"] == FIGSHARE_SHA256
    assert prov["rtx3060_processed"] is False
    assert prov["unique_node_session_files"] == 32
    assert "CC BY-NC-ND" in prov["license"]


def test_envelope_does_not_halve_8gpu_as_kestrel():
    env = json.loads((ANALYSIS / "H100_NODE_BOUNDARY_BRIDGE.json").read_text())
    assert "illustrative_unrelated_idle_overhead_4gpu_W" not in env.get("envelope", {})
    csv = pd.read_csv(ANALYSIS / "H100_NODE_BOUNDARY_BRIDGE.csv")
    assert "external_unrelated_idle_illustration" not in set(csv.regime)
    assert env["envelope"]["external_scenario_high"] == "NOT IDENTIFIED for the 4-GPU Kestrel node"


def test_cpu_artifact_hashes_unchanged():
    init = json.loads((MANIFESTS / "IT_POWER_CLOSURE_INITIAL_STATE.json").read_text())

    def _sha(p: Path) -> str:
        h = hashlib.sha256()
        with p.open("rb") as f:
            for c in iter(lambda: f.read(1 << 20), b""):
                h.update(c)
        return h.hexdigest()

    assert _sha(CPU_STATUS) == init["file_sha256"]["cpu_status"]
    assert _sha(CPU_FREEZE) == init["file_sha256"]["cpu_freeze"]
    assert _sha(H100_RUNNER) == init["file_sha256"]["h100_runner"]
    assert _sha(GENAI_ZIP) == init["file_sha256"]["genai_zip"]
    assert _sha(FIGSHARE_ZIP) == FIGSHARE_SHA256
    assert _sha(NEWKIRK_ZIP) == NEWKIRK_ZIP_SHA256


def test_saturated_anchor_is_ex_ante_not_default():
    sat = json.loads((H100 / "analysis" / "H100_SATURATED_ANCHOR.json").read_text())
    assert sat["not_a_universal_default"] is True
    assert "not observed watts" in sat["SATURATED_COMPUTE_SCENARIO_ANCHOR"]["definition_ex_ante"]
    freeze = json.loads((H100 / "manifests" / "H100_COMPUTE_FINAL_FREEZE.json").read_text())
    assert freeze["canonical_batch"].startswith("E_compute = p_{w,N}")
