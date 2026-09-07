# Pre-sweep checkpoint report — for external review

`design_v1` · Phase 1 complete · **the full Monte Carlo sweep has NOT been launched**

Executed exactly the authorized sequence and stopped:

```
design implementation -> design freeze -> pytest -> SGI_G0 -> engineering smoke
-> runtime/storage benchmark -> STOP
```

No substantive analysis was run, and no scientific conclusion is drawn anywhere in this
report. Everything below is design, implementation validity, or cost.

---

## A. Hashes and provenance

| item | value |
|---|---|
| `DESIGN_HASH` | `6e70d37874f9895a3fc089b1f3a982cd8033a1bb2201153b418492bbba41bdcc` |
| `CODE_HASH` | `94ce983d26c715ecf431e5f35f8256deadd2c6ebe48a4a276d8fd3233c8aa8ca` |
| design artifacts hashed | `config/design_v1.yaml`, `DESIGN_FREEZE.md` |
| scientific code files hashed | 24 (individually in `outputs/provenance/CODE_MANIFEST.csv`) |
| frozen at | 2026-09-07 T02:41 UTC |
| Python / NumPy | 3.11.15 / 2.4.6 |
| RNG | `numpy.random.Generator(PCG64)`, seeded per `(pool, cell, seed)` |
| `design_status` | `FROZEN` |
| `full_sweep_launched` | `false` |

Both hashes were re-verified against the freeze record after the last code change; they
match. `DESIGN_FREEZE.md` is hashed as a design artifact because it contains scientific
choices, not just narrative.

Seed pools are disjoint by construction and hashed individually:

| pool | n | purpose |
|---|---|---|
| `ANALYSIS` | 60 | substantive inference only (unused so far) |
| `CALIBRATION` | 8 | pre-freeze characterization only |
| `G0` | 5 | deterministic sanity check |
| `SMOKE` | 3 | engineering only; excluded from all inference |

## B. Frozen regimes

16 systems validated at freeze. Realized relaxation time is computed from the transition
matrix eigensystem, not from the nominal label, and hits its target exactly in every case
(`tau_deviation = 0.0` throughout).

| topology | memory | realized `tau_relax` | `rho(A)` | true edges | candidate pairs | decoys |
|---|---|---|---|---|---|---|
| `path5` | LOW | 4.0 | 0.7788 | 4 | 7 | 3 |
| `path5` | MED | 20.0 | 0.9512 | 4 | 7 | 3 |
| `path5` | HIGH | 80.0 | 0.9876 | 4 | 7 | 3 |
| `star5` | MED | 20.0 | 0.9512 | 4 | 10 | 6 |
| `bridge6` | MED | 20.0 | 0.9512 | 7 | 12 | 5 |
| `path5_hidden` | MED | 20.0 | 0.9512 | 5 | 7 | 3 |
| `null5` | MED | 20.0 | 0.9512 | 0 | 7 | 7 |
| `single` | MED | 20.0 | 0.9512 | 0 | 0 | 0 |

All systems are contracting. The 520-week analysis horizon begins **after** burn-in, which is
set per system (104–641 fine steps) rather than fixed. Time base by cadence, in
transitions split train/validation/test:

| cadence (weeks) | transitions | train / val / test | cadence / `tau_relax` at MED |
|---|---|---|---|
| 1 | 519 | 363 / 78 / 78 | 0.05 |
| 2 | 259 | 181 / 39 / 39 | 0.10 |
| 4 | 129 | 90 / 19 / 20 | 0.20 |
| 13 | 39 | 27 / 6 / 6 | 0.65 |

`path5_hidden` deliberately places 1 true edge outside the candidate set; every other
topology has `true_edges_outside_candidates = 0`.

## C. Tests

134 tests, all passing, in 7.2 s.

| file | n | covers |
|---|---|---|
| `test_dgp.py` | 49 | state equation, contraction, stationarity, forcing, clipping, reproducibility |
| `test_g0_and_design.py` | 20 | exact recovery, transition algebra, design integrity, gate namespace |
| `test_protocol.py` | 20 | splits, train-only preprocessing, masked-node leakage, pairing |
| `test_solver.py` | 20 | nonnegative-L1 vs `lsq_linear`, SLSQP, coordinate descent, KKT |
| `test_estimands_and_freeze.py` | 15 | cadence-dependent estimands, row admissibility, label discipline |
| `test_no_truth_leakage.py` | 10 | signature introspection, runtime tripwire, AST checks on split usage |

The leakage guards are adversarial rather than nominal: the masked-node test poisons every
withheld value with a `1e9` sentinel and requires bit-identical output, and the split test
parses the AST of `fit_ladder` to confirm selection reads only `VALIDATION`.

## D. SGI_G0 — deterministic implementation sanity

**PASS on all 5 G0 seeds.** Under noiseless, fully observed, cadence-1 conditions the
estimator recovers the truth to machine precision, which is what this gate exists to
establish.

| criterion | value | threshold |
|---|---|---|
| `G0_transition_exact` | 1.42e-14 | 1e-9 |
| `G0_coefficient_exact` | 6.45e-14 | 1e-8 |
| `G0_storage_exact` | 4.80e-15 | 1e-8 |
| `G0_design_full_rank` | 0 deficiency | 0 |

Design conditioning at G0: rank 6, condition number 9.88, max VIF 17.8, pumping excitation
fraction 0.259.

## E. Engineering smoke — validity only, not science

381 replicates over 127 cells × 3 smoke seeds. **0 failures, 127/127 cells covered, all
systems contracting.** Wall time 46 s.

Metric availability, and the reason for each gap:

| quantity | finite | explanation |
|---|---|---|
| `rmse_test_L` | 100% | — |
| `condition_number_L` | 100% | — |
| `nire_persistent_step_h26_L` | 100% | — |
| `nire_persistent_step_h26_N` | 91.3% | single-node topologies, where N does not exist |
| `edge_f1` | 91.1% | single-node cells, plus N unfittable at 50% missingness |
| `masked_node_nmpe_N` | 88.7% | 50% missingness and cadence 13, where the horizon barely fits |

Every gap is now attributable rather than silent: `estimability_status_{B0,L,S,N}` and
`masked_node_status*` are populated on every replicate. This matters because "the network
model is not estimable at this observation quality" is a *result* on the data-adequacy map,
and it must be distinguishable from a crash or a missing column.

Max forcing clipping across all 127 cells is 0.029%, against the frozen 0.1% limit.

## F. Runtime and storage

| quantity | value |
|---|---|
| per-replicate median / max | 122 ms / 206 ms |
| projected sweep, 127 cells × 60 seeds = **7,620 replicates** | **15.2 min single-core** |
| same, if every replicate is bootstrapped (upper bound) | 19.6 min |
| bootstrap overhead, paired measurement | +35 ms/replicate |
| projected output storage | 31.0 MB (4,269 bytes/record) |
| peak RSS | 91 MB |
| SLURM needed | **no** |

Slowest cells are `G2R2` (206 ms), `G2R1` (201 ms), `CURVE_curve_confounding_0p0` (201 ms).

## G. Proposed final sweep size

**127 cells × 60 analysis seeds = 7,620 replicates**, single-core, ~15 min (~20 min if every
replicate is bootstrapped), ~31 MB. The
cost is low enough that seed count is not the binding constraint; 60 was chosen for stable
medians and rank statistics rather than to fit a budget. Awaiting authorization.

---

## H. Deviations from the approved plan

Five, all pre-sweep, all recorded in the frozen design.

**1. S6 marginal head variance is NOT force-matched.** The plan called for calibrating the
null scenario's process noise to match the coupled reference's marginal head variance. This
was attempted on the calibration seeds and is infeasible: process noise contributes 0.35% of
head variance at the reference level, so it is not a variance knob, and the null already has
2.13× the reference variance at *zero* process noise. The difference is structural —
coupling drains node-specific forcing through additional boundary paths — so suppressing it
would distort the truth the null scenario exists to represent. Instead `snr_head` is defined
against realized head sd, which equalizes the quantity that actually governs inference
difficulty, and realized variances are reported per replicate.
**Consequence for review: `SGI_G2` vs `SGI_G3` comparisons must be read against the reported
realized variances, which differ by roughly 2× in absolute terms.** Full rationale in
`DESIGN_FREEZE.md` §2.16; measurements in `outputs/provenance/S6_VARIANCE_CHARACTERIZATION.json`.

**2. A `process_noise_sd` stress curve was added** (`{0.05, 0.25, 1.0}`). The measurement
above shows the reference regime is strongly **observation-limited**. Conclusions drawn there
would not license any claim about the process-noise-limited case, so the curve now spans
negligible, comparable, and dominant flux disturbance. See `DESIGN_FREEZE.md` §2.16b.

**3. The S7 latent climate factor is multiplicative, not additive.** As an additive AR(1) it
left only ~2.5 sd of headroom above zero at the seasonal trough and drove this cell to 2.5%
forcing clipping — an *undocumented nonlinearity* in the one scenario whose misspecification
is supposed to be exactly characterized. It is now
`R = R_base * exp(f_t - log_sd^2/2)`, scaled so the induced absolute sd at mean recharge
still equals the frozen `common_factor_sd = 0.20`. Recharge is strictly positive by
construction and the cell now contributes zero clipping. Confounder strength is unchanged.

**4. The masked-node protocol gained two deterministic rules.** Both follow the frozen
wording rather than relaxing it. The recursion starts at the last instant the node was
*actually observed* at or before onset−1, since the design says "final **admissible**
pre-mask head observation"; anchoring rigidly at onset−1 discarded 10% of replicates for no
scientific reason. And when the frozen preferred node index is uninstrumented — unavoidable
once `observed_node_fraction < 1`, and universal at 0.4 — the protocol falls back to the
nearest observed node, ties toward the lower index. Together these raised masked-node
availability from 59% to 89% with no change to what is being measured.

**5. Estimability is now recorded as a first-class outcome.** `estimability_status_*`,
`median_admissible_train_rows_*`, and `n_cols_design_*` are populated on every replicate.
This was not in the plan but the data-adequacy map is unreadable without it.

### Non-deviation worth flagging

At 50% MCAR the N rung has ~9.5 median admissible training rows against ~7 columns, so the
solver correctly refuses to fit it, and `edge_f1` is legitimately absent there. This is
implementation behaving correctly, and it is a preview of the kind of finding the sweep is
designed to produce — but it is measured on smoke seeds and is **not** a result. It is
recorded here only so a reviewer does not mistake the empty cells for a defect.

## I. Repository discipline

`git status --porcelain` at the repository root:

```
 M Data-center-PUE-prediction-tool
?? other_sources/groundwater_identifiability_synthetic/
```

The entire module is confined to one new untracked directory. Nothing outside it was created
or modified. The `Data-center-PUE-prediction-tool` gitlink was already dirty before this work
began and was deliberately left untouched; a test asserts its recorded index SHA is unchanged.

Premise/repository conflicts found while implementing — the gate namespace collision with
`ocwd_groundwater_feasibility`, the absent `M0R`/`M1S` model labels, the restricted DGP form,
and the execution-instruction conflict — are documented in `REPOSITORY_PREMISE_CONFLICTS.md`.

## J. What is NOT established

`SGI_G0` is an implementation sanity check. It shows the estimator recovers a known truth
under ideal conditions; it says nothing about whether any rung is identifiable under
realistic observation, which is the actual research question and requires the sweep.
`SGI_G1`–`SGI_G3` are unevaluated. Nothing in this report bears on GRACE, data assimilation,
Bayesian implementation, or Andhra Pradesh hydrogeology; see `SCOPE.md`.
