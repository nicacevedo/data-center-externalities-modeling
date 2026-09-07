# DESIGN_FREEZE_V3.md

V3 prospective mechanism-confirmation follow-up. Isolated under
`followups/v3_mechanism_confirmation/`. Does not mutate frozen V2.

## Evidence hierarchy

- V2 = confirmatory known-truth qualification study
- POST-V2 AUDIT = post-hoc mechanism diagnosis (preserved verbatim)
- V3 = prospective mechanism-confirmation follow-up motivated by that audit

V3 may explain V2. V3 may not overturn V2.
`LOCAL_RESPONSE_STATUS = LOCAL_RESPONSE_NOT_IDENTIFIED` and
`NETWORK_SUPPORT_FINAL = NOT_EARNED` remain the authoritative V2 statuses
under every V3 outcome.

## Frozen scientific design

- 21 unique cells; n = 200 ANALYSIS seeds per cell (Pass 2 only)
- Blocks A (5), A′ (2), B (4), C (2 additional), D (8 = 2×2×2)
- Named-substream CRN for substantive work
- Legal mode pairs only:
  - `(legacy_sequential, legacy_v2)` — V2 bit-for-bit parity
  - `(named_substreams, orthogonal_v3)` — all V3 substantive work
- `gates: {}` — no V3 qualification gates
- SESOI 0.05 NIRE / 0.10 rate / 0.05 reliability discrepancy are
  decision-relevance reference magnitudes only
- `gamma=NONE` uses the existing validated V2 zero-coupling `build_system()`
  branch under V3 orthogonal structural-seed semantics
- Pumping error is mean-corrected unit-mean multiplicative lognormal
  (`E[m]=1`; median `exp(-σ²/2)`). The mathematical corruption model is unchanged.
- Intervals are pointwise Monte Carlo uncertainty intervals, not simultaneous
  family-wise bands
- `D_PM_RN_R3` is an external-consistency anchor, not a numeric 0.600 gate.
  Hard implementation validation is G1R1/G2R3/G3R3 bit-for-bit parity under
  legacy modes.

## Pass 1 authorization state

```
V3_ANALYSIS_POOL_FROZEN = true
V3_ANALYSIS_REPLICATES_RUN = 0
V3_ANALYSIS_OUTCOMES_INSPECTED = false
```

Mechanical materialization of the V3 ANALYSIS seed pool for hashing and
disjointness is permitted. Individual seed values are not printed, inspected,
or used to generate data in Pass 1.

## Canonical artifacts in V3_DESIGN_HASH

- `config/design_v3.yaml`
- `DESIGN_FREEZE_V3.md`
- `BENCHMARK_DEFINITIONS.md`
