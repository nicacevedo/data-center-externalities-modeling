# Forest City v2 final report

Isolated package. Frozen v1 and Prineville were not modified. MODEL_CALIBRATED = NO.

## 1. What was frozen from v1/Prineville?

Forest City v1 public-validation status is preserved: MODEL_CALIBRATED = NO; facility-effective DeltaT UNIDENTIFIED; IT design DeltaT 35 F is a design specification; dashboard SCREENSHOT_ONLY; 2012-06-25 mixing PASS; 2012-07-01 evaporative PASS; summer DX-required hours = 0 on valid KFQD hours; Prineville→Forest City qualitative/structural physics transfer SUPPORTABLE; water magnitude UNIDENTIFIED. Acquisition priority is unchanged (air-side/TAB first, then cooling-water meter, then interval electricity, then emissions, then source-water externality). Upstream hashes for Forest City controller/structural/contracts, Prineville structural/psychrometrics/gray-box/architecture YAML, CPU, H100, and ESIF were checked before and after this pass.

## 2. What new sources were found?

Targeted primary pages: Town of Forest City wastewater-treatment description (WWTP NC0025984; five unnamed Significant Industrial Users) and NC DEQ NPDES notice for that **town** plant discharging to the Second Broad River. These improve the water-boundary graph by documenting a municipal discharge node; they do **not** identify a Meta cooling-water meter. A Rutherford EDC construction-era page was attempted as campus chronology context. Hsu/Mulay remains a design-slide reference (DX existence) and was not promoted to TAB. Secondary journalism citing 4.2 million gallons (16 ML) and an unverified 30 MW was noted and **not** used quantitatively. No other data-center site was acquired.

## 3. What architecture epochs are independently identified?

Hard documentary epochs: FRC1 construction (2010-11 to opening); FRC1 operating architecture from 2012-04-19 (direct OA evaporative + DX backup); second large production hall present by the 2014 tour; FRC4 cold storage ~2014 (different function). Membrane vs misters, SPLC/indirect at Forest City, and a post-2014 additional hall remain CANDIDATE / UNRESOLVED. Epoch dates were **not** inferred from Meta annual water or electricity.

## 4. Which Forest City control/physics evidence validates the frozen Prineville framework?

**VALIDATED:** 2012-06-25 mixing family and DX-not-required; 2012-07-01 evaporative family and DX-not-required; JJA DX-required hours = 0 on observed KFQD hours. **SUPPORTED:** shared psychrometrics, enthalpy-conserving mixing, and adiabatic evaporative mass/energy balance under Forest City's local 85 F / 90% RH envelope (not copied Prineville A–H thresholds). This is physics/controller transfer.

## 5. Which transfer claims fail?

No STRUCTURAL_FAIL on the documented 2012 events. Claims that **fail if asserted**: screenshot dashboard as numeric ground truth; municipal industrial-class flow as Meta campus water; 2024 campus electricity as 2012 FRC1 load; treating campus withdrawal as cooling WUE. Seasonal PUE 1.07 remains **UNIDENTIFIED** for quantitative reconstruction (no interval electricity). Absolute site water magnitude is **not** validated.

## 6. What is identified about normalized air-side evaporative demand?

Humidity-ratio lift `dw` is **ENGINEERING_BOUNDED** from frozen controller + psychrometrics on valid hours. On 1253 valid JJA hours, mean `dw` when spray is on is about 0.00104 kg/kg; DX-required hours remain 0 across effectiveness 0.70 / 0.85 / 1.00. Mean `dw` is insensitive across that predeclared band on these hours (the 85 F supply target, not thermal effectiveness, binds). Cubic-meter intensity per MW_IT using the 35 F IT design rise as if it were facility-effective DeltaT is **SCENARIO_BOUNDED** only (JJA mean about 0.020 m3/h per MW_IT; p95 about 0.189). FACILITY_EFFECTIVE_DELTA_T remains UNIDENTIFIED. No optimizer; annual Meta series did not enter parameter selection.

## 7. Is absolute cooling-water magnitude identified?

**UNIDENTIFIED.** Airflow / effective DeltaT missing; cooling-water meter missing.

## 8. Is the cooling-water → campus-withdrawal edge identified?

**UNIDENTIFIED.** Meta EDI is site withdrawal. Town industrial class is not Meta. NPDES is the town WWTP.

## 9. What can sparse annual Meta electricity/water records legitimately validate?

Descriptive campus-level electricity and withdrawal totals and a **SITE_WITHDRAWAL_INTENSITY** (not WUE). They can serve as external consistency checks only. They cannot validate 2012 FRC1 load, cooling evaporation, or controller parameters.

## 10. Is a stationary 2012 architecture compatible with later observations?

**UNIDENTIFIED.** Campus composition hard-changes in 2014, but cooling-technology change dates are unresolved, and annuals are the wrong boundary. Do not assume yes. Do not reject or accept H0 by fitting water.

## 11. What remains unresolved?

As-operated CFM/SAT/RAT/TAB; facility-effective DeltaT; cooling-water meter and WUE numerator; RO vs UV vs makeup split; blowdown; FRC1 interval electricity; year-matched emissions-factor compatibility; membrane/SPLC dates; post-2014 hall identity; June 1–20 2012 weather.

## 12. Highest-value next dataset

As-operated FRC1 air-side measurements / mechanical / TAB / commissioning (CFM, SAT/RAT, airflow balance, sequence of operations, evaporative and DX). That remains priority 1.

## 13. Does Forest City strengthen Prineville external validity, and at which layers?

**Yes, at weather → psychrometrics → controller → air-side regime layers** for a hot/humid climate, with local envelope (85 F / 90% RH, DX backup unused in documented summer). **No** at absolute cooling-water magnitude, campus withdrawal, WUE, 2012 FRC1 electricity, or source-water externality.

Claim classes used: VALIDATED, SUPPORTED, ENGINEERING_BOUNDED, SCENARIO_BOUNDED, UNIDENTIFIED, FAILED.
