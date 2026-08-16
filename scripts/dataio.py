"""Shared loading layer: unpack the raw zips and read whatever is inside.

Every script in this repo goes through here, so the three stages of the
workflow — inspect, present, export to QGIS — always see exactly the same
set of layers.
"""

from __future__ import annotations

import argparse
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import pandas as pd

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
        gdf = gpd.read_file(path)

    if gdf is None or gdf.empty or "geometry" not in gdf:
        return None

    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    if gdf.empty:
        return None

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


def _load_table(path: Path, lat_col: str | None, lon_col: str | None,
                assume_crs: str) -> gpd.GeoDataFrame | None:
    """Turn a delimited text file into points using its lat/lon columns."""
    sep = "\t" if path.suffix.lower() == ".tsv" else None
    try:
        df = pd.read_csv(path, sep=sep, engine="python", low_memory=False)
    except Exception:
        return None
    if df.empty:
        return None

    lat_col = lat_col or _match_column(df.columns, LAT_NAMES)
    lon_col = lon_col or _match_column(df.columns, LON_NAMES)
    if not lat_col or not lon_col or lat_col not in df or lon_col not in df:
        return None

    lat = pd.to_numeric(df[lat_col], errors="coerce")
    lon = pd.to_numeric(df[lon_col], errors="coerce")
    keep = lat.notna() & lon.notna()
    if not keep.any():
        return None

    return gpd.GeoDataFrame(
        df[keep].reset_index(drop=True),
        geometry=gpd.points_from_xy(lon[keep], lat[keep]),
        crs=assume_crs,
    )


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
