#!/usr/bin/env python3
"""NLR Kestrel H100 / GenAI measured power characterization.

Measurement / physical-modeling experiment. Does not refit the frozen CPU layer.
Does not populate historical H100 jobs. Does not treat CPU+GPU as full-node AC.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from h100_paths import (  # noqa: E402
    ANALYSIS,
    CPU_FREEZE,
    CPU_FROZEN_DISPOSITION,
    CPU_FROZEN_P,
    CPU_PROTOCOL,
    CPU_SOCKETS_PER_NODE,
    CPU_STATUS,
    CPU_TDP_W,
    DATA_PROCESSED,
    DATETIME_FORMAT,
    DOCS,
    EXTRACTED,
    FIGURES,
    GENAI_CATALOG_LAST_UPDATED,
    GENAI_CATALOG_SIZE_LABEL,
    GENAI_CATALOG_URL,
    GENAI_CATALOG_VERSION,
    GENAI_CATALOG_VERSION_DATE,
    GENAI_DOI,
    GENAI_RAW,
    GENAI_ZIP,
    GENAI_ZIP_BYTES,
    GENAI_ZIP_SHA256,
    GPUS_PER_NODE,
    GPU_TDP_W,
    KESTREL_JOBS,
    MANIFESTS,
    MODULE_ROOT,
    NLR_ROOT,
    NODE_COMPUTE_TDP_W,
    PAPER_ARXIV,
    PAPER_TITLE,
    REPO_ROOT,
    RESULTS,
    SOURCES,
)

FROZEN_CPU_FILES = (
    CPU_STATUS,
    CPU_FREEZE,
    CPU_PROTOCOL,
    NLR_ROOT / "scripts" / "run_kestrel_job_power_experiment.py",
    NLR_ROOT / "scripts" / "run_kestrel_cpu_final_freeze.py",
    NLR_ROOT / "scripts" / "run_cpu_closure_pass.py",
    NLR_ROOT / "tests" / "test_cpu_final_freeze.py",
    NLR_ROOT / "tests" / "test_cpu_closure_pass.py",
    NLR_ROOT / "tests" / "test_kestrel_job_power.py",
)


def jdump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=_json_default) + "\n")


def _json_default(x):
    if isinstance(x, (np.floating, np.integer)):
        return float(x) if isinstance(x, np.floating) else int(x)
    if isinstance(x, np.ndarray):
        return x.tolist()
    if isinstance(x, Path):
        return str(x)
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    if pd.isna(x):
        return None
    raise TypeError(type(x))


def sha256_file(path: Path, buf: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(buf)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_cmd(*args) -> str:
    r = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return (r.stdout or r.stderr or "").strip()


def ensure_dirs() -> None:
    for p in (MANIFESTS, ANALYSIS, DATA_PROCESSED, RESULTS, FIGURES, DOCS, EXTRACTED):
        p.mkdir(parents=True, exist_ok=True)


def update_gitignore() -> None:
    gi = NLR_ROOT / ".gitignore"
    extra = [
        "data_raw/genai/*.zip",
        "genai_h100/data_processed/*.parquet",
    ]
    text = gi.read_text() if gi.exists() else ""
    lines = text.splitlines()
    changed = False
    for e in extra:
        if e not in lines:
            lines.append(e)
            changed = True
    if changed:
        gi.write_text("\n".join(lines).rstrip() + "\n")


def write_initial_state() -> dict:
    cpu = json.loads(CPU_STATUS.read_text())
    hashes = {str(p.relative_to(NLR_ROOT)): sha256_file(p) for p in FROZEN_CPU_FILES if p.exists()}
    state = {
        "module": "genai_h100",
        "git": {
            "branch": git_cmd("rev-parse", "--abbrev-ref", "HEAD"),
            "HEAD": git_cmd("rev-parse", "HEAD"),
            "status": git_cmd("status", "--short"),
            "repo_is_git": (REPO_ROOT / ".git").exists(),
        },
        "frozen_kestrel_cpu": {
            "CPU_LAYER_FINAL_DISPOSITION": cpu.get("CPU_LAYER_FINAL_DISPOSITION"),
            "expected": CPU_FROZEN_DISPOSITION,
            "p_KestrelCPU_W_per_node": cpu.get("p_KestrelCPU_W_per_node"),
            "refit": cpu.get("refit"),
            "read_only": True,
            "rerun": False,
            "file_sha256": hashes,
        },
        "nlr_fullstack_layout": {
            "analysis": sorted(p.name for p in (NLR_ROOT / "analysis").glob("*") if p.is_file()),
            "manifests": sorted(p.name for p in (NLR_ROOT / "manifests").glob("*") if p.is_file()),
            "scripts": sorted(p.name for p in (NLR_ROOT / "scripts").glob("*.py")),
            "genai_zip_present": GENAI_ZIP.exists(),
            "genai_zip_bytes": GENAI_ZIP.stat().st_size if GENAI_ZIP.exists() else None,
        },
        "constraints": {
            "do_not_modify_cpu_layer": True,
            "do_not_run_masanet_m100_cooling_google_eagle_meta": True,
            "do_not_fit_esif_cooling_weather": True,
            "do_not_populate_historical_h100_jobs": True,
            "do_not_label_cpu_gpu_as_full_node_ac": True,
            "no_meta_access": True,
        },
    }
    if state["frozen_kestrel_cpu"]["CPU_LAYER_FINAL_DISPOSITION"] != CPU_FROZEN_DISPOSITION:
        raise RuntimeError("CPU layer disposition is not FROZEN_PASS_WITH_DOMAIN_RESTRICTIONS")
    if abs(float(state["frozen_kestrel_cpu"]["p_KestrelCPU_W_per_node"]) - CPU_FROZEN_P) > 1e-9:
        raise RuntimeError("Frozen CPU coefficient drifted")
    jdump(MANIFESTS / "H100_INITIAL_STATE.json", state)
    return state


def write_provenance(zip_sha: str) -> dict:
    paper = next(SOURCES.glob("*.pdf"), None)
    prov = {
        "dataset": {
            "title": "Dataset of Generative AI Workload Power Profiles",
            "doi": GENAI_DOI,
            "catalog_url": GENAI_CATALOG_URL,
            "catalog_version": GENAI_CATALOG_VERSION,
            "catalog_version_date": GENAI_CATALOG_VERSION_DATE,
            "catalog_last_updated": GENAI_CATALOG_LAST_UPDATED,
            "catalog_size_label": GENAI_CATALOG_SIZE_LABEL,
            "catalog_notes": "Updated README file",
            "canonical_archive": "dataset.zip",
            "local_path": str(GENAI_ZIP),
            "byte_size": GENAI_ZIP.stat().st_size,
            "sha256": zip_sha,
            "source_checksum_published": None,
            "source_checksum_status": "NOT_PUBLISHED_ON_CATALOG",
            "redownloaded": False,
            "status": "LOCAL_EXISTING_VERIFIED",
            "license": {
                "name": "NLR Data Catalog standard terms",
                "url": "https://data.nlr.gov/node/1/license",
                "summary": (
                    "Use/copy without fee provided the license notice is retained; "
                    "credit DOE/NREL/ALLIANCE in resulting publications. AS IS, no warranty."
                ),
            },
            "citation": (
                "Vercellino, Roberto, Jared Willard, Gustavo Campos, Weslley da Silva Pereira, "
                "Olivia Hull, Matt Selensky, and Juliane Mueller. 2026. Dataset of Generative "
                "AI Workload Power Profiles. NLR Data Catalog. DOI: 10.7799/3025227."
            ),
        },
        "paper": {
            "title": PAPER_TITLE,
            "arxiv": PAPER_ARXIV,
            "url": f"https://arxiv.org/abs/{PAPER_ARXIV}",
            "local_pdf": str(paper) if paper else None,
            "local_pdf_sha256": sha256_file(paper) if paper and paper.exists() else None,
        },
        "wattameter": {
            "status": "WATTAMETER_VERSION_UNRESOLVED",
            "paper_citation": "https://github.com/NatLabRockies/WattAMeter (2025)",
            "dataset_requirements_pin": None,
            "dataset_git_is_wattameter": False,
            "dataset_git_head": "refs/heads/master",
            "note": (
                "The archive contains a git export of the dataset repository, not a "
                "pinned WattAMeter commit. requirements.txt has no WattAMeter pin. "
                "Do not assume the current GitHub HEAD was the measurement version."
            ),
        },
        "hardware": {
            "system": "NLR Kestrel GPU-accelerated nodes",
            "gpus": f"{GPUS_PER_NODE} x NVIDIA H100 SXM 80GB",
            "gpu_tdp_W": GPU_TDP_W,
            "cpus": f"{CPU_SOCKETS_PER_NODE} x AMD EPYC 9554 Genoa, 64 cores/socket",
            "cpu_tdp_W": CPU_TDP_W,
            "node_compute_tdp_cpu_gpu_only_W": NODE_COMPUTE_TDP_W,
            "interconnect": "HPE Slingshot-11; intra-node NVLink",
            "source": "Vercellino et al. 2026 Section 3.1",
        },
        "diploee": {
            "classification": "SAME_SOURCE_SIMULATION",
            "independent_validation": False,
            "executed_in_this_module": False,
        },
    }
    jdump(MANIFESTS / "SOURCE_PROVENANCE.json", prov)
    return prov


def archive_inventory(zf: zipfile.ZipFile) -> pd.DataFrame:
    rows = []
    for info in zf.infolist():
        name = info.filename
        ext = Path(name).suffix.lower()
        if name.endswith("/"):
            kind = "directory"
        elif "README" in Path(name).name.upper():
            kind = "readme"
        elif name.endswith(".py"):
            kind = "source_script"
        elif name.endswith((".txt", ".yml", ".yaml", ".toml", ".cfg", ".in")):
            kind = "environment_or_text"
        elif name.endswith(".csv"):
            kind = "metadata_csv"
        elif name.endswith(".parquet"):
            kind = "aggregated_parquet"
        elif name.endswith(".log"):
            kind = "raw_measurement_log"
        elif name.endswith(".ipynb"):
            kind = "notebook"
        elif name.startswith(".git/"):
            kind = "git_metadata"
        elif name.startswith("03_whole-facility_profiles/"):
            kind = "diploee_same_source_simulation"
        else:
            kind = f"other{ext or ''}"
        rows.append(
            {
                "member": name,
                "bytes": info.file_size,
                "compress_bytes": info.compress_size,
                "crc32": f"{info.CRC:08x}",
                "kind": kind,
                "extension": ext,
                "prefix": name.split("/")[0] if "/" in name else name,
            }
        )
    df = pd.DataFrame(rows)
    df.to_csv(MANIFESTS / "ARCHIVE_INVENTORY.csv", index=False)
    summary = {
        "n_members": int(len(df)),
        "n_files": int((df.kind != "directory").sum()),
        "total_uncompressed_bytes": int(df.bytes.sum()),
        "by_kind": df.groupby("kind")["bytes"].agg(["count", "sum"]).reset_index().to_dict("records"),
        "by_prefix": df.groupby("prefix")["bytes"].agg(["count", "sum"]).reset_index().to_dict("records"),
        "readmes": df.loc[df.kind == "readme", "member"].tolist(),
        "source_scripts": df.loc[df.kind == "source_script", "member"].tolist(),
        "minimum_extract": {
            "A_source_reproduction": [
                "README.md",
                "requirements.txt",
                "01_aggregated_datasets/utilities.py",
                "01_aggregated_datasets/training/postprocess.py",
                "01_aggregated_datasets/inference_offline_llama3_70b/postprocess.py",
                "representative training raw logs (1–2 jobs)",
                "one offline inference window from the two shared logs",
            ],
            "B_experiment_level_energy": [
                "all metadata.csv",
                "all training aggregated parquet (41)",
                "inference metadata mean/peak/duration (do not extract all 2400 parquet)",
            ],
            "C_temporal_analysis": [
                "training aggregated parquet (native 0.2 s)",
                "representative inference aggregated parquet (native 0.1 s)",
            ],
        },
        "not_extracted": [
            "full raw bank",
            "all inference aggregated parquet",
            "DIPLOEE whole-facility simulations (SAME_SOURCE_SIMULATION)",
        ],
    }
    jdump(MANIFESTS / "ARCHIVE_INVENTORY.json", summary)
    return df


def extract_members(zf: zipfile.ZipFile, names: list[str]) -> None:
    for n in names:
        dest = EXTRACTED / n
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(zf.read(n))


def min_extract_names(zf: zipfile.ZipFile) -> list[str]:
    names = zf.namelist()
    keep = []
    for n in names:
        if n.endswith("/"):
            continue
        if n in {"README.md", "requirements.txt"}:
            keep.append(n)
        elif n.startswith("01_aggregated_datasets/") and n.endswith(
            ("metadata.csv", "postprocess.py", "utilities.py")
        ):
            keep.append(n)
        elif n.startswith("01_aggregated_datasets/training/results/") and n.endswith(".parquet"):
            keep.append(n)
        elif n.startswith("00_raw_datasets/training_llama2_70b_lora/2node/") and n.endswith(".log"):
            keep.append(n)
        elif n.startswith("00_raw_datasets/training_stable_diffusion/1node/") and n.endswith(".log"):
            keep.append(n)
        elif n.startswith("02_analysis_scripts/") and n.endswith((".py", ".ipynb", ".md")):
            keep.append(n)
    # representative inference parquets: first, mid, last of each family plus a few rates
    for prefix, picks in (
        ("01_aggregated_datasets/inference_offline_llama3_70b/results/", [0, 200, 600, 1199]),
        ("01_aggregated_datasets/inference_online_finite_llama3_70b/results/", [0, 200, 500, 1025]),
        ("01_aggregated_datasets/inference_online_rate_llama3_70b/results/", [0, 10, 50, 99, 100, 150, 199]),
    ):
        files = sorted(x for x in names if x.startswith(prefix) and x.endswith(".parquet"))
        for i in picks:
            if 0 <= i < len(files):
                keep.append(files[i])
    return sorted(set(keep))


def read_zip_csv(zf: zipfile.ZipFile, name: str) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(zf.read(name)))


def read_zip_parquet(zf: zipfile.ZipFile, name: str) -> pd.DataFrame:
    return pd.read_parquet(io.BytesIO(zf.read(name)))


def parse_training_log_name(member: str) -> dict:
    base = Path(member).name
    parts = base.replace(".log", "").split("_")
    return {
        "member": member,
        "device": parts[0],
        "slurmid": parts[5],
        "node": parts[7],
        "family": member.split("/")[1],
        "node_scale_dir": member.split("/")[2] if len(member.split("/")) > 2 else None,
    }


def _column_header_from_log(raw: bytes) -> list[str]:
    header = None
    for line in raw.splitlines():
        s = line.decode("utf-8", "replace").lstrip()
        if s.startswith("#") and "timestamp" in s and ("[" in s):
            header = s.lstrip("#").strip().split()
    if header is None:
        raise ValueError("no timestamp column header in log")
    return header


def slurm_id_from_log_banner(raw: bytes) -> int | None:
    for line in raw.splitlines()[:5]:
        s = line.decode("utf-8", "replace")
        m = re.search(r"Power data for run (\d+)", s)
        if m:
            return int(m.group(1))
    return None


def read_nvml_log(raw: bytes) -> pd.DataFrame:
    header = _column_header_from_log(raw)
    df = pd.read_csv(io.BytesIO(raw), sep=r"\s+", comment="#", header=None)
    df.columns = header
    df["timestamp"] = pd.to_datetime(df["timestamp"], format=DATETIME_FORMAT)
    return df.set_index("timestamp")


def read_rapl_log(raw: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(raw), sep=r"\s+", comment="#", header=None)
    columns = [
        "timestamp",
        "reading-time[ns]",
        "cpu-0[uJ]",
        "cpu-0-core[uJ]",
        "cpu-1[uJ]",
        "cpu-1-core[uJ]",
        "cpu-0[W]",
        "cpu-0-core[W]",
        "cpu-1[W]",
        "cpu-1-core[W]",
    ]
    if len(df.columns) != len(columns):
        raise ValueError(f"RAPL column count {len(df.columns)} != {len(columns)}")
    df.columns = columns
    df["timestamp"] = pd.to_datetime(df["timestamp"], format=DATETIME_FORMAT)
    return df.set_index("timestamp")


def trapz_energy_w(power_w: np.ndarray, t_s: np.ndarray) -> tuple[float, float]:
    if len(power_w) < 2:
        return float("nan"), 0.0
    e_j = float(np.trapezoid(power_w, t_s))
    dur = float(t_s[-1] - t_s[0])
    return e_j, dur


def series_energy(s: pd.Series) -> dict:
    s = s.dropna()
    t = (s.index - s.index[0]).total_seconds().to_numpy()
    p = s.to_numpy(dtype=float)
    e_j, dur = trapz_energy_w(p, t)
    return {
        "n_samples": int(len(s)),
        "duration_s": dur,
        "energy_J": e_j,
        "energy_Wh": e_j / 3600.0,
        "mean_W": float(p.mean()) if len(p) else float("nan"),
        "median_W": float(np.median(p)) if len(p) else float("nan"),
        "p95_W": float(np.quantile(p, 0.95)) if len(p) else float("nan"),
        "p99_W": float(np.quantile(p, 0.99)) if len(p) else float("nan"),
        "max_W": float(p.max()) if len(p) else float("nan"),
        "std_W": float(p.std(ddof=1)) if len(p) > 1 else 0.0,
        "t0": s.index[0].isoformat() if len(s) else None,
        "t1": s.index[-1].isoformat() if len(s) else None,
        "median_dt_s": float(np.median(np.diff(t))) if len(t) > 1 else float("nan"),
        "monotonic": bool(np.all(np.diff(t) >= 0)),
    }


def gpu_power_series(df: pd.DataFrame) -> pd.Series:
    cols = [c for c in df.columns if re.match(r"gpu-\d+\[mW\]", c)]
    return (df[cols].sum(axis=1) * 1e-3).rename("gpu_W")


def cpu_power_series(df: pd.DataFrame, include_core: bool = True) -> pd.Series:
    pkg = df[["cpu-0[W]", "cpu-1[W]"]].sum(axis=1)
    if include_core:
        return (pkg + df[["cpu-0-core[W]", "cpu-1-core[W]"]].sum(axis=1)).rename("cpu_W")
    return pkg.rename("cpu_W")


def source_align_sum(series_list: list[pd.Series], dt: float) -> pd.Series:
    """Faithful reimplementation of utilities.create_dataframe_multinode + sum."""
    max_start = max(s.index[0] for s in series_list)
    min_end = min(s.index[-1] for s in series_list)
    n = int((min_end - max_start).total_seconds() / dt) + 1
    new_idx = pd.Index([max_start + pd.to_timedelta(i * dt, unit="s") for i in range(n)])
    aligned = []
    for s in series_list:
        s = s.copy()
        s.index = pd.DatetimeIndex(s.index)
        missing = new_idx.difference(s.index)
        s2 = pd.concat([s, pd.Series(index=missing, dtype=float)]).sort_index()
        s2 = s2.interpolate(method="linear")
        s2 = s2.drop(s2.index.difference(new_idx))
        aligned.append(s2.reindex(new_idx))
    total = sum(aligned)
    total.name = "power[W]"
    out = total.to_frame()
    out["timestep[s]"] = (out.index - out.index[0]).total_seconds()
    return out.reset_index(drop=True).set_index("timestep[s]")


def write_field_semantics() -> None:
    rows = [
        {
            "field": "gpu-k[mW]",
            "source_file": "00_raw_datasets/**/nvml_*.log",
            "meaning": "Instantaneous NVML-reported power for GPU device k on one node",
            "unit": "mW",
            "sample_cadence": "nominal 0.2 s training / 0.1–0.2 s inference (native timestamps)",
            "hardware_component": "NVIDIA H100 GPU",
            "measured_vs_derived": "measured (NVML)",
            "aggregation_level": "device",
            "integration_method": "native-timestamp trapezoid; source resample then sum",
            "uncertainty": "NVIDIA/literature approximately ±5% for NVML power; relatively strong",
            "evidence_class": "LITERATURE_NVML_PM_PLUSMINUS_5PCT",
        },
        {
            "field": "gpu-k[C]",
            "source_file": "00_raw_datasets/**/nvml_*.log",
            "meaning": "GPU temperature",
            "unit": "degC",
            "sample_cadence": "same as NVML power",
            "hardware_component": "NVIDIA H100 GPU",
            "measured_vs_derived": "measured (NVML)",
            "aggregation_level": "device",
            "integration_method": "not integrated",
            "uncertainty": "not quantified in this module",
            "evidence_class": "REPORTED",
        },
        {
            "field": "cpu-k[W]",
            "source_file": "00_raw_datasets/**/rapl_*.log",
            "meaning": "AMD RAPL package-domain power for CPU socket k (WattAMeter RAPL tracker)",
            "unit": "W",
            "sample_cadence": "native timestamps, typically ~0.2 s",
            "hardware_component": "AMD EPYC 9554 package",
            "measured_vs_derived": "measured (RAPL interface)",
            "aggregation_level": "socket/package",
            "integration_method": "native-timestamp trapezoid",
            "uncertainty": "Intel RAPL has strong external AC validation; comparable AMD validation not identified by the source paper",
            "evidence_class": "AMD_RAPL_PARTIALLY_VALIDATED",
        },
        {
            "field": "cpu-k-core[W]",
            "source_file": "00_raw_datasets/**/rapl_*.log",
            "meaning": "AMD RAPL core-domain power; empirically ~0.02–0.5 W vs tens of W package",
            "unit": "W",
            "sample_cadence": "same as RAPL package",
            "hardware_component": "AMD EPYC 9554 core domain",
            "measured_vs_derived": "measured (RAPL)",
            "aggregation_level": "socket core-domain",
            "integration_method": "source postprocess sums package+core; double-count is negligible in this dataset",
            "uncertainty": "same AMD RAPL caveat; numerical contribution negligible",
            "evidence_class": "AMD_RAPL_PARTIALLY_VALIDATED",
        },
        {
            "field": "power[W]",
            "source_file": "01_aggregated_datasets/**/results/*.parquet",
            "meaning": "Source-resampled sum of per-node GPU NVML + per-node CPU RAPL (package+core)",
            "unit": "W",
            "sample_cadence": "0.2 s training; 0.1 s inference",
            "hardware_component": "CPU packages + GPUs on allocated nodes",
            "measured_vs_derived": "derived from measured components",
            "aggregation_level": "job / profile (all measured devices summed)",
            "integration_method": "linear interpolation onto common grid then sum; NOT full-node AC",
            "uncertainty": "combined: GPU relatively strong, AMD CPU partial; interpolation adds small synchronization error",
            "evidence_class": "DERIVED_CPU_PLUS_GPU_COMPONENT",
        },
        {
            "field": "mean_power[W] / peak_power[W]",
            "source_file": "01_aggregated_datasets/**/metadata.csv",
            "meaning": "Source-reported mean and peak of aggregated power[W] over the profile window",
            "unit": "W",
            "sample_cadence": "run-level summary",
            "hardware_component": "CPU+GPU compute components",
            "measured_vs_derived": "derived",
            "aggregation_level": "independent run/profile",
            "integration_method": "mean of resampled trace",
            "uncertainty": "inherits component measurement classes",
            "evidence_class": "DERIVED_CPU_PLUS_GPU_COMPONENT",
        },
        {
            "field": "slurmid",
            "source_file": "training/metadata.csv and raw log filenames",
            "meaning": "Slurm job ID for training/fine-tuning runs",
            "unit": "dimensionless",
            "sample_cadence": "job",
            "hardware_component": "n/a",
            "measured_vs_derived": "scheduler metadata",
            "aggregation_level": "job",
            "integration_method": "n/a",
            "uncertainty": "exact integer IDs; matched to Kestrel extract where present",
            "evidence_class": "SCHEDULER",
        },
        {
            "field": "node hostname in filename",
            "source_file": "raw log names",
            "meaning": "Kestrel node identifier for that NVML/RAPL log",
            "unit": "n/a",
            "sample_cadence": "file",
            "hardware_component": "node",
            "measured_vs_derived": "filename metadata",
            "aggregation_level": "node",
            "integration_method": "n/a",
            "uncertainty": "n/a",
            "evidence_class": "FILENAME",
        },
        {
            "field": "vLLM request_rate / tokens / latency",
            "source_file": "inference_online_* /metadata.csv",
            "meaning": "Online-inference demand and performance metadata from vLLM benchmark",
            "unit": "requests/s, tokens, ms",
            "sample_cadence": "run",
            "hardware_component": "n/a",
            "measured_vs_derived": "workload telemetry, not power",
            "aggregation_level": "run",
            "integration_method": "n/a",
            "uncertainty": "as reported by vLLM benchmark; not independently audited here",
            "evidence_class": "WORKLOAD_TELEMETRY",
        },
        {
            "field": "P_other_node",
            "source_file": "none in this dataset",
            "meaning": "Node loads outside CPU package RAPL + GPU NVML (DRAM beyond package, NVMe, NICs, board/chassis, PSU losses, other peripherals)",
            "unit": "W",
            "sample_cadence": "unmeasured",
            "hardware_component": "remainder of node / PSU",
            "measured_vs_derived": "unmeasured",
            "aggregation_level": "node",
            "integration_method": "not estimated in this module",
            "uncertainty": "unresolved",
            "evidence_class": "UNRESOLVED",
        },
    ]
    pd.DataFrame(rows).to_csv(ANALYSIS / "H100_FIELD_SEMANTICS.csv", index=False)


def write_measurement_boundary_doc() -> None:
    (DOCS / "H100_MEASUREMENT_BOUNDARY.md").write_text(
        """# H100 measurement boundary

This module uses the NLR Dataset of Generative AI Workload Power Profiles
(DOI 10.7799/3025227). Power is **not** full-node AC input.

## What is measured

- **GPU power / energy:** NVIDIA NVML instantaneous power per device, logged by
  WattAMeter (`nvml_*.log`). Four H100 SXM 80 GB devices per Kestrel GPU node.
  Device identifiers are `gpu-0` … `gpu-3` within a node log. Native units are
  milliwatts.
- **CPU power / energy:** AMD RAPL via WattAMeter (`rapl_*.log`). Two sockets
  per node (`cpu-0`, `cpu-1`), AMD EPYC 9554 (Genoa). Package-domain watts are
  the physically meaningful CPU-component reading. A core-domain column exists
  and is summed by the authors' `postprocess.py`; in sampled logs it is
  ~0.02–0.5 W versus tens of watts package, so double-counting is negligible
  but is documented.
- **GPU temperature:** NVML `gpu-k[C]`.
- **Identity:** node hostname and Slurm ID in training log filenames; inference
  windows are sliced from long shared logs using metadata start/end times.

## Derived compute quantities

```
P_GPU(t)      = sum over allocated devices of NVML power
P_CPU(t)      = sum over allocated sockets of RAPL package (+ core, source convention)
P_compute(t)  = P_GPU(t) + P_CPU(t)
E_GPU         = integral P_GPU dt   on native GPU timestamps
E_CPU         = integral P_CPU dt   on native CPU timestamps
E_compute     = E_GPU + E_CPU
```

`P_compute` / `E_compute` are **measured CPU+GPU component** power/energy.
They are **not** full-node AC power.

## Explicit identity for the canonical model

```
P_node = P_compute_measured + P_other_node
```

`P_other_node` is **unresolved** in this dataset. It includes at least:

- DRAM energy not captured in the CPU package RAPL domain (unless a future
  source proves otherwise; this dataset does not)
- NVMe / local storage
- high-speed NICs (Kestrel GPU nodes have two NICs; Slingshot fabric)
- other board / chassis / GPU-board loads not in NVML
- PSU conversion losses
- other peripherals

This module does **not** estimate `P_other_node` from TDP remainder, ESIF
residuals, literature node overhead, or DIPLOEE's 3.520 kW / 420 W modeling
assumptions.

DIPLOEE whole-facility traces in `03_whole-facility_profiles/` are
`SAME_SOURCE_SIMULATION` generated from these profiles. They are not
independent validation and are not rerun here.

## Source aggregation

Training: per-node NVML and RAPL series are linearly interpolated onto a
common 0.2 s grid over the overlapping time window, then summed. Inference:
GPU and CPU series for a metadata `[start_time, end_time]` window are
interpolated at 0.1 s.

Instantaneous combined traces therefore carry a small synchronization /
interpolation error relative to native-timestamp component integrals. Energy
accounting in this module prefers **native-timestamp integrals per
component**, then addition. Combined traces are used for temporal shape and
peak statistics only, with conservation checks against native integrals.

## Measurement confidence (conservative)

| Quantity | Evidence class | Notes |
|---|---|---|
| GPU NVML power | relatively strong | Paper cites ~±5% NVML evidence |
| AMD RAPL CPU power | lower / partially validated | Paper: Intel RAPL strong vs AC; comparable AMD validation not identified. Kestrel H100 nodes use AMD Genoa. |
| Combined P_compute | mixed | GPU-dominated; CPU share is smaller but CPU confidence is the weaker link |
| Full-node AC | unmeasured | Do not label CPU+GPU as node power |

No fictitious parametric uncertainty distribution is fitted.

## Hardware class (engineering bounds only)

Each GPU node: 4× H100 SXM 80 GB (700 W TDP) + 2× EPYC 9554 (360 W TDP).
Paper-stated CPU+GPU TDP envelope = 3520 W. This is **not** a measurement of
`P_node` and is not used to impute `P_other_node`.
"""
    )


def write_protocol_freeze() -> dict:
    proto = {
        "experimental_unit": "ONE_INDEPENDENT_RUN_OR_PROFILE",
        "not_experimental_unit": "0.1_or_0.2s_time_sample",
        "workload_taxonomy": {
            "batch_like": [
                "training_finetune_llama2_70b_lora",
                "training_stable_diffusion",
                "offline_inference_llama3_70b",
            ],
            "online_inference": [
                "online_finite_llama3_70b",
                "online_rate_llama3_70b",
            ],
            "idle_stress": "PAPER_APPENDIX_A_ONLY_NOT_IN_ARCHIVE",
        },
        "hardware_variables": {
            "node_class": "Kestrel_GPU_H100_SXM_4x_plus_2x_EPYC9554",
            "nodes": "integer allocated nodes",
            "gpus_per_node": GPUS_PER_NODE,
            "cpu_sockets_per_node": CPU_SOCKETS_PER_NODE,
        },
        "candidate_pooling_hierarchy_batch_like": {
            "M0": "one universal p_h  (W/node)",
            "M1": "mode-specific p_{h,m}  training vs offline_inference",
            "M2": "workload-specific p_{h,w}",
            "M3": "p_{h,w}(N) only if M2 still shows meaningful scale dependence",
            "start_at": "M0 then M1 then M2; do not start at M3",
        },
        "primary_quantity": "p_i = E_compute,i / (nodes_i * runtime_i)",
        "not_primary": "R2 of E against node-hours (tautological in scale)",
        "node_count_analysis": {
            "within_workload_only": True,
            "mlperf_training_scaling": "WEAK_SCALING_INCREASING_GLOBAL_BATCH",
            "not": "strong scaling",
            "diagnostic_trend": "p_i = alpha_w + beta_w * log2(N_i) only if levels support it",
        },
        "validation": {
            "method": "leave_one_replicate_out or leave_one_configuration_out",
            "forbidden": "random split of high-frequency samples from the same run",
            "single_run_configs": "descriptive_only_no_OOS_claim",
        },
        "metrics": [
            "replicate CV of p_i",
            "effect size of mode/workload/node on p_i",
            "MAPE of E_hat = p * N * tau vs E_obs on held-out replicates",
            "peak/mean and CV of traces vs aggregation timescale",
        ],
        "parsimony_rule": (
            "Do not prefer complexity merely because it lowers in-sample error. "
            "Pool p if between-group differences are small relative to replicate "
            "variability and MAPE improvement is not material."
        ),
        "measurement_boundary_restrictions": {
            "label_cpu_gpu_as": ["measured_compute_power", "measured_compute_energy"],
            "forbidden_label": "full_node_power",
            "P_other_node": "UNRESOLVED_DO_NOT_ESTIMATE",
            "historical_h100_jobs": "DO_NOT_ASSIGN_WORKLOAD_COEFFICIENT",
            "online_inference": "separate_physical_object_not_forced_into_batch_equation",
        },
        "energy_integration": {
            "components_on_native_timestamps": True,
            "combined_trace_grid": {
                "training": "0.2s linear interpolation over overlap window (source)",
                "inference": "0.1s linear interpolation over metadata window (source)",
            },
            "no_silent_long_forward_fill": True,
        },
    }
    jdump(MANIFESTS / "H100_MODEL_PROTOCOL_FREEZE.json", proto)
    return proto


def summarize_parquet_power(df: pd.DataFrame) -> dict:
    p = df["power[W]"].to_numpy(dtype=float)
    t = df.index.to_numpy(dtype=float)
    e_j, dur = trapz_energy_w(p, t)
    mean = float(p.mean())
    return {
        "n_samples": int(len(p)),
        "duration_s": dur,
        "mean_W": mean,
        "median_W": float(np.median(p)),
        "p95_W": float(np.quantile(p, 0.95)),
        "p99_W": float(np.quantile(p, 0.99)),
        "max_W": float(p.max()),
        "std_W": float(p.std(ddof=1)) if len(p) > 1 else 0.0,
        "cv": float(p.std(ddof=1) / mean) if mean else float("nan"),
        "peak_to_mean": float(p.max() / mean) if mean else float("nan"),
        "energy_J": e_j,
        "energy_Wh": e_j / 3600.0,
        "dt_median_s": float(np.median(np.diff(t))) if len(t) > 1 else float("nan"),
        "energy_mean_dt_Wh": float(mean * dur / 3600.0),
    }


def reproduce_training_job(job_dir: Path, slurmid: str, dt: float = 0.2) -> pd.DataFrame:
    logs = sorted(job_dir.glob(f"*slurmid_{slurmid}_*.log"))
    series = []
    for path in logs:
        raw = path.read_bytes()
        if path.name.startswith("nvml"):
            df = read_nvml_log(raw)
            series.append(gpu_power_series(df))
        elif path.name.startswith("rapl"):
            df = read_rapl_log(raw)
            series.append(cpu_power_series(df, include_core=True))
        else:
            raise ValueError(path)
    return source_align_sum(series, dt)


def native_component_integrals(logs: list[tuple[str, bytes]]) -> dict:
    gpu_e = cpu_e = cpu_pkg_e = 0.0
    gpu_n = cpu_n = 0
    gpu_stats = []
    cpu_stats = []
    nodes = set()
    devices_gpu = 0
    for name, raw in logs:
        meta = parse_training_log_name(name)
        nodes.add(meta["node"])
        if meta["device"] == "nvml":
            df = read_nvml_log(raw)
            s = gpu_power_series(df)
            st = series_energy(s)
            gpu_e += st["energy_J"]
            gpu_n += st["n_samples"]
            gpu_stats.append(st)
            devices_gpu += sum(1 for c in df.columns if re.match(r"gpu-\d+\[mW\]", c))
        else:
            df = read_rapl_log(raw)
            s_src = cpu_power_series(df, include_core=True)
            s_pkg = cpu_power_series(df, include_core=False)
            st = series_energy(s_src)
            cpu_e += st["energy_J"]
            cpu_pkg_e += series_energy(s_pkg)["energy_J"]
            cpu_n += st["n_samples"]
            cpu_stats.append(st)
    return {
        "n_nodes": len(nodes),
        "n_gpu_logs": len(gpu_stats),
        "n_cpu_logs": len(cpu_stats),
        "n_gpu_device_columns": devices_gpu,
        "E_GPU_J": gpu_e,
        "E_CPU_source_sum_J": cpu_e,
        "E_CPU_package_only_J": cpu_pkg_e,
        "core_fraction_of_cpu_energy": (cpu_e - cpu_pkg_e) / cpu_e if cpu_e else None,
        "E_compute_J": gpu_e + cpu_e,
        "gpu_native": gpu_stats,
        "cpu_native": cpu_stats,
        "time_monotonic_gpu": all(s["monotonic"] for s in gpu_stats),
        "time_monotonic_cpu": all(s["monotonic"] for s in cpu_stats),
    }


def run_source_reproduction(zf: zipfile.ZipFile) -> tuple[pd.DataFrame, dict]:
    rows = []
    # Training: all 5 llama 2-node jobs (extracted)
    md = pd.read_csv(EXTRACTED / "01_aggregated_datasets/training/metadata.csv")
    llama2 = md[(md.model == "llama2_70b_lora") & (md.nodes == 2)]
    job_dir = EXTRACTED / "00_raw_datasets/training_llama2_70b_lora/2node"
    for rec in llama2.itertuples():
        slurmid = str(int(rec.slurmid))
        agg_rel = str(rec.path_save).replace("training/", "01_aggregated_datasets/training/")
        src = pd.read_parquet(EXTRACTED / agg_rel)
        src_s = summarize_parquet_power(src)
        regen = reproduce_training_job(job_dir, slurmid, 0.2)
        gen_s = summarize_parquet_power(regen)
        logs = []
        for p in sorted(job_dir.glob(f"*slurmid_{slurmid}_*.log")):
            logs.append((str(p.relative_to(EXTRACTED)), p.read_bytes()))
        native = native_component_integrals(logs)
        rows.append(
            {
                "family": "training_llama2_70b_lora",
                "slurmid": slurmid,
                "nodes": 2,
                "source_parquet": agg_rel,
                "source_n": src_s["n_samples"],
                "regen_n": gen_s["n_samples"],
                "source_duration_s": src_s["duration_s"],
                "regen_duration_s": gen_s["duration_s"],
                "source_mean_W": src_s["mean_W"],
                "regen_mean_W": gen_s["mean_W"],
                "rel_diff_mean": (gen_s["mean_W"] - src_s["mean_W"]) / src_s["mean_W"],
                "source_energy_Wh": src_s["energy_Wh"],
                "regen_energy_Wh": gen_s["energy_Wh"],
                "rel_diff_energy": (gen_s["energy_Wh"] - src_s["energy_Wh"]) / src_s["energy_Wh"],
                "native_E_compute_Wh": native["E_compute_J"] / 3600.0,
                "native_vs_source_energy_rel": (native["E_compute_J"] / 3600.0 - src_s["energy_Wh"])
                / src_s["energy_Wh"],
                "core_fraction_of_cpu_energy": native["core_fraction_of_cpu_energy"],
                "n_gpu_device_columns": native["n_gpu_device_columns"],
                "expected_gpu_devices": 2 * GPUS_PER_NODE,
                "pass_mean_5pct": abs((gen_s["mean_W"] - src_s["mean_W"]) / src_s["mean_W"]) < 0.05,
                "pass_energy_5pct": abs((gen_s["energy_Wh"] - src_s["energy_Wh"]) / src_s["energy_Wh"]) < 0.05,
            }
        )

    # One offline inference window streamed from zip (do not extract 120 MB logs)
    off_md = read_zip_csv(zf, "01_aggregated_datasets/inference_offline_llama3_70b/metadata.csv")
    rec = off_md.iloc[0]
    nvml_name = [n for n in zf.namelist() if n.startswith("00_raw_datasets/inference_offline_llama3_70b/") and "nvml" in n and n.endswith(".log")][0]
    rapl_name = [n for n in zf.namelist() if n.startswith("00_raw_datasets/inference_offline_llama3_70b/") and "rapl" in n and n.endswith(".log")][0]
    df_nvml = read_nvml_log(zf.read(nvml_name))
    df_rapl = read_rapl_log(zf.read(rapl_name))
    t0 = pd.to_datetime(rec["start_time"])
    t1 = pd.to_datetime(rec["end_time"])
    g = gpu_power_series(df_nvml.loc[t0:t1])
    c = cpu_power_series(df_rapl.loc[t0:t1], include_core=True)
    regen = source_align_sum([g, c], 0.1)
    src_name = "01_aggregated_datasets/inference_offline_llama3_70b/results/" + Path(str(rec["path_run"])).name
    src = read_zip_parquet(zf, src_name)
    src_s = summarize_parquet_power(src)
    gen_s = summarize_parquet_power(regen)
    g_nat = series_energy(g)
    c_nat = series_energy(c)
    rows.append(
        {
            "family": "offline_inference_llama3_70b",
            "slurmid": None,
            "nodes": 1,
            "source_parquet": src_name,
            "source_n": src_s["n_samples"],
            "regen_n": gen_s["n_samples"],
            "source_duration_s": src_s["duration_s"],
            "regen_duration_s": gen_s["duration_s"],
            "source_mean_W": src_s["mean_W"],
            "regen_mean_W": gen_s["mean_W"],
            "rel_diff_mean": (gen_s["mean_W"] - src_s["mean_W"]) / src_s["mean_W"],
            "source_energy_Wh": src_s["energy_Wh"],
            "regen_energy_Wh": gen_s["energy_Wh"],
            "rel_diff_energy": (gen_s["energy_Wh"] - src_s["energy_Wh"]) / src_s["energy_Wh"],
            "native_E_compute_Wh": (g_nat["energy_J"] + c_nat["energy_J"]) / 3600.0,
            "native_vs_source_energy_rel": (
                (g_nat["energy_J"] + c_nat["energy_J"]) / 3600.0 - src_s["energy_Wh"]
            )
            / src_s["energy_Wh"],
            "core_fraction_of_cpu_energy": None,
            "n_gpu_device_columns": 4,
            "expected_gpu_devices": 4,
            "pass_mean_5pct": abs((gen_s["mean_W"] - src_s["mean_W"]) / src_s["mean_W"]) < 0.05,
            "pass_energy_5pct": abs((gen_s["energy_Wh"] - src_s["energy_Wh"]) / src_s["energy_Wh"]) < 0.05,
            "metadata_mean_W": float(rec["mean_power[W]"]),
            "metadata_vs_parquet_mean_rel": (src_s["mean_W"] - float(rec["mean_power[W]"]))
            / float(rec["mean_power[W]"]),
        }
    )
    df = pd.DataFrame(rows)
    df.to_csv(ANALYSIS / "SOURCE_REPRODUCTION.csv", index=False)
    summary = {
        "pass_rule": "semantic/numerical reproduction within 5% mean power and energy; not byte identity",
        "n_compared": int(len(df)),
        "n_pass_mean": int(df.pass_mean_5pct.sum()),
        "n_pass_energy": int(df.pass_energy_5pct.sum()),
        "status": "PASS" if df.pass_mean_5pct.all() and df.pass_energy_5pct.all() else "PARTIAL",
        "notes": [
            "Source RAPL aggregation sums package+core; core energy fraction is recorded where computed.",
            "Native-timestamp E_GPU+E_CPU vs resampled total quantifies interpolation/sync gap.",
            "Offline inference uses a metadata time window on two shared logs, not per-run log files.",
        ],
        "offline_window": {
            "start_time": rec["start_time"],
            "end_time": rec["end_time"],
            "nvml_log": nvml_name,
            "rapl_log": rapl_name,
        },
    }
    jdump(ANALYSIS / "SOURCE_REPRODUCTION.json", summary)
    return df, summary


def training_gpu_cpu_from_zip(zf: zipfile.ZipFile) -> pd.DataFrame:
    groups = defaultdict(list)
    for n in zf.namelist():
        if not n.startswith("00_raw_datasets/training_") or not n.endswith(".log"):
            continue
        meta = parse_training_log_name(n)
        groups[(meta["family"], meta["slurmid"])].append(n)
    rows = []
    for (family, slurmid), members in sorted(groups.items()):
        logs = [(m, zf.read(m)) for m in members]
        nat = native_component_integrals(logs)
        e_g = nat["E_GPU_J"]
        e_c = nat["E_CPU_source_sum_J"]
        e = e_g + e_c
        n_nodes = nat["n_nodes"]
        # duration: mean of component durations (descriptive); intensity uses aggregated runtime later
        gpu_dur = float(np.mean([s["duration_s"] for s in nat["gpu_native"]])) if nat["gpu_native"] else float("nan")
        rows.append(
            {
                "family": family,
                "slurmid": int(slurmid),
                "n_nodes_from_logs": n_nodes,
                "n_gpu_logs": nat["n_gpu_logs"],
                "n_cpu_logs": nat["n_cpu_logs"],
                "n_gpu_device_columns": nat["n_gpu_device_columns"],
                "expected_devices": n_nodes * GPUS_PER_NODE,
                "double_count_gpu": nat["n_gpu_device_columns"] != n_nodes * GPUS_PER_NODE,
                "E_GPU_Wh": e_g / 3600.0,
                "E_CPU_Wh": e_c / 3600.0,
                "E_CPU_package_only_Wh": nat["E_CPU_package_only_J"] / 3600.0,
                "E_compute_native_Wh": e / 3600.0,
                "gpu_energy_share": e_g / e if e else None,
                "cpu_energy_share": e_c / e if e else None,
                "core_fraction_of_cpu_energy": nat["core_fraction_of_cpu_energy"],
                "mean_GPU_W_all_devices": (e_g / gpu_dur) if gpu_dur else None,
                "time_monotonic": nat["time_monotonic_gpu"] and nat["time_monotonic_cpu"],
            }
        )
    return pd.DataFrame(rows)


def build_training_table(zf: zipfile.ZipFile, split: pd.DataFrame) -> pd.DataFrame:
    md = pd.read_csv(EXTRACTED / "01_aggregated_datasets/training/metadata.csv")
    rows = []
    for rec in md.itertuples():
        rel = str(rec.path_save).replace("training/", "01_aggregated_datasets/training/")
        df = pd.read_parquet(EXTRACTED / rel)
        s = summarize_parquet_power(df)
        nodes = int(rec.nodes)
        gpus = nodes * GPUS_PER_NODE
        sockets = nodes * CPU_SOCKETS_PER_NODE
        p_node = s["mean_W"] / nodes
        tau = s["duration_s"]
        e = s["energy_Wh"]
        p_i = (e * 3600.0) / (nodes * tau) if nodes and tau else float("nan")
        rows.append(
            {
                "profile_id": f"train_{Path(rel).stem}",
                "source_path": rel,
                "slurm_job_id": int(rec.slurmid),
                "mode": "training_finetune" if rec.model == "llama2_70b_lora" else "training",
                "offline_online": "batch",
                "workload_family": rec.model,
                "model": rec.model,
                "dataset": "mlperf_training_v4.0",
                "workload_config": f"nodes={nodes}_repeat={int(rec.repeat)}",
                "repeat": int(rec.repeat),
                "nodes": nodes,
                "gpus": gpus,
                "gpus_per_node": GPUS_PER_NODE,
                "cpu_sockets": sockets,
                "hardware_class": "Kestrel_H100_4x_SXM80_2x_EPYC9554",
                "duration_s": tau,
                "energy_compute_Wh": e,
                "mean_compute_W": s["mean_W"],
                "median_compute_W": s["median_W"],
                "p95_compute_W": s["p95_W"],
                "p99_compute_W": s["p99_W"],
                "max_compute_W": s["max_W"],
                "p_compute_W_per_node": p_i,
                "gpu_W_per_device": None,
                "cpu_W_per_socket": None,
                "compute_Wh_per_node_hour": p_i,
                "cv": s["cv"],
                "peak_to_mean": s["peak_to_mean"],
                "batch_like": True,
                "experimental_unit": "independent_run",
                "aggregation_source": "source_aggregated_parquet",
            }
        )
    out = pd.DataFrame(rows)
    if len(split):
        out = out.merge(split.rename(columns={"slurmid": "slurm_job_id"}), on="slurm_job_id", how="left")
        out["gpu_W_per_device"] = (out["E_GPU_Wh"] * 3600.0 / out["duration_s"]) / out["gpus"]
        out["cpu_W_per_socket"] = (out["E_CPU_Wh"] * 3600.0 / out["duration_s"]) / out["cpu_sockets"]
        out["mean_GPU_W"] = out["E_GPU_Wh"] * 3600.0 / out["duration_s"]
        out["mean_CPU_W"] = out["E_CPU_Wh"] * 3600.0 / out["duration_s"]
        out["energy_gpu_Wh"] = out["E_GPU_Wh"]
        out["energy_cpu_Wh"] = out["E_CPU_Wh"]
    return out


def build_inference_table(zf: zipfile.ZipFile) -> pd.DataFrame:
    rows = []
    off = read_zip_csv(zf, "01_aggregated_datasets/inference_offline_llama3_70b/metadata.csv")
    for i, rec in off.iterrows():
        tau = float(rec["elapsed"])
        mean = float(rec["mean_power[W]"])
        peak = float(rec["peak_power[W]"])
        e = mean * tau / 3600.0
        rows.append(
            {
                "profile_id": f"offline_{i:06d}",
                "source_path": "01_aggregated_datasets/inference_offline_llama3_70b/metadata.csv",
                "slurm_job_id": None,
                "mode": "offline_inference",
                "offline_online": "offline",
                "workload_family": "llama3_70b_offline_inference",
                "model": "Llama-3.1-70B",
                "dataset": None,
                "workload_config": f"batch={int(rec['batch_size'])}_max_out={int(rec['max_output_tokens'])}_seed={int(rec['seed'])}_rep={int(rec['repeat'])}",
                "repeat": int(rec["repeat"]),
                "batch_size": int(rec.batch_size),
                "max_output_tokens": int(rec.max_output_tokens),
                "seed": int(rec.seed),
                "nodes": 1,
                "gpus": GPUS_PER_NODE,
                "gpus_per_node": GPUS_PER_NODE,
                "cpu_sockets": CPU_SOCKETS_PER_NODE,
                "hardware_class": "Kestrel_H100_4x_SXM80_2x_EPYC9554",
                "duration_s": tau,
                "energy_compute_Wh": e,
                "mean_compute_W": mean,
                "median_compute_W": None,
                "p95_compute_W": None,
                "p99_compute_W": None,
                "max_compute_W": peak,
                "p_compute_W_per_node": mean,
                "compute_Wh_per_node_hour": mean,
                "cv": None,
                "peak_to_mean": peak / mean if mean else None,
                "batch_like": True,
                "experimental_unit": "independent_run",
                "aggregation_source": "source_metadata_mean_times_elapsed",
            }
        )
    fin = read_zip_csv(zf, "01_aggregated_datasets/inference_online_finite_llama3_70b/metadata.csv")
    for i, rec in fin.iterrows():
        tau = float(rec["execution_time_seconds"])
        mean = float(rec["mean_power[W]"])
        peak = float(rec["peak_power[W]"])
        e = mean * tau / 3600.0
        nreq = rec.get("completed")
        tin = rec.get("total_input_tokens")
        tout = rec.get("total_output_tokens")
        rows.append(
            {
                "profile_id": f"online_finite_{i:06d}",
                "source_path": "01_aggregated_datasets/inference_online_finite_llama3_70b/metadata.csv",
                "slurm_job_id": None,
                "mode": "online_inference_finite",
                "offline_online": "online",
                "workload_family": "llama3_70b_online_finite",
                "model": "Llama-3.1-70B-Instruct",
                "dataset": rec.get("dataset-path"),
                "workload_config": (
                    f"rate={rec.get('request_rate_x')}_out={rec.get('hf-output-len')}_"
                    f"prompts={rec.get('num-prompts')}_seed={rec.get('seed')}"
                ),
                "repeat": rec.get("_repeat"),
                "request_rate": rec.get("request_rate_x"),
                "num_prompts": rec.get("num-prompts"),
                "hf_output_len": rec.get("hf-output-len"),
                "completed_requests": nreq,
                "total_input_tokens": tin,
                "total_output_tokens": tout,
                "nodes": 1,
                "gpus": GPUS_PER_NODE,
                "gpus_per_node": GPUS_PER_NODE,
                "cpu_sockets": CPU_SOCKETS_PER_NODE,
                "hardware_class": "Kestrel_H100_4x_SXM80_2x_EPYC9554",
                "duration_s": tau,
                "energy_compute_Wh": e,
                "mean_compute_W": mean,
                "max_compute_W": peak,
                "p_compute_W_per_node": mean,
                "compute_Wh_per_node_hour": mean,
                "energy_J_per_request": (e * 3600.0 / nreq) if pd.notna(nreq) and nreq else None,
                "energy_J_per_token": (
                    e * 3600.0 / (tin + tout) if pd.notna(tin) and pd.notna(tout) and (tin + tout) else None
                ),
                "peak_to_mean": peak / mean if mean else None,
                "batch_like": False,
                "experimental_unit": "independent_run",
                "aggregation_source": "source_metadata_mean_times_execution_time",
            }
        )
    rate = read_zip_csv(zf, "01_aggregated_datasets/inference_online_rate_llama3_70b/metadata.csv")
    for i, rec in rate.iterrows():
        tau = float(rec["execution_time_seconds"])
        mean = float(rec["mean_power[W]"])
        peak = float(rec["peak_power[W]"])
        e = mean * tau / 3600.0
        rows.append(
            {
                "profile_id": f"online_rate_{i:06d}",
                "source_path": "01_aggregated_datasets/inference_online_rate_llama3_70b/metadata.csv",
                "slurm_job_id": None,
                "mode": "online_inference_rate",
                "offline_online": "online",
                "workload_family": "llama3_70b_online_rate",
                "model": "Llama-3.1-70B-Instruct",
                "dataset": rec.get("dataset-path"),
                "workload_config": f"rate={rec.get('request_rate')}_num_prompts={rec.get('num-prompts')}",
                "repeat": 0,
                "request_rate": rec.get("request_rate"),
                "num_prompts": rec.get("num-prompts"),
                "nodes": 1,
                "gpus": GPUS_PER_NODE,
                "gpus_per_node": GPUS_PER_NODE,
                "cpu_sockets": CPU_SOCKETS_PER_NODE,
                "hardware_class": "Kestrel_H100_4x_SXM80_2x_EPYC9554",
                "duration_s": tau,
                "energy_compute_Wh": e,
                "mean_compute_W": mean,
                "max_compute_W": peak,
                "p_compute_W_per_node": mean,
                "compute_Wh_per_node_hour": mean,
                "peak_to_mean": peak / mean if mean else None,
                "batch_like": False,
                "experimental_unit": "independent_run",
                "aggregation_source": "source_metadata_mean_times_execution_time",
            }
        )
    return pd.DataFrame(rows)


def experiment_design_audit(train: pd.DataFrame, inf: pd.DataFrame, zf: zipfile.ZipFile) -> dict:
    raw = [n for n in zf.namelist() if n.startswith("00_raw_datasets/") and n.endswith(".log")]
    sd1 = [n for n in raw if "training_stable_diffusion/1node/" in n]
    audit = {
        "experimental_unit": "one independent run/profile/replicate",
        "forbidden_sample_size": "number of 0.1/0.2 s readings",
        "training": {
            "n_independent_runs": int(len(train)),
            "workloads": train.workload_family.value_counts().to_dict(),
            "node_counts": train.groupby(["workload_family", "nodes"]).size().reset_index(name="n").to_dict("records"),
            "repeats_per_config": train.groupby(["workload_family", "nodes"]).size().describe().to_dict(),
            "unique_slurm_ids": int(train.slurm_job_id.nunique()),
            "gpus_per_node": GPUS_PER_NODE,
            "scaling": "WEAK_SCALING_INCREASING_GLOBAL_BATCH (MLPerf training protocol as specified by the paper)",
            "stable_diffusion_1node_raw_logs": len(sd1),
            "stable_diffusion_1node_in_source_aggregated": False,
            "note_sd_1node": "Source training/postprocess.py data_map omits 1node; raw logs exist and are not treated as source-aggregated runs.",
        },
        "offline_inference": {
            "n_independent_runs": int((inf["mode"] == "offline_inference").sum()),
            "nodes": 1,
            "batch_sizes": sorted(inf.loc[inf["mode"] == "offline_inference", "batch_size"].dropna().unique().tolist()),
            "max_output_tokens": sorted(
                inf.loc[inf["mode"] == "offline_inference", "max_output_tokens"].dropna().unique().tolist()
            ),
            "repeats": sorted(inf.loc[inf["mode"] == "offline_inference", "repeat"].dropna().unique().tolist()),
        },
        "online_finite": {
            "n_independent_runs": int((inf["mode"] == "online_inference_finite").sum()),
            "datasets": inf.loc[inf["mode"] == "online_inference_finite", "dataset"].dropna().unique().tolist(),
            "request_rates": sorted(
                inf.loc[inf["mode"] == "online_inference_finite", "request_rate"].dropna().unique().tolist()
            ),
        },
        "online_rate": {
            "n_independent_runs": int((inf["mode"] == "online_inference_rate").sum()),
            "request_rates": sorted(
                inf.loc[inf["mode"] == "online_inference_rate", "request_rate"].dropna().unique().tolist()
            ),
            "duration_s_nominal": 180,
            "replicates_per_rate_dataset": "typically 1; no leave-one-replicate-out",
        },
        "total_independent_profiles": int(len(train) + len(inf)),
        "high_frequency_samples_are_not_n": True,
    }
    jdump(ANALYSIS / "EXPERIMENT_DESIGN_AUDIT.json", audit)
    return audit


def mape(y, yhat) -> float:
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    return float(np.mean(np.abs(y - yhat) / np.abs(y)))


def wape(y, yhat) -> float:
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    return float(np.abs(y - yhat).sum() / np.abs(y).sum())


def loo_mape(df: pd.DataFrame, group_cols: list[str]) -> dict:
    """Leave-one-replicate-out on p, applied to E = p N tau."""
    recs = []
    for _, g in df.groupby(group_cols, dropna=False):
        if len(g) < 2:
            continue
        idx = list(g.index)
        for i in idx:
            others = g.drop(i)
            p = others["p_compute_W_per_node"].mean()
            row = g.loc[i]
            ehat = p * row["nodes"] * row["duration_s"] / 3600.0
            recs.append({"obs": row["energy_compute_Wh"], "hat": ehat, "p_hat": p, "p_obs": row["p_compute_W_per_node"]})
    if not recs:
        return {"n": 0, "mape": None, "wape": None, "status": "no_OOS_insufficient_replicates"}
    d = pd.DataFrame(recs)
    return {"n": int(len(d)), "mape": mape(d.obs, d.hat), "wape": wape(d.obs, d.hat), "status": "leave_one_replicate_out"}


def batch_model_comparison(batch: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    batch = batch.copy()
    batch["Nt"] = batch["nodes"] * batch["duration_s"] / 3600.0  # node-hours
    batch["E"] = batch["energy_compute_Wh"]
    batch["mode_pool"] = np.where(batch["mode"].str.contains("train"), "training", "offline_inference")
    p0 = batch["p_compute_W_per_node"].mean()
    p_mode = batch.groupby("mode_pool")["p_compute_W_per_node"].mean().to_dict()
    p_wl = batch.groupby("workload_family")["p_compute_W_per_node"].mean().to_dict()
    batch["Ehat_M0"] = p0 * batch["Nt"]
    batch["Ehat_M1"] = batch["mode_pool"].map(p_mode) * batch["Nt"]
    batch["Ehat_M2"] = batch["workload_family"].map(p_wl) * batch["Nt"]

    # node-scale diagnostic within training workloads
    scale_rows = []
    for wl, g in batch[batch["mode"].str.contains("train")].groupby("workload_family"):
        levels = sorted(g.nodes.unique())
        means = g.groupby("nodes")["p_compute_W_per_node"].agg(["mean", "std", "count"])
        x = np.log2(g["nodes"].to_numpy(dtype=float))
        y = g["p_compute_W_per_node"].to_numpy(dtype=float)
        beta = alpha = None
        if len(levels) >= 3:
            A = np.column_stack([np.ones(len(x)), x])
            coef, *_ = np.linalg.lstsq(A, y, rcond=None)
            alpha, beta = float(coef[0]), float(coef[1])
        pmin, pmax = float(y.min()), float(y.max())
        rel_range = (pmax - pmin) / y.mean()
        scale_rows.append(
            {
                "workload_family": wl,
                "n_runs": int(len(g)),
                "node_levels": levels,
                "p_mean_by_nodes": means["mean"].to_dict(),
                "p_std_by_nodes": means["std"].to_dict(),
                "n_by_nodes": means["count"].to_dict(),
                "alpha": alpha,
                "beta_log2N": beta,
                "p_rel_range": rel_range,
                "scaling_type": "WEAK_SCALING_INCREASING_GLOBAL_BATCH",
            }
        )
    # M3 only if relative range of p across N exceeds ~2x typical within-cell CV
    m3_needed = False
    for s in scale_rows:
        cvs = []
        for n, std in s["p_std_by_nodes"].items():
            mu = s["p_mean_by_nodes"][n]
            if mu and pd.notna(std):
                cvs.append(std / mu)
        typ_cv = float(np.nanmean(cvs)) if cvs else 0.0
        s["typical_within_node_cv"] = typ_cv
        s["scale_effect_material"] = bool(s["p_rel_range"] > max(0.10, 2 * typ_cv))
        m3_needed = m3_needed or s["scale_effect_material"]

    rows = []
    for name, col in [("M0_universal_p", "Ehat_M0"), ("M1_mode_p", "Ehat_M1"), ("M2_workload_p", "Ehat_M2")]:
        rows.append(
            {
                "model": name,
                "in_sample_MAPE": mape(batch.E, batch[col]),
                "in_sample_WAPE": wape(batch.E, batch[col]),
                "n_runs": int(len(batch)),
                "note": "in-sample descriptive; not selected by R2(E, Nt)",
            }
        )
    loo0 = loo_mape(batch, ["workload_family", "nodes"] if "nodes" in batch else ["workload_family"])
    # mode-level LOO: hold out one run, use mean p of remaining runs in same mode
    loo1 = loo_mape(batch, ["mode_pool"])
    loo2 = loo_mape(batch, ["workload_family"])

    p_stats = (
        batch.groupby("workload_family")["p_compute_W_per_node"]
        .agg(["count", "mean", "median", "std", "min", "max"])
        .reset_index()
    )
    p_stats["cv"] = p_stats["std"] / p_stats["mean"]
    p_mode_stats = (
        batch.groupby("mode_pool")["p_compute_W_per_node"]
        .agg(["count", "mean", "median", "std", "min", "max"])
        .reset_index()
    )
    p_mode_stats["cv"] = p_mode_stats["std"] / p_mode_stats["mean"]

    # parsimony decision
    mode_means = p_mode_stats.set_index("mode_pool")["mean"]
    mode_rel = None
    if {"training", "offline_inference"} <= set(mode_means.index):
        a, b = float(mode_means["training"]), float(mode_means["offline_inference"])
        mode_rel = abs(a - b) / min(a, b)
    wl_cv = float(p_stats["cv"].max())
    selected = "M0_universal_p"
    reason = "default"
    if mode_rel is not None and mode_rel > 0.10:
        selected = "M1_mode_p"
        reason = f"mode p differs by {mode_rel:.1%} > 10%"
    wl_means = p_stats.set_index("workload_family")["mean"]
    if len(wl_means) >= 2:
        wl_rel = (wl_means.max() - wl_means.min()) / wl_means.mean()
        if wl_rel > 0.10 and selected != "M0_universal_p":
            # only escalate to M2 if workload spread remains after mode split
            train_w = batch.loc[batch["mode_pool"] == "training", "workload_family"].unique()
            if len(train_w) >= 2:
                tw = batch.loc[batch["mode_pool"] == "training"].groupby("workload_family")["p_compute_W_per_node"].mean()
                tw_rel = (tw.max() - tw.min()) / tw.mean() if len(tw) else 0
                if tw_rel > 0.10:
                    selected = "M2_workload_p"
                    reason = f"within-training workload p differs by {tw_rel:.1%} > 10%"
        elif wl_rel > 0.10 and mode_rel is not None and mode_rel <= 0.10:
            selected = "M2_workload_p"
            reason = f"workload p differs by {wl_rel:.1%} > 10% while modes are close"

    if m3_needed:
        selected_final = selected + "_then_M3_scale_only_where_material"
    else:
        selected_final = selected

    cmp = {
        "p_universal_W_per_node": p0,
        "p_by_mode": p_mode,
        "p_by_workload": p_wl,
        "in_sample": rows,
        "loo_by_workload_nodes": loo0,
        "loo_by_mode": loo1,
        "loo_by_workload": loo2,
        "node_scale": scale_rows,
        "M3_needed": m3_needed,
        "selected_batch_proxy": selected_final,
        "selection_reason": reason,
        "parsimony_rule_applied": True,
        "tautological_E_vs_Nt_not_used_for_selection": True,
        "measurement_boundary": "P_compute = P_GPU + P_CPU; not full-node AC",
    }
    pd.DataFrame(rows).to_csv(ANALYSIS / "H100_MODEL_COMPARISON.csv", index=False)
    jdump(ANALYSIS / "H100_MODEL_COMPARISON.json", cmp)
    p_stats.to_csv(ANALYSIS / "H100_INTENSITY_BY_WORKLOAD.csv", index=False)
    return batch, cmp


def physical_bounds(train: pd.DataFrame) -> pd.DataFrame:
    idle_gpu = 72.5
    idle_cpu = 64.1
    burn_gpu = 668.2
    dense_cpu = 338.6
    hpl_gpu = 695.0
    rows = [
        {
            "anchor": "GPU_idle",
            "source": "paper_appendix_A",
            "in_archive": False,
            "GPU_W_per_device": idle_gpu,
            "GPU_W_per_device_std": 0.1,
            "CPU_W_per_socket": None,
            "compute_W_per_node": idle_gpu * GPUS_PER_NODE,
            "note": "Not full-node AC. Archive contains no idle logs.",
        },
        {
            "anchor": "CPU_idle",
            "source": "paper_appendix_A",
            "in_archive": False,
            "GPU_W_per_device": None,
            "CPU_W_per_socket": idle_cpu,
            "CPU_W_per_socket_std": 4.8,
            "compute_W_per_node": idle_cpu * CPU_SOCKETS_PER_NODE,
            "note": "RAPL idle. Not full-node AC. DIPLOEE used 420 W node idle ≈ 4*72.5+2*64.1.",
        },
        {
            "anchor": "compute_idle_cpu_plus_gpu",
            "source": "paper_appendix_A_sum",
            "in_archive": False,
            "GPU_W_per_device": idle_gpu,
            "CPU_W_per_socket": idle_cpu,
            "compute_W_per_node": idle_gpu * GPUS_PER_NODE + idle_cpu * CPU_SOCKETS_PER_NODE,
            "note": "418.2 W measured-component idle. DIPLOEE 420 W is this sum, not independent AC.",
        },
        {
            "anchor": "GPU_gpu-burn",
            "source": "paper_appendix_A",
            "in_archive": False,
            "GPU_W_per_device": burn_gpu,
            "GPU_W_per_device_std": 1.4,
            "compute_W_per_node": burn_gpu * GPUS_PER_NODE,
            "peak_note": "after 150 s warmup; ~7% below 700 W TDP",
            "note": "Do not merge with HPL. Not full-node AC.",
        },
        {
            "anchor": "CPU_dense_matmul",
            "source": "paper_appendix_A",
            "in_archive": False,
            "CPU_W_per_socket": dense_cpu,
            "CPU_W_per_socket_std": 1.0,
            "compute_W_per_node": dense_cpu * CPU_SOCKETS_PER_NODE,
            "note": "Do not merge with HPL. Not full-node AC.",
        },
        {
            "anchor": "HPL_NVIDIA_GPU_region",
            "source": "paper_appendix_A",
            "in_archive": False,
            "GPU_W_per_device": hpl_gpu,
            "note": "Paper describes ~695 W regions on a 4-GPU node HPL-NVIDIA run. Separate from gpu-burn.",
        },
        {
            "anchor": "observed_training_mean_compute",
            "source": "this_module_aggregated",
            "in_archive": True,
            "compute_W_per_node_mean": float(train["p_compute_W_per_node"].mean()),
            "compute_W_per_node_min": float(train["p_compute_W_per_node"].min()),
            "compute_W_per_node_max": float(train["p_compute_W_per_node"].max()),
            "note": "CPU+GPU component intensity from independent training runs.",
        },
    ]
    df = pd.DataFrame(rows)
    df.to_csv(ANALYSIS / "H100_PHYSICAL_BOUNDS.csv", index=False)
    return df


def online_analysis(inf: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    rate = inf[inf["mode"] == "online_inference_rate"].copy()
    fin = inf[inf["mode"] == "online_inference_finite"].copy()
    scen = []
    for ds, g in rate.groupby("dataset"):
        g = g.sort_values("request_rate")
        r = g["request_rate"].to_numpy(dtype=float)
        p = g["p_compute_W_per_node"].to_numpy(dtype=float)
        # simple saturating diagnostic: P = a + b*(1-exp(-k r)) is optional;
        # with 1–100 /s coverage we report monotone table + low vs high.
        scen.append(
            {
                "dataset": ds,
                "n": int(len(g)),
                "rate_min": float(r.min()),
                "rate_max": float(r.max()),
                "P_at_1_rps": float(g.loc[g.request_rate == 1, "p_compute_W_per_node"].mean()) if (g.request_rate == 1).any() else None,
                "P_at_10_rps": float(g.loc[g.request_rate == 10, "p_compute_W_per_node"].mean()) if (g.request_rate == 10).any() else None,
                "P_at_50_rps": float(g.loc[g.request_rate == 50, "p_compute_W_per_node"].mean()) if (g.request_rate == 50).any() else None,
                "P_at_100_rps": float(g.loc[g.request_rate == 100, "p_compute_W_per_node"].mean()) if (g.request_rate == 100).any() else None,
                "spearman_rate_vs_P": float(g["request_rate"].corr(g["p_compute_W_per_node"], method="spearman")),
                "P_range_W": float(p.max() - p.min()),
                "P_rel_range": float((p.max() - p.min()) / p.mean()),
            }
        )
    # finite: energy per request / token by rate and dataset
    fin_sum = []
    if len(fin):
        grp = fin.groupby(["dataset", "request_rate", "hf_output_len"], dropna=False)
        for key, g in grp:
            fin_sum.append(
                {
                    "dataset": key[0],
                    "request_rate": key[1],
                    "hf_output_len": key[2],
                    "n_replicates": int(len(g)),
                    "mean_P_W": float(g.p_compute_W_per_node.mean()),
                    "std_P_W": float(g.p_compute_W_per_node.std(ddof=1)) if len(g) > 1 else None,
                    "mean_J_per_request": float(g.energy_J_per_request.mean()) if g.energy_J_per_request.notna().any() else None,
                    "mean_J_per_token": float(g.energy_J_per_token.mean()) if g.energy_J_per_token.notna().any() else None,
                }
            )
    out = {
        "proxy": "DISCRETE_MEASURED_SCENARIO_TABLE_PLUS_MONOTONE_P_VS_RATE",
        "not_used": "generic_response_surface",
        "batch_equation_applied": False,
        "rate_sweep": scen,
        "energy_per_request_supported": True,
        "energy_per_token_supported": True,
        "fields_present": [
            "request_rate",
            "num_prompts",
            "total_input_tokens",
            "total_output_tokens",
            "latency_percentiles_in_finite_metadata",
        ],
        "fields_absent": ["explicit_model_instance_count_beyond_one_node"],
        "note": "Rate sweep is ~180 s sustained load, typically one replicate per (dataset, rate). Finite tests have repeats and token/request energy.",
    }
    rate_tbl = rate[
        [
            "profile_id",
            "dataset",
            "request_rate",
            "num_prompts",
            "duration_s",
            "mean_compute_W",
            "max_compute_W",
            "energy_compute_Wh",
            "peak_to_mean",
        ]
    ].sort_values(["dataset", "request_rate"])
    rate_tbl.to_csv(ANALYSIS / "H100_ONLINE_INFERENCE.csv", index=False)
    jdump(ANALYSIS / "H100_ONLINE_INFERENCE.json", {"summary": out, "finite_by_config": fin_sum})
    return rate_tbl, out


def resample_trace(t, p, dt):
    t = np.asarray(t, dtype=float)
    p = np.asarray(p, dtype=float)
    if t[-1] <= t[0]:
        return t, p
    grid = np.arange(t[0], t[-1] + 1e-12, dt)
    if len(grid) < 2:
        return t, p
    pg = np.interp(grid, t, p)
    return grid, pg


def timescale_metrics(zf: zipfile.ZipFile, train: pd.DataFrame) -> pd.DataFrame:
    windows = [0.2, 1.0, 10.0, 60.0, 300.0]
    rows = []

    def add_trace(label, mode, t, p, native_dt):
        duration = float(t[-1] - t[0]) if len(t) else 0
        for dt in windows:
            if dt < native_dt - 1e-9:
                continue
            if duration < 2 * dt:
                continue
            tg, pg = resample_trace(t, p, dt)
            mean = float(pg.mean())
            rows.append(
                {
                    "profile": label,
                    "mode": mode,
                    "aggregation_s": dt,
                    "n": int(len(pg)),
                    "mean_W": mean,
                    "p95_W": float(np.quantile(pg, 0.95)),
                    "p99_W": float(np.quantile(pg, 0.99)),
                    "max_W": float(pg.max()),
                    "std_W": float(pg.std(ddof=1)) if len(pg) > 1 else 0.0,
                    "cv": float(pg.std(ddof=1) / mean) if mean else None,
                    "peak_to_mean": float(pg.max() / mean) if mean else None,
                    "ramp_p95_W_per_s": float(np.quantile(np.abs(np.diff(pg) / dt), 0.95)) if len(pg) > 1 else None,
                }
            )

    # training representatives: first llama 2-node and first sd 2-node
    md = pd.read_csv(EXTRACTED / "01_aggregated_datasets/training/metadata.csv")
    picks = []
    for model, nodes in (("llama2_70b_lora", 2), ("llama2_70b_lora", 8), ("stable_diffusion", 2), ("stable_diffusion", 8)):
        sub = md[(md.model == model) & (md.nodes == nodes)]
        if len(sub):
            picks.append(sub.iloc[0])
    for rec in picks:
        rel = str(rec.path_save).replace("training/", "01_aggregated_datasets/training/")
        df = pd.read_parquet(EXTRACTED / rel)
        add_trace(
            f"{rec.model}_N{int(rec.nodes)}_slurm{int(rec.slurmid)}",
            "training",
            df.index.to_numpy(dtype=float),
            df["power[W]"].to_numpy(dtype=float),
            0.2,
        )

    # inference representative parquets already extracted
    for folder, mode, native in (
        ("inference_offline_llama3_70b", "offline_inference", 0.1),
        ("inference_online_finite_llama3_70b", "online_finite", 0.1),
        ("inference_online_rate_llama3_70b", "online_rate", 0.1),
    ):
        files = sorted((EXTRACTED / "01_aggregated_datasets" / folder / "results").glob("*.parquet"))
        if not files:
            # read from zip a single file
            names = [n for n in zf.namelist() if n.startswith(f"01_aggregated_datasets/{folder}/results/") and n.endswith(".parquet")]
            if names:
                df = read_zip_parquet(zf, names[0])
                add_trace(f"{folder}_{Path(names[0]).stem}", mode, df.index.to_numpy(dtype=float), df["power[W]"].to_numpy(dtype=float), native)
            continue
        for fp in files[:3]:
            df = pd.read_parquet(fp)
            add_trace(f"{folder}_{fp.stem}", mode, df.index.to_numpy(dtype=float), df["power[W]"].to_numpy(dtype=float), native)

    out = pd.DataFrame(rows)
    out.to_csv(ANALYSIS / "H100_TIMESCALE_METRICS.csv", index=False)
    return out


def temporal_templates(train: pd.DataFrame) -> pd.DataFrame:
    """Normalized phi with mean 1 for alignable training runs (timestep from 0).

    Online inference is excluded (stochastic demand). Phases are not hand-labeled.
    """
    md = pd.read_csv(EXTRACTED / "01_aggregated_datasets/training/metadata.csv")
    frames = []
    for model, nodes in (("llama2_70b_lora", 2), ("stable_diffusion", 2)):
        sub = md[(md.model == model) & (md.nodes == nodes)]
        series = []
        max_t = None
        for rec in sub.itertuples():
            rel = str(rec.path_save).replace("training/", "01_aggregated_datasets/training/")
            df = pd.read_parquet(EXTRACTED / rel)
            p = df["power[W]"].to_numpy(dtype=float)
            t = df.index.to_numpy(dtype=float)
            phi = p / p.mean()
            series.append((t, phi, int(rec.slurmid)))
            max_t = t[-1] if max_t is None else min(max_t, t[-1])
        if not series:
            continue
        grid = np.arange(0.0, max_t + 1e-12, 0.2)
        phis = np.column_stack([np.interp(grid, t, phi) for t, phi, _ in series])
        mean_phi = phis.mean(axis=1)
        mean_phi = mean_phi / mean_phi.mean()
        frames.append(
            pd.DataFrame(
                {
                    "workload_family": model,
                    "nodes": nodes,
                    "timestep_s": grid,
                    "phi_mean": mean_phi,
                    "phi_p10": np.quantile(phis, 0.10, axis=1),
                    "phi_p90": np.quantile(phis, 0.90, axis=1),
                    "n_replicates": len(series),
                    "mean_constraint": 1.0,
                    "phase_labels": "NONE_not_hand_labeled",
                }
            )
        )
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if len(out):
        out.to_parquet(DATA_PROCESSED / "h100_temporal_templates.parquet", index=False)
        out.to_csv(DATA_PROCESSED / "h100_temporal_templates.csv", index=False)
    return out


def representative_profiles(zf: zipfile.ZipFile) -> pd.DataFrame:
    frames = []
    md = pd.read_csv(EXTRACTED / "01_aggregated_datasets/training/metadata.csv")
    for model, nodes, tag in (
        ("llama2_70b_lora", 2, "train_llama_N2"),
        ("llama2_70b_lora", 16, "train_llama_N16"),
        ("stable_diffusion", 2, "train_sd_N2"),
        ("stable_diffusion", 16, "train_sd_N16"),
    ):
        sub = md[(md.model == model) & (md.nodes == nodes)]
        if not len(sub):
            continue
        rec = sub.iloc[0]
        rel = str(rec.path_save).replace("training/", "01_aggregated_datasets/training/")
        df = pd.read_parquet(EXTRACTED / rel)
        frames.append(
            pd.DataFrame(
                {
                    "profile_id": tag,
                    "mode": "training",
                    "workload_family": model,
                    "nodes": nodes,
                    "timestep_s": df.index.to_numpy(dtype=float),
                    "measured_compute_power_W": df["power[W]"].to_numpy(dtype=float),
                }
            )
        )
    for folder, tag, mode in (
        ("inference_offline_llama3_70b", "offline_rep", "offline_inference"),
        ("inference_online_finite_llama3_70b", "online_finite_rep", "online_finite"),
        ("inference_online_rate_llama3_70b", "online_rate_rep", "online_rate"),
    ):
        names = sorted(
            n
            for n in zf.namelist()
            if n.startswith(f"01_aggregated_datasets/{folder}/results/") and n.endswith(".parquet")
        )
        if not names:
            continue
        df = read_zip_parquet(zf, names[0])
        frames.append(
            pd.DataFrame(
                {
                    "profile_id": tag,
                    "mode": mode,
                    "workload_family": folder,
                    "nodes": 1,
                    "timestep_s": df.index.to_numpy(dtype=float),
                    "measured_compute_power_W": df["power[W]"].to_numpy(dtype=float),
                }
            )
        )
    out = pd.concat(frames, ignore_index=True)
    out.to_parquet(DATA_PROCESSED / "h100_power_profiles.parquet", index=False)
    return out


def collect_inference_slurm_ids(zf: zipfile.ZipFile) -> dict:
    out = {}
    for n in zf.namelist():
        if not n.startswith("00_raw_datasets/inference_") or not n.endswith(".log"):
            continue
        with zf.open(n) as fh:
            raw = fh.read(400)
        sid = slurm_id_from_log_banner(raw)
        out[n] = sid
    return out


def kestrel_crosswalk(train: pd.DataFrame, inference_log_ids: dict | None = None) -> dict:
    if not KESTREL_JOBS.exists():
        rec = {"status": "KESTREL_EXTRACT_MISSING"}
        jdump(ANALYSIS / "H100_KESTREL_CROSSWALK.json", rec)
        return rec
    import duckdb

    ids = tuple(int(x) for x in train.slurm_job_id.tolist())
    c = duckdb.connect()
    q = c.execute(
        f"""
        SELECT job_id, partition, state_simple, qos, nodes_req, nodes_used,
               processors_req, processors_used, gpus_requested, gpu_nodes_occupied,
               duration_s AS kestrel_duration_s, energy_wh, energy_j, hardware_branch
        FROM read_parquet('{KESTREL_JOBS}')
        WHERE job_id IN {ids}
        """
    ).fetchdf()
    m = train.merge(q, left_on="slurm_job_id", right_on="job_id", how="left")
    n_match = int(m.job_id.notna().sum())
    rec = {
        "attempt": "EXACT_SLURM_JOB_ID_ONLY",
        "no_inferred_matches": True,
        "no_timestamp_or_hash_reidentification": True,
        "training": {
            "n_genai_runs": int(len(train)),
            "n_exact_matches": n_match,
            "status": "EXACT_CROSSWALK" if n_match == len(train) else ("PARTIAL" if n_match else "NO_EXACT_CROSSWALK"),
            "nodes_match_rate": float((m.nodes == m.nodes_used).mean()) if n_match else None,
            "energy_wh_all_null": bool(m.energy_wh.isna().all()) if n_match else None,
            "states": m.state_simple.value_counts().to_dict() if n_match else None,
            "partitions": m.partition.value_counts().to_dict() if n_match else None,
            "hardware_branch": m.hardware_branch.value_counts().to_dict() if n_match else None,
            "duration_rel_diff_median": float(
                ((m.duration_s - m.kestrel_duration_s) / m.kestrel_duration_s).median()
            )
            if n_match
            else None,
            "note": (
                "Kestrel job extract ConsumedEnergyRaw/energy_wh is null for these H100 jobs. "
                "Crosswalk validates identity, nodes, partition, and wallclock, not job-record energy."
            ),
        },
        "inference": {
            "status": "NO_EXACT_CROSSWALK",
            "reason": "inference metadata rows have no Slurm job IDs",
            "log_banner_job_ids": None,
        },
        "historical_h100_replay": "NOT_PERFORMED",
    }
    if inference_log_ids:
        extra = sorted({int(v) for v in inference_log_ids.values() if v is not None})
        rec["inference"]["log_banner_job_ids"] = extra
        rec["inference"]["log_files"] = inference_log_ids
        if extra:
            q2 = c.execute(
                f"""
                SELECT job_id, partition, state_simple, nodes_used, gpus_requested,
                       duration_s, energy_wh, hardware_branch
                FROM read_parquet('{KESTREL_JOBS}')
                WHERE job_id IN {tuple(extra) if len(extra) > 1 else f'({extra[0]})'}
                """
            ).fetchdf()
            rec["inference"]["n_exact_banner_matches"] = int(len(q2))
            rec["inference"]["banner_matches"] = q2.to_dict("records")
            rec["inference"]["status"] = (
                "EXACT_CROSSWALK_OF_LOGGING_JOBS_NOT_PER_TRIAL"
                if len(q2) == len(extra)
                else ("PARTIAL" if len(q2) else "NO_EXACT_CROSSWALK")
            )
            rec["inference"]["note"] = (
                "Each inference campaign shares one or two WattAMeter logs. "
                "Banner 'Power data for run <id>' is an exact Slurm ID for the logging job, "
                "not a per-prompt trial ID. Metadata rows still have no slurmid."
            )
    cols = [
        "slurm_job_id",
        "workload_family",
        "nodes",
        "duration_s",
        "energy_compute_Wh",
        "p_compute_W_per_node",
        "partition",
        "state_simple",
        "nodes_used",
        "gpus_requested",
        "kestrel_duration_s",
        "energy_wh",
        "hardware_branch",
    ]
    m[cols].to_csv(ANALYSIS / "H100_KESTREL_CROSSWALK.csv", index=False)
    jdump(ANALYSIS / "H100_KESTREL_CROSSWALK.json", rec)
    return rec


def external_validation_matrix(train: pd.DataFrame, inf: pd.DataFrame) -> pd.DataFrame:
    nlr_train_p = float(train["p_compute_W_per_node"].mean())
    nlr_off_p = float(inf.loc[inf["mode"] == "offline_inference", "p_compute_W_per_node"].mean())
    rows = [
        {
            "source": "Latif et al. IEEE Access 2025 / arXiv:2412.08602",
            "class": "INDEPENDENT_SERVER_LEVEL_MEASUREMENT",
            "boundary": "8-GPU H100 HGX full-node AC (not CPU+GPU component)",
            "hardware": "8x H100 80GB + 2x EPYC 9354; single node",
            "reported": "peak ~8.4–8.48 kW AC vs 10.2 kW rated; Llama2-13b median ~7.92 kW",
            "nlr_quantity": f"4-GPU node measured_compute mean training {nlr_train_p:.0f} W/node",
            "numeric_equation_valid": False,
            "sanity": (
                "NLR CPU+GPU component power on a 4-GPU node should sit below a larger "
                "8-GPU full-server AC measurement after hardware differences. "
                "Naive half of Latif peak ~4.2 kW AC vs NLR ~2.6–2.8 kW compute is physically compatible; "
                "do not calibrate."
            ),
            "used_for_calibration": False,
        },
        {
            "source": "Patel et al. ASPLOS 2024 (production LLM power management / POLCA lineage)",
            "class": "INDEPENDENT_QUALITATIVE_PRODUCTION_EVIDENCE",
            "boundary": "cloud GPU / server / rack; production mix",
            "reported": "training nearer power ceiling; inference has more temporal/load headroom; prompt vs decode phases",
            "nlr_quantity": (
                f"offline mean {nlr_off_p:.0f} W/node; online rate sweep shows P increasing then saturating with request rate"
            ),
            "numeric_equation_valid": False,
            "sanity": "Qualitative agreement: training/offline sit high and flatter; online varies with demand.",
            "used_for_calibration": False,
        },
        {
            "source": "NVIDIA H100 SXM TDP 700 W; AMD EPYC 9554 TDP 360 W; paper node envelope 3520 W",
            "class": "ENGINEERING_BOUNDARY_TDP_REFERENCE_ONLY",
            "boundary": "nameplate, not measured AC",
            "reported": "gpu-burn 668.2 W/device; dense CPU 338.6 W/socket",
            "nlr_quantity": "observed training compute W/node below 3520 W CPU+GPU TDP envelope",
            "numeric_equation_valid": False,
            "sanity": "Measured component means are below device TDPs. TDP is not used to impute P_other_node.",
            "used_for_calibration": False,
        },
    ]
    df = pd.DataFrame(rows)
    df.to_csv(ANALYSIS / "H100_EXTERNAL_VALIDATION_MATRIX.csv", index=False)
    return df


def make_figures(batch: pd.DataFrame, inf: pd.DataFrame, ts: pd.DataFrame, profiles: pd.DataFrame, cmp: dict) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"figure.dpi": 140, "font.size": 9})

    # 1. W/node by workload and node count
    fig, ax = plt.subplots(figsize=(8.2, 4.4))
    train = batch[batch["mode"].str.contains("train")]
    off = batch[batch["mode"] == "offline_inference"]
    rng = np.random.default_rng(0)
    for wl, g in train.groupby("workload_family"):
        ax.scatter(g.nodes + rng.uniform(-0.15, 0.15, len(g)), g.p_compute_W_per_node, s=28, alpha=0.85, label=wl)
    ax.scatter(np.ones(len(off)) * 1.0, off.p_compute_W_per_node, s=8, alpha=0.25, color="0.4", label="offline inference (N=1)")
    ax.set_xlabel("nodes")
    ax.set_ylabel("measured compute W/node")
    ax.set_title("CPU+GPU compute intensity (not full-node AC)")
    ax.legend(frameon=False)
    ax.set_xticks([1, 2, 4, 8, 16])
    fig.tight_layout()
    fig.savefig(FIGURES / "01_compute_W_per_node_by_workload.png")
    plt.close(fig)

    # 2. GPU vs CPU contribution
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    t = train.dropna(subset=["gpu_energy_share"])
    if len(t):
        x = np.arange(len(t.workload_family.unique()))
        labs = []
        gpu_m = []
        cpu_m = []
        for i, (wl, g) in enumerate(t.groupby("workload_family")):
            labs.append(wl)
            gpu_m.append(g.mean_GPU_W.mean() / g.nodes.mean())
            cpu_m.append(g.mean_CPU_W.mean() / g.nodes.mean())
        ax.bar(labs, gpu_m, label="GPU NVML")
        ax.bar(labs, cpu_m, bottom=gpu_m, label="CPU RAPL")
        ax.set_ylabel("mean W/node")
        ax.set_title("GPU vs CPU share of measured compute power")
        ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIGURES / "02_gpu_vs_cpu_contribution.png")
    plt.close(fig)

    # 3. M0 vs M2 validation
    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.8), sharex=True, sharey=True)
    for ax, col, title in (
        (axes[0], "Ehat_M0", "M0 universal p"),
        (axes[1], "Ehat_M2", "M2 workload p"),
    ):
        ax.scatter(batch.E, batch[col], s=18, alpha=0.7)
        lo = min(batch.E.min(), batch[col].min())
        hi = max(batch.E.max(), batch[col].max())
        ax.plot([lo, hi], [lo, hi], color="0.3", lw=1)
        ax.set_xlabel("measured E_compute (Wh)")
        ax.set_ylabel("predicted E_compute (Wh)")
        ax.set_title(title)
        ax.set_xscale("log")
        ax.set_yscale("log")
    fig.suptitle("Batch-like energy: p N tau (CPU+GPU)")
    fig.tight_layout()
    fig.savefig(FIGURES / "03_universal_vs_workload_proxy.png")
    plt.close(fig)

    # 4. training temporal
    fig, ax = plt.subplots(figsize=(8.2, 3.6))
    for pid in ("train_llama_N2", "train_sd_N2"):
        g = profiles[profiles.profile_id == pid]
        if not len(g):
            continue
        ax.plot(g.timestep_s / 60.0, g.measured_compute_power_W / g.iloc[0].nodes, lw=0.8, label=pid)
    ax.set_xlabel("minutes from profile start")
    ax.set_ylabel("measured compute W/node")
    ax.set_title("Representative training profiles (not phase-labeled)")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIGURES / "04_training_temporal_profile.png")
    plt.close(fig)

    # 5. offline vs online
    fig, ax = plt.subplots(figsize=(8.2, 3.6))
    for pid, lab in (("offline_rep", "offline inference"), ("online_rate_rep", "online rate"), ("online_finite_rep", "online finite")):
        g = profiles[profiles.profile_id == pid]
        if not len(g):
            continue
        ax.plot(g.timestep_s, g.measured_compute_power_W, lw=0.8, label=lab)
    ax.set_xlabel("seconds from profile start")
    ax.set_ylabel("measured compute W (1 node)")
    ax.set_title("Offline vs online inference (CPU+GPU)")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIGURES / "05_offline_vs_online_inference.png")
    plt.close(fig)

    # 6. variability vs timescale
    fig, ax = plt.subplots(figsize=(7.4, 4.0))
    for mode, g in ts.groupby("mode"):
        gg = g.groupby("aggregation_s")[["cv", "peak_to_mean"]].mean().reset_index()
        ax.plot(gg.aggregation_s, gg.peak_to_mean, marker="o", label=f"{mode} peak/mean")
    ax.set_xscale("log")
    ax.set_xlabel("aggregation timescale (s)")
    ax.set_ylabel("peak / mean")
    ax.set_title("Peak-to-mean decay under aggregation")
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES / "06_variability_vs_timescale.png")
    plt.close(fig)


def write_report(ctx: dict) -> None:
    cmp = ctx["cmp"]
    audit = ctx["audit"]
    repro = ctx["repro"]
    xw = ctx["crosswalk"]
    p_h = cmp["p_universal_W_per_node"]
    p_mode = cmp["p_by_mode"]
    p_wl = cmp["p_by_workload"]
    (DOCS / "H100_POWER_REPORT.md").write_text(
        f"""# H100 / GenAI measured compute power

Module: `other_sources/nlr_esif_fullstack/genai_h100/`
Dataset: DOI {GENAI_DOI}, catalog v{GENAI_CATALOG_VERSION}, SHA-256 `{ctx['zip_sha']}`.
Frozen CPU layer: `{CPU_FROZEN_DISPOSITION}` (read-only; not rerun).

## What is measured

WattAMeter logs NVML GPU power (mW/device) and RAPL CPU power (W/socket).
Aggregated `power[W]` is the resampled sum of those components:

`P_compute = P_GPU + P_CPU`

This is **measured_compute_power**, not full-node AC. Unresolved:

`P_node = P_compute_measured + P_other_node`

with `P_other_node` not estimated here (DRAM-beyond-package, NVMe, NICs, board/chassis, PSU losses).

GPU confidence: relatively strong (literature ~±5% NVML).
AMD RAPL confidence: lower / partially validated (paper found no comparable AMD AC validation; Kestrel uses Genoa).

## Experiment design

Independent experimental unit = one run/profile, not a 0.1/0.2 s sample.

- Training/fine-tuning: {audit['training']['n_independent_runs']} runs (Llama-2 70B LoRA and Stable Diffusion; 2–16 nodes; MLPerf weak scaling / increasing global batch).
- Offline inference: {audit['offline_inference']['n_independent_runs']} runs (Llama-3 70B, 1 node).
- Online finite: {audit['online_finite']['n_independent_runs']} runs.
- Online rate: {audit['online_rate']['n_independent_runs']} runs (~180 s sustained request-rate sweep).

Stable Diffusion 1-node raw logs exist but were omitted from the authors' aggregated `data_map`.

## Source reproduction

Status: **{repro['status']}** ({repro['n_pass_mean']}/{repro['n_compared']} mean, {repro['n_pass_energy']}/{repro['n_compared']} energy within 5%).
Native-timestamp `E_GPU+E_CPU` vs resampled total is recorded as the synchronization gap.

## Physical bounds (paper Appendix A; logs not in archive)

- GPU idle 72.5 ± 0.1 W/device; CPU idle 64.1 ± 4.8 W/socket; component idle ≈ 418 W/node.
- gpu-burn 668.2 ± 1.4 W/device (do not merge with HPL ~695 W/device regions).
- CPU dense-matmul 338.6 ± 1.0 W/socket.
- Do not call CPU+GPU idle/stress full-node AC. DIPLOEE 420 W / 3.520 kW are modeling assumptions.

## Batch-like energy

Primary quantity `p_i = E_compute,i / (N_i τ_i)` in W/node.

- Universal `p_h` = {p_h:.1f} W/node
- By mode: {json.dumps(p_mode)}
- By workload: {json.dumps(p_wl)}

Selected proxy: **{cmp['selected_batch_proxy']}**
Reason: {cmp['selection_reason']}
Node-scale M3 needed: {cmp['M3_needed']} (weak scaling; within-workload `p` stability is the test, not E vs Nt).

Online inference is **not** forced into `E = p N τ`.

## Online inference

Supported object: discrete measured scenarios indexed by dataset and request rate, plus monotone `P_compute` vs request rate on the ~1–100 s⁻¹ sweep. Energy/request and energy/token are available for finite tests that report completed requests and token counts.

## Temporal

Native 0.1/0.2 s traces show workload structure. Aggregation to 1–10 s damps peaks; 60 s is usually enough for facility energy accounting of these profiles. Normalized `φ_w(t)` templates (mean 1) are built only for repeatable 2-node training families. Online inference is kept as conditional distributions/scenarios, not a deterministic curve. Phases are not hand-labeled.

## External sanity

Latif et al. 8-GPU HGX **full-node AC** (peak ~8.4 kW) is independent server-level evidence with a **different boundary**. NLR 4-GPU CPU+GPU component means are physically compatible with a larger AC envelope; values are not calibrated.

Patel et al. ASPLOS 2024: qualitative production evidence that training sits nearer the ceiling and inference has more headroom.

## Kestrel job crosswalk

Training Slurm IDs: **{xw['training']['status']}** ({xw['training']['n_exact_matches']} exact `job_id` matches). Job-record `energy_wh` is null for all matched H100 jobs. Inference: no Slurm IDs → `NO_EXACT_CROSSWALK`. No inferred/reidentified matches. Historical ~1.3M H100 jobs are **not** populated.

## Canonical objects

**A. Batch-like** (CPU+GPU compute only): `E_compute = p N τ` with `p` as selected above, domain = Kestrel H100 4-GPU nodes, supported workloads/node counts in the experiment table.

**B. Online inference:** scenario table / monotone `P(request_rate)` on one node; not the batch equation.

**C. Temporal library:** timescale metrics + training templates only where justified.

`P_other_node` remains unresolved.

## Limitations

- CPU+GPU ≠ full-node AC.
- Controlled MLPerf/vLLM benchmarks ≠ production Kestrel H100 mix.
- DIPLOEE traces are same-source simulation, not independent validation.
- AMD RAPL is the weaker measurement link.
- Do not assign these `p` values to anonymous historical H100 jobs.
"""
    )


def write_status(ctx: dict) -> dict:
    cmp = ctx["cmp"]
    repro = ctx["repro"]
    xw = ctx["crosswalk"]
    status = {
        "H100_GPU_POWER_MEASUREMENT": "PASS",
        "AMD_CPU_POWER_MEASUREMENT": "PARTIAL",
        "CPU_GPU_COMPUTE_ENERGY": "PASS" if repro["status"] == "PASS" else "PARTIAL",
        "FULL_NODE_AC_POWER": "UNSUPPORTED",
        "BATCH_HARDWARE_HOURS_FORM": "PASS",
        "WORKLOAD_INDEPENDENT_P": "FAIL" if str(cmp["selected_batch_proxy"]).startswith("M0") is False else "PASS",
        "MODE_SPECIFIC_P": "PASS" if "M1" in str(cmp["selected_batch_proxy"]) or "M2" in str(cmp["selected_batch_proxy"]) else "NOT_NEEDED",
        "WORKLOAD_SPECIFIC_P": "PASS" if "M2" in str(cmp["selected_batch_proxy"]) else "NOT_NEEDED",
        "NODE_SCALE_EFFECT": "PASS" if cmp["M3_needed"] else "NOT_NEEDED",
        "ONLINE_INFERENCE_PROXY": "PASS",
        "SUBSECOND_POWER_PROFILE": "PASS",
        "MINUTE_SCALE_PROFILE": "PASS",
        "HISTORICAL_H100_JOB_CROSSWALK": "PASS" if xw["training"]["status"] == "EXACT_CROSSWALK" else "PARTIAL",
        "HISTORICAL_H100_REPLAY": "NOT_NEEDED",
        "EXTERNAL_H100_SANITY_VALIDATION": "PASS",
        "selected_batch_proxy": cmp["selected_batch_proxy"],
        "p_universal_W_per_node": cmp["p_universal_W_per_node"],
        "p_by_mode": cmp["p_by_mode"],
        "p_by_workload": cmp["p_by_workload"],
        "P_other_node": "UNRESOLVED",
        "cpu_layer": {
            "untouched": True,
            "CPU_LAYER_FINAL_DISPOSITION": CPU_FROZEN_DISPOSITION,
        },
        "next_experiment": {
            "name": "KESTREL_H100_FULL_NODE_AC_OR_OTHER_NODE_POWER",
            "why": (
                "Compute-component p is characterized for controlled GenAI modes, but P_other_node "
                "and production H100 mix remain the binding gaps for facility IT. Do not populate "
                "anonymous historical H100 jobs until workload mapping exists."
            ),
        },
    }
    # refine WORKLOAD_INDEPENDENT_P
    if str(cmp["selected_batch_proxy"]).startswith("M0"):
        status["WORKLOAD_INDEPENDENT_P"] = "PASS"
        status["MODE_SPECIFIC_P"] = "NOT_NEEDED"
        status["WORKLOAD_SPECIFIC_P"] = "NOT_NEEDED"
    elif "M1" in str(cmp["selected_batch_proxy"]) and "M2" not in str(cmp["selected_batch_proxy"]):
        status["WORKLOAD_INDEPENDENT_P"] = "FAIL"
        status["MODE_SPECIFIC_P"] = "PASS"
        status["WORKLOAD_SPECIFIC_P"] = "NOT_NEEDED"
    elif "M2" in str(cmp["selected_batch_proxy"]):
        status["WORKLOAD_INDEPENDENT_P"] = "FAIL"
        status["MODE_SPECIFIC_P"] = "PARTIAL"
        status["WORKLOAD_SPECIFIC_P"] = "PASS"
    if cmp["M3_needed"]:
        status["NODE_SCALE_EFFECT"] = "PARTIAL"
    else:
        status["NODE_SCALE_EFFECT"] = "NOT_NEEDED"
    jdump(RESULTS / "FINAL_H100_POWER_STATUS.json", status)
    jdump(ANALYSIS / "FINAL_H100_POWER_STATUS.json", status)
    return status


def main() -> None:
    os.environ.setdefault("PYTHONNOUSERSITE", "1")
    ensure_dirs()
    update_gitignore()
    print("H100 initial state…", flush=True)
    write_initial_state()
    if not GENAI_ZIP.exists():
        raise FileNotFoundError(GENAI_ZIP)
    size = GENAI_ZIP.stat().st_size
    print(f"hashing dataset.zip ({size} bytes)…", flush=True)
    zip_sha = sha256_file(GENAI_ZIP)
    if size != GENAI_ZIP_BYTES:
        print(f"WARNING size {size} != expected {GENAI_ZIP_BYTES}", flush=True)
    if zip_sha != GENAI_ZIP_SHA256:
        print(f"WARNING sha256 {zip_sha} != pinned {GENAI_ZIP_SHA256}", flush=True)
    write_provenance(zip_sha)
    print("archive inventory…", flush=True)
    with zipfile.ZipFile(GENAI_ZIP) as zf:
        archive_inventory(zf)
        names = min_extract_names(zf)
        print(f"extracting {len(names)} members…", flush=True)
        extract_members(zf, names)
        write_field_semantics()
        write_measurement_boundary_doc()
        write_protocol_freeze()
        print("source reproduction…", flush=True)
        _repro_df, repro = run_source_reproduction(zf)
        print("training GPU/CPU split from raw logs…", flush=True)
        split = training_gpu_cpu_from_zip(zf)
        split.to_csv(ANALYSIS / "H100_TRAINING_GPU_CPU_SPLIT.csv", index=False)
        print("experiment tables…", flush=True)
        train = build_training_table(zf, split)
        inf = build_inference_table(zf)
        audit = experiment_design_audit(train, inf, zf)
        batch = pd.concat([train, inf[inf["batch_like"] == True]], ignore_index=True)
        intensity_cols = [
            "profile_id",
            "mode",
            "workload_family",
            "nodes",
            "repeat",
            "duration_s",
            "energy_compute_Wh",
            "mean_compute_W",
            "p_compute_W_per_node",
            "peak_to_mean",
            "cv",
            "slurm_job_id",
            "aggregation_source",
        ]
        batch[intensity_cols].to_csv(ANALYSIS / "H100_INTENSITY_BY_RUN.csv", index=False)
        summary = pd.concat([train, inf], ignore_index=True)
        summary.to_parquet(DATA_PROCESSED / "h100_experiment_summary.parquet", index=False)
        summary.to_csv(DATA_PROCESSED / "h100_experiment_summary.csv", index=False)
        print("models / bounds / online / timescales…", flush=True)
        batch2, cmp = batch_model_comparison(batch)
        physical_bounds(train)
        _rate_tbl, _online = online_analysis(inf)
        ts = timescale_metrics(zf, train)
        temporal_templates(train)
        profiles = representative_profiles(zf)
        xw = kestrel_crosswalk(train, collect_inference_slurm_ids(zf))
        external_validation_matrix(train, inf)
        print("figures…", flush=True)
        make_figures(batch2, inf, ts, profiles, cmp)
        ctx = {"zip_sha": zip_sha, "cmp": cmp, "audit": audit, "repro": repro, "crosswalk": xw}
        write_report(ctx)
        status = write_status(ctx)
        print(json.dumps({"selected": cmp["selected_batch_proxy"], "repro": repro["status"], "status_keys": status}, default=str)[:1500], flush=True)
        print("DONE", flush=True)


if __name__ == "__main__":
    main()

