# PSCC M0 Recovery Audit

**`M0_STATUS = INCOMPLETE`**
**`EXACT_M0 = NOT RECOVERED`**

This directory records an audit undertaken to recover the exact implementation and input bundle
underlying the PSCC 2026 static data-center siting experiments. No executable submission-era
implementation and no complete processed input bundle was found in the repository history through
commit `f575f0daa9247799116c06e4255262a76532c307`, nor in any accessible host location that was
searched. Accordingly, no reproduction was attempted and no exact PSCC baseline was frozen.

This is a **negative provenance result**, not a reconstructed model. Recovery of the exact
historical object — denoted `M0^{PSCC}` — remains contingent on author-side artifacts.

## Historical search boundary

> Only commit `f575f0daa9247799116c06e4255262a76532c307` and its ancestors may be treated as
> pre-audit repository evidence. Later commits contain recovery/audit documentation and must not be
> interpreted as historical PSCC artifacts.

This matters because the audit documents in this directory necessarily quote PSCC-specific strings
(`18070105`, `18050004`, `EnergySage`, `Wind Toolkit`, `GE1.5-77`, `fmax`, `fMAD`, σ symbols, paper
equations, and published numerical targets). A future `git log -S` or `grep` sweep will match those
strings **here**, in post-audit documentation. Such matches are not evidence that PSCC
implementation artifacts ever existed in the repository's history. See `AUDIT_BOUNDARY.md` for the
executable membership test (`git merge-base --is-ancestor <commit> <boundary>`).

**Search-window membership is not equivalent to PSCC provenance.** The pre-audit repository already
contains later narrative and audit material that refers retrospectively to the PSCC model. Such
hits must still be classified by provenance and must not be treated as evidence that the
submission-era implementation or input bundle was present.

## Contents

| File | Purpose |
|---|---|
| `README.md` | This overview |
| `AUDIT_BOUNDARY.md` | The historical evidence boundary and anti-contamination notice |
| `PSCC_M0_RECOVERY_REPORT.md` | Full audit: scope, method, findings, missing components, classification, next step |
| `artifact_inventory.csv` | Every candidate artifact examined, with classification and confidence |
| `dataflow_provenance.csv` | Provenance chains for each model input, with the break point identified |
| `SHA256SUMS.txt` | Hashes of the permanent audit files |

## What this result does and does not imply

It **does** mean exact historical reproduction of `M0^{PSCC}` is blocked pending author-side
artifacts, that no reproduction run was performed, and that no exact baseline was frozen.

It **does not** mean that no copy of the PSCC implementation exists anywhere. The audit searched
this repository's full history and the host locations accessible to it. A copy could still exist on
an author machine, in a private repository, in institutional or personal cloud storage, or in an
account this audit could not reach.

It also **does not** mean planning research must halt indefinitely. A separately named,
transparently constructed, paper-faithful static control may be developed later if needed. Such an
object would be a **new scientific control**, not the historical PSCC experiment, and must never be
labelled `M0^{PSCC}` or presented as exact PSCC lineage. Designing it is outside the scope of this
audit.

## Next step

Request the submission-era experiment bundle from the paper authors (Richard Chen, Disha Chauhan,
Nathan Engelman Lado, Saurabh Amin). The specific artifacts needed are itemized by priority in
`PSCC_M0_RECOVERY_REPORT.md` §8.

## Source documents

The PSCC 2026 manuscript, the two-region exploratory document, and the J-WAFS proposal were used as
specification inputs during the audit. They are **not** redistributed here: the manuscript was
unpublished at the time of the audit, and the proposal contains personnel, budget, and
letter-of-support material that is not appropriate for a public repository. They are referenced by
citation only.

- R. Chen, D. Chauhan, N. Engelman Lado, and S. Amin, "A Multi-Objective Linear Programming
  Framework for Sustainable and Equitable Data Center Siting," 24th Power Systems Computation
  Conference (PSCC 2026).
