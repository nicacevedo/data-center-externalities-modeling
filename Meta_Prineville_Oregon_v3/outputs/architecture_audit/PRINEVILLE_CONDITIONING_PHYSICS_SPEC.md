# Prineville conditioning physics (structure only; not fitted)

## Early direct-air architecture (PRN1 2011; OCP v1.0)

`outside air → optional return-air mixing → ECH mist (cool and/or humidify) → mist eliminators → fan wall → data hall`

Unfitted mass balance:

`W_airside ≈ m_da × Δω` with `Δω = max(w_supply − w_mixed, 0)`

`w_mixed` depends on outdoor humidity ratio and return-air fraction. The current gray-box uses outdoor air only (`w_outdoor`), so winter mixing is named but not applied.

Water is consumed **in the air stream** (direct evaporative / humidification). There is **no** 2011 cooling-tower heat-rejection loop. Dry/economizer operation exists whenever outdoor air already meets SAT/RH without spray.

Predicted physical boundary: `CONDITIONING_SITE_WATER` (mist + RO/softener feed).  
Outside that boundary: City vs POD withdrawal split, sewer/return, Meta annual disclosed withdrawal, irrigation, construction water.

## CCO (2020–2022)

ECH piping in a CCO data hall is **SUPPORTED**. Full penthouse identity is **UNKNOWN**. IWS/IWR implies some facility water loop whose technology is unnamed.

## PRN1 addition (2024-02)

Chilled-water / CRAH / chiller is **CONFIRMED** at PRN1. Heat-rejection device (tower vs dry cooler vs air-cooled) is **UNKNOWN**. Do not add open-tower water physics from the word “chiller”.

Do not fit these equations in this pass.
