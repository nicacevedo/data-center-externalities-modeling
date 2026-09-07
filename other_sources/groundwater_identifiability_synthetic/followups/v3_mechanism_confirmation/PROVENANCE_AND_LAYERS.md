# PROVENANCE_AND_LAYERS.md

## Layers

1. Frozen V2 design/code hashes (immutable).
2. Post-V2 independent scientific audit (preserved verbatim; post-hoc).
3. V3 design freeze (`V3_DESIGN_HASH`).
4. V3 code freeze (`V3_CODE_HASH`).
5. V3 seed pools (`V3_DETERMINISM`, `V3_BENCHMARK`, `V3_SMOKE`, `V3_ANALYSIS`).
6. Benchmarks (Pass 1; no ANALYSIS outcomes).
7. Engineering smoke (Pass 1; non-inferential).
8. V3 ANALYSIS (Pass 2 only).

## Hash scopes

`V3_DESIGN_HASH` covers:

- `config/design_v3.yaml`
- `DESIGN_FREEZE_V3.md`
- `BENCHMARK_DEFINITIONS.md`

`V3_CODE_HASH` covers:

- `src_v3/*.py`
- `scripts_v3/*.py`
- `tests_v3/*.py`

V2 `src/*.py`, `scripts/*.py`, `tests/*.py` are **not** in `V3_CODE_HASH`.

## Seed pools

Mechanical materialization of `V3_ANALYSIS` for hashing/disjointness is
allowed. Outcomes are not inspected in Pass 1.

```
V3_ANALYSIS_POOL_FROZEN = true
V3_ANALYSIS_REPLICATES_RUN = 0
V3_ANALYSIS_OUTCOMES_INSPECTED = false
```
