# 2024 ESIF HVAC regime audit (post-hoc, non-fitting)

This audit interprets the already-frozen TEST failure of the stationary HVAC F0 model. It does **not** select a new specification, fit an epoch intercept, or revise TEST metrics.

Protocol: `manifests/HVAC_REGIME_AUDIT_PROTOCOL.json`.

## 1. When does the persistent 2024 HVAC level shift begin?

Descriptive 28-day before/after scan of daily HVAC (coverage ≥80% on both sides; persistency = the following 28 days remain high) locates the **maximum HVAC level difference** at **2024-03-29**:

| Window | Candidate | HVAC before (kW) | HVAC after (kW) | Δ HVAC | Δ AUX | Δ PUE |
| --- | --- | --- | --- | --- | --- | --- |
| 14 d | 2024-03-31 | 46 | 194 | +148 | +136 | +0.117 |
| **28 d** | **2024-03-29** | **15** | **184** | **+169** | **+150** | **+0.106** |
| 56 d | 2024-03-28 | 14 | 186 | +172 | +155 | +0.071 |

Day-level series (not used as a model breakpoint):

- through **2024-03-27**: HVAC ≈ **12 kW** while IT ≈ **3.6 MW**;
- **2024-03-28**: 8 valid hours, HVAC mean **107 kW** (partial/transitional day);
- **2024-03-29** onward: HVAC ≈ **200 kW**, IT still ≈ **3.6 MW**.

The HVAC step is therefore a **late-March 2024 level change**, not a smooth weather response and not an IT-load response.

## 2. Component reallocation?

At the 28-day candidate:

- HVAC **+169 kW**
- pumps **−19 kW**
- cooling **+1 kW**
- plug/light **−0.4 kW**
- auxiliary sum **+150 kW**

A within-list category reclassification would require another published component to fall by a comparable amount while AUX stayed flat. That does **not** occur. `METER_CATEGORY_RECLASSIFICATION_SUPPORTED` is **not** justified.

## 3. Total-boundary / PUE

AUX rises with HVAC. Source PUE rises by about **0.11** in the 28-day window. Calendar-year means: HVAC 10 kW (2023) vs 139 kW (2024); AUX 71 vs 193 kW; PUE 1.040 vs 1.083. Pure within-category reclassification is **disfavored**.

## 4. Meter artifacts

Native HVAC (±21 days around 2024-03-29; 53,779 rows):

- continuously sampled (median dt 60 s);
- no negatives/zeros;
- 29,643 distinct values — not a newly quantized integer channel;
- 7-day post/pre HVAC ratio ≈ 12, **not** an exact ×2/×5/×10 scale change;
- 7-day IT mean unchanged at **3642 kW** on both sides of the step;
- longest gap (~3.8 d) is a **mid-April** coverage hole **after** the step.

Public README / NLR PUE page / OSTI 3015212 currently use the **same** `hvac_kw` wording. Catalog power resource is version 3. There is **no public changelog** showing a 2024 HVAC semantic redefinition. An unpublished meter-boundary change **cannot be ruled out** (`METER_BOUNDARY_CHANGE_POSSIBLE` remains a residual possibility, not the primary disposition).

## 5. Documented 2024 events (compatibility, not causality)

| Event | Timing vs HVAC step |
| --- | --- |
| Kestrel CPU install / FY2024 opening | 2023; HVAC still ~10 kW through 2023 and through 2024-03-27 |
| GPU integration outage 2024-01-29–02-09; GPU arrival February | **weeks before** the HVAC step; HVAC remained ~12 kW through 27 March |
| 5 MW → 7.5 MW electrical **and** cooling-capacity work (NLR 2024-06-11) | 2024 campaign; **temporally compatible** with a late-March plant/control change; exact device **not named** |
| Eagle decommission 2024-06-15 | **after** the HVAC step; HVAC remains ~165–200 kW afterward |
| Kestrel GPU production / full-buildout messaging Aug 2024 | months after the HVAC step; TEST starts 2024-08-29 |

Original ESIF design already included **fan-wall AHUs** (NREL fact sheet OSTI 1050124). Do **not** infer `2024 HVAC jump = new fan walls`.

GPU node counts disagree across public documents (NREL news/DCD: **132** 4×H100 nodes; current NLR Kestrel configuration page: **156** GPU-accelerated nodes). The discrepancy is preserved.

## 6. Conservative disposition

`HVAC_REGIME_CAUSE = PHYSICAL_OR_OPERATIONAL_INFRASTRUCTURE_CHANGE_SUPPORTED_EXACT_CAUSE_UNRESOLVED`

Confidence:

- HVAC level shift exists: **HIGH**
- stationary IT+weather fails across the shift: **HIGH**
- broader 2024 facility electrical/mechanical regime change is compatible: **MEDIUM/HIGH**
- exact device/event: **LOW**

Not claimed: GPU-caused HVAC; Eagle-caused HVAC; new-fan-wall HVAC.

No epoch HVAC model was fitted. The untouched TEST remains the production result.
