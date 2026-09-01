# Compute/workload → IT power: source audit and smallest experiment

M100 is closed/frozen. This stage maps **workload / utilization / hardware state → node or system IT power**. It does not fit cooling, water, or a large black-box model.

M100 is used only as a **node-sum ↔ facility-IT boundary** result (hourly HQ node `total_power` sum vs canonical `Tot_ict`). Median `P_nodes / Tot_ict` on overlapping 2021 months is about **0.74–0.81**, with high correlation and a systematic level offset. That offset is a **meter-boundary residual**, not a PSU-efficiency parameter.

## Source audit

### 1. NLR GenAI Power Profiles

| Item | Documented fact |
| --- | --- |
| Identity | Vercellino et al., *Measurement of Generative AI Workload Power Profiles…*, arXiv:2604.07345; dataset DOI [10.7799/3025227](https://doi.org/10.7799/3025227) (OSTI/DOE) |
| Hardware | NLR Kestrel GPU nodes: **4× NVIDIA H100 SXM 80 GB**, 2× AMD EPYC 9554 (128 cores), HPE Slingshot-11 |
| Workloads | MLCommons **Llama-2 70B fine-tune** and **Stable Diffusion v2 train**; **vLLM Llama-3 70B** inference. Node counts **1–16** (training/fine-tune) |
| Variables / units | Time-resolved **GPU power (NVML, W or mW in WattAMeter logs)**; **CPU RAPL energy (µJ) → W**; GPU temperature (°C). Metadata: job type, node count, prompts / max tokens for inference |
| Sampling | **0.1 s** (10 Hz); dataset text also mentions 5/10 Hz (0.2/0.1 s) |
| Measurement boundary | **On-node device telemetry** (NVML + RAPL), not rack PDU and not facility `Tot_ict`. Whole-facility traces in the package are **DIPLOEE simulated scale-up**, not measured facility power |
| Access / size | Public OSTI dataset; landing page does not state a single archive byte size. Paper + CSV/parquet traces; expect at least hundreds of MB if all instantaneous files are fetched |
| What it can identify | Multi-node **job-level IT power profiles** vs workload class and scale; idle vs active shape; **not** a generic utilization regression unless NVML/RAPL series are aligned to utilization (utilization is not the primary published table) |
| What it cannot | Facility cooling/PUE; independent validation of M100; B200; wall-plug vs NVML gap without extra meters |

### 2. 2026 H100/B200 Scientific Data dataset

| Item | Documented fact |
| --- | --- |
| Identity | Elsayed, Al-Obaidi, Farag, *Sci Data* (2026) [10.1038/s41597-026-07496-6](https://doi.org/10.1038/s41597-026-07496-6); companion [figshare 10.6084/m9.figshare.31654879](https://doi.org/10.6084/m9.figshare.31654879) |
| Hardware | **8× H100 SXM 80 GB** and **8× B200 180 GB** Lambda Cloud nodes; plus **40 sessions on RTX 3060 12 GB** (desktop) |
| Workloads | **32** node-scale + **40** single-machine **15-minute** training sessions: forecasting, classification, RL, text and image generation |
| Variables / units | GPU utilization (% SM active); GPU/CPU **power (W)**; GPU memory utilization; temperature (°C); CPU usage/utilization. Node-scale: **per-GPU** power and utilization |
| Sampling | Paper: **50 Hz (20 ms)** on node-scale; figshare: **100 ms** single-machine, **20 ms** multi-GPU. Use the file timestamps, not a single headline rate |
| Measurement boundary | **Device/node telemetry** on a cloud VM (Lambda Stack). Not a certified analyzer at the PSU; not facility IT. Desktop 3060 is not a datacenter node |
| Access / size | Open figshare + GitHub codes. **>1.8e6 samples**; figshare page does not quote a total GB figure. Compact relative to multi-day facility traces |
| What it can identify | **P_device or P_node ≈ f(GPU util, memory util, GPU generation, workload family)** including H100 vs B200 at matched 8-GPU form factor |
| What it cannot | Multi-rack fabric power; inference serving at MLPerf quality targets; M100-style facility `Tot_ict` |

### 3. MLPerf Power

| Item | Documented fact |
| --- | --- |
| Identity | MLCommons Power (inference + limited training). Framework paper: Tschand et al., arXiv:2410.12032. Rules: `mlcommons/inference_policies` `power_measurement.adoc`. Results: `mlcommons/inference_results_v*` and training results repos |
| Hardware / workloads | Submitter **systems under test**: datacenter GPUs (including H100 MaxQ/MaxP), edge, tiny. Closed models (ResNet, BERT, GPT-J/Llama, DLRM, RetinaNet, …) at required quality |
| Variables / units | Run energy (J) and average power (W) over the timed LoadGen window; samples/J; system description. Logs: `spl.txt` analyzer samples when PTDaemon is used |
| Sampling | Analyzer/telemetry during the **timed performance window** (often ~1 Hz collated; vendor telemetry varies). Not a 10–50 Hz utilization campaign |
| Measurement boundary | **System / node** (PSU DC or AC analyzer, or IPMI/Redfish; PDU only if all nodes on the PDU are in the job). Interconnect may be estimated. **Cooling attribution is inconsistent** (node fans in, facility liquid often out) — do not use MLPerf Power as a cooling model |
| Access / size | Public GitHub result trees; PTDaemon binary is **EULA/private**. Full clone of a results repo is typically **hundreds of MB to a few GB**, not a single curated parquet. Start from published tables + a few power-log directories |
| What it can identify | **Wall-ish system IT power at a quality/throughput operating point** across vendors and GPU generations; MaxQ vs MaxP |
| What it cannot | Continuous util→power curves; training-from-scratch energy except the small training-power subset; facility IT meter translation |

## Complementarity (why all three)

| Question | Best source | Role of others |
| --- | --- | --- |
| Does GPU util / memory explain node IT power on modern accelerators? | Scientific Data H100/B200 | NLR checks multi-node job shape; MLPerf checks system-boundary level |
| How do training vs inference vs scale change the **profile**? | NLR 0.1 s jobs, 1–16 nodes | Sci. Data is 15 min sessions; MLPerf is a point estimate |
| What is **system** IT power, not NVML GPU power? | MLPerf Power | Sci. Data / NLR are mostly device telemetry |
| How would node IT sit under a **facility IT** meter? | Frozen M100 node→`Tot_ict` residual | None of the three is a facility ICT meter |

Do **not** use NLR DIPLOEE whole-facility series as measured truth. Do **not** transfer M100 cooling or PUE.

## Smallest complementary experiment (no large model)

**Target.** A reduced-order map

`P_IT,node(t) = a_h + b_h · u_GPU(t) + c_h · u_mem(t) + d_h · P_GPU,sum(t)  [optional]`

with **hardware class** `h ∈ {H100-8, B200-8, H100-4 NLR, desktop-3060}` estimated separately, plus a **system-boundary correction** from MLPerf (node/SUT power vs implied GPU power) and an **ICT-meter translation** from M100 (`P_facility_IT ≈ P_nodes / r` with `r` the frozen median ratio band 0.74–0.81, reported as a range not a calibrated efficiency).

**Design (predeclared).**

1. **Ingest only.** Scientific Data 15-minute sessions (downsample to 1 s). NLR traces downsample to 1 s. MLPerf: one recent datacenter power table (H100 and, if present, B200/Blackwell), average power and energy, no PTDaemon reverse-engineering.
2. **Nested identification, chronological or session holdout — not a DNN.**  
   - M0: hardware-class idle/mean power.  
   - M1: M0 + GPU utilization.  
   - M2: M1 + memory utilization.  
   Stop if M1 already explains most 1 s MAE; do not add cooling, fans, or weather.
3. **Holdouts.** (i) leave-one-workload-family-out on Scientific Data; (ii) H100-trained, B200-tested (and reverse) to see whether a generic modern-AI map exists across generations; (iii) NLR multi-node mean power vs 4× single-node expectation (communication tax, not a fabric model).
4. **Boundary stack, explicit.** GPU-NVML → node IT (MLPerf / PSU if available) → facility IT (M100 residual band). Each step keeps its own error; do not collapse into one “PSU efficiency.”
5. **Out of scope.** Cooling, water, PUE, control, large-model training, coefficient transfer from M100 facility W1/W2.

**Success criterion.** Whether a **generic** util→IT-power map is supported across H100/B200 and workload families at 1 s, and how large the **boundary gaps** (device vs SUT vs facility ICT) remain. If B200 holdout fails, the honest conclusion is hardware-class maps, not one global curve.

**First download.** Figshare 31654879 + OSTI 3025227 metadata/file list (confirm GB before pulling instantaneous dumps) + MLPerf inference results CSV/tables for the latest public power-capable version. No cooling datasets.


## CLOSURE UPDATE (do not execute obsolete plan as written)

NLR GenAI H100 compute is now frozen with `p_{w,N}`. The 2026 Sci. Data H100/B200 set was used only to test workload/util transfer, not as a second primary H100 model. RTX 3060 was not processed. MLPerf was not cloned. The util→IT-power nested M0/M1 map is **hardware-class specific**; H100→B200 transfer **fails**. Public 8-GPU AC data provide an EXTERNAL envelope only. Kestrel full-node AC is still missing; see `NLR_H100_FULL_NODE_DATA_REQUEST.md`. Do not use M100 0.74–0.81 as a PSU efficiency. Next layer is ESIF cooling, not more H100 job population.
