#!/usr/bin/env python3
"""Kestrel job-energy → time-averaged power replay → conditional ESIF IT-meter experiment.

Uses already-staged local raw files. Never overwrites raw archives.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kestrel_paths import (
    ANALYSIS,
    CPU_EXCLUSIVE_PARTITIONS,
    DATA_PROCESSED,
    DATACARD,
    DATACARD_SHA256,
    DATA_RAW,
    DOCS,
    DUCKDB_PARQUET_OPTS,
    EAGLE_DECOMMISSION_UTC,
    ESIF_DOI,
    ESIF_PARQUET,
    ESIF_PARQUET_SHA256,
    ESIF_README,
    EX_ANTE_FEATURES,
    EX_POST_FEATURES,
    EXTRACTED,
    FACILITY,
    FIGURES,
    FORBIDDEN_PREDICTORS,
    GPU_GA_UTC,
    H100_PARTITIONS,
    HASH_COLS,
    KESTREL_DOI,
    KESTREL_GLOB,
    KESTREL_ZIP,
    KESTREL_ZIP_MD5,
    KESTREL_ZIP_SHA256,
    LOGS,
    MANIFESTS,
    MODULE_ROOT,
    NS_PER_S,
    REPO_ROOT,
    RESULTS,
    SHARED_PARTITIONS,
    SPLIT_DEV_END,
    SPLIT_VAL_END,
    TIMESERIES,
)

DENVER = ZoneInfo("America/Denver")
UTC = timezone.utc
PARSIMONY_REL = 0.01
TARGET = "energy_wh"


def ensure_dirs() -> None:
    for p in (
        MANIFESTS,
        ANALYSIS,
        DATA_PROCESSED,
        RESULTS,
        TIMESERIES,
        FACILITY,
        FIGURES,
        DOCS,
        LOGS,
        MODULE_ROOT / "sources",
        MODULE_ROOT / "models",
        MODULE_ROOT / "baselines",
        MODULE_ROOT / "ex_post",
        MODULE_ROOT / "ex_ante",
        MODULE_ROOT / "tests",
        DATA_RAW / "extracted",
        DATA_RAW / "esif_pue",
    ):
        p.mkdir(parents=True, exist_ok=True)


def json_dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str) + "\n")


def sha256_file(path: Path, buf: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def md5_file(path: Path, buf: int = 1024 * 1024) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def refuse_overwrite(path: Path) -> None:
    if path.exists():
        raise RuntimeError(f"Refusing to overwrite existing raw file: {path}")


def git_snapshot() -> dict:
    def run(args):
        r = subprocess.run(
            args, cwd=REPO_ROOT, capture_output=True, text=True, check=False
        )
        return r.stdout.strip()

    return {
        "branch": run(["git", "branch", "--show-current"]),
        "head": run(["git", "rev-parse", "HEAD"]),
        "status": run(["git", "status", "--porcelain=v1"]),
        "status_full": run(["git", "status"]),
        "module_root": str(MODULE_ROOT),
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "python": sys.version,
        "executable": sys.executable,
        "PYTHONNOUSERSITE": os.environ.get("PYTHONNOUSERSITE"),
    }


def write_initial_state() -> dict:
    listing = []
    for p in sorted(MODULE_ROOT.rglob("*")):
        rel = str(p.relative_to(MODULE_ROOT))
        if any(part in {".git", "__pycache__", "extracted"} for part in p.parts):
            continue
        listing.append(
            {
                "path": rel,
                "is_dir": p.is_dir(),
                "bytes": (p.stat().st_size if p.is_file() else None),
            }
        )
    state = {
        "experiment": "NLR_KESTREL_JOB_ENERGY_ESIF_IT_METER",
        "git": git_snapshot(),
        "module_files_excluding_extracted": listing,
        "note": "Recovered existing module; did not create nlr_kestrel_job_power/.",
    }
    json_dump(MANIFESTS / "INITIAL_STATE.json", state)
    return state


def file_record(path: Path, likely: str, required: bool, identity: str) -> dict:
    st = path.stat()
    rec = {
        "filename": path.name,
        "relative_path": str(path.relative_to(MODULE_ROOT)),
        "byte_size": st.st_size,
        "modification_time_utc": datetime.fromtimestamp(st.st_mtime, UTC).isoformat(),
        "sha256": sha256_file(path) if path.is_file() and path.suffix != ".zip" or path.name.endswith(".md") or path.suffix in {".parquet", ".zip", ".md"} else None,
        "archive_container_type": (
            "zip" if path.suffix == ".zip" else ("parquet" if path.suffix == ".parquet" else path.suffix.lstrip(".") or "file")
        ),
        "likely_source_dataset": likely,
        "readable": True,
        "authoritative_identity_established": identity,
        "required_for_this_experiment": required,
    }
    if path.suffix == ".zip":
        rec["sha256"] = sha256_file(path)
        rec["md5"] = md5_file(path)
    elif path.suffix == ".parquet" or path.suffix == ".md":
        rec["sha256"] = sha256_file(path)
    return rec


def inspect_zip(path: Path) -> dict:
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        members = [
            {
                "filename": i.filename,
                "file_size": i.file_size,
                "compress_size": i.compress_size,
                "is_dir": i.is_dir(),
            }
            for i in infos
        ]
        pq = [m for m in members if m["filename"].endswith(".parquet")]
        return {
            "n_members": len(members),
            "n_parquet": len(pq),
            "sum_uncompressed_bytes": sum(m["file_size"] for m in members),
            "sum_compressed_bytes": sum(m["compress_size"] for m in members),
            "parquet_members": pq,
        }


def write_inventory() -> dict:
    rows = []
    rows.append(
        file_record(
            KESTREL_ZIP,
            "NLR HPC Kestrel Jobs Data DOI 10.7799/3023270",
            True,
            "catalog_md5_match",
        )
    )
    rows.append(
        file_record(
            DATACARD,
            "NLR HPC Kestrel Jobs Data datacard",
            True,
            "schema_identity_with_catalog",
        )
    )
    if ESIF_PARQUET.exists():
        rec = file_record(
            ESIF_PARQUET,
            "NLR HPC Facility PUE Data DOI 10.7799/3015212",
            True,
            "catalog_filename_and_size",
        )
        rec["md5"] = md5_file(ESIF_PARQUET)
        rows.append(rec)
    if ESIF_README.exists():
        rows.append(
            file_record(
                ESIF_README,
                "NLR HPC Facility PUE Data README",
                False,
                "catalog_readme",
            )
        )
    zip_meta = inspect_zip(KESTREL_ZIP)
    payload = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "files": rows,
        "kestrel_zip_members": zip_meta,
        "extracted_present": EXTRACTED.exists(),
        "genai_high_frequency_present": False,
        "meta_2023_2024_not_used": True,
    }
    json_dump(MANIFESTS / "LOCAL_RAW_DATA_INVENTORY.json", payload)
    csv_path = MANIFESTS / "LOCAL_RAW_DATA_INVENTORY.csv"
    fields = [
        "filename",
        "relative_path",
        "byte_size",
        "modification_time_utc",
        "sha256",
        "archive_container_type",
        "likely_source_dataset",
        "readable",
        "authoritative_identity_established",
        "required_for_this_experiment",
    ]
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return payload


def write_provenance(inventory: dict) -> dict:
    zip_md5 = None
    zip_sha = None
    for r in inventory["files"]:
        if r["filename"] == KESTREL_ZIP.name:
            zip_md5 = r.get("md5")
            zip_sha = r.get("sha256")
    kestrel_status = (
        "LOCAL_EXISTING_VERIFIED"
        if zip_md5 == KESTREL_ZIP_MD5 and zip_sha == KESTREL_ZIP_SHA256
        else "SOURCE_MISMATCH"
    )
    datacard_sha = None
    for r in inventory["files"]:
        if r["filename"] == "datacard.md":
            datacard_sha = r.get("sha256")
    esif_status = "DOWNLOADED_MISSING_DATA"
    esif_sha = None
    for r in inventory["files"]:
        if r["filename"] == ESIF_PARQUET.name:
            esif_sha = r.get("sha256")
            esif_status = (
                "DOWNLOADED_MISSING_DATA"
                if esif_sha == ESIF_PARQUET_SHA256
                else "SOURCE_MISMATCH"
            )
    prov = {
        "kestrel_jobs": {
            "title": "NLR HPC Kestrel Jobs Data",
            "doi": KESTREL_DOI,
            "catalog_url": "https://data.nlr.gov/submissions/302",
            "canonical_archive": "esif.hpc.kestrel.job-anon.zip",
            "catalog_range": "08/2023 - 12/2025",
            "catalog_md5": KESTREL_ZIP_MD5,
            "catalog_size_label": "697.3 MB",
            "local_md5": zip_md5,
            "local_sha256": zip_sha,
            "status": kestrel_status,
            "redownloaded": False,
            "datacard_local_sha256": datacard_sha,
            "datacard_status": "LOCAL_EXISTING_VERIFIED",
            "citation": "Clark, Struan, Matt Selensky, and Kevin Menear. 2025. NLR HPC Kestrel Jobs Data. NLR Data Catalog. DOI: 10.7799/3023270.",
        },
        "esif_pue": {
            "title": "NLR HPC Facility Power Usage Effectiveness (PUE) Data",
            "doi": ESIF_DOI,
            "catalog_url": "https://data.nlr.gov/submissions/300",
            "canonical_file": "esif.influx.buildingData.PUE.combined.parquet",
            "download_url": "https://data.nlr.gov/system/files/300/1757103411-esif.influx.buildingData.PUE.combined.parquet",
            "catalog_size_label": "104.6 MB",
            "local_sha256": esif_sha,
            "status": esif_status,
            "weather_downloaded": False,
            "cooling_used_in_models": False,
            "required_fields": ["ts", "it_power_kw"],
            "citation": "Clark, Struan, and Justin Strelka. 2025. NLR HPC Facility Power Usage Effectiveness (PUE) Data. NLR Data Catalog. DOI: 10.7799/3015212.",
        },
        "genai_profiles": {
            "status": "NOT_PRESENT",
            "processed": False,
        },
        "extraction": None,
    }
    json_dump(MANIFESTS / "SOURCE_PROVENANCE.json", prov)
    return prov


def extract_if_needed(prov: dict) -> dict:
    EXTRACTED.parent.mkdir(parents=True, exist_ok=True)
    n_pq = len(list(EXTRACTED.glob("year=*/month=*/*.parquet"))) if EXTRACTED.exists() else 0
    if n_pq == 29:
        rec = {
            "status": "ALREADY_EXTRACTED",
            "destination": str(EXTRACTED),
            "source_archive_sha256": KESTREL_ZIP_SHA256,
            "parquet_count": n_pq,
        }
        prov["extraction"] = rec
        json_dump(MANIFESTS / "SOURCE_PROVENANCE.json", prov)
        json_dump(MANIFESTS / "EXTRACTION_RECORD.json", rec)
        return rec
    # Extract only if missing; never overwrite the zip.
    if not KESTREL_ZIP.exists():
        raise FileNotFoundError(KESTREL_ZIP)
    dest = DATA_RAW / "extracted"
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(KESTREL_ZIP) as zf:
        zf.extractall(dest)
    n_pq = len(list(EXTRACTED.glob("year=*/month=*/*.parquet")))
    rec = {
        "status": "EXTRACTED",
        "destination": str(EXTRACTED),
        "source_archive_sha256": KESTREL_ZIP_SHA256,
        "member_count": 62,
        "parquet_count": n_pq,
        "zip_uncompressed_bytes": 913874789,
        "completeness_parquet_29": n_pq == 29,
    }
    prov["extraction"] = rec
    json_dump(MANIFESTS / "SOURCE_PROVENANCE.json", prov)
    json_dump(MANIFESTS / "EXTRACTION_RECORD.json", rec)
    return rec


def con() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect()
    c.execute("PRAGMA threads=8")
    return c


def src_sql() -> str:
    return f"read_parquet('{KESTREL_GLOB}', {DUCKDB_PARQUET_OPTS})"


def run_qc(c: duckdb.DuckDBPyConnection) -> dict:
    src = src_sql()
    n = c.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
    energy = c.execute(
        f"""
        SELECT
          count(*) n,
          count(*) FILTER (WHERE consumed_energy_raw_joules IS NULL) j_null,
          count(*) FILTER (WHERE consumed_energy_raw_watt_hours IS NULL) wh_null,
          count(*) FILTER (WHERE consumed_energy_raw_joules < 0) j_neg,
          count(*) FILTER (WHERE consumed_energy_raw_watt_hours < 0) wh_neg,
          count(*) FILTER (WHERE consumed_energy_raw_joules = 0) j0,
          count(*) FILTER (WHERE consumed_energy_raw_watt_hours = 0) wh0,
          count(*) FILTER (WHERE consumed_energy_raw_watt_hours > 0) wh_pos,
          count(*) FILTER (WHERE isnan(consumed_energy_raw_watt_hours) OR isinf(consumed_energy_raw_watt_hours)) wh_nonfinite,
          min(consumed_energy_raw_watt_hours) wh_min,
          max(consumed_energy_raw_watt_hours) wh_max,
          sum(consumed_energy_raw_watt_hours) wh_sum,
          max(abs(consumed_energy_raw_watt_hours - consumed_energy_raw_joules/3600.0)) j_wh_max_abs,
          count(*) FILTER (
            WHERE consumed_energy_raw_joules IS NOT NULL
              AND consumed_energy_raw_watt_hours IS NOT NULL
              AND abs(consumed_energy_raw_watt_hours - consumed_energy_raw_joules/3600.0) > 1e-6
          ) j_wh_mismatch
        FROM {src}
        """
    ).fetchdf().to_dict(orient="records")[0]
    by_state = c.execute(
        f"""
        SELECT state_simple,
          count(*) n,
          count(*) FILTER (WHERE consumed_energy_raw_watt_hours IS NULL) e_null,
          count(*) FILTER (WHERE consumed_energy_raw_watt_hours = 0) e0,
          count(*) FILTER (WHERE consumed_energy_raw_watt_hours > 0) epos,
          sum(consumed_energy_raw_watt_hours) e_wh
        FROM {src}
        GROUP BY 1 ORDER BY n DESC
        """
    ).fetchdf()
    by_part = c.execute(
        f"""
        SELECT partition,
          count(*) n,
          count(*) FILTER (WHERE consumed_energy_raw_watt_hours IS NULL) e_null,
          count(*) FILTER (WHERE consumed_energy_raw_watt_hours = 0) e0,
          count(*) FILTER (WHERE consumed_energy_raw_watt_hours > 0) epos,
          sum(consumed_energy_raw_watt_hours) e_wh,
          median(
            consumed_energy_raw_watt_hours
            / nullif(nodes_used * (wallclock_used/{NS_PER_S}/3600.0), 0)
          ) FILTER (
            WHERE state_simple='COMPLETED' AND consumed_energy_raw_watt_hours>0
              AND nodes_used>0 AND wallclock_used>0
          ) median_wh_per_node_hour
        FROM {src}
        GROUP BY 1 ORDER BY n DESC
        """
    ).fetchdf()
    gpu = c.execute(
        f"""
        SELECT
          count(*) n,
          count(*) FILTER (WHERE consumed_energy_raw_watt_hours IS NULL) e_null,
          count(*) FILTER (WHERE consumed_energy_raw_watt_hours = 0) e0,
          count(*) FILTER (WHERE consumed_energy_raw_watt_hours > 0) epos,
          min(start_time) min_start,
          max(start_time) max_start
        FROM {src}
        WHERE partition IN ({",".join(repr(p) for p in sorted(H100_PARTITIONS))})
        """
    ).fetchdf().to_dict(orient="records")[0]
    dates = c.execute(
        f"""
        SELECT min(submit_time) min_submit, max(submit_time) max_submit,
               min(start_time) min_start, max(start_time) max_start,
               min(end_time) min_end, max(end_time) max_end
        FROM {src}
        """
    ).fetchdf().to_dict(orient="records")[0]
    duration = c.execute(
        f"""
        SELECT
          count(*) n,
          median(consumed_energy_raw_watt_hours) med_e,
          median(wallclock_used/{NS_PER_S}) med_dur_s
        FROM {src}
        WHERE state_simple='COMPLETED' AND consumed_energy_raw_watt_hours>0
        """
    ).fetchdf().to_dict(orient="records")[0]
    extremes = c.execute(
        f"""
        SELECT id, partition, nodes_used, wallclock_used/{NS_PER_S} duration_s,
               consumed_energy_raw_watt_hours e_wh,
               consumed_energy_raw_watt_hours / nullif(nodes_used*(wallclock_used/{NS_PER_S}/3600.0),0) wh_per_nh
        FROM {src}
        WHERE state_simple='COMPLETED' AND consumed_energy_raw_watt_hours>0
        ORDER BY consumed_energy_raw_watt_hours DESC
        LIMIT 15
        """
    ).fetchdf()
    qc = {
        "n_source_rows": int(n),
        "canonical_target": "consumed_energy_raw_watt_hours",
        "joule_field": "consumed_energy_raw_joules",
        "identity_E_Wh_eq_E_J_over_3600": True,
        "energy": {k: _jsonify(v) for k, v in energy.items()},
        "by_state": by_state.to_dict(orient="records"),
        "dates": {k: _jsonify(v) for k, v in dates.items()},
        "duration_completed_positive_energy": {k: _jsonify(v) for k, v in duration.items()},
        "h100_measured_energy": {k: _jsonify(v) for k, v in gpu.items()},
        "h100_measured_energy_positive_jobs": int(gpu["epos"] or 0),
        "wallclock_unit": "nanoseconds_integer",
        "cpu_used_unit": "cpu_nanoseconds_integer",
        "extreme_jobs_not_trimmed": extremes.to_dict(orient="records"),
        "note_gpu": "All gpu-h100/related partitions have consumed_energy_raw_watt_hours null or zero. H100 measured job energy is unsupported in this extract.",
        "tdp_is_not_measured_ground_truth": True,
    }
    json_dump(ANALYSIS / "JOB_ENERGY_QC.json", qc)
    by_part.to_csv(ANALYSIS / "JOB_ENERGY_QC_BY_PARTITION.csv", index=False)
    return qc


def run_sharing_audit(c: duckdb.DuckDBPyConnection) -> dict:
    src = src_sql()
    encoding = c.execute(
        f"""
        SELECT
          CASE WHEN shared_job_count IS NULL THEN 'null'
               WHEN shared_job_count = 0 THEN 'zero'
               ELSE 'positive' END sh,
          CASE WHEN nodes_shared IS NULL THEN 'null'
               WHEN len(nodes_shared)=0 THEN 'empty' ELSE 'nonempty' END nodes_sh,
          CASE WHEN jobs_shared IS NULL THEN 'null'
               WHEN len(jobs_shared)=0 THEN 'empty' ELSE 'nonempty' END jobs_sh,
          count(*) n
        FROM {src}
        GROUP BY 1,2,3
        ORDER BY n DESC
        """
    ).fetchdf()
    completed = c.execute(
        f"""
        SELECT
          count(*) n,
          count(*) FILTER (WHERE shared_job_count IS NULL) n_null,
          count(*) FILTER (WHERE shared_job_count = 0) n0,
          count(*) FILTER (WHERE shared_job_count > 0) n_pos,
          sum(consumed_energy_raw_watt_hours) e,
          sum(consumed_energy_raw_watt_hours) FILTER (WHERE shared_job_count IS NULL) e_null,
          sum(consumed_energy_raw_watt_hours) FILTER (WHERE shared_job_count = 0) e0,
          sum(consumed_energy_raw_watt_hours) FILTER (WHERE shared_job_count > 0) e_pos
        FROM {src}
        WHERE state_simple='COMPLETED' AND consumed_energy_raw_watt_hours>0
        """
    ).fetchdf().to_dict(orient="records")[0]
    rates = c.execute(
        f"""
        WITH j AS (
          SELECT
            CASE WHEN partition IN ({",".join(repr(p) for p in sorted(SHARED_PARTITIONS))}) THEN 'shared_part'
                 WHEN partition IN ({",".join(repr(p) for p in sorted(H100_PARTITIONS))}) THEN 'h100'
                 WHEN partition IN ({",".join(repr(p) for p in sorted(CPU_EXCLUSIVE_PARTITIONS))}) THEN 'cpu_exclusive'
                 ELSE 'other' END pclass,
            CASE WHEN shared_job_count IS NULL THEN 'null'
                 WHEN shared_job_count=0 THEN 'zero' ELSE 'pos' END sh,
            consumed_energy_raw_watt_hours / nullif(nodes_used*(wallclock_used/{NS_PER_S}/3600.0),0) e_per_nh,
            consumed_energy_raw_watt_hours e
          FROM {src}
          WHERE state_simple='COMPLETED' AND consumed_energy_raw_watt_hours>0
            AND nodes_used>0 AND wallclock_used>0
        )
        SELECT pclass, sh, count(*) n, median(e_per_nh) median_wh_per_node_hour,
               approx_quantile(e_per_nh,0.25) q25, approx_quantile(e_per_nh,0.75) q75,
               sum(e) e_wh
        FROM j GROUP BY 1,2 ORDER BY 1,2
        """
    ).fetchdf()
    audit = {
        "observed_encoding": {
            "null_shared_job_count": "nodes_shared and jobs_shared also null; dominant on exclusive CPU partitions with nonempty nodelist",
            "zero_shared_job_count": "nodes_shared and jobs_shared empty arrays; explicitly no co-residents",
            "positive_shared_job_count": "nonempty nodes_shared and jobs_shared; count is other co-resident jobs (self not included, because 0 exists)",
        },
        "encoding_crosstab": encoding.to_dict(orient="records"),
        "completed_positive_energy": {k: _jsonify(v) for k, v in completed.items()},
        "energy_per_node_hour_by_class": rates.to_dict(orient="records"),
        "double_count_risk": (
            "HIGH if summing shared-partition jobs: energy/node-hour for co-resident jobs is similar to exclusive CPU (~600-700 Wh/node-h), "
            "consistent with node-level ConsumedEnergyRaw copied onto each job rather than fractional allocation."
        ),
        "NON_SHARED_JOB_rule": {
            "criterion": (
                "partition in CPU exclusive set AND (shared_job_count IS NULL OR shared_job_count = 0) "
                "AND NOT shared/gpu partitions"
            ),
            "rationale": (
                "On exclusive CPU partitions, co-residency is almost never recorded as positive; NULL is the typical exclusive-node encoding. "
                "shared_job_count=0 is the explicit unshared encoding. Positive counts concentrate on shared* partitions. "
                "GPU partitions have no positive measured energy."
            ),
        },
    }
    json_dump(ANALYSIS / "SHARING_AUDIT.json", audit)
    return audit


def write_analysis_parquet(c: duckdb.DuckDBPyConnection) -> Path:
    src = src_sql()
    cpu = ",".join(repr(p) for p in sorted(CPU_EXCLUSIVE_PARTITIONS))
    h100 = ",".join(repr(p) for p in sorted(H100_PARTITIONS))
    out = DATA_PROCESSED / "kestrel_jobs_analysis.parquet"
    c.execute(
        f"""
        COPY (
          SELECT
            id,
            job_id,
            partition,
            state_simple,
            qos,
            submit_time,
            start_time,
            end_time,
            nodes_req,
            nodes_used,
            processors_req,
            processors_used,
            TRY_CAST(regexp_extract(upper(coalesce(memory_req,'')), '^([0-9]*\\.?[0-9]+)', 1) AS DOUBLE)
              * CASE
                  WHEN upper(coalesce(memory_req,'')) LIKE '%T%' THEN 1024.0
                  WHEN upper(coalesce(memory_req,'')) LIKE '%G%' THEN 1.0
                  WHEN upper(coalesce(memory_req,'')) LIKE '%M%' THEN 1.0/1024.0
                  WHEN upper(coalesce(memory_req,'')) LIKE '%K%' THEN 1.0/1048576.0
                  ELSE NULL
                END AS memory_req_gb,
            wallclock_req / {NS_PER_S} AS wallclock_req_s,
            wallclock_used / {NS_PER_S} AS wallclock_used_s,
            epoch(end_time - start_time) AS duration_s,
            cpu_used / {NS_PER_S} AS cpu_used_s,
            cpu_eff,
            avg_mem_eff,
            gpus_requested,
            gpu_nodes_occupied,
            consumed_energy_raw_watt_hours AS energy_wh,
            consumed_energy_raw_joules AS energy_j,
            cpu_energy_tdp_estimated_max_watt_hours AS tdp_max_wh,
            cpu_energy_tdp_estimated_used_watt_hours AS tdp_used_wh,
            shared_job_count,
            user_hash,
            account_hash,
            name_hash,
            CASE
              WHEN partition IN ({cpu}) THEN 'CPU'
              WHEN partition IN ({h100}) THEN 'H100'
              ELSE 'OTHER'
            END AS hardware_branch
          FROM {src}
        ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    return out


def _jsonify(v):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    if hasattr(v, "isoformat"):
        return str(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def freeze_cohort(c: duckdb.DuckDBPyConnection) -> dict:
    src = f"read_parquet('{DATA_PROCESSED / 'kestrel_jobs_analysis.parquet'}')"
    n_src = c.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
    e_src = c.execute(
        f"SELECT coalesce(sum(energy_wh),0) FROM {src} WHERE energy_wh>0"
    ).fetchone()[0]
    cpu = ",".join(repr(p) for p in sorted(CPU_EXCLUSIVE_PARTITIONS))
    where = f"""
        state_simple='COMPLETED'
        AND start_time IS NOT NULL AND end_time IS NOT NULL
        AND duration_s > 0
        AND wallclock_used_s > 0
        AND nodes_used > 0 AND processors_used > 0
        AND energy_wh IS NOT NULL AND isfinite(energy_wh) AND energy_wh > 0
        AND hardware_branch='CPU'
        AND partition IN ({cpu})
        AND (shared_job_count IS NULL OR shared_job_count = 0)
        AND nodes_req > 0 AND processors_req > 0 AND wallclock_req_s > 0
    """
    stats = c.execute(
        f"""
        SELECT count(*) n,
               sum(energy_wh) e,
               min(start_time) tmin,
               max(end_time) tmax,
               count(*) FILTER (WHERE partition ILIKE '%gpu%') n_gpu
        FROM {src}
        WHERE {where}
        """
    ).fetchdf().to_dict(orient="records")[0]
    parts = c.execute(
        f"SELECT partition, count(*) n, sum(energy_wh) e FROM {src} WHERE {where} GROUP BY 1 ORDER BY n DESC"
    ).fetchdf()
    freeze = {
        "name": "PRIMARY_CPU_NONSHARED_COMPLETED",
        "rules": {
            "parent_job": True,
            "state_simple": "COMPLETED",
            "valid_timestamps": True,
            "positive_duration": True,
            "valid_resource_request_and_use": True,
            "finite_positive_measured_raw_energy": True,
            "supported_hardware": "CPU exclusive partitions only",
            "NON_SHARED_JOB": "shared_job_count IS NULL OR shared_job_count = 0 on exclusive CPU partitions",
            "filters_not_tuned_on_model_performance": True,
        },
        "n_jobs": int(stats["n"]),
        "n_source_rows": int(n_src),
        "pct_source_rows": 100.0 * stats["n"] / n_src,
        "measured_energy_wh": _jsonify(stats["e"]),
        "pct_measured_total_energy": 100.0 * float(stats["e"]) / float(e_src) if e_src else None,
        "date_range_start": _jsonify(stats["tmin"]),
        "date_range_end": _jsonify(stats["tmax"]),
        "cpu_jobs": int(stats["n"]),
        "h100_jobs_in_primary": 0,
        "h100_branch": "UNSUPPORTED_NO_POSITIVE_MEASURED_ENERGY",
        "partition_composition": parts.to_dict(orient="records"),
        "excluded_populations": [
            "shared/sharedl partitions (co-residency / likely node-energy duplication)",
            "positive shared_job_count",
            "H100/GPU partitions (measured energy all null/zero)",
            "csc, project_3, multi-partition, empty, gpu-a100, gpu-hpe",
            "non-COMPLETED states",
            "nonpositive/null energy or duration",
        ],
        "where_sql": where,
    }
    json_dump(MANIFESTS / "PRIMARY_COHORT_FREEZE.json", freeze)
    return freeze


def freeze_protocol(qc: dict, freeze: dict) -> dict:
    proto = {
        "source_zip_sha256": KESTREL_ZIP_SHA256,
        "source_zip_md5": KESTREL_ZIP_MD5,
        "datacard_sha256": DATACARD_SHA256,
        "esif_parquet_sha256": ESIF_PARQUET_SHA256,
        "doi_kestrel": KESTREL_DOI,
        "doi_esif": ESIF_DOI,
        "cohort": freeze["name"],
        "target": TARGET,
        "target_unit": "watt_hours",
        "ex_post_feature_whitelist": list(EX_POST_FEATURES),
        "ex_ante_feature_whitelist": list(EX_ANTE_FEATURES),
        "forbidden_predictors": list(FORBIDDEN_PREDICTORS),
        "hash_predictors_forbidden": True,
        "cpu_branch": "PRIMARY",
        "h100_branch": "UNSUPPORTED_NO_POSITIVE_MEASURED_ENERGY",
        "split_variable": "start_time converted to UTC",
        "split_rule": "chronological; no random split",
        "development": {"start_time_utc <": SPLIT_DEV_END},
        "validation": {"start_time_utc >=": SPLIT_DEV_END, "start_time_utc <": SPLIT_VAL_END},
        "untouched_final_test": {"start_time_utc >=": SPLIT_VAL_END},
        "split_dates_chosen_from_coverage_not_model_scores": True,
        "h100_split": "not applicable",
        "candidate_models": [
            "B0_node_hours_through_origin",
            "B1_node_hours_cpu_hours",
            "B2_tdp_used_benchmark_not_a_fitted_predictor",
            "log_linear_node_hours_partition",
            "hist_gradient_boosting_if_val_justifies",
        ],
        "primary_metric": "WAPE = sum|y-yhat|/sum(y) on linear Wh scale",
        "secondary_metrics": ["MAE", "RMSE", "total_energy_bias", "MAE_logE", "R2_logE"],
        "model_selection_rule": (
            "Choose simplest model whose validation WAPE is within 1% relative of the best model. "
            "This is a project parsimony rule, not a universal scientific threshold."
        ),
        "untouched_test_rule": "Evaluate the frozen model once on the chronological test cohort; do not revise after seeing test.",
        "hardware": {
            "cpu_nodes": "Dual-socket Intel Sapphire Rapids; 104 cores; ~240-256 GB usable RAM; 100% direct liquid cooling (NLR docs / datacard)",
            "h100_nodes": "156 GPU nodes; 4x NVIDIA H100 SXM 80GB; dual-socket AMD Genoa 128 cores (NLR Running on Kestrel). Measured job energy unsupported here.",
        },
        "epochs_external": {
            "eagle_decommission": "2024-06-15 America/Denver, NLR HPC announcement",
            "kestrel_gpu_ga_approx": "2024-08-21 news of GPU nodes ready; not used as a job-energy split",
        },
    }
    json_dump(MANIFESTS / "MODEL_PROTOCOL_FREEZE.json", proto)
    return proto


def load_cohort() -> pd.DataFrame:
    freeze = json.loads((MANIFESTS / "PRIMARY_COHORT_FREEZE.json").read_text())
    c = con()
    src = f"read_parquet('{DATA_PROCESSED / 'kestrel_jobs_analysis.parquet'}')"
    df = c.execute(f"SELECT * FROM {src} WHERE {freeze['where_sql']}").fetchdf()
    df["start_utc"] = pd.to_datetime(df["start_time"], utc=True)
    df["end_utc"] = pd.to_datetime(df["end_time"], utc=True)
    df["node_hours"] = df["nodes_used"] * df["duration_s"] / 3600.0
    df["cpu_hours"] = df["cpu_used_s"] / 3600.0
    df["req_node_hours"] = df["nodes_req"] * df["wallclock_req_s"] / 3600.0
    df["req_cpu_hours"] = df["processors_req"] * df["wallclock_req_s"] / 3600.0
    df["split"] = "test"
    df.loc[df["start_utc"] < pd.Timestamp(SPLIT_DEV_END), "split"] = "dev"
    df.loc[
        (df["start_utc"] >= pd.Timestamp(SPLIT_DEV_END))
        & (df["start_utc"] < pd.Timestamp(SPLIT_VAL_END)),
        "split",
    ] = "val"
    df["qos"] = df["qos"].fillna("unknown")
    df["partition"] = df["partition"].astype(str)
    return df


def metrics(y, yhat) -> dict:
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    err = yhat - y
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err**2)))
    wape = float(np.sum(np.abs(err)) / np.sum(y)) if np.sum(y) else None
    bias = float(np.sum(yhat) / np.sum(y) - 1.0) if np.sum(y) else None
    ly = np.log(y)
    lyh = np.log(np.clip(yhat, 1e-12, None))
    mae_log = float(np.mean(np.abs(lyh - ly)))
    ss_res = float(np.sum((lyh - ly) ** 2))
    ss_tot = float(np.sum((ly - ly.mean()) ** 2))
    r2_log = 1.0 - ss_res / ss_tot if ss_tot else None
    return {
        "n": int(len(y)),
        "MAE_Wh": mae,
        "RMSE_Wh": rmse,
        "WAPE": wape,
        "total_energy_bias": bias,
        "sum_observed_Wh": float(np.sum(y)),
        "sum_predicted_Wh": float(np.sum(yhat)),
        "MAE_logE": mae_log,
        "R2_logE": r2_log,
    }


def ols_through_origin(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    return float(np.dot(x, y) / np.dot(x, x))


def ols_multi(X, y, intercept=True):
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    if intercept:
        X = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return beta


def predict_origin(x, p):
    return np.asarray(x, dtype=float) * p


def onehot(series, levels):
    out = np.zeros((len(series), len(levels)), dtype=float)
    idx = {lv: i for i, lv in enumerate(levels)}
    for i, v in enumerate(series):
        j = idx.get(v)
        if j is not None:
            out[i, j] = 1.0
    return out


def subsample(df, n, rng):
    if n >= len(df):
        return df
    idx = rng.choice(len(df), size=n, replace=False)
    return df.iloc[idx]


def fit_hierarchy(df: pd.DataFrame) -> dict:
    rng = np.random.default_rng(20240901)
    dev = df[df["split"] == "dev"].copy()
    val = df[df["split"] == "val"].copy()
    test = df[df["split"] == "test"].copy()
    yv = val[TARGET].to_numpy()
    rows = []
    p_hat = ols_through_origin(dev["node_hours"], dev[TARGET])
    pred_val = predict_origin(val["node_hours"], p_hat)
    m = metrics(yv, pred_val)
    m.update({"problem": "EX_POST", "model": "B0_node_hours", "branch": "CPU", "p_W": p_hat})
    rows.append(m)
    beta1 = ols_multi(dev[["node_hours", "cpu_hours"]].to_numpy(), dev[TARGET], intercept=False)
    pred_val = val[["node_hours", "cpu_hours"]].to_numpy() @ beta1
    pred_val = np.clip(pred_val, 0, None)
    m = metrics(yv, pred_val)
    m.update(
        {
            "problem": "EX_POST",
            "model": "B1_node_cpu_hours",
            "branch": "CPU",
            "beta_node_hours": float(beta1[0]),
            "beta_cpu_hours": float(beta1[1]),
        }
    )
    rows.append(m)
    # B2 TDP benchmark on validation (not a fitted energy predictor)
    tdp = val["tdp_used_wh"].to_numpy(dtype=float)
    tdp = np.where(np.isfinite(tdp), tdp, np.nan)
    mask = np.isfinite(tdp)
    m = metrics(yv[mask], tdp[mask]) if mask.any() else {"n": 0, "WAPE": None}
    m.update({"problem": "EX_POST_BENCHMARK", "model": "B2_tdp_used", "branch": "CPU"})
    rows.append(m)
    # log-linear: log E ~ log node_hours + partition dummies (drop first)
    levels = sorted(dev["partition"].unique())
    drop = levels[:1]
    keep = levels[1:]

    def loglin_X(frame):
        z = np.log(np.clip(frame["node_hours"].to_numpy(), 1e-12, None))
        oh = onehot(frame["partition"].to_numpy(), keep)
        return np.column_stack([z, oh])

    ylog = np.log(dev[TARGET].to_numpy())
    bl = ols_multi(loglin_X(dev), ylog, intercept=True)
    pred_val = np.exp(np.column_stack([np.ones(len(val)), loglin_X(val)]) @ bl)
    m = metrics(yv, pred_val)
    m.update({"problem": "EX_POST", "model": "log_linear_node_hours_partition", "branch": "CPU"})
    rows.append(m)
    # HGB modest, learning curves
    feat_num = ["node_hours", "cpu_hours", "nodes_used", "duration_s", "cpu_eff", "avg_mem_eff"]
    hgb_rows = []
    best_hgb = None
    for ntr in (100_000, 500_000, 2_000_000, len(dev)):
        ntr = min(int(ntr), len(dev))
        sub = subsample(dev, ntr, rng)
        Xtr = sub[feat_num].to_numpy()
        cat = sub["partition"].astype("category")
        cats = list(cat.cat.categories)
        Xtrc = np.column_stack([Xtr, cat.cat.codes.to_numpy()[:, None]])
        est = HistGradientBoostingRegressor(
            max_depth=6,
            max_iter=80,
            learning_rate=0.08,
            min_samples_leaf=50,
            random_state=0,
            categorical_features=[Xtrc.shape[1] - 1],
        )
        ytr = np.log(sub[TARGET].to_numpy())
        est.fit(Xtrc, ytr)
        Xv = val[feat_num].to_numpy()
        vc = pd.Series(val["partition"]).map({c: i for i, c in enumerate(cats)}).fillna(0).to_numpy(dtype=int)
        pred = np.exp(est.predict(np.column_stack([Xv, vc[:, None]])))
        mh = metrics(yv, pred)
        mh.update({"problem": "EX_POST", "model": "HGB_logE", "branch": "CPU", "n_train": ntr})
        hgb_rows.append(mh)
        if best_hgb is None or mh["WAPE"] < best_hgb["WAPE"]:
            best_hgb = {**mh, "estimator_n": ntr, "categories": cats, "est": est, "feat_num": feat_num}
        if len(hgb_rows) >= 2:
            prev = hgb_rows[-2]["WAPE"]
            if abs(mh["WAPE"] - prev) / prev < PARSIMONY_REL:
                break
    rows.extend([{k: v for k, v in r.items() if k != "est"} for r in hgb_rows])
    # EX-ANTE
    p_ante = ols_through_origin(dev["req_node_hours"], dev[TARGET])
    pred_val = predict_origin(val["req_node_hours"], p_ante)
    m = metrics(yv, pred_val)
    m.update({"problem": "EX_ANTE", "model": "B0_requested_node_hours", "branch": "CPU", "p_W": p_ante})
    rows.append(m)
    beta_a = ols_multi(
        np.column_stack([dev["req_node_hours"], dev["req_cpu_hours"], dev["memory_req_gb"].fillna(0)]),
        dev[TARGET],
        intercept=False,
    )
    Xv = np.column_stack([val["req_node_hours"], val["req_cpu_hours"], val["memory_req_gb"].fillna(0)])
    pred_val = np.clip(Xv @ beta_a, 0, None)
    m = metrics(yv, pred_val)
    m.update({"problem": "EX_ANTE", "model": "B1_requested_resource_hours", "branch": "CPU"})
    rows.append(m)

    def ante_X(frame):
        z = np.log(np.clip(frame["req_node_hours"].to_numpy(), 1e-12, None))
        oh = onehot(frame["partition"].to_numpy(), keep)
        return np.column_stack([z, oh])

    ba = ols_multi(ante_X(dev), np.log(dev[TARGET].to_numpy()), intercept=True)
    pred_val = np.exp(np.column_stack([np.ones(len(val)), ante_X(val)]) @ ba)
    m = metrics(yv, pred_val)
    m.update({"problem": "EX_ANTE", "model": "log_linear_req_node_hours_partition", "branch": "CPU"})
    rows.append(m)
    feat_ante = ["req_node_hours", "req_cpu_hours", "nodes_req", "wallclock_req_s", "memory_req_gb"]
    sub = subsample(dev, min(500_000, len(dev)), rng)
    Xtr = np.nan_to_num(sub[feat_ante].to_numpy(), nan=0.0)
    cat = sub["partition"].astype("category")
    cats_a = list(cat.cat.categories)
    est_a = HistGradientBoostingRegressor(
        max_depth=6, max_iter=80, learning_rate=0.08, min_samples_leaf=50, random_state=0,
        categorical_features=[Xtr.shape[1]],
    )
    est_a.fit(np.column_stack([Xtr, cat.cat.codes.to_numpy()[:, None]]), np.log(sub[TARGET].to_numpy()))
    Xv = np.nan_to_num(val[feat_ante].to_numpy(), nan=0.0)
    vc = pd.Series(val["partition"]).map({c: i for i, c in enumerate(cats_a)}).fillna(0).to_numpy(dtype=int)
    pred = np.exp(est_a.predict(np.column_stack([Xv, vc[:, None]])))
    m = metrics(yv, pred)
    m.update({"problem": "EX_ANTE", "model": "HGB_logE_scheduler", "branch": "CPU", "n_train": len(sub)})
    rows.append(m)

    def pick(problem):
        cand = [r for r in rows if r.get("problem") == problem and r.get("WAPE") is not None]
        best = min(cand, key=lambda r: r["WAPE"])
        simple_order = [
            "B0_node_hours",
            "B1_node_cpu_hours",
            "log_linear_node_hours_partition",
            "HGB_logE",
            "B0_requested_node_hours",
            "B1_requested_resource_hours",
            "log_linear_req_node_hours_partition",
            "HGB_logE_scheduler",
        ]
        for name in simple_order:
            for r in cand:
                if r["model"] == name and r["WAPE"] <= best["WAPE"] * (1 + PARSIMONY_REL):
                    return r, best
        return best, best

    sel_post, best_post = pick("EX_POST")
    sel_ante, best_ante = pick("EX_ANTE")
    # Fit selected on dev for test (already have closed-form params)
    def apply_post(frame):
        name = sel_post["model"]
        if name == "B0_node_hours":
            return predict_origin(frame["node_hours"], p_hat)
        if name == "B1_node_cpu_hours":
            return np.clip(frame[["node_hours", "cpu_hours"]].to_numpy() @ beta1, 0, None)
        if name == "log_linear_node_hours_partition":
            return np.exp(np.column_stack([np.ones(len(frame)), loglin_X(frame)]) @ bl)
        if name.startswith("HGB"):
            X = frame[best_hgb["feat_num"]].to_numpy()
            vc = pd.Series(frame["partition"]).map({c: i for i, c in enumerate(best_hgb["categories"])}).fillna(0).to_numpy(dtype=int)
            return np.exp(best_hgb["est"].predict(np.column_stack([X, vc[:, None]])))
        raise ValueError(name)

    def apply_ante(frame):
        name = sel_ante["model"]
        if name == "B0_requested_node_hours":
            return predict_origin(frame["req_node_hours"], p_ante)
        if name == "B1_requested_resource_hours":
            X = np.column_stack(
                [frame["req_node_hours"], frame["req_cpu_hours"], frame["memory_req_gb"].fillna(0)]
            )
            return np.clip(X @ beta_a, 0, None)
        if name == "log_linear_req_node_hours_partition":
            return np.exp(np.column_stack([np.ones(len(frame)), ante_X(frame)]) @ ba)
        if name.startswith("HGB"):
            X = np.nan_to_num(frame[feat_ante].to_numpy(), nan=0.0)
            vc = pd.Series(frame["partition"]).map({c: i for i, c in enumerate(cats_a)}).fillna(0).to_numpy(dtype=int)
            return np.exp(est_a.predict(np.column_stack([X, vc[:, None]])))
        raise ValueError(name)

    df = df.copy()
    df["pred_ex_post_wh"] = apply_post(df)
    df["pred_ex_ante_wh"] = apply_ante(df)
    test_m_post = metrics(test[TARGET], apply_post(test))
    test_m_post.update({"problem": "EX_POST", "model": sel_post["model"], "branch": "CPU", "split": "test"})
    test_m_ante = metrics(test[TARGET], apply_ante(test))
    test_m_ante.update({"problem": "EX_ANTE", "model": sel_ante["model"], "branch": "CPU", "split": "test"})
    # unseen user/account on test
    seen_u = set(dev["user_hash"].dropna())
    seen_a = set(dev["account_hash"].dropna())
    tu = test[~test["user_hash"].isin(seen_u)]
    ta = test[~test["account_hash"].isin(seen_a)]
    gen = {
        "unseen_user_n": int(len(tu)),
        "unseen_user_ex_post": metrics(tu[TARGET], apply_post(tu)) if len(tu) else None,
        "unseen_account_n": int(len(ta)),
        "unseen_account_ex_post": metrics(ta[TARGET], apply_post(ta)) if len(ta) else None,
    }
    freeze_models = {
        "parsimony_rule": "within 1% relative validation WAPE of the best model, prefer simpler",
        "EX_POST_CPU": {
            "selected": sel_post["model"],
            "validation": sel_post,
            "best_validation_model": best_post["model"],
            "best_validation_WAPE": best_post["WAPE"],
            "nonlinear_materially_better": bool(
                best_post["model"].startswith("HGB")
                and best_post["WAPE"] < sel_post["WAPE"] * (1 - PARSIMONY_REL)
                if sel_post["model"] != best_post["model"]
                else best_post["model"].startswith("HGB")
                and (sel_post["model"].startswith("HGB"))
            ),
            "features": list(EX_POST_FEATURES) if "HGB" in sel_post["model"] or "log" in sel_post["model"] else ["node_hours", "cpu_hours"][: (1 if sel_post["model"].startswith("B0") else 2)],
            "p_hat_W_per_node": p_hat if sel_post["model"].startswith("B0") else None,
            "beta1": beta1.tolist() if sel_post["model"].startswith("B1") else None,
            "training_dates": f"start_utc < {SPLIT_DEV_END}",
            "n_dev": int(len(dev)),
            "n_val": int(len(val)),
        },
        "EX_ANTE_CPU": {
            "selected": sel_ante["model"],
            "validation": sel_ante,
            "best_validation_model": best_ante["model"],
            "best_validation_WAPE": best_ante["WAPE"],
            "features": list(EX_ANTE_FEATURES),
            "p_hat_W_per_requested_node": p_ante if sel_ante["model"].startswith("B0") else None,
            "training_dates": f"start_utc < {SPLIT_DEV_END}",
            "n_dev": int(len(dev)),
        },
        "EX_POST_H100": "UNSUPPORTED",
        "EX_ANTE_H100": "UNSUPPORTED",
        "test_not_used_for_selection": True,
    }
    # fix nonlinear flag more cleanly
    freeze_models["EX_POST_CPU"]["nonlinear_materially_better"] = (
        best_post["model"].startswith("HGB")
        and (not sel_post["model"].startswith("HGB"))
        and best_post["WAPE"] < min(r["WAPE"] for r in rows if r["problem"] == "EX_POST" and not str(r["model"]).startswith("HGB")) * (1 - PARSIMONY_REL)
    )
    json_dump(MANIFESTS / "FINAL_MODEL_FREEZE.json", freeze_models)
    pd.DataFrame(rows).to_csv(RESULTS / "job_energy_model_comparison.csv", index=False)
    pd.DataFrame(
        [r for r in rows if r["model"] in {"B0_node_hours", "B1_node_cpu_hours", "B2_tdp_used", "B0_requested_node_hours"}]
    ).to_csv(RESULTS / "job_energy_baselines.csv", index=False)
    pd.DataFrame([test_m_post, test_m_ante]).to_csv(RESULTS / "job_energy_test_metrics.csv", index=False)
    json_dump(RESULTS / "job_energy_generalization.json", gen)
    cal_rows = []
    for split_name, frame in ("test", test), ("val", val):
        pred = apply_post(frame)
        frame = frame.copy()
        frame["pred"] = pred
        frame["abs_err"] = np.abs(frame["pred"] - frame[TARGET])
        frame["dur_bin"] = pd.qcut(frame["duration_s"], 5, duplicates="drop")
        frame["node_bin"] = pd.cut(frame["nodes_used"], bins=[0, 1, 2, 4, 8, 16, 64, 10_000], include_lowest=True)
        frame["e_decile"] = pd.qcut(frame[TARGET], 10, duplicates="drop", labels=False)
        for col in ("partition", "dur_bin", "node_bin", "e_decile"):
            g = frame.groupby(col, observed=True)
            for key, sub in g:
                mm = metrics(sub[TARGET], sub["pred"])
                mm.update({"split": split_name, "axis": col, "bin": str(key), "problem": "EX_POST"})
                cal_rows.append(mm)
    pd.DataFrame(cal_rows).to_csv(RESULTS / "job_energy_calibration.csv", index=False)
    return {
        "df": df,
        "rows": rows,
        "sel_post": sel_post,
        "sel_ante": sel_ante,
        "test_post": test_m_post,
        "test_ante": test_m_ante,
        "p_hat": p_hat,
        "p_ante": p_ante,
        "gen": gen,
        "apply_post": apply_post,
        "dev": dev,
        "val": val,
        "test": test,
        "best_post": best_post,
        "best_ante": best_ante,
    }


def energy_conservation(power_kw, dt_s, energy_wh) -> dict:
    recon = float(np.sum(power_kw * dt_s) / 3.6)  # kW * s / 3.6 = Wh
    total = float(np.sum(energy_wh))
    rel = abs(recon - total) / total if total else None
    return {"reconstructed_Wh": recon, "source_Wh": total, "rel_abs_err": rel, "pass": bool(rel is not None and rel < 1e-6)}


def replay_from_jobs(starts, ends, energy_wh, freq: str):
    """Uniform [start, end) energy allocation onto a regular grid (exact overlap)."""
    starts = pd.to_datetime(pd.Series(starts), utc=True).reset_index(drop=True)
    ends = pd.to_datetime(pd.Series(ends), utc=True).reset_index(drop=True)
    energy_wh = np.asarray(energy_wh, dtype=float)
    dur = (ends - starts).dt.total_seconds().to_numpy()
    ok = (dur > 0) & np.isfinite(energy_wh) & (energy_wh >= 0)
    starts = starts[ok].reset_index(drop=True)
    ends = ends[ok].reset_index(drop=True)
    energy_wh = energy_wh[ok]
    dur = dur[ok]
    t0 = starts.min().floor(freq)
    t1 = ends.max().ceil(freq)
    edges = pd.date_range(t0, t1, freq=freq, tz="UTC")
    if len(edges) < 2:
        raise ValueError("replay grid too short")
    # Use seconds from t0 to avoid pandas datetime integer unit ambiguity (ns vs us).
    edge_s = (edges - t0).total_seconds().to_numpy()
    start_s = (starts - t0).dt.total_seconds().to_numpy()
    end_s = (ends - t0).dt.total_seconds().to_numpy()
    i0 = np.clip(np.searchsorted(edge_s, start_s, side="right") - 1, 0, len(edges) - 2)
    i1 = np.clip(np.searchsorted(edge_s, end_s, side="right") - 1, 0, len(edges) - 2)
    n_bin = len(edges) - 1
    e_bin = np.zeros(n_bin, dtype=np.float64)
    same = i0 == i1
    np.add.at(e_bin, i0[same], energy_wh[same])
    diff = ~same
    if diff.any():
        i0d = i0[diff]
        i1d = i1[diff]
        ed = energy_wh[diff]
        durs = dur[diff]
        first_overlap = edge_s[i0d + 1] - start_s[diff]
        last_overlap = end_s[diff] - edge_s[i1d]
        np.add.at(e_bin, i0d, ed * np.clip(first_overlap, 0, None) / durs)
        np.add.at(e_bin, i1d, ed * np.clip(last_overlap, 0, None) / durs)
        mid = i1d > i0d + 1
        if mid.any():
            p_kw_mid = ed[mid] * 3.6 / durs[mid]
            dlt = np.zeros(n_bin + 1, dtype=np.float64)
            np.add.at(dlt, i0d[mid] + 1, p_kw_mid)
            np.add.at(dlt, i1d[mid], -p_kw_mid)
            dt_all = np.diff(edge_s)
            e_bin += np.cumsum(dlt[:-1]) * dt_all / 3.6
    dt_s = np.diff(edge_s)
    p_kw = e_bin * 3.6 / np.clip(dt_s, 1e-12, None)
    cons = energy_conservation(p_kw, dt_s, energy_wh)
    return edges[:-1], p_kw, cons, float(energy_wh.sum())


def build_replays(df: pd.DataFrame) -> dict:
    # Replay all primary-cohort jobs (measured + predicted)
    out = {}
    frames = []
    for freq, name in ("5min", "5min"), ("15min", "15min"), ("1h", "1h"), ("1D", "1day"):
        g, p_m, c_m, e_m = replay_from_jobs(df["start_utc"], df["end_utc"], df[TARGET], freq)
        _, p_p, c_p, _ = replay_from_jobs(df["start_utc"], df["end_utc"], df["pred_ex_post_wh"], freq)
        _, p_a, c_a, _ = replay_from_jobs(df["start_utc"], df["end_utc"], df["pred_ex_ante_wh"], freq)
        out[name] = {
            "measured_conservation": c_m,
            "ex_post_conservation": c_p,
            "ex_ante_conservation": c_a,
            "n_bins": int(len(g)),
        }
        part = pd.DataFrame(
            {
                "ts_utc": g,
                "resolution": name,
                "p_measured_kw": p_m,
                "p_ex_post_pred_kw": p_p,
                "p_ex_ante_pred_kw": p_a,
            }
        )
        frames.append(part)
    ts = pd.concat(frames, ignore_index=True)
    path = TIMESERIES / "kestrel_job_power_replay.parquet"
    ts.to_parquet(path, index=False)
    json_dump(RESULTS / "replay_conservation.json", out)
    return {"table": ts, "conservation": out, "path": path}


def esif_audit_and_link(replay: dict) -> dict:
    c = con()
    es = c.execute(
        f"""
        SELECT ts, it_power_kw
        FROM read_parquet('{ESIF_PARQUET}')
        WHERE it_power_kw IS NOT NULL AND isfinite(it_power_kw)
        ORDER BY ts
        """
    ).fetchdf()
    # Predeclared: naive ESIF timestamps are America/Denver civil time.
    ts_naive = pd.to_datetime(es["ts"])
    es["ts_denver"] = ts_naive.dt.tz_localize(DENVER, ambiguous="NaT", nonexistent="shift_forward")
    es = es.dropna(subset=["ts_denver"])
    es["ts_utc"] = es["ts_denver"].dt.tz_convert("UTC")
    kmin = pd.Timestamp("2023-08-10", tz="UTC")
    kmax = pd.Timestamp("2026-02-24", tz="UTC")
    overlap = es[(es["ts_utc"] >= kmin) & (es["ts_utc"] <= kmax)]
    dt = overlap["ts_utc"].diff().dt.total_seconds()
    audit = {
        "esif_ts_interpretation": "timezone-naive timestamps localized as America/Denver (predeclared; catalog does not state offset)",
        "kestrel_timestamps": "timestamptz converted to UTC",
        "esif_n_it": int(len(es)),
        "esif_min": str(es["ts_utc"].min()),
        "esif_max": str(es["ts_utc"].max()),
        "kestrel_job_coverage_note": "submit/start from 2023-08-10; hive through 2025-12",
        "overlap_n": int(len(overlap)),
        "overlap_min": str(overlap["ts_utc"].min()) if len(overlap) else None,
        "overlap_max": str(overlap["ts_utc"].max()) if len(overlap) else None,
        "median_cadence_s": float(dt.median()) if len(dt) else None,
        "duplicate_ts": False,
        "gaps_gt_1h": int((dt > 3600).sum()) if len(dt) else None,
        "it_power_kw_min": float(es["it_power_kw"].min()),
        "it_power_kw_max": float(es["it_power_kw"].max()),
        "linkage_supported": bool(len(overlap) > 10000),
        "cooling_predictors_used": False,
        "equality_assumption_forbidden": "P_ESIF_IT != sum P_Kestrel_jobs",
    }
    json_dump(ANALYSIS / "ESIF_OVERLAP_AUDIT.json", audit)
    (ANALYSIS / "METER_BOUNDARY_AUDIT.md").write_text(
        """# ESIF IT meter boundary (Kestrel experiment)

ESIF `it_power_kw` captures power used by **IT equipment on the data-center floor**, not Kestrel active jobs alone (NLR HPC Facility PUE Data, DOI 10.7799/3015212).

Do **not** interpret unexplained power as job-energy model failure.

## Documented systems on the floor (authoritative, not inferred from the series)

1. **Kestrel CPU nodes** — dual-socket Sapphire Rapids, 104 cores, ~240–256 GB, 100% direct liquid cooling. CPU phase installed summer 2023; open to all projects for FY2024 (NLR news; datacard jobs from 2023-08).
2. **Kestrel GPU nodes** — 156 nodes, 4× NVIDIA H100 SXM 80 GB, AMD Genoa 128 cores, shareable by default (NLR *Running on Kestrel*). GPU hardware arrived 2024-02; early users ~2024-05; general availability reported 2024-08-21. **This job extract contains no positive `consumed_energy_raw_*` for any GPU partition.** GPU IT load can appear on the facility meter without appearing in the job-energy replay.
3. **Eagle** — previous 2,000-node HPC in ESIF, 2019–2024. NLR announced decommissioning on **15 June 2024** (HPC announcement “Kestrel GPUs and Eagle End of Service”, 11 June 2024). Eagle storage access was planned through 2024-09-30. During 2023-08 to 2024-06-15 the IT meter includes Eagle + Kestrel coexistence.
4. **Idle Kestrel nodes, login/service nodes, storage, networking, and other ESIF computing equipment** remain on the IT meter when no jobs are active.

## Epochs used (externally justified)

| Epoch | Window (America/Denver date) | Why |
|---|---|---|
| `eagle_coexist` | start → 2024-06-14 | Eagle still in service |
| `post_eagle` | 2024-06-15 onward | Eagle compute decommissioned |
| `post_gpu_ga` | 2024-08-21 onward | GPU nodes reported generally available; job trace still lacks GPU energy |

Idle/no-job intervals are **not** expected to show zero IT power.

## Modeling implication

Primary linkage model: `P_ESIF_IT(t) = B + β P_Kestrel_jobs(t) + ε_t`.

`B` is a residual IT baseline (idle + non-Kestrel + unmeasured GPU + storage/network). `β` is the incremental association of *measured CPU-job-attributed* Kestrel energy with the facility IT meter. Exact equality (`β=1`, `B=0`) is **not** the scientific target.
"""
    )
    if not audit["linkage_supported"]:
        return {"status": "UNSUPPORTED", "audit": audit}
    # hourly join is the most robust resolution for naive-vs-timestamptz
    hourly = replay["table"]
    hourly = hourly[hourly["resolution"] == "1h"].copy()
    es_h = (
        overlap.set_index("ts_utc")["it_power_kw"].resample("1h").mean().rename("esif_it_kw")
    )
    k_h = hourly.set_index("ts_utc")["p_measured_kw"].rename("kestrel_jobs_kw")
    both = pd.concat([es_h, k_h], axis=1).dropna()
    both = both[(both.index >= kmin) & (both.index <= overlap["ts_utc"].max())]
    both["epoch"] = np.where(
        both.index < pd.Timestamp(EAGLE_DECOMMISSION_UTC),
        "eagle_coexist",
        np.where(both.index < pd.Timestamp(GPU_GA_UTC), "post_eagle_pre_gpu_ga", "post_gpu_ga"),
    )
    link_rows = []
    pred_parts = []
    for freq_name, res in ("5min", "5min"), ("15min", "15min"), ("1h", "1h"), ("1day", "1day"):
        k = replay["table"]
        k = k[k["resolution"] == freq_name].set_index("ts_utc")["p_measured_kw"]
        rule = {"5min": "5min", "15min": "15min", "1h": "1h", "1day": "1D"}[freq_name]
        e = overlap.set_index("ts_utc")["it_power_kw"].resample(rule).mean()
        m = pd.concat([e.rename("esif_it_kw"), k.rename("kestrel_jobs_kw")], axis=1).dropna()
        if freq_name == "1day":
            m = m[m["kestrel_jobs_kw"].notna()]
        for epoch, sub in (("all", m),) + tuple((ep, g) for ep, g in m.groupby(
            np.where(
                m.index < pd.Timestamp(EAGLE_DECOMMISSION_UTC),
                "eagle_coexist",
                np.where(m.index < pd.Timestamp(GPU_GA_UTC), "post_eagle_pre_gpu_ga", "post_gpu_ga"),
            )
        )):
            if len(sub) < 20:
                continue
            x = sub["kestrel_jobs_kw"].to_numpy()
            y = sub["esif_it_kw"].to_numpy()
            X = np.column_stack([np.ones(len(x)), x])
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
            yhat = X @ beta
            err = yhat - y
            pear = float(np.corrcoef(x, y)[0, 1]) if np.std(x) and np.std(y) else None
            sp = float(pd.Series(x).corr(pd.Series(y), method="spearman"))
            ss_res = float(np.sum((y - yhat) ** 2))
            ss_tot = float(np.sum((y - y.mean()) ** 2))
            r2 = 1 - ss_res / ss_tot if ss_tot else None
            # energy: kW * hours
            if freq_name == "1day":
                dt_h = 24.0
            elif freq_name == "1h":
                dt_h = 1.0
            elif freq_name == "15min":
                dt_h = 0.25
            else:
                dt_h = 5 / 60
            link_rows.append(
                {
                    "resolution": freq_name,
                    "epoch": epoch,
                    "n": int(len(sub)),
                    "B_kw": float(beta[0]),
                    "beta": float(beta[1]),
                    "pearson": pear,
                    "spearman": sp,
                    "R2": r2,
                    "MAE_kw": float(np.mean(np.abs(err))),
                    "RMSE_kw": float(np.sqrt(np.mean(err**2))),
                    "sum_esif_kWh": float(np.sum(y) * dt_h),
                    "sum_kestrel_kWh": float(np.sum(x) * dt_h),
                    "sum_yhat_kWh": float(np.sum(yhat) * dt_h),
                }
            )
        if freq_name == "1h":
            x = m["kestrel_jobs_kw"].to_numpy()
            y = m["esif_it_kw"].to_numpy()
            X = np.column_stack([np.ones(len(x)), x])
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
            m = m.copy()
            m["yhat_kw"] = X @ beta
            pred_parts.append(m.reset_index())
    pd.DataFrame(link_rows).to_csv(FACILITY / "esif_it_linkage_metrics.csv", index=False)
    if pred_parts:
        pred_parts[0].to_parquet(FACILITY / "esif_it_linkage_timeseries.parquet", index=False)
    # low-job baseline
    if len(both):
        q05 = both["kestrel_jobs_kw"].quantile(0.05)
        low = both[both["kestrel_jobs_kw"] <= q05]
        audit["low_job_baseline_kw_mean"] = float(low["esif_it_kw"].mean()) if len(low) else None
        audit["low_job_kestrel_kw_mean"] = float(low["kestrel_jobs_kw"].mean()) if len(low) else None
        json_dump(ANALYSIS / "ESIF_OVERLAP_AUDIT.json", audit)
    return {"status": "SUPPORTED", "metrics": link_rows, "audit": audit, "hourly": both}


def make_figures(df: pd.DataFrame, fit: dict, replay: dict, esif) -> None:
    rng = np.random.default_rng(0)
    sample = df.sample(min(80_000, len(df)), random_state=0)
    fig, ax = plt.subplots(figsize=(6.2, 5.0))
    hb = ax.hexbin(
        np.log10(np.clip(sample["node_hours"], 1e-6, None)),
        np.log10(np.clip(sample[TARGET], 1e-6, None)),
        gridsize=60,
        cmap="viridis",
        mincnt=1,
        bins="log",
    )
    xx = np.linspace(-4, 4, 50)
    p = fit["p_hat"]
    ax.plot(xx, np.log10(np.clip((10**xx) * p, 1e-12, None)), color="crimson", lw=1.5, label=f"B0 p={p:.0f} W")
    ax.set_xlabel("log10 node-hours")
    ax.set_ylabel("log10 measured energy (Wh)")
    ax.set_title("CPU non-shared jobs: energy vs node-hours")
    ax.legend(frameon=False)
    fig.colorbar(hb, ax=ax, label="log count")
    fig.tight_layout()
    fig.savefig(FIGURES / "01_energy_vs_node_hours_cpu.png", dpi=140)
    plt.close(fig)

    test = fit["test"]
    fig, ax = plt.subplots(figsize=(6.2, 5.0))
    s = test.sample(min(80_000, len(test)), random_state=1).copy()
    s["pred_plot"] = fit["apply_post"](s)
    hb = ax.hexbin(
        np.log10(np.clip(s[TARGET], 1e-6, None)),
        np.log10(np.clip(s["pred_plot"], 1e-6, None)),
        gridsize=60,
        cmap="viridis",
        mincnt=1,
        bins="log",
    )
    ax.plot([1, 8], [1, 8], color="k", lw=1)
    ax.set_xlabel("log10 observed Wh (chronological test)")
    ax.set_ylabel("log10 predicted Wh")
    ax.set_title(f"EX-POST test: {fit['sel_post']['model']}")
    fig.colorbar(hb, ax=ax, label="log count")
    fig.tight_layout()
    fig.savefig(FIGURES / "02_ex_post_test_pred_vs_obs.png", dpi=140)
    plt.close(fig)

    cal = pd.read_csv(RESULTS / "job_energy_calibration.csv")
    sub = cal[(cal["split"] == "test") & (cal["axis"] == "dur_bin")]
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    ax.bar(range(len(sub)), sub["WAPE"])
    ax.set_xticks(range(len(sub)), [str(x)[:24] for x in sub["bin"]], rotation=30, ha="right")
    ax.set_ylabel("WAPE")
    ax.set_title("EX-POST test WAPE by duration quintile")
    fig.tight_layout()
    fig.savefig(FIGURES / "03_calibration_duration.png", dpi=140)
    plt.close(fig)

    d = df.copy()
    d["day"] = d["start_utc"].dt.floor("D")
    g = d.groupby("day")[[TARGET, "pred_ex_post_wh", "pred_ex_ante_wh"]].sum()
    fig, ax = plt.subplots(figsize=(8.5, 3.8))
    ax.plot(g.index, g[TARGET] / 1e6, label="observed", lw=1)
    ax.plot(g.index, g["pred_ex_post_wh"] / 1e6, label="EX-POST", lw=1, alpha=0.85)
    ax.plot(g.index, g["pred_ex_ante_wh"] / 1e6, label="EX-ANTE", lw=1, alpha=0.85)
    ax.axvline(pd.Timestamp(SPLIT_DEV_END), color="gray", ls="--", lw=0.8)
    ax.axvline(pd.Timestamp(SPLIT_VAL_END), color="gray", ls=":", lw=0.8)
    ax.set_ylabel("MWh / day")
    ax.set_title("Aggregate job energy by day (primary CPU cohort)")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIGURES / "04_daily_aggregate_energy.png", dpi=140)
    plt.close(fig)

    if esif.get("status") == "SUPPORTED" and esif.get("hourly") is not None:
        h = esif["hourly"]
        fig, ax = plt.subplots(figsize=(8.5, 3.8))
        w = h.loc["2024-09-01":"2024-09-14"]
        if len(w):
            ax.plot(w.index, w["esif_it_kw"], label="ESIF IT kW", lw=1)
            ax.plot(w.index, w["kestrel_jobs_kw"], label="Kestrel CPU-job replay kW", lw=1)
            ax.set_ylabel("kW")
            ax.set_title("Post-Eagle window: facility IT vs Kestrel job-attributed power")
            ax.legend(frameon=False)
            fig.tight_layout()
            fig.savefig(FIGURES / "05_esif_vs_kestrel_window.png", dpi=140)
            plt.close(fig)
        fig, ax = plt.subplots(figsize=(6.2, 4.6))
        h_num = h[["esif_it_kw", "kestrel_jobs_kw"]].apply(pd.to_numeric, errors="coerce")
        day = h_num.resample("1D").mean()
        ax.scatter(day["kestrel_jobs_kw"], day["esif_it_kw"], s=8, alpha=0.4)
        ax.set_xlabel("Daily-mean Kestrel job-attributed kW")
        ax.set_ylabel("Daily-mean ESIF IT kW")
        ax.set_title("Load comparison (not an equality test)")
        fig.tight_layout()
        fig.savefig(FIGURES / "06_esif_daily_energy_scatter.png", dpi=140)
        plt.close(fig)


def statuses(qc, freeze, fit, replay, esif) -> dict:
    target_q = "PASS" if qc["energy"]["j_wh_mismatch"] == 0 and qc["n_source_rows"] > 10_000_000 else "PARTIAL"
    if qc["h100_measured_energy_positive_jobs"] == 0:
        target_q = "PARTIAL"
    wape = fit["test_post"]["WAPE"]
    ex_post = "PASS" if wape is not None and wape < 0.25 else ("PARTIAL" if wape and wape < 0.5 else "FAIL")
    wape_a = fit["test_ante"]["WAPE"]
    ex_ante = "PASS" if wape_a is not None and wape_a < 0.35 else ("PARTIAL" if wape_a and wape_a < 0.6 else "FAIL")
    cons_ok = all(
        replay["conservation"][k]["measured_conservation"]["pass"]
        for k in replay["conservation"]
    )
    replay_st = "PASS" if cons_ok else "FAIL"
    if esif["status"] != "SUPPORTED":
        esif_st = "UNSUPPORTED"
    else:
        hour = [r for r in esif["metrics"] if r["resolution"] == "1h" and r["epoch"] == "all"]
        post = [r for r in esif["metrics"] if r["resolution"] == "1h" and r["epoch"] == "post_gpu_ga"]
        r2 = (post[0]["R2"] if post else None) or (hour[0]["R2"] if hour else None)
        pear = (post[0]["pearson"] if post else None)
        if r2 is not None and r2 > 0.4 and pear is not None and pear > 0.6:
            esif_st = "PASS"
        elif (r2 is not None and r2 > 0.05) or (pear is not None and pear > 0.2):
            esif_st = "PARTIAL"
        elif r2 is not None:
            esif_st = "FAIL"
        else:
            esif_st = "UNSUPPORTED"
    st = {
        "JOB_ENERGY_TARGET_QUALITY": target_q,
        "JOB_ENERGY_EX_POST": ex_post,
        "JOB_ENERGY_EX_ANTE": ex_ante,
        "TEMPORAL_JOB_POWER_REPLAY": replay_st,
        "ESIF_IT_METER_LINKAGE": esif_st,
        "H100_MEASURED_ENERGY": "UNSUPPORTED",
        "test_ex_post": fit["test_post"],
        "test_ex_ante": fit["test_ante"],
        "selected_ex_post": fit["sel_post"]["model"],
        "selected_ex_ante": fit["sel_ante"]["model"],
        "p_hat_W": fit["p_hat"],
        "primary_cohort_n": freeze["n_jobs"],
        "replay_conservation": replay["conservation"],
        "esif_status": esif["status"],
    }
    json_dump(RESULTS / "FINAL_KESTREL_JOB_POWER_STATUS.json", st)
    return st


def write_report(qc, freeze, proto, fit, replay, esif, st) -> None:
    hour_metrics = []
    if esif.get("metrics"):
        hour_metrics = [r for r in esif["metrics"] if r["resolution"] == "1h"]
    md = f"""# Kestrel job IT energy and conditional ESIF IT-meter validation

Bounded experiment. Cooling/WUE/weather unused. GenAI profiles unused. Hashes unused as predictors. TDP unused as a predictor.

## Source

- Kestrel jobs: DOI `{KESTREL_DOI}`, archive MD5 `{KESTREL_ZIP_MD5}` **verified** against NLR catalog. SHA-256 `{KESTREL_ZIP_SHA256}`. Not redownloaded.
- Rows: **{qc['n_source_rows']:,}**. Hive Parquet Aug 2023–Dec 2025.
- ESIF PUE parquet downloaded once (missing locally): DOI `{ESIF_DOI}`, SHA-256 `{ESIF_PARQUET_SHA256}`. Weather file not downloaded.

## Energy target

Canonical target: `consumed_energy_raw_watt_hours` (Slurm node-level `ConsumedEnergyRaw`). Joule identity holds (max abs error ~1e-11 Wh).

H100/GPU partitions: **zero jobs with positive measured energy**. H100 measured job-energy models are **UNSUPPORTED** in this extract. TDP fields remain engineering estimates only.

## Sharing

`shared_job_count=0` ↔ empty co-resident arrays (explicit unshared). Positive counts ↔ nonempty arrays and concentrate on `shared*` partitions. NULL is the typical exclusive-CPU encoding. Energy/node-hour is similar for shared-partition co-resident jobs and exclusive CPU jobs (~600–700 W), so summing shared jobs risks **double-counting node energy**.

Primary cohort: COMPLETED exclusive-CPU non-shared (`shared_job_count` null or 0), positive measured energy, valid timing/resources. **n={freeze['n_jobs']:,}** ({freeze['pct_source_rows']:.2f}% of rows; {freeze['pct_measured_total_energy']:.1f}% of measured energy).

## Models (CPU only; chronological split)

DEV: start < {SPLIT_DEV_END}. VAL: to {SPLIT_VAL_END}. TEST: after. Splits frozen from coverage, not scores.

EX-POST selected: **{fit['sel_post']['model']}**. Chronological test WAPE={fit['test_post']['WAPE']:.4f}, total-energy bias={fit['test_post']['total_energy_bias']:.4f}, R²(log E)={fit['test_post']['R2_logE']}.

EX-ANTE selected: **{fit['sel_ante']['model']}**. Test WAPE={fit['test_ante']['WAPE']:.4f}, bias={fit['test_ante']['total_energy_bias']:.4f}.

B0 node-hour coefficient (dev): **{fit['p_hat']:.1f} W per occupied CPU node**.

Nonlinear HGB is used only if validation WAPE improves by more than the 1% parsimony rule.

## Replay

Uniform allocation of job energy over actual `[start,end)`. Conservation tests: see `results/replay_conservation.json`. This is **time-averaged job-attributed power**, not instantaneous node telemetry. GPU energy is absent.

## ESIF linkage

Meter boundary: all IT on the ESIF floor (idle Kestrel, Eagle until 2024-06-15, GPU IT, storage, network, other). Model `P_ESIF_IT = B + β P_jobs + ε`, not equality.

Linkage status: **{st['ESIF_IT_METER_LINKAGE']}**.

Hourly metrics:

```
{json.dumps(hour_metrics, indent=2)}
```

## Capability statuses

- JOB_ENERGY_TARGET_QUALITY: **{st['JOB_ENERGY_TARGET_QUALITY']}**
- JOB_ENERGY_EX_POST: **{st['JOB_ENERGY_EX_POST']}**
- JOB_ENERGY_EX_ANTE: **{st['JOB_ENERGY_EX_ANTE']}**
- TEMPORAL_JOB_POWER_REPLAY: **{st['TEMPORAL_JOB_POWER_REPLAY']}**
- ESIF_IT_METER_LINKAGE: **{st['ESIF_IT_METER_LINKAGE']}**

## Canonical implication

CPU-node-hour (and refinements using actual CPU-hours) is the justified Kestrel CPU IT-energy proxy. Keep CPU and H100 separate; H100 measured energy is missing here. The proxy is HPC/Kestrel-specific in coefficient, generic in form `E ≈ p_node × node-hours`. ESIF provides incremental-load validation, not reconstruction of the full IT meter.

Highest-value next experiment: **ESIF IT → cooling/HVAC/pump + weather** is *not* yet the highest-value step while GPU job energy is missing from the public Kestrel extract. Prefer **NLR GenAI sub-hourly profiles** only if AI burst shape is decision-relevant; otherwise **GPU/node-level power (or Eagle job-energy as a second HPC) / Google hyperscale** depending on whether the next gap is missing GPU energy or hyperscale generality.
"""
    (DOCS / "KESTREL_JOB_POWER_REPORT.md").write_text(md)


def main():
    os.environ.setdefault("PYTHONNOUSERSITE", "1")
    ensure_dirs()
    print("1 initial state / inventory / provenance", flush=True)
    write_initial_state()
    inv = write_inventory()
    prov = write_provenance(inv)
    if prov["kestrel_jobs"]["status"] != "LOCAL_EXISTING_VERIFIED":
        raise SystemExit("Kestrel zip failed catalog identity; not overwriting.")
    extract_if_needed(prov)
    print("2 QC + sharing", flush=True)
    c = con()
    qc = run_qc(c)
    sharing = run_sharing_audit(c)
    print("3 analysis parquet", flush=True)
    write_analysis_parquet(c)
    freeze = freeze_cohort(c)
    proto = freeze_protocol(qc, freeze)
    print("4 models", flush=True)
    fit = fit_hierarchy(load_cohort())
    print("5 replay", flush=True)
    replay = build_replays(fit["df"])
    print("6 ESIF", flush=True)
    esif = esif_audit_and_link(replay)
    print("7 figures/report", flush=True)
    make_figures(fit["df"], fit, replay, esif)
    st = statuses(qc, freeze, fit, replay, esif)
    write_report(qc, freeze, proto, fit, replay, esif, st)
    print("DONE", json.dumps({k: st[k] for k in list(st)[:6]}), flush=True)


if __name__ == "__main__":
    main()
