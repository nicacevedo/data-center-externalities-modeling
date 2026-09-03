# Forest City v3 — Cross-Site Transportability, Partial Identification, and Acquisition-Readiness

Additive folder. It does **not** modify Forest City v1/v2, Prineville,
frozen Masanet/CPU/H100/ESIF, or the PUE-prediction-tool submodule. Material
external inputs are enumerated in `outputs/provenance/V3_DEPENDENCY_MANIFEST.*`.
Forest City v2 targets are read from Git blobs at
`da7fd6f55e1aef5216ceabe80bfc3e31265f7927`; dirty v2 worktree replacements
are not scientific inputs.

## Claims contract

See `config/claims_contract.yaml`. Evidence classes: OBSERVED, DERIVED, MODEL_REPLAY, TRANSFERRED_MODEL, SCENARIO, UNIDENTIFIED.

A TRANSFERRED_MODEL or SCENARIO value is never reported as OBSERVED or empirically calibrated.

Frozen identification boundaries unless new independent evidence appears:

- `QUANTITATIVE_PHYSICS_TRANSFER = NOT_VALIDATED`
- `FACILITY_EFFECTIVE_DELTA_T = UNIDENTIFIED` (35 °F is IT/server design rise, not facility ΔT)
- `FACILITY_AIRFLOW_CFM = UNIDENTIFIED`
- `FRC1_COOLING_ONLY_WATER_MAGNITUDE = UNIDENTIFIED`
- `FRC1_TO_LATER_CAMPUS_MAPPING = UNIDENTIFIED`
- `CAMPUS_ANNUAL_WATER_WITHDRAWAL = IDENTIFIED`
- `CAMPUS_WATER_CONSUMPTION = UNIDENTIFIED`

## Run

```bash
/home/nacevedo/.conda/envs/dc_externalities/bin/python scripts/run_v3_pipeline.py
/home/nacevedo/.conda/envs/dc_externalities/bin/python -m pytest tests/test_v3_guards.py -q
/home/nacevedo/.conda/envs/dc_externalities/bin/python scripts/run_cleanroom_replay.py
/home/nacevedo/.conda/envs/dc_externalities/bin/python scripts/finalize_freeze.py
```

Slurm (Sloan CPU only; never default `mit_normal`):

```bash
sbatch slurm/run_masanet_sloan.sh
```

## Outputs

- `outputs/FINAL_CLAIMS_LEDGER.md`
- `outputs/FOREST_CITY_V3_REPORT.md`
- `outputs/reproducibility/CLEANROOM_FINAL_STATUS.json`
- `outputs/provenance/FINAL_V3_FILE_HASHES.csv`
- `outputs/figures/fig01_*.png` … `fig06_*.png`
