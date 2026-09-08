# E0 public-source acquisition store

Native files and metadata for the targeted AP E0 public-source pass.

```text
raw/        native downloaded files (do not overwrite)
metadata/   landing-page snapshots, API/schema samples, catalogs
derived/    summaries separate from raw sources
```

Large native binaries may be local-only under `raw/` (see `raw/.gitignore`).
Hashes for every acquired artifact are in
[../AP_E0_SOURCE_PROVENANCE_MANIFEST.csv](../AP_E0_SOURCE_PROVENANCE_MANIFEST.csv).

Do not treat a file in this directory as scientifically ADEQUATE.
ACCESS_STATUS and SCIENTIFIC_STATUS are recorded independently.
