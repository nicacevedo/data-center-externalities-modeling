# Forest City evidence-scope crosswalk

Do not merge 2012 FRC1 engineering evidence with 2023–2024 campus totals.
FRC1_ADDRESS = INTERVAL/SET_UNRESOLVED (284 / 404 / 408 Social Circle remain a set).
Dashboard evidence remains screenshot-only unless a structured source is independently recovered.

n_rows = 30

## Counts by bucket

| bucket | n |
| --- | --- |
| A_original_design_era_FRC1 | 11 |
| B_controller_design | 2 |
| C_weather | 4 |
| D_later_campus_annual | 5 |
| E_dashboard_screenshot | 3 |
| F_address_parcel | 1 |
| G_permit_utility | 4 |

## Rows

| source_id | bucket | date_period | observed_vs_inferred | usable_for | not_usable_for |
| --- | --- | --- | --- | --- | --- |
| META_FC_OPENING_2012_04_19 | A_original_design_era_FRC1 | 2012-04-19 | OBSERVED_OPENING | campus announcement | Does not report PUE/WUE, DeltaT, or controller setpoints. |
| META_FC_OPENING_NEWSROOM_2012 | A_original_design_era_FRC1 | 2012-04-19 | OBSERVED_OPENING | campus announcement | Same facts as Data Centers post; no engineering setpoints. |
| MAGUIRE_2011_OCP_REFLECTIONS | B_controller_design | 2011 planned operation | DESIGN_SPEC_PLANNED | server inlet / cold-to-hot aisle DESIGN | Planned Forest City operation as of 2011; not as-operated BMS. DeltaT is IT/server aisle rise, not proven facility effective ΔT. |
| OCP_2013_HOT_HUMID | B_controller_design | summer 2012; 2012-06-25 and 2012-07-01 events | OPERATOR_OBSERVED | operator-observed outdoor/indoor behavior; PUE seasonal | Blog, not BMS extract. Event DB/RH are outdoor snapshots. PUE 1.07 is seasonal, not WUE. Rutherfordton weather ~6 miles used for design analysis, not necessarily this blog's event sensors. |
| OCP_2012_PUE_WUE_DASHBOARD | E_dashboard_screenshot | 2012 dashboard launch | OBSERVED_DASHBOARD_PRODUCT | see post for WUE/PUE definitions; not recovered here until dashboard freeze | Describes dashboard product; raw time series not in this HTML. |
| DPR_FOREST_CITY_PROJECT | A_original_design_era_FRC1 | original campus construction | DESIGN_CONSTRUCTION | construction/design description | Does not identify later buildings; square feet are construction figures not measured load. |
| DPR_BUILDING_COMMUNITY_BLOG | A_original_design_era_FRC1 | construction of original FC building | DESIGN_CONSTRUCTION | construction | 125000 sqft penthouse is 5x 25000; consistent with four suites. Not a later-campus inventory. |
| ENR_2013_GREEN_LIKES | A_original_design_era_FRC1 | original building as constructed | DESIGN_CONSTRUCTION | construction journalism | 354k vs DPR 370k discrepancy preserved. Not BMS. |
| DCK_2013_SERVERS_HOTTER | A_original_design_era_FRC1 | summer 2012 | OPERATOR_OBSERVED_VIA_PRESS | operator quotes | Secondary; quotes OCP/Lee post. |
| DCK_2011_85_COLD_AISLE | A_original_design_era_FRC1 | 2011 | DESIGN_SPEC_VIA_PRESS | quotes Maguire; DCK interprets 35F as cold-to-hot aisle | 120F is DCK inference from 85+35, not a measured AHU ΔT. |
| ITNEWS_MCCAMMON_FC | A_original_design_era_FRC1 | second hottest NC summer; later membrane vs misters | OPERATOR_OBSERVED | qualitative operations | Membrane retrofit timing vs 2012 misting is not a 2012 controller parameter. Do not fit. |
| AIWIRE_2014_COLD_STORAGE | A_original_design_era_FRC1 | 2014 tour | OBSERVED_CAMPUS_TOUR | journalism/tour | Building numbering (B2 empty pad, B3 as second large hall) must not be overwritten by later marketing names without evidence. |
| ENR_2014_FRC4 | A_original_design_era_FRC1 | 2014 | DESIGN_CONSTRUCTION | construction award writeup | Does not give CFM or DeltaT. Permit-level capacities are not measured load. |
| CHARLOTTE_OBSERVER_COLD_STORAGE | A_original_design_era_FRC1 | 2014 media tour | OBSERVED_CAMPUS_TOUR | press tour | Paywall possible; qualitative. |
| META_FC_FACTSHEET_2025 | D_later_campus_annual | circa 2025 | OPERATOR_CLAIM_QUALITATIVE | community factsheet not EDI | No 2012 controller parameters. Do not treat later campus as 2012 Building 1. |
| META_EDI_2025 | D_later_campus_annual | 2020-2024 | REPORTED_ANNUAL | Meta site reporting; not ISO WUE | Site total; later years include unidentified later buildings/cold storage. 2020 electricity rounded. Do not fit 2012 controller to these. |
| TOWN_FC_WATER_TREATMENT | G_permit_utility | current page | SYSTEM_DESCRIPTION | municipal raw/finished water | Not Meta customer meter. Do not call municipal production Meta consumption. |
| NC_LWSP_FC_2023 | G_permit_utility | 2023 | REPORTED_MUNICIPAL | municipal LWSP | Industrial demand is municipal class, not proven Meta-only. |
| TOWN_FC_PERMIT_PORTAL | G_permit_utility | public portal | PORTAL | public records index | Detailed drawings may require login or in-person request. Do not invent permit numbers. |
| FBPUEWUE_DASHBOARD_LIVE | E_dashboard_screenshot | historical public | OBSERVED_IF_RECOVERED | UNIDENTIFIED_UNTIL_RECOVERY | Live site likely dead; Wayback attempted separately. |
| KFQD_2012_hourly | C_weather | 2012 | OBSERVED | climate_replay | as_operated_RAT |
| KEHO_2012_raw_isd | C_weather | 2012 | OBSERVED | climate_replay | as_operated_RAT |
| KGSP_2012_raw_isd | C_weather | 2012 | OBSERVED | climate_replay | as_operated_RAT |
| KRDM_hourly | C_weather | 2011-2024 | OBSERVED | climate_replay | as_operated_RAT |
| FC_annual_electricity | D_later_campus_annual | 2015-2024 | OBSERVED | campus_accounting | 2012 FRC1 cooling WUE |
| FC_annual_water | D_later_campus_annual | 2017-2024 | OBSERVED | campus_accounting | 2012 FRC1 cooling WUE |
| PRN_annual_audit | D_later_campus_annual | 2011-2024 | OBSERVED | campus_accounting | 2012 FRC1 cooling WUE |
| dashboard_recovery_status | E_dashboard_screenshot | 2012-2014 | SCREENSHOT_ONLY | identity_set | as_operated_RAT |
| v1_facility_registry | F_address_parcel | 2012-2025 | UNIDENTIFIED | identity_set | as_operated_RAT |
| permit_inventory | G_permit_utility | public portal | NOT_FOUND_PUBLIC | identity_set | as_operated_RAT |

