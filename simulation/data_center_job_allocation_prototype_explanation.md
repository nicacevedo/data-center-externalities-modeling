Below is the code in its exact execution order. The key distinction is:

* **Structural equation:** follows directly from queueing, energy, or mass-balance accounting.
* **Source-calibrated proxy:** numerical value comes from a credible source but is not facility-specific.
* **Synthetic assumption:** chosen only to make the first simulation run; it must eventually be estimated or replaced with data.

The complete code is here: [data_center_job_allocation_prototype.py](sandbox:/mnt/data/data_center_job_allocation_prototype.py). 

---

# Update: multi-objective tradeoffs

The prototype now schedules against **three competing objectives** — electricity
cost, operational CO2 emissions, and water footprint — instead of a single
impact-aware objective. Three things changed relative to the description below,
and the affected sections are corrected inline:

1. **Distinct diurnal phases.** Price peaks in the evening (~19h), grid emissions
   peak in the early morning (~5h), and water intensity peaks in mid-afternoon
   (~15h). Previously price and emissions were phase-aligned, so cost and carbon
   barely competed. Only the annual-average *levels* are source-calibrated; the
   diurnal *shapes* remain synthetic.
2. **Time-varying water.** Site WUE and grid water now follow the afternoon
   water-stress shape, so water genuinely affects the schedule (previously it
   was constant and could not).
3. **Normalized weighted objective.** Each marginal impact is rescaled to mean 1
   and combined with weights in [0, 1]. The scheduler minimizes
   `w_cost * cost_n + w_em * emissions_n + w_water * water_n` plus a tiny queue
   tie-breaker. Named focus scenarios (cost / emissions / water / balanced) and a
   pairwise weight sweep trace the three Pareto frontiers
   (`pareto_sweep.csv`, `05_pareto_frontiers.png`). The dollar carbon/water
   prices are now used only for reporting columns, not for the schedule.

---

# 0. Overall model

The simulation represents one data center over hourly periods (t=0,\ldots,T-1).

The causal chain is

[
\text{job arrivals}
\longrightarrow
\text{queued IT work}
\longrightarrow
\text{processed IT energy}
\longrightarrow
\text{facility electricity}
\longrightarrow
{\text{cost, water, CO}_2,\text{heat}}.
]

Jobs are aggregated into continuous units of IT energy, measured in (\mathrm{MWh}_{IT}). Therefore, the optimizer can split and preempt work; it is not scheduling indivisible jobs.

This implements the queue, PUE, WUE, grid-water, emissions, and cost relationships developed in your preliminary modeling.  

---

# 1. Imports

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Tuple
```

* `dataclass`: stores all model parameters together.
* `Path`: creates output folders and file paths.
* `Dict`, `Tuple`: type annotations.
* `Iterable` is imported but never used and could be removed.

```python
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
```

* NumPy: random generation and arrays.
* pandas: hourly tables and CSV files.
* Matplotlib: plots.

```python
from scipy.optimize import linprog
from scipy.sparse import lil_matrix
```

* `linprog`: solves

[
\min_x c^\top x
]

subject to

[
A_{ub}x\le b_{ub},\qquad
A_{eq}x=b_{eq},\qquad
x\ge0.
]

* `lil_matrix`: constructs the large but sparse constraint matrices.

SciPy’s `method="highs"` automatically uses one of the HiGHS linear-programming solvers. ([SciPy Documentation][1])

---

# 2. `SimulationConfig`: all parameters

## 2.1 Time horizon

```python
seed = 15087
number_of_days = 7
time_step_hours = 1.0
```

Therefore,

[
T^{arr}=7(24)=168\text{ hours}.
]

The seed makes the random simulation reproducible. It has no physical meaning.

```python
maximum_delay_hours = 12
total_hours = 168 + 12 = 180
```

The extra 12-hour **clearing tail** lets a flexible job arriving in hour 167 use its complete 12-hour allowance.

Important: the fixed IT load also continues during these 12 extra hours, so summary energy and cost cover **180 hours**, not only the original week.

---

## 2.2 IT capacity

```python
it_power_capacity_mw = 10.0
fixed_it_power_fraction = 0.10
target_flexible_it_load_fraction = 0.40
```

Let

[
K^{IT}=10\text{ MW}.
]

This is a **synthetic scale assumption**, not a measured Virginia facility capacity.

Fixed IT power is

[
P^{fixed}=0.10K^{IT}=1\text{ MW}.
]

For a one-hour period,

[
E^{fixed}*t=P^{fixed}\Delta t=1\text{ MWh}*{IT}.
]

The remaining flexible processing capacity is

[
K^{flex}
========

# (K^{IT}-P^{fixed})\Delta t

# (10-1)(1)

9\text{ MWh}_{IT}/\text{hour}.
]

The target average flexible arrival load is

[
\bar A^{flex}=0.40K^{IT}=4\text{ MWh}_{IT}/\text{hour}.
]

Thus, before congestion or truncation, the model targets approximately

[
1+4=5\text{ MW},
]

or 50% average IT utilization. All three percentages and the 10 MW scale are synthetic.

---

## 2.3 Job arrival rate

```python
mean_job_arrivals_per_hour = 8.0
daily_arrival_amplitude = 0.025
```

The hourly rate is

[
\lambda_t
=========

8\left[
1+0.025\sin\left(
\frac{2\pi(h_t-13)}{24}
\right)
\right].
]

Then

[
N_t\sim\operatorname{Poisson}(\lambda_t).
]

This is a discretized non-homogeneous Poisson process: each hour has its own expected arrival count. NumPy interprets `lam` as the expected number of events in the interval. ([NumPy][2])

The **2.5% daily amplitude** is adapted from the business-schedule demand sensitivity in the attached PSCC model. There it describes energy demand, while here it is applied to job counts, so this is still a modeling assumption rather than empirical arrival data. 

The value of eight jobs per hour is fully synthetic.

---

## 2.4 Job energy

```python
job_energy_lognormal_sigma = 0.80
maximum_single_job_energy_mwh = 3.0
```

Job energy (X_j) is drawn from

[
X_j\sim\operatorname{Lognormal}(\mu_{\log},\sigma_{\log}^2),
\qquad
\sigma_{\log}=0.8.
]

For a lognormal random variable,

[
\mathbb E[X_j]
==============

\exp\left(
\mu_{\log}+\frac{\sigma_{\log}^2}{2}
\right).
]

The desired mean before capping is

[
\bar e
======

# \frac{4\text{ MWh/hour}}{8\text{ jobs/hour}}

0.5\text{ MWh/job}.
]

Therefore, the code sets

[
\mu_{\log}
==========

\log(0.5)-\frac{0.8^2}{2}.
]

NumPy’s `mean` and `sigma` inputs refer to the underlying normal variable (\log X), not directly to (X). ([NumPy][3])

Finally,

[
E_j=\min{X_j,3\text{ MWh}}.
]

The lognormal distribution, (\sigma=0.8), and the 3 MWh cap are **synthetic**. Production traces support heterogeneous workloads, but they do not justify these exact values. Google’s public Borg traces contain real job submissions, scheduling events, and resource use and are the appropriate future calibration source. ([GitHub][4])

Because of the cap, the actual expected job energy is slightly below 0.5 MWh.

---

## 2.5 Deadline classes

```python
("urgent_0h", 0)
("short_4h", 4)
("flexible_12h", 12)
```

with probabilities

[
(0.30,;0.45,;0.25).
]

For job (j),

[
d_j=a_j+L_j,
]

where (a_j) is its arrival hour and (L_j\in{0,4,12}) is its maximum delay.

These classes and probabilities are **synthetic scenario choices**.

The underlying idea—delay temporally flexible workloads while retaining completion requirements—is well established in carbon-aware data-center scheduling. Google’s carbon-aware system delays flexible work toward lower-carbon hours while preserving required daily capacity. ([arXiv][5])

A 0-hour job must be completed in its arrival hour. Consequently, the LP becomes infeasible if urgent work in one hour exceeds the 9 MWh flexible capacity.

---

## 2.6 PUE

```python
pue = 1.25
```

Power Usage Effectiveness is

[
PUE_t
=====

\frac{E^{DC}_t}{E^{IT}_t}.
]

Therefore,

[
E^{DC}_t=PUE_tE^{IT}_t,
]

and

[
E^{aux}_t
=========

# E^{DC}_t-E^{IT}_t

(PUE_t-1)E^{IT}_t.
]

LBNL defines PUE as total facility electricity divided by IT electricity. It estimates a U.S. average near 1.4 in 2023 and projects an average range of 1.15–1.35 by 2028. Thus, (1.25) is a reasonable **efficient-facility scenario**, but it is not a measured PUE for a particular Virginia data center. 

With (PUE=1.25),

[
E^{aux}_t=0.25E^{IT}_t.
]

---

## 2.7 Direct/site water

```python
site_water_consumption_m3_per_mwh_it = 0.36
```

The code interprets WUE as **site water consumption**:

[
W^{site,cons}_t
===============

WUE_tE^{IT}_t.
]

Since

[
1\text{ L/kWh}=1\text{ m}^3/\text{MWh},
]

the LBNL value of approximately (0.36\text{ L/kWh}_{IT}) becomes

[
WUE=0.36\text{ m}^3/\text{MWh}_{IT}.
]

LBNL defines site WUE as site water consumption divided by IT electricity and reports a U.S. average slightly above 0.36 L/kWh through 2023. It also emphasizes that WUE varies substantially with cooling system, climate, and operations. 

This is a national-average proxy, not observed site withdrawal.

---

## 2.8 Cooling-tower water balance

```python
cooling_tower_cycles_of_concentration = 4.0
```

Let

* (M_t): makeup water or withdrawal;
* (E_t): evaporation, treated here as consumption;
* (B_t): blowdown or discharge;
* (C): cycles of concentration.

Ignoring drift, leaks, and storage,

[
M_t=E_t+B_t.
]

The cycles approximation is

[
C\approx\frac{M_t}{B_t}.
]

Combining them,

[
B_t=\frac{E_t}{C-1},
]

and

[
M_t=E_t+B_t.
]

With (C=4),

[
W^{discharge}_t
===============

\frac{W^{cons}_t}{3},
]

and

[
W^{withdrawal}_t
================

\frac{4}{3}W^{cons}_t.
]

DOE states that many cooling towers operate at two to four cycles of concentration. The exact feasible value depends on water chemistry and treatment. ([The Department of Energy's Energy.gov][6])

---

## 2.9 Indirect grid water and emissions

```python
grid_water_consumption_m3_per_mwh = 4.52
grid_emissions_kg_per_mwh = 340.0
```

Indirect grid water is

[
W^{grid}_t
==========

\beta_t E^{grid}_t.
]

Operational grid emissions are

[
CO_{2,t}
========

\varepsilon_tE^{grid}_t.
]

LBNL estimates 2023 national data-center-weighted averages of

[
\beta=4.52\text{ L/kWh}
=======================

4.52\text{ m}^3/\text{MWh}
]

and

[
\varepsilon=0.34\text{ kg/kWh}
==============================

340\text{ kg/MWh}.
]

These are **average grid-mix accounting factors**, not PJM marginal emissions or Virginia-node-specific intensities. 

---

## 2.10 Electricity price

```python
average_grid_price_per_mwh = 31.08
```

The average is calibrated to the PJM-wide 2023 real-time load-weighted LMP:

[
\bar p=$31.08/\text{MWh}.
]

Monitoring Analytics reports that PJM’s real-time load-weighted average LMP fell to $31.08/MWh in 2023. ([Monitoring Analytics][7])

This is a wholesale-energy proxy. It is not:

* a Dominion-specific node price;
* a retail utility tariff;
* a power-purchase agreement;
* a full bill including capacity, transmission, demand, and fixed charges.

Your prior model correctly identifies PJM LMP as a wholesale proxy rather than the complete data-center electricity bill. 

---

## 2.11 Objective weights

```python
carbon_price_per_metric_ton = 50.0
water_externality_price_per_m3 = 0.0
delay_penalty_per_mwh_hour = 0.50
```

These are entirely **scenario weights**:

[
\pi^{CO2}=$50/\text{tCO}_2e,
]

[
\pi^W=$0/\text{m}^3,
]

[
\pi^Q=$0.50/(\text{MWh}_{IT}\cdot\text{hour}).
]

They are not claimed tariffs or estimated willingness-to-pay values.

**Note (updated):** these dollar prices no longer drive the schedule. The
scheduler uses the normalized weighted objective described in the update at the
top of this document, and water now varies over the day, so it genuinely affects
the schedule. The carbon/water prices only feed the dollar-denominated reporting
columns.

---

# 3. `generate_exogenous_profiles`

The function creates the hourly price and emissions signals.

## 3.1 Time indexes

```python
t = np.arange(total_hours)
hour_of_day = t % 24
day = t // 24
```

Mathematically,

[
h_t=t\bmod 24,
\qquad
d_t=\left\lfloor\frac{t}{24}\right\rfloor.
]

---

## 3.2 Synthetic hourly price

[
p_t
===

31.08
+
12\sin\left(
\frac{2\pi(h_t-14)}{24}
\right)
+
\xi_t,
]

where

[
\xi_t\sim N(0,3^2).
]

The sinusoid peaks around hour 20, or 8 p.m.

The code then shifts the complete generated series so that its sample mean is 31.08:

```python
grid_price += average_price - grid_price.mean()
```

Finally,

[
p_t\leftarrow\max{p_t,1}.
]

The average level is source-calibrated; the sinusoidal amplitude, phase, Gaussian noise, and $1 floor are synthetic.

---

## 3.3 Synthetic hourly emissions

[
\varepsilon_t
=============

340
+
55\cos\left(
\frac{2\pi(h_t-20)}{24}
\right)
+
\zeta_t,
]

where

[
\zeta_t\sim N(0,15^2).
]

The series is recentered to a sample mean of 340 kg/MWh and clipped below at 50 kg/MWh.

The average is source-calibrated. The hourly shape is synthetic.

### Phases (corrected)

Price and emissions now peak at **different** hours, so the two objectives
genuinely compete:

* price peaks in the evening (~h=19);
* emissions peak in the early morning (~h=5) and trough at midday.

The cheapest hours are therefore not the cleanest hours, which is what produces
a non-degenerate cost-versus-carbon Pareto frontier.

---

## 3.4 Water and PUE profiles

PUE is repeated in every hour ((PUE_t=1.25)). Site WUE and grid water now vary
over the day around their calibrated means ((\overline{WUE}=0.36),
(\overline{\beta}=4.52)), following the mid-afternoon water-stress shape.

All are kept as columns so real hourly PJM, Cambium, WUE, or weather-derived data
can later replace them without changing the optimization structure.

---

# 4. `generate_job_arrivals`

## 4.1 Generate hourly job counts

For every arrival hour,

[
N_t\sim\operatorname{Poisson}(\lambda_t).
]

This creates an integer count of jobs.

---

## 4.2 Generate each job’s energy

For each of the (N_t) jobs,

[
E_j
===

\min{
\operatorname{Lognormal}(\mu_{\log},0.8^2),
3
}.
]

Each job therefore has positive, right-skewed IT-energy demand.

---

## 4.3 Assign deadline classes

Each job independently receives one of the three classes using probabilities

[
P(L_j=0)=0.30,
]

[
P(L_j=4)=0.45,
]

[
P(L_j=12)=0.25.
]

The job table stores:

* job identifier;
* arrival hour;
* deadline class;
* maximum delay;
* deadline hour;
* IT-energy demand.

---

## 4.4 Aggregate jobs

The optimization does not retain individual job identities.

It constructs

[
a_{c,t}
=======

\sum_{\substack{j:,a_j=t\\text{class}(j)=c}}
E_j,
]

where (a_{c,t}) is arriving IT work in (\mathrm{MWh}_{IT}) for class (c) during hour (t).

The final 12 hours have

[
a_{c,t}=0,
]

because they exist only to clear the queue.

---

# 5. `solve_temporal_schedule`: optimization model

Let

[
\mathcal C
==========

{\text{urgent},\text{short},\text{flexible}}.
]

## 5.1 Decision variables

[
s_{c,t}\ge0:
\quad
\text{class-}c\text{ IT work processed in hour }t,
]

[
q_{c,t}\ge0:
\quad
\text{class-}c\text{ work left queued after hour }t.
]

Units are (\mathrm{MWh}_{IT}), not numbers of jobs.

---

## 5.2 Queue equation

The code creates

[
q_{c,t}+s_{c,t}-q_{c,t-1}=a_{c,t},
]

or equivalently,

[
q_{c,t}
=======

q_{c,t-1}+a_{c,t}-s_{c,t}.
]

For (t=0),

[
q_{c,-1}=0.
]

This is the continuous-energy version of your original job-flow equation

[
Q_{t+1}=Q_t+A_t-S_t.
]



Because arrivals during hour (t) appear in the same equation as service during hour (t), work may be processed immediately in its arrival hour.

---

## 5.3 IT capacity

[
\sum_{c\in\mathcal C}s_{c,t}
\le
9\text{ MWh}_{IT}
\qquad\forall t.
]

Adding the fixed 1 MWh gives

[
E^{IT}_t
========

1+\sum_c s_{c,t}
\le10\text{ MWh}_{IT}.
]

Thus, IT utilization cannot exceed 100%.

---

## 5.4 Deadlines

For class (c) with maximum delay (L_c), by hour (t) the scheduler must have processed everything that arrived by (t-L_c):

[
\sum_{\tau=0}^{t}s_{c,\tau}
\ge
\sum_{\tau=0}^{t-L_c}a_{c,\tau},
\qquad
t\ge L_c.
]

Examples:

### Urgent class: (L_c=0)

[
\sum_{\tau=0}^{t}s_{c,\tau}
\ge
\sum_{\tau=0}^{t}a_{c,\tau}.
]

Together with queue balance, this forces urgent work to be processed during its arrival hour.

### Four-hour class: (L_c=4)

By hour (t), every unit arriving by hour (t-4) must be complete.

### Twelve-hour class

By hour (t), every unit arriving by hour (t-12) must be complete.

---

## 5.5 Terminal condition

[
q_{c,T-1}=0
\qquad\forall c.
]

No work may remain after the clearing tail.

---

# 6. The two policies

## 6.1 ASAP policy

The ASAP objective is

[
\min_{s,q}
\sum_{c,t}q_{c,t}.
]

With hourly intervals, this sum has units of

[
\mathrm{MWh}_{IT}\text{-hour}.
]

It is the discrete area under the queue. Minimizing it pushes work as early as capacity and deadlines allow.

This is closely related to Little’s Law and its sample-path interpretation: the area under the queue measures total accumulated waiting. ([PubsOnline][8])

The policy is not explicitly earliest-deadline-first. Deadline constraints ensure feasibility, while the total-queue objective encourages early service. There may be multiple equally optimal class allocations when they produce the same total queue.

---

## 6.2 Impact-aware policy

For one additional (\mathrm{MWh}_{IT}) processed during hour (t), the model calculates:

### Electricity cost

[
m_t^E
=====

PUE_t,p_t.
]

Units:

[
\frac{\mathrm{MWh}*{grid}}{\mathrm{MWh}*{IT}}
\frac{$}{\mathrm{MWh}_{grid}}
=============================

\frac{$}{\mathrm{MWh}_{IT}}.
]

### Carbon externality

[
m_t^{CO2}
=========

PUE_t
\frac{\varepsilon_t}{1000}
\pi^{CO2}.
]

The division by 1000 converts kilograms to metric tons.

### Water externality

[
m_t^W
=====

\pi^W
\left(
WUE_t+PUE_t\beta_t
\right).
]

The first term is direct site water per IT MWh; the second is grid water induced by the additional facility electricity.

### Total processing coefficient

[
m_t
===

m_t^E+m_t^{CO2}+m_t^W.
]

The impact-aware optimization is

[
\min_{s,q}
\sum_{c,t}
\left[
m_ts_{c,t}
+
\pi^Qq_{c,t}
\right].
]

The delay term prevents all flexible work from waiting until only the cheapest hour.

This structure follows the standard carbon-aware scheduling principle: temporally flexible work is shifted toward lower-impact hours while capacity and completion requirements remain satisfied. ([arXiv][5])

---

## 6.3 Matrix implementation

The code stores the variable vector as

[
x=
\begin{bmatrix}
s\q
\end{bmatrix}.
]

It then constructs:

* `A_eq`, `b_eq`: queue equations and terminal queues;
* `A_ub`, `b_ub`: capacity and deadline constraints;
* `bounds=(0,None)`: nonnegativity.

Deadline inequalities are multiplied by (-1) because SciPy expects constraints in the form

[
A_{ub}x\le b_{ub}.
]

---

# 7. `evaluate_schedule`: physical accounting

## 7.1 Flexible workload totals

[
A^{flex}*t=\sum_ca*{c,t},
]

[
S^{flex}*t=\sum_cs*{c,t},
]

[
Q^{flex}*t=\sum_cq*{c,t}.
]

---

## 7.2 IT electricity

Fixed IT energy:

[
E^{fixed}_t
===========

# P^{fixed}\Delta t

1\text{ MWh}.
]

Total IT energy:

[
E^{IT}_t
========

E^{fixed}_t+S^{flex}_t.
]

IT utilization:

[
u_t
===

\frac{E^{IT}_t}
{K^{IT}\Delta t}.
]

Because (\Delta t=1) hour, the numerical value of MWh during the hour is also the average MW over that hour, but power and energy remain conceptually different quantities.

---

## 7.3 Facility and grid electricity

The baseline assumes grid-only operation:

[
E^{grid}_t=E^{DC}_t.
]

Using PUE,

[
E^{DC}_t
========

PUE_tE^{IT}_t,
]

and

[
E^{aux}_t
=========

# E^{DC}_t-E^{IT}_t

(PUE_t-1)E^{IT}_t.
]

No solar, storage, local generation, or backup-generator dispatch is modeled.

---

## 7.4 Site water

[
W^{site,cons}_t
===============

WUE_tE^{IT}_t.
]

The code treats this consumption as cooling-tower evaporation.

Then

[
W^{site,discharge}_t
====================

\frac{W^{site,cons}_t}{C-1},
]

and

[
W^{site,withdrawal}_t
=====================

W^{site,cons}_t
+
W^{site,discharge}_t.
]

This ignores drift, leaks, storage changes, alternative cooling technologies, and reclaimed-water shares.

---

## 7.5 Indirect grid water

[
W^{grid}_t
==========

\beta_tE^{grid}_t.
]

The reported total water footprint is

[
W^{footprint}_t
===============

W^{site,cons}_t+W^{grid}_t.
]

It is an environmental consumption footprint. It is **not** the physical water entering the data-center site. Your modeling document makes this same direct-versus-indirect distinction. 

---

## 7.6 Operational emissions

[
CO_{2,t}^{grid}
===============

\frac{\varepsilon_tE^{grid}_t}{1000}
\quad
[\text{metric tons CO}_2e].
]

These are operational electricity emissions only. They exclude:

* construction;
* server and chip manufacturing;
* backup-generator emissions;
* refrigerants;
* upstream embodied emissions.

Because (\varepsilon_t) varies synthetically by hour, temporal shifting can change total modeled emissions even when total electricity remains constant.

---

## 7.7 Heat

The code sets

[
H^{rejected}_t
\approx
E^{DC}_t.
]

This is a first-order steady-state energy balance: essentially all facility electricity ultimately leaves the facility as heat.

It does not separately model:

* cooling-system COP;
* heat storage;
* heat reuse;
* sensible versus latent heat;
* heat carried away in water or exhaust air.

Your attached model explicitly proposes (H_t\approx E_t^{DC}) as the simplest heat-accounting approximation. 

---

## 7.8 Costs

Electricity:

[
C_t^E=p_tE^{grid}_t.
]

Carbon externality:

[
C_t^{CO2}
=========

\pi^{CO2}CO_{2,t}^{grid}.
]

Water externality:

[
C_t^W
=====

\pi^WW_t^{footprint}.
]

Delay:

[
C_t^Q
=====

\pi^QQ_t^{flex}.
]

Reported modeled cost:

[
C_t^{model}
===========

C_t^E+C_t^{CO2}+C_t^W+C_t^Q.
]

This is not a complete financial operating cost. It omits server costs, labor, demand charges, capacity charges, network costs, cooling maintenance, and other facility expenses.

---

## 7.9 Average delay

The code calculates

[
\bar D
======

\frac{\sum_tQ^{flex}_t}
{\sum_tA^{flex}_t}.
]

Units are hours.

This is an **energy-weighted average delay**:

* a 2 MWh job has twice the weight of a 1 MWh job;
* it is not the simple average delay across job identifiers.

It is appropriate because the LP schedules continuous IT energy rather than complete indivisible jobs.

---

# 8. `validate_solution`

The validation checks four conditions.

## Capacity

[
\sum_cs_{c,t}
\le K^{flex}.
]

## Nonnegative queues

[
q_{c,t}\ge0.
]

## Deadlines

[
\sum_{\tau=0}^{t}s_{c,\tau}
\ge
\sum_{\tau=0}^{t-L_c}a_{c,\tau}.
]

## Empty terminal queues

[
q_{c,T-1}=0.
]

The tolerance is

[
10^{-6}.
]

One small inconsistency: the docstring says queue balance is independently validated, but the function does not recompute

[
q_{c,t}=q_{c,t-1}+a_{c,t}-s_{c,t}.
]

The solver enforces it, but the separate validation routine does not check it again.

---

# 9. `save_plots`

The code creates four diagnostics.

1. `01_operating_conditions.png`: synthetic hourly price and emissions intensity.

2. `02_workload_schedule.png`: arriving flexible work and processing under both policies.

3. `03_queue.png`: remaining queue under each policy.

4. `04_cumulative_electricity_cost.png`: cumulative wholesale electricity-cost proxy.

These plots are diagnostics, not additional model components.

---

# 10. `run_simulation`

The execution sequence is:

[
\text{configuration}
\rightarrow
\text{profiles}
\rightarrow
\text{jobs}
\rightarrow
\text{optimization}
\rightarrow
\text{validation}
\rightarrow
\text{accounting}
\rightarrow
\text{outputs}.
]

Specifically:

1. Create the output directory.
2. Initialize one reproducible random generator.
3. Generate price, emissions, PUE, and WUE profiles.
4. Generate individual jobs.
5. Aggregate arrivals by class and hour.
6. Solve ASAP.
7. Validate and evaluate ASAP.
8. Solve impact-aware.
9. Validate and evaluate impact-aware.
10. Combine the results.
11. Save CSVs and plots.
12. Print a compact summary.

---

# 11. Output files

| File                                | Meaning                                            |
| ----------------------------------- | -------------------------------------------------- |
| `jobs.csv`                          | One row per generated job                          |
| `arrival_rate.csv`                  | Expected hourly Poisson rate (\lambda_t)           |
| `arrivals_by_deadline_class.csv`    | Arriving MWh by class and hour                     |
| `exogenous_profiles.csv`            | Price, emissions, water factors, PUE and WUE       |
| `service_<scenario>.csv`            | Processing by class for asap and each focus        |
| `queue_<scenario>.csv`              | Queue by class for asap and each focus             |
| `hourly_results_all_scenarios.csv`  | Complete hourly physical accounting                |
| `summary_comparison.csv`            | Aggregate comparison across focus scenarios        |
| `tradeoff_normalized.csv`           | Each objective rescaled to [0,1] (best->worst)     |
| `pareto_sweep.csv`                  | Pairwise weight sweep: totals at each weight step  |

---

# 12. Most important interpretation points

1. **The LP schedules energy, not actual indivisible jobs.** Jobs are generated individually but then aggregated by arrival hour and deadline class.

2. **The model is an offline oracle.** It knows all future arrivals, prices, and emissions. A real controller would use a rolling horizon and forecasts.

3. **The exact job distribution is synthetic.** Only the broad idea of heterogeneous, temporally flexible workload is literature-supported.

4. **PUE, WUE, grid water, emissions, and price are credible average proxies, not facility-specific observations.**

5. **Water now affects scheduling.** Its intensities vary over the day (afternoon peak), so a water focus shifts work out of the hot afternoon hours.

6. **Price, emissions, and water have distinct diurnal phases** (evening, early morning, mid-afternoon), which is what makes the three objectives genuinely compete.

7. **Total water, emissions, and cost now differ between schedules** because all three hourly intensities vary. (Heat and total energy stay essentially fixed, since total completed work and PUE are constant.)

8. **The solver objective is not comparable across scenarios.** For ASAP it is a queue inventory; for the weighted scenarios it is a dimensionless weighted-normalized impact. The comparable quantities are the physical totals (`electricity_cost_usd`, `grid_co2e_metric_tons`, `total_water_footprint_m3`).

9. **Average delay is MWh-weighted**, not job-count-weighted.

10. **The model is a proxy-based operational simulation**, not evidence of the actual operation of a specific Virginia data center.

[1]: https://docs.scipy.org/doc/scipy-1.13.1/reference/optimize.linprog-highs.html?utm_source=chatgpt.com "linprog(method=’highs’) — SciPy v1.13.1 Manual"
[2]: https://numpy.org/doc/1.21/reference/random/generated/numpy.random.poisson.html?utm_source=chatgpt.com "numpy.random.poisson — NumPy v1.21 Manual"
[3]: https://numpy.org/doc/1.14/reference/generated/numpy.random.lognormal.html?utm_source=chatgpt.com "numpy.random.lognormal — NumPy v1.14 Manual"
[4]: https://github.com/google/cluster-data "GitHub - google/cluster-data: Borg cluster traces from Google · GitHub"
[5]: https://arxiv.org/abs/2106.11750?utm_source=chatgpt.com "Carbon-Aware Computing for Datacenters"
[6]: https://www.energy.gov/cmei/femp/best-management-practice-10-cooling-tower-management "Best Management Practice #10: Cooling Tower Management | Department of Energy"
[7]: https://www.monitoringanalytics.com/reports/PJM_State_of_the_Market/2023/2023-som-pjm-vol1.pdf "2023 Annual State of the Market Report for PJM"
[8]: https://pubsonline.informs.org/doi/fpi/10.1287/opre.9.3.383?utm_source=chatgpt.com "A Proof for the Queuing Formula: L = λW | Operations Research"
