"""Synthetic known-truth groundwater identifiability experiment (design_v1).

Scope: reduced-order head / pumping / recharge response core only. See SCOPE.md.

Architectural rule enforced by tests: estimation code in `models` and `fit` receives only
`ObservationBundle` objects. True parameters live in `SystemTruth` / `Trajectory` and are
reachable only from the data-generating process and the post-fit evaluation layer.
"""

MODULE_NAME = "groundwater_identifiability_synthetic"
DESIGN_VERSION = "design_v1"
