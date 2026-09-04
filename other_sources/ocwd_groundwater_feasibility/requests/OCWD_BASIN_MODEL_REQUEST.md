# Draft separate request: OCWD calibrated Basin Model package

**Status: DRAFT — DO NOT SUBMIT without requester review.**  
**Priority: SECONDARY to the observational WRMS request.**

To: Orange County Water District, Public Records Coordinator  
Subject: Releasable OCWD Basin Model / MODFLOW reference package and documentation

Please provide, if releasable, the calibrated OCWD Basin Model/MODFLOW package and enough documentation to reproduce its historical simulation setup. Requested materials include:

- complete model input package and MODFLOW/version information;
- model grid, spatial reference, discretization, active domain, and layer geometry;
- authoritative aquifer-to-model-layer definitions and cross-sections;
- hydraulic conductivity, vertical leakance, storage coefficient/specific yield, and other property arrays/zones;
- boundary-condition types, locations, values, and time series;
- stress periods and time-step definitions;
- pumping, surface-recharge, injection, river, and other stress inputs with source provenance;
- starting heads and representative historical simulated-head and budget outputs;
- calibration observations, observation IDs/locations/layers, weights, targets, residuals, and summary statistics;
- preprocessing/postprocessing scripts or documented workflows and required data dictionaries;
- documented model versions, updates, known limitations, and scenario-specific changes.

If the complete current package cannot be released, please provide the model version and inputs used for the documented **November 1990-November 1999 transient calibration**, together with representative outputs and calibration-observation files.

This package would be used only as a physics/reference benchmark (`REFERENCE_MODEL`). Simulated heads and water budgets will not be treated as empirical ground truth. The observational WRMS records requested separately are the higher scientific priority.

