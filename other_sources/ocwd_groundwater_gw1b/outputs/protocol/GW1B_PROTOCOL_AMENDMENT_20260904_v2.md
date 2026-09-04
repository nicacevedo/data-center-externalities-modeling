# GW-1B protocol amendment v2 — frozen 2026-09-04

Status: **FROZEN BEFORE THE V2 WRMS DELIVERY CHECK OR ANY PUMPING-RESPONSE INSPECTION**

This additive amendment corrects only the non-nested B6 wording in the prior
waiting protocol. It does not overwrite or silently reinterpret the earlier
files. All unchanged GW-1A/GW-1C population, holdout, outcome, background,
bootstrap, and prohibited-inference rules remain binding.

## Correct nested hierarchy

The primary response is `delta_h`, and **BC is the frozen GW-1C B1C**:
season/trend plus the six fixed gridMET precipitation/ET0 features. Prado
remains sensitivity-only because GW-1C found no incremental OOS value after
climate.

| Stage | Exact frozen definition |
|---|---|
| BC | Frozen GW-1C B1C |
| B4 | BC + basin-wide `Phi(managed recharge)` + basin-wide `Phi(injection)` |
| B5 | B4 + basin-wide `Phi(pumping)` |
| B6 | B5 + spatial `Phi(pumping)` + spatial `Phi(managed recharge)` + spatial `Phi(injection)` |

Thus `BC ⊂ B4 ⊂ B5 ⊂ B6`. B6 must retain every B5 basin-total feature.

The headline contrasts are:

- **B5 − B4:** incremental predictive value of pumping quantity.
- **B6 − B5:** incremental predictive value of spatial location beyond total
  quantity.

B4 − BC is supporting managed-recharge/injection context.

## One immutable common-support population

One sample `S*` must be constructed before model comparison. It contains only
frozen GW-1C transitions for which every BC feature, every basin-total managed
forcing feature, all spatial features required to select among 2/5/10 km,
eligible authoritative identities/coordinates, original temporal split, and
original spatial fold are available. `S*` is used unchanged for BC, B4, B5,
and B6.

The historical window remains 1991-10 through 1998-11; the frozen temporal
boundaries and `SPATIAL_FOLDS.csv` remain exact. No period or fold may be
changed after observing support or skill. If `S*` is inadequate or a fold
loses meaningful TEST support, execution stops.

## Monthly forcing alignment

For monthly volume `Q_jm` and transition `(t0,t1)`, the interval exposure is

```
sum_m Q_jm × days((t0,t1] ∩ month_m) / days_in_month(m).
```

This is `DERIVED_FROM_MONTHLY_VOLUME` under an explicit uniform-within-month
allocation—not daily measured forcing. The same proportional-overlap
arithmetic defines interval, pre-30, and pre-90 exposure. Original source
classes (`MEASURED_REPORTED`, `ALLOCATED`, `ESTIMATED`, `CALCULATED`) must be
preserved. No alternative lag search is allowed.

The secondary calendar-compatible sensitivity is frozen to transitions whose
origin and target dates are both calendar month-end, so the interval contains
complete intervening calendar months.

## Spatial exposure

For authoritative projected coordinates,

```
w_ij(l) = exp(-d_ij/l),       E_i,k(l) = sum_j w_ij(l) Q_jk.
```

Only `l ∈ {2, 5, 10} km` may be considered. One common `l` is selected on
VALIDATION only and then used for pumping, managed recharge, and injection in
the primary B6. TEST cannot select it. Same-layer exposure is a pre-specified
sensitivity only when authoritative layer/aquifer identity exists; layers are
never guessed.

## Model, metrics, and uncertainty

Primary models are train-scaled OLS. Only if the standardized design is
numerically problematic may Ridge with `alpha ∈ {1e-6, 1e-4, 1e-2}` be selected
on VALIDATION. The primary metric is TEST RMSE of `delta_h`; secondary metrics
are MAE, bias, fraction of wells improved, median per-well improvement, and
per-well IQR. Uncertainty uses 1,000 well-level bootstrap resamples with seed
20260904; transition rows are not independent bootstrap units.

## Placebos frozen before data inspection

- **Temporal pumping placebo:** 100 replicates, seed base 2026090400. Within
  each production well, calendar month, and TRAIN/VALIDATION/TEST partition,
  permute across years. No value crosses a temporal split. Each replicate uses
  the real model's validation procedure; TEST never selects.
- **Spatial placebo:** 100 replicates, seed base 2026090500. Run only with
  authoritative layer/aquifer or another defensible stratum, permuting
  production-well spatial identities within stratum. Physically impossible
  layer reassignment is prohibited. The real validation procedure is reused.

## Stop before B7

No groundwater network, GNN, or A matrix may be fit in this task. Tracer and
MBI evidence remains untouched. After B5/B6 and placebos, report network
justification as `EARNED`, `NOT_EARNED`, or `UNRESOLVED`; even `EARNED` only
recommends a separate B7 experiment.

