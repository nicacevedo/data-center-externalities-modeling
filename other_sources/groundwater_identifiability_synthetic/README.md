# Synthetic known-truth groundwater identifiability experiment

`design_v1` · **Phase 1 complete: stopped at the pre-sweep external-review checkpoint**

## What this is

A known-truth synthetic **identifiability and falsification** experiment. It asks one
question:

> What level of reduced-order groundwater response structure can actually be identified and
> trusted for intervention-aware infrastructure planning, under realistic observation
> limitations?

It is **not** an Andhra Pradesh fit, an OCWD fit, a PSCC reconstruction, a siting
optimization, a MODFLOW model, a GNN experiment, or an attempt to show that a network model
must succeed. **A negative result is a successful outcome.** See `SCOPE.md`.

## Status

| Stage | State |
|---|---|
| Design implemented and frozen | done |
| `pytest` | done |
| `SGI_G0` deterministic sanity | done |
| Engineering smoke (all cells) | done |
| Runtime / storage benchmark | done |
| **Full Monte Carlo sweep** | **NOT LAUNCHED — requires explicit authorization** |
| Summarization, figures, final report, AP requirements | not started (Phase 2) |

`scripts/run_experiment.py` refuses to run without an explicit authorization token, so the
sweep cannot start by accident.

## Layout

```text
├── README.md                        this file
├── SCOPE.md                         scientific boundary; what is and is not qualified
├── DESIGN_FREEZE.md                 canonical design artifact (part of DESIGN_HASH)
├── REPOSITORY_PREMISE_CONFLICTS.md  conflicts between task premises and the repository
├── config/design_v1.yaml            canonical design artifact (part of DESIGN_HASH)
├── src/
│   ├── design.py                    design loading, cell resolution, seeds, hashing
│   ├── dgp.py                       synthetic truth  (TRUTH — never seen by estimators)
│   ├── observations.py              observation model (the only boundary truth crosses)
│   ├── models.py                    design matrices for the B0/L/S/N ladder
│   ├── fit.py                       estimation, incl. the nonnegative-L1 solver
│   ├── identifiability.py           rank / conditioning / excitation diagnostics
│   ├── interventions.py             paired counterfactuals; masked-node protocol
│   ├── metrics.py                   NIRE, edge recovery, D_phys, pseudo-true coarse B
│   ├── evaluation.py                replicate runner and gate evaluation
│   └── plan.py                      enumeration of every cell in the frozen plan
├── scripts/
│   ├── freeze_protocol.py           stage 1: validate + freeze + hash
│   ├── run_g0.py                    stage 2: SGI_G0
│   ├── run_smoke.py                 stage 3: engineering smoke (NOT science)
│   ├── benchmark.py                 stage 4: runtime/storage projection, then STOP
│   └── run_experiment.py            phase 2: full sweep (authorization-gated)
├── tests/                           131 tests
└── outputs/                         provenance, G0 result, smoke, benchmark
```

## Reproducing Phase 1

Run in this order; each stage refuses to proceed if the design hash has moved.

```bash
python -m pytest tests -q
python scripts/freeze_protocol.py
python scripts/run_g0.py
python scripts/run_smoke.py
python scripts/benchmark.py
```

## The five things most likely to be misread

1. **`B0`/`L`/`S`/`N` are estimator rungs of a synthetic ladder, not planning models.** They
   are not `M0`/`M0S`/`M1L`/`M1N` and must not be cited as such.
2. **`kappa_ij = dt*C_ij/S_i` is an effective directed coupling, not a conductance.** It is
   deliberately not symmetric, because `S_i != S_j`.
3. **Direct parameter recovery is primary only at cadence `k = 1`.** At `k > 1` there is in
   general no exact coarse coefficient for interval-aggregated forcing, so the targets become
   transition, intervention, and impulse-response recovery, and any reported coarse
   coefficient is an explicitly labelled pseudo-true projection.
4. **Masked-node evaluation measures propagation through monitoring loss.** It is not
   zero-shot prediction at an unseen aquifer node, which node-specific parameters make
   mathematically impossible.
5. **Smoke output is not a scientific result.** It exists to detect implementation failures
   and measure runtime. It may not set thresholds, choose regimes, tune gates, or support any
   claim.

## Gates

Named `SGI_G0`–`SGI_G3` to avoid colliding with the `G1`–`G10` already defined in
`other_sources/ocwd_groundwater_feasibility`. Each is defined by enumerated cells, seed
pools, aggregation rules, and statistics in `config/design_v1.yaml`; every required cell must
pass on its own, and oracle cells cannot compensate for a failing realistic cell.

Only `SGI_G0` has been evaluated in Phase 1. `SGI_G1`–`SGI_G3` require the full sweep.
