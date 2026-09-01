"""Paths and frozen identity for the NLR GenAI H100 measurement module.

Does not import or modify the frozen Kestrel CPU layer except to record its
read-only disposition.
"""
from __future__ import annotations

from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
NLR_ROOT = MODULE_ROOT.parent
REPO_ROOT = NLR_ROOT.parents[1]

DATA_RAW = NLR_ROOT / "data_raw"
GENAI_RAW = DATA_RAW / "genai"
GENAI_ZIP = GENAI_RAW / "dataset.zip"
EXTRACTED = DATA_RAW / "extracted" / "genai"

MANIFESTS = MODULE_ROOT / "manifests"
ANALYSIS = MODULE_ROOT / "analysis"
DATA_PROCESSED = MODULE_ROOT / "data_processed"
RESULTS = MODULE_ROOT / "results"
FIGURES = MODULE_ROOT / "figures"
DOCS = MODULE_ROOT / "docs"
TESTS = MODULE_ROOT / "tests"
SOURCES = MODULE_ROOT / "sources"
SCRIPTS = MODULE_ROOT / "scripts"

CPU_STATUS = NLR_ROOT / "analysis" / "FINAL_KESTREL_CPU_STATUS.json"
CPU_FREEZE = NLR_ROOT / "manifests" / "FINAL_MODEL_FREEZE.json"
CPU_PROTOCOL = NLR_ROOT / "manifests" / "MODEL_PROTOCOL_FREEZE.json"
KESTREL_JOBS = NLR_ROOT / "data_processed" / "kestrel_jobs_analysis.parquet"

GENAI_DOI = "10.7799/3025227"
GENAI_CATALOG_URL = "https://data.nlr.gov/submissions/312"
GENAI_CATALOG_VERSION = 2
GENAI_CATALOG_SIZE_LABEL = "1021.3 MB"
GENAI_CATALOG_VERSION_DATE = "2026-04-10"
GENAI_CATALOG_LAST_UPDATED = "2026-07-17"
PAPER_ARXIV = "2604.07345"
PAPER_TITLE = (
    "Measurement of Generative AI Workload Power Profiles for "
    "Whole-Facility Data Center Infrastructure Planning"
)

# Local archive identity (computed once; tests re-check).
GENAI_ZIP_SHA256 = "dcad6de800fb565d850b163902e2eddae48aabd1ed1c7336f9a1cdaf3012f137"
GENAI_ZIP_BYTES = 1_070_866_623

GPUS_PER_NODE = 4
CPU_SOCKETS_PER_NODE = 2
GPU_TDP_W = 700.0
CPU_TDP_W = 360.0
NODE_COMPUTE_TDP_W = GPUS_PER_NODE * GPU_TDP_W + CPU_SOCKETS_PER_NODE * CPU_TDP_W

CPU_FROZEN_P = 700.6894574294788
CPU_FROZEN_DISPOSITION = "FROZEN_PASS_WITH_DOMAIN_RESTRICTIONS"

DATETIME_FORMAT = "%Y-%m-%d_%H:%M:%S.%f"
