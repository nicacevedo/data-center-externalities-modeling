"""Focused tests for the NLR GenAI H100 measurement module."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest

H100 = Path(__file__).resolve().parents[1]
NLR = H100.parent
SCRIPTS = H100 / "scripts"
import sys

sys.path.insert(0, str(SCRIPTS))
from h100_paths import (  # noqa: E402
    ANALYSIS,
    CPU_FROZEN_DISPOSITION,
    CPU_FROZEN_P,
    CPU_STATUS,
    DATA_PROCESSED,
    DOCS,
    GENAI_DOI,
    GENAI_ZIP,
    GENAI_ZIP_BYTES,
    GENAI_ZIP_SHA256,
    MANIFESTS,
    RESULTS,
)

FORBIDDEN_FULL_NODE = (
    "full node power",
    "full-node power",
    "full_node_power",
    "full node AC as CPU+GPU",
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def test_dataset_hash_and_size():
    assert GENAI_ZIP.exists()
    assert GENAI_ZIP.stat().st_size == GENAI_ZIP_BYTES
    prov = json.loads((MANIFESTS / "SOURCE_PROVENANCE.json").read_text())
    assert prov["dataset"]["doi"] == GENAI_DOI
    assert prov["dataset"]["catalog_version"] == 2
    assert prov["dataset"]["sha256"] == GENAI_ZIP_SHA256
    assert prov["dataset"]["redownloaded"] is False
    assert _sha256(GENAI_ZIP) == GENAI_ZIP_SHA256


def test_wattameter_version_unresolved_if_unpinned():
    prov = json.loads((MANIFESTS / "SOURCE_PROVENANCE.json").read_text())
    assert prov["wattameter"]["status"] == "WATTAMETER_VERSION_UNRESOLVED"


def test_archive_member_identity():
    inv = json.loads((MANIFESTS / "ARCHIVE_INVENTORY.json").read_text())
    assert inv["n_members"] == 3191
    csv = pd.read_csv(MANIFESTS / "ARCHIVE_INVENTORY.csv")
    assert len(csv) == 3191
    with zipfile.ZipFile(GENAI_ZIP) as z:
        assert len(z.namelist()) == 3191
        assert "README.md" in z.namelist()


def test_cpu_layer_untouched():
    init = json.loads((MANIFESTS / "H100_INITIAL_STATE.json").read_text())
    st = json.loads(CPU_STATUS.read_text())
    assert st["CPU_LAYER_FINAL_DISPOSITION"] == CPU_FROZEN_DISPOSITION
    assert st["p_KestrelCPU_W_per_node"] == pytest.approx(CPU_FROZEN_P)
    assert st["refit"] is False
    assert init["frozen_kestrel_cpu"]["read_only"] is True
    recorded = init["frozen_kestrel_cpu"]["file_sha256"]
    for rel, digest in recorded.items():
        path = NLR / rel
        assert path.exists()
        assert _sha256(path) == digest


def test_source_reproduction_semantics():
    js = json.loads((ANALYSIS / "SOURCE_REPRODUCTION.json").read_text())
    df = pd.read_csv(ANALYSIS / "SOURCE_REPRODUCTION.csv")
    assert js["n_compared"] == len(df)
    assert js["status"] in {"PASS", "PARTIAL"}
    assert df["pass_mean_5pct"].all()
    assert df["pass_energy_5pct"].all()


def test_units_and_experimental_unit():
    audit = json.loads((ANALYSIS / "EXPERIMENT_DESIGN_AUDIT.json").read_text())
    assert audit["experimental_unit"] == "one independent run/profile/replicate"
    assert audit["high_frequency_samples_are_not_n"] is True
    summary = pd.read_parquet(DATA_PROCESSED / "h100_experiment_summary.parquet")
    assert len(summary) == audit["total_independent_profiles"]
    assert summary["experimental_unit"].eq("independent_run").all()
    train = summary[summary["mode"].str.contains("train")]
    assert train.gpus.eq(train.nodes * 4).all()
    assert train.cpu_sockets.eq(train.nodes * 2).all()
    assert (train.p_compute_W_per_node > 0).all()


def test_no_time_sample_pseudoreplication():
    audit = json.loads((ANALYSIS / "EXPERIMENT_DESIGN_AUDIT.json").read_text())
    n = audit["total_independent_profiles"]
    assert n < 5000
    assert n == (
        audit["training"]["n_independent_runs"]
        + audit["offline_inference"]["n_independent_runs"]
        + audit["online_finite"]["n_independent_runs"]
        + audit["online_rate"]["n_independent_runs"]
    )


def test_cpu_gpu_energy_sum_and_no_double_count():
    split = pd.read_csv(ANALYSIS / "H100_TRAINING_GPU_CPU_SPLIT.csv")
    # source-aggregated training jobs only (exclude unaaggregated SD 1-node extras if present)
    agg = split[split.n_nodes_from_logs >= 2]
    assert not agg.double_count_gpu.any()
    assert (agg.n_gpu_device_columns == agg.expected_devices).all()
    recon = agg.E_GPU_Wh + agg.E_CPU_Wh
    assert (abs(recon - agg.E_compute_native_Wh) / agg.E_compute_native_Wh < 1e-12).all()
    assert agg.time_monotonic.all()


def test_native_vs_resampled_energy_conservation():
    df = pd.read_csv(ANALYSIS / "SOURCE_REPRODUCTION.csv")
    # interpolation/sync gap should be small relative to energy, not silently huge
    assert df["native_vs_source_energy_rel"].abs().max() < 0.08


def test_no_full_node_label_on_cpu_gpu():
    texts = []
    for p in (
        DOCS / "H100_MEASUREMENT_BOUNDARY.md",
        DOCS / "H100_POWER_REPORT.md",
        RESULTS / "FINAL_H100_POWER_STATUS.json",
        MANIFESTS / "H100_MODEL_PROTOCOL_FREEZE.json",
    ):
        texts.append(p.read_text().lower())
    blob = "\n".join(texts)
    assert "measured_compute" in blob or "measured compute" in blob
    assert "p_other_node" in blob
    st = json.loads((RESULTS / "FINAL_H100_POWER_STATUS.json").read_text())
    assert st["FULL_NODE_AC_POWER"] == "UNSUPPORTED"
    assert st["P_other_node"] == "UNRESOLVED"


def test_workload_and_node_mapping():
    proto = json.loads((MANIFESTS / "H100_MODEL_PROTOCOL_FREEZE.json").read_text())
    assert proto["node_count_analysis"]["mlperf_training_scaling"] == "WEAK_SCALING_INCREASING_GLOBAL_BATCH"
    assert proto["experimental_unit"] == "ONE_INDEPENDENT_RUN_OR_PROFILE"
    intensity = pd.read_csv(ANALYSIS / "H100_INTENSITY_BY_RUN.csv")
    assert set(intensity.loc[intensity["mode"].str.contains("train"), "nodes"].unique()) <= {2, 4, 8, 16}


def test_no_historical_h100_population():
    xw = json.loads((ANALYSIS / "H100_KESTREL_CROSSWALK.json").read_text())
    assert xw["no_inferred_matches"] is True
    assert xw["historical_h100_replay"] == "NOT_PERFORMED"
    st = json.loads((RESULTS / "FINAL_H100_POWER_STATUS.json").read_text())
    assert st["HISTORICAL_H100_REPLAY"] == "NOT_NEEDED"
    assert st["HISTORICAL_H100_JOB_CROSSWALK"] in {"PASS", "PARTIAL"}
    assert xw["training"]["status"] == "EXACT_CROSSWALK"
    init = json.loads((MANIFESTS / "H100_INITIAL_STATE.json").read_text())
    assert init["constraints"]["do_not_populate_historical_h100_jobs"] is True
    assert init["constraints"]["no_meta_access"] is True


def test_protocol_frozen_before_models():
    proto = json.loads((MANIFESTS / "H100_MODEL_PROTOCOL_FREEZE.json").read_text())
    assert proto["candidate_pooling_hierarchy_batch_like"]["start_at"]
    cmp = json.loads((ANALYSIS / "H100_MODEL_COMPARISON.json").read_text())
    assert cmp["tautological_E_vs_Nt_not_used_for_selection"] is True
    assert cmp["parsimony_rule_applied"] is True
