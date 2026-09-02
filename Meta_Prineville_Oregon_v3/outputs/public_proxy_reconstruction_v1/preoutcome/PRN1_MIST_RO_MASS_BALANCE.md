# PRN1 mist/RO symbolic mass balance

Steady-state declared for closure only. Early PRN1 (OCP water blog).

```
W_raw_or_RO_feed --> RO --> W_RO_product (0.75)
                     \--> W_RO_reject (0.25) blown down

W_RO_product (+ possibly recapture) --> high-pressure mist
W_spray_circulation --> W_air_vapor (0.85 of spray)
                    \--> W_recaptured (0.15) via mist eliminators to RO tanks
```

Do **not** set `W_external_makeup = W_air_vapor / 0.85`.

0.85 is the sprayed-water evaporated fraction, not thermal effectiveness ε_T and not external-makeup efficiency.

If recapture returns to product tanks (skips RO): `W_makeup ≈ W_air_vapor / 0.75`.

If recapture returns to RO feed: `W_makeup ≈ 1.392 * W_air_vapor`.

Piping topology is PUBLICLY_UNRESOLVED. Both remain in the feasible set for early PRN1 only.
