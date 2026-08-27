#!/usr/bin/env python3
"""Phase 3: energy/water/stochastic/scaling audit. Does not modify nested upstream source."""
from __future__ import annotations

import ast
import csv
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from common import (
    ARCHETYPE_META,
    ARCHETYPE_PARAMS,
    CANONICAL_SEED,
    EXTRA_SEEDS,
    POWER_LABELS,
    UPSTREAM,
    WATER_LABELS,
    WORK_ROOT,
    atomic_write_json,
    atomic_write_text,
    load_upstream,
    set_threads,
    utcnow,
    vector_for,
)
from instrument_upstream import load_instrumented


def _finite(x) -> bool:
    arr = np.asarray(x, dtype=float)
    return bool(np.all(np.isfinite(arr)))


def cooling_tower_identity(mod, x_climate=None):
    T, RH, P = 25.0, 50.0, 101325.0
    AT_CT, Power_IT, Q, dT, wind, CC, LG = 3.36, 1.0, 1.2, 5.1, 0.00294, 11.17, 0.272
    wue, m_air, lg, evap, windage, drain = mod.Cooling_Tower(
        T, RH, P, AT_CT, Power_IT, Q, dT, wind, CC, LG
    )
    recon = (evap + windage + drain) * 3600 / Power_IT
    return {
        "WUE": float(wue),
        "evap_kg_s": float(evap),
        "windage_kg_s": float(windage),
        "drainoff_kg_s": float(drain),
        "reconstructed_WUE": float(recon),
        "abs_err": float(abs(wue - recon)),
        "closes": bool(abs(wue - recon) <= 1e-10),
        "nonneg": bool(evap >= -1e-15 and windage >= -1e-15 and drain >= -1e-15),
        "units_interpretation": (
            "Q in kW / latent heat (kJ/kg) => kg/s; *3600/Power_IT => kg/kWh = L/kWh at rho=1000."
        ),
    }


def count_random_in_function(src: str, fn_name: str) -> dict:
    tree = ast.parse(src)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == fn_name)
    n_rand = 0
    for n in ast.walk(node):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Attribute):
            pass
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if isinstance(n.func.value, ast.Attribute) and getattr(n.func.value, "attr", None) == "random":
                n_rand += 1
            if isinstance(n.func.value, ast.Name) and n.func.value.id == "random":
                n_rand += 1
    # fallback: source slice
    start, end = node.lineno, node.end_lineno
    lines = src.splitlines()[start - 1 : end]
    n_rand_src = sum(1 for ln in lines if "np.random" in ln and not ln.strip().startswith("#"))
    return {"ast_random_calls_in_fn_body": n_rand, "source_np_random_active_lines": n_rand_src}


def water_audit_rows():
    """Traceable classifications only. Do not map WUE to groundwater."""
    rows = []

    def add(**kw):
        rows.append(kw)

    common = dict(
        units="kg/s internally; WUE constructed as sum(kg/s)*3600/Power_IT → L/kWh at 1 kg/L",
        withdrawal_interpretation="NOT automatically groundwater. Closest reading is facility makeup/source water if WUE follows ASHRAE/The Green Grid site WUE, but the code never names a source.",
        consumption_interpretation="NOT_IDENTIFIED as a named output. Evaporation is the only term that is unambiguously consumptive in the hydrologic sense.",
        return_discharge_interpretation="Drain-off/blowdown is a candidate discharge/return term, not automatically consumptive.",
    )
    for arch, fn in [
        ("hyperscale_AE_adiabatic_water_chiller", "PUE_WUE_AE_Chiller"),
        ("hyperscale_WE_water_chiller", "PUE_WUE_Chiller_Watereconomier"),
        ("colo_AE_water_chiller", "PUE_WUE_AE_Chiller_Colo"),
        ("colo_WE_water_chiller", "PUE_WUE_WE_Chiller_Colo"),
        ("colo_water_chiller", "PUE_WUE_Chiller"),
    ]:
        add(
            archetype=arch,
            upstream_function="Cooling_Tower",
            upstream_variable="Water_CT_evaporated",
            equation_source_line="Water_CT_evaporated = Q/Latent_heat_vaporization(T_CT)",
            physical_meaning="Cooling-tower evaporative loss",
            included_in_upstream_WUE="yes",
            our_candidate_boundary="W_cons (evaporative) and also part of W_use/model",
            confidence="high",
            notes="Q is the heat argument passed by the parent function; for some WE archetypes that argument is Q_IT-side rather than condenser rejection. See audit JSON.",
            **common,
        )
        add(
            archetype=arch,
            upstream_function="Cooling_Tower",
            upstream_variable="Water_CT_windage",
            equation_source_line="Water_CT_windage = m_CT * Windage_p",
            physical_meaning="Drift/windage as a fraction of circulating tower water",
            included_in_upstream_WUE="yes",
            our_candidate_boundary="W_use/model; hydrologic fate NOT_IDENTIFIED (may deposit locally or leave site)",
            confidence="medium",
            notes="Physical water leaving the tower; do not over-claim aquifer vs drift deposition.",
            **common,
        )
        add(
            archetype=arch,
            upstream_function="Cooling_Tower",
            upstream_variable="Water_CT_DF",
            equation_source_line="Water_CT_DF = max(Water_CT_evaporated/(CC-1) - Water_CT_windage, 0)",
            physical_meaning="Drain-off / blowdown to hold cycles of concentration",
            included_in_upstream_WUE="yes",
            our_candidate_boundary="W_discharge/return candidate; included in W_use/model; NOT automatically W_cons",
            confidence="high",
            notes="Standard makeup identity makeup ≈ evap + drift + blowdown. Blowdown is typically wastewater/discharge.",
            **common,
        )
        add(
            archetype=arch,
            upstream_function=fn,
            upstream_variable="hd_amount (and hd_amount_ae where present)",
            equation_source_line="hd_amount = max(Q_heat_latent/2266, 0) and/or AE humidification m_cd_dry*delta_d",
            physical_meaning="Humidification / adiabatic water added to air",
            included_in_upstream_WUE="yes",
            our_candidate_boundary="W_use/model; consumption if evaporated to room air that is exhausted; source NOT_IDENTIFIED",
            confidence="medium",
            notes="w_eff is hard-coded to 1. AE_Chiller also uses Air_side_economizer outputs with a suspicious HD_use = d_sa indexing (tuple slot 1 is humidity, not a 0/1 flag).",
            **common,
        )
        add(
            archetype=arch,
            upstream_function=fn,
            upstream_variable="WUE",
            equation_source_line="WUE = sum(Water_comp)*3600/Power_IT",
            physical_meaning="IT-normalized sum of humidification + tower evap + windage + drain-off",
            included_in_upstream_WUE="yes (is the metric)",
            our_candidate_boundary="W_use/model intensity. W_source/withdrawal = NOT_IDENTIFIED. W_cons = NOT_IDENTIFIED as a separate output.",
            confidence="high",
            notes="Do not map WUE to groundwater pumping. 2022 preprint Eq (1) includes draw-off in on-site use; code matches.",
            **common,
        )
    for arch, fn in [
        ("dx_air_cooled", "PUE_WUE_DX"),
        ("air_cooled_chiller", "PUE_WUE_AIRChiller"),
        ("AE_air_cooled_chiller", "PUE_WUE_AE_AIRChiller"),
    ]:
        add(
            archetype=arch,
            upstream_function=fn,
            upstream_variable="hd_amount",
            equation_source_line="hd_amount = max(Q_heat_latent/2266, 0); WUE = hd_amount*3600/Power_IT",
            units="same L/kWh construction; no cooling tower",
            physical_meaning="Only humidification-like term; no evap/drift/blowdown",
            included_in_upstream_WUE="yes (entire WUE)",
            our_candidate_boundary="W_use/model humidification only",
            withdrawal_interpretation="NOT_IDENTIFIED",
            consumption_interpretation="NOT_IDENTIFIED as a named output",
            return_discharge_interpretation="NOT_IDENTIFIED (no drain-off term)",
            confidence="high",
            notes="Air-cooled archetypes have no Cooling_Tower water. DX sets Power_hd = Q_heat_latent/1 (kW), a reheat/steam-style energy term, not a pump.",
        )
    add(
        archetype="all_implemented",
        upstream_function="(none)",
        upstream_variable="W_source/withdrawal",
        equation_source_line="not present",
        units="NOT_IDENTIFIED",
        physical_meaning="Source water / groundwater / municipal withdrawal",
        included_in_upstream_WUE="not named",
        our_candidate_boundary="NOT_IDENTIFIED",
        withdrawal_interpretation="NOT_IDENTIFIED",
        consumption_interpretation="NOT_IDENTIFIED",
        return_discharge_interpretation="NOT_IDENTIFIED",
        confidence="high",
        notes="No well, basin, or utility-water object exists in the implementation.",
    )
    return rows


def main():
    set_threads()
    mod, cop_notes = load_upstream()
    src = (UPSTREAM / "simulation_funs_DC.py").read_text()
    tree = ast.parse(src)
    pue_fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("PUE_WUE_")]

    energy = {"Power_IT_hardcoded_1": True, "archetypes": {}}
    for node in pue_fns:
        assigns = [
            ast.unparse(n)
            for n in ast.walk(node)
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "Power_IT" for t in n.targets)
        ]
        energy["archetypes"][node.name] = {
            "Power_IT_assign": assigns,
            "is_one": all("= 1" in a.replace(" ", "") or "=1" in a.replace(" ", "") for a in assigns),
        }
        if not energy["archetypes"][node.name]["is_one"]:
            energy["Power_IT_hardcoded_1"] = False

    # Instrumented accounting closure
    inst = load_instrumented(1.0)
    accounting = {}
    for name in ARCHETYPE_PARAMS:
        fn = getattr(inst, name)
        x = vector_for(name)
        np.random.seed(CANONICAL_SEED)
        try:
            pue, wue = fn(x)
            last = dict(inst._LAST)
            pc = np.asarray(last.get("Power_comp", []), dtype=float)
            wc = np.asarray(last.get("Water_comp", []), dtype=float)
            pit = float(last.get("Power_IT", 1.0))
            pue_from_comp = float(pc.sum() / pit) if pc.size else None
            wue_from_comp = float(wc.sum() * 3600 / pit) if wc.size else None
            accounting[name] = {
                "ok": True,
                "PUE": float(pue),
                "WUE": float(wue),
                "Power_IT": pit,
                "Power_comp": pc.tolist(),
                "power_labels": POWER_LABELS[name],
                "Water_comp_kg_s": wc.tolist(),
                "water_labels": WATER_LABELS[name],
                "PUE_from_components": pue_from_comp,
                "WUE_from_components": wue_from_comp,
                "energy_closes": bool(pue_from_comp is not None and abs(pue_from_comp - pue) <= 1e-10),
                "water_closes": bool(wue_from_comp is not None and abs(wue_from_comp - wue) <= 1e-8),
                "PUE_ge_1": bool(pue >= 1),
                "water_nonneg": bool(wc.size == 0 or np.all(wc >= -1e-12)),
                "finite": bool(np.isfinite(pue) and np.isfinite(wue) and _finite(pc) and _finite(wc)),
                "mode_flags": {k: last.get(k) for k in ("AE_use", "WE_use", "HD_use", "COP_chiller", "Q") if k in last},
            }
        except Exception as e:
            accounting[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    ct = cooling_tower_identity(mod)

    # Stochastic
    random_lines = []
    for i, ln in enumerate(src.splitlines(), 1):
        if "np.random" in ln:
            random_lines.append({"line": i, "text": ln.rstrip(), "commented": ln.strip().startswith("#")})
    stoch = {"np_random_lines": random_lines, "per_archetype": {}}
    for name, meta in ARCHETYPE_META.items():
        helpers = meta["stochastic_helpers"]
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        calls = Counter()
        for n in ast.walk(node):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
                calls[n.func.id] += 1
        x = vector_for(name)
        fn = getattr(mod, name)
        seeded = {}
        for s in (CANONICAL_SEED,) + EXTRA_SEEDS:
            np.random.seed(s)
            pue, wue = fn(x)
            seeded[str(s)] = [float(pue), float(wue)]
        pues = [v[0] for v in seeded.values()]
        wues = [v[1] for v in seeded.values()]
        stoch["per_archetype"][name] = {
            "stochastic_helpers": helpers,
            "helper_calls_in_one_eval": {h: calls.get(h, 0) for h in helpers + ["Cooling_Tower", "Air_side_economizer", "Air_side_economizer_colo", "Chiller_system", "Chiller_system_DX"]},
            "repeated_helper_risk": {h: calls.get(h, 0) > 1 for h in helpers},
            "seeded_PUE_WUE": seeded,
            "PUE_range": [min(pues), max(pues)],
            "WUE_range": [min(wues), max(wues)],
            "PUE_seed_spread": float(max(pues) - min(pues)),
            "WUE_seed_spread": float(max(wues) - min(wues)),
        }

    # Scaling diagnostic (instrumented copy only)
    scaling = {"relative_IT_loads": [0.5, 1.0, 2.0], "archetypes": {}}
    for name in ARCHETYPE_PARAMS:
        rows = []
        x = vector_for(name)
        for load in (0.5, 1.0, 2.0):
            inst = load_instrumented(load)
            fn = getattr(inst, name)
            np.random.seed(CANONICAL_SEED)
            pue, wue = fn(x)
            last = dict(inst._LAST)
            pc = np.asarray(last.get("Power_comp", []), dtype=float)
            wc = np.asarray(last.get("Water_comp", []), dtype=float)
            rows.append(
                {
                    "IT_load": load,
                    "PUE": float(pue),
                    "WUE": float(wue),
                    "Power_IT": float(last.get("Power_IT", load)),
                    "sum_Power_comp": float(pc.sum()) if pc.size else None,
                    "sum_Water_comp_kg_s": float(wc.sum()) if wc.size else None,
                    "Power_comp": pc.tolist(),
                    "Water_comp": wc.tolist(),
                }
            )
        pues = [r["PUE"] for r in rows]
        wues = [r["WUE"] for r in rows]
        waters = [r["sum_Water_comp_kg_s"] for r in rows]
        powers = [r["sum_Power_comp"] for r in rows]
        # Linear intensity: PUE,WUE invariant; component sums scale with IT load
        scaling["archetypes"][name] = {
            "rows": rows,
            "PUE_invariant": bool(np.nanmax(pues) - np.nanmin(pues) < 1e-8),
            "WUE_invariant": bool(np.nanmax(wues) - np.nanmin(wues) < 1e-8),
            "power_sum_ratio_2_over_1": None
            if not powers[1]
            else float(powers[2] / powers[1]),
            "water_sum_ratio_2_over_1": None
            if not waters[1]
            else float(waters[2] / waters[1]),
            "interpretation": (
                "Intensity model: Chiller_load is an exogenous GP input, not computed from Power_IT. "
                "If PUE/WUE stay invariant and component sums double when IT doubles, there is no genuine part-load nonlinearity vs IT power."
            ),
        }

    rows = water_audit_rows()
    csv_path = WORK_ROOT / "docs" / "WATER_BOUNDARY_AUDIT.csv"
    fields = [
        "archetype",
        "upstream_function",
        "upstream_variable",
        "equation_source_line",
        "units",
        "physical_meaning",
        "included_in_upstream_WUE",
        "our_candidate_boundary",
        "withdrawal_interpretation",
        "consumption_interpretation",
        "return_discharge_interpretation",
        "confidence",
        "notes",
    ]
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})

    energy_ok = energy["Power_IT_hardcoded_1"] and all(
        v.get("energy_closes") for v in accounting.values() if v.get("ok")
    )
    water_ok = ct["closes"] and all(v.get("water_closes") for v in accounting.values() if v.get("ok"))
    all_ok = all(v.get("ok") for v in accounting.values())
    if all_ok and energy_ok and water_ok:
        status = "PASS"
        gate = "PROCEED"
    elif all_ok:
        status = "PARTIAL"
        gate = "PROCEED"
    else:
        status = "FAIL"
        gate = "STOP"

    out = {
        "status": status,
        "hard_gate": gate,
        "timestamp_utc": utcnow(),
        "cop_compat_notes": cop_notes,
        "energy_boundary": energy,
        "accounting": accounting,
        "cooling_tower_identity": ct,
        "stochasticity": stoch,
        "scaling": scaling,
        "water_quantities": {
            "W_use_model": "Upstream WUE * Power_IT / 3600  (sum of humidification + CT terms where present)",
            "W_cons": "NOT_IDENTIFIED as a separate output; evaporation is the only clearly consumptive CT term",
            "W_discharge_return": "CT drain-off is a candidate; hydrologic destination NOT_IDENTIFIED",
            "W_source_withdrawal": "NOT_IDENTIFIED (WUE is not groundwater pumping)",
        },
        "quirks_reported_not_fixed": [
            "WE/colo functions call Cooling_Tower with Q (IT+UPS+PD+lighting) rather than condenser heat CT_heat_removed for water and CT fan.",
            "PUE functions call Air_side_economizer or Chiller_system multiple times; stochastic helpers can draw inconsistent d_sa within one evaluation.",
            "AE_Chiller sets HD_use from Air_side_economizer tuple index 1 (d_sa), not a humidification flag.",
            "DX Power_hd = Q_heat_latent/1 is an energy term, not a humidification pump.",
        ],
        "paper_pdf": (
            "2022 Research Square preprint used for Eq (1) and WUE=onsite use/IT (Patterson 2011). "
            "Elsevier typeset PDF not in folder. Table 3 (not Table B.1) holds facility ranges. "
            "2025 Lei/Shehabi review uses consumption/use interchangeably for WUE-site; 2022 Eq (1)+code include draw-off, so we do not reclassify WUE as consumption-only."
        ),
    }
    atomic_write_json(WORK_ROOT / "results" / "masanet_boundary_audit.json", out)
    print(json.dumps({"status": status, "hard_gate": gate}, indent=2))
    if gate != "PROCEED":
        sys.exit(2)


if __name__ == "__main__":
    main()
