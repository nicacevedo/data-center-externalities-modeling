"""Top-level RNG worker (picklable)."""
from __future__ import annotations


def rng_year_payload(item):
    from run_replication import _one_sample, load_weather

    case, zone, facility, n_hours, internal_seed, facility_id = item
    wx = load_weather(zone)
    T = wx["T_oa"].to_numpy(dtype=float)[:n_hours]
    RH = wx["RH_oa"].to_numpy(dtype=float)[:n_hours]
    P = wx["P_oa"].to_numpy(dtype=float)[:n_hours]
    r = _one_sample(
        {
            "paper_case": case,
            "facility": facility,
            "T": T,
            "RH": RH,
            "P": P,
            "n_hours": n_hours,
            "facility_sample_id": facility_id,
            "internal_seed": internal_seed,
        }
    )
    return {
        "facility_id": facility_id,
        "internal_seed": internal_seed,
        "annual_PUE": r["annual_PUE"],
        "annual_WUE": r["annual_WUE"],
        "water_mean_kg_s": r["water_mean_kg_s"],
    }
