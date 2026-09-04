"""Deterministic utilities for a data audit; this module contains no model fitting."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")


def write_markdown_table(path: Path, frame: pd.DataFrame, heading: str, intro: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {heading}", ""]
    if intro:
        lines.extend([intro, ""])
    if frame.empty:
        lines.append("No rows.")
    else:
        safe = frame.fillna("").astype(str)
        columns = list(safe.columns)
        lines.append("| " + " | ".join(columns) + " |")
        lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
        for row in safe.itertuples(index=False, name=None):
            cells = [str(value).replace("|", "\\|").replace("\n", " ") for value in row]
            lines.append("| " + " | ".join(cells) + " |")
    path.write_text("\n".join(lines) + "\n")


def point_in_ring(longitude: float, latitude: float, ring: list[list[float]]) -> bool:
    """Ray-casting point-in-ring test in the ring's native lon/lat coordinates."""
    inside = False
    count = len(ring)
    if count < 3:
        return False
    prior = count - 1
    for current in range(count):
        x_i, y_i = ring[current][:2]
        x_j, y_j = ring[prior][:2]
        crosses = (y_i > latitude) != (y_j > latitude)
        if crosses:
            x_cross = (x_j - x_i) * (latitude - y_i) / (y_j - y_i) + x_i
            if longitude < x_cross:
                inside = not inside
        prior = current
    return inside


def point_in_geometry(longitude: float, latitude: float, geometry: dict[str, Any]) -> bool:
    """Return membership for GeoJSON Polygon/MultiPolygon, respecting holes."""
    if pd.isna(longitude) or pd.isna(latitude):
        return False
    geom_type = geometry["type"]
    coordinates = geometry["coordinates"]
    polygons = [coordinates] if geom_type == "Polygon" else coordinates
    if geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError(f"Unsupported geometry type: {geom_type}")
    for polygon in polygons:
        if not polygon or not point_in_ring(float(longitude), float(latitude), polygon[0]):
            continue
        if any(point_in_ring(float(longitude), float(latitude), hole) for hole in polygon[1:]):
            continue
        return True
    return False


def geometry_rings(geometry: dict[str, Any]) -> Iterable[list[list[float]]]:
    coordinates = geometry["coordinates"]
    polygons = [coordinates] if geometry["type"] == "Polygon" else coordinates
    for polygon in polygons:
        if polygon:
            yield polygon[0]


def read_usgs_rdb(path: Path) -> pd.DataFrame:
    lines = [line for line in path.read_text(errors="replace").splitlines() if not line.startswith("#")]
    if len(lines) < 3:
        raise ValueError(f"No tabular records in {path}")
    return pd.read_csv(io.StringIO("\n".join([lines[0], *lines[2:]])), sep="\t", dtype=str)


def records_from_ckan_json(path: Path) -> pd.DataFrame:
    payload = json.loads(path.read_text())
    if not payload.get("success"):
        raise ValueError(f"Unsuccessful CKAN response: {path}")
    return pd.DataFrame(payload["result"]["records"])


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))

