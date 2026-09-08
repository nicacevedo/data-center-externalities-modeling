# AP E0 delta status (public acquisition pass)

Relative to the pre-acquisition freeze at commit
`7a767e3f51c5d8f345723f56cac806457fc76cb2`
(`[Feature] AE Empirical GW Phase`).

Only documented status changes are listed. Frozen eligibility rules were not
modified. No model was fit.

Retrieval: `2026-09-08T00:15:03Z`.

---

## Terminal decision

| Item | Before | After |
|---|---|---|
| `CURRENT_E0_DECISION` | `UNRESOLVED` | `UNRESOLVED` (unchanged) |
| `LOCAL_STUDY_ELIGIBLE` | false | false |
| `STATIC_ONLY_ELIGIBLE` | false | false |
| `EMPIRICAL_M1N_AUTHORIZED` | false | false |
| `COUPLING_STATUS` | `UNRESOLVED` | `UNRESOLVED` |
| `ELIGIBLE_UNIT_COUNT` | 0 | 0 |
| `CURRENTLY_EARNED_PLANNING_COMPLEXITY` | `NONE` | `NONE` |
| `HIGHEST_PLAUSIBLE_NEAR_TERM_COMPLEXITY` | `M0S` | `M0S` |
| `M1L` | `NOT_EARNED` | `NOT_EARNED` |
| `M1N` | `NOT_EARNED` | `NOT_EARNED` |
| `existing_data_clears_blocker` | false | false |

`STATIC_ONLY` was not frozen: coupling and forcing absences remain missing-data,
not a completed hydrogeologic or agency confirmation that subannual pumping
does not exist.

---

## Domain rollups

| Domain | Before | After | Why |
|---|---|---|---|
| E0.1 spatial identity | `INADEQUATE` | `INADEQUATE` | Official 2024 GIS documented; polygons not obtained |
| E0.2 monitoring-well identity | `INADEQUATE` | `INADEQUATE` | Telemetry found; identity fields still missing |
| E0.3 withdrawal forcing | `INADEQUATE` | `INADEQUATE` | No subannual well/node pumping file |
| E0.4 recharge forcing | `INADEQUATE` | `INADEQUATE` | Rainfall now PARTIAL; recharge components still missing |
| E0.5 coupling evidence | `NOT_OBTAINED` | `NOT_OBTAINED` | PDFs obtained; GIS/tests not obtained; not weak coupling |
| E0.6 overlap / excitation | `INADEQUATE` | `INADEQUATE` | Heads longer; still no subannual pumping overlap |

---

## Item-level deltas

### E0.1

- **679 assessment-unit polygons:** `ACCESS_STATUS` remains `ACCESS_REQUIRED`.
  New fact: NWIC `GWR2024_CGWB` layer 8 is the official polygon service and
  was not queryable (`Instance not available on server`).
  `SCIENTIFIC_STATUS` remains `NOT_ASSESSABLE` (geometry not in-hand).
- **assessment-unit stable IDs:** `ACCESS_STATUS` `ACCESS_REQUIRED` →
  `OBTAINED` for the GWRA-2024 block-wise categorization PDF.
  `SCIENTIFIC_STATUS` remains `INADEQUATE` (names/categories, not joinable IDs).
- **679 vs 667 reconciliation:** no change.

### E0.2

- **telemetry / weekly heads:** `NOT_OBTAINED` / `NOT_LOCATED` →
  `ACCESS_STATUS=OBTAINED`, `SCIENTIFIC_STATUS=PARTIAL`.
  2,278,844 six-hourly rows (2021-01-04 to 2025-09-22) plus 259,248 rows
  (2026-01-01 to 2026-09-06). Still no stable ID.
- **updated heads after 2023-08-20:** stale CGWB manual ending 2023-08-20 is
  now accompanied by AP GWD telemetry through 2026-09-06.
  `ACCESS_STATUS=OBTAINED`, `SCIENTIFIC_STATUS=PARTIAL`. Identity unrepaired.
- **manual quarterly series:** additional AP GWD CSVs obtained; still
  name-keyed; `SCIENTIFIC_STATUS` remains `PARTIAL`.
- **stable ID / aquifer / monitoring-vs-pumping / datum:** not cleared.
  `RL_MSL` column exists and is empty.

### E0.3

- No item moved to `ADEQUATE` or even to a subannual `PARTIAL` pumping series.
- New negative search result: NWDP has no extraction/abstraction dataset.

### E0.4

- **rainfall:** `NOT_OBTAINED` → `ACCESS_STATUS=OBTAINED`,
  `SCIENTIFIC_STATUS=PARTIAL` (IMD RF25 years 1996, 2020, 2023).
- **recharge components / managed recharge / canal-tank:** no change.
- **GRACE:** still not downloaded (protocol).

### E0.5

- **hydrogeological reports:** still `PARTIAL`, now with statewide aquifer-system
  PDF plus Ananthapuramu and Nandyal NAQUIM PDFs and a 26-district catalog.
- **NAQUIM GIS, T/S, pumping tests, interference tests, cross-well effects:**
  no change; `COUPLING_STATUS` remains `UNRESOLVED`.
- Failure to obtain GIS/tests is **not** `WEAKLY_SUPPORTED`.

### E0.6

- Head support now includes public telemetry into 2026.
- Overlap/excitation items remain `INADEQUATE` / `NOT_ASSESSABLE` because
  subannual pumping and analogue documentation were not obtained.

---

## Access-versus-science examples from this pass

| Artifact | ACCESS_STATUS | SCIENTIFIC_STATUS | Clears blocker |
|---|---|---|---|
| AP GWD telemetry CSV | `OBTAINED` | `PARTIAL` | no |
| IMD RF25 1996/2020/2023 | `OBTAINED` | `PARTIAL` | no |
| GWRA-2024 block-wise PDF | `OBTAINED` | `INADEQUATE` | no |
| GWR2024 MapServer metadata | `OBTAINED` | `INADEQUATE` | no |
| GWR2024 layer-8 geometry | `ERROR` / `ACCESS_REQUIRED` | `NOT_ASSESSABLE` | no |
| NAQUIM district PDFs | `OBTAINED` | `PARTIAL` | no |
| Subannual well pumping | `ACCESS_REQUIRED` | `NOT_ASSESSABLE` | no |

---

## Planning complexity

Unchanged. M0S is still the highest plausible near-term rung and is still
not earned (polygons, unit-level GWRA tables, candidates, source feasibility).
M1L remains `NOT_EARNED`. M1N remains unavailable.
