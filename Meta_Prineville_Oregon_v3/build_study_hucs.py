import csv
import requests

SITE_HUC12 = "170703051002"
SITE_HUC10 = "1707030510"
SITE_HUC8  = "17070305"

WBD_URL = (
    "https://hydro.nationalmap.gov/"
    "arcgis/rest/services/wbd/MapServer/6/query"
)


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def query_prefix(prefix):
    """
    Return every HUC12 beginning with a specified HUC prefix.
    """
    params = {
        "f": "json",
        "where": f"huc12 LIKE '{prefix}%'",
        "outFields": "huc12,name,tohuc,areasqkm,states",
        "returnGeometry": "false",
    }

    r = requests.get(
        WBD_URL,
        params=params,
        timeout=120,
    )
    r.raise_for_status()

    data = r.json()

    if "error" in data:
        raise RuntimeError(data["error"])

    return [
        x["attributes"]
        for x in data.get("features", [])
    ]


# ------------------------------------------------------------
# Existing files you already created
# ------------------------------------------------------------

network = read_csv(
    "meta_huc12_hydrologic_network.csv"
)

touching = read_csv(
    "touching_huc12s.csv"
)


network_by_huc = {
    r["huc12"]: r
    for r in network
}

touching_ids = {
    r["huc12"]
    for r in touching
}


# ------------------------------------------------------------
# Query HUC10 and HUC8 constituent HUC12s
# ------------------------------------------------------------

huc10_rows = query_prefix(SITE_HUC10)
huc8_rows = query_prefix(SITE_HUC8)

huc10_ids = {
    r["huc12"]
    for r in huc10_rows
}

huc8_ids = {
    r["huc12"]
    for r in huc8_rows
}


# Metadata lookup
metadata = {}

for collection in [
    huc8_rows,
    huc10_rows,
    touching,
]:
    for r in collection:
        metadata[r["huc12"]] = r

for r in network:
    metadata[r["huc12"]] = r


# ------------------------------------------------------------
# Which HUC12s should appear in MASTER file?
#
# Include:
#   * entire HUC8
#   * touching site
#   * near upstream/downstream units
#
# Full recursive network is NOT added automatically.
# ------------------------------------------------------------

study_ids = set(huc8_ids)

study_ids.add(SITE_HUC12)
study_ids.update(touching_ids)

# Add near hydrologic units even if outside site HUC8
for r in network:

    try:
        depth = int(r["depth"])
    except (ValueError, TypeError):
        continue

    direction = r["direction"]

    if (
        direction == "upstream"
        and depth <= 2
    ):
        study_ids.add(r["huc12"])

    if (
        direction == "downstream"
        and depth <= 2
    ):
        study_ids.add(r["huc12"])


# ------------------------------------------------------------
# Construct master table
# ------------------------------------------------------------

output = []

for huc in sorted(study_ids):

    meta = metadata.get(huc, {})
    net = network_by_huc.get(huc, {})

    direction = net.get(
        "direction",
        ""
    )

    depth = net.get(
        "depth",
        ""
    )

    is_site = int(
        huc == SITE_HUC12
    )

    is_touching = int(
        huc in touching_ids
    )

    same_huc10 = int(
        huc in huc10_ids
    )

    same_huc8 = int(
        huc in huc8_ids
    )


    # Core local geography:
    # site + polygons sharing boundary
    scope_local = int(
        is_site
        or is_touching
    )


    # Hydrologically near:
    # site + first two network steps either way
    hydro_near = is_site

    if direction in (
        "upstream",
        "downstream",
    ):
        try:
            hydro_near = (
                hydro_near
                or int(depth) <= 2
            )
        except ValueError:
            pass

    scope_hydro_near = int(
        hydro_near
    )


    output.append({
        "huc12": huc,
        "name": meta.get("name", ""),
        "tohuc": meta.get("tohuc", ""),
        "areasqkm": meta.get("areasqkm", ""),
        "states": meta.get("states", ""),

        "is_site": is_site,
        "is_touching_site": is_touching,

        "network_direction": direction,
        "network_depth": depth,

        "same_site_huc10": same_huc10,
        "same_site_huc8": same_huc8,

        "scope_local": scope_local,
        "scope_hydro_near": scope_hydro_near,
    })


# ------------------------------------------------------------
# Save
# ------------------------------------------------------------

fields = [
    "huc12",
    "name",
    "tohuc",
    "areasqkm",
    "states",
    "is_site",
    "is_touching_site",
    "network_direction",
    "network_depth",
    "same_site_huc10",
    "same_site_huc8",
    "scope_local",
    "scope_hydro_near",
]

with open(
    "meta_prineville_study_hucs.csv",
    "w",
    newline=""
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=fields
    )

    writer.writeheader()
    writer.writerows(output)


# ------------------------------------------------------------
# Summary
# ------------------------------------------------------------

print("\nMETA PRINEVILLE STUDY GEOGRAPHY")
print("=" * 80)

print("Site HUC12 :", SITE_HUC12)
print("Site HUC10 :", SITE_HUC10)
print("Site HUC8  :", SITE_HUC8)

print(
    "\nTouching HUC12s:",
    len(touching_ids)
)

print(
    "HUC12s in site HUC10:",
    len(huc10_ids)
)

print(
    "HUC12s in site HUC8:",
    len(huc8_ids)
)

print(
    "Local scope:",
    sum(
        r["scope_local"]
        for r in output
    )
)

print(
    "Hydrologically near:",
    sum(
        r["scope_hydro_near"]
        for r in output
    )
)

print(
    "\nSaved:",
    "meta_prineville_study_hucs.csv"
)
