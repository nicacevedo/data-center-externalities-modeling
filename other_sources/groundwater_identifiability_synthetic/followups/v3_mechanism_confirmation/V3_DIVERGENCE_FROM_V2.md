# V3_DIVERGENCE_FROM_V2.md

Vendored V2 modules live in `src_v3/`. Any vendored file **not** listed here
as changed must match its V2 parent byte-for-byte (see `V2_PARENT_MANIFEST.csv`).

## New files (no V2 parent)

- `src_v3/rng.py`
- `src_v3/modes.py`
- `src_v3/reliability.py`
- `src_v3/diagnostics.py`
- `src_v3/benchmarks.py`
- `src_v3/summarize_v3.py`

## Intentional changes to vendored files

### `src_v3/__init__.py`

V3 package pin of frozen V2 parent hashes. Not byte-identical to V2 `src/__init__.py`.

### `src_v3/design.py`

Retargeted module root, V3 design/code hash globs, V2 parent hash helpers,
`OBS_FAV_GAMMA_FREE` override token, `resolve_v3_cell` / `v3_all_cells` /
`resolved_cell_table`, empty-`gates` safety.

### `src_v3/dgp.py`

`system_seed_mode` (`orthogonal_v3` drops `gamma_label` from the structural
seed; `legacy_v2` restores V2). Named-substream forcing, placebo, and process
noise. Dummy consumption of reserved initial-condition streams in named mode.

### `src_v3/observations.py`

Named-substream pumping/recharge degradation, head noise, missingness, and
block-outage starts. Shared `pumping_degradation_z` for the σ ladder.
`pumping_degradation_z` stored in `bundle.meta` for CRN tests (observation
noise, not system truth).

### `src_v3/evaluation.py`

Required legal `(rng_mode, system_seed_mode)` pairs. StreamBank wiring.
V3 diagnostics: signed `A` diagonal error, recombination NIRE, residualized
reliability, `neighbour_flux_share`, `predicted_edge_count`, placebo
collinearity, pairing metadata. No V3 SESOI gates.

### `src_v3/plan.py`

`all_cells` returns the frozen 21 V3 cells.

## Unchanged vendored parents (must match V2)

- `src_v3/fit.py`
- `src_v3/identifiability.py`
- `src_v3/interventions.py`
- `src_v3/metrics.py`
- `src_v3/models.py`
- `src_v3/summarize.py`
