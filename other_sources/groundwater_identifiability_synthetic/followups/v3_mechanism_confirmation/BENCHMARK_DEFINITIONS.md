# BENCHMARK_DEFINITIONS.md

Seed-independent benchmarks for V3. Computed in Pass 1 from the frozen system
and, where needed, the disjoint `V3_BENCHMARK` pool. Not V3 ANALYSIS outcomes.

## Verified frozen model-L family (from V2 code)

Inspected in vendored `fit.py`, `models.py`, and `interventions.py`:

- L is unpenalized OLS (`lam=0`).
- Own-level coefficient `a` is **unconstrained**.
- Pumping coefficient is **unconstrained** (no sign constraint in the estimator).
- Pumping regressor is **own-node only** (`Q_obs[:, node]`). Neighbour pumping
  is model S, not L.
- `implied_transition_matrix` for L is **diagonal**: `A_ii = a_i`, `A_ij = 0`.
- Frozen `persistent_step` is applied to **node 0**.
- NIRE averages `normalized_error` over nodes whose true-response L2 norm is
  at least `nire_node_inclusion_threshold` times the max node norm, at the
  frozen cadence-sampled scoring instants (primary horizon h=26).
- Multi-step evaluation recursion:
  `out[t+1] = A_hat @ out[t] + beta_q * delta_Q_interval[t]`
  with non-finite `A_hat` entries replaced by 0. There is **no**
  `a ∈ [0, a_max]` clamp in fitting or evaluation.

`F_intervention` therefore minimizes frozen persistent-step NIRE over that
actual algebraic family. No invented physical sign constraint. No invented
stability box. Parameters that overflow the finite-horizon recursion are
excluded only because NIRE is then undefined.

## F_train

Population / pseudo-true one-step model-L parameters under the V3 cell's
exact data-generating process, cadence, deterministic seasonal structure,
intervention-independent forcing distribution, and TRAIN-transition support.

This is **not** a claim that the DGP is strictly stationary. The frozen truth
has finite-horizon seasonal structure.

Approximation: pooled TRAIN-row OLS across the `V3_BENCHMARK` pool
(entropy `20260907030004`, n=16), then the pooled coefficients are pushed
through the frozen NIRE routine on the cell's system.

`F_train` uses no V3 ANALYSIS seeds.

**Licensed claim:** better finite data cannot repair the intervention behavior
of the current one-step-trained population target.

**Not licensed:** "no member of the local model class can do better."

## F_intervention

Minimum frozen persistent-step NIRE in the actual L family:

- Node 0 may have a direct local pumping response `κ_0`.
- Non-pumped nodes do **not** receive an artificial direct Q coefficient.
- Any true response at non-pumped nodes induced through hydraulic coupling
  is therefore potentially unrepresentable by L.
- Objective scores the same nodes and times as frozen NIRE.

Optimization: closed-form `κ | a` for node 0; dense-grid search over `a`
plus local refinement; independent verification on a denser grid.

## neighbour_flux_share

A synthetic dimensionless coupling-materiality diagnostic internal to this
known-truth system. Not a directly observable Andhra Pradesh field quantity.

Also stored: realized `tau_relax`, spectral radius, mean diagonal transition.

## Monte Carlo vs deterministic

- System quantities (`tau_relax`, `neighbour_flux_share`, `F_intervention`)
  are deterministic given the cell's structural construction.
- `F_train` is a Monte-Carlo approximated pseudo-true quantity. Convergence
  diagnostics (split-half NIRE, coefficient MC SE) are stored.
