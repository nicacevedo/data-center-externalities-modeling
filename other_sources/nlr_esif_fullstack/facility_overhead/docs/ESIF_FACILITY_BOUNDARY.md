# ESIF facility meter boundary

Official source: NLR HPC Facility PUE Data, DOI `10.7799/3015212`, README in `data_raw/esif_pue/`.

Canonical modeling uses **published source fields unchanged**.

## Power

| Field | Equipment (source wording) |
| --- | --- |
| `it_power_kw` | IT equipment on the data-center floor |
| `cooling_kw` | Outdoor-equipment fans, pipe trace heaters, **and** the dedicated cooling-tower filter pump |
| `hvac_kw` | Fan walls, electrical-room fan coils, make-up air |
| `pump_kw` | Energy-recovery-water loop, tower-water loop, and fan-wall boost pumps. **Does not** include the ~2.67 kW tower filter pump |
| `plug_and_light_kw` | Data-center / dedicated mechanical-room plugs and lights, plus standby-generator crank-case heater |
| `pue` | Source PUE. Not a regression target |
| `energy_reuse` | Source energy-reuse effectiveness. Not a canonical predictor |

## Descriptive physical reclassification (not canonical)

If the documented constant tower-filter pump is accepted:

`pump_physical_kw = pump_kw + 2.67`

`cooling_fans_trace_kw = cooling_kw - 2.67`

These are **not** substitutes for the published fields.

## Architecture context (not transferable coefficients)

Warm-water liquid cooled; chiller-less HPC hall; waste-heat reuse; evaporative cooling towers; thermosyphon hybrid dry heat rejection.

## Weather

README names: `outside_air_temp` (°F), `outside_air_humidity` (% RH).

The weather parquet columns are `outdoor_air_temp` / `outdoor_air_humidity`. Semantics follow the README; names are mapped, values are not altered.

## Out of scope inputs

Reconstructed Kestrel CPU power, H100 CPU+GPU replay, TDP, M100, Meta data.
