#!/usr/bin/env python3
"""V3 ANALYSIS launcher. Pass 1 must not authorize or execute this sweep."""

from __future__ import annotations

import argparse

import _bootstrap_path  # noqa: F401

from src_v3.design import load_design


def main() -> int:
    design = load_design()
    token = str(design["v3"]["analysis_authorization_token"])
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorize", default="")
    parser.add_argument("--pool", default="V3_ANALYSIS")
    args = parser.parse_args()
    if args.pool != "V3_ANALYSIS":
        raise SystemExit("run_v3.py is the ANALYSIS launcher only")
    if args.authorize != token:
        raise SystemExit(
            "V3 ANALYSIS refused: missing/incorrect --authorize token. "
            "Pass 1 STOP. V3_ANALYSIS_REPLICATES_RUN=0"
        )
    raise SystemExit(
        "Authorization token accepted, but this Pass-1 checkpoint does not "
        "execute the 21×200 ANALYSIS sweep. V3_ANALYSIS_REPLICATES_RUN=0"
    )


if __name__ == "__main__":
    raise SystemExit(main())
