# ESIF heat and water accounting boundary

Electrical cooling/HVAC power is **not** rejected thermal power. `hvac_kw` and `cooling_kw` from DOI `10.7799/3015212` are forbidden as heat-rejection or WUE predictors in this experiment.

## Thermal routing (documented)

```
Q_IT  →  Q_reuse  →  remaining  →  Q_TSC (dry)  →  remaining  →  Q_tower (evaporative)
```

Conceptually `Q_IT ≈ Q_reuse + Q_TSC + Q_tower`, subject to storage, measurement uncertainty, and unmeasured terms. Equality is **not** forced.

First full year (2016-09-01 through 2017-08-31), Sickinger Fig. 4 pie / §2.2 — evidence class **MEASUREMENT_DERIVED**:

| Branch | Share |
| --- | --- |
| Building heat reuse | 10.5% |
| Thermosyphon dry rejection | 42.5% |
| Evaporative cooling towers | 47.0% |

## Water boundary

Canonical quantity: **`W_ESIF_reported_cooling`**.

Primary project tag: **`CONDITIONING_SITE_WATER`**.

Do **not** classify the entire Meter 1 + Meter 2 + estimated-filter total narrowly as `TOWER_MAKEUP`.

Sickinger §3.2.1:

- City water → softeners; regeneration to sewer through **Meter 2** (`RETURN_FLOW`).
- Softened water mixed with city water → sumps.
- Side-stream sand filter flushed with city water to sewer a few times per month (**estimated** blowdown; `BLOWDOWN`).
- Sumps → cooling towers: evaporation (`CONSUMPTION`, not separately published), return to sumps, or blowdown to sewer.
- **Total reported water = Meter 1 + Meter 2 + estimated sand-filter blowdown** (`CONDITIONING_SITE_WATER`).
- Meter 1 is the majority **tower-makeup path**, a subcomponent, not the whole reported total.
- **Meter 3** → cycles of concentration (TDS ratio). First-year COC = **12.8**.
- Manual readings by two entities. Digital meters recommended, not used for the paper.

**Explicitly unmetered / excluded:** makeup-air-unit (MAU) humidification water.

This is **not** automatically:

- total facility water;
- withdrawal source split (beyond “city water”);
- groundwater;
- hydrologic consumption vs return (regen/blowdown go to sewer; evaporation is consumptive);
- `WUESOURCE` (power-plant water via EWIF).

Project tags that apply:

- `CONDITIONING_SITE_WATER` (primary)
- `TOWER_MAKEUP` (Meter 1 majority path only; not the entire reported total)
- `EVAPORATION` / `BLOWDOWN` (occur; not separately published as time series)
- `MUNICIPAL_SUPPLY` (city water)
- `RETURN_FLOW` (softener regen + blowdown to sewer)
- **Do not** tag as `GROUNDWATER_WITHDRAWAL` or `CONSUMPTION` without extra assumptions.

WUE reported (0.70 L/kWh) is Green Grid **site** WUE using `W_ESIF_reported_cooling / E_IT`, **excluding MAU**, so it is narrower than a complete humidification-inclusive Green Grid WUE.
