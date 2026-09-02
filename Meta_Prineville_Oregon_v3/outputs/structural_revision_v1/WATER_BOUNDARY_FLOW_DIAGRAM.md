# Early-PRN1 water-boundary flow (structural-reference-v1)

Do not invert unobserved arrows. Do not label air-stream evaporated water as withdrawal.

```
outdoor + return mixed air
        |
        v
  ECH high-pressure atomization  (spray ON or BYPASS)
        |
        +--> AIR_STREAM_EVAPORATED_WATER  = m_da * max(w_supply - w_entering, 0)
        |         [COMPUTED in v1; tag AIR_STREAM_EVAPORATED_WATER]
        |
        +--> unevaporated mist to eliminators
                  |
                  v
            ECH_SPRAY_CIRCULATION     UNIDENTIFIED
                  |
                  v
            recapture / sump recycle  UNIDENTIFIED  (not automatically makeup)
                  |
                  v
            treatment (softener/RO)   UNIDENTIFIED  (RO reject ≠ mist recapture)
                  |
                  v
            ECH_EXTERNAL_MAKEUP       UNIDENTIFIED
                  |
                  v
            CONDITIONING_SYSTEM_INPUT_WATER   UNIDENTIFIED
                  |
                  v
            G_site accounting map     SEPARATE_ACCOUNTING_LAYER
                  |
                  v
            WITHDRAWAL / MUNICIPAL_SUPPLY / DIRECT_POD_WITHDRAWAL
```

`EVAP_THERMAL_EFFECTIVENESS` (ε_T) is a temperature-approach prior.
It is **not** a one-pass sprayed-water evaporation fraction.
Do **not** compute `external_makeup = air_vapor / 0.85`.
One-pass spray evaporation, if later sourced, is a different quantity from loop makeup
because recaptured water can recirculate.
