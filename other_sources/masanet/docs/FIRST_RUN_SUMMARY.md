# First-run summary

Overall: **PARTIAL**

This run did not inspect Meta Prineville 2023–2024 water outcomes.

## 1. What did we successfully reproduce?

Public `nuoaleon/Data-Center-Water-footprint` commit `2cc53bee89b0a61bdad10c02b4d170d7f673e2dc` runs in env `masanet_lei` (Python 3.9, sklearn 1.0.2, CoolProp 6.6.0). All three COP pickles predict after a documented load-time shim for `COP_AC.pkl`. Seed 2025 is bit-stable. Notebook WUE for the demo vector matches to ~1e-12; notebook PUE does not, because `demo.ipynb` did not seed `np.random`. Bundled `UE.xlsx` is climate-zone × case × quantile annual output, not the demo snapshot. Reproduction status: **PARTIAL**.

## 2. What does the Lei–Masanet model actually measure?

An **IT-normalized intensity model**: `Power_IT = 1` in every archetype. Paper: PUE = total facility electricity / IT electricity; WUE = **total onsite water use** / IT electricity (L/kWh), citing The Green Grid (Patterson 2011). Eq. (1) on-site water = cooling-tower evaporation + windage + draw-off + adiabatic cooling + space humidification. Eight cooling archetypes; COP from GP regressions on wet-bulb/load or outdoor T.

## 3. What water quantities are usable for groundwater coupling?

| Quantity | Status |
| --- | --- |
| W_use/model (WUE intensity) | Identified: onsite use, makeup-like (includes blowdown) |
| W_cons | NOT_IDENTIFIED as a separate output; evaporation is the consumptive CT term |
| W_discharge/return | Draw-off is a candidate discharge term **included in WUE** |
| W_source/withdrawal | NOT_IDENTIFIED; **WUE is not groundwater pumping** |

Paper: does not address indirect (grid) water; future work should consider qualities and local stress. Do not map WUE to source wells.

## 4. Is IT-load scaling modeled or only normalized?

Only normalized. `Chiller_load` is an exogenous GP feature, not computed from IT power. Instrumented tests at relative IT = 0.5/1/2: PUE and WUE should be invariant if components scale linearly. Status: **PASS**.

## 5. How material is upstream stochasticity?

Two layers: (code) `np.random.uniform` indoor humidity in colo/chiller/DX helpers, sometimes called >1× per evaluation so states can be internally inconsistent; (paper) Latin-hypercube facility-parameter uncertainty for annual ranges — not used in this first grid. Demo WUE was seed-invariant; PUE moved with seed. Status: **PASS**. Not fixed in this run.

## 6. Climate/technology patterns

Small T×RH factorial, facility parameters held at the demo/LHS vector. Joint PUE–WUE only. LBNL 2024: **QUALITATIVE_TRIANGULATION_ONLY** (annual/stock vs instantaneous; shared Lei lineage). Grid status: **PASS**.

## 7. What does Frontier independently validate?

Physical structure at a liquid-cooled HPC facility, **not** Lei–Masanet coefficients. Thermal: Q = ρ cp V̇ (T_return − T_supply) with ρ=1060, cp=3.5 kJ/kg-K, overall supply T for all loops. PUE reconstructed from compute vs total. Reduced accessory-power models F0/F1/F2 with expanding monthly folds; F2 is a contemporaneous oracle using measured Q.

- QC: PASS
- Thermal: PARTIAL
- PUE: PASS
- Reduced: PASS

## 8. What remains unsupported?

Part-load vs IT; liquid-cooling generic archetype; source-water/groundwater identity; annual weather-weighted WUE; independent statistical validation vs LBNL; nonlinear facility response; Prineville holdout (intentionally untouched).

## 9. Highest-value next experiment

Annual EnergyPlus-weather evaluation of the eight archetypes at Table 3 ranges, keeping water components separate, before any Prineville coupling or groundwater mapping.
