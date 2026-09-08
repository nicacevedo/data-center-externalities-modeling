# Andhra Pradesh E0 data request (V2)

**Do not submit without project review. This file is not an outgoing letter.**

Purpose: obtain the evidence required to freeze

```text
CURRENT_E0_DECISION = LOCAL_STUDY_ELIGIBLE | STATIC_ONLY | UNRESOLVED
```

before any groundwater-response model is fit. No OCWD or California physical
coefficient will be transferred to Andhra Pradesh.

Please provide machine-readable records (CSV, GeoPackage/shapefile, Parquet, or
documented API) with a data dictionary, units, CRS/vertical datum, QA codes,
revision history, and license.

Three tracks may be fulfilled **in parallel**.

---

## MUST HAVE — TRACK I (spatial / identity)

From CGWB and the Andhra Pradesh Ground Water and Water Audit Department:

1. **679 groundwater assessment units (GWRA 2024 vintage):** polygons, stable IDs, CRS, effective dates.
2. **Reconciliation** of 679 assessment units with 667 revenue mandals, with a versioned crosswalk (unit–village–mandal–district) and effective dates.
3. **Monitoring-station master** for Andhra Pradesh, including:
   - stable station ID (and name aliases)
   - verified coordinates and horizontal datum
   - well type (dug well / piezometer / other)
   - **monitoring versus production / mixed flag**
   - aquifer / layer (authoritative; not a depth threshold)
   - screen/perforation interval if available
   - measuring-point and land-surface elevations with vertical datum
   - active dates and known relocations
4. **Corrected groundwater-level archive** linked to that master: station ID, timestamp with timezone, depth and/or head, unit, datum, method, **pumping-status at measurement**, QA, revision flag. Please resolve the public NWDP AP CSV issues: no stable IDs, missing QA/method/layer, 998 numeric rows without coordinates, 14,714 rows outside the published AP coordinate envelope.
5. **Telemetry / DWLR / AWLR / weekly participatory** series if they exist for AP, in the same station-ID system. Documentation that telemetry exists is not a substitute for the file.

---

## MUST HAVE — TRACK II (forcing)

From CGWB, AP Ground Water and Water Audit Department, and the rainfall-product owner:

1. **Subannual groundwater extraction** by production well and/or assessment unit.
   - **Target cadence:** monthly or finer.
   - **Scientific minimum:** subannual series whose time step can be justified against aquifer-response timescale, head-observation cadence, and any documented pumping change.
   - **Annual totals alone are not sufficient** for dynamic analysis.
2. For every pumping series: **method class** (`metered` / `reported-measured` / `estimated` / `proxy` such as electricity or pump-hours), units (m³), **missing-value convention (missing is not zero)**, coverage fraction, QA, and revisions.
3. **Reconciliation** of subannual sums with published annual assessment extraction where both exist (method statement if only one resolution exists).
4. **Rainfall** overlapping the head archive (target 1996–present): station daily or the agency’s recommended monthly/unit product, with product name, version, and units (mm).
5. **Recharge components** at unit or facility scale, separated where available: rainfall recharge, canal/tank/irrigation return, managed recharge, injection. Include method and whether each series is measured, calculated, or estimated. Do not substitute a transform of the pumping series for rainfall.

---

## MUST HAVE — TRACK III (hydrogeology)

From CGWB (NAQUIM) and AP Ground Water Department:

1. **Machine-readable aquifer mapping (NAQUIM or equivalent GIS)** for Andhra Pradesh, with aquifer/layer attributes and scale/vintage.
2. **Mapped aquifer connectivity or barriers** (faults, compartments) that can be joined to well aquifer IDs.
3. **Transmissivity and storage / specific yield** with method, aquifer, location/well, date, and units.
4. **Pumping tests and interference tests:** pumping well, observation wells, rates, durations, distances, aquifer, and drawdown tables or reports.
5. **Documented neighbouring-well responses** (or documented negligible response) to known withdrawals, with dates and well IDs.

Track III is required to classify coupling as `WEAKLY_SUPPORTED`, `MATERIAL`, or `UNRESOLVED`. Absence of a correlation in untreated head series will not be treated as proof of weak coupling.

---

## NICE TO HAVE (not required to freeze E0 dynamics)

Provide if readily available; these do not block the E0 classification of
whether a **local study** can run, but they will be needed later for static
source-resolved planning (M0S) or impact claims.

- Annual GWRA 2024 **unit-level** tables: recharge components, extractable resource, irrigation/domestic/industrial extraction, stage, category, for each of the 679 units (plus GEC-2015/INGRES table keys). Statewide PDF totals are already in-hand.
- 748 microbasin polygons and unit–microbasin map; 74 subbasins / 40 basins (secondary).
- Canal/tank operating dates and releases for potential documented events.
- Crop-season irrigated area and groundwater-dependence at assessment-unit scale (DES/NRSC).
- ULB groundwater abstraction and service-area geometry.
- Eligible data-center parcels, source entitlements, and grid interconnection (planning, not E0).
- A paper-faithful static planning reconstruction may be built later; **exact historical PSCC recovery is not requested as an E0 condition.**

Do **not** send GRACE as groundwater-head evidence. Do **not** send undifferentiated statewide remote-sensing dumps; if ET or LULC is used in an official recharge method, send that named product and version only.

---

## How we will use the files

Identity and forcing will be scored against a pre-registered evidence matrix.
No groundwater-response model will be fit until E0 is classified. Missing
extraction will not be treated as zero. Synthetic model parameters from other
studies will not be used as Andhra Pradesh estimates.
