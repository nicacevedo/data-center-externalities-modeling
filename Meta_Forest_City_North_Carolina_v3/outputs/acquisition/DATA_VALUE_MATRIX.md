# Data-value matrix



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
