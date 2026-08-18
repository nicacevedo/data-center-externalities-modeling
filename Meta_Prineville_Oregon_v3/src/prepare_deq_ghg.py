"""Prepare Oregon DEQ electricity-supplier GHG evidence for Pacific Power.

This is utility Oregon-delivery GHG, not Vitesse onsite backup-generator CO2e and
not eGRID/PACW campus Scope 2. Other GHG workbooks are retained as provenance
unless they contain directly relevant Vitesse (07-0037) observations.

Raw files under data/raw/deq_ghg/ are never modified.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "deq_ghg"
CANON = ROOT / "data" / "canonical"
PROC = ROOT / "data" / "processed"
OUT_PAC = PROC / "pacific_power_deq_ghg_annual.csv"
OUT_INV = CANON / "deq_document_inventory.csv"

PACIFIC_POWER = "Pacific Power (PacifiCorp)"
VITESSE_PAT = re.compile(r"vitesse|07-0037|meta platforms|facebook", re.I)
FALSE_POSITIVE = re.compile(r"07-0063|prineville landfill|metco|metallurgical", re.I)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_workbook(path: Path) -> dict:
    xl = pd.ExcelFile(path)
    hits = []
    for sheet in xl.sheet_names:
        df = pd.read_excel(path, sheet_name=sheet, header=None, dtype=str)
        text = " ".join(df.astype(str).fillna("").values.ravel().tolist())
        if FALSE_POSITIVE.search(text) and not VITESSE_PAT.search(text):
            continue
        if VITESSE_PAT.search(text):
            hits.append(sheet)
    return {
        "source_file": path.name,
        "relative_path": str(path.relative_to(ROOT)),
        "sha256": sha256_file(path),
        "n_pages": pd.NA,
        "extractable_chars": pd.NA,
        "text_extractable": True,
        "scan_only": False,
        "document_type": "deq_ghg_workbook",
        "filename_year": pd.NA,
        "document_calendar_year": pd.NA,
        "permit_number": pd.NA,
        "facility_name": PACIFIC_POWER if path.name == "ghgElectricityEms.xlsx" else pd.NA,
        "extraction_status": "processed_pacific_power" if path.name == "ghgElectricityEms.xlsx" else "provenance_only",
        "ocr_used": False,
        "sheets": ";".join(xl.sheet_names),
        "vitesse_sheet_hits": ";".join(hits) if hits else pd.NA,
        "note": (
            "Oregon electricity-supplier GHG. Pacific Power row is utility delivery, not campus onsite DEQ emissions."
            if path.name == "ghgElectricityEms.xlsx"
            else "Preserved as source/provenance. No direct Vitesse 07-0037 observations identified."
        ),
    }


def pacific_power_annual(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="Emissions and Power by Year", header=None)
    years = []
    for col, val in df.iloc[0].items():
        if pd.notna(val):
            try:
                years.append((int(col), int(val)))
            except (TypeError, ValueError):
                continue
    match = df[0].astype(str).str.fullmatch(re.escape(PACIFIC_POWER), case=False)
    if not match.any():
        raise ValueError(f"{PACIFIC_POWER} not found in Emissions and Power by Year")
    row = df.loc[match].iloc[0]
    recs = []
    for start_col, year in years:
        energy = row.iloc[start_col]
        emis = row.iloc[start_col + 1] if start_col + 1 < len(row) else pd.NA
        intensity = row.iloc[start_col + 2] if start_col + 2 < len(row) else pd.NA
        recs.append({
            "year": year,
            "supplier": PACIFIC_POWER,
            "supplier_category": "Investor-Owned Utility",
            "energy_mwh": pd.to_numeric(energy, errors="coerce"),
            "anthropogenic_emissions_mtco2e": pd.to_numeric(emis, errors="coerce"),
            "emission_intensity_mtco2e_per_mwh": pd.to_numeric(intensity, errors="coerce"),
            "source_file": path.name,
            "source_sheet": "Emissions and Power by Year",
            "extraction_method": "workbook_row",
            "not_vitesse_onsite_emissions": True,
            "not_egrid_or_pacw_campus_scope2": True,
            "not_backup_generator_co2e": True,
            "geography": "Oregon electricity deliveries by supplier",
        })
    return pd.DataFrame(recs)


def main() -> None:
    if not RAW.exists():
        raise FileNotFoundError(RAW)
    inv_rows = []
    pac = None
    for path in sorted(RAW.glob("*.xlsx")):
        inv_rows.append(scan_workbook(path))
        if path.name == "ghgElectricityEms.xlsx":
            pac = pacific_power_annual(path)
    if pac is None:
        raise FileNotFoundError(RAW / "ghgElectricityEms.xlsx")
    OUT_PAC.parent.mkdir(parents=True, exist_ok=True)
    pac.to_csv(OUT_PAC, index=False, na_rep="")
    print(f"Wrote {OUT_PAC.relative_to(ROOT)} rows={len(pac)} years={sorted(pac['year'].tolist())}")

    ghg_inv = pd.DataFrame(inv_rows)
    if OUT_INV.exists():
        air = pd.read_csv(OUT_INV)
        for col in ghg_inv.columns:
            if col not in air.columns:
                air[col] = pd.NA
        for col in air.columns:
            if col not in ghg_inv.columns:
                ghg_inv[col] = pd.NA
        out = pd.concat([air, ghg_inv[air.columns]], ignore_index=True)
    else:
        out = ghg_inv
    out.to_csv(OUT_INV, index=False, na_rep="")
    print(f"Updated {OUT_INV.relative_to(ROOT)} rows={len(out)}")


if __name__ == "__main__":
    main()
