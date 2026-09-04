# OCWD GW-1A: pre-registered null predictive benchmark

This isolated module freezes the historical analysis population, temporal and
spatial holdouts, and a transparent no-pumping baseline ladder for Basin 8-001.
It answers a deliberately limited question: how predictable are observed
groundwater-head transitions from the observed prior head, calendar structure,
and public Santa Ana River discharge before OCWD WRMS pumping and managed
recharge data are available?

GW-1A does **not** estimate a groundwater network, pumping response,
groundwater optimization model, MODFLOW parameter, or spatial connectivity
coefficient. Missing heads are never interpolated. Prado discharge is public
boundary/background hydrology, not managed recharge. Tracer and MBI evidence
is reserved outside fitting and tuning.

## Reproduction

Use the pinned project environment and run the protocol freeze before any
model comparison:

```bash
export MPLCONFIGDIR=/tmp/ocwd-gw1a-mpl
export PYTHONDONTWRITEBYTECODE=1
/home/nacevedo/.conda/envs/dc_externalities/bin/python scripts/freeze_protocol.py
/home/nacevedo/.conda/envs/dc_externalities/bin/python scripts/run_benchmarks.py
/home/nacevedo/.conda/envs/dc_externalities/bin/python -m unittest discover -s tests -v
```

The first stage verifies the frozen feasibility hashes, independently finds
the coverage-selected dense interval, writes non-imputed representations, and
freezes holdouts. The second stage refuses to run if any frozen protocol file
or dependency has changed.

Canonical conclusions are in
`outputs/FINAL_GW1A_REPORT.md` and `outputs/FINAL_GW1A_STATUS.json`.

