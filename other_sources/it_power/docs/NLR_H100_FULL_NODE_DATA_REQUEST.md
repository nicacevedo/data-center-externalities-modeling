# Kestrel H100 full-node telemetry request (do not send automatically)

This package is for NLR HPC / ESIF operators. It is **not** an email draft to fire.

## Why

NLR GenAI profiles measure **CPU RAPL + GPU NVML** on exact Kestrel H100 jobs.
Kestrel job records have **null** `ConsumedEnergyRaw` for these H100 jobs.
Public 8-GPU AC studies cannot identify `P_other_node` on the 4-GPU Kestrel node.

## Primary request (smallest sufficient set)

Per-node BMC / IPMI / Redfish / inlet or PSU input power for the **exact Slurm job IDs below**, plus a few idle windows on the same nodes.

Needed fields:

* node ID (hostname)
* timestamp
* timezone and whether DST is applied
* power value and **unit**
* cadence (≤ 1 minute if possible)
* measurement location / boundary (PSU AC in, DC bus, BMC estimate, …)
* whether PSU losses are included
* quality / missingness flags

Job windows: `46` training/fine-tune jobs (including 5 Stable Diffusion N=1 reconstructions).

Approximate span: `2025-09-19 22:33:11-04:00` → `2025-09-20 19:35:33-04:00` (Kestrel extract timestamps).

Slurm job IDs:

10742766, 10742795, 10742796, 10742797, 10742798, 10742800, 10742817, 10742818, 10742819, 10742820, 10742821, 10742829, 10742831, 10742832, 10742833, 10742834, 10742842, 10742843, 10742844, 10742845, 10742846, 10742933, 10742935, 10742937, 10742938, 10742939, 10742951, 10742971, 10742974, 10742976, 10742977, 10742978, 10742981, 10742982, 10742983, 10742986, 10742988, 10742992, 10742993, 10742994, 10742995, 10742996, 10743000, 10743001, 10743003, 10743005

See `analysis/NLR_H100_FULL_NODE_REQUEST_WINDOWS.csv` for start, end, nodes, workload.

## Idle windows

Several 10–15 minute idle traces on the **same H100 nodes** when no user job is running, with the same meter boundary.

## Fallback (only if per-node is unavailable)

Rack / cabinet / PDU power that **only** feeds those H100 nodes, with:

* exact node membership of the PDU
* active-node counts at each timestamp
* the same time windows

Do not send months of facility-wide telemetry.

## What we will **not** do with the data

* re-identify users
* populate the anonymous ~1.3M H100 job archive with guessed workloads
* treat the result as a transferable PSU-efficiency coefficient for other sites
