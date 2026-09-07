"""Legal (rng_mode, system_seed_mode) pairs. Mixed combinations are rejected."""

from __future__ import annotations

LEGAL_PAIRS: frozenset[tuple[str, str]] = frozenset(
    {
        ("legacy_sequential", "legacy_v2"),
        ("named_substreams", "orthogonal_v3"),
    }
)

RNG_LEGACY = "legacy_sequential"
RNG_NAMED = "named_substreams"
SEED_LEGACY = "legacy_v2"
SEED_ORTHOGONAL = "orthogonal_v3"


def require_legal(rng_mode: str, system_seed_mode: str) -> tuple[str, str]:
    pair = (str(rng_mode), str(system_seed_mode))
    if pair not in LEGAL_PAIRS:
        raise ValueError(
            "illegal (rng_mode, system_seed_mode) pair "
            f"{pair!r}; legal pairs are {sorted(LEGAL_PAIRS)}"
        )
    return pair


def is_legacy(rng_mode: str, system_seed_mode: str) -> bool:
    require_legal(rng_mode, system_seed_mode)
    return rng_mode == RNG_LEGACY and system_seed_mode == SEED_LEGACY


def is_substantive(rng_mode: str, system_seed_mode: str) -> bool:
    require_legal(rng_mode, system_seed_mode)
    return rng_mode == RNG_NAMED and system_seed_mode == SEED_ORTHOGONAL
