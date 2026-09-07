# Post-sweep provenance audit (mechanical / procedural)

This is **not** an independent scientific review. It checks hashes, counts,
contamination, and that summarization used the frozen pathway.

Valid ANALYSIS execution commit: `8782efb75f5cf31cbbdabc9291c33d89de9eb9c2`

A prior launch under `6a1a68e` completed 7740 replicates but was **invalidated**
before scientific inspection: the summarizer refused the file because uint64 seeds
were parsed through `float`. Those replicates were deleted. Code was fixed,
`CODE_HASH` regenerated, a new freeze recorded, and the sweep was rerun in full
from the frozen ANALYSIS pool.

## Invariants

| check | result |
|---|---|
| FEATURE_COMMIT | `8782efb75f5cf31cbbdabc9291c33d89de9eb9c2` |
| DESIGN_HASH current = freeze = sweep | `b53f5594a444ae4826adfe2c47818080508a4c4b00a38fa25b4ffc483e20a8a5` |
| CODE_HASH current = freeze = sweep | `7cc64809bf240d7afea164c9a24a737c75de88a0b5e8d38f4e85b704f00d863c` |
| ANALYSIS seed-pool hash | `bd6db2aac7743cc83d5d5ecd8b5f07fefe18747649e3489a5b89e7e0cb689015` |
| expected replicates | 7740 (129 × 60) |
| observed replicates | 7740 |
| unique (cell_id, seed) | 7740 |
| duplicate IDs | 0 |
| missing planned cells | none |
| extra cells | none |
| seeds ⊆ ANALYSIS pool | true (60 unique) |
| overlap G0 | none |
| overlap SMOKE | none |
| overlap CALIBRATION | none |
| `smoke` flag | False on all 7740 |
| NOT_ESTIMABLE N rows retained | 829 |
| FIT_FAILED L | 0 |
| bootstrap | false |
| post-result scientific-code edits | none after the valid launch |
| files outside isolated module | none (gitlink dirty, pre-existing, untouched) |

Gate calculations in `FINAL_SYNTHETIC_IDENTIFIABILITY_STATUS.json` were produced by
`scripts/summarize_results.py --analysis` after manifest/hash validation, not by
ad-hoc scripts. Output hashes: `outputs/provenance/ANALYSIS_OUTPUT_HASHES.csv`.

Wall time: 14.1 min. Storage: sweep CSV 21,980,087 bytes.
