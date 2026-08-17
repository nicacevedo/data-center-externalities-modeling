"""
First prototype: temporal allocation of deferrable data-center jobs.

The model is intentionally small, linear, and readable.

Main idea
---------
1. Jobs arrive each hour.
2. Each job has an IT-energy requirement and a maximum delay.
3. The scheduler decides how much queued IT work to process each hour.
4. IT energy is converted to total facility/grid energy with PUE.
5. The simulation accounts for electricity cost, direct site water,
   indirect grid water, operational CO2 emissions, and rejected heat.

Multi-objective focus
---------------------
The scheduler trades off three "costs" that a data center can care about:
electricity cost, operational CO2 emissions, and water stress. Each is
normalized to a common dimensionless scale, and the scheduler minimizes a
weighted sum with weights in [0, 1]. By sweeping the weights we trace the
pairwise Pareto frontiers and see how operation shifts when the focus changes.

Important scope
---------------
- One data center and hourly time steps.
- Work is aggregated by deadline class and is divisible/preemptible.
- The optimization has perfect information over the simulated horizon.
  It is therefore an "oracle" baseline, not yet an online controller.
- Grid-only normal operation. Backup generation is intentionally excluded
  from the baseline and should be added as a separate outage/testing module.
- PUE is constant in the baseline. The three hourly *intensity* signals
  (price, grid emissions, water) have source-calibrated annual means; only
  their diurnal shapes are synthetic and are given distinct phases so that
  the three objectives genuinely compete.

Run
---
    python data_center_job_allocation_prototype.py

Outputs are written to ./data_center_prototype_outputs/.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy.sparse import csr_matrix, lil_matrix


# ============================================================================
# 1. Parameters
# ============================================================================


@dataclass(frozen=True)
class SimulationConfig:
    """All assumptions are collected in one place for easy editing."""

    # Reproducibility and horizon
    seed: int = 123456
    number_of_days: int = 7
    time_step_hours: float = 1.0

    # IT system
    it_power_capacity_mw: float = 10.0
    fixed_it_power_fraction: float = 0.10
    target_flexible_it_load_fraction: float = 0.40

    # Synthetic job arrivals
    mean_job_arrivals_per_hour: float = 8.0
    daily_arrival_amplitude: float = 0.025
    job_energy_lognormal_sigma: float = 0.80
    maximum_single_job_energy_mwh: float = 3.0

    # Deadline classes: name -> maximum delay in hours
    deadline_hours: Tuple[Tuple[str, int], ...] = (
        ("urgent_0h", 0),
        ("short_4h", 4),
        ("flexible_12h", 12),
    )
    deadline_probabilities: Tuple[float, ...] = (0.30, 0.45, 0.25)

    # Facility resource intensities
    # Efficient large-facility proxy within the 1.15-1.35 range discussed
    # by LBNL for 2028 scenarios.
    pue: float = 1.25

    # 2023 U.S. average site WUE reported by LBNL: about 0.36 L/kWh_IT,
    # numerically equal to 0.36 m^3/MWh_IT. Used as the *daily mean*.
    site_water_consumption_m3_per_mwh_it: float = 0.36

    # Cooling-tower water balance assumption. DOE notes many systems operate
    # at 2-4 cycles; 4 is used as a readable baseline.
    cooling_tower_cycles_of_concentration: float = 4.0

    # 2023 U.S. data-center-weighted average grid impacts reported by LBNL.
    # Used as the *daily means* of the hourly signals below.
    grid_water_consumption_m3_per_mwh: float = 4.52
    grid_emissions_kg_per_mwh: float = 340.0

    # --- Diurnal shapes (means above are source-calibrated; shapes synthetic) --
    # Each signal is given a DISTINCT daily phase, loosely motivated by a real
    # driver, so that the three objectives do not collapse into one:
    #   * price     peaks in the evening   (system demand peak).
    #   * emissions peak in the early morning (fossil baseload on the margin,
    #     no solar), and trough at midday.
    #   * water     peaks in mid-afternoon (hot wet-bulb -> more cooling-tower
    #     evaporation on site and more thermal cooling water off site).

    # Synthetic hourly wholesale price profile calibrated to the 2023 PJM
    # real-time load-weighted average LMP of $31.08/MWh.
    average_grid_price_per_mwh: float = 31.08
    grid_price_daily_amplitude: float = 12.0
    grid_price_peak_hour: float = 19.0
    grid_price_noise_sd: float = 3.0

    # Synthetic hourly emissions variation around the LBNL average.
    grid_emissions_daily_amplitude: float = 55.0
    grid_emissions_peak_hour: float = 5.0
    grid_emissions_noise_sd: float = 15.0

    # Synthetic hourly water-intensity variation (site WUE and grid water).
    water_daily_amplitude_fraction: float = 0.35
    water_peak_hour: float = 15.0
    water_noise_fraction: float = 0.05

    # --- Scheduling objective ------------------------------------------------
    # The scheduler minimizes a weighted sum of three NORMALIZED marginal
    # impacts (each rescaled to mean 1 over the horizon). Weights live in
    # [0, 1]; only their relative size matters. A tiny queue tie-breaker makes
    # the schedule prefer earlier processing among otherwise-equivalent hours,
    # without materially distorting the impact tradeoff.
    default_weights: Tuple[float, float, float] = (1.0 / 3, 1.0 / 3, 1.0 / 3)
    queue_tiebreak_weight: float = 1e-3

    # Externality prices used ONLY for the dollar-denominated accounting
    # columns; they do not drive the schedule (that is done by the weights).
    carbon_price_per_metric_ton: float = 50.0
    water_externality_price_per_m3: float = 0.0
    delay_penalty_per_mwh_hour: float = 0.50

    # Pareto sweep resolution (number of weight steps from 0 to 1).
    pareto_grid_points: int = 11

    # Output
    output_directory: str = "data_center_prototype_outputs"

    @property
    def arrival_hours(self) -> int:
        return int(self.number_of_days * 24 / self.time_step_hours)

    @property
    def maximum_delay_hours(self) -> int:
        return max(delay for _, delay in self.deadline_hours)

    @property
    def total_hours(self) -> int:
        # Add a clearing tail so jobs arriving near the end retain their full
        # allowed delay instead of being forced to finish artificially early.
        return self.arrival_hours + self.maximum_delay_hours

    @property
    def fixed_it_power_mw(self) -> float:
        return self.fixed_it_power_fraction * self.it_power_capacity_mw

    @property
    def flexible_it_capacity_mwh_per_step(self) -> float:
        return (
            self.it_power_capacity_mw - self.fixed_it_power_mw
        ) * self.time_step_hours

    @property
    def target_flexible_work_mwh_per_hour(self) -> float:
        return self.target_flexible_it_load_fraction * self.it_power_capacity_mw

    @property
    def mean_job_energy_mwh(self) -> float:
        # Calibrate the job size so the expected flexible arrival load is the
        # desired fraction of IT capacity.
        return (
            self.target_flexible_work_mwh_per_hour
            / self.mean_job_arrivals_per_hour
        )

    @property
    def deadline_map(self) -> Dict[str, int]:
        return dict(self.deadline_hours)


# The three competing objectives, in a fixed order used throughout.
OBJECTIVE_NAMES: Tuple[str, str, str] = ("cost", "emissions", "water")
OBJECTIVE_LABELS: Dict[str, str] = {
    "cost": "Electricity cost ($)",
    "emissions": "CO2 emissions (t)",
    "water": "Water footprint (m3)",
}


# ============================================================================
# 2. Synthetic exogenous profiles
# ============================================================================


def _recentered(series: np.ndarray, target_mean: float, floor: float) -> np.ndarray:
    """Shift a series to a target sample mean, then clip below at ``floor``."""
    series = series + (target_mean - series.mean())
    return np.clip(series, floor, None)


def generate_exogenous_profiles(
    config: SimulationConfig,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Create hourly price and environmental-intensity profiles.

    Their annual-average levels are source-calibrated. Their hourly shapes are
    transparent synthetic profiles, each with a DISTINCT daily phase, used only
    to exercise the scheduling model. Replace these columns with
    PJM/Cambium/weather data when available.
    """

    t = np.arange(config.total_hours)
    hour_of_day = t % 24
    day = t // 24

    def diurnal(peak_hour: float) -> np.ndarray:
        # A cosine that equals +1 at ``peak_hour`` and -1 twelve hours later.
        return np.cos(2 * np.pi * (hour_of_day - peak_hour) / 24)

    # Price: evening demand peak.
    grid_price = (
        config.average_grid_price_per_mwh
        + config.grid_price_daily_amplitude * diurnal(config.grid_price_peak_hour)
        + rng.normal(0.0, config.grid_price_noise_sd, config.total_hours)
    )
    grid_price = _recentered(grid_price, config.average_grid_price_per_mwh, 1.0)

    # Grid emissions: early-morning fossil peak, midday solar trough.
    grid_emissions = (
        config.grid_emissions_kg_per_mwh
        + config.grid_emissions_daily_amplitude
        * diurnal(config.grid_emissions_peak_hour)
        + rng.normal(0.0, config.grid_emissions_noise_sd, config.total_hours)
    )
    grid_emissions = _recentered(grid_emissions, config.grid_emissions_kg_per_mwh, 50.0)

    # Water intensities: mid-afternoon (hot wet-bulb) peak. Site WUE and grid
    # water share the same weather-driven shape but keep their own mean levels.
    water_shape = 1.0 + config.water_daily_amplitude_fraction * diurnal(
        config.water_peak_hour
    )
    site_wue = config.site_water_consumption_m3_per_mwh_it * water_shape * (
        1.0 + rng.normal(0.0, config.water_noise_fraction, config.total_hours)
    )
    site_wue = _recentered(
        site_wue, config.site_water_consumption_m3_per_mwh_it, 0.05
    )
    grid_water = config.grid_water_consumption_m3_per_mwh * water_shape * (
        1.0 + rng.normal(0.0, config.water_noise_fraction, config.total_hours)
    )
    grid_water = _recentered(
        grid_water, config.grid_water_consumption_m3_per_mwh, 0.5
    )

    return pd.DataFrame(
        {
            "time": t,
            "day": day,
            "hour_of_day": hour_of_day,
            "grid_price_per_mwh": grid_price,
            "grid_emissions_kg_per_mwh": grid_emissions,
            "grid_water_m3_per_mwh": grid_water,
            "pue": config.pue,
            "site_wue_m3_per_mwh_it": site_wue,
        }
    )


# ============================================================================
# 3. Job arrivals
# ============================================================================


def generate_job_arrivals(
    config: SimulationConfig,
    rng: np.random.Generator,
) -> Tuple[pd.DataFrame, pd.DataFrame, np.ndarray]:
    """Generate job-level arrivals and aggregate them by deadline class.

    Job count follows a non-homogeneous Poisson process. Job IT-energy demand
    follows a capped lognormal distribution. The lognormal is used as a simple
    heavy-right-tail proxy for heterogeneous production workloads.
    """

    t = np.arange(config.arrival_hours)
    hour_of_day = t % 24

    # Small business-hour-like variation around the mean arrival rate.
    lambda_t = config.mean_job_arrivals_per_hour * (
        1.0
        + config.daily_arrival_amplitude
        * np.sin(2 * np.pi * (hour_of_day - 13) / 24)
    )
    lambda_t = np.clip(lambda_t, 0.01, None)
    jobs_per_hour = rng.poisson(lambda_t)

    # numpy.lognormal expects parameters of log(X), not mean(X).
    sigma_log = config.job_energy_lognormal_sigma
    mu_log = np.log(config.mean_job_energy_mwh) - 0.5 * sigma_log**2

    class_names = list(config.deadline_map)
    class_probabilities = np.asarray(config.deadline_probabilities, dtype=float)
    class_probabilities /= class_probabilities.sum()

    job_records = []
    job_id = 0

    for arrival_time, number_of_jobs in enumerate(jobs_per_hour):
        if number_of_jobs == 0:
            continue

        job_energy = rng.lognormal(mu_log, sigma_log, number_of_jobs)
        job_energy = np.minimum(
            job_energy,
            config.maximum_single_job_energy_mwh,
        )
        job_classes = rng.choice(
            class_names,
            size=number_of_jobs,
            p=class_probabilities,
        )

        for energy_mwh, job_class in zip(job_energy, job_classes):
            maximum_delay = config.deadline_map[job_class]
            job_records.append(
                {
                    "job_id": job_id,
                    "arrival_time": arrival_time,
                    "deadline_class": job_class,
                    "maximum_delay_hours": maximum_delay,
                    "deadline_time": arrival_time + maximum_delay,
                    "it_energy_mwh": float(energy_mwh),
                }
            )
            job_id += 1

    jobs = pd.DataFrame(job_records)

    # Full optimization horizon, including the zero-arrival clearing tail.
    arrivals = pd.DataFrame(
        0.0,
        index=np.arange(config.total_hours),
        columns=class_names,
    )

    if not jobs.empty:
        aggregated = jobs.pivot_table(
            index="arrival_time",
            columns="deadline_class",
            values="it_energy_mwh",
            aggfunc="sum",
            fill_value=0.0,
        )
        arrivals.loc[aggregated.index, aggregated.columns] = aggregated

    arrivals.index.name = "time"
    arrivals = arrivals.reset_index()

    return jobs, arrivals, lambda_t


# ============================================================================
# 4. Linear scheduling model
# ============================================================================


@dataclass(frozen=True)
class SchedulingProblem:
    """The part of the LP that does not depend on the objective.

    Built once and reused for every weight vector in the Pareto sweep, so the
    only thing that changes between solves is the objective vector.
    """

    class_names: List[str]
    total_hours: int
    number_of_variables: int
    number_of_service_variables: int
    a_eq: csr_matrix
    b_eq: np.ndarray
    a_ub: csr_matrix
    b_ub: np.ndarray

    def service_index(self, class_index: int, time_index: int) -> int:
        return class_index * self.total_hours + time_index

    def queue_index(self, class_index: int, time_index: int) -> int:
        return (
            self.number_of_service_variables
            + class_index * self.total_hours
            + time_index
        )


def build_scheduling_problem(
    arrivals: pd.DataFrame,
    config: SimulationConfig,
) -> SchedulingProblem:
    """Assemble the objective-independent constraints of the schedule LP.

    Variables
    ---------
    service[c,t] : MWh_IT of deadline class c processed in hour t
    queue[c,t]   : MWh_IT of class c left queued after hour t

    Constraints
    -----------
    queue[c,t] = queue[c,t-1] + arrivals[c,t] - service[c,t]
    sum_c service[c,t] <= flexible IT capacity
    cumulative service by t >= arrivals that are due by t
    terminal queue = 0
    """

    class_names = list(config.deadline_map)
    number_of_classes = len(class_names)
    total_hours = config.total_hours

    arrival_matrix = arrivals[class_names].to_numpy(dtype=float).T

    number_of_service_variables = number_of_classes * total_hours
    number_of_variables = 2 * number_of_service_variables

    def service_index(class_index: int, time_index: int) -> int:
        return class_index * total_hours + time_index

    def queue_index(class_index: int, time_index: int) -> int:
        return number_of_service_variables + class_index * total_hours + time_index

    # ----------------------------------------------------------------------
    # Equality constraints: queue dynamics and empty terminal queues
    # ----------------------------------------------------------------------
    number_of_equalities = number_of_classes * total_hours + number_of_classes
    equality_matrix = lil_matrix((number_of_equalities, number_of_variables))
    equality_rhs = np.zeros(number_of_equalities)

    row = 0
    for class_index in range(number_of_classes):
        for time_index in range(total_hours):
            equality_matrix[row, queue_index(class_index, time_index)] = 1.0
            equality_matrix[row, service_index(class_index, time_index)] = 1.0

            if time_index > 0:
                equality_matrix[row, queue_index(class_index, time_index - 1)] = -1.0

            equality_rhs[row] = arrival_matrix[class_index, time_index]
            row += 1

        # All work is completed by the end of the clearing tail.
        equality_matrix[row, queue_index(class_index, total_hours - 1)] = 1.0
        equality_rhs[row] = 0.0
        row += 1

    # ----------------------------------------------------------------------
    # Inequality constraints: IT capacity and deadline completion
    # ----------------------------------------------------------------------
    deadline_constraint_count = sum(
        total_hours - delay for delay in config.deadline_map.values()
    )
    number_of_inequalities = total_hours + deadline_constraint_count
    inequality_matrix = lil_matrix((number_of_inequalities, number_of_variables))
    inequality_rhs = np.zeros(number_of_inequalities)

    row = 0

    # Flexible IT processing capacity each hour.
    for time_index in range(total_hours):
        for class_index in range(number_of_classes):
            inequality_matrix[row, service_index(class_index, time_index)] = 1.0
        inequality_rhs[row] = config.flexible_it_capacity_mwh_per_step
        row += 1

    # Deadline constraints.
    # For class c with maximum delay L, by hour t we must have processed all
    # work that arrived on or before t-L.
    for class_index, class_name in enumerate(class_names):
        maximum_delay = config.deadline_map[class_name]
        cumulative_arrivals = np.cumsum(arrival_matrix[class_index])

        for time_index in range(maximum_delay, total_hours):
            for service_time in range(time_index + 1):
                inequality_matrix[row, service_index(class_index, service_time)] = -1.0

            due_arrival_time = time_index - maximum_delay
            inequality_rhs[row] = -cumulative_arrivals[due_arrival_time]
            row += 1

    return SchedulingProblem(
        class_names=class_names,
        total_hours=total_hours,
        number_of_variables=number_of_variables,
        number_of_service_variables=number_of_service_variables,
        a_eq=equality_matrix.tocsr(),
        b_eq=equality_rhs,
        a_ub=inequality_matrix.tocsr(),
        b_ub=inequality_rhs,
    )


def marginal_impacts(
    profiles: pd.DataFrame,
    config: SimulationConfig,
) -> Dict[str, np.ndarray]:
    """Marginal impact of processing one extra MWh_IT in hour t.

    Returns both the physical marginals (used for reporting) and their
    normalized (mean-1, dimensionless) versions used in the weighted objective.
    """

    pue = profiles["pue"].to_numpy()
    price = profiles["grid_price_per_mwh"].to_numpy()
    emissions = profiles["grid_emissions_kg_per_mwh"].to_numpy()
    grid_water = profiles["grid_water_m3_per_mwh"].to_numpy()
    site_wue = profiles["site_wue_m3_per_mwh_it"].to_numpy()

    cost = pue * price                       # $/MWh_IT
    emissions_t = pue * emissions / 1000.0   # tCO2e/MWh_IT
    water = site_wue + pue * grid_water      # m3/MWh_IT (site + indirect grid)

    marginals = {"cost": cost, "emissions": emissions_t, "water": water}
    for name in OBJECTIVE_NAMES:
        marginals[f"{name}_normalized"] = marginals[name] / marginals[name].mean()
    return marginals


def build_objective(
    problem: SchedulingProblem,
    marginals: Dict[str, np.ndarray],
    weights: Tuple[float, float, float],
    config: SimulationConfig,
) -> np.ndarray:
    """Weighted, normalized processing cost plus a tiny queue tie-breaker."""

    per_hour_cost = sum(
        weight * marginals[f"{name}_normalized"]
        for weight, name in zip(weights, OBJECTIVE_NAMES)
    )

    objective = np.zeros(problem.number_of_variables)
    for class_index in range(len(problem.class_names)):
        for time_index in range(problem.total_hours):
            objective[problem.service_index(class_index, time_index)] = per_hour_cost[
                time_index
            ]
            objective[problem.queue_index(class_index, time_index)] = (
                config.queue_tiebreak_weight
            )
    return objective


def build_asap_objective(problem: SchedulingProblem) -> np.ndarray:
    """Minimize total queue inventory (process as early as capacity allows)."""
    objective = np.zeros(problem.number_of_variables)
    for class_index in range(len(problem.class_names)):
        for time_index in range(problem.total_hours):
            objective[problem.queue_index(class_index, time_index)] = 1.0
    return objective


def solve_schedule(
    problem: SchedulingProblem,
    objective: np.ndarray,
    label: str = "schedule",
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Solve the LP for a given objective vector and return service/queue tables."""

    result = linprog(
        c=objective,
        A_ub=problem.a_ub,
        b_ub=problem.b_ub,
        A_eq=problem.a_eq,
        b_eq=problem.b_eq,
        bounds=[(0.0, None)] * problem.number_of_variables,
        method="highs",
    )
    if not result.success:
        raise RuntimeError(f"Scheduling model failed for '{label}': {result.message}")

    solution = result.x
    total_hours = problem.total_hours
    class_names = problem.class_names

    service = pd.DataFrame(index=np.arange(total_hours), columns=class_names, dtype=float)
    queue = pd.DataFrame(index=np.arange(total_hours), columns=class_names, dtype=float)

    for class_index, class_name in enumerate(class_names):
        for time_index in range(total_hours):
            service.loc[time_index, class_name] = solution[
                problem.service_index(class_index, time_index)
            ]
            queue.loc[time_index, class_name] = solution[
                problem.queue_index(class_index, time_index)
            ]

    service.index.name = "time"
    queue.index.name = "time"
    return service.reset_index(), queue.reset_index()


# ============================================================================
# 5. Physical and environmental accounting
# ============================================================================


def evaluate_schedule(
    scenario_name: str,
    arrivals: pd.DataFrame,
    service: pd.DataFrame,
    queue: pd.DataFrame,
    profiles: pd.DataFrame,
    config: SimulationConfig,
) -> Tuple[pd.DataFrame, pd.Series]:
    """Convert the scheduling result into energy, water, carbon, heat, and cost."""

    class_names = list(config.deadline_map)

    hourly = profiles.copy()
    hourly["scenario"] = scenario_name
    hourly["arriving_flexible_it_mwh"] = arrivals[class_names].sum(axis=1)
    hourly["processed_flexible_it_mwh"] = service[class_names].sum(axis=1)
    hourly["queued_flexible_it_mwh"] = queue[class_names].sum(axis=1)

    hourly["fixed_it_energy_mwh"] = config.fixed_it_power_mw * config.time_step_hours
    hourly["total_it_energy_mwh"] = (
        hourly["fixed_it_energy_mwh"] + hourly["processed_flexible_it_mwh"]
    )
    hourly["it_utilization"] = hourly["total_it_energy_mwh"] / (
        config.it_power_capacity_mw * config.time_step_hours
    )

    # Grid-only baseline: E_grid = E_DC = PUE * E_IT.
    hourly["dc_energy_mwh"] = hourly["pue"] * hourly["total_it_energy_mwh"]
    hourly["grid_energy_mwh"] = hourly["dc_energy_mwh"]
    hourly["auxiliary_energy_mwh"] = (
        hourly["dc_energy_mwh"] - hourly["total_it_energy_mwh"]
    )

    # Direct/site water: WUE is interpreted as net site water consumption.
    hourly["site_water_consumption_m3"] = (
        hourly["site_wue_m3_per_mwh_it"] * hourly["total_it_energy_mwh"]
    )

    cycles = config.cooling_tower_cycles_of_concentration
    if cycles <= 1.0:
        raise ValueError("Cooling-tower cycles of concentration must exceed 1.")

    # Ignoring drift and leaks:
    # blowdown = evaporation / (cycles - 1); withdrawal = evaporation + blowdown
    hourly["site_water_discharge_m3"] = (
        hourly["site_water_consumption_m3"] / (cycles - 1.0)
    )
    hourly["site_water_withdrawal_m3"] = (
        hourly["site_water_consumption_m3"] + hourly["site_water_discharge_m3"]
    )

    # Indirect water consumed by electricity generation.
    hourly["indirect_grid_water_consumption_m3"] = (
        hourly["grid_water_m3_per_mwh"] * hourly["grid_energy_mwh"]
    )
    hourly["total_water_footprint_m3"] = (
        hourly["site_water_consumption_m3"]
        + hourly["indirect_grid_water_consumption_m3"]
    )

    hourly["grid_co2e_metric_tons"] = (
        hourly["grid_emissions_kg_per_mwh"] * hourly["grid_energy_mwh"] / 1000.0
    )

    # Nearly all electricity consumed by the facility ultimately leaves as heat.
    hourly["heat_rejected_mwh_thermal"] = hourly["dc_energy_mwh"]

    hourly["electricity_cost_usd"] = (
        hourly["grid_price_per_mwh"] * hourly["grid_energy_mwh"]
    )
    hourly["carbon_externality_usd"] = (
        config.carbon_price_per_metric_ton * hourly["grid_co2e_metric_tons"]
    )
    hourly["water_externality_usd"] = (
        config.water_externality_price_per_m3 * hourly["total_water_footprint_m3"]
    )
    hourly["delay_cost_usd"] = (
        config.delay_penalty_per_mwh_hour * hourly["queued_flexible_it_mwh"]
    )

    total_flexible_work = hourly["arriving_flexible_it_mwh"].sum()
    average_delay = (
        hourly["queued_flexible_it_mwh"].sum() / total_flexible_work
        if total_flexible_work > 0
        else 0.0
    )

    summary = pd.Series(
        {
            "scenario": scenario_name,
            "flexible_it_work_mwh": total_flexible_work,
            "total_it_energy_mwh": hourly["total_it_energy_mwh"].sum(),
            "total_dc_grid_energy_mwh": hourly["grid_energy_mwh"].sum(),
            "average_it_utilization": hourly["it_utilization"].mean(),
            "peak_it_utilization": hourly["it_utilization"].max(),
            "average_delay_hours": average_delay,
            "peak_queue_mwh": hourly["queued_flexible_it_mwh"].max(),
            "electricity_cost_usd": hourly["electricity_cost_usd"].sum(),
            "grid_co2e_metric_tons": hourly["grid_co2e_metric_tons"].sum(),
            "site_water_consumption_m3": hourly["site_water_consumption_m3"].sum(),
            "site_water_withdrawal_m3": hourly["site_water_withdrawal_m3"].sum(),
            "indirect_grid_water_consumption_m3": hourly[
                "indirect_grid_water_consumption_m3"
            ].sum(),
            "total_water_footprint_m3": hourly["total_water_footprint_m3"].sum(),
            "heat_rejected_mwh_thermal": hourly["heat_rejected_mwh_thermal"].sum(),
        }
    )
    return hourly, summary


def objective_totals(summary: pd.Series) -> Dict[str, float]:
    """Extract the three competing objective totals from an evaluation summary."""
    return {
        "cost": float(summary["electricity_cost_usd"]),
        "emissions": float(summary["grid_co2e_metric_tons"]),
        "water": float(summary["total_water_footprint_m3"]),
    }


def normalized_tradeoff_table(summary_table: pd.DataFrame) -> pd.DataFrame:
    """Rescale each objective to [0, 1] across scenarios (0 = best, 1 = worst).

    This makes the tradeoff explicit: a focus scenario should score ~0 on the
    objective it targets and higher on the objectives it sacrifices.
    """
    columns = {
        "cost": "electricity_cost_usd",
        "emissions": "grid_co2e_metric_tons",
        "water": "total_water_footprint_m3",
    }
    table = summary_table[["scenario"]].copy()
    for name, column in columns.items():
        values = summary_table[column].to_numpy(dtype=float)
        span = values.max() - values.min()
        table[f"{name}_normalized"] = (
            0.0 if span == 0 else (values - values.min()) / span
        )
    return table


# ============================================================================
# 6. Validation
# ============================================================================


def validate_solution(
    arrivals: pd.DataFrame,
    service: pd.DataFrame,
    queue: pd.DataFrame,
    config: SimulationConfig,
    tolerance: float = 1e-6,
) -> None:
    """Fail loudly if capacity, queue balance, or deadlines are violated."""

    class_names = list(config.deadline_map)

    processed_each_hour = service[class_names].sum(axis=1).to_numpy()
    if np.any(processed_each_hour > config.flexible_it_capacity_mwh_per_step + tolerance):
        raise AssertionError("Flexible IT capacity is violated.")

    if np.any(queue[class_names].to_numpy() < -tolerance):
        raise AssertionError("A queue became negative.")

    # Recompute the queue balance q[c,t] = q[c,t-1] + a[c,t] - s[c,t].
    for class_name in class_names:
        a = arrivals[class_name].to_numpy()
        s = service[class_name].to_numpy()
        q = queue[class_name].to_numpy()
        previous = np.concatenate(([0.0], q[:-1]))
        if np.any(np.abs(q - (previous + a - s)) > 1e-5):
            raise AssertionError(f"Queue balance violated for {class_name}.")

    for class_name, maximum_delay in config.deadline_map.items():
        cumulative_arrivals = np.cumsum(arrivals[class_name].to_numpy())
        cumulative_service = np.cumsum(service[class_name].to_numpy())

        for time_index in range(maximum_delay, config.total_hours):
            due_arrival_time = time_index - maximum_delay
            if (
                cumulative_service[time_index] + tolerance
                < cumulative_arrivals[due_arrival_time]
            ):
                raise AssertionError(
                    f"Deadline violation for {class_name} at time {time_index}."
                )

        if abs(queue[class_name].iloc[-1]) > tolerance:
            raise AssertionError(f"Terminal queue for {class_name} is not zero.")


# ============================================================================
# 7. Experiments: focus scenarios and pairwise Pareto sweeps
# ============================================================================


def focus_scenarios(config: SimulationConfig) -> Dict[str, Tuple[float, float, float]]:
    """Named weight vectors that each emphasize one objective (plus balanced)."""
    return {
        "cost_focus": (1.0, 0.0, 0.0),
        "emissions_focus": (0.0, 1.0, 0.0),
        "water_focus": (0.0, 0.0, 1.0),
        "balanced": config.default_weights,
    }


def run_focus_scenarios(
    problem: SchedulingProblem,
    marginals: Dict[str, np.ndarray],
    arrivals: pd.DataFrame,
    profiles: pd.DataFrame,
    config: SimulationConfig,
) -> Tuple[Dict[str, pd.DataFrame], pd.DataFrame, Dict[str, Tuple[pd.DataFrame, pd.DataFrame]]]:
    """Solve ASAP plus the named focus scenarios and evaluate each."""

    hourly_by_scenario: Dict[str, pd.DataFrame] = {}
    schedules: Dict[str, Tuple[pd.DataFrame, pd.DataFrame]] = {}
    summaries = []

    # ASAP reference.
    service, queue = solve_schedule(problem, build_asap_objective(problem), "asap")
    validate_solution(arrivals, service, queue, config)
    hourly, summary = evaluate_schedule("asap", arrivals, service, queue, profiles, config)
    summary["weights"] = "-"
    hourly_by_scenario["asap"] = hourly
    schedules["asap"] = (service, queue)
    summaries.append(summary)

    for name, weights in focus_scenarios(config).items():
        objective = build_objective(problem, marginals, weights, config)
        service, queue = solve_schedule(problem, objective, name)
        validate_solution(arrivals, service, queue, config)
        hourly, summary = evaluate_schedule(name, arrivals, service, queue, profiles, config)
        summary["weights"] = str(tuple(round(w, 3) for w in weights))
        hourly_by_scenario[name] = hourly
        schedules[name] = (service, queue)
        summaries.append(summary)

    summary_table = pd.DataFrame(summaries)
    return hourly_by_scenario, summary_table, schedules


def run_pareto_sweep(
    problem: SchedulingProblem,
    marginals: Dict[str, np.ndarray],
    arrivals: pd.DataFrame,
    profiles: pd.DataFrame,
    config: SimulationConfig,
) -> pd.DataFrame:
    """Sweep the three pairwise weight tradeoffs and record the objective totals.

    For pair (A, B) we put weight w on A and (1 - w) on B, holding the third
    objective at zero, and sweep w from 0 to 1. Evaluating the true (physical)
    totals at each solution traces the pairwise Pareto frontier.
    """

    weight_grid = np.linspace(0.0, 1.0, config.pareto_grid_points)
    pairs = [("cost", "emissions"), ("cost", "water"), ("emissions", "water")]

    records = []
    for objective_a, objective_b in pairs:
        for w in weight_grid:
            weights_map = {name: 0.0 for name in OBJECTIVE_NAMES}
            weights_map[objective_a] = float(w)
            weights_map[objective_b] = float(1.0 - w)
            weights = tuple(weights_map[name] for name in OBJECTIVE_NAMES)

            objective = build_objective(problem, marginals, weights, config)
            service, queue = solve_schedule(problem, objective, f"{objective_a}-{objective_b}")
            _, summary = evaluate_schedule(
                f"{objective_a}_vs_{objective_b}", arrivals, service, queue, profiles, config
            )
            totals = objective_totals(summary)
            records.append(
                {
                    "pair": f"{objective_a}_vs_{objective_b}",
                    "objective_a": objective_a,
                    "objective_b": objective_b,
                    "weight_on_a": float(w),
                    "total_cost_usd": totals["cost"],
                    "total_emissions_tco2e": totals["emissions"],
                    "total_water_m3": totals["water"],
                    "average_delay_hours": float(summary["average_delay_hours"]),
                }
            )

    return pd.DataFrame(records)


# ============================================================================
# 8. Plots and output files
# ============================================================================


PARETO_TOTAL_COLUMN = {
    "cost": "total_cost_usd",
    "emissions": "total_emissions_tco2e",
    "water": "total_water_m3",
}


def save_signal_plots(profiles: pd.DataFrame, output_directory: Path) -> None:
    """Plot the full time series and the average diurnal shape of each signal."""

    signals = [
        ("grid_price_per_mwh", "Grid price ($/MWh)"),
        ("grid_emissions_kg_per_mwh", "Grid emissions (kg CO2e/MWh)"),
        ("grid_water_m3_per_mwh", "Grid water (m3/MWh)"),
    ]

    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
    for ax, (column, label) in zip(axes, signals):
        ax.plot(profiles["time"], profiles[column])
        ax.set_ylabel(label)
    axes[-1].set_xlabel("Hour")
    axes[0].set_title("Synthetic hourly operating conditions (source-calibrated means)")
    fig.tight_layout()
    fig.savefig(output_directory / "01_operating_conditions.png", dpi=180)
    plt.close(fig)

    # Average diurnal profile makes the DISTINCT phases obvious.
    diurnal = profiles.groupby("hour_of_day").mean(numeric_only=True)
    fig, ax = plt.subplots(figsize=(10, 5))
    for column, label in signals:
        normalized = diurnal[column] / diurnal[column].mean()
        ax.plot(diurnal.index, normalized, marker="o", label=label)
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Intensity relative to daily mean")
    ax.set_title("Average diurnal shape of each signal (distinct phases drive tradeoffs)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_directory / "02_diurnal_signals.png", dpi=180)
    plt.close(fig)


def save_schedule_plots(
    arrivals: pd.DataFrame,
    hourly_by_scenario: Dict[str, pd.DataFrame],
    output_directory: Path,
    config: SimulationConfig,
) -> None:
    """Show how processing and the queue shift under different focuses."""

    focus = ["cost_focus", "emissions_focus", "water_focus"]

    # Average diurnal processing profile: shows WHEN each focus runs work.
    # Restricted to the arrival week so the zero-arrival clearing tail does not
    # distort the by-hour averages.
    fig, ax = plt.subplots(figsize=(11, 5))
    arriving = arrivals.iloc[: config.arrival_hours].copy()
    arriving["hour_of_day"] = arriving["time"] % 24
    mean_arrival = (
        arriving.groupby("hour_of_day")[list(config.deadline_map)].sum().sum(axis=1)
        / config.number_of_days
    )
    ax.plot(mean_arrival.index, mean_arrival.values, color="black", linewidth=1.5,
            alpha=0.6, label="Arriving flexible work")
    for name in focus:
        week = hourly_by_scenario[name].iloc[: config.arrival_hours]
        diurnal = week.groupby("hour_of_day")["processed_flexible_it_mwh"].mean()
        ax.plot(diurnal.index, diurnal.values, marker="o", label=f"Processed: {name}")
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Average MWh_IT per hour")
    ax.set_title("When each focus processes work (average diurnal profile)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_directory / "03_workload_by_focus.png", dpi=180)
    plt.close(fig)

    # Queue per hour.
    fig, ax = plt.subplots(figsize=(12, 4.5))
    for name in ["asap"] + focus:
        ax.plot(
            hourly_by_scenario[name]["time"],
            hourly_by_scenario[name]["queued_flexible_it_mwh"],
            label=name,
        )
    ax.set_xlabel("Hour")
    ax.set_ylabel("Queued flexible work (MWh_IT)")
    ax.set_title("Flexible-work queue by scheduling focus")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_directory / "04_queue_by_focus.png", dpi=180)
    plt.close(fig)


def save_pareto_plots(
    pareto: pd.DataFrame,
    summary_table: pd.DataFrame,
    output_directory: Path,
) -> None:
    """Plot the three pairwise Pareto frontiers."""

    pairs = [("cost", "emissions"), ("cost", "water"), ("emissions", "water")]

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    for ax, (objective_a, objective_b) in zip(axes, pairs):
        pair_key = f"{objective_a}_vs_{objective_b}"
        subset = pareto[pareto["pair"] == pair_key].sort_values(
            PARETO_TOTAL_COLUMN[objective_a]
        )

        x = subset[PARETO_TOTAL_COLUMN[objective_a]]
        y = subset[PARETO_TOTAL_COLUMN[objective_b]]
        scatter = ax.scatter(x, y, c=subset["weight_on_a"], cmap="viridis", zorder=3)
        ax.plot(x, y, color="grey", alpha=0.5, zorder=2)

        # Overlay the named focus scenarios for reference.
        for scenario, marker in [("cost_focus", "s"), ("emissions_focus", "^"), ("water_focus", "D")]:
            row = summary_table[summary_table["scenario"] == scenario].iloc[0]
            totals = objective_totals(row)
            ax.scatter(
                totals[objective_a],
                totals[objective_b],
                marker=marker,
                s=90,
                edgecolor="black",
                facecolor="none",
                linewidths=1.5,
                zorder=4,
                label=scenario,
            )

        ax.set_xlabel(f"Total {OBJECTIVE_LABELS[objective_a]}")
        ax.set_ylabel(f"Total {OBJECTIVE_LABELS[objective_b]}")
        ax.set_title(f"{objective_a.title()} vs {objective_b.title()} frontier")
        ax.legend(fontsize=8)
        fig.colorbar(scatter, ax=ax, label=f"weight on {objective_a}")

    fig.suptitle("Pairwise Pareto frontiers (color = weight on the x-axis objective)")
    fig.tight_layout()
    fig.savefig(output_directory / "05_pareto_frontiers.png", dpi=180)
    plt.close(fig)


def save_cost_plot(
    hourly_by_scenario: Dict[str, pd.DataFrame],
    output_directory: Path,
) -> None:
    """Cumulative electricity-cost proxy by focus."""
    fig, ax = plt.subplots(figsize=(12, 4.5))
    for name in ["asap", "cost_focus", "emissions_focus", "water_focus"]:
        hourly = hourly_by_scenario[name]
        ax.plot(hourly["time"], hourly["electricity_cost_usd"].cumsum(), label=name)
    ax.set_xlabel("Hour")
    ax.set_ylabel("Cumulative electricity cost ($)")
    ax.set_title("Cumulative wholesale electricity-cost proxy by focus")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_directory / "06_cumulative_electricity_cost.png", dpi=180)
    plt.close(fig)


# ============================================================================
# 9. Main simulation
# ============================================================================


def run_simulation(config: SimulationConfig) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Run focus scenarios and the Pareto sweep, then save all outputs."""

    output_directory = Path(config.output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(config.seed)

    profiles = generate_exogenous_profiles(config, rng)
    jobs, arrivals, lambda_t = generate_job_arrivals(config, rng)

    jobs.to_csv(output_directory / "jobs.csv", index=False)
    arrivals.to_csv(output_directory / "arrivals_by_deadline_class.csv", index=False)
    profiles.to_csv(output_directory / "exogenous_profiles.csv", index=False)
    pd.DataFrame(
        {"time": np.arange(config.arrival_hours), "arrival_rate_jobs_per_hour": lambda_t}
    ).to_csv(output_directory / "arrival_rate.csv", index=False)

    # Build the objective-independent LP once, then reuse it everywhere.
    problem = build_scheduling_problem(arrivals, config)
    marginals = marginal_impacts(profiles, config)

    hourly_by_scenario, summary_table, schedules = run_focus_scenarios(
        problem, marginals, arrivals, profiles, config
    )
    pareto = run_pareto_sweep(problem, marginals, arrivals, profiles, config)

    for name, (service, queue) in schedules.items():
        service.to_csv(output_directory / f"service_{name}.csv", index=False)
        queue.to_csv(output_directory / f"queue_{name}.csv", index=False)

    hourly_all = pd.concat(hourly_by_scenario.values(), ignore_index=True)
    hourly_all.to_csv(output_directory / "hourly_results_all_scenarios.csv", index=False)
    summary_table.to_csv(output_directory / "summary_comparison.csv", index=False)
    pareto.to_csv(output_directory / "pareto_sweep.csv", index=False)
    normalized_tradeoff_table(summary_table).to_csv(
        output_directory / "tradeoff_normalized.csv", index=False
    )

    save_signal_plots(profiles, output_directory)
    save_schedule_plots(arrivals, hourly_by_scenario, output_directory, config)
    save_pareto_plots(pareto, summary_table, output_directory)
    save_cost_plot(hourly_by_scenario, output_directory)

    return summary_table, pareto


if __name__ == "__main__":
    configuration = SimulationConfig()
    summary, pareto = run_simulation(configuration)

    summary_columns = [
        "scenario",
        "weights",
        "average_delay_hours",
        "electricity_cost_usd",
        "grid_co2e_metric_tons",
        "total_water_footprint_m3",
    ]

    print("\nSimulation completed.\n")
    print("Focus scenarios (relative to ASAP):")
    print(summary[summary_columns].round(3).to_string(index=False))

    print("\nNormalized tradeoff (0 = best, 1 = worst across scenarios):")
    print(normalized_tradeoff_table(summary).round(3).to_string(index=False))

    # Compact tradeoff table: best and worst of each objective across the sweep.
    print("\nPareto sweep ranges by pair:")
    for pair, group in pareto.groupby("pair"):
        print(
            f"  {pair}: "
            f"cost [{group['total_cost_usd'].min():.0f}, {group['total_cost_usd'].max():.0f}] $, "
            f"CO2 [{group['total_emissions_tco2e'].min():.1f}, {group['total_emissions_tco2e'].max():.1f}] t, "
            f"water [{group['total_water_m3'].min():.0f}, {group['total_water_m3'].max():.0f}] m3"
        )

    print(f"\nOutputs saved in: {Path(configuration.output_directory).resolve()}")
