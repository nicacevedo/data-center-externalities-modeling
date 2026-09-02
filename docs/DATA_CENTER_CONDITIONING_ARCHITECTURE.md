# Data-center conditioning architecture (generic interface)

`GENERALIZE BOUNDARIES AND MECHANISM CLASSES; LOCALIZE ARCHITECTURES AND COEFFICIENTS.`

This document is the project-level **structure** specification. It contains no ESIF or Prineville numerical coefficients.

## Canonical chain

```
workload
  → P_IT
  → architecture/control state A_t, mode S_t, weather Ω_t
  → architecture-specific conditioning mechanism
  → W_conditioning
  → local water-supply accounting (City / POD / sewer / …)
```

Do not reduce this automatically to `W = WUE × E_IT` except as a coarse scenario baseline.

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
Early Prineville is **`DIRECT_OUTSIDE_AIR_EVAP`**.  
PRN1 from 2024-02-02 is a **PRN1-local hybrid** with confirmed chilled-water/CRAH/chiller and **unidentified** condenser water.

## Interface fields every site model should carry

- `architecture_class`
- `operating_mode` (e.g. dry OA, mix, full evaporative, mechanical)
- `weather_state`
- `thermal_or_conditioning_demand`
- `water_consuming_mechanism`
- `W_conditioning` with a **boundary tag**
- `parameter_provenance` (site-specific / generic prior / fitted mapping)
- `domain_restrictions` / epoch `A_t`

## Water-boundary tags (do not sum across tags)

`CONDITIONING_SITE_WATER` · `TOWER_MAKEUP` · `EVAPORATION` · `BLOWDOWN` · `WITHDRAWAL` · `MUNICIPAL_SUPPLY` · `GROUNDWATER_WITHDRAWAL` · `SURFACE_WATER_WITHDRAWAL` · `CONSUMPTION` · `RETURN_FLOW`

## What generalizes from ESIF

Series routing of **remaining thermal load** among reuse, dry rejection, and evaporative rejection. Weather can gate the water-consuming branch. Electrical HVAC kW is not rejected heat.

## What is Prineville-specific

Penthouse OA + high-pressure ECH mist; winter mixed-air; no 2011 chiller/tower; later PRN1 chilled-water addition; City vs POD accounting; Meta withdrawal as a **different** boundary from air-side mist.

## Coefficients that must never transfer

ESIF 0.70 / 1.27 / 1.42 L/kWh; 42.5% TSC / 47% tower; 49 °F TSC threshold; COC 12.8; Prineville 2011 design WUE 0.31 as later-campus truth; Lei scenario WUE; gray-box `ε=0.85` or `s` water-scale.
