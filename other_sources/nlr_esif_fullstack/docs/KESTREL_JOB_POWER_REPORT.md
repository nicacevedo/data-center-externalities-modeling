# Kestrel job IT energy and conditional ESIF IT-meter validation

Bounded experiment under `other_sources/nlr_esif_fullstack/`. Cooling, WUE, weather, HVAC, and GenAI high-frequency profiles were not used. Anonymized hashes were not used as predictors and were not re-identified. TDP energy is an engineering benchmark only.

## A. Source identity

| Dataset | DOI | Local file | Status |
|---|---|---|---|
| NLR HPC Kestrel Jobs Data | 10.7799/3023270 | `data_raw/esif.hpc.kestrel.job-anon.zip` | **LOCAL_EXISTING_VERIFIED** (catalog MD5 `8f1d3be1cbe6345ef45e658a783c2aa0` matches; SHA-256 `3a90f9ac40991712f8718c686fa7b05d7a303a44a87ed1a8f21b403c11efd26f`). Not redownloaded. |
| Datacard | same | `data_raw/datacard.md` | LOCAL_EXISTING_VERIFIED by schema identity |
| NLR HPC Facility PUE | 10.7799/3015212 | `data_raw/esif_pue/esif.influx.buildingData.PUE.combined.parquet` | **DOWNLOADED_MISSING_DATA** (IT parquet + README only; weather not downloaded) SHA-256 `19cd12405dde9144b1a360e8c8418666c399a3d0d15a7f846880d71ab22f9dd4` |

Kestrel extract: **10,559,977** parent job rows, 29 Hive Parquet members, submit months 2023-08 through 2025-12. Wallclock/CPU-time integers are **nanoseconds** / CPU-nanoseconds (verified against `end−start`).

## B. Measured energy target

Canonical target: **`consumed_energy_raw_watt_hours`** (Slurm `ConsumedEnergyRaw`, node-level power monitoring). `E_Wh = E_J / 3600` holds (0 mismatches > 1e-6; max abs error 2.9e-11 Wh).

Full-trace QA:

- null energy: 1,489,930 (14.1%)
- zero energy: 2,005,097 (19.0%)
- negative / nonfinite: 0
- positive energy: 7,064,950; total 2.394×10^10 Wh

**H100/GPU partitions (1,327,785 jobs, first start 2024-02-22): 0 jobs with positive measured energy** (1,161,754 null + 166,031 zero). H100 measured job-energy models are **UNSUPPORTED** in this public extract. TDP fields must not be substituted as ground truth.

TIMEOUT jobs carry **more measured energy than COMPLETED** (10.86 GWh vs 9.93 GWh). The frozen primary cohort is COMPLETED-only, so replay understates Kestrel IT relative to the facility meter. Large jobs were inspected, not trimmed; top jobs have ~700 Wh/node-hour, consistent with the typical CPU-node rate.

## C. Sharing / co-residency

Observed encoding (datacard + values):

- `shared_job_count = 0` ↔ empty `nodes_shared` / `jobs_shared` (explicitly no co-residents; self is **not** counted)
- `shared_job_count > 0` ↔ nonempty arrays; almost entirely `shared*` partitions
- `NULL` ↔ both arrays null; dominant on exclusive CPU partitions with nonempty nodelist

Median energy/node-hour is ~630 W on exclusive CPU (NULL or zero sharing) and ~690 W on shared-partition co-resident jobs. That is **not** a fractional node allocation. Summing shared jobs would likely **double-count node-level ConsumedEnergyRaw**.

**NON_SHARED_JOB (frozen):** exclusive CPU partition AND (`shared_job_count` IS NULL OR = 0).

## D. Primary cohort

COMPLETED, valid start/end, positive duration, positive finite measured energy, exclusive CPU partitions, NON_SHARED_JOB, valid requests.

- **n = 4,456,925** (42.2% of source rows)
- **9.282 GWh** (38.8% of all measured job energy in the extract)
- CPU only; H100 in primary = 0
- Dominant partitions: `standard`, `short`, `standard-stdby`, `long`

Hardware (NLR docs, not inferred from energy): CPU nodes = dual-socket Intel Sapphire Rapids, 104 cores, ~240–256 GB, 100% direct liquid cooling. H100 nodes = 4× H100 SXM 80 GB, AMD Genoa 128 cores, shareable; **not modeled here**.

## E. Chronological protocol

Split on `start_time` UTC, frozen from coverage/epochs **before** comparing model scores:

- DEV: start < 2025-01-01 (n = 2,013,738)
- VAL: 2025-01-01 ≤ start < 2025-07-01 (n = 1,308,441)
- TEST: start ≥ 2025-07-01 (n = 1,134,746), untouched

Primary metric: WAPE on Wh. Project parsimony: prefer the simpler model if validation WAPE is within 1% relative of the best.

## F. EX-POST (actual execution telemetry)

B0 `E = p × nodes_used × runtime_hours` with **p = 700.7 W per occupied CPU node** (dev OLS through origin).

| Model | VAL WAPE | notes |
|---|---|---|
| B0 node-hours | 0.1236 | selected |
| B1 node + CPU hours | 0.1232 | CPU-hour coefficient ~0 and slightly negative (collinear with full-node occupancy) |
| log-linear + partition | 0.1424 | |
| HGB log E (100k→2M) | 0.146→0.135 | log-scale R² better; **aggregate WAPE not better than B0** |
| B2 TDP-used (benchmark) | 0.239 | underestimates (−24% energy bias); not a predictor |

**Chronological test (B0):** WAPE **0.136**, MAE 285 Wh, total-energy bias **+3.1%**, R²(log E) **0.976**.

Unseen-user test WAPE 0.131; unseen-account 0.161 — resource–energy relationship is not an artifact of recurring hashes.

**Nonlinear ML does not materially improve EX-POST aggregate accuracy.** The physical node-hour model is the justified object.

## G. EX-ANTE (scheduler-visible only)

Permitted: partition, nodes/processors/memory requested, wallclock requested, QoS. Forbidden: actual runtime, utilization, energy, TDP, hashes.

Requested wallclock is a cap, not a duration forecast. B0 on requested node-hours has VAL WAPE **1.25** (over-prediction). The selected HGB still has test WAPE **0.919** and **−82%** total-energy bias.

**EX-ANTE is not suitable as a planning energy model** without a separate runtime model. Actual occupancy duration is the missing piece.

## H. Temporal replay

Uniform allocation of each primary-cohort job’s energy over actual `[start, end)`. Resolutions 5 min / 15 min / 1 h / 1 day. Energy conservation relative error ~10^−14 to 10^−16 at all four resolutions (measured, EX-POST predicted, EX-ANTE predicted).

This is **time-averaged job-attributed power**, not instantaneous node telemetry, and it excludes GPU energy, TIMEOUT energy, shared-partition jobs, and idle nodes. Finest defensible resolution for *this* replay is 5 min for conservation; scientific content vs the facility meter is similar from 5 min through hourly (see ESIF table). Daily aggregation raises R² by averaging noise.

## I. Conditional ESIF IT-meter linkage

Overlap is sufficient: ESIF `it_power_kw` ~60 s cadence, 2016-06-12 to 2025-08-29 UTC after localizing naive timestamps as **America/Denver** (predeclared; catalog does not state offset). Kestrel overlap 2023-08-10 to 2025-08-29, n ≈ 1.04e6 meter points.

Meter boundary (DOI 10.7799/3015212 + NLR ops docs): `it_power_kw` is **all IT on the ESIF floor**, not Σ Kestrel jobs. Eagle compute decommissioned **2024-06-15**. GPU nodes exist on the meter after 2024 but contribute **zero** job-energy in this extract. Idle nodes, storage, network, login/service remain.

Model: `P_ESIF_IT(t) = B + β P_Kestrel_CPU_jobs(t) + ε`. Equality (`B=0`, `β=1`) is not the target.

| Resolution | Epoch | Pearson | R² | B (kW) | β |
|---|---|---|---|---|---|
| 1 h | all | 0.33 | 0.11 | 2287 | 0.74 |
| 1 h | eagle_coexist | 0.58 | 0.34 | 2475 | 1.49 |
| 1 h | post_eagle_pre_gpu_ga | 0.18 | 0.03 | 2421 | 0.21 |
| 1 h | post_gpu_ga | 0.51 | 0.26 | 1991 | 0.86 |
| 1 day | post_gpu_ga | 0.61 | 0.37 | 1831 | 1.14 |
| 1 day | eagle_coexist | 0.69 | 0.47 | 2208 | 2.01 |

Low-job intervals: ESIF IT still ≈ **1390 kW** mean while Kestrel completed-CPU replay ≈ 0. Regression intercepts ~1.8–2.5 MW are the residual IT baseline.

In the overlap window, completed-CPU job replay is ~7.7 GWh vs ~38.8 GWh ESIF IT (~20%). Exact equality is not expected.

## J. Capability statuses

| Status | Result |
|---|---|
| JOB_ENERGY_TARGET_QUALITY | **PARTIAL** (CPU measured energy is internally consistent; GPU energy is entirely missing; TIMEOUT holds a large energy share) |
| JOB_ENERGY_EX_POST | **PASS** |
| JOB_ENERGY_EX_ANTE | **FAIL** (for planning totals; requested wallclock is not runtime) |
| TEMPORAL_JOB_POWER_REPLAY | **PASS** |
| ESIF_IT_METER_LINKAGE | **PARTIAL** (real incremental association after Eagle; not majority reconstruction) |
| H100_MEASURED_ENERGY | **UNSUPPORTED** |

## K. Canonical project implication

1. **Workload/resource → IT energy (CPU):** \(\hat E_j = 701\,\mathrm{W} \times N_{\mathrm{nodes},j} \times t_{\mathrm{runtime},j}\) with chronological test WAPE 13.6% and +3% energy bias. Optional partition intercepts are unnecessary at the 1% parsimony rule.
2. **Inputs:** actual nodes occupied and actual runtime (EX-POST). Partition is optional. Do not use measured energy, TDP energy, hashes, or post-execution efficiency as inputs to this proxy.
3. **Uncertainty:** ~14% WAPE job-level; ~3% aggregate energy bias on later-2025 test; higher error in the far tail (RMSE 1.6 kWh vs MAE 0.29 kWh).
4. **CPU and H100 must remain separate.** H100 measured job energy is missing from this extract.
5. **Form is generic** (`E ≈ p_{\mathrm{node}} × \mathrm{node\text{-}hours}`); **coefficient is Kestrel-CPU-specific** (~701 W, matching dual Sapphire Rapids-class occupancy). Do not export 701 W to GPU or hyperscale CPU nodes.
6. **ESIF does provide meaningful workload → facility-IT validation of incremental load**, not a reconstruction of the IT meter. Baseline ~1.4–2.5 MW is other/idle/GPU/unreplayed energy.
7. **Highest-value next experiment:** recover **GPU/node-level measured power** (or wait for an extract where `ConsumedEnergyRaw` is populated on `gpu-h100`). Until GPU IT is in the job layer, ESIF IT → cooling/weather will confound missing GPU load with cooling response. GenAI sub-hourly profiles are second-priority (shape, not missing totals). Google hyperscale is the right later test of generality of the node-hour form.

Suggested commit message (not committed): `Add NLR Kestrel job-energy EX-POST node-hour model and conditional ESIF IT-meter linkage.`
