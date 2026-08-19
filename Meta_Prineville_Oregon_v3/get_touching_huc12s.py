import json
import csv
from pathlib import Path

import requests

CANONICAL = Path("data/canonical/usgs")
CANONICAL.mkdir(parents=True, exist_ok=True)

URL = (
    "https://hydro.nationalmap.gov/"
    "arcgis/rest/services/wbd/MapServer/6/query"
)

SITE = "170703051002"

# -------------------------------------------------------
# 1. Retrieve site polygon as ArcGIS geometry
# -------------------------------------------------------

r = requests.get(
    URL,
    params={
        "f": "json",
        "where": f"huc12='{SITE}'",
        "outFields": "huc12,name,tohuc,areasqkm,states",
        "returnGeometry": "true",
        "outSR": "4326",
    },
    timeout=120,
)

r.raise_for_status()
data = r.json()

if "error" in data:
    raise RuntimeError(json.dumps(data["error"], indent=2))

site_feature = data["features"][0]
site_geom = site_feature["geometry"]

print("\nSITE")
print("=" * 80)
print(site_feature["attributes"])


# -------------------------------------------------------
# 2. Send that polygon back to WBD
#    and ask which HUC12 polygons touch it
# -------------------------------------------------------

r = requests.post(
    URL,
    data={
        "f": "geojson",
        "where": f"huc12 <> '{SITE}'",
        "geometry": json.dumps(site_geom),
        "geometryType": "esriGeometryPolygon",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelTouches",
        "outFields": "huc12,name,tohuc,areasqkm,states",
        "returnGeometry": "true",
        "outSR": "4326",
    },
    timeout=120,
)

r.raise_for_status()
neighbors = r.json()

if "error" in neighbors:
    raise RuntimeError(json.dumps(neighbors["error"], indent=2))

features = neighbors.get("features", [])


# -------------------------------------------------------
# 3. Print results
# -------------------------------------------------------

print("\nTOUCHING HUC12s")
print("=" * 80)

for feat in sorted(
    features,
    key=lambda x: x["properties"]["huc12"]
):
    p = feat["properties"]

    print(
        f"{p['huc12']} | "
        f"{p['name']} | "
        f"ToHUC={p.get('tohuc')} | "
        f"{p.get('areasqkm')} km2"
    )

print("\nTotal touching HUC12s:", len(features))


# -------------------------------------------------------
# 4. Save geometry
# -------------------------------------------------------

with open(CANONICAL / "touching_huc12s.geojson", "w") as f:
    json.dump(neighbors, f, indent=2)
with open("touching_huc12s.geojson", "w") as f:
    json.dump(neighbors, f, indent=2)


# -------------------------------------------------------
# 5. Save easy-to-use CSV
# -------------------------------------------------------

with open(CANONICAL / "touching_huc12s.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["huc12", "name", "tohuc", "areasqkm", "states"])
    for feat in features:
        p = feat["properties"]
        writer.writerow([
            p.get("huc12"), p.get("name"), p.get("tohuc"),
            p.get("areasqkm"), p.get("states"),
        ])

with open("touching_huc12s.csv", "w", newline="") as f:
    writer = csv.writer(f)

    writer.writerow([
        "huc12",
        "name",
        "tohuc",
        "areasqkm",
        "states",
    ])

    for feat in features:
        p = feat["properties"]

        writer.writerow([
            p.get("huc12"),
            p.get("name"),
            p.get("tohuc"),
            p.get("areasqkm"),
            p.get("states"),
        ])

print("\nSaved:")
print("  data/canonical/usgs/touching_huc12s.geojson")
print("  data/canonical/usgs/touching_huc12s.csv")
