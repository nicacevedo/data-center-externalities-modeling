# BENCHMARK_DEFINITIONS.md

Seed-independent and pseudo-true benchmarks for V3. Computed in Pass 1 / Pass 1.1 from the
frozen system and, where needed, the disjoint `V3_BENCHMARK` pool. **Not** V3 ANALYSIS
outcomes.

Canonical implementation: `src_v3/benchmarks.py`, `src_v3/diagnostics.py`.
Canonical machine-readable definition: `config/design_v3.yaml → benchmark_layers`.

---

## Verified frozen model-L family (from V2 code, not preference)

Inspected in vendored `fit.py`, `models.py`, and `interventions.py`:

- L is unpenalized OLS (`lam=0`).
- Own-level coefficient `a` is **unconstrained**.
- Pumping coefficient is **unconstrained** (no sign constraint in the estimator).
- Pumping regressor is **own-node only** (`Q_obs[:, node]`). Neighbour pumping is model S,
  not L.
- `implied_transition_matrix` for L is **diagonal**: `A_ii = a_i`, `A_ij = 0`.
- Frozen `persistent_step` is applied to **node 0**.
- NIRE averages `normalized_error` over nodes whose true-response L2 norm is at least
  `nire_node_inclusion_threshold` times the max node norm, at the frozen cadence-sampled
  scoring instants (primary horizon h=26). It is therefore a **mean over included nodes of
  per-node ratios of L2 norms**, not a single global norm ratio. That algebra matters
  everywhere below.
- Multi-step evaluation recursion:
  `out[t+1] = A_hat @ out[t] + beta_q * delta_Q_interval[t]`
  with non-finite `A_hat` entries replaced by 0. There is **no** `a ∈ [0, a_max]` clamp in
  fitting or evaluation.
- `dgp.rollout` is linear with no clipping, so the paired intervention difference
  `h_intervention − h_baseline` cancels forcing, initial state and process noise exactly and
  is a deterministic function of the cell's structural construction.

---

## The four-layer decomposition

```text
F_intervention_all
    ->
F_train_true
    ->
F_train_obs
    ->
finite-sample fitted NIRE
```

### Layer 1 — `F_intervention_all`

Minimum intervention-response error attainable by the **actual frozen L response family**,
scored on the exact planning-relevant frozen NIRE scoring set (all materially affected
included nodes, all frozen scoring times, primary horizon h=26).

Deterministic given the cell's structural construction.

### Layer 2 — `F_train_true`

Intervention NIRE of the **pseudo-true one-step L target when the one-step fitting objective
is evaluated using the latent true variables** on the same cadence-specific TRAIN support:

- true head state `h_t`
- true next head `h_{t+k}`
- true pumping `Q`
- true recharge `R`

under the exact frozen cadence transformation (heads sampled at the same observation
instants; forcing summed over the same `[t, t+k)` intervals), with the same TRAIN time
support and the same admissible-row structure as the observed-data target, and the same
frozen L column set (including the S8 placebo column where the frozen design has one — the
placebo series is an exactly aggregated latent forcing channel and is uncorrupted in both
layers).

Nothing is altered: cadence, truth physics, topology, gamma and the TRAIN time horizon are
the frozen ones. The purpose is to remove measurement/proxy corruption while retaining the
current one-step training objective and the current local functional family.

### Layer 3 — `F_train_obs`

Intervention NIRE of the pseudo-true one-step target of the **actual observed-data
estimator** under the frozen observation regime, using the actual estimator-facing
quantities:

- observed/noisy lagged head
- observed pumping (including the mean-corrected unit-mean multiplicative lognormal error)
- recharge proxy (noise, lag, efficiency as the cell specifies)
- actual confounding regime
- actual missingness / admissible rows
- actual cadence

pooled over the frozen `V3_BENCHMARK` distribution. This is the asymptotic target of the
estimator actually being tested.

### Layer 4 — finite-sample fitted NIRE

Actual V3 estimator performance, `nire_persistent_step_h26_L` over the `V3_ANALYSIS` pool.
Pass 2 only.

---

## Licensed interpretation of the gaps

```text
F_intervention_all -> F_train_true
    = training-target / functional-approximation cost

F_train_true -> F_train_obs
    = asymptotic observation / proxy / forcing-data bias

F_train_obs -> fitted NIRE
    = finite-sample estimation cost
```

**These are nested benchmark comparisons, not an exact additive decomposition.** The frozen
NIRE is a mean over included nodes of per-node ratios of L2 norms; that metric algebra does
not license writing the fitted error as a sum of the benchmark levels plus differences. The
gaps are reported as differences between nested benchmark levels and must be described that
way.

**Layer 1 → Layer 2 is NOT pure "objective mismatch".** Both sides live in the same frozen
functional family, so unavoidable functional restrictions (diagonal own-lag, own-node
pumping only, one mode) remain in force on both sides. The licensed wording is
*training-target / functional-approximation gap*.

**Layer 2 → Layer 3 does not isolate one measurement channel.** Several corruption channels
move together (head measurement error, recharge proxy noise and lag, pumping error,
interaction with the confounded forcing). Isolation of an individual channel comes from
another experimental contrast (Block A for pumping, Block D for the forcing channels), not
from this gap.

**Common support is deliberate.** Layers 2 and 3 share the admissible-row support and the
confounded true forcing distribution by construction. The Layer 2 → Layer 3 gap is therefore
a statement about *value* corruption, not about row attrition and not about confounding per
se.

**`F_intervention_all ≤ F_train_true` is not asserted a priori.** `F_train_true` evaluates a
particular point of the family and `F_intervention_all` minimises over it *at the same
scoring set*, so the inequality does hold by construction there; it is verified numerically
per cell rather than assumed.

---

## Layer-1 companions

### `F_intervention_pumped`

The same Layer-1 minimisation, scored **only on the directly pumped intervention node**,
using the exact same normalized response geometry restricted to that node.

This lets the paper distinguish

```text
Can L represent the DIRECT local response?
```

from

```text
Can L represent CROSS-UNIT propagated groundwater externalities?
```

It is a diagnostic companion and never replaces the planning-relevant all-node metric.

### `neighbor_unmodeled_floor`

Under a single-node intervention the frozen L recursion drives a non-pumped node `j` only
through `beta_q[j] * delta_Q_interval[t, j]`, and `delta_Q_interval[:, j] == 0` for every
non-pumped node. With `A` diagonal the L state at `j` therefore stays **identically zero for
every admissible `(a_j, beta_q_j)`**: the own-pumping-only local family structurally cannot
propagate a withdrawal to a hydraulically affected non-pumped unit.

`neighbor_unmodeled_floor` evaluates that structural zero through the **same norm, scoring
instants and node weighting as the frozen all-node NIRE**, giving the pumped node its ideal
zero-error contribution:

```text
|| true response on materially affected non-pumped nodes ||
-----------------------------------------------------------   under the frozen NIRE weighting
|| true response on all materially affected scored nodes ||
```

Because the frozen NIRE averages *per-node* ratios and a structurally-zero prediction has
per-node normalized error exactly `||0 − true_j|| / ||true_j|| = 1`, this evaluates in closed
form to

```text
n_included_nonpumped / n_included
```

which is why realized values land on `1/2`, `2/3`, `4/5`, … as the number of materially
affected neighbours grows. **That is a consequence of the frozen metric's node weighting, not
a hydraulic-coupling threshold.** It is a known-truth representational floor induced by the
own-pumping-only local structure.

The secondary global-norm reading of the same concept is also stored, as
`neighbor_unmodeled_floor_norm_share_secondary`, so both readings are on the record.

### Exact invariant

Whenever the local family predicts zero response on the non-pumped nodes,

```text
F_intervention_all = neighbor_unmodeled_floor + F_intervention_pumped / n_included
                     (when the pumped node is included)

=> F_intervention_all >= neighbor_unmodeled_floor
```

Verified numerically per cell as `F_intervention_all_identity_residual` (realized frozen
NIRE at the certified optimum minus the closed form) and enforced as a hard invariant in
`scripts_v3/compute_benchmarks.py`.

---

## `F_intervention` global validity

**Parameter domain.** `a ∈ ℝ` (own-lag, unconstrained) and `κ ∈ ℝ` (own-node pumping
amplitude, unconstrained). The frozen L fit imposes neither a sign constraint nor a
stability box, so the benchmark may not impose one either.

**Reduction.** Only the pumped node's parameters matter (non-pumped nodes are structurally
zero, see above), and only through `out[t] = κ g_t(a)` with

```text
g_t(a) = sum_{s<t} a^{t-1-s} d_s ,   g_0 = 0
```

where `d_s` is the frozen cadence-aggregated intervention pumping increment. Profiling the
amplitude analytically (`κ | a` is a one-dimensional least-squares problem) leaves

```text
NIRE_pumped(a)^2 = 1 - c(a)^2 / Q(a)
c(a) = sum_t yhat_t g_t(a)        Q(a) = sum_t g_t(a)^2
```

with `yhat` the unit-normalised true pumped-node response.

**Why this is global, not a window.**

1. `g_1(a) = d_0` is a nonzero constant, so `Q(a) ≥ d_0² > 0` for every real `a`: the
   rational function has **no real poles**.
2. It is continuous on the two-point compactification `ℝ ∪ {±∞}` with limit exactly
   `yhat_last²` (ratio of leading coefficients), handled explicitly.
3. A global optimum therefore exists and is attained either at a real stationary point or in
   that limit.
4. `d/da (c²/Q) = c·(2c'Q − cQ')/Q²`, so the stationary set is exactly the real root set of
   the polynomial `c·(2c'Q − cQ')`. All of its real roots are enumerated via
   companion-matrix eigenvalues (degree ≤ 74 at k=1, ≤ 20 at k=4), each polished in a tight
   deterministic bracket.
5. An **independent** dense scan over the compactified coordinate `u = a/(1+|a|)` on the
   **closed** interval `[-1, 1]`, with the analytic endpoint limits, covers the same complete
   extended parameter line and must agree.

`F_intervention_global_certified` is True only when the two independent global strategies
agree within tolerance and the optimum is not attained at infinity. Paper language for this
verification is **numerically globally verified over the full extended-real response
parameterization**, not a formal interval-arithmetic / root certificate. If the flag were
ever False for a cell, the quantity is reported under the weaker name
`F_intervention_verified_domain` with `F_intervention_domain` stating the exact numerical
domain, and the paper claim is weakened accordingly. Realized Pass-1.1 state: the flag is
True for all 21 cells, domain `a ∈ ℝ ∪ {±∞}`, `κ ∈ ℝ`. The scientific interpretation
(pumped-node representability, all-node spatial-propagation limitation, neighbour-unmodeled
structural floor, true-variable training target, observed-variable pseudo-true target) is
unchanged.

**Value reporting.** The rational form *locates* the optimum; the value there is *reported*
from the direct residual norm, because `sqrt(1 − ρ²)` has absolute resolution only
`sqrt(machine eps) ≈ 1.5e-8` when the true minimum is zero. Both are stored
(`F_intervention_pumped` and `F_intervention_ratio_form_pumped`).

---

## Monte Carlo pseudo-true benchmarks and their convergence

`F_train_true` and `F_train_obs` are Monte-Carlo approximated pseudo-true quantities: pooled
TRAIN-row unpenalized OLS (the same solver model L uses) across the `V3_BENCHMARK` pool, with
the pooled coefficients pushed through the frozen NIRE routine on the cell's system.

`V3_BENCHMARK` is **n = 128**, fixed prospectively in Pass 1.1 before any V3 ANALYSIS
replicate exists. At the Pass-1 value of n = 16 several single-node / cadence-4 cells showed
split-half benchmark-NIRE instability of order 0.07–0.10, too large relative to the
preregistered 0.05 NIRE SESOI for a benchmark carrying major interpretive weight.

**Nested-prefix convergence diagnostics** are preregistered at

```text
16   32   64   128
```

for **both** `F_train_true` and `F_train_obs`. `SeedSequence(entropy).spawn(n)` is
sequential, so `spawn(128)[:m] == spawn(m)`: the prefixes are strictly nested subsets of one
deterministic frozen pool, not four separate pools. Verified in
`scripts_v3/freeze_protocol_v3.py` and in the test suite.

At each prefix the reported quantities are, at minimum:

- pseudo-true own-state coefficient(s) (`a`, at the pumped node and averaged over nodes)
- pseudo-true pumping coefficient(s) (`beta_q`, same)
- benchmark intervention NIRE
- pseudo-true recharge coefficient

together with the deltas `16→32`, `32→64`, `64→128`.

**These values may not be used to adaptively select n**, nor to alter cells, sigma, gamma,
`n_ANALYSIS`, hypotheses or SESOI. If the benchmark were still grossly unstable at 128 the
protocol STOPS for external review rather than expanding the pool post hoc.

`F_train_true` / `F_train_obs` use no V3 ANALYSIS seeds.

**Licensed claim (Layer 2).** Better finite data cannot repair the intervention behaviour of
the current one-step-trained latent-true population target.

**Not licensed.** "No member of the local model class can do better" — that statement belongs
to `F_intervention_all`, and only for the frozen family at the frozen scoring set.

---

## Recombination diagnostics

`nire_recomb_trueA_hatB` and `nire_recomb_hatA_trueB` are **algebraic recombination
diagnostics for the retained local terms** of the frozen model-L response family: the own-lag
diagonal and the own-node pumping amplitude.

- For single-node and uncoupled systems they are strong algebraic diagnostics that separate
  persistence error from pumping-response error, because those two terms are the whole
  family.
- For coupled systems they are **not** an exact decomposition and **not** a complete
  partition of intervention error. The omitted neighbour-state propagation lies outside the
  local family altogether and is not decomposed by these two quantities; it is quantified
  separately and exactly by `neighbor_unmodeled_floor`.

---

## `neighbour_flux_share`

A synthetic dimensionless coupling-materiality diagnostic internal to this known-truth
system. Not a directly observable Andhra Pradesh field quantity.

Also stored: realized `tau_relax`, spectral radius, mean diagonal transition.

---

## Monte Carlo vs deterministic

- System quantities (`tau_relax`, `neighbour_flux_share`, `F_intervention_all`,
  `F_intervention_pumped`, `neighbor_unmodeled_floor`) are deterministic given the cell's
  structural construction.
- `F_train_true` and `F_train_obs` are Monte-Carlo approximated pseudo-true quantities.
  Nested-prefix convergence diagnostics are stored.
