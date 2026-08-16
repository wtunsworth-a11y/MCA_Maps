# MCA Maps

Clan land boundary surveys from Oro Province, Papua New Guinea — turned into
maps you can look at, share, and open in QGIS.

The current data is **69 GPS surveys across 6 zones, 601 tracks, ~1,349 km**,
recorded July–August 2026 and supplied as one zip per zone.

The workflow has three stages, each a separate script so you can stop and look
at the results before moving on:

| Stage | Script | Produces |
| --- | --- | --- |
| 1. Look at the data | `scripts/inspect_data.py` | Layer profiles, cross-zone summary, quality checks |
| 2. Present it | `scripts/make_maps.py` | PNG + interactive HTML maps in `output/` |
| 3. Open in QGIS | `scripts/export_qgis.py` | A GeoPackage and a ready-to-open `.qgs` project |

All three read the same source — the zips in `data/raw` — through a shared
loader (`scripts/dataio.py`), so they always agree on what the data is.

## Setup

```bash
pip install -r requirements.txt
```

## Running it

```bash
python scripts/inspect_data.py --summary     # what have we got?
python scripts/make_maps.py                  # draw it
python scripts/export_qgis.py                # hand it to QGIS
```

Then open **`data/processed/mca_maps.qgs`**.

## Where the data goes

Copy zip archives into **`data/raw/`** — the scripts unpack them into
`data/processed/extracted/` (git-ignored, safe to delete, rebuilt with
`--refresh`). Archives can hold shapefiles, GeoPackages, GeoJSON, KML, CSVs
with coordinate columns, or further nested zips. See `data/raw/README.md` for
the format details.

## What the scripts do with these files

**The zone, clan and custodian live in the file names, not in the data.**
`scripts/clans.py` reads them, handling both conventions in use:

```
Jethro_Akse_Asingi_Clan_Land_Boundary_Zone_2_14July2026
└─ custodian ─┘ └clan┘                  └zone┘ └─ date ─┘

manuvoora_clan_egobeyas_kuarisi_tracks_zone_6
└─ clan ─┘     └─── custodian ────┘     └zone┘
```

Files that omit the zone inherit it from the archive they came in. The parsed
values become attributes — `clan`, `custodian`, `zone`, `feature_type`,
`survey_date`, `source_name` — on every feature.

**69 layers are merged into one.** Separate layers per file are unusable in
QGIS; a single `clan_boundaries` layer carrying those attributes can be
categorised, filtered and queried instead. Per-zone layers are written
alongside it. Use `--separate` to keep one layer per source file, or
`--group-by clan` to split by clan instead of zone.

**Broken geometry is repaired, not skipped.** These are GPS track exports and
31 of the 69 files contain track parts with a single recorded point, which GEOS
rejects — taking the whole file down with it. `scripts/geomfix.py` rewrites the
WKB without those parts, copying every surviving part byte-for-byte, so a
boundary is never lost over two stray points. Parts logged while the receiver
sat still (every point identical) are dropped the same way. Every repair is
reported as it happens.

## QGIS

Targets **QGIS 3.28 LTR (Firenze)**; the project format is forward-compatible
with newer releases.

`export_qgis.py` writes two files into `data/processed/`:

- **`mca_maps.gpkg`** — the merged layer plus one layer per zone.
- **`mca_maps.qgs`** — a project that opens with `clan_boundaries` shown and
  coloured by zone, an OpenStreetMap basemap beneath it, a collapsed **By
  zone** group holding each zone separately, and the canvas zoomed to the data.

Zone colours are consistent between the merged layer and the per-zone layers,
so toggling between them doesn't change what a zone looks like.

The project points at the GeoPackage by a *relative* path, so `data/processed`
can be moved or copied anywhere as long as the two files travel together.

Everything is reprojected to EPSG:4326 on the way in (this data is already in
it). To restyle, change symbology in QGIS and save — your version wins until
the next export overwrites it, so save under a new name if it's worth keeping.

## Useful flags

Shared by all three scripts:

| Flag | Effect |
| --- | --- |
| `--only <text>` | Restrict to sources whose path contains this text |
| `--refresh` | Re-extract archives instead of reusing the unpacked cache |
| `--group-by <col>` | Split and colour by a different attribute (default `zone`) |
| `--separate` | One layer per source file, no merge |
| `--lat-col` / `--lon-col` | Name coordinate columns when auto-detection misses |
| `--crs EPSG:27700` | CRS to assume for data that declares none |
| `--raw-dir` | Read from somewhere other than `data/raw` |

`inspect_data.py` also takes `--summary` (skip the per-layer detail),
`--report FILE` (write markdown) and `--outlier-factor`.

## Layout

```
data/raw/                    ← zip archives (committed)
data/processed/extracted/    ← unpacked archives (git-ignored, regenerated)
data/processed/mca_maps.gpkg ← merged + per-zone layers (git-ignored)
data/processed/mca_maps.qgs  ← QGIS project
output/                      ← rendered maps and data_profile.md (git-ignored)
scripts/dataio.py            ← shared unpack + load + merge
scripts/clans.py             ← file-name conventions
scripts/geomfix.py           ← WKB geometry repair
```

Derived outputs are git-ignored because they are all reproducible from
`data/raw` by re-running the scripts.

> **File sizes:** GitHub rejects files over 100 MB and warns above 50 MB. For
> archives larger than that, keep them outside the repo and point the scripts
> at them with `--raw-dir /path/to/archives`.
