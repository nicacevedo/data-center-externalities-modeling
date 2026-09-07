# DESIGN_FREEZE_V3.md

V3 prospective mechanism-confirmation follow-up. Isolated under
`followups/v3_mechanism_confirmation/`. Does not mutate frozen V2.

Current checkpoint: **PASS 1.1 — FINAL PRE-ANALYSIS FREEZE**.

## Evidence hierarchy

- V2 = confirmatory known-truth qualification study
- POST-V2 AUDIT = post-hoc mechanism diagnosis (preserved verbatim)
- V3 = prospective mechanism-confirmation follow-up motivated by that audit

V3 may explain V2. V3 may not overturn V2.
`LOCAL_RESPONSE_STATUS = LOCAL_RESPONSE_NOT_IDENTIFIED` and
`NETWORK_SUPPORT_FINAL = NOT_EARNED` remain the authoritative V2 statuses
under every V3 outcome.

## Frozen scientific design

- 21 unique cells; n = 200 ANALYSIS seeds per cell (Pass 2 only); 4,200 prospective
  substantive replicates
- Blocks A (5), A′ (2), B (4), C (2 additional), D (8 = 2×2×2)
- Named-substream CRN for substantive work
- `orthogonal_v3` structural seeding for substantive work
- Legal mode pairs only:
  - `(legacy_sequential, legacy_v2)` — V2 bit-for-bit parity
  - `(named_substreams, orthogonal_v3)` — all V3 substantive work
- `gates: {}` — no V3 qualification gates
- SESOI 0.05 NIRE / 0.10 rate / 0.05 reliability discrepancy are
  decision-relevance reference magnitudes only
- `gamma=NONE` uses the existing validated V2 zero-coupling `build_system()` branch under V3
  orthogonal structural-seed semantics
- Pumping error is **mean-corrected unit-mean multiplicative lognormal**
  (`E[m]=1`; median `exp(-σ²/2)`). The mathematical corruption model is unchanged.
- Intervals are pointwise Monte Carlo uncertainty intervals, not simultaneous
  family-wise bands
- `D_PM_RN_R3` is an external-consistency anchor, not a numeric 0.600 gate.
  Hard implementation validation is G1R1/G2R3/G3R3 bit-for-bit parity under
  legacy modes.

## Pass 1.1 changes relative to the Pass 1 freeze

```text
cells changed                 = 0
resolved cell count           = 21   (unchanged)
ANALYSIS seed count changed   = 0    (n = 200 per cell, unchanged)
BENCHMARK pool count changed  = 16 -> 128
```

1. **Benchmark pool.** `V3_BENCHMARK` raised from 16 to 128 seeds, fixed prospectively before
   any V3 ANALYSIS replicate exists. Motivation: at n=16 several single-node / cadence-4
   cells showed split-half benchmark-NIRE instability of order 0.07–0.10, too large relative
   to the 0.05 NIRE SESOI for a benchmark carrying major interpretive weight. Nested-prefix
   convergence diagnostics are preregistered at 16 / 32 / 64 / 128 for both training
   benchmarks. Benchmark n is not adapted after inspecting convergence.
2. **Benchmark definitions.** The single conceptual `F_train` is replaced by two
   scientifically distinct quantities, `F_train_true` (latent-true one-step target) and
   `F_train_obs` (observed-data one-step estimator target), inside a frozen four-layer
   decomposition. `F_intervention` is split into the planning-relevant `F_intervention_all`
   and the diagnostic `F_intervention_pumped`, and the exact known-truth
   `neighbor_unmodeled_floor` is added. See `BENCHMARK_DEFINITIONS.md`.
3. **`F_intervention` global validity.** Replaced the finite `a ∈ [-2.5, 2.5]` search with an
   exact global argument over the complete algebraic response family (`a ∈ ℝ ∪ {±∞}`,
   `κ ∈ ℝ`): amplitude profiled analytically, all stationary points of the resulting pole-free
   rational function enumerated as polynomial roots, explicit limit at infinity, cross-checked
   against an independent compactified full-line scan.
4. **Recombination language.** Documented as algebraic recombination diagnostics for the
   retained local terms; explicitly not an exact decomposition or complete partition for
   coupled systems.
5. **Executable frozen launcher.** `scripts_v3/run_v3.py` now executes exactly the frozen
   21 × 200 ANALYSIS plan when the correct authorization token is supplied and every frozen
   invariant matches. Pass 2 requires zero source-code changes.
6. **Frozen analysis summarizer.** `src_v3/summarize_v3.py` produces every preregistered
   Block A / A′ / B / C / D output, benchmark merge, benchmark convergence, paired contrasts,
   pointwise intervals, estimability and prediction-versus-intervention diagnostics with no
   post-result code edit. No gates, no support status, no V2 reinterpretation.

Nothing in Block A's Tier-1 measurement-error design and nothing in Block D's 8 cells was
weakened or redesigned.

## Pass 1.1 authorization state

```text
V3_ANALYSIS_POOL_FROZEN = true
V3_ANALYSIS_REPLICATES_RUN = 0
V3_ANALYSIS_OUTCOMES_INSPECTED = false
FULL ANALYSIS LAUNCHER = IMPLEMENTED AND FROZEN
FULL ANALYSIS LAUNCHER = NOT EXECUTED
```

Mechanical materialization of the V3 ANALYSIS seed pool for hashing and
disjointness is permitted. Individual seed values are not printed, inspected,
or used to generate data in Pass 1 / Pass 1.1.

## Future-paper claim boundaries

Permitted from V3 *if supported by the frozen results*: pumping measurement error
attenuates intervention magnitude; that attenuation is quantitatively consistent with
residualized regressor reliability; the one-step true-variable training target differs
from the intervention-optimal target; observation/proxy corruption moves the one-step
pseudo-true estimator target further from the intervention target; an own-pumping-only
local response family cannot propagate withdrawal effects to hydraulically affected
non-pumped units; network recovery depends on both physical signal strength and the
broader identification regime; specific forcing channels create placebo attribution.

Not permitted from V3 alone: Andhra Pradesh groundwater parameters are identified;
actual AP pumping-error magnitude follows the synthetic model; M1L is empirically
validated; M1N is validated; a calibrated real groundwater network exists; no local
groundwater model can represent cross-node dynamics.

The strongest structural statement is restricted to **the frozen own-pumping, one-mode
local response family** under the known-truth intervention.

## Canonical artifacts in V3_DESIGN_HASH

- `config/design_v3.yaml`
- `DESIGN_FREEZE_V3.md`
- `BENCHMARK_DEFINITIONS.md`
