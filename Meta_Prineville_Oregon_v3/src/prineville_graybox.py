"""Small, explicitly provisional Prineville gray-box model.

This is intentionally a scaffold, not a claimed digital twin. It provides the accounting
and air-side physics interfaces required once monthly/hourly validation data are acquired.
It never fabricates an 'observed' hourly IT load.

API / versioning (structural-reference-v1 pass):

* `simulate()` defaults to the **canonical/legacy** frozen pre-structural model.
  Downstream reconstruction must not silently pick up the uncalibrated candidate.
* `simulate_legacy()` is the same canonical model (explicit alias).
* `simulate_structural_reference_v0()` is the uncalibrated v0 structural path
  (isothermal-by-default humidification) retained for synthetic comparison only.
* `simulate_structural_reference_v1()` is the corrected adiabatic candidate.
  calibration_status=NOT_CALIBRATED, validation_status=PHYSICS_ONLY.

Do not promote v1 to production without a separate identification/validation pass.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd

try:
    import psychrolib
    psychrolib.SetUnitSystem(psychrolib.SI)
except Exception:
    psychrolib=None

@dataclass
class Params:
    supply_target_C: float = 25.0
    return_air_C: float = 35.0
    evap_effectiveness: float = 0.85
    server_deltaT_C: float = 12.0
    dry_air_cp_J_kgK: float = 1006.0
    fan_fraction_of_it: float = 0.025
    other_facility_fraction_of_it: float = 0.035
    # These two fractions sum to 0.06, leaving room for a ~1.07 mild-weather PUE
    # after evaporative auxiliaries. They are provisional/scenario electrical
    # proxies, not architecture-audit-validated and not refit in the structural pass.
    # supply_target_C is retained for simulate_legacy only; the structural controller
    # uses documented OCP DESIGN_SPEC thresholds instead of this single 25 C rule.
    evap_aux_fraction_of_it: float = 0.005
    airflow_method: str = "sensible_heat_balance"


def _sat_vapor_pressure_pa(t_c):
    """Buck-style saturation vapor pressure approximation over liquid water."""
    if not np.isfinite(t_c): return np.nan
    return 611.21*np.exp((18.678 - t_c/234.5)*(t_c/(257.14+t_c)))


def _hum_ratio(t_c,rh_pct,p_pa):
    if not np.isfinite(t_c) or not np.isfinite(rh_pct) or not np.isfinite(p_pa):
        return np.nan
    if psychrolib is not None:
        return psychrolib.GetHumRatioFromRelHum(float(t_c),float(np.clip(rh_pct,0,100))/100,float(p_pa))
    pv=(np.clip(rh_pct,0,100)/100.0)*_sat_vapor_pressure_pa(t_c)
    pv=min(float(pv),0.99*float(p_pa))
    return 0.621945*pv/(float(p_pa)-pv)


def _moist_air_enthalpy_j_per_kg_da(t_c, w):
    # ASHRAE-form psychrometric approximation in SI.
    return 1006.0*t_c + w*(2501000.0 + 1860.0*t_c)


def _hum_ratio_from_enthalpy_t(h_j_per_kg_da, t_c):
    return (h_j_per_kg_da - 1006.0*t_c)/(2501000.0 + 1860.0*t_c)


REQUIRED_WEATHER_DRIVERS = ("t_db_C", "t_wb_C", "rh_pct", "pressure_Pa")
REQUIRED_PHYSICAL_OUTPUTS = (
    "p_it_mw",
    "p_fan_mw",
    "p_other_mw",
    "p_evap_aux_mw",
    "p_fac_mw",
    "t_supply_C",
    "evap_water_m3_per_h",
)


def assert_finite_weather(weather: pd.DataFrame, year=None) -> None:
    """Fail loudly if any required physical driver is non-finite. Does not impute."""
    n = len(weather)
    loc = f" year={int(year)}" if year is not None else ""
    for col in REQUIRED_WEATHER_DRIVERS:
        if col not in weather.columns:
            raise ValueError(f"Missing required weather driver {col}{loc}.")
        x = pd.to_numeric(weather[col], errors="coerce").to_numpy(dtype=float)
        n_bad = int((~np.isfinite(x)).sum())
        if n_bad:
            raise ValueError(
                f"Non-finite required weather driver {col}{loc}: {n_bad}/{n} rows. "
                "Gray-box does not impute missing weather or treat it as zero."
            )


def assert_finite_physical_outputs(out: pd.DataFrame, year=None) -> None:
    """Fail loudly if required physical outputs are non-finite before aggregation."""
    n = len(out)
    loc = f" year={int(year)}" if year is not None else ""
    for col in REQUIRED_PHYSICAL_OUTPUTS:
        x = pd.to_numeric(out[col], errors="coerce").to_numpy(dtype=float)
        n_bad = int((~np.isfinite(x)).sum())
        if n_bad:
            raise ValueError(
                f"Non-finite physical output {col}{loc}: {n_bad}/{n} rows. "
                "Annual aggregation will not skip missing values."
            )
    pit = pd.to_numeric(out["p_it_mw"], errors="coerce").to_numpy(dtype=float)
    pue = pd.to_numeric(out["pue"], errors="coerce").to_numpy(dtype=float)
    need = pit > 0
    n_bad_pue = int((need & ~np.isfinite(pue)).sum())
    if n_bad_pue:
        raise ValueError(
            f"Non-finite PUE where IT power > 0{loc}: {n_bad_pue} rows."
        )


def simulate_legacy(weather: pd.DataFrame, p_it_mw, params=Params()):
    """Pre-revision controller: 100% OA, water only if t_supply < t_db.

    Retained for synthetic structural comparison. Not a Meta-water calibration path.
    """
    w=weather.copy()
    pit=np.broadcast_to(np.asarray(p_it_mw,float),len(w)).copy() if np.ndim(p_it_mw)==0 else np.asarray(p_it_mw,float)
    if len(pit)!=len(w): raise ValueError('p_it_mw length must equal weather length.')
    if np.any(pit<0): raise ValueError('IT power must be nonnegative.')
    assert_finite_weather(w)
    tdb=w['t_db_C'].to_numpy(float); twb=w['t_wb_C'].to_numpy(float)
    rh=w['rh_pct'].to_numpy(float); p=w['pressure_Pa'].to_numpy(float)

    # Airflow needed to carry IT sensible heat at the chosen server-air delta-T.
    m_air = pit*1e6/(params.dry_air_cp_J_kgK*params.server_deltaT_C)
    # Full evaporative outlet temperature; actual controller uses no spray if outdoor <= target,
    # partial spray if target is reachable, else full evaporative effectiveness.
    t_full = tdb - params.evap_effectiveness*np.maximum(tdb-twb,0)
    t_supply=np.where(tdb<=params.supply_target_C,tdb,
                      np.where(t_full<=params.supply_target_C,params.supply_target_C,t_full))

    # Approximate adiabatic humidification water from constant-moist-air enthalpy.
    water_kg_s=np.zeros(len(w),float)
    for i in range(len(w)):
        wo=_hum_ratio(tdb[i],rh[i],p[i])
        if t_supply[i] >= tdb[i]-1e-9:
            ws=wo
        else:
            if psychrolib is not None:
                h=psychrolib.GetMoistAirEnthalpy(float(tdb[i]),float(wo))
                ws=psychrolib.GetHumRatioFromEnthalpyAndTDryBulb(float(h),float(t_supply[i]))
            else:
                h=_moist_air_enthalpy_j_per_kg_da(float(tdb[i]),float(wo))
                ws=_hum_ratio_from_enthalpy_t(float(h),float(t_supply[i]))
            ws=max(ws,wo)
        water_kg_s[i]=m_air[i]*max(ws-wo,0)

    p_fan=params.fan_fraction_of_it*pit
    p_other=params.other_facility_fraction_of_it*pit
    # Small evaporative auxiliary proxy proportional to spray activation; to be calibrated.
    spray=np.clip((tdb-t_supply)/np.maximum(tdb-twb,1e-6),0,1)
    p_evap_aux=0.005*pit*spray
    p_fac=pit+p_fan+p_other+p_evap_aux
    out=pd.DataFrame({
        'timestamp_utc':w['timestamp_utc'], 'p_it_mw':pit, 'p_fan_mw':p_fan,
        'p_other_mw':p_other, 'p_evap_aux_mw':p_evap_aux, 'p_fac_mw':p_fac,
        'pue':np.divide(p_fac,pit,out=np.full_like(p_fac,np.nan),where=pit>0),
        't_supply_C':t_supply, 'evap_water_m3_per_h':water_kg_s*3.6,
        'cooling_mode':np.where(tdb<=params.supply_target_C,'outside_air_or_winter_mix',
                         np.where(t_full<=params.supply_target_C,'partial_evap','full_evap')),
        'provenance':'scenario/fitted IT power + physics-derived facility outputs'
    })
    assert_finite_physical_outputs(out)
    out = out.copy()
    out["model_version"] = "canonical_legacy"
    out["calibration_status"] = "NOT_REOPENED_THIS_PASS"
    out["validation_status"] = "PRODUCTION_CANONICAL_UNCHANGED"
    return out


def simulate_canonical(weather: pd.DataFrame, p_it_mw, params=Params()):
    """Canonical frozen gray-box (pre-structural 25 C / 100% OA rule)."""
    return simulate_legacy(weather, p_it_mw, params)


def simulate_structural_reference_v0(weather: pd.DataFrame, p_it_mw, params=Params()):
    """Uncalibrated structural-reference-v0 (synthetic comparison only)."""
    from prineville_structural import StructuralParams, simulate_building

    sp = StructuralParams(
        return_air_C=params.return_air_C,
        evap_effectiveness=params.evap_effectiveness,
        server_deltaT_C=params.server_deltaT_C,
        dry_air_cp_J_kgK=params.dry_air_cp_J_kgK,
        fan_fraction_of_it=params.fan_fraction_of_it,
        other_facility_fraction_of_it=params.other_facility_fraction_of_it,
        evap_aux_fraction_of_it=getattr(params, "evap_aux_fraction_of_it", 0.005),
        airflow_method=getattr(params, "airflow_method", "sensible_heat_balance"),
    )
    out = simulate_building(weather, p_it_mw, sp)
    out = out.copy()
    out["model_version"] = "structural_reference_v0"
    out["calibration_status"] = "NOT_CALIBRATED"
    out["validation_status"] = "STRUCTURAL_BEHAVIOR_ONLY"
    return out


def simulate_structural_reference_v1(weather: pd.DataFrame, p_it_mw, params=Params(), **kwargs):
    """Corrected adiabatic structural candidate. Not the default simulate() path."""
    from prineville_structural_v1 import (
        StructuralV1Params,
        simulate_structural_reference_v1 as _v1,
    )

    sp = StructuralV1Params(
        evap_thermal_effectiveness=getattr(params, "evap_thermal_effectiveness", params.evap_effectiveness),
        server_deltaT_C=params.server_deltaT_C,
        dry_air_cp_J_kgK=params.dry_air_cp_J_kgK,
        fan_fraction_of_it=params.fan_fraction_of_it,
        other_facility_fraction_of_it=params.other_facility_fraction_of_it,
        evap_aux_fraction_of_it=getattr(params, "evap_aux_fraction_of_it", 0.005),
        airflow_method=getattr(params, "airflow_method", "sensible_heat_balance"),
    )
    return _v1(weather, p_it_mw, sp, **kwargs)


def simulate(weather: pd.DataFrame, p_it_mw, params=Params(), *, model_version: str = "canonical"):
    """Dispatch. Default is the canonical/legacy frozen model, not structural-reference-v1.

    model_version:
      canonical | legacy | canonical_legacy — frozen pre-structural gray-box
      structural_reference_v0 | v0 — uncalibrated v0 structural path
      structural_reference_v1 | v1 — requires explicit kwargs (return_air); not a silent default
    """
    mv = (model_version or "canonical").lower()
    if mv in ("canonical", "legacy", "canonical_legacy", "canonical_legacy_v0_pre_structural"):
        return simulate_canonical(weather, p_it_mw, params)
    if mv in ("structural_reference_v0", "v0"):
        return simulate_structural_reference_v0(weather, p_it_mw, params)
    if mv in ("structural_reference_v1", "v1"):
        raise TypeError(
            "simulate(..., model_version='structural_reference_v1') is not a silent default. "
            "Call simulate_structural_reference_v1(..., return_air=ReturnAirSpec(...)) explicitly. "
            "v1 is NOT_CALIBRATED / PHYSICS_ONLY and must not replace canonical production results."
        )
    raise ValueError(
        f"Unknown model_version={model_version!r}. "
        "Use canonical (default), structural_reference_v0, or simulate_structural_reference_v1()."
    )
