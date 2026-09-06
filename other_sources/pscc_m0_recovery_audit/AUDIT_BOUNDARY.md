# Historical Evidence Boundary

## The boundary

> The historical PSCC artifact search is valid only through commit
> `f575f0daa9247799116c06e4255262a76532c307` and its ancestors. Subsequent commits contain
> audit/reference material introduced after the recovery effort and MUST NOT be interpreted as
> evidence that PSCC implementation artifacts existed in the original repository history.

| Field | Value |
|---|---|
| Boundary commit | `f575f0daa9247799116c06e4255262a76532c307` |
| Boundary commit subject | `[Feature] Adhra Pradesh preliminaries` |
| Boundary commit date | 2026-09-04 |
| Commits searched | 64 (the boundary commit and all ancestors, across all refs) |
| Repository history begins | 2026-08-17 |
| Evidence class of later commits | POST-AUDIT DOCUMENTATION — not historical evidence |

## Why this notice exists

The audit's conclusion is a negative search result: no PSCC implementation or processed input
bundle was found. To document that conclusion in a falsifiable way, the audit files in this
directory must state exactly which signatures were searched and which published values were sought.
As a result, this directory contains PSCC-specific strings that did not previously appear anywhere
in the repository.

Strings now present in post-audit documentation include:

- HUC8 identifiers `18070105` (Los Angeles) and `18050004` (San Francisco Bay)
- Data-source names `EnergySage`, `NSRDB`, `Wind Toolkit`
- Turbine model `GE1.5-77`
- Inequity symbols `fmax`, `fMAD`
- Normalization symbols `sigma_WSF`, `sigma_P`, `sigma_E`
- Solver/package names `cvxpy`, `gurobi`
- Paper constants such as `68.49`, `1.8`, `26.7`, and `12000000`
- Published target values such as site counts `1 / 7 / 8 / 11` and max-WSF `407 / 20 / 10 / 4`
- PSCC terminology and the Eq. (10) / Eq. (11a–d) formulation

## Instruction to future researchers and future automated searches

The admissible repository-history search window is commit
`f575f0daa9247799116c06e4255262a76532c307` **and all of its ancestors**. A candidate commit
`<commit>` lies inside that window if and only if it is an ancestor of the boundary, or is the
boundary itself:

```bash
BOUNDARY=f575f0daa9247799116c06e4255262a76532c307
COMMIT=<commit>

if git merge-base --is-ancestor "$COMMIT" "$BOUNDARY"; then
    echo "IN VALID SEARCH WINDOW: commit is the boundary or one of its ancestors"
else
    echo "OUTSIDE VALID SEARCH WINDOW: do not use as pre-audit repository evidence"
fi
```

Do **not** invert the argument order. The test
`git merge-base --is-ancestor "$BOUNDARY" "$COMMIT"` asks whether the boundary is an ancestor of
`<commit>`. That is true of the boundary itself (every commit is an ancestor of itself) and of
every descendant of the boundary. The inverted form therefore misclassifies the boundary commit
as outside the search window. Use the form above.

Hits **outside** the window include this audit's own documentation. They are self-references
created after the recovery search closed and carry **zero** evidential weight regarding whether a
PSCC implementation was ever committed to this repository.

## Search-window membership is not equivalent to PSCC provenance

Being inside the valid historical search window means only that the artifact existed in the
repository **before this PSCC M0 recovery audit introduced its own reference material**. It does
**not** establish that the artifact originated from, or was used in, the PSCC submission-era
experiment.

The repository at or before the boundary already contains later, non-submission-era narrative and
audit material that refers retrospectively to the PSCC model. Verified examples present at
`f575f0daa9247799116c06e4255262a76532c307` include:

- `main_documents/master.tex`
- `Meta_Prineville_Oregon_v3/modeling/glossary_mapping.tex`
- `main_documents/glossary/Network_Based_Data_Center_Glossary.tex`
- `other_sources/andhra_pradesh_planning_preflight/` (the boundary commit itself)

A search hit inside the boundary must still undergo provenance classification. Those files are
**reference-only or corroborating** artifacts: they discuss or audit the PSCC model after the
fact. They are not evidence that the submission-era executable implementation or processed input
bundle was present. See `artifact_inventory.csv` for the per-item classifications.

## What the pre-audit search actually found

Within the valid window (the boundary commit and its 63 ancestors), every distinctive PSCC
implementation signature returned **zero** hits: `18070105`, `18050004`, `EnergySage`,
`Wind Toolkit`, `GE1.5-77`, `fmax`, `fMAD`, `sigma_WSF`, `sigma_P`, `sigma_E`, `cvxpy`, `gurobi`.

The only pre-audit PSCC *references* were later narrative prose, bibliography citations, and the
Andhra Pradesh planning-preflight audit. All of those discuss the model conceptually or record that
the executable artifact was already missing; none is the submission-era implementation or input
bundle. Matches on the bare numbers `68.49` and `1.8` were coincidental cell values in unrelated
datasets that the audit protocol explicitly excluded from M0.

A structural point reinforces this: the repository's first commit is dated 2026-08-17, which
postdates the PSCC submission work. The original experiment was therefore never committed here, and
this is not a case of deleted work recoverable from the object store.

## Scope limitation

This boundary statement governs *repository* evidence. It makes no claim about material outside the
repository. See `README.md` and `PSCC_M0_RECOVERY_REPORT.md` §9 for the residual limitations of the
search.
