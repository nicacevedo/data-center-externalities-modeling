# OCWD GW-1B preregistration

Status: **frozen before receipt of WRMS data**. GW-1B must reuse the GW-1A
calendar-month temporal boundaries and immutable spatial-fold membership.
Tracer and MBI response evidence remains reserved until the candidate
groundwater model is frozen.

## Comparison ladder

| ID | Information added | Scientific role |
|---|---|---|
| B0 | Prior observed head | Persistence |
| B1 | Gap, season, linear trend | Calendar drift |
| B2 | Pooled linear head history | Head-history response |
| B3 | Public USGS 11074000 discharge | Background/boundary hydrology; not managed recharge |
| B4 | Observed managed recharge/injection from WRMS | Managed recharge increment |
| B5 | Observed pumping | Pumping increment |
| B6 | Spatially structured pumping/recharge | Spatial forcing increment |
| B7 | Smallest physically constrained groundwater network | Network-structure increment |

The primary pumping comparison is **B5 minus B4**. The primary network
comparison is **B7 minus B5**. Pumping predictive value and network added
value are separate claims. No spatial pumping crosswalk will be invented
before authoritative WRMS well, screen, aquifer/layer, and facility metadata
arrive.

## Future placebos

1. **Season-preserving temporal pumping placebo.** Permute pumping across
   years within calendar month, preserving approximate seasonality while
   destroying the true time relation. Real pumping must outperform this
   placebo for pumping-response support.
2. **Spatial pumping placebo.** After authoritative aquifer/layer metadata
   arrive, permute pumping-well spatial identities only within defensible
   strata. A spatial/network model must outperform this placebo for spatial
   structure support.

Neither placebo is run in GW-1A because no WRMS pumping panel exists locally.

## Claim categories

`PUMPING_PREDICTIVE_VALUE = STRONG_SUPPORT` requires robust held-out
improvement, a model-difference interval excluding zero, positive median
well-level improvement, improvement not confined to a small subset, and real
pumping outperforming the temporal placebo.

`PUMPING_PREDICTIVE_VALUE = PARTIAL` denotes a small, heterogeneous, or
sensitivity-dependent aggregate improvement. `NO_SUPPORT` denotes no robust
OOS improvement or placebo performance comparable to real pumping.

`NETWORK_ADDED_VALUE` is adjudicated separately only after B7 exists. A
pumping improvement alone cannot establish network value.

