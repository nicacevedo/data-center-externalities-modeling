# OCWD GW-1C climate/background null benchmark

This isolated module extends the frozen GW-1A no-pumping benchmark with a
pre-specified, small gridMET climate subset. It tests whether precipitation and
grass-reference evapotranspiration improve held-out groundwater-head-change
prediction, and whether the already-frozen Prado discharge features add value
after those climate controls.

Scope is deliberately limited:

- response and holdouts come unchanged from frozen GW-1A;
- groundwater heads are never interpolated;
- B1 is reproduced before any climate comparison;
- B1C uses only the six pre-registered precipitation/ET0 features;
- B1CH adds only the two existing GW-1A Prado features;
- all fitted models are pooled, train-scaled ordinary least squares;
- no pumping, recharge, spatial-forcing, groundwater-network, GNN, or MODFLOW
  model is fitted here;
- tracer and MBI evidence remain reserved outside fitting and selection.

Run with the project environment:

```bash
PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp/ocwd-gw1c-mpl \
  /home/nacevedo/.conda/envs/dc_externalities/bin/python \
  scripts/run_gw1c.py
```

The climate acquisition stage requires network access to the official
University of Idaho / Northwest Knowledge Network gridMET THREDDS service. Raw
bounded OPeNDAP responses are retained and hashed. All scientific outputs are
regenerated deterministically from the pinned parent artifacts and raw climate
subsets.

