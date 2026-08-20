"""Run the USGS NWAA HUC12 water module.

Order is required so the audit cannot validate a stale municipal HUC12 crosswalk:

organize/reuse raw → panels → municipal-source HUC12 crosswalk → audit.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from usgs_nwaa_config import LEGACY_ARCHIVE, LEGACY_SCRIPTS, ROOT


def archive_legacy_scripts() -> None:
    LEGACY_ARCHIVE.mkdir(parents=True, exist_ok=True)
    readme = LEGACY_ARCHIVE / "README.md"
    if not readme.exists():
        readme.write_text(
            "One-off USGS download/panel scripts superseded by "
            "`src/download_usgs_nwaa.py`, `src/build_usgs_huc12_panels.py`, "
            "and `src/audit_usgs_nwaa.py`. Geography builders remain at the "
            "package root because they were not replaced.\n",
            encoding="utf-8",
        )
    for name in LEGACY_SCRIPTS:
        src = ROOT / name
        dest = LEGACY_ARCHIVE / name
        if src.exists() and not dest.exists():
            shutil.move(str(src), str(dest))


def main() -> None:
    from download_usgs_nwaa import main as download_main
    from build_usgs_huc12_panels import main as panel_main
    from audit_usgs_nwaa import main as audit_main
    from build_municipal_huc12_crosswalk import main as crosswalk_main

    download_main()  # organize/reuse existing raw; skip files that already exist
    panel_main()
    crosswalk_main()  # municipal-source HUC12 crosswalk before audit
    audit_main()
    archive_legacy_scripts()


if __name__ == "__main__":
    main()
