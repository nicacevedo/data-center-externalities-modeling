# Phase 1.5 checkpoint report — design_v2 pre-sweep freeze

`design_v2` · Phase 1.5 complete · **FULL SUBSTANTIVE SWEEP NOT RUN**

Executed exactly:

```
pytest -> freeze design_v2 -> SGI_G0 -> engineering smoke (SMOKE seeds)
-> summarize_results on fixtures and smoke only -> runtime/storage benchmark -> STOP
```

No `ANALYSIS` seed was inspected. No scientific conclusion is drawn from G0, smoke,
fixtures, or this report. This phase only establishes that the experiment is
mathematically, computationally, and procedurally ready for the known-truth test.

---

## A. Repository state

| item | value |
|---|---|
| branch | `testing/synthetic-groundwater-identifiability` |
| starting HEAD | `1b95209b1a2f0e20ae8bfac3910bd5359a420c82` (`[Feature] GW synthetic`) |
| ending HEAD | `1b95209b1a2f0e20ae8bfac3910bd5359a420c82` (unchanged; no commit) |
| `main` | `84c4c81e7a4927ca36e95200dfb957f4e9014378` |
| `origin/main` | `84c4c81e7a4927ca36e95200dfb957f4e9014378` |
| `git diff --name-status 1b95209..HEAD` | empty |
| new commit | none |
| push / merge / rebase / amend | none |

Working-tree status: uncommitted v2 work under
`other_sources/groundwater_identifiability_synthetic/` plus the pre-existing dirty
gitlink `Data-center-PUE-prediction-tool` (`11663ab…-dirty`). That gitlink was not
reset, staged, cleaned, committed, entered, or updated.

Tracked files outside the groundwater module: none changed.

---

## B. v1 → v2 changes

v1 materials (`config/design_v1.yaml`, `DESIGN_FREEZE.md`, Phase-1 provenance under
`outputs/provenance/DESIGN_FREEZE.json` and companions) were not mutated.

Classified list: `DESIGN_V1_TO_V2_CHANGELOG.md`. Summary:

| change | class | why |
|---|---|---|
| S7 latent climate: multiplicative factor + stationary-sd → AR(1) innovation conversion | implementation bugfix (documented as v2 protocol) | Additive / mis-scaled AR(1) drove clipping |
| Cadence estimands made machine-explicit (`k=1` physical vs `k>1` `A^k` / pseudo-true coarse B) | scientific-design clarification | v1 stated the rule; v1 bootstrap still compared coarse coefficients to fine `-B_Q` |
| Masked-node: frozen target before missingness; warm-forward unscored; TEST-aligned scoring; no fallback | scientific-design change | v1 selected an easier node after missingness and scored from an early anchor |
| Estimability first-class (`NOT_ESTIMABLE` / `FIT_FAILED` / `ESTIMATED` + gate states) | scientific-design / reporting | Must not collapse into silent NaNs |
| Process-noise curve `{0.05, 0.25, 1.0}` retained as explicit v2 pre-analysis addition | scientific-design (pre-analysis) | Reference regime is observation-limited |
| S8: estimator receives `Q_real_observed` **and** `P_placebo`; truth coefficient on placebo is 0 | scientific-design change | v1 replaced real pumping |
| S6a preserved (global-memory null); S6b added (matched local dynamics) | scientific-design change | One null is not enough |
| Cadence-correct moving-block bootstrap | scientific-design change | Physical coverage only at `k=1` where identifiable |
| Physical `S`/`C` recovery requires the full conjunction, not known pumping scale alone | scientific-design change | v1 overclaimed |
| `summarize_results.py` frozen on fixtures/smoke schema | reporting/provenance | Analysis logic preregistered |
| SGI_G0–G3 cells/metrics/`NOT_ESTIMABLE`/S6a vs S6b vs S8 severity made machine-explicit | scientific-design / reporting | No vague “relevant regimes” |
| v2 provenance filenames | reporting/provenance | Keep v1 freeze as historical evidence |
| S6b timescale recorded from `A_null`, not retuned to MED `τ=20` | scientific-design documentation | Coupled MED `τ` is a network eigenmode |
| Summarizer evaluates G1/G2 statistics and G3 prediction–intervention inversion, not only `metric_column` criteria | reporting/provenance | Incomplete gate wiring would have under-enforced G1/G2 |

---

## C. Masked-node fix

**Old (v1):** after missingness, fall back to a nearer observed node if the intended
target lacked a usable pre-mask observation; recursive forecast could start at that
earlier anchor and be scored as if it were TEST-onset aligned.

**New (v2):**

1. Frozen topology table **before** missingness (`path5→2`, `star5/single→0`).
2. Node must have TRAIN/VALIDATION history sufficient for estimability.
3. TEST-onset head of that node is withheld for a contiguous horizon.
4. Last admissible pre-mask observation is the recursion anchor.
5. If that instant is before `TEST_onset - 1`, warm-forward internally to onset (**not scored**).
6. Score only predictions at instants `onset … onset+horizon-1`.
7. No withheld TEST head re-enters the recursion (poisoned TEST-head regression test).
8. If the frozen target is unobserved or has no anchor: `status = NOT_ESTIMABLE`. No
   substitution.

Interpretation remains **monitoring-loss propagation for a previously observed node**,
not zero-shot prediction at an unseen aquifer node (`zero_shot_held_out_node =
NOT_PERFORMED_IN_V2`).

Tests: `test_masked_node_start_walks_back_past_a_missing_pre_mask_instant`,
`test_masked_node_no_leak`, `test_frozen_masked_node_has_no_post_missingness_fallback`.

---

## D. S8 placebo

**DGP.** Real pumping `Q` still enters the state equation. Placebo `Q_placebo` is
generated correlated with recharge (`placebo_correlation_with_recharge = 0.85`) and
**does not appear** in the head update:

```text
h_{t+1} = A h_t + b + B_R R_t - B_Q Q_real,t + B_Q ε_t
          + 0 * P_placebo,t
```

**Estimator inputs.** `Q_obs` is always real pumping (measured/proxy under the regime).
`P_placebo` is a separate column on L/S/N. `use_placebo_as_pumping=True` raises
`ValueError`.

**Proof real pumping remains included.** `make_observations` always writes `Q_obs` from
`Q_true`. Tests: `test_s8_real_pumping_and_placebo_both_present`,
`test_s8_refuses_to_replace_real_pumping`. Smoke (schema only): all 6 S8 records have
`has_placebo=True` and `s8_real_pumping_present_L=1`.

**Proof placebo truth coefficient is zero.** The simulate loop never subtracts
`Q_placebo`. Required outputs: `placebo_coef_*`, sign, abs, `placebo_false_effect_*`
(vs `0.20 ×` true real-pumping step), `placebo_step_response_*`. Cadence-dependent
estimands apply (`k>1` uses the same coarse-step response objects as other
interventions).

**Smoke-only false-effect diagnostics (NON-INFERENTIAL).** 2 of 6 SMOKE S8 replicates
had `placebo_false_effect_L=1`. This is a schema/path check, not an SGI_G3 result.

---

## E. S6

**S6a (`S6a_global_memory_null`).** Topology `null5`, `C_ij=0`, local memory independently
targeted to the same `τ_relax` rule as coupled systems. v1 construction retained.
`A_ii` is **not** matched to the coupled reference.

**S6b (`S6b_matched_local_dynamics_null`).** From coupled `path5` / MED / MED (or the
cell’s gamma, including oracle `HIGH`):

```text
C_ij_null = 0
C_i0_null = C_i0_ref + Σ_j C_ij_ref
⇒ A_ii_null = A_ii_ref,  A_ij_null = 0
b_null = (I − A_null) h_eq_ref
```

`S_i`, `B_Q`, `B_R`, forcing, noise, cadence, missingness, geometry, and observation
design are preserved. Marginal variance is **not** claimed to match.

**Mathematical local-persistence matching (freeze, CALIBRATION pool, path5 MED MED):**

| quantity | coupled reference | S6a | S6b |
|---|---|---|---|
| mean `A_ii` | 0.897333 | 0.942788 | 0.897333 (exact) |
| `ρ(A)` | 0.951229 | 0.951229 | 0.945055 = max\|A_ii\| |
| `τ_relax` (weeks) | 20.000 | 20.000 | **17.695** (not retuned) |
| head variance | 7.799 | 16.612 (ratio 2.130) | 8.073 (ratio 1.035) |
| process-noise variance share | 0.352% | 0.125% | — |

S6b `τ` is shorter because the coupled MED mode is a **network** eigenvalue, not
`max|A_ii|`. Burn-in for that S6b system is 142 weeks.

**Smoke-only realized SNR/persistence (NON-INFERENTIAL).** Smoke pools G3R1/G3R2 (S6a)
and G3R1b/G3R2b (S6b). G3R2b uses `ORACLE_FAVOURABLE` (`gamma=HIGH`), so smoke-pooled
S6b `τ` mixes two systems. `snr_head` is comparable by construction. Do not read
false-edge counts from smoke as G3 evidence.

---

## F. Cadence and uncertainty

Fine step = 1 week; season = 52; analysis horizon = 520 **after** burn-in;
`k ∈ {1,2,4,13}`. Usable transitions (train/val/test):

| k | transitions | split |
|---|---|---|
| 1 | 519 | 363 / 78 / 78 |
| 2 | 259 | 181 / 39 / 39 |
| 4 | 129 | 90 / 19 / 20 |
| 13 | 39 | 27 / 6 / 6 |

**`k=1`:** if the physical-identifiability conjunction holds, moving-block bootstrap
coverage is reported vs fine `-B_Q` (`bootstrap_coverage_beta_q_physical`). Coverage is
a **diagnostic**, not an SGI_G1 gate.

**`k>1`:** physical coverage is NaN. Report `bootstrap_coverage_beta_q_pseudo_true`
and interval width only. Smoke check: 0 finite physical-coverage values at `k>1`.

**Bootstrap.** Moving-block; resampling unit = contiguous TRAIN transition blocks;
block length `max(2, ceil(2 τ_relax_realized / k))`. iid bootstrap remains prohibited.
Paired overhead ≈ **37 ms/replicate** at `n_bootstrap_analysis=200`.

---

## G. Identifiability

Absolute `S_i` / `C_ij` recovery requires **all** of:

- `k = 1`
- absolute forcing scale known
- pumping quality in `{P-EXACT, P-MULTNOISE}`
- recharge quality `R-EXACT`
- `confounding_rho = 0`
- design full rank (`rank_deficiency_max_L = 0`)
- `condition_number_L < 1e6`
- `pumping_excitation_fraction_L > 0.05`
- scenario not in `{S7, S8, S6a, S6b, S9}`

Otherwise report `A`, effective `B_Q`, `κ_ij = dt C_ij / S_i` (not conductance), and
intervention response. A `0.0` rank deficiency is not treated as falsy (that bug was
fixed in this pass).

---

## H. Analysis pipeline

`src/summarize.py` + `scripts/summarize_results.py`.

CLI: `--fixtures` or `--smoke` only. No flag, or ANALYSIS, exits 2.

Logic frozen: replicate-status handling; per-cell median/q10/q90; estimability rates;
predictive/intervention/network metrics; S6 false edges; S8 placebo false-effect;
S9 support misspecification; prediction-vs-intervention inversion; `SGI_G0`–`G3`
(G0 numeric criteria remain owned by `run_g0.py`; G1/G2 statistics parsed from the
yaml; G3 triggers include S6a hard, S6b robustness, S8 hard, prediction–intervention
inversion); data-adequacy `complexity_unsupported` when N estimability rate is 0.

Fixture classifications (tests):

| fixture | expected |
|---|---|
| all models estimable and passing | `ESTIMATED_PASSED_GATE` |
| required-cell `N = NOT_ESTIMABLE` | cell fails; rate retained; `complexity_unsupported` |
| solver failure | `FIT_FAILED`, distinct from `NOT_ESTIMABLE` |
| good prediction, poor intervention | inversion flag true |
| S6 false edges | G3 hard trigger |
| S8 false placebo | G3 hard trigger |
| S9 support misspec | visible in adequacy rows |
| oracle G2 pass + realistic `NOT_ESTIMABLE` | oracle cannot compensate |

Outputs go to `outputs/summarizer/`. No `FINAL_*` or `sweep_replicates.csv`.

---

## I. Gate definitions

**SGI_G0** — seed pool `G0`; cell `C_G0` = S0 / single / noise-free oracle. All 5 seeds
must pass. Failure blocks downstream scientific conclusions.

**SGI_G1** — pool `ANALYSIS`; model `L`; cells G1R1–G1R6 (S1 single reference; S1 `k=1`;
S1 MCAR 0.30; S2 confounding 0.60; S3 noisy recharge; S1 local model on path5).
Criteria: sign, NIRE≤0.20, no blowup, RMSE not worse than B0. `NOT_ESTIMABLE` fails
that cell. Each cell independently. Coverage excluded in v2.

**SGI_G2** — pool `ANALYSIS`; model `N`; G2R1–R2 oracle (S4 path5/star5); G2R3–R4
realistic (S5 path5/star5). Oracle cannot compensate. Also requires G3 not hard-triggered.

**SGI_G3** — pool `ANALYSIS`:

| cell | scenario | topology | role |
|---|---|---|---|
| G3R1 | S6a | null5 | hard null |
| G3R2 | S6a | null5 | oracle hard null |
| G3R1b | S6b | path5 | robustness null |
| G3R2b | S6b | path5 | oracle robustness null |
| G3R3 | S8 | single | placebo (L) |
| G3R4 | S8 | path5 | placebo |

S6a false-edge median>0.5 or fraction≥1 >0.20 → **HARD_FAILURE** (overrides G2).
S6b same statistics → **ROBUSTNESS_EVIDENCE** (does not alone override G2).
S8 `placebo_false_effect_L` fraction >0.20 → **HARD_FAILURE**.
Prediction–intervention inversion on G2 cells → **HARD_FAILURE**.

`NOT_ESTIMABLE` on a required cell fails that cell and is retained in every aggregate.

---

## J. Tests

**154 passed, 0 failed, 0 skipped** (after freeze).

New / substantially updated:

- `tests/test_v2_corrections.py` — v1 preserved; S6a vs S6b; S6b diagonal; S8 both
  channels; physical ident not just scale; bootstrap `k>1`; auth lock; seed disjointness
- `tests/test_summarizer.py` — seven fixture classifications + G3 inversion
- `tests/test_protocol.py` — onset−1 missing alignment, no TEST-head leak, no fallback
- `tests/test_estimands_and_freeze.py` — physical-S conjunction; v2 freeze path

Failure encountered and corrected in this pass: `absolute_S_identifiable` was False on a
valid `k=1` known-scale cell because `float(0.0) or 1.0` treated rank deficiency 0 as
missing. Conjunction was **not** loosened.

Existing tests were not weakened.

---

## K. SGI_G0

**PASS** (5 G0 seeds). Code hash at run matches freeze.

| criterion | value | threshold |
|---|---|---|
| `G0_transition_exact` | 1.421×10⁻¹⁴ | ≤ 1×10⁻⁹ |
| `G0_coefficient_exact` | 6.454×10⁻¹⁴ | ≤ 1×10⁻⁸ |
| `G0_storage_exact` | 4.804×10⁻¹⁵ | ≤ 1×10⁻⁸ |
| `G0_design_full_rank` | 0 | == 0 |

Rank/conditioning: rank 6, deficiency 0, cond ≈ 9.876, max VIF ≈ 17.78,
pumping excitation ≈ 0.259, smallest singular value ≈ 3.201, `n_rows_L=363`,
`τ_relax=20`, `k/τ=0.05`. This is implementation sanity, not identifiability of
field groundwater.

---

## L. Smoke

**NON-INFERENTIAL.** Engineering only.

- 129 cells × 3 SMOKE seeds = 387 replicates
- 387/387 succeeded; 0 exceptions
- all cells covered; all systems contracting; max clip 0.0294% (limit 0.1%)
- L: 387/387 `ESTIMATED`
- N: 344 `ESTIMATED`, 43 `NOT_ESTIMABLE` (21 `model_not_applicable` on `single`;
  10 `insufficient_training_rows`; 12 `no_admissible_rows`)
- S: 366 `ESTIMATED`, 21 `NOT_ESTIMABLE`
- 0 `FIT_FAILED`; no `|prediction|>1000`; `ρ(A)<1` throughout
- required G2/G3 network cells: N estimable on all smoke seeds; G1R1–G1R5 and G3R3
  N not applicable (single-node) as designed
- finite NIRE_N 91.5% (NaNs are the NOT_ESTIMABLE N cases)

Do not use these numbers to choose thresholds, drop cells, pick a model, or claim
recovery.

---

## M. Provenance

| item | value |
|---|---|
| `design_v2` hash | `b53f5594a444ae4826adfe2c47818080508a4c4b00a38fa25b4ffc483e20a8a5` |
| code hash | `5429a6378005b4152130f6b9707cc1fc61abdf3a81a83e3849530d1ea8f856fd` |
| `DESIGN_V2_FREEZE.json` sha256 | `a4235a004c4ca1fef637a29b5c2343bec347883ec242d39beafcb16719a61306` |
| `RUN_MANIFEST_V2.json` sha256 | `92318073295b5a71650486ef1ee8d19509f9304b8e30d8a8b18b162baa893cab` |
| `CODE_MANIFEST_V2.csv` sha256 | `9c16836f112099d298de357855485790617f65b0ab185df4caab104f77141cdd` |
| frozen at UTC | 2026-09-07T04:19:39 |
| Python / NumPy | 3.11.15 / 2.4.6 |
| RNG | `numpy.random.Generator(PCG64)` |
| parent checkpoint | `1b95209` |
| cells / scenarios | 129 / 12 |
| frozen systems | 17 (16 used combinations + S6b_from_path5) |
| `full_sweep_launched` | false |
| `analysis_seeds_inspected` | false |

Seed pool hashes (sizes 60 / 8 / 5 / 3): ANALYSIS
`bd6db2aac7743cc83d5d5ecd8b5f07fefe18747649e3489a5b89e7e0cb689015`; CALIBRATION
`7aedf1a97f413d4642668e5741b17c7418db60593c0246df64faaea8c8b00228`; G0
`3bbd798d908bdf08d888efb5756236757f2b9bd5fdc19bc7cbe5fe7d7725c489`; SMOKE
`d4e3c7dcd48e6f1f24713ca3113252be1642392abef9afa25db5d6b66ccac633`.

Pools remain disjoint. A future scientific-code change must invalidate `CODE_HASH` and
rerun affected outputs even if `design_v3` is not required.

---

## N. Runtime and storage

Projected **ANALYSIS** sweep: 129 cells × 60 seeds = **7740** replicates
(v1 was 7620 = 127×60; +2 cells are G3R1b and G3R2b).

| quantity | value |
|---|---|
| median / max per replicate (no bootstrap) | 116 ms / 245 ms |
| projected single-core, no bootstrap | **14.8 min** (0.25 h) |
| bootstrap overhead (paired, n=200, 6 cells) | 37 ms / replicate |
| projected if every replicate bootstrapped | **19.6 min** |
| storage | 34.4 MB (4654 bytes/record) |
| peak RSS during benchmark | ~95 MB |
| Slurm needed? | **No** (threshold was 4 h) |

Summarizer on 387 smoke rows is negligible. Preferred partitions remain those in
`design_v2.yaml` if a cluster run is later chosen; it is not required.

---

## O. Deviations

1. This pass is **uncommitted**, as instructed.
2. v2 G0 / smoke / benchmark reused the v1 output **filenames**, overwriting Phase-1
   engineering CSVs/JSON. v1 **freeze** artifacts (`DESIGN_FREEZE.json`,
   `CODE_MANIFEST.csv`, `FROZEN_SYSTEMS.csv`, `S6_VARIANCE_CHARACTERIZATION.json`)
   remain. v1 numbers remain in `CHECKPOINT_REPORT.md`.
3. Full ANALYSIS size is 7740, not 7620, because S6b added two gate cells.
4. S6b `τ_relax` is 17.695 weeks at path5 MED MED, not 20. Recorded; not retuned.
5. `CHECKPOINT_REPORT_V2.md` is written after freeze, so it is not inside `CODE_HASH`.
6. Freeze was re-run after (a) S6b timescale provenance and (b) summarizer G1/G2/G3
   wiring; hashes above are the **final** freeze.
7. G2 yaml name `strong_edge_undirected_f1` is evaluated on record column `edge_f1`.
8. G3R3 network model is `NOT_ESTIMABLE` (`single` / `model_not_applicable`); S8 G3
   uses `placebo_false_effect_L`.
9. Summarizer skips G0 `max_over_seeds` / `min_over_seeds` statistics; G0 is owned by
   `scripts/run_g0.py`.
10. ANALYSIS seed **values** were not printed or used; only the pool hash is stored.
11. Gitlink `Data-center-PUE-prediction-tool` remains dirty and untouched.

No silent v2 redesign was made in response to smoke outcomes.

---

## P. Final authorization state

```text
FULL SUBSTANTIVE SWEEP NOT RUN
```

`scripts/run_experiment.py` without `--authorize I_AUTHORIZE_THE_FULL_PREREGISTERED_SWEEP`
exits 2 with `REFUSING TO RUN`. That token was **not** passed. `summarize_results.py`
without `--fixtures`/`--smoke` also exits 2.

This checkpoint does **not** claim that `M1N` works, that `M1L` is sufficient, that
network dynamics are identifiable, that Andhra Pradesh data are adequate, that
groundwater impacts are validated, or that any planning model is ready.

The eventual substantive study must still answer: under which observation regimes can
local, spatial, and network groundwater response structures recover the counterfactual
effects of pumping accurately enough to support infrastructure planning?
