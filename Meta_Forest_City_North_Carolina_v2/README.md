# Forest City v2 — source-boundary and Prineville transfer observability

Isolated follow-on to frozen `Meta_Forest_City_North_Carolina_v1/`.
**Does not modify v1, Prineville, CPU, H100, or ESIF artifacts.**

Forest City is an external hot/humid validation site for already-developed
Prineville physics. This pass does **not** fit a new Forest City model.

A previous untracked draft lives at `Meta_Forest_City_North_Carolina_v2_prior_untracked/`
and is **not** this protocol.

Run:

```
/home/nacevedo/.conda/envs/dc_externalities/bin/python scripts/00_preflight.py
/home/nacevedo/.conda/envs/dc_externalities/bin/python scripts/run_v2_pipeline.py
/home/nacevedo/.conda/envs/dc_externalities/bin/python -m pytest tests/test_v2_guards.py -q
```

Scheduled work uses `sched_mit_sloan_batch` only. Never `mit_normal`.
