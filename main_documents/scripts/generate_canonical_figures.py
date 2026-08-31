"""Synthesize canonical master-document diagrams from master.tex status only.

Content source: main_documents/master.tex (27 Aug 2026 snapshot).
Does not read experimental outputs or invent quantities.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle, Patch
from matplotlib.lines import Line2D

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "img"

plt.rcParams.update(
    {
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "font.family": "DejaVu Sans",
        "font.size": 8.2,
        "axes.linewidth": 0.6,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.04,
    }
)

GRAY = {
    "box": "#f4f4f4",
    "box2": "#e8e8e8",
    "box3": "#dedede",
    "edge": "#333333",
    "mute": "#666666",
    "break": "#222222",
    "s": "#2b2b2b",
    "p": "#8a8a8a",
    "t": "#c8c8c8",
    "n": "#ffffff",
}


def _box(ax, x, y, w, h, text, fc=None, lw=0.9, fs=7.4, weight="normal"):
    p = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.012,rounding_size=0.04",
        facecolor=fc or GRAY["box"],
        edgecolor=GRAY["edge"],
        linewidth=lw,
        mutation_aspect=0.6,
    )
    ax.add_patch(p)
    ax.text(
        x + w / 2,
        y + h / 2,
        text,
        ha="center",
        va="center",
        fontsize=fs,
        color=GRAY["edge"],
        weight=weight,
        wrap=True,
    )
    return p


def _arrow(ax, x1, y1, x2, y2, style="-|>"):
    ax.add_patch(
        FancyArrowPatch(
            (x1, y1),
            (x2, y2),
            arrowstyle=style,
            mutation_scale=9,
            linewidth=0.9,
            color=GRAY["edge"],
            shrinkA=0,
            shrinkB=0,
        )
    )


def fig_architecture(path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.05, 3.55))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    w, h = 0.132, 0.22
    y_top = 0.68
    xs = [0.02, 0.175, 0.33, 0.485, 0.64, 0.795]
    labels = [
        "Workload /\nhardware",
        "Device / node /\nsystem power",
        "Facility IT\n$P^{IT}$",
        "Facility\n$P^{fac}$, $W^{cond}$",
        "Grid $E$  |  source-\nresolved $W^{with}$",
        "Externalities:\nCO$_2$, gen. water,\n$q^{gw}$ pumping",
    ]
    fcs = [GRAY["box"], GRAY["box2"], GRAY["box"], GRAY["box"], GRAY["box3"], GRAY["box"]]
    for x, lab, fc in zip(xs, labels, fcs):
        _box(ax, x, y_top, w, h, lab, fc=fc, fs=6.7)

    for i in range(len(xs) - 1):
        _arrow(ax, xs[i] + w, y_top + h / 2, xs[i + 1], y_top + h / 2)

    # Boundary markers between 2-3, 4-5, and on grid branch
    def brk(x, label):
        ax.plot([x, x], [y_top - 0.04, y_top + h + 0.04], ls=(0, (2.2, 1.6)), lw=1.05, color=GRAY["break"])
        ax.text(x, y_top - 0.07, label, ha="center", va="top", fontsize=5.8, color=GRAY["break"])

    brk(xs[1] + w + 0.5 * (xs[2] - xs[1] - w), "B1  device/node\n$\\neq$ facility IT")
    brk(xs[3] + w + 0.5 * (xs[4] - xs[3] - w), "B2  $W^{cond}\\neq$\nwithdrawal / $q^{gw}$")
    brk(xs[4] + w + 0.5 * (xs[5] - xs[4] - w), "B3  regional grid\n$\\neq$ campus/marginal")

    _box(ax, 0.02, 0.10, 0.22, 0.26, "Competing users\n$q^{ag}$, $q^{mun}$\n(not merely\ndownstream impacts)", fc="#ececec", fs=6.5)
    _box(ax, 0.33, 0.10, 0.34, 0.26, "Groundwater state $h$\nshared withdrawals\n$q^{ag}+q^{mun}+q^{dc}$", fc="#ececec", fs=7.2)
    _box(ax, 0.72, 0.10, 0.26, 0.26, "Operations, siting,\ntechnology, source,\nand policy", fc=GRAY["box2"], fs=7.2, weight="medium")
    _arrow(ax, xs[5] + w / 2, y_top, 0.50, 0.36)
    _arrow(ax, 0.24, 0.23, 0.33, 0.23)
    _arrow(ax, 0.67, 0.23, 0.72, 0.23)
    fig.savefig(path)
    plt.close(fig)


def fig_evidence_map(path: Path) -> None:
    # Status codes from master.tex: S strong, P partial/benchmark, T site-specific, N pending/not identified
    cols = [
        "WL/hw\n→ IT power",
        "Node/sys.\n→ fac. IT",
        "Facility\nelec. / PUE",
        "Cond. water\n/ WUE",
        "Source\nbridge $\\Psi$",
        "Regional\ngrid",
        "Pumping\n→ GW",
        "Planning\n/ policy",
    ]
    rows = [
        "M100",
        "Frontier",
        "Lei–Masanet",
        "NLR GenAI",
        "H100/B200",
        "MLPerf Power",
        "Meta Prineville",
        "Canonical weather",
        "EIA/FERC/PACW",
        "Permits / chronology",
        "Utility / campus meters",
        "POD / reuse / discharge",
        "GWIS / OWRD / USGS",
        "India / IWMI / CGWB / GRACE\n(prospective)",
    ]
    # Row-major; taken from master status tables, not new analysis
    N, P, S, T = "N", "P", "S", "T"
    M = [
        [P, S, S, N, N, N, N, P],  # M100
        [N, N, P, N, N, N, N, N],  # Frontier (QC pending → partial)
        [N, N, P, P, N, N, N, P],  # Lei–Masanet (annual/RNG gate pending)
        [P, P, N, N, N, N, N, N],  # NLR
        [P, P, N, N, N, N, N, N],  # H100/B200
        [P, P, N, N, N, N, N, N],  # MLPerf
        [N, N, T, T, N, T, T, T],  # Prineville disclosures / test bed
        [N, N, S, P, N, N, N, N],  # weather
        [N, N, N, N, N, T, N, N],  # regional grid
        [N, N, T, N, N, N, N, T],  # permits
        [N, N, N, N, N, N, N, N],  # campus meters missing
        [N, N, N, N, N, N, T, N],  # POD reported at POD boundary only
        [N, N, N, N, N, N, T, N],  # GW observations; dynamics not identified
        [N, N, N, N, N, N, N, N],  # prospective India
    ]
    fill = {S: GRAY["s"], P: GRAY["p"], T: GRAY["t"], N: GRAY["n"]}
    txtc = {S: "white", P: "white", T: GRAY["edge"], N: GRAY["mute"]}
    glyph = {S: "S", P: "P", T: "T", N: "—"}

    fig, ax = plt.subplots(figsize=(7.05, 5.55))
    ax.set_xlim(0, 10.2)
    ax.set_ylim(0, 16.2)
    ax.axis("off")

    x0, y0 = 2.35, 1.15
    cw, rh = 0.95, 0.92
    for j, c in enumerate(cols):
        ax.text(x0 + (j + 0.5) * cw, y0 + len(rows) * rh + 0.18, c, ha="center", va="bottom", fontsize=6.0)
    for i, r in enumerate(rows):
        yi = y0 + (len(rows) - 1 - i) * rh
        ax.text(x0 - 0.08, yi + rh / 2, r, ha="right", va="center", fontsize=6.4)
        for j, st in enumerate(M[i]):
            x = x0 + j * cw
            rect = Rectangle((x + 0.06, yi + 0.08), cw - 0.12, rh - 0.16, facecolor=fill[st], edgecolor=GRAY["edge"], linewidth=0.45)
            ax.add_patch(rect)
            ax.text(x + cw / 2, yi + rh / 2, glyph[st], ha="center", va="center", fontsize=7.2, color=txtc[st])

    legend = [
        ("S  strong structural support", GRAY["s"], "white"),
        ("P  partial / benchmark support", GRAY["p"], "white"),
        ("T  site-specific evidence", GRAY["t"], GRAY["edge"]),
        ("—  pending / not identified", GRAY["n"], GRAY["mute"]),
    ]
    lx = 0.35
    for k, (lab, fc, tc) in enumerate(legend):
        ax.add_patch(Rectangle((lx + k * 2.45, 0.22), 0.28, 0.32, facecolor=fc, edgecolor=GRAY["edge"], lw=0.5))
        ax.text(lx + k * 2.45 + 0.38, 0.38, lab, ha="left", va="center", fontsize=6.2)
    ax.text(
        5.1,
        0.02,
        "No cell means the full chain is identified. Shared-lineage sources are complementary, not independent replicates.",
        ha="center",
        va="bottom",
        fontsize=5.8,
        color=GRAY["mute"],
    )
    fig.savefig(path)
    plt.close(fig)


def fig_prineville(path: Path) -> None:
    layers = [
        ("Meta annual facility electricity", "reported", "High-confidence annual scale; not hourly IT"),
        ("Meta annual water withdrawal", "reported", "From 2014; not WUE or source mix"),
        ("Meta location Scope 2", "reported", "Site accounting; not marginal/campus-attributed generators"),
        ("Weather (KS39/KRDM)", "measured", "External cooling driver; wet bulb derived; not campus microclimate"),
        ("Regional grid (EIA-930 / FERC PACW)", "proxy", "Regional context; not campus demand or serving plants"),
        ("Permits / facility chronology", "reported", "Technology not static; not causal water-model evidence"),
        ("Campus / utility electricity meters", "missing", "Not identified in the public test bed"),
        ("Campus water-meter / billing", "missing", "Not identified in the public test bed"),
        ("Sewer / wastewater discharge", "missing", "Consumption/return remain unidentified"),
        ("POD / direct pumping", "reported", "POD boundary only; not campus $\\theta^{gw}$"),
        ("Reuse / reclaimed water", "not_identified", "Not identified"),
        ("Source bridge $\\Psi$ (with/cons/return)", "not_identified", "Conditioning water is not withdrawal"),
        ("GWIS / OWRD groundwater observations", "measured", "Observed layer; network dynamics not identified"),
        ("USGS HUC12 / IWA context", "proxy", "Regional hydrology/use; not an aquifer node"),
        ("Hourly IT telemetry", "not_target", "Not an active public-data target"),
    ]
    style = {
        "reported": ("reported / measured", GRAY["s"], "white"),
        "measured": ("reported / measured", GRAY["s"], "white"),
        "proxy": ("derived / proxy", GRAY["p"], "white"),
        "missing": ("missing / pending", GRAY["t"], GRAY["edge"]),
        "not_identified": ("not identified / not a target", GRAY["n"], GRAY["edge"]),
        "not_target": ("not identified / not a target", GRAY["n"], GRAY["edge"]),
    }
    fig, ax = plt.subplots(figsize=(7.05, 5.35))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    top = 0.93
    row_h = 0.052
    ax.text(0.02, 0.97, "Prineville coupled-chain evidence (public test bed)", fontsize=8.5, weight="medium")
    for i, (name, st, note) in enumerate(layers):
        y = top - i * row_h
        lab, fc, tc = style[st]
        ax.add_patch(Rectangle((0.02, y - 0.018), 0.34, 0.042, facecolor=GRAY["box"], edgecolor=GRAY["edge"], lw=0.4))
        ax.text(0.19, y + 0.003, name, ha="center", va="center", fontsize=5.9)
        ax.add_patch(Rectangle((0.38, y - 0.018), 0.22, 0.042, facecolor=fc, edgecolor=GRAY["edge"], lw=0.4))
        ax.text(0.49, y + 0.003, lab, ha="center", va="center", fontsize=5.5, color=tc)
        ax.text(0.62, y + 0.003, note, ha="left", va="center", fontsize=5.7, color=GRAY["mute"])
        if i < len(layers) - 1:
            ax.annotate("", xy=(0.19, y - 0.022), xytext=(0.19, y - 0.008), arrowprops=dict(arrowstyle="-", color=GRAY["mute"], lw=0.4))

    ax.text(
        0.02,
        0.04,
        "Statuses follow master.tex / pipeline provenance. Fitted reconstructions are omitted so they are not read as telemetry.",
        fontsize=5.8,
        color=GRAY["mute"],
    )
    fig.savefig(path)
    plt.close(fig)


def fig_gates(path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.05, 3.45))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    def col(x, title, items):
        ax.text(x + 0.145, 0.95, title, ha="center", va="top", fontsize=7.4, weight="medium")
        y = 0.82
        boxes = []
        for t in items:
            _box(ax, x, y - 0.13, 0.29, 0.13, t, fs=6.3)
            boxes.append((x + 0.145, y - 0.13))
            y -= 0.16
        for i in range(len(boxes) - 1):
            _arrow(ax, boxes[i][0], boxes[i][1], boxes[i + 1][0], boxes[i + 1][1] + 0.13)
        return boxes

    col(0.02, "Facility / evidence", ["M100 closed / frozen", "Frontier QC closeout", "Lei–Masanet annual/RNG gate", "Modern AI IT-power experiment"])
    col(0.355, "Water / groundwater", ["Identify source-water bridge $\\Psi$", "Pumping → GW chronological benchmark", "Reduced-order GW module\nonly if benchmark supports it"])
    col(0.69, "Integrated planning", ["$M_0$ static PSCC-style baseline", "$M_1$ archetypes + source/GW\nonly if prior gates pass", "$M_2$ higher fidelity\nonly if decision-relevant"])

    ax.plot([0.02, 0.98], [0.18, 0.18], color=GRAY["edge"], lw=0.7)
    ax.text(0.5, 0.135, "Fail a gate: restrict claims; do not escalate or retune through the failure.", ha="center", fontsize=6.6, color=GRAY["break"])
    ax.text(0.5, 0.05, "Final escalation, only after coupling is credible:  decision replay / regret  →  uncertainty  →  policy / decentralization", ha="center", fontsize=6.3)
    fig.savefig(path)
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig_architecture(OUT / "fig_canonical_project_architecture.pdf")
    fig_evidence_map(OUT / "fig_evidence_to_model_map.pdf")
    fig_prineville(OUT / "fig_prineville_testbed_status.pdf")
    fig_gates(OUT / "fig_research_gates.pdf")
    for p in sorted(OUT.glob("*.pdf")):
        print(p)


if __name__ == "__main__":
    main()
