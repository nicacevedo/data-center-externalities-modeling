"""Parse FERC Form 714 inline-XBRL filings for PacifiCorp West and East+West.

Raw HTML under data/raw/ferc_form_714/ is never modified. West monthly values are
FERC-reported PacifiCorp-West evidence. East+West hourly demand is the combined
planning-area shape and is never labeled PACW-West.

FERC Schedule 2 hours are hour-ending local prevailing time (PPT/PST/PDT →
America/Los_Angeles). EIA-930 PACW hours are hour-ending UTC. The two conventions
are kept in separate columns and files.
"""
from __future__ import annotations

import html
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "ferc_form_714"
OUT = ROOT / "data" / "processed" / "ferc714"
EIA_HOURLY = ROOT / "data" / "processed" / "pacw_hourly.csv"
EIA_CANONICAL = ROOT / "data" / "processed" / "pacw_hourly.csv"
EXTENDED = ROOT / "data" / "processed" / "pacw_demand_hourly_extended.csv"
OUT_QA = ROOT / "outputs" / "ferc714_qa.csv"
OUT_VAL = ROOT / "outputs" / "ferc714_eia930_validation.csv"
OUT_PNG = ROOT / "outputs" / "ferc714_eia930_validation.png"
OUT_MONTHLY_CMP = ROOT / "outputs" / "ferc714_eia930_monthly_compare.csv"

EIA_REPORTED_MIN_MW = 0.0
EIA_REPORTED_MAX_MW = 8000.0
TZ_PACIFIC = "America/Los_Angeles"
TZINFO = ZoneInfo(TZ_PACIFIC)
MONTH_MEMBER = {
    "JanuaryMember": 1,
    "FebruaryMember": 2,
    "MarchMember": 3,
    "AprilMember": 4,
    "MayMember": 5,
    "JuneMember": 6,
    "JulyMember": 7,
    "AugustMember": 8,
    "SeptemberMember": 9,
    "OctoberMember": 10,
    "NovemberMember": 11,
    "DecemberMember": 12,
}
WEST_CONCEPTS = {
    "nel": "ferc:NetEnergyForLoadAndPeakDemandSourcesByMonthNetEnergyForLoad",
    "generation": "ferc:NetEnergyForLoadAndPeakDemandSourcesByMonthBalancingAuthorityAreaNetGeneration",
    "interchange": "ferc:NetEnergyForLoadAndPeakDemandSourcesByMonthNetActualInterchange",
    "peak": "ferc:LoadSourcesAtTimeOfBalancingAuthorityAreaMonthlyPeakDemandMonthlyPeakDemand",
    "minimum": "ferc:NetEnergyForLoadAndPeakDemandSourcesByMonthMonthlyMinimumDemand",
}
HOURLY_CONCEPT = "ferc:PlanningAreaHourlyDemandMegawatts"
CTX_RE = re.compile(r'<xbrli:context id="([^"]+)">([\s\S]*?)</xbrli:context>')
FACT_RE = re.compile(
    r"<(ix:nonFraction|ix:nonNumeric)([^>]*)>([\s\S]*?)</\1>",
    re.IGNORECASE,
)
INSTANT_RE = re.compile(r"<xbrli:instant>([^<]+)</xbrli:instant>")
MONTH_RE = re.compile(r'dimension="ferc:MonthAxis">(?:ferc:)?([A-Za-z]+Member)<')
ATTR_RE = re.compile(r'([A-Za-z:]+)\s*=\s*"([^"]*)"')
YEAR_IN_NAME = re.compile(r"-(\d{4})Q4F714_(\d+)\.html$", re.I)
RESP_IN_NAME = re.compile(r"-(\d+)-\d{4}Q4F714_", re.I)


def discover_filings(raw_dir: Path = RAW) -> pd.DataFrame:
    files = sorted(raw_dir.glob("*.html")) + sorted(raw_dir.glob("*.xhtml"))
    rows = []
    for path in files:
        name = path.name
        lower = name.lower()
        if "eastwest" in lower or "partiisch2" in lower or "part2sch2" in lower:
            kind = "east_west_combined_hourly"
        elif "pacificorpwest" in lower.replace("-", "") or "pacificorpwest" in lower:
            kind = "pacificorp_west_monthly"
        else:
            kind = "unclassified"
        ym = YEAR_IN_NAME.search(name)
        rm = RESP_IN_NAME.search(name)
        rows.append(
            {
                "path": str(path),
                "filename": name,
                "kind": kind,
                "report_year_from_name": int(ym.group(1)) if ym else np.nan,
                "filing_id": ym.group(2) if ym else "",
                "respondent_code_from_name": rm.group(1) if rm else "",
            }
        )
    return pd.DataFrame(rows)


def _attrs(blob: str) -> dict[str, str]:
    return {k: v for k, v in ATTR_RE.findall(blob)}


def _num(attrs: dict[str, str], text: str) -> float:
    raw = html.unescape(text).strip().replace(",", "")
    if raw in {"", "-", "None", "nan"}:
        return float("nan")
    try:
        value = float(raw)
    except ValueError:
        return float("nan")
    if attrs.get("sign") == "-":
        value = -value
    scale = attrs.get("scale")
    if scale not in (None, ""):
        value *= 10 ** int(scale)
    return value


def parse_ixbrl(path: Path) -> tuple[dict[str, dict], list[dict], str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    contexts: dict[str, dict] = {}
    for cid, body in CTX_RE.findall(text):
        inst = INSTANT_RE.search(body)
        month = MONTH_RE.search(body)
        contexts[cid] = {
            "instant": inst.group(1) if inst else None,
            "month": month.group(1) if month else None,
        }
    facts = []
    for tag, attr_blob, body in FACT_RE.findall(text):
        attrs = _attrs(attr_blob)
        name = attrs.get("name", "")
        if not name:
            continue
        facts.append(
            {
                "tag": tag.split(":")[-1].lower(),
                "name": name,
                "context": attrs.get("contextRef", ""),
                "unit": attrs.get("unitRef", ""),
                "attrs": attrs,
                "text": html.unescape(re.sub(r"\s+", " ", body)).strip(),
            }
        )
    return contexts, facts, text


def _first_text(facts: list[dict], name: str) -> str:
    for f in facts:
        if f["name"] == name and f["text"]:
            return f["text"]
    return ""


def _report_year(facts: list[dict], fallback) -> int:
    raw = _first_text(facts, "ferc:ReportYear")
    if raw:
        return int(float(raw.replace(",", "")))
    return int(fallback)


def extract_west_monthly(path: Path, meta: dict) -> pd.DataFrame:
    contexts, facts, _ = parse_ixbrl(path)
    year = _report_year(facts, meta.get("report_year_from_name"))
    respondent = _first_text(facts, "ferc:RespondentLegalName")
    ba_name = _first_text(facts, "ferc:BalancingAuthorityAreaName")
    company = _first_text(facts, "ferc:CompanyIdentifier")
    by_ctx: dict[str, dict] = {}
    for f in facts:
        concept = None
        for key, cname in WEST_CONCEPTS.items():
            if f["name"] == cname:
                concept = key
                break
        if concept is None:
            continue
        ctx = contexts.get(f["context"], {})
        month = MONTH_MEMBER.get(ctx.get("month") or "", np.nan)
        rec = by_ctx.setdefault(
            f["context"],
            {"year": year, "month": month, "context_id": f["context"]},
        )
        rec[concept] = _num(f["attrs"], f["text"])
        if pd.isna(rec.get("month")) and month == month:
            rec["month"] = month
    rows = []
    for rec in by_ctx.values():
        if pd.isna(rec.get("month")):
            continue
        rows.append(rec)
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["year"] = year
    out["west_net_energy_for_load_mwh"] = pd.to_numeric(out.get("nel"), errors="coerce")
    out["west_net_generation_mwh"] = pd.to_numeric(out.get("generation"), errors="coerce")
    out["west_net_interchange_mwh"] = pd.to_numeric(out.get("interchange"), errors="coerce")
    out["west_monthly_peak_mw"] = pd.to_numeric(out.get("peak"), errors="coerce")
    out["west_monthly_minimum_mw"] = pd.to_numeric(out.get("minimum"), errors="coerce")
    out["respondent_legal_name"] = respondent
    out["balancing_authority_area_name"] = ba_name
    out["company_identifier"] = company
    out["source_file"] = Path(path).name
    out["filing_id"] = meta.get("filing_id", "")
    out["respondent_code"] = meta.get("respondent_code_from_name", "")
    out["timezone"] = TZ_PACIFIC
    out["time_convention"] = (
        "FERC Form 714 Part II monthly accounting; PacifiCorp-West balancing authority; "
        "not EIA-930 hour-ending UTC"
    )
    out["provenance"] = (
        "reported FERC Form 714 PacifiCorp-West monthly NEL/generation/interchange/peak/minimum; "
        "regional BA evidence, not campus electricity"
    )
    out["provenance_class"] = "reported"
    cols = [
        "year", "month", "west_net_energy_for_load_mwh", "west_net_generation_mwh",
        "west_net_interchange_mwh", "west_monthly_peak_mw", "west_monthly_minimum_mw",
        "respondent_legal_name", "balancing_authority_area_name", "company_identifier",
        "filing_id", "respondent_code", "source_file", "timezone", "time_convention",
        "provenance", "provenance_class",
    ]
    return out[cols].sort_values(["year", "month"]).reset_index(drop=True)


def _localize_hour_ending(ferc_date: date, hour_ending: int) -> tuple[pd.Timestamp, str]:
    """Hour-ending local prevailing time → timezone-aware Pacific timestamp.

    Hour 24 is midnight at the start of the next local date. Spring-forward
    nonexistent clock times are shifted forward (filing may label the gap as
    hour 2). Ambiguous fall-back times use the first (DST) occurrence. The
    unrepeated fall-back physical hour is left missing; it is not interpolated.
    """
    note = ""
    if hour_ending == 24:
        naive = datetime(ferc_date.year, ferc_date.month, ferc_date.day) + timedelta(days=1)
        local = pd.Timestamp(naive).tz_localize(TZ_PACIFIC)
        return local, "hour_ending_24_next_local_midnight"
    naive = datetime(ferc_date.year, ferc_date.month, ferc_date.day, int(hour_ending), 0, 0)
    ts = pd.Timestamp(naive)
    loc = ts.tz_localize(TZ_PACIFIC, ambiguous=True, nonexistent="NaT")
    if pd.isna(loc):
        loc = ts.tz_localize(TZ_PACIFIC, nonexistent="shift_forward")
        note = "nonexistent_spring_forward_shifted"
    return loc, note


def extract_combined_hourly(path: Path, meta: dict) -> pd.DataFrame:
    contexts, facts, _ = parse_ixbrl(path)
    year = _report_year(facts, meta.get("report_year_from_name"))
    planning = _first_text(facts, "ferc:PlanningAreaName")
    respondent = _first_text(facts, "ferc:RespondentLegalName")
    tz_tags = [f["text"].strip().upper() for f in facts if f["name"] == "ferc:TimeZone" and f["text"]]
    tz_reported = ";".join(sorted(set(tz_tags))) if tz_tags else "PPT/PST/PDT"
    rows = []
    for f in facts:
        if f["name"] != HOURLY_CONCEPT:
            continue
        inst = contexts.get(f["context"], {}).get("instant")
        if not inst:
            continue
        date_s, time_s = inst.split("T")
        ferc_date = date.fromisoformat(date_s)
        hour_ending = int(time_s.split(":")[0])
        local, dst_note = _localize_hour_ending(ferc_date, hour_ending)
        rows.append(
            {
                "ferc_local_date": ferc_date.isoformat(),
                "hour_ending": hour_ending,
                "local_timestamp": local,
                "timestamp_utc": local.tz_convert("UTC") if pd.notna(local) else pd.NaT,
                "year_local": ferc_date.year,
                "month_local": ferc_date.month,
                "east_west_hourly_demand_mw": _num(f["attrs"], f["text"]),
                "dst_note": dst_note,
                "context_id": f["context"],
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["timestamp_utc"] = pd.to_datetime(out["timestamp_utc"], utc=True)
    dup = out["timestamp_utc"].duplicated(keep=False)
    if dup.any():
        # Duplicate UTC from reporting both spring HE2 (nonexistent) and HE3.
        keep_existing = ~dup | (out["dst_note"] == "")
        dropped = int((dup & ~keep_existing).sum())
        out = out.loc[keep_existing].copy()
        out.loc[out["timestamp_utc"].duplicated(keep="first"), "dst_note"] = (
            out.loc[out["timestamp_utc"].duplicated(keep="first"), "dst_note"].astype(str)
            + ";duplicate_utc_dropped"
        )
        out = out.drop_duplicates("timestamp_utc", keep="first")
        if dropped:
            out["dst_note"] = out["dst_note"].where(
                out["dst_note"].astype(str) != "",
                other="",
            )
    if out["timestamp_utc"].duplicated().any():
        raise ValueError(f"Non-unique UTC timestamps after DST normalization in {path.name}")
    out["report_year"] = year
    out["planning_area_name"] = planning
    out["respondent_legal_name"] = respondent
    out["timezone_reported"] = tz_reported
    out["timezone_normalized"] = TZ_PACIFIC
    out["time_convention"] = (
        "FERC Form 714 Schedule 2 hour-ending local prevailing Pacific time; "
        "not EIA-930 hour-ending UTC; not PacifiCorp-West hourly demand"
    )
    out["source_file"] = Path(path).name
    out["filing_id"] = meta.get("filing_id", "")
    out["provenance"] = (
        "reported FERC Form 714 PacifiCorp East+West combined planning-area hourly demand; "
        "not PACW-West and not campus electricity"
    )
    out["provenance_class"] = "reported"
    out["series_label"] = "pacificorp_east_west_combined_planning_area"
    return out.sort_values("timestamp_utc").reset_index(drop=True)


def eia_reported_usable(series: pd.Series) -> pd.Series:
    """Keep EIA reported demand that is physically possible for PACW.

    Does not substitute adjusted/imputed values. Out-of-range reported points
    (negatives and multi-GW spikes present in the Grid Monitor extract) are
    set to missing and counted in QA.
    """
    s = pd.to_numeric(series, errors="coerce")
    return s.where((s > EIA_REPORTED_MIN_MW) & (s <= EIA_REPORTED_MAX_MW))


def nel_identity_table(monthly: pd.DataFrame) -> pd.DataFrame:
    z = monthly.copy()
    z["nel_minus_gen_plus_interchange_mwh"] = (
        z["west_net_energy_for_load_mwh"]
        - (z["west_net_generation_mwh"] + z["west_net_interchange_mwh"])
    )
    return z[["year", "month", "nel_minus_gen_plus_interchange_mwh"]]


def compare_ferc_eia_monthly(west: pd.DataFrame, eia: pd.DataFrame) -> pd.DataFrame:
    e = eia.copy()
    e["timestamp_utc"] = pd.to_datetime(e["timestamp_utc"], utc=True)
    if "local_date" in e.columns:
        loc = pd.to_datetime(e["local_date"], errors="coerce")
        e["year_local"] = loc.dt.year
        e["month_local"] = loc.dt.month
    else:
        loc = e["timestamp_utc"].dt.tz_convert(TZ_PACIFIC)
        e["year_local"] = loc.dt.year
        e["month_local"] = loc.dt.month
    e["demand_reported_usable_mwh"] = eia_reported_usable(e["demand_reported_mwh"])
    agg = (
        e.groupby(["year_local", "month_local"], as_index=False)
        .agg(
            eia_demand_reported_mwh=("demand_reported_mwh", "sum"),
            eia_demand_reported_usable_mwh=("demand_reported_usable_mwh", "sum"),
            eia_demand_reported_usable_n=("demand_reported_usable_mwh", "count"),
            eia_demand_reported_usable_mean_mw=("demand_reported_usable_mwh", "mean"),
            eia_demand_adjusted_mwh=("demand_adjusted_mwh", "sum")
            if "demand_adjusted_mwh" in e.columns
            else ("demand_reported_mwh", "sum"),
            eia_demand_adjusted_mean_mw=("demand_adjusted_mwh", "mean")
            if "demand_adjusted_mwh" in e.columns
            else ("demand_reported_mwh", "mean"),
            eia_net_generation_reported_mwh=("net_generation_reported_mwh", "sum"),
            eia_total_interchange_reported_mwh=("total_interchange_reported_mwh", "sum"),
            eia_n_hours=("timestamp_utc", "size"),
        )
    )
    w = west.rename(columns={"year": "year_local", "month": "month_local"})
    j = w.merge(agg, on=["year_local", "month_local"], how="left")
    j["expected_hours"] = j.apply(
        lambda r: 24 * pd.Period(year=int(r.year_local), month=int(r.month_local), freq="M").days_in_month,
        axis=1,
    )
    j["overlap_status"] = np.select(
        [
            j["eia_n_hours"].fillna(0).le(0),
            (j["year_local"] == 2015) & j["eia_n_hours"].fillna(0).gt(0),
            j["year_local"].between(2016, 2018) & (j["eia_n_hours"] >= 0.9 * j["expected_hours"]),
        ],
        ["no_eia", "partial_2015", "full_overlap"],
        default="other",
    )
    j["ferc_nel_mean_mw"] = j["west_net_energy_for_load_mwh"] / j["expected_hours"]
    j["demand_bias_mwh"] = j["west_net_energy_for_load_mwh"] - j["eia_demand_reported_usable_mwh"]
    j["demand_pct_diff"] = 100.0 * (j["ferc_nel_mean_mw"] - j["eia_demand_reported_usable_mean_mw"]) / j["eia_demand_reported_usable_mean_mw"]
    j["demand_raw_reported_pct_diff"] = 100.0 * (
        j["west_net_energy_for_load_mwh"] - j["eia_demand_reported_mwh"]
    ) / j["eia_demand_reported_mwh"]
    j["generation_bias_mwh"] = j["west_net_generation_mwh"] - j["eia_net_generation_reported_mwh"]
    j["generation_pct_diff"] = 100.0 * j["generation_bias_mwh"] / j["eia_net_generation_reported_mwh"]
    j["interchange_bias_mwh"] = j["west_net_interchange_mwh"] - j["eia_total_interchange_reported_mwh"]
    j["interchange_pct_diff"] = 100.0 * j["interchange_bias_mwh"] / j["eia_total_interchange_reported_mwh"].replace(0, np.nan)
    j["demand_adjusted_pct_diff"] = 100.0 * (
        j["west_net_energy_for_load_mwh"] - j["eia_demand_adjusted_mwh"]
    ) / j["eia_demand_adjusted_mwh"]
    j["comparison_note"] = (
        "Primary comparison uses EIA demand_reported_mwh inside "
        f"({EIA_REPORTED_MIN_MW}, {EIA_REPORTED_MAX_MW}] MW (physically possible PACW). "
        "Adjusted/imputed EIA demand is sensitivity only and never replaces reported values. "
        "FERC NEL = reported net generation + net actual interchange. "
        "EIA demand is BA load; interchange sign conventions may differ."
    )
    return j


def monthly_consistency_summary(cmp_: pd.DataFrame) -> dict:
    out = {}
    for label, mask in (
        ("partial_2015", cmp_["overlap_status"].eq("partial_2015") & cmp_["eia_demand_reported_mwh"].notna()),
        ("full_2016_2018", cmp_["overlap_status"].eq("full_overlap") & cmp_["eia_demand_reported_mwh"].notna()),
    ):
        z = cmp_.loc[mask]
        if z.empty:
            out[label] = {"n_months": 0}
            continue
        d = z["demand_pct_diff"].to_numpy(float)
        out[label] = {
            "n_months": int(len(z)),
            "demand_mean_mw_ferc": float(z["ferc_nel_mean_mw"].mean()),
            "demand_mean_mw_eia_reported_usable": float(z["eia_demand_reported_usable_mean_mw"].mean()),
            "demand_bias_mean_mw": float((z["ferc_nel_mean_mw"] - z["eia_demand_reported_usable_mean_mw"]).mean()),
            "demand_mean_pct_diff": float(np.nanmean(d)),
            "demand_median_pct_diff": float(np.nanmedian(d)),
            "demand_correlation": float(z["ferc_nel_mean_mw"].corr(z["eia_demand_reported_usable_mean_mw"])),
            "ferc_nel_annual_sum_mwh": float(z["west_net_energy_for_load_mwh"].sum()),
            "eia_demand_reported_usable_sum_mwh": float(z["eia_demand_reported_usable_mwh"].sum()),
            "generation_mean_pct_diff": float(z["generation_pct_diff"].mean()),
            "interchange_mean_pct_diff": float(z["interchange_pct_diff"].mean()),
            "adjusted_demand_mean_pct_diff": float(z["demand_adjusted_pct_diff"].mean()),
            "raw_reported_energy_median_pct_diff": float(z["demand_raw_reported_pct_diff"].median()),
            "note": (
                "Primary monthly demand comparison is mean MW using EIA reported values "
                f"inside ({EIA_REPORTED_MIN_MW}, {EIA_REPORTED_MAX_MW}] MW. "
                "Adjusted demand is sensitivity only. Raw unfiltered reported energy is not used "
                "because the extract contains negative and multi-GW spikes."
            ),
        }
    return out


def backcast_west_hourly(west: pd.DataFrame, ew: pd.DataFrame) -> pd.DataFrame:
    """FERC-only affine shape: Dhat = mean_W + b * (D_EW - mean_EW), b>=0.

    Monthly energy closes exactly to West NEL. b is chosen to match West peak and
    minimum in least squares. EIA-930 is not used to fit b.
    """
    parts = []
    for (year, month), wrow in west.groupby(["year", "month"], sort=True):
        nel = float(wrow["west_net_energy_for_load_mwh"].iloc[0])
        peak = float(wrow["west_monthly_peak_mw"].iloc[0])
        minimum = float(wrow["west_monthly_minimum_mw"].iloc[0])
        m = ew[(ew["year_local"] == year) & (ew["month_local"] == month)].copy()
        if m.empty or not np.isfinite(nel):
            continue
        d = pd.to_numeric(m["east_west_hourly_demand_mw"], errors="coerce")
        h = int(d.notna().sum())
        if h == 0:
            continue
        mean_ew = float(d.mean())
        mean_w = nel / h
        max_ew = float(d.max())
        min_ew = float(d.min())
        d1 = max_ew - mean_ew
        d2 = min_ew - mean_ew
        t1 = peak - mean_w if np.isfinite(peak) else np.nan
        t2 = minimum - mean_w if np.isfinite(minimum) else np.nan
        num = 0.0
        den = 0.0
        if np.isfinite(d1) and np.isfinite(t1) and abs(d1) > 1e-9:
            num += d1 * t1
            den += d1 * d1
        if np.isfinite(d2) and np.isfinite(t2) and abs(d2) > 1e-9:
            num += d2 * t2
            den += d2 * d2
        b = max(0.0, num / den) if den > 0 else 0.0
        m["west_hourly_backcast_mw"] = mean_w + b * (d - mean_ew)
        m["west_hourly_backcast_mw"] = m["west_hourly_backcast_mw"].where(d.notna(), np.nan)
        m["b_m"] = b
        m["mean_west_mw"] = mean_w
        m["mean_east_west_mw"] = mean_ew
        m["west_nel_mwh"] = nel
        m["n_hours_month"] = h
        m["monthly_energy_closure_mwh"] = float(m["west_hourly_backcast_mw"].sum()) - nel
        parts.append(m)
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts, ignore_index=True)
    out["provenance"] = (
        "FERC-constrained hourly PACW-West proxy: West monthly NEL/peak/minimum with "
        "East+West intramonth shape; not reported PACW hourly demand; not campus electricity"
    )
    out["provenance_class"] = "proxy"
    out["source"] = "ferc714_west_monthly_plus_eastwest_shape"
    keep = [
        "timestamp_utc", "local_timestamp", "ferc_local_date", "hour_ending",
        "year_local", "month_local", "west_hourly_backcast_mw",
        "east_west_hourly_demand_mw", "b_m", "mean_west_mw", "mean_east_west_mw",
        "west_nel_mwh", "n_hours_month", "monthly_energy_closure_mwh",
        "dst_note", "provenance", "provenance_class", "source",
    ]
    return out[keep].sort_values("timestamp_utc").reset_index(drop=True)


def _metrics(pred, obs) -> dict:
    pred = np.asarray(pred, dtype=float)
    obs = np.asarray(obs, dtype=float)
    mask = np.isfinite(pred) & np.isfinite(obs)
    pred, obs = pred[mask], obs[mask]
    if pred.size == 0:
        return {k: np.nan for k in ("n", "corr", "mae", "rmse", "nrmse", "mean_bias")}
    err = pred - obs
    rmse = float(np.sqrt(np.mean(err ** 2)))
    scale = float(np.mean(np.abs(obs))) if np.mean(np.abs(obs)) > 0 else np.nan
    return {
        "n": int(pred.size),
        "corr": float(np.corrcoef(pred, obs)[0, 1]) if pred.size > 2 else np.nan,
        "mae": float(np.mean(np.abs(err))),
        "rmse": rmse,
        "nrmse": rmse / scale if np.isfinite(scale) else np.nan,
        "mean_bias": float(err.mean()),
    }


def validate_backcast(backcast: pd.DataFrame, eia: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    b = backcast.copy()
    e = eia.copy()
    b["timestamp_utc"] = pd.to_datetime(b["timestamp_utc"], utc=True)
    e["timestamp_utc"] = pd.to_datetime(e["timestamp_utc"], utc=True)
    e["demand_reported_usable_mwh"] = eia_reported_usable(e["demand_reported_mwh"])
    keep_cols = ["timestamp_utc", "demand_reported_mwh", "demand_reported_usable_mwh"]
    if "demand_adjusted_mwh" in e.columns:
        keep_cols.append("demand_adjusted_mwh")
    j = b.merge(e[keep_cols], on="timestamp_utc", how="inner")
    j_raw = j[j["demand_reported_mwh"].notna() & j["west_hourly_backcast_mw"].notna()].copy()
    j = j[j["demand_reported_usable_mwh"].notna() & j["west_hourly_backcast_mw"].notna()].copy()
    j["year"] = j["year_local"]

    def pack(z, pred_col, obs_col, subset):
        m = _metrics(z[pred_col], z[obs_col])
        m["subset"] = subset
        daily = (
            z.assign(day=z["timestamp_utc"].dt.floor("D"))
            .groupby("day")[[pred_col, obs_col]]
            .mean()
        )
        ldc_p = np.sort(pd.to_numeric(z[pred_col], errors="coerce").to_numpy(float))
        ldc_o = np.sort(pd.to_numeric(z[obs_col], errors="coerce").to_numpy(float))
        ldc_p = ldc_p[np.isfinite(ldc_p)][::-1]
        ldc_o = ldc_o[np.isfinite(ldc_o)][::-1]
        n = min(len(ldc_p), len(ldc_o))
        m["daily_mean_corr"] = float(daily[pred_col].corr(daily[obs_col])) if len(daily) > 2 else np.nan
        m["ldc_mae"] = float(np.mean(np.abs(ldc_p[:n] - ldc_o[:n]))) if n else np.nan
        return m

    rows = []
    for subset, z in (
        ("hourly_2016_2018", j[j.year.between(2016, 2018)]),
        ("hourly_2015_partial", j[j.year.eq(2015)]),
        ("hourly_2015_2018", j[j.year.between(2015, 2018)]),
    ):
        if z.empty:
            continue
        rows.append(pack(z, "west_hourly_backcast_mw", "demand_reported_usable_mwh", subset))
    raw16 = j_raw[j_raw["year_local"].between(2016, 2018)]
    if len(raw16):
        rows.append(pack(raw16, "west_hourly_backcast_mw", "demand_reported_mwh", "sensitivity_raw_reported_2016_2018"))
    if "demand_adjusted_mwh" in j.columns:
        adj = j[j.year.between(2016, 2018) & j["demand_adjusted_mwh"].notna()]
        if len(adj):
            rows.append(pack(adj, "west_hourly_backcast_mw", "demand_adjusted_mwh", "sensitivity_adjusted_2016_2018"))
    for year, z in j.groupby("year"):
        rows.append(pack(z, "west_hourly_backcast_mw", "demand_reported_usable_mwh", f"year_{int(year)}"))
    season = {12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM",
              6: "JJA", 7: "JJA", 8: "JJA", 9: "SON", 10: "SON", 11: "SON"}
    j["season"] = j["month_local"].map(season)
    for s, z in j.groupby("season"):
        z = z[z.year.between(2016, 2018)]
        if z.empty:
            continue
        rows.append(pack(z, "west_hourly_backcast_mw", "demand_reported_usable_mwh", f"season_{s}_2016_2018"))
    for hr, z in j[j.year.between(2016, 2018)].groupby("hour_ending"):
        rows.append(pack(z, "west_hourly_backcast_mw", "demand_reported_usable_mwh", f"hour_ending_{int(hr)}"))
    val = pd.DataFrame(rows)
    primary = next((r for r in rows if r["subset"] == "hourly_2016_2018"), {})
    return val, primary


def plot_validation(backcast: pd.DataFrame, eia: pd.DataFrame, path: Path) -> None:
    import matplotlib.pyplot as plt

    b = backcast.copy()
    e = eia.copy()
    b["timestamp_utc"] = pd.to_datetime(b["timestamp_utc"], utc=True)
    e["timestamp_utc"] = pd.to_datetime(e["timestamp_utc"], utc=True)
    e["demand_reported_usable_mwh"] = eia_reported_usable(e["demand_reported_mwh"])
    j = b.merge(e[["timestamp_utc", "demand_reported_usable_mwh"]], on="timestamp_utc", how="inner")
    j = j[j.year_local.between(2016, 2018) & j["demand_reported_usable_mwh"].notna() & j["west_hourly_backcast_mw"].notna()]
    fig, axes = plt.subplots(3, 1, figsize=(10.5, 9.2), constrained_layout=True)
    axes[0].plot(j["demand_reported_usable_mwh"], j["west_hourly_backcast_mw"], ".", ms=2, alpha=0.15, color="#1d4ed8")
    lim = [
        float(np.nanmin([j.demand_reported_usable_mwh.min(), j.west_hourly_backcast_mw.min()])),
        float(np.nanmax([j.demand_reported_usable_mwh.max(), j.west_hourly_backcast_mw.max()])),
    ]
    axes[0].plot(lim, lim, color="#6b7280", lw=1)
    axes[0].set(xlabel="EIA-930 PACW demand reported, usable (MW)", ylabel="FERC-only backcast (MW)",
                title="2016–2018 hourly overlap (construction constraints excluded)")
    axes[0].grid(alpha=0.3)
    ldc_p = np.sort(j["west_hourly_backcast_mw"].to_numpy(float))[::-1]
    ldc_o = np.sort(j["demand_reported_usable_mwh"].to_numpy(float))[::-1]
    x = np.linspace(0, 1, len(ldc_o))
    axes[1].plot(x, ldc_o, label="EIA-930 reported (usable)", color="#111827")
    axes[1].plot(np.linspace(0, 1, len(ldc_p)), ldc_p, label="FERC-only proxy", color="#1d4ed8", alpha=0.85)
    axes[1].set(xlabel="Duration fraction", ylabel="MW", title="Load-duration curves, 2016–2018")
    axes[1].legend(frameon=False)
    axes[1].grid(alpha=0.3)
    hod = j.groupby("hour_ending")[["west_hourly_backcast_mw", "demand_reported_usable_mwh"]].mean()
    axes[2].plot(hod.index, hod["demand_reported_usable_mwh"], label="EIA-930 reported (usable)")
    axes[2].plot(hod.index, hod["west_hourly_backcast_mw"], label="FERC-only proxy")
    axes[2].set(xlabel="FERC hour-ending (local)", ylabel="Mean MW", title="Hour-of-day mean, 2016–2018")
    axes[2].legend(frameon=False)
    axes[2].grid(alpha=0.3)
    fig.suptitle("FERC-only PACW-West hourly proxy vs EIA-930 reported demand (usable)", fontsize=12)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def build_extended_demand(eia: pd.DataFrame, backcast: pd.DataFrame) -> pd.DataFrame:
    e = eia.copy()
    e["timestamp_utc"] = pd.to_datetime(e["timestamp_utc"], utc=True)
    e = e.sort_values("timestamp_utc")
    first_eia = e.loc[e["demand_reported_mwh"].notna(), "timestamp_utc"].min()
    b = backcast.copy()
    b["timestamp_utc"] = pd.to_datetime(b["timestamp_utc"], utc=True)
    pre = b.loc[b["timestamp_utc"] < first_eia, ["timestamp_utc", "west_hourly_backcast_mw", "year_local", "month_local"]].copy()
    pre = pre.rename(columns={"west_hourly_backcast_mw": "demand_mwh"})
    pre["provenance"] = (
        "FERC-constrained PACW-West hourly proxy before EIA-930 coverage; "
        "not reported PACW hourly demand; not campus electricity"
    )
    pre["provenance_class"] = "proxy"
    pre["source"] = "ferc714_backcast"
    eia_part = pd.DataFrame(
        {
            "timestamp_utc": e["timestamp_utc"],
            "demand_mwh": e["demand_reported_mwh"],
            "year_local": pd.to_datetime(e["local_date"]).dt.year if "local_date" in e.columns else e["timestamp_utc"].dt.tz_convert(TZ_PACIFIC).dt.year,
            "month_local": pd.to_datetime(e["local_date"]).dt.month if "local_date" in e.columns else e["timestamp_utc"].dt.tz_convert(TZ_PACIFIC).dt.month,
            "provenance": "reported EIA-930 PACW demand; balancing-authority operations; not campus electricity",
            "provenance_class": "reported",
            "source": "eia930_pacw",
        }
    )
    out = pd.concat([pre, eia_part], ignore_index=True).sort_values("timestamp_utc")
    out = out.drop_duplicates("timestamp_utc", keep="last")
    if out["timestamp_utc"].duplicated().any():
        raise ValueError("Extended PACW demand has duplicate UTC timestamps")
    return out.reset_index(drop=True)


def _qa_rows(items: dict) -> pd.DataFrame:
    return pd.DataFrame([{"item": k, "value": v} for k, v in items.items()])


def main() -> None:
    filings = discover_filings()
    if filings.empty:
        raise SystemExit(f"No FERC Form 714 HTML files in {RAW}")
    west_parts = []
    ew_parts = []
    for row in filings.itertuples(index=False):
        meta = {
            "path": row.path,
            "filename": row.filename,
            "kind": row.kind,
            "report_year_from_name": row.report_year_from_name,
            "filing_id": row.filing_id,
            "respondent_code_from_name": row.respondent_code_from_name,
        }
        path = Path(meta["path"])
        if meta["kind"] == "pacificorp_west_monthly":
            west_parts.append(extract_west_monthly(path, meta))
        elif meta["kind"] == "east_west_combined_hourly":
            ew_parts.append(extract_combined_hourly(path, meta))
        else:
            raise ValueError(f"Unclassified FERC filing: {path.name}")
    west = pd.concat(west_parts, ignore_index=True).sort_values(["year", "month"])
    ew = pd.concat(ew_parts, ignore_index=True).sort_values("timestamp_utc")
    if west.duplicated(["year", "month"]).any():
        raise ValueError("Duplicate West year×month rows")
    if ew["timestamp_utc"].duplicated().any():
        raise ValueError("Combined East+West hourly UTC timestamps are not unique")
    ident = nel_identity_table(west)
    max_ident = float(ident["nel_minus_gen_plus_interchange_mwh"].abs().max())

    OUT.mkdir(parents=True, exist_ok=True)
    west.to_csv(OUT / "pacw_west_monthly.csv", index=False)
    ew.to_csv(OUT / "pacificorp_east_west_hourly.csv", index=False)

    backcast = backcast_west_hourly(west, ew)
    backcast.to_csv(OUT / "pacw_hourly_backcast.csv", index=False)
    if not np.allclose(backcast.groupby(["year_local", "month_local"])["west_hourly_backcast_mw"].sum(),
                       backcast.groupby(["year_local", "month_local"])["west_nel_mwh"].first(),
                       atol=1e-4, rtol=0):
        # grouped allclose on series index alignment
        chk = backcast.groupby(["year_local", "month_local"]).agg(
            s=("west_hourly_backcast_mw", "sum"), n=("west_nel_mwh", "first")
        )
        if (chk["s"] - chk["n"]).abs().max() > 1e-3:
            raise ValueError("Backcast monthly energy does not close to West NEL")

    eia = pd.read_csv(EIA_HOURLY) if EIA_HOURLY.exists() else pd.DataFrame()
    cmp_ = pd.DataFrame()
    val = pd.DataFrame()
    primary = {}
    monthly_summary = {}
    if len(eia):
        cmp_ = compare_ferc_eia_monthly(west, eia)
        cmp_.to_csv(OUT_MONTHLY_CMP, index=False)
        monthly_summary = monthly_consistency_summary(cmp_)
        val, primary = validate_backcast(backcast, eia)
        val.to_csv(OUT_VAL, index=False)
        plot_validation(backcast, eia, OUT_PNG)
        extended = build_extended_demand(eia, backcast)
        EXTENDED.parent.mkdir(parents=True, exist_ok=True)
        extended.to_csv(EXTENDED, index=False)
        # never overwrite EIA canonical
        if not EIA_CANONICAL.exists():
            raise ValueError("EIA canonical pacw_hourly.csv missing after FERC prepare")
    full = monthly_summary.get("full_2016_2018", {})
    demand_pct = abs(full.get("demand_median_pct_diff", float("nan")))
    hourly_corr = primary.get("corr", float("nan"))
    compatible = bool(np.isfinite(demand_pct) and demand_pct < 15 and np.isfinite(hourly_corr) and hourly_corr >= 0.7)
    promote = bool(compatible and np.isfinite(hourly_corr) and hourly_corr >= 0.85 and primary.get("nrmse", 1) < 0.25)
    qa = {
        "n_html_filings": int(len(filings)),
        "west_years": ",".join(map(str, sorted(west.year.unique()))),
        "west_n_year_month": int(len(west)),
        "ew_n_hours": int(len(ew)),
        "ew_utc_unique": bool(ew["timestamp_utc"].is_unique),
        "nel_identity_max_abs_mwh": max_ident,
        "backcast_n_hours": int(len(backcast)),
        "eia_canonical_untouched": str(EIA_CANONICAL),
        "series_not_labeled_pacw_west": "pacificorp_east_west_combined_planning_area",
        "monthly_consistency_json": json.dumps(monthly_summary),
        "hourly_2016_2018_corr": primary.get("corr", ""),
        "hourly_2016_2018_mae": primary.get("mae", ""),
        "hourly_2016_2018_rmse": primary.get("rmse", ""),
        "hourly_2016_2018_nrmse": primary.get("nrmse", ""),
        "hourly_2016_2018_mean_bias": primary.get("mean_bias", ""),
        "hourly_2016_2018_daily_mean_corr": primary.get("daily_mean_corr", ""),
        "hourly_2016_2018_ldc_mae": primary.get("ldc_mae", ""),
        "ferc_eia_monthly_compatible": compatible,
        "hourly_proxy_promotable": promote,
        "proxy_role": (
            "candidate_2011_mid2015_hourly_pacw_demand_proxy"
            if promote
            else "diagnostic_proxy_not_promoted_as_observed_pacw_hourly"
        ),
        "campus_electricity": "never; FERC remains regional/grid context",
        "time_semantics": (
            "FERC=hour-ending local Pacific prevailing; EIA-930=hour-ending UTC; kept separate"
        ),
    }
    _qa_rows(qa).to_csv(OUT_QA, index=False)
    print(
        f"West monthly {len(west)} rows; East+West hourly {len(ew):,}; "
        f"backcast {len(backcast):,}; NEL identity max |err|={max_ident:.3f} MWh; "
        f"2016-2018 corr={primary.get('corr', float('nan')):.3f}; "
        f"promote={promote}"
    )


if __name__ == "__main__":
    main()
