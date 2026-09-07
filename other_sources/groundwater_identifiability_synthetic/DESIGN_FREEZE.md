# DESIGN FREEZE — design_v1

This file is a **canonical scientific-design artifact**. Together with
`config/design_v1.yaml` it determines `DESIGN_HASH`, recorded in
`outputs/provenance/DESIGN_FREEZE.json`.

`DESIGN_FREEZE_SCOPE = config/design_v1.yaml + DESIGN_FREEZE.md`

## Change policy

| Change | Requires `design_v2`? | Requires rerun? | Changes which hash |
|---|---|---|---|
| Any scientific content (equations, thresholds, cells, seeds, regimes, gates) | **Yes** | Yes, of all affected experiments | `DESIGN_HASH` |
| Pure implementation bugfix with scientific design unchanged | No | **Yes**, of all affected outputs | `CODE_HASH` only |
| Cosmetic/non-scientific code change (docstrings, formatting) | No | Yes (hash changes, outputs revalidated) | `CODE_HASH` only |

A post-freeze bugfix never silently keeps stale outputs. Every change is appended to the
changelog at the bottom of this file.

## 1. Why this experiment exists

The repository lists the dynamic groundwater network `(A, B_R, B_Q)` as `\NotIdentified`
in `main_documents/master.tex`, and the OCWD modules explicitly refuse to estimate it
(`B7_execution: prohibited_in_this_task`, `NETWORK_MODEL_JUSTIFICATION = UNRESOLVED`). The
Andhra Pradesh preflight records `AP9 = FAIL`.

This experiment does not fit any of those. It asks, on known synthetic truth, **what level
of reduced-order groundwater response structure could be identified and trusted for
intervention-aware planning at all**, and under exactly which observation regime. A
negative result is a successful outcome.

Scope boundary: see `SCOPE.md`. This qualifies the reduced-order head/pumping/recharge
response core only. It does not validate GRACE, data assimilation, Bayesian inference, or
Andhra Pradesh hydrogeology.

## 2. Scientific choices frozen here (not only in the YAML)

### 2.1 Realized hydraulic timescale is authoritative

`tau_relax` is **computed from the generated transition matrix eigensystem**, not read off
the regime label:

```
tau_relax_realized = -1 / log( spectral_radius(A) )
```

`LOW = 4`, `MED = 20`, `HIGH = 80` fine steps are **targets**. The freeze script asserts the
realized value matches its target to within 2%. Every cadence result is reported against the
dimensionless ratio `k / tau_relax_realized`; a bare `k` is never interpreted.

### 2.2 Burn-in and horizon

The **520-fine-step analysis horizon begins strictly AFTER burn-in**. Burn-in is
`max(104, ceil(8 * tau_relax_realized))` fine steps, with 104 as the frozen floor.

The floor alone is insufficient for the HIGH-memory regime: `104 / 80 = 1.3` relaxation
times leaves roughly 27% of the initial transient, so the analysis window would not be
stationary. Extending burn-in to `8 * tau` reduces the residual transient to `exp(-8) ~ 3e-4`
in every regime while leaving the analysis horizon exactly as frozen. Stationarity is
verified by `test_analysis_window_is_stationary`.

### 2.3 Contraction margin

`delta = 0.005`, chosen because `HIGH` memory implies `rho(A) = exp(-1/80) = 0.98758`, which
a tighter margin such as `0.02` would reject. `delta = 0.005` admits `tau_relax` up to
`-1/log(0.995) = 199.5` fine steps, comfortably above the `HIGH` target of 80. The separate
discretization margin `delta_diag = 0.05` keeps `A` entrywise nonnegative with positive
diagonal, which is what makes the response physically monotone.

Contraction requires strictly positive boundary leakage `C_i0 > 0` at every node; with
`C_i0 == 0` the Laplacian has a zero eigenvalue and `rho(A) = 1`. Non-contracting systems
are declared out of scope for v1 rather than left implicit.

### 2.4 Process noise is a flux disturbance

`eps` sits inside the storage balance next to `R` and `Q`, so it carries their units and
enters head as `dt * eps_i / S_i`. An additive head-state disturbance is a different object
and is **not** used in v1. This is stated because the two choices give different
signal-to-noise interpretations and different apparent identifiability.

### 2.5 Boundary intercept

`b_i = dt * C_i0 * h_i_b / S_i` with `h_b = 5.0`, deliberately nonzero so every estimator
must absorb a real intercept instead of inheriting a convenient zero.

### 2.6 The DGP is a restricted special case

`B_R = B_Q = dt * diag(1/S)` and a Laplacian-plus-leakage `A` are **restrictions** on the
repository's general `(A, B_R, B_Q)` family, not a reparameterization of it. The restriction
`B_R == B_Q` is itself stressed in `S7.recharge_efficiency_mismatch`, where the truth uses
`B_R != B_Q` while the estimator retains the restricted family. See
`REPOSITORY_PREMISE_CONFLICTS.md` C4.

### 2.7 Estimands change with cadence

The exact coarse dynamics are

```
h_{t+k} = A^k h_t + sum_{r=0}^{k-1} A^{k-1-r} B u_{t+r}
```

With only the interval aggregate `U = sum_r u_{t+r}` observed there is in general **no exact
`B_k`** with `sum_r A^{k-1-r} B u_{t+r} = B_k U` for all forcing paths. Therefore:

- at `k = 1`, direct fine-parameter recovery of `A` and `B_Q` is a **primary** metric;
- at `k > 1` it is **not** primary. `A_hat` is compared to `A^k` where meaningful, flagged as
  state-transition recovery rather than clean parameter recovery, because `A_hat` also
  absorbs forcing-aggregation effects. The primary targets become protected transition,
  intervention, and impulse-response recovery.
- Any coarse coefficient that is reported is the **pseudo-true projection**

  ```
  B_k_pseudo := argmin_B  E_forcing || sum_{r=0}^{k-1} A^{k-1-r} B u_{t+r} - B U ||^2
  ```

  the population L2 projection onto the aggregate-forcing linear family under the frozen
  forcing process. It is forcing-process dependent, computed in the evaluation layer from
  truth by Monte Carlo (400 draws), and is always labelled pseudo-true. It is never called
  "the" coarse parameter.

### 2.8 Absolute physical parameters are conditional

Absolute `S_i` and `C_ij` are recoverable **only when all four** conditions hold: pumping is
observed on a true absolute scale; the pumping-channel parameterization `B_Q = dt*diag(1/S)`
holds; excitation is sufficient as measured by the rank/condition/excitation diagnostics
rather than assumed; and `k = 1`. Otherwise the study reports **effective response
coefficients** (`kappa_hat`, `beta_hat_Q`, impulse responses) and reporting physical storage
or conductance is prohibited.

A regime with unknown pumping scale (`P-SCALEBIAS`, `P-SPATIALAGG`, `R-SCALE`) can **never**
be scored as planning-ready for absolute withdrawal constraints, however good its relative
recovery is. `RELATIVE` and `ABSOLUTE` intervention recovery are separate reported columns.

### 2.9 kappa is not conductance

The estimated coefficient on `(h_j - h_i)` is `kappa_ij = dt * C_ij / S_i`, an **effective
directed coupling**. Consequences: `kappa_ij == kappa_ji` is **not** enforced, because
`S_i != S_j`; edge support is undirected; physical `C_ij` is reconstructed only where
absolute `S_i` is identifiable.

The physics-consistency diagnostic uses a **bounded symmetric normalized discrepancy**, not
the raw ratio `(kappa_ij S_i)/(kappa_ji S_j)`, which is unstable near zero:

```
D_phys_ij = |kappa_hat_ij*S_hat_i - kappa_hat_ji*S_hat_j|
            / ( |kappa_hat_ij*S_hat_i| + |kappa_hat_ji*S_hat_j| + eps_stab )
```

with `eps_stab = 1e-9`, so `D_phys` lies in `[0, 1]`. `D_phys` near 0 indicates directional
consistency with a common physical conductance. It is computed **only** where absolute `S`
is identifiable and both directional estimates are nondegenerate
(`kappa_hat >= strong_edge_threshold` in both directions); otherwise it is reported as null,
never as a number.

### 2.10 The candidate graph is geometry-only

The candidate graph comes from node coordinates plus a frozen radius rule
(`d_cand = 2.5`, kNN fallback `k = 3`). It **never** inspects the true edge set; a test
builds two systems with identical geometry and different true edges and asserts the
candidate graphs are identical.

In favourable topologies the true graph is **nested inside** the candidate rule *by design of
the truth*, which is a designer-side choice recorded here, not estimator-side peeking.
`path5_hidden` (scenario `S9`) deliberately places a genuine link at distance 4.0, outside
the rule, so `N` cannot represent it. True strong edges outside the candidate set are counted
as **false negatives**, not excused.

### 2.11 Masked-node protocol is monitoring loss, not zero-shot

Zero-shot held-out-node evaluation is **not performed**. `B0/L/S/N` use node-specific
parameters, so a node absent from training has no parameters and zero-shot inference at it is
not mathematically possible; that would require an explicitly shared-parameter model, which
v1 does not implement.

What is performed instead: the masked node **has** train/validation history and estimable
parameters; at the preregistered protected-test onset its head observations are withheld for
a contiguous 12-cadence-step horizon; recursive prediction starts from the **final admissible
pre-mask head observation**; afterwards only its own predicted state, its own pumping and
recharge proxy, observed heads of non-masked neighbours, and calendar features may be used;
no withheld head may enter the recursion. The leak test poisons every withheld entry with a
large sentinel and asserts the forecast is bit-identical to the NaN-masked run.

This evaluates **propagation through monitoring loss**, and is described as nothing else.

### 2.12 Paired interventions

True baseline and true intervention trajectories share initial state, recharge/background
forcing, and the process-noise realization `eps`, so common disturbances cancel exactly and
the estimand is the paired difference. Because both the DGP and the estimators are linear
(with forcing clipping asserted inactive), the paired difference is the deterministic
structural response; `test_paired_intervention_noise_cancels` asserts it is invariant to the
noise realization, and `test_zero_intervention_zero_delta` asserts a null intervention gives
exactly zero.

### 2.13 Uncertainty is diagnostic, not a gate

The iid bootstrap is invalid for these dependent series and is prohibited. The interval
estimator is a **moving-block bootstrap** with block length `max(2, ceil(2*tau_relax/k))`
cadence steps, defined before use. **Coverage is excluded from `SGI_G1` in v1** and reported
as a diagnostic alongside separately reported Monte Carlo variability. Promotion to a gate
criterion is deferred to a possible v2, and only after the interval estimator is itself
validated on `S0`/`S1`.

### 2.14 Nonnegative L1 without cvxpy

`scipy.optimize.lsq_linear` provides no L1 path. Because `kappa >= 0`, the L1 penalty is the
**linear** term `lambda * 1'kappa`, so the problem

```
minimize_{beta free, kappa >= 0}  || y - X beta - Z kappa ||^2 + lambda * 1'kappa
```

is a smooth convex QP with simple bounds. The unpenalized block is profiled out analytically
(`M = I - X(X'X)^-1 X'`, objective `||M(y - Z kappa)||^2 + lambda*1'kappa`) and the bounded
problem in `kappa` is solved with `L-BFGS-B` and an analytic gradient. Pumping and recharge
coefficients are never penalized and never sign-constrained, so the `SGI_G1` sign-recovery
metric stays non-vacuous. Correctness is tested three ways: against `lsq_linear` at
`lambda = 0`, against SLSQP and a coordinate-descent reference at `lambda > 0`, and by KKT
conditions.

### 2.15 Reference regime and grid rationale

Every 1-D stress curve is a deviation from exactly one frozen reference point
(`reference_regime` in the YAML). The generic fractional factorial was **removed**: it would
leave its estimable interactions undocumented and its aliasing unstated. The replacement is
interpretable curves plus five named two-factor grids. Stated openly as a limitation: no
formal estimate of higher-order interactions outside those five grids is produced.

### 2.16 S6 marginal variance: matching attempted, measured to be infeasible, rejected

The original intent was to calibrate the null scenario's process-noise scale so its
stationary marginal head variance matched the coupled `path5 / MED / MED` reference. This was
attempted at freeze time on the dedicated `CALIBRATION` seed pool and **rejected on
measurement**, before any substantive run:

| quantity | value |
|---|---|
| coupled reference head variance | 7.799 |
| coupled reference at zero process noise | 7.771 |
| null head variance | 16.612 |
| null at zero process noise | 16.591 |
| null / reference variance ratio | 2.130 |
| process-noise variance share, coupled reference | **0.35%** |
| process-noise variance share, null | **0.13%** |

Two facts follow. First, the process-noise channel is not a variance knob at all: it moves
head variance by a fraction of a percent, because head variance is dominated by the
integrated low-frequency forcing. Second, the required direction is downward, and the null
variance already exceeds the reference at *zero* process noise. Matching would require
changing the forcing process or the relaxation time, both of which are controlled factors.

The difference itself is structural rather than a nuisance: coupling drains node-specific
forcing through additional boundary paths, so a coupled aquifer genuinely has lower head
variance than an uncoupled one under the same forcing. Suppressing it would distort the truth
the null scenario exists to represent.

What replaces it: the quantity that governs inference difficulty is already equalized by
construction, because `snr_head` ties observation-noise sd to **realized** head sd, so `S5`
and `S6` face the same head signal-to-noise ratio at the same nominal SNR. Realized head sd,
observation-noise sd, realized SNR, detrended SNR, and the process-noise variance share are
reported for every replicate, and `S5`-vs-`S6` comparisons — hence `SGI_G2` versus `SGI_G3` —
must be read against them. The measurements are written to
`outputs/provenance/S6_VARIANCE_CHARACTERIZATION.json` as part of the frozen record.

### 2.16b v1 is deliberately an observation-limited regime

The measurement above has a consequence beyond `S6`. At the reference process-noise level the
flux disturbance contributes well under 1% of head variance, while observation noise at the
reference SNR contributes far more. The reference regime is therefore **observation-limited**,
which is the realistic case for groundwater monitoring but is a restriction that must be
stated rather than left implicit.

Because a scenario suite that only ever probes one side of that balance would be incomplete,
`curve_process_noise` spans `process_noise_sd` in `{0.05, 0.25, 1.0}`, taking the flux
disturbance from negligible, through comparable to observation noise, to dominant. Conclusions
drawn at the reference regime apply to the observation-limited case, and the curve is what
licenses any statement about the process-noise-limited case.

Related reporting caveat: `snr_head` is defined against **total** head sd, which the annual
swing dominates. A nominal SNR of 10 is therefore harsher than it sounds for the
non-seasonal variability that actually identifies the forcing response, so
`realized_snr_head_detrended` and `seasonal_variance_share` are reported alongside it.

### 2.17 Seed discipline

Four disjoint pools with distinct root entropies: `G0` (5), `CALIBRATION` (8), `SMOKE` (3),
`ANALYSIS` (60). Disjointness is asserted by test. **Engineering smoke results exist only to
detect implementation failures and measure runtime.** They must not alter scientific
thresholds, select favourable regimes, tune gates, or support substantive claims, and no
smoke seed may appear in any substantive output.

## 3. Gate populations

`SGI_G0`–`SGI_G3` are defined by **enumerated cells, seed pools, aggregation rules and
statistics** in `gates:` of `config/design_v1.yaml`. No vague term such as "relevant
replicates" or "realistic regimes" is used anywhere in a gate definition.

Every required cell must pass **on its own**; oracle or otherwise easy cells cannot
compensate for failure in a required realistic cell. Combination across required cells is
logical AND. For multi-node cells, node-level values are reduced to a replicate-level value
by the mean over evaluated nodes **before** the across-seed statistic is taken.

`G1R6` deliberately applies a **local** model to a genuinely coupled truth and is kept in the
required set: its failure would be a scientific result about local-model adequacy under
coupling, not an implementation defect.

## 4. Execution phases

Phase 1, authorized: `pytest -> SGI_G0 -> engineering smoke -> runtime/storage benchmark`,
terminating at a **mandatory external-review checkpoint**. The full Monte Carlo sweep,
summarization, figures, final report/status, and the Andhra Pradesh requirements document
are Phase 2 and require explicit authorization.

## 5. Changelog

| Date | Change | Design or code | Rerun triggered |
|---|---|---|---|
| 2026-09-06 | `design_v1` initial freeze | design | n/a (first freeze) |
