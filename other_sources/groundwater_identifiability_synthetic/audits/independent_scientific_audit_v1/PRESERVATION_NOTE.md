# Preservation note — independent scientific audit v1

This directory is an **additive verbatim preservation** of the post-V2 independent scientific audit originally written under `/tmp/sgi_independent_audit/`.

## Provenance of the audit itself

- The audit was conducted **after** the frozen V2 ANALYSIS results existed.
- It is **post-hoc relative to V2**. It is not a preregistered V2 analysis and must not be rewritten to look like one.
- It diagnosed candidate mechanisms from already-stored V2 quantities.
- Those post-hoc mechanism hypotheses are what V3 tests **prospectively**. V3 hypotheses were not preregistered before V2.

Evidence hierarchy (must survive into paper language):

```text
V2        = confirmatory frozen known-truth qualification study
POST-V2 AUDIT = post-hoc mechanism diagnosis (this directory)
V3        = prospective mechanism-confirmation follow-up motivated by that audit
```

## What was preserved

Verbatim copies, SHA-256 matched to the `/tmp` source (see `SOURCE_MANIFEST.csv`):

- `INDEPENDENT_SCIENTIFIC_AUDIT.md`
- `EMPIRICAL_DECISION_TABLE.csv`
- `EMPIRICAL_DECISION_TABLE.md`
- `scratch/` — auditor scripts and intermediate tables (`.py` files live here, **never** under V2 `src/`, `scripts/`, or `tests/`)

No audit file was edited to change scientific claims. This note and the manifest are the only additive files.

## What this preservation does not do

- It does not alter frozen V2 design, code, or ANALYSIS outputs.
- It does not change `LOCAL_RESPONSE_STATUS = LOCAL_RESPONSE_NOT_IDENTIFIED`.
- It does not change `NETWORK_SUPPORT_FINAL = NOT_EARNED`.
- It does not authorize V3 ANALYSIS execution.
