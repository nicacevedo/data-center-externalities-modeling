# Prineville vs Lei WUE boundary crosswalk

Do not treat `WUE_PRN1 = 0.22 L/kWh` and `WUE_site_model(AE_AD_ACC, 5B) ≈ 0.024` as the same numerator until this table is read.

## Observed (OCP 2012, PRN1)

Mechanical: 100% outside air + direct ECH misting; **no chillers or cooling towers**. Water path: storage → carbon filter → softener → **RO** → high-pressure mist → ~**85% evaporates**, ~**15% recaptured**; RO **25% reject blown down**. WUE “measures water used for cooling only,” quarterly Q2 2012, after adding water metering.

## Modeled (Lei AE_AD_ACC)

Airside economizer + adiabatic/humidification + **supplemental air-cooled chiller**. No cooling tower in this class. WUE_site_model is humidification/adiabatic intensity from the lineage model. **No RO reject term. No mist-eliminator recycle.**

## Juxtaposition after crosswalk

Even if Facebook’s 0.22 were 100% evaporative (it is not), it would still sit **above** the Lei 5B Large-scale AE_AD_ACC source-scenario 95th (~0.038). RO reject and quarterly-vs-annual grain **cannot fully explain** the gap. LBNL 2024 itself notes hyperscale reported WUE 0.1–0.3 L/kWh for similar AE+adiabatic systems versus lower simulated values.

Therefore the early-epoch check is **not** a license to pick another Lei `k` with higher WUE (e.g. towers). Architecture evidence still says no tower.

Full flow table: `analysis/PRINEVILLE_WUE_BOUNDARY_CROSSWALK.csv`.
