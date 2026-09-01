#!/usr/bin/env python3
"""Independent-validation coverage matrix figure (local)."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path("/home/nacevedo/RA/data-center-externalities-modeling/other_sources/cooling_technology_proxies")


def main():
    m = pd.read_csv(ROOT / "data_processed" / "INDEPENDENT_VALIDATION_MATRIX.csv")
    fig, ax = plt.subplots(figsize=(11, 4.8))
    ax.axis("off")
    cols = ["technology", "source_id", "evidence_class", "water_boundary", "quantitative_comparison_possible"]
    tbl = m[cols].copy()
    tbl["technology"] = tbl["technology"].str.slice(0, 42)
    table = ax.table(
        cellText=tbl.values.tolist(),
        colLabels=["technology", "source", "class", "water boundary", "quant. vs Lei?"],
        loc="center",
        cellLoc="left",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(7)
    table.scale(1, 1.35)
    ax.set_title("Independent-validation coverage (not same-lineage self-check)", fontsize=11, pad=12)
    fig.tight_layout()
    out = ROOT / "figures" / "independent_validation_coverage.png"
    fig.savefig(out, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(out)


if __name__ == "__main__":
    main()
