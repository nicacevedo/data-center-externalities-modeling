# AP empirical unit eligibility protocol

Pre-register which groundwater assessment units may enter a local empirical
study **before** any regression, correlation scan, coefficient inspection,
RMSE comparison, or visual response screening.

Parent plan: [EMPIRICAL_GW_QUALIFICATION_PLAN.md](../../../EMPIRICAL_GW_QUALIFICATION_PLAN.md).
Coupling: [AP_COUPLING_QUALIFICATION_PROTOCOL.md](AP_COUPLING_QUALIFICATION_PROTOCOL.md).
Pumping class: [AP_PUMPING_MEASUREMENT_AUDIT_PROTOCOL.md](AP_PUMPING_MEASUREMENT_AUDIT_PROTOCOL.md).

```text
Eligibility uses only pre-outcome evidence.
Do not select units based on regression results, correlation strength,
coefficient sign, RMSE, or visual response.
```

The preliminary preferred geographic unit remains the **GWRA assessment unit**,
status `UNRESOLVED` until polygons and IDs exist
([SPATIAL_UNIT_DECISION.md](../outputs/protocol/SPATIAL_UNIT_DECISION.md)).

---

## Eligibility may use only

- data completeness
- aquifer identity
- forcing availability
- head coverage
- intervention-analogue availability
- coupling qualification

Not: model fit quality, sign of a pumping coefficient, pairwise head
correlation, or plots of “visible drawdown.”

---

## Mandatory fields (unit-level)

A unit is ineligible until all are present:

1. Versioned `groundwater_node_id` matching the 679-unit vintage in use.
2. Authoritative polygon for that vintage.
3. Aquifer / layer assignment for the monitoring wells used as heads.
4. Monitoring-versus-pumping flag for those wells (pumping wells are not
   silent substitutes for piezometers).
5. Datum-consistent head series keyed to the station master.
6. Withdrawal forcing covering the unit with a pumping-audit class other than
   `UNRESOLVED` / `UNUSABLE`, at the scientific-minimum cadence in the parent
   plan (subannual; annual totals insufficient).
7. A recharge/climate channel independent of that pumping series.
8. `COUPLING_STATUS` scored for the unit (`WEAKLY_SUPPORTED` required for
   study entry; `MATERIAL` and `UNRESOLVED` do not enter).
9. Declared analogue level A, B, or C with dates.

---

## Minimum overlap

Heads, withdrawal, and recharge/climate must share a common time support
sufficient for:

- a time-blocked TRAIN period, and
- a later held-out analogue window,

with at least two monsoon cycles in the union of TRAIN and analogue support
preferred; one documented Level A event plus surrounding pre/post heads may
substitute if the event is independently dated.

Do not interpolate heads to manufacture overlap.

---

## Aquifer consistency

Monitoring wells, production locations, and the coupling evidence must refer
to the **same aquifer/layer**. Depth thresholds are not aquifer identity
(NAQUIM limitation already on the source registry).

---

## Forcing support

- Class `OBSERVED_METERED` or `OBSERVED_REPORTED` preferred.
- `ESTIMATED` subannual series may keep a unit eligible only if the estimation
  method is documented and is **not** a monthly spread of an annual total.
- `PROXY` does not by itself make a unit eligible for M1L-claiming analysis.
- Annual GWRA extraction alone: ineligible for the local study.

---

## Intervention-analogue status

| Level | Eligible for study? | Allowable claim if study later runs |
|---|---|---|
| A documented intervention | yes | strongest; still not automatic M1L earn |
| B quasi-intervention | yes | quasi-experimental language only |
| C observational held-out variation | yes | associational/predictive only; **not** causal/intervention identification |
| none | no | — |

---

## Coupling status

| `COUPLING_STATUS` | Eligible for local study? |
|---|---|
| `WEAKLY_SUPPORTED` | yes, if all other rules pass |
| `MATERIAL` | no (planning-scale local family not valid) |
| `UNRESOLVED` | no |

---

## Exclusions

- Units without polygons/IDs.
- GWRA **saline** units (39 reported statewide) for freshwater response
  identification.
- Units whose only heads fail the coordinate/identity QA in the preflight
  coverage audit and are not repaired by a station master.
- Visakhapatnam project region as an automatic unit
  (`primary_eligible=false`; city/region is not an assessment-unit ID).
- Outcome-based inclusion or exclusion after peeking at fits.

---

## When more than two units qualify

1. **If feasible, analyze all eligible units.** Feasible means the forcing and
   head panels are in hand and the study remains the minimum empirical design
   in the parent plan, not a statewide fishing expedition.
2. **Otherwise** apply this deterministic order, stopping when two units
   remain:
   1. Higher analogue level (A then B then C).
   2. Better pumping class (`OBSERVED_METERED` then `OBSERVED_REPORTED` then
      documented subannual `ESTIMATED`).
   3. Longer overlapping head–forcing support (more distinct observation times
      in the overlap, then longer span).
   4. Lexicographic `groundwater_node_id` as the final tie-break.

Do not replace this order with “the unit that looks like it responds.”

---

## Current application

No unit can be scored yet: E0.1 polygons/IDs are not in-hand,
`COUPLING_STATUS = UNRESOLVED` globally, and subannual well pumping is not
obtained.

```text
ELIGIBLE_UNIT_COUNT = 0
SELECTION_RULE_APPLIED = NOT_APPLICABLE
```
