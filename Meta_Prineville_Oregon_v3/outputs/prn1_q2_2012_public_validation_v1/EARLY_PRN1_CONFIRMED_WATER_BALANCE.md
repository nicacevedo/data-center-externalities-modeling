# Early PRN1 confirmed water balance

`RECIRCULATION_TOPOLOGY = PRODUCT_STORAGE_RETURN_CONFIRMED`

OCP and ITherm: unevaporated mist → mist eliminator → micron filter → UV → **RO water storage tanks** (product).

Let `r` be RO recovery (`DISCREPANT_{0.67, 0.75}`), `S` spray, `E` air-stream evaporated water, `R` recapture, `P` new RO product, `F` fresh/raw RO feed.

Source: `E = 0.85 S`, `R = 0.15 S`, `R` returns to product storage.

Steady state: `P + R = S` ⇒ `P = E`.

If the observable is raw RO/fresh input: `F = E / r`.

If the observable is net RO product / ECH makeup: `W_obs = P = E`.

Do **not** use `E/0.85` as makeup. Do **not** use the removed 1.392 RO-feed topology.
