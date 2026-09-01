# Proxy model specification (frozen)

## Two tiers

**LEVEL 1 — annual planning / scenario proxy (this freeze)**

\[
S_{k,c,s,l} = \{( \mathrm{PUE}_j,\ \mathrm{WUE_{site,model}}_j )\}_{j=1}^{N}
\]

Lei et al. 2025 source-model annual scenarios. Not an empirically estimated probability distribution of real facilities.

If downstream uses equal weights \(\pi_j=1/N\), that weighting is **`DESIGN_PRIOR_UNIFORM`**: a design/scenario prior over the source ensemble, **not** a frequency of real-world states.

Source 5th/95th are **SOURCE-SCENARIO QUANTILES**, not confidence intervals or population quantiles.

**LEVEL 2 — operational / hourly**

\(\mathrm{PUE}_t,\mathrm{WUE}_t = f(k, w_t, P_{\mathrm{IT},t}, \theta)\)

**UNSUPPORTED** for generic modern liquid cooling with current public evidence. Do not use annual pairs for hour-to-hour load shifting, daily efficiency, temperature-driven marginal water, or chiller part-load.

2022 air-IT hourly code exists under `other_sources/masanet/` with its own domain; V1 annual published-range reproduction **FAIL**; V2 **PENDING**. That is not this API.

## Fail-closed interface

`scripts/cooling_proxy_api.py` → `get_cooling_scenarios(...)`

- unsupported combination → `CoolingProxyUnsupportedError`
- no climate / facility / subtype averaging
- no independent PUE/WUE sampling
- Cases 17/18 require `include_source_extra=True`
- sampling requires `scenario_weighting='DESIGN_PRIOR_UNIFORM'`

Default downstream set: **PAPER_CORE** ten technologies. Source-extra dry-cooler air-IT (Cases 17/18) opt-in only.

## Inputs / outputs

Inputs: `tech_id` or cooling-system label; climate zone; facility class; liquid subtype for liquid IT.

Outputs: paired rows; scenario IDs; `source_scope_status`; water-boundary warning; `WUE_site_model`.

Implied \(P_{\mathrm{fac}}=P_{\mathrm{IT}}\times\mathrm{PUE}\) and \(W_{\mathrm{conditioning,model}}=E_{\mathrm{IT}}\times\mathrm{WUE_{site,model}}\) are identities, not source-water.

## Liquid subtypes

From SI Rmd (not inferred from PUE):

- `15_1`,`16_1` → `REAR_DOOR_HEAT_EXCHANGER`
- `15_2`,`16_2` → `DIRECT_TO_CHIP_COLD_PLATE`
- `15_3`,`16_3` → `IMMERSION`

Case **15** = liquid + waterside/tower; Case **16** = liquid + dry/adiabatic.

## Evidence

Same-lineage source scenarios: **PASS** as source semantics. Independent facility WUE by Lei `k`: generally **UNSUPPORTED**. Early Prineville operator check vs AE_AD_ACC 5B: **materially discrepant** on WUE (architecture-predeclared; not used to retune).
