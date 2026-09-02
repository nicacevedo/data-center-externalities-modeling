# Value of information (deterministic; no fake probabilities)

DATA_VALUE_LEADERBOARD (final campus-water range):

1. Cooling architecture of unidentified buildings (PRN5/6, CCO*, later PRN1 CHW path) — campus total is not identifiable until this is resolved.
2. Building load shares λ (only after architecture is known; equal weights forbidden).
3. PRN1 CHW condenser / heat rejection (2023– onward PRN1 water boundary).
4. Water-system subepoch B (mist/RO vs media vs tower) — maps AIR_STREAM_EVAPORATED_WATER to makeup/withdrawal.
5. Airflow / ΔT — public OCP CFM does **not** numerically bound ΔT; 12 K remains GENERIC_PRIOR_SCENARIO. Weather-grid intensity width at 12 K is 0.7201 L/kWh_IT on the synthetic points.
6. Source split (city vs direct POD) — does not narrow campus withdrawal; needed for groundwater.
7. Early-PRN1 RO recapture topology — small (~4%) once vapor is known.

Answers:

1. Building-physics: matched server power at the OCP CFM operating point, or facility BMS airflow / ΔT telemetry.
2. Campus-aggregation: per-building IT load (or even ranked MW) plus architecture class for every active hall.
3. Water-boundary: ECH makeup meter vs RO feed vs withdrawal, and PRN1 condenser type.
4. Single acquisition that most reduces final campus-water range: **per-building cooling architecture + served IT load (or λ) for all PRN/CCO halls**, or equivalently campus-total cooling-water meters with building submeters. Highest-value external dataset: Meta BMS/architecture schedule or City/Meta building-level water and PacifiCorp interval load by account/building — not more public OCP CFM.
