# MCA Maps

Clan land boundary surveys from Oro Province, Papua New Guinea — turned into
maps you can look at, share, and open in QGIS.

The current data is **69 GPS surveys across 6 zones, 601 raw tracks, 1,327 km**,
recorded July–August 2026 and supplied as one zip per zone.

The workflow runs in stages, each a separate script so you can stop and look
at the results before moving on:

| Stage | Script | Produces |
| --- | --- | --- |
| 1. Look at the data | `scripts/inspect_data.py` | Layer profiles, cross-zone summary, quality checks |
| 2. Clip and smooth | `scripts/smooth_tracks.py` | Clipped, resampled tracks in `data/smoothed/` |
| 3. Present it | `scripts/make_maps.py` | PNG + interactive HTML maps in `output/` |
| 4. Open in QGIS | `scripts/export_qgis.py` | A GeoPackage and a ready-to-open `.qgs` project |
| 5. Closure | `scripts/closure.py` | Which boundaries close into polygons |
| 6. Areas & overlaps | `scripts/polygons.py` | Mapped-area polygons, clan overlaps, and the straight lines nobody walked |
| 7. Sacred sites | `scripts/sacred_sites.py` | Site areas and share of clan land |
| 8. Field queries | `scripts/queries.py` | Query pack with a map per question |
| 9. Per-clan maps | `scripts/clan_maps.py` | One map per clan, with neighbours and overlaps |
| 10. Steward days | `scripts/stewards.py` | Who walked, on which days, how far |
| 11. Working project | `scripts/build_project.py` | The QGIS project to open and look at |
| 12. Provenance | `scripts/provenance.py` | Versions, checksums and citations for every run |
| 13. Give it back | `scripts/clan_gpx.py` | One GPX per clan, gaps marked, for the stewards |
| 14. Documents | `scripts/build_reports.py` | The two Word documents, versioned and dated |

All stages read the same source — the zips in `data/raw` — through a shared
loader (`scripts/dataio.py`), so they always agree on what the data is.

## Setup

```bash
pip install -r requirements.txt
```

## Running it

Run everything, with an audit that no data was lost:

```bash
python scripts/fetch_dem.py        # once — Copernicus 30 m terrain
python scripts/run_pipeline.py
```

Or a stage at a time:

```bash
python scripts/inspect_data.py --summary     # what have we got?
python scripts/smooth_tracks.py              # clip to the MCA, smooth the bounce
python scripts/make_maps.py --smoothed       # draw the smoothed tracks
python scripts/export_qgis.py --smoothed --with-boundary \
    --gpkg data/smoothed/mca_smoothed_qgis.gpkg
python scripts/closure.py --report output/closure_report.md
python scripts/polygons.py --report output/polygon_report.md \
    --map output/areas_mapped.png
```

Then open **`data/smoothed/mca_smoothed_qgis.qgs`**. Methods, results and open
questions are documented in **`docs/METHODS.md`**; questions for the field team
are generated into **`output/queries/`**. Drop `--smoothed` from any
of these to work from the raw archives instead.

## The documents

```bash
python scripts/build_reports.py
```

Two Word documents, both built from `output/report/*.json` and nothing else,
so text and maps always come from the same run:

- **`Managalas_Clan_Land_Mapping_v<version>_<date>.docx`** — results, then a
  page per clan with its own map, its problems and its queries.
- **`Managalas_Steward_Days_v<version>_<date>.docx`** — who walked, on which
  days, and how far.

The version comes from `docs/VERSION`; bump it when the content changes
materially. Version and date appear in the file name, on the title page and in
the footer of every page, and **earlier builds are never overwritten** — the
copy already in someone's inbox stays valid and findable.

## Giving the survey back

```bash
python scripts/clan_gpx.py
```

One GPX per clan in `output/gpx/`, for the Clan Stewards who walked it to load
onto the phone or handheld they mapped with. Each file holds:

- **their own tracks**, one per steward and named for them;
- **the gaps**, as straight lines named `GAP 3 OF 8 - NOT WALKED - 2.31 km`,
  so a gap shows up as something on the screen rather than as an absence;
- **a waypoint at each end of each gap** — the useful part, since a steward
  can navigate straight to where the walking stopped and carry on.

Gaps under 100 m (`--min-gap`) are not marked: two ends that close are the
same place to anyone standing there, and flagging them buries the ones that
matter.

## The straight lines on the maps

Where a boundary was walked in several pieces — the receiver switched off at
the end of one day and on again somewhere else — the pieces are joined with
straight lines so an area can be given at all. **Those lines are not
boundary.** They are drawn in pink on every map, written as their own
`inferred_bridges` layer rather than merged into the boundary, excluded from
every distance total, and reported per clan as "not walked".

Which end of each piece the ring enters by matters: take one the wrong way
round and the joining lines cross, enclosing two slivers instead of one block.
`closure.order_chains` orders and orients the pieces to make the joining as
short as possible, which leaves no crossings — see `docs/METHODS.md` §4.8.

## Where the data goes

Copy zip archives into **`data/raw/`** — the scripts unpack them into
`data/processed/extracted/` (git-ignored, safe to delete, rebuilt with
`--refresh`). Archives can hold shapefiles, GeoPackages, GeoJSON, KML, CSVs
with coordinate columns, or further nested zips. See `data/raw/README.md` for
the format details.

## What the scripts do with these files

**The zone, clan and steward live in the file names, not in the data.**
`scripts/clans.py` reads them, handling both conventions in use:

```
Jethro_Akse_Asingi_Clan_Land_Boundary_Zone_2_14July2026
└─ steward ─┘ └clan┘                  └zone┘ └─ date ─┘

manuvoora_clan_egobeyas_kuarisi_tracks_zone_6
└─ clan ─┘     └─── steward ────┘     └zone┘
```

Files that omit the zone inherit it from the archive they came in. The parsed
values become attributes — `clan`, `steward`, `zone`, `feature_type`,
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

## Terrain

`scripts/fetch_dem.py` pulls the Copernicus GLO-30 DEM from AWS S3 (open data,
no credentials) and crops it to the data extent using HTTP range requests, so
only the needed window transfers. It writes `mca_dem.tif` and a derived
`mca_hillshade.tif` into `data/reference/dem/`, both git-ignored and rebuilt on
demand.

Terrain then backs the static maps, the query maps and the QGIS project. Nothing
depends on it — without the DEM the maps just draw without it. Re-fetch with
`python scripts/run_pipeline.py --fetch-dem` when new surveys extend beyond the
area already covered.

## Clipping and smoothing

`smooth_tracks.py` never touches `data/raw`. It reads the archives, and writes
a separate `data/smoothed/mca_tracks_smoothed.gpkg`. Three steps, in order:

1. **Clip** — drop track parts more than 10 km from the MCA boundary
   (`--max-distance-km`). Distance is measured to the conservation *area*, so
   anything inside it is zero away; only genuinely outside data goes.
2. **Resample** — one point every 20 m (`--spacing`), so every track is
   described at the same resolution regardless of how fast the surveyor walked.
3. **Smooth** — a 3-point moving average (`--window`, or `--no-smooth`) to take
   out the remaining GPS jitter. Track endpoints are held in place, because
   they are exactly what the closure analysis measures.

All lengths are computed in **EPSG:32755** (UTM zone 55S). Web Mercator would
overstate distances here by about 1.2%.

The MCA boundary itself lives in `data/reference/mca_boundary.kml` — the WDPA
Managalas Conservation Area polygon, 213,269 ha.

## Closure

`closure.py` asks whether each survey's tracks ring the land. Closure is judged
per survey, not per track, since a boundary is walked in several sessions.

Track ends within 25 m (`--tolerance`) are treated as joined, then the tracks
are **polygonized**: a boundary counts as closed when the polygon it encloses
has a perimeter of at least half the distance walked (`--min-enclosure`). This
is a geometric test on purpose — walking a line out and back makes a loop in a
connectivity graph but encloses nothing.

For the rest, the **gap to close** is the straight-line distance still needed to
join the pieces into one ring. For a survey recorded in one piece that is
exactly the distance between its two open ends; for one recorded in several
pieces, every join counts. Under 10% of the distance walked (`--threshold`)
counts as near closure.

Because the answer moves with the joining tolerance, the report always prints
the totals at 10 m, 25 m, 50 m and 100 m.

## Mapped areas and overlaps

`polygons.py` turns the walks into areas, keeping two kinds strictly apart:

- **Surveyed** — the tracks already ring the land, so the polygon is exactly
  what was walked.
- **Inferred** — the tracks stop short, the open ends are bridged with straight
  lines, and the result is an *estimate*. Every one carries `gap_pct`, the share
  of the perimeter that was bridged rather than walked. Anything bridged across
  more than half its walk (`--max-gap`) is dropped as too speculative.

The distinction lives in a `basis` column so it survives into QGIS, and
`--surveyed-only` restricts everything to polygons that were actually walked.
An inferred polygon is a working estimate of area mapped — not a boundary
anyone has agreed.

Overlaps are reported pairwise, as shared area and as a share of each clan's own
polygon, in hectares. Two uses: finding where clans genuinely contest ground, and confirming
whether two similar clan names are one clan recorded twice.

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

Shared by the loading scripts:

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
data/raw/                    ← zip archives, never edited (committed)
data/reference/              ← MCA boundary KML (committed)
data/smoothed/               ← clipped + smoothed output (git-ignored)
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
