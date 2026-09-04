# Draft Andhra Pradesh planning-data access request

Do not submit without project review. Machine-readable records are requested
in CSV, database export, GeoPackage/shapefile, Parquet, or documented API form,
with data dictionaries, units, coordinate/vertical datums, QA codes, revision
history, and licenses.

## 1. Groundwater geography and identity — highest priority

From CGWB and the Andhra Pradesh Ground Water and Water Audit Department:

- Versioned polygons and stable IDs for the 679 groundwater assessment units,
  748 microbasins, reported 74 subbasins, and 40 drainage basins used in the
  2024 dynamic-resource assessment.
- Full unit-to-microbasin-to-village/revenue-mandal/district crosswalk,
  including effective dates and explanation of the reported 679 assessment
  units versus 667 revenue mandals.
- Groundwater monitoring-station master: stable ID, names/aliases, verified
  coordinates and horizontal datum, measuring-point and land-surface
  elevations with vertical datum, well type/use, owner/operator, active dates,
  construction, screen/perforation intervals, aquifer, and authoritative
  model/layer assignment.
- Corrected historical manual groundwater levels and all available
  DWLR/AWLR/telemetry observations: station ID, date/time/timezone, water-level
  value and type, unit, datum, method, pumping-status flag, QA, source agency,
  revision status, and reason for correction/deletion.
- Resolution of the downloaded NWDP Andhra CSV issues: no stable station IDs,
  missing QA/method/layer fields, 998 numeric candidate rows without complete
  coordinates, and 14,714 candidate rows outside CGWB's published Andhra
  Pradesh coordinate envelope.

## 2. Recharge and extraction forcing — highest priority

- Monthly or finer extraction by individual production well and groundwater
  assessment/aquifer unit, with volume, unit, source/use, metered/reported/
  allocated/estimated class, coverage fraction, QA, and revisions.
- Monthly or finer recharge by facility and groundwater unit, separating
  rainfall recharge, canal/tank/irrigation return, managed recharge, and
  injection; include inflow, outflow, storage, calculated recharge/percolation,
  method, evidence class, QA, and revisions.
- Annual assessment inputs/outputs for each 2024 assessment unit: recharge
  components, extractable resource, irrigation/domestic/industrial extraction,
  stage, category, allocation, and natural discharge, plus the exact
  GEC-2015/INGRES method and table keys.

## 3. Agriculture exposure

From DES, NRSC, and state agriculture/irrigation agencies:

- Versioned crop-season irrigated/cropped area at the finest authoritative
  compatible unit; crop/season IDs; irrigation source; crop ET or water-demand
  method; groundwater-dependence share; uncertainty/QA; and unit crosswalks.
- Metadata and download access for the exact Bhuvan/NRSC LULC, irrigated-area,
  crop, and ET products recommended for Andhra Pradesh, including product
  version, time support, resolution, projection, scale factors, cloud/quality
  layers, and validation information.

## 4. Municipal and wastewater exposure

From ULBs, state water/municipal authorities, and treatment-plant operators:

- Versioned ULB/service-area geometry, served population, monthly demand and
  supply, groundwater abstraction, surface/imported supply, losses, reliability,
  source constraints, and groundwater-unit crosswalk.
- Wastewater generation, installed/operational/utilized treatment capacity,
  treatment quality, current reuse, committed supply, uncommitted reusable
  capacity, operating history, and conveyance geometry/cost to candidates.

## 5. Data-center candidates, water sources, and power

From AP ITE&C/project authorities, APTRANSCO/CEA, project proponents, and
source-owning utilities:

- Canonical eligible candidate parcels/regions with stable IDs, geometry,
  project status, capacity, schedule, and land/infrastructure constraints.
- Cooling technology and operating envelope; water-service boundary; legally
  available groundwater/reuse/desalination/surface source; withdrawal versus
  consumption; source shares; treatment/conveyance; capacity; contract;
  chronology; and uncertainty.
- Candidate-to-substation/power-region mapping, voltage, interconnection and
  deliverable capacity, grid/renewable options, emissions, costs, and effective
  dates.
- The canonical PSCC/MITEI static-model implementation and input bundle:
  objective algebra/weights, decision variables, constraints, demand, costs,
  WSF, power/renewable, equity, candidates, horizon, and frozen result.

These records enable local estimation and controlled comparison; no California
or OCWD physical coefficient will be transferred to Andhra Pradesh.
