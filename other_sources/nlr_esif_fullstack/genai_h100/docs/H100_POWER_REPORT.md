# H100 / GenAI measured compute power

Module: `other_sources/nlr_esif_fullstack/genai_h100/`  
Dataset: DOI `10.7799/3025227`, NLR catalog version **2** (updated README, 2026-04-10; catalog last updated 2026-07-17).  
Local `dataset.zip`: 1,070,866,623 bytes; SHA-256 `dcad6de800fb565d850b163902e2eddae48aabd1ed1c7336f9a1cdaf3012f137`. Not redownloaded.  
Paper: Vercellino et al. 2026, arXiv:2604.07345.  
Frozen CPU layer: `FROZEN_PASS_WITH_DOMAIN_RESTRICTIONS` (read-only; not rerun).  
WattAMeter: `WATTAMETER_VERSION_UNRESOLVED` (paper cites the 2025 GitHub repo; dataset `requirements.txt` has no pin).

## What is measured

WattAMeter logs:

- **GPU:** NVML instantaneous power per device (`gpu-k[mW]`) plus temperature.
- **CPU:** AMD RAPL package and core domains (`cpu-k[W]`, `cpu-k-core[W]`) on two EPYC 9554 sockets.

Source aggregated `power[W]` is the linearly resampled sum of those components:

```
P_compute = P_GPU + P_CPU
E_compute = E_GPU + E_CPU
```

with each energy integral taken on **native timestamps** in this module, then added. Combined traces use the authors' 0.2 s (training) / 0.1 s (inference) common grid.

This is **measured_compute_power / measured_compute_energy**, not full-node AC.

```
P_node = P_compute_measured + P_other_node
```

`P_other_node` is **unresolved** (DRAM beyond package RAPL, NVMe, NICs, board/chassis, PSU losses, other peripherals). It is not estimated from TDP remainder, ESIF residuals, or literature overhead.

GPU evidence class: relatively strong (~±5% NVML in the paper/literature).  
AMD RAPL: lower / partially validated (paper: Intel RAPL vs AC is strong; comparable AMD validation was not identified; Kestrel H100 nodes are Genoa).  
Combined compute: GPU-dominated (~90% of training energy), so the weaker CPU link is a minority of `P_compute`.

Core-domain RAPL is ~0.3% of CPU energy in training logs. Source `postprocess.py` sums package+core; double-count is negligible.

## Experiment design

The scientific unit is **one independent run/profile**, not a 0.1/0.2 s sample (2,467 independent profiles, not millions of time points).

| Class | Independent runs | Nodes | Notes |
|---|---:|---|---|
| Llama-2 70B LoRA fine-tune | 21 | 2,4,8,16 | MLPerf Training v4.0; **weak scaling** / increasing global batch |
| Stable Diffusion training | 20 | 2,4,8,16 | Same; 1-node raw logs exist but source `data_map` omitted them |
| Llama-3 70B offline inference | 1200 | 1 | batch 25–1000 × max_out 512/1024 × 3 repeats |
| Online finite | 1026 | 1 | vLLM; two datasets; request-rate and output-length grid |
| Online rate | 200 | 1 | ~180 s sustained; 1–100 requests/s × 2 datasets; typically 1 replicate |

## Source reproduction

**PASS.** Five Llama 2-node jobs and one offline window regenerated with the authors' overlap-window linear interpolation.

Mean power and energy agreed to <0.05% (training) and <0.06% (offline). Native-timestamp `E_GPU+E_CPU` vs resampled total differed by <0.1%. Semantics reproduced; byte identity was not required.

## Physical bounds (paper Appendix A; idle/stress logs are **not** in the archive)

| Anchor | Value | Note |
|---|---|---|
| GPU idle | 72.5 ± 0.1 W/device | |
| CPU idle | 64.1 ± 4.8 W/socket | |
| Component idle | **418 W/node** | 4×72.5 + 2×64.1; DIPLOEE's 420 W is this sum, not AC |
| gpu-burn | 668.2 ± 1.4 W/device | after 150 s warmup; do not merge with HPL |
| CPU dense-matmul | 338.6 ± 1.0 W/socket | |
| HPL-NVIDIA | ~695 W/device regions | separate benchmark |
| Observed training GPU | mean **548 W/device** | NVML |
| Observed training CPU | mean **126 W/socket** | RAPL; far below 360 W TDP / 339 W stress |

CPU+GPU TDP envelope 3520 W is nameplate, not measured `P_node`.

## Batch-like energy

Primary quantity:

```
p_i = E_compute,i / (N_i × τ_i)     [W/node]
```

A high R² of `E` vs node-hours is not used for selection.

**Is one `p_h` enough?** Not across the full bank. It **is** enough for GPU-saturated 1–2 node jobs.

| Slice | mean p (W/node) | replicate / within-slice spread |
|---|---:|---|
| Llama LoRA N=2 | 2632 | std 11 (CV 0.4%) |
| SD N=2 | 2657 | std 15 (CV 0.6%) |
| Offline, batch ≤100 | 2169 | std 110 |
| Offline, batch >400 | 2747 | std 54 |
| Llama N=16 | 2402 | std 16 |
| SD N=16 | 2068 | std 150 |

Run-count-weighted universal mean (2660 W/node) is almost entirely the 1200 offline trials. Training-wide mean (2445 W/node) mixes node scales and should not be used as “the H100 wattage.”

**Node scale (weak scaling, not strong scaling):**

- Llama: monotone decline 2632 → 2402 W/node from N=2→16 (~10%), far larger than replicate CV (0.7%). Detectable, modest.
- SD: 2657 → 2068 W/node (~33%) with large replicate SD at N≥4. Consistent with the paper: evaluation-time fraction falls as global batch grows. Do not infer a smooth physical `p(N)` from four levels.

**Canonical batch object (CPU+GPU only):**

1. GPU-saturated default (1–2 node LLM fine-tune / large-batch offline):

```
E_compute = 2650 W/node × N × τ
```

2. Supported domain: the empirical table `p_{h,w}` (and for training `p_{h,w,N}`) in `H100_INTENSITY_BY_RUN.csv`. That is the minimum valid form for the full bank.

Leave-one-replicate-out MAPE on `E = p N τ` is ~5% when grouping by (workload, nodes). In-sample MAPE of M0/M1/M2 is similar (~5.4–5.6%) because offline n dominates; WAPE improves when training is not forced onto the offline mean.

Online inference is **not** in this equation.

## Online inference

Demand metadata that actually exist: request rate, prompt counts, input/output tokens, vLLM latency percentiles, concurrency fields where populated.

Supported proxy: **discrete measured scenarios** plus a monotone-then-saturating `P_compute(request_rate)` on one node. Spearman ρ(rate, P) is only 0.35–0.45 because power saturates near **50 requests/s**.

| Dataset | P(1/s) | P(10/s) | P(50/s) | P(100/s) |
|---|---:|---:|---:|---:|
| InstructCoder | 2070 | 2257 | 2862 | 2793 |
| MLPerf Llama-2 prompts | 2063 | 2170 | 2779 | 2747 |

Finite tests support energy/request and energy/token, but they are **configuration-dependent** (median ~88 J/request and ~0.25 J/token; ranges span several-fold). Not a universal law. No generic response surface was fit.

## Temporal characterization

Training peak/mean stays **~1.25 from 0.2 s through 5 min**. The structure is **phase-scale (minutes)**, not subsecond noise. Subsecond resolution does not change the facility representation; a 1-minute model still needs a peak factor or a template, not a flat `p`.

Sustained online-rate traces are nearly flat (PAR ~1.02–1.07). Offline/finite short windows can look more variable at coarse bins because the run is short.

Normalized templates `φ_w(t)` with mean 1 are built only for 2-node Llama and 2-node SD (alignable from t=0). Phases are **not** hand-labeled. Online inference is not forced onto a deterministic curve.

Finest resolution useful for the broader facility model: **1 minute with a training peak factor / template**; native 0.1–0.2 s is for measurement, not for ESIF-scale accounting.

## External sanity

- **Latif et al. IEEE Access 2025:** 8-GPU H100 HGX **full-node AC**, peak ~8.4 kW vs 10.2 kW rated. Different boundary and 8 vs 4 GPUs. NLR 4-GPU CPU+GPU means (~2.6–2.8 kW saturated) are physically compatible with a larger AC envelope. **Not calibrated.**
- **Patel et al. ASPLOS 2024:** qualitative production evidence — training nearer the ceiling, inference more headroom. Agrees directionally (online P rises with rate then saturates; training PAR is phase-driven).
- **TDP:** engineering bound only.

DIPLOEE traces in the archive are `SAME_SOURCE_SIMULATION`. Not independent validation. Not rerun.

## Kestrel job crosswalk

Exact Slurm ID match only. No timestamp/hash/user re-identification.

- Training: **41/41** `job_id` matches on `gpu-h100`, `hardware_branch=H100`, nodes identical. Profile duration is ~0.8% shorter than Slurm wallclock (overlap window). `energy_wh` is **null** for all matched jobs (confirms H100 job-record energy remains unmeasured in the Kestrel extract). 11 Llama jobs are Slurm `CANCELLED` but have complete measured profiles.
- Inference: metadata rows have no slurmid. Log banners give logging-job IDs 10720618, 11763012, 12146821. First two match 1-node `gpu-h100` CANCELLED jobs; **12146821 is not in the extract** (rate tests are 2026-01; extract catalog range ends 2025-12).
- Historical ~1.3M H100 jobs are **not** populated.

## Canonical objects for the project

**A. Batch-like compute energy (CPU+GPU):**

```
E_compute = p N τ
```

with `p = 2650 W/node` for GPU-saturated 1–2 node jobs, otherwise `p_{h,w}` / `p_{h,w,N}` from the measured table. Domain: Kestrel 4×H100 SXM 80 GB + 2×EPYC 9554. Not full-node AC.

**B. Online inference:** scenario table `P_compute(request_rate, dataset)` with saturation near 50 s⁻¹; energy/request and energy/token only as config-indexed finite-test values.

**C. Temporal library:** training 2-node `φ_w` templates (mean 1); peak/mean vs aggregation timescale; no universal H100 burst shape.

## Limitations

- CPU+GPU ≠ full-node AC.
- Controlled MLPerf/vLLM benchmarks ≠ production Kestrel H100 mix.
- Same-source DIPLOEE ≠ independent validation.
- AMD RAPL is the weaker measurement link.
- Do not assign these coefficients to anonymous historical H100 jobs.

## Status

See `results/FINAL_H100_POWER_STATUS.json`.

**Next experiment:** measure or bound `P_other_node` / full-node AC on a Kestrel H100 node. Do not populate historical H100 jobs until workload mapping exists. Do not fit ESIF cooling in this layer.
