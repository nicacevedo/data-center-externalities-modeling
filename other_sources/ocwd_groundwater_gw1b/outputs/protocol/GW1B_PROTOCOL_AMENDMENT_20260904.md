# GW-1B protocol amendment — frozen 2026-09-04

Status: **FROZEN BEFORE WRMS RESPONSE INSPECTION**

This amendment is justified only by the already-frozen GW-1A and GW-1C
results. The single permitted local scan found no WRMS delivery, so no pumping
or managed-recharge outcomes were opened or analyzed.

## Frozen response and background

The primary response is `delta_h`. The primary background model is **BC =
B1C**:

- frozen B1 season/trend response terms;
- `P_interval_mm`, `ET0_interval_mm` over `(t0,t1]` calendar days;
- `P_pre30_mm`, `P_pre90_mm`, `ET0_pre30_mm`, `ET0_pre90_mm`, all strictly
  pre-origin.

GW-1C found `CLIMATE_INCREMENTAL_SKILL = PARTIAL`, so climate remains a
mandatory background/confounding control. It found
`PRADO_AFTER_CLIMATE_SKILL = NONE`: B1CH worsened T1 and T2 held-out RMSE and
MAE. Prado is therefore excluded from primary BC and retained only as a
predeclared public-background-hydrology sensitivity control. It must never be
relabeled managed recharge.

## Frozen ladder and primary contrasts

| Stage | Frozen definition | Primary contrast |
|---|---|---|
| BC | B1 + fixed gridMET climate | B1C − B1: natural climate value |
| B4 | BC + managed recharge/injection | B4 − BC: managed-recharge value |
| B5 | B4 + basin-wide pumping | B5 − B4: pumping predictive value |
| B6 | B4 + spatially resolved pumping/recharge/injection | B6 − B5: value of WHERE forcing occurs |
| B7 | B6 + minimal potential-driven coupling, only after gate | B7 − B6: network added value |

The contrasts are incremental out-of-sample predictive-information tests, not
automatic causal estimates.

## Forcing alignment frozen before receipt

Reported monthly volume will remain monthly evidence. A derived
piecewise-constant daily rate will be `Q_month / days_in_month`; integrating it
over `(t0,t1]` must exactly preserve each monthly total. Every transition
exposure is labeled `DERIVED_FROM_MONTHLY_REPORTED_VOLUME`. The only forcing
windows are interval, pre-30, and pre-90; no window search is permitted.

Only `EXACT` and `HIGH_CONFIDENCE` authoritative ID crosswalks may enter the
primary analysis. `AMBIGUOUS` and `NO_MATCH` records remain outside it. Layers
cannot be guessed.

## Spatial and placebo protocol

B6 may use only exponential distance scales `{2, 5, 10} km`, selected on
VALIDATION and then frozen. Same-layer exposure exists only if OCWD supplies
authoritative layer identity.

- Temporal placebo: within each production well and calendar month, permute
  pumping across years.
- Spatial placebo: permute production-well spatial identities only within
  defensible authoritative layer/management strata.

Real forcings must outperform the relevant placebo for strong support.

## Network gate and reserved validation

B7 is prohibited unless B6 provides meaningful OOS support and/or beats its
spatial placebo, vertical/identity metadata are adequate, and common support
remains adequate. No free A matrix or GNN is allowed. A geometry-only diagnostic
without reliable vertical identity is `DIAGNOSTIC_NOT_PROMOTABLE`.

LLNL/Kraemer tracer evidence and the 2015/2020 MBI events remain completely
outside training, feature/scale/kernel selection, graph construction, and
tuning until an eligible B7 is frozen.

