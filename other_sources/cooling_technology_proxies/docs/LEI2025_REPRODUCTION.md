# Lei et al. 2025 source reproduction

## What was reproduced

Public repository:

`https://github.com/nuoaleon/The-Water-Use-of-Data-Center-Workloads-A-Review-and-Assessment-of-Key-Determinants`

Frozen commit: `155b0216f4bfc20679310360e9966a65951712d0`

User-provided `sources/lei2025/UEs_16cases.csv` is **byte-identical** to `upstream/data/UEs_16cases.csv` (SHA-256 `4924fdb451dfefc433b4de375322dadbbf5fb056876c12e5cc1a913d5cf4c031`). Same for `SPEC_2024.xlsx` and `SI Supporting Code.Rmd`.

### `UEs_16cases.csv`

| Check | Result |
| --- | --- |
| Rows | 19,000 |
| Columns | PUE, WUE, Case, Climate Zone, Cooling system (Original), Cooling system, Data center size, type, Case (Original) |
| Missing / duplicates | 0 / 0 |
| PUE range | 1.020–3.288; **no PUE < 1** |
| WUE range | 0–4.637 L/kWh; **no WUE < 0**; 256 exact zeros |
| Cases | integers 0–11 and 15–18 (16 values). **12–14 absent** |
| Subcases | 15_1/15_2/15_3 and 16_1/16_2/16_3 |
| Climate zones | 19 including **0A/0B** (not in 2022 15-zone `UE.xlsx`) |
| Group size | subcase × climate = **50** everywhere; Case 15/16 × climate = **150** (3×50) |
| Facility size | Large-scale 9500, Midsize 6650, Small 2850 |

Classification: **SAME_LEI_MASANET_LINEAGE**. Temporal grain: **annual scenario**, not hourly.

`SPEC_2024.xlsx` is 330×6 (Year, Workload, Performance, Power, ssj_ops, Server quantile). It is a **server power/performance** table, not a cooling (PUE, WUE) pair file.

`SI Supporting Code 2 (WaterSensitivity).ipynb` is a **Sobol/SALib analysis on L/ssj_ops**, not the physical hourly cooling simulator.

### Quantiles PUE_5 / PUE_95 / WUE_5 / WUE_95

SI `Supporting Code.Rmd` (chunk after Fig. 3):

```r
filter(Case != 12 & Case != 13 & Case != 14 & Case != 17 & Case != 18) %>%
group_by(Case, Climate.Zone, Cooling.system, Data.center.size, type) %>%
summarize(PUE_5th = quantile(PUE, 0.05), PUE_95th = quantile(PUE, 0.95),
          WUE_5th = quantile(WUE, 0.05), WUE_95th = quantile(WUE, 0.95))
```

R default `quantile` is **type 7**, equivalent to `numpy.quantile(..., interpolation="linear")`.

This pass recomputes those four statistics on the full CSV and on the Rmd-filtered subset (drops 17–18). Outputs:

- `analysis/lei2025_reproduction.csv` (304 groups; Cases 15–16 have n=150)
- `analysis/lei2025_reproduction_rmd_filtered.csv` (266 groups)

**Status: PASS** for estimator-on-source-CSV.

## What was not reproduced / discrepancies (not hidden)

1. **No published machine-readable 5th/95th table** is bundled in the GitHub repo. We cannot numeric-match a typeset SI table; we reproduce the **Rmd estimator**.
2. Filename `UEs_16cases` vs 16 integer Case values with a gap at 12–14.
3. Rmd **drops Cases 17–18** (dry cooler air-cooled IT) from that figure pipeline. Those 1,900 rows remain in the proxy dataset and are labeled.
4. The **hourly physical simulator that generated the 19,000 annual rows is not in this repo.** Liquid cases therefore remain annual proxies. The 2022 air-IT hourly code lives under `other_sources/masanet/` and was **not rerun**.
5. User PDF of the 2025 paper is treated as a **user-provided version**. Journal article is *Resources, Conservation & Recycling* 219 (2025) 108310. eScholarship OA: `qt1vx545q7`. Versions were **not silently substituted**.
6. Cases 15–16 **pool** rear-door, cold-plate, and immersion (paper SI Fig. S6.3). Public CSV cannot unpool them.

## Independence diagnostic

Paired vs independent-marginal resampling within cooling × climate × size (304 cells, 2000 draws, seed 20260901):

- Median Pearson ≈ 0.14 (global); **water-cooled chiller median Pearson ≈ 0.38**
- Median |relative bias| of E[PUE×WUE] ≈ 0.4%
- 17/304 cells have >10% independent draws farther than paired NN p95

**Policy: PAIRED SAMPLING REQUIRED** because the source emits joints. Weak global correlation does not authorize independent sampling.

## Lineage

Lei 2025 SI data, Lei–Masanet 2022 public code, and LBNL 2024 §4 cooling model share authors and physics lineage. Agreement among them is **not independent validation**.
