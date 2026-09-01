"""Paths for the IT-power workload→node closure pass."""
from __future__ import annotations

from pathlib import Path

IT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = IT_ROOT.parents[1]
NLR_ROOT = IT_ROOT.parent / "nlr_esif_fullstack"
H100_ROOT = NLR_ROOT / "genai_h100"

MANIFESTS = IT_ROOT / "manifests"
ANALYSIS = IT_ROOT / "analysis"
DOCS = IT_ROOT / "docs"
TESTS = IT_ROOT / "tests"
SCRIPTS = IT_ROOT / "scripts"
FIGURES = IT_ROOT / "figures"
DATA_PROCESSED = IT_ROOT / "data_processed"

FIGSHARE_ZIP = (
    IT_ROOT
    / "independent_h100_b200"
    / "High-resolution-AI-Data-Center-Training-Workloads-Dataset_FigShare.zip"
)
NEWKIRK_ZIP = IT_ROOT / "full_node_h100" / "sources" / "newkirk_2025" / "29067572.zip"
NEWKIRK_PAPER = IT_ROOT / "independent_h100_b200" / "2025_Empirically-calibrated H100 node power models.pdf"
ELSAYED_PAPER = (
    IT_ROOT
    / "independent_h100_b200"
    / "2026_Characterization of high-resolution AI data center training workloads on single and multiple GPU nodes.pdf"
)
LATIF_PAPER = (
    IT_ROOT
    / "full_node_h100"
    / "sources"
    / "newkirk_2025"
    / "2025_Single-Node_Power_Demand_During_AI_Training_Measurements_on_an_8-GPU_NVIDIA_H100_System.pdf"
)
COOLING_PAPER = (
    IT_ROOT
    / "full_node_h100"
    / "sources"
    / "newkirk_2025"
    / "2025_Cooling_Matters_Benchmarking_Large_Language_Models_and_Vision-Language_Models_on_Liquid-Cooled_Versus_Air-Cooled_H100_GPU_Systems.pdf"
)

CPU_STATUS = NLR_ROOT / "analysis" / "FINAL_KESTREL_CPU_STATUS.json"
CPU_FREEZE = NLR_ROOT / "manifests" / "FINAL_MODEL_FREEZE.json"
H100_STATUS = H100_ROOT / "results" / "FINAL_H100_POWER_STATUS.json"
H100_RUNNER = H100_ROOT / "scripts" / "run_h100_experiment.py"
H100_INTENSITY = H100_ROOT / "analysis" / "H100_INTENSITY_BY_RUN.csv"
H100_SUMMARY = H100_ROOT / "data_processed" / "h100_experiment_summary.parquet"
GENAI_ZIP = NLR_ROOT / "data_raw" / "genai" / "dataset.zip"
KESTREL_JOBS = NLR_ROOT / "data_processed" / "kestrel_jobs_analysis.parquet"
EXTRACTED = NLR_ROOT / "data_raw" / "extracted" / "genai"

CPU_P_KW = 0.7006894574294788
CPU_DISPOSITION = "FROZEN_PASS_WITH_DOMAIN_RESTRICTIONS"

# Newkirk Environ. Res.: Energy 2025 preferred specification (paper Table 3 / §6).
NEWKIRK_PIDLE_KW = 1.86
NEWKIRK_ALPHA = 5.11
NEWKIRK_BETA_LLM_KW = 6.89
NEWKIRK_BETA_CNN_KW = 6.28
NEWKIRK_PMAX_KW = 8.4
NEWKIRK_OOS_MAPE_PUBLISHED = 0.0539
NEWKIRK_INSAMPLE_MAPE_ARCH = 0.111

FIGSHARE_SHA256 = "c0ccebea568612f5445b70c3baa7ce659935a949e5cc8f345a0af907739fa6f3"
NEWKIRK_ZIP_SHA256 = "eb09d4aa8167bc121b906fde4b7dacf12dcdd56012d621ae9ca895a512794d37"
GENAI_SHA256 = "dcad6de800fb565d850b163902e2eddae48aabd1ed1c7336f9a1cdaf3012f137"
