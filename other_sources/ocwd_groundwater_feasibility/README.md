# OCWD Groundwater Data-Feasibility Benchmark

This package audits whether public Orange County Water District (OCWD)
groundwater-state, pumping, recharge, river, intervention, and tracer records
can support a future reduced-order groundwater-network benchmark with genuinely
held-out validation.

It is a **data availability and identification audit**, not a groundwater
model. Nothing in this package fits groundwater dynamics, estimates a network,
constructs system matrices, calibrates MODFLOW, interpolates missing heads,
selects future model nodes, or infers pumping from groundwater heads.

## Scientific boundary

- Basin: California DWR Bulletin 118 Basin 8-001, Coastal Plain of Orange
  County.
- Evidence classes are fixed in `config/evidence_classes.yaml`.
- Feasibility gates are preregistered in `config/feasibility_gates.yaml`.
- Raw downloads are immutable inputs under `data/raw/`; every downloaded file
  is paired to its official URL, access time, and SHA-256 digest in the raw
  download manifest.
- DWR periodic groundwater levels are not interpolated.
- DWR republication of an OCWD-origin observation is not independent
  validation.
- OCWD calculated storage change is accounting-derived and is not independent
  observed validation.
- MODFLOW output is a `REFERENCE_MODEL`, not empirical ground truth.

## Reproduction

The package's deterministic, non-fitting build and tests are run with:

```bash
/home/nacevedo/.conda/envs/dc_externalities/bin/python scripts/build_feasibility_audit.py
/home/nacevedo/.conda/envs/dc_externalities/bin/python -m unittest discover -s tests -v
```

The raw acquisition commands and environment are recorded under
`outputs/provenance/`. Network acquisition is intentionally separate from the
deterministic build.

## Current feasibility result

- `PUBLIC_DATA_ONLY_STATUS = PARTIAL`
- `PUBLIC_DATA_ONLY_TIER = TIER_C`
- `EXPECTED_STATUS_WITH_OCWD_WRMS = TIER_A_CANDIDATE`

The final decision, gate evidence, and exact blockers are in
`outputs/feasibility/FINAL_FEASIBILITY_REPORT.md`. Tier A is not claimed: it
remains conditional on the requested WRMS pumping/recharge records, common
support, authoritative vertical identity, QA, and reserved held-out wells.
