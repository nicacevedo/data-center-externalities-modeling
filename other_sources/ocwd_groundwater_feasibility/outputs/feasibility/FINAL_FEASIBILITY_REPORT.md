# OCWD groundwater data-feasibility audit

## Decision

`PUBLIC_DATA_ONLY_STATUS = PARTIAL`  
`PUBLIC_DATA_ONLY_TIER = TIER_C`  
`EXPECTED_STATUS_WITH_OCWD_WRMS = TIER_A_CANDIDATE`

The public package does not yet identify the joint state/forcing panel needed for a well/facility-resolution dynamic network benchmark. It does provide substantial public head coverage, an official basin geometry, long USGS river forcing, page-traceable recharge/injection accounting, intervention dates, and physical tracer benchmarks. The binding omission is the non-public WRMS well/facility time series—especially monthly geocoded per-well pumping, complete recharge/injection forcing, and authoritative vertical identity—with common QA and timestamps.

This is a data audit only. No groundwater dynamics, network, A/B matrix, VAR, state-space model, GNN, graphical model, MODFLOW calibration, interpolation, node selection, pumping inference, or optimization was performed.

## Public DWR head coverage

- DWR stations spatially inside Basin 8-001: **626**.
- Wells with usable head observations: **552**.
- Wells with at least 24 / 60 observations: **359 / 230**.
- Wells spanning at least 5 / 10 years: **417 / 333**.
- Wells overlapping Nov. 1990-Nov. 1999 / 2008+: **274 / 225**.
- Wells with DWR perforation metadata: **121** (19.3%).
- Usable observations: **60751**, from 1901-01-01 00:00:00 through 2026-06-25 11:57:00.
- Median of per-well median intervals: **38.0 days**; no interpolation.
- Strongest annual intersection: **179** wells in each year of the best five-year window and **146** in each year of the best ten-year window.
- Longest consecutive monthly support with at least 50 observed wells: **86 months**, 1991-10 through 1998-11.

The DWR periodic dataset republishes cooperating-agency data. Among usable heads, source-origin classifications are {"OCWD_ORIGIN_REPUBLISHED_BY_DWR": 56222, "INDEPENDENT_AGENCY_OBSERVATION": 4529}. The observation-independence ledger therefore identifies OCWD-origin records, clearly independent DWR/USGS collection, and unknown origin rather than double-counting a DWR copy as a second sensor.

## Supplementary construction and forcing evidence

The Orange-only WCR supplement yields match statuses: {"NO_MATCH": 282, "HIGH_CONFIDENCE_METADATA_MATCH": 171, "AMBIGUOUS": 116, "EXACT_ID": 57}. WCR coordinates remain supplementary and never replace DWR monitoring-station coordinates. No Shallow/Principal/Deep layer was assigned from a depth threshold.

USGS 11074000 supplies 31384 daily discharge records from 1940-09-30 00:00:00 through 2026-09-02 00:00:00 with approval/estimate/provisional flags preserved. OCWD's historical recharge report shows facility-level measured-flow and water-level inputs, calculated storage/percolation, and estimated losses. The 2023 GWRS report supplies one year of combined MBI monthly injection, while per-well monthly forcing remains missing.

The tracer registry contains 35 experiment-well records transcribed only from explicit LLNL/DOE and peer-reviewed tables. No graph pixels were digitized. These are future physical propagation checks, not targets used to fit this audit.

## Feasibility gates

| Gate | Result | Evidence |
| --- | --- | --- |
| G1 STATE | PASS | 552 public DWR wells have usable head observations; threshold is 50. |
| G2 TEMPORAL | PASS | Best annual intersection: 179 wells in every year of a 5-year window and 146 in every year of a 10-year window. Longest consecutive monthly run with at least 50 observed wells is 86 months (1991-10 to 1998-11); individual cadence remains heterogeneous. |
| G3 PUMPING | PENDING_REQUEST | OCWD documents monthly large-well WRMS reporting covering about 97% of extraction, but geocoded per-well raw pumping is not public in this package. |
| G4 RECHARGE | PARTIAL | Named-facility 2009-10 recharge and 2023 combined MBI monthly injection are reproducibly extractable, but complete geocoded monthly facility/well forcing is not public. |
| G5 VERTICAL | PARTIAL | DWR perforations cover 121 basin stations and MBI screens/layers are authoritative for that project; basinwide authoritative aquifer/model-layer mapping is missing. |
| G6 PROVENANCE | PASS | The audit distinguishes OBSERVED, REPORTED_MEASURED, DERIVED_FROM_MEASUREMENTS, ESTIMATED, MODELED, and REFERENCE_MODEL quantities. |
| G7 COMMON SUPPORT | PENDING_REQUEST | Public heads cannot yet be aligned with absent per-well WRMS pumping and complete facility/well recharge histories. |
| G8 SPATIAL VALIDATION | PASS | Public state locations are counted without performance-based selection; final held-out-well design remains conditional on cadence, vertical identity, and forcing overlap. |
| G9 INDEPENDENT PROPAGATION VALIDATION | PASS | Registry contains 35 published tracer experiment-well records and 5 MBI operational-start events; independence from future model fitting is explicit. |
| G10 REPRODUCIBILITY | PENDING_REQUEST | Public DWR/USGS data are machine-readable and report extracts are page-traceable, but required WRMS pumping/recharge tables are not public. |

## Exact blocking data

1. WRMS monthly production by individual well, with coordinates/datum, screens/layers, metered/reported versus allocated/estimated status, QA, revisions, and active dates.
2. Complete monthly or finer managed surface-recharge records by named facility: source, inflow/outflow, storage, calculated percolation, units, QA, and measured/estimated components.
3. Monthly or finer injection by well/casing and aquifer zone, including operational/backwash flags and set/swap/revision history.
4. A common well/facility identity crosswalk tying heads, pumping, screens, OCWD aquifer names, Basin Model layers, coordinates, and activity periods.
5. Raw tracer/intervention supporting series if they are to be used for quantitative held-out response tests.

## Next action

Submit the drafted observational WRMS request in `requests/OCWD_WRMS_DATA_REQUEST.md` first, asking for 1990-01-01 through the latest available records. If volume is prohibitive, request the exact November 1990-November 1999 transient Basin Model calibration dataset. Keep the separate MODFLOW package request secondary: the empirical WRMS observations are the higher-priority gate-closing data.
