# Forest City v3 manual data-request package

Engineering and utility records now have higher marginal scientific value than additional generic modeling. These are qualitative, goal-specific tiers—not numerical value-of-information scores.

| goal | priority_tier | record_package | required_records | identifies | caveat | engineering_records_higher_value_than_more_weather |
| --- | --- | --- | --- | --- | --- | --- |
| A physical airflow / heat scale | VERY HIGH | AIR-SIDE COMMISSIONING PACKAGE | TAB/BMS CFM + SAT/RAT + OA/RA or mixed-air state + named historical operating period | airflow and air-side temperature difference; heat scale only with matched Q/load boundary | CFM alone identifies airflow, NOT facility effective Delta-T | True |
| B controller validation | VERY HIGH | CONTROLLER VALIDATION PACKAGE | sequence of operations + economizer/evap/DX logic + DX runtime/disable evidence | as-operated control logic and independent replay validation | operator anecdotes are not a BMS validation series | True |
| C cooling-water boundary | VERY HIGH | COOLING-WATER METER PACKAGE | cooling makeup meter IDs + service boundary + monthly history + set/swap chronology | cooling-only makeup magnitude at a named boundary | campus withdrawal is not cooling-only water | True |
| D withdrawal-to-consumption accounting | HIGH | WATER BALANCE PACKAGE | blowdown + reuse + return-flow records + treatment accounting | withdrawal-to-consumption fraction | withdrawal cannot be assumed consumed | True |
| E retrofit/temporal attribution | HIGH | RETROFIT CHRONOLOGY | dated change orders + P&IDs + mechanical schedules + 2022-2024 operating changes | candidate explanation for the reported withdrawal break | annual discontinuity alone is not causal attribution | True |
| F facility identity | HIGH | FACILITY IDENTITY CROSSWALK | facility/address/parcel crosswalk + building commissioning dates + meter-to-building map | FRC1-to-later-campus mapping | 284/404/408 Social Circle remains an unresolved set | True |

The binding first action is one named-period air-side commissioning package: TAB/BMS CFM, SAT/RAT, OA/RA or mixed-air state, and a matched heat/load boundary.
