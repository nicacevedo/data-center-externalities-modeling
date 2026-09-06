# PSCC M0 Recovery Report

| Field | Value |
|---|---|
| `M0_STATUS` | **`INCOMPLETE`** |
| `EXACT_M0` | **`NOT RECOVERED`** |
| `artifact_class` | `NONE_FOUND` — no candidate reached `EXACT_M0`, `RECOVERED_EQUIVALENT`, or `PAPER_REIMPLEMENTATION` |
| Freeze decision | **FAIL** — freeze gates unreachable; nothing was frozen |
| Historical search boundary | `f575f0daa9247799116c06e4255262a76532c307` and ancestors |
| Audit date (UTC) | 2026-09-06 |

---

## 1. Objective

Recover the exact submission-era implementation and processed input bundle behind the PSCC 2026
static data-center siting experiments, reproduce the published results, and — only if the evidence
justified it — freeze that experiment as the immutable static control for downstream planning work.

The exact historical object is denoted **`M0^{PSCC}`**. The requirement was recovery of that object,
not construction of a similar model. A paper-based reimplementation would not satisfy the objective,
because a control used to attribute later modelling changes must have verifiable lineage to the
published experiment.

## 2. Historical repository boundary

> The historical PSCC artifact search is valid only through commit
> `f575f0daa9247799116c06e4255262a76532c307` and its ancestors. Subsequent commits contain
> audit/reference material introduced after the recovery effort and MUST NOT be interpreted as
> evidence that PSCC implementation artifacts existed in the original repository history.

This report itself is post-audit documentation and quotes PSCC-specific strings for
falsifiability. See `AUDIT_BOUNDARY.md` for the full anti-contamination notice. A commit
`<commit>` is inside the valid search window if and only if
`git merge-base --is-ancestor <commit> f575f0daa9247799116c06e4255262a76532c307` succeeds
(the commit is the boundary or one of its ancestors).

**Search-window membership is not equivalent to PSCC provenance.** The pre-audit repository already
contains later narrative and audit material that refers retrospectively to the PSCC model
(`main_documents/master.tex`, the Prineville glossary mapping, the network glossary, and
`other_sources/andhra_pradesh_planning_preflight/`). Such hits must still be classified by
provenance and must not be treated as evidence that the submission-era implementation or input
bundle was present.

## 3. Repository state at the boundary

| Field | Value |
|---|---|
| Branch | `main` |
| HEAD | `f575f0daa9247799116c06e4255262a76532c307` |
| Subject | `[Feature] Adhra Pradesh preliminaries` (2026-09-04) |
| Total commits in history | 64 |
| History range | 2026-08-17 → 2026-09-04 |
| Tags | none |
| Branches | `main` only |
| Stashes | none |
| Git LFS | no LFS files |
| Working tree | one pre-existing dirty submodule, unrelated to PSCC and left untouched |

Submodule gitlinks present in the index: `Data-center-PUE-prediction-tool`,
`other_sources/cooling_technology_proxies/sources/lei2025/upstream`, and
`other_sources/m100/external/exadata`. Note that `Data-center-PUE-prediction-tool` is a gitlink with
no corresponding `.gitmodules` entry — a pre-existing repository inconsistency, unrelated to PSCC,
which the audit did not modify.

## 4. Search scope and methodology

All searching was read-only. No checkout, reset, clean, stash, garbage collection, or prune was
performed at any point.

### 4.1 Git history

- All 64 commits across all refs (`git log --all --pretty=fuller --stat`).
- All 3,239 reachable objects (`git rev-list --objects --all`).
- All 74 deleted paths (`git log --all --diff-filter=D --summary`).
- All 20 unreachable/dangling objects (`git fsck --full --no-reflogs --unreachable`). Both dangling
  commits were inspected with `git ls-tree -r` **without checkout**.
- Reflog, all refs, tags, branches, stashes, and the LFS index.

### 4.2 Signature searches

Pickaxe (`git log --all -S<pattern>`) and regex (`git log --all -G<pattern>`) sweeps were run over
the full signature list. Results within the valid pre-audit window:

| Signature | Meaning | Hit lines in history |
|---|---|---|
| `18070105` | Los Angeles HUC8 | 0 |
| `18050004` | San Francisco Bay HUC8 | 0 |
| `EnergySage` | grid price source | 0 |
| `Wind Toolkit` | wind resource source | 0 |
| `GE1.5-77` | turbine model | 0 |
| `fmax` | minimax inequity variable | 0 |
| `fMAD` | mean-absolute-difference inequity | 0 |
| `water scarcity footprint` | WSF term | 0 |
| `cvxpy` | modelling package | 0 |
| `gurobi` | solver | 0 |
| `sigma_WSF` / `sigma_P` / `sigma_E` | normalization constants | 0 |
| `NSRDB` | solar resource source | 1 — bibliography citation only |
| `PSCC` | — | narrative prose and citations only (§5) |
| `68.49` | DC levelized cost | coincidental numeric cell values (§5c) |
| `1.8` | DC direct water m³/MWh | coincidental numeric cell values (§5c) |

The zero result for `cvxpy` and `gurobi` is the single most informative finding: the paper states
the model was built in CVXPY and solved with Gurobi, and neither package name appears in any commit.

### 4.3 Filesystem

Searched outside the repository, on the host running the audit:

- The auditing user's full home directory tree, at full depth, for `*PSCC*` and `*M0*bundle*`
  filename patterns.
- A root-filesystem sweep (`find / -xdev`) for the same patterns.
- Three adjacent research project directories belonging to the same user.
- A local backup directory containing decompiled Python bytecode from an unrelated
  mass-appraisal project.
- Temporary directories and mount points.
- Institutional HPC storage allocated to the user (pool and home areas).
- Nearby archives and notebooks were inventoried but contained no PSCC material.

A content sweep of those locations for
`18070105|18050004|EnergySage|GE1.5-77|sigma_WSF|water scarcity footprint|Wind Toolkit`
matched **only** the audit's own specification inputs and its own discovery output — no project file
in any searched location contained any of them.

### 4.4 Reproducing this negative result

The searches above are reproducible from the boundary commit with standard Git commands and a
content grep over the signature list. Raw discovery logs (~1.8 MB of history dumps, object lists,
and content-hit files) were **deliberately not committed**: they are bulky, contain host-specific
paths, and would themselves contaminate future signature searches. They are retained outside the
repository by the auditing user; their location is recorded in the cleanup handover notes rather
than in this public record.

## 5. What was found

No artifact qualifies as a PSCC implementation. Every hit falls into one of four categories.

### (a) Narrative description — REFERENCE ONLY, not executable

| Path | SHA-256 |
|---|---|
| `main_documents/master.tex` | `83231ddc5cbf3b2682eab972da1254490b3e3178f588da027f92c89c4f830a06` |
| `Meta_Prineville_Oregon_v3/modeling/glossary_mapping.tex` | `8179ae861810fbee853c4da1c5da29e14f896a93d6068d4bcfec8e0da515ca43` |
| `main_documents/glossary/Network_Based_Data_Center_Glossary.tex` | `cf880b49cde92bc241e07f56b1034bf796c8b748bde0ec97b93d60905f2e0946` |

These describe M0 as the static PSCC baseline, cite the paper, and define WSF and minimax semantics
in general terms. The glossary even carries the directive "Reproduce the PSCC static siting model
literally before extending it." None contains an executable formulation or a single input array, so
none can regenerate any published value.

### (b) Prior independent audit — corroboration, not new evidence

`other_sources/andhra_pradesh_planning_preflight/`, committed 2026-09-04, had already reached the
same negative conclusion:

| Path | SHA-256 |
|---|---|
| `outputs/readiness/M0_REPRODUCTION_STATUS.json` | `d541d85bdf473a7f12470552e741d1b0a0cdc1b5b9c8f9a53aaeae6110848bf7` |
| `outputs/protocol/M0_STATIC_BASELINE_SPEC.md` | `d1540c2e8d27746fbbf856ff4611e0985e8c7166dd090e4391d077122f498aa9` |

That status file records `status: "PARTIAL"`, `code_path: null`,
`frozen_numerical_result_reproduced: false`, and `false` for all ten exactness flags. It cites the
same two narrative `.tex` files with identical hashes.

### (c) Coincidental string matches — IRRELEVANT

- `68.49` matches numeric cells in Prineville, ESIF/NREL HVAC, LBNL cooling, and Forest City CSVs.
- `1.8` matches values in OCWD groundwater outputs.
- `fmax` matches a local variable in a PUE sensitivity notebook, not a siting LP.
- HUC8 filename matches are all Oregon basin `17070305`, not California `18070105`/`18050004`.

All of the datasets above are explicitly excluded from M0 by the audit protocol, and none was used.

### (d) Unreachable Git objects — IRRELEVANT

Twenty unreachable objects were examined without checkout. The two dangling commits carry unrelated
subjects ("NLR Kestrel Job data" and "Initial commit") and neither tree contains a PSCC path. The
unreachable blobs are Parquet data, a PDF, a LaTeX article, a README stub, and a `.gitignore`.

### (e) Decisive structural finding

The repository's history begins 2026-08-17, which postdates the PSCC 2026 submission work. The
original code and processed inputs were therefore never committed to this repository at any point.
This is not deleted work awaiting recovery from the object store.

## 6. What was not found: missing P0 and P1 components

**Recovered: none.** Every component required for exact reproduction is missing.

| Priority | Item | Status |
|---|---|---|
| P0 | Source commit/archive/notebook that generated PSCC results | MISSING |
| P0 | Processed 136-HUC8 candidate list **and ordering** | MISSING |
| P0 | `Y_l` existing-capacity vector (Eq. 11c) | MISSING — **not** assumed zero |
| P0 | Processed `P`, `WSF`, `E` coefficient arrays | MISSING |
| P0 | 2013 `C^s`/`C^w` arrays and 2011 validation arrays | MISSING |
| P0 | `sigma_P`, `sigma_E`, `sigma_WSF` and std convention (`ddof`, ordering) | MISSING |
| P0 | Flat / business / CAISO demand arrays | MISSING |
| P0 | Model code for Eq. 10 and Eq. 11a–d, and the inequity construction | MISSING |
| P0 | Solver environment (Python, CVXPY, Gurobi, NumPy, Pandas, options) | MISSING |
| P1 | NSRDB product, variables, timezone, nearest-node method | MISSING |
| P1 | WTK product/height, GE1.5-77 power curve and interpolation | MISSING |
| P1 | HUC8 centroid CRS and boundary vintage | MISSING |
| P1 | EnergySage and NREL SLOPE vintages | MISSING |
| P1 | County→HUC8 area-weighting implementation | MISSING |
| P1 | Siddik / Meldrum / NREL LCA files and unit conversions | MISSING |
| P1 | Active-site threshold behind the reported subbasin counts | MISSING |
| P1 | Output aggregation/rounding scripts and Figure/Table source data | MISSING |
| P1 | Any undocumented filtering, bounds, or extra constraints | MISSING |

Per-input provenance chains, each with its break point identified, are in
`dataflow_provenance.csv`.

## 7. Why no reproduction was attempted

The audit protocol requires the first reproduction run to use the strongest **recovered** source and
data bundle. No source and no data were recovered, so there was nothing to run.

Producing numbers anyway would have required reconstructing missing P0 inputs, silently setting the
Eq. 11c vector `Y_l` to zero, or refreshing datasets to current public versions — each of which the
protocol explicitly forbids, and each of which would have yielded a plausible-looking result with no
lineage to the published experiment.

Consequently every reproduction gate is **NOT RUN**, including the primary freeze gate (statewide
full-8760 minimax: active sites 1 / 7 / 8 / 11 and max WSF 407 / 20 / 10 / 4 million m³-eq per year),
the LA/SF Table I input checksum, the LA/SF δ sweep, and the Table II–V secondary fingerprints.
No `reproduction_summary.json` was generated, because producing one without a real run would be
fabrication.

**No numerical results were manufactured. No hidden assumption was introduced. No reconstruction
was performed.**

## 8. Why `INCOMPLETE` is the correct classification

| Class | Requirement | Met? |
|---|---|---|
| `EXACT_M0` | Direct submission-era lineage plus enough exact code/data/config to reproduce the published experiment | No — no such artifact exists here |
| `RECOVERED_EQUIVALENT` | Original code and essentially original inputs recovered, and numerical reproduction succeeds | No — none of the three conditions holds |
| `PAPER_REIMPLEMENTATION` | Core P0 components rebuilt from the paper or current public sources | Not performed — it would not satisfy the freeze objective, and the no-label-inflation rule warns it is not the exact baseline |
| `INCOMPLETE` | Experiment cannot yet be executed or reproduced; key P0 items unresolved | **Yes** |

`M0_STATUS = FROZEN` is therefore **not** scientifically justified, and no freeze was performed. No
paper-based reconstruction, inferred dataset, refreshed source, or approximate implementation has
been promoted to exact PSCC lineage.

## 9. Residual limitations of the search

Stated plainly, so the negative result is not overread:

1. **Scope.** The audit establishes that no PSCC implementation or submission-era input bundle was
   found in the repository history or in any accessible host location searched. It does **not**
   prove that no copy exists. A copy could reside on an author machine, in a private repository, in
   personal or institutional cloud storage, on external media, or in an account the audit could not
   reach.
2. **Remote refs not enumerable.** An attempt to list remote branches and tags failed because SSH
   credentials were unavailable in the audit environment. The local tracking branch matched local
   `main`, and the remote is the same post-submission repository, so remote-only PSCC code is
   unlikely — but this was not positively verified and should be confirmed when credentials allow.
3. **Binary content.** Signature searching is text-based. A PSCC implementation embedded inside an
   opaque binary or an encrypted archive would not have been matched by content grep, though no
   candidate archive of that kind was found by filename either.
4. **Submodules.** Submodule contents were checked by gitlink and path, not by exhaustive search of
   every upstream history; all three submodules belong to clearly unrelated upstream projects.

## 10. Recommended next step: author-side recovery

Exact recovery of `M0^{PSCC}` now depends on the original authors. Request the submission-era
experiment bundle — ideally a single archive or a repository commit/tag reference — from
Richard Chen and Disha Chauhan, with Nathan Engelman Lado and Saurabh Amin copied.

Requested items in priority order:

| # | Item | Priority |
|---|---|---|
| 1 | Exact code/notebooks that generated Figures 1–4 and Tables II–V | P0 |
| 2 | Processed 136-HUC8 California input table **and its ordering** | P0 |
| 3 | `Y_l` existing-capacity vector for Eq. (11c), including whether it is zero and why | P0 |
| 4 | 2013 `C^s`/`C^w` hourly arrays and the 2011 validation arrays | P0 |
| 5 | Flat, business, and 2013 CAISO demand arrays | P0 |
| 6 | Processed cost, WSF, and emissions arrays | P0 |
| 7 | `sigma_WSF`, `sigma_P`, `sigma_E` and the exact std implementation (`ddof`, concatenation order) | P0 |
| 8 | Scenario configs for the four statewide weightings and the LA/SF δ sweep | P0 |
| 9 | Python / CVXPY / Gurobi / NumPy / Pandas versions and solver options | P0 |
| 10 | Raw source/version notes: NSRDB, WTK, SLOPE, EnergySage, LCA data, HUC8 shapefile and centroid preprocessing | P1 |
| 11 | Original result CSV/NPY files or plotting inputs behind the Figures/Tables | P1 |
| 12 | Original repo commit/tag/archive checksum, if one exists | P1 |

Two clarifications would also help: the **active-site threshold** used to report the subbasin counts
(the solver may return tiny positive capacities, and inventing a cutoff is not acceptable), and any
**filtering, variable bounds, or constraints** present in the code but not described in the paper.

On receipt, the bundle should be preserved byte-unchanged, hashed with SHA-256 before anything reads
it, and any compatibility shims kept in a separate layer that is fully diffed and alters no
mathematics or data.

Worth checking on the author side: personal or lab machines, institutional cloud drives, the
Overleaf submission snapshot, private Git hosting, and any HPC scratch space used for the
8760-hour statewide runs.

## 11. Scope note on future work

Exact historical reproduction remains blocked. That does not require planning research to halt
indefinitely. A separately named, transparently constructed, paper-faithful static control may be
developed later if the project needs one. It would be a **new scientific control** — not the
historical PSCC experiment — and must never be labelled `M0^{PSCC}` or presented as exact PSCC
lineage. Designing or building such an object is outside the scope of this audit, and none was
created here.
