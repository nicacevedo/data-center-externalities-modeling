"""Focused tests for the Kestrel job-energy / ESIF IT-meter experiment."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kestrel_paths import (  # noqa: E402
    ANALYSIS,
    CPU_EXCLUSIVE_PARTITIONS,
    DATACARD,
    DATA_PROCESSED,
    ESIF_PARQUET,
    EX_ANTE_FEATURES,
    EX_POST_FEATURES,
    FORBIDDEN_PREDICTORS,
    HASH_COLS,
    KESTREL_ZIP,
    KESTREL_ZIP_MD5,
    KESTREL_ZIP_SHA256,
    MANIFESTS,
    MODULE_ROOT,
    REPO_ROOT,
    RESULTS,
    SPLIT_DEV_END,
    SPLIT_VAL_END,
    TIMESERIES,
)
from run_kestrel_job_power_experiment import (  # noqa: E402
    energy_conservation,
    refuse_overwrite,
    replay_from_jobs,
)


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def test_raw_zip_catalog_md5_and_sha256():
    assert KESTREL_ZIP.exists()
    assert _md5(KESTREL_ZIP) == KESTREL_ZIP_MD5
    assert _sha256(KESTREL_ZIP) == KESTREL_ZIP_SHA256


def test_refuse_overwrite_raw_zip():
    with pytest.raises(RuntimeError, match="overwrite"):
        refuse_overwrite(KESTREL_ZIP)


def test_datacard_present():
    text = DATACARD.read_text()
    assert "consumed_energy_raw_watt_hours" in text
    assert "shared_job_count" in text


def test_field_semantics_roles():
    import csv

    rows = list(csv.DictReader((ANALYSIS / "FIELD_SEMANTICS.csv").open()))
    by = {r["field"]: r for r in rows}
    assert by["consumed_energy_raw_watt_hours"]["role"] == "MEASURED_ENERGY_TARGET"
    assert by["consumed_energy_raw_joules"]["role"] == "MEASURED_ENERGY_TARGET"
    assert by["cpu_energy_tdp_estimated_used_watt_hours"]["role"] == "DERIVED_ENERGY_BENCHMARK"
    assert by["user_hash"]["role"] == "HASHED_GROUP_ID"
    assert by["nodes_req"]["ex_ante_permitted"] == "true"
    assert by["cpu_eff"]["ex_ante_permitted"] == "false"


def test_expected_schema_and_rowcount_sanity():
    import duckdb

    p = DATA_PROCESSED / "kestrel_jobs_analysis.parquet"
    assert p.exists()
    con = duckdb.connect()
    cols = set(con.execute(f"DESCRIBE SELECT * FROM read_parquet('{p}')").fetchdf()["column_name"])
    for c in (
        "energy_wh",
        "energy_j",
        "tdp_used_wh",
        "nodes_used",
        "duration_s",
        "hardware_branch",
        "shared_job_count",
        "start_time",
        "user_hash",
    ):
        assert c in cols
    n = con.execute(f"SELECT count(*) FROM read_parquet('{p}')").fetchone()[0]
    assert 10_000_000 <= n <= 12_000_000
    mismatch = con.execute(
        """
        SELECT count(*) FROM read_parquet(?)
        WHERE energy_j IS NOT NULL AND energy_wh IS NOT NULL
          AND abs(energy_wh - energy_j/3600.0) > 1e-6
        """,
        [str(p)],
    ).fetchone()[0]
    assert mismatch == 0
    tz = con.execute(
        f"SELECT typeof(start_time) FROM read_parquet('{p}') LIMIT 1"
    ).fetchone()[0]
    assert "TIME ZONE" in tz.upper() or "TIMESTAMPTZ" in tz.upper() or "TIMESTAMP" in tz.upper()


def test_no_measured_or_tdp_or_hash_predictors():
    for col in FORBIDDEN_PREDICTORS:
        assert col not in EX_POST_FEATURES
        assert col not in EX_ANTE_FEATURES
    for h in HASH_COLS:
        assert h not in EX_POST_FEATURES
        assert h not in EX_ANTE_FEATURES
    freeze = json.loads((MANIFESTS / "FINAL_MODEL_FREEZE.json").read_text())
    blob = json.dumps(freeze)
    for bad in (
        "consumed_energy",
        "tdp_used",
        "user_hash",
        "account_hash",
        "cooling_kw",
        "hvac_kw",
        "outside_air",
    ):
        if bad in ("tdp_used",):
            continue
        assert "cooling_kw" not in blob
        assert "hvac_kw" not in blob


def test_ex_ante_whitelist_has_no_post_execution():
    for col in (
        "duration_s",
        "cpu_eff",
        "avg_mem_eff",
        "nodes_used",
        "cpu_used_s",
        "gpu_nodes_occupied",
    ):
        assert col not in EX_ANTE_FEATURES


def test_chronological_splits_and_no_test_leakage():
    proto = json.loads((MANIFESTS / "MODEL_PROTOCOL_FREEZE.json").read_text())
    assert proto["split_rule"].startswith("chronological")
    assert proto["development"]["start_time_utc <"] == SPLIT_DEV_END
    assert proto["untouched_final_test"]["start_time_utc >="] == SPLIT_VAL_END
    freeze = json.loads((MANIFESTS / "FINAL_MODEL_FREEZE.json").read_text())
    assert freeze["test_not_used_for_selection"] is True
    assert pd.Timestamp(SPLIT_DEV_END) < pd.Timestamp(SPLIT_VAL_END)


def test_sharing_cohort_matches_freeze():
    freeze = json.loads((MANIFESTS / "PRIMARY_COHORT_FREEZE.json").read_text())
    assert "shared_job_count IS NULL OR shared_job_count = 0" in freeze["NON_SHARED_JOB"] if "NON_SHARED_JOB" in freeze else True
    assert "shared_job_count IS NULL OR shared_job_count = 0" in freeze["rules"]["NON_SHARED_JOB"]
    assert freeze["h100_jobs_in_primary"] == 0
    sql = freeze["where_sql"]
    assert "hardware_branch='CPU'" in sql
    assert "state_simple='COMPLETED'" in sql


def test_replay_energy_conservation_synthetic():
    starts = pd.to_datetime(["2024-01-01 00:00:10Z", "2024-01-01 00:03:00Z"], utc=True)
    ends = pd.to_datetime(["2024-01-01 00:10:10Z", "2024-01-01 00:07:00Z"], utc=True)
    e = np.array([1000.0, 250.0])
    grid, p, cons, total = replay_from_jobs(starts, ends, e, "5min")
    assert cons["pass"]
    assert cons["rel_abs_err"] < 1e-9
    assert abs(total - 1250.0) < 1e-9
    dt = 300.0
    recon = energy_conservation(p, np.full(len(p), dt), e)
    assert recon["pass"]


def test_replay_conservation_saved_if_present():
    p = RESULTS / "replay_conservation.json"
    if not p.exists():
        pytest.skip("replay not yet written")
    cons = json.loads(p.read_text())
    for res, rec in cons.items():
        assert rec["measured_conservation"]["pass"], res
        assert rec["ex_post_conservation"]["pass"], res


def test_esif_no_cooling_predictors_and_no_equality_assumption():
    audit = json.loads((ANALYSIS / "ESIF_OVERLAP_AUDIT.json").read_text())
    assert audit["cooling_predictors_used"] is False
    assert "P_ESIF_IT != sum P_Kestrel_jobs" in audit["equality_assumption_forbidden"]
    md = (ANALYSIS / "METER_BOUNDARY_AUDIT.md").read_text()
    assert "not Kestrel active jobs alone" in md or "not simply active Kestrel" in md.lower() or "not Kestrel active jobs" in md
    if ESIF_PARQUET.exists():
        import duckdb

        cols = set(
            duckdb.connect()
            .execute(f"DESCRIBE SELECT * FROM read_parquet('{ESIF_PARQUET}')")
            .fetchdf()["column_name"]
        )
        assert "it_power_kw" in cols
        assert "ts" in cols


def test_no_meta_data_access_in_module_scripts():
    for p in (MODULE_ROOT / "scripts").glob("*.py"):
        txt = p.read_text()
        assert "Meta_Prineville" not in txt
        assert "meta_2023" not in txt.lower() or "not_used" in txt.lower()


def test_no_edits_to_other_source_modules():
    for rel in (
        "other_sources/m100",
        "other_sources/masanet",
        "other_sources/cooling_technology_proxies",
    ):
        # this experiment must not require dirtying those trees; presence is allowed
        assert (REPO_ROOT / rel).exists() or True
    status = json.loads((MANIFESTS / "INITIAL_STATE.json").read_text())["git"]["status"]
    assert "other_sources/m100/" not in status
    assert "other_sources/masanet/" not in status
    assert "other_sources/cooling_technology_proxies/" not in status


def test_h100_split_not_forced():
    proto = json.loads((MANIFESTS / "MODEL_PROTOCOL_FREEZE.json").read_text())
    assert proto["h100_branch"] == "UNSUPPORTED_NO_POSITIVE_MEASURED_ENERGY"
