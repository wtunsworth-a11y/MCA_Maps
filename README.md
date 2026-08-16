# MCA Maps

Turn zipped spatial data into maps you can look at, share, and open in QGIS.

The workflow has three stages, each a separate script so you can stop and look
at the results before moving on:

| Stage | Script | Produces |
| --- | --- | --- |
| 1. Look at the data | `scripts/inspect_data.py` | A printed profile of every layer found |
| 2. Present it | `scripts/make_maps.py` | PNG + interactive HTML maps in `output/` |
| 3. Open in QGIS | `scripts/export_qgis.py` | A GeoPackage and a ready-to-open `.qgs` project |

All three read the same source — whatever is sitting in `data/raw` — through a
shared loader (`scripts/dataio.py`), so they always agree on what the data is.

## Setup

```bash
pip install -r requirements.txt
```

## Where the data goes

Copy your zip archives into **`data/raw/`**. Nothing else is needed — the
scripts unpack them for you into `data/processed/extracted/` (git-ignored, and
safe to delete at any time; re-run with `--refresh` to rebuild it).

Zips are the expected input, and they can contain anything readable:
shapefiles, GeoJSON, GeoPackages, KML, CSVs with coordinate columns, or more
zips nested inside. Loose unzipped files in `data/raw` are picked up too.
See `data/raw/README.md` for the full format list and the coordinate-column
naming rules.

## Running it

```bash
# 1. What have we actually got?
python scripts/inspect_data.py
python scripts/inspect_data.py --report output/data_profile.md

# 2. Draw it
python scripts/make_maps.py
python scripts/make_maps.py --colour-by status     # shade the PNGs by a column

# 3. Hand it to QGIS
python scripts/export_qgis.py
```

Then open **`data/processed/mca_maps.qgs`**.

### Useful flags

These work on all three scripts:

| Flag | Effect |
| --- | --- |
| `--only <text>` | Restrict to sources whose path contains this text |
| `--refresh` | Re-extract archives instead of reusing the unpacked cache |
| `--lat-col` / `--lon-col` | Name the coordinate columns when auto-detection misses |
| `--crs EPSG:27700` | CRS to assume for data that declares none |
| `--raw-dir` | Read from somewhere other than `data/raw` |

## QGIS

Targets **QGIS 3.28 LTR (Firenze)**, and the project format is
forward-compatible with newer releases.

`export_qgis.py` writes two files into `data/processed/`:

- **`mca_maps.gpkg`** — one GeoPackage holding every layer. A single portable
  file, and the format QGIS is happiest with.
- **`mca_maps.qgs`** — a project that loads those layers already styled by
  geometry type, adds an OpenStreetMap basemap, and opens zoomed to the extent
  of your data.

The project points at the GeoPackage by a *relative* path, so you can move or
copy the `data/processed` folder anywhere as long as the two files stay
together.

Everything is reprojected to EPSG:4326 on the way in. If your source data is in
a national grid it will be converted, and the original CRS is reported by
`inspect_data.py` so you can check the conversion looks right.

To restyle: change symbology in QGIS and save the project — your version wins
until you re-run the export, which overwrites it. If you have styling worth
keeping, save it as a `.qml` alongside, or save the project under a new name.

## Layout

```
data/raw/                    ← your zip archives go here (committed)
data/processed/extracted/    ← unpacked archives (git-ignored, regenerated)
data/processed/mca_maps.gpkg ← all layers, one GeoPackage (git-ignored)
data/processed/mca_maps.qgs  ← QGIS project
output/                      ← rendered PNG and HTML maps (git-ignored)
scripts/dataio.py            ← shared unpack + load layer
```

Derived outputs are git-ignored on purpose: they are all reproducible from
`data/raw` by re-running the scripts, so only the raw inputs are worth
committing.

> **Note on file sizes:** GitHub rejects files over 100 MB and warns above
> 50 MB. If your archives are larger than that, keep them outside the repo and
> point the scripts at them with `--raw-dir /path/to/archives`.
