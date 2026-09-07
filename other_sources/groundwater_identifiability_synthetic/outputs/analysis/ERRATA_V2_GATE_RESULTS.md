# Errata — `gate_results.csv` G3 presentation (frozen V2)

**This note is additive. The frozen file `outputs/analysis/gate_results.csv` is not edited.**

## Defect

In `outputs/analysis/gate_results.csv`, the six G3 cells (`G3R1`, `G3R2`, `G3R1b`, `G3R2b`, `G3R3`, `G3R4`) are rendered with:

- `pass=True`
- `state=ESTIMATED_PASSED_GATE`
- `support_status=SUPPORTED`

and the CSV contains **no** `SGI_G3` aggregate row.

Those per-cell columns encode **estimability / generic per-cell gate-state semantics** (the replicate was estimated and the *cell-level metric fields in that CSV* did not trip the generic renderer). They do **not** mean that G3 falsification passed.

## Authoritative aggregate result

The canonical frozen aggregate is `outputs/analysis/FINAL_SYNTHETIC_IDENTIFIABILITY_STATUS.json`:

```text
SGI_G3.hard_failure = true
NETWORK_SUPPORT_FINAL.status = NOT_EARNED
LOCAL_RESPONSE_STATUS = LOCAL_RESPONSE_NOT_IDENTIFIED
```

A reader consulting only `gate_results.csv` would incorrectly conclude that G3 passed. Use the JSON status file (and `POST_SWEEP_PROVENANCE_AUDIT.md`) for the qualification outcome.

This presentation defect was identified in the independent post-V2 scientific audit. It does not change any frozen scientific result.
