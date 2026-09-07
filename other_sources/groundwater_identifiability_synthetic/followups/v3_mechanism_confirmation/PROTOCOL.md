# PROTOCOL.md

V3 Pass-1 / Pass-2 protocol. Canonical scientific plan:
`/home/nacevedo/RA/data-center-externalities-modeling/V3 GW PLAN.md`

## Pass 1 (this checkpoint)

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

## Pass 2 (not this task)

Requires `--authorize I_AUTHORIZE_THE_V3_MECHANISM_CONFIRMATION_SWEEP`.

## Modes

| Use | rng_mode | system_seed_mode |
|---|---|---|
| V2 parity | `legacy_sequential` | `legacy_v2` |
| All V3 substantive work | `named_substreams` | `orthogonal_v3` |

Mixed pairs raise.

## Interval semantics

Reported 95% bootstrap and Wilson intervals are pointwise Monte Carlo
uncertainty intervals for their individual estimands. They are not
simultaneous family-wise confidence bands over all V3 contrasts.
