# Next Prineville conditioning experiment (NOT executed)

Disposition: `MINIMAL_STRUCTURAL_REVISION_REQUIRED`

This is a **preregistered structural-revision** experiment, not a holdout-chasing refit.

## Implement ONLY these confirmed missing / incomplete mechanisms

1. **Winter/economizer mixed-air fraction** in the air-side mass balance  
   `w_in = OA_frac * w_oa + (1-OA_frac) * w_return`  
   with OA_frac from documented control logic (OCP sequence), not from 2023–2024 water.
2. **Architecture state `A_t`**  
   - `DIRECT_OUTSIDE_AIR_EVAP` for early PRN (and CCO only as a SUPPORTED same-class scenario, not a fitted switch).  
   - `PRN1_HYBRID_CHILLED_WATER` from **2024-02-02** at **PRN1 only**.  
   Do **not** convert the whole campus to chillers.
3. **Explicit water-boundary tags**  
   Gray-box output remains `CONDITIONING_SITE_WATER` (air-side). Any map to Meta `WITHDRAWAL` stays a labeled mapping, not physics.
4. **PRN1 chiller water**  
   Include a **placeholder unidentified heat-rejection water term** with provenance `UNKNOWN` unless condenser type is acquired. Do not assume a cooling tower.

## Freeze before outcome inspection

Write `PRINEVILLE_STRUCTURAL_REVISION_FREEZE.json` containing equations, epoch dates, and parameters still unidentified. Then stop. Only after freeze may previously exposed 2023–2024 water be scored as `DIAGNOSTIC_PREVIOUSLY_EXPOSED`.

## Inputs

- Existing weather (KS39/KRDM canonical).
- Latent IT scale from annual electricity **closure** (not a new IT model).
- OCP/Meta 2011 control structure for mixing.
- Permit epoch dates (not estimated from water).

## Target boundary

Primary: modeled `W_conditioning` (air-side mist).  
Secondary diagnostic: existing mapping to Meta annual withdrawal, clearly tagged.

Temporal resolution: hourly physics aggregated to month/year. No invented hourly water meters.

## Fit / calibration data

Allowed: 2011–2022 for remaining unidentified scalars (effectiveness, OA-fraction parameters) **if** a calibration is still needed after implementing documented control. Prefer documenting priors over fitting.

Forbidden as structure selectors: Meta 2023–2024 water.

## Validation data

- Prefer new City monthly meter-boundary series or a future Meta annual vintage.  
- 2023–2024 Meta water: diagnostic only, previously exposed.

## Metrics

Water-volume WAPE on the **declared** boundary. Secondary: WUE if both water and IT energy share a boundary. Do not optimize architecture on these metrics.

## Stopping rule

Stop when: mixing is implemented; `A_t` exists; PRN1 chiller is an epoch flag with unidentified condenser water; freeze file written; no ESIF/Lei coefficients entered; 2023–2024 not used to choose terms.

## Uncertainty

Keep evidence class on every term (CONFIRMED / SUPPORTED / UNKNOWN). Do not turn UNKNOWN condenser type into a tower model.

## Must NOT add

SPLC; campus-wide chillers; ESIF 0.70/1.27/1.42; 42.5% TSC; Lei WUE; 2011 WUE 0.31 as later-campus truth; IEC as installed.
