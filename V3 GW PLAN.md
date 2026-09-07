---

# V3 Prospective Mechanism-Confirmation Study — **Canonical Protocol (Pass 1 freeze)**

**Status:** canonical V3 protocol after final external-review corrections. 21 cells and n=200 unchanged. This file is the implementation source of truth.

**Revision log.**

- *Prior revision:* nine mandatory scientific corrections (benchmarks split; `IDENTIFICATION_REGIME`; dual RNG/system-seed modes; SESOI not gates; CRN SD bound; pairing tiers; γ=NONE; synthetic `neighbour_flux_share`; preserved 21-cell design).
- *This revision (final external-review corrections, pre-implementation):* (4.1) `gamma=NONE` uses the existing validated V2 zero-coupling branch, not a new S6a-like formula; (4.2) pumping error is **mean-corrected unit-mean multiplicative lognormal**, not median-corrected; (4.3) `F_train` is the cadence-specific TRAIN-distribution one-step target, with `V3_BENCHMARK` if MC is required — not a claim of stationarity; (4.4–4.5) `F_intervention` is over the **actual unconstrained own-pumping L family**, no invented sign/`a∈[0,a_max]` constraints; (4.6) ANALYSIS pool may be materialized for hashing (`V3_ANALYSIS_POOL_FROZEN=true`) but outcomes remain uninspected; (4.7) Block D reports the three-way interaction as secondary; (4.8) `D_PM_RN_R3` is an external-consistency anchor, not a numeric reproduction gate; (4.9) zero-edge F1/precision/recall follow actual V2 NaN semantics; (4.10) 95% intervals are pointwise Monte Carlo intervals, not family-wise bands.

---

## A. Current-state verification

All checks read-only against the working tree.

| item | observed | verdict |
|---|---|---|
| current branch | `testing/synthetic-groundwater-identifiability` | as expected |
| `HEAD` | `c9870ec0bbe78400c27071d30b528af9f504757a` | tip |
| `main` = `origin/main` | `84c4c81e7a4927ca36e95200dfb957f4e9014378` | branch unmerged, in sync with remote |
| `git status -sb` | in sync; single dirty entry ` m Data-center-PUE-prediction-tool` | pre-existing dirty gitlink, unrelated, untouched |
| newest commit `c9870ec` | adds only `pscc_m0_handoff/PSCC_M0_AUTHOR_REQUEST.md` | no `.py`, no module file |
| ANALYSIS execution commit | `8782efb` | matches `SWEEP_MANIFEST.json` |

Frozen v2 hashes recomputed from the live tree rather than read from a note:

| hash | recomputed now | frozen value | verdict |
|---|---|---|---|
| `DESIGN_HASH` | `b53f5594…e20a8a5` | `b53f5594…e20a8a5` | identical |
| `CODE_HASH` | `7cc64809…f00d863c` | `7cc64809…f00d863c` | identical |
| ANALYSIS seed pool | `bd6db2aa…cb689015` | `bd6db2aa…cb689015` | identical |
| G0 / CALIBRATION / SMOKE pools | `3bbd798d…`, `7aedf1a9…`, `d4e3c7dc…` | regenerate deterministically | identical |

**Frozen v2 state.** `other_sources/groundwater_identifiability_synthetic/` holds `config/design_v2.yaml` + `DESIGN_FREEZE_V2.md` (design-hash scope), a 30-file code manifest, `POST_SWEEP_PROVENANCE_AUDIT.md`, and `outputs/analysis/` with 7,740 replicates across 129 cells and 24 hashed artifacts. `FINAL_SYNTHETIC_IDENTIFIABILITY_STATUS.json` records `LOCAL_RESPONSE_STATUS = LOCAL_RESPONSE_NOT_IDENTIFIED` and `NETWORK_SUPPORT_FINAL.status = NOT_EARNED`. Neither is touched.

**Audit availability.** `/tmp/sgi_independent_audit/` is complete: `INDEPENDENT_SCIENTIFIC_AUDIT.md` (1,045 lines), `EMPIRICAL_DECISION_TABLE.csv` (129 rows), `EMPIRICAL_DECISION_TABLE.md`, plus seven scratch scripts and their outputs. It lives in `/tmp` and is at risk from any reboot; preservation is the first Build action.

### Premise confirmations and one premise conflict

1. **The `ORACLE_FAVOURABLE` confound is literal in the config**, not inferred from results: the bundle sets nine factors including `gamma: HIGH`, against the reference regime's `gamma: MED`.
2. **The decisive Q1 cell genuinely does not exist.** v2's only `P-EXACT` local cell sits on a *coupled* `path5` truth at `gamma=MED` (NIRE 0.706). The audit independently names this absence as the reason its own recommendation is capped at MODERATE-TO-HIGH.
3. **The S8 gap is as stated.** Exactly two S8 cells, both at the reference regime: `R-NOISE(0.20)`, `rho=0.3`, `P-MULTNOISE(0.10)`, `snr=10`, `k=4`. No S8 cell varies recharge quality, confounding, or pumping quality.
4. **Premise conflict — CRN is not available in v2 and cannot be retrofitted without code changes.** Each replicate uses one sequential `PCG64` stream through `simulate()` then `make_observations()`, and the *number of draws consumed depends on factor levels* (`P-EXACT` zero, `P-MULTNOISE` an array, `P-SCALEBIAS` a scalar, `P-SPATIALAGG` a Dirichlet). So changing `pumping_quality` shifts the stream for everything drawn afterward, including the recharge-proxy corruption. Two consequences, both load-bearing: the CRN refactor is a **prerequisite**, and **no v2 cell can serve as a paired arm** — every contrast arm is re-run inside v3, and v2's `G1R1` becomes an external consistency check rather than an experimental arm.

---

## B. Scientific rationale

v2 answered its preregistered question and answered it negatively across 129 cells; the independent audit reproduced every gate value with zero discrepancies. What v2 cannot do is support the *next* decision — metering versus well-network density versus deferral — because each choice is justified by a different mechanism and v2's design does not separate them:

1. **The dominant candidate mechanism was never isolated.** Roughly half the local intervention error traces to a −0.51 signed attenuation of the estimated pumping response, present in 100% of `P-MULTNOISE` replicates and absent in every other pumping regime. But the cell that would test "would exact metering fix it?" sits on a coupled truth where a structural term of 0.71–0.85 dominates. The claim "withdrawal data is the top lever" is currently an extrapolation across a cell never run.
2. **Two mechanisms are superimposed everywhere.** The reference regime carries `P-MULTNOISE` *and* `gamma=MED`, so every realistic local cell contains a measurement-error term and a misspecification term simultaneously, with no cell switching one off at a realistic level of the other.
3. **The oracle contrast changes the truth.** Because `ORACLE_FAVOURABLE` moves `gamma` MED→HIGH, the F1 improvement 0.727→1.000 mixes better data with stronger edges. v2's own coupling curve reaches F1 0.878 at `gamma=HIGH` on *realistic* data.
4. **S8 has no controlled contrast at all.** The 0.600 false-effect rate is a hard failure and stands, but the mechanism evidence is a *sign* argument (placebo coefficient positive in 95–100% of replicates, i.e. recharge-like), and v2 contains a direct internal tension it cannot reconcile: the confounding curve shows ρ nearly inert and slightly wrong-signed for local NIRE (0.858→0.828 as ρ 0→0.9), while S8 fails with a recharge-signed coefficient.

Additionally v2 stores only *unsigned* scalar error summaries for the transition matrix and no fitted matrices, so the audit could not compute the decomposition it needed and fell back on analytic sensitivity — several diagnostics are marked `NOT IDENTIFIABLE FROM STORED FROZEN OUTPUTS`.

V3 exists to run the small number of orthogonal cells that turn four mechanism hypotheses into four mechanism measurements, and to store the diagnostics that make the decomposition exact. It is deliberately not broader: v2 already mapped the surface.

---

## C. The four causal questions, with exact estimands

A *cell* is a fixed factor configuration; a *replicate* is one seed within a cell. **Paired** means two cells evaluated at the same seed under the sharing tier defined in §E — the tier matters and is stated per contrast. No estimand compares a v3 cell to a v2 cell as if paired.

Notation: $\text{NIRE}_L(c,s) = $ `nire_persistent_step_h26_L`, the frozen v2 G1 estimand. $\hat\beta_Q(c,s)$ is the signed estimated pumping coefficient (`beta_q_hat_mean_L`).

### Q1 — Does pumping measurement error cause the local-response amplitude failure?

Holding physics, recharge, head observations, missingness, confounding, cadence, process noise and the random realization bit-identical, with the truth uncoupled by construction (Tier 1 pairing):

$$\Delta^{Q1}(\sigma) = \operatorname{med}_s\big[\text{NIRE}_L(A_\sigma,s) - \text{NIRE}_L(A_{\text{EXACT}},s)\big], \qquad \sigma \in \{0.025,0.05,0.10,0.20\}$$

$$\rho^{Q1}(\sigma) = \operatorname{med}_s\!\left[\frac{\hat\beta_Q(A_\sigma,s)}{\hat\beta_Q(A_{\text{EXACT}},s)}\right], \qquad \delta^{Q1}(\sigma) = \operatorname{med}_s\!\left[\frac{\hat\beta_Q(A_\sigma,s)}{\hat\beta_Q(A_{\text{EXACT}},s)} - \hat\lambda^{\text{partial}}(A_\sigma,s)\right]$$

$\delta^{Q1}$ is the mechanism estimand: not whether attenuation happens but whether its magnitude is what measurement-error theory predicts (§I).

### Q2 — When does omitted hydraulic coupling make a local model structurally invalid?

With pumping and observation quality fixed at a favorable bundle that does not touch coupling (Tier 3 pairing):

$$\Delta^{Q2}(\gamma) = \operatorname{med}_s\big[\text{NIRE}_L(B_\gamma,s) - \text{NIRE}_L(B_{\text{NONE}},s)\big], \qquad \gamma \in \{\text{LOW},\text{MED},\text{HIGH}\}$$

plus the two per-cell deterministic benchmarks $F_{\text{train}}(\gamma)$ and $F_{\text{intervention}}(\gamma)$ defined in §J. These are what separate an estimator/objective limitation from a representational limitation of the frozen local response family.

### Q3 — How much of the v2 oracle network success came from stronger true edges?

**Reformulated per correction 2.** The contrast is not "data quality"; the `FAVOURABLE` bundle moves cadence (and hence TRAIN sample size and the coarse estimand), pumping quality, recharge quality, confounding, missingness, head SNR, and process noise together — and because ρ and `process_noise_sd` change, the realized latent forcing and head paths change too, even under shared base innovations. The factor is therefore named

$$\texttt{IDENTIFICATION\_REGIME} \in \{\text{REALISTIC}, \text{FAVOURABLE}\} \quad \text{(equivalently } \texttt{ORACLE\_BUNDLE} \in \{\text{OFF},\text{ON}\}\text{)}$$

Q3 asks: *at fixed γ, what is the effect of the broader favourable identification bundle; and at fixed identification regime, what is the effect of stronger coupling?*

$$\text{BUNDLE}(\gamma) = \operatorname{med}_s\big[F1(\text{FAV},\gamma,s) - F1(\text{REAL},\gamma,s)\big], \qquad \text{GAM}(d) = \operatorname{med}_s\big[F1(d,\text{HIGH},s) - F1(d,\text{MED},s)\big]$$

for $F1=$ `strong_edge_undirected_f1`, repeated for `edge_precision`, `false_edge_count` and `nire_persistent_step_h26_N`. **Permitted conclusion:** *v2 oracle success cannot be attributed to stronger edges alone or to the favourable bundle alone if both orthogonal contrasts are material.* The bundle effect is **not** attributed to measurement quality specifically, and is not decomposable into per-factor effects by this design.

### Q4 — Is S8 placebo failure primarily recharge/climate confounding?

Real pumping always included, true placebo coefficient exactly zero, full factorial in the three forcing-observation channels:

$$\pi(p,r,\rho) = \Pr_s\big[\texttt{placebo\_false\_effect\_L}=1 \mid D_{p,r,\rho}\big]$$

with three marginal contrasts and the continuous companion $\operatorname{med}_s[\texttt{placebo\_relative\_to\_true\_L}]$ per cell. The false-effect indicator uses the frozen v2 rule (|placebo step response| > 0.20 × |true real-pumping step response|), reported as a **legacy v2 reference criterion**; the continuous ratio distribution carries the inference.

---

## D. Exact cell matrix

`V3_REFERENCE` — byte-identical to v2's `reference_regime`:

| memory | cadence | gamma | pumping | recharge | rho | mcar | blocks | obs nodes | snr_head | proc noise |
|---|---|---|---|---|---|---|---|---|---|---|
| MED | 4 | MED | P-MULTNOISE(0.10) | R-NOISE(0.20) | 0.3 | 0.10 | 0 | 1.0 | 10 | 0.05 |

`OBS_FAV_GAMMA_FREE` — **new v3 bundle**: v2's `oracle_favourable_overrides` with the `gamma: HIGH` line deleted, nothing else changed:

| memory | cadence | gamma | pumping | recharge | rho | mcar | blocks | obs nodes | snr_head | proc noise |
|---|---|---|---|---|---|---|---|---|---|---|
| MED (inherited) | 1 | **per cell** | P-EXACT | R-EXACT | 0.0 | 0.0 | 0 | 1.0 | 20 | 0.02 |

| cell | block | scen | topo | mem | k | γ | pumping | recharge | ρ | mcar | blk | obs frac | snr | proc | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `A_PEXACT` | A | S1 | single | MED | 4 | n/a | **P-EXACT** | R-NOISE(0.20) | 0.3 | 0.10 | 0 | 1.0 | 10 | 0.05 | Q1 reference arm |
| `A_S025` | A | S1 | single | MED | 4 | n/a | **P-MULTNOISE(0.025)** | R-NOISE(0.20) | 0.3 | 0.10 | 0 | 1.0 | 10 | 0.05 | |
| `A_S050` | A | S1 | single | MED | 4 | n/a | **P-MULTNOISE(0.05)** | R-NOISE(0.20) | 0.3 | 0.10 | 0 | 1.0 | 10 | 0.05 | |
| `A_S100` | A | S1 | single | MED | 4 | n/a | **P-MULTNOISE(0.10)** | R-NOISE(0.20) | 0.3 | 0.10 | 0 | 1.0 | 10 | 0.05 | v2 `G1R1` configuration |
| `A_S200` | A | S1 | single | MED | 4 | n/a | **P-MULTNOISE(0.20)** | R-NOISE(0.20) | 0.3 | 0.10 | 0 | 1.0 | 10 | 0.05 | |
| `A1_PEXACT_K1` | A′ | S1 | single | MED | **1** | n/a | **P-EXACT** | R-NOISE(0.20) | 0.3 | 0.10 | 0 | 1.0 | 10 | 0.05 | k=1 anchor |
| `A1_S100_K1` | A′ | S1 | single | MED | **1** | n/a | **P-MULTNOISE(0.10)** | R-NOISE(0.20) | 0.3 | 0.10 | 0 | 1.0 | 10 | 0.05 | v2 `G1R2` configuration |
| `B_GNONE` | B | S5 | path5 | MED | 1 | **NONE** | P-EXACT | R-EXACT | 0.0 | 0.0 | 0 | 1.0 | 20 | 0.02 | V2 zero-coupling construction, §D.1 |
| `B_GLOW` | B | S5 | path5 | MED | 1 | **LOW** | P-EXACT | R-EXACT | 0.0 | 0.0 | 0 | 1.0 | 20 | 0.02 | |
| `B_GMED` | B/C | S5 | path5 | MED | 1 | **MED** | P-EXACT | R-EXACT | 0.0 | 0.0 | 0 | 1.0 | 20 | 0.02 | reused: C FAV×MED |
| `B_GHIGH` | B/C | S5 | path5 | MED | 1 | **HIGH** | P-EXACT | R-EXACT | 0.0 | 0.0 | 0 | 1.0 | 20 | 0.02 | reused: C FAV×HIGH |
| `C_REAL_GMED` | C | S5 | path5 | MED | 4 | **MED** | P-MULTNOISE(0.10) | R-NOISE(0.20) | 0.3 | 0.10 | 0 | 1.0 | 10 | 0.05 | v2 `G2R3` configuration |
| `C_REAL_GHIGH` | C | S5 | path5 | MED | 4 | **HIGH** | P-MULTNOISE(0.10) | R-NOISE(0.20) | 0.3 | 0.10 | 0 | 1.0 | 10 | 0.05 | v2 coupling-curve HIGH config |
| `D_PE_RE_R0` | D | S8 | single | MED | 4 | n/a | P-EXACT | R-EXACT | 0.0 | 0.10 | 0 | 1.0 | 10 | 0.05 | clean corner |
| `D_PE_RE_R3` | D | S8 | single | MED | 4 | n/a | P-EXACT | R-EXACT | 0.3 | 0.10 | 0 | 1.0 | 10 | 0.05 | |
| `D_PE_RN_R0` | D | S8 | single | MED | 4 | n/a | P-EXACT | R-NOISE(0.20) | 0.0 | 0.10 | 0 | 1.0 | 10 | 0.05 | |
| `D_PE_RN_R3` | D | S8 | single | MED | 4 | n/a | P-EXACT | R-NOISE(0.20) | 0.3 | 0.10 | 0 | 1.0 | 10 | 0.05 | |
| `D_PM_RE_R0` | D | S8 | single | MED | 4 | n/a | P-MULTNOISE(0.10) | R-EXACT | 0.0 | 0.10 | 0 | 1.0 | 10 | 0.05 | pumping-only corner |
| `D_PM_RE_R3` | D | S8 | single | MED | 4 | n/a | P-MULTNOISE(0.10) | R-EXACT | 0.3 | 0.10 | 0 | 1.0 | 10 | 0.05 | |
| `D_PM_RN_R0` | D | S8 | single | MED | 4 | n/a | P-MULTNOISE(0.10) | R-NOISE(0.20) | 0.0 | 0.10 | 0 | 1.0 | 10 | 0.05 | |
| `D_PM_RN_R3` | D | S8 | single | MED | 4 | n/a | P-MULTNOISE(0.10) | R-NOISE(0.20) | 0.3 | 0.10 | 0 | 1.0 | 10 | 0.05 | **v2 `G3R3` config** — replication anchor |

**21 unique cells.** Justifications for the three departures from the brief's default (Block A′ at k=1; Block D as a full 2×2×2 including pumping quality; every arm re-run inside v3) are as previously approved and unchanged.

### D.1 `gamma=NONE` — preserve the validated V2 zero-coupling construction

Inspection of frozen V2 `build_system()` (`src/dgp.py`) shows a **clean, already-validated** branch. `gamma=NONE` uses that construction under V3's orthogonal structural-seed semantics. V3 does **not** invent a different S6a-like implementation.

V2 already does:

```text
has_coupling = (gamma > 0.0) and (len(edges) > 0)
if has_coupling:
    unit_C  := adjacency                         # true edges
    unit_C0 := degree * (1 - gamma) / gamma      # this expression is NEVER evaluated at gamma=0
else:
    unit_C  := 0                                 # off-diagonal coupling exactly zero
    unit_C0 := 1                                 # ones vector
# then both branches share the same analytic scale c so realized tau_relax hits the memory target
C  := c_scale * unit_C
C0 := c_scale * unit_C0
```

So at `gamma=NONE`:

- no division by gamma;
- off-diagonal coupling exactly zero;
- finite stable transition matrix (same stability checks as every other V2 system);
- target memory semantics preserved by the existing V2 analytic `c_scale` that matches realized `tau_relax` to the memory-regime target.

This is **not** S6a's `null5` construction (independent local memory via boundary leakage on a no-edge topology with a different structural seed). It is the path5 geometry with zero cross-node conductance, scaled to the MED `tau_relax` target — the same object V2 already used on `CURVE_curve_coupling_strength_NONE`.

A dedicated test, `test_gamma_none_construction.py`, asserts on `B_GNONE`: (a) all off-diagonal conductances are exactly `0.0`; (b) realized `tau_relax` meets the MED target within the frozen V2 tolerance; (c) every entry of the constructed system is finite — no `inf`, no `nan`; (d) `rho(A)` sits inside the frozen stability margin; (e) `neighbour_flux_share` is exactly `0.0`; (f) the `(1-gamma)/gamma` expression is never evaluated when `gamma == 0.0`.

Because `B_GNONE` has zero true edges, network F1/precision/recall follow **actual V2 metric semantics** (§L / `metrics.edge_metrics`): empty-true and empty-predicted ⇒ F1/precision/recall are NaN; empty-true with false predicted edges ⇒ precision=0, recall=NaN, F1=0. The scientifically meaningful null-network diagnostics are `false_edge_count`, `false_edge_any`, and `predicted_edge_count`. Do not impute F1/recall merely to make tables rectangular. `B_GNONE` is a mechanism observation only — not a G3 trigger, not a gate, and incapable of altering `NETWORK_SUPPORT_FINAL`.

---

## E. Pairing structure (common random numbers)

### E.1 Required code change 1: named substreams (`rng_mode = named_substreams`)

Replace the single sequential replicate stream with a named-substream layer in which every component draws a **fixed-shape** array whose size does not depend on any factor level:

```python
# followups/v3_mechanism_confirmation/src_v3/rng.py  (NEW)
COMPONENTS = (
    "initial_condition", "recharge_innovations", "latent_climate",
    "pumping_innovations", "pumping_excitation", "placebo_independent",
    "process_noise", "head_measurement_noise",
    "node_subsample", "mcar_uniforms", "block_outage_starts",
    "pumping_degradation", "recharge_degradation",
    "pseudo_true_mc", "bootstrap",
)

def substream(seed: int, component: str) -> np.random.Generator:
    """Factor-independent substream. spawn_key from a stable digest of the component
    name, so adding a component never reindexes existing ones."""
    key = int.from_bytes(hashlib.sha256(component.encode()).digest()[:8], "big")
    return np.random.default_rng(np.random.SeedSequence(entropy=seed, spawn_key=(key,)))
```

Two invariants, enforced by tests rather than convention:

- **Fixed-shape drawing.** `pumping_degradation` always draws the full $(T,n)$ standard-normal array *and* the scale-bias scalar *and* the Dirichlet vector regardless of regime; the regime selects which to apply. Same for `recharge_degradation`. `head_measurement_noise` always draws its $(T,n)$ array and multiplies by zero when `snr_head` is infinite. `mcar_uniforms` always draws $(T,n)$ uniforms and thresholds at the cell's level, making masks **nested** across levels. `block_outage_starts` draws at the maximum count and truncates.
- **One noise realization scaled by σ.** The ladder uses a single standard-normal array $z$ with $m_t=\exp(\sigma z_t-\sigma^2/2)$ rather than re-drawing per σ, so `A_S025 ⊂ A_S050 ⊂ A_S100 ⊂ A_S200` is the *same* corruption realization at four amplitudes — a within-replicate dose-response curve rather than four Monte Carlo samples.

`Q_obs = Q_true_interval · exp(N(0,σ²) − σ²/2)` is **mean-corrected unit-mean multiplicative lognormal error**: $E[m]=1$ exactly, while the median is $\exp(-\sigma^2/2)$. Do not call this median-corrected. $\operatorname{Cov}(Q_{\text{true}},u)=0$ for $u=Q_{\text{true}}(m-1)$: the classical no-correlation condition holds despite multiplicative error. The error is heteroskedastic, $\operatorname{Var}(u_t)=Q_{\text{true},t}^2(e^{\sigma^2}-1)$, which is why §I computes reliability in realized sample form. The mathematical corruption model is unchanged from frozen V2.

### E.2 Required code change 2: `system_seed_mode = orthogonal_v3` — a *separate* flag (correction 3)

v2 keys the system draw on `structural_seed("system", topology, memory, gamma_label, recharge_efficiency)`, so storage coefficients $S_i$ differ across γ. For Block B/C, γ must be the only thing that changes, so `gamma_label` is dropped from the key. **This is a distinct change from the RNG refactor and is controlled by its own flag**, because the two are logically independent: one governs how randomness is drawn within a replicate, the other governs which system the cell simulates.

```text
rng_mode          ∈ {legacy_sequential, named_substreams}
system_seed_mode  ∈ {legacy_v2,         orthogonal_v3}
```

| purpose | `rng_mode` | `system_seed_mode` |
|---|---|---|
| v2 bit-for-bit parity check (§P step 6) | `legacy_sequential` | `legacy_v2` |
| **the substantive v3 experiment** | `named_substreams` | `orthogonal_v3` |

**Only these two combinations are legal.** The two mixed combinations are rejected at construction time, and `test_mode_pairing.py` asserts: (a) both mixed pairs raise before any simulation begins; (b) the parity script sets exactly `(legacy_sequential, legacy_v2)` and the sweep script sets exactly `(named_substreams, orthogonal_v3)`, verified by reading the resolved config rather than the source text; (c) both mode values are recorded in `RUN_MANIFEST_V3.json` and in every output row, so a mixed run could not be silently summarized even if it were somehow produced; (d) `summarize_v3.py --analysis` refuses any input file whose rows are not uniformly `(named_substreams, orthogonal_v3)`.

**What the γ contrast can and cannot hold fixed.** v2 chooses the conductance scale $c$ analytically so realized `tau_relax` hits the memory target at every γ, with boundary leakage absorbing the remainder. A γ contrast is therefore "same hydraulic memory, different share of relaxation routed through neighbours" — **not** "unchanged local system with neighbours added." I keep the v2 choice (the alternative confounds coupling with memory, which has its own independent effect), but it means $A_{ii}$ necessarily differs across γ, and it is disclosed everywhere the γ profile is reported.

### E.3 Three pairing tiers, and the tier of every contrast (correction 6)

Pairing strength is not uniform across this design, and calling it uniform would misdescribe Block C. Three tiers:

- **Tier 1 — same-truth, same estimand.** The latent truth is bit-identical and only the observation map changes. Supports the exact finite-sample identity in §I.
- **Tier 2 — same-truth, different estimand and sample size.** The fine-step latent truth is bit-identical, but interval aggregation, the TRAIN transition count, and the pseudo-true coarse estimand all change.
- **Tier 3 — shared-base-innovation, different realized truth.** Structural parameters and base innovation arrays are shared, but the realized latent forcing and head paths necessarily differ. Pairing here is a **variance-reduction device**, not a same-truth counterfactual.

| contrast | tier | shared bit-identically | necessarily differs |
|---|---|---|---|
| `A_PEXACT` vs `A_S{025,050,100,200}`; `A1_PEXACT_K1` vs `A1_S100_K1` | **1** | system, phases, initial condition, true recharge, true pumping, process noise, head-noise array, missingness mask, recharge-proxy corruption — hence **every non-pumping regressor column** | observed pumping only |
| σ ladder internally (`A_S025`→`A_S200`) | **1** | all of the above plus the same $z$ array | the σ multiplier only |
| Block D across pumping quality; Block D across recharge quality | **1** | latent truth, all base noise, mask, and the other observed regressors | `Q_obs` / `R_proxy` respectively |
| Block A (k=4) vs Block A′ (k=1) | **2** | fine-step latent truth, fine-step head-noise array, fine-step MCAR uniforms | interval aggregation; TRAIN transitions (≈129 vs 519); the coarse-step estimand |
| Block B across γ | **3** | $S_i$, seasonal phases, initial condition, recharge innovations, pumping innovations, pumping excitation, process-noise array, head-noise array, MCAR uniforms, degradation $z$ arrays | conductance matrix, hence $A$ (including $A_{ii}$, since $c$ is re-solved to hold `tau_relax`), hence the **realized latent head path** — this *is* the treatment |
| Block D across ρ | **3** | all base innovation arrays, process-noise array, head-noise array, mask, degradation $z$ arrays | realized $R$ and $Q$ paths, via the deterministic seasonal rotation $s_Q=\rho\sin+\sqrt{1-\rho^2}\cos$; hence the realized latent head and the placebo's standardized $r_z$ |
| **Block C: `C_REAL_Gγ` vs `B_Gγ`** (`IDENTIFICATION_REGIME`) | **3** | system structural parameters ($S_i$, $C$, geometry, phases — same topology/memory/γ), and the *base* innovation arrays: initial condition, recharge innovations, pumping innovations, pumping excitation, process-noise standard normals, head-noise standard normals, MCAR uniforms, block-outage draws, degradation $z$ arrays, placebo array | **the realized latent truth is not identical.** ρ changes 0.3→0.0, rotating the realized seasonal forcing shapes; `process_noise_sd` changes 0.05→0.02, rescaling the realized process-noise path; both propagate into a different realized head trajectory. On top of that, cadence changes 4→1 (aggregation, sampling instants, TRAIN row count, coarse estimand), `snr_head` 10→20 (realized measurement-noise scale), `mcar` 0.10→0.0 (mask, nested), and pumping and recharge quality both change |
| Block C across γ at fixed regime | **3** | as Block B row | as Block B row |
| Block A/A′/D vs Block B/C | **not paired** | nothing | topology, dimension, system |

**Block C is explicitly not an exact same-truth paired contrast.** The paired difference remains a valid estimator of the `IDENTIFICATION_REGIME` bundle effect, and sharing base innovations still reduces Monte Carlo variance, but the two arms do not simulate the same realized aquifer history. This is stated in the freeze document, in the summary tables, and in any paper text reporting Q3.

The Tier 1 row that matters most is the first: because the pumping ladder shares the recharge-proxy realization, the entire design matrix except the pumping column is bit-identical across the pair, so the residual-maker $M$ is identical between pair members. That is what makes §I's attenuation prediction an exact finite-sample identity rather than an asymptotic approximation, and it would not have held under v2's stream layout.

---

## F. Seed count (correction 5)

**Proposal: `n = 200` seeds per unique cell, fixed before execution. 21 × 200 = 4,200 replicates.** No adaptive stopping, no interim inspection, single launch. n=200 is **not increased**; no calculation below shows it inadequate.

### F.1 Primary justification — Wilson precision for rate-type outcomes

The binding outcomes are proportions: Block D's `placebo_false_effect_L` rate and Block C/B's `false_edge_any` rate. v2 estimated these from 60 seeds.

| Wilson 95% half-width | n=60 (v2) | n=100 | **n=200** | n=400 |
|---|---|---|---|---|
| at p = 0.60 | ±0.120 | ±0.094 | **±0.067** | ±0.048 |
| at p = 0.50 | ±0.125 | ±0.096 | **±0.069** | ±0.049 |
| at p = 0.20 | ±0.101 | ±0.078 | **±0.055** | ±0.039 |
| at p = 0.05 | ±0.061 | ±0.045 | **±0.031** | ±0.023 |
| upper bound given 0 events | 0.060 | 0.037 | **0.019** | 0.009 |

At n=60, v2's 0.600 rate carries an interval of roughly [0.47, 0.71], wide enough that a v3 clean corner at 0.35 would be ambiguous. At n=200 a corner at 0.60 is separated from one at 0.20 without interval overlap, the SESOI of 0.10 in a rate is resolved, and — decisively for the Outcome D-versus-E fork — a near-zero corner can be bounded above at ~0.02–0.03 rather than ~0.06. Distinguishing "false attribution disappears" from "it is merely reduced" requires exactly that tight upper bound on a small rate, and n=60 cannot supply one.

### F.2 Secondary justification — conservative precision for continuous paired effects

The paired-difference standard deviation $\sigma_d$ is **not** bounded above by the unpaired per-cell standard deviation. Common random numbers reduce $\sigma_d$ only when the two arms' outcomes are positively correlated across seeds; if they were negatively correlated, $\operatorname{Var}(D)=\sigma_1^2+\sigma_2^2-2\rho\sigma_1\sigma_2$ would *exceed* $\sigma_1^2+\sigma_2^2$. The only distribution-free bound is $\sigma_d \le \sigma_1+\sigma_2$.

Taking v2's `G1R1` spread (q10 0.349, q90 0.721 ⇒ per-cell SD ≈ 0.145) for both arms gives the adversarial bound $\sigma_d \le 0.29$:

| assumed $\sigma_d$ | SE of paired mean at n=200 | ratio to SESOI 0.05 |
|---|---|---|
| 0.05 (strong positive pairing) | 0.0035 | 14× |
| 0.145 (pairing does nothing) | 0.0103 | 4.9× |
| **0.29 (adversarial bound, perfect negative correlation)** | **0.0205** | **2.4×** |

So even in the mathematically worst case the SESOI is resolved at ~2.4 standard errors, and the effects actually anticipated (Q1's exact-versus-noisy contrast, Q2's γ span) are 0.15–0.40, i.e. 7–20 adversarial-case standard errors. The realized $\sigma_d$ and the realized paired correlation will be **reported per contrast** rather than assumed, so the pairing's actual efficiency becomes an output of the study instead of a premise. n=100 would also clear the continuous constraint; it does not clear F.1.

### F.3 Third justification — compute cost is negligible

v2 ran 7,740 replicates in 14.1 minutes. v3's 4,200 replicates plus the new per-replicate diagnostics is roughly 8–10 minutes; `F_intervention` is deterministic given the cell's system, and `F_train` uses only the disjoint `V3_BENCHMARK` pool. There is no cost argument for economizing below the precision the decisions require, and no precision argument for going above it: n=400 buys ~30% on rate half-widths, i.e. resolution only on differences too small to change a decision, while making trivially small differences look "detectable" in a study whose reporting is deliberately continuous. n=200 is the smallest round number clearing the binding constraint.

---

## G. Prospective hypotheses H1–H4 (correction 4)

Frozen before execution; **post-hoc relative to v2 and prospective relative to v3**. Each hypothesis preregisters five things and **no pass/fail rule**: a direction, an expected mechanism pattern, a continuous paired estimand, the uncertainty interval that will accompany it, and a SESOI / decision-relevance reference magnitude. Results inconsistent with a stated direction or pattern are reported as such — as *evidence against* the hypothesis, with the continuous estimate and interval carrying the weight. No hypothesis has a threshold whose crossing constitutes a verdict.

**Preregistered SESOI / decision-relevance reference magnitudes.** 0.05 in NIRE (one quarter of v2's legacy planning criterion); 0.10 in a rate; 0.05 in the reliability discrepancy $\delta^{Q1}$. These are *interpretive reference magnitudes for judging whether an estimated effect is large enough to matter to a project decision*. They are **not gates**, not thresholds, and not pass criteria; no cell was selected to cross any of them; and `design_v3.yaml` contains `gates: {}` so no v3 artifact can evaluate them as such.

**H1 — pumping attenuation.**
*Direction.* Under uncoupled truth at otherwise realistic observation quality, increasing pumping measurement error increases persistent-step intervention NIRE and attenuates the estimated pumping-response magnitude.
*Expected mechanism pattern.* $\Delta^{Q1}(\sigma)$ increasing in σ; $\rho^{Q1}(\sigma)$ decreasing in σ with $\rho^{Q1}(0.10)$ in the neighbourhood of 0.5; `relative_shape_error` remaining small throughout, locating the failure in amplitude rather than dynamics; $\hat\lambda^{\text{partial}}$ tracking $\rho^{Q1}$ across the ladder while $\hat\lambda^{\text{uncond}}$ does not.
*Estimands.* $\Delta^{Q1}(\sigma)$, $\rho^{Q1}(\sigma)$, $\delta^{Q1}(\sigma)$, each as a paired median and paired mean with a 95% percentile-bootstrap interval over seeds, plus the full paired difference distribution.
*Reference magnitudes.* 0.05 NIRE for $\Delta^{Q1}$; 0.05 for $|\delta^{Q1}|$.

**H2 — coupling misspecification.**
*Direction.* With observation quality fixed at `OBS_FAV_GAMMA_FREE`, local intervention error worsens as true hydraulic coupling becomes material.
*Expected mechanism pattern.* $\Delta^{Q2}(\gamma)$ ordered LOW ≤ MED ≤ HIGH; $\hat\beta_Q$ signed bias and $\hat\lambda^{\text{partial}}$ flat and near-clean across γ (confirming the pumping channel is not the driver); and the two benchmarks of §J separating an objective/estimator limitation from a representational one — specifically, $F_{\text{train}}(\gamma)$ rising with γ, and $F_{\text{intervention}}(\gamma)$ either rising with it (representational limit within the frozen family) or staying low while $F_{\text{train}}$ rises (objective mismatch).
*Estimands.* $\Delta^{Q2}(\gamma)$ paired median/mean with intervals; the deterministic per-cell profiles $F_{\text{train}}(\gamma)$, $F_{\text{intervention}}(\gamma)$, and the median estimated NIRE, reported as the three-term decomposition of §J.
*Reference magnitude.* 0.05 NIRE.

**H3 — oracle-network confound.**
*Direction.* Both orthogonal contrasts are material: the favourable identification bundle improves network recovery at fixed γ, *and* stronger coupling improves it at fixed identification regime.
*Expected mechanism pattern.* $\text{BUNDLE}(\gamma)>0$ at both γ and $\text{GAM}(d)>0$ at both regimes, with the degradation from FAVOURABLE to REALISTIC being **precision-driven** (precision falling substantially while recall largely holds), consistent with v2's 1.00→0.67 precision against 1.00→0.75 recall.
*Estimands.* $\text{BUNDLE}(\gamma)$ and $\text{GAM}(d)$ on F1, precision, recall, `false_edge_count`, `false_edge_any` and `nire_persistent_step_h26_N`, as Tier-3 paired medians with intervals.
*Reference magnitude.* 0.10 in a rate; 0.05 in F1.
*Permitted conclusion, and only this one.* If both contrasts are material, v2 oracle success cannot be attributed to stronger edges alone or to the favourable bundle alone. No attribution of the bundle effect to measurement quality specifically.

**H4 — placebo forcing leakage.**
*Direction.* False placebo attribution declines when the forcing-observation channels are cleaned.
*Expected mechanism pattern.* At least one of the three marginal effects (recharge quality, confounding, pumping quality) is material on the false-effect rate; the fully clean corner `D_PE_RE_R0` sits materially below the `D_PM_RN_R3` external-consistency anchor; that anchor is not required to numerically reproduce v2's 0.600; and the placebo coefficient's recharge-like positive sign (95–100% of replicates in v2) weakens or randomizes in the clean corners.
*Estimands.* $\pi(p,r,\rho)$ per cell with Wilson intervals; the three main effects, three two-way interactions, and the three-way interaction (secondary) with pointwise bootstrap intervals; and per-cell paired medians of the continuous `placebo_relative_to_true_L`.
*Reference magnitude.* 0.10 in the false-effect rate.

**Explicitly not hypothesized.** V3 states no hypothesis about, and takes no position on, whether local or network response modeling is empirically viable. That determination belongs to v2 and stands as v2 left it.

---

## H. Primary and secondary outcomes

### Primary (pre-registered, one family per hypothesis)

| # | outcome | cells | statistic | interpretation |
|---|---|---|---|---|
| P1 | `nire_persistent_step_h26_L` | `A_PEXACT` vs `A_S100` (Tier 1) | paired median difference + 95% bootstrap interval | does exact metering fix uncoupled local intervention recovery at k=4 |
| P2 | `beta_q_ratio_vs_exact` (derived), `partial_reliability_q` | `A_*` ladder (Tier 1) | paired median of ratio, and of ratio − $\hat\lambda^{\text{partial}}$ | is the attenuation the size measurement-error theory predicts |
| P3 | `nire_persistent_step_h26_L` + the §J benchmark triple | `B_GNONE`→`B_GHIGH` (Tier 3) | paired median differences; deterministic benchmark profiles | does coupling break the local model when data are excellent, and at which stage |
| P4 | `strong_edge_undirected_f1`, `edge_precision`, `false_edge_count` | `C_REAL_Gγ` vs `B_Gγ`; `B_GMED` vs `B_GHIGH` (Tier 3) | paired median differences | separating the identification bundle from edge strength |
| P5 | `placebo_false_effect_L` rate; `placebo_relative_to_true_L` | Block D 2×2×2 | Wilson intervals; three marginal contrasts; paired continuous medians | which forcing channel causes false attribution |

### Secondary and diagnostic

| outcome | role |
|---|---|
| `relative_shape_error_persistent_step_L` | shape-versus-amplitude discriminator. v2 median 0.037 against NIRE 0.849 ⇒ amplitude failure. Suggestive only: v2 shows shape stays below 0.20 in 124/128 cells including coupled ones. |
| `nire_persistent_step_h{4,13,52}_L` | error growth with horizon: "wrong from step one" versus "accumulated" |
| `A_diag_signed_relative_error_L` (**new, signed**) | v2 stored only the unsigned value, which is why the audit could not determine the direction of persistence bias |
| `nire_recomb_trueA_hatB`, `nire_recomb_hatA_trueB` (**new**) | exact partition of intervention error between persistence and response-magnitude terms, replacing v2's analytic-sensitivity fallback |
| `nire_pop_one_step_pseudotrue_L` = $F_{\text{train}}$ (**new**) | §J.4 — the one-step-trained estimator target |
| `nire_intervention_optimal_local_family` = $F_{\text{intervention}}$ (**new**) | §J.5 — representational benchmark of the frozen local response family |
| `partial_reliability_q`, `uncond_reliability_q`, `theory_reliability_q` (**new**) | §I; reporting the unconditional form alongside demonstrates why it is the wrong diagnostic |
| `neighbour_flux_share` (**new**) | **synthetic dimensionless physical-materiality diagnostic** (correction 8): the share of the true one-step head increment carried by cross-node conductance terms, averaged over the analysis window. It expresses coupling materiality on a scale internal to the simulation, in place of the uninterpretable γ label. It is **not** a directly observable field quantity: estimating it in Andhra Pradesh would itself require a calibrated hydrogeological model, which is out of v3's scope and is not assumed available. |
| `pumping_excitation_fraction_L`, `condition_number_L`, `max_vif_L` | conditioning controls; confirm the σ ladder is not silently changing design conditioning |
| `rmse_test_L / rmse_test_B0` | prediction-versus-intervention divergence, carried forward for continuity with v2's headline |
| `corr_placebo_qobs`, `corr_placebo_rproxy`, `vif_placebo` (**new**) | Block D leakage pathway |
| `estimability_status_L/N` + reason codes | first-class outcomes, never dropped, exactly as in v2 |
| `edge_recall`, `false_edge_any`, `nire_persistent_step_h26_N`, network estimability rate | Block C mechanism detail |
| realized `tau_relax`, `mean A_ii`, spectral radius, realized/detrended head SNR, TRAIN transition count | per-cell regime characterization; the transition count is required because Tier-2 and Tier-3 contrasts change it |

Every "new" column is a metric over quantities already available in the evaluation layer, or the frozen intervention/NIRE routine applied to a modified parameter vector. **No new estimator, filter, or inference method is introduced**; §17's exclusions hold in full.

---

## I. Pumping attenuation diagnostic

### I.1 Why the unconditional reliability ratio is the wrong statistic

Model L's regressors are `[intercept, own_level_lag1, season_sin, season_cos, time_trend, pumping, recharge_proxy]`, fit by unpenalized OLS with train-only z-scoring, coefficients returned in original units, and **no sign constraint** on the pumping coefficient. In a multivariate regression the attenuation of the focal coefficient is governed by the reliability of the focal regressor *after* projecting out the others. Here the pumping series has mean 1.0 with a seasonal amplitude of 0.4 that the seasonal terms largely absorb, so unconditional variance is dominated by variation the design does not use for identification, and $\operatorname{Var}(Q_{\text{true}})/\operatorname{Var}(Q_{\text{obs}})$ would badly understate the attenuation. This is the trap the brief flags, and it is why the audit could only offer its ~0.5 attenuation as "consistent with the frozen constants" rather than derived.

### I.2 Exact definition

Per replicate, per fitted node, on **TRAIN admissible rows only**. Let $Z$ be the model-L design matrix with the pumping column removed and the intercept retained, $Z=[\mathbf{1},h_t,\sin,\cos,\text{trend},R_{\text{proxy}}]$ (plus the placebo column in S8), and $M=I-Z(Z^\top Z)^{+}Z^\top$ its residual-maker (pseudo-inverse for rank safety; $M$ is invariant to affine column rescaling because the intercept is included, so z-scoring is immaterial). Let $q_{\text{obs}}$ be the observed pumping column, $q_{\text{true}}$ the true pumping aggregated over the same cadence intervals and the same rows, and $u=q_{\text{obs}}-q_{\text{true}}$:

$$SS_{\text{true}}=\|Mq_{\text{true}}\|^2,\quad SS_{\text{obs}}=\|Mq_{\text{obs}}\|^2,\quad SS_u=\|Mu\|^2,\quad CP=(Mq_{\text{true}})^\top(Mq_{\text{obs}})$$

$$\boxed{\hat\lambda^{\text{partial}}=\frac{CP}{SS_{\text{obs}}}}\qquad \hat\lambda^{\text{var}}=\frac{SS_{\text{true}}}{SS_{\text{true}}+SS_u}\qquad \hat\lambda^{\text{uncond}}=\frac{\operatorname{Var}(q_{\text{true}})}{\operatorname{Var}(q_{\text{obs}})}$$

$\hat\lambda^{\text{partial}}$ is the projection form the theory predicts; $\hat\lambda^{\text{var}}$ is the variance-ratio form, equal in expectation when $\operatorname{Cov}(Mq_{\text{true}},Mu)=0$; $\hat\lambda^{\text{uncond}}$ is reported only to quantify the error one would make by using it. All three plus $SS_{\text{true}},SS_{\text{obs}},SS_u,CP$ and the realized σ are stored per replicate.

### I.3 The finite-sample identity — and why it needs Tier 1

Because the Tier-1 pair shares every non-pumping regressor and the same outcome vector, $M$ and $\tilde y=My$ are **bit-identical between pair members**. Then exactly, with no asymptotics:

$$\frac{\hat\beta_Q^{(\sigma)}}{\hat\beta_Q^{(\text{EXACT})}}=\underbrace{\frac{q_{\text{obs}}^\top\tilde y}{q_{\text{true}}^\top\tilde y}}_{\to 1\ \text{under classical error}}\cdot\underbrace{\frac{SS_{\text{true}}}{SS_{\text{obs}}}}_{\text{reliability}}\ \Longrightarrow\ E\!\left[\frac{\hat\beta_Q^{(\sigma)}}{\hat\beta_Q^{(\text{EXACT})}}\right]\approx\hat\lambda^{\text{partial}}$$

since $E[u^\top\tilde y]=0$ ($u$ is fresh measurement noise, independent of the head path and the equation error) and $E[SS_{\text{obs}}]=SS_{\text{true}}+E[SS_u]$. This identity is available **only** for Tier-1 contrasts, which is why the σ ladder is Tier 1 by construction and why the diagnostic is not attempted on Tier-2 or Tier-3 contrasts.

### I.4 Theory-side prediction

Since $E[uu^\top]=(e^{\sigma^2}-1)\operatorname{diag}(q_{\text{true}}^2)$ and $M$ is idempotent, $E[SS_u]=(e^{\sigma^2}-1)\sum_t q_{\text{true},t}^2M_{tt}$:

$$\lambda^{\text{theory}}(\sigma)=\frac{SS_{\text{true}}}{SS_{\text{true}}+(e^{\sigma^2}-1)\sum_t q_{\text{true},t}^2M_{tt}}$$

### I.5 What this can and cannot distinguish

Reporting the three curves — realized paired ratio $\rho^{Q1}(\sigma)$, realized $\hat\lambda^{\text{partial}}(\sigma)$, and $\lambda^{\text{theory}}(\sigma)$ — over four σ levels sharing one noise realization gives genuine discrimination:

- **All three agree within the 0.05 reference magnitude across the ladder** ⇒ classical input attenuation, quantitatively and not merely by sign. Claimable: *the estimated withdrawal response is attenuated by the amount the residualized reliability of the withdrawal regressor implies.*
- **Realized ratio tracks $\hat\lambda^{\text{partial}}$ but not $\lambda^{\text{theory}}$** ⇒ classical mechanism, analytic form invalidated by heteroskedasticity, interval aggregation, or the mask; empirical reliability remains the right diagnostic.
- **Realized ratio systematically below both** ⇒ additional attenuation from another channel. The pre-registered next look is the recombination pair plus the signed $\hat A$ diagonal, testing whether pumping attenuation is partly absorbed by a compensating shift in the correlated lagged-state coefficient.
- **Realized ratio exceeds 1 or is non-monotone** ⇒ the classical framing fails. Report as such; do not force it.

**Guards, pre-registered.** The ratio is undefined when $\hat\beta_Q^{(\text{EXACT})}\approx0$; the count with $|\hat\beta_Q^{(\text{EXACT})}|<10^{-6}$ is reported and those replicates are excluded from the ratio statistic only, remaining in every other statistic, with the paired *difference* $\hat\beta_Q^{(\sigma)}-\hat\beta_Q^{(\text{EXACT})}$ reported as the guard-free companion. v2's 100% sign-correct rate at these settings makes the exclusion set likely empty. No winsorization; the full paired distribution is reported.

**Limits on the claim.** This establishes a mechanism *inside a known-truth simulation with mean-corrected unit-mean multiplicative lognormal error on reported withdrawal*. It does not establish that real administrative withdrawal error is classical — real reported abstraction is plausibly rounded, temporally aggregated, under-reported and spatially allocated, and v2 already shows `P-SCALEBIAS`, `P-TEMPAGG` and `P-SPATIALAGG` fail through *different* mechanisms (scale non-identification, excitation collapse). It does not establish that any correction method works; none is in scope.

---

## J. Coupling diagnostic — separating data, objective, and representational limits (correction 1)

Block B holds pumping at `P-EXACT` and every observation factor at the favorable bundle, so the measurement-error channel is off by construction and only γ moves. Five nested diagnostics.

**J.1 Pumping-channel control.** $\hat\beta_Q$ signed bias and $\hat\lambda^{\text{partial}}$ across γ. Flat and near-clean is a *precondition* for interpreting the rest, not a result.

**J.2 Shape versus amplitude.** `relative_shape_error_persistent_step_L` across γ. Suggestive only, for the reason noted in §H.

**J.3 Exact error decomposition.** `nire_recomb_trueA_hatB` (true $A^k$ diagonal with the estimated pumping response) and `nire_recomb_hatA_trueB` (estimated transition with the pseudo-true coarse pumping response), each pushed through the *same* frozen intervention/NIRE routine. This is the decomposition the audit wanted and could not compute, without refitting.

### J.4 `population_one_step_pseudotrue_benchmark` — $F_{\text{train}}(\gamma)$

**Definition.** Population / pseudo-true one-step model-L parameters under the V3 cell's **exact data-generating process, cadence, deterministic seasonal structure, intervention-independent forcing distribution, and TRAIN-transition support** — not a claim that the DGP is strictly stationary. The frozen truth has finite-horizon seasonal structure; `F_train` is the one-step L2 projection of next-head onto the actual L regressors as they appear in TRAIN rows of that process.

If an analytic expectation is unavailable, approximate it by Monte Carlo using the dedicated pool:

```text
V3_BENCHMARK
entropy 20260907030004
```

This pool is deterministic, disjoint from V3 ANALYSIS / SMOKE / DETERMINISM and from all V2 pools, fixed before V3 ANALYSIS, and used **only** to approximate deterministic pseudo-true benchmark quantities. Store convergence diagnostics (coefficient MC SE, NIRE MC SE vs pooled fit). Do not use `V3_ANALYSIS` seeds.

Then push those coefficients through the frozen NIRE routine.

**What it is.** The intervention behaviour of the current one-step-trained population target.

**What it licenses.** $F_{\text{train}}(\gamma)$ high supports exactly one claim: *better finite data cannot repair the intervention behavior of the current one-step-trained population target at this coupling level.*

**What it does not license.** It is **not** a lower bound on 26-step intervention error over the local model class. Any statement of the form "no member of the local model class can do better" is **not** supported by $F_{\text{train}}$.

### J.5 `intervention_optimal_local_response_benchmark` — $F_{\text{intervention}}(\gamma)$

**Verified frozen model-L family (from V2 code, not preference).**

- L is unpenalized OLS (`lam=0`); **own-level `a` is unconstrained**; **pumping coefficient is unconstrained** (no sign constraint; sign-recovery is a reported diagnostic, not a fit constraint).
- L's pumping regressor is **own-node only** (`Q_obs[:, node]`). Neighbour pumping is model S, not L.
- For L, `implied_transition_matrix` is **diagonal**: $A_{ii}=a_i$, $A_{ij}=0$.
- Frozen `persistent_step` is applied to **node 0**.
- NIRE averages `normalized_error` over nodes whose true-response L2 norm is at least `nire_node_inclusion_threshold` times the max node norm, at the frozen cadence-sampled scoring instants (primary horizon h=26).
- Multi-step evaluation is the recursion `out[t+1] = A_hat @ out[t] + beta_q * delta_Q_interval[t]` with non-finite `A_hat` entries replaced by 0. There is **no** `a ∈ [0, a_max]` clamp in fitting or evaluation.

Therefore `F_intervention` minimizes frozen persistent-step NIRE over the **actual algebraic L response family**: diagonal own-lag plus own-node pumping drive, with no invented physical sign constraint and no invented stability box.

**Own-pumping structure (mandatory).** Node 0 may have a direct local pumping response. Non-pumped nodes do **not** receive an artificial direct Q coefficient. Any true response at non-pumped nodes induced through hydraulic coupling is therefore potentially unrepresentable by L — that is part of the structural claim, not a bug to paper over. The objective scores the same nodes and times as frozen NIRE.

**Admissible domain.** A parameter vector is admissible iff the frozen evaluation recursion produces a finite predicted response at all scored instants. Parameters that overflow are excluded because the frozen NIRE is then undefined, not because L constrains them. Practically, for each node the own-lag $a_i$ is searched over a dense grid of finite values (including negative and $|a|>1$ where the finite-horizon response remains finite); for each $a$, the own-pumping amplitude $\kappa_i$ is optimized in closed form (linear in the residual). Only node 0's $\kappa$ can be nonzero under a node-0 persistent step; other nodes' $\kappa$ stay 0 because L cannot see neighbour Q.

**Certified minimum.** Exploit analytic $\kappa\mid a$; globally search $a$ by dense-grid bracketing plus deterministic local refinement; independently verify with a second denser grid. Report the minimum NIRE value (unique to numerical tolerance); disclose a non-unique argmin if it occurs.

**If after inspection this problem is not cleanly unique, omit `F_intervention` rather than inventing a domain.**

Tests required:

```text
uncoupled truth -> non-pumped nodes have zero true induced response
coupled truth -> non-pumped nodes may have nonzero true induced response
local-family benchmark -> cannot fake neighbor response with an unphysical direct Q coefficient
```

### J.6 The three-term decomposition, and its four readings

By construction $F_{\text{intervention}}(\gamma)\le F_{\text{train}}(\gamma)$, since $F_{\text{train}}$ evaluates a *particular* point of the family and $F_{\text{intervention}}$ minimizes over it. Reported alongside the median estimated NIRE:

$$\underbrace{F_{\text{intervention}}}_{\text{representational limit of the frozen family}} \ \le\ \underbrace{F_{\text{train}}}_{+\ \text{one-step-objective mismatch}} \ \lesssim\ \underbrace{\operatorname{med}_s \text{NIRE}_L}_{+\ \text{estimation and data cost}}$$

(the last relation is a median-level expectation, not an inequality: finite-sample noise can occasionally land a fitted model closer to the truth than the population one-step point.)

| pattern across γ | reading |
|---|---|
| $F_{\text{intervention}}$ near 0 at NONE and rising at MED/HIGH, with $F_{\text{train}}$ tracking it | **Representational limit within the frozen family.** Supports: *local response is adequate only where hydraulic coupling is sufficiently weak, and neither better data nor a better fitting objective repairs it within this family.* |
| $F_{\text{intervention}}$ stays low at all γ while $F_{\text{train}}$ rises | **Objective mismatch, not representational failure.** The family *can* represent the coupled response; one-step training does not target it. Implication is an intervention-aware fitting criterion — scoped as future work, not built here. |
| Both low while median estimated NIRE is high | **Estimation/data cost dominates.** Consistent with Block A's mechanism rather than a coupling mechanism. |
| $F_{\text{intervention}}$ high even at γ=NONE | The frozen one-mode family is inadequate for reasons unrelated to coupling — at k>1 this is expected to some degree, since interval aggregation of a linear system produces a distributed forcing lag the family cannot represent. Quantifying it is directly useful: it bounds how much of Block A's residual at `P-EXACT` is irreducible cadence-aggregation misspecification rather than measurement error. |

Both benchmarks are computed for **every** v3 cell, not just Block B, precisely because of that last row. Neither is a gate; neither has a threshold; and if the intervention-optimal problem turns out not to be uniquely or cleanly definable in the frozen NIRE geometry during Build, **$F_{\text{intervention}}$ is omitted and the structural claim is weakened accordingly** — reduced to $F_{\text{train}}$'s licensed statement plus the empirical floor (the minimum estimated NIRE observed at each γ under the favourable bundle) — rather than forced.

---

## K. S8 diagnostic — exact recharge/confounding/pumping contrasts

Full 2×2×2 on `S8 / single / cadence 4`, everything else at `V3_REFERENCE` (`snr_head` 10, `mcar` 0.10, `blocks` 0, `obs_frac` 1.0, `process_noise_sd` 0.05, `memory` MED). Real pumping present in every fit, verified per replicate by `s8_real_pumping_present_L`; true placebo coefficient exactly zero; placebo correlated 0.85 with true recharge via v2's frozen `s8_placebo_construction`.

| factor | levels | v2 provenance |
|---|---|---|
| pumping quality | P-EXACT / P-MULTNOISE(0.10) | both frozen v2 levels |
| recharge quality | R-EXACT / R-NOISE(0.20) | both frozen v2 levels |
| confounding ρ | 0.0 / 0.3 | both frozen levels; 0.3 is the reference and the frozen S8 level |

The frozen V3 summarizer reports, for `placebo_false_effect_L` and `placebo_relative_to_true_L`:

- 3 main effects (pumping, recharge, confounding);
- 3 two-way interactions (pumping×recharge, pumping×confounding, recharge×confounding);
- 1 three-way interaction (pumping×recharge×confounding) as **preregistered secondary/descriptive**, not primary.

Pairing tier per contrast: pumping and recharge contrasts are **Tier 1**; the ρ contrast is **Tier 3**.

**S8 validation vs external consistency (do not conflate).**

- **Hard implementation validation** is the bit-for-bit V2 legacy parity test on `G3R3` under `(legacy_sequential, legacy_v2)`. That is the real code-path check.
- **`D_PM_RN_R3` under `(named_substreams, orthogonal_v3)` is an external-consistency anchor**, not a bit-level replication. Its false-effect rate need not numerically reproduce 0.600, because V3 deliberately changes randomization architecture and structural-seed semantics. If its behaviour is *radically* inconsistent with V2, investigate before interpreting Block D; do **not** create an arbitrary numeric reproduction gate.

No new placebo threshold is invented. The frozen 0.20 rule is used unchanged as a legacy v2 reference criterion; the continuous ratio distribution carries the inference. v2 found the median false attribution at 0.22–0.25 — just above the frozen line, with no replicate reaching parity — so the binary indicator is threshold-marginal and the continuous quantity is the more informative one.

---

## L. Network oracle-confound diagnostic

Fixed topology `path5` throughout, so the candidate graph (7 candidate pairs) and true edge set are constant except through γ.

| | γ = MED | γ = HIGH |
|---|---|---|
| `IDENTIFICATION_REGIME = REALISTIC` | `C_REAL_GMED` | `C_REAL_GHIGH` |
| `IDENTIFICATION_REGIME = FAVOURABLE` | `B_GMED` | `B_GHIGH` |

$\text{BUNDLE}(\gamma)$: `B_GMED − C_REAL_GMED` and `B_GHIGH − C_REAL_GHIGH`. $\text{GAM}(d)$: `C_REAL_GHIGH − C_REAL_GMED` and `B_GHIGH − B_GMED`. Outcomes: `strong_edge_undirected_f1`, `edge_precision`, `edge_recall`, `false_edge_count`, `false_edge_any`, `nire_persistent_step_h26_N`, network estimability rate with reason codes. Because v2's evidence shows the degradation is precision-driven (recall 1.00→0.75 while precision 1.00→0.67), precision and false-edge count are co-primary with F1.

**Three hard limits, all disclosed wherever Q3 is reported.**

1. **`IDENTIFICATION_REGIME` is a bundle of seven factor changes, and not a measurement-quality factor.** It moves cadence (hence TRAIN sample size ≈129→519 and the coarse-step estimand), pumping quality, recharge quality, confounding, missingness, head SNR, and process noise together. Because ρ and `process_noise_sd` change, the realized latent forcing and head paths change too, so this is a Tier-3 contrast (§E.3) and **not** an exact same-truth comparison. The bundle effect is reported as a bundle effect. It is not attributed to measurement quality, to observation quality, or to any individual factor, and it is not decomposable by this design. Un-bundling it would cost roughly one cell per factor per γ, which the brief correctly rules out.
2. **The γ contrast holds realized `tau_relax` fixed by re-solving the conductance scale**, so "more coupling" also means "less boundary leakage," and $A_{ii}$ differs across γ.
3. **`NETWORK_SUPPORT_FINAL = NOT_EARNED` stands regardless**, and v3 may not be cited as support for empirical `M1N`. `B_GNONE`'s false-edge behaviour, however favourable, is a mechanism observation only.

---

## M. Statistical analysis

**Paired contrasts, continuous reporting, no gates.** For every contrast: paired per-seed differences; paired median and paired mean; 95% percentile-bootstrap intervals from 10,000 resamples **resampling seeds as the unit** (preserving pairing); proportion of seeds improving; the full paired difference distribution (q05, q10, q25, q50, q75, q90, q95); and the **realized $\sigma_d$ and paired correlation**, so the pairing's efficiency is measured rather than assumed. For rate outcomes: point estimate, Wilson 95% interval, and paired rate differences with a bootstrap interval over seeds. Every contrast is labelled with its pairing tier (§E.3).

**Interval semantics.** All 95% bootstrap and Wilson intervals in V3 are **pointwise Monte Carlo uncertainty intervals** for their individual estimands. They are not simultaneous family-wise confidence bands over all V3 contrasts and should not be interpreted as such. No formal multiplicity correction is required because there are no p-values, no significance declarations, all preregistered primaries are reported, and reporting is continuous. Do not imply simultaneous 95% coverage across primary families.

**No hypothesis-testing machinery.** No p-values, no significance declarations, no test statistics, no "falsified if" rules. Hypotheses preregister direction, mechanism pattern, estimands, intervals, and SESOI (§G); results are reported as continuous estimates with uncertainty and compared to the reference magnitudes as an interpretive aid.

**Reference magnitudes are SESOI, not gates.** 0.05 NIRE, 0.10 rate difference, 0.05 reliability discrepancy — fixed in the freeze document before execution, described there and in every output artifact as *preregistered smallest-effect-of-interest / decision-relevance reference magnitudes*. They generate no boolean column, no pass field, and no status. `design_v3.yaml` contains `gates: {}`, the v3 summarizer computes no pass/fail statuses, no support statuses and no gate aggregation, and `test_no_gates_in_v3.py` enforces all of this — including that no output column name matches a pass/fail pattern and that no SESOI value is compared to produce a boolean in any summarizer path.

**Multiplicity.** Five primary families (§H), each pre-specified and attached to a distinct decision, all reported in full regardless of outcome — so there is no selection to correct for, and no correction is applied. Everything else is explicitly secondary/descriptive, carries no confirmatory claim, and may not be promoted to primary after results are seen.

**Legacy criteria.** v2's NIRE 0.20, edge-F1 0.80, and placebo 0.20 rules are shown for orientation only, labelled *pre-existing legacy v2 planning criteria*. They are not retuned, not optimized against, and no v3 cell was chosen to cross any of them.

---

## N. File architecture

Two additive trees. Nothing under `config/`, `src/`, `scripts/`, `tests/`, or `outputs/` at the v2 module root is created, renamed, or modified.

```text
other_sources/groundwater_identifiability_synthetic/
├── audits/independent_scientific_audit_v1/          # STEP 1, additive only
│   ├── INDEPENDENT_SCIENTIFIC_AUDIT.md              #   verbatim
│   ├── EMPIRICAL_DECISION_TABLE.csv                 #   verbatim
│   ├── EMPIRICAL_DECISION_TABLE.md                  #   verbatim
│   ├── PRESERVATION_NOTE.md                         #   NEW, additive
│   ├── SOURCE_MANIFEST.csv                          #   sha256 of each preserved file
│   └── scratch/                                     #   auditor .py + intermediates, verbatim
│       ├── 00_verify_hashes.py … 06_ranking_and_decision_table.py
│       └── 00_hash_verification.json, 01_gate_reproduction.json, 02_cell_surface.csv,
│           03_local_mechanism.txt, 04_eiv.txt, 04_nonG0_with_growth.csv,
│           05_s8_s6_net.txt, 06_factor_ranking_local.csv, 06_rank.txt
└── followups/v3_mechanism_confirmation/
    ├── PROTOCOL.md                     # Q1–Q4, H1–H4, estimands, SESOI, pairing tiers
    ├── DESIGN_FREEZE_V3.md             # in V3_DESIGN_HASH scope
    ├── PROVENANCE_AND_LAYERS.md        # three-evidence-layer statement (§O)
    ├── V3_DIVERGENCE_FROM_V2.md        # every code change vs vendored parent, with rationale
    ├── BENCHMARK_DEFINITIONS.md        # F_train and F_intervention: exact definitions, scope limits
    ├── config/design_v3.yaml           # in V3_DESIGN_HASH scope; contains `gates: {}`
    ├── src_v3/                         # vendored from v2 CODE_HASH 7cc64809…, then modified
    │   ├── design_v3.py dgp.py observations.py fit.py models.py interventions.py
    │   │   metrics.py identifiability.py evaluation.py plan_v3.py summarize_v3.py
    │   ├── rng.py                      # NEW: named-substream CRN layer
    │   ├── modes.py                    # NEW: rng_mode × system_seed_mode legality
    │   ├── reliability.py              # NEW: partial reliability + attenuation + recombination
    │   └── benchmarks.py               # NEW: F_train (V3_BENCHMARK MC), F_intervention
    ├── scripts_v3/
    │   ├── freeze_protocol_v3.py  run_determinism_v3.py  run_v2_parity_check.py
    │   ├── compute_benchmarks.py       # Pass 1; no ANALYSIS seed touched
    │   ├── run_smoke_v3.py  run_v3.py  summarize_v3.py  pair_contrasts.py
    ├── tests_v3/
    │   ├── test_v2_hashes_unchanged.py     test_vendored_parity.py
    │   ├── test_mode_pairing.py            test_crn_pairing.py
    │   ├── test_gamma_none_construction.py test_reliability_math.py
    │   ├── test_benchmarks.py              test_no_gates_in_v3.py
    │   ├── test_seed_disjointness.py       test_no_truth_leakage_v3.py
    │   └── test_plan_v3.py
    └── outputs/
        ├── provenance/  DESIGN_V3_FREEZE.json, DESIGN_V3_FREEZE_MANIFEST.csv,
        │                CODE_MANIFEST_V3.csv, V2_PARENT_MANIFEST.csv,
        │                SEED_POOL_V3.json, RUN_MANIFEST_V3.json, V3_OUTPUT_HASHES.csv
        ├── benchmarks/  BENCHMARKS_V3.csv, BENCHMARKS_V3.json     # Pass 1; no ANALYSIS outcomes
        ├── determinism/ DETERMINISM_V3.json, V2_PARITY_REPORT.json
        ├── smoke/       SMOKE_V3_REPLICATES.csv, SMOKE_V3_SUMMARY.json, CRN_PARITY_REPORT.json
        ├── analysis/    (created only after the checkpoint clears)
        │                v3_replicates.csv, blockA_pumping.csv, blockB_coupling.csv,
        │                blockC_network.csv, blockD_placebo.csv, paired_contrasts.csv,
        │                V3_MECHANISM_FINDINGS.json
        └── audits/      POST_RUN_AUDIT_V3.md
```

### Why the code is vendored rather than imported

v2's hash scope is literal, not configurable:

```28:31:other_sources/groundwater_identifiability_synthetic/src/design.py
DESIGN_ARTIFACTS = ("config/design_v2.yaml", "DESIGN_FREEZE_V2.md")

# Every source file whose content is scientific. Determines CODE_HASH.
CODE_GLOBS = ("src/*.py", "scripts/*.py", "tests/*.py")
```

`CODE_HASH` is a **glob**, not a fixed file list, so adding a single `.py` under `src/`, `scripts/`, or `tests/` — including an innocuous helper or the auditor's scratch scripts — silently changes it. Meanwhile the CRN refactor and the structural-seed change necessarily modify `dgp.py` and `observations.py`. Importing v2's `src/` is therefore not viable, and editing it destroys v2's `CODE_HASH`. Vendoring a frozen copy under `src_v3/` and modifying that leaves v2 byte-identical. Duplication is mitigated by `V2_PARENT_MANIFEST.csv` (v2 SHA-256 of every vendored file), `test_vendored_parity.py` (any vendored file not listed in the divergence manifest must still match its parent byte-for-byte), and `V3_DIVERGENCE_FROM_V2.md` (every intentional change with rationale). The `_v3` suffixes are defensive: even if v2's globs were later widened to `**/*.py`, `src_v3/` would not be captured.

**Two easy accidents this prevents:** placing the auditor's seven scratch `.py` files under `scripts/` or `tests/`, and adding a v3 helper under `src/`. Both are blocked by `test_v2_hashes_unchanged.py`. Preserving `.md`, `.csv`, `.json`, `.txt` anywhere is safe, since the globs match only `.py`.

---

## O. Provenance and freeze protocol

**Three evidence layers**, recorded in `PROVENANCE_AND_LAYERS.md` and required to survive into paper language:

```text
LAYER 1 — V2: confirmatory frozen known-truth experiment.
  Preregistered before any ANALYSIS seed. DESIGN_HASH b53f5594…, CODE_HASH 7cc64809….
  LOCAL_RESPONSE_NOT_IDENTIFIED and NETWORK_SUPPORT_FINAL = NOT_EARNED are final.

LAYER 2 — POST-V2 AUDIT: post-hoc mechanism diagnosis.
  Written after v2 results existed, from already-stored quantities. Explanatory only.
  Never a pass/fail determination. Preserved verbatim; not rewritten to look preregistered.

LAYER 3 — V3: prospective orthogonal mechanism-confirmation experiment.
  H1–H4 are POST-HOC RELATIVE TO V2 and PROSPECTIVE RELATIVE TO V3.
  Frozen before any V3 ANALYSIS seed is generated or inspected.
  Defines no gates and cannot alter any v2 status.
```

Required sentence, appearing in `PROTOCOL.md`, `DESIGN_FREEZE_V3.md`, and any paper section reporting v3: *v3 is a prospective mechanism-confirmation experiment motivated by post-hoc analysis of the frozen v2 study; its hypotheses were not preregistered before v2.*

**Hashes.** `V3_DESIGN_HASH` over `(config/design_v3.yaml, DESIGN_FREEZE_V3.md, BENCHMARK_DEFINITIONS.md)`; `V3_CODE_HASH` over `(src_v3/*.py, scripts_v3/*.py, tests_v3/*.py)`; `V2_PARENT_CODE_HASH = 7cc64809…` recorded and test-asserted. `RUN_MANIFEST_V3.json` records both v3 hashes, the v2 parent hashes, **`rng_mode` and `system_seed_mode`**, the feature commit, seed-pool hashes, cell count, seeds per cell, wall time, and platform/library versions. Both mode flags are additionally written into every output row. Every v3 output is SHA-256'd into `V3_OUTPUT_HASHES.csv`. Results are immutable once summarized; any post-result code change invalidates and re-runs the affected outputs and regenerates `V3_CODE_HASH` — the protocol v2 actually exercised when it invalidated 7,740 replicates over a `uint64`-through-`float` seed-parsing defect.

**Seed pools.** New entropy family, disjoint by construction and by verification:

| pool | entropy | n | role |
|---|---|---|---|
| `V3_DETERMINISM` | 20260907030001 | 5 | deterministic sanity only |
| `V3_SMOKE` | 20260907030002 | 3 | engineering only, never inferential |
| `V3_ANALYSIS` | 20260907030003 | 200 | substantive; outcomes unused until Pass 2 |
| `V3_BENCHMARK` | 20260907030004 | 16 | `F_train` Monte Carlo approximation only |

Same materialization as v2 (`SeedSequence(entropy).spawn(n)`, `uint64` per child, `PCG64`).

**ANALYSIS seed handling.** Mechanical deterministic materialization of the complete V3 ANALYSIS seed pool for hashing, disjointness checking, and immutable manifest generation **is permitted** before Pass 2:

```text
V3_ANALYSIS_POOL_FROZEN = true
V3_ANALYSIS_OUTCOMES_INSPECTED = false
V3_ANALYSIS_REPLICATES_RUN = 0
```

Do not print individual seed values; do not manually inspect them; do not use them to generate data, run any replicate, compute any metric, or sample/select among them. The v2-parity check uses three **frozen v2 ANALYSIS** seeds already published in the v2 sweep file.

**v2 immutability, verified not asserted.** `test_v2_hashes_unchanged.py` recomputes v2's `DESIGN_HASH` and `CODE_HASH` and compares against the frozen literals; it must pass in every Build pass, before and after audit preservation. v2's `outputs/` are never written to.

**Additive v2 errata.** The audit identified a presentation defect in `outputs/analysis/gate_results.csv`: the six G3 cells render as `pass=True / state=ESTIMATED_PASSED_GATE / support_status=SUPPORTED` and the file contains no `SGI_G3` row, because that column reflects per-cell estimability rather than falsification triggers. The authoritative `FINAL_SYNTHETIC_IDENTIFIABILITY_STATUS.json` correctly records `SGI_G3.hard_failure = true`, so nothing scientific is affected, but a reader consulting only the CSV would conclude G3 passed. The frozen CSV must **not** be edited; instead an additive `outputs/analysis/ERRATA_V2_GATE_RESULTS.md` records the defect, its scope, and the authoritative source, with a matching note in the paper's supplement.

---

## P. Checkpoint protocol

Two Build passes with a hard stop between them. Pass 1 may freeze the ANALYSIS pool for hashing but must not run or inspect ANALYSIS outcomes.

**Pass 1 — preserve, freeze, implement, verify. Ends at a stop.**

1. Preserve the audit into `audits/independent_scientific_audit_v1/` verbatim, with `.py` scratch under `scratch/` and never under `src|scripts|tests`. Write `PRESERVATION_NOTE.md` and `SOURCE_MANIFEST.csv`. Re-verify v2 hashes. Commit — additive only.
2. Write `PROTOCOL.md`, `DESIGN_FREEZE_V3.md`, `PROVENANCE_AND_LAYERS.md`, `BENCHMARK_DEFINITIONS.md`, `config/design_v3.yaml`. Compute `V3_DESIGN_HASH`.
3. Vendor v2 code into `src_v3/`; record `V2_PARENT_MANIFEST.csv`. Implement `rng.py`, `modes.py`, `reliability.py`, `benchmarks.py`, the `gamma=NONE` branch, the new stored columns, `plan_v3.py` (21 cells), `summarize_v3.py` (no gates), `pair_contrasts.py`. Write `V3_DIVERGENCE_FROM_V2.md`.
4. Tests green: v2 hashes unchanged; vendored parity; **mode pairing** (mixed `rng_mode`/`system_seed_mode` combinations rejected, scripts pinned to the legal pairs, both modes recorded per row, summarizer refuses non-uniform inputs); **CRN parity** (for every planned Tier-1 pair, every shared component array bit-identical; for Tier-3 pairs, the *base innovation* arrays bit-identical and the realized truth confirmed to differ); **`gamma=NONE` construction** (§D.1, all seven assertions); reliability math on fixtures with known answers; benchmark math on fixtures with analytically known minima; no gates in v3; seed disjointness; no truth leakage; cell matrix matches the freeze document exactly.
5. Deterministic sanity: v3's analogue of `SGI_G0` — noise-free, `P-EXACT`, `R-EXACT`, ρ=0, `snr=inf`, single node — recovers coefficients to ≤1e-8 on `V3_DETERMINISM` seeds.
6. **v2 bit-for-bit parity check, expanded.** With `rng_mode=legacy_sequential` **and** `system_seed_mode=legacy_v2`, v3 must reproduce v2's `sweep_replicates.csv` rows exactly for **`G1R1` (local), `G2R3` (network), and `G3R3` (S8/placebo)** at **three frozen v2 ANALYSIS seeds each** — nine replicates covering the local, network, and placebo evaluation paths. This is the strongest available evidence that vendoring plus the two refactors did not perturb the physics, the estimator, or the placebo construction. Written to `V2_PARITY_REPORT.json`. **Gate on Pass 2.**
7. Compute per-cell benchmarks $F_{\text{train}}$ (V3_BENCHMARK Monte Carlo if needed) and $F_{\text{intervention}}$ (deterministic given the system) for all 21 cells; publish `BENCHMARKS_V3.csv`. No `V3_ANALYSIS` outcomes are involved.
8. Engineering smoke: 21 cells × 3 `V3_SMOKE` seeds. Schema completeness, estimability distribution, runtime and storage projection, `CRN_PARITY_REPORT.json`. **Non-inferential**: no smoke value may alter any design choice, threshold, hypothesis, SESOI, or cell.
9. **STOP.** Publish `V3_DESIGN_HASH`, `V3_CODE_HASH`, both mode flags, seed-pool hashes and disjointness, and the benchmark/parity/determinism/smoke reports for external review.

```text
V3_ANALYSIS_POOL_FROZEN = true
V3_ANALYSIS_REPLICATES_RUN = 0
V3_ANALYSIS_OUTCOMES_INSPECTED = false
```

**Pass 2 — only on explicit external authorization.**

10. Validate manifests and hashes; assert `V3_CODE_HASH` unchanged since the freeze and both modes set to `(named_substreams, orthogonal_v3)`. Run the sweep: 21 × 200 = 4,200 replicates, single launch, no adaptive stopping, no interim inspection.
11. Frozen summarization via `summarize_v3.py --analysis` after hash and mode validation — never ad-hoc scripts, preserving the discipline v2's provenance audit made a point of. Write output hashes.
12. Independent post-run audit by a fresh reviewer: read-only, re-deriving every primary contrast from `v3_replicates.csv` **without importing `summarize_v3.py`**, mirroring how the v2 audit re-implemented the hashing rules rather than importing them. Write `POST_RUN_AUDIT_V3.md`.

Design changes discovered after step 9 require an explicit `design_v4` with a new hash and a fresh freeze; they are not folded into v3 retroactively.

---

## Q. Decision map

Reference magnitudes are the preregistered SESOI (0.05 NIRE, 0.10 rate) and, for orientation only, v2's legacy 0.20 planning criterion. None is a gate.

| # | v3 result pattern | project implication |
|---|---|---|
| **A** | `A_PEXACT` NIRE near or below the legacy 0.20 marker with a large paired improvement over `A_S100`, **and** `A1_PEXACT_K1` also materially improved | **Outcome A.** Withdrawal-measurement identification is the immediate empirical priority; forcing-data acquisition (metering resolution, absolute scale, sub-annual reporting) becomes the top-ranked data investment, and the audit's Option C moves from MODERATE-HIGH to HIGH. |
| **B** | `A_PEXACT` improves materially but stays well above the marker; `nire_recomb_*` attributes the residual to the persistence term; `A1_PEXACT_K1` shows persistence compounding at k=1 | **Outcome B.** Metering is necessary but insufficient; a second limitation remains, on the state side at long horizons. This does not authorize building a state-space estimator (out of scope); it authorizes *scoping* one as future work, with the measurement-error term correctly placed on Q first. |
| **C** | Block B: NIRE_L low at γ NONE/LOW and materially degraded at MED/HIGH under `P-EXACT` + favourable observations, with **both** $F_{\text{train}}(\gamma)$ and $F_{\text{intervention}}(\gamma)$ rising | **Outcome C.** No member of the *frozen one-mode local response family* can represent the coupled intervention, so `M1L` is defensible only where weak coupling holds. Because `neighbour_flux_share` is a **synthetic** materiality diagnostic and not a field-observable quantity, this outcome implies a prior hydrogeological assessment step — itself a calibrated-modeling task, not a data lookup — before `M1L` could be justified in Andhra Pradesh. Richer local families (higher-order own-lags, distributed forcing lags) are not excluded by this result. |
| **C′** | Block B: NIRE_L degrades with γ and $F_{\text{train}}$ rises, but $F_{\text{intervention}}$ stays low | **Objective mismatch, not representational failure.** The frozen family can represent the coupled response; one-step training does not target it. More optimistic than C: scope an intervention-aware fitting criterion as future work. Do not conclude structural invalidity. |
| **C″** | Block B: both benchmarks low while median estimated NIRE is high | The coupling penalty is an **estimation/data** cost, not a coupling-specific structural cost. Folds back into Outcomes A/B. |
| **D** | Block D: false-effect rate materially lower at `R-EXACT` and/or ρ=0, with a clear marginal effect | **Outcome D.** Recharge/climate identification becomes a required empirical qualification for `M1L`, reversing the audit's rank-7 low-priority reading — which rested on the recharge curve's inertness for NIRE and which the audit itself flagged as in tension with S8. |
| **D′** | Block D: the dominant marginal effect is **pumping quality** | A new finding that inverts the prescription: false causal attribution to a pumping-like regressor is driven by noise in the *real* withdrawal channel, so the fix is metering rather than climate covariates. This is the specific reason Block D includes the pumping factor. |
| **E** | Block D: `D_PE_RE_R0` within the 0.10 rate SESOI of the `D_PM_RN_R3` external-consistency anchor, with no evidence that cleaning forcing channels reduces false attribution | **Outcome E.** The estimator has a more fundamental attribution problem that clean forcing does not fix. Strengthens deferral and becomes a first-order methodological finding. |
| **E′** | `D_PM_RN_R3` is *radically* inconsistent with the V2 S8 pattern (e.g. near-zero false-effect where V2 was high), after the bit-for-bit `G3R3` parity check already passed | Investigate the V3 placebo path under named-substream/orthogonal modes before interpreting Block D. Not an arbitrary numeric reproduction gate of 0.600. |
| **F** | Block C: $\text{BUNDLE}(\gamma)$ material at both γ **and** $\text{GAM}(d)$ material at both regimes | v2 oracle network success cannot be attributed to stronger edges alone or to the favourable bundle alone. Constrains paper language; attributes nothing to measurement quality specifically. |
| **F′** | Block C: $\text{BUNDLE}(\gamma)$ null | The v2 oracle network improvement was true-signal strength. Well-network investment loses its principal synthetic justification — a materially stronger negative than v2 currently supports. |
| **G** | H1's mechanism pattern not met: attenuation exceeds the reliability prediction | Not classical input attenuation alone. Report as such; do not force the theoretical model. Re-scope via the recombination decomposition and the signed $\hat A$ diagonal. |

**Network rule, unconditional.** `NETWORK_SUPPORT_FINAL = NOT_EARNED` from v2 remains authoritative under **every** row above. V3 may *explain* network failure; it may not convert v2 into network support. **Empirical `M1N` is not recommended from v3 under any outcome**, and v3 defines no `M1N` qualification gate.

---

## R. Paper relevance

**What v3 could legitimately add** — three candidate contributions, all currently hypotheses:

1. *Two distinct failure mechanisms with different remedies.* "Groundwater-response errors for infrastructure planning arise from at least two mechanisms: noisy withdrawal measurements attenuate the estimated intervention magnitude, while omitted hydraulic coupling creates misspecification that better measurement cannot repair." V3 would make this measured rather than inferred, and §I lets the first half be stated *quantitatively* — the attenuation matches the residualized reliability of the withdrawal regressor — which is considerably stronger than "attenuation was observed." Most likely to transfer beyond groundwater, since the structure recurs wherever a mismeasured policy input drives a counterfactual. The second half must be stated at the precision §J supports: within the frozen one-mode local response family, and distinguishing an objective mismatch from a representational limit.
2. *Joint dependence of network recovery on the identification bundle and on physical signal strength.* "Network-recovery success depends jointly on the favourable identification regime and on true coupling strength; oracle experiments that change both cannot attribute improvement to either alone." Partly a methodological caution about oracle-bundle design in identifiability studies, with v2's own confound as the worked example. Narrower, and it must not be phrased as a claim about measurement quality.
3. *A forcing channel produces false causal attribution.* "Recharge/climate confounding can produce false pumping-like causal attribution even when the true placebo effect is zero" — or, per Outcome D′, that withdrawal measurement error does. Either version is publishable; which is true is currently unknown.

**What v3 cannot establish, and must not be written as establishing.**

- Anything about v2's statuses; both stand as frozen.
- That local or network response modeling is viable in Andhra Pradesh. v3 is synthetic, its truth is a linear coupled reservoir system, and attainability in a real basin is untouched.
- That `neighbour_flux_share` is a field-checkable criterion. It is a synthetic dimensionless diagnostic; mapping it to a real basin requires a calibrated hydrogeological model that v3 neither builds nor assumes.
- That **no local model** can represent a coupled intervention. Only the frozen one-mode family is characterized; higher-order own-lags or distributed forcing lags could enlarge the family and lower $F_{\text{intervention}}$.
- That better data cannot help when $F_{\text{train}}$ is high. That statement is licensed only for the *current one-step-trained estimator target*, not for the model class.
- That real withdrawal-measurement error is classical. v2 already shows `P-SCALEBIAS`, `P-TEMPAGG` and `P-SPATIALAGG` fail through *different* mechanisms (scale non-identification, excitation collapse).
- That any correction method works. A demonstrated mechanism is not a demonstrated remedy; no estimator development is in scope.
- Attribution of the `IDENTIFICATION_REGIME` effect to measurement quality or to any single factor.

**Proportionality.** v2's strongest results — prediction-versus-intervention divergence at 128/128 versus 126/128, and false network discovery at a 96.7% any-rate in networks with no edges — remain the headline. V3 is a mechanism section that explains *why* and converts a data-acquisition recommendation from inference into measurement. The project is groundwater-aware infrastructure planning; synthetic identifiability is instrumental to it, not the subject.

---

## S. Risks

| # | risk | severity | mitigation |
|---|---|---|---|
| 1 | **The refactors silently change physics, estimator, or placebo construction**, making v3's clean-looking contrasts quietly incomparable to everything established | high | Expanded bit-for-bit parity: `G1R1`, `G2R3`, `G3R3` × 3 frozen v2 seeds under `(legacy_sequential, legacy_v2)`, covering local, network and placebo paths. **Gate on Pass 2.** Plus vendored-parity tests and a line-level divergence manifest. |
| 2 | **Accidental mixing of `rng_mode` and `system_seed_mode`**, producing a run that is neither v2-comparable nor v3-valid | high | Only two combinations legal, rejected at construction; scripts pinned; both flags in every output row and in the run manifest; summarizer refuses non-uniform inputs; `test_mode_pairing.py`. |
| 3 | **Breaking v2's `CODE_HASH`** by adding any `.py` under `src/`, `scripts/`, `tests/` — including the audit's scratch scripts | high | `test_v2_hashes_unchanged.py` asserts the frozen literals; scratch under `audits/.../scratch/`; `_v3`-suffixed v3 directories. |
| 4 | **Over-claiming from the benchmarks** — reading $F_{\text{train}}$ as a model-class bound | medium-high | Two separately named quantities with distinct licensed claims in `BENCHMARK_DEFINITIONS.md`, `PROTOCOL.md` and every reporting artifact; §J.6's four-way reading table; and the pre-committed fallback of omitting $F_{\text{intervention}}$ and *weakening* the structural claim rather than forcing it. |
| 5 | **$F_{\text{intervention}}$ misread as a bound over all local models** | medium-high | Family $\mathcal{G}$ defined explicitly as one-mode; the scope limit stated with the definition, in the decision map, and in the paper-claims list. |
| 6 | **`orthogonal_v3` changes v3's realized systems relative to v2**, so v3 numbers are not cell-for-cell comparable to v2's | medium-high | Disclosed in the freeze; every v3 claim rests on internal paired contrasts; each block re-runs its own reference arm; v2 comparisons are qualitative external-consistency checks only. Accepted deliberately — γ-orthogonality is worth more than cross-study numerical comparability. |
| 7 | **v3 read as rescuing `M1L`/`M1N` or overturning v2** | medium-high | `gates: {}` enforced by test; no pass/fail output of any kind; SESOI explicitly not gates; `PROVENANCE_AND_LAYERS.md`; the unconditional network rule; the post-hoc-relative-to-v2 sentence in every v3 document. |
| 8 | **Block C over-interpreted** as a measurement-quality or same-truth contrast | medium | Factor renamed `IDENTIFICATION_REGIME`; statistic renamed `BUNDLE(γ)`; Tier-3 label attached to every reported contrast; shared-versus-differing components enumerated in §E.3; sample-size change disclosed. |
| 9 | **Block D's clean corners look good because the placebo pipeline is broken** | medium | `D_PM_RN_R3` reproduces the frozen `G3R3` configuration; Outcome E′ blocks all Q4 interpretation if the anchor fails; parity check covers the S8 path. |
| 10 | **`gamma=NONE` hits a division-by-zero or a silently degenerate system** | medium | Explicit division-free branch on exact equality (§D.1) with a seven-assertion dedicated test, including instrumented confirmation that the γ-dividing branch is never entered. |
| 11 | **The attenuation ratio is unstable** when $\hat\beta_Q^{(\text{EXACT})}\approx0$ | low-medium | Pre-registered guard with the excluded count disclosed; guard-free paired difference reported alongside; v2's 100% sign-correct rate makes the exclusion set likely empty. |
| 12 | **CRN could increase rather than decrease paired variance** on some contrast | low-medium | No design decision depends on CRN reducing variance; n=200 is justified against the adversarial bound $\sigma_d\le\sigma_1+\sigma_2$ (§F.2); realized $\sigma_d$ and paired correlation are reported per contrast. |
| 13 | **n=200 makes decision-irrelevant differences look "detectable"** | low-medium | Continuous reporting only, no p-values, and SESOI fixed before execution. |
| 14 | **Post-hoc hypotheses invite selective reporting** | low-medium | Freeze and benchmarks published before any `V3_ANALYSIS` seed exists; all primaries reported regardless of outcome; secondaries may not be promoted afterwards. |
| 15 | **Block A generalizes from a single node** to "uncoupled truth" | low | `B_GNONE` supplies the multi-node uncoupled case under the same favourable bundle; A and B jointly cover both. |
| 16 | **γ contrast confounds coupling share with boundary leakage** (memory held fixed by re-solving $c$) | low | Intrinsic to the v2 factor definition and correct for a fixed-memory contrast; disclosed, with `neighbour_flux_share` reported for interpretability. |
| 17 | **Model N undefined on `single`**, used by Blocks A and D | low | Blocks A and D report L only; `summarize_v3` must tolerate absent N — v2's `G3R3` is already S8/single, so the path exists and is covered by the parity check. |
| 18 | **F1 undefined at γ=NONE** (zero true edges) | low | Use actual V2 `edge_metrics` semantics (NaN when both true and predicted edge sets are empty); report `false_edge_count` / `false_edge_any` / `predicted_edge_count`; never impute F1/recall for rectangular tables. |
| 19 | **The frozen persistent-step intervention may not be applied at the evaluation node** on `path5`, making $F_{\text{intervention}}=1$ by construction | low | Build verification item stated in §J.5; if so, reported as a construction fact rather than a fitted minimum. |

---

## T. Recommendation

**The 21-cell orthogonal design at n=200 is sufficient**, with the nine mandated corrections integrated. No cell is added or removed, n is unchanged, and no correction below expands scope; five of the nine tighten claims, three harden verification, and one adds a diagnostic that is deterministic and seed-free.

| # | change in this revision | why it matters | confidence |
|---|---|---|---|
| 1 | **Split the structural floor into `population_one_step_pseudotrue_benchmark` ($F_{\text{train}}$) and `intervention_optimal_local_response_benchmark` ($F_{\text{intervention}}$)**, with distinct licensed claims and a three-term decomposition | The previous single construct conflated the one-step estimator target with a model-class bound, licensing "no local model of this class can represent the intervention" from a quantity that cannot support it. The split also creates a genuinely new outcome (C′: objective mismatch rather than representational failure) that would otherwise have been misfiled as structural invalidity. | **High** on the correction; **high** that $F_{\text{intervention}}$ is cleanly definable — the family is two-parameter, $\kappa$ is linear given $a$, and the reduced 1-D problem on a compact interval has a unique minimum *value*; **medium-high** that it will survive the two Build verification items in §J.5, with the pre-committed fallback of omitting it and weakening the claim |
| 2 | **`IDENTIFICATION_REGIME` replaces "data quality"; `BUNDLE(γ)` replaces `DQ(γ)`** | The bundle moves seven factors including cadence and sample size, and because ρ and process-noise scale change, the realized truth changes too. Calling it data quality would have licensed a measurement-quality claim the design cannot support. | **High** |
| 3 | **`rng_mode` and `system_seed_mode` separated; parity extended to `G1R1`/`G2R3`/`G3R3` × 3 seeds** | The two refactors are logically independent and were previously conflated under one flag, so a mixed run was possible and a parity check on only local and network paths would not have covered the placebo construction that Block D depends on. | **High** |
| 4 | **Hypotheses reformulated as direction + mechanism pattern + estimand + interval + SESOI; all "falsified if" rules removed** | The previous phrasing recreated binary gates in a study whose whole protection against threshold gaming is having none. | **High** |
| 5 | **"Hard upper bound" claim removed; n=200 rejustified from Wilson precision, the adversarial bound $\sigma_d\le\sigma_1+\sigma_2$, and compute cost** | The prior claim was mathematically false — CRN reduces paired variance only under positive correlation. The corrected argument reaches the same n from a valid premise, and now reports realized $\sigma_d$ as an output. | **High** |
| 6 | **Three-tier pairing taxonomy; Block C downgraded to shared-base-innovation** | Block C was described as an exact same-truth paired contrast, which it is not. The taxonomy also clarifies that §I's finite-sample identity is available *only* for Tier 1, which is why the σ ladder is Tier 1 by construction. | **High** |
| 7 | **Explicit division-free `gamma=NONE` construction with a dedicated test** | v2's boundary-leakage formula divides by γ; the branch had to be specified rather than assumed, and `B_GNONE` is the reference arm for the entire Q2 profile. | **High** |
| 8 | **`neighbour_flux_share` reframed as a synthetic dimensionless diagnostic; Outcome C's implication corrected** | The prior framing implied a field-checkable criterion. Estimating it in Andhra Pradesh would itself require a calibrated hydrogeological model, so Outcome C implies a prior modeling task, not a data lookup. | **High** |
| 9 | All previously approved elements preserved unchanged: 21 cells; n=200; Blocks A/A′/B/C/D; named-substream CRN; nested σ ladder; full 2×2×2 S8; new v3 seed family; no v2 cells as paired arms; separate v3 code tree; v2 hashes immutable; audit preservation; additive G3 CSV errata; no gates; two-pass checkpoint; no substantive `V3_ANALYSIS` before external review; `NETWORK_SUPPORT_FINAL = NOT_EARNED` under every outcome | — | **High** |

**Highest-risk item for the reviewer's attention, unchanged in kind but now broader in coverage:** the parity check. If the RNG and structural-seed refactors are implemented without step 6 of §P — now nine replicates spanning the local, network, and placebo paths under `(legacy_sequential, legacy_v2)` — and they perturb the physics or the estimator even slightly, v3 will produce clean-looking paired contrasts that are quietly incomparable to everything the project has established. It is cheap, and it should remain a gate on Pass 2 rather than a nice-to-have.

**Second-highest, new in this revision:** the two benchmark quantities carry the most interpretive weight per line of code in the plan, and they are the easiest place to over-claim. `BENCHMARK_DEFINITIONS.md` exists specifically so that the licensed claim for each is fixed in writing, at freeze time, before any value is known.