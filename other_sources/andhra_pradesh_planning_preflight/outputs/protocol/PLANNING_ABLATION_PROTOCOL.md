# Planning ablation protocol

Status: **preregistered, not run**.

| Model | Water representation |
|---|---|
| M0 | PSCC-style static WSF |
| M0S | Source-resolved but static |
| M1L | Source-resolved plus locally estimated groundwater dynamics |
| M1N | Source-resolved plus locally estimated and validated network groundwater dynamics |

All four models must use the same demand, costs, power options, candidate
locations, feasible source set, and non-water constraints. Only the water
representation changes.

Decision-value metrics are capacity relocation,
`0.5 sum_l |x_M1[l]-x_M0[l]| / total_capacity`; source switching among
physically distinct supplies; cost premium `(C_M1-C_M0)/C_M0`; and replay of
the static plan under dynamic physics, reporting head-threshold violations,
duration, affected groundwater nodes, agriculture exposure, and municipal
exposure. These consequences remain separate rather than being collapsed into
an arbitrary welfare score.
