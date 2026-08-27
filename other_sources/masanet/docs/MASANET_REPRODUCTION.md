# Lei–Masanet reproduction

Status: **PARTIAL**

Upstream commit `2cc53bee89b0a61bdad10c02b4d170d7f673e2dc`. Nested clone is unlicensed; used in place.

## Environment

Python 3.9.23, numpy 1.21.6, sklearn 1.0.2, scipy 1.7.3, CoolProp 6.6.0.
`dc_externalities` lacks CoolProp/sklearn; dedicated env `masanet_lei` was created.

COP pickles were trained on sklearn 0.22.2/0.23.1. They load under 1.0.2. `COP_AC.pkl` lacks `_y_train_std`; our loader sets it to 1 because `normalize_y` is False. Upstream files were not edited.

## Demo

`PUE_WUE_WE_Chiller_Colo` with the notebook vector.

| | PUE | WUE |
| --- | --- | --- |
| notebook (seed unset) | 1.339160993824991 | 2.417390377483526 |
| seed 2025 | 1.4444979364282609 | 2.417390377483134 |
| seed 2025 repeat | 1.4444979364282609 | 2.417390377483134 |
| seed 2026 | 1.4446755394003432 | 2.417390377483134 |
| seed 7 | 1.4445384042130782 | 2.417390377483134 |

Seed reset to 2025 reproduces exactly: `True`.
WUE vs notebook absolute difference `3.921e-13`. PUE differs because `Chiller_system` draws `d_sa` randomly and the notebook did not seed.

## Bundled `Simulation Results/UE.xlsx`

Climate-zone × case × quantile table (PUE 1.074–2.694, WUE 0.002–4.286). Not comparable to a single demo climate snapshot.

## Archetypes on mapped canonical vector

All eight PUE/WUE functions evaluated at seed 2025. See JSON.
