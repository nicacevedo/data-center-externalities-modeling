# PROVENANCE_AND_LAYERS.md

## Layers

1. Frozen V2 design/code hashes (immutable).
2. Post-V2 independent scientific audit (preserved verbatim; post-hoc).
3. V3 design freeze (`V3_DESIGN_HASH`).
4. V3 code freeze (`V3_CODE_HASH`).
5. V3 seed pools (`V3_DETERMINISM`, `V3_BENCHMARK`, `V3_SMOKE`, `V3_ANALYSIS`).
6. Benchmarks (Pass 1 / Pass 1.1; no ANALYSIS outcomes).
7. Engineering smoke (Pass 1 / Pass 1.1; non-inferential).
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

Files under `outputs/` are in neither hash, so `outputs/provenance/DESIGN_V3_FREEZE.json` can
record both hashes without circularity. The ANALYSIS launcher recomputes both live and
compares them against that frozen file: editing any V3 source file changes `V3_CODE_HASH` and
the launcher refuses until `scripts_v3/freeze_protocol_v3.py` is re-run.

## Pass 1.1 provenance change

```text
cells changed                 = 0
resolved cell count           = 21   (unchanged)
ANALYSIS seed count changed   = 0    (n = 200 per cell, unchanged)
BENCHMARK pool count changed  = 16 -> 128
benchmark definitions changed = yes  (four-layer decomposition; see BENCHMARK_DEFINITIONS.md)
```

The `V3_BENCHMARK` pool is one deterministic frozen pool. Because
`SeedSequence(entropy).spawn(n)` is sequential, `spawn(128)[:m] == spawn(m)` for
`m ∈ {16, 32, 64}`: the preregistered convergence prefixes are strictly nested subsets, and
the Pass-1 16-seed pool is exactly the first prefix of the Pass-1.1 pool. Prefix nesting and
per-prefix hashes are recorded in `outputs/provenance/SEED_POOL_V3.json` and verified in
`scripts_v3/freeze_protocol_v3.py` and the test suite.

Because both the design artifacts and the V3 source changed, Pass 1.1 issues a new
`V3_DESIGN_HASH` and a new `V3_CODE_HASH`. The 21-cell resolved scientific matrix itself is
unchanged, which the resolved-cell manifest hash records independently of the design hash.

## Seed pools

Mechanical materialization of `V3_ANALYSIS` for hashing/disjointness is
allowed. Outcomes are not inspected in Pass 1 / Pass 1.1.

`V3_BENCHMARK` (and each of its convergence prefixes) is pairwise disjoint from
`V3_DETERMINISM`, `V3_SMOKE`, `V3_ANALYSIS` and from the V2 `G0`, `CALIBRATION`, `SMOKE` and
`ANALYSIS` pools.

```text
V3_ANALYSIS_POOL_FROZEN = true
V3_ANALYSIS_REPLICATES_RUN = 0
V3_ANALYSIS_OUTCOMES_INSPECTED = false
```

## Provenance artifacts

| artifact | content |
|---|---|
| `outputs/provenance/DESIGN_V3_FREEZE.json` | both hashes, seed-pool hashes, cell count, resolved-cell manifest hash, benchmark-pool block, Pass-1.1 change summary, launcher and summarizer descriptors |
| `outputs/provenance/DESIGN_V3_FREEZE_MANIFEST.csv` | per-file sha256 of the design artifacts |
| `outputs/provenance/CODE_MANIFEST_V3.csv` | per-file sha256 of every file in `V3_CODE_HASH` |
| `outputs/provenance/RESOLVED_CELLS_V3.csv` | the 21 resolved cells, every scientific factor explicit |
| `outputs/provenance/SEED_POOL_V3.json` | pool hashes, sizes, benchmark prefix hashes, disjointness statement |
| `outputs/provenance/RUN_MANIFEST_V3.json` | phase, mode pair, hashes, authorization state |
| `outputs/provenance/V2_PARENT_MANIFEST.csv` | vendored-vs-parent sha256 with changed/unchanged classification |
| `outputs/benchmarks/BENCHMARKS_V3.{csv,json}` | the four-layer benchmark values and companions for all 21 cells |
| `outputs/benchmarks/BENCHMARK_CONVERGENCE_V3.csv` | nested-prefix convergence at 16/32/64/128 |
| `outputs/determinism/V2_PARITY_REPORT.json` | 9-replicate V2 bit-for-bit parity |
| `outputs/determinism/DETERMINISM_V3.json` | engineering deterministic sanity |
| `outputs/smoke/*` | 63-replicate engineering smoke, explicitly non-inferential |
