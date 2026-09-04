# OCWD GW-1B preregistered waiting module

`GW1B_DATA_STATUS = WAITING_FOR_WRMS`

This module freezes the GW-1B design amendment after GW-1A and GW-1C but
before any OCWD WRMS response relationship is inspected. A single local
filename scan on 2026-09-04 found no WRMS delivery. No pumping or managed
recharge data are fabricated or replaced with public basin aggregates.

The primary background is frozen as **B1C**: the GW-1A B1 seasonal/trend
response baseline plus the six fixed gridMET precipitation/ET0 controls.
Prado is retained only as a sensitivity control because B1CH worsened held-out
error relative to B1C in both T1 and T2.

Nothing in this module fits B4, B5, B6, B7, a spatial kernel, a groundwater
network, an A/B matrix, a GNN, or MODFLOW. Tracer and MBI evidence remains
reserved until after a future eligible B7 is frozen.

