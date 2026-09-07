# Scope boundary of the synthetic groundwater identifiability experiment (v1)

`SYNTHETIC_IDENTIFIABILITY_SCOPE = REDUCED_ORDER_HEAD_PUMPING_RECHARGE_CORE_ONLY`

## What this experiment qualifies

This is a **known-truth synthetic identifiability and falsification experiment**. It
qualifies **only the reduced-order head / pumping / recharge response core**: whether a
linear reduced-order groundwater response, and the pumping-intervention responses derived
from it, can be identified from head observations plus imperfect forcing information under
controlled, preregistered observation limitations.

The governing scientific question is:

> What groundwater model complexity can the kinds of observations available to this
> project actually support for counterfactual data-center planning?

A negative result is a successful outcome.

## What this experiment explicitly does NOT establish

This experiment does **not** validate, calibrate, or provide evidence about:

- the proposal's eventual GRACE, data-assimilation, or Bayesian implementation;
- Andhra Pradesh hydrogeology or any Andhra Pradesh physical parameter;
- OCWD physical parameters, aquifer geometry, or fitted coefficients;
- actual groundwater connectivity anywhere in the world;
- actual data-center groundwater impacts;
- actual siting decisions;
- a validated policy model.

No GRACE product, data-assimilation stack, or complex Bayesian inference model is added in
v1. Synthetic success is not empirical validation.

## Model-class boundary

Deliberately **not** implemented, and out of scope:

- graph neural networks or any neural network;
- MODFLOW or any distributed physical groundwater simulator;
- large Bayesian graphical models;
- high-dimensional black-box models.

The goal is **identifiability**, not model sophistication. Every estimator in the ladder is
a transparent linear or bound-constrained linear estimator.

## Relationship to real datasets

No fitted physical coefficient is imported from OCWD, Andhra Pradesh, Prineville, any
data-center facility model, or PSCC. All synthetic truth is generated from the frozen
design in `config/design_v1.yaml`.

Where a real dataset informs anything at all, it may only inform **observation-design
features** such as cadence and missingness structure, and any such use must be documented
explicitly as **observation-design transfer, not physical-parameter transfer**. In
`design_v1` no such transfer is used: the cadence and missingness grids are generic and
declared a priori.

## Naming boundary

This module uses only model labels that already exist in the repository:
`M0^{PSCC}`, `M0`, `M0S`, `M1L`, `M1N`. Two labels named in the task premise are absent
upstream and are therefore not used anywhere here; see `REPOSITORY_PREMISE_CONFLICTS.md` C3,
which also records the consequence for the ladder.

Per `other_sources/pscc_m0_recovery_audit/AUDIT_BOUNDARY.md`, no future paper-faithful
static reimplementation may be labelled `M0^{PSCC}`.

The estimator rungs in this module (`B0`, `L`, `S`, `N`) are **estimator rungs of a
synthetic identifiability ladder**, not planning models. They are not `M0`/`M0S`/`M1L`/`M1N`
and must not be cited as such.
