# AP E0 evidence package

Documentation, provenance, and data-request preparation only.

```text
CURRENT_E0_DECISION = UNRESOLVED
DYNAMIC_MODELING_AUTHORIZED = NO
EMPIRICAL_M1N_AUTHORIZED = NO
```

Parent freeze: [EMPIRICAL_GW_QUALIFICATION_PLAN.md](../../../EMPIRICAL_GW_QUALIFICATION_PLAN.md).

| File | Role |
|---|---|
| [AP_E0_EVIDENCE_MATRIX.csv](AP_E0_EVIDENCE_MATRIX.csv) | One row per required evidence item. `ACCESS_STATUS` and `SCIENTIFIC_STATUS` are independent; a downloaded file is never automatically ADEQUATE. |
| [AP_E0_STATUS.json](AP_E0_STATUS.json) | Six-domain scores and terminal decision |
| [AP_PUMPING_MEASUREMENT_AUDIT_PROTOCOL.md](AP_PUMPING_MEASUREMENT_AUDIT_PROTOCOL.md) | Pumping series classes before any M1L fit |
| [AP_COUPLING_QUALIFICATION_PROTOCOL.md](AP_COUPLING_QUALIFICATION_PROTOCOL.md) | `WEAKLY_SUPPORTED` / `MATERIAL` / `UNRESOLVED` |
| [AP_EMPIRICAL_UNIT_ELIGIBILITY_PROTOCOL.md](AP_EMPIRICAL_UNIT_ELIGIBILITY_PROTOCOL.md) | Pre-outcome unit selection |
| [AP_E0_ACCESS_REQUEST_GAP_AUDIT.md](AP_E0_ACCESS_REQUEST_GAP_AUDIT.md) | V1 request vs E0 requirements |
| [../requests/AP_PLANNING_DATA_ACCESS_REQUEST_V2.md](../requests/AP_PLANNING_DATA_ACCESS_REQUEST_V2.md) | Revised request (**do not submit** in this freeze) |
| [AP_E0_PUBLIC_SOURCE_ACQUISITION_LOG.csv](AP_E0_PUBLIC_SOURCE_ACQUISITION_LOG.csv) | Targeted public-source search log |
| [AP_E0_SOURCE_PROVENANCE_MANIFEST.csv](AP_E0_SOURCE_PROVENANCE_MANIFEST.csv) | Provenance for acquired artifacts |
| [AP_E0_PUBLIC_SOURCE_ASSESSMENT.md](AP_E0_PUBLIC_SOURCE_ASSESSMENT.md) | Per-domain public-source assessment |
| [AP_E0_DELTA_STATUS.md](AP_E0_DELTA_STATUS.md) | Changes relative to the pre-acquisition E0 freeze |

Do not fit M1L/M1N, run siting, create V4, or treat synthetic parameters as AP
estimates.
