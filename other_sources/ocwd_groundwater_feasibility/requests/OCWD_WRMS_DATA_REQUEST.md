# Draft public-records request: OCWD WRMS observational data

**Status: DRAFT — DO NOT SUBMIT without requester review.**

To: Orange County Water District, Public Records Coordinator  
Subject: Machine-readable Water Resources Management System records for groundwater data-feasibility research

Please provide the following non-confidential records from **January 1, 1990 through the latest available date** for the Orange County groundwater basin. The research purpose is to evaluate whether groundwater states and spatial pumping/recharge inputs can support a reduced-order groundwater-network benchmark with genuinely held-out validation. This request seeks observational and accounting data, not personal customer information.

Please provide CSV, Excel, database export, GeoPackage/shapefile, or another documented machine-readable format. For every table, please include a stable primary key, data dictionary, units, QA codes, missing-value codes, revision/version fields, coordinate reference system and datum, elevation datum, and a description of relationships among tables.

## 1. Well master and identity crosswalk

- OCWD/WRMS well ID and all historical IDs, aliases, and local/state well numbers;
- well/casing name, owner or producer, type/use, and production/monitoring/injection role;
- coordinates, horizontal datum, coordinate source and accuracy;
- ground/reference-point elevations, vertical datum, and measurement-point history;
- installation, activation, inactivation, replacement, abandonment, and other lifecycle dates;
- casing, screen/perforation top and bottom, units, construction changes, and screen/casing identifiers;
- authoritative OCWD aquifer name and Basin Model layer assignment for each screen/casing, including assignment version/date;
- facility identity/address/parcel or producer crosswalks needed to join well, pumping, and monitoring tables.

## 2. Groundwater levels

- well/casing ID and measurement date/time;
- groundwater elevation and/or depth to water, with units;
- measurement-point/reference elevation and vertical datum used for each observation;
- collection method, accuracy, collecting/reporting organization, and QA/review flag;
- pumping-status or nearby-operational-status flag, if maintained;
- provisional/final status, comments, correction/revision flags, and original/revised values where retained.

Please retain raw observation timing and gaps; no interpolation or filled values are requested unless clearly flagged as estimates and supplied separately from measurements.

## 3. Groundwater production

- monthly production volume by individual well/casing and producer;
- units and reporting/billing period;
- whether each value is directly metered/reported, allocated, prorated, calculated, or estimated;
- meter ID, meter set/swap/lifecycle dates, correction factors, and active/inactive status if maintained;
- QA, revision, and late-report flags, and original/revised values where available;
- coordinates or join key to the requested well master.

## 4. Managed surface recharge

- recharge facility ID/name and geospatial location or polygon;
- date/time or monthly period and source-water category;
- delivery/inflow, interfacility transfer, outflow, bypass/loss, and units;
- facility water level, storage, storage change, and supporting storage-elevation relationship/version;
- calculated percolation, calculation method/version, and its measured versus estimated inputs;
- precipitation, evaporation, operational/maintenance, instrumentation, and QA flags relevant to the calculation.

## 5. Groundwater injection

- injection well/casing ID, date/time or monthly period, and injected volume/rate with units;
- source-water category and aquifer/screen zone;
- operational, shutdown, backwash/pumping, meter, QA, and revision flags;
- meter/instrument ID and set/swap/lifecycle metadata where maintained;
- join key to the well master and authoritative aquifer/model-layer assignment.

## 6. Monthly basin-water-budget components

- every component used in the Water Resources Summary or equivalent WRMS accounting;
- period, quantity, value, unit, source/facility scope, and sign convention;
- measured/reported, calculated/derived, allocated, or estimated status;
- calculation definitions, dependencies, revisions, and QA flags;
- source-share fields and documentation needed to distinguish managed recharge, natural/incidental recharge, pumping, injection, losses, and storage change.

Calculated groundwater-storage change will be treated as an accounting-derived quantity, not as independent observed validation.

## 7. Documentation

- full WRMS schema/data dictionary and table relationships;
- all field definitions, controlled vocabularies, units, QA/missing/revision codes, and calculation-method documentation;
- documentation of whether records supplied to DWR are duplicates/republications of OCWD observations;
- documentation of known discontinuities, system migrations, meter changes, well renamings, or retrospective corrections.

## Scope-preserving fallback

If a 1990-present export is too large or burdensome, please instead provide the exact **November 1990-November 1999 transient Basin Model calibration dataset**. OCWD's Basin Model documentation states that this interval had essentially complete monthly groundwater-elevation, production, and recharge data and used nearly 250 water-level targets across all three model layers. The fallback should include the same well/facility identities, monthly observation and forcing tables, screens/layers, QA, data dictionary, and calibration-observation crosswalk described above.

Please identify any requested field that is not maintained, withheld, or available only in a non-machine-readable form, rather than silently omitting it.

