# Proxy model specification — cooling energy and onsite conditioning water

## Decision

**Level A + B** (empirical paired scenario distribution + quantile lookup).

Not Level C (reduced-form climate response fitted here) and **not Level D** (hourly physical model for modern/liquid cases).

Mathematical object:

\[
(\mathrm{PUE},\mathrm{WUE}_{\mathrm{site}})_s \sim F_{k,c,\mathrm{class},\mathrm{source}}
\]

where \(s\) indexes a source scenario (Lei 2025 LHS realization), \(k\) is cooling architecture (CSV label + taxonomy mechanisms), \(c\) is climate zone, and class is facility size / type as given by the source.

Operational use:

1. Condition on \((k,c,\mathrm{class})\).
2. Sample a **row**, preserving the pair \((\mathrm{PUE}_s,\mathrm{WUE}_s)\).
3. Optionally report cell 5/25/50/75/95th and covariance from `cooling_proxy_summary.csv`.

Do **not** sample PUE and WUE from separate marginals. **PAIRED SAMPLING REQUIRED.**

If a point estimate is required, use the cell median pair, not independently chosen medians.

## Inputs

| Input | Role | Required |
| --- | --- | --- |
| Cooling technology \(k\) | Lei 2025 `Cooling system` label or `tech_id` | yes |
| Climate zone \(c\) | IECC/ASHRAE label in the CSV (Prineville ≈ **5B**) | yes |
| Facility class | `Data center size` and `type` | yes if the cell exists; else refuse to average |
| Liquid subcase | `Case (Original)` 15_1…16_3 | optional; subtypes not identified |
| Weather hourly series | — | **not used** at this level |

## Outputs

| Output | Units | Boundary |
| --- | --- | --- |
| PUE | 1 | \(E_{\mathrm{fac}}/E_{\mathrm{IT}}\) annual |
| WUE_site | L/kWh | onsite conditioning-water **use** / \(E_{\mathrm{IT}}\) |
| Implied \(P_{\mathrm{fac}} = P_{\mathrm{IT}}\times\mathrm{PUE}\) | W | identity, not a component split |
| Implied \(W_{\mathrm{cond}} = E_{\mathrm{IT}}\times\mathrm{WUE}_{\mathrm{site}}\) | L | **not** withdrawal, consumption, return, or groundwater |

## Uncertainty

Within each \((k,c,\mathrm{class})\) cell: \(n=50\) empirical pairs (Cases 15–16: three subcase cells of 50). Report the empirical distribution, IQR, MAD, and \(\mathrm{Cov}(\mathrm{PUE},\mathrm{WUE})\).

Between climates: **do not average** without an explicit spatial weight (e.g. TMY station or campus location). Prineville should use **5B** (and sensitivity 4C/6B if desired), not a 19-zone mean.

Lineage uncertainty: this \(F\) is a **same-lineage model output**, not a field posterior.

## Applicability

- US climate-zone archetypes in the 19-zone list.
- Air-IT systems in the 2025 catalog, plus two **pooled** liquid-IT heat-rejection classes.
- Hyperscale/AI **energy–water intensity envelopes** at annual grain.

## Limitations / unsupported behaviors

- Hourly PUE(\(w_t\)) or WUE(\(w_t\)) for liquid cases: **UNSUPPORTED** (no public 2025 hourly engine).
- 2022 public hourly code (`PUE_WUE_*`) covers **air-IT archetypes only**; annual published envelopes are a separate masanet experiment (do not treat as closed PASS here).
- Rear-door vs cold-plate vs immersion: **PARTIAL** (pooled).
- Cooling-component electricity (chiller vs fan vs CDU): **UNSUPPORTED** in the 2025 CSV (PUE is a scalar).
- Cooling-tower makeup vs blowdown vs drift split: **UNSUPPORTED** in the CSV (WUE is a scalar use intensity).
- Groundwater / City / reclaimed / well allocation: **out of scope**.
- Independent field WUE by Lei \(k\): **UNSUPPORTED** (NREL ESIF is a different plant).
- Meta 2023–2024 water: **must not** select or calibrate \(k\).

## Evidence supporting each term

| Term | Evidence | Confidence |
| --- | --- | --- |
| Joint \(F_{k,c,\mathrm{class}}\) | `UEs_16cases.csv` 19,000 pairs | HIGH as SI semantics |
| 50 realizations / cell | group-size audit; LBNL 2024 also states 50 ops scenarios | HIGH |
| Quantile 5/95 | Rmd `quantile(x, 0.05/0.95)` type 7 | HIGH estimator; no typeset table to match |
| Same-lineage with LBNL 2024 / Lei 2022 | report §4; shared authors/labels | HIGH lineage, **not** independent validation |
| Paired sampling | source structure + water-cooled Pearson (median ~0.38 for WCC) | HIGH as policy; MEDIUM as global correlation |

## Recommended next modeling experiment

Stop at this annual paired lookup for optimization/scenario work **unless** a gated hourly question is separately justified **and** a public engine exists for that \(k\).

For Prineville: retain **multiple \(k\)** (2011 OA-evaporative design vs later PRN1 CHW/CRAH/chiller). Map each to the nearest Lei cell **by documentary identification**, not by matching holdout WUE.
