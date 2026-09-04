# Static-versus-dynamic ranking protocol

Status: **preregistered, not run**.

Each eligible candidate region will receive the same standardized incremental
groundwater-withdrawal pulse after pulse magnitude, duration, horizons,
node-weights, and head thresholds are frozen without inspecting rankings. A
locally estimated and frozen Andhra Pradesh groundwater model—not OCWD
coefficients—will generate `delta_h[n,tau | l]`.

For horizon `H`:

```text
D_cum[l,H] = sum_tau sum_n omega[n] max(-delta_h[n,tau|l], 0)
D_max[l,H] = max_(n,tau) max(-delta_h[n,tau|l], 0)
D_thr[l,H] = sum_(n,tau) 1{h[n,tau|l] < h_min[n]}
```

The primary comparator is the PSCC-style static water-scarcity metric. A local
CGWB extraction-stage/stress metric is secondary only where spatial units are
compatible. Preregistered comparisons are Spearman and Kendall correlations,
top-k overlap for a predeclared `k`, maximum displacement, and the count/share
of pairwise reversals.

No ranking will be generated until a local groundwater model and a common
candidate set exist.
