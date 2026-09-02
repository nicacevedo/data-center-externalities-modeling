# Handoff contract: heat-rejection regime → water / WUE

This is the entry contract for the **next** major ESIF experiment. It is **not** a water model.

Electrical facility-overhead F0–F4 results remain frozen. Do not “correct” water using the failed stationary HVAC model.

## A. Thermosyphon timeline

High-authority sources: Sickinger et al., NREL/TP-2C00-72196, DOI `10.2172/1471661`; NREL 2018 “Data Center Water-Savings Win Wins.”

| Epoch | Dates | Role |
| --- | --- | --- |
| Pre-TSC available in this electrical sample | 2016-06-12 through 2016-07-31 | short summer overlap only |
| Commissioning / transition | **August 2016** (month-level) | mixed installation/operation; Sickinger Fig. 3 caption states TSC became operational **2016-08-16** — recorded, **not** used as a fitted day |
| First full TSC operating year | **2016-09-01 through 2017-08-31** | Sickinger §2.2 definition |

The common ESIF power/weather sample **does cross** commissioning. Prior `NOT_IN_SAMPLE` was false.

Electrical consistency (valid common hours, not a causal TSC estimate):

- first full year mean IT **885 kW** vs Sickinger **888 kW**;
- mean source PUE **1.034**, consistent with Sickinger that TSC did not degrade energy efficiency;
- pre-period is ~7 summer weeks — **do not** estimate a causal TSC electrical effect.

## B. Do not use failed HVAC predictions as heat rejection

`hvac_kw` is **electrical** power of fan walls, electrical-room fan coils, and make-up air.

It is **not** thermal heat rejected.

The 2024 HVAC electrical regime shift is an overhead-accounting fact. It does **not** define 2016–2018 thermosyphon water splits.

## C. Do not equate `cooling_kw` with heat rejection

`cooling_kw` is **electrical** power for outdoor-equipment fans, pipe trace heaters, and the dedicated tower-filter-pump allocation (~2.67 kW).

It is **not** rejected thermal energy, evaporative mass, or WUE.

## D. Next-stage physical object

Model/validate, using **directly documented or measured** ESIF source evidence:

`IT heat → allocation among building heat reuse + thermosyphon dry rejection + evaporative-tower rejection → conditioning water / WUE`

Sickinger first-year heat-rejection split (context for the water stage, **not** an electrical coefficient): building reuse 10.5%, TSC 42.5%, cooling towers 47%. Reproduce or challenge that **thermal/water** object from primary evidence. Do not back-solve it from `cooling_kw` or `hvac_kw`.

## E. Water boundary (keep separate)

- conditioning / site cooling water
- withdrawal
- source split
- consumption
- return flow
- groundwater

Do not collapse these into one “WUE number” without stating the boundary.

## F. Transfer

- ESIF **structural** evidence may inform generic heat-rejection mechanisms (reuse first, then dry TSC, then evaporative tower; climate as wet-/dry-bulb opportunity).
- ESIF **coefficients, WUE levels (e.g. 0.70 L/kWh), PUE levels, and 2024 HVAC kW must not** be copied into Prineville.

`PRINEVILLE_COEFFICIENT_TRANSFER = NOT_ALLOWED`.

## G. Electrical uncertainty that does **not** block water/WUE

The 2024 HVAC stationary-model **FAIL** is a 2024 operational/infrastructure electrical regime change.

The thermosyphon water experiment’s primary window is **2016–2018** (commissioning through the published 24-month results). That window is **before** the 2024 HVAC step.

Therefore:

`READY_FOR_HEAT_REJECTION_WATER_WUE = PASS_WITH_BOUNDARY_RESTRICTIONS`

Restrictions:

- do not use HVAC F0 predictions as thermal load;
- do not use `cooling_kw` as rejected heat;
- do not refit electrical overhead to “help” WUE;
- carry forward that facility architecture/control state `A_t, S_t` can change electrical overhead without a proportional IT/weather change.

## Forbidden in the water experiment’s electrical layer

- reconstructed Kestrel CPU / H100 replay as IT
- Meta / Prineville water or coefficients
- lagged-target HVAC/cooling patches
- treating 2024 HVAC kW as a thermosyphon water covariate
