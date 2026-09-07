# DESIGN FREEZE — design_v2

This is the canonical scientific-design artifact for the **final pre-analysis** protocol.
Together with `config/design_v2.yaml` it determines `DESIGN_HASH`.

`DESIGN_FREEZE_SCOPE = config/design_v2.yaml + DESIGN_FREEZE_V2.md`

`design_v1.yaml` and `DESIGN_FREEZE.md` are preserved unchanged as historical Phase-1
evidence. They are **not** part of the v2 hash.

Parent checkpoint commit: `1b95209 [Feature] GW synthetic`.

A post-freeze code bugfix does not require `design_v3` if scientific design is unchanged,
but it MUST change `CODE_HASH` and invalidate/rerun affected outputs.

No `ANALYSIS` seed is inspected in this freeze.

---

## What v2 changes relative to v1

See `DESIGN_V1_TO_V2_CHANGELOG.md` for the classified list. Scientific choices frozen here
are the ones that were not already frozen in v1, or that supersede a v1 choice.

v1 choices that remain in force (time base, memory targets, stability margins, DGP form,
geometry-only candidate graph, pairing, nonnegative-L1, smoke/analysis seed disjointness,
SGI namespace) are not restated at length. If v1 and v2 conflict, **v2 wins**.

---

## 1. Masked-node protocol (supersedes v1 §2.12 / design_v1 start_instant_rule)

Interpretation remains **monitoring-loss propagation for a previously observed node**, not
zero-shot prediction at an unseen aquifer node.

Frozen rule:

1. Select the evaluation node from the topology table **before missingness is realized**:
   index 0 for `single`/`star5`, index 2 for `path5`/`path5_hidden`/`bridge6`/`null5`.
2. Do **not** adaptively fall back to a nearer or easier node after missingness is realized.
   If the frozen target is unobserved or lacks sufficient train/validation history,
   `status = NOT_ESTIMABLE` (reason `target_node_unobserved` or `unavailable_mask_anchor`).
3. At TEST onset, withhold that node's head for a contiguous horizon of 12 cadence steps
   (or the remaining test length if shorter).
4. Find the last admissible pre-mask observation at instant `t_anchor < TEST_onset`.
5. If `t_anchor < TEST_onset - 1`, recursively propagate internally from `t_anchor` up to
   TEST onset. Those warm-forward predictions are **not scored**.
6. Score only predictions aligned with heads at instants
   `onset, onset+1, ..., onset+horizon-1` (TEST-onset truth and subsequent protected TEST
   times).
7. No withheld TEST head may re-enter the recursion. Neighbour carry-forward remains
   permitted for non-masked stations only.

v1's nearest-observed-node fallback and "start scoring from the early anchor" are
**withdrawn**. They mixed a temporal offset into the scored horizon.

---

## 2. S8 placebo (supersedes v1 s8_placebo_construction)

v1 offered the placebo **instead of** real pumping. That is not a conditional placebo test.

v2: the estimator receives **both** `Q_real_observed` (the ordinary pumping channel of that
observation regime) and `P_placebo` (a separate pumping-like series correlated with
recharge). Truth is

```text
h_{t+1} = A h_t + b + B_R R_t - B_Q Q_real,t + 0 * P_placebo,t + B_Q eps_t
```

The diagnostic is whether the estimator assigns a nonzero response to `P_placebo`
**conditional on** real pumping. Cadence-dependent estimands apply: at `k > 1` the placebo
coefficient is an effective coarse response, not a fine-step physical coefficient.

False-effect rule, frozen: `abs(placebo_step_response) > 0.20 * abs(true_real_pumping_step_response)`.

---

## 3. Null networks: S6a kept, S6b added

**S6a global-memory null** is v1's `null5` construction: `C_ij = 0`, local memory independently
targeted to the same `tau_relax` as coupled systems via boundary leakage. Marginal head
variance is **not** force-matched.

**S6b matched-local-dynamics null** is new. From the coupled `path5 / MED / MED` reference:

```text
C_ij_null = 0
C_i0_null = C_i0_ref + sum_j C_ij_ref
A_ii_null = A_ii_ref
A_ij_null = 0
```

`S_i`, `B_Q`, `B_R`, forcing, process noise, measurement noise, cadence, missingness,
geometry, and observation design are preserved. The unforced equilibrium is preserved by

```text
b_null = (I - A_null) h_eq_ref,   h_eq_ref = (I - A_ref)^{-1} b_ref
```

Do **not** claim exact marginal-variance matching. Realized head variance, SNR, local
persistence (`mean A_ii`), spectral radius, excitation, and false-edge counts are reported
for both families.

S6a false-edge exceedance is a **hard** SGI_G3 trigger. S6b false-edge exceedance is
**robustness evidence**: scored separately; an S6b-only trigger does not override SGI_G2.

---

## 4. Cadence-correct uncertainty

Moving-block bootstrap, block length `max(2, ceil(2 * tau_relax_realized / k))` TRAIN
cadence steps, resampling unit = contiguous blocks of one node's training transitions.
iid bootstrap remains prohibited.

- At `k = 1` and only where `physical_parameter_identifiability` is true: coverage may be
  compared to fine-step `-B_Q` (`bootstrap_coverage_beta_q_physical`).
- At `k > 1`: never compare a fitted coarse coefficient to fine-step `B_Q`. Coverage, if
  reported, is against the pseudo-true coarse estimand
  (`bootstrap_coverage_beta_q_pseudo_true`). Interval width is always a diagnostic.

Coverage is **not** an SGI_G1 hard gate.

---

## 5. Absolute physical `S_i` / `C_ij` recovery

All of the following are required. Absolute pumping scale known is necessary, not sufficient.

- `k = 1`
- absolute forcing scale known (`P-EXACT` or `P-MULTNOISE`)
- `R-EXACT`
- `confounding_rho = 0`
- design full rank, condition number `< 1e6`, pumping excitation fraction `> 0.05`
- scenario not in `{S7, S8, S6a, S6b, S9}`

Otherwise report `A`, effective `B_Q`, `kappa_ij = dt C_ij / S_i`, and intervention
response. Do not label those as physical storage or conductance.

---

## 6. Estimability is a first-class outcome

Every replicate/model records one of `NOT_ESTIMABLE`, `FIT_FAILED`, `ESTIMATED`, with a
reason code. Gate aggregation maps `ESTIMATED` onto `ESTIMATED_FAILED_GATE` /
`ESTIMATED_PASSED_GATE`. `NOT_ESTIMABLE` is never dropped. A required realistic cell that
is `NOT_ESTIMABLE` means that complexity is unsupported under that regime. Oracle cells
cannot compensate.

---

## 7. Process-noise stress curve

v2 pre-analysis addition, not tuned from results. Levels `{0.05, 0.25, 1.0}` on S5/path5.
Reference level `0.05`. Role: distinguish observation-limited from process-limited
identification. Do not infer from smoke.

---

## 8. Analysis pipeline frozen pre-analysis

`scripts/summarize_results.py` is part of the scientific code hash. Its aggregation,
gate evaluation, estimability handling, and classification logic are frozen before any
`ANALYSIS` seed is touched. It may be developed on smoke schema and hand-constructed
fixtures only.

---

## 9. Time base (reaffirmed)

Fine step = 1 week (interpretation). Seasonal period = 52. Burn-in floor = 104, adaptive
`max(104, ceil(8 * tau_relax_realized))`. Analysis horizon = 520 **after** burn-in.
Cadences `{1, 2, 4, 13}`. Realized `tau_relax` from the transition-matrix eigensystem;
targets 4 / 20 / 80. If `rho(A)` is 0 or 1, `tau_relax` is reported as non-finite rather
than inferred from the nominal label.
