# Shared CPU reconstruction feasibility

Disposition: **UNSUPPORTED**

## Questions

A. Unique physical node × time reconstruction? **No** (not in this pass).

B. De-duplicate raw shared-job energy without arbitrary allocation? **No**.

C. Defensible bound? Raw `ConsumedEnergyRaw` summed across co-resident jobs is an **overcount**. Exclusive-CPU replay is a conservative **lower** account of job-attributed CPU energy. No tight upper bound without node-interval occupancy.

## Evidence

- Shared-or-positive-count rows: 1,747,690
- Positive-energy rows among them: 939,913
- Raw energy sum (NOT additive): 1.262 GWh
- `Analysis extract omits nodelist/jobs_shared. Even in the source, ConsumedEnergyRaw appears occupancy-copied onto co-resident jobs. Interval-overlap on shared nodes would require an allocator and is not simple/reliable. No exact reconstruction in this pass.`

Do **not** sum shared-job `ConsumedEnergyRaw` into facility replay.
