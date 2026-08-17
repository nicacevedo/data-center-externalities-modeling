"""
Second prototype: normalized multi-objective tradeoffs for temporal
allocation of deferrable data-center jobs.

This script uses exactly the same simulated jobs, operating profiles,
physical accounting, capacity constraints, and deadline constraints as
`data_center_job_allocation_prototype.py`. It adds a transparent
multi-objective analysis.

Metrics minimized
-----------------
1. Electricity cost                 [USD]
2. Operational grid CO2e            [metric tons]
3. Total operational water footprint [m^3]
4. Delay burden                     [MWh_IT-hour]

Normalization
-------------
For each metric k, the code solves two linear programs over the same
feasible scheduling set:

    F_k^min = min F_k(x)
    F_k^max = max F_k(x)

It then defines the exact feasible-range normalization

    Fhat_k(x) = (F_k(x) - F_k^min) / (F_k^max - F_k^min).

For each pair (i, j), alpha is swept from 0 to 1 and the model solves

    min alpha * Fhat_i(x) + (1 - alpha) * Fhat_j(x).

Thus, all weights are dimensionless and directly comparable. Metrics
with zero feasible range are detected automatically. In the current
baseline, water is constant across schedules because PUE, site WUE, and
grid-water intensity are time-invariant and all work must be completed.
Consequently, a water weight cannot change the schedule; the output flags
this rather than manufacturing a false water tradeoff.

The script also runs an optional four-metric simplex sweep using weights
that sum to one.

Run
---
Place this file beside `data_center_job_allocation_prototype.py`, then run:

    python data_center_pairwise_tradeoffs.py

Outputs are written to ./data_center_tradeoff_outputs/.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy.sparse import csr_matrix, lil_matrix, vstack

from data_center_job_allocation_prototype import (
    SimulationConfig,
    evaluate_schedule,
    generate_exogenous_profiles,
    generate_job_arrivals,
    validate_solution,
)


# ============================================================================
# 1. Tradeoff-analysis parameters
# ============================================================================


@dataclass(frozen=True)
class TradeoffConfig:
    """Settings used only by the multi-objective analysis."""

    output_directory: str = "data_center_tradeoff_outputs"

    # Pairwise alpha grid: 0.00, 0.05, ..., 1.00.
    pairwise_weight_step: float = 0.05

    # Optional all-metric simplex grid: weights in {0, .25, .50, .75, 1}
    # constrained to sum to one.
    run_all_metric_simplex: bool = True
    simplex_weight_step: float = 0.25

    # A metric is treated as schedule-invariant when its feasible range is
    # negligible relative to its magnitude.
    inactive_metric_relative_tolerance: float = 1e-8

    # Lexicographic tie-breaking tolerance for the primary LP objective.
    lexicographic_relative_tolerance: float = 1e-8


METRIC_ORDER: Tuple[str, ...] = (
    "electricity_cost_usd",
    "grid_co2e_metric_tons",
    "total_water_footprint_m3",
    "delay_mwh_hours",
)

METRIC_LABELS: Dict[str, str] = {
    "electricity_cost_usd": "Electricity cost",
    "grid_co2e_metric_tons": "Operational grid CO2e",
    "total_water_footprint_m3": "Operational water footprint",
    "delay_mwh_hours": "Delay burden",
}

METRIC_UNITS: Dict[str, str] = {
    "electricity_cost_usd": "USD",
    "grid_co2e_metric_tons": "metric tons CO2e",
    "total_water_footprint_m3": "m^3",
    "delay_mwh_hours": "MWh_IT-hour",
}


# ============================================================================
# 2. Reusable scheduling feasible set
# ============================================================================


class TemporalSchedulingLP:
    """Build the scheduling constraints once and solve many LP objectives.

    Variable ordering
    -----------------
    x = [all service[c,t] variables | all queue[c,t] variables]

    The feasible set is exactly the same as in the first prototype:

        q[c,t] = q[c,t-1] + a[c,t] - s[c,t]
        sum_c s[c,t] <= flexible IT capacity
        cumulative service satisfies every deadline
        terminal queue equals zero
        s[c,t], q[c,t] >= 0
    """

    def __init__(self, arrivals: pd.DataFrame, config: SimulationConfig) -> None:
        self.config = config
        self.class_names = list(config.deadline_map)
        self.number_of_classes = len(self.class_names)
        self.total_hours = config.total_hours
        self.arrival_matrix = arrivals[self.class_names].to_numpy(dtype=float).T

        self.number_of_service_variables = (
            self.number_of_classes * self.total_hours
        )
        self.number_of_queue_variables = (
            self.number_of_classes * self.total_hours
        )
        self.number_of_variables = (
            self.number_of_service_variables + self.number_of_queue_variables
        )

        self.A_eq, self.b_eq = self._build_equality_constraints()
        self.A_ub, self.b_ub = self._build_inequality_constraints()
        self.bounds = [(0.0, None)] * self.number_of_variables

    def service_index(self, class_index: int, time_index: int) -> int:
        return class_index * self.total_hours + time_index

    def queue_index(self, class_index: int, time_index: int) -> int:
        return (
            self.number_of_service_variables
            + class_index * self.total_hours
            + time_index
        )

    def _build_equality_constraints(self) -> Tuple[csr_matrix, np.ndarray]:
        number_of_equalities = (
            self.number_of_classes * self.total_hours
            + self.number_of_classes
        )
        matrix = lil_matrix((number_of_equalities, self.number_of_variables))
        rhs = np.zeros(number_of_equalities)

        row = 0
        for class_index in range(self.number_of_classes):
            for time_index in range(self.total_hours):
                # q[c,t] + s[c,t] - q[c,t-1] = a[c,t]
                matrix[row, self.queue_index(class_index, time_index)] = 1.0
                matrix[row, self.service_index(class_index, time_index)] = 1.0

                if time_index > 0:
                    matrix[
                        row,
                        self.queue_index(class_index, time_index - 1),
                    ] = -1.0

                rhs[row] = self.arrival_matrix[class_index, time_index]
                row += 1

            # Empty queue at the end of the clearing tail.
            matrix[
                row,
                self.queue_index(class_index, self.total_hours - 1),
            ] = 1.0
            rhs[row] = 0.0
            row += 1

        return matrix.tocsr(), rhs

    def _build_inequality_constraints(self) -> Tuple[csr_matrix, np.ndarray]:
        deadline_constraint_count = sum(
            self.total_hours - delay
            for delay in self.config.deadline_map.values()
        )
        number_of_inequalities = self.total_hours + deadline_constraint_count

        matrix = lil_matrix((number_of_inequalities, self.number_of_variables))
        rhs = np.zeros(number_of_inequalities)

        row = 0

        # Hourly flexible IT capacity.
        for time_index in range(self.total_hours):
            for class_index in range(self.number_of_classes):
                matrix[
                    row,
                    self.service_index(class_index, time_index),
                ] = 1.0
            rhs[row] = self.config.flexible_it_capacity_mwh_per_step
            row += 1

        # Deadline completion constraints.
        for class_index, class_name in enumerate(self.class_names):
            maximum_delay = self.config.deadline_map[class_name]
            cumulative_arrivals = np.cumsum(self.arrival_matrix[class_index])

            for time_index in range(maximum_delay, self.total_hours):
                # -sum_{tau <= t} s[c,tau] <= -arrivals due by t
                for service_time in range(time_index + 1):
                    matrix[
                        row,
                        self.service_index(class_index, service_time),
                    ] = -1.0

                due_arrival_time = time_index - maximum_delay
                rhs[row] = -cumulative_arrivals[due_arrival_time]
                row += 1

        return matrix.tocsr(), rhs

    def solve_lexicographic(
        self,
        primary_objective: np.ndarray,
        secondary_objective: np.ndarray,
        relative_tolerance: float,
    ) -> Tuple[np.ndarray, float]:
        """Minimize a primary objective, then a secondary objective.

        The second solve is constrained to remain within a very small tolerance
        of the exact primary optimum. This removes arbitrary solver choices when
        a metric has many optimal schedules, without mixing objectives through
        an ad hoc epsilon coefficient.
        """

        primary_objective = np.asarray(primary_objective, dtype=float)
        secondary_objective = np.asarray(secondary_objective, dtype=float)

        if primary_objective.shape != (self.number_of_variables,):
            raise ValueError("Primary objective has the wrong length.")
        if secondary_objective.shape != (self.number_of_variables,):
            raise ValueError("Secondary objective has the wrong length.")

        first = linprog(
            c=primary_objective,
            A_ub=self.A_ub,
            b_ub=self.b_ub,
            A_eq=self.A_eq,
            b_eq=self.b_eq,
            bounds=self.bounds,
            method="highs",
        )
        if not first.success:
            raise RuntimeError(f"Primary scheduling LP failed: {first.message}")

        primary_optimum = float(first.fun)
        absolute_tolerance = relative_tolerance * max(
            1.0,
            abs(primary_optimum),
        )

        # Preserve the primary optimum, then minimize the secondary metric.
        added_row = csr_matrix(primary_objective.reshape(1, -1))
        augmented_A_ub = vstack([self.A_ub, added_row], format="csr")
        augmented_b_ub = np.append(
            self.b_ub,
            primary_optimum + absolute_tolerance,
        )

        second = linprog(
            c=secondary_objective,
            A_ub=augmented_A_ub,
            b_ub=augmented_b_ub,
            A_eq=self.A_eq,
            b_eq=self.b_eq,
            bounds=self.bounds,
            method="highs",
        )
        if not second.success:
            # The first-stage solution is still a valid exact optimum.
            return first.x, primary_optimum

        return second.x, primary_optimum

    def decode_solution(
        self,
        solution: np.ndarray,
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        service = pd.DataFrame(
            index=np.arange(self.total_hours),
            columns=self.class_names,
            dtype=float,
        )
        queue = service.copy()

        for class_index, class_name in enumerate(self.class_names):
            for time_index in range(self.total_hours):
                service.loc[time_index, class_name] = solution[
                    self.service_index(class_index, time_index)
                ]
                queue.loc[time_index, class_name] = solution[
                    self.queue_index(class_index, time_index)
                ]

        service.index.name = "time"
        queue.index.name = "time"
        return service.reset_index(), queue.reset_index()


# ============================================================================
# 3. Linear definitions of the four objective metrics
# ============================================================================


def build_metric_expressions(
    model: TemporalSchedulingLP,
    profiles: pd.DataFrame,
    config: SimulationConfig,
) -> Tuple[Dict[str, np.ndarray], Dict[str, float]]:
    """Return F_k(x) = constant_k + coefficient_k^T x for every metric."""

    pue = profiles["pue"].to_numpy(dtype=float)
    price = profiles["grid_price_per_mwh"].to_numpy(dtype=float)
    emissions = profiles["grid_emissions_kg_per_mwh"].to_numpy(dtype=float)
    site_wue = profiles["site_wue_m3_per_mwh_it"].to_numpy(dtype=float)
    grid_water = profiles["grid_water_m3_per_mwh"].to_numpy(dtype=float)

    # Marginal effect of one extra MWh_IT processed at hour t.
    marginal_by_metric: Dict[str, np.ndarray] = {
        "electricity_cost_usd": pue * price,
        "grid_co2e_metric_tons": pue * emissions / 1000.0,
        "total_water_footprint_m3": site_wue + pue * grid_water,
    }

    vectors = {
        metric: np.zeros(model.number_of_variables, dtype=float)
        for metric in METRIC_ORDER
    }

    # Processing metrics have the same hourly coefficient for every class.
    for metric, marginal_values in marginal_by_metric.items():
        for class_index in range(model.number_of_classes):
            for time_index in range(model.total_hours):
                vectors[metric][
                    model.service_index(class_index, time_index)
                ] = marginal_values[time_index]

    # Delay burden is the discrete area under every class queue.
    # Multiplication by Delta t preserves MWh_IT-hour units if the time step
    # later changes from one hour.
    for class_index in range(model.number_of_classes):
        for time_index in range(model.total_hours):
            vectors["delay_mwh_hours"][
                model.queue_index(class_index, time_index)
            ] = config.time_step_hours

    # Fixed IT electricity contributes to physical totals but does not depend
    # on scheduling. It is included in reported metric values.
    fixed_it_energy_per_step = (
        config.fixed_it_power_mw * config.time_step_hours
    )
    constants = {
        metric: float(np.sum(marginal * fixed_it_energy_per_step))
        for metric, marginal in marginal_by_metric.items()
    }
    constants["delay_mwh_hours"] = 0.0

    return vectors, constants


def metric_values_from_solution(
    solution: np.ndarray,
    metric_vectors: Mapping[str, np.ndarray],
    metric_constants: Mapping[str, float],
) -> Dict[str, float]:
    return {
        metric: float(metric_constants[metric] + vector @ solution)
        for metric, vector in metric_vectors.items()
    }


# ============================================================================
# 4. Exact feasible-range normalization
# ============================================================================


def compute_exact_metric_bounds(
    model: TemporalSchedulingLP,
    metric_vectors: Mapping[str, np.ndarray],
    metric_constants: Mapping[str, float],
    tradeoff_config: TradeoffConfig,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Compute the exact feasible minimum and maximum of every metric."""

    delay_vector = metric_vectors["delay_mwh_hours"]
    bound_records: List[Dict[str, object]] = []
    extreme_records: List[Dict[str, object]] = []

    for metric in METRIC_ORDER:
        vector = metric_vectors[metric]
        constant = metric_constants[metric]

        # Minimum F_k.
        minimum_solution, minimum_variable_objective = model.solve_lexicographic(
            primary_objective=vector,
            secondary_objective=delay_vector,
            relative_tolerance=tradeoff_config.lexicographic_relative_tolerance,
        )
        exact_minimum = constant + minimum_variable_objective
        minimum_values = metric_values_from_solution(
            minimum_solution,
            metric_vectors,
            metric_constants,
        )

        # Maximum F_k is obtained by minimizing -F_k.
        maximum_solution, negative_maximum_variable_objective = (
            model.solve_lexicographic(
                primary_objective=-vector,
                secondary_objective=delay_vector,
                relative_tolerance=(
                    tradeoff_config.lexicographic_relative_tolerance
                ),
            )
        )
        exact_maximum = constant - negative_maximum_variable_objective
        maximum_values = metric_values_from_solution(
            maximum_solution,
            metric_vectors,
            metric_constants,
        )

        feasible_range = max(0.0, exact_maximum - exact_minimum)
        scale = max(1.0, abs(exact_minimum), abs(exact_maximum))
        active = (
            feasible_range
            > tradeoff_config.inactive_metric_relative_tolerance * scale
        )

        bound_records.append(
            {
                "metric": metric,
                "label": METRIC_LABELS[metric],
                "unit": METRIC_UNITS[metric],
                "feasible_minimum": exact_minimum,
                "feasible_maximum": exact_maximum,
                "feasible_range": feasible_range,
                "schedule_sensitive": active,
                "normalization_formula": (
                    "(value - feasible_minimum) / feasible_range"
                    if active
                    else "0 (metric is constant across feasible schedules)"
                ),
            }
        )

        for direction, values in (
            ("minimum", minimum_values),
            ("maximum", maximum_values),
        ):
            record: Dict[str, object] = {
                "optimized_metric": metric,
                "direction": direction,
            }
            record.update(values)
            extreme_records.append(record)

    return pd.DataFrame(bound_records), pd.DataFrame(extreme_records)


def build_normalized_weighted_objective(
    weights: Mapping[str, float],
    metric_vectors: Mapping[str, np.ndarray],
    bounds: pd.DataFrame,
) -> np.ndarray:
    """Build sum_k w_k * Fhat_k(x); constant offsets can be omitted."""

    number_of_variables = len(next(iter(metric_vectors.values())))
    objective = np.zeros(number_of_variables, dtype=float)
    bounds_by_metric = bounds.set_index("metric")

    for metric in METRIC_ORDER:
        weight = float(weights.get(metric, 0.0))
        if weight < 0.0 or weight > 1.0:
            raise ValueError(f"Weight for {metric} must lie in [0, 1].")

        feasible_range = float(bounds_by_metric.loc[metric, "feasible_range"])
        active = bool(bounds_by_metric.loc[metric, "schedule_sensitive"])

        if active and weight > 0.0:
            objective += weight * metric_vectors[metric] / feasible_range

    return objective


def normalized_metric_values(
    raw_values: Mapping[str, float],
    bounds: pd.DataFrame,
) -> Dict[str, float]:
    bounds_by_metric = bounds.set_index("metric")
    normalized: Dict[str, float] = {}

    for metric in METRIC_ORDER:
        minimum = float(bounds_by_metric.loc[metric, "feasible_minimum"])
        feasible_range = float(bounds_by_metric.loc[metric, "feasible_range"])
        active = bool(bounds_by_metric.loc[metric, "schedule_sensitive"])

        if not active:
            normalized[metric] = 0.0
        else:
            value = (float(raw_values[metric]) - minimum) / feasible_range
            # Remove only numerical noise beyond the mathematically valid range.
            normalized[metric] = float(np.clip(value, 0.0, 1.0))

    return normalized


# ============================================================================
# 5. Pairwise and all-metric weight sweeps
# ============================================================================


def weight_grid(step: float) -> np.ndarray:
    if step <= 0.0 or step > 1.0:
        raise ValueError("Weight step must lie in (0, 1].")

    number_of_intervals = int(round(1.0 / step))
    if not np.isclose(number_of_intervals * step, 1.0):
        raise ValueError("Weight step must divide 1 exactly.")

    return np.linspace(0.0, 1.0, number_of_intervals + 1)


def mark_pairwise_nondominated(
    table: pd.DataFrame,
    metric_1: str,
    metric_2: str,
    relative_tolerance: float = 1e-8,
) -> pd.Series:
    """Mark points not dominated on the two raw minimization metrics."""

    values = table[[metric_1, metric_2]].to_numpy(dtype=float)
    nondominated = np.ones(len(table), dtype=bool)

    scales = np.maximum(1.0, np.max(np.abs(values), axis=0))
    tolerance = relative_tolerance * scales

    for i in range(len(values)):
        no_worse = np.all(values <= values[i] + tolerance, axis=1)
        strictly_better = np.any(values < values[i] - tolerance, axis=1)
        dominated_by_another = np.any(no_worse & strictly_better)
        nondominated[i] = not dominated_by_another

    return pd.Series(nondominated, index=table.index)


def solve_weight_scenario(
    scenario_id: str,
    weights: Mapping[str, float],
    model: TemporalSchedulingLP,
    metric_vectors: Mapping[str, np.ndarray],
    metric_constants: Mapping[str, float],
    bounds: pd.DataFrame,
    arrivals: pd.DataFrame,
    profiles: pd.DataFrame,
    simulation_config: SimulationConfig,
    tradeoff_config: TradeoffConfig,
) -> Tuple[Dict[str, object], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Solve one normalized weighted objective and return all outputs."""

    objective = build_normalized_weighted_objective(
        weights=weights,
        metric_vectors=metric_vectors,
        bounds=bounds,
    )

    solution, primary_optimum = model.solve_lexicographic(
        primary_objective=objective,
        secondary_objective=metric_vectors["delay_mwh_hours"],
        relative_tolerance=tradeoff_config.lexicographic_relative_tolerance,
    )

    service, queue = model.decode_solution(solution)
    validate_solution(arrivals, service, queue, simulation_config)

    raw_values = metric_values_from_solution(
        solution,
        metric_vectors,
        metric_constants,
    )
    normalized_values = normalized_metric_values(raw_values, bounds)

    hourly, physical_summary = evaluate_schedule(
        policy_name=scenario_id,
        arrivals=arrivals,
        service=service,
        queue=queue,
        profiles=profiles,
        config=simulation_config,
    )

    total_flexible_work = float(
        arrivals[list(simulation_config.deadline_map)].to_numpy().sum()
    )
    average_delay = (
        raw_values["delay_mwh_hours"] / total_flexible_work
        if total_flexible_work > 0.0
        else 0.0
    )

    bounds_by_metric = bounds.set_index("metric")
    active_weight_sum = sum(
        float(weights.get(metric, 0.0))
        for metric in METRIC_ORDER
        if bool(bounds_by_metric.loc[metric, "schedule_sensitive"])
    )

    record: Dict[str, object] = {
        "scenario_id": scenario_id,
        "normalized_solver_objective": primary_optimum,
        "active_weight_sum": active_weight_sum,
        "average_delay_hours": average_delay,
        "peak_queue_mwh": float(
            queue[list(simulation_config.deadline_map)].sum(axis=1).max()
        ),
        "total_dc_grid_energy_mwh": float(
            physical_summary["total_dc_grid_energy_mwh"]
        ),
        "site_water_consumption_m3": float(
            physical_summary["site_water_consumption_m3"]
        ),
        "indirect_grid_water_consumption_m3": float(
            physical_summary["indirect_grid_water_consumption_m3"]
        ),
        "heat_rejected_mwh_thermal": float(
            physical_summary["heat_rejected_mwh_thermal"]
        ),
    }

    for metric in METRIC_ORDER:
        record[f"weight_{metric}"] = float(weights.get(metric, 0.0))
        record[metric] = raw_values[metric]
        record[f"normalized_{metric}"] = normalized_values[metric]

    hourly.insert(0, "scenario_id", scenario_id)
    service.insert(0, "scenario_id", scenario_id)
    queue.insert(0, "scenario_id", scenario_id)

    return record, hourly, service, queue


def run_pairwise_tradeoffs(
    model: TemporalSchedulingLP,
    metric_vectors: Mapping[str, np.ndarray],
    metric_constants: Mapping[str, float],
    bounds: pd.DataFrame,
    arrivals: pd.DataFrame,
    profiles: pd.DataFrame,
    simulation_config: SimulationConfig,
    tradeoff_config: TradeoffConfig,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summary_records: List[Dict[str, object]] = []
    hourly_tables: List[pd.DataFrame] = []
    service_tables: List[pd.DataFrame] = []
    queue_tables: List[pd.DataFrame] = []

    alphas = weight_grid(tradeoff_config.pairwise_weight_step)

    for metric_1, metric_2 in combinations(METRIC_ORDER, 2):
        pair_name = f"{metric_1}__vs__{metric_2}"

        for alpha in alphas:
            weights = {metric: 0.0 for metric in METRIC_ORDER}
            weights[metric_1] = float(alpha)
            weights[metric_2] = float(1.0 - alpha)

            scenario_id = f"{pair_name}__alpha_{alpha:.2f}"
            record, hourly, service, queue = solve_weight_scenario(
                scenario_id=scenario_id,
                weights=weights,
                model=model,
                metric_vectors=metric_vectors,
                metric_constants=metric_constants,
                bounds=bounds,
                arrivals=arrivals,
                profiles=profiles,
                simulation_config=simulation_config,
                tradeoff_config=tradeoff_config,
            )

            record["pair_name"] = pair_name
            record["metric_1"] = metric_1
            record["metric_2"] = metric_2
            record["alpha_weight_on_metric_1"] = float(alpha)
            record["one_minus_alpha_weight_on_metric_2"] = float(1.0 - alpha)

            summary_records.append(record)
            hourly_tables.append(hourly)
            service_tables.append(service)
            queue_tables.append(queue)

    summary = pd.DataFrame(summary_records)

    # Nondominance is evaluated separately inside each pair.
    summary["pairwise_nondominated"] = False
    for pair_name, group in summary.groupby("pair_name", sort=False):
        metric_1 = str(group["metric_1"].iloc[0])
        metric_2 = str(group["metric_2"].iloc[0])
        summary.loc[group.index, "pairwise_nondominated"] = (
            mark_pairwise_nondominated(group, metric_1, metric_2).to_numpy()
        )

    return (
        summary,
        pd.concat(hourly_tables, ignore_index=True),
        pd.concat(service_tables, ignore_index=True),
        pd.concat(queue_tables, ignore_index=True),
    )


def integer_compositions(total: int, parts: int) -> Iterable[Tuple[int, ...]]:
    """Yield nonnegative integer tuples of length `parts` summing to `total`."""

    if parts == 1:
        yield (total,)
        return

    for first in range(total + 1):
        for remainder in integer_compositions(total - first, parts - 1):
            yield (first,) + remainder


def run_all_metric_simplex(
    model: TemporalSchedulingLP,
    metric_vectors: Mapping[str, np.ndarray],
    metric_constants: Mapping[str, float],
    bounds: pd.DataFrame,
    arrivals: pd.DataFrame,
    profiles: pd.DataFrame,
    simulation_config: SimulationConfig,
    tradeoff_config: TradeoffConfig,
) -> pd.DataFrame:
    """Run a coarse grid of all four nonnegative weights summing to one."""

    step = tradeoff_config.simplex_weight_step
    number_of_units = int(round(1.0 / step))
    if not np.isclose(number_of_units * step, 1.0):
        raise ValueError("Simplex weight step must divide 1 exactly.")

    records: List[Dict[str, object]] = []

    for scenario_number, units in enumerate(
        integer_compositions(number_of_units, len(METRIC_ORDER))
    ):
        weights = {
            metric: units[index] / number_of_units
            for index, metric in enumerate(METRIC_ORDER)
        }
        scenario_id = f"all_metrics_{scenario_number:03d}"

        record, _, _, _ = solve_weight_scenario(
            scenario_id=scenario_id,
            weights=weights,
            model=model,
            metric_vectors=metric_vectors,
            metric_constants=metric_constants,
            bounds=bounds,
            arrivals=arrivals,
            profiles=profiles,
            simulation_config=simulation_config,
            tradeoff_config=tradeoff_config,
        )
        records.append(record)

    return pd.DataFrame(records)


# ============================================================================
# 6. Tradeoff plots
# ============================================================================


def safe_file_name(metric: str) -> str:
    return metric.replace("_", "-")


def save_pairwise_plots(
    pairwise_summary: pd.DataFrame,
    bounds: pd.DataFrame,
    output_directory: Path,
) -> None:
    bounds_by_metric = bounds.set_index("metric")

    for pair_name, group in pairwise_summary.groupby("pair_name", sort=False):
        metric_1 = str(group["metric_1"].iloc[0])
        metric_2 = str(group["metric_2"].iloc[0])
        group = group.sort_values("alpha_weight_on_metric_1")

        metric_1_active = bool(
            bounds_by_metric.loc[metric_1, "schedule_sensitive"]
        )
        metric_2_active = bool(
            bounds_by_metric.loc[metric_2, "schedule_sensitive"]
        )

        fig, ax = plt.subplots(figsize=(7.5, 5.5))

        if metric_1_active and metric_2_active:
            # Standard Pareto-style view when both metrics can change.
            ax.plot(
                group[metric_1],
                group[metric_2],
                marker="o",
                linewidth=1.2,
            )

            first = group.iloc[0]
            last = group.iloc[-1]
            ax.annotate(
                f"alpha={first['alpha_weight_on_metric_1']:.2f}",
                (first[metric_1], first[metric_2]),
                xytext=(5, 5),
                textcoords="offset points",
            )
            ax.annotate(
                f"alpha={last['alpha_weight_on_metric_1']:.2f}",
                (last[metric_1], last[metric_2]),
                xytext=(5, -15),
                textcoords="offset points",
            )

            ax.set_xlabel(
                f"{METRIC_LABELS[metric_1]} [{METRIC_UNITS[metric_1]}]"
            )
            ax.set_ylabel(
                f"{METRIC_LABELS[metric_2]} [{METRIC_UNITS[metric_2]}]"
            )
        elif metric_1_active or metric_2_active:
            # A raw x-y frontier is meaningless when one axis is constant.
            # Show how the active metric responds to the pairwise weight instead.
            active_metric = metric_1 if metric_1_active else metric_2
            inactive_metric = metric_2 if metric_1_active else metric_1

            ax.plot(
                group["alpha_weight_on_metric_1"],
                group[active_metric],
                marker="o",
                linewidth=1.2,
            )
            ax.set_xlabel(
                f"alpha: weight on {METRIC_LABELS[metric_1]}"
            )
            ax.set_ylabel(
                f"{METRIC_LABELS[active_metric]} "
                f"[{METRIC_UNITS[active_metric]}]"
            )
            ax.ticklabel_format(axis="y", style="plain", useOffset=False)
            ax.text(
                0.02,
                0.98,
                f"{METRIC_LABELS[inactive_metric]} is constant across "
                "all feasible schedules.",
                transform=ax.transAxes,
                va="top",
            )
        else:
            ax.axis("off")
            ax.text(
                0.5,
                0.5,
                "Both metrics are constant across feasible schedules;\n"
                "there is no scheduling tradeoff.",
                ha="center",
                va="center",
                transform=ax.transAxes,
            )

        ax.set_title(
            f"Pairwise normalized-weight tradeoff\n"
            f"alpha on {METRIC_LABELS[metric_1]}, 1-alpha on "
            f"{METRIC_LABELS[metric_2]}"
        )

        fig.tight_layout()
        filename = (
            f"pairwise_{safe_file_name(metric_1)}"
            f"__vs__{safe_file_name(metric_2)}.png"
        )
        fig.savefig(output_directory / filename, dpi=180)
        plt.close(fig)


# ============================================================================
# 7. Main analysis
# ============================================================================


def run_tradeoff_analysis(
    simulation_config: SimulationConfig,
    tradeoff_config: TradeoffConfig,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    output_directory = Path(tradeoff_config.output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)

    # Use the same seed and the same generation order as the first prototype,
    # so jobs and exogenous profiles are exactly reproducible.
    rng = np.random.default_rng(simulation_config.seed)
    profiles = generate_exogenous_profiles(simulation_config, rng)
    jobs, arrivals, lambda_t = generate_job_arrivals(simulation_config, rng)

    profiles.to_csv(output_directory / "exogenous_profiles.csv", index=False)
    jobs.to_csv(output_directory / "jobs.csv", index=False)
    arrivals.to_csv(
        output_directory / "arrivals_by_deadline_class.csv",
        index=False,
    )
    pd.DataFrame(
        {
            "time": np.arange(simulation_config.arrival_hours),
            "arrival_rate_jobs_per_hour": lambda_t,
        }
    ).to_csv(output_directory / "arrival_rate.csv", index=False)

    model = TemporalSchedulingLP(arrivals, simulation_config)
    metric_vectors, metric_constants = build_metric_expressions(
        model=model,
        profiles=profiles,
        config=simulation_config,
    )

    bounds, extreme_solutions = compute_exact_metric_bounds(
        model=model,
        metric_vectors=metric_vectors,
        metric_constants=metric_constants,
        tradeoff_config=tradeoff_config,
    )
    bounds.to_csv(output_directory / "normalization_bounds.csv", index=False)
    extreme_solutions.to_csv(
        output_directory / "single_metric_extreme_solutions.csv",
        index=False,
    )

    pairwise_summary, pairwise_hourly, pairwise_service, pairwise_queue = (
        run_pairwise_tradeoffs(
            model=model,
            metric_vectors=metric_vectors,
            metric_constants=metric_constants,
            bounds=bounds,
            arrivals=arrivals,
            profiles=profiles,
            simulation_config=simulation_config,
            tradeoff_config=tradeoff_config,
        )
    )

    pairwise_summary.to_csv(
        output_directory / "pairwise_tradeoff_summary.csv",
        index=False,
    )
    pairwise_hourly.to_csv(
        output_directory / "pairwise_tradeoff_hourly.csv",
        index=False,
    )
    pairwise_service.to_csv(
        output_directory / "pairwise_service_by_class.csv",
        index=False,
    )
    pairwise_queue.to_csv(
        output_directory / "pairwise_queue_by_class.csv",
        index=False,
    )

    save_pairwise_plots(
        pairwise_summary=pairwise_summary,
        bounds=bounds,
        output_directory=output_directory,
    )

    if tradeoff_config.run_all_metric_simplex:
        simplex_summary = run_all_metric_simplex(
            model=model,
            metric_vectors=metric_vectors,
            metric_constants=metric_constants,
            bounds=bounds,
            arrivals=arrivals,
            profiles=profiles,
            simulation_config=simulation_config,
            tradeoff_config=tradeoff_config,
        )
        simplex_summary.to_csv(
            output_directory / "all_metric_simplex_summary.csv",
            index=False,
        )

    return bounds, pairwise_summary


if __name__ == "__main__":
    simulation_configuration = SimulationConfig()
    tradeoff_configuration = TradeoffConfig()

    metric_bounds, pairwise_results = run_tradeoff_analysis(
        simulation_config=simulation_configuration,
        tradeoff_config=tradeoff_configuration,
    )

    print("\nNormalized tradeoff analysis completed.\n")
    print(
        metric_bounds[
            [
                "label",
                "unit",
                "feasible_minimum",
                "feasible_maximum",
                "feasible_range",
                "schedule_sensitive",
            ]
        ].round(6).to_string(index=False)
    )
    print(
        f"\nPairwise scenarios solved: {len(pairwise_results)}"
        f"\nOutputs saved in: "
        f"{Path(tradeoff_configuration.output_directory).resolve()}"
    )
