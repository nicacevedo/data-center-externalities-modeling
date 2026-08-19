import requests
import csv
import time

URL = (
    "https://hydro.nationalmap.gov/"
    "arcgis/rest/services/wbd/MapServer/6/query"
)

SITE = "170703051002"


def query(where):
    params = {
        "f": "json",
        "where": where,
        "outFields": "huc12,name,tohuc,areasqkm,states",
        "returnGeometry": "false",
    }

    r = requests.get(URL, params=params, timeout=120)
    r.raise_for_status()

    data = r.json()

    if "error" in data:
        raise RuntimeError(data["error"])

    return [
        f["attributes"]
        for f in data.get("features", [])
    ]


def get_huc(huc):
    rows = query(f"huc12='{huc}'")

    if not rows:
        return None

    return rows[0]


def get_immediate_upstream(huc):
    return query(f"tohuc='{huc}'")


# ============================================================
# DOWNSTREAM PATH
# ============================================================

downstream = []

current = SITE
depth = 0
seen = set()

while current and current not in seen:
    seen.add(current)

    row = get_huc(current)

    if row is None:
        break

    if depth > 0:
        downstream.append({
            **row,
            "direction": "downstream",
            "depth": depth,
        })

    next_huc = row.get("tohuc")

    if (
        not next_huc
        or next_huc == current
        or next_huc in ("0", "000000000000")
    ):
        break

    current = next_huc
    depth += 1

    time.sleep(0.1)


# ============================================================
# UPSTREAM NETWORK
#
# Breadth-first search:
# Find everything whose ToHUC eventually leads to SITE.
# ============================================================

upstream = []

queue = [(SITE, 0)]
seen = {SITE}

while queue:

    receiving_huc, depth = queue.pop(0)

    parents = get_immediate_upstream(receiving_huc)

    for row in parents:

        huc = row["huc12"]

        if huc in seen:
            continue

        seen.add(huc)

        upstream.append({
            **row,
            "direction": "upstream",
            "depth": depth + 1,
        })

        queue.append(
            (huc, depth + 1)
        )

    time.sleep(0.1)


# ============================================================
# PRINT
# ============================================================

print("\nSITE")
print("=" * 90)

site = get_huc(SITE)
print(
    SITE,
    "|",
    site["name"],
    "| ToHUC:",
    site["tohuc"],
)


print("\nUPSTREAM NETWORK")
print("=" * 90)

for row in sorted(
    upstream,
    key=lambda x: (x["depth"], x["huc12"])
):
    indent = "  " * row["depth"]

    print(
        f"{indent}"
        f"depth={row['depth']} "
        f"{row['huc12']} | "
        f"{row['name']} | "
        f"ToHUC={row['tohuc']}"
    )


print("\nDOWNSTREAM PATH")
print("=" * 90)

for row in downstream:
    print(
        f"depth={row['depth']} "
        f"{row['huc12']} | "
        f"{row['name']} | "
        f"ToHUC={row['tohuc']}"
    )


# ============================================================
# SAVE CSV
# ============================================================

rows = []

rows.append({
    **site,
    "direction": "site",
    "depth": 0,
})

rows.extend(upstream)
rows.extend(downstream)

with open(
    "meta_huc12_hydrologic_network.csv",
    "w",
    newline=""
) as f:

    fields = [
        "direction",
        "depth",
        "huc12",
        "name",
        "tohuc",
        "areasqkm",
        "states",
    ]

    writer = csv.DictWriter(
        f,
        fieldnames=fields
    )

    writer.writeheader()

    for row in rows:
        writer.writerow({
            k: row.get(k)
            for k in fields
        })


print("\nSaved:")
print("meta_huc12_hydrologic_network.csv")

print("\nCounts:")
print("Upstream HUC12s :", len(upstream))
print("Downstream HUC12s:", len(downstream))
