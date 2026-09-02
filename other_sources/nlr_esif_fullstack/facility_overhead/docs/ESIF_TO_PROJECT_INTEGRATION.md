# ESIF facility overhead → project integration (structural only)

ESIF coefficients **do not transfer** to Prineville or to a generic hyperscale hall.

ESIF architecture: warm-water liquid cooling, chiller-less HPC hall, waste-heat reuse, evaporative towers, thermosyphon hybrid dry rejection. Prineville gray-box is a different architecture.

`PRINEVILLE_COEFFICIENT_TRANSFER = NOT_ALLOWED`.

## Transferable high-level structure

Held-out evidence supports:

`P_overhead,t = f(P_IT,t, weather_t, A_t, S_t)`

where:

- `A_t` = facility architecture / configuration state (plant lineup, capacity, metering boundary);
- `S_t` = operational / control state.

A missing architecture/configuration/control state is **strongly indicated**. An epoch intercept is **one plausible future representation** of that missing state. It is **not** a validated production model: no epoch HVAC model was fitted, and TEST was not used to select one.

## What each component actually showed

Selected specs were frozen on DEV/CV. TEST was not used to change them.

| Component | Selected (DEV/CV) | IT | Weather | Nonlinear / interaction | What TEST supports | What TEST does not support |
| --- | --- | --- | --- | --- | --- | --- |
| cooling | F4 | weak/mixed (F1 worse than F0 on CV) | descriptively relevant (Twb/Tdb) | F4 selected on DEV | weather/control dependence and non-monotonicity are plausible | stationary F4 is **not** a strongly validated transferable cooling law (hourly WAPE 0.66) |
| HVAC | F0 | not first-order on historical CV | not first-order on historical CV | not selected | existence of a large 2024 regime shift | any stationary IT+weather HVAC map |
| pumps | F4 | useful for **aggregate energy** | useful for aggregate energy | F4 marginally over F2_PHYS | daily-energy WAPE 0.17 | hourly dynamics (TEST R² = −0.74) |
| plug/light | F2_PHYS | negligible | weak | F3/F4 unnecessary | partial | a physical plug law |

Heat-reuse diagnostic: `energy_reuse` on TEST does **not** explain much of the HVAC-dominated residual (`LOW_FOR_TESTED_DIAGNOSTIC`). That does **not** mean heat reuse is generally unimportant as a **thermal** allocation. It was not added as an electrical predictor.

Hourly cooling residuals are autocorrelated (ACF 1 h = 0.8288581320055117). Lagged **targets** were not used. Optional lagged-**input** fallback was **not** exercised (`protocol_deviation = false`). `COOLING_DYNAMICS_UNRESOLVED = true`.

## Comparison (conceptual)

- **Generic facility/cooling split** (IT + cooling + other overhead): ESIF **validates the published accounting identity**. Electrically, ESIF `cooling_kw` is a **small** outdoor-fan/heater/filter-pump term, not a chiller.
- **Lei/Masanet**: climate×technology annual PUE can hide a **step change in HVAC electricity** that is not a smooth weather function. Do not insert ESIF β into Lei `k`.
- **Prineville gray-box** (structure to **review**, not numbers to copy):
  1. fan/HVAC electricity can have a large intercept that is **regime-dependent** (`A_t`, `S_t`), not a universal constant;
  2. pump **aggregate energy** can track IT and wet-bulb, but a selected polynomial **did not** reproduce held-out hourly dynamics;
  3. outdoor heat-rejection **electricity** on this liquid/thermosyphon plant is small and weather-nonmonotonic — and is **not** rejected heat.

## Must not be inferred from ESIF

- Any ESIF coefficient, intercept, or PUE level (~1.03–1.08)
- The 2.67 kW filter-pump constant as a universal pump correction
- Chiller-less / thermosyphon operating points as Prineville parameters
- 2024 HVAC kW as “GPU-era HVAC”
- `HVAC_base(epoch)` as a validated model
- “Pump power tracks IT and wet bulb” as an hourly dynamical law
- `cooling_kw` or `hvac_kw` as heat rejection
