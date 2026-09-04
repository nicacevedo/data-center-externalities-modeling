# Advisor glossary refresh audit

Status: **PASS**  
Mode: reporting-only; no scientific model fit, search, tuning, or promotion  
Branch / HEAD / origin-main: `main` / `08b0c112d8883eb4d23bb05d0d40e1a42c863593` / `08b0c112d8883eb4d23bb05d0d40e1a42c863593`

## Canonical registry and coverage state

- 50 Prineville source products, 82 quantities, and 26 methods/models; all three regenerated registries are byte-identical to the canonical outputs.
- Meta annual withdrawal: 11 reported annual values, 2014--2024.
- City WATER-COMM + ADD'L WATER service: 163 observed meter months, 2012-12 through 2026-07; 2012, 2015, and 2026 are partial years. This is an observed customer-service component, not total monthly Meta/campus withdrawal.
- Canonical weather: 122,736 unique local hours, 2011--2024, with KS39 -> KRDM -> bias-adjusted KBDN hierarchy and all required drivers finite.
- OWRD pumping: 1,751 rows across 14 accepted reporting groups, 2009-10 through 2025-09. GWIS: 812 rows, 800 numeric BLS, 796 state-model-eligible. Pumping-to-groundwater response remains NOT IDENTIFIED.
- EIA-930 PACW: 83,320 rows (2015-07 through 2024-12); FERC historical backcast: 70,120 rows (2011-01 through 2019-01). These are regional, not campus, boundaries.
- Registry discrepancy retained explicitly: all-source monthly campus withdrawal is a coverage/reporting concept but not a distinct row in the current 82-row quantity registry; `Q_W_WITH` is annual.

## Frozen City-service validation

- Identical common support: n=120 months across ten complete years within 2014--2024; incomplete 2015 excluded.
- Seasonal persistence: MAE 7,473.1 m3; RMSE 11,164.8 m3.
- Gray-box evaporation candidate: MAE 11,728.1 m3.
- Gray-box normalized seasonal-shape correlation: r=0.751; observed JJA share range 0.365--0.544, gray-box 0.751--0.939.
- Conclusion reproduced: the strongest simple baseline has lower error; the gray-box retains seasonal-shape signal but overconcentrates water in summer.

## Water-boundary and external-status controls

- Service + bulk is reported only as `diagnostic only -- not an identified campus mass balance`.
- WELL METER FOR SEW vs OWRD direct POD identity remains unresolved; no proximity/name/correlation-based source or master/submeter inference is made.
- Frozen status synthesis: M100 CLOSED/FROZEN; Frontier CLOSED; Lei--Masanet PARTIAL/CLOSED with adapter blocked; ESIF PARTIAL/CLOSED; Forest City qualitative PARTIAL and quantitative NOT VALIDATED; modern AI IT-power exact disposition `FROZEN_BOUNDED_WITH_EXPLICIT_NODE_UNCERTAINTY`.
- Critical path is site-water/source accounting -> groundwater forcing -> groundwater response -> M0-vs-M1 decision replay.

## Document and integrity checks

- Focused canonical tests: 39 passed.
- LaTeX compiled twice; 40-page PDF; no fatal error, undefined control sequence, unresolved cross-reference, or overfull box >=8 pt.
- Stale active wording audit: PASS. Historical wording remains only in blue-struck `oldtxt` spans.
- Frozen annual ground-truth, protected annual-water holdout, and GWIS candidate-well figures are hash-identical before/after.
- `main_documents/master.tex` is untouched. The pre-existing dirty submodule is preserved.
