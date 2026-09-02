# Data-center conditioning architecture (generic interface)

`GENERALIZE PHYSICS AND INTERFACES; LOCALIZE ARCHITECTURES, CONTROLS, PARAMETERS, AND ACCOUNTING.`

This document is the project-level **structure** specification. It contains no ESIF or Prineville numerical coefficients.

## Canonical chain (site `j`, building `b`, time `t`)

```
P_IT[j,b,t] = F_hardware(workload, hardware)

S[j,b,t] = F_control(A[j,b,t], weather[j,t], internal_state)

(P_aux[j,b,t], W_conditioning[j,b,t]) =
    F_architecture(A[j,b,t], S[j,b,t], P_IT[j,b,t], weather[j,t])

P_site[j,t] = sum_b P_IT[j,b,t] + sum_b P_aux[j,b,t]
W_conditioning_site[j,t] = sum_b W_conditioning[j,b,t]

W_withdrawal_site[j,t] = G_site(W_conditioning_site[j,t], local_water_system)
```

Do not put groundwater or emissions inside the conditioning module.

Do not form `W_conditioning_site` by silently equal-weighting buildings when `λ_b = P_IT,b / P_IT,campus` is UNKNOWN.

Do not reduce this automatically to `W = WUE × E_IT` except as a coarse scenario baseline.

Layers that must not be conflated: **PHYSICS**, **ARCHITECTURE**, **CONTROLS**, **CAMPUS AGGREGATION**, **ACCOUNTING BOUNDARIES**.

## Architecture classes (use only where identified)

| Class | Water-consuming mechanism (typical) | Do not assume |
| --- | --- | --- |
| `DIRECT_OUTSIDE_AIR_EVAP` | Air-stream evaporative cooling / humidification (`Δω`) | Cooling towers, chillers, SPLC |
| `INDIRECT_EVAP` | Secondary loop + evaporative heat rejection | Direct mist |
| `LIQUID_DRY_REJECTION` | Little/no evaporative site water if truly dry | Open towers |
| `LIQUID_EVAP_TOWER` | Tower evaporation + blowdown | Air-side mist |
| `MECHANICAL_CHILLER` | Depends on condenser (tower vs dry vs air-cooled) — **must be identified** | That “chiller” implies a cooling tower |
| `HYBRID` | Explicit remaining-load split among the above | A single campus-wide WUE |

ESIF (Golden) is a **liquid / reuse / dry-TSC / wet-tower** hybrid.  
Early Prineville PRN1 is **`DIRECT_OUTSIDE_AIR_EVAP`**.  
Later PRN1 chilled-water/CRAH/chiller is **`CHILLED_WATER_AIR_COOLING` CONFIRMED as architecture metadata** with **unidentified** condenser/heat-rejection water (operation start **interval-censored**; not a campus-wide architecture).  
PRN2–6 and CCO complete hall architecture remain **UNKNOWN / PARTIAL**. Do not copy PRN1 negative chiller/tower evidence forward.

## Interface fields every site model should carry

- `architecture_class` as `A_{j,b,t}` (building/phase, not only campus `A_t`)
- `operating_mode` / control state `S` (e.g. mixed-air humidification, dry OA, evaporative, mechanical)
- `weather_state`
- `thermal_or_conditioning_demand`
- `water_consuming_mechanism`
- `W_conditioning` with a **boundary tag** (not `W_withdrawal`)
- `parameter_provenance` (site-specific / generic prior / fitted **accounting** mapping)
- `domain_restrictions` / epoch
- `lambda_b` load share or explicit `UNKNOWN` (do not default to 1/N)

## Water-boundary tags (do not sum across tags)

`CONDITIONING_SITE_WATER` · `TOWER_MAKEUP` · `EVAPORATION` · `BLOWDOWN` · `WITHDRAWAL` · `MUNICIPAL_SUPPLY` · `GROUNDWATER_WITHDRAWAL` · `SURFACE_WATER_WITHDRAWAL` · `CONSUMPTION` · `RETURN_FLOW` · `DIRECT_POD_WITHDRAWAL`

`W_conditioning` is the architecture-module primary water output. An empirical scale onto Meta annual withdrawal is `G_site`, not “evaporative efficiency.” Do not invent unobserved subcomponents.

## What generalizes from ESIF

Series routing of **remaining thermal load** among reuse, dry rejection, and evaporative rejection. Weather can gate the water-consuming branch. Electrical HVAC kW is not rejected heat.

## What is Prineville-specific

Penthouse OA + high-pressure ECH mist; OCP Appendix A psychrometric **DESIGN_SPEC** sequence (as-operated UNIDENTIFIED); winter mixed-air; no 2011 chiller/tower at PRN1; later PRN1 chilled-water addition with unidentified heat rejection; City vs POD accounting; Meta withdrawal as a **different** boundary from air-side mist.

## Coefficients that must never transfer

ESIF 0.70 / 1.27 / 1.42 L/kWh; 42.5% TSC / 47% tower; 49 °F TSC threshold; COC 12.8; Prineville 2011 design WUE 0.31 as later-campus truth; Lei scenario WUE; gray-box `ε=0.85` or `s` water-scale.
