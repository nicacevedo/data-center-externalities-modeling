# Forest City airflow identification requirements

Status freeze:

- `IT_DELTA_T_DESIGN = IDENTIFIED` (35 °F / 19.44 K, Maguire 2011). This is server inlet to server exhaust design rise.
- `FACILITY_EFFECTIVE_DELTA_T = UNIDENTIFIED`.
- No Forest City WUE is computed. No facility-electricity WUE. No 2012 water magnitude.

The air-stream evaporated water identity is

`V_dot_water = m_dot_da * Δw / ρ_water`

where `Δw` is closed by moist-air states (mixing + adiabatic evaporation) once SAT/RAT and OA/RA fractions are known. The unidentified term for magnitude is `m_dot_da`.

A sensible heat-balance candidate is

`m_dot_da = Q_air / (cp * ΔT_effective)`

`Q_air` is the air-stream sensible load at the chosen boundary (IT only, IT+fan, or another served load). `ΔT_effective` is not automatically the 35 °F IT design rise.

## Measurements that close which equation

| Measurement | Equation / boundary it closes |
| --- | --- |
| TAB measured AHU CFM (supply, return, OA) | Directly identifies `m_dot` (with density/humidity). Does not require ΔT. |
| AHU schedule / design CFM | Upper-bound / design `m_dot` only (`DESIGN_SPEC`, not as-operated). |
| SAT and RAT (as-operated) | Identifies AHU ΔT. Combined with measured CFM closes `Q_air = m cp ΔT_AHU`. Still not IT ΔT. |
| Cold-aisle / hot-aisle temperatures | Identifies as-operated IT ΔT vs the 35 °F design value. |
| BMS airflow or VFD/fan speed with a fan curve | Identifies time-varying `m_dot` if the curve and operating point are documented. |
| Served load boundary (IT kW vs facility kW; which halls) | Closes `Q` in `m = Q/(cp ΔT)`. Without this, even a measured ΔT does not give site water. |
| Fan heat / bypass / recirculation / economizer OA fraction | Distinguishes IT ΔT, AHU ΔT, and facility effective ΔT. Bypass makes 35 °F the wrong `m_dot` ΔT. |
| Makeup / blowdown / drain meters | Maps air-stream `m Δw` onto cooling-system input water (treatment, cycles, non-evaporative uses). |

Until one of {TAB CFM, BMS airflow, explicit effective ΔT at a named load boundary} is identified, Forest City water magnitude remains `UNIDENTIFIED` and quantitative airflow transfer remains `NOT_VALIDATED`.
