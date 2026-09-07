# ANALYSIS orchestration (does not affect DESIGN_HASH)

This file documents executable mappings that implement already-frozen `design_v2`
intent. It is **not** a design artifact and is not hashed into `DESIGN_HASH`.

## G3 evaluated models

| cells | model | reason |
|---|---|---|
| G3R1, G3R2 (S6a) | N | null-network false edges |
| G3R1b, G3R2b (S6b) | N | null-network false edges |
| G3R3, G3R4 (S8) | L | placebo coefficient/response |
| G2R1–G2R4 (inversion) | N | N vs best simpler model |

Encoded in `src/summarize.py` as `G3_CELL_EVALUATED_MODEL`. G3 has no global
`evaluated_model` in `design_v2.yaml`.

## Strong-edge F1

Canonical column: `strong_edge_undirected_f1`.

Alias: `edge_f1` (identical value).

Definition: undirected F1 of detected edges vs true strong edges, where a true
strong edge satisfies `max((A^k)_ij,(A^k)_ji) >= 0.01` and a detected edge
satisfies `max(kappa_hat_ij, kappa_hat_ji) >= 0.01`. True strong edges outside
the candidate set count as false negatives.

## G2 / G3

`SGI_G2_RAW` is G2 performance before falsification.
`NETWORK_SUPPORT_FINAL` applies hard G3 override and estimability overlay.
