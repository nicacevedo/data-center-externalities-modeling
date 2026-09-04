# Andhra Pradesh planning preflight

This isolated module audits whether repository and authoritative public data
are ready to support a future comparison of static water-scarcity planning
with locally estimated dynamic groundwater impacts in Andhra Pradesh.

It does **not** fit a groundwater model, transfer an OCWD coefficient, or
solve a siting problem. OCWD contributes only a transferable identification
and validation protocol. All Andhra Pradesh physical parameters must be
estimated from Andhra Pradesh evidence.

## Frozen outcomes

- `TRACK_A_STATUS = WAITING_FOR_WRMS`: the single permitted workspace search
  found no newly delivered OCWD WRMS package. No B4--B7 model was run.
- `M0_REPRODUCTION_STATUS = PARTIAL`: repository narrative establishes the
  PSCC-style model semantics, but no canonical implementation/input bundle or
  frozen numerical PSCC result is present.
- `AP_SPATIAL_UNIT_STATUS = UNRESOLVED`: groundwater assessment units are the
  preliminary preferred basis, but canonical boundaries, identifiers, and
  versioned crosswalks are missing.
- No M0S, M1L, or M1N optimization was run.

## Deterministic build

```bash
cd other_sources/andhra_pradesh_planning_preflight
MPLCONFIGDIR=/tmp/ap-preflight-mpl \
PYTHONDONTWRITEBYTECODE=1 \
/home/nacevedo/.conda/envs/dc_externalities/bin/python scripts/run_preflight.py

PYTHONDONTWRITEBYTECODE=1 \
/home/nacevedo/.conda/envs/dc_externalities/bin/python -m pytest -q
```

The build verifies frozen OCWD parents against commit
`975821ae679713cc6b2bcd984f2d16d4328289a8`, verifies every downloaded raw
file against a pinned SHA-256, and regenerates the public groundwater coverage
audit without interpolating groundwater levels.

## Scientific boundary

The next defensible step is acquisition and reconciliation, not optimization:
obtain authoritative assessment-unit boundaries/IDs, a corrected stable-ID
groundwater-station panel with QA and aquifer metadata, time-resolved local
recharge/extraction, a complete candidate-site/grid/source crosswalk, and
sectoral agriculture/municipal baselines. Only then estimate and freeze a
local groundwater model before computing any static-versus-dynamic ranking.
