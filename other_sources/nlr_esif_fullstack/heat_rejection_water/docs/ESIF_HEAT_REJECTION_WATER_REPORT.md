# ESIF heat-rejection → conditioning-water / WUE — closed report

CPU, H100, IT-power, and facility-overhead layers were not modified. No Prineville/Meta water was used. No HVAC/`cooling_kw` electrical series was treated as thermal heat. No time-series water model was fitted.

Canonical status: `analysis/FINAL_ESIF_HEAT_WATER_STATUS.json`.

Disposition: **`STRUCTURAL_ACCOUNTING_VALIDATION`**. That is a successful endpoint.

## Provenance

| Source | ID / DOI | Hash (SHA-256 prefix) |
| --- | --- | --- |
| Sickinger et al. NREL/TP-2C00-72196 | `10.2172/1471661` | `c850d6b4…` |
| Carter et al. NREL/CP-2C00-66690 | `10.2172/1343488` | `d99942a6…` |
| NLR WUE page | nlr.gov/computational-science/reducing-water-usage | `6b76075c…` |
| ESIF PUE/weather | `10.7799/3015212` | power `19cd1240…` weather `97b42499…` |

OSTI PDFs have **zero** embedded supplemental files. No official water spreadsheet or hourly water dump was found. A GitHub 1-min ESIF heat-flow repo was identified and **not acquired** (not a water-meter package).

## Evidence classes (do not mix)

- **DIRECT:** mean IT 888 kW; IT energy 7,776 MWh; facility energy 8,037,500 kWh; entering TSC water 28.9 °C; outside Tdb series.
- **MEASUREMENT_DERIVED:** WUE 0.70 L/kWh; PUE 1.034; ERE 0.929; COC 12.8; heat shares 10.5 / 42.5 / 47%.
- **MODELED_COUNTERFACTUAL:** WUE 1.27 (reuse+tower); 1.42 (tower-only); 4,400 m³ / 7,950 m³ TSC “savings”; Carter pre-install 8,300→3,700 m³ projection.
- **DOCUMENTED_CONTROL_RULE:** 9.4 °C / 49 °F aggressive-TSC example. **Not** estimated from water outcomes.
- **FIGURE_DIGITIZED:** Fig. 4 monthly bars **not digitized**.

## Boundaries

Thermal: reuse then TSC then tower. Water: `W_ESIF_reported_cooling` = Meter 1 + Meter 2 + estimated sand-filter blowdown. MAU humidification **unmetered and excluded**. Not groundwater, not WUESOURCE.

## First-year reproduction — PASS (source accounting / arithmetic consistency)

Period 2016-09-01 through 2017-08-31. This is **source-accounting reproduction / independent arithmetic consistency**, not an independently re-observed annual meter total.

| Quantity | Source | Independent arithmetic |
| --- | --- | --- |
| Mean IT | 888 kW | — |
| IT energy | 7,776 MWh | 888×8760 h = 7,778.88 MWh (−2.88 MWh, 0.037%) |
| PUE | 1.034 | 8,037,500/7,776,000 = 1.0336 |
| WUE | 0.70 L/kWh | identity |
| Implied water | not printed | 0.70×7,776,000 L = **5,443.2 m³** |
| CF reuse+tower water | 1.27 | **9,875.5 m³** |
| CF tower-only water | 1.42 | **11,041.9 m³** |
| TSC savings | 4,400 m³ / 1.16 Mgal | 9,875.5−5,443.2 = **4,432.3 m³**; 4,400 m³ = 1.162 Mgal |
| 24-month savings | 7,950 m³ / 2.10 Mgal | gal conversion PASS; m³ not independently reconstructable without year-2 water |

4,432 vs 4,400 m³ is two-decimal WUE rounding (tolerance 50 m³). Counterfactuals remain counterfactuals.

## Temporal eligibility

**`STRUCTURAL_ACCOUNTING_ONLY`.** Manual meters; no public hourly/daily/monthly numeric water table. High-resolution weather does not create hourly water. Fig. 4 not digitized.

## Heat-rejection mechanism

Source: Nov–Apr TSC rejected the most heat. Independent ESIF weather, first TSC year: Nov–Apr mean Tdb **6.5 °C** vs May–Oct **19.2 °C**. Fraction of hours Tdb < 9.4 °C = **0.335** vs Carter’s modeled “≈50% of the year.” Weather supports a real cold season; it does **not** independently measure `Q_TSC(t)`. Classification: descriptive/structural. **PARTIAL.**

## Water / WUE technology deltas (engineering counterfactuals)

- `delta_reuse` = 0.15 L/kWh ≈ 1,166 m³ (tower-only → reuse+tower).
- `delta_TSC` = 0.57 L/kWh ≈ 4,432 m³ (reuse+tower → reuse+TSC+tower).

Never a measured randomized treatment effect.

## Model eligibility

A fitted time-series water model is **not justified**. Annual identity `W = WUE × E_IT` is already the source. No honest OOT water validation sample exists. Structural validation is the correct scientific endpoint (`NO_FITTED_MODEL_REQUIRED`).

## Lei/Masanet (after freeze)

Preregistered closest: `LIQ_DRY_AD`, climate **5B**, Large-scale, direct-to-chip. Architecture match **PARTIAL**. Contrast: `WE_WCC` 5B Large (evaporative-tower water).

Lei LIQ_DRY_AD 5B WUE p05–p95 ≈ 0.14–0.26; WE_WCC 5B ≈ 1.87–2.55. ESIF observed 0.70 sits between dry-liquid and open-tower Lei water, as expected for a **hybrid**. Direction consistent; magnitudes not transferable. ESIF evidence is **independent** of the Lei modeled lineage; architecture mismatch prevents coefficient validation (`PARTIAL_INDEPENDENT_EXTERNAL_STRUCTURAL_VALIDATION`).

## Project implications

Generic `Q_IT → (Q_reuse, Q_dry, Q_evap) → W(Q_evap, weather, water state)` is supported. Universal WUE×IT is only a coarse baseline. Prineville gray-box should be **reviewed** for missing dry vs evaporative **heat-rejection** structure — not refit here.

## Remaining uncertainty

Manual meter precision unpublished; MAU excluded; heat shares annual only; Carter 3,700 m³ projection ≠ observed implied 5,443 m³; 24-month savings not fully reconstructable; 2024 HVAC electrical failure is out of this window.

Next project-wide experiment (not executed): **generic architecture `A_t` / dry-vs-evap routing in the project model**, or **Prineville structural review without coefficient transfer** — not more ESIF electrical refits.
