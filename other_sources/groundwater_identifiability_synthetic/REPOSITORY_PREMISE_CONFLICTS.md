# Repository premise conflicts recorded before design freeze

The task specification for this module carried several premises that the repository as it
actually stands does not satisfy. Each is recorded here before the design was frozen, as
required, rather than being silently resolved.

## C1 — `git submodule status` fails; the dirty path is an unregistered gitlink

Expected premise: `Data-center-PUE-prediction-tool` is a submodule with pre-existing
modified content.

Actual state:

```
$ git status --short
 m Data-center-PUE-prediction-tool

$ git submodule status
fatal: no submodule mapping found in .gitmodules for path 'Data-center-PUE-prediction-tool'

$ git ls-files -s Data-center-PUE-prediction-tool
160000 11663ab76cd03100c56ab7adcb3ab65b4dd728ca 0	Data-center-PUE-prediction-tool
```

`.gitmodules` maps only `other_sources/m100/external/exadata`. So the path is a **gitlink
recorded in the index with no `.gitmodules` entry**: git tracks a commit pointer for it but
does not consider it a configured submodule.

Resolution: the dirty-content premise is confirmed, only the mechanism differs. The path is
left completely untouched — not reset, cleaned, staged, committed, or entered. The
`test_no_edits_outside_module` guard allowlists exactly this one pre-existing entry.

## C2 — gate-token namespace collision

Expected premise: gates may be named `G0`–`G3`.

Actual state: `other_sources/ocwd_groundwater_feasibility/config/feasibility_gates.yaml`
already defines `G1`–`G10` with entirely unrelated meanings (`G1_STATE`, `G2_TEMPORAL`,
`G3_PUMPING`, ... `G10_REPRODUCIBILITY`).

Resolution (user decision): this module's gates are named `SGI_G0`, `SGI_G1`, `SGI_G2`,
`SGI_G3`. Plain `G0`–`G3` are retained only as in-module aliases and are never written to
machine-readable status files without the `SGI_` prefix.

## C3 — `M0R` and `M1S` do not exist in this repository

Expected premise: the planning ladder is `M0^{PSCC}` / `M0R` / `M1L` / `M1S` / `M1N`.

Actual state: the preregistered ladder in
`other_sources/andhra_pradesh_planning_preflight/outputs/protocol/PLANNING_ABLATION_PROTOCOL.md`
is `M0 -> M0S -> M1L -> M1N`. Neither `M0R` nor `M1S` appears anywhere in the repository.
`main_documents/master.tex` separately uses a fidelity ladder `M_0 / M_1 / M_2` for the
facility model, which is a different axis.

Resolution (user decision): use repository labels only. Consequence, recorded as a finding
rather than papered over: because `M0S` means *source-resolved but static*, it is **not** a
spatial-forcing model, so the synthetic `S` rung has **no** planning-ladder counterpart. The
repository ladder jumps directly from `M1L` to `M1N`. If the `S` rung turns out to be earned
while `N` is not, the existing ladder has a genuine gap.

## C4 — the DGP is a restricted special case, not a reparameterization of the paper model

Expected premise (original plan wording): the storage/conductance form is an "exact
reparameterization" of the repository's groundwater model.

Actual state: `main_documents/master.tex` specifies the **general** reduced-order model

```latex
h_{m+1} = A h_m + B_R R_m - B_Q ( q^{ag}_m + q^{mun}_m + q^{dc}_m ) + \varepsilon_m
```

with `A`, `B_R`, `B_Q` unrestricted, and lists `Dynamic groundwater network (A, B_R, B_Q)`
as `\NotIdentified`. The storage/conductance DGP used here imposes

- `A = I - dt * diag(1/S) * L`, with `L` a Laplacian-plus-leakage matrix, and
- `B_R = B_Q = dt * diag(1/S)`.

Resolution: this is described throughout as a **restricted, physically interpretable special
case** of the paper's model family, never as an exact reparameterization. The restriction
`B_R = B_Q` (unit recharge efficiency) is itself treated as an assumption to be stressed:
scenario `S7` includes a `recharge_efficiency_mismatch` variant in which the truth has
`B_R != B_Q` while the estimator retains the restricted family.

## C5 — repository groundwater modules use a different model form entirely

Recorded for completeness. The implemented OCWD modules (`ocwd_groundwater_gw1_preflight`,
`ocwd_groundwater_gw1_climate`, `ocwd_groundwater_gw1b`) do **not** fit a state equation with
storage or conductance at all. They fit pooled, train-scaled OLS on observed head
transitions with calendar and forcing features, and explicitly prohibit A/B network
estimation (`B7_execution: prohibited_in_this_task`,
`NETWORK_MODEL_JUSTIFICATION = UNRESOLVED`).

This is not a contradiction with the present task: this module is synthetic and asks whether
the network object those modules refuse to estimate *could* be identified at all, and under
what observation regime. It does, however, mean that no OCWD implementation could be reused
as an estimator here, so the estimator ladder is implemented from scratch while inheriting
OCWD's **protocol** conventions (chronological splits, train-only scaling, no head
interpolation, validation-only complexity selection, protected test, freeze-then-run,
SHA-256 output manifests).

## C6 — execution-instruction conflict

The task specification instructed autonomous execution through the full Monte Carlo sweep.
A subsequent explicit user instruction supersedes it: implementation proceeds only through
`pytest -> SGI_G0 -> engineering smoke -> runtime/storage benchmark`, then stops for
external review. The full sweep is **not** launched in this phase.
