# ESIF facility overhead → project integration (structural only)

ESIF coefficients **do not transfer** to Prineville or to a generic hyperscale hall.
ESIF is warm-water liquid + heat reuse + evaporative towers + thermosyphon. Prineville gray-box is a different architecture.

`PRINEVILLE_COEFFICIENT_TRANSFER = NOT_ALLOWED`.

Selected specs were frozen on DEV/CV. TEST was not used to change them.

| Component | Selected | IT first-order? | Weather first-order? | Nonlinear / interaction? | Base load? | OOT TEST |
| --- | --- | --- | --- | --- | --- | --- |
| cooling | F4 | weak/mixed (F1 worse than F0 on CV) | yes (Twb/Tdb in F4) | yes, F4 selected | yes ~12 kW at mean climate | PARTIAL (WAPE 0.66) |
| HVAC | F0 | no on DEV CV (F1 did not beat F0) | no on DEV CV | no | yes, but **nonstationary** | **FAIL** (2024 level shift ~9→130 kW) |
| pumps | F4 | yes | yes | F4 marginally over F2_PHYS | yes | PASS (WAPE 0.17) |
| plug/light | F2_PHYS | negligible | weak | no (F3/F4 not needed) | yes ~3.5 kW | PARTIAL |

Heat-reuse residual effect: `LOW` relative to the HVAC miss. Not added as a predictor.

Hourly cooling residuals are strongly autocorrelated (ACF 1 h ≈ 0.83). Lagged **targets** were not used. A lagged-input extension was not added: the dominant OOT failure is an HVAC **level shift**, not cooling lag. That is a protocol deviation only in the sense that cooling DEV daily WAPE exceeded a 0.25 predeclared “clear fail” flag; it was not used to touch TEST.

## Comparison (conceptual)

- **Generic facility/cooling split** (IT + cooling + other overhead): ESIF **supports the accounting decomposition** (`PUE` closes from the four published components). Electrically, **cooling is small** (fans/trace heat/filter pump, ~8–20 kW), not a chiller plant. **HVAC and pumps dominate auxiliary electricity** after 2023–24.
- **Lei/Masanet**: climate×technology annual PUE. ESIF shows that a single climate-driven PUE can hide a **step change in HVAC electricity** that is not a smooth weather function. Do not insert ESIF β into Lei `k`.
- **Prineville gray-box**: air-side evaporative / fan-and-other fractions of IT. ESIF suggests reviewing, as **structure not numbers**: (1) a large HVAC/fan-wall intercept that can **jump with operational epochs**; (2) pump power that **does** track IT and wet-bulb; (3) outdoor heat-rejection electricity that is **small and weather-nonmonotonic** (heaters vs fans) on a liquid/thermosyphon plant.

## Must not transfer

- Any ESIF coefficient, intercept, or PUE level (~1.03–1.08)
- The 2.67 kW filter-pump constant as a universal pump correction
- Chiller-less / thermosyphon operating points as Prineville parameters
- The 2024 HVAC kW level as a universal “GPU-era HVAC” coefficient
