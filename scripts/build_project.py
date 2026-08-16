#!/usr/bin/env python3
"""Assemble the working QGIS project — everything, in one place to open.

This is the project to look at when you want to see what the pipeline sees. It
gathers every layer the analysis produces into one GeoPackage and one .qgs, so
opening it shows the raw tracks, the smoothed tracks, the areas with surveyed
and inferred kept apart, the sacred sites, the modelled landform, and the MCA
boundary over terrain.

Layer order is deliberate. What is measured sits above what is inferred, which
sits above what is modelled, which sits above context. A layer that carries an
assumption is named so that its name says so.

Only the layers worth seeing first are switched on. The rest are present and
one click away, because a project that opens with twenty layers stacked shows
nothing at all.

Rebuilt from scratch each run, so it always matches the current data.

Usage:
    python scripts/build_project.py
    python scripts/build_project.py --out data/smoothed/mca_working.qgs
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402
import export_qgis  # noqa: E402
import hydrology  # noqa: E402
import landform  # noqa: E402
import terrain  # noqa: E402

# name, path, layer, colour, on by default
SOURCES = [
    ("Smoothed boundaries", "smoothed", "tracks_smoothed", "#111827", True),
    ("Raw boundaries (unsmoothed)", "raw", None, "#9ca3af", False),
    ("Areas — surveyed (walked ring)", "polygons", "survey_polygons",
     "#2563eb", True),
    ("Areas — inferred (gap bridged)", "polygons_inferred", "survey_polygons",
     "#f59e0b", True),
    ("Clan areas (dissolved)", "polygons", "clan_polygons", "#7c3aed", False),
    ("Sacred site extents (estimated)", "sacred", "sacred_site_hulls",
     "#be185d", False),
    ("Modelled watercourses", "streams", "streams", "#0369a1", False),
    ("Modelled ridgelines", "ridges", "ridges", "#c2410c", False),
    ("MCA boundary", "boundary", None, "#475569", True),
]


def collect(args) -> list[tuple[str, gpd.GeoDataFrame, str, bool]]:
    """Load every layer that exists, quietly skipping those that do not."""
    smoothed = dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg"
    polygons = dataio.SMOOTHED_DIR / "mca_polygons.gpkg"
    sacred = dataio.SMOOTHED_DIR / "mca_sacred_sites.gpkg"

    def read(path: Path, layer: str | None):
        if not path.exists():
            return None
        try:
            return gpd.read_file(path, layer=layer) if layer else \
                gpd.read_file(path)
        except Exception:
            return None

    out = []
    for label, kind, layer, colour, visible in SOURCES:
        if kind == "smoothed":
            frame = read(smoothed, layer)
        elif kind == "raw":
            frame = raw_tracks(args)
        elif kind == "polygons":
            frame = read(polygons, layer)
        elif kind == "polygons_inferred":
            frame = read(polygons, layer)
            if frame is not None and "basis" in frame:
                frame = frame[frame.basis == "inferred"]
        elif kind == "sacred":
            frame = read(sacred, layer)
        elif kind == "streams":
            frame = read(hydrology.STREAMS_PATH, layer)
        elif kind == "ridges":
            frame = read(landform.RIDGES_PATH, layer)
        elif kind == "boundary":
            frame = read(dataio.MCA_BOUNDARY, None)
        else:
            frame = None

        if kind == "polygons" and layer == "survey_polygons" \
                and frame is not None and "basis" in frame:
            frame = frame[frame.basis == "surveyed"]

        if frame is None or frame.empty:
            print(f"  - {label}: not available")
            continue
        out.append((label, frame.to_crs(dataio.WGS84), colour, visible))
        print(f"  + {label}: {len(frame):,} features")
    return out


def raw_tracks(args) -> gpd.GeoDataFrame | None:
    """The unsmoothed archives, merged, for comparison against the smoothed."""
    if not args.raw_dir.exists():
        return None
    layers = dataio.load_all(raw_dir=args.raw_dir, quiet=True)
    merged = dataio.combine(layers)
    if merged is None:
        return None
    frame = merged.gdf
    # Keep it light: the raw tracks are only here to eyeball the smoothing.
    keep = [c for c in ("zone", "clan", "custodian", "feature_type",
                        "source_name", "geometry") if c in frame.columns]
    return frame[keep]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw-dir", type=Path, default=dataio.RAW_DIR)
    parser.add_argument("--gpkg", type=Path,
                        default=dataio.SMOOTHED_DIR / "mca_working.gpkg")
    parser.add_argument("--out", type=Path,
                        default=dataio.SMOOTHED_DIR / "mca_working.qgs")
    parser.add_argument("--title", default="MCA Maps — working project")
    parser.add_argument("--qgis-version",
                        default=export_qgis.DEFAULT_QGIS_VERSION)
    parser.add_argument("--no-raw", action="store_true",
                        help="skip the raw tracks, which are slow to rebuild")
    args = parser.parse_args(argv)

    print("Collecting layers")
    if args.no_raw:
        global SOURCES
        SOURCES = [s for s in SOURCES if s[1] != "raw"]
    collected = collect(args)
    if not collected:
        print("Nothing to put in a project.")
        return 1

    layers = [dataio.Layer(name=dataio.safe_name(label), gdf=frame,
                           source=args.gpkg)
              for label, frame, _, _ in collected]

    print(f"\nWriting {args.gpkg}")
    export_qgis.write_geopackage(layers, args.gpkg)

    # Rebuild the display names, which safe_name flattened for the GeoPackage.
    display = {dataio.safe_name(label): (label, colour, visible)
               for label, _, colour, visible in collected}

    terrain_layers = [(path, name) for path, name in
                      ((terrain.HILLSHADE_PATH, "Terrain hillshade"),
                       (terrain.DEM_PATH, "Elevation (m)"))
                      if path.exists()]

    export_qgis.build_project(
        layers[1:], args.gpkg, args.out, args.qgis_version,
        basemap=True, title=args.title, lead=layers[0],
        group="All layers", terrain_layers=terrain_layers)

    _apply_names(args.out, display)

    print(f"\nWrote {args.out}")
    print(f"Open it in QGIS {args.qgis_version.split('-')[0]} or newer — "
          f"{len(layers)} data layer(s) plus terrain and basemap.")
    return 0


def _apply_names(project: Path, display: dict) -> None:
    """Restore readable layer names and per-layer visibility in the .qgs."""
    from xml.sax.saxutils import quoteattr

    text = project.read_text(encoding="utf-8")
    for safe, (label, _colour, visible) in display.items():
        text = text.replace(f'name={quoteattr(safe)}', f'name={quoteattr(label)}')
        text = text.replace(f'<layername>{safe}</layername>',
                            f'<layername>{label}</layername>')
        if visible:
            marker = f'name={quoteattr(label)} '
            start = text.find(marker)
            if start != -1:
                end = text.find('>', start)
                segment = text[start:end].replace('checked="Qt::Unchecked"',
                                                  'checked="Qt::Checked"')
                text = text[:start] + segment + text[end:]
    project.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
