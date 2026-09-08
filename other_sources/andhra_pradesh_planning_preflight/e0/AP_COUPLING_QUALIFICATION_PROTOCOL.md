# AP coupling qualification protocol

Decide whether a **local own-pumping response family** can be used for
planning-scale (all-node / community) groundwater impact in an Andhra Pradesh
assessment unit.

This protocol does not fit a network model, does not define a path to
empirical M1N, and does not treat synthetic `neighbour_flux_share` or `γ` as
field quantities.

Parent plan: [EMPIRICAL_GW_QUALIFICATION_PLAN.md](../../../EMPIRICAL_GW_QUALIFICATION_PLAN.md).

```text
COUPLING_STATUS = WEAKLY_SUPPORTED | MATERIAL | UNRESOLVED
NOT_DETECTED != WEAK
DO_NOT_ATTEMPT_EMPIRICAL_M1N_YET
```

Default until admissible evidence is scored:

```text
COUPLING_STATUS = UNRESOLVED
```

---

## Why this exists

V3 Block B (known-truth, P-EXACT, favourable identification bundle): the frozen
own-pumping one-mode local family can represent the **directly pumped node**
and predicts **zero** at non-pumped included neighbours. All-node intervention
error therefore cannot fall below the neighbour-share floor once neighbours are
materially affected. Better metering does not repair that floor.

That is a limitation of **this frozen family**, not a statement about all
local groundwater models, and not an AP measurement.

Empirical consequence: a local all-node planning model is only a live option
where coupling is **weakly supported** by hydrogeological evidence. Material
coupling forces static-only planning-scale response (`STATIC_ONLY` for M1L
all-node use). Unresolved coupling is not weak coupling.

V2 `NETWORK_SUPPORT_FINAL = NOT_EARNED` remains controlling. This protocol
does not reopen M1N.

---

## Status definitions

**`MATERIAL`**
Admissible evidence shows that a withdrawal at a planning-relevant location
produces a planning-relevant head (or flux) response at non-pumped neighbours
or community wells in the same planning unit, or that mapped aquifer
connectivity makes that response expected.

Effect:

```text
evidence of material coupling
  => local all-node response family not valid
```

Planning-scale M1L is not earned. `CURRENT_E0_DECISION` becomes `STATIC_ONLY`
for dynamic all-node use when this status is frozen (other E0 domains may still
be incomplete for M0S). A pumped-node diagnostic study is **not** thereby
authorized as M1L validation and is not a network model.

**`WEAKLY_SUPPORTED`**
Admissible **strong** evidence supports that non-pumped neighbours / community
wells are **not** planning-material for the withdrawal locations and aquifer
under study, and supporting evidence is not contradictory.

Only this status can contribute to `LOCAL_STUDY_ELIGIBLE`.

**`UNRESOLVED`**
Insufficient admissible evidence, contradictory evidence, or only
insufficient-alone indicators.

```text
failure to detect coupling != proof of weak coupling
```

`UNRESOLVED` blocks `LOCAL_STUDY_ELIGIBLE`. It does **not** by itself freeze
`STATIC_ONLY` (missing files are not a hydrogeologic finding).

---

## Evidence hierarchy

Score only documented AP (or unit-specific) hydrogeologic evidence. Do not
import V3 magnitudes.

### Strong (can support MATERIAL or, in combination, WEAKLY_SUPPORTED)

- Pumping tests with documented radius of influence / time-drawdown.
- Interference tests between production and monitoring wells.
- Transmissivity and storage / specific-yield estimates with method and
  aquifer assignment.
- Mapped aquifer connectivity or barriers (NAQUIM or equivalent GIS, faults,
  clay barriers, compartment boundaries) joined to the same aquifer as the
  wells.
- Documented neighboring-well response to a known withdrawal (dates, wells,
  aquifer).

### Supporting (cannot alone set WEAKLY_SUPPORTED)

- Hydraulic gradients consistent with a connectivity hypothesis.
- Residual lagged coherence **after** rainfall/recharge and own-pumping
  controls.
- Synchronized drawdown/recovery not explained by shared climate after
  controls.

Supporting evidence may corroborate strong evidence. It may raise
`UNRESOLVED` to a documented contradiction. It may not convert “no
correlation found” into `WEAKLY_SUPPORTED`.

### Insufficient alone (may not set WEAKLY_SUPPORTED or MATERIAL by themselves)

- Geographic proximity of wells.
- Raw head correlation.
- Shared monsoon seasonality.
- Failure to detect correlation (power, cadence, and shared climate are
  confounded).

Proximity and raw correlation may motivate **acquiring** strong evidence.
They are not the qualification.

---

## Decision table

| Condition | Status |
|---|---|
| At least one strong item shows planning-relevant neighbour / community response, or mapped connectivity that implies it, and is not refuted by other strong items | `MATERIAL` |
| Strong evidence that the relevant aquifer is compartmentalized or that documented tests show negligible neighbour response at planning-relevant distance **and** supporting evidence is not contradictory | `WEAKLY_SUPPORTED` |
| Only insufficient-alone indicators, or no strong items, or contradiction among strong items | `UNRESOLVED` |
| Supporting residual coherence without strong items | `UNRESOLVED` (may be MATERIAL-leaning notes; not a freeze) |

“Planning-relevant” is defined **before** looking at regression outcomes: the
distance and receptors that would matter for a data-center withdrawal mapped
into the unit (community/monitoring wells, agriculture exposure nodes). Do
not back-solve relevance from a fitted coefficient.

---

## What permits a local pumped-node empirical study

A pumped-node study (own-response at monitoring wells the protocol says should
respond) may be considered **only if** the parent plan’s
`LOCAL_STUDY_ELIGIBLE` rule holds, which requires
`COUPLING_STATUS = WEAKLY_SUPPORTED` plus E0.1–E0.4 and E0.6.

If `COUPLING_STATUS = MATERIAL`, do **not** fit the frozen own-pumping local
family for all-node / community planning impact. That is static-only for
planning-scale dynamics. It is not a license for M1N.

If `COUPLING_STATUS = UNRESOLVED`, do not fit.

---

## What forces STATIC_ONLY (for dynamic planning response)

Freeze `STATIC_ONLY` for dynamic all-node use when `COUPLING_STATUS = MATERIAL`
is scored from strong evidence.

Also freeze `STATIC_ONLY` for dynamics when forcing or identity is
authoritatively absent (parent plan §A.2) — that is a data finding, not a
coupling finding.

There is **no** coupling outcome that authorizes empirical M1N.

---

## Current score

No pumping tests, interference tests, machine-readable NAQUIM GIS, or
documented cross-well effects have been obtained in the AP preflight.

```text
COUPLING_STATUS = UNRESOLVED
```

The downloaded CGWB yearbook PDF is network/cadence context. It has not been
scored as unit-level coupling evidence in this freeze.
