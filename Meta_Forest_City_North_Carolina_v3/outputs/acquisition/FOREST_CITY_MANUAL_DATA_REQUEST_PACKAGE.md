# Forest City v3 data-request package

Read-only reuse of committed v2 package plus v3 ranking. Working-tree v2 is not written.
# Forest City manual data / records request package

Do not send these requests from this pass. Freeze public v2 first.

**Address/entity scope (do not guess FRC1):** request the original 2010–2013 Facebook/Andale campus and **all** of:

- 284 Social Circle, Forest City, NC 28043 (Andale Data Center / Andale, Inc. / Facebook elevator owner, 2011)
- 408 Social Circle, Forest City, NC 28043 (FACEBOOK FRC 3 elevator occupant, 2012-07-31)
- 404 Social Circle, Forest City, NC 28043 (FACEBOOK DATA CENTER elevator occupant 2016; campus mailing)
- Legal entities: Andale, Inc. (NC SOS 1188765); Andale, LLC (2010 development agreement); Facebook, Inc. / Meta Platforms, Inc.
- Brownfields project #14036-10-081 (Andale Facebook Data Center)
- Town of Forest City / Rutherford County building, planning, and utility files for the Social Circle campus
- Date range for original-campus cooling/control: **2010-11 through 2013-12**, plus **2022-01 through 2024-12** for the water-withdrawal discontinuity

`FRC1_ADDRESS = INTERVAL/SET_UNRESOLVED`. Records requests must use the set, not a single guessed street.

## VERY_HIGH

1. **AHU schedules + design and measured CFM (TAB)** for original production halls (Building 1 / Andale 284 and any 2012 hall that was actually operating). Why: closes `m_dot` directly. Equation: `V_dot_water = m Δw / ρ`. Expected value: identifies or bounds `FACILITY_EFFECTIVE_DELTA_T` vs 35 °F IT design.
2. **SAT / RAT time series or commissioning snapshots (summer 2012)** including OA/RA damper positions. Why: closes mixed-air state and as-operated return-air rise. Distinguishes design-reference 25/35 °F scenarios from RAT.
3. **Sequence of operations** for OA/RA mixing, evaporative, and DX. Why: independent of the OCP blog cases that defined the v1 controller. Needed before treating June 25 / July 1 as validation.
4. **Cooling makeup meter IDs, service boundary, and 2012 + 2022–2024 monthly totals** (Town of Forest City utility; Meta customer). Why: maps air-stream water onto site withdrawal. Does not infer industrial class = Meta.
5. **2022–2024 mechanical / water-treatment / reuse retrofit files** (permits, change orders, P&ID). Why: only dated evidence can explain 55 ML → 16 ML. Early-2010s membrane story is not acceptable as a 2024 cause.

## HIGH

6. **DX schedule, capacity, and 2012 runtime / disable logs.** Why: independent check of “DX unused summer 2012” beyond the operator blog.
7. **Evaporative system specifications** (Munters or successor; effectiveness; mist vs membrane dates). Why: `evap_thermal_effectiveness` is currently a generic prior, not Forest City sourced.
8. **Commissioning reports (2011–2013)** for Building 1 and FRC 3 (408 Social Circle). Why: as-operated vs design envelope (85 °F / 90 % RH).
9. **Fan curves / penthouse AHU as-built.** Why: fan heat and bypass break IT ΔT ≠ AHU ΔT.
10. **Utility meter installation/replacement history 2022–2024.** Why: reporting discontinuity vs physical use.

## MEDIUM

11. **P&ID and water treatment (UV, RO/membrane, reuse, blowdown/drain).** Why: cooling-system input vs air-stream evaporated water.
12. **Rutherford County PIN / tax cards** for 284 / 404 / 408 Social Circle. Why: entity/building crosswalk; parcel_id currently UNIDENTIFIED.
13. **Town SmartGov building permits** (drawings if releasable) 2010–2017 and 2022–2024.
14. **Duke Energy account / interval mapping** (later; electricity is already disclosed annually).

## LOW

15. **eGRID SRVC / DUK EIA-930 reconstruction inputs** for location-based Scope 2. Secondary; Meta already publishes location-based totals. Stopped this pass at `INSUFFICIENT_BOUNDARY_INFORMATION`.
16. **Groundwater / surface-water impact studies.** Out of scope for v2 freeze.

Expected scientific value ranking follows the missing measurements in `AIRFLOW_IDENTIFICATION_REQUIREMENTS.md`. Highest-value missing measurement: **TAB or BMS CFM at the original-campus AHU boundary for 2012**, or SAT/RAT that would identify effective ΔT at a named load.


## v3 data-value ranking

Engineering and utility records now have **higher marginal value** than additional weather stations.

| priority | record | identifies | upgrades | uncertainty | owner | engineering_records_higher_value_than_more_weather |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | TAB/design AHU CFM | m_dot / FACILITY_EFFECTIVE_DELTA_T | UNIDENTIFIED airflow -> IDENTIFIED or BOUNDED | removes circular water calibration path | Meta / commissioning / TAB contractor; Town permit drawings | True |
| 2 | SAT/RAT and OA/RA 2012 | as-operated return-air rise vs 35F IT design | SCENARIO RA -> OBSERVED RAT | separates design-reference from operation | BMS / commissioning | True |
| 3 | cooling / economizer / DX sequence of operations | independent controller vs OCP blog cases | implementation consistency -> possible validation | stops using June 25/July 1 as definition and test | Meta facilities | True |
| 4 | cooling makeup meter IDs + 2012 and 2022-2024 totals | cooling-only water vs campus withdrawal | campus accounting -> cooling boundary | 2023-24 drop cause | Town of Forest City utility; Meta | True |
| 5 | blowdown/reuse/return-flow accounting | withdrawal vs consumption | UNIDENTIFIED water split | cycles of concentration | P&ID / treatment | True |
| 6 | retrofit chronology 2022-2024 | 55->16 ML cause | CAUSE_PUBLICLY_UNRESOLVED | reporting vs physical | permits / change orders | True |
| 7 | P&IDs / mechanical schedules | AHU vs plant boundary | architecture map | served-load | DPR / Meta | True |
