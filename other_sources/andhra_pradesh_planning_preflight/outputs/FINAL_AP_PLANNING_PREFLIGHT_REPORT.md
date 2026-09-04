# Final Andhra Pradesh planning preflight report

## Scope and scientific boundary

This pass completed two independent tracks without committing, pushing,
altering frozen parents, fitting a groundwater model, transferring OCWD
coefficients, or solving a planning model. OCWD contributes a method and
identification protocol only. Andhra Pradesh physical parameters remain local
estimation targets.

## A. Repository and frozen-parent state

- Repository: `/home/nacevedo/RA/data-center-externalities-modeling`
- Branch: `main`
- HEAD/scientific baseline: `975821ae679713cc6b2bcd984f2d16d4328289a8`
- Initial dirty path: `Data-center-PUE-prediction-tool` with submodule-style
  lowercase `m`; it was not touched.
- `git submodule status` cannot resolve that path because `.gitmodules` has no
  mapping for it; no repair was attempted.
- Python: `/home/nacevedo/.conda/envs/dc_externalities/bin/python`, 3.11.15.
- Frozen parents: 203 tracked files across OCWD feasibility, GW-1A, GW-1C,
  and GW-1B v2 match the baseline Git blobs; parent status is empty.

See `outputs/provenance/FROZEN_PARENT_DEPENDENCY_MANIFEST.{csv,json}`.

## Track A — OCWD managed-forcing identification

The permitted workspace search was performed once at
`2026-09-04T17:37:06.846589+00:00`. It scanned 5,910 files and reviewed seven
OCWD/WRMS-term matches; every match was an existing baseline scientific
artifact. No new WRMS delivery was present.

```ini
TRACK_A_STATUS = WAITING_FOR_WRMS
TRACK_A_DATA_GATE = PENDING_DELIVERY
S_STAR = NOT_CONSTRUCTED_WITHOUT_WRMS
B4 = NOT_RUN
B5 = NOT_RUN
B6 = NOT_RUN
B7 = NOT_RUN
PLACEBOS = NOT_RUN
NETWORK_MODEL_JUSTIFICATION = UNRESOLVED
TRACER_MBI_VALIDATION = NOT_TOUCHED
```

There are consequently no delivery hashes, S* support counts, managed-recharge
result, pumping result, temporal placebo, spatial result, spatial placebo, or
legitimately earned B7 result to report. The existing GW-1B v2 protocol was not
revised. `OCWD_METHOD_TRANSFER_CONTRACT.md` records what transfers to India
methodologically and prohibits physical coefficient transfer.

## Track B — M0 static baseline audit

`M0_REPRODUCTION_STATUS = PARTIAL`. Repository narrative supports the
PSCC-style semantics: location/technology capacity and operations, demand,
cost, carbon, static WSF, renewable/power, and equity tradeoffs. The canonical
PSCC implementation/data, exact equations and weights, candidates, time
horizon, and a frozen numerical result were not found. No result was invented,
and no unrelated legacy repair was attempted. See
`outputs/protocol/M0_STATIC_BASELINE_SPEC.md`.

## Authoritative source registry and raw provenance

The registry contains 19 sources, led by CGWB/NWIC, AP groundwater/IT and
municipal authorities, NRSC/Bhuvan, CEA/APTRANSCO, Census/DES/CPCB, and
NASA/USGS products. External validation/source families are kept separate from
planning-ready inputs. Five gating artifacts were downloaded and pinned:

| Raw artifact | Bytes | SHA-256 |
|---|---:|---|
| NWDP/CGWB AP manual GWL 1991-2020 resource | 10,980,474 | `9f8f48406abd579b10b6379d0177df743f1d427833eae80688576a4d1c9be017` |
| NWDP/CGWB AP manual GWL 2021-2025 resource | 1,481,218 | `1bb1399deb6391566ca6ac4bfe1e255fd2a99eb19e32feca0de587839c504dbb` |
| CGWB AP Ground Water Year Book 2024-25 | 7,273,182 | `37353014cb7eccb457940fc70db78b2d2b46777b0efcdcbeb6cb3e6dc441d55c` |
| CGWB Dynamic Ground Water Resources AP 2024 | 8,363,672 | `d2e3c9d86665f250228c71045ea120709076c72d14b19cb9608a68a9a3b52bbf` |
| AP Data Center Policy 4.0, 2024-29 | 421,027 | `63d5fdafcc5fc7aa4e7e90bcd000a57ffcd9a0202f74d30b7a969971c0dd7ae0` |

The exact official URLs, access times, limitations, and evidence classes are
in `sources/AP_AUTHORITATIVE_SOURCE_REGISTRY.*` and
`outputs/provenance/RAW_DOWNLOAD_MANIFEST.*`.

## Public groundwater coverage audit

The two downloaded NWDP/CGWB CSVs contain 87,239 rows, of which 87,217 have a
numeric time/value. The nominal 1991-2020 resource begins in the defensible
screened subset in January 1996; the nominal 2021-2025 resource ends on
2023-08-20. These filenames are therefore not treated as verified coverage.

The CSVs have no stable station ID, QA flag, measurement-method field,
screen/perforation, or aquifer/layer. A conservative current-state label and
published-coordinate-envelope screen excludes 121 numeric Khammam-labeled
rows; 998 further candidate rows lack coordinates and 14,714 fall outside the
published AP envelope. All raw rows are preserved. The screen is a plausibility
filter—not a state-polygon join and not outcome selection.

The resulting coverage summary is:

- 71,384 spatial-QA-usable observations (81.960136% of non-Khammam numeric
  candidates);
- 2,584 agency/district/name keys as a lower identity bound and 2,746
  station-location series as an upper bound;
- 160 name keys map to multiple coordinate pairs and three series-date groups
  contain conflicting numeric values;
- coverage 1996-01-05 through 2023-08-20 across 28 calendar years and 16
  normalized district labels;
- 1,011 series have at least 24 observations, 384 at least 60, 1,304 span at
  least five years, and 701 span at least ten years;
- median series has 17 observations over four years; median within-series
  interval is 92 days;
- interval-frequency classes: 7 series at <=45 days, 617 at 46-90, 1,627 at
  91-180, 212 above 180, and 283 singleton series.

CGWB separately reports a current network of 1,473 stations (676 dug wells and
797 piezometers), primarily measured four times per year, and 105 participatory
weekly wells. The yearbook prose says March 2025 while its table/figure says
March 2024 for the same total; the discrepancy is retained. An official
machine-readable AP high-frequency telemetry resource was not located.

No head was interpolated and no groundwater model was fit. GRACE remains
coarse, complementary total-storage evidence, never well-level ground truth.

## Static groundwater/agriculture context

The CGWB/AP 2024 assessment reports estimated—not monthly observed—state
totals: 27.80 bcm/year recharge, 26.41 bcm/year extractable resource, 7.88
bcm/year extraction, and 29.83% extraction stage. Extraction is reported as
6.75 bcm irrigation, 1.01 bcm domestic, and 0.13 bcm industrial. It reports
15.75 lakh ha groundwater-irrigated versus 22.37 lakh ha surface-water
irrigated. Of 679 assessment units: 591 safe, 38 semi-critical, 2 critical, 9
over-exploited, and 39 saline. These quantities are static estimated context,
not dynamic forcing or candidate-site entitlement.

Agriculture readiness is partial: official crop/land-use and ET product
families exist, but crop-season demand, groundwater dependence, uncertainty,
and node crosswalks are missing. Municipal readiness requires access: Census
and CPCB provide population/facility context, but current service areas,
abstraction, alternate supply, losses, and uncommitted reuse are absent.

## Spatial-unit and crosswalk decision

`AP_SPATIAL_UNIT_STATUS = UNRESOLVED`. The preliminary preferred base is the
groundwater assessment unit because the GWRA attaches recharge, extraction,
and stage to 679 units. Selection is blocked by missing canonical polygons,
stable IDs, vintage, and crosswalks. The GWRA describes 748 microbasins and
17,467 villages, while the yearbook reports 667 revenue mandals and the GWRA
reports 679 assessment units/mandals; an authoritative versioned crosswalk is
required.

The AP policy establishes a statewide data-center framework and up-to-1-GW
target; a company announcement supports Visakhapatnam as a documented project
region. Neither is a full candidate set. Visakhapatnam is therefore retained
as a regional reference with `UNRESOLVED` mappings and
`primary_eligible=false`. `M_GW`, `M_AG`, and `M_MUN` contain schemas only.

## Water-source feasibility and coupling

Groundwater, reclaimed wastewater, desalinated seawater, and other
surface/municipal supply are distinct. Each is currently `UNCERTAIN` for the
Visakhapatnam reference because entitlement, usable/uncommitted capacity,
quality, commitment, conveyance, and source share are unverified. No capacity
is inferred from coastal proximity, treatment capacity, policy language, or
naming.

The frozen future interface is

```text
q_dc[n,t] = sum_(l,k,s) M_GW[n,l] * theta_gw[l,k,s]
             * rho[l,k,t] * a[l,k,s,t].
```

Neither `theta_gw`, `rho`, nor unresolved mappings received fabricated values.

## Preregistered decision experiment

The static-versus-dynamic protocol defines standardized candidate pulses and,
after a locally estimated AP groundwater model is frozen, cumulative drawdown,
worst-node drawdown, and threshold exposure. It compares their rankings with
the PSCC-style static WSF and secondarily a spatially compatible CGWB
extraction-stage metric using Spearman/Kendall correlation, predeclared top-k
overlap, maximum displacement, and pairwise reversals. No ranking was computed.

The planning ablation is frozen as M0 (static WSF), M0S (source-resolved
static), M1L (local dynamics), and M1N (network dynamics). Demand, costs, power,
candidates, feasible sources, capacity, and reliability constraints must be
identical. Future decision-value outputs are capacity relocation, source
switching, cost premium, and a static-plan replay reporting head violations,
duration, affected nodes, agriculture exposure, and municipal exposure. No
single arbitrary welfare score is introduced.

## AP1-AP10 readiness

| Gate | Status | Binding reason |
|---|---|---|
| AP1 candidates | PARTIAL | Policy and one regional reference, no canonical eligible set |
| AP2 site->groundwater | ACCESS_REQUIRED | Candidate parcels and assessment polygons/IDs absent |
| AP3 groundwater states | PARTIAL | Large public panel, but identity/QA/vertical/geography defects |
| AP4 recharge/extraction | ACCESS_REQUIRED | Annual estimates only; no geocoded monthly dynamic forcing |
| AP5 agriculture | PARTIAL | Source families identified; demand/dependence/crosswalk absent |
| AP6 municipal | ACCESS_REQUIRED | Service, abstraction, alternatives, reuse and crosswalk absent |
| AP7 source feasibility | ACCESS_REQUIRED | Site entitlement/capacity/conveyance unverified |
| AP8 M0/power | PARTIAL | Semantics/source families only; canonical bundle absent |
| AP9 local groundwater model | FAIL | Not fit and local state/forcing/vertical inputs incomplete |
| AP10 common support | FAIL | No common site-grid-source-sector-groundwater panel |

OCWD success cannot change AP9.

## Reproducibility and exact next action

The deterministic build verifies parent and raw hashes, emits source/coverage
tables and one decision-relevant public-groundwater coverage figure, and runs
guard tests. A multilayer planning map was not generated because the spatial
crosswalk is not yet defensible.

The highest-value next action is one coordinated authoritative data request and
reconciliation sprint for: (1) the 679 assessment-unit/748-microbasin
geometry/ID/vintage crosswalk; (2) corrected stable-ID groundwater heads with
QA, screens, aquifers and telemetry; (3) monthly geocoded recharge/extraction;
and (4) canonical candidate parcel, grid, source entitlement/capacity,
agriculture and municipal mappings. Then estimate and freeze an Andhra Pradesh
groundwater model. Only after that should the standardized static-versus-
dynamic ranking be run; M0/M0S/M1L/M1N follows only if those gates pass.
