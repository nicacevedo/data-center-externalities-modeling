# ESIF facility-overhead experiment report

CPU `FROZEN_PASS_WITH_DOMAIN_RESTRICTIONS` and H100 `FROZEN_PASS_WITH_DOMAIN_RESTRICTIONS` were not modified.

Source DOI `10.7799/3015212`. Power SHA-256 `19cd1240…`. Weather SHA-256 `97b42499…`.

Clock: `ALIGNED_SAME_CLOCK_NEAREST_CADENCE` (nearest p50 = 12 s; tolerance 60 s frozen from cadence). Timezone UTC vs Denver was not reopened.

PUE component closure: **PASS** (median recon−source = 0; MAE 0.00019 on 4.43M native samples).

Split: DEV 2016-06-12 → 2024-08-29; TEST 2024-08-29 → 2025-08-29; 46 expanding 180/60-day folds on DEV only.

Selected (DEV/CV, TEST unused): cooling F4; HVAC F0; pumps F4; plug/light F2_PHYS; direct aux F2_PHYS (diagnostic).

TEST: pumps reconstruct (hourly WAPE 0.18). HVAC F0 **fails** (mean 134 kW vs 19.5 kW intercept) after a 2024 HVAC level shift (~9 kW through 2023 → ~110–139 kW in 2024–25). Auxiliary component-sum therefore fails. Energy-weighted PUE error is smaller (~0.046) only because overhead is a small share of IT.

Heat reuse: LOW vs the HVAC residual. Models not revised after TEST.

Disposition: `PARTIAL`. Next recommended (not executed): heat rejection → water/WUE.
