# PROTOCOL.md

V3 Pass-1 / Pass-1.1 / Pass-2 protocol. Canonical scientific plan:
`/home/nacevedo/RA/data-center-externalities-modeling/V3 GW PLAN.md`

## Pass 1 (first checkpoint)

1. Preserve post-V2 audit verbatim.
2. Freeze V3 design and code hashes.
3. Vendor V2 scientific modules into `src_v3/`.
4. Implement named substreams, orthogonal structural seeding, 21 cells,
   reliability, recombination, benchmarks, Block D factorial.
5. Tests green; V2 hashes unchanged.
6. Deterministic sanity (engineering).
7. V2 bit-for-bit parity on G1R1, G2R3, G3R3 × 3 ANALYSIS seeds (legacy modes).
8. Compute seed-independent benchmarks for all 21 cells.
9. Engineering smoke: 21 cells × 3 V3_SMOKE seeds.
10. STOP. Do not run `21 × 200` ANALYSIS.

## Pass 1.1 (final pre-analysis freeze — this checkpoint)

Narrow correction and verification pass. No new experiment design. 21 cells, n=200,
Blocks A / A′ / B / C / D, named-substream CRN, `orthogonal_v3` seeding, full 2×2×2 S8
factorial, no V3 gates, V2 immutable — all preserved unchanged.

1. Split the pseudo-true training benchmark into `F_train_true` and `F_train_obs`.
2. Freeze the four-layer benchmark decomposition
   `F_intervention_all -> F_train_true -> F_train_obs -> fitted NIRE`.
3. Raise `V3_BENCHMARK` from 16 to 128, prospectively, with nested-prefix convergence
   diagnostics at 16 / 32 / 64 / 128.
4. Establish `F_intervention` global validity over the complete algebraic response family.
5. Split intervention representability into `F_intervention_all` and
   `F_intervention_pumped`; add the exact `neighbor_unmodeled_floor`.
6. Tighten recombination-diagnostic language.
7. Make `scripts_v3/run_v3.py` execute the frozen 21 × 200 plan under authorization.
8. Complete the frozen analysis summarizer.
9. Re-run all validation: V2 + V3 test suites, 9-replicate V2 parity, deterministic sanity,
   benchmarks, 63-replicate engineering smoke.
10. STOP. Do not run `21 × 200` ANALYSIS.

### Four-layer benchmark decomposition (frozen)

```text
Layer 1  F_intervention_all   minimum intervention-response error attainable by the actual
                              frozen L response family, on the frozen planning-relevant
                              scoring set
Layer 2  F_train_true         intervention error of the latent-true-variable one-step
                              pseudo-true training target
Layer 3  F_train_obs          intervention error of the observed-variable one-step
                              pseudo-true estimator target
Layer 4  fitted NIRE          actual finite-sample V3 estimator performance (Pass 2)
```

Licensed gap readings:

```text
F_intervention_all -> F_train_true   training-target / functional-approximation cost
F_train_true -> F_train_obs          asymptotic observation / proxy / forcing-data bias
F_train_obs -> fitted NIRE           finite-sample estimation cost
```

**These are nested benchmark comparisons, not an exact additive decomposition.** The frozen
NIRE is a mean over included nodes of per-node ratios of L2 norms, and that algebra does not
license writing the fitted error as a sum of the benchmark levels plus differences. Layer 1 →
Layer 2 is a *training-target / functional-approximation* gap, not pure "objective mismatch",
because unavoidable functional restrictions of the frozen family remain in force on both
sides. Layer 2 → Layer 3 does not isolate an individual measurement channel; Layers 2 and 3
deliberately share the admissible-row support and the confounded forcing distribution, so
that gap is about value corruption rather than row attrition or confounding per se.

Companions: `F_intervention_pumped` (direct local response only) and
`neighbor_unmodeled_floor` (exact known-truth representational floor of the own-pumping-only
local structure — **not** a hydraulic-coupling threshold). Invariant:
`F_intervention_all >= neighbor_unmodeled_floor`.

Full definitions: `BENCHMARK_DEFINITIONS.md`.

### Recombination diagnostics

`nire_recomb_trueA_hatB` and `nire_recomb_hatA_trueB` are **algebraic recombination
diagnostics for the retained local terms** (own-lag diagonal, own-node pumping amplitude).
For single-node / uncoupled systems they are strong algebraic diagnostics of
persistence-versus-pumping-response error. For coupled systems they are **not** an exact
decomposition and **not** a complete partition of intervention error: the omitted
neighbour-state propagation lies outside the local family and is quantified separately and
exactly by `neighbor_unmodeled_floor`.

## Pass 2 (not this task)

Requires `--authorize <TOKEN>` where `<TOKEN>` is the frozen
`v3.analysis_authorization_token` in `config/design_v3.yaml`. Do not paste the token into
ad-hoc notes; read it from the frozen design.

Zero source-code changes required:

```bash
python scripts_v3/freeze_protocol_v3.py        # verify / refresh hashes
python scripts_v3/run_v3.py --preflight-only   # verify invariants; runs nothing
python scripts_v3/run_v3.py --authorize <TOKEN>
python scripts_v3/summarize_v3.py --analysis   # if a separate summarizer pass is wanted
```

The launcher refuses without the exact token. With the token it verifies, and refuses on any
mismatch of: legal + substantive mode pair, `gates: {}`, 21 resolved cells, cell ids against
the config, n = 200 ANALYSIS seeds per cell, 4,200 expected replicates, seed uniqueness and
uint64 range, `V3_DESIGN_HASH`, `V3_CODE_HASH`, resolved-cell manifest hash, `V3_ANALYSIS`
seed-pool hash, frozen resolved cell count, V2 parent design/code hashes, pairwise seed-pool
disjointness, and absence of pre-existing ANALYSIS replicate outputs. Only then does it
execute exactly the frozen plan and hand the records to
`src_v3.summarize_v3.summarize_analysis`.

`execute_plan(..., authorized=True)` is the only way to run the `V3_ANALYSIS` pool. The test
suite never passes it, so no test can execute a substantive seed.

## Modes

| Use | rng_mode | system_seed_mode |
|---|---|---|
| V2 parity | `legacy_sequential` | `legacy_v2` |
| All V3 substantive work | `named_substreams` | `orthogonal_v3` |

Mixed pairs raise. The ANALYSIS launcher additionally requires the substantive pair, and the
ANALYSIS summarizer refuses input whose rows are not uniformly substantive.

## Interval semantics

Reported 95% bootstrap and Wilson intervals are pointwise Monte Carlo
uncertainty intervals for their individual estimands. They are not
simultaneous family-wise confidence bands over all V3 contrasts.

The across-seed bootstrap resamples **seeds** as the unit (10,000 percentile resamples),
preserving pairing; its stream is derived from the contrast label by SHA-256 and never from
the analysis seed values.
