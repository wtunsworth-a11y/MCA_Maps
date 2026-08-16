# Raw data

Drop source data files here, exactly as you received them. Nothing in this
folder should ever be edited by a script — treat it as read-only input.

## Supported formats

`scripts/make_maps.py` picks up these automatically:

| Format | Extensions | Notes |
| --- | --- | --- |
| Delimited text | `.csv`, `.tsv` | Needs latitude/longitude columns (see below) |
| GeoJSON | `.geojson`, `.json` | Any geometry type |
| Shapefile | `.shp` | Keep the sidecar files (`.dbf`, `.shx`, `.prj`) alongside it |
| GeoPackage | `.gpkg` | First layer is used unless one is named |
| KML | `.kml` | |
| Zipped vector | `.zip` | A zipped shapefile directory works as-is |

## Point data in CSV/TSV

Latitude and longitude columns are detected case-insensitively from these
names, so you usually don't need to rename anything:

- latitude: `lat`, `latitude`, `y`, `lat_dd`, `ycoord`
- longitude: `lon`, `long`, `lng`, `longitude`, `x`, `lon_dd`, `xcoord`

If your columns are named something else, pass them explicitly:

```bash
python scripts/make_maps.py --lat-col SiteLat --lon-col SiteLon
```

## Coordinate reference system

Files carrying their own CRS (shapefile `.prj`, GeoPackage, most GeoJSON) are
reprojected automatically. Bare CSV coordinates are assumed to be WGS84
(EPSG:4326) — override with `--crs EPSG:27700` or similar if they aren't.

## Subfolders

Subfolders are fine and are scanned recursively. Organising by source or by
date (`data/raw/2026-08-survey/`) keeps things tidy as the project grows.
