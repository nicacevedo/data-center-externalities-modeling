# design_v1 → design_v2 changelog

Parent checkpoint: `1b95209 [Feature] GW synthetic`.
v1 materials (`config/design_v1.yaml`, `DESIGN_FREEZE.md`, Phase-1 provenance) are
preserved and were not mutated in this pass.

Classification of every change:

| # | Change | Class | Why |
|---|---|---|---|
| 1 | S7 latent-climate factor is multiplicative with stationary-sd conversion | implementation bugfix (already in v1 code; documented as v2 protocol) | Passing stationary sd as AR(1) innovation sd inflated the factor 2.3× and drove clipping. An additive factor left insufficient headroom above zero. Clipping would have been an undocumented extra misspecification. |
| 2 | Cadence-dependent estimands (`k=1` physical vs `k>1` A^k / pseudo-true coarse B) made machine-explicit in reporting and bootstrap | scientific-design clarification | v1 stated the rule; v1 bootstrap still compared coarse coefficients to fine-step `B_Q`. |
| 3 | Masked-node: frozen target selected **before** missingness; no post-missingness fallback; warm-forward unscored; score only TEST-aligned instants | scientific-design change | v1 fallback after missingness selected an easier node. v1 scoring from an early anchor misaligned prediction times with TEST-onset truth. |
| 4 | Estimability is a first-class outcome with reason codes and gate-level states | scientific-design change (reporting made mandatory) | `NOT_ESTIMABLE` and `FIT_FAILED` must not collapse into silent NaNs; required-cell non-estimability means complexity unsupported. |
| 5 | Process-noise stress curve `{0.05, 0.25, 1.0}` retained as an explicit v2 pre-analysis addition | scientific-design change (pre-analysis) | Reference regime is observation-limited; the curve is what licenses any process-limited claim. Frozen; not tuned from results. |
| 6 | S8 placebo redesigned: estimator receives `Q_real_observed` **and** `P_placebo`; truth coefficient on placebo is exactly 0 | scientific-design change | v1 replaced real pumping with the placebo, so a nonzero placebo coefficient could not be interpreted as a false causal effect *conditional on* real pumping. |
| 7 | S6 renamed S6a (global-memory null) and S6b (matched-local-dynamics null) added | scientific-design change | One null is not enough. S6a keeps v1's independently targeted memory. S6b preserves `A_ii` from the coupled reference while zeroing `A_ij`. |
| 8 | Cadence-correct moving-block bootstrap semantics | scientific-design change | Physical coverage against fine-step `B_Q` only at `k=1` where identifiable. At `k>1`, pseudo-true or interval-width diagnostics only. Still not an SGI_G1 gate. |
| 9 | Absolute `S_i`/`C_ij` recovery requires the full identifiability conjunction, not merely known pumping scale | scientific-design change | v1 used `absolute_pumping_scale_known && k==1 && scenario not S7`, which overclaimed physical recovery under noisy/lagged recharge and confounding. |
| 10 | `scripts/summarize_results.py` and its fixture classifications frozen before `ANALYSIS` | reporting/provenance change | Analysis logic must be preregistered. Developed on smoke schema and hand-constructed fixtures only. |
| 11 | SGI_G0–G3 cells, metrics, aggregation, `NOT_ESTIMABLE` handling, S6a/S6b/S8 severity made machine-explicit | scientific-design / reporting | Vague phrases ("relevant regimes") are prohibited. Oracle cells cannot compensate. |
| 12 | v2 provenance filenames (`DESIGN_V2_FREEZE.json`, `CODE_MANIFEST_V2.csv`, `RUN_MANIFEST_V2.json`, `FROZEN_SYSTEMS_V2.csv`) | reporting/provenance change | Versioning must be explicit so v1 freeze artifacts remain historical evidence. |

No `ANALYSIS` seed was inspected while making these changes.
