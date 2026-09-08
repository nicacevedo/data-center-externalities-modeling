# AP E0 access-request gap audit

Audit of
[AP_PLANNING_DATA_ACCESS_REQUEST.md](../requests/AP_PLANNING_DATA_ACCESS_REQUEST.md)
(V1 draft) against frozen E0 requirements in
[EMPIRICAL_GW_QUALIFICATION_PLAN.md](../../../EMPIRICAL_GW_QUALIFICATION_PLAN.md)
and [AP_E0_EVIDENCE_MATRIX.csv](AP_E0_EVIDENCE_MATRIX.csv).

V1 must **not** be submitted. The revised request is
[AP_PLANNING_DATA_ACCESS_REQUEST_V2.md](../requests/AP_PLANNING_DATA_ACCESS_REQUEST_V2.md).
This audit does not send any request.

---

## Summary

V1 already asks for most Track I identity items and for monthly extraction and
recharge. It is too broad for an E0 freeze: agriculture, municipal, candidates,
power, and exact PSCC recovery are bundled as if they were E0 MUST-HAVEs. It
is also incomplete on Track III hydrogeology (the coupling decision) and on
pumping-audit metadata (missing vs zero, reconciliation, proxy class). It
hard-codes “monthly or finer” as the scientific threshold; E0 now uses monthly
as the **target** and subannual adequacy as the **minimum**.

| Verdict | Count |
|---|---|
| V1 already covers (keep, possibly rephrase) | 12 |
| Missing from V1 (add to V2 MUST HAVE) | 11 |
| In V1 but E0 NICE TO HAVE / not an E0 gate (move) | 6 |
| In V1 and should be dropped or narrowed | 2 |

---

## Missing from V1 — add to V2 MUST HAVE

### 1. NAQUIM machine-readable GIS

- **Why:** E0.5 strong-evidence support; aquifer identity; coupling.
- **Preferred format:** GeoPackage/shapefile/file geodatabase with data dictionary.
- **Minimum usable:** district/study-area aquifer polygons with layer attributes.
- **Time span:** current NAQUIM vintage for AP.
- **Spatial identifier:** aquifer/layer ID joinable to wells.
- **Units:** CRS declared; depths in metres.
- **Metadata:** product vintage, scale (1:50k/1:10k), lineage.
- **Unlocks:** E0.5.

### 2. Aquifer boundaries and structural barriers

- **Why:** MATERIAL vs WEAKLY_SUPPORTED; proximity is insufficient alone.
- **Preferred format:** GIS with barrier/fault/compartment attributes.
- **Minimum usable:** maps or GIS for candidate districts with citations.
- **Time span:** current mapping vintage.
- **Spatial identifier:** aquifer ID; structure ID.
- **Units:** metres; CRS.
- **Metadata:** source report, scale, reliability.
- **Unlocks:** E0.5.

### 3. Transmissivity

- **Why:** strong coupling evidence; aquifer-response timescale for cadence.
- **Preferred format:** table of T, method, aquifer, well/test ID, date.
- **Minimum usable:** published test T for study units with method.
- **Time span:** all available tests.
- **Spatial identifier:** well/test ID + aquifer.
- **Units:** m²/day (or stated SI).
- **Metadata:** method (pumping test, specific capacity, etc.), uncertainty.
- **Unlocks:** E0.5, E0.6 timescale.

### 4. Storage / specific yield

- **Why:** same as T.
- **Preferred format:** table of S or Sy, method, aquifer, location.
- **Minimum usable:** published Sy/S for the unit aquifer.
- **Time span:** all available.
- **Spatial identifier:** well/test + aquifer.
- **Units:** dimensionless or m⁻¹ as applicable.
- **Metadata:** method, uncertainty.
- **Unlocks:** E0.5, E0.6.

### 5. Pumping tests

- **Why:** strong coupling evidence; radius of influence.
- **Preferred format:** Q, durations, observation-well drawdown tables.
- **Minimum usable:** reports with Q, duration, aquifer, observation distances.
- **Time span:** all available in AP, prioritized for later candidate units.
- **Spatial identifier:** pumping well + observation wells.
- **Units:** m³/day, metres, minutes/hours.
- **Metadata:** aquifer, confined/unconfined, validity notes.
- **Unlocks:** E0.5.

### 6. Interference tests

- **Why:** documented neighbour response under controlled withdrawal.
- **Preferred format:** multi-well time-drawdown.
- **Minimum usable:** narrative plus wells, distances, and whether response was observed.
- **Time span:** all available.
- **Spatial identifier:** well pair IDs.
- **Units:** m, m³/day, time.
- **Metadata:** aquifer consistency.
- **Unlocks:** E0.5.

### 7. Documented cross-well effects / hydrogeologic event reports

- **Why:** strong evidence of MATERIAL coupling or documented negligible response.
- **Preferred format:** dated well IDs, volumes, observed neighbour change.
- **Minimum usable:** cited agency reports.
- **Time span:** historical through present.
- **Spatial identifier:** well IDs.
- **Units:** m, m³.
- **Metadata:** aquifer, quality of observation.
- **Unlocks:** E0.5, analogue Level A.

### 8. Rainfall as a distinct product

- **Why:** E0.4 independent climate channel (V3 placebo mechanism). V1 bundled rainfall only inside recharge.
- **Preferred format:** station daily or agency-recommended gridded monthly with version.
- **Minimum usable:** monthly rainfall by assessment unit or representative stations.
- **Time span:** overlap with heads (target 1996–present).
- **Spatial identifier:** IMD/station ID or unit ID.
- **Units:** mm.
- **Metadata:** product name, version, QA.
- **Unlocks:** E0.4, E0.6.

### 9. Missing-versus-zero convention for extraction

- **Why:** contract: missing is unknown, never zero; else series `UNUSABLE`.
- **Preferred format:** written convention + coverage fraction field.
- **Minimum usable:** codebook stating missing ≠ 0.
- **Time span:** matches pumping file.
- **Spatial identifier:** same as pumping.
- **Units:** n/a.
- **Metadata:** codebook.
- **Unlocks:** E0.3 pumping audit.

### 10. Subannual vs annual pumping reconciliation

- **Why:** detect monthly spreads of annual totals (not observation).
- **Preferred format:** residual table well/unit × year.
- **Minimum usable:** method statement if only one resolution exists.
- **Time span:** all years with both resolutions.
- **Spatial identifier:** well and unit IDs.
- **Units:** m³.
- **Metadata:** method, fiscal vs calendar year.
- **Unlocks:** E0.3.

### 11. Explicit meter / reported / estimated / proxy class field

- **Why:** pumping-audit classes; V1 asked for metered/reported/allocated/estimated but not electricity/capacity-hours proxy as a named class.
- **Preferred format:** enumerated field on every pumping row.
- **Minimum usable:** method column that can be mapped to the four classes plus UNRESOLVED.
- **Time span:** matches pumping file.
- **Spatial identifier:** production_id.
- **Units:** n/a.
- **Metadata:** class definitions.
- **Unlocks:** E0.3.

---

## V1 items to keep (rephrase cadence)

These remain MUST HAVE, with monthly as **target** not a universal gate:

1. 679 polygons and stable IDs (drop 74 subbasins / 40 basins to NICE TO HAVE).
2. 679/667 explanation and unit–mandal–village crosswalk (microbasin GIS NICE TO HAVE if 679 units arrive).
3. Station master: ID, coordinates, datum, well type, screens, aquifer, active dates, MP/LS elevations.
4. Monitoring vs pumping / well-use (present in V1 as well type/use; make the flag explicit).
5. Corrected historical heads + telemetry with pumping-status and QA.
6. Subannual extraction by well/unit (rephrase: target monthly; minimum subannual adequacy).
7. Recharge components with evidence class (keep; add rainfall separately).
8. Annual GWRA unit-level tables (needed for later M0S; NICE TO HAVE for E0 dynamics but cheap if already in the same PDF export).

NWDP CSV defects (no IDs, 998 missing coords, 14,714 out-of-envelope) stay as a **correction request** under Track I, not a separate dump.

---

## In V1 — move to NICE TO HAVE (not E0 gates)

| V1 section | Why not E0 MUST HAVE |
|---|---|
| Agriculture crop-season ET / Bhuvan product dump | Impact layer after response qualification (AP5) |
| Municipal ULB demand, losses, wastewater, conveyance | Impact / reuse feasibility (AP6/AP7), not local-response identification |
| Canonical DC parcels, cooling, source agreements | Planning integration; blocks M0S later, not E0 dynamics class |
| Candidate–substation / APTRANSCO interconnection | Power, not groundwater E0 |
| Canonical PSCC/MITEI implementation and frozen result | `M0_PSCC_EXACT = NOT_RECOVERED` must not block E0 |

---

## Narrow or drop

| V1 item | Action |
|---|---|
| 74 subbasins and 40 drainage basins as highest priority | NICE TO HAVE; too coarse for primary (scorecard) |
| Broad Bhuvan/NRSC LULC/AET/crop download “recommended for Andhra Pradesh” | Drop as MUST HAVE; invite agency to name the exact product if used for recharge. Avoid exploratory remote-sensing dumps |
| GRACE | Do not request; never well-level ground truth |

---

## Cadence language change

V1: “Monthly or finer extraction … Monthly or finer recharge”

V2 MUST HAVE:

```text
Target = monthly or finer.
Scientific minimum = subannual forcing whose cadence can be shown
adequate relative to aquifer-response timescale, head cadence,
and the intervention analogue.
Annual totals are inadequate for dynamic identification.
```

---

## Nothing in V1 should be submitted as-is

V1 is useful as a historical draft. V2 is the E0-scoped request. Do not submit
either file in this documentation freeze.
