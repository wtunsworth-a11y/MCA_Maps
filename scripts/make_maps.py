#!/usr/bin/env python3
"""Build maps from whatever vector data is sitting in data/raw.

Raw inputs are expected to be zip archives (the loader also accepts loose
files). Each archive is unpacked into a cache directory, scanned recursively
for readable layers, and every layer found is rendered as both a static PNG
and an interactive HTML map. A combined map stacking all layers is written
last.

Usage:
    python scripts/make_maps.py
    python scripts/make_maps.py --raw-dir data/raw --out-dir output
    python scripts/make_maps.py --lat-col SiteLat --lon-col SiteLon
    python scripts/make_maps.py --only survey_2026 --refresh
"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

VECTOR_SUFFIXES = {".shp", ".geojson", ".gpkg", ".kml", ".gml", ".gpx", ".fgb"}
TABLE_SUFFIXES = {".csv", ".tsv", ".txt"}
# .json is ambiguous — probed as GeoJSON, skipped quietly if it isn't spatial.
PROBE_SUFFIXES = {".json"}

LAT_NAMES = ("lat", "latitude", "y", "lat_dd", "ycoord", "y_coord", "northing")
LON_NAMES = ("lon", "long", "lng", "longitude", "x", "lon_dd", "xcoord",
             "x_coord", "easting")

WEB_MERCATOR = "EPSG:3857"
WGS84 = "EPSG:4326"


@dataclass
class Layer:
    """One renderable table of geometries, plus where it came from."""

    name: str
    gdf: gpd.GeoDataFrame
    source: Path


# --------------------------------------------------------------------------
# Unpacking
# --------------------------------------------------------------------------

def unpack_archives(raw_dir: Path, cache_dir: Path, refresh: bool) -> list[Path]:
    """Extract every zip under raw_dir into cache_dir, one folder per archive.

    Nested zips are extracted too, since export tools often wrap a bundle of
    per-region archives inside a single download. Returns the list of
    directories that now hold extracted content.
    """
    archives = sorted(p for p in raw_dir.rglob("*.zip") if p.is_file())
    if not archives:
        return []

    extracted: list[Path] = []
    for archive in archives:
        rel = archive.relative_to(raw_dir).with_suffix("")
        target = cache_dir / rel
        if target.exists() and refresh:
            shutil.rmtree(target)
        if not target.exists():
            target.mkdir(parents=True, exist_ok=True)
            try:
                with zipfile.ZipFile(archive) as zf:
                    _safe_extract(zf, target)
            except zipfile.BadZipFile:
                print(f"  ! {archive.name}: not a readable zip, skipping")
                shutil.rmtree(target, ignore_errors=True)
                continue
            print(f"  extracted {archive.relative_to(raw_dir)}")
        else:
            print(f"  cached    {archive.relative_to(raw_dir)}")
        extracted.append(target)

        # Unwrap any zips that were themselves inside the archive.
        for inner in sorted(target.rglob("*.zip")):
            inner_target = inner.with_suffix("")
            if inner_target.exists():
                continue
            inner_target.mkdir(parents=True, exist_ok=True)
            try:
                with zipfile.ZipFile(inner) as zf:
                    _safe_extract(zf, inner_target)
                print(f"  extracted {inner.name} (nested)")
            except zipfile.BadZipFile:
                shutil.rmtree(inner_target, ignore_errors=True)

    return extracted


def _safe_extract(zf: zipfile.ZipFile, target: Path) -> None:
    """Extract without letting archive entries escape the target directory."""
    target = target.resolve()
    for member in zf.infolist():
        dest = (target / member.filename).resolve()
        if not str(dest).startswith(str(target)):
            raise ValueError(f"unsafe path in archive: {member.filename}")
    zf.extractall(target)


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def find_sources(search_dirs: list[Path]) -> list[Path]:
    """Collect every candidate data file, skipping extraction cruft."""
    found: list[Path] = []
    for directory in search_dirs:
        for path in sorted(directory.rglob("*")):
            if not path.is_file():
                continue
            if any(part in {"__MACOSX", ".git"} for part in path.parts):
                continue
            if path.name.startswith("."):
                continue
            suffix = path.suffix.lower()
            if suffix in VECTOR_SUFFIXES | TABLE_SUFFIXES | PROBE_SUFFIXES:
                found.append(path)
    return found


def load_layer(path: Path, args: argparse.Namespace) -> Layer | None:
    """Read one file into a GeoDataFrame, or return None if it isn't spatial."""
    suffix = path.suffix.lower()
    name = path.stem

    if suffix in TABLE_SUFFIXES:
        gdf = _load_table(path, args)
    elif suffix in PROBE_SUFFIXES:
        try:
            gdf = gpd.read_file(path)
        except Exception:
            return None  # plain JSON sidecar, not GeoJSON
    else:
        gdf = gpd.read_file(path)

    if gdf is None or gdf.empty:
        return None
    if "geometry" not in gdf or gdf.geometry.isna().all():
        return None

    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    if gdf.empty:
        return None

    if gdf.crs is None:
        gdf = gdf.set_crs(args.crs)
    gdf = gdf.to_crs(WGS84)
    return Layer(name=name, gdf=gdf, source=path)


def _load_table(path: Path, args: argparse.Namespace) -> gpd.GeoDataFrame | None:
    """Turn a delimited text file into points using its lat/lon columns."""
    sep = "\t" if path.suffix.lower() == ".tsv" else None
    try:
        df = pd.read_csv(path, sep=sep, engine="python", low_memory=False)
    except Exception as exc:
        print(f"  ! {path.name}: unreadable ({exc})")
        return None
    if df.empty:
        return None

    lat_col = args.lat_col or _match_column(df.columns, LAT_NAMES)
    lon_col = args.lon_col or _match_column(df.columns, LON_NAMES)
    if not lat_col or not lon_col:
        print(f"  - {path.name}: no lat/lon columns found, skipping")
        return None

    lat = pd.to_numeric(df[lat_col], errors="coerce")
    lon = pd.to_numeric(df[lon_col], errors="coerce")
    keep = lat.notna() & lon.notna()
    dropped = int((~keep).sum())
    if dropped:
        print(f"  - {path.name}: dropped {dropped} rows without coordinates")
    df = df[keep]
    if df.empty:
        return None

    return gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(lon[keep], lat[keep]),
        crs=args.crs,
    )


def _match_column(columns, candidates: tuple[str, ...]) -> str | None:
    lookup = {str(c).strip().lower(): c for c in columns}
    for candidate in candidates:
        if candidate in lookup:
            return lookup[candidate]
    return None


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def render_static(layer: Layer, out_dir: Path) -> Path:
    """Write a PNG of one layer with a basemap underneath when available."""
    gdf = layer.gdf.to_crs(WEB_MERCATOR)
    fig, ax = plt.subplots(figsize=(11, 9), dpi=150)

    geom_types = set(gdf.geom_type)
    if geom_types & {"Point", "MultiPoint"}:
        gdf.plot(ax=ax, markersize=14, color="#2563eb", alpha=0.75,
                 edgecolor="white", linewidth=0.4)
    elif geom_types & {"LineString", "MultiLineString"}:
        gdf.plot(ax=ax, color="#2563eb", linewidth=1.0, alpha=0.85)
    else:
        gdf.plot(ax=ax, facecolor="#93c5fd", edgecolor="#1e3a8a",
                 linewidth=0.5, alpha=0.7)

    _add_basemap(ax, gdf)
    ax.set_axis_off()
    ax.set_title(f"{layer.name}  ({len(gdf):,} features)", fontsize=13, pad=12)
    fig.tight_layout()

    out_path = out_dir / f"{layer.name}.png"
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _add_basemap(ax, gdf) -> None:
    """Best-effort tile basemap; silently skipped if contextily/net is absent."""
    try:
        import contextily as cx
    except ImportError:
        return
    try:
        cx.add_basemap(ax, crs=gdf.crs, source=cx.providers.CartoDB.Positron,
                       attribution_size=6)
    except Exception:
        pass


def render_interactive(layers: list[Layer], out_path: Path, title: str) -> Path:
    """Write a folium HTML map holding one toggleable overlay per layer."""
    import folium

    bounds = _combined_bounds(layers)
    center = [(bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2]
    fmap = folium.Map(location=center, zoom_start=6, tiles="CartoDB positron")

    palette = ["#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed",
               "#0891b2", "#be185d", "#4d7c0f"]

    for index, layer in enumerate(layers):
        color = palette[index % len(palette)]
        gdf = _stringify_for_json(layer.gdf)
        fields = [c for c in gdf.columns if c != "geometry"][:10]
        folium.GeoJson(
            gdf.to_json(),
            name=f"{layer.name} ({len(gdf):,})",
            marker=folium.CircleMarker(radius=4, fill=True, fill_opacity=0.7,
                                       color=color, fill_color=color),
            style_function=lambda _f, c=color: {
                "color": c, "weight": 1.5, "fillColor": c, "fillOpacity": 0.35,
            },
            tooltip=folium.GeoJsonTooltip(fields=fields) if fields else None,
        ).add_to(fmap)

    folium.LayerControl(collapsed=False).add_to(fmap)
    fmap.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])
    fmap.get_root().html.add_child(folium.Element(
        f"<h3 style='font-family:system-ui;margin:8px 12px'>{title}</h3>"
    ))
    fmap.save(str(out_path))
    return out_path


def _stringify_for_json(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Cast non-JSON-safe columns (dates, objects) to strings for folium."""
    out = gdf.copy()
    for column in out.columns:
        if column == "geometry":
            continue
        if not pd.api.types.is_numeric_dtype(out[column]):
            out[column] = out[column].astype(str)
    return out


def _combined_bounds(layers: list[Layer]) -> tuple[float, float, float, float]:
    frames = [layer.gdf.total_bounds for layer in layers]
    minx = min(b[0] for b in frames)
    miny = min(b[1] for b in frames)
    maxx = max(b[2] for b in frames)
    maxy = max(b[3] for b in frames)
    if minx == maxx:
        minx, maxx = minx - 0.05, maxx + 0.05
    if miny == maxy:
        miny, maxy = miny - 0.05, maxy + 0.05
    return minx, miny, maxx, maxy


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw-dir", type=Path, default=REPO_ROOT / "data" / "raw",
                        help="folder holding the zipped source data")
    parser.add_argument("--cache-dir", type=Path,
                        default=REPO_ROOT / "data" / "processed" / "extracted",
                        help="where archives are unpacked")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "output",
                        help="where rendered maps are written")
    parser.add_argument("--only", default=None,
                        help="only process sources whose path contains this text")
    parser.add_argument("--lat-col", default=None, help="latitude column override")
    parser.add_argument("--lon-col", default=None, help="longitude column override")
    parser.add_argument("--crs", default=WGS84,
                        help="CRS to assume for data that declares none")
    parser.add_argument("--refresh", action="store_true",
                        help="re-extract archives instead of reusing the cache")
    parser.add_argument("--no-combined", action="store_true",
                        help="skip the all-layers combined map")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    raw_dir: Path = args.raw_dir

    if not raw_dir.exists():
        print(f"No raw data directory at {raw_dir}")
        return 1

    print(f"Reading archives from {raw_dir}")
    search_dirs = unpack_archives(raw_dir, args.cache_dir, args.refresh)
    search_dirs.append(raw_dir)  # loose, unzipped files are welcome too

    sources = find_sources(search_dirs)
    if args.only:
        sources = [p for p in sources if args.only in str(p)]
    if not sources:
        print(
            f"\nNothing to map yet — no data files found under {raw_dir}.\n"
            "Add your zip archives there and re-run this script."
        )
        return 0

    print(f"\nFound {len(sources)} candidate file(s)")
    layers: list[Layer] = []
    for path in sources:
        try:
            layer = load_layer(path, args)
        except Exception as exc:
            print(f"  ! {path.name}: {exc}")
            continue
        if layer is None:
            continue
        layers.append(layer)
        print(f"  + {layer.name}: {len(layer.gdf):,} features "
              f"({', '.join(sorted(set(layer.gdf.geom_type)))})")

    if not layers:
        print("\nNo spatial layers could be read from those files.")
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nWriting maps to {args.out_dir}")
    for layer in layers:
        png = render_static(layer, args.out_dir)
        html = render_interactive([layer], args.out_dir / f"{layer.name}.html",
                                  layer.name)
        print(f"  {png.name}\n  {html.name}")

    if len(layers) > 1 and not args.no_combined:
        combined = render_interactive(layers, args.out_dir / "all_layers.html",
                                      "All layers")
        print(f"  {combined.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
