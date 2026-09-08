# AP E0 public-source assessment

Targeted public acquisition pass. Retrieval timestamp:
`2026-09-08T00:15:03Z`.

This file does not fit a model, does not transfer synthetic V2/V3 parameters,
and does not change frozen E0 eligibility rules.

```text
ACCESS_STATUS and SCIENTIFIC_STATUS are independent.
Obtained != ADEQUATE.
```

Provenance: [AP_E0_SOURCE_PROVENANCE_MANIFEST.csv](AP_E0_SOURCE_PROVENANCE_MANIFEST.csv).
Search log: [AP_E0_PUBLIC_SOURCE_ACQUISITION_LOG.csv](AP_E0_PUBLIC_SOURCE_ACQUISITION_LOG.csv).
Delta: [AP_E0_DELTA_STATUS.md](AP_E0_DELTA_STATUS.md).

---

## E0.1 Spatial identity

**What was searched.** CGWB GWRA 2024 / IN-GRES; NWIC `GWR2024_CGWB` MapServer
(layer 8, Categorization of Blocks/Talukas/Mandals); India-WRIS GIS directory;
CGWB block-wise GWRA-2024 categorization PDF; 679-versus-667 reconciliation
language in already-frozen yearbook vs GWRA PDFs.

**Authoritative source found.** Yes. NWIC publishes an official 2024
block/taluka/mandal polygon layer with attributes `block`, `code`, `district`,
`state`, `class`, and annual draft/recharge fields. IN-GRES is the official
CGWB/IIT-Hyderabad assessment GIS dashboard (Andhra Pradesh location UUID
`609c5df4-6414-4bbd-a22d-ff5fbdad6836` appears in public dashboard URLs).
CGWB publishes a national block-wise categorization PDF for GWRA-2024.

**Artifact obtained.** Service metadata JSON and layer-8 schema. Block-wise
categorization PDF (`sha256=74ab848032c756aeea77f35386d8b664ac9983a1559673313f55f418081d43fb`).
No native GeoPackage/shapefile/GeoJSON of the 679-unit vintage.

**Blocker cleared?** No.

**Remaining missing fields.** Versioned 679-unit polygons with declared CRS;
stable IDs matching GWRA tables; geometry vintage attached to those polygons;
authoritative 679-versus-667 revenue-mandal crosswalk; unit–village–mandal
crosswalk. A PDF name/category table is not geometry.

**Access request still needed?** Yes. Track I MUST-HAVE items 1–2 in
[AP_PLANNING_DATA_ACCESS_REQUEST_V2.md](../requests/AP_PLANNING_DATA_ACCESS_REQUEST_V2.md).
The NWIC feature instance returned `Instance not available on server`; IN-GRES
has no public polygon API located in this pass.

**Confidence.** High that official GIS exists and was not downloadable here.
High that the geometry blocker remains.

Outcome: `OFFICIAL_SOURCE_FOUND_BUT_ACCESS_REQUIRED` (polygons);
`PUBLIC_SOURCE_OBTAINED` (PDF names/categories, scientifically inadequate).

---

## E0.2 Monitoring-well identity

**What was searched.** NWDP organization `andhra-pradesh-gw`; AP GWD telemetry
and manual-quarterly groundwater-level datasets; NWIC `Groundwater_Stations`
MapServer; frozen CGWB NWDP quarterly CSVs (not re-downloaded).

**Authoritative source found.** Yes. Andhra Pradesh Ground Water Department
publishes public CSVs on NWDP. Dataset notes advertise a “station identifier
with geographic hierarchy.” Inspected fields are `Station` (name), LGD
state/district codes, Tehsil/Block/Village (often `-`), lat/lon, empty
`RL_MSL`, and a depth/level column. `SlNo` is a row number.

**Artifact obtained.** Native CSVs (hashes in the provenance manifest),
including 2,278,844 six-hourly telemetry rows (2021-01-04 to 2025-09-22) and
259,248 rows (2026-01-01 to 2026-09-06). Coverage audit:
[acquired/derived/AP_GWD_NWDP_COVERAGE_AUDIT.json](acquired/derived/AP_GWD_NWDP_COVERAGE_AUDIT.json).

**Blocker cleared?** No. E0.2 ADEQUATE still requires stable ID, aquifer,
monitoring-versus-pumping flag, and vertical datum. Telemetry existence was
previously `NOT_LOCATED`; it is now `PARTIAL`.

**Remaining missing fields.** Stable station ID; aquifer/layer; screen;
monitoring versus production flag; active dates/relocations; populated
measuring-point / land-surface elevations with vertical datum; QA/method
flags. 10,509 telemetry rows in the 2021–2025 file fall outside the published
AP envelope. `RL_MSL` is empty on all audited rows.

**Access request still needed?** Yes. Track I station master and corrected
archive.

**Confidence.** High.

Outcome: `PUBLIC_SOURCE_OBTAINED` for name-keyed heads/telemetry;
scientifically `PARTIAL` / `INADEQUATE` for identity. Do not construct
synthetic IDs from names and coordinates.

---

## E0.3 Withdrawal forcing

**What was searched.** NWDP CKAN for extraction / abstraction / pumping /
draft; GWR2024 layer-8 annual `agwd_tot` attributes; IN-GRES dashboard;
already-in-hand CGWB AP GWRA 2024 statewide annual totals.

**Authoritative source found.** Annual ESTIMATED GWRA extraction remains
documented (statewide 7.88 bcm/y). GWR2024 GIS would expose annual
block-level draft if the feature instance were queryable. No public
well-level or node-level subannual withdrawal dataset was located on NWDP.

**Artifact obtained.** None that is subannual well/node pumping. Pumping
audit protocol applied to the only in-hand withdrawal evidence:

| Series | Class |
|---|---|
| CGWB/AP GWRA 2024 statewide annual extraction | `ESTIMATED` |
| GWR2024 block annual draft (not downloaded) | not scored as a series |
| Electricity / capacity / crop proxies | not used |

No `OBSERVED_METERED`, `OBSERVED_REPORTED`, `PROXY`, or new `UNUSABLE`
series. Missing-versus-zero convention for well pumping remains unobtainable
because no pumping file exists.

**Blocker cleared?** No. Annual totals remain inadequate for dynamic
identification. Monthly-from-annual synthesis was not performed.

**Remaining missing fields.** Subannual well/node volumes; meter / reported /
estimated / proxy class; missingness convention; revisions; monthly–annual
reconciliation.

**Access request still needed?** Yes. Track II MUST-HAVE extraction items.

**Confidence.** High.

Outcome: `NO_AUTHORITATIVE_SOURCE_LOCATED` for subannual well pumping;
`OFFICIAL_SOURCE_FOUND_BUT_ACCESS_REQUIRED` for unit-level annual draft GIS.

---

## E0.4 Recharge forcing

**What was searched.** Specified IMD 0.25° daily gridded rainfall product
(Pai et al. 2014); AP GWD NWDP hourly rainfall; CGWB/IN-GRES recharge
components; GRACE (explicitly not downloaded). Wind/temperature/humidity
AP GWD telemetry were listed on NWDP and **not** downloaded (no frozen E0
item).

**Authoritative source found.** IMD RF25 is the official independent rainfall
product. AP GWD rainfall telemetry exists but is two stations and a few
thousand hourly rows. Statewide annual ESTIMATED recharge (27.80 bcm/y)
remains from the frozen GWRA PDF.

**Artifact obtained.** IMD NetCDF years 1996, 2020, 2023 (classic CDF-1;
`RAINFALL` in mm; 135×129 grid; 6.5N–38.5N, 66.5E–100.0E; missing encoded
as `-999`). Product inspect:
[acquired/derived/IMD_RF25_PRODUCT_INSPECT.json](acquired/derived/IMD_RF25_PRODUCT_INSPECT.json).
Sparse AP GWD rainfall CSVs.

**Blocker cleared?** No. Rainfall is `PARTIAL` (product identified; only three
overlap years in-hand; not joined to 679 units). Recharge components,
managed recharge, and canal/tank series were not obtained.

**Remaining missing fields.** Remaining IMD years in the head-overlap window
if a full panel is required; unit or station join after polygons exist;
rainfall-recharge vs canal/tank/irrigation-return vs managed-recharge split
with method and evidence class.

**Access request still needed?** Yes for recharge components. Remaining IMD
years are publicly posted at the same official endpoint and were not
mass-downloaded in this pass.

**Confidence.** High for product identity. High that recharge components
still block E0.4 ADEQUATE.

Outcome: `PUBLIC_SOURCE_OBTAINED` (IMD samples + sparse AP GWD rainfall);
`OFFICIAL_SOURCE_FOUND_BUT_ACCESS_REQUIRED` (recharge components).

---

## E0.5 Hydrogeological coupling

**What was searched.** CGWB aquifer-mapping programme page; CGWB publications
warehouse (Aquifer Mapping category); statewide *Aquifer System of Andhra
Pradesh*; 26 district NAQUIM PDFs posted Feb–Mar 2025; NWIC
`AquiferSystems_GSI` and `AquiferLitholog_NWIC` services.

**Authoritative source found.** Yes for PDF reports. Machine-readable NAQUIM
GIS was not confirmed. CGWB states NAQUIM outputs are shared with states and
disseminated via cgwb.gov.in, aims-cgwb.org, and India-WRIS.

**Artifact obtained.** Statewide aquifer-system PDF; Ananthapuramu and Nandyal
NAQUIM PDFs (targeted, not all districts); catalog of 26 official district
PDF URLs. No GeoPackage/shapefile of aquifers. No pumping-test or T/S table
file.

**Blocker cleared?** No.

```text
COUPLING_STATUS = UNRESOLVED
NOT_DETECTED != WEAK
```

PDFs were not scored as `WEAKLY_SUPPORTED` or `MATERIAL`. T/S and test
coefficients were not extracted into model parameters. Compressed PDF
prose was not treated as a finding that tests are absent.

**Remaining missing fields.** NAQUIM machine-readable GIS; mapped barriers
joined to well aquifers; T and S/Sy with method; pumping tests; interference
tests; documented cross-well effects.

**Access request still needed?** Yes. Track III MUST-HAVE items.

**Confidence.** High that GIS/tests remain missing. Medium that district PDFs
contain narrative hydrogeology that still cannot, by itself, freeze coupling.

Outcome: `PUBLIC_SOURCE_OBTAINED` (reports); `SOURCE_EXISTS_BUT_MACHINE_READABLE_DATA_NOT_FOUND`
(NAQUIM GIS).

---

## E0.6 Temporal overlap / excitation

**What was searched.** Factual metadata only from acquired head, rainfall, and
pumping-search results. No correlations, no response fits.

**Authoritative source found.** Heads: CGWB quarterly 1996–2023 (preflight)
plus AP GWD telemetry 2021–2026. Rainfall: IMD samples 1996/2020/2023 plus
sparse AP GWD station rainfall. Pumping: none subannual.

**Artifact obtained.** Coverage audit JSON and chronological spans
(`AP_GWD_CHRONOLOGICAL_SPAN.json`).

**Blocker cleared?** No. Common support of repaired heads and subannual
withdrawal forcing does not exist. Aquifer timescale is still unknown
without T/S/tests. No Level A/B/C analogue is documented.

**Remaining missing fields.** Subannual pumping overlapping heads; analogue
dates/volumes; hydraulic timescale.

**Access request still needed?** Yes. Track II pumping and analogue
documentation; Track III for timescale.

**Confidence.** High.

Outcome: coverage/excitation feasibility remains inadequate. Telemetry
updates the post-2023 head window but cannot create excitation without
forcing.

---

## Decision (unchanged)

```text
CURRENT_E0_DECISION = UNRESOLVED
LOCAL_STUDY_ELIGIBLE = FALSE
STATIC_ONLY_ELIGIBLE = FALSE
EMPIRICAL_M1N_AUTHORIZED = FALSE
CURRENTLY_EARNED_PLANNING_COMPLEXITY = NONE
HIGHEST_PLAUSIBLE_NEAR_TERM_COMPLEXITY = M0S
M1L = NOT_EARNED
M1N = NOT_EARNED
COUPLING_STATUS = UNRESOLVED
ELIGIBLE_UNIT_COUNT = 0
```

No unit is pre-outcome eligible: polygons/IDs, aquifer assignment,
monitoring-versus-pumping flag, subannual classified pumping, independent
recharge-component completeness, `WEAKLY_SUPPORTED` coupling, and a declared
analogue are all still missing.
