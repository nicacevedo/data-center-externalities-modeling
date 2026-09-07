"""Frozen-design loading, cell resolution, and seed management (V3 tree).

Vendored from V2 then path/hash scopes retargeted. V2 hashes are recomputed against the
parent module root and must remain b53f5594… / 7cc64809….
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
V2_PARENT_ROOT = MODULE_ROOT.parent.parent
CONFIG_PATH = MODULE_ROOT / "config" / "design_v3.yaml"
FREEZE_DOC_PATH = MODULE_ROOT / "DESIGN_FREEZE_V3.md"
FREEZE_JSON_RELATIVE = "outputs/provenance/DESIGN_V3_FREEZE.json"

# Canonical scientific-design artifacts. Together these determine V3_DESIGN_HASH.
DESIGN_ARTIFACTS = (
    "config/design_v3.yaml",
    "DESIGN_FREEZE_V3.md",
    "BENCHMARK_DEFINITIONS.md",
)

# Every V3 scientific source file. Determines V3_CODE_HASH. Does NOT glob V2 src/.
CODE_GLOBS = ("src_v3/*.py", "scripts_v3/*.py", "tests_v3/*.py")

V2_DESIGN_ARTIFACTS = ("config/design_v2.yaml", "DESIGN_FREEZE_V2.md")
V2_CODE_GLOBS = ("src/*.py", "scripts/*.py", "tests/*.py")
V2_EXPECTED_DESIGN_HASH = "b53f5594a444ae4826adfe2c47818080508a4c4b00a38fa25b4ffc483e20a8a5"
V2_EXPECTED_CODE_HASH = "7cc64809bf240d7afea164c9a24a737c75de88a0b5e8d38f4e85b704f00d863c"


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
    """SHA-256 over every V3 scientific source file. Changes on any bugfix."""
    base = root or MODULE_ROOT
    accumulator = hashlib.sha256()
    for path in code_files(base):
        accumulator.update(path.relative_to(base).as_posix().encode("utf-8"))
        accumulator.update(sha256_file(path).encode("utf-8"))
    return accumulator.hexdigest()


def _hash_artifacts(base: Path, artifacts: tuple[str, ...]) -> str:
    accumulator = hashlib.sha256()
    for relative in artifacts:
        accumulator.update(relative.encode("utf-8"))
        accumulator.update(sha256_file(base / relative).encode("utf-8"))
    return accumulator.hexdigest()


def _hash_globs(base: Path, globs: tuple[str, ...]) -> str:
    found: list[Path] = []
    for pattern in globs:
        found.extend(sorted(base.glob(pattern)))
    files = [p for p in found if "__pycache__" not in p.parts]
    accumulator = hashlib.sha256()
    for path in files:
        accumulator.update(path.relative_to(base).as_posix().encode("utf-8"))
        accumulator.update(sha256_file(path).encode("utf-8"))
    return accumulator.hexdigest()


def v2_parent_design_hash() -> str:
    return _hash_artifacts(V2_PARENT_ROOT, V2_DESIGN_ARTIFACTS)


def v2_parent_code_hash() -> str:
    return _hash_globs(V2_PARENT_ROOT, V2_CODE_GLOBS)


# -------------------------------------------------------------------------------------
# Seed pools. Four disjoint pools with distinct root entropies.
# -------------------------------------------------------------------------------------


def seed_pool_hash(design: dict[str, Any], pool: str) -> str:
    """SHA-256 of the materialized integer seed list for a named pool."""
    values = seed_list(design, pool)
    return hashlib.sha256(",".join(str(v) for v in values).encode("utf-8")).hexdigest()


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
    elif overrides == "OBS_FAV_GAMMA_FREE":
        override_map = dict(design["obs_fav_gamma_free_overrides"])
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
    """All enumerated gate cells, resolved. Keys are cell ids such as G1R3.

    V3 designs may set `gates: {}`; then this returns an empty dict.
    """
    resolved: dict[str, RegimeSpec] = {}
    gates = design.get("gates") or {}
    if not gates:
        return resolved
    for gate_name in ("SGI_G0", "SGI_G1", "SGI_G2", "SGI_G3"):
        block = gates.get(gate_name) or {}
        required = block.get("required_cells") or {}
        for cell_id, spec in required.items():
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


_V3_FACTOR_KEYS = (
    "memory",
    "cadence",
    "gamma",
    "pumping_quality",
    "pumping_quality_param",
    "recharge_quality",
    "recharge_quality_param",
    "confounding_rho",
    "mcar_fraction",
    "blocks_per_node",
    "observed_node_fraction",
    "snr_head",
    "process_noise_sd",
)


def resolve_v3_cell(design: dict[str, Any], cell_id: str) -> RegimeSpec:
    """Resolve a fully materialized V3 cell. Every scientific factor is explicit."""
    spec = design["v3_cells"][cell_id]
    overrides = {k: spec[k] for k in _V3_FACTOR_KEYS if k in spec}
    regime = resolve_regime(
        design,
        cell_id=cell_id,
        scenario=str(spec["scenario"]),
        topology=str(spec["topology"]),
        overrides=overrides,
    )
    extra = dict(regime.extra)
    extra.update(
        {
            "block": spec.get("block"),
            "identification_regime": spec.get("identification_regime"),
            "pairing_group": spec.get("pairing_group"),
            "notes": spec.get("notes"),
            "resolved_factors": {k: spec[k] for k in _V3_FACTOR_KEYS if k in spec},
        }
    )
    return RegimeSpec(**{**asdict(regime), "extra": extra})


def v3_all_cells(design: dict[str, Any]) -> dict[str, RegimeSpec]:
    return {cid: resolve_v3_cell(design, cid) for cid in design["v3_cells"]}


def resolved_cell_table(design: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for cid, regime in v3_all_cells(design).items():
        spec = design["v3_cells"][cid]
        row = {
            "cell_id": cid,
            "block": spec.get("block"),
            "scenario": regime.scenario,
            "topology": regime.topology,
            "memory": regime.memory,
            "cadence": regime.cadence,
            "gamma": regime.gamma,
            "pumping_quality": regime.pumping_quality,
            "pumping_noise_s": regime.pumping_noise_s,
            "recharge_quality": regime.recharge_quality,
            "recharge_sigma": regime.recharge_sigma,
            "recharge_lag": regime.recharge_lag,
            "confounding_rho": regime.confounding_rho,
            "mcar_fraction": regime.mcar_fraction,
            "blocks_per_node": regime.blocks_per_node,
            "observed_node_fraction": regime.observed_node_fraction,
            "snr_head": regime.snr_head,
            "process_noise_sd": regime.process_noise_sd,
            "identification_regime": spec.get("identification_regime"),
            "pairing_group": spec.get("pairing_group"),
        }
        rows.append(row)
    return rows
