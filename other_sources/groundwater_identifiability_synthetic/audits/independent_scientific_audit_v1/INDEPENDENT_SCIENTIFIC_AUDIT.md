# Independent Scientific Audit — Frozen Synthetic Groundwater Identifiability Sweep

**Scope.** Read-only mechanism audit of the completed known-truth sweep. The preregistered
statuses `LOCAL_RESPONSE_STATUS = LOCAL_RESPONSE_NOT_IDENTIFIED` and
`NETWORK_SUPPORT_FINAL = NOT_EARNED` are treated as frozen. Nothing below rewrites them.

**Labelling convention used throughout.**

- `CONFIRMATORY FROZEN RESULT` — a preregistered gate outcome, reproduced independently.
- `POST-HOC MECHANISM DIAGNOSTIC` — explanatory analysis of already-stored quantities. Never
  a pass/fail determination.

**Auditor artefacts.** All scratch code and tables live in `/tmp/sgi_independent_audit/`
(`00_verify_hashes.py`, `01_reproduce_gates.py`, `02_cell_surface.py`,
`03_local_mechanism.py`, `04_eiv_decomposition.py`, `05_s8_s6_network.py`,
`06_ranking_and_decision_table.py`, plus their outputs). No repository file was modified.

---

## A. Provenance verification

`CONFIRMATORY` — every invariant was recomputed from first principles, not read from the
existing audit note. The hashing rules were re-implemented in scratch code from the
definitions in `src/design.py` rather than by importing that module, so a defect in the
frozen hashing helper would have surfaced as a mismatch.

| item | expected | independently recomputed | verdict |
|---|---|---|---|
| Valid ANALYSIS execution commit | `8782efb75f5cf31cbbdabc9291c33d89de9eb9c2` | matches `SWEEP_MANIFEST.json.feature_commit` | OK |
| Current branch tip (HEAD) | — | `347d88c5778a1130fad42ffcf12820e7dde4eee6` | OK |
| `main` / `origin/main` | — | `84c4c81e7a4927ca36e95200dfb957f4e9014378` (identical) | OK, not merged |
| `DESIGN_HASH` | `b53f5594…e20a8a5` | `b53f5594a444ae4826adfe2c47818080508a4c4b00a38fa25b4ffc483e20a8a5` | OK |
| `CODE_HASH` | `7cc64809…f00d863c` | `7cc64809bf240d7afea164c9a24a737c75de88a0b5e8d38f4e85b704f00d863c` | OK |
| ANALYSIS seed-pool hash | `bd6db2aa…cb689015` | `bd6db2aac7743cc83d5d5ecd8b5f07fefe18747649e3489a5b89e7e0cb689015` | OK |
| ANALYSIS seed list (60 uint64) | — | regenerated from `SeedSequence(entropy)`; element-wise identical | OK |
| Expected cells / replicates | 129 / 7740 | 129 cells, 7740 records, 7740 unique `(cell_id, seed)`, 0 duplicates, 60 per cell | OK |
| Seed-pool disjointness | G0/SMOKE/CALIBRATION excluded | `source_pool` is `ANALYSIS` on all 7740; `smoke` False on all 7740 | OK |
| Code manifest (`CODE_MANIFEST_V2.csv`) | 30 files | 30/30 SHA-256 match the working tree | OK |
| Output integrity (`ANALYSIS_OUTPUT_HASHES.csv`) | — | 24/24 artefacts present, all SHA-256 match | OK |
| `n_code_files` | 30 | 30 | OK |
| CALIBRATION / G0 / SMOKE pool hashes | — | all three regenerate identically | OK |

**Estimability accounting.** 829 `NOT_ESTIMABLE` network rows and 15 `NOT_ESTIMABLE` local
rows are retained in the file; 0 local `FIT_FAILED`. These match the post-sweep note's
counts and are carried into every aggregate rather than dropped.

**Results-preservation step (task section 2).** No preservation commit was required or made.
The canonical substantive artefacts were already committed at HEAD. `git diff 8782efb 347d88c`
shows 26 added files, **all** of them generated ANALYSIS outputs, figures, the provenance
audit and the output-hash manifest; **zero** files under `src/`, `scripts/`, `tests/`, or
`config/` differ. `git status --porcelain` for the module is empty. The only working-tree
entries are the pre-existing dirty gitlink `Data-center-PUE-prediction-tool` and the untracked
`pscc_m0_handoff/`; both were left untouched.

**One reporting inconsistency (not a scientific discrepancy).** In
`outputs/analysis/gate_results.csv` the six G3 cells are rendered with `pass=True`,
`state=ESTIMATED_PASSED_GATE`, `support_status=SUPPORTED`, and the file contains no
`SGI_G3` row at all. That column reflects per-cell estimability/metrics, not the
falsification triggers, and the authoritative
`FINAL_SYNTHETIC_IDENTIFIABILITY_STATUS.json` correctly records
`SGI_G3.hard_failure = true`. The final `NETWORK_SUPPORT_FINAL / NOT_EARNED` row in the CSV
does carry the correct outcome. Still, a reader consulting only `gate_results.csv` would
conclude that G3 passed. Worth fixing in presentation before the paper; it changes nothing
about the frozen result.

---

## B. Independent gate reproduction

`CONFIRMATORY` — recomputed from `sweep_replicates.csv` with aggregation rules re-read from
`config/design_v2.yaml` and re-implemented in scratch code (`01_reproduce_gates.py`).
`src/summarize.py` was deliberately **not** imported.

### SGI_G1 (local response support, evaluated model `L`, threshold 0.20)

| cell | n | est. rate | median NIRE h26 (L) | q10 | q90 | threshold | pass | sign crit. | rmse/B0 crit. |
|---|---|---|---|---|---|---|---|---|---|
| G1R1 | 60 | 1.000 | **0.564834** | 0.349 | 0.721 | 0.20 | FAIL | 1.000 (pass) | 0.834 (pass) |
| G1R2 | 60 | 1.000 | **0.530328** | 0.396 | 0.694 | 0.20 | FAIL | 1.000 (pass) | 0.941 (pass) |
| G1R3 | 60 | 1.000 | **0.571730** | 0.389 | 0.758 | 0.20 | FAIL | 1.000 (pass) | 0.879 (pass) |
| G1R4 | 60 | 1.000 | **0.546377** | 0.361 | 0.693 | 0.20 | FAIL | 1.000 (pass) | 0.816 (pass) |
| G1R5 | 60 | 1.000 | **0.541081** | 0.312 | 0.721 | 0.20 | FAIL | 1.000 (pass) | 0.895 (pass) |
| G1R6 | 60 | 1.000 | **0.849710** | 0.779 | 0.908 | 0.20 | FAIL | 1.000 (pass) | 0.802 (pass) |

Reproduces the reported 0.565 / 0.530 / 0.572 / 0.546 / 0.541 / 0.850 exactly. Every cell
fails on `G1_intervention` **and only** on `G1_intervention`. The sign criterion is perfect
(100% of replicates estimate a drawdown-signed pumping coefficient), no stability blow-ups
occur, and the local model beats the naive baseline on one-step RMSE in every cell. The
failure is specific to counterfactual intervention recovery.

### SGI_G2 (network complexity support, evaluated model `N`)

| cell | regime | scenario/topology | edge F1 (thr 0.80) | precision | recall | NIRE_N | NIRE_L | best simple | gain (thr 0.10) | masked/observed (thr 1.5) | pass |
|---|---|---|---|---|---|---|---|---|---|---|
| G2R1 | oracle | S4 path5 | **1.000** | 1.000 | 1.00 | 0.229 | 0.823 | 0.823 | 0.722 | 0.809 | **PASS** |
| G2R2 | oracle | S4 star5 | **0.889** | 0.800 | 1.00 | 0.303 | 0.823 | 0.808 | 0.625 | 0.894 | **PASS** |
| G2R3 | realistic | S5 path5 | **0.727** | 0.667 | 0.75 | 0.733 | 0.850 | 0.850 | 0.138 | 1.273 | FAIL |
| G2R4 | realistic | S5 star5 | **0.545** | 0.500 | 0.75 | 0.806 | 0.903 | 0.903 | 0.107 | 0.931 | FAIL |

Both realistic cells fail on `G2_strong_edge_f1` **and only** on that criterion. Note the
`G2_intervention_gain` criterion nominally passes in the realistic cells (0.138, 0.107) even
though the network model's absolute intervention error there is 0.73 and 0.81. The gain
criterion is relative to a best-simple comparator that is itself catastrophic (0.85, 0.90),
so passing it carries no absolute planning meaning. That is a property of the frozen design
worth stating plainly in the paper, not a defect in the reproduction.

### SGI_G3 (no-network falsification)

| trigger | severity | cell | model | statistic value | threshold | fired |
|---|---|---|---|---|---|---|
| `G3_null_s6a_false_edges_median` | HARD | G3R1 (realistic) | N | 3.0 | > 0.5 | **YES** |
| | | G3R2 (oracle) | N | 0.0 | > 0.5 | no |
| `G3_null_s6a_false_edges_any` | HARD | G3R1 (realistic) | N | 0.9667 | > 0.2 | **YES** |
| | | G3R2 (oracle) | N | 0.4833 | > 0.2 | **YES** |
| `G3_null_s6b_false_edges_median` | ROBUSTNESS | G3R1b (realistic) | N | 2.0 | > 0.5 | **YES** |
| | | G3R2b (oracle) | N | 0.0 | > 0.5 | no |
| `G3_null_s6b_false_edges_any` | ROBUSTNESS | G3R1b (realistic) | N | 0.9667 | > 0.2 | **YES** |
| | | G3R2b (oracle) | N | 0.2667 | > 0.2 | **YES** |
| `G3_placebo_effect` | HARD | G3R3 (realistic) | **L** | 0.600 | > 0.2 | **YES** |
| | | G3R4 (realistic) | **L** | 0.600 | > 0.2 | **YES** |
| `G3_prediction_intervention_inversion` | HARD | G2R1–G2R4 | N | 0.0 | rule | no |

Evaluated-model assignment confirmed correct and matching the design's stated intent:
S6a → `N`, S6b → `N`, S8 → `L`, inversion → `N`.

Required cells are **not** pooled in a way that hides failure. Each trigger is evaluated per
cell first and the gate fires if any cell fires; `oracle_cells_may_not_compensate` is
honoured — G3R2's clean median (0.0) does not offset G3R1's 3.0. Conversely the oracle cells'
own any-edge rates (0.483, 0.267) independently exceed threshold, so oracle success does not
exist to be hidden in the first place.

### Derived statuses and discrepancies

`LOCAL_RESPONSE_STATUS = LOCAL_RESPONSE_NOT_IDENTIFIED`; `SGI_G2_RAW_pass = false`;
`SGI_G3_hard_failure = true`; `NETWORK_SUPPORT_FINAL = NOT_EARNED`.

**Discrepancies versus the canonical tables: NONE.** Every G1 pass/fail, estimability rate
and failed-criteria list; every G2 pass/fail and failed-criteria list; every G3 trigger value
(to 1e-9), per-cell trigger state, evaluated model, and the hard-failure flag; and both
top-level statuses reproduce exactly.

---

## C. Best and worst local-response regimes

`POST-HOC MECHANISM DIAGNOSTIC` (audit question A). Metric: per-cell median
`nire_persistent_step_h26_L`, the frozen G1 estimand. Compared continuously against the
frozen 0.20 criterion; no new threshold is defined.

**Distribution over the 128 non-G0 cells:** min 0.1791, q05 0.5447, q25 0.8260, median
0.8492, q75 0.8595, max 1.0000. Cells at or below 0.20: **2**. Cells at or below 0.40: **2**.
Cells at or below 0.50: **2**. The `C_G0` implementation-sanity cell sits at 4.3e-15 and
carries no claim about attainable data.

**Answer to audit question A: yes — but only two, and they are a cliff, not a gradient.**

### The two qualifying regimes (full frozen configuration)

| field | G3R2b | G3R2 |
|---|---|---|
| median NIRE h26 (L) | **0.1791** | **0.1900** |
| scenario / topology | S6b / path5 geometry | S6a / null5 |
| **true cross-node coupling** | **C_ij = 0 by construction** | **C_ij = 0 by construction** |
| cadence k | 1 | 1 |
| k / tau_relax | 0.0730 | 0.0500 |
| tau_relax realized | 13.70 | 20.00 |
| pumping quality | **P-EXACT** | **P-EXACT** |
| pumping absolute scale known | True | True |
| recharge quality | **R-EXACT** | **R-EXACT** |
| recharge lag | 0 | 0 |
| forcing confounding rho | **0.0** | **0.0** |
| head SNR (nominal / realized / detrended) | 20 / 20.52 / 5.12 | 20 / 20.52 / 5.12 |
| process noise sd | 0.02 | 0.02 |
| MCAR fraction / block outages | 0.0 / 0 | 0.0 / 0 |
| observed node fraction | 1.0 | 1.0 |
| local persistence (mean A_ii) | 0.8509 | 0.9418 |
| pumping excitation fraction | 0.2592 | 0.2445 |
| condition number / max VIF | 11.17 / 21.19 | ~10 / ~20 |
| n transitions / n design rows | 519 / 363 | 519 / 363 |
| **absolute_S_identifiable** | **False** | **False** |

Both are the full `ORACLE_FAVOURABLE` observation bundle applied to a truth that has **no
cross-node coupling at all**. Neither was designed as a local-response demonstration cell —
they are the S6 network-falsification nulls, and they function here as an incidental oracle
for local response. The sweep contains **no** S1 or S5 cell with the oracle bundle, so no
purpose-built confirmation of this regime exists.

### The worst regimes

| cell | NIRE_L | driver |
|---|---|---|
| `GRID_grid_missing_x_obsnodes_0p5_0p4` | 1.0000 | MCAR 0.5 with only 40% of nodes observed |
| `GRID_grid_missing_x_obsnodes_0p3_0p4` | 0.9588 | MCAR 0.3, 40% nodes observed |
| `GRID_grid_coupling_x_snr_HIGH_2` | 0.9578 | strong true coupling + SNR 2 |
| `CURVE_curve_snr_2` | 0.9360 | SNR 2 |
| `GRID_grid_cadence_x_memory_13_LOW` | 0.9210 | k=13 against tau=4 (k/tau = 3.25) |
| `CURVE_curve_coupling_strength_HIGH` | 0.9143 | strong coupling, local model misspecified |

### The decisive 2×2: truth structure versus observation quality

| truth | observation | representative cell | median NIRE_L |
|---|---|---|---|
| uncoupled | ORACLE bundle, k=1 | G3R2b / G3R2 | **0.179 / 0.190** |
| uncoupled (single node) | realistic, k=1 | G1R2 | 0.530 |
| uncoupled (single node) | realistic, k=4 | G1R1 | 0.565 |
| uncoupled (null5, 5 nodes) | realistic, k=4 | G3R1 | 0.544 |
| zero coupling (gamma NONE) | realistic, k=4 | `CURVE_curve_coupling_strength_NONE` | 0.580 |
| **coupled** | **ORACLE bundle, k=1** | G2R1 / G2R2 | **0.823 / 0.823** |
| coupled | realistic, k=4 | G2R3 | 0.850 |

Read across the rows: when the truth is genuinely local, upgrading observation quality from
realistic to oracle moves intervention error from ~0.53–0.58 down to ~0.18 — a factor of
three, and across the frozen criterion. When the truth is coupled, the identical observation
upgrade moves it only from 0.850 to 0.823. **Both conditions are necessary; neither is
sufficient.** A local response model applied to a coupled aquifer sits at 0.82–0.91
regardless of how good the data are.

---

## D. Local failure mechanism

`POST-HOC MECHANISM DIAGNOSTIC` (audit question B). Cadence-dependent estimands are
respected throughout: `A_diag_relative_error_L` is measured against A^k, direct `B_Q`
comparison is used only at k=1, and the frozen pseudo-true coarse coefficient
`B_Q_pseudo_true_relative_error_median` is used at k>1.

### D.1 The failure is amplitude, not dynamics

The frozen sweep stores a scale-invariant counterpart to NIRE:
`relative_shape_error_persistent_step_L` normalises each response path by its own L2 norm
before comparison, so it measures shape only. Across the 128 non-G0 cells:

- median NIRE (shape **and** scale) = **0.8492**
- median relative shape error (shape only) = **0.0371**
- 124/128 cells have shape error ≤ 0.20; **128/128** have shape error ≤ half their NIRE
- rank correlation between the two is only **+0.179**

The trajectory of the counterfactual drawdown is recovered well nearly everywhere. What is
wrong is how big it is.

### D.2 The amplitude error is a pumping-coefficient attenuation

Comparing the stored estimated pumping coefficient against the frozen pseudo-true coarse
target (k>1, 118 cells):

- median **signed** relative bias in the pumping response = **−0.5126**
- fraction of cells attenuated (bias < 0) = **96.6%** (q10 −0.525, q90 −0.485)

Decomposed by pumping-observation regime, the effect is essentially entirely attributable to
`P-MULTNOISE`, the reference regime:

| pumping regime | cells | median signed relative bias | replicate-level check (k=4 curve) |
|---|---|---|---|
| P-EXACT | 1 | +0.012 | +0.013, 41.7% attenuated |
| **P-MULTNOISE** | 114 | **−0.513** | **−0.516, 100.0% attenuated** |
| P-SCALEBIAS | 1 | +0.013 | +0.011, 46.7% attenuated |
| P-TEMPAGG | 1 | +0.081 | +0.082, 45.0% attenuated |
| P-SPATIALAGG | 1 | +0.110 | +0.108, 30.0% attenuated |

The attenuation is invariant to head SNR (−0.519 / −0.510 / −0.512 / −0.513 at SNR
2 / 5 / 10 / 20) and to process noise (−0.513 / −0.498 / −0.445 at sd 0.05 / 0.25 / 1.0).
It is a property of the pumping channel alone.

Correspondingly, the pumping-coefficient error moves by a factor of 5.2 across the pumping
stress curve while everything else is held fixed:

| pumping regime | NIRE_L | shape error | A_diag rel. error | B_Q pseudo-true rel. error | excitation fraction | cond. number |
|---|---|---|---|---|---|---|
| P-EXACT | 0.706 | 0.028 | 0.060 | **0.098** | 0.104 | 10.2 |
| P-MULTNOISE | 0.850 | 0.037 | 0.071 | **0.514** | 0.197 | 9.5 |
| P-SCALEBIAS | 0.737 | 0.031 | 0.056 | 0.202 | 0.105 | 10.2 |
| P-TEMPAGG | 0.806 | 0.050 | 0.091 | 0.492 | **0.009** | **29.5** |
| P-SPATIALAGG | 0.780 | 0.035 | 0.078 | 0.282 | 0.324 | 9.2 |

**Interpretation.** `P-MULTNOISE` is 10% multiplicative noise on observed pumping — noise
proportional to the pumping *level*. The variation that actually identifies the pumping
response is not the level but the residual temporal variation left after the design absorbs
seasonality. In the frozen forcing process that identifying variation is itself of order 10%
of the mean pumping level (AR(1) innovation sd 0.06 with phi 0.7, plus independent excitation
sd 0.15, against a mean of 1.0 and a seasonal amplitude of 0.4 that the design largely
absorbs). Measurement noise scaled to the level is therefore comparable in size to the
identifying signal, and classical attenuation of roughly one half follows. The exact
attenuation factor depends on the post-seasonal identifying variance, which is not separately
stored, so this is offered as a mechanism consistent with the frozen constants rather than a
derived quantity. The empirical facts — 5.2x coefficient degradation and 51% attenuation from
10% pumping noise — stand on their own.

**This is an errors-in-variables failure, but on the forcing regressor, not on the state.**

### D.3 Persistence, and where compounding does matter

Analytic sensitivity using only stored medians (single-node persistent step,
`dh_m = -B * sum_{j<m} a^j * dQ`, `a = A^k`, `m = ceil(26/k)`):

| cell | k | m | a per step | stored e_A | stored e_B | NIRE from A error alone | NIRE from B error alone | observed NIRE | observed shape err |
|---|---|---|---|---|---|---|---|---|---|
| G1R1 | 4 | 7 | 0.819 | 0.075 | 0.491 | 0.120 – 0.143 | **0.491** | 0.565 | 0.046 |
| G1R5 | 4 | 7 | 0.819 | 0.063 | 0.479 | 0.101 – 0.117 | **0.479** | 0.541 | 0.037 |
| `CURVE_curve_pumping_quality_PMULTNOISE` | 4 | 7 | 0.648 | 0.071 | 0.514 | 0.078 – 0.089 | **0.514** | 0.850 | 0.037 |
| `CURVE_curve_pumping_quality_PEXACT` | 4 | 7 | 0.648 | 0.060 | 0.098 | 0.066 – 0.074 | 0.098 | 0.706 | 0.028 |
| `CURVE_curve_snr_2` | 4 | 7 | 0.648 | 0.758 | 0.479 | **0.501 – 1.079** | 0.479 | 0.936 | 0.338 |
| G1R2 | 1 | 26 | 0.951 | 0.076 | 0.225 | **0.391 – 0.534** | 0.225 | 0.530 | 0.130 |
| G3R2 | 1 | 26 | 0.942 | 0.037 | 0.053 | **0.220 – 0.333** | 0.053 | 0.190 | 0.060 |
| G3R2b | 1 | 26 | 0.851 | 0.053 | 0.042 | **0.191 – 0.290** | 0.042 | 0.179 | 0.059 |

Two distinct regimes:

- **At k = 4 (7 cadence steps to the horizon)** the stored persistence error can generate only
  0.07–0.14 of NIRE on its own, while the pumping-coefficient error generates 0.48–0.51.
  Amplitude dominates and its source is the forcing channel.
- **At k = 1 (26 steps to the horizon)** the geometric sum is long and a 4–8% persistence error
  is amplified into 0.19–0.53 of NIRE. Here persistence compounding is the larger term. This
  is exactly the residual that remains in G3R2/G3R2b once the forcing problem is removed.

### D.4 Factor-by-factor summary for the local model

- **A / persistence** — recovered well whenever head SNR ≥ 5. `A_diag_relative_error_L` falls
  from 0.758 at SNR 2 to 0.082 at SNR 20 (an 89% reduction). It becomes the binding term only
  at k=1 over long horizons, or at SNR 2, or at k=13 (0.411) where the coarse-step estimand
  itself degrades.
- **B_Q / pumping response** — the dominant failure term under realistic pumping observation.
  Attenuated ~51%, invariant to head quality.
- **Head noise** — matters for persistence, barely for intervention. SNR 2 → 20 moves NIRE only
  0.936 → 0.831 (−11%).
- **Process noise** — essentially inert for the local model. A 20-fold increase (0.05 → 1.0)
  changes NIRE by 0.008 (< 1%), while one-step RMSE degrades 3.6x. Identification here is
  observation-limited, not process-limited.
- **Recharge** — nearly inert. All five recharge regimes span 0.845–0.860, a swing of 0.015.
- **Confounding** — inert and slightly non-monotone in the unhelpful direction: rho 0.0 → 0.9
  moves NIRE from 0.858 to 0.828. Seasonal pumping/recharge confounding is *not* what breaks
  the local model in this design.
- **Cadence** — modest and non-monotone (k=1 0.844, k=2 0.824, k=4 0.850, k=13 0.914). Only
  k=13 clearly hurts, and the cadence × memory grid shows why: damage tracks k/tau_relax, not
  k. At k/tau = 3.25 (k=13, LOW memory) NIRE is 0.921 and A error explodes to 49.6; at
  k/tau ≤ 0.25 the estimand stays well behaved.
- **Excitation** — the clearest conditioning failure is `P-TEMPAGG`, where annual-total
  reporting collapses the pumping excitation fraction from ~0.20 to **0.009** and drives the
  condition number to 29.5. Insufficient excitation is real but confined to that regime.
- **Coupling (a property of the truth, not the data)** — the single largest swing: NIRE
  0.580 → 0.774 → 0.850 → 0.914 across gamma NONE → LOW → MED → HIGH.

---

## E. State-estimation / errors-in-variables hypothesis

`POST-HOC MECHANISM DIAGNOSTIC`. The hypothesis under test: *noisy observed head used as a
lagged regressor creates errors-in-variables bias in estimated persistence, and small
persistence bias compounds over 26 intervention steps.* Each of the five stated predictions
was tested against the frozen outputs.

| # | prediction | verdict | evidence |
|---|---|---|---|
| 1 | intervention NIRE improves **strongly** with head SNR | **weakly supported** | SNR 2→20 improves NIRE by only 11% (0.936→0.831) while it improves persistence recovery by 89% (0.758→0.082) and leaves the pumping-coefficient error flat (0.479→0.512, +6.9%). Head quality fixes the wrong term. |
| 2 | improves when process/observation noise decreases | **refuted for process noise** | 20x process-noise increase changes NIRE by 0.008 (<1%). Observation noise: see row 1. |
| 3 | persistence systematically biased | **NOT IDENTIFIABLE FROM STORED FROZEN OUTPUTS** | `A_diag_relative_error_L` is an unsigned absolute relative error. Magnitude is modest at reference conditions (0.071). The *direction* of the bias — the crux of an attenuation argument — is not recoverable without refitting. |
| 4 | long-horizon intervention error >> one-step prediction error | **supported in level, weak in growth** | The local model beats the naive baseline on one-step RMSE in 128/128 cells (median ratio 0.81) while median NIRE is 0.849. But the h52/h4 growth ratio has median only 1.03, and in 120/128 cells the h4 error already exceeds 0.5. The error is present from the first step, not accumulated. Exception: k=1 cells show real growth — G3R2 5.22x, G3R2b 4.77x, G1R2 2.06x. |
| 5 | pumping-response coefficients better recovered than persistence | **refuted, decisively** | At k=1, B_Q error exceeds A error in **9/10** cells (medians 0.139 vs 0.058; ratios 1.2–4.9x). At k>1, in **110/118** cells (medians 0.512 vs 0.076, ~6.7x). The relationship is the reverse of what the hypothesis requires. |

### Conceptual decomposition of intervention failure

- **Transition / persistence contribution** — small at k>1 (0.07–0.14 of NIRE), dominant at
  k=1 over 26 steps (0.19–0.53), catastrophic at SNR 2 (0.50–1.08).
- **Pumping-response contribution** — 0.48–0.51 under `P-MULTNOISE`, 0.10 under `P-EXACT`.
  The largest single term in the reference regime.
- **Other forcing (recharge, confounding)** — negligible: swings of 0.015 and 0.030
  respectively across their full frozen ranges.
- **Structural (coupling ignored by the local model)** — 0.33 of swing, and it sets an
  irreducible floor of 0.82–0.91 that no observation improvement in the sweep penetrates.

### Counterfactual recombination

Exact recombinations of the form `true A + estimated B_Q` and `estimated A + pseudo-true B_Q`
are **NOT IDENTIFIABLE FROM STORED FROZEN OUTPUTS**. The sweep stores scalar error summaries
(`A_diag_relative_error_L`, `A_vs_Ak_max_abs_error_L`, `B_Q_relative_error_median`,
`B_Q_pseudo_true_relative_error_median`, `beta_q_hat_mean_L`,
`B_Q_pseudo_true_diag_mean`), not the fitted matrices themselves, and no model was refit for
this audit. The analytic sensitivity in section D.3 is the closest admissible substitute and
is labelled as such.

**Additional stored diagnostics a future experiment should retain** so that this
decomposition becomes exact without refitting:

1. the full fitted `A_hat` and `B_hat` per replicate (or at minimum the **signed** diagonal
   of `A_hat` alongside the true `A^k` diagonal);
2. the intervention response recomputed under the two recombinations, evaluated with the same
   frozen NIRE routine;
3. the realised post-seasonal identifying variance of the observed pumping regressor, so the
   attenuation factor can be predicted rather than inferred;
4. the signed pumping-coefficient bias at k=1 (currently only the unsigned relative error is
   stored there).

### Verdict

**The lagged-state errors-in-variables hypothesis is not supported as the dominant mechanism.**
Persistence is the well-recovered quantity in the reference regime; the pumping-response
coefficient is the badly-recovered one; head SNR improves the former and not the latter; and
the failure is present at the shortest horizon rather than accumulated over 26 steps.

The hypothesis retains genuine but **secondary and conditional** force: at k=1 over a long
horizon, once pumping observation is exact, the residual ~0.18 error in G3R2/G3R2b is
consistent with persistence compounding, and there the geometric-sum amplification is real.
A state-space treatment would therefore be the *second* correction to make, not the first —
and the measurement-error term that most needs modelling is on **Q**, not on **h**.

---

## F. Data-quality sensitivity ranking

`POST-HOC MECHANISM DIAGNOSTIC` (audit question C). Each 1-D stress curve shares the same
S5/path5 reference baseline, so the swing within a curve isolates one factor over its frozen
tested range. Interpretable medians and contrasts only; no causal meta-model was fitted.

| rank | factor | frozen levels tested | best NIRE_L | worst NIRE_L | swing | best level | gap of best to 0.20 | monotone? |
|---|---|---|---|---|---|---|---|---|
| 1 | true coupling strength *(not a data choice)* | NONE→LOW→MED→HIGH | 0.580 | 0.914 | **0.334** | NONE | +0.380 | yes |
| 2 | **pumping quality** | P-EXACT→P-MULTNOISE→P-SCALEBIAS→P-TEMPAGG→P-SPATIALAGG | 0.706 | 0.850 | **0.143** | P-EXACT | +0.506 | n/a (categorical) |
| 3 | head SNR | 2→5→10→20 | 0.831 | 0.936 | 0.105 | 20 | +0.631 | yes |
| 4 | cadence | 1→2→4→13 | 0.824 | 0.914 | 0.091 | 2 | +0.624 | no (k=13 only) |
| 5 | hydraulic memory | LOW→MED→HIGH | 0.770 | 0.850 | 0.080 | HIGH | +0.570 | no |
| 6 | observed node fraction | 0.4→0.6→0.8→1.0 | 0.831 | 0.894 | 0.064 | 0.8 | +0.631 | approx. |
| 7 | confounding rho | 0.0→0.3→0.6→0.9 | 0.828 | 0.858 | 0.030 | **0.9** | +0.628 | yes, *wrong direction* |
| 8 | block outage | 0→1→2 | 0.836 | 0.859 | 0.022 | 2 | +0.636 | no |
| 9 | recharge quality | R-EXACT→R-NOISE→R-LAG→R-NOISELAG→R-SCALE | 0.845 | 0.860 | 0.015 | R-NOISELAG | +0.645 | n/a |
| 10 | process noise | 0.05→0.25→1.0 | 0.842 | 0.850 | 0.008 | 1.0 | +0.642 | yes, wrong direction |
| 11 | MCAR missingness | 0.0→0.1→0.3→0.5 | 0.842 | 0.850 | 0.008 | 0.0 | +0.642 | no |

For the network model the ranking is different and worth stating separately:

| factor | edge-F1 swing | note |
|---|---|---|
| true coupling strength | **0.878** | F1 goes 0.000 (gamma NONE) → 0.878 (gamma HIGH) |
| **observed node fraction** | **0.727** | F1 collapses to 0.000 at 40% of nodes observed |
| MCAR missingness | 0.229 | at MCAR 0.5 the network model is **0% estimable**; at 0.3 it is 38% estimable |
| cadence | 0.133 | |
| head SNR | 0.083 | |
| pumping quality | 0.048 | |
| recharge quality / confounding | 0.023 each | |
| process noise | 0.000 (F1) but 0.323 on NIRE_N | |

**Two conclusions.** First, among factors the project can actually buy, **pumping observation
quality is the top lever for local response**, and **well-network coverage plus record
completeness are the top levers for network support** — they are different measurements.
Second, and more important: *no single-factor improvement is sufficient*. The best value
attainable by moving any one factor is 0.580 (removing coupling from the truth, which is not
a data choice) or 0.706 (perfect pumping). Only the full oracle bundle over an uncoupled
truth crosses 0.20.

---

## G. S8 placebo mechanism

`CONFIRMATORY`: false-effect rate 0.600 in both G3R3 and G3R4, against the frozen 0.20
threshold, with real pumping verifiably retained in every fit
(`s8_real_pumping_present_L = 1` for all 120 replicates). Hard failure stands.

`POST-HOC MECHANISM DIAGNOSTIC`:

| quantity | G3R3 (single) | G3R4 (path5) |
|---|---|---|
| placebo coefficient, median | **+0.2398** | **+0.2162** |
| fraction of replicates with a **negative** (drawdown-like) placebo coefficient | 0.050 | 0.000 |
| placebo step response, median | 1.514 | 1.395 |
| true real-pumping step response, median | 6.740 | 5.570 |
| placebo / true ratio, median (q10, q90) | 0.225 (0.074, 0.396) | 0.250 (0.042, 0.444) |
| fraction with ratio in (0.20, 0.50] | 0.583 | 0.550 |
| fraction with ratio > 1.0 | 0.000 | 0.000 |

Three observations.

1. **The sign identifies the channel.** The placebo coefficient is *positive* in 95–100% of
   replicates. A positive coefficient on a pumping-like regressor says "more of this raises
   head" — a recharge-like, not a drawdown-like, response. By construction the placebo is
   correlated 0.85 with recharge/climate and has exactly zero causal effect. The estimator is
   loading unexplained climate variance onto the placebo channel; it is not inventing a
   spurious drawdown.
2. **The failure is threshold-marginal, not catastrophic.** The median false attribution is
   22–25% of the true pumping effect, sitting just above the frozen 0.20 line, and 55–58% of
   replicates fall in the (0.20, 0.50] band. No replicate reaches parity with the true effect.
   That is still a preregistered hard failure and is not reinterpreted here, but it matters for
   how the result should be described: a modest, systematic climate-attribution leak, not a
   wholesale inability to tell pumping from weather.
3. **The section-10 question cannot be answered.** The entire frozen sweep contains exactly
   **two** S8 cells, G3R3 and G3R4, and both use the reference regime: `R-NOISE` with sigma
   0.2, confounding rho 0.3, SNR 10, k=4, process noise 0.05. There is **no** S8 cell with
   `R-EXACT` recharge, none with rho ≠ 0.3, and no S8 variation in SNR, cadence, pumping
   quality or process noise. Whether placebo failure disappears under exact recharge and zero
   confounding is therefore **NOT IDENTIFIABLE FROM STORED FROZEN OUTPUTS**.

Within-cell replicate-level associations across the 60 seeds are weak and inconsistent
between the two cells (|rho| ≤ 0.32; the largest are +0.315 with detrended SNR and −0.279 with
max VIF in G3R4, and −0.172 with excitation fraction in G3R3). They do not support a
confident within-regime driver.

**Assessment.** The sign evidence points strongly at unresolved recharge/climate variance as
the attribution channel, and that is the leading hypothesis. It is a hypothesis supported by
mechanism and sign, **not** by a controlled contrast, because the required contrast cells do
not exist. A future experiment must cross S8 with recharge quality and confounding strength.

---

## H. S6a / S6b false-edge mechanism

`CONFIRMATORY` values reproduced; `POST-HOC` mechanism below.

| cell | null | regime | est. rate N | median false edges | mean | **any-false-edge rate** | q90 | max | median selected lambda |
|---|---|---|---|---|---|---|---|---|---|
| G3R1 | S6a | realistic | 1.00 | **3.0** | 3.52 | **0.967** | 5.1 | 7.0 | 1.0 |
| G3R2 | S6a | **oracle** | 1.00 | 0.0 | 0.57 | **0.483** | 1.0 | 2.0 | 0.3 |
| G3R1b | S6b | realistic | 1.00 | **2.0** | 2.43 | **0.967** | 4.0 | 6.0 | 1.0 |
| G3R2b | S6b | **oracle** | 1.00 | 0.0 | 0.33 | **0.267** | 1.0 | 2.0 | 0.3 |

In every one of these cells the true edge count is **zero** and roughly 7 candidate pairs are
available.

**Answer to the key question: both.** Spurious network discovery is primarily a realistic-data
problem in *magnitude* — the median false-edge count falls from 3 (S6a) and 2 (S6b) to 0 under
the oracle bundle. But it does **not disappear**: under favourable known truth, 48.3% (S6a) and
26.7% (S6b) of replicates still discover at least one edge in a network that has none, and both
rates exceed the frozen 0.2 threshold on their own. Regularisation selection does not rescue
this; the selected penalty simply moves from 1.0 to 0.3 with the better data.

**S6b, the cleaner falsification.** S6b preserves the coupled reference's local self-dynamics
(A_ii matched, A_ij zeroed, equilibrium preserved), so it isolates cross-node discovery from
any local-dynamics mismatch. It is *milder* than S6a — oracle any-rate 0.267 versus 0.483,
realistic median 2.0 versus 3.0 — which is consistent with S6a's unmatched A_ii and 2.13x
marginal-variance ratio making it a somewhat easier null to break. S6b nevertheless triggers
both of its criteria. Its preregistered role as `ROBUSTNESS_EVIDENCE` is preserved here and
**not** reinterpreted as a hard gate; the hard failure comes from S6a and S8.

**Corroboration outside S6.** The same phenomenon appears in a scenario that was not designed
as a null. In `CURVE_curve_coupling_strength_NONE` (S5, path5 geometry, realistic observation,
gamma = NONE so no true edges), the median false-edge count is **3.0** with an any-rate of
**0.983**. False-edge behaviour tracks true coupling strength directly:

| gamma | edge precision | median false edges | any-false-edge rate |
|---|---|---|---|
| NONE | 0.000 | 3.0 | 0.983 |
| LOW | 0.667 | 1.0 | 0.833 |
| MED | 0.667 | 1.0 | 0.800 |
| HIGH | **1.000** | **0.0** | **0.000** |

The estimator manufactures structure precisely when there is little or no true structure to
find. Process noise makes it worse (any-rate 0.80 → 0.85 → 0.97 across sd 0.05 → 0.25 → 1.0)
and so does confounding at the high end (median false edges 1.0 → 2.0 from rho 0.0 → 0.9).

---

## I. Oracle-versus-realistic network boundary

`POST-HOC MECHANISM DIAGNOSTIC`.

| quantity | G2R1 oracle path5 | G2R3 realistic path5 | G2R2 oracle star5 | G2R4 realistic star5 | R_S4_bridge oracle | R_S5_bridge realistic |
|---|---|---|---|---|---|---|
| edge F1 | 1.000 | 0.727 | 0.889 | 0.545 | 0.933 | 0.667 |
| **edge precision** | **1.000** | **0.667** | **0.800** | **0.500** | **0.938** | **0.667** |
| edge recall | 1.000 | 0.750 | 1.000 | 0.750 | 1.000 | 0.571 |
| median false edges | 0.0 | 1.0 | 1.0 | 3.0 | 0.5 | 2.0 |
| any-false-edge rate | 0.300 | 0.800 | 0.600 | 1.000 | 0.500 | 0.917 |
| NIRE_N (h26) | 0.229 | 0.733 | 0.303 | 0.806 | 0.392 | 0.801 |
| one-step RMSE (N) | 0.201 | 0.518 | 0.188 | 0.589 | 0.205 | 0.676 |
| A_diag rel. error (N) | 0.048 | 0.087 | 0.032 | 0.099 | 0.052 | 0.103 |
| strong-coupling weight error | 0.011 | 0.048 | 0.011 | 0.041 | 0.011 | 0.041 |

**The degradation is precision-driven.** Recall holds up reasonably (1.00 → 0.75) while
precision collapses (1.00 → 0.67, 0.80 → 0.50). The network estimator does not lose the real
edges under realistic data; it *adds false ones*. This is the same mechanism as the S6 nulls
and it is what fails `G2_strong_edge_f1`.

**A design confound that must be disclosed.** The `ORACLE_FAVOURABLE` bundle changes eight
things at once — cadence 4→1, P-MULTNOISE→P-EXACT, R-NOISE→R-EXACT, rho 0.3→0.0, MCAR 0.1→0.0,
SNR 10→20, process noise 0.05→0.02 — **and gamma MED→HIGH**. The last of these changes the
*truth*, not the observation: it makes the true edges stronger and therefore intrinsically
easier to detect. The frozen coupling curve isolates that effect at realistic observation
quality: at gamma = HIGH with ordinary S5 data, edge F1 is already **0.878** with precision
1.000 and an any-false-edge rate of **0.000**. So a substantial share of the "oracle network
success" is attributable to stronger true coupling rather than to better data.

Isolating the observational factors one at a time at fixed realistic truth:

| factor | edge F1 across levels | note |
|---|---|---|
| observed node fraction 0.4 → 1.0 | 0.000 → 0.333 → 0.571 → 0.727 | **dominant**; recall goes to zero at 40% coverage |
| MCAR 0.0 → 0.5 | 0.800 → 0.727 → 0.571 → *not estimable* | N is 38% estimable at 0.3 and **0% estimable at 0.5** |
| cadence 1 → 13 | 0.750 → 0.800 → 0.727 → 0.667 | mild; estimability falls to 83% at k=13 |
| head SNR 2 → 20 | 0.667 → 0.750 → 0.727 → 0.739 | mild |
| confounding 0.0 → 0.9 | 0.727 → 0.750 | negligible for F1, but median false edges rise 1.0 → 2.0 |
| process noise 0.05 → 1.0 | 0.727 → 0.727 | no F1 effect, but any-false-edge rate rises 0.80 → 0.97 |

**Verdict on the required distinction.** The evidence supports *"capable in favourable known
truth but not supportable at realistic information quality"* — **with the qualification that
"favourable" in this design includes a stronger true network, not only better observations.**
It does **not** support "incapable in principle": at gamma HIGH the estimator recovers support
well even on realistic data, and under the full oracle bundle it reaches F1 = 1.000 with
NIRE_N = 0.229. Equally, it does not support planning readiness: false-edge discovery persists
under the oracle bundle in the nulls (section H), which is what triggered the hard failure.

---

## J. Prediction versus intervention

`POST-HOC MECHANISM DIAGNOSTIC`. No new binary "good prediction" threshold is introduced;
the comparison is continuous, against the naive B0 baseline that the frozen design already
uses in `G1_stability_vs_B0`.

- **In 128 of 128 non-G0 cells the local model predicts better than the naive baseline.**
  Median `rmse_test_L / rmse_test_B0` = **0.810** (q10 0.726, q90 0.897), i.e. a typical 19%
  one-step forecasting improvement.
- **In 126 of those 128 the intervention error exceeds the frozen 0.20 criterion, and in 126
  it exceeds 0.5.** The two exceptions are the same two oracle null cells from section C.
- Rank correlation between prediction and intervention error is weak: **+0.234** for the local
  model, +0.458 for the network model.
- In the best-predicting tail the relationship essentially vanishes. The single
  best-predicting cell in the whole sweep, `GRID_grid_recharge_x_confounding_REXACT_0p9`
  (rmse ratio 0.626), has intervention error **0.843**. `R_S7_latentclimate` (ratio 0.644) has
  0.829. `CURVE_curve_pumping_quality_PEXACT` (ratio 0.702) has 0.706.
- The frozen binary `G3_prediction_intervention_inversion` correctly did **not** trigger; the
  weaker N-vs-L inversion flag fires in only 3 cells with negligible magnitudes
  (prediction gains 0.004–0.008, intervention losses 0.002–0.015). **The binary indicator is
  not where the evidence lives.** The continuous evidence above is far stronger.
- The S7 controlled-misspecification cells behave as designed: one-step RMSE beats the
  baseline by 20–36% in every variant while intervention error stays at 0.83–0.85.

**Why this matters for infrastructure optimisation.** A siting or withdrawal-permitting
optimiser queries the model with a counterfactual — *what happens to head if this facility
withdraws Q?* — and the answer's usefulness is governed by intervention error, not forecast
error. The frozen sweep shows these two quantities coming apart almost completely: a model
that forecasts 19% better than a naive baseline can be wrong about the drawdown response by
85% of its magnitude. Any pipeline that validates a groundwater model on held-out predictive
fit and then embeds it in an optimiser is, on this evidence, selecting on the wrong quantity.

---

## K. Failure-mechanism classification

Categories per task section 14. Each regime gets its dominant mechanism(s), the strongest
competing explanation, and a confidence level. Where the experiment cannot separate
alternatives, that is stated rather than forced.

### K.1 Local intervention failure under realistic observation, uncoupled truth (G1R1–G1R5, G3R1, G3R3)

- **Primary: D — FORCING CONFOUNDING / SCALE UNCERTAINTY**, specifically errors-in-variables in
  the *pumping* channel. Evidence: signed pumping-coefficient attenuation of −0.51 present in
  100% of `P-MULTNOISE` replicates and absent in all other pumping regimes; 5.2x coefficient
  degradation from P-EXACT to P-MULTNOISE at otherwise identical settings; relative shape error
  0.03–0.13 against NIRE 0.53–0.57, locating the failure in amplitude; analytic sensitivity
  attributing 0.48–0.49 of NIRE to the stored B error at k=4.
- **Secondary: C — ERRORS-IN-VARIABLES / STATE-ESTIMATION LIMITATION**, but only at k=1.
  Evidence: G1R2's h4→h52 growth of 2.06x and A-only analytic NIRE of 0.39–0.53 over 26 steps.
- **Alternative explanation considered:** B (practical/noise-limited). Rejected as primary
  because head SNR and process noise, the two noise channels, move NIRE by 11% and <1%
  respectively while pumping quality moves the coefficient by a factor of 5.
- **Confidence: HIGH.**

### K.2 Local intervention failure under coupled truth, any observation quality (G1R6, G2R1–G2R4, most S5 cells)

- **Primary: A — STRUCTURAL NON-IDENTIFIABILITY** (the local model omits real cross-node
  dynamics). Evidence: NIRE_L is 0.823 under the *full oracle bundle* with coupled truth
  versus 0.179–0.190 under the same bundle with uncoupled truth; the gamma curve spans
  0.580–0.914 at fixed observation quality; the floor is unmoved by an eightfold observation
  upgrade (0.850 → 0.823).
- **Alternative explanation considered:** D (forcing). Present as well — these cells also carry
  the −0.51 pumping attenuation — but it cannot be primary, because removing it entirely
  (P-EXACT, gamma MED) still leaves 0.706.
- **Confidence: HIGH.**

### K.3 Local failure at SNR 2 and at k=13

- **Primary: B — PRACTICAL / NOISE-LIMITED IDENTIFICATION** at SNR 2 (A error 0.758, shape
  error 0.338, NIRE 0.936).
- **Primary at k=13: A + F combined** — the coarse-step estimand itself degrades
  (A error 0.411, rising to 49.6 at k/tau = 3.25) and excitation falls (fraction 0.134,
  condition number 12.3). This is a genuine cadence-versus-hydraulic-timescale limit.
- **Confidence: HIGH** for SNR 2; **MODERATE** for k=13, since sample size also falls with
  cadence (39 transitions versus 519 at k=1) and the design cannot separate coarse-estimand
  degradation from **G — INSUFFICIENT SAMPLE SIZE**.

### K.4 P-TEMPAGG (annual pumping totals)

- **Primary: F — INSUFFICIENT EXCITATION.** Excitation fraction collapses from ~0.197 to
  **0.009** and the condition number rises to 29.5. Within-year pumping variation is the
  identifying signal, and annual reporting destroys it.
- **Confidence: HIGH.**

### K.5 S8 placebo false attribution

- **Primary: D — FORCING CONFOUNDING**, in the specific form of unresolved climate/recharge
  variance loading onto a climate-correlated regressor. Evidence: placebo coefficient positive
  in 95–100% of replicates (recharge-like sign) with a construction correlation of 0.85 to
  recharge and zero true effect.
- **Alternative explanation considered:** a more fundamental attribution defect in the
  estimator. Cannot be excluded — the median false attribution is only 0.22–0.25 of the true
  effect and never reaches parity, which is more consistent with a leak than with an inability
  to attribute, but the discriminating cells do not exist.
- **Also present: I — INCONCLUSIVE** on the section-10 question specifically. The sweep has no
  S8 cell with exact recharge or altered confounding.
- **Confidence: MODERATE** on the mechanism; **the controlled contrast is unavailable.**

### K.6 S6a / S6b false-edge discovery

- **Primary: E — NETWORK SUPPORT / TOPOLOGY MISSPECIFICATION**, in the form of false-positive
  support recovery when true coupling is weak or absent. Evidence: median 2–3 false edges out
  of ~7 candidate pairs at realistic quality with a 96.7% any-rate; the precision-driven
  (not recall-driven) degradation in G2; and the independent corroboration at gamma = NONE
  (median 3.0, any-rate 0.983) outside the null scenarios.
- **Secondary: B — PRACTICAL / NOISE-LIMITED**, since the oracle bundle removes the median
  entirely (3.0 → 0.0).
- **Not supported: A (structural non-identifiability).** The estimator reaches F1 = 1.000 with
  zero false edges under the oracle bundle and F1 = 0.878 with zero false edges at gamma HIGH
  on realistic data. It is capable; it is not reliable at low true-signal strength.
- **Confidence: HIGH.**

### K.7 Network failure at low well coverage / high missingness

- **Primary: G — INSUFFICIENT SAMPLE SIZE / OBSERVATION DENSITY.** Evidence: edge F1 falls to
  0.000 at 40% node coverage; the network model is 38% estimable at MCAR 0.3 and **0%
  estimable at MCAR 0.5**; the local model remains 92–98% estimable in the same cells.
- **Confidence: HIGH.**

### K.8 Absolute physical scale

- **Primary: D — SCALE UNCERTAINTY**, by frozen design rule rather than by empirical failure.
  `absolute_S_identifiable` is True in only 4 of 129 cells (`C_G0`, `G2R1`, `G2R2`,
  `R_S4_bridge`), all of which require k=1, P-EXACT, R-EXACT and rho = 0 simultaneously.
- **Confidence: HIGH** (this is a definitional consequence of the preregistered rule, verified
  against the data).

### K.9 What the experiment cannot classify

- The **direction** of persistence bias (section E, prediction 3): **H / I**.
- Whether exact recharge and zero confounding remove the S8 placebo effect: **I**.
- Whether pumping metering alone would restore local recovery at an uncoupled truth with
  otherwise realistic observation: **I** — the required cell does not exist (see Q).

---

## L. Empirical decision table

Written to `/tmp/sgi_independent_audit/EMPIRICAL_DECISION_TABLE.csv` (129 rows × 34 fields)
and rendered in `/tmp/sgi_independent_audit/EMPIRICAL_DECISION_TABLE.md`. Classification uses
only frozen criteria: the G1 threshold 0.20 on `median(nire_persistent_step_h26_L)`, the G2
edge criterion 0.80 on `median(strong_edge_undirected_f1)`, the G3 falsification outcome
(hard failure ⇒ network NOT_EARNED globally), and the frozen `absolute_S_identifiable` flag.
No new thresholds were invented; regimes the continuous evidence cannot categorise are marked
`INCONCLUSIVE`.

| label | cells (of 129) |
|---|---|
| `FORECASTING_ONLY` | 126 |
| `ABSOLUTE_PHYSICAL_SCALE_NOT_IDENTIFIED` | 125 |
| `NETWORK_NOT_EARNED` | 122 |
| `SPATIAL_FORCING_DIAGNOSTIC_ONLY` | 17 |
| `NETWORK_CONDITIONALLY_TESTABLE` | 7 |
| `LOCAL_RESPONSE_CREDIBLE` | 3 (of which 1 is the noise-free `C_G0` sanity cell) |
| `LOCAL_RESPONSE_CONDITIONALLY_CREDIBLE` | 0 |
| `INCONCLUSIVE` | 0 |

**What model complexity is supportable, and where.**

- **Forecasting only** is the supportable answer for essentially the entire realistic design
  space. The local model reliably beats a naive baseline on one-step prediction in every cell,
  and reliably fails counterfactual intervention recovery in all but two.
- **Local response is credible in exactly two non-G0 regimes**, both requiring simultaneously:
  k=1 cadence, exact pumping, exact recharge, zero confounding, zero missingness, full node
  coverage, SNR 20, process noise 0.02, **and a truth with no cross-node coupling**. Neither
  was designed as a local-response cell.
- **`NETWORK_CONDITIONALLY_TESTABLE` is a weak label and must not be over-read.** The 7 cells
  that meet the frozen edge criterion with no false edges are all high-coupling or
  low-memory/short-cadence regimes at full node coverage. Their network *intervention* error
  ranges from 0.506 to 0.910 — support recovery without usable counterfactual accuracy. And
  the global G3 hard failure applies regardless, so `NETWORK_NOT_EARNED` remains the operative
  status everywhere.
- **Spatial forcing without dynamic network** beats the local model on intervention in 17 of
  129 cells, but by tiny margins in most (e.g. 0.774 → 0.772). The clearest gains are at LOW
  hydraulic memory (0.810 → 0.640, and 0.761 → 0.711 at k=1). The best spatial-model
  intervention error anywhere outside G0 is 0.181, in the same oracle null cell — so spatial
  forcing does not open a route that local response does not already have.
- **Absolute physical scale is essentially never identified.** Only 4 of 129 cells satisfy the
  frozen conditions, and **not one cell in the entire sweep is simultaneously
  local-response-credible and absolute-scale-identifiable**, apart from the noise-free `C_G0`
  sanity cell. Absolute drawdown-per-unit-withdrawal — precisely the quantity a siting
  optimiser needs — is never jointly established with credible response recovery anywhere in
  the frozen evidence.

---

## M. Recommended next methodological step

### **Option C — improve forcing identification first.**

### Confidence: MODERATE-TO-HIGH.

**Why C.** The dominant, reproducible, mechanism-identified term in local intervention failure
is a ~51% attenuation of the estimated pumping response, driven entirely by measurement error
in the observed pumping regressor and completely insensitive to head quality and process
noise. It is the largest actionable single factor in the frozen sensitivity ranking (0.143 of
NIRE swing, versus 0.105 for head SNR and 0.008 for missingness), and the underlying
coefficient error moves by a factor of 5.2 across that one factor. Nothing else the project
can buy has comparable leverage on the local estimand.

**Why not A (proceed to empirical M1L).** A requires credible local intervention recovery
under observation conditions plausibly attainable in Andhra Pradesh. The frozen sweep places
that recovery behind a conjunction of k=1 cadence, exact pumping, exact recharge, zero
confounding, zero missingness, full node coverage, SNR 20 **and** a truth with no cross-node
coupling. Basin-wide exactly-metered pumping at fine time resolution is not attainable, and
the coupled-truth rows show that even if it were, a local model over a coupled aquifer stays
at 0.82. The next-best regime after those two oracle cells is 0.530 — 2.65 times the criterion.

**Why not B (state-space estimator first).** B is warranted only if local failure is dominated
by lagged-head measurement error and persistence bias. Four of the five stated predictions of
that hypothesis fail against the frozen outputs, and the fifth — that pumping coefficients are
better recovered than persistence — is decisively reversed (B_Q error exceeds A error in
110/118 cells at k>1 and 9/10 at k=1). Persistence is already well recovered at SNR ≥ 5;
response *shape* is recovered to within 0.037 median error. A latent-state formulation of the
form `h_{t+1} = A h_t + B_R R_t − B_Q Q_t + eps`, `y_t = h_t + nu_t` corrects noise on `y`,
which is the smaller problem. **If a measurement-error estimator is built, the error model must
be placed on `Q`, not on `h`** — that is the single most actionable methodological finding in
this audit. A joint treatment (state estimation *and* forcing-error modelling) is the natural
eventual target, but forcing comes first on this evidence.

**Why not D (stop dynamic response modelling).** Too strong. The oracle cells demonstrate that
the estimator recovers local intervention response to within the frozen criterion when the
information regime is good enough and the truth is genuinely local. The failure is
informational and structural, not a demonstration that the modelling approach is void.

**Why not E (inconclusive).** The frozen outputs discriminate cleanly among the options on the
decisive quantities: signed coefficient bias by pumping regime, shape-versus-scale
decomposition, SNR and process-noise stress curves, and the coupled/uncoupled × oracle/realistic
contrast.

**What "improve forcing identification" concretely means, and the honest caveat.** The most
valuable immediate step is a small, targeted synthetic extension — *not* an empirical model —
that crosses pumping-observation quality with an uncoupled truth at otherwise realistic
observation quality. The current sweep's `P-EXACT` cell sits on a coupled path5 truth, so it
cannot isolate the effect. Establishing whether pumping metering alone restores local recovery
at an uncoupled truth is a small number of cells and would move the recommendation from
MODERATE-HIGH to HIGH, or refute it. That cell's absence is the main reason the confidence is
not HIGH (see section Q).

---

## N. Network recommendation

### **`DO_NOT_ATTEMPT_M1N_YET`**

Empirical `M1N` should **not** be attempted now. Reasoning, none of which overturns the frozen
`NETWORK_SUPPORT_FINAL = NOT_EARNED`:

1. **The falsification test failed, and not only on bad data.** Under the full oracle bundle,
   48.3% (S6a) and 26.7% (S6b) of replicates discover at least one edge in a truth with zero
   coupling. A method that invents structure a quarter to a half of the time under
   best-case known-truth conditions cannot be pointed at a real basin where no ground truth
   exists to catch it.
2. **The realistic-quality failure is a false-positive failure.** Edge precision falls
   1.000 → 0.667 and 0.800 → 0.500 while recall largely holds. In a planning context, false
   connections between a data-centre wellfield and distant users are exactly the errors that
   produce wrong siting and wrong liability attribution.
3. **Support recovery does not deliver intervention accuracy.** Even in the 7 cells that meet
   the frozen edge criterion with zero false edges, network intervention error is 0.51–0.91.
4. **The empirical setting is far worse than the failing synthetic cells.** Network F1 is 0.000
   at 40% node coverage, and the network model is 0% estimable at 50% MCAR — both plausible for
   real observation-well panels.
5. **The oracle success is partly an artefact of stronger true coupling.** The
   `ORACLE_FAVOURABLE` bundle also raises gamma MED→HIGH, so the oracle result overstates what
   better observations alone would buy.

The accurate scientific characterisation of the method is
`NETWORK_METHOD_WORTH_FUTURE_RESEARCH_BUT_NOT_PLANNING_READY` — the estimator reaches F1 = 1.000
with zero false edges when true coupling is strong and data are good, so it is not incapable in
principle. The two statements are compatible: worth further methods research, not to be
attempted on Andhra Pradesh data now. **The operative recommendation is
`DO_NOT_ATTEMPT_M1N_YET`.** Any future network work must carry a false-discovery control that
is validated on a null before any real-data claim is made.

---

## O. Andhra Pradesh data priorities

Ranked strictly by leverage observed in the frozen synthetic evidence. Ranks 1–3 are for local
response, which is the near-term target; ranks 4–6 matter only if network work is ever revived.

| rank | information | frozen evidence | expected value |
|---|---|---|---|
| **1** | **Absolute time-resolved pumping, accurate in its *variation* not just its level** | P-EXACT → P-MULTNOISE degrades the pumping coefficient 5.2x (0.098 → 0.514) and attenuates it 51% in 100% of replicates; largest actionable NIRE swing (0.143) | **Highest.** The binding constraint on local response. Critically: what matters is measurement error relative to the *temporal variability* of pumping, not relative to its mean. Metering that is 10% accurate on the level is not good enough when the identifying variation is itself ~10% of the level. |
| **2** | **Sub-annual pumping cadence (never annual totals)** | P-TEMPAGG collapses excitation from 0.197 to **0.009** and drives condition number to 29.5 | **Very high, and cheap to get wrong.** Annual pumping totals disaggregated by a seasonal template destroy the identifying signal outright. This is a data-collection design decision, not a budget question. |
| **3** | **Head measurement cadence matched to hydraulic timescale (k/tau ≲ 0.25), with adequate head SNR (≥ 5)** | damage tracks k/tau_relax, not k: NIRE 0.921 and A error 49.6 at k/tau = 3.25, well behaved at k/tau ≤ 0.25; A error falls 0.758 → 0.082 from SNR 2 → 20, with most of the gain by SNR 5 | **High**, but with a ceiling. Fixes persistence estimation; moves intervention error only ~11%. Necessary, not sufficient. Requires estimating local tau first, so a short pilot is warranted before fixing the monitoring interval. |
| **4** | **Stable, dense observation-well panels (node coverage)** | edge F1 0.000 → 0.727 across 40% → 100% coverage; the dominant network factor after true coverage strength | **High for network only.** Near-irrelevant for local response (NIRE swing 0.064). |
| **5** | **Record completeness / outage structure** | network model 38% estimable at MCAR 0.3, **0% at MCAR 0.5**; local model 92–98% estimable in the same cells | **Moderate, and asymmetric.** Missingness is what makes network estimation impossible rather than merely inaccurate. It barely touches local intervention error (swing 0.008). Block outages are similarly inert for local (0.022). |
| **6** | **Aquifer / network support information (prior connectivity constraints)** | S9 candidate-support misspecification degrades F1 0.878 → 0.727 (nested HIGH → misspecified HIGH) and raises median false edges 0 → 2 | **Moderate for network only.** A credible candidate graph reduces but does not eliminate false discovery. |
| **7** | **Recharge timing and quality** | all five recharge regimes span only 0.845–0.860 on local NIRE (swing 0.015); no effect on edge F1 (0.023) | **Low for local response.** Genuinely surprising and worth stating in the paper. But see caveat below. |
| **8** | **Covariates separating climate from pumping (confounding controls)** | confounding rho 0.0 → 0.9 moves local NIRE 0.858 → 0.828, i.e. slightly *better* at higher confounding | **Low on the direct evidence, but not dismissible.** The S8 placebo failure is a climate-attribution failure and the placebo coefficient carries a recharge-like sign, which points at exactly this channel. The 1-D confounding curve and the S8 evidence disagree, and the sweep cannot reconcile them because no S8 cell varies recharge quality or confounding. Treat as **unresolved**, not as low priority. |

**Two cross-cutting points.**

- **Absolute drawdown-per-unit-withdrawal requires the full conjunction** — k=1, P-EXACT,
  R-EXACT, rho = 0 — and is satisfied in only 4 of 129 cells, none of which is also
  local-response-credible. If the planning application needs absolute withdrawal constraints
  rather than relative response shapes, the frozen evidence says that quantity is not on the
  table with any observation regime tested.
- **No amount of data fixes a local model applied to a coupled aquifer.** Before investing in
  the measurements above, the project needs evidence about whether the target Andhra Pradesh
  units behave as effectively independent local systems or as a coupled network. That is a
  hydrogeological question, and on this evidence it determines whether ranks 1–3 are worth
  buying at all.

---

## P. Paper implication

**The strongest defensible message is supported, and it is the one proposed:**

> Predictive groundwater fit alone is insufficient for infrastructure planning. Response models
> should be qualified using known-truth intervention recovery and falsification before being
> embedded in siting optimisation.

The frozen evidence for it is unusually clean: **in 128 of 128 non-G0 regimes the local model
forecasts better than a naive baseline (median 19% RMSE improvement), and in 126 of those the
same model's counterfactual intervention error exceeds the preregistered criterion — 126 of them
by more than a factor of 2.5.** The rank correlation between the two competences is +0.234, and
in the best-forecasting tail it disappears entirely. A practitioner selecting a groundwater
model on held-out predictive skill would, on this evidence, have essentially no information
about whether the model can answer the question a planner actually asks.

The falsification half of the message is equally well supported: the estimator discovers 2–3
false connections out of ~7 candidate pairs in networks that have none, at a 96.7% any-rate
under realistic data and still at 27–48% under best-case known truth — and it does so while
passing ordinary predictive checks.

**Emphasis, in priority order:**

1. **Prediction-versus-intervention divergence.** The strongest, cleanest, most transferable
   result. 128/128 versus 126/128 is a striking headline and it generalises beyond groundwater.
2. **False network discovery.** The second-strongest. It has a preregistered null, an oracle
   control, a robustness null that isolates cross-node discovery from local-dynamics mismatch,
   and independent corroboration at gamma = NONE outside the null scenarios.
3. **Forcing observation quality as the binding constraint on response identification.** The
   specific, actionable, and somewhat counterintuitive finding: 10% multiplicative noise on
   pumping attenuates the estimated response by half, while a tenfold improvement in head
   signal-to-noise buys 11%. This reframes "better groundwater data" from head monitoring
   toward withdrawal metering.
4. **Local data-adequacy thresholds**, stated honestly as a conjunction rather than a set of
   marginal requirements. The cliff structure — two cells at 0.18–0.19, then nothing until
   0.53 — is itself the finding.
5. **State-estimation requirements.** Worth a section, but it must be framed correctly: the
   errors-in-variables problem that matters here is on the forcing regressor, not on the lagged
   state. Publishing the naive version of that claim would be wrong on this evidence.
6. **Forcing confounding** should be reported with its tension intact: the direct confounding
   curve shows almost no effect on local intervention error, while the S8 placebo test fails
   at 0.60 with a recharge-signed coefficient. The paper should present both and say the
   design cannot reconcile them.

A structural point the paper should also make, because the sweep establishes it well: **model
misspecification about aquifer connectivity dominates observation quality.** Under the identical
oracle observation bundle, local intervention error is 0.18 when the truth is uncoupled and 0.82
when it is coupled. Data quality cannot rescue a structurally wrong response model, and known
truth is what makes that visible.

---

## Q. Unsupported interpretations

Claims the frozen sweep does **not** establish, and which should not appear in the paper or in
downstream planning documents:

1. **That `G1R2` is an oracle or favourable local-response regime.** It is not. `G1R2` overrides
   **only** `cadence: 1`. Every other factor stays at the degraded reference regime: P-MULTNOISE
   pumping noise s = 0.1, R-NOISE recharge sigma = 0.2, confounding rho = 0.3, MCAR 0.1, nominal
   head SNR 10 (detrended realised SNR **3.52**), process noise sd 0.05. **The prior report's
   statement — "G1R2 already has k=1 and favourable local conditions, so better pumping/recharge
   metadata alone would not have flipped G1" — is not supported and must not be repeated.** The
   frozen stress surface shows the opposite direction of evidence: pumping quality is the single
   largest actionable factor, and the two regimes that do meet the criterion differ from G1R2
   precisely in the pumping/recharge/noise bundle.
2. **That better pumping metadata alone would flip G1.** Equally unsupported, and this is the
   audit's own main gap. No cell isolates `P-EXACT` at an uncoupled truth with otherwise
   realistic observation. The sweep's `P-EXACT` cell sits on a coupled path5 truth (NIRE 0.706).
   The inference from the mechanism is strong but it is an extrapolation across a cell that was
   never run.
3. **That local response identification is attainable in Andhra Pradesh.** The two qualifying
   regimes require a conjunction that includes exact basin-wide pumping and exact recharge.
   Nothing in the sweep speaks to attainability in a real basin.
4. **That the S8 placebo failure is caused by unresolved recharge confounding.** This is the
   leading hypothesis, supported by the sign of the placebo coefficient and by the construction
   correlation of 0.85, but the frozen sweep contains only two S8 cells and neither varies
   recharge quality or confounding. Stated as established, this would be a claim about cells
   that do not exist.
5. **That the network estimator is incapable in principle.** It reaches F1 = 1.000 with zero
   false edges under the oracle bundle and F1 = 0.878 with zero false edges at gamma HIGH on
   realistic data.
6. **That oracle network success demonstrates what better observations would buy.** The
   `ORACLE_FAVOURABLE` bundle also changes the truth (gamma MED → HIGH), making the true edges
   intrinsically stronger. Observation quality and true signal strength are confounded in that
   contrast.
7. **That the direction of persistence bias is known.** Only the unsigned relative error is
   stored. Any claim that persistence is systematically over- or under-estimated is
   `NOT IDENTIFIABLE FROM STORED FROZEN OUTPUTS`.
8. **That `NETWORK_CONDITIONALLY_TESTABLE` cells are network-ready.** Their intervention error
   is 0.506–0.910, and the global G3 hard failure applies to them as it does to everything else.
9. **That passing `G2_intervention_gain` in the realistic cells means the network model is
   useful there.** The gain is measured against a best-simple comparator that is itself at
   0.85–0.90; a 10–14% relative improvement over a catastrophic baseline is still catastrophic.
10. **That confounding is unimportant.** The direct curve says so; the S8 result points the
    other way. The design cannot settle it.
11. **That process noise and missingness are unimportant for the project generally.** They are
    nearly inert for *local intervention error*, but MCAR 0.5 makes the network model entirely
    unestimable and degrades local estimability to 92–98%. The claim is metric-specific.
12. **That any regime supports absolute withdrawal constraints.** Not one cell is jointly
    local-response-credible and absolute-scale-identifiable outside the noise-free `C_G0`
    sanity cell.
13. **That 129 cells at 60 seeds resolves interaction structure generally.** The frozen design
    states this openly: no formal estimate of higher-order interactions exists outside the five
    named two-factor grids. Nothing in this audit changes that.

---

## R. Repository verification

Confirmed at the close of the audit:

- **No repository scientific file changed.** `git status --porcelain` scoped to
  `other_sources/groundwater_identifiability_synthetic/` is **empty**. All 30 files in
  `CODE_MANIFEST_V2.csv` still hash to their frozen values, and the recomputed `CODE_HASH` and
  `DESIGN_HASH` are unchanged from the freeze and from the sweep manifest.
- **No output artefact changed.** All 24 entries in `ANALYSIS_OUTPUT_HASHES.csv` verify.
- **No commit was created, amended, merged, rebased or force-pushed.** HEAD is
  `347d88c5778a1130fad42ffcf12820e7dde4eee6`, unchanged throughout. `main` and `origin/main`
  remain at `84c4c81e7a4927ca36e95200dfb957f4e9014378`; no merge to `main` occurred. The
  results-preservation commit required by task section 2 already existed at HEAD and contains
  only generated outputs.
- **The pre-existing dirty gitlink `Data-center-PUE-prediction-tool` was not touched or
  staged.** It remains the only tracked working-tree modification, exactly as it was on entry.
- **The sweep was not rerun**, no new seeds were inspected, no model was refit, no threshold or
  gate was altered, `design_v2` and the DGP and estimator code were not modified, and no new
  synthetic scenario was created.
- **All scratch analysis lives under `/tmp/sgi_independent_audit/`.** Nothing was written into
  the repository.

### PSCC independence (task section 20)

- `M0^{PSCC}` was **not** modified. `git status --porcelain` scoped to
  `other_sources/pscc_m0_recovery_audit/` is **empty**.
- PSCC was **not** reconstructed and no PSCC recovery provenance was touched or read for
  inferential purposes.
- The untracked `pscc_m0_handoff/` directory was left untracked and unmodified; it was not
  staged, not committed, and not inspected as part of this audit.
- PSCC artefact recovery remains a parallel independent lane, unaffected by this work.
