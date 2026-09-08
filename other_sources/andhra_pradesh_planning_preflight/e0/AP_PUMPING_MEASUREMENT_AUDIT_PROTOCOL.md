# AP pumping measurement audit protocol

Apply this protocol to every withdrawal series **before** any M1L fit.
This file does not estimate pumping, does not invent a synthetic `σ`, and
does not authorize a model.

Parent plan: [EMPIRICAL_GW_QUALIFICATION_PLAN.md](../../../EMPIRICAL_GW_QUALIFICATION_PLAN.md).

```text
Do not estimate synthetic sigma for Andhra Pradesh.
```

---

## Purpose

V3 showed that, in a known-truth uncoupled design, mean-corrected multiplicative
pumping error attenuates intervention **amplitude** and that the attenuation
tracked **residualized** reliability, not unconditional reliability. V2 already
showed that scale bias, temporal aggregation, and spatial aggregation fail by
**other** mechanisms.

AP therefore needs an **audit of how pumping was produced**, not a transferred
error scale. A series without a class is `UNRESOLVED` and is not a M1L input.

---

## Series classes

Each well- or node-level pumping series receives exactly one class:

```text
OBSERVED_METERED
OBSERVED_REPORTED
ESTIMATED
PROXY
UNRESOLVED
UNUSABLE
```

| Class | Meaning | Claim limit if later used |
|---|---|---|
| `OBSERVED_METERED` | Volume from a meter (mechanical, electromagnetic, ultrasonic, or equivalent) with documented unit and timestamp | Strongest withdrawal evidence; still subject to missingness and revision audit |
| `OBSERVED_REPORTED` | Operator/agency reported as measured, without a meter record that can be inspected | Treat as measured-but-unverified; not equivalent to metered |
| `ESTIMATED` | GEC-2015/INGRES, allocation, assessment, or other assumption-based construction | Annual GWRA unit totals may support M0S static context only; inadequate alone for dynamic identification |
| `PROXY` | Electricity, pump-hours × capacity, irrigated area, or crop-ET transform | Cannot be used as pumping without a documented AP error characterization; collinear with recharge (V3 Block D risk) |
| `UNRESOLVED` | Class cannot be determined from available metadata | Not a M1L input |
| `UNUSABLE` | Fatal defects (missing treated as zero without documentation, unit contradiction, duplicate conflicting volumes, undocumented scale change) | Exclude |

Evidence classes from
[EVIDENCE_CLASSES.yaml](../config/EVIDENCE_CLASSES.yaml) still apply:
`ESTIMATED` assessment extraction is not metered monthly forcing.

---

## Audit checklist

Score every series on all items. Record the finding; do not impute.

1. **Meter vs estimate vs proxy.** Source method field or equivalent. If absent → `UNRESOLVED`.
2. **Revisions.** Vintage, reason, and whether superseded rows are retained.
3. **Annual / monthly (or other subannual) reconciliation.** Subannual sums vs published annual totals; document residual. Absence of subannual data is `INADEQUATE` for dynamics, not a reconciliation pass.
4. **Scale changes.** Unit changes (L, m³, Mcft, bcm), fiscal- vs calendar-year breaks, assessment-method changes.
5. **Missing vs zero.** Missing extraction is unknown, never zero
   ([AP_PLANNING_DATA_CONTRACT.yaml](../config/AP_PLANNING_DATA_CONTRACT.yaml)).
   A series that codes missing as 0 without a written convention is `UNUSABLE`.
6. **Duplicate measurements.** Same well/period, conflicting volumes.
7. **Electricity proxy availability.** If used, class is `PROXY`. Record tariff, hours, and whether monsoon/irrigation load is separable.
8. **Pump capacity / operating hours.** If volume = capacity × hours, class is `PROXY` unless hours are metered and capacity is documented.
9. **Allocation rules.** How well volumes become node/unit totals; coverage fraction.
10. **Rounding / smoothing.** Annual spreading of a single total into months is not subannual observation.
11. **Unit consistency.** Horizontal CRS is not a volume unit; keep volume units explicit.

Cadence (from the parent plan):

```text
Target              = monthly or finer
Scientific minimum  = subannual, adequate vs aquifer timescale,
                      head cadence, and analogue
Annual totals       = inadequate for dynamic identification
```

Monthly is the **target**, not a universal hard scientific threshold.

---

## Decision rules

- If method is meter and items 5–6 and 11 pass → `OBSERVED_METERED`.
- If method is reported measured, no inspectable meter → `OBSERVED_REPORTED`.
- If method is GEC/allocation/assessment → `ESTIMATED`.
- If method is electricity, irrigated area, ET, or capacity×hours → `PROXY`.
- If method unknown → `UNRESOLVED`.
- If missing=zero without convention, or irreconcilable duplicates/units → `UNUSABLE`.

A `PROXY` series does not become `OBSERVED_METERED` by calibration against
annual GWRA totals.

---

## Outputs (when an audit is later run)

One row per series: `production_id`, `groundwater_node_id`, class, cadence,
coverage fraction, missingness convention, revision flag, reconciliation
residual, claim limit. No synthetic `σ`. No model coefficient.

This protocol file is not that table. No audit table exists yet because
subannual well pumping has not been obtained.
