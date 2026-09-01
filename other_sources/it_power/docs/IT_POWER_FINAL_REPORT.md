# IT-power layer final report

## A. Repository / freeze scope

CPU remains `FROZEN_PASS_WITH_DOMAIN_RESTRICTIONS` at 0.7007 kW/node and was **not** refit.
H100 compute is `FROZEN_PASS_WITH_DOMAIN_RESTRICTIONS`.
IT-power layer disposition: `FROZEN_BOUNDED_WITH_EXPLICIT_NODE_UNCERTAINTY`.
Same-system node bridge was **not** run (Kestrel node AC telemetry not present in this repository).

## B. H100 compute freeze

Measurement boundary: `P_compute = P_GPU_NVML + P_CPU_RAPL` (not full-node AC).

Canonical batch object:

`E_compute = p_{w,N} * N * tau`

using `analysis/H100_P_W_N_TABLE.csv`. Author-supplied training runs: 41. Experimental unit = independent run, not a time sample.

### SD N=1 (`RAW_RECONSTRUCTED_SOURCE_RUN`)

n = 5; mean duration 24729 s; mean GPU energy 16964 Wh; mean CPU (source package+core) 1629 Wh; mean compute energy 18593 Wh; mean 2706.7 W/node (std 8.8, CV 0.0032). These 1-node Stable Diffusion runs sit in the same high-intensity band as Llama/SD N=2 (~2630–2660 W/node). They are **not** author-supplied aggregates.

### RAPL

Source reproduction keeps package+core. Preferred physical CPU is package only. Median core fraction of CPU energy 0.0032; median share of CPU+GPU compute energy 0.00034; median source−package difference 3.3452336636935223 W. Models were **not** refit.

### 2650 W/node

Retained only as `SATURATED_COMPUTE_SCENARIO_ANCHOR` for **ex-ante** training `llama2_70b_lora` or `stable_diffusion` with N≤2 (workload + node count, not observed watts). n=16, mean 2664.6 W/node, rounded illustration 2650 W/node. Not a universal H100 default and not a predictive shortcut.

### Temporal

`PAR_{workload,node_count,resolution}` at native / 1 s / 10 s / 60 s / 5 min where run length supports it. No universal training PAR≈1.25. Alignable templates remain 2-node Llama and SD only.

Online inference remains a discrete measured scenario library, not a general response model.

## C. Independent H100/B200 (Elsayed et al.)

16 H100 + 16 B200 sessions (unit = session, not 20 ms samples). RTX 3060 skipped. CPU power columns empty. Boundary: sum of 8 pynvml GPU powers, not node AC.

H100 session-mean GPU-sum: LLM 3717 W vs diffusion 1995 W. B200: LLM 4712 W vs diffusion 3165 W. Workload family changes power on both platforms (qualitative replication of NLR).

H100 M0 MAE 1025 W (WAPE 0.346); M1 util MAE 691 W (WAPE 0.233). Leave-one-family-out WAPE: diffusion 0.530, LLM 0.419. Leave-one-session-out M1 MAE 777.5122908539508.

M2 memory was run because M1 residual vs memory util corr=0.7543747042172781. M2 is a diagnostic, not a project H100 model.

H100→B200 WAPE 0.309; B200→H100 WAPE 0.435. Transfer **not** supported. Coefficients were not silently reused.

## D–E. Full-node bank / Newkirk

Preferred Newkirk specification (Table 3, architecture-specific asymptotic): Pidle=1.86 kW, α=5.11, β_LLM=6.89 kW, β_CNN=6.28 kW, cap 8.4 kW. Published energy MAPE 11.1% in-sample / **5.39%** OOS on four named workloads. This module's runtype-mean tot_power MAPE is 0.175 (in) / 0.139 (test export). Those are different metrics; 5.39% is not claimed as reproduced. BNL rows are the Latif campaign — one lineage.

Cooling Matters: liquid vs air ~1–1.5 kW on 8×H100; distinct campaign. GitHub raw data not retrieved.

Public 8-GPU AC context (Latif/Newkirk, EXTERNAL): idle/rated=0.182; loaded Llama median/rated=0.776; peak stress/rated=0.831; incremental (loaded−idle)/GPU=758 W.

## F. Component→node

`KESTREL_H100_FULL_NODE = PARTIAL_EXTERNAL_ENVELOPE`.

Lower bound only: `P_node >= P_compute`. Upper bound for the 4-GPU Kestrel node is **not identified**. Envelope labeled EXTERNAL/CROSS-SYSTEM, not KESTREL_CALIBRATED. 8-GPU numbers were not halved. P_other_node remains UNCERTAIN.

## G. MLPerf

`NO_CLEAN_MLPERF_COMPARATOR`.

## H. Kestrel request

46 exact job windows in `NLR_H100_FULL_NODE_REQUEST_WINDOWS.csv`. Do not send automatically.

## I. Canonical IT objects

- CPU: `E = 0.7007 kW/node * N * tau` (frozen exclusive Kestrel CPU domain)
- H100 batch compute: `p_{w,N}` table, CPU+GPU boundary
- H100 online: discrete `P_compute(rate, config)`
- H100 temporal: PAR table / 2-node templates
- H100 node: P_other UNCERTAIN + external 8-GPU ratios
- Facility IT: sum of nodes + other IT; M100 residual is a meter boundary, not a PSU coefficient

## J. Status

See `analysis/FINAL_IT_POWER_STATUS.json`.

## K. Next (not executed)

Facility IT + weather → cooling/HVAC/pump using ESIF measured components.
