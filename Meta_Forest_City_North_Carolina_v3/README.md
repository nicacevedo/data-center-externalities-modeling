# Forest City v3 — Cross-Site Transportability, Partial Identification, and Acquisition-Readiness

Additive folder. Does **not** modify Forest City v1/v2, Prineville, frozen Masanet/CPU/H100/ESIF, or the PUE-prediction-tool submodule.

## Claims contract

See `config/claims_contract.yaml`. Evidence classes: OBSERVED, DERIVED, MODEL_REPLAY, TRANSFERRED_MODEL, SCENARIO, UNIDENTIFIED.

A TRANSFERRED_MODEL or SCENARIO value is never reported as OBSERVED or empirically calibrated.

Frozen findings unless new independent evidence appears:

- `QUANTITATIVE_PHYSICS_TRANSFER = NOT_VALIDATED`
- `FACILITY_EFFECTIVE_DELTA_T = UNIDENTIFIED` (35 °F is IT/server design rise, not facility ΔT)
- `FRC1_ADDRESS = INTERVAL/SET_UNRESOLVED`

## Run

```bash
/home/nacevedo/.conda/envs/dc_externalities/bin/python scripts/run_v3_pipeline.py
/home/nacevedo/.conda/envs/dc_externalities/bin/python -m pytest tests/test_v3_guards.py -q
```

Slurm (Sloan CPU only; never default `mit_normal`):

```bash
sbatch slurm/run_masanet_sloan.sh
```

## Outputs

- `outputs/FINAL_CLAIMS_LEDGER.md`
- `outputs/FOREST_CITY_V3_REPORT.md`
- `outputs/figures/fig01_*.png` … `fig06_*.png`
