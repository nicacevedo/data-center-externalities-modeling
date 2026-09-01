# LBNL latest US data-center energy-use update — bounded audit

Date of audit: 2026-09-01.

## What exists

Lawrence Berkeley National Laboratory published **United States Data Center Energy Usage Report: 2025 Update** (listed June 2026 on ETA/SETA pages). It updates the 2024 report’s electricity outlook to 2030 (reference 649 TWh; range 521–843 TWh; ~11.8% of US electricity in the reference case). Drivers are IT shipments, AI/GPU stock, idle/utilization, and device lifetime.

## Cooling taxonomy / PUE / WUE / microdata

From the public abstract and secondary summaries available in this pass:

- The update remains a **bottom-up electricity (and related) stock model** using cooling-system performance simulations plus facility type/location — the same structural idea as 2024.
- No public CSV/XLSX of the cooling simulation microdata was identified.
- No evidence in the abstracts that the **ten Lei 2025 cooling labels** or the `UEs_16cases.csv` ensemble are superseded.
- AI/liquid cooling is discussed as a stock/energy driver, not as a new public hourly engine for rear-door / cold-plate / immersion.

## Decision

**Nothing material found that requires rebuilding this cooling-proxy freeze.**

If the 2025 Update PDF later shows a new cooling catalog or released microdata, treat that as a separately gated intake. Do not rebuild from electricity-outlook headlines.

Confidence: **MEDIUM** (PDF fetch of the 2025 Update timed out here; conclusion is from official abstracts, not a page-level cooling-table extraction).
