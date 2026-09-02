Forest City v2 robustness, cross-climate, and acquisition-readiness pass.

Does not modify `Meta_Forest_City_North_Carolina_v1/` or Prineville frozen artifacts.
Does not fit parameters. UNKNOWN / PARTIAL / FAIL are valid.

Run:

```
/home/nacevedo/.conda/envs/dc_externalities/bin/python scripts/00_record_initial_state.py
/home/nacevedo/.conda/envs/dc_externalities/bin/python scripts/run_pipeline.py
/home/nacevedo/.conda/envs/dc_externalities/bin/python -m pytest tests/test_v2_guards.py -q
```
