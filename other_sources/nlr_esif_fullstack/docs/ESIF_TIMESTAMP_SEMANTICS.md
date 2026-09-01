# ESIF timestamp semantics

Catalog field `ts` is timezone-naive. Candidates were frozen **before** inspecting the meter:

- A. America/Denver civil time (predeclared operational interpretation)
- B. UTC
- C. MST (UTC−7, no DST)

Offset/lag was **not** chosen by maximizing correlation with Kestrel jobs.

## External clock anchors

1. **Full ESIF power outage 2025-06-26 through 2025-06-30**, targeted return 2025-07-03 (NLR HPC: “Data Center Outage: 06/26-07/03”, June 25, 2025). Construction required a **full ESIF power outage**; all HPC systems shut down.
2. **Kestrel GPU-integration outage** 2024-01-29 07:00 AM through 2024-02-09 (NLR HPC announcement Jan 12, 2024). Eagle still on the floor, so the IT meter need not go to zero.
3. **Network outage** 2025-07-11 17:00 MT – 2025-07-13 23:59 MT (explicit MT). Systems **remain powered**; IT should not collapse.

## Disposition

**AMBIGUOUS** between America/Denver and UTC at hour-of-day resolution.

Independent of Kestrel correlation: the IT-meter **drops out for ~96.8 hours** after naive `2025-06-26 17:08` and resumes `2025-06-30 17:57`, matching the documented full ESIF power outage (June 26–30) and IT recovery to ~2.6 MW by **2025-07-03**. Adjacent June 21–25 naive dates have a full ~1440 samples/day; June 27–29 have **zero**. The July 11–13 **network** outage (explicit MT, systems remain powered) shows **no** IT collapse (~2680 kW).

That rejects a large clock error. It does **not** uniquely separate Denver civil time from UTC because the outage spans multiple days. Daily ESIF linkage remains usable. Hourly/sub-hourly linkage retains a ±6–7 h timezone caveat. America/Denver stays the operational convention; it was not chosen by maximizing R² vs Kestrel jobs.

