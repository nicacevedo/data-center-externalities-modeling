# H100 measurement boundary

This module uses the NLR Dataset of Generative AI Workload Power Profiles
(DOI 10.7799/3025227). Power is **not** full-node AC input.

## What is measured

- **GPU power / energy:** NVIDIA NVML instantaneous power per device, logged by
  WattAMeter (`nvml_*.log`). Four H100 SXM 80 GB devices per Kestrel GPU node.
  Device identifiers are `gpu-0` … `gpu-3` within a node log. Native units are
  milliwatts.
- **CPU power / energy:** AMD RAPL via WattAMeter (`rapl_*.log`). Two sockets
  per node (`cpu-0`, `cpu-1`), AMD EPYC 9554 (Genoa). Package-domain watts are
  the physically meaningful CPU-component reading. A core-domain column exists
  and is summed by the authors' `postprocess.py`; in sampled logs it is
  ~0.02–0.5 W versus tens of watts package, so double-counting is negligible
  but is documented.
- **GPU temperature:** NVML `gpu-k[C]`.
- **Identity:** node hostname and Slurm ID in training log filenames; inference
  windows are sliced from long shared logs using metadata start/end times.

## Derived compute quantities

```
P_GPU(t)      = sum over allocated devices of NVML power
P_CPU(t)      = sum over allocated sockets of RAPL package (+ core, source convention)
P_compute(t)  = P_GPU(t) + P_CPU(t)
E_GPU         = integral P_GPU dt   on native GPU timestamps
E_CPU         = integral P_CPU dt   on native CPU timestamps
E_compute     = E_GPU + E_CPU
```

`P_compute` / `E_compute` are **measured CPU+GPU component** power/energy.
They are **not** full-node AC power.

## Explicit identity for the canonical model

```
P_node = P_compute_measured + P_other_node
```

`P_other_node` is **unresolved** in this dataset. It includes at least:

- DRAM energy not captured in the CPU package RAPL domain (unless a future
  source proves otherwise; this dataset does not)
- NVMe / local storage
- high-speed NICs (Kestrel GPU nodes have two NICs; Slingshot fabric)
- other board / chassis / GPU-board loads not in NVML
- PSU conversion losses
- other peripherals

This module does **not** estimate `P_other_node` from TDP remainder, ESIF
residuals, literature node overhead, or DIPLOEE's 3.520 kW / 420 W modeling
assumptions.

DIPLOEE whole-facility traces in `03_whole-facility_profiles/` are
`SAME_SOURCE_SIMULATION` generated from these profiles. They are not
independent validation and are not rerun here.

## Source aggregation

Training: per-node NVML and RAPL series are linearly interpolated onto a
common 0.2 s grid over the overlapping time window, then summed. Inference:
GPU and CPU series for a metadata `[start_time, end_time]` window are
interpolated at 0.1 s.

Instantaneous combined traces therefore carry a small synchronization /
interpolation error relative to native-timestamp component integrals. Energy
accounting in this module prefers **native-timestamp integrals per
component**, then addition. Combined traces are used for temporal shape and
peak statistics only, with conservation checks against native integrals.

## Measurement confidence (conservative)

| Quantity | Evidence class | Notes |
|---|---|---|
| GPU NVML power | relatively strong | Paper cites ~±5% NVML evidence |
| AMD RAPL CPU power | lower / partially validated | Paper: Intel RAPL strong vs AC; comparable AMD validation not identified. Kestrel H100 nodes use AMD Genoa. |
| Combined P_compute | mixed | GPU-dominated; CPU share is smaller but CPU confidence is the weaker link |
| Full-node AC | unmeasured | Do not label CPU+GPU as node power |

No fictitious parametric uncertainty distribution is fitted.

## Hardware class (engineering bounds only)

Each GPU node: 4× H100 SXM 80 GB (700 W TDP) + 2× EPYC 9554 (360 W TDP).
Paper-stated CPU+GPU TDP envelope = 3520 W. This is **not** a measurement of
`P_node` and is not used to impute `P_other_node`.
