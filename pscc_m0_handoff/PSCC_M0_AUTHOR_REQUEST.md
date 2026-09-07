# PSCC M0 — Minimal Author Artifact Request

Status: **required**. Local recovery is exhausted and blocked (see `PSCC_M0_RECOVERY_REPORT.md`).

**To:** Richard Chen, Disha Chauhan
**Cc:** Nathan Engelman Lado, Saurabh Amin
**Re:** Submission-era experiment bundle for PSCC 2026, "A Multi-Objective Linear Programming
Framework for Sustainable and Equitable Data Center Siting"

## Why local recovery failed

`data-center-externalities-modeling` was initialized on 2026-08-17, which postdates the PSCC
submission work. All 64 commits, all refs, all deleted paths, and all unreachable Git objects were
searched read-only, as was the wider filesystem including adjacent research directories and ORCD
pool storage. Every distinctive PSCC signature returned zero hits: `18070105`, `18050004`,
`EnergySage`, `Wind Toolkit`, `GE1.5-77`, `sigma_WSF`, `fmax`, `fMAD`, `cvxpy`, `gurobi`. The
repository contains the PSCC model only as narrative description and citation, never as code or
data. The original experiment was therefore never committed here and cannot be recovered from this
host.

## Suggested message

> We are freezing the PSCC 2026 model as the immutable M0 baseline for the groundwater-network
> planning extension, so we need to reproduce the original experiment rather than reconstruct a
> similar model. Could you share the submission-era code plus processed input/output bundle (or the
> exact commit/archive) that generated the California results? The most important missing pieces
> are the 136-HUC8 processed inputs/order, Y vector, 2013/2011 renewable arrays, demand arrays,
> normalization sigmas/implementation, configs, and original outputs. We will preserve the bundle
> unchanged and record hashes/provenance.

## Requested items, in priority order

Ideally a single archive or a repository commit/tag reference.

| # | Item | Priority | Why it is blocking |
|---|---|---|---|
| 1 | Exact code/notebooks that generated Figures 1–4 and Tables II–V | P0 | Establishes experiment identity; nothing executable exists locally |
| 2 | Processed 136-HUC8 California input table **and its ordering** | P0 | Ordering changes every vector/matrix and the optimum |
| 3 | `Y_l` existing-capacity vector for Eq. (11c), **including whether it is zero and why** | P0 | Appears explicitly in the constraint but is not specified numerically in the paper; we will not assume zero |
| 4 | 2013 `C^s` and `C^w` hourly arrays, plus the 2011 validation arrays | P0 | Drive renewable complementarity and siting; Table V |
| 5 | Flat, business, and 2013 CAISO demand arrays | P0 | Determine the hourly optimization; Table IV |
| 6 | Processed cost, WSF, and emissions arrays | P0 | Core Eq. 10 objective coefficients; Table I |
| 7 | `sigma_WSF`, `sigma_P`, `sigma_E` and the exact std implementation (`ddof`, flatten/concatenation order) | P0 | Alters effective objective weights; paper reports only σ_WSF = 26.7 |
| 8 | Scenario configs: four statewide weightings and the LA/SF δ sweep | P0 | Needed to run the primary freeze gate |
| 9 | Python / CVXPY / Gurobi / NumPy / Pandas versions and solver options | P0 | Needed to explain numerical or degenerate differences |
| 10 | Raw source/version notes: NSRDB, WTK, SLOPE, EnergySage, Siddik/Meldrum/NREL LCA, HUC8 shapefile and centroid preprocessing | P1 | Current public versions are not the historical experiment values |
| 11 | Original result CSV/NPY files or plotting inputs behind the Figures/Tables | P1 | Provide exact targets stronger than paper rounding |
| 12 | Original repo commit/tag/archive checksum, if one exists | P1 | Establishes verifiable lineage for `EXACT_M0` |

Two further clarifications would help:

- The **active-site threshold** used to report "1 / 7 / 8 / 11 subbasins" — the solver may return
  tiny positive capacities, and we do not want to invent a cutoff.
- Any **filtering, variable bounds, or constraints** present in the code but not described in the
  paper.

## Commitments on our side

- The bundle will be preserved byte-unchanged in `source_original/` and hashed with SHA-256 before
  anything reads it.
- Compatibility shims needed to run on current systems will live in a separate `compat/` layer,
  fully diffed, and will not alter mathematics or data.
- No coefficient will be tuned to match published values.
- Full provenance chains (`raw → hash → preprocessing → processed → model variable → result`) will
  be recorded and shared back.

## Also worth checking on the author side

Locations this host cannot reach: personal or lab machines, MIT Drive / Dropbox, Overleaf project
archives (including the submission snapshot), private GitHub or GitLab repositories, and any HPC
scratch or home space used for the 8760-hour statewide runs.
