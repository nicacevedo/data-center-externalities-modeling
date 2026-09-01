# Water boundary — WUE_site_model / W_conditioning_model

Lei et al. 2025 (eScholarship OA methods) define **WUE-site** as the ratio of a data center’s **total onsite water use** to IT electricity, following The Green Grid. The same paragraph states that simulated WUE-site considers water associated with:

- direct adiabatic cooling;
- humidification;
- cooling-tower **evaporated water**;
- **windage/drift**;
- **draw-off / blowdown** (mineral control).

The 2022 public `Cooling_Tower` implementation matches that sum:

`WUE = (evap + windage + drain-off [+ humidification]) * 3600 / Power_IT`.

The paper text sometimes says “consumption” while **including blowdown**, which is typically **discharged**, not evaporated. This module therefore uses:

| Term | Meaning |
| --- | --- |
| `WUE_site_model` | Lei/Masanet onsite conditioning-water **use intensity** (L/kWh_IT) |
| `W_conditioning_model` | `E_IT × WUE_site_model` |

These are **not**:

- municipal withdrawal;
- ISO consumption (withdrawal − discharge);
- RO reject (unless a tower draw-off term is doing similar work in a tower class);
- sewer/return;
- groundwater pumping.

## Component fate

| Component | Withdrawal/input | Consumptive evaporative loss | Potentially discharged | Unresolved fate |
| --- | --- | --- | --- | --- |
| Tower evaporation | part of makeup | YES | no | — |
| Windage/drift | part of makeup | maybe locally deposited | maybe | YES |
| Tower draw-off | part of makeup | no | YES typically | destination unknown |
| Adiabatic / humidification | part of makeup | often yes if exhausted | maybe drain | source unnamed |
| Air-only DX/ACC classes | humidification-like term only | as humidification | no tower blowdown | — |

Facebook/Meta **operator WUE** is defined in Meta indexes as **withdrawal / IT kWh**, and in the 2012 OCP PRN1 note as **cooling water only** (not offices). That is a different meter story than Lei’s modeled intensity. See `docs/PRINEVILLE_WUE_BOUNDARY_CROSSWALK.md`.
