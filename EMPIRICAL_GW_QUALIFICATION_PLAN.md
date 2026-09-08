# Empirical groundwater qualification plan (Andhra Pradesh)

Frozen E0 documentation. This file does not fit a groundwater model, does not
optimize siting, does not create V4, and does not transfer synthetic V2/V3
parameter magnitudes to Andhra Pradesh.

Companion E0 package:

- [other_sources/andhra_pradesh_planning_preflight/e0/README.md](other_sources/andhra_pradesh_planning_preflight/e0/README.md)
- [other_sources/andhra_pradesh_planning_preflight/e0/AP_E0_EVIDENCE_MATRIX.csv](other_sources/andhra_pradesh_planning_preflight/e0/AP_E0_EVIDENCE_MATRIX.csv)
- [other_sources/andhra_pradesh_planning_preflight/e0/AP_E0_STATUS.json](other_sources/andhra_pradesh_planning_preflight/e0/AP_E0_STATUS.json)
- [other_sources/andhra_pradesh_planning_preflight/e0/AP_PUMPING_MEASUREMENT_AUDIT_PROTOCOL.md](other_sources/andhra_pradesh_planning_preflight/e0/AP_PUMPING_MEASUREMENT_AUDIT_PROTOCOL.md)
- [other_sources/andhra_pradesh_planning_preflight/e0/AP_COUPLING_QUALIFICATION_PROTOCOL.md](other_sources/andhra_pradesh_planning_preflight/e0/AP_COUPLING_QUALIFICATION_PROTOCOL.md)
- [other_sources/andhra_pradesh_planning_preflight/e0/AP_EMPIRICAL_UNIT_ELIGIBILITY_PROTOCOL.md](other_sources/andhra_pradesh_planning_preflight/e0/AP_EMPIRICAL_UNIT_ELIGIBILITY_PROTOCOL.md)
- [other_sources/andhra_pradesh_planning_preflight/e0/AP_E0_ACCESS_REQUEST_GAP_AUDIT.md](other_sources/andhra_pradesh_planning_preflight/e0/AP_E0_ACCESS_REQUEST_GAP_AUDIT.md)
- [other_sources/andhra_pradesh_planning_preflight/requests/AP_PLANNING_DATA_ACCESS_REQUEST_V2.md](other_sources/andhra_pradesh_planning_preflight/requests/AP_PLANNING_DATA_ACCESS_REQUEST_V2.md)

```text
CURRENT_E0_DECISION = UNRESOLVED
LOCAL_STUDY_ELIGIBLE = false
STATIC_ONLY_ELIGIBLE = false
DYNAMIC_MODELING_AUTHORIZED = NO
EMPIRICAL_M1N_AUTHORIZED = NO
DO_NOT_ATTEMPT_EMPIRICAL_M1N_YET
NEW_SYNTHETIC_STUDY_REQUIRED = NO
CURRENTLY_EARNED_PLANNING_COMPLEXITY = NONE
HIGHEST_PLAUSIBLE_NEAR_TERM_COMPLEXITY = M0S
M1L = NOT_EARNED
M1N = NOT_EARNED
M0_PSCC_EXACT = NOT_RECOVERED
COUPLING_STATUS = UNRESOLVED
```

No response model may be fit before `CURRENT_E0_DECISION` is re-frozen from
acquired evidence as one of `LOCAL_STUDY_ELIGIBLE`, `STATIC_ONLY`, or
`UNRESOLVED`.

---

## 0. Controlling evidence (frozen)

Do not reinterpret synthetic quantities as Andhra Pradesh estimates.

**V2** (`other_sources/groundwater_identifiability_synthetic`):

```text
LOCAL_RESPONSE_STATUS = LOCAL_RESPONSE_NOT_IDENTIFIED
NETWORK_SUPPORT_FINAL = NOT_EARNED
```

**V3 independent audit:**

```text
DO_NOT_ATTEMPT_EMPIRICAL_M1N_YET
NEW_SYNTHETIC_STUDY_REQUIRED = NO
HIGHEST_VALUE_EMPIRICAL_NEXT_STEP = E
```

Lane E is an empirical local-response study **under weak-coupling
qualification**, with pumping-quality and recharge-proxy identification as
co-requirements. It is not a license to fit the frozen synthetic local family
to the public AP well panel.

**AP preflight** (`other_sources/andhra_pradesh_planning_preflight`):

```text
AP9 = FAIL
AP10 = FAIL
AP_SPATIAL_UNIT_STATUS = UNRESOLVED
M0_REPRODUCTION_STATUS = PARTIAL
M0_PSCC_EXACT = NOT_RECOVERED
```

Evidence hierarchy: V2 (known-truth qualification) → post-V2 audit (post-hoc
diagnosis) → V3 (prospective mechanism confirmation) → AP E0 (first real-world
test of whether the required information exists).

Forbidden transfers: synthetic `σ`, NIRE, λ, k=1 vs k=4, F1, γ, and
`neighbour_flux_share`. `neighbour_flux_share` is a synthetic dimensionless
diagnostic, not an AP field quantity.

---

## A. Formal E0

E0 is the evidence/data-acquisition phase that classifies whether AP can
support a local empirical study, static-only planning, or neither yet.

Acquisition proceeds in **three parallel tracks** (Section D). Do not serialize
identity, forcing, and hydrogeology unless an agency requires it.

### A.1 Six evidence domains

Each domain is scored only from documented evidence as:

```text
ADEQUATE | PARTIAL | INADEQUATE | NOT_OBTAINED
```

| Domain | Scientific content |
|---|---|
| **E0.1 spatial identity** | Versioned 679 assessment-unit polygons and IDs; vintage; 679/667 reconciliation; microbasin/village/mandal crosswalk |
| **E0.2 monitoring-well identity** | Stable station IDs; coordinates; well type; aquifer/layer; screen; monitoring vs pumping flag; active dates; datum/reference elevation; usable head series keyed to that master |
| **E0.3 withdrawal forcing** | Subannual well/node pumping; meter/estimate/proxy class; revisions; missingness; monthly–annual reconciliation |
| **E0.4 recharge forcing** | Rainfall and recharge components independent of the pumping series; managed recharge; canal/tank |
| **E0.5 hydrogeological coupling evidence** | NAQUIM GIS, aquifer connectivity/barriers, T/S, pumping/interference tests, documented neighbour response — scored by [AP_COUPLING_QUALIFICATION_PROTOCOL.md](other_sources/andhra_pradesh_planning_preflight/e0/AP_COUPLING_QUALIFICATION_PROTOCOL.md) |
| **E0.6 temporal overlap / excitation** | Common support of heads and forcing; cadence relative to aquifer-response timescale; documented pumping variation or intervention analogue |

Current domain scores are in
[AP_E0_STATUS.json](other_sources/andhra_pradesh_planning_preflight/e0/AP_E0_STATUS.json)
and must remain conservative until evidence is in hand.

### A.2 Terminal E0 decisions

Exactly one of:

```text
LOCAL_STUDY_ELIGIBLE
STATIC_ONLY
UNRESOLVED
```

**`LOCAL_STUDY_ELIGIBLE`** — all of the following hold:

1. E0.1 is `ADEQUATE` or `PARTIAL` such that monitoring wells can be joined to a
   versioned assessment unit.
2. E0.2 is `ADEQUATE` (stable ID, aquifer, monitoring-vs-pumping, datum).
3. E0.3 is `ADEQUATE` or `PARTIAL` meeting the **scientific minimum** in §B
   (not annual totals).
4. E0.4 is `ADEQUATE` or `PARTIAL` with a recharge/climate channel that is not
   a transform of the pumping series.
5. `COUPLING_STATUS = WEAKLY_SUPPORTED` under the coupling protocol (not
   `UNRESOLVED`, not `MATERIAL`).
6. E0.6 is `ADEQUATE` (overlap plus excitation or a declared analogue).
7. At least one unit passes
   [AP_EMPIRICAL_UNIT_ELIGIBILITY_PROTOCOL.md](other_sources/andhra_pradesh_planning_preflight/e0/AP_EMPIRICAL_UNIT_ELIGIBILITY_PROTOCOL.md).
8. An intervention-analogue level A, B, or C is declared; level C may not be
   called causal identification.

A local study, if authorized, is a **pumped-node / own-response** study in
eligible units. It is not empirical M1N and is not an AP-wide fit of frozen L.

**`STATIC_ONLY`** — freeze this when dynamics are not scientifically earnable
and that conclusion is evidence-based, not a default from missing files:

- `COUPLING_STATUS = MATERIAL` (local all-node family not valid for
  planning-scale response), or
- E0.3 is `INADEQUATE` after an authoritative confirmation that subannual
  withdrawal forcing does not exist, or
- E0.2 cannot be repaired (identity of heads remains unusable), or
- the minimum empirical study in §F fails its predeclared failure criteria.

`STATIC_ONLY` authorizes later **M0S** work if static-source evidence is
sufficient. It does not authorize M1L or M1N. It does not require exact
historical PSCC recovery (`M0_PSCC_EXACT = NOT_RECOVERED` does not block E0).

**`UNRESOLVED`** — current state. Missing coupling evidence is
`COUPLING_STATUS = UNRESOLVED`, not weak coupling. Failure to obtain files is
not a finding that the basin is static-only.

### A.3 Asymmetric coupling logic (summary)

Full protocol:
[AP_COUPLING_QUALIFICATION_PROTOCOL.md](other_sources/andhra_pradesh_planning_preflight/e0/AP_COUPLING_QUALIFICATION_PROTOCOL.md).

```text
evidence of material coupling  =>  local all-node response family not valid
failure to detect coupling     !=  proof of weak coupling
COUPLING_STATUS default        =  UNRESOLVED
```

There is no path from this protocol to empirical M1N.

---

## B. Pumping cadence (not a universal monthly gate)

```text
Target cadence     = monthly or finer
Scientific minimum = subannual forcing whose cadence is demonstrably
                     adequate relative to (i) aquifer-response timescale,
                     (ii) head-observation cadence, and (iii) the
                     intervention analogue under study
Annual totals      = inadequate for dynamic identification
```

V3 k=1 vs k=4 is **not** a metering specification: that contrast changed
estimand and TRAIN size. Do not write “weekly meters are required because
k=1 failed.” Do not write “monthly meters are required because k=4 passed.”

M0S may use **annual** unit-level GWRA extraction/recharge as `ESTIMATED`
static context. That does not make annual totals adequate for M1L.

Pumping series class (before any M1L fit):
[AP_PUMPING_MEASUREMENT_AUDIT_PROTOCOL.md](other_sources/andhra_pradesh_planning_preflight/e0/AP_PUMPING_MEASUREMENT_AUDIT_PROTOCOL.md).
Do not estimate a synthetic `σ` for AP.

---

## C. V3-to-empirical implication map

| V3 mechanism | Empirical requirement | Not licensed |
|---|---|---|
| Pumping attenuation of intervention **amplitude** (uncoupled, this error model) | Well/node withdrawal with meter-vs-estimate class; subannual variation; AP measurement-error audit | Treating AP error as the synthetic multiplicative `σ` ladder |
| Residualized reliability | Any local pumping regressor must be residualized the way it would actually be used; reliability from AP duplicates/revisions | Classical unconditional attenuation as an AP fact |
| Cadence (Tier 2) | Match head and forcing cadence to aquifer timescale; disclose sample size | k=1 vs k=4 as a causal metering rule |
| Pumped-node representability of frozen own-pumping L | If a local study runs, the target is the directly affected monitoring wells | “Local models in general work”; community-scale success |
| Spatial propagation limit of frozen own-pumping one-mode L | Hydrogeologic neighbour-materiality assessment | `neighbour_flux_share` as a field check; “all local GW models fail” |
| Training-target mismatch (small in V3) | Not the AP binding constraint | Intervention-aware retraining as the next project |
| Observation/proxy bias | Keep evidence classes; missing extraction is unknown, never zero | Collapsing OBSERVED heads with ESTIMATED forcing |
| Recharge-proxy placebo | Independent rainfall/recharge components | Cleaning pumping while leaving a pumping-collinear recharge proxy |
| Network oracle bundle vs γ | Do not densify wells as an M1N program | Empirical M1N; F1=1 as intervention validity |
| Prediction ⇏ intervention | Validation target is an intervention analogue, not RMSE | A new inversion threshold transferred from V2 |

---

## D. Three parallel acquisition tracks

Start together. Do not wait for polygons before requesting pumping tests, or
for NAQUIM before requesting station IDs.

**TRACK I — spatial / identity (E0.1, E0.2)**
679 assessment-unit polygons, stable IDs, vintage, 679/667 reconciliation,
microbasin/village/mandal crosswalk, monitoring-station master (coordinates,
well type, aquifer/layer, screen, monitoring vs pumping, active dates,
datum/reference elevation).

**TRACK II — forcing (E0.3, E0.4, E0.6 heads)**
Subannual well/node pumping; meter/estimate/proxy class; revisions;
missingness conventions; monthly/annual reconciliation; rainfall; recharge
components; managed recharge; canal/tank; corrected/updated heads;
telemetry/weekly series.

**TRACK III — hydrogeology (E0.5)**
NAQUIM machine-readable GIS, aquifer boundaries, structural barriers,
transmissivity, storage/specific yield, pumping tests, interference tests,
documented cross-well effects, hydrogeological reports for candidate units.

The human-facing request is
[AP_PLANNING_DATA_ACCESS_REQUEST_V2.md](other_sources/andhra_pradesh_planning_preflight/requests/AP_PLANNING_DATA_ACCESS_REQUEST_V2.md)
(**do not submit** until reviewed). Gap audit versus V1:
[AP_E0_ACCESS_REQUEST_GAP_AUDIT.md](other_sources/andhra_pradesh_planning_preflight/e0/AP_E0_ACCESS_REQUEST_GAP_AUDIT.md).

---

## E. Data-adequacy (current)

Item-level rows:
[AP_E0_EVIDENCE_MATRIX.csv](other_sources/andhra_pradesh_planning_preflight/e0/AP_E0_EVIDENCE_MATRIX.csv).

**Present and usable with stated class**

- Observed name-keyed quarterly heads: 71,384 spatial-QA-usable rows,
  1996-01-05 to 2023-08-20; median interval 92 days; no interpolation
  ([AP_GROUNDWATER_COVERAGE_SUMMARY.md](other_sources/andhra_pradesh_planning_preflight/outputs/tables/AP_GROUNDWATER_COVERAGE_SUMMARY.md)).
- Yearbook network description: 1,473 stations (676 dug, 797 piezometers);
  four rounds/year; 105 participatory weekly wells reported; machine-readable
  telemetry **NOT_LOCATED**.
- GWRA 2024 statewide **ESTIMATED** annual context: recharge 27.80 bcm/y,
  extraction 7.88 bcm/y, stage 29.83%; 679 units (591 safe / 38 semi-critical /
  2 critical / 9 over-exploited / 39 saline). Not monthly forcing; unit
  polygons not in-hand.

**Missing and blocking for any dynamic response model**

- Machine-readable 679 polygons/IDs and 679/667 crosswalk.
- Station master (ID, aquifer, monitoring vs pumping, datum).
- Subannual extraction with measurement class.
- Independent subannual recharge/rainfall.
- Admissible coupling evidence (tests, T/S, mapped connectivity).

**Missing for planning, not for E0 classification of dynamics**

- Eligible candidate parcels, `M_GW`, source entitlements, power
  interconnection, exact PSCC bundle.

No existing public file unexpectedly clears an E0 blocker. Public heads are
real observations; they do not clear E0.2 identity or E0.3 forcing.

---

## F. Minimum empirical validation study (not authorized now)

Question:

> Can a groundwater-response model recover intervention-relevant behavior well
> enough to constrain infrastructure planning?

**Not authorized** until `CURRENT_E0_DECISION = LOCAL_STUDY_ELIGIBLE`. Not an
AP-wide fit of frozen L. Not M1N.

- **Geography.** Eligible assessment units only, after polygons and station
  master exist, using
  [AP_EMPIRICAL_UNIT_ELIGIBILITY_PROTOCOL.md](other_sources/andhra_pradesh_planning_preflight/e0/AP_EMPIRICAL_UNIT_ELIGIBILITY_PROTOCOL.md).
  Do not pre-select Visakhapatnam (`primary_eligible=false`).
- **Time horizon.** Overlapping head and forcing support; target multiple
  monsoon cycles within the repaired identity period. Do not interpolate heads.
- **Train/test.** Time-blocked. Never random row splits. Hold out a later
  high-pumping or drought window. Disclose TRAIN length.
- **Intervention analogue hierarchy** (allowable claims follow the level):

```text
LEVEL_A = documented intervention (commissioning, canal shutdown,
          industrial/municipal well change with dates and volumes)
LEVEL_B = quasi-intervention (policy/season operational change with
          independent timing, not selected from the head series)
LEVEL_C = observational held-out pumping variation
```

  Level C may be reported as associational/predictive structure. It may **not**
  be called causal or intervention identification.
- **Validation target.** Datum-consistent head change at monitoring wells the
  coupling protocol says should respond. RMSE is a secondary diagnostic only.
- **Baselines.** Climate/persistence-only; static GWRA stage (must not be
  treated as within-year response); local own-pumping response. No network
  estimator.
- **Placebo / leakage.** Recharge-like placebo; wells that should not respond
  if weak coupling holds; no future forcing; missing extraction ≠ 0.
- **Failure criteria.** Identity/forcing unusable → stop. Material neighbour
  drawdown → do not use this local family for all-node planning. Placebo
  remains high after recharge controls → do not use pumping coefficients.
  RMSE succeeds and analogue fails → do not enter planning. Only annual
  estimated pumping → dynamics inadequate.

---

## G. Explicit no-go

- Fit frozen L to the public name-keyed quarterly panel as M1L validation.
- Transfer V3 `σ`, NIRE, λ, k, F1, or `neighbour_flux_share` to AP.
- Attempt empirical M1N, or densify wells to “earn” network support.
- Treat `NOT_DETECTED` coupling as `WEAKLY_SUPPORTED`.
- Treat GWRA annual stage as dynamic response.
- Treat GRACE as well-level ground truth.
- Transfer OCWD/California physical coefficients.
- Use electricity or crop proxies as pumping without the pumping-audit class
  `PROXY` and its claim limit.
- Select empirical units using RMSE, coefficient sign, correlation, or plots.
- Optimize siting or run M0/M0S/M1L/M1N ablation before E0 is re-frozen and
  shared planning inputs exist.
- Block E0 on exact historical PSCC recovery.
- Create V4 because a V3 result was interesting.
- Claim causal identification from a Level C split.

---

## H. Planning-integration pathway (after qualification only)

Frozen interface
([WATER_COUPLING_INTERFACE.md](other_sources/andhra_pradesh_planning_preflight/outputs/protocol/WATER_COUPLING_INTERFACE.md)):

```text
candidate site / withdrawal
  -> q_dc[n,t] = sum M_GW[n,l] * theta_gw[l,k,s] * rho[l,k,t] * a[l,k,s,t]
  -> qualified groundwater response at node n
  -> community/resource impact (agriculture / municipal exposure)
  -> planning constraint or objective
```

`APPROXIMATE` / `UNRESOLVED` `M_GW` stay out of the primary set. Groundwater,
reuse, desal, and other surface/municipal supply remain distinct.

Until E0 is `LOCAL_STUDY_ELIGIBLE` and §F passes, or E0 is `STATIC_ONLY` and
M0S inputs exist: no ranking experiment, no ablation, no siting.

If dynamics fail and static unit stress is documented, M0S may later constrain
siting via **source switching away from groundwater** without a dynamic head
forecast. Label that claim static.

Exact historical PSCC recovery is **not** an E0 gate:

```text
M0_PSCC_EXACT = NOT_RECOVERED
```

Any future reconstructed static baseline must be labeled a **new
paper-faithful reconstruction**, not historical exact M0.

---

## I. Model-complexity status

Taxonomy only: `M0`, `M0S`, `M1L`, `M1N`
([PLANNING_ABLATION_PROTOCOL.yaml](other_sources/andhra_pradesh_planning_preflight/config/PLANNING_ABLATION_PROTOCOL.yaml)).
Do not create new formal planning labels. Synthetic estimator rungs `B0/L/S/N`
are not these models.

| Model | Current status | Minimum evidence | Currently earned |
|---|---|---|---|
| M0 | Semantics PARTIAL; exact artifact not recovered | Canonical PSCC bundle | no |
| M0S | PREREGISTERED_NOT_RUN | Unit polygons + unit-level GWRA stage/extraction/recharge (annual ESTIMATED allowed) + source-distinct feasibility + candidates mapped to units | no |
| M1L | NOT_EARNED; BLOCKED_ON_AP9 | E0 `LOCAL_STUDY_ELIGIBLE` plus §F | no |
| M1N | NOT_EARNED | Not an available immediate path | no |

```text
CURRENTLY_EARNED_PLANNING_COMPLEXITY = NONE
HIGHEST_PLAUSIBLE_NEAR_TERM_COMPLEXITY = M0S
M1L = NOT_EARNED
M1N = NOT_EARNED
DO_NOT_ATTEMPT_EMPIRICAL_M1N_YET
```

M0S may proceed later if static-source evidence is sufficient even if dynamics
fail. M1N remains unavailable. V2 `NETWORK_SUPPORT_FINAL = NOT_EARNED` is
controlling.

---

## J. Future-paper contribution map

Primary subject: **groundwater-aware infrastructure planning under empirically
qualified environmental-response complexity**, not synthetic experimentation
for its own sake.

- **Main text.** Planning question; earned vs unearned complexity; AP E0
  result (`LOCAL_STUDY_ELIGIBLE` / `STATIC_ONLY` / `UNRESOLVED`); empirical
  study or documented inability to run it; planning implication.
- **Methods.** Evidence classes; no coefficient transfer; pumping-audit and
  coupling protocols; leakage and analogue-level claim limits.
- **Empirical section.** AP inventory; E0 scores; coupling status; analogue
  level. No V3 numbers as AP estimates.
- **Synthetic qualification (instrumental).** V2 prediction ⇏ intervention;
  V2 network not earned; V3 pumping-amplitude and omitted-neighbour
  mechanisms; V3 recharge placebo; oracle bundle vs γ. Required sentence: V3
  hypotheses were not preregistered before V2.
- **Appendix.** Hashes, 21-cell design, E0 matrix, access-request text,
  preflight coverage audit.

---

## K. Confidence

- High: V2/V3 statuses; AP9/AP10 fail; E0 currently `UNRESOLVED`; public heads
  do not clear identity/forcing blockers; M1N not earned; annual GWRA is not
  dynamic forcing; prediction ⇏ intervention.
- Medium-high: three parallel tracks are the right acquisition structure.
- Medium: whether agencies will release subannual well extraction, telemetry,
  and pumping tests; whether any Level A analogue exists.
- Medium-low: whether any unit will reach `COUPLING_STATUS = WEAKLY_SUPPORTED`
  at community-relevant distance. Default: do not assume it.
- High: no new synthetic study is required to interpret V3.

---

## L. Recommended path

```text
HIGHEST_VALUE_NEXT_ACTION = SUBMIT_REVIEWED_E0_DATA_REQUESTS_AND_ACQUIRE_PUBLIC_E0_SOURCES
DYNAMIC_MODELING_AUTHORIZED = NO
EMPIRICAL_M1N_AUTHORIZED = NO
CURRENT_E0_DECISION = UNRESOLVED
```

Human/data-acquisition actions, in parallel after request review:

1. Submit Track I/II/III MUST-HAVE items in the V2 request (do not submit in
   this documentation freeze).
2. Locate already-identified public sources that E0 still lacks as files:
   NAQUIM GIS if publicly listed; India-WRIS hydrologic boundaries; IMD
   rainfall product identity (download only a specified product after review,
   not an exploratory scrape).
3. Re-score the six E0 domains from acquired files. Freeze
   `CURRENT_E0_DECISION`. Only then consider §F or an M0S static path.
