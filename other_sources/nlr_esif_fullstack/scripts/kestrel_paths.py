"""Paths and frozen source identity for the Kestrel job-power experiment."""
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MODULE_ROOT.parents[1]

DATA_RAW = MODULE_ROOT / "data_raw"
EXTRACTED = DATA_RAW / "extracted" / "esif.hpc.kestrel.job-anon"
KESTREL_ZIP = DATA_RAW / "esif.hpc.kestrel.job-anon.zip"
DATACARD = DATA_RAW / "datacard.md"
ESIF_DIR = DATA_RAW / "esif_pue"
ESIF_PARQUET = ESIF_DIR / "esif.influx.buildingData.PUE.combined.parquet"
ESIF_README = ESIF_DIR / "README.md"

MANIFESTS = MODULE_ROOT / "manifests"
ANALYSIS = MODULE_ROOT / "analysis"
DATA_PROCESSED = MODULE_ROOT / "data_processed"
RESULTS = MODULE_ROOT / "results"
TIMESERIES = MODULE_ROOT / "timeseries"
FACILITY = MODULE_ROOT / "facility_validation"
FIGURES = MODULE_ROOT / "figures"
DOCS = MODULE_ROOT / "docs"
LOGS = MODULE_ROOT / "logs"
TESTS = MODULE_ROOT / "tests"
SOURCES = MODULE_ROOT / "sources"

KESTREL_GLOB = str(EXTRACTED / "year=*" / "month=*" / "*.parquet")
DUCKDB_PARQUET_OPTS = "hive_partitioning=true, union_by_name=true"

# Catalog identity for the already-staged Kestrel archive (DOI 10.7799/3023270).
KESTREL_ZIP_MD5 = "8f1d3be1cbe6345ef45e658a783c2aa0"
KESTREL_ZIP_SHA256 = "3a90f9ac40991712f8718c686fa7b05d7a303a44a87ed1a8f21b403c11efd26f"
KESTREL_DOI = "10.7799/3023270"
ESIF_DOI = "10.7799/3015212"
ESIF_PARQUET_SHA256 = "19cd12405dde9144b1a360e8c8418666c399a3d0d15a7f846880d71ab22f9dd4"
DATACARD_SHA256 = "0139b75b80cd3029e0af54e22fc0dbad3080e92a8a7a602f1bd62cd7a36f62e9"

NS_PER_S = 1_000_000_000.0

CPU_EXCLUSIVE_PARTITIONS = frozenset(
    {
        "standard",
        "short",
        "long",
        "debug",
        "nvme",
        "hbw",
        "hbwl",
        "medmem",
        "bigmem",
        "bigmeml",
        "standard-stdby",
        "short-stdby",
        "long-stdby",
        "debug-stdby",
        "hbw-stdby",
        "bigmem-stdby",
        "bigmeml-stdby",
        "medmem-stdby",
    }
)
H100_PARTITIONS = frozenset(
    {
        "gpu-h100",
        "gpu-h100s",
        "gpu-h100l",
        "gpu-h100-stdby",
        "gpu-h100s-stdby",
        "debug-gpu",
        "debug-gpu-stdby",
    }
)
SHARED_PARTITIONS = frozenset(
    {"shared", "sharedl", "shared-stdby", "sharedl-stdby"}
)

# Chronological protocol — frozen from coverage/epochs, not model scores.
SPLIT_DEV_END = "2025-01-01T00:00:00+00:00"
SPLIT_VAL_END = "2025-07-01T00:00:00+00:00"
EAGLE_DECOMMISSION_UTC = "2024-06-15T06:00:00+00:00"  # 2024-06-15 00:00 America/Denver
GPU_GA_UTC = "2024-08-21T06:00:00+00:00"

EX_ANTE_FEATURES = (
    "partition",
    "nodes_req",
    "processors_req",
    "memory_req_gb",
    "wallclock_req_s",
    "qos",
)
EX_POST_FEATURES = (
    "partition",
    "nodes_used",
    "processors_used",
    "duration_s",
    "cpu_used_s",
    "cpu_eff",
    "avg_mem_eff",
    "qos",
)
FORBIDDEN_PREDICTORS = (
    "consumed_energy_raw_joules",
    "consumed_energy_raw_watt_hours",
    "consumed_energy_joules",
    "cpu_energy_tdp_estimated_max_watt_hours",
    "cpu_energy_tdp_estimated_used_watt_hours",
    "user_hash",
    "account_hash",
    "name_hash",
    "submit_line_hash",
    "work_dir_hash",
    "submit_script_hash",
    "job_type_hash",
)
EX_ANTE_FORBIDDEN_POST_EXEC = (
    "start_time",
    "end_time",
    "nodes_used",
    "processors_used",
    "wallclock_used",
    "cpu_used",
    "cpu_eff",
    "max_mem_eff",
    "min_mem_eff",
    "avg_mem_eff",
    "gpu_nodes_occupied",
    "nodelist",
    "queue_wait",
    "duration_s",
    "cpu_used_s",
    "node_hours",
    "cpu_hours",
)

HASH_COLS = (
    "name_hash",
    "user_hash",
    "account_hash",
    "submit_line_hash",
    "work_dir_hash",
    "submit_script_hash",
    "job_type_hash",
)
