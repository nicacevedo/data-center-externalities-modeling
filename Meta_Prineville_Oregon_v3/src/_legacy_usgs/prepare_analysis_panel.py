import pandas as pd

INFILE = "meta_prineville_water_panel_same_site_huc8.csv"
OUTFILE = "meta_prineville_analysis_panel.csv"

df = pd.read_csv(
    INFILE,
    dtype={"huc12_id": str}
)

# ------------------------------------------------------------
# Geographic role
# ------------------------------------------------------------

def classify(row):

    if row["is_site"] == 1:
        return "site"

    if row["network_direction"] == "upstream":
        try:
            d = int(row["network_depth"])

            if d == 1:
                return "upstream_depth1"

            if d == 2:
                return "upstream_depth2"

            return "upstream_far"

        except (ValueError, TypeError):
            return "upstream"

    if row["network_direction"] == "downstream":
        try:
            d = int(row["network_depth"])

            if d == 1:
                return "downstream_depth1"

            if d == 2:
                return "downstream_depth2"

            return "downstream_far"

        except (ValueError, TypeError):
            return "downstream"

    if row["is_touching_site"] == 1:
        return "touching_other"

    if row["same_site_huc10"] == 1:
        return "same_huc10_other"

    return "same_huc8_other"


df["geo_role"] = df.apply(
    classify,
    axis=1
)


# ------------------------------------------------------------
# Useful indicators
# ------------------------------------------------------------

df["direct_upstream"] = (
    (df["network_direction"] == "upstream")
    &
    (df["network_depth"] == 1)
).astype(int)

df["direct_downstream"] = (
    (df["network_direction"] == "downstream")
    &
    (df["network_depth"] == 1)
).astype(int)

df["near_upstream"] = (
    (df["network_direction"] == "upstream")
    &
    (df["network_depth"] <= 2)
).astype(int)

df["near_downstream"] = (
    (df["network_direction"] == "downstream")
    &
    (df["network_depth"] <= 2)
).astype(int)


# ------------------------------------------------------------
# Month-of-year seasonality
# ------------------------------------------------------------

df["month_of_year"] = (
    pd.to_datetime(df["date"]).dt.month
)


# ------------------------------------------------------------
# QA
# ------------------------------------------------------------

print("\nGeographic roles:")
print(
    df[
        ["huc12_id", "name", "geo_role"]
    ]
    .drop_duplicates()
    .sort_values("geo_role")
    .to_string(index=False)
)

print("\nObservations by geographic role:")
print(
    df.groupby("geo_role")
    .size()
    .sort_values(ascending=False)
)

print("\nUnique HUC12s by geographic role:")
print(
    df.groupby("geo_role")["huc12_id"]
    .nunique()
    .sort_values(ascending=False)
)

print("\nSite observations:")
print(
    df.loc[df["is_site"] == 1].shape[0]
)

assert (
    df.loc[df["is_site"] == 1].shape[0]
    == 132
)

assert not df.duplicated(
    ["huc12_id", "year_month"]
).any()


# ------------------------------------------------------------
# Save
# ------------------------------------------------------------

df.to_csv(
    OUTFILE,
    index=False
)

print("\nSaved:")
print(OUTFILE)

print("\nShape:")
print(df.shape)
