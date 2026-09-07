"""Frozen-design loading, cell resolution, and seed management.

Nothing in this module touches synthetic truth values; it only resolves the frozen design
into concrete regime specifications and reproducible RNG streams.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import numpy as np
import yaml

MODULE_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = MODULE_ROOT / "config" / "design_v1.yaml"
FREEZE_DOC_PATH = MODULE_ROOT / "DESIGN_FREEZE.md"

# Canonical scientific-design artifacts. Together these determine DESIGN_HASH.
DESIGN_ARTIFACTS = ("config/design_v1.yaml", "DESIGN_FREEZE.md")

# Every source file whose content is scientific. Determines CODE_HASH.
CODE_GLOBS = ("src/*.py", "scripts/*.py", "tests/*.py")


def load_design(path: Path | None = None) -> dict[str, Any]:
    with open(path or CONFIG_PATH, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def design_hash(root: Path | None = None) -> str:
    """SHA-256 over ALL canonical scientific-design artifacts, not just config/."""
    base = root or MODULE_ROOT
    accumulator = hashlib.sha256()
    for relative in DESIGN_ARTIFACTS:
        accumulator.update(relative.encode("utf-8"))
        accumulator.update(sha256_file(base / relative).encode("utf-8"))
    return accumulator.hexdigest()


def code_files(root: Path | None = None) -> list[Path]:
    base = root or MODULE_ROOT
    found: list[Path] = []
    for pattern in CODE_GLOBS:
        found.extend(sorted(base.glob(pattern)))
    return [p for p in found if "__pycache__" not in p.parts]


def code_hash(root: Path | None = None) -> str:
    """SHA-256 over every scientific source file. Changes on any bugfix."""
    base = root or MODULE_ROOT
    accumulator = hashlib.sha256()
    for path in code_files(base):
        accumulator.update(path.relative_to(base).as_posix().encode("utf-8"))
        accumulator.update(sha256_file(path).encode("utf-8"))
    return accumulator.hexdigest()


# -------------------------------------------------------------------------------------
# Seed pools. Four disjoint pools with distinct root entropies.
# -------------------------------------------------------------------------------------


def seed_list(design: dict[str, Any], pool: str) -> list[int]:
    """Materialize a pool's seeds as plain integers, reproducibly.

    Uses numpy.random.SeedSequence spawning, which is the pinned RNG protocol. The
    materialized integers are what the disjointness test compares.
    """
    spec = design["seeds"]["pools"][pool]
    root = np.random.SeedSequence(entropy=int(spec["entropy"]))
    children = root.spawn(int(spec["n_seeds"]))
    return [int(child.generate_state(1, dtype=np.uint64)[0]) for child in children]


def rng_for(seed: int) -> np.random.Generator:
    """Pinned RNG implementation: PCG64 via numpy.random.default_rng."""
    return np.random.Generator(np.random.PCG64(seed))


def structural_seed(*parts: Any) -> int:
    """Deterministic seed for the *system* (S, C, geometry), fixed within a cell.

    The truth system is held fixed across replicates inside a cell so that across-seed
    variability is purely stochastic (forcing and noise realizations), not structural.
    """
    payload = "|".join(str(p) for p in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


# -------------------------------------------------------------------------------------
# Regime resolution
# -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RegimeSpec:
    """A fully resolved experiment cell. Contains no truth values."""

    cell_id: str
    scenario: str
    topology: str
    memory: str
    cadence: int
    gamma: str
    pumping_quality: str
    pumping_noise_s: float
    recharge_quality: str
    recharge_sigma: float
    recharge_lag: int
    confounding_rho: float
    mcar_fraction: float
    blocks_per_node: int
    observed_node_fraction: float
    snr_head: float
    process_noise_sd: float
    variant: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def key(self) -> str:
        payload = asdict(self)
        payload.pop("cell_id")
        return json.dumps(payload, sort_keys=True, default=str)


def _pumping_noise_s(design: dict[str, Any], regime: str, explicit: Any) -> float:
    """Multiplicative-noise scale for a pumping-quality regime.

    Only P-MULTNOISE carries a noise scale; the other regimes have their own frozen
    parameters read directly from the design at observation time.
    """
    if regime != "P-MULTNOISE":
        return 0.0
    if explicit is not None:
        return float(explicit)
    return float(design["observation"]["pumping_quality_regimes"]["P-MULTNOISE"]["s_default"])


def _recharge_params(design: dict[str, Any], regime: str, explicit_sigma: Any) -> tuple[float, int]:
    """(sigma, lag) for a recharge-quality regime.

    R-NOISELAG legitimately needs both, which is why these are separate fields rather than
    one overloaded parameter.
    """
    regimes = design["observation"]["recharge_quality_regimes"]
    spec = regimes.get(regime, {})
    sigma = 0.0
    lag = 0
    if regime in ("R-NOISE", "R-NOISELAG"):
        sigma = float(spec.get("sigma_default", 0.0))
    if regime in ("R-LAG", "R-NOISELAG"):
        lag = int(spec.get("lag_default", 0))
    if explicit_sigma is not None and regime in ("R-NOISE", "R-NOISELAG"):
        sigma = float(explicit_sigma)
    return sigma, lag


def resolve_regime(
    design: dict[str, Any],
    cell_id: str,
    scenario: str,
    topology: str,
    overrides: Any = None,
    variant: str | None = None,
) -> RegimeSpec:
    """Resolve a cell against the frozen reference regime.

    `overrides` may be the literal string ORACLE_FAVOURABLE, a mapping of field overrides,
    or None. An override that changes a quality regime without naming a parameter picks up
    that regime's frozen default.
    """
    base = dict(design["reference_regime"])
    override_map: dict[str, Any] = {}
    if overrides == "ORACLE_FAVOURABLE":
        override_map = dict(design["oracle_favourable_overrides"])
    elif isinstance(overrides, dict):
        override_map = dict(overrides)
    elif overrides not in (None, {}):
        raise ValueError(f"unsupported overrides for cell {cell_id}: {overrides!r}")
    base.update(override_map)

    pumping_regime = str(base["pumping_quality"])
    recharge_regime = str(base["recharge_quality"])

    # An explicit parameter counts only if the caller actually supplied one, or if the
    # regime itself was left at the reference value.
    explicit_pump = override_map.get("pumping_quality_param")
    if explicit_pump is None and "pumping_quality" not in override_map:
        explicit_pump = base.get("pumping_quality_param")
    explicit_recharge = override_map.get("recharge_quality_param")
    if explicit_recharge is None and "recharge_quality" not in override_map:
        explicit_recharge = base.get("recharge_quality_param")

    sigma, lag = _recharge_params(design, recharge_regime, explicit_recharge)

    return RegimeSpec(
        cell_id=cell_id,
        scenario=scenario,
        topology=topology,
        memory=str(base["memory"]),
        cadence=int(base["cadence"]),
        gamma=str(base["gamma"]),
        pumping_quality=pumping_regime,
        pumping_noise_s=_pumping_noise_s(design, pumping_regime, explicit_pump),
        recharge_quality=recharge_regime,
        recharge_sigma=sigma,
        recharge_lag=lag,
        confounding_rho=float(base["confounding_rho"]),
        mcar_fraction=float(base["mcar_fraction"]),
        blocks_per_node=int(base["blocks_per_node"]),
        observed_node_fraction=float(base["observed_node_fraction"]),
        snr_head=float(base["snr_head"]),
        process_noise_sd=float(base["process_noise_sd"]),
        variant=variant,
    )


def gate_cells(design: dict[str, Any]) -> dict[str, RegimeSpec]:
    """All enumerated gate cells, resolved. Keys are cell ids such as G1R3."""
    resolved: dict[str, RegimeSpec] = {}
    for gate_name in ("SGI_G0", "SGI_G1", "SGI_G2", "SGI_G3"):
        for cell_id, spec in design["gates"][gate_name]["required_cells"].items():
            if cell_id in resolved:
                continue
            resolved[cell_id] = resolve_regime(
                design,
                cell_id=cell_id,
                scenario=spec["scenario"],
                topology=spec["topology"],
                overrides=spec.get("overrides"),
            )
    return resolved


def reporting_cells(design: dict[str, Any]) -> dict[str, RegimeSpec]:
    resolved: dict[str, RegimeSpec] = {}
    for cell_id, spec in design.get("reporting_cells", {}).items():
        resolved[cell_id] = resolve_regime(
            design,
            cell_id=cell_id,
            scenario=spec["scenario"],
            topology=spec["topology"],
            overrides=spec.get("overrides"),
            variant=spec.get("variant"),
        )
    return resolved
