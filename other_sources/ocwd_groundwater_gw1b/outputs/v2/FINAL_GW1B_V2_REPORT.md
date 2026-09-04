# Final OCWD GW-1B v2 nested managed-forcing readiness report

## A. Repository state

- Repository: `/home/nacevedo/RA/data-center-externalities-modeling`
- Branch / HEAD: `main` / `131657d62712f76acd12dcff461524937ca9fe44`
- Scientific baseline: `131657d62712f76acd12dcff461524937ca9fe44`
- Task-start dirty state: ` m Data-center-PUE-prediction-tool` only.
- Python: `/home/nacevedo/.conda/envs/dc_externalities/bin/python` (3.11.15).
- Git submodule enumeration remains unavailable because `.gitmodules` has no mapping for the existing PUE path; it was not modified.

## B. Parent and prior-protocol integrity

All material artifacts in the feasibility, GW-1A, and GW-1C parents match their exact baseline blobs or their committed package manifests. Start/end tree hashes are identical. The five previously existing GW-1B protocol/report artifacts also retain their recorded baseline SHA-256 values. No reset, clean, merge, rebase, commit, or push occurred.

## C-D. Additive v2 correction and exact hierarchy

The earlier preregistration remains untouched. `GW1B_PROTOCOL_AMENDMENT_20260904_v2.yaml` and its Markdown counterpart add the correction:

```
BC = frozen GW-1C B1C
B4 = BC + Phi(total managed recharge) + Phi(total injection)
B5 = B4 + Phi(total pumping)
B6 = B5 + Phi(spatial pumping) + Phi(spatial managed recharge) + Phi(spatial injection)
```

Therefore `BC ⊂ B4 ⊂ B5 ⊂ B6`; B6 retains every B5 total feature. Primary contrasts are B5−B4 for pumping quantity and B6−B5 for spatial location. The versioned protocol and ingestion contract predate the one WRMS scan; no pumping-response outcomes were inspected.

## E. Common support

One immutable `S*` must be used by BC/B4/B5/B6. It requires every BC, basin-total, identity, coordinate, and spatial feature through all 2/5/10 km B6 candidates. Model-specific samples and period/fold reselection are prohibited.

- Original GW-1C transitions: **9406**.
- Pre-WRMS BC-eligible: **8686 transitions / 186 wells**.
- `S*`: **PENDING / not constructible without WRMS**. Retained rows, wells, retention percentage, and final split/fold counts are not identified; missing forcing is not zero.

Pre-WRMS BC support by split/fold (context only, not `S*`):

| temporal_split | spatial_fold | pre_WRMS_BC_eligible_transitions |
|---|---|---|
| TEST | 1 | 146 |
| TEST | 2 | 361 |
| TEST | 3 | 276 |
| TEST | 4 | 239 |
| TEST | 5 | 219 |
| TRAIN | 1 | 917 |
| TRAIN | 2 | 1668 |
| TRAIN | 3 | 1279 |
| TRAIN | 4 | 1309 |
| TRAIN | 5 | 813 |
| VALIDATION | 1 | 210 |
| VALIDATION | 2 | 459 |
| VALIDATION | 3 | 315 |
| VALIDATION | 4 | 300 |
| VALIDATION | 5 | 175 |

## F. Monthly-forcing arithmetic

For monthly `Q_jm`, interval exposure is `sum_m Q_jm × overlap_days((t0,t1],m) / days_in_month(m)`. Pre-30 and pre-90 use identical proportional overlap. Source measurement classes remain separate and every transition feature is `DERIVED_FROM_MONTHLY_VOLUME`, never daily measured. Explicit zero rows are required for active months; missing months are not zero. Full-month conservation is guarded at 1e-12 acre-feet. The month-compatible sensitivity requires both origin and target dates to be calendar month-end.

## G. Spatial exposure

`w_ij(l)=exp(-d_ij/l)` and `E_i,k=sum_j w_ij Q_jk`, using authoritative projected coordinates. Only 2, 5, and 10 km are eligible; one common scale is selected on VALIDATION and shared across the primary spatial family. TEST never selects. Same-layer exposure is sensitivity-only with authoritative layer metadata; layers are not guessed.

## H. Placebos

- Temporal pumping: 100 fixed replicates, permuting across years within production well, calendar month, and TRAIN/VALIDATION/TEST partition. Values never cross splits.
- Spatial: 100 fixed replicates, run only within authoritative aquifer/layer or another defensible stratum.

Each placebo uses the real model's validation procedure; TEST remains untouched for selection.

## I-J. Ingestion readiness and WRMS availability

`WRMS_INGESTION_READY = YES`. The contract accepts a manifest-controlled CSV/Parquet/Excel delivery and guards units, required IDs, duplicate months, coordinate/activity conflicts, negative volumes, evidence classes, crosswalk status, QA/revisions, and allocation conservation.

The single path/type scan initially surfaced four untracked filename matches. Path-only adjudication identified two as Prineville artifacts and two as M100 artifacts. No candidate is OCWD/WRMS; no second scan or content inspection occurred. Thus `GW1B_DATA_STATUS = WAITING_FOR_WRMS`.

## K-L. WRMS gates and S* support

WRMS QA, G3/G4/G5/G7/G10 re-evaluation, and final `S*` counts are `PENDING_WRMS`. This is not a failed empirical result. Aggregate public pumping, synthetic pumping, inferred pumping, and MODFLOW forcing were not substituted.

## M-R. Managed-forcing results and classifications

- B4 managed recharge/injection: `NOT_RUN_WAITING_FOR_WRMS`
- B5 pumping quantity: `NOT_RUN_WAITING_FOR_WRMS`
- Temporal placebo: `NOT_RUN_WAITING_FOR_WRMS`
- B6 spatial forcing: `NOT_RUN_WAITING_FOR_WRMS`
- Spatial placebo: `NOT_RUN_WAITING_FOR_WRMS`
- `PUMPING_PREDICTIVE_VALUE = UNRESOLVED`
- `SPATIAL_FORCING_VALUE = UNRESOLVED`

No scientific figure was created because no WRMS experiment ran.

## S. Network decision

`NETWORK_MODEL_JUSTIFICATION = UNRESOLVED`. B7, a GNN, and an A matrix were not fit. Tracer and MBI evidence remains completely untouched. An earned decision requires future B5/B6 and placebo evidence under this frozen protocol.

## T. Tests, replay, and hashes

The readiness guards cover frozen parents and prior protocol, strict nesting, exact climate/Prado state, ingestion schema, units, duplicate/missing/negative/conflicting records, evidence classes, monthly conservation, `S*`, split-preserving placebos, no substitutions, and no B7 execution. Canonical output hashes and deterministic replay status are under `outputs/provenance/`.

## U. Exact next experiment

On WRMS receipt: preserve and hash raw files before scientific inspection; validate schema, units, QA/revisions, measurement classes, coordinates, active dates, crosswalks, screens/layers, and completeness; re-evaluate G3/G4/G5/G7/G10; construct one `S*`; then execute B4→B5→B6 plus frozen placebos. Stop before B7. Recommend the separate B7 + reserved tracer/MBI experiment only if `NETWORK_MODEL_JUSTIFICATION = EARNED`.
