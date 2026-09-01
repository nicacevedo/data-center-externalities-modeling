# ESIF IT meter boundary (Kestrel experiment)

ESIF `it_power_kw` captures power used by **IT equipment on the data-center floor**, not Kestrel active jobs alone (NLR HPC Facility PUE Data, DOI 10.7799/3015212).

Do **not** interpret unexplained power as job-energy model failure.

## Documented systems on the floor (authoritative, not inferred from the series)

1. **Kestrel CPU nodes** — dual-socket Sapphire Rapids, 104 cores, ~240–256 GB, 100% direct liquid cooling. CPU phase installed summer 2023; open to all projects for FY2024 (NLR news; datacard jobs from 2023-08).
2. **Kestrel GPU nodes** — 156 nodes, 4× NVIDIA H100 SXM 80 GB, AMD Genoa 128 cores, shareable by default (NLR *Running on Kestrel*). GPU hardware arrived 2024-02; early users ~2024-05; general availability reported 2024-08-21. **This job extract contains no positive `consumed_energy_raw_*` for any GPU partition.** GPU IT load can appear on the facility meter without appearing in the job-energy replay.
3. **Eagle** — previous 2,000-node HPC in ESIF, 2019–2024. NLR announced decommissioning on **15 June 2024** (HPC announcement “Kestrel GPUs and Eagle End of Service”, 11 June 2024). Eagle storage access was planned through 2024-09-30. During 2023-08 to 2024-06-15 the IT meter includes Eagle + Kestrel coexistence.
4. **Idle Kestrel nodes, login/service nodes, storage, networking, and other ESIF computing equipment** remain on the IT meter when no jobs are active.

## Epochs used (externally justified)

| Epoch | Window (America/Denver date) | Why |
|---|---|---|
| `eagle_coexist` | start → 2024-06-14 | Eagle still in service |
| `post_eagle` | 2024-06-15 onward | Eagle compute decommissioned |
| `post_gpu_ga` | 2024-08-21 onward | GPU nodes reported generally available; job trace still lacks GPU energy |

Idle/no-job intervals are **not** expected to show zero IT power.

## Modeling implication

Primary linkage model: `P_ESIF_IT(t) = B + β P_Kestrel_jobs(t) + ε_t`.

`B` is a residual IT baseline (idle + non-Kestrel + unmeasured GPU + storage/network). `β` is the incremental association of *measured CPU-job-attributed* Kestrel energy with the facility IT meter. Exact equality (`β=1`, `B=0`) is **not** the scientific target.
