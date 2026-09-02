"""Fail-closed guard against reading protected Meta water files in this pass.

2023–2024 Meta water remains DIAGNOSTIC_PREVIOUSLY_EXPOSED and is not an input
to structural revision, physics validation, or parameter choice.
"""
from __future__ import annotations

import builtins
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROTECTED_RELATIVE = (
    "data/canonical/meta_prineville_annual.csv",
    "outputs/conditional_annual_compare.csv",
    "outputs/conditional_water_model.csv",
    "outputs/pipeline_report/water_holdout_baseline_compare.csv",
    "outputs/city_prineville/frozen_annual_water_validation_v1/water_holdout_baseline_compare.csv",
    "outputs/pipeline_report/result_claims.csv",
    "outputs/weather_ks39/canonical_conditional_annual_compare.csv",
)


class HoldoutAccessError(RuntimeError):
    """Raised if a protected Meta-water file is opened during structural execution."""


def protected_paths(root: Path | None = None) -> list[Path]:
    base = (root or ROOT).resolve()
    return [(base / rel).resolve() for rel in PROTECTED_RELATIVE]


def is_protected_path(path: Path, root: Path | None = None) -> bool:
    try:
        resolved = Path(path).resolve()
    except OSError:
        return False
    return resolved in set(protected_paths(root))


class HoldoutGuard:
    """Wrap builtins.open so protected Meta-water files cannot be read."""

    def __init__(self, root: Path | None = None):
        self.root = (root or ROOT).resolve()
        self.protected_files = [str(p) for p in protected_paths(self.root)]
        self.access_attempts: list[str] = []
        self.accessed = False
        self._installed = False
        self._orig_open = None
        self._orig_io_open = None

    def _check(self, file) -> None:
        if isinstance(file, (int, bytes)):
            return
        try:
            path = Path(file)
        except TypeError:
            return
        if not path.parts:
            return
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in set(protected_paths(self.root)) or is_protected_path(path, self.root):
            self.access_attempts.append(str(resolved))
            self.accessed = True
            raise HoldoutAccessError(
                f"Protected Meta-water file opened during structural revision: {resolved}. "
                "2023–2024 values are DIAGNOSTIC_PREVIOUSLY_EXPOSED and are not part of this pass."
            )

    def install(self) -> None:
        if self._installed:
            return
        self._orig_open = builtins.open
        self._orig_io_open = io.open

        def _guarded_open(file, *args, **kwargs):
            self._check(file)
            return self._orig_open(file, *args, **kwargs)

        def _guarded_io_open(file, *args, **kwargs):
            self._check(file)
            return self._orig_io_open(file, *args, **kwargs)

        builtins.open = _guarded_open
        io.open = _guarded_io_open
        self._installed = True

    def uninstall(self) -> None:
        if self._installed:
            if self._orig_open is not None:
                builtins.open = self._orig_open
            if self._orig_io_open is not None:
                io.open = self._orig_io_open
        self._installed = False

    def record(self) -> dict:
        return {
            "protected_files": self.protected_files,
            "access_attempts": list(self.access_attempts),
            "accessed": bool(self.accessed),
            "holdout_status": "DIAGNOSTIC_PREVIOUSLY_EXPOSED",
            "structural_runner_imports_holdout_data_module": False,
        }

    def __enter__(self):
        self.install()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.uninstall()
        return False
