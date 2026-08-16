#!/usr/bin/env python3
"""Derive the drainage network from the DEM, and test boundaries against it.

No hydrology dataset is reachable from this environment, so the stream network
is computed from the Copernicus 30 m DEM instead: depressions filled, flats
resolved, D8 flow directions, flow accumulation, then channels extracted
wherever enough ground drains through a cell.

This is **modelled drainage, not surveyed rivers.** It shows where water would
run given the terrain. In steep country it tracks the real channels closely; on
flat ground, and anywhere the 30 m DEM cannot see a channel narrower than a
cell, it is unreliable. It should be treated as a prompt for the field team,
never as evidence that a boundary is right or wrong.

Its use here is to ask a specific question: **do the clan boundary walks follow
watercourses?** If a boundary runs along a stream, that corroborates it
independently of the survey. If an *inferred* closure cuts across drainage the
walked part never crosses, that is a sign the straight-line guess is wrong.

Usage:
    python scripts/hydrology.py
    python scripts/hydrology.py --threshold 500 --buffer 60
    python scripts/hydrology.py --report output/hydrology_report.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402
import terrain  # noqa: E402

HYDRO_DIR = dataio.REFERENCE_DIR / "hydro"
STREAMS_PATH = HYDRO_DIR / "streams.gpkg"

# D8 directions, clockwise from east, as pysheds expects them.
DIRMAP = (64, 128, 1, 2, 4, 8, 16, 32)

# A value the elevation raster cannot hold, so nothing real is masked out.
NODATA = -32768.0


def derive_streams(dem_path: Path, threshold: int,
                   sea_level: float = 0.0) -> gpd.GeoDataFrame:
    """Fill, route and accumulate flow, then extract the channel network."""
    # pysheds 0.5 still calls np.in1d, which NumPy 2 removed in favour of
    # np.isin. Same semantics for this use, so alias it before importing.
    if not hasattr(np, "in1d"):
        np.in1d = np.isin

    from pysheds.grid import Grid

    print(f"Reading {dem_path}")
    # The cropped DEM carries no nodata value, and pysheds would otherwise
    # default to 0 — which is a real elevation here, not missing data. Point it
    # at a value the raster cannot contain instead.
    grid = Grid.from_raster(str(dem_path), nodata=NODATA)
    dem = grid.read_raster(str(dem_path), nodata=NODATA)

    # The DEM window reaches the Solomon Sea in its north-east corner, where
    # elevation is flat zero. D8 has no gradient to follow there and fans out
    # into parallel diagonal lines that look like rivers but are an artefact of
    # routing across water. Mask the sea out before routing; the survey area is
    # mountainous and nowhere near sea level, so nothing real is lost.
    sea = np.asarray(dem) <= sea_level
    if sea.any():
        print(f"  masking {sea.sum():,} sea cells at or below "
              f"{sea_level:g} m")
        dem[sea] = NODATA

    print("  filling pits, depressions and flats")
    filled = grid.fill_pits(dem)
    flooded = grid.fill_depressions(filled)
    inflated = grid.resolve_flats(flooded)

    print("  computing flow direction and accumulation")
    directions = grid.flowdir(inflated, dirmap=DIRMAP)
    accumulation = grid.accumulation(directions, dirmap=DIRMAP)

    cells = int((accumulation > threshold).sum())
    print(f"  {cells:,} cells exceed {threshold:,} upstream cells "
          f"(~{threshold * 0.0009:.2f} km² drainage)")

    print("  extracting the channel network")
    network = grid.extract_river_network(directions, accumulation > threshold,
                                         dirmap=DIRMAP)

    streams = gpd.GeoDataFrame.from_features(network["features"],
                                             crs=dataio.WGS84)
    streams = streams[streams.geometry.notna() & ~streams.geometry.is_empty]

    metric = streams.to_crs(dataio.METRIC_CRS)
    streams = streams.assign(length_m=metric.geometry.length.round(1))
    return streams


def drop_sea_channels(streams: gpd.GeoDataFrame, dem_path: Path,
                      sea_level: float) -> gpd.GeoDataFrame:
    """Remove channels that sit at sea level.

    Masking the sea before routing stops most of the artefact, but flow still
    escapes along the masked edge and emerges as long, dead-straight diagonals.
    They are unmistakable once measured: sinuosity ~1.00 against a real-channel
    median of 1.23, at 0–1 m elevation in a survey area that starts at 400 m.
    Sampling the DEM along each segment removes them without touching anything
    inland.
    """
    import rasterio

    with rasterio.open(dem_path) as handle:
        elevations = []
        for geometry in streams.to_crs(dataio.WGS84).geometry:
            points = list(geometry.coords)[::5] or list(geometry.coords)
            values = [v[0] for v in handle.sample(points)]
            elevations.append(float(np.mean(values)) if values else 0.0)

    keep = np.array(elevations) > sea_level
    dropped = int((~keep).sum())
    if dropped:
        print(f"  dropped {dropped} channel(s) at or below {sea_level:g} m "
              "(sea-level routing artefact)")
    return streams[keep]


def clip_to_area(streams: gpd.GeoDataFrame, distance_m: float
                 ) -> gpd.GeoDataFrame:
    """Keep only drainage near the conservation area, as the tracks are."""
    boundary = dataio.load_boundary()
    if boundary is None or distance_m <= 0:
        return streams
    zone = boundary.buffer(distance_m)
    metric = streams.to_crs(dataio.METRIC_CRS)
    kept = metric[metric.intersects(zone)]
    print(f"  clipped to within {distance_m / 1000:g} km of the MCA: "
          f"{len(kept):,} of {len(metric):,} segments")
    return kept.to_crs(streams.crs)


def boundary_agreement(tracks: gpd.GeoDataFrame, streams: gpd.GeoDataFrame,
                       buffer_m: float) -> pd.DataFrame:
    """How much of each survey's walk runs along a modelled watercourse."""
    corridor = streams.to_crs(dataio.METRIC_CRS).geometry.buffer(buffer_m)
    from shapely.ops import unary_union
    water = unary_union(list(corridor))

    rows = []
    for source, group in tracks.groupby("source_name"):
        walked = group.geometry.length.sum()
        if walked <= 0:
            continue
        along = sum(part.intersection(water).length
                    for part in group.geometry)
        first = group.iloc[0]
        rows.append({
            "zone": first.get("zone", ""),
            "clan": first.get("clan", ""),
            "steward": first.get("steward", ""),
            "source_name": source,
            "walked_km": round(walked / 1000, 2),
            "along_water_km": round(along / 1000, 2),
            "pct_along_water": round(along / walked * 100, 1),
        })
    return pd.DataFrame(rows).sort_values("pct_along_water", ascending=False)


def bridge_check(polygons: gpd.GeoDataFrame, streams: gpd.GeoDataFrame,
                 buffer_m: float) -> pd.DataFrame:
    """Compare an inferred polygon's straight closures against its walked edge.

    A bridge that crosses far more drainage per kilometre than the walked part
    is a straight line drawn through country the surveyor would have had to
    cross — worth a second look.
    """
    from shapely.ops import unary_union

    lines = unary_union(list(streams.to_crs(dataio.METRIC_CRS).geometry))
    rows = []
    for _, row in polygons[polygons.basis == "inferred"].iterrows():
        ring = row.geometry.exterior
        crossings = 0
        if lines.intersects(ring):
            intersection = lines.intersection(ring)
            crossings = (len(intersection.geoms)
                         if hasattr(intersection, "geoms") else 1)
        rows.append({
            "zone": row.zone, "clan": row.clan, "steward": row.steward,
            "area_ha": row.area_ha, "gap_pct": row.gap_pct,
            "stream_crossings": crossings,
        })
    return pd.DataFrame(rows).sort_values("gap_pct", ascending=False)


def render(streams: gpd.GeoDataFrame, tracks: gpd.GeoDataFrame, boundary,
           out_path: Path) -> Path:
    """Draw the modelled drainage under the surveyed boundaries."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    figure, axis = plt.subplots(figsize=(11, 10), dpi=150)
    terrain.add_hillshade(axis, dataio.METRIC_CRS, alpha=0.45)

    if boundary is not None:
        gpd.GeoSeries([boundary], crs=dataio.METRIC_CRS).boundary.plot(
            ax=axis, color="#475569", linewidth=1.2, zorder=1)

    metric = streams.to_crs(dataio.METRIC_CRS)
    # Wider lines for longer channels, which stands in for stream order.
    if "length_m" in metric.columns and len(metric) > 1:
        widths = np.interp(metric.length_m,
                           (metric.length_m.min(), metric.length_m.quantile(0.97)),
                           (0.35, 1.9))
    else:
        widths = 0.8
    metric.plot(ax=axis, color="#0369a1", linewidth=widths, alpha=0.85, zorder=2)

    tracks.to_crs(dataio.METRIC_CRS).plot(ax=axis, color="#b91c1c",
                                          linewidth=0.9, alpha=0.9, zorder=3)

    axis.set_axis_off()
    axis.set_title("Modelled drainage from the 30 m DEM, with the surveyed "
                   f"boundaries\n{len(streams):,} channel segments, "
                   f"{metric.geometry.length.sum() / 1000:,.0f} km",
                   fontsize=12, pad=12)
    axis.legend(handles=[
        Line2D([0], [0], color="#0369a1", lw=2, label="Modelled drainage"),
        Line2D([0], [0], color="#b91c1c", lw=2, label="Surveyed boundaries"),
        Line2D([0], [0], color="#475569", lw=1.5, label="MCA boundary"),
    ], loc="lower left", fontsize=9, frameon=True)
    figure.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(out_path, bbox_inches="tight")
    plt.close(figure)
    return out_path


def _markdown(frame: pd.DataFrame, limit: int | None = None) -> str:
    if frame.empty:
        return "_None._"
    view = frame.head(limit) if limit else frame
    columns = [c for c in view.columns if c != "geometry"]
    lines = ["| " + " | ".join(columns) + " |",
             "| " + " | ".join("---" for _ in columns) + " |"]
    for _, row in view.iterrows():
        lines.append("| " + " | ".join(
            "" if pd.isna(row[c]) else str(row[c]) for c in columns) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dem", type=Path, default=terrain.DEM_PATH)
    parser.add_argument("--threshold", type=int, default=1000,
                        help="upstream cells needed to start a channel "
                             "(1000 ≈ 0.9 km² of drainage)")
    parser.add_argument("--sea-level", type=float, default=0.0,
                        help="elevation at or below which cells are treated as "
                             "sea and excluded from routing")
    parser.add_argument("--max-distance-km", type=float, default=10.0,
                        help="keep drainage within this distance of the MCA, "
                             "matching the track clip")
    parser.add_argument("--buffer", type=float, default=50.0,
                        help="metres either side of a channel counted as "
                             "'along' it")
    parser.add_argument("--tracks", type=Path,
                        default=dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg")
    parser.add_argument("--polygons", type=Path,
                        default=dataio.SMOOTHED_DIR / "mca_polygons.gpkg")
    parser.add_argument("--out", type=Path, default=STREAMS_PATH)
    parser.add_argument("--map", type=Path,
                        default=dataio.OUT_DIR / "drainage.png")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.dem.exists():
        print(f"No DEM at {args.dem}. Run scripts/fetch_dem.py first.")
        return 1

    streams = derive_streams(args.dem, args.threshold, args.sea_level)
    streams = drop_sea_channels(streams, args.dem, args.sea_level)
    streams = clip_to_area(streams, args.max_distance_km * 1000)
    metric = streams.to_crs(dataio.METRIC_CRS)
    total_km = metric.geometry.length.sum() / 1000
    print(f"\n{len(streams):,} channel segments, {total_km:,.0f} km total")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        args.out.unlink()
    streams.to_file(args.out, layer="streams", driver="GPKG")
    print(f"Wrote {args.out}")

    agreement = pd.DataFrame()
    bridges = pd.DataFrame()
    if args.tracks.exists():
        tracks = gpd.read_file(args.tracks,
                               layer="tracks_smoothed").to_crs(dataio.METRIC_CRS)
        agreement = boundary_agreement(tracks, streams, args.buffer)
        overall = (agreement.along_water_km.sum()
                   / agreement.walked_km.sum() * 100)
        print(f"\nBoundary walks running along modelled drainage "
              f"(within {args.buffer:g} m): {overall:.1f}% of all distance "
              "walked\n")
        print(agreement.head(12).to_string(index=False))

        if args.polygons.exists():
            polygons = gpd.read_file(args.polygons,
                                     layer="survey_polygons").to_crs(
                                         dataio.METRIC_CRS)
            bridges = bridge_check(polygons, streams, args.buffer)

        render(streams, tracks, dataio.load_boundary(), args.map)
        print(f"\nWrote {args.map}")

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        overall = (agreement.along_water_km.sum() / agreement.walked_km.sum()
                   * 100) if not agreement.empty else 0
        args.report.write_text(
            "# Modelled drainage\n\n"
            "Derived from the Copernicus 30 m DEM — depressions filled, D8 flow "
            "routing, channels extracted above "
            f"{args.threshold:,} upstream cells (~"
            f"{args.threshold * 0.0009:.2f} km² of drainage).\n\n"
            "**This is modelled drainage, not surveyed rivers.** It shows where "
            "water would run given the terrain. Treat it as a prompt for the "
            "field team, never as evidence a boundary is right or wrong.\n\n"
            f"- **Channel segments:** {len(streams):,}\n"
            f"- **Total channel length:** {total_km:,.0f} km\n"
            f"- **Boundary walked along drainage** (within {args.buffer:g} m): "
            f"**{overall:.1f}%**\n\n"
            "## Surveys most closely following drainage\n\n"
            + _markdown(agreement, 25) + "\n\n"
            "## Inferred closures against drainage\n\n"
            "Straight-line closures that cross many channels are worth a "
            "second look — a surveyor would have had to cross them.\n\n"
            + _markdown(bridges, 25) + "\n",
            encoding="utf-8")
        print(f"Wrote {args.report}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
