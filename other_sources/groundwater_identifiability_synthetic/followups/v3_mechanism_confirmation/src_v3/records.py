"""Canonical V3 scientific-record I/O: exact uint64 seeds, typed CSV, fail-closed writer.

A uint64 seed identifier must remain an exact integer through generation, CSV
serialization, CSV loading, pairing, resume, summarization, auditing, and output
generation. No seed is ever routed through IEEE-754 floating point.

This module is the single parser/writer reused by the ANALYSIS launcher (including
resume), the frozen summarizer, the standalone summarizer CLI, and tests.
"""

from __future__ import annotations

import csv
import hashlib
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

UINT64_MAX = 2**64 - 1
FLOAT64_EXACT_INT_MAX = 2**53

INTEGER_FIELDS = frozenset({"seed"})

BOOLEAN_FIELDS = frozenset(
    {
        "false_edge_any",
        "direct_parameter_recovery_is_primary",
        "absolute_S_identifiable",
        "physical_parameter_identifiable",
        "absolute_pumping_scale_known",
        "has_placebo",
        "smoke",
        "include_node0",
        "F_intervention_global_certified",
        "F_intervention_attained_at_infinity",
        "F_train_is_monte_carlo",
        "F_intervention_is_deterministic",
    }
)
BOOLEAN_PREFIXES = (
    "placebo_false_effect_",
    "estimable_",
    "s8_real_pumping_present_",
)

CATEGORICAL_FIELDS = frozenset(
    {
        "cell_id",
        "scenario",
        "topology",
        "status",
        "memory",
        "gamma",
        "pumping_quality",
        "recharge_quality",
        "rng_mode",
        "system_seed_mode",
        "source_pool",
        "pairing_group",
        "identification_regime",
        "block",
        "variant",
        "null_mode",
        "bootstrap_resampling_unit",
        "masked_node_status",
        "masked_node_reason",
        "F_intervention_domain",
        "F_intervention_verification_strategy",
    }
)
CATEGORICAL_PREFIXES = (
    "estimability_status_",
    "estimability_reason_",
    "masked_node_status_",
    "masked_node_reason_",
)

_TRUE_TOKENS = {"True"}
_FALSE_TOKENS = {"False"}
_MISSING_TOKENS = frozenset({"", "nan", "NaN", "None", "null"})


class SeedParseError(ValueError):
    """A seed identifier was missing, malformed, or routed through floating point."""


class RecordParseError(ValueError):
    """A scientific CSV field could not be parsed under the frozen schema."""


class RecordWriteError(ValueError):
    """A scientific field would have been silently dropped on write."""


def parse_seed(value: Any) -> int:
    """Parse a uint64 seed identifier with no floating-point conversion.

    Accepts Python ``int``, NumPy integer types, and decimal digit strings.
    Rejects ``bool``, IEEE floats, scientific notation, and any string that is
    not a plain decimal integer. Range: ``0 <= seed < 2**64``.
    """
    if isinstance(value, bool) or type(value) is np.bool_:
        raise SeedParseError("seed must not be a boolean")
    if isinstance(value, np.integer):
        seed = int(value)
    elif isinstance(value, int):
        seed = value
    elif isinstance(value, str):
        text = value.strip()
        if text in _MISSING_TOKENS:
            raise SeedParseError("seed is missing")
        if text[0] in "+-" and text[1:].isdigit():
            raise SeedParseError(f"seed must be a non-negative decimal integer, got {value!r}")
        if not text.isdigit():
            raise SeedParseError(
                f"seed must be a decimal digit string with no floating-point form, got {value!r}"
            )
        seed = int(text, 10)
    elif isinstance(value, (float, np.floating)):
        raise SeedParseError(
            "seed must not be routed through IEEE-754 floating point; "
            f"got {type(value).__name__} {value!r}"
        )
    else:
        raise SeedParseError(f"seed has unsupported type {type(value).__name__}: {value!r}")
    if not 0 <= seed <= UINT64_MAX:
        raise SeedParseError(f"seed {seed} is outside uint64 range [0, 2**64-1]")
    return seed


def is_boolean_field(name: str) -> bool:
    return name in BOOLEAN_FIELDS or name.startswith(BOOLEAN_PREFIXES)


def is_categorical_field(name: str) -> bool:
    return name in CATEGORICAL_FIELDS or name.startswith(CATEGORICAL_PREFIXES)


def is_integer_field(name: str) -> bool:
    return name in INTEGER_FIELDS


def parse_bool(value: Any, *, field: str = "") -> bool | None:
    """Parse a canonical boolean. Missing -> None. Rejects silent rounding."""
    if value is None:
        return None
    if isinstance(value, bool) and not isinstance(value, np.generic):
        return value
    if type(value) is np.bool_ or isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, str):
        text = value.strip()
        if text in _MISSING_TOKENS:
            return None
        if text in _TRUE_TOKENS:
            return True
        if text in _FALSE_TOKENS:
            return False
        raise RecordParseError(f"{field or 'boolean'} has non-canonical value {value!r}")
    if isinstance(value, (int, np.integer)) and not isinstance(value, (bool, np.bool_)):
        if int(value) == 1:
            return True
        if int(value) == 0:
            return False
        raise RecordParseError(f"{field or 'boolean'} numeric value {value!r} is not 0 or 1")
    if isinstance(value, (float, np.floating)):
        if not np.isfinite(value):
            return None
        if float(value) == 1.0:
            return True
        if float(value) == 0.0:
            return False
        raise RecordParseError(f"{field or 'boolean'} float value {value!r} is not 0 or 1")
    raise RecordParseError(f"{field or 'boolean'} has unsupported type {type(value).__name__}")


def parse_float(value: Any, *, field: str = "") -> float:
    if value is None:
        return float("nan")
    if isinstance(value, bool) or isinstance(value, np.bool_):
        return 1.0 if bool(value) else 0.0
    if isinstance(value, str):
        text = value.strip()
        if text in _MISSING_TOKENS:
            return float("nan")
        try:
            return float(text)
        except ValueError as exc:
            raise RecordParseError(f"{field or 'float'} is not numeric: {value!r}") from exc
    if isinstance(value, (int, np.integer, float, np.floating)):
        return float(value)
    raise RecordParseError(f"{field or 'float'} has unsupported type {type(value).__name__}")


def field_kind(name: str) -> str:
    if is_integer_field(name):
        return "integer"
    if is_boolean_field(name):
        return "boolean"
    if is_categorical_field(name):
        return "categorical"
    return "float"


def parse_field(name: str, value: Any) -> Any:
    kind = field_kind(name)
    if kind == "integer":
        return parse_seed(value)
    if kind == "boolean":
        return parse_bool(value, field=name)
    if kind == "categorical":
        if value is None:
            return ""
        text = str(value)
        return "" if text in _MISSING_TOKENS else text
    return parse_float(value, field=name)


def parse_record(row: Mapping[str, Any]) -> dict[str, Any]:
    """Idempotent typed parse of one scientific row."""
    return {str(key): parse_field(str(key), value) for key, value in row.items()}


def serialize_field(name: str, value: Any) -> str:
    kind = field_kind(name)
    if kind == "integer":
        return str(parse_seed(value))
    if kind == "boolean":
        parsed = parse_bool(value, field=name)
        if parsed is None:
            return ""
        return "True" if parsed else "False"
    if kind == "categorical":
        if value is None:
            return ""
        text = str(value)
        return "" if text in _MISSING_TOKENS else text
    number = parse_float(value, field=name)
    if not math.isfinite(number):
        return ""
    return repr(number) if isinstance(number, float) else str(number)


def fieldnames_of(records: Sequence[Mapping[str, Any]]) -> list[str]:
    keys: set[str] = set()
    for row in records:
        keys.update(str(k) for k in row)
    return sorted(keys)


def write_csv(path: Path, records: Sequence[Mapping[str, Any]]) -> list[str]:
    """Write records using the deterministic sorted union of keys.

    Never silently drops unknown fields (DictWriter extrasaction is raise, not
    ignore). An empty record list writes an empty file. Returns the fieldnames used.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    typed = [parse_record(row) for row in records]
    fields = fieldnames_of(typed)
    if not fields:
        path.write_text("", encoding="utf-8")
        return []
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise", restval="")
        writer.writeheader()
        for row in typed:
            payload = {name: serialize_field(name, row.get(name)) for name in fields}
            extra = set(row) - set(fields)
            if extra:
                raise RecordWriteError(f"would drop unexpected fields: {sorted(extra)}")
            writer.writerow(payload)
    return fields


def append_record(path: Path, record: Mapping[str, Any], existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Append one typed record, rewriting the CSV if the union schema grows.

    This is the fail-closed streaming path: new scientific keys expand the schema
    rather than disappearing, and ``extrasaction='raise'`` is used on every write.
    """
    typed = parse_record(record)
    combined = list(existing) + [typed]
    old_fields = fieldnames_of(existing) if existing else []
    new_fields = fieldnames_of(combined)
    if new_fields != old_fields:
        write_csv(path, combined)
        return combined
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists() and path.stat().st_size > 0
    with open(path, "a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=new_fields, extrasaction="raise", restval="")
        if not file_exists:
            writer.writeheader()
        writer.writerow({name: serialize_field(name, typed.get(name)) for name in new_fields})
    return combined


def parse_csv(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return []
    with open(path, "r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [parse_record(row) for row in rows]


def pair_key(row: Mapping[str, Any]) -> tuple[str, int]:
    return str(row["cell_id"]), parse_seed(row["seed"])


def existing_keys(csv_path: Path) -> set[tuple[str, int]]:
    return {pair_key(row) for row in parse_csv(csv_path)}


def unique_pairs(records: Sequence[Mapping[str, Any]]) -> list[tuple[str, int]]:
    return sorted({pair_key(row) for row in records})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_output_hashes(out_dir: Path, files: Iterable[Path]) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / "V3_OUTPUT_HASHES.csv"
    rows = []
    for path in files:
        path = Path(path)
        if not path.exists():
            continue
        rows.append({"relative_path": path.name, "sha256": sha256_file(path)})
    with open(dest, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["relative_path", "sha256"], extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)
    return dest


def scientific_equal(left: Any, right: Any, *, path: str = "$") -> None:
    """Require exact scientific equality, with NaN-aware floats and typed seeds."""
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        extra_l = set(left) - set(right)
        extra_r = set(right) - set(left)
        if extra_l or extra_r:
            raise AssertionError(f"{path} key mismatch extra_left={sorted(extra_l)} extra_right={sorted(extra_r)}")
        for key in left:
            scientific_equal(left[key], right[key], path=f"{path}.{key}")
        return
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        if len(left) != len(right):
            raise AssertionError(f"{path} length {len(left)} != {len(right)}")
        for i, (a, b) in enumerate(zip(left, right)):
            scientific_equal(a, b, path=f"{path}[{i}]")
        return
    if isinstance(left, bool) or isinstance(right, bool):
        if bool(left) is not bool(right) or type(left) is not type(right) and not (
            isinstance(left, (bool, np.bool_)) and isinstance(right, (bool, np.bool_))
        ):
            if left != right:
                raise AssertionError(f"{path} boolean {left!r} != {right!r}")
        return
    if isinstance(left, (int, np.integer)) and isinstance(right, (int, np.integer)):
        if int(left) != int(right):
            raise AssertionError(f"{path} int {int(left)} != {int(right)}")
        return
    if isinstance(left, (float, np.floating)) or isinstance(right, (float, np.floating)):
        a = float(left) if left is not None else float("nan")
        b = float(right) if right is not None else float("nan")
        if math.isnan(a) and math.isnan(b):
            return
        if a != b:
            raise AssertionError(f"{path} float {a!r} != {b!r}")
        return
    if left != right:
        raise AssertionError(f"{path} {left!r} != {right!r}")
