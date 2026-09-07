"""Named-substream RNG for V3 common-random-number pairing.

Component spawn keys are SHA-256 derived, never Python's salted runtime hash().
Adding a component does not reindex existing ones.
"""

from __future__ import annotations

import hashlib
from typing import Iterable

import numpy as np

COMPONENTS: tuple[str, ...] = (
    "initial_condition",
    "recharge_innovations",
    "recharge_initial",
    "latent_climate_innovations",
    "latent_climate_initial",
    "pumping_innovations",
    "pumping_initial",
    "pumping_excitation",
    "placebo_independent",
    "process_noise",
    "head_measurement_noise",
    "node_subsample",
    "mcar_uniforms",
    "block_outage_starts",
    "pumping_degradation_z",
    "pumping_scalebias",
    "pumping_dirichlet",
    "recharge_degradation_z",
    "recharge_scalebias",
    "pseudo_true_mc",
    "bootstrap",
    "benchmark_mc",
)


def component_spawn_key(component: str) -> int:
    digest = hashlib.sha256(f"v3-substream:{component}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def substream(seed: int, component: str) -> np.random.Generator:
    if component not in COMPONENTS:
        raise ValueError(f"unknown RNG component {component!r}")
    key = component_spawn_key(component)
    seq = np.random.SeedSequence(entropy=int(seed), spawn_key=(key,))
    return np.random.Generator(np.random.PCG64(seq))


class StreamBank:
    """Per-replicate named streams. Constructed once; never reindexed."""

    def __init__(self, seed: int):
        self.seed = int(seed)
        self._streams = {name: substream(self.seed, name) for name in COMPONENTS}

    def __getitem__(self, component: str) -> np.random.Generator:
        return self._streams[component]

    def names(self) -> Iterable[str]:
        return COMPONENTS
