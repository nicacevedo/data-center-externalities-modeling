# Baseline repository source audit

The repository was searched before external acquisition using the exact
baseline tree at `975821ae679713cc6b2bcd984f2d16d4328289a8`.

```bash
git ls-tree -r --name-only 975821ae679713cc6b2bcd984f2d16d4328289a8 \
  | rg -i 'andhra|india.?wris|cgwb|bhuvan|grace|modis|pscc|groundwater'
```

Findings:

- No Andhra Pradesh, CGWB, India-WRIS, Bhuvan, GRACE, or MODIS input package
  was present.
- No PSCC implementation, PSCC input bundle, manuscript artifact, or frozen
  numerical result was present.
- The matched groundwater files belonged to frozen Prineville and OCWD
  packages and were not candidates for transfer into India.
- PSCC-style semantics were available only in the read-only project narrative
  and Prineville glossary mapping recorded in `M0_STATIC_BASELINE_SPEC.md`.

The external acquisition was consequently limited to five small gating
artifacts from official NWIC/CGWB and Andhra Pradesh government endpoints. No
national archive or non-gating bulk remote-sensing product was downloaded.
