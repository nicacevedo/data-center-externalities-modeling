import numpy as np
import xarray as xr

PATH = "raw/20140710_1200.nc"

ds = xr.open_dataset(PATH, engine="netcdf4")


def clean_string(x):
    """Safely normalize MADIS byte/string fields."""
    if isinstance(x, bytes):
        return x.decode("ascii", errors="ignore").strip("\x00 ").upper()
    return str(x).strip("\x00 ").upper()


# ---------------------------------------------------------
# 1. Decode station identifiers
# ---------------------------------------------------------

station = np.array(
    [clean_string(x) for x in ds["stationName"].values],
    dtype=object,
)

print(f"Records in file: {len(station):,}")
print(f"Unique station IDs: {len(np.unique(station)):,}")

print("\nFirst 30 station IDs:")
print(np.unique(station)[:30])


# ---------------------------------------------------------
# 2. Search explicitly for Prineville
# ---------------------------------------------------------

targets = {"KS39", "S39"}

mask = np.array([x in targets for x in station])

print("\nExact KS39/S39 matches:")
print(np.unique(station[mask], return_counts=True))


# ---------------------------------------------------------
# 3. Also search spatially, in case MADIS uses another ID
# ---------------------------------------------------------

TARGET_LAT = 44.2870
TARGET_LON = -120.9038

lat = ds["latitude"].values
lon = ds["longitude"].values

near = (
    np.isfinite(lat)
    & np.isfinite(lon)
    & (np.abs(lat - TARGET_LAT) <= 0.10)
    & (np.abs(lon - TARGET_LON) <= 0.10)
)

print("\nStations within about 0.10 degrees of Prineville Airport:")

near_idx = np.where(near)[0]

for i in near_idx:
    loc = clean_string(ds["locationName"].values[i])

    print(
        i,
        station[i],
        loc,
        float(lat[i]),
        float(lon[i]),
        float(ds["elevation"].values[i]),
    )


# ---------------------------------------------------------
# 4. If KS39 exists, print its observations
# ---------------------------------------------------------

idx = np.where(mask)[0]

if len(idx) == 0:
    print("\nKS39/S39 NOT PRESENT in this MADIS hourly file.")
else:
    print(f"\nFound {len(idx)} KS39/S39 record(s).")

    fields = [
        "stationName",
        "locationName",
        "latitude",
        "longitude",
        "elevation",
        "timeObs",
        "timeNominal",
        "reportType",
        "temperature",
        "temperatureQCA",
        "temperatureQCR",
        "dewpoint",
        "dewpointQCA",
        "dewpointQCR",
        "seaLevelPress",
        "seaLevelPressQCA",
        "seaLevelPressQCR",
        "altimeter",
        "windDir",
        "windSpeed",
        "windGust",
        "precip1Hour",
        "rawMETAR",
    ]

    for i in idx:
        print("\n-----------------------------")
        print(f"Record {i}")
        print("-----------------------------")

        for field in fields:
            if field not in ds:
                continue

            value = ds[field].values[i]

            if field in {"stationName", "locationName", "reportType", "rawMETAR"}:
                value = clean_string(value)

            print(f"{field:22s}: {value}")


# ---------------------------------------------------------
# 5. Print time metadata so we decode timestamps correctly
# ---------------------------------------------------------

print("\ntimeObs metadata:")
print(ds["timeObs"].attrs)

print("\nRelevant unit metadata:")
for field in [
    "temperature",
    "dewpoint",
    "seaLevelPress",
    "altimeter",
    "windSpeed",
    "precip1Hour",
]:
    if field in ds:
        print(field, ds[field].attrs)