"""Shared loading layer: unpack the raw zips and read whatever is inside.

Every script in this repo goes through here, so the three stages of the
workflow — inspect, present, export to QGIS — always see exactly the same
set of layers.
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import pandas as pd

import geomfix

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
CACHE_DIR = REPO_ROOT / "data" / "processed" / "extracted"
OUT_DIR = REPO_ROOT / "output"
GPKG_PATH = REPO_ROOT / "data" / "processed" / "mca_maps.gpkg"

VECTOR_SUFFIXES = {".shp", ".geojson", ".gpkg", ".kml", ".gml", ".gpx", ".fgb",
                   ".tab", ".mif"}
TABLE_SUFFIXES = {".csv", ".tsv", ".txt"}
# .json is ambiguous — probed as GeoJSON, skipped quietly if it isn't spatial.
PROBE_SUFFIXES = {".json"}

LAT_NAMES = ("lat", "latitude", "y", "lat_dd", "ycoord", "y_coord", "northing")
LON_NAMES = ("lon", "long", "lng", "longitude", "x", "lon_dd", "xcoord",
             "x_coord", "easting")

WGS84 = "EPSG:4326"
WEB_MERCATOR = "EPSG:3857"
# UTM zone 55S covers 144–150°E, which holds all of this survey area. Web
# Mercator would overstate distances by ~1.2% at this latitude, so every
# length, spacing and buffer in metres is measured here instead.
METRIC_CRS = "EPSG:32755"

REFERENCE_DIR = REPO_ROOT / "data" / "reference"
SMOOTHED_DIR = REPO_ROOT / "data" / "smoothed"
MCA_BOUNDARY = REFERENCE_DIR / "mca_boundary.kml"


@dataclass
class Layer:
    """One renderable table of geometries, plus where it came from."""

    name: str
    gdf: gpd.GeoDataFrame
    source: Path
    source_crs: str | None = None

    @property
    def geom_types(self) -> list[str]:
        return sorted(set(self.gdf.geom_type.dropna()))

    @property
    def qgis_geometry(self) -> str:
        """The geometry family QGIS needs for its renderer."""
        joined = " ".join(self.geom_types)
        if "Polygon" in joined:
            return "Polygon"
        if "Line" in joined:
            return "Line"
        return "Point"


# --------------------------------------------------------------------------
# Unpacking
# --------------------------------------------------------------------------

def unpack_archives(raw_dir: Path = RAW_DIR, cache_dir: Path = CACHE_DIR,
                    refresh: bool = False, quiet: bool = False) -> list[Path]:
    """Extract every zip under raw_dir into cache_dir, one folder per archive.

    Nested zips are unwrapped too, since export tools often bundle a set of
    per-region archives inside a single download. Returns the directories now
    holding extracted content.
    """
    archives = sorted(p for p in raw_dir.rglob("*.zip") if p.is_file())
    extracted: list[Path] = []

    for archive in archives:
        target = cache_dir / archive.relative_to(raw_dir).with_suffix("")
        if target.exists() and refresh:
            shutil.rmtree(target)
        if not target.exists():
            target.mkdir(parents=True, exist_ok=True)
            try:
                with zipfile.ZipFile(archive) as zf:
                    _safe_extract(zf, target)
            except (zipfile.BadZipFile, ValueError) as exc:
                _say(quiet, f"  ! {archive.name}: {exc or 'unreadable zip'}")
                shutil.rmtree(target, ignore_errors=True)
                continue
            _say(quiet, f"  extracted {archive.relative_to(raw_dir)}")
        else:
            _say(quiet, f"  cached    {archive.relative_to(raw_dir)}")
        extracted.append(target)

        for inner in sorted(target.rglob("*.zip")):
            inner_target = inner.with_suffix("")
            if inner_target.exists():
                continue
            inner_target.mkdir(parents=True, exist_ok=True)
            try:
                with zipfile.ZipFile(inner) as zf:
                    _safe_extract(zf, inner_target)
                _say(quiet, f"  extracted {inner.name} (nested)")
            except (zipfile.BadZipFile, ValueError):
                shutil.rmtree(inner_target, ignore_errors=True)

    return extracted


def _safe_extract(zf: zipfile.ZipFile, target: Path) -> None:
    """Extract without letting archive entries escape the target directory."""
    root = target.resolve()
    for member in zf.infolist():
        dest = (root / member.filename).resolve()
        if not str(dest).startswith(str(root)):
            raise ValueError(f"unsafe path in archive: {member.filename}")
    zf.extractall(root)


def _say(quiet: bool, message: str) -> None:
    if not quiet:
        print(message)


# --------------------------------------------------------------------------
# Discovery and loading
# --------------------------------------------------------------------------

def find_sources(search_dirs: list[Path]) -> list[Path]:
    """Collect every candidate data file, skipping extraction cruft."""
    found: list[Path] = []
    seen: set[Path] = set()
    for directory in search_dirs:
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path in seen:
                continue
            if any(part in {"__MACOSX", ".git"} for part in path.parts):
                continue
            if path.name.startswith("."):
                continue
            if path.suffix.lower() in VECTOR_SUFFIXES | TABLE_SUFFIXES | PROBE_SUFFIXES:
                found.append(path)
                seen.add(path)
    return found


def load_layer(path: Path, lat_col: str | None = None, lon_col: str | None = None,
               assume_crs: str = WGS84, to_crs: str = WGS84) -> Layer | None:
    """Read one file into a Layer, or return None if it holds no geometry."""
    suffix = path.suffix.lower()

    if suffix in TABLE_SUFFIXES:
        gdf = _load_table(path, lat_col, lon_col, assume_crs)
    elif suffix in PROBE_SUFFIXES:
        try:
            gdf = gpd.read_file(path)
        except Exception:
            return None  # a plain JSON sidecar, not GeoJSON
    else:
        try:
            gdf = gpd.read_file(path)
        except Exception as exc:
            # GPS exports often carry single-point track segments, which GEOS
            # rejects outright — taking the whole file down with them. Rebuild
            # the geometries without those parts rather than lose the file.
            gdf = _read_repaired(path, exc)
            if gdf is None:
                raise

    if gdf is None or gdf.empty or "geometry" not in gdf:
        return None

    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    if gdf.empty:
        return None

    gdf = _repair_invalid(gdf, path)

    source_crs = str(gdf.crs) if gdf.crs is not None else None
    if gdf.crs is None:
        gdf = gdf.set_crs(assume_crs)
        source_crs = f"{assume_crs} (assumed)"
    gdf = gdf.to_crs(to_crs)

    return Layer(name=safe_name(path.stem), gdf=gdf, source=path,
                 source_crs=source_crs)


def load_all(raw_dir: Path = RAW_DIR, cache_dir: Path = CACHE_DIR,
             only: str | None = None, refresh: bool = False,
             lat_col: str | None = None, lon_col: str | None = None,
             assume_crs: str = WGS84, quiet: bool = False) -> list[Layer]:
    """Unpack, discover and read everything under raw_dir in one call."""
    _say(quiet, f"Reading archives from {raw_dir}")
    search_dirs = unpack_archives(raw_dir, cache_dir, refresh, quiet)
    search_dirs.append(raw_dir)  # loose, unzipped files are welcome too

    sources = find_sources(search_dirs)
    if only:
        sources = [p for p in sources if only.lower() in str(p).lower()]
    if not sources:
        return []

    _say(quiet, f"\nFound {len(sources)} candidate file(s)")
    layers: list[Layer] = []
    used: set[str] = set()
    for path in sources:
        try:
            layer = load_layer(path, lat_col, lon_col, assume_crs)
        except Exception as exc:
            _say(quiet, f"  ! {path.name}: {exc}")
            continue
        if layer is None:
            continue
        layer.name = _unique(layer.name, used)
        layers.append(layer)
        _say(quiet, f"  + {layer.name}: {len(layer.gdf):,} features "
                    f"({', '.join(layer.geom_types)})")
    return layers


def _repair_invalid(gdf: gpd.GeoDataFrame, path: Path) -> gpd.GeoDataFrame:
    """Strip degenerate parts from geometries that loaded but are invalid.

    A track part with no points is legal enough for GEOS to construct but
    leaves the feature invalid, which quietly breaks buffers and overlays
    later. Only replacements that actually come back valid are kept, so a
    genuinely self-intersecting polygon is left alone for a human to judge.
    """
    try:
        invalid = ~gdf.geometry.is_valid
    except Exception:
        return gdf
    if not invalid.any():
        return gdf

    import shapely

    fixed_count = 0
    geometries = gdf.geometry.copy()
    for position in gdf.index[invalid]:
        geometry = geometries.loc[position]
        rebuilt = None
        try:
            candidate, removed = geomfix.repair(shapely.to_wkb(geometry))
            if candidate is not None and removed:
                rebuilt = shapely.from_wkb(candidate)
        except Exception:
            rebuilt = None
        if rebuilt is None or not rebuilt.is_valid:
            rebuilt = _drop_stationary_parts(geometry)
        if rebuilt is not None and rebuilt.is_valid and not rebuilt.is_empty:
            geometries.loc[position] = rebuilt
            fixed_count += 1

    if fixed_count:
        print(f"  ~ {path.name}: repaired {fixed_count} invalid geometry(ies) "
              "by dropping parts that record no line")
        gdf = gdf.set_geometry(geometries)
    return gdf


def _drop_stationary_parts(geometry):
    """Remove track parts that never moved.

    A receiver left running in one spot logs many points at a single
    coordinate. Structurally that part is a fine LineString, but every point
    is the same, so GEOS reduces it to under two distinct vertices and calls
    the whole feature invalid. The part records no line, so dropping it loses
    nothing. Comparison is on X/Y only, matching how GEOS judges validity.
    """
    parts = getattr(geometry, "geoms", None)
    if parts is None:
        return None

    kept = [part for part in parts if _has_extent(part)]
    if not kept or len(kept) == len(geometry.geoms):
        return None
    try:
        return type(geometry)(kept)
    except Exception:
        return None


def _has_extent(part) -> bool:
    coordinates = getattr(part, "coords", None)
    if coordinates is None:
        return not part.is_empty
    return len({(x, y) for x, y, *_ in coordinates}) >= 2


def _read_repaired(path: Path, original: Exception) -> gpd.GeoDataFrame | None:
    """Re-read a file that GEOS refused, dropping only the illegal parts.

    Falls back to None if the failure was something other than bad geometry,
    so the caller can re-raise the original error.
    """
    try:
        import shapely
        from pyogrio.raw import read as raw_read

        meta, _index, geometries, field_data = raw_read(str(path))
    except Exception:
        return None

    repaired: list = []
    dropped_parts = 0
    dropped_features = 0

    for blob in geometries:
        if blob is None:
            repaired.append(None)
            continue
        raw = bytes(blob)
        try:
            repaired.append(shapely.from_wkb(raw))
            continue
        except Exception:
            pass
        try:
            fixed, removed = geomfix.repair(raw)
        except geomfix.WkbError:
            repaired.append(None)
            dropped_features += 1
            continue
        dropped_parts += removed
        if fixed is None:
            repaired.append(None)
            dropped_features += 1
            continue
        try:
            repaired.append(shapely.from_wkb(fixed))
        except Exception:
            repaired.append(None)
            dropped_features += 1

    if all(geom is None for geom in repaired):
        return None  # not a geometry problem we can solve

    note = f"  ~ {path.name}: repaired — dropped {dropped_parts} single-point part(s)"
    if dropped_features:
        note += f", {dropped_features} feature(s) unrecoverable"
    print(note)

    frame = pd.DataFrame(dict(zip(meta["fields"], field_data)))
    return gpd.GeoDataFrame(frame, geometry=repaired, crs=meta["crs"])


def _load_table(path: Path, lat_col: str | None, lon_col: str | None,
                assume_crs: str) -> gpd.GeoDataFrame | None:
    """Turn a delimited text file into points using its lat/lon columns.

    Reasons for skipping are printed rather than swallowed — a CSV that
    quietly vanishes from the output is far worse than a noisy one.
    """
    df = _read_table(path)
    if df is None or df.empty:
        return None

    lat_col = lat_col or _match_column(df.columns, LAT_NAMES)
    lon_col = lon_col or _match_column(df.columns, LON_NAMES)
    if not lat_col or not lon_col or lat_col not in df or lon_col not in df:
        print(f"  - {path.name}: no latitude/longitude columns found "
              f"(has: {', '.join(map(str, df.columns[:8]))}) — "
              "pass --lat-col/--lon-col to map it")
        return None

    lat = pd.to_numeric(df[lat_col], errors="coerce")
    lon = pd.to_numeric(df[lon_col], errors="coerce")
    keep = lat.notna() & lon.notna()
    if not keep.any():
        print(f"  - {path.name}: '{lat_col}'/'{lon_col}' hold no usable numbers")
        return None
    if (dropped := int((~keep).sum())):
        print(f"  - {path.name}: dropped {dropped:,} row(s) without coordinates")

    return gpd.GeoDataFrame(
        df[keep].reset_index(drop=True),
        geometry=gpd.points_from_xy(lon[keep], lat[keep]),
        crs=assume_crs,
    )


def _read_table(path: Path) -> pd.DataFrame | None:
    """Read a delimited file, sniffing its separator and encoding."""
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            sep = _sniff_separator(path, encoding)
        except (UnicodeDecodeError, OSError):
            continue
        if sep is None:
            return None  # empty file
        try:
            return pd.read_csv(path, sep=sep, encoding=encoding,
                               low_memory=False)
        except UnicodeDecodeError:
            continue
        except Exception as exc:
            print(f"  ! {path.name}: could not be parsed ({exc})")
            return None
    print(f"  ! {path.name}: no supported text encoding")
    return None


def _sniff_separator(path: Path, encoding: str) -> str | None:
    """Detect the delimiter from a sample; .tsv is taken at its word."""
    if path.suffix.lower() == ".tsv":
        return "\t"
    with path.open("r", encoding=encoding, newline="") as handle:
        sample = handle.read(64 * 1024)
    if not sample.strip():
        return None
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def _match_column(columns, candidates: tuple[str, ...]) -> str | None:
    lookup = {str(c).strip().lower(): c for c in columns}
    for candidate in candidates:
        if candidate in lookup:
            return lookup[candidate]
    return None


def safe_name(name: str) -> str:
    """A layer name that is safe for GeoPackage tables and file names."""
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", name).strip("_")
    if not cleaned:
        cleaned = "layer"
    if cleaned[0].isdigit():
        cleaned = f"l_{cleaned}"
    return cleaned[:60]


def _unique(name: str, used: set[str]) -> str:
    candidate, suffix = name, 2
    while candidate in used:
        candidate = f"{name}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def load_boundary(path: Path = MCA_BOUNDARY):
    """Load the MCA reference boundary as a single metric-CRS geometry."""
    if not path.exists():
        return None
    boundary = gpd.read_file(path).to_crs(METRIC_CRS)
    return boundary.geometry.union_all()


def load_prepared(gpkg_path: Path, layer_name: str) -> Layer | None:
    """Read back a layer this pipeline already wrote, attributes and all.

    Used for the smoothed output: its zone/clan/custodian columns are already
    present, so it must skip the file-name parsing that raw sources go through.
    """
    if not gpkg_path.exists():
        return None
    gdf = gpd.read_file(gpkg_path, layer=layer_name)
    if gdf.empty:
        return None
    if gdf.crs is None:
        gdf = gdf.set_crs(WGS84)
    return Layer(name=layer_name, gdf=gdf.to_crs(WGS84), source=gpkg_path,
                 source_crs=str(gdf.crs))


def combine(layers: list[Layer], name: str = "clan_boundaries") -> Layer | None:
    """Merge every layer into one, tagged with what its file name encodes.

    69 near-identical layers are unusable in QGIS; one layer carrying zone,
    clan and custodian as attributes can be categorised and filtered instead.
    The original per-file identity survives in the `source_name` column.
    """
    import clans

    if not layers:
        return None

    frames = []
    for layer in layers:
        gdf = layer.gdf.copy()
        # Parse the file's own stem, not layer.name — the latter is truncated
        # to fit GeoPackage table limits, which can cut a trailing date in half
        # and leave the fragment looking like part of somebody's name.
        stem = layer.source.stem if layer.source.suffix else layer.name
        record = clans.parse(stem or layer.name, layer.source)
        # Provenance first, so it reads left-to-right in the attribute table.
        for column, value in reversed(record.as_dict().items()):
            gdf.insert(0, column, value)
        frames.append(gdf)

    merged = pd.concat(frames, ignore_index=True)
    merged = gpd.GeoDataFrame(merged, geometry="geometry", crs=layers[0].gdf.crs)

    merged = _merge_case_variants(merged)

    # The sources carry different schemas, so the union has columns that are
    # empty for every row. They only clutter the QGIS attribute table.
    empty = [c for c in merged.columns
             if c != "geometry" and merged[c].isna().all()]
    if empty:
        merged = merged.drop(columns=empty)
        print(f"  dropped {len(empty)} empty column(s) from the merge")

    return Layer(name=name, gdf=merged, source=layers[0].source.parent,
                 source_crs=layers[0].source_crs)


def _merge_case_variants(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Reconcile columns that differ only in case, e.g. `name` and `Name`.

    GeoPackage field names are case-insensitive, so these collide on write.
    Where the variants never both hold a value for the same row they are the
    same field arriving from two source schemas (GPX vs KML here), and are
    coalesced. Where they genuinely overlap, the extras are suffixed instead,
    because merging would silently discard one of two real values.
    """
    groups: dict[str, list[str]] = {}
    for column in gdf.columns:
        if column != "geometry":
            groups.setdefault(column.lower(), []).append(column)

    for variants in groups.values():
        if len(variants) < 2:
            continue
        keep, extras = variants[0], variants[1:]
        overlapping = (gdf[variants].notna().sum(axis=1) > 1).any()
        if overlapping:
            for index, column in enumerate(extras, start=2):
                gdf = gdf.rename(columns={column: f"{column}_{index}"})
            print(f"  kept {len(variants)} overlapping variants of "
                  f"'{keep}' under suffixed names")
            continue
        for column in extras:
            gdf[keep] = gdf[keep].where(gdf[keep].notna(), gdf[column])
        gdf = gdf.drop(columns=extras)
        print(f"  merged {', '.join(extras)} into '{keep}' "
              "(same field, different source schemas)")
    return gdf


def split_by(layer: Layer, column: str) -> list[Layer]:
    """Break one layer into several, one per distinct value of a column."""
    if column not in layer.gdf.columns:
        return [layer]
    out: list[Layer] = []
    for value, group in layer.gdf.groupby(column, sort=True):
        label = safe_name(str(value)) or "unknown"
        out.append(Layer(name=label, gdf=group.reset_index(drop=True),
                         source=layer.source, source_crs=layer.source_crs))
    return out


def combined_bounds(layers: list[Layer]) -> tuple[float, float, float, float]:
    """The extent covering every layer, padded if it collapses to a point."""
    boxes = [layer.gdf.total_bounds for layer in layers]
    minx = min(b[0] for b in boxes)
    miny = min(b[1] for b in boxes)
    maxx = max(b[2] for b in boxes)
    maxy = max(b[3] for b in boxes)
    if minx == maxx:
        minx, maxx = minx - 0.05, maxx + 0.05
    if miny == maxy:
        miny, maxy = miny - 0.05, maxy + 0.05
    return minx, miny, maxx, maxy


def add_common_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """The input-selection flags every script in this repo shares."""
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR,
                        help="folder holding the zipped source data")
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR,
                        help="where archives are unpacked")
    parser.add_argument("--only", default=None,
                        help="only process sources whose path contains this text")
    parser.add_argument("--lat-col", default=None, help="latitude column override")
    parser.add_argument("--lon-col", default=None, help="longitude column override")
    parser.add_argument("--crs", default=WGS84,
                        help="CRS to assume for data that declares none")
    parser.add_argument("--refresh", action="store_true",
                        help="re-extract archives instead of reusing the cache")
    return parser


def load_from_args(args: argparse.Namespace) -> list[Layer]:
    return load_all(raw_dir=args.raw_dir, cache_dir=args.cache_dir,
                    only=args.only, refresh=args.refresh,
                    lat_col=args.lat_col, lon_col=args.lon_col,
                    assume_crs=args.crs)
