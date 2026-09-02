# Data-acquisition ranking (v1)

Do not automatically rank condenser type above building load shares.

| Rank | Item | Reduces |
|---|---|---|
| 1 | Building/phase IT or electrical load shares λ_b | **Campus aggregation** uncertainty (without λ, campus totals stay unidentified) |
| 2 | As-operated OA/RA/ECH control + air-side T/RH/flow | **Building physics** (control as-operated, ΔT, ε_T) |
| 3 | Mist/ECH loop water (makeup vs recapture vs RO) | **Water-boundary** (AIR_STREAM vs CONDITIONING_INPUT) |
| 4 | PRN1 CHW condenser/heat-rejection schedule | Later-PRN1 **building physics** / whether a second water mechanism exists |
| 5 | PRN2–6 architecture | Campus mechanism mix |
| 6 | CCO mechanical narrative | Campus mechanism mix |
| 7 | City meter identity/boundary | **Water accounting** G_site |
| 8 | PacifiCorp temporal electricity | P_fac / IT scale |
| 9 | POD completeness | Groundwater vs municipal split |

Building-physics bottleneck: supply/return/mixed T/RH + airflow + dampers.
Campus-level bottleneck: λ_b (then architecture of unidentified halls).
Water-accounting bottleneck: City meter boundary after physics is tagged correctly.
