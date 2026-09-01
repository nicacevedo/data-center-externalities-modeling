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

This is **time-averaged job-attributed energy replay**, not instantaneous node telemetry. Energy conservation at 5-minute bins **does not** validate 5-minute physical power shape.

- daily energy accounting: supported
- hourly average replay: useful/supported for aggregate comparison
- 15-minute replay: scenario/accounting approximation
- 5-minute physical transient shape: **UNSUPPORTED**
- instantaneous/burst shape: **UNSUPPORTED** (GenAI/H100 profiles are the appropriate source)

The original primary replay covers completed exclusive non-shared CPU only. Replay v2 (below) adds TIMEOUT and CANCELLED where transfer tests passed. Both remain accounting allocations. They exclude shared-partition jobs, H100, FAILED/NODE_FAIL/OOM, and idle nodes.

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
| JOB_ENERGY_TARGET_QUALITY | **PARTIAL** (CPU measured energy is internally consistent; GPU energy is entirely missing) |
| JOB_ENERGY_EX_POST | **PASS** |
| JOB_ENERGY_EX_ANTE | **FAIL** (requested wallclock is not runtime; not retuned) |
| CPU_COMPLETED_NODE_HOUR | **PASS** |
| CPU_TIMEOUT_TRANSFER | **PASS** |
| CPU_OTHER_STATE_TRANSFER | **PARTIAL** (CANCELLED PASS; FAILED/NODE_FAIL/OOM FAIL) |
| SHARED_CPU_RECONSTRUCTION | **UNSUPPORTED** |
| CPU_ENERGY_COVERAGE | **PARTIAL** (~89% of positive measured job energy in the validated exclusive/non-shared CPU law) |
| ENERGY_CONSERVING_JOB_REPLAY | **PASS** (accounting conservation, not physical 5-minute shape) |
| SUBHOURLY_POWER_SHAPE | **UNSUPPORTED** |
| TEMPORAL_JOB_POWER_REPLAY | **PASS** as energy-conserving job replay; **UNSUPPORTED** as subhourly physical shape |
| ESIF_TIMESTAMP_SEMANTICS | **AMBIGUOUS** (calendar-consistent with June 2025 power outage; Denver vs UTC hour-of-day unresolved) |
| ESIF_IT_METER_LINKAGE | **PARTIAL** (association improves with coverage expansion; not causal; not meter equality) |
| H100_MEASURED_JOB_ENERGY | **UNSUPPORTED_IN_KESTREL_JOB_EXTRACT** |

## K. Canonical project implication

1. **Workload/resource → IT energy (CPU, validated domain):** \(E^{IT}_{j,\mathrm{CPU}} = p_{\mathrm{KestrelCPU}} N_j \tau_j \epsilon_j\) with \(p_{\mathrm{KestrelCPU}}=700.6894574294788\,\mathrm{W/node}\) on exclusive non-shared Kestrel CPU jobs in COMPLETED, TIMEOUT, and CANCELLED, using actual occupied nodes and actual runtime. Chronological completed TEST: WAPE 0.136 (diagnostic), aggregate energy bias **+3.1%**. TIMEOUT transfer: WAPE 0.100, bias **−1.2%**. Optional partition intercepts remain unnecessary at the 1% parsimony rule.
2. **Inputs:** actual nodes occupied and actual runtime (EX-POST). Partition is optional. Do not use measured energy, TDP energy, hashes, or post-execution efficiency as inputs to this proxy.
3. **Uncertainty:** point coefficient \(\approx 700.689\) W/node; aggregate completed-TEST energy bias \(\approx +3\%\); held-out residual multiplier \(\epsilon=E_{\mathrm{obs}}/(p N t)\) has median 0.879 and p05–p95 \([0.445, 1.097]\). **WAPE (0.136 on completed TEST) is an aggregate diagnostic, not a confidence interval or “~14% job-level uncertainty.”** RMSE 1.6 kWh vs MAE 0.29 kWh shows a heavy right tail.
4. **CPU and H100 must remain separate.** H100 measured job energy is missing from this extract (`H100_MEASURED_JOB_ENERGY = UNSUPPORTED_IN_KESTREL_JOB_EXTRACT`). Do not apply 700.689 W/node to H100 or substitute TDP.
5. **Form is generic** (`E \propto` hardware-hours); **coefficient is Kestrel-CPU-specific**. Do not export 701 W to GPU or hyperscale CPU nodes until externally validated.
6. **ESIF:** Kestrel validated CPU job-attributed load is associated with a measurable component of ESIF total IT variation. This is **not** a causal claim that CPU jobs explain a percentage of facility IT. Baseline intercepts remain other/idle/GPU/unreplayed energy. Naive timestamps are calendar-consistent with the June 2025 ESIF power outage; Denver vs UTC hour-of-day remains **AMBIGUOUS**.
7. **Highest-value next experiment:** NLR GenAI H100 measured power profiles, DOI `10.7799/3025227` (not executed in this pass). Shared-CPU reconstruction is unsupported and should not block that experiment.

Suggested commit message (not committed): `Add NLR Kestrel job-energy EX-POST node-hour model and conditional ESIF IT-meter linkage.`

---

# CPU-coverage and ESIF-closure addendum

Closure pass on frozen completed-job coefficient **p = 700.6894574294788 W/node**. No refit.

## TIMEOUT transfer

n = 362,521; measured **10.326 GWh** (95.1% of all TIMEOUT measured energy).

WAPE = 0.1004; bias = -0.0123; R²(log E) = 0.9648.
Median W/node-hour = 738.4 (p05=302.1, p95=777.2).

COMPLETED frozen TEST: WAPE 0.1362, bias 0.0308, median W/node-hour 615.6.

**PASS_TRANSFER.** Median W/node-hour=738.4 vs p=700.7 (relative 0.054); |bias|=0.012; WAPE ratio vs completed test=0.738; R²(log E)=0.965. Same physical occupancy law; no refit.

## Coverage

Validated exclusive/non-shared CPU energy now represented by the frozen law: **21.295 GWh** of 23.939 GWh positive measured job energy (**89.0%**). Shared raw sums are **not** included. H100 measured energy remains 0. Of the 3.035 GWh in other exclusive states, only CANCELLED (1.687 GWh) transferred; FAILED/NODE_FAIL/OOM did not.

Shared reconstruction: **UNSUPPORTED**.

## Canonical CPU domain

\(E^{IT}_{j,CPU} = p_{\rm KestrelCPU} N_j \tau_j \epsilon_j\) with \(p_{\rm KestrelCPU}=700.6894574294788\,\mathrm{W/node}\).

Domain: Kestrel CPU nodes; actual occupied nodes; actual runtime; exclusive/non-shared jobs; TIMEOUT (and other states only if listed as validated). Not H100. Not shared jobs. Form \(E\propto\)hardware-hours may transfer; **p is Kestrel-CPU-specific**.

Planning: \(\hat E_j = p_h N_j \hat\tau_j\). Requested wallclock is not \(\hat\tau\). No new EX-ANTE energy model in this pass.

## Uncertainty

Held-out completed TEST residual multiplier \(\epsilon = E_{\rm obs}/(p N t)\): median 0.879; p05–p95 [0.445, 1.097]. Aggregate test bias 0.031. **WAPE is a diagnostic, not a CI.** Duration split of median ε is 0.806 vs 0.899; unconditional distribution is preferred unless that split is large.

## Temporal replay

Energy-conserving job replay is an accounting allocation, not 5-minute physical power shape.

- daily energy accounting: supported
- hourly average: useful for aggregate comparison
- 15-minute: scenario/accounting approximation
- 5-minute physical transients: **UNSUPPORTED**
- instantaneous/burst: **UNSUPPORTED** (GenAI/H100 profiles)

Replay v2 built: True.

## ESIF time

Disposition: **AMBIGUOUS** at hour-of-day (Denver vs UTC not uniquely identified). Naive IT has a **96.8 h dropout** after 2025-06-26 17:08 resuming 2025-06-30 17:57, matching the documented ESIF full power outage; IT recovers by 2025-07-03. The July 11–13 network outage (power on) shows no IT collapse. Daily linkage remains usable; hourly retains a ±6–7 h caveat. Offset was not chosen by maximizing Kestrel correlation.

## ESIF linkage

Rerun justified because replay v2 materially increased represented Kestrel CPU energy. Timezone interpretation did **not** change (still operational America/Denver with hourly caveat).

Kestrel validated CPU job-attributed load is associated with a measurable component of ESIF total IT variation. This is **not** a causal statement that CPU jobs explain a share of facility IT. Omitted H100, idle, storage, network, and other systems remain possible correlated loads.

| Resolution | Epoch | Replay | Pearson | R² | B (kW) | β | Kestrel/ESIF energy |
|---|---|---|---|---|---|---|---|
| 1 h | post_gpu_ga | completed-only (v1) | 0.51 | 0.26 | 1991 | 0.86 | 0.22 |
| 1 h | post_gpu_ga | validated CPU v2 | 0.82 | 0.67 | 1320 | 0.93 | 0.50 |
| 1 day | post_gpu_ga | completed-only (v1) | 0.61 | 0.37 | 1831 | 1.14 | 0.22 |
| 1 day | post_gpu_ga | validated CPU v2 | 0.88 | 0.77 | 1216 | 1.02 | 0.49 |
| 1 h | all | validated CPU v2 | 0.50 | 0.25 | 1831 | 0.73 | 0.43 |

v1 completed-only post-GPU Kestrel share uses 4.80 GWh replay / 21.47 GWh ESIF IT in that hourly epoch. v2 uses 10.67 GWh / 21.47 GWh.

H100 measured job energy: **UNSUPPORTED_IN_KESTREL_JOB_EXTRACT**. Do not apply 700.689 W/node to H100. Next separate experiment: NLR GenAI H100 measured power profiles, DOI `10.7799/3025227` (not executed).
