"""Render pipeline diagrams from canonical source/model edge tables.

Does not invent relationships: mermaid links are the CSV edges; PNG arrows
are the same implemented lineage, laid out so branches stay distinct.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Patch

from pipeline_report_catalog import model_io_edges, source_quantity_edges


def _escape(label: str) -> str:
    return (
        str(label)
        .replace('"', "#quot;")
        .replace("[", "(")
        .replace("]", ")")
        .replace("{", "(")
        .replace("}", ")")
    )


def write_source_tree_mmd(path: Path, sources) -> Path:
    """Mermaid source tree from source_quantity_edges.csv mappings."""
    src = sources.set_index("source_id")
    edges = source_quantity_edges()
    groups: dict[str, list[str]] = {}
    for sid in sorted({e["source_id"] for e in edges}):
        grp = str(src.loc[sid, "branch_group"]) if sid in src.index else "other"
        groups.setdefault(grp, []).append(sid)
    qids = sorted({e["quantity_id"] for e in edges})

    lines = [
        "%% Generated from outputs/pipeline_report/source_quantity_edges.csv",
        "%% OWRD City/POD and USGS HUC12 are parallel context; neither produces the other.",
        "flowchart TB",
        "  classDef src fill:#eff6ff,stroke:#1d4ed8,color:#111",
        "  classDef qty fill:#f8fafc,stroke:#334155,color:#111",
    ]
    for grp, sids in groups.items():
        gid = "G_" + "".join(ch if ch.isalnum() else "_" for ch in grp)
        lines.append(f"  subgraph {gid}[{_escape(grp)}]")
        for sid in sids:
            lines.append(f"    {sid}[{_escape(sid)}]")
        lines.append("  end")
    lines.append("  subgraph QTY[Quantities linked by canonical source edges]")
    for qid in qids:
        lines.append(f"    {qid}[{_escape(qid)}]")
    lines.append("  end")
    for e in edges:
        lines.append(f"  {e['source_id']} -->|{e['role']}| {e['quantity_id']}")
    # Explicit non-edge note: do not draw OWRD → USGS or USGS → OWRD
    lines.append("  classDef note fill:#fff7ed,stroke:#c2410c,color:#111")
    lines.append(
        "  PARALLEL[OWRD City/POD and USGS HUC12 are parallel external context — no producer/consumer edge]:::note"
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_quantity_mmd(path: Path) -> Path:
    """Mermaid model-quantity graph from model_io_edges.csv mappings."""
    edges = model_io_edges()
    lines = [
        "%% Generated from outputs/pipeline_report/model_io_edges.csv",
        "%% Conditional reconstruction, stochastic scenario, and annual water candidates are separate.",
        "%% Energy-only water model has no evaporation input.",
        "flowchart TB",
        "  classDef mdl fill:#fef3c7,stroke:#b45309,color:#111",
        "  classDef qty fill:#e0f2fe,stroke:#0369a1,color:#111",
        "",
        "  subgraph COND[Conditional branch]",
        "    Q_E_FAC_C[Q_E_FAC Meta annual facility electricity]",
        "    Q_WEATHER_C[Q_WEATHER]",
        "    M_ELEC_CLOSURE[M_ELEC_CLOSURE annual latent IT-scale closure]",
        "    Q_P_IT_C[Q_P_IT fitted hourly IT power]",
        "    Q_P_FAC_C[Q_P_FAC fitted hourly facility power]",
        "    M_GRAYBOX[M_GRAYBOX gray-box evaporation]",
        "    Q_W_EVAP_C[Q_W_EVAP raw evaporation]",
        "    M_WATER_SCALE_GLOBAL[M_WATER_SCALE_GLOBAL train-only conditional water scale]",
        "    Q_W_WITH_C[Q_W_WITH annual water target]",
        "    Q_WATER_PROXY[Q_WATER_PROXY annual water prediction]",
        "  end",
        "  Q_E_FAC_C -->|target/input| M_ELEC_CLOSURE",
        "  Q_WEATHER_C -->|input| M_ELEC_CLOSURE",
        "  Q_WEATHER_C -->|input| M_GRAYBOX",
        "  M_ELEC_CLOSURE -->|output| Q_P_IT_C",
        "  M_ELEC_CLOSURE -->|output| Q_P_FAC_C",
        "  Q_P_IT_C -->|input| M_GRAYBOX",
        "  M_GRAYBOX -->|output| Q_W_EVAP_C",
        "  M_GRAYBOX -->|output| Q_P_FAC_C",
        "  Q_W_EVAP_C -->|input| M_WATER_SCALE_GLOBAL",
        "  Q_W_WITH_C -->|target| M_WATER_SCALE_GLOBAL",
        "  M_WATER_SCALE_GLOBAL -->|output| Q_WATER_PROXY",
        "",
        "  subgraph STOCH[Stochastic branch — separate from conditional reconstruction]",
        "    Q_ARRIVALS[Q_ARRIVALS scenario workload]",
        "    Q_UTILIZATION[Q_UTILIZATION / IT-power shape]",
        "    Q_E_FAC_S[Q_E_FAC Meta annual electricity]",
        "    M_STOCHASTIC[M_STOCHASTIC annual scaling]",
        "    Q_P_FAC_S[Q_P_FAC scenario facility]",
        "    Q_W_EVAP_S[Q_W_EVAP scenario cooling/evaporation]",
        "  end",
        "  Q_ARRIVALS -->|output| M_STOCHASTIC",
        "  M_STOCHASTIC -->|output| Q_UTILIZATION",
        "  Q_E_FAC_S -->|target| M_STOCHASTIC",
        "  M_STOCHASTIC -->|output| Q_P_FAC_S",
        "  M_STOCHASTIC -->|output| Q_W_EVAP_S",
        "",
        "  subgraph WATER[Separate annual water predictive models]",
        "    Q_E_FAC_W[Q_E_FAC]",
        "    Q_W_EVAP_W[Q_W_EVAP gray-box annual raw evaporation]",
        "    Q_W_WITH_W[Q_W_WITH]",
        "    M_WATER_ENERGY_NULL[M_WATER_ENERGY_NULL energy-only — no evaporation input]",
        "    M_WATER_EVAP_PHYS[M_WATER_EVAP_PHYS evaporation-only]",
        "    M_WATER_TWOCOMP[M_WATER_TWOCOMP electricity + evaporation NNLS]",
        "  end",
        "  Q_E_FAC_W -->|input| M_WATER_ENERGY_NULL",
        "  Q_W_WITH_W -->|target| M_WATER_ENERGY_NULL",
        "  Q_W_EVAP_W -->|input| M_WATER_EVAP_PHYS",
        "  Q_W_WITH_W -->|target| M_WATER_EVAP_PHYS",
        "  Q_E_FAC_W -->|input| M_WATER_TWOCOMP",
        "  Q_W_EVAP_W -->|input| M_WATER_TWOCOMP",
        "  Q_W_WITH_W -->|target| M_WATER_TWOCOMP",
        "",
        "  subgraph EXT[Parallel external / contextual evidence — not producer/consumer of each other]",
        "    Q_CITY_PROD[Q_CITY_PROD OWRD City production]",
        "    Q_DIRECT_POD[Q_DIRECT_POD Vitesse/Facebook POD]",
        "    Q_USGS_PS[Q_USGS_PS HUC12 public-supply]",
        "    Q_IWA_AVAIL[Q_IWA_AVAIL routed IWA availability]",
        "    Q_IRRIGATION[Q_IRRIGATION HUC12 irrigation]",
        "    M_OWRD_EXTERNAL[M_OWRD_EXTERNAL]",
        "    M_IWA_IDENTITY[M_IWA_IDENTITY]",
        "    Q_SCOPE2_META[Q_SCOPE2_META]",
        "    Q_SCOPE2_EGRID[Q_SCOPE2_EGRID]",
        "    M_EGRID_BENCH[M_EGRID_BENCH accounting benchmark]",
        "  end",
        "  Q_CITY_PROD -->|validation| M_OWRD_EXTERNAL",
        "  Q_DIRECT_POD -->|validation| M_OWRD_EXTERNAL",
        "  Q_IWA_STRFLOW[Q_IWA_STRFLOW] -->|input| M_IWA_IDENTITY",
        "  Q_IWA_CONSUM[Q_IWA_CONSUM] -->|input| M_IWA_IDENTITY",
        "  M_IWA_IDENTITY -->|output| Q_IWA_AVAIL",
        "  Q_E_FAC_W -->|input| M_EGRID_BENCH",
        "  M_EGRID_BENCH -->|output| Q_SCOPE2_EGRID",
        "  Q_SCOPE2_META -->|benchmark| M_EGRID_BENCH",
        "",
        "  %% Remaining canonical model_io edges (same table; IDs not duplicated above)",
    ]
    shown = {
        ("M_ELEC_CLOSURE", "Q_E_FAC", "target"),
        ("M_ELEC_CLOSURE", "Q_E_FAC", "input"),
        ("M_ELEC_CLOSURE", "Q_WEATHER", "input"),
        ("M_ELEC_CLOSURE", "Q_P_IT", "output"),
        ("M_ELEC_CLOSURE", "Q_P_FAC", "output"),
        ("M_GRAYBOX", "Q_WEATHER", "input"),
        ("M_GRAYBOX", "Q_P_IT", "input"),
        ("M_GRAYBOX", "Q_W_EVAP", "output"),
        ("M_GRAYBOX", "Q_P_FAC", "output"),
        ("M_WATER_SCALE_GLOBAL", "Q_W_EVAP", "input"),
        ("M_WATER_SCALE_GLOBAL", "Q_W_WITH", "target"),
        ("M_WATER_SCALE_GLOBAL", "Q_WATER_PROXY", "output"),
        ("M_STOCHASTIC", "Q_ARRIVALS", "output"),
        ("M_STOCHASTIC", "Q_UTILIZATION", "output"),
        ("M_STOCHASTIC", "Q_E_FAC", "target"),
        ("M_STOCHASTIC", "Q_P_FAC", "output"),
        ("M_STOCHASTIC", "Q_W_EVAP", "output"),
        ("M_WATER_ENERGY_NULL", "Q_E_FAC", "input"),
        ("M_WATER_ENERGY_NULL", "Q_W_WITH", "target"),
        ("M_WATER_EVAP_PHYS", "Q_W_EVAP", "input"),
        ("M_WATER_EVAP_PHYS", "Q_W_WITH", "target"),
        ("M_WATER_TWOCOMP", "Q_E_FAC", "input"),
        ("M_WATER_TWOCOMP", "Q_W_EVAP", "input"),
        ("M_WATER_TWOCOMP", "Q_W_WITH", "target"),
        ("M_OWRD_EXTERNAL", "Q_CITY_PROD", "validation"),
        ("M_OWRD_EXTERNAL", "Q_DIRECT_POD", "validation"),
        ("M_IWA_IDENTITY", "Q_IWA_STRFLOW", "input"),
        ("M_IWA_IDENTITY", "Q_IWA_CONSUM", "input"),
        ("M_IWA_IDENTITY", "Q_IWA_AVAIL", "output"),
        ("M_EGRID_BENCH", "Q_E_FAC", "input"),
        ("M_EGRID_BENCH", "Q_SCOPE2_EGRID", "output"),
        ("M_EGRID_BENCH", "Q_SCOPE2_META", "benchmark"),
    }
    extra = [
        e for e in edges
        if (e["model_id"], e["quantity_id"], e["io_role"]) not in shown
    ]
    if extra:
        lines.append("  subgraph REST[Other canonical model I/O from model_io_edges.csv]")
        declared = {
            "M_ELEC_CLOSURE", "M_GRAYBOX", "M_WATER_SCALE_GLOBAL", "M_STOCHASTIC",
            "M_WATER_ENERGY_NULL", "M_WATER_EVAP_PHYS", "M_WATER_TWOCOMP",
            "M_OWRD_EXTERNAL", "M_IWA_IDENTITY", "M_EGRID_BENCH",
            "Q_CITY_PROD", "Q_DIRECT_POD", "Q_USGS_PS", "Q_IWA_AVAIL", "Q_IRRIGATION",
            "Q_SCOPE2_META", "Q_SCOPE2_EGRID", "Q_IWA_STRFLOW", "Q_IWA_CONSUM",
            "Q_ARRIVALS", "Q_UTILIZATION",
        }
        extra_nodes = sorted(
            ({e["model_id"] for e in extra} | {e["quantity_id"] for e in extra}) - declared
        )
        for n in extra_nodes:
            lines.append(f"    {n}[{_escape(n)}]")
        lines.append("  end")
        for e in extra:
            lines.append(f"  {e['model_id']} -->|{e['io_role']}| {e['quantity_id']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _box(ax, x, y, w, h, text, color, fontsize=7):
    p = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.012,rounding_size=0.06",
        facecolor=color,
        edgecolor="#1f2937",
        linewidth=0.7,
    )
    ax.add_patch(p)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fontsize, wrap=True)
    return (x, y, w, h)


def _arrow(ax, a, b, text="", color="#111827", side="h"):
    """Visible directional arrow between two boxes (x,y,w,h)."""
    ax1, ay1, aw, ah = a
    bx, by, bw, bh = b
    if side == "h":
        x1, y1 = ax1 + aw, ay1 + ah / 2
        x2, y2 = bx, by + bh / 2
    elif side == "hl":
        x1, y1 = ax1, ay1 + ah / 2
        x2, y2 = bx + bw, by + bh / 2
    elif side == "v":
        x1, y1 = ax1 + aw / 2, ay1
        x2, y2 = bx + bw / 2, by + bh
    else:
        x1, y1 = ax1 + aw / 2, ay1 + ah
        x2, y2 = bx + bw / 2, by
    ax.annotate(
        "",
        xy=(x2, y2),
        xytext=(x1, y1),
        arrowprops=dict(arrowstyle="-|>", color=color, lw=1.35, mutation_scale=11),
    )
    if text:
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.11, text, ha="center", va="bottom", fontsize=6.0, color=color)


def render_source_tree_png(path: Path) -> Path:
    """PNG with visible arrows. Layout follows canonical lineage, not grouped boxes alone."""
    fig, ax = plt.subplots(figsize=(15.4, 11.2))
    ax.set_xlim(0, 15.4)
    ax.set_ylim(0, 11.2)
    ax.axis("off")
    ax.set_title(
        "Data-source / quantity tree (arrows from canonical source_quantity_edges and model_io_edges)",
        loc="left",
        fontsize=11,
        pad=6,
    )

    ax.add_patch(FancyBboxPatch((0.15, 6.55), 15.1, 4.45, boxstyle="round,pad=0.02",
                                facecolor="#eff6ff", edgecolor="#93c5fd", alpha=0.55, linewidth=0.8))
    ax.text(0.25, 10.82, "Conditional branch", fontsize=9, fontweight="bold", color="#1e3a8a")

    meta_e = _box(ax, 0.3, 9.55, 2.15, 0.85, "Meta annual\nfacility electricity\nQ_E_FAC", "#dbeafe", 6.2)
    wx = _box(ax, 0.3, 8.35, 2.15, 0.85, "KRDM weather\nNOAA_GH_KRDM\nQ_WEATHER", "#ecfccb", 6.2)
    clos = _box(ax, 3.0, 8.95, 2.25, 0.95, "annual latent\nIT-scale closure\nM_ELEC_CLOSURE", "#fed7aa", 6.2)
    pit = _box(ax, 5.7, 8.95, 2.2, 0.95, "fitted hourly\nIT / facility power\nQ_P_IT, Q_P_FAC", "#fde68a", 6.2)
    gray = _box(ax, 8.35, 8.95, 2.15, 0.95, "gray-box\nevaporation\nM_GRAYBOX", "#fbcfe8", 6.2)
    scale = _box(ax, 10.85, 8.95, 2.2, 0.95, "train-only\nconditional water scale\nM_WATER_SCALE_GLOBAL", "#fde68a", 6.0)
    wpred = _box(ax, 13.15, 8.95, 1.95, 0.95, "annual water\nprediction\nQ_WATER_PROXY", "#ddd6fe", 6.2)
    meta_w = _box(ax, 10.85, 7.55, 2.2, 0.75, "Meta annual withdrawal\nQ_W_WITH (target)", "#dbeafe", 6.0)
    _arrow(ax, meta_e, clos, "target")
    _arrow(ax, wx, clos, "input")
    _arrow(ax, clos, pit, "output")
    _arrow(ax, pit, gray, "P_IT in")
    ax.annotate("", xy=(8.35, 9.15), xytext=(2.45, 8.75),
                arrowprops=dict(arrowstyle="-|>", color="#3f6212", lw=1.1, mutation_scale=10))
    ax.text(5.2, 8.55, "weather input", fontsize=6, color="#3f6212")
    _arrow(ax, gray, scale, "Q_W_EVAP")
    _arrow(ax, scale, wpred, "output")
    ax.annotate("", xy=(10.85 + 1.1, 8.95), xytext=(10.85 + 1.1, 8.30),
                arrowprops=dict(arrowstyle="-|>", color="#1d4ed8", lw=1.2, mutation_scale=10))
    ax.text(13.15, 8.35, "target", fontsize=6, color="#1d4ed8")

    ax.add_patch(FancyBboxPatch((0.15, 4.55), 15.1, 1.85, boxstyle="round,pad=0.02",
                                facecolor="#f5f3ff", edgecolor="#c4b5fd", alpha=0.55, linewidth=0.8))
    ax.text(0.25, 6.18, "Stochastic branch (separate)", fontsize=9, fontweight="bold", color="#5b21b6")
    wl = _box(ax, 0.3, 4.75, 2.2, 0.85, "scenario workload\nQ_ARRIVALS", "#e9d5ff", 6.2)
    util = _box(ax, 3.0, 4.75, 2.3, 0.85, "scenario utilization /\nIT-power shape", "#e9d5ff", 6.2)
    meta_es = _box(ax, 5.8, 4.75, 2.2, 0.85, "Meta annual\nelectricity Q_E_FAC", "#dbeafe", 6.2)
    stoch = _box(ax, 8.5, 4.75, 2.3, 0.85, "annual scaling\nM_STOCHASTIC", "#fed7aa", 6.2)
    scen = _box(ax, 11.3, 4.75, 3.5, 0.85, "scenario facility / cooling quantities\nQ_P_FAC, Q_W_EVAP, …", "#fbcfe8", 6.2)
    _arrow(ax, wl, util, "scenario")
    _arrow(ax, util, stoch, "shape")
    _arrow(ax, meta_es, stoch, "annual scaling")
    _arrow(ax, stoch, scen, "output")

    ax.add_patch(FancyBboxPatch((0.15, 2.35), 15.1, 2.05, boxstyle="round,pad=0.02",
                                facecolor="#fff7ed", edgecolor="#fdba74", alpha=0.55, linewidth=0.8))
    ax.text(0.25, 4.18, "Separate annual water predictive models  (energy-only has NO evaporation input)",
            fontsize=9, fontweight="bold", color="#9a3412")
    e_only_in = _box(ax, 0.3, 2.55, 2.0, 0.8, "Meta annual E\nQ_E_FAC", "#dbeafe", 6.2)
    e_only = _box(ax, 2.7, 2.55, 2.15, 0.8, "energy-only\nM_WATER_ENERGY_NULL", "#fde68a", 6.0)
    evap_in = _box(ax, 5.3, 2.55, 2.15, 0.8, "gray-box annual\nraw evaporation", "#fbcfe8", 6.0)
    evap_m = _box(ax, 7.8, 2.55, 2.15, 0.8, "evaporation-only\nM_WATER_EVAP_PHYS", "#fde68a", 6.0)
    two_in = _box(ax, 10.3, 2.55, 2.15, 0.8, "electricity +\nevaporation", "#fed7aa", 6.0)
    two_m = _box(ax, 12.8, 2.55, 2.15, 0.8, "two-component\nNNLS", "#fde68a", 6.0)
    _arrow(ax, e_only_in, e_only, "input")
    _arrow(ax, evap_in, evap_m, "input")
    _arrow(ax, two_in, two_m, "inputs")

    ax.add_patch(FancyBboxPatch((0.15, 0.15), 15.1, 2.05, boxstyle="round,pad=0.02",
                                facecolor="#ecfeff", edgecolor="#67e8f9", alpha=0.5, linewidth=0.8))
    ax.text(0.25, 1.95, "Parallel external / contextual evidence  (no arrow from OWRD to USGS or USGS to OWRD)",
            fontsize=9, fontweight="bold", color="#155e75")
    city = _box(ax, 0.3, 0.4, 2.05, 0.85, "OWRD City\nproduction\nQ_CITY_PROD", "#cffafe", 6.0)
    pod = _box(ax, 2.5, 0.4, 2.05, 0.85, "OWRD Vitesse/\nFacebook POD\nQ_DIRECT_POD", "#cffafe", 6.0)
    iwa = _box(ax, 5.0, 0.4, 2.15, 0.85, "USGS IWA routed\nQ_IWA_*", "#fae8ff", 6.0)
    usgs = _box(ax, 7.3, 0.4, 2.15, 0.85, "USGS HUC12\nPS / irrigation", "#fae8ff", 6.0)
    egrid = _box(ax, 9.7, 0.4, 2.2, 0.85, "eGRID NWPP × Meta MWh\naccounting benchmark", "#fef3c7", 5.8)
    s2 = _box(ax, 12.1, 0.4, 2.8, 0.85, "Meta location Scope 2\n(same Meta MWh; not independent validation)", "#dbeafe", 5.7)
    _arrow(ax, egrid, s2, "benchmark")
    ax.text(3.7, 1.35, "parallel — no edge", fontsize=7, color="#0f766e", ha="center")
    ax.text(6.2, 1.35, "parallel — no edge", fontsize=7, color="#7e22ce", ha="center")
    ax.legend(
        handles=[
            Patch(facecolor="#dbeafe", edgecolor="#1f2937", label="Meta campus reported"),
            Patch(facecolor="#ecfccb", edgecolor="#1f2937", label="weather"),
            Patch(facecolor="#fed7aa", edgecolor="#1f2937", label="model"),
            Patch(facecolor="#cffafe", edgecolor="#1f2937", label="OWRD context"),
            Patch(facecolor="#fae8ff", edgecolor="#1f2937", label="USGS HUC12 context"),
        ],
        loc="lower right",
        fontsize=7,
        frameon=False,
        ncol=5,
        bbox_to_anchor=(1.0, -0.02),
    )
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def render_quantity_png(path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(15.2, 10.6))
    ax.set_xlim(0, 15.2)
    ax.set_ylim(0, 10.6)
    ax.axis("off")
    ax.set_title(
        "Model–quantity dependency from model_io_edges.csv (conditional ≠ stochastic ≠ annual water candidates)",
        loc="left",
        fontsize=10.5,
        pad=6,
    )

    ax.add_patch(FancyBboxPatch((0.15, 6.7), 14.9, 3.7, boxstyle="round,pad=0.02",
                                facecolor="#eff6ff", edgecolor="#93c5fd", alpha=0.5))
    ax.text(0.25, 10.2, "Conditional: Meta E + weather → latent IT closure → hourly IT/facility → gray-box evap → train-only scale → water pred",
            fontsize=8, fontweight="bold", color="#1e3a8a")
    n = {}
    n["e"] = _box(ax, 0.3, 8.85, 1.9, 0.85, "Q_E_FAC", "#dbeafe", 7)
    n["wx"] = _box(ax, 0.3, 7.55, 1.9, 0.85, "Q_WEATHER", "#ecfccb", 7)
    n["cl"] = _box(ax, 2.55, 8.2, 2.15, 0.9, "M_ELEC_CLOSURE", "#fed7aa", 6.5)
    n["pit"] = _box(ax, 5.05, 8.2, 1.9, 0.9, "Q_P_IT / Q_P_FAC", "#fde68a", 6.5)
    n["gb"] = _box(ax, 7.25, 8.2, 1.9, 0.9, "M_GRAYBOX", "#fbcfe8", 6.5)
    n["ev"] = _box(ax, 9.45, 8.2, 1.9, 0.9, "Q_W_EVAP", "#fbcfe8", 7)
    n["sc"] = _box(ax, 11.6, 8.2, 1.7, 0.9, "M_WATER_SCALE\n_GLOBAL", "#fde68a", 6)
    n["pr"] = _box(ax, 13.5, 8.2, 1.4, 0.9, "Q_WATER_\nPROXY", "#ddd6fe", 6)
    n["ww"] = _box(ax, 11.6, 6.95, 1.7, 0.75, "Q_W_WITH target", "#dbeafe", 6)
    _arrow(ax, n["e"], n["cl"], "input/target")
    ax.annotate("", xy=(2.55, 8.45), xytext=(2.2, 7.95),
                arrowprops=dict(arrowstyle="-|>", color="#3f6212", lw=1.2, mutation_scale=10))
    ax.text(1.5, 8.15, "input", fontsize=6, color="#3f6212")
    _arrow(ax, n["cl"], n["pit"], "output")
    _arrow(ax, n["pit"], n["gb"], "input")
    _arrow(ax, n["gb"], n["ev"], "output")
    _arrow(ax, n["ev"], n["sc"], "input")
    _arrow(ax, n["sc"], n["pr"], "output")
    ax.annotate("", xy=(12.45, 8.2), xytext=(12.45, 7.70),
                arrowprops=dict(arrowstyle="-|>", color="#1d4ed8", lw=1.2, mutation_scale=10))

    ax.add_patch(FancyBboxPatch((0.15, 4.55), 14.9, 1.95, boxstyle="round,pad=0.02",
                                facecolor="#f5f3ff", edgecolor="#c4b5fd", alpha=0.5))
    ax.text(0.25, 6.28, "Stochastic: scenario workload → utilization / IT-power shape + Meta E → annual scaling → scenario facility/cooling",
            fontsize=8, fontweight="bold", color="#5b21b6")
    n["ar"] = _box(ax, 0.3, 4.75, 2.0, 0.85, "Q_ARRIVALS", "#e9d5ff", 7)
    n["ut"] = _box(ax, 2.6, 4.75, 2.2, 0.85, "Q_UTILIZATION\nQ_P_IT shape", "#e9d5ff", 6.2)
    n["es"] = _box(ax, 5.1, 4.75, 1.9, 0.85, "Q_E_FAC", "#dbeafe", 7)
    n["st"] = _box(ax, 7.3, 4.75, 2.2, 0.85, "M_STOCHASTIC", "#fed7aa", 7)
    n["sf"] = _box(ax, 9.8, 4.75, 4.9, 0.85, "scenario Q_P_FAC / Q_W_EVAP / cooling", "#fbcfe8", 7)
    _arrow(ax, n["ar"], n["ut"], "output")
    _arrow(ax, n["ut"], n["st"], "shape")
    _arrow(ax, n["es"], n["st"], "target")
    _arrow(ax, n["st"], n["sf"], "output")

    ax.add_patch(FancyBboxPatch((0.15, 2.15), 14.9, 2.2, boxstyle="round,pad=0.02",
                                facecolor="#fff7ed", edgecolor="#fdba74", alpha=0.5))
    ax.text(0.25, 4.1, "Annual water candidates (separate). Selected energy-only model does not take Q_W_EVAP.",
            fontsize=8, fontweight="bold", color="#9a3412")
    n["ew"] = _box(ax, 0.3, 2.4, 1.7, 0.8, "Q_E_FAC", "#dbeafe", 7)
    n["en"] = _box(ax, 2.3, 2.4, 2.3, 0.8, "M_WATER_ENERGY_NULL\n(selected; no evap)", "#fde68a", 6)
    n["evw"] = _box(ax, 5.0, 2.4, 1.7, 0.8, "Q_W_EVAP", "#fbcfe8", 7)
    n["ep"] = _box(ax, 7.0, 2.4, 2.2, 0.8, "M_WATER_EVAP_PHYS", "#fde68a", 6.2)
    n["tw"] = _box(ax, 9.6, 2.4, 2.5, 0.8, "M_WATER_TWOCOMP\nE + evap NNLS", "#fde68a", 6.2)
    n["wt"] = _box(ax, 12.5, 2.4, 2.2, 0.8, "Q_W_WITH target", "#dbeafe", 7)
    _arrow(ax, n["ew"], n["en"], "input")
    _arrow(ax, n["evw"], n["ep"], "input")
    ax.annotate("", xy=(9.6, 2.8), xytext=(2.0, 2.55),
                arrowprops=dict(arrowstyle="-|>", color="#b45309", lw=1.0, mutation_scale=9,
                                connectionstyle="arc3,rad=0.18"))
    ax.text(6.3, 3.35, "two-comp inputs", fontsize=6, color="#b45309")
    ax.annotate("", xy=(12.5, 2.9), xytext=(4.6, 2.9),
                arrowprops=dict(arrowstyle="-|>", color="#1d4ed8", lw=1.1, mutation_scale=9))
    ax.text(8.4, 3.05, "targets", fontsize=6, color="#1d4ed8")

    ax.add_patch(FancyBboxPatch((0.15, 0.15), 14.9, 1.85, boxstyle="round,pad=0.02",
                                facecolor="#ecfeff", edgecolor="#67e8f9", alpha=0.5))
    ax.text(0.25, 1.75, "Parallel context (OWRD  confounds neither USGS nor Meta withdrawal)",
            fontsize=8, fontweight="bold", color="#155e75")
    _box(ax, 0.3, 0.35, 2.2, 0.8, "Q_CITY_PROD\nPRINEVILLE_PWS", "#cffafe", 6)
    _box(ax, 2.7, 0.35, 2.2, 0.8, "Q_DIRECT_POD\nVITESSE_DIRECT_POD", "#cffafe", 6)
    _box(ax, 5.15, 0.35, 2.3, 0.8, "Q_USGS_PS / IRR\nHUC12_LOCAL_USE", "#fae8ff", 6)
    _box(ax, 7.65, 0.35, 2.4, 0.8, "Q_IWA_* routed\nHUC12_ROUTED_HYDROLOGY", "#fae8ff", 5.8)
    n["eg"] = _box(ax, 10.3, 0.35, 2.2, 0.8, "M_EGRID_BENCH\nQ_SCOPE2_EGRID", "#fef3c7", 6)
    n["s2"] = _box(ax, 12.7, 0.35, 2.1, 0.8, "Q_SCOPE2_META\nbenchmark", "#dbeafe", 6)
    _arrow(ax, n["eg"], n["s2"], "accounting")
    ax.text(3.8, 1.25, "no edge", fontsize=6.5, color="#0f766e", ha="center")
    ax.text(6.5, 1.25, "no edge", fontsize=6.5, color="#7e22ce", ha="center")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path
