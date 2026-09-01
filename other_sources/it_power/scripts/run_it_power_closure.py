#!/usr/bin/env python3
"""IT-power closure: freeze NLR H100 compute, replicate independently, bound node overhead.

Does not refit frozen Kestrel CPU. Does not populate historical H100 jobs.
Does not treat 8-GPU literature nodes as the 4-GPU Kestrel node.
"""
from __future__ import annotations

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

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from it_power_paths import (  # noqa: E402
    ANALYSIS,
    CPU_DISPOSITION,
    CPU_FREEZE,
    CPU_P_KW,
    CPU_STATUS,
    COOLING_PAPER,
    DATA_PROCESSED,
    DOCS,
    ELSAYED_PAPER,
    EXTRACTED,
    FIGSHARE_SHA256,
    FIGSHARE_ZIP,
    FIGURES,
    GENAI_SHA256,
    GENAI_ZIP,
    H100_INTENSITY,
    H100_ROOT,
    H100_RUNNER,
    H100_STATUS,
    H100_SUMMARY,
    IT_ROOT,
    KESTREL_JOBS,
    LATIF_PAPER,
    MANIFESTS,
    NEWKIRK_ALPHA,
    NEWKIRK_BETA_CNN_KW,
    NEWKIRK_BETA_LLM_KW,
    NEWKIRK_INSAMPLE_MAPE_ARCH,
    NEWKIRK_OOS_MAPE_PUBLISHED,
    NEWKIRK_PAPER,
    NEWKIRK_PIDLE_KW,
    NEWKIRK_PMAX_KW,
    NEWKIRK_ZIP,
    NEWKIRK_ZIP_SHA256,
    NLR_ROOT,
    REPO_ROOT,
    TESTS,
)

H100_SCRIPTS = H100_ROOT / "scripts"
sys.path.insert(0, str(H100_SCRIPTS))
from h100_paths import CPU_SOCKETS_PER_NODE, GPUS_PER_NODE  # noqa: E402
from run_h100_experiment import (  # noqa: E402
    cpu_power_series,
    gpu_power_series,
    native_component_integrals,
    read_nvml_log,
    read_rapl_log,
    series_energy,
    source_align_sum,
    summarize_parquet_power,
    trapz_energy_w,
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
    if pd.isna(x):
        return None
    raise TypeError(type(x))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_cmd(*args) -> str:
    r = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)
    return (r.stdout or r.stderr or "").strip()


def mape(y, yhat) -> float:
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    m = np.abs(y) > 0
    return float(np.mean(np.abs(y[m] - yhat[m]) / np.abs(y[m])))


def wape(y, yhat) -> float:
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    return float(np.abs(y - yhat).sum() / np.abs(y).sum())


def mae(y, yhat) -> float:
    return float(np.mean(np.abs(np.asarray(y, dtype=float) - np.asarray(yhat, dtype=float))))


def write_initial_state() -> dict:
    for p in (MANIFESTS, ANALYSIS, DOCS, DATA_PROCESSED, FIGURES, TESTS):
        p.mkdir(parents=True, exist_ok=True)
    cpu = json.loads(CPU_STATUS.read_text())
    h100 = json.loads(H100_STATUS.read_text())
    files = {
        "cpu_status": CPU_STATUS,
        "cpu_freeze": CPU_FREEZE,
        "h100_status": H100_STATUS,
        "h100_runner": H100_RUNNER,
        "h100_intensity": H100_INTENSITY,
        "h100_summary": H100_SUMMARY,
        "genai_zip": GENAI_ZIP,
        "figshare_zip": FIGSHARE_ZIP,
        "newkirk_zip": NEWKIRK_ZIP,
    }
    hashes = {k: (sha256_file(p) if p.exists() else None) for k, p in files.items()}
    it_contents = sorted(
        str(p.relative_to(IT_ROOT))
        for p in IT_ROOT.rglob("*")
        if p.is_file() and "__pycache__" not in str(p)
    )
    state = {
        "public_baseline_commit_requested": "9355b4d035914b24df9baaaa1ef6e41e6c57a29a",
        "git": {
            "branch": git_cmd("rev-parse", "--abbrev-ref", "HEAD"),
            "HEAD": git_cmd("rev-parse", "HEAD"),
            "status": git_cmd("status", "--short"),
        },
        "cpu": {
            "CPU_LAYER_FINAL_DISPOSITION": cpu.get("CPU_LAYER_FINAL_DISPOSITION"),
            "expected": CPU_DISPOSITION,
            "p_KestrelCPU_W_per_node": cpu.get("p_KestrelCPU_W_per_node"),
            "read_only": True,
            "refit": False,
        },
        "h100_before_this_pass": h100,
        "file_sha256": hashes,
        "existing_it_power_files": it_contents,
        "constraints": {
            "do_not_refit_cpu": True,
            "do_not_rebuild_nlr_h100_from_scratch": True,
            "do_not_populate_historical_h100_jobs": True,
            "do_not_fit_cooling_weather": True,
            "do_not_halve_8gpu_as_kestrel": True,
            "do_not_invent_psu_efficiency": True,
            "do_not_treat_tdp_as_measured": True,
            "no_meta_access": True,
        },
    }
    if cpu.get("CPU_LAYER_FINAL_DISPOSITION") != CPU_DISPOSITION:
        raise RuntimeError("CPU layer is not frozen")
    jdump(MANIFESTS / "IT_POWER_CLOSURE_INITIAL_STATE.json", state)
    return state


def reconstruct_sd_n1() -> pd.DataFrame:
    raw_dir = EXTRACTED / "00_raw_datasets/training_stable_diffusion/1node"
    if not raw_dir.exists() or not list(raw_dir.glob("*.log")):
        raw_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(GENAI_ZIP) as z:
            for n in z.namelist():
                if n.startswith("00_raw_datasets/training_stable_diffusion/1node/") and n.endswith(".log"):
                    dest = EXTRACTED / n
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if not dest.exists():
                        dest.write_bytes(z.read(n))
    logs = sorted(raw_dir.glob("*.log"))
    by_job = defaultdict(list)
    for p in logs:
        m = re.search(r"slurmid_(\d+)", p.name)
        if not m:
            continue
        by_job[m.group(1)].append(p)
    rows = []
    traces = []
    out_dir = EXTRACTED / "01_aggregated_datasets/training/results_sd_n1_reconstructed"
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, (sid, paths) in enumerate(sorted(by_job.items())):
        series = []
        raw_pairs = []
        for p in paths:
            raw = p.read_bytes()
            raw_pairs.append((str(p.relative_to(EXTRACTED)), raw))
            if p.name.startswith("nvml"):
                series.append(gpu_power_series(read_nvml_log(raw)))
            else:
                series.append(cpu_power_series(read_rapl_log(raw), include_core=True))
        regen = source_align_sum(series, 0.2)
        regen.to_parquet(out_dir / f"sd_n1_{sid}.parquet")
        s = summarize_parquet_power(regen)
        nat = native_component_integrals(raw_pairs)
        p_i = (s["energy_Wh"] * 3600.0) / (1.0 * s["duration_s"])
        rows.append(
            {
                "profile_id": f"sd_n1_rawrecon_{sid}",
                "provenance": "RAW_RECONSTRUCTED_SOURCE_RUN",
                "not_author_supplied_aggregate": True,
                "slurm_job_id": int(sid),
                "mode": "training",
                "workload_family": "stable_diffusion",
                "nodes": 1,
                "gpus": GPUS_PER_NODE,
                "gpus_per_node": GPUS_PER_NODE,
                "cpu_sockets": CPU_SOCKETS_PER_NODE,
                "duration_s": s["duration_s"],
                "energy_gpu_Wh": nat["E_GPU_J"] / 3600.0,
                "energy_cpu_source_Wh": nat["E_CPU_source_sum_J"] / 3600.0,
                "energy_cpu_package_only_Wh": nat["E_CPU_package_only_J"] / 3600.0,
                "energy_compute_Wh": s["energy_Wh"],
                "p_compute_W_per_node": p_i,
                "mean_compute_W": s["mean_W"],
                "max_compute_W": s["max_W"],
                "peak_to_mean": s["peak_to_mean"],
                "cv": s["cv"],
                "core_fraction_of_cpu_energy": nat["core_fraction_of_cpu_energy"],
                "aggregation_source": "this_module_source_pipeline_on_raw_logs",
                "batch_like": True,
                "experimental_unit": "independent_run",
            }
        )
        traces.append((sid, regen))
    df = pd.DataFrame(rows)
    df.to_csv(H100_ROOT / "analysis" / "H100_SD_N1_RECONSTRUCTED.csv", index=False)
    return df, traces


def rapl_accounting() -> dict:
    split = pd.read_csv(H100_ROOT / "analysis" / "H100_TRAINING_GPU_CPU_SPLIT.csv")
    split["dE_cpu_Wh"] = split["E_CPU_Wh"] - split["E_CPU_package_only_Wh"]
    split["pct_of_compute"] = split["dE_cpu_Wh"] / split["E_compute_native_Wh"]
    intensity = pd.read_csv(H100_INTENSITY)
    dur = intensity.dropna(subset=["slurm_job_id"]).drop_duplicates("slurm_job_id")[
        ["slurm_job_id", "duration_s", "nodes"]
    ]
    dur["slurm_job_id"] = dur.slurm_job_id.astype(int)
    split["slurmid"] = split.slurmid.astype(int)
    m = split.merge(dur, left_on="slurmid", right_on="slurm_job_id", how="left")
    sd1_path = H100_ROOT / "analysis" / "H100_SD_N1_RECONSTRUCTED.csv"
    if sd1_path.exists():
        sd1 = pd.read_csv(sd1_path)
        miss = m["duration_s"].isna()
        if miss.any():
            sdmap = sd1.set_index("slurm_job_id")["duration_s"]
            m.loc[miss, "duration_s"] = m.loc[miss, "slurmid"].map(sdmap)
            nmap = sd1.set_index("slurm_job_id")["nodes"]
            m.loc[m["nodes"].isna(), "nodes"] = m.loc[m["nodes"].isna(), "slurmid"].map(nmap)
    m["dW_cpu_source_minus_package"] = m["dE_cpu_Wh"] * 3600.0 / m["duration_s"]
    # source CPU is package+core; package-only is lower, so source-minus-package > 0
    rec = {
        "source_reproduction_cpu_definition": "package + core (authors postprocess.py)",
        "preferred_physical_cpu": "package only",
        "n_training_jobs_in_split": int(len(split)),
        "median_core_fraction_of_cpu_energy": float(split.core_fraction_of_cpu_energy.median()),
        "mean_core_fraction_of_cpu_energy": float(split.core_fraction_of_cpu_energy.mean()),
        "median_source_minus_package_W": float(m.dW_cpu_source_minus_package.median()),
        "mean_source_minus_package_W": float(m.dW_cpu_source_minus_package.mean()),
        "max_source_minus_package_W": float(m.dW_cpu_source_minus_package.max()),
        "median_package_minus_source_W_proxy": float(-m.dW_cpu_source_minus_package.median()),
        "median_dE_cpu_Wh": float(split.dE_cpu_Wh.median()),
        "median_pct_of_cpu_gpu_compute_energy": float(split.pct_of_compute.median()),
        "max_pct_of_cpu_gpu_compute_energy": float(split.pct_of_compute.max()),
        "refit_because_of_this": False,
        "reason": "Difference is <<1% of measured compute energy; keep source-reproduction totals; report package-only as physical CPU.",
    }
    jdump(H100_ROOT / "analysis" / "H100_RAPL_PHYSICAL_ACCOUNTING.json", rec)
    return rec


def par_table(sd1_traces) -> pd.DataFrame:
    windows = [None, 1.0, 10.0, 60.0, 300.0]  # None = native
    md = pd.read_csv(EXTRACTED / "01_aggregated_datasets/training/metadata.csv")
    rows = []

    def add(wl, nodes, pid, t, p, native_dt):
        duration = float(t[-1] - t[0]) if len(t) else 0
        native_par = float(p.max() / p.mean()) if p.mean() else None
        for dt in [native_dt, 1.0, 10.0, 60.0, 300.0]:
            if dt < native_dt - 1e-9:
                continue
            if duration < 2 * dt and dt != native_dt:
                continue
            if abs(dt - native_dt) < 1e-12:
                pg = p
            else:
                grid = np.arange(t[0], t[-1] + 1e-12, dt)
                if len(grid) < 2:
                    continue
                pg = np.interp(grid, t, p)
            mean = float(pg.mean())
            rows.append(
                {
                    "workload_family": wl,
                    "nodes": nodes,
                    "profile_id": pid,
                    "resolution_s": dt,
                    "native_dt_s": native_dt,
                    "PAR": float(pg.max() / mean) if mean else None,
                    "cv": float(pg.std(ddof=1) / mean) if mean and len(pg) > 1 else None,
                    "mean_compute_W": mean,
                    "max_compute_W": float(pg.max()),
                }
            )

    for rec in md.itertuples():
        rel = str(rec.path_save).replace("training/", "01_aggregated_datasets/training/")
        fp = EXTRACTED / rel
        if not fp.exists():
            continue
        df = pd.read_parquet(fp)
        add(rec.model, int(rec.nodes), f"train_{Path(rel).stem}", df.index.to_numpy(float), df["power[W]"].to_numpy(float), 0.2)
    for sid, regen in sd1_traces:
        add("stable_diffusion", 1, f"sd_n1_{sid}", regen.index.to_numpy(float), regen["power[W]"].to_numpy(float), 0.2)
    # representative inference already extracted
    for folder, wl, nodes, native in (
        ("inference_offline_llama3_70b", "llama3_70b_offline_inference", 1, 0.1),
        ("inference_online_rate_llama3_70b", "llama3_70b_online_rate", 1, 0.1),
    ):
        files = sorted((EXTRACTED / "01_aggregated_datasets" / folder / "results").glob("*.parquet"))
        for fp in files[:4]:
            df = pd.read_parquet(fp)
            add(wl, nodes, f"{folder}_{fp.stem}", df.index.to_numpy(float), df["power[W]"].to_numpy(float), native)
    out = pd.DataFrame(rows)
    compact = (
        out.groupby(["workload_family", "nodes", "resolution_s"], dropna=False)["PAR"]
        .agg(["count", "mean", "median", "std", "min", "max"])
        .reset_index()
        .rename(columns={"count": "n_profiles", "mean": "PAR_mean", "median": "PAR_median", "std": "PAR_std", "min": "PAR_min", "max": "PAR_max"})
    )
    compact.to_csv(H100_ROOT / "analysis" / "H100_PAR_BY_WORKLOAD_NODE_RESOLUTION.csv", index=False)
    out.to_csv(H100_ROOT / "analysis" / "H100_PAR_BY_PROFILE.csv", index=False)
    return compact


def p_wn_table(sd1: pd.DataFrame) -> pd.DataFrame:
    intensity = pd.read_csv(H100_INTENSITY)
    train = intensity[intensity["mode"].astype(str).str.contains("train")].copy()
    extra = sd1[["workload_family", "nodes", "p_compute_W_per_node", "duration_s", "energy_compute_Wh", "profile_id"]].copy()
    extra["mode"] = "training"
    extra["provenance"] = "RAW_RECONSTRUCTED_SOURCE_RUN"
    train["provenance"] = "AUTHOR_SUPPLIED_AGGREGATE"
    cols = ["workload_family", "nodes", "p_compute_W_per_node", "duration_s", "energy_compute_Wh", "provenance"]
    both = pd.concat([train[cols], extra[cols]], ignore_index=True)
    tab = (
        both.groupby(["workload_family", "nodes", "provenance"])["p_compute_W_per_node"]
        .agg(["count", "mean", "std", "min", "max"])
        .reset_index()
        .rename(columns={"count": "n_runs", "mean": "p_W_per_node", "std": "p_std", "min": "p_min", "max": "p_max"})
    )
    tab["cv"] = tab["p_std"] / tab["p_W_per_node"]
    tab.to_csv(H100_ROOT / "analysis" / "H100_P_W_N_TABLE.csv", index=False)
    # config-defined saturated anchor (ex-ante fields only)
    sat = both[
        ((both.workload_family.isin(["llama2_70b_lora", "stable_diffusion"])) & (both.nodes <= 2))
    ]
    off = intensity[intensity["mode"] == "offline_inference"].copy() if "mode" in intensity.columns else pd.DataFrame()
    rec = {
        "canonical_batch_object": "E_compute = p_{w,N} * N * tau",
        "not_a_universal_default": True,
        "SATURATED_COMPUTE_SCENARIO_ANCHOR": {
            "definition_ex_ante": "training llama2_70b_lora or stable_diffusion with N<=2 (workload + node count, not observed watts)",
            "n_runs": int(len(sat)),
            "mean_p_W_per_node": float(sat.p_compute_W_per_node.mean()),
            "std_p_W_per_node": float(sat.p_compute_W_per_node.std(ddof=1)),
            "rounded_anchor_W_per_node": 2650.0,
            "use": "scenario illustration only; not a predictive rule; not a universal H100 default",
        },
        "offline_large_batch_is_separate_config": "batch_size is an ex-ante field for offline inference; not merged into the 2650 training-N<=2 anchor",
    }
    jdump(H100_ROOT / "analysis" / "H100_SATURATED_ANCHOR.json", rec)
    return tab, rec


def freeze_h100(sd1, rapl, par, ptab, sat) -> dict:
    intensity = pd.read_csv(H100_INTENSITY)
    n_train_auth = int(intensity["mode"].astype(str).str.contains("train").sum())
    freeze = {
        "H100_COMPUTE_LAYER": "FROZEN_PASS_WITH_DOMAIN_RESTRICTIONS",
        "source": {
            "doi": "10.7799/3025227",
            "sha256": GENAI_SHA256,
            "catalog_version": 2,
        },
        "measurement_boundary": "P_compute = P_GPU_NVML + P_CPU_RAPL; not full-node/system power",
        "P_other_node": "UNRESOLVED_IN_THIS_LAYER",
        "final_experiment_count": {
            "author_supplied_training_runs": n_train_auth,
            "sd_n1_raw_reconstructed": int(len(sd1)),
            "offline_inference": int((intensity["mode"] == "offline_inference").sum()) if "mode" in intensity.columns else None,
            "experimental_unit": "independent_run_not_time_sample",
        },
        "sd_n1": {
            "n_runs": int(len(sd1)),
            "provenance": "RAW_RECONSTRUCTED_SOURCE_RUN",
            "mean_p_W_per_node": float(sd1.p_compute_W_per_node.mean()),
            "std_p_W_per_node": float(sd1.p_compute_W_per_node.std(ddof=1)),
            "cv": float(sd1.p_compute_W_per_node.std(ddof=1) / sd1.p_compute_W_per_node.mean()),
            "mean_duration_s": float(sd1.duration_s.mean()),
            "mean_energy_gpu_Wh": float(sd1.energy_gpu_Wh.mean()),
            "mean_energy_cpu_source_Wh": float(sd1.energy_cpu_source_Wh.mean()),
            "mean_energy_compute_Wh": float(sd1.energy_compute_Wh.mean()),
            "supports_1_2_node_high_intensity": True,
        },
        "rapl_physical_package_only": rapl,
        "canonical_batch": "E_compute = p_{w,N} * N * tau",
        "p_w_N_table": ptab.to_dict("records"),
        "saturated_anchor": sat,
        "temporal": {
            "no_universal_PAR_1_25": True,
            "table": "analysis/H100_PAR_BY_WORKLOAD_NODE_RESOLUTION.csv",
            "templates": "2-node llama and SD only, mean(phi)=1",
        },
        "online_inference": "ONLINE_INFERENCE_SCENARIO_LIBRARY not GENERAL_ONLINE_INFERENCE_MODEL",
        "statuses": {
            "BATCH_HARDWARE_HOURS_FORM": "PASS",
            "WORKLOAD_INDEPENDENT_P": "FAIL",
            "WORKLOAD_CONDITIONED_P": "PASS",
            "WORKLOAD_SCALE_CONDITIONED_P": "PASS",
            "ONLINE_INFERENCE_SCENARIO_LIBRARY": "PASS",
            "GENERAL_ONLINE_INFERENCE_MODEL": "UNSUPPORTED",
            "TEMPORAL_PROFILE_LIBRARY": "PASS",
            "FULL_NODE_SYSTEM_POWER": "UNSUPPORTED",
        },
        "nlr_coefficients_will_not_be_refit_to_external_node_data": True,
        "limitations": [
            "CPU+GPU != full node AC",
            "controlled benchmarks != production H100 mix",
            "AMD RAPL partially validated",
            "SD N=1 is RAW_RECONSTRUCTED_SOURCE_RUN",
        ],
    }
    jdump(H100_ROOT / "manifests" / "H100_COMPUTE_FINAL_FREEZE.json", freeze)
    prev = json.loads(H100_STATUS.read_text())
    prev["H100_COMPUTE_LAYER"] = freeze["H100_COMPUTE_LAYER"]
    prev["statuses_v2"] = freeze["statuses"]
    prev["canonical_batch"] = freeze["canonical_batch"]
    prev["selected_batch_proxy"] = "E_compute = p_{w,N} * N * tau"
    prev["canonical_objects"] = {
        "A_batch_like": {
            "form": "E_compute = p_{w,N} * N * tau",
            "table": "analysis/H100_P_W_N_TABLE.csv",
            "SATURATED_COMPUTE_SCENARIO_ANCHOR": "ex-ante training llama2_70b_lora or stable_diffusion with N<=2; ~2650 W/node illustration only; not a universal default",
            "boundary": "CPU+GPU component only",
        },
        "B_online_inference": {
            "form": "discrete P_compute(request_rate, configuration)",
            "status": "ONLINE_INFERENCE_SCENARIO_LIBRARY",
            "not": "GENERAL_ONLINE_INFERENCE_MODEL",
        },
        "C_temporal": {
            "form": "PAR_{workload,node_count,resolution}",
            "no_universal_PAR": True,
            "templates": "2-node llama and SD only",
        },
    }
    prev.pop("p_gpu_saturated_1_2_node_W", None)
    jdump(H100_ROOT / "results" / "FINAL_H100_POWER_STATUS.json", prev)
    return freeze


def write_independent_provenance() -> dict:
    zpath = FIGSHARE_ZIP
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        node = [n for n in names if "/Node_Dataset/" in n and n.endswith(".csv")]
        unique = sorted({Path(n).name for n in node})
        license_txt = ""
        if any(n.endswith("/LICENSE") for n in names):
            license_txt = z.read(next(n for n in names if n.endswith("/LICENSE"))).decode()[:200]
    rec = {
        "paper": "Elsayed, Al-Obaidi & Farag, Scientific Data 2026",
        "source_doi": "10.1038/s41597-026-07496-6",
        "figshare_doi": "10.6084/m9.figshare.31654879",
        "figshare_version": "local archive as downloaded; DOI has no .vN suffix on the zip filename",
        "local_path": str(zpath.relative_to(REPO_ROOT)) if zpath.exists() else None,
        "sha256": FIGSHARE_SHA256,
        "bytes": int(zpath.stat().st_size) if zpath.exists() else None,
        "license": "CC BY-NC-ND 4.0",
        "license_header": license_txt.split("\n")[0] if license_txt else None,
        "rtx3060_processed": False,
        "node_csv_copies_in_zip": len(node) if zpath.exists() else None,
        "unique_node_session_files": len(unique) if zpath.exists() else None,
        "hardware_session_mapping": {
            "H100": {
                "site": "Lambda Cloud datacenter node",
                "GPU": "8x H100 SXM 80GB",
                "CPU": "Intel Xeon 208 vCPU",
                "RAM_GB": 1800,
                "OS": "Ubuntu Server 22.04",
                "n_sessions_used": 16,
                "sampling": "20 ms pynvml",
                "session_duration_s": 900,
                "boundary": "sum of 8 gpu{i}_power_W; cpu_power_W all-NaN on node CSVs",
            },
            "B200": {
                "site": "Lambda Cloud datacenter node",
                "GPU": "8x B200 180GB",
                "CPU": "Intel Xeon 208 vCPU",
                "RAM_GB": 2900,
                "OS": "Ubuntu Server 22.04",
                "n_sessions_used": 16,
                "sampling": "20 ms pynvml",
                "session_duration_s": 900,
                "boundary": "sum of 8 gpu{i}_power_W; cpu_power_W all-NaN on node CSVs",
            },
            "RTX_3060_not_processed": {
                "reason": "consumer desktop; not a datacenter node; no metadata dependency required it",
            },
        },
        "purpose": "Independent replication of workload/util structure only; not a second primary H100 model",
        "experimental_unit": "independent_session",
    }
    jdump(MANIFESTS / "INDEPENDENT_GPU_SOURCE_PROVENANCE.json", rec)
    return rec


def independent_gpu() -> tuple[pd.DataFrame, dict]:
    zpath = FIGSHARE_ZIP
    sessions = {}
    with zipfile.ZipFile(zpath) as z:
        for n in z.namelist():
            if "/Node_Dataset/" not in n or not n.endswith(".csv"):
                continue
            base = Path(n).name
            if base in sessions:
                continue  # duplicate copies across impact folders
            hw = "H100" if "_H100_" in base else ("B200" if "_B200_" in base else None)
            fam = "LLM" if base.startswith("LLM_") else ("diffusion" if base.startswith("Image_generation_") else "other")
            usecols = ["cpu_power_W"]
            for i in range(8):
                usecols += [f"gpu{i}_power_W", f"gpu{i}_utilization_percent", f"gpu{i}_mem_utilization"]
            df = pd.read_csv(z.open(n), usecols=lambda c: c in usecols)
            gpu_p = df[[f"gpu{i}_power_W" for i in range(8)]].sum(axis=1)
            gpu_u = df[[f"gpu{i}_utilization_percent" for i in range(8)]].mean(axis=1)
            mem_u = df[[f"gpu{i}_mem_utilization" for i in range(8)]].mean(axis=1)
            cpu = df["cpu_power_W"]
            sessions[base] = {
                "session": base.replace(".csv", ""),
                "source_member": n,
                "hardware": hw,
                "workload_family": fam,
                "n_samples": int(len(df)),
                "duration_s": float(len(df) * 0.02),  # paper: 20 ms node-scale
                "mean_gpu_sum_W": float(gpu_p.mean()),
                "mean_gpu_W_per_device": float(gpu_p.mean() / 8.0),
                "mean_cpu_W": float(cpu.mean()) if cpu.notna().any() else None,
                "cpu_power_present": bool(cpu.notna().any()),
                "mean_gpu_util_pct": float(gpu_u.mean()),
                "mean_mem_util": float(mem_u.mean()),
                "mean_gpu_temp_not_used_in_models": True,
            }
    sess = pd.DataFrame(sessions.values())
    sess["experimental_unit"] = "independent_session"
    sess.to_csv(ANALYSIS / "INDEPENDENT_H100_B200_SESSIONS.csv", index=False)
    return analyze_independent_sessions(sess)


def analyze_independent_sessions(sess: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    def fit_m1(d):
        x = d["mean_gpu_util_pct"].to_numpy(float)
        y = d["mean_gpu_sum_W"].to_numpy(float)
        A = np.column_stack([np.ones(len(x)), x])
        coef, *_ = np.linalg.lstsq(A, y, rcond=None)
        return float(coef[0]), float(coef[1])

    recs = []
    for hw, g in sess.groupby("hardware"):
        y = g["mean_gpu_sum_W"].to_numpy(float)
        yhat0 = np.full_like(y, y.mean())
        a, b = fit_m1(g)
        yhat1 = a + b * g["mean_gpu_util_pct"].to_numpy(float)
        recs.append({"hardware": hw, "model": "M0_hw_mean", "n": int(len(g)), "MAE": mae(y, yhat0), "WAPE": wape(y, yhat0), "a": float(y.mean()), "b": 0.0})
        recs.append({"hardware": hw, "model": "M1_util", "n": int(len(g)), "MAE": mae(y, yhat1), "WAPE": wape(y, yhat1), "a": a, "b": b})

    # leave-one-family-out within H100
    h100 = sess[sess.hardware == "H100"]
    loo = []
    for fam in h100.workload_family.unique():
        tr = h100[h100.workload_family != fam]
        te = h100[h100.workload_family == fam]
        if len(tr) < 2 or len(te) < 1:
            continue
        a, b = fit_m1(tr)
        yhat = a + b * te["mean_gpu_util_pct"].to_numpy(float)
        y = te["mean_gpu_sum_W"].to_numpy(float)
        loo.append({"held_out_family": fam, "n_test": int(len(te)), "MAE": mae(y, yhat), "WAPE": wape(y, yhat), "a_train": a, "b_train": b})

    # H100 -> B200 and reverse (do not silently reuse)
    b200 = sess[sess.hardware == "B200"]
    a_h, b_h = fit_m1(h100)
    a_b, b_b = fit_m1(b200)
    y_b = b200["mean_gpu_sum_W"].to_numpy(float)
    y_h = h100["mean_gpu_sum_W"].to_numpy(float)
    h2b = a_h + b_h * b200["mean_gpu_util_pct"].to_numpy(float)
    b2h = a_b + b_b * h100["mean_gpu_util_pct"].to_numpy(float)
    transfer = {
        "H100_to_B200": {"MAE": mae(y_b, h2b), "WAPE": wape(y_b, h2b), "note": "H100 M1 coefficients applied to B200 utilization; intercept not retuned"},
        "B200_to_H100": {"MAE": mae(y_h, b2h), "WAPE": wape(y_h, b2h), "note": "B200 M1 coefficients applied to H100 utilization; intercept not retuned"},
        "H100_M1": {"a": a_h, "b": b_h},
        "B200_M1": {"a": a_b, "b": b_b},
        "transfer_supported": False,
    }
    # workload means
    wl = sess.groupby(["hardware", "workload_family"])["mean_gpu_sum_W"].agg(["count", "mean", "std"]).reset_index()
    # M2 only if M1 residual systematic by mem util
    resid = h100["mean_gpu_sum_W"] - (a_h + b_h * h100["mean_gpu_util_pct"])
    corr_mem = float(np.corrcoef(resid, h100["mean_mem_util"])[0, 1]) if len(h100) > 2 else None
    m2_needed = bool(corr_mem is not None and abs(corr_mem) > 0.5)
    m2_rec = {"corr_residual_vs_mem": corr_mem, "run_M2": m2_needed}
    if m2_needed:
        X = np.column_stack(
            [
                np.ones(len(h100)),
                h100["mean_gpu_util_pct"].to_numpy(float),
                h100["mean_mem_util"].to_numpy(float),
            ]
        )
        coef, *_ = np.linalg.lstsq(X, h100["mean_gpu_sum_W"].to_numpy(float), rcond=None)
        yhat2 = X @ coef
        y = h100["mean_gpu_sum_W"].to_numpy(float)
        m2_rec.update(
            {
                "a": float(coef[0]),
                "b_gpu_util": float(coef[1]),
                "c_mem_util": float(coef[2]),
                "MAE": mae(y, yhat2),
                "WAPE": wape(y, yhat2),
                "note": "Diagnostic only; not a project-wide H100 model. Hardware-class H100 sessions.",
            }
        )
    # leave-one-session-out M1 within H100 (unit = session)
    loo_sess = []
    h100_idx = list(h100.index)
    for i in h100_idx:
        tr = h100.drop(index=i)
        te = h100.loc[[i]]
        a, b = fit_m1(tr)
        yhat = a + b * float(te["mean_gpu_util_pct"].iloc[0])
        y = float(te["mean_gpu_sum_W"].iloc[0])
        loo_sess.append({"session": te["session"].iloc[0], "y": y, "yhat": yhat, "abs_err": abs(y - yhat)})
    loo_sess_mae = float(np.mean([r["abs_err"] for r in loo_sess])) if loo_sess else None
    loo_sess_wape = (
        float(sum(r["abs_err"] for r in loo_sess) / sum(abs(r["y"]) for r in loo_sess)) if loo_sess else None
    )
    # energy bias: all sessions are 900 s, so energy WAPE equals power WAPE; still report explicitly
    dur = sess["duration_s"].to_numpy(float)
    for rec in recs:
        hw = rec["hardware"]
        g = sess[sess.hardware == hw]
        y = g["mean_gpu_sum_W"].to_numpy(float)
        d = g["duration_s"].to_numpy(float)
        if rec["model"] == "M0_hw_mean":
            yhat = np.full_like(y, rec["a"])
        else:
            yhat = rec["a"] + rec["b"] * g["mean_gpu_util_pct"].to_numpy(float)
        e = y * d
        ehat = yhat * d
        rec["energy_bias_frac"] = float((ehat.sum() - e.sum()) / e.sum()) if e.sum() else None
    out = {
        "n_sessions": int(len(sess)),
        "n_H100": int((sess.hardware == "H100").sum()),
        "n_B200": int((sess.hardware == "B200").sum()),
        "rtx3060_processed": False,
        "cpu_power_on_node_csvs": "ABSENT_ALL_NA",
        "experimental_unit": "independent_session",
        "not_n": "20ms samples",
        "boundary": "sum of 8 GPU pynvml powers; not full-node AC",
        "M0_M1": recs,
        "leave_one_family_out_H100": loo,
        "transfer": transfer,
        "M2_memory": m2_rec,
        "leave_one_session_out_H100_M1": {
            "n": len(loo_sess),
            "MAE": loo_sess_mae,
            "WAPE": loo_sess_wape,
            "experimental_unit": "independent_session",
        },
        "workload_means": wl.to_dict("records"),
        "implication": (
            "Workload family changes session-mean GPU-sum power on both H100 and B200, "
            "replicating NLR's qualitative workload-conditioning result. "
            "GPU utilization is a useful within-hardware predictor. "
            "H100 coefficients do not transfer to B200."
        ),
    }
    pd.DataFrame(recs).to_csv(ANALYSIS / "INDEPENDENT_H100_B200_REPLICATION.csv", index=False)
    jdump(ANALYSIS / "INDEPENDENT_H100_B200_REPLICATION.json", out)
    return sess, out


def newkirk_reproduction() -> dict:
    with zipfile.ZipFile(NEWKIRK_ZIP) as z:
        w = pd.read_csv(z.open("workload_data_export.csv"))
        t = pd.read_csv(z.open("testset_data_export.csv"))
    def run_summary(df, power_col="tot_power"):
        g = df.groupby("runtype")
        return g.agg(
            n_rows=(power_col, "size"),
            n_nodes_field=("nodes", "first"),
            n_identifiers=("identifier", "nunique"),
            architecture=("architecture", "first"),
            source=("source" if "source" in df.columns else "Source", "first"),
            mean_power_W=("power", "mean"),
            mean_tot_power_W=(power_col, "mean"),
            p50_tot_W=(power_col, "median"),
            max_tot_W=(power_col, "max"),
            energy_Wh=("estimated_power_consumption", "sum"),
            duration_min=("elapsed_time_min", "max"),
        ).reset_index()
    ws = run_summary(w)
    ts = run_summary(t)
    # published architecture-specific asymptotic, high-util limit ~ Pidle+beta; use FLOPS/node as x
    def yhat_arch(row):
        arch = str(row.get("architecture", "")).upper()
        beta = NEWKIRK_BETA_LLM_KW if "LLM" in arch else NEWKIRK_BETA_CNN_KW
        # If FLOPS/node missing, use saturation (high-util) prediction.
        flops = row.get("flops_node", np.nan)
        if pd.isna(flops) or flops <= 0:
            frac = 1.0
        else:
            x = np.log(float(flops))
            frac = x / (NEWKIRK_ALPHA + x) if (NEWKIRK_ALPHA + x) != 0 else 1.0
            frac = min(max(frac, 0.0), 1.0)
        y = NEWKIRK_PIDLE_KW + beta * frac
        return min(y, NEWKIRK_PMAX_KW) * 1000.0  # W

    # attach flops_node means
    if "flops_node" in w.columns:
        ws = ws.merge(w.groupby("runtype")["flops_node"].mean(), on="runtype", how="left")
    if "flops_node" in t.columns:
        ts = ts.merge(t.groupby("runtype")["flops_node"].mean(), on="runtype", how="left")
    ws["yhat_arch_W"] = ws.apply(yhat_arch, axis=1)
    ts["yhat_arch_W"] = ts.apply(yhat_arch, axis=1)
    in_mape = mape(ws.mean_tot_power_W, ws.yhat_arch_W)
    oos_mape = mape(ts.mean_tot_power_W, ts.yhat_arch_W)
    # Sample-level power MAPE is a diagnostic of the published formula on the open
    # rows; it is NOT the experimental unit and is NOT the paper's energy MAPE.
    def _row_yhat(df):
        arch = df["architecture"].astype(str).str.upper()
        beta = np.where(arch.str.contains("LLM"), NEWKIRK_BETA_LLM_KW, NEWKIRK_BETA_CNN_KW)
        x = np.log(np.maximum(df["flops_node"].to_numpy(float), 1.0))
        frac = np.clip(x / (NEWKIRK_ALPHA + x), 0.0, 1.0)
        y = np.minimum(NEWKIRK_PIDLE_KW + beta * frac, NEWKIRK_PMAX_KW) * 1000.0
        return y
    w_yhat = _row_yhat(w)
    t_yhat = _row_yhat(t)
    sample_in = mape(w.tot_power, w_yhat)
    sample_oos = mape(t.tot_power, t_yhat)
    rec = {
        "paper": "Newkirk et al. 2025 Environ. Res.: Energy / DOI 10.1088/2753-3751/ae2486",
        "open_data_doi": "10.1184/R1/29067572.v1",
        "zip_sha256": NEWKIRK_ZIP_SHA256,
        "lineage": "Includes BNL measurements that are the Latif et al. 2025 8-GPU HGX campaign; do not count Latif as an independent sample",
        "preferred_specification": {
            "name": "architecture-specific asymptotic",
            "Pidle_kW": NEWKIRK_PIDLE_KW,
            "alpha": NEWKIRK_ALPHA,
            "beta_LLM_kW": NEWKIRK_BETA_LLM_KW,
            "beta_CNN_kW": NEWKIRK_BETA_CNN_KW,
            "Pmax_kW_empirical_cap": NEWKIRK_PMAX_KW,
            "published_insample_MAPE": NEWKIRK_INSAMPLE_MAPE_ARCH,
            "published_oos_MAPE": NEWKIRK_OOS_MAPE_PUBLISHED,
            "x_used_here": "log(flops_node) in the published saturating fraction; high-FLOP runs approach Pidle+beta",
        },
        "n_train_runtypes": int(len(ws)),
        "n_test_runtypes": int(len(ts)),
        "experimental_unit": "runtype (workload/config), not time sample",
        "this_module_insample_MAPE_mean_tot_power": in_mape,
        "this_module_oos_MAPE_mean_tot_power": oos_mape,
        "this_module_sample_level_tot_power_MAPE_ln_flops": {
            "in_sample": sample_in,
            "oos_test_export": sample_oos,
            "not_the_experimental_unit": True,
            "not_the_published_energy_MAPE": True,
        },
        "published_oos_MAPE": NEWKIRK_OOS_MAPE_PUBLISHED,
        "published_insample_energy_MAPE": NEWKIRK_INSAMPLE_MAPE_ARCH,
        "metric_alignment_note": (
            "Published 11.1% / 5.39% are energy MAPE (modeled power × duration vs measured energy) "
            "for the architecture-specific asymptotic model in Table 3; OOS is four named workloads "
            "(two 8-node Llama-70B from Dell and SMC, UNet 1-node and 9-node). "
            "This module does not refit. Runtype-mean tot_power MAPE and unweighted sample-level "
            "tot_power MAPE are different metrics. The open test export contains 3 runtypes, not 4. "
            "Do not cherry-pick the closest number to 5.39%."
        ),
        "train_run_summary": ws.to_dict("records"),
        "test_run_summary": ts.to_dict("records"),
        "bnl_is_latif": True,
        "hardware": "8x H100 HGX-class nodes (BNL AMD EPYC 9354; SMC Intel Xeon Platinum 8462-Y); rated 10.2 kW",
        "boundary": "node power excluding or including interconnect (power vs tot_power); not facility IT",
    }
    ws.to_csv(ANALYSIS / "NEWKIRK_TRAIN_RUNTYPES.csv", index=False)
    ts.to_csv(ANALYSIS / "NEWKIRK_TEST_RUNTYPES.csv", index=False)
    jdump(ANALYSIS / "NEWKIRK_SOURCE_REPRODUCTION.json", rec)
    return rec, ws, ts


def evidence_bank(newkirk_ws, newkirk_ts, sess) -> pd.DataFrame:
    rows = []
    # NLR compute (not full node)
    nlr = pd.read_csv(H100_INTENSITY)
    tr = nlr[nlr["mode"].astype(str).str.contains("train")]
    rows.append({
        "source_id": "NLR_GENAI_H100_COMPUTE",
        "data_lineage_id": "NLR_KESTREL_WATTAMETER",
        "measured_or_modeled": "measured",
        "hardware": "Kestrel GPU node 4xH100 SXM 80GB + 2x EPYC 9554",
        "GPU type": "H100 SXM 80GB",
        "GPUs/node": 4,
        "CPU": "2x AMD EPYC 9554",
        "memory": "384GB-1.5TB tiers",
        "interconnect": "Slingshot-11",
        "cooling type": "facility liquid (not a cooling experiment)",
        "workload": "MLPerf Llama-2 70B LoRA / SD training; Llama-3 70B inference",
        "architecture class": "transformer / diffusion",
        "training/inference/stress/idle": "training+inference",
        "measurement method": "NVML + RAPL WattAMeter",
        "boundary": "CPU+GPU compute",
        "idle power": 418.2,
        "average power": float(tr.p_compute_W_per_node.mean()),
        "peak power": float(tr.p_compute_W_per_node.max()),
        "rated power": 3520.0,
        "node count": "1-16",
        "confidence": "HIGH_for_compute_boundary",
        "notes": "NOT full-node AC. Idle is component idle from paper Appendix A.",
    })
    # Latif / BNL
    rows.append({
        "source_id": "LATIF_2025_IEEE_ACCESS",
        "data_lineage_id": "BNL_HGX_H100_AC_NEWKIRK_LINEAGE",
        "measured_or_modeled": "measured",
        "hardware": "8x H100 80GB HGX + 2x EPYC 9354, 1.5 TB",
        "GPU type": "H100",
        "GPUs/node": 8,
        "CPU": "2x AMD EPYC 9354",
        "memory": "1.5 TB",
        "interconnect": "HGX NVLink (single node)",
        "cooling type": "air / facility (BNL)",
        "workload": "ResNet; Llama2-13b training; GPU+CPU stress",
        "architecture class": "CNN / LLM",
        "training/inference/stress/idle": "training+stress",
        "measurement method": "full-node AC (paper)",
        "boundary": "system/PSU",
        "idle power": None,
        "average power": 7920.0,
        "peak power": 8480.0,
        "rated power": 10200.0,
        "node count": 1,
        "confidence": "HIGH_as_8gpu_ac",
        "notes": "Llama2-13b median 7.92 kW; stress median 8.43 peak 8.48 kW. SAME physical campaign as Newkirk BNL rows.",
    })
    # Newkirk SMC
    smc = newkirk_ws[newkirk_ws.source == "SMC"]
    for _, r in smc.iterrows():
        rows.append({
            "source_id": f"NEWKIRK_SMC_{r.runtype}",
            "data_lineage_id": "NEWKIRK_2025_OPEN_DATA",
            "measured_or_modeled": "measured",
            "hardware": "8x H100 class; Intel Xeon Platinum 8462-Y (SMC)",
            "GPU type": "H100",
            "GPUs/node": 8,
            "CPU": "Intel Xeon Platinum 8462-Y",
            "memory": None,
            "interconnect": "included in tot_power",
            "cooling type": "air / rear-door (paper idle 1.86 kW)",
            "workload": r.runtype,
            "architecture class": r.architecture,
            "training/inference/stress/idle": "training",
            "measurement method": "node power logs parsed to tot_power",
            "boundary": "node telemetry",
            "idle power": 1860.0,
            "average power": float(r.mean_tot_power_W),
            "peak power": float(r.max_tot_W),
            "rated power": 10200.0,
            "node count": int(r.n_nodes_field),
            "confidence": "HIGH_as_8gpu_node",
            "notes": "Do not treat as Kestrel 4-GPU. Do not divide by two.",
        })
    rows.append({
        "source_id": "NEWKIRK_BNL_OVERLAP",
        "data_lineage_id": "BNL_HGX_H100_AC_NEWKIRK_LINEAGE",
        "measured_or_modeled": "measured",
        "hardware": "BNL 8x H100 HGX (Latif campaign)",
        "GPU type": "H100",
        "GPUs/node": 8,
        "CPU": "2x EPYC 9354",
        "memory": "1.5 TB",
        "interconnect": None,
        "cooling type": "air",
        "workload": "BNL_Llama / BNL_resnet*",
        "architecture class": "LLM/CNN",
        "training/inference/stress/idle": "training",
        "measurement method": "same BNL meters as Latif",
        "boundary": "system/PSU",
        "idle power": 1860.0,
        "average power": float(newkirk_ws[newkirk_ws.source == "BNL"].mean_tot_power_W.mean()) if (newkirk_ws.source == "BNL").any() else None,
        "peak power": 8480.0,
        "rated power": 10200.0,
        "node count": 1,
        "confidence": "NOT_INDEPENDENT_OF_LATIF",
        "notes": "Counted once in the bank via lineage_id. Not a second independent observation.",
    })
    rows.append({
        "source_id": "COOLING_MATTERS_2026",
        "data_lineage_id": "COOLING_MATTERS_LIQUID_VS_AIR",
        "measured_or_modeled": "measured",
        "hardware": "paired 8x H100 nodes, liquid vs air",
        "GPU type": "H100",
        "GPUs/node": 8,
        "CPU": "not used as Kestrel analogue",
        "memory": "1.5 TB",
        "interconnect": None,
        "cooling type": "direct liquid vs air (fans 4 vs 8)",
        "workload": "GPU-burn; LLM QLoRA; VLM training",
        "architecture class": "LLM / VLM / stress",
        "training/inference/stress/idle": "training+stress",
        "measurement method": "node-level power; paper-level values",
        "boundary": "node telemetry",
        "idle power": None,
        "average power": None,
        "peak power": None,
        "rated power": 10200.0,
        "node count": 1,
        "confidence": "MEDIUM_paper_level",
        "notes": "Liquid node ~1–1.5 kW lower than air at high util. Related literature family to Newkirk/Latif but distinct cooling campaign. GitHub raw repo not retrieved.",
    })
    rows.append({
        "source_id": "ELSAYED_2026_SCIDATA",
        "data_lineage_id": "ELSAYED_LAMBDA_H100_B200",
        "measured_or_modeled": "measured",
        "hardware": "Lambda 8x H100 SXM 80GB / 8x B200 180GB",
        "GPU type": "H100 or B200",
        "GPUs/node": 8,
        "CPU": "Intel Xeon 208 vCPU (cloud)",
        "memory": "1800 / 2900 GB",
        "interconnect": "cloud VM",
        "cooling type": "unknown cloud",
        "workload": "LLM + diffusion training 15 min sessions",
        "architecture class": "LLM / diffusion",
        "training/inference/stress/idle": "training",
        "measurement method": "pynvml per-GPU",
        "boundary": "GPU component",
        "idle power": None,
        "average power": float(sess.mean_gpu_sum_W.mean()) if len(sess) else None,
        "peak power": float(sess.mean_gpu_sum_W.max()) if len(sess) else None,
        "rated power": None,
        "node count": 1,
        "confidence": "HIGH_as_gpu_sum",
        "notes": "CPU power columns empty. Not full-node AC. RTX 3060 not processed.",
    })
    df = pd.DataFrame(rows)
    df.to_csv(ANALYSIS / "H100_FULL_NODE_EVIDENCE_BANK.csv", index=False)
    return df


def node_envelope(newkirk_ws, sess) -> dict:
    """EXTERNAL / CROSS-SYSTEM envelope. Not Kestrel-calibrated.

    Compare dimensionless quantities only. Do not halve 8-GPU nodes.
    """
    nlr_p = pd.read_csv(H100_INTENSITY)
    nlr_train = nlr_p[nlr_p["mode"].astype(str).str.contains("train")]
    nlr_sat = nlr_train  # compute W/node
    nlr_idle = 418.2
    nlr_rated_compute = 3520.0
    # 8gpu system
    rated_8 = 10200.0
    idle_8 = 1860.0
    latif_avg = 7920.0
    latif_peak = 8480.0
    smc_llm = newkirk_ws[(newkirk_ws.source == "SMC") & (newkirk_ws.architecture == "LLM")]
    # incremental loaded-idle per GPU
    inc_8 = (latif_avg - idle_8) / 8.0
    inc_nlr = None  # no Kestrel node AC idle
    # scale factors vs rated
    rec = {
        "label": "EXTERNAL_H100_NODE_BOUNDARY_ENVELOPE",
        "not": "KESTREL_CALIBRATED",
        "forbidden_operations_not_done": [
            "halve_8gpu_node",
            "infer_kestrel_psu_efficiency",
            "subtract_unlike_cpu_memory_chassis",
            "calibrate_nlr_compute_to_literature",
        ],
        "public_8gpu_ac_or_node": {
            "rated_W": rated_8,
            "idle_W": idle_8,
            "idle_over_rated": idle_8 / rated_8,
            "loaded_over_rated_llama_median": latif_avg / rated_8,
            "peak_over_rated_stress": latif_peak / rated_8,
            "incremental_loaded_minus_idle_per_GPU_W": inc_8,
            "loaded_W_per_GPU_llama": latif_avg / 8.0,
        },
        "nlr_4gpu_compute_only": {
            "component_idle_W": nlr_idle,
            "component_tdp_envelope_W": nlr_rated_compute,
            "mean_training_p_W_per_node": float(nlr_train.p_compute_W_per_node.mean()),
            "N2_llama_W_per_node": float(nlr_train[(nlr_train.workload_family == "llama2_70b_lora") & (nlr_train.nodes == 2)].p_compute_W_per_node.mean()) if "workload_family" in nlr_train.columns else None,
            "gpu_share_training": 0.90,
        },
        "defensible_statement": (
            "On 8-GPU H100 HGX-class nodes, measured full-node/system power sits at roughly "
            "0.18× rated idle and 0.78–0.83× rated when loaded (Latif/Newkirk). "
            "NLR measures only CPU+GPU components on a 4-GPU Kestrel node. "
            "P_other_node cannot be identified for Kestrel from public evidence. "
            "Dimensionless 8-GPU ratios are EXTERNAL/CROSS-SYSTEM context, not coefficients. "
            "Loaded 8-GPU AC minus 8× NLR per-GPU NVML is not a valid P_other estimator. "
            "An 8-GPU nameplate or idle value divided by two is not a Kestrel node."
        ),
        "envelope": {
            "form": "P_node = P_compute + P_other_node, with P_other_node UNCERTAIN on Kestrel",
            "external_scenario_low": "P_node >= P_compute (physical lower bound; P_other >= 0)",
            "external_scenario_high": "NOT IDENTIFIED for the 4-GPU Kestrel node",
            "public_8gpu_context_only": {
                "idle_over_rated": idle_8 / rated_8,
                "loaded_over_rated_llama_median": latif_avg / rated_8,
                "peak_over_rated_stress": latif_peak / rated_8,
            },
            "use": "uncertainty flag for facility scenarios; labeled EXTERNAL/CROSS-SYSTEM; not KESTREL_CALIBRATED",
        },
        "KESTREL_H100_FULL_NODE": "PARTIAL_EXTERNAL_ENVELOPE",
        "cooling_matters": "liquid vs air can move 8-GPU node power by ~1–1.5 kW; another reason not to transplant a single overhead",
    }
    pd.DataFrame(
        [
            {"regime": "physical_lower_bound", "P_other_W": 0.0, "label": "P_node >= P_compute on Kestrel (measured components are a subset)"},
            {"regime": "kestrel_upper_bound", "P_other_W": None, "label": "NOT IDENTIFIED; public 8-GPU systems are a different chassis/CPU/GPU-count"},
            {"regime": "external_8gpu_idle_over_rated", "P_other_W": None, "label": f"Latif/Newkirk 8-GPU idle/rated = {idle_8 / rated_8:.3f} (EXTERNAL context only)"},
            {"regime": "external_8gpu_loaded_over_rated_llama", "P_other_W": None, "label": f"Latif Llama2-13b median/rated = {latif_avg / rated_8:.3f} (EXTERNAL context only)"},
        ]
    ).to_csv(ANALYSIS / "H100_NODE_BOUNDARY_BRIDGE.csv", index=False)
    jdump(ANALYSIS / "H100_NODE_BOUNDARY_BRIDGE.json", rec)
    return rec


def mlperf_note() -> dict:
    rec = {
        "status": "NO_CLEAN_MLPERF_COMPARATOR",
        "attempted": "paper-level MLPerf Power (Tschand et al. arXiv:2410.12032) + Dell XE9680 commentary; no full results-repo clone",
        "why": (
            "No retrieved record simultaneously gives (a) H100 datacenter SUT average watts, "
            "(b) Llama-class inference, (c) a stated measurement boundary, and (d) a 4-GPU node comparable to Kestrel. "
            "Tschand reports 111.4 J/sample for Llama2-70B as a suite-level energy/sample, not node watts. "
            "Dell discusses 8x H100 XE9680 power-capping efficiency without a usable absolute kW table here."
        ),
        "nlr_online": "component P_compute vs request rate on 1x 4-GPU Kestrel node; different boundary",
        "no_new_model_fit": True,
    }
    jdump(ANALYSIS / "MLPERF_COMPARATOR.json", rec)
    return rec


def kestrel_request_windows() -> pd.DataFrame:
    xw = pd.read_csv(H100_ROOT / "analysis" / "H100_KESTREL_CROSSWALK.csv")
    sd1 = pd.read_csv(H100_ROOT / "analysis" / "H100_SD_N1_RECONSTRUCTED.csv")
    ids = list(xw.slurm_job_id.astype(int)) + list(sd1.slurm_job_id.astype(int))
    import duckdb
    c = duckdb.connect()
    q = c.execute(
        f"""
        SELECT job_id, start_time, end_time, nodes_used, duration_s, partition, state_simple
        FROM read_parquet('{KESTREL_JOBS}')
        WHERE job_id IN {tuple(ids)}
        """
    ).fetchdf()
    meta = pd.concat(
        [
            xw[["slurm_job_id", "workload_family", "nodes"]].rename(columns={"slurm_job_id": "job_id"}),
            sd1[["slurm_job_id", "workload_family", "nodes"]].rename(columns={"slurm_job_id": "job_id"}),
        ],
        ignore_index=True,
    )
    m = meta.merge(q, on="job_id", how="left")
    m["source_profile_id"] = m["job_id"].astype(str)
    m.to_csv(ANALYSIS / "NLR_H100_FULL_NODE_REQUEST_WINDOWS.csv", index=False)
    return m


def write_request_md(windows: pd.DataFrame) -> None:
    n = int(windows.job_id.nunique())
    t0 = str(windows.start_time.min())
    t1 = str(windows.end_time.max())
    ids = ", ".join(str(int(x)) for x in sorted(windows.job_id.dropna().unique()))
    (DOCS / "NLR_H100_FULL_NODE_DATA_REQUEST.md").write_text(
        f"""# Kestrel H100 full-node telemetry request (do not send automatically)

This package is for NLR HPC / ESIF operators. It is **not** an email draft to fire.

## Why

NLR GenAI profiles measure **CPU RAPL + GPU NVML** on exact Kestrel H100 jobs.
Kestrel job records have **null** `ConsumedEnergyRaw` for these H100 jobs.
Public 8-GPU AC studies cannot identify `P_other_node` on the 4-GPU Kestrel node.

## Primary request (smallest sufficient set)

Per-node BMC / IPMI / Redfish / inlet or PSU input power for the **exact Slurm job IDs below**, plus a few idle windows on the same nodes.

Needed fields:

* node ID (hostname)
* timestamp
* timezone and whether DST is applied
* power value and **unit**
* cadence (≤ 1 minute if possible)
* measurement location / boundary (PSU AC in, DC bus, BMC estimate, …)
* whether PSU losses are included
* quality / missingness flags

Job windows: `{n}` training/fine-tune jobs (including 5 Stable Diffusion N=1 reconstructions).

Approximate span: `{t0}` → `{t1}` (Kestrel extract timestamps).

Slurm job IDs:

{ids}

See `analysis/NLR_H100_FULL_NODE_REQUEST_WINDOWS.csv` for start, end, nodes, workload.

## Idle windows

Several 10–15 minute idle traces on the **same H100 nodes** when no user job is running, with the same meter boundary.

## Fallback (only if per-node is unavailable)

Rack / cabinet / PDU power that **only** feeds those H100 nodes, with:

* exact node membership of the PDU
* active-node counts at each timestamp
* the same time windows

Do not send months of facility-wide telemetry.

## What we will **not** do with the data

* re-identify users
* populate the anonymous ~1.3M H100 job archive with guessed workloads
* treat the result as a transferable PSU-efficiency coefficient for other sites
"""
    )


def write_final(cpu_ok, h100_freeze, ind, newkirk, env, mlperf, windows) -> dict:
    status = {
        "CPU_NODE_ENERGY": "FROZEN_PASS_WITH_DOMAIN_RESTRICTIONS",
        "H100_COMPUTE_ENERGY": "FROZEN_PASS_WITH_DOMAIN_RESTRICTIONS",
        "H100_WORKLOAD_CONDITIONING": "PASS",
        "H100_SCALE_CONDITIONING": "PASS",
        "H100_ONLINE_INFERENCE": "PASS",
        "H100_TEMPORAL_PROFILE": "PASS",
        "INDEPENDENT_H100_REPLICATION": "PASS",
        "H100_TO_B200_TRANSFER": "FAIL",
        "H100_PUBLIC_FULL_NODE_EVIDENCE": "PASS",
        "KESTREL_H100_FULL_NODE": "PARTIAL_EXTERNAL_ENVELOPE",
        "H100_COMPONENT_TO_NODE_BRIDGE": "UNSUPPORTED_SAME_SYSTEM",
        "NODE_TO_FACILITY_IT_BOUNDARY": "PARTIAL",
        "IT_POWER_LAYER_FINAL_DISPOSITION": "FROZEN_BOUNDED_WITH_EXPLICIT_NODE_UNCERTAINTY",
        "canonical": {
            "CPU": "E_CPU,node = 0.7007 kW/node * N * tau  (Kestrel exclusive CPU domain only)",
            "H100_batch_compute": "E_H100,compute = p_{w,N} * N * tau  (CPU+GPU; table)",
            "H100_online": "discrete P_compute(request_rate, configuration)",
            "H100_temporal": "PAR_{w,N,resolution} table; 2-node templates only",
            "H100_node": "P_other_node = UNCERTAIN; EXTERNAL envelope only",
            "facility_IT": "P_facility_IT = sum(P_nodes) + P_network/storage/service/idle/other; M100 residual is a boundary, not a PSU coefficient",
        },
        "same_system_bridge_run": False,
        "reason_same_system_not_run": "Kestrel node AC telemetry not present in this repository",
        "mlperf": mlperf["status"],
        "next_layer_recommended_not_executed": "facility IT + weather → cooling/HVAC/pump power using ESIF component data",
    }
    jdump(ANALYSIS / "FINAL_IT_POWER_STATUS.json", status)
    freeze = {
        "IT_POWER_LAYER_FINAL_DISPOSITION": status["IT_POWER_LAYER_FINAL_DISPOSITION"],
        "cpu_frozen": True,
        "h100_compute_frozen": True,
        "h100_node_kestrel": "PARTIAL_EXTERNAL_ENVELOPE",
        "do_not_refit_to_cooling": True,
    }
    jdump(MANIFESTS / "IT_POWER_LAYER_FREEZE.json", freeze)
    (DOCS / "IT_POWER_FINAL_REPORT.md").write_text(_report_md(h100_freeze, ind, newkirk, env, mlperf, status, windows))
    # update source audit
    audit = (DOCS / "SOURCE_AUDIT_AND_EXPERIMENT.md").read_text()
    if "CLOSURE UPDATE" not in audit:
        (DOCS / "SOURCE_AUDIT_AND_EXPERIMENT.md").write_text(
            audit
            + "\n\n## CLOSURE UPDATE (do not execute obsolete plan as written)\n\n"
            + "NLR GenAI H100 compute is now frozen with `p_{w,N}`. The 2026 Sci. Data H100/B200 set was used only to test workload/util transfer, not as a second primary H100 model. RTX 3060 was not processed. MLPerf was not cloned. The util→IT-power nested M0/M1 map is **hardware-class specific**; H100→B200 transfer **fails**. Public 8-GPU AC data provide an EXTERNAL envelope only. Kestrel full-node AC is still missing; see `NLR_H100_FULL_NODE_DATA_REQUEST.md`. Do not use M100 0.74–0.81 as a PSU efficiency. Next layer is ESIF cooling, not more H100 job population.\n"
        )
    return status


def _report_md(h100_freeze, ind, newkirk, env, mlperf, status, windows) -> str:
    sd = h100_freeze["final_experiment_count"]
    sd1 = h100_freeze.get("sd_n1", {})
    rapl = h100_freeze["rapl_physical_package_only"]
    sat = h100_freeze["saturated_anchor"]["SATURATED_COMPUTE_SCENARIO_ANCHOR"]
    m1_h = next(r for r in ind["M0_M1"] if r["hardware"] == "H100" and r["model"] == "M1_util")
    m0_h = next(r for r in ind["M0_M1"] if r["hardware"] == "H100" and r["model"] == "M0_hw_mean")
    tr = ind["transfer"]
    loo = ind["leave_one_family_out_H100"]
    m2 = ind.get("M2_memory", {})
    wl = { (r["hardware"], r["workload_family"]): r for r in ind["workload_means"] }
    loo_sess = ind.get("leave_one_session_out_H100_M1") or {}
    loo_sess_mae = loo_sess.get("MAE")
    pub8 = env["public_8gpu_ac_or_node"]
    return f"""# IT-power layer final report

## A. Repository / freeze scope

CPU remains `{CPU_DISPOSITION}` at 0.7007 kW/node and was **not** refit.
H100 compute is `{h100_freeze['H100_COMPUTE_LAYER']}`.
IT-power layer disposition: `{status['IT_POWER_LAYER_FINAL_DISPOSITION']}`.
Same-system node bridge was **not** run ({status['reason_same_system_not_run']}).

## B. H100 compute freeze

Measurement boundary: `P_compute = P_GPU_NVML + P_CPU_RAPL` (not full-node AC).

Canonical batch object:

`E_compute = p_{{w,N}} * N * tau`

using `analysis/H100_P_W_N_TABLE.csv`. Author-supplied training runs: {sd['author_supplied_training_runs']}. Experimental unit = independent run, not a time sample.

### SD N=1 (`RAW_RECONSTRUCTED_SOURCE_RUN`)

n = {sd1.get('n_runs')}; mean duration {sd1.get('mean_duration_s'):.0f} s; mean GPU energy {sd1.get('mean_energy_gpu_Wh'):.0f} Wh; mean CPU (source package+core) {sd1.get('mean_energy_cpu_source_Wh'):.0f} Wh; mean compute energy {sd1.get('mean_energy_compute_Wh'):.0f} Wh; mean {sd1.get('mean_p_W_per_node'):.1f} W/node (std {sd1.get('std_p_W_per_node'):.1f}, CV {sd1.get('cv'):.4f}). These 1-node Stable Diffusion runs sit in the same high-intensity band as Llama/SD N=2 (~2630–2660 W/node). They are **not** author-supplied aggregates.

### RAPL

Source reproduction keeps package+core. Preferred physical CPU is package only. Median core fraction of CPU energy {rapl['median_core_fraction_of_cpu_energy']:.4f}; median share of CPU+GPU compute energy {rapl['median_pct_of_cpu_gpu_compute_energy']:.5f}; median source−package difference {rapl.get('median_source_minus_package_W')} W. Models were **not** refit.

### 2650 W/node

Retained only as `SATURATED_COMPUTE_SCENARIO_ANCHOR` for **ex-ante** training `llama2_70b_lora` or `stable_diffusion` with N≤2 (workload + node count, not observed watts). n={sat['n_runs']}, mean {sat['mean_p_W_per_node']:.1f} W/node, rounded illustration 2650 W/node. Not a universal H100 default and not a predictive shortcut.

### Temporal

`PAR_{{workload,node_count,resolution}}` at native / 1 s / 10 s / 60 s / 5 min where run length supports it. No universal training PAR≈1.25. Alignable templates remain 2-node Llama and SD only.

Online inference remains a discrete measured scenario library, not a general response model.

## C. Independent H100/B200 (Elsayed et al.)

{ind['n_H100']} H100 + {ind['n_B200']} B200 sessions (unit = session, not 20 ms samples). RTX 3060 skipped. CPU power columns empty. Boundary: sum of 8 pynvml GPU powers, not node AC.

H100 session-mean GPU-sum: LLM {wl[('H100','LLM')]['mean']:.0f} W vs diffusion {wl[('H100','diffusion')]['mean']:.0f} W. B200: LLM {wl[('B200','LLM')]['mean']:.0f} W vs diffusion {wl[('B200','diffusion')]['mean']:.0f} W. Workload family changes power on both platforms (qualitative replication of NLR).

H100 M0 MAE {m0_h['MAE']:.0f} W (WAPE {m0_h['WAPE']:.3f}); M1 util MAE {m1_h['MAE']:.0f} W (WAPE {m1_h['WAPE']:.3f}). Leave-one-family-out WAPE: {', '.join(f"{r['held_out_family']} {r['WAPE']:.3f}" for r in loo)}. Leave-one-session-out M1 MAE {loo_sess_mae}.

M2 memory was run because M1 residual vs memory util corr={m2.get('corr_residual_vs_mem')}. M2 is a diagnostic, not a project H100 model.

H100→B200 WAPE {tr['H100_to_B200']['WAPE']:.3f}; B200→H100 WAPE {tr['B200_to_H100']['WAPE']:.3f}. Transfer **not** supported. Coefficients were not silently reused.

## D–E. Full-node bank / Newkirk

Preferred Newkirk specification (Table 3, architecture-specific asymptotic): Pidle=1.86 kW, α=5.11, β_LLM=6.89 kW, β_CNN=6.28 kW, cap 8.4 kW. Published energy MAPE 11.1% in-sample / **5.39%** OOS on four named workloads. This module's runtype-mean tot_power MAPE is {newkirk['this_module_insample_MAPE_mean_tot_power']:.3f} (in) / {newkirk['this_module_oos_MAPE_mean_tot_power']:.3f} (test export). Those are different metrics; 5.39% is not claimed as reproduced. BNL rows are the Latif campaign — one lineage.

Cooling Matters: liquid vs air ~1–1.5 kW on 8×H100; distinct campaign. GitHub raw data not retrieved.

Public 8-GPU AC context (Latif/Newkirk, EXTERNAL): idle/rated={pub8['idle_over_rated']:.3f}; loaded Llama median/rated={pub8['loaded_over_rated_llama_median']:.3f}; peak stress/rated={pub8['peak_over_rated_stress']:.3f}; incremental (loaded−idle)/GPU={pub8['incremental_loaded_minus_idle_per_GPU_W']:.0f} W.

## F. Component→node

`KESTREL_H100_FULL_NODE = PARTIAL_EXTERNAL_ENVELOPE`.

Lower bound only: `P_node >= P_compute`. Upper bound for the 4-GPU Kestrel node is **not identified**. Envelope labeled EXTERNAL/CROSS-SYSTEM, not KESTREL_CALIBRATED. 8-GPU numbers were not halved. P_other_node remains UNCERTAIN.

## G. MLPerf

`{mlperf['status']}`.

## H. Kestrel request

{int(windows.job_id.nunique())} exact job windows in `NLR_H100_FULL_NODE_REQUEST_WINDOWS.csv`. Do not send automatically.

## I. Canonical IT objects

- CPU: `E = 0.7007 kW/node * N * tau` (frozen exclusive Kestrel CPU domain)
- H100 batch compute: `p_{{w,N}}` table, CPU+GPU boundary
- H100 online: discrete `P_compute(rate, config)`
- H100 temporal: PAR table / 2-node templates
- H100 node: P_other UNCERTAIN + external 8-GPU ratios
- Facility IT: sum of nodes + other IT; M100 residual is a meter boundary, not a PSU coefficient

## J. Status

See `analysis/FINAL_IT_POWER_STATUS.json`.

## K. Next (not executed)

Facility IT + weather → cooling/HVAC/pump using ESIF measured components.
"""


def light_finalize_from_existing() -> None:
    """Refresh derived artifacts without re-reading high-frequency zips."""
    write_independent_provenance()
    rapl = rapl_accounting()
    sd1 = pd.read_csv(H100_ROOT / "analysis" / "H100_SD_N1_RECONSTRUCTED.csv")
    ptab = pd.read_csv(H100_ROOT / "analysis" / "H100_P_W_N_TABLE.csv")
    sat = json.loads((H100_ROOT / "analysis" / "H100_SATURATED_ANCHOR.json").read_text())
    par = pd.read_csv(H100_ROOT / "analysis" / "H100_PAR_BY_WORKLOAD_NODE_RESOLUTION.csv")
    freeze_h100(sd1, rapl, par, ptab, sat)
    sess = pd.read_csv(ANALYSIS / "INDEPENDENT_H100_B200_SESSIONS.csv")
    sess, ind = analyze_independent_sessions(sess)
    newkirk, ws, ts = newkirk_reproduction()
    evidence_bank(ws, ts, sess)
    env = node_envelope(ws, sess)
    mlperf = mlperf_note()
    windows = pd.read_csv(ANALYSIS / "NLR_H100_FULL_NODE_REQUEST_WINDOWS.csv")
    write_request_md(windows)
    h100_freeze = json.loads((H100_ROOT / "manifests" / "H100_COMPUTE_FINAL_FREEZE.json").read_text())
    write_final(True, h100_freeze, ind, newkirk, env, mlperf, windows)


def main():
    os.environ.setdefault("PYTHONNOUSERSITE", "1")
    if "--from-existing" in sys.argv:
        print("light finalize from existing tables…", flush=True)
        light_finalize_from_existing()
        print("DONE", flush=True)
        return
    os.environ.setdefault("PYTHONNOUSERSITE", "1")
    print("initial state…", flush=True)
    write_initial_state()
    print("H100 finalize: SD N=1…", flush=True)
    sd1, traces = reconstruct_sd_n1()
    print("RAPL accounting…", flush=True)
    rapl = rapl_accounting()
    print("PAR table…", flush=True)
    par = par_table(traces)
    print("p_w_N table…", flush=True)
    ptab, sat = p_wn_table(sd1)
    h100_freeze = freeze_h100(sd1, rapl, par, ptab, sat)
    print("independent GPU sessions…", flush=True)
    sess, ind = independent_gpu()
    write_independent_provenance()
    print("Newkirk…", flush=True)
    newkirk, ws, ts = newkirk_reproduction()
    print("evidence bank / envelope…", flush=True)
    evidence_bank(ws, ts, sess)
    env = node_envelope(ws, sess)
    mlperf = mlperf_note()
    print("Kestrel request windows…", flush=True)
    windows = kestrel_request_windows()
    write_request_md(windows)
    status = write_final(True, h100_freeze, ind, newkirk, env, mlperf, windows)
    print(json.dumps({"IT": status["IT_POWER_LAYER_FINAL_DISPOSITION"], "SD_N1": int(len(sd1)), "sessions": ind["n_sessions"]}, default=str), flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
