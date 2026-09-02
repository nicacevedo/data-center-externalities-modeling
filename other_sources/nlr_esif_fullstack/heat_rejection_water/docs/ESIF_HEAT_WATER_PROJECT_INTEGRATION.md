# ESIF heat→water: project integration (structure only)

`PRINEVILLE_COEFFICIENT_TRANSFER = NOT_ALLOWED`.

ESIF coefficients, WUE levels (0.70 / 1.27 / 1.42 L/kWh), 42.5% TSC / 47% tower / 10.5% reuse, 49°F threshold, and COC 12.8 **must not** be copied into Prineville or Lei calibrations.

## Generic structure now empirically supported

```
Q_IT
  → architecture/control allocation A_t, S_t:
       Q_reuse,  Q_dry,  Q_evap
  → W_conditioning = g(Q_evap, weather, water-system state)
```

Do **not** collapse this automatically to `W = WUE × IT_energy` except as a coarse scenario baseline.

ESIF supports:

1. **Series heat hierarchy** (reuse first, then dry rejection, then evaporative tower).
2. **Weather-gated dry vs wet remaining-heat split** (documented 9.4 °C / 49 °F aggressive-TSC rule; Nov–Apr TSC dominance in source prose; independent weather shows Nov–Apr much colder).
3. **Conditioning-site water driven by the evaporative branch**, not by HVAC electrical kW.
4. **Technology counterfactuals** as engineering scenarios (tower-only vs reuse+tower vs reuse+TSC+tower), not as randomized treatment effects.

## Source-specific (do not transfer)

- Warm-water liquid, chiller-less ESIF plant.
- BlueStream thermosyphon hardware and its economic fan-control law.
- Manual meter identity Meter1+Meter2+estimated filter blowdown.
- MAU exclusion.
- Golden/5B climate and 2016–18 IT load (~888 kW).
- 2024 HVAC electrical regime (irrelevant to 2016–18 water).

## Lei/Masanet

The public Lei bank has **no exact ESIF architecture**. Closest preregistered case is `LIQ_DRY_AD` in climate 5B (liquid + dry cooler) — missing reuse-first and open-tower remainder, and it includes adiabatic/ACC. Direction (dry rejection uses less site water than open-tower evaporation) is consistent. Magnitudes are **not** a calibration target. Agreement is **not** independent validation of Lei (same modeled lineage).

## Prineville — review, do not refit

Current Prineville gray-box is **air-side evaporative spray**, not liquid-first reuse→dry→wet-tower. Future structural revision candidates (documentation only):

- explicit evaporative vs dry **heat-rejection** split (not only spray-on/off);
- weather-dependent remaining-heat regime;
- architecture epochs `A_t`;
- `W_conditioning` tagged separately from withdrawal/source split.

Do not implement those changes in this experiment. Do not use Meta 2023–2024 water.

## Water-boundary schema (project-wide)

Every water quantity must carry one primary tag:

`CONDITIONING_SITE_WATER` | `TOWER_MAKEUP` | `EVAPORATION` | `BLOWDOWN` | `WITHDRAWAL` | `MUNICIPAL_SUPPLY` | `GROUNDWATER_WITHDRAWAL` | `SURFACE_WATER_WITHDRAWAL` | `CONSUMPTION` | `RETURN_FLOW`

Do not sum across tags. ESIF 0.70 L/kWh is `CONDITIONING_SITE_WATER` (tower-loop makeup identity above), not groundwater.
