# Final Lei–Masanet reproducibility closure (v2)

Evidence-only. V1 artifacts were not overwritten. Meta 2023–2024 water was not read.
No seed search, range tuning, weather substitution, or upstream-physics edit was used to change the verdict.

## Final disposition: **PARTIAL**

Adapter promotion: **NO / blocked**

Reasons:
- Physical/accounting/climate×technology structure remains useful, but quantitative envelopes are only partially compatible.
- joint empirical tail 0.020
- isolated extreme cells: ['case5_2A']

## A. What Lei–Masanet strongly supports

- Ten public cooling archetypes as intensity models (`P_IT = 1` in all `PUE_WUE_*` functions).
- Climate-hour physics through TMY T/RH/P and economizer/chiller helpers.
- Onsite conditioning-water *use* components (humidification/adiabatic, CT evaporation, windage, draw-off), not source/groundwater.
- Qualitative hot-vs-cold / wet-vs-DX structure on the pre-registered cells, if ordering_ok is true.

## B. What is supported only as a planning/intensity approximation

- Finite-N=50 LHS 5th/95th envelopes as *typical* published-range construction under the frozen public code, not as a unique seed-matched table.
- Homogeneous map `P_fac = P_IT · PUE(w,θ)`, `W_conditioning = P_IT · WUE(w,θ)` if and only if the adapter was promoted.

## C. What remains unsupported

- Exact numerical equality to `UE.xlsx` (original LHS seed/library unavailable).
- Stored `demo.ipynb` PUE 1.33916 as a reproducible snapshot (see notebook disposition).
- Nonlinear IT part-load digital twin; liquid-cooled AI archetypes; groundwater pumping; municipal withdrawal/consumption; Meta 2023–2024 site water.
- Full 10×15 published table (only locked cells were retested).

## Notebook

Disposition: `NON_REPRODUCIBLE_STORED_SNAPSHOT`
This is not by itself a failure of the annual scientific reproduction.

## Joint compatibility

Empirical tail P(D_k ≥ D_published) = 0.02
Per-cell tails: {"case1_1A": 0.56, "case2_8": 0.04, "case5_2A": 0.0, "case7_8": 1.0}

## RNG

- case1_1A: PUE f_RNG=0.0000; WUE f_RNG=0.0000 (project rules: <10% secondary; 10–25% material secondary; >25% problematic).
- case5_2A: PUE f_RNG=0.0000; WUE f_RNG=0.0000 (project rules: <10% secondary; 10–25% material secondary; >25% problematic).
- Case 5×2A same-LHS internal-RNG endpoint SDs: {'PUE_lower_5th': 1.111514806307605e-06, 'PUE_upper_95th': 1.9159432386603546e-06, 'WUE_lower_5th': 0.0, 'WUE_upper_95th': 0.0}

## Replication count

Result files: 160. Planned publication-scale tasks: 160 (50+50+50+10).

## Stopping rule

Stop further Lei–Masanet reproducibility work unless genuinely new upstream evidence appears.

