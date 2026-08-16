#!/usr/bin/env python3
"""Clip the raw surveys to the MCA area and smooth the GPS bounce out of them.

Raw handheld GPS tracks wander: consecutive fixes scatter by several metres
even when the surveyor walked a straight line, which inflates every distance
measured from them. This stage does three things, in order:

1. **Clip.** Drop track parts further than a set distance from the MCA
   boundary (10 km by default). Distance is measured to the conservation area
   itself, so anything inside it counts as zero — only genuinely outside data
   is removed.
2. **Resample.** Replace each track with points at a fixed spacing (20 m by
   default), so every track is described at one consistent resolution.
3. **Smooth.** Run a moving average over those points to take out the
   remaining jitter.

Raw data is never modified. Output goes to data/smoothed/ as a separate
GeoPackage, and the raw archives in data/raw/ stay exactly as supplied.

Usage:
    python scripts/smooth_tracks.py
    python scripts/smooth_tracks.py --spacing 10 --window 5
    python scripts/smooth_tracks.py --max-distance-km 5 --no-smooth
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, MultiLineString
from shapely.ops import transform

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402

DEFAULT_SPACING_M = 20.0
DEFAULT_WINDOW = 3
DEFAULT_MAX_DISTANCE_KM = 10.0

SMOOTHED_LAYER = "tracks_smoothed"


# --------------------------------------------------------------------------
# Clipping
# --------------------------------------------------------------------------

def clip_to_boundary(gdf: gpd.GeoDataFrame, boundary, max_distance_m: float):
    """Drop track parts lying further than max_distance_m outside the boundary.

    Filtering is done per part, not per feature: a survey can hold one errant
    track alongside good ones, and dropping the whole survey for it would lose
    real boundary data.
    """
    zone = boundary.buffer(max_distance_m)
    kept_geometries, dropped_parts, dropped_features = [], 0, []

    for index, geometry in gdf.geometry.items():
        parts = list(geometry.geoms) if hasattr(geometry, "geoms") else [geometry]
        keep = [p for p in parts if p.intersects(zone)]
        dropped_parts += len(parts) - len(keep)
        if not keep:
            kept_geometries.append(None)
            dropped_features.append(index)
        elif len(keep) == len(parts):
            kept_geometries.append(geometry)
        else:
            kept_geometries.append(MultiLineString(keep) if len(keep) > 1
                                    else keep[0])

    out = gdf.copy()
    out["geometry"] = kept_geometries
    out = out[out.geometry.notna()]
    return out, dropped_parts, dropped_features


# --------------------------------------------------------------------------
# Resampling and smoothing
# --------------------------------------------------------------------------

def resample_line(line: LineString, spacing: float) -> LineString | None:
    """Place a point every `spacing` metres along the line, keeping both ends.

    The final point is the true line end rather than the last whole step, so a
    track is never silently shortened by up to one spacing.
    """
    length = line.length
    if length <= 0:
        return None
    if length <= spacing:
        # Too short to resample — keep its two ends so it still counts.
        return LineString([line.coords[0], line.coords[-1]])

    steps = int(length // spacing)
    distances = [i * spacing for i in range(steps + 1)]
    if length - distances[-1] > spacing * 0.01:
        distances.append(length)

    points = [line.interpolate(d) for d in distances]
    coordinates = [(p.x, p.y) for p in points]
    return LineString(coordinates) if len(coordinates) >= 2 else None


def smooth_line(line: LineString, window: int) -> LineString:
    """Moving-average the vertices, holding the two endpoints in place.

    Endpoints are preserved because they are what the closure analysis
    measures; averaging them would pull the ends of a boundary together and
    flatter the closure figures.
    """
    coordinates = list(line.coords)
    if window < 3 or len(coordinates) <= window:
        return line

    half = window // 2
    smoothed = [coordinates[0]]
    for i in range(1, len(coordinates) - 1):
        low, high = max(0, i - half), min(len(coordinates), i + half + 1)
        chunk = coordinates[low:high]
        smoothed.append((sum(c[0] for c in chunk) / len(chunk),
                         sum(c[1] for c in chunk) / len(chunk)))
    smoothed.append(coordinates[-1])
    return LineString(smoothed)


def process_geometry(geometry, spacing: float, window: int):
    """Resample then smooth every part of one feature's geometry."""
    parts = list(geometry.geoms) if hasattr(geometry, "geoms") else [geometry]
    out = []
    for part in parts:
        resampled = resample_line(part, spacing)
        if resampled is None:
            continue
        out.append(smooth_line(resampled, window) if window >= 3 else resampled)
    if not out:
        return None
    return MultiLineString(out) if len(out) > 1 else out[0]


def _smooth_geometry(geometry, window: int):
    """Apply the moving average to every part of an already-resampled feature."""
    parts = list(geometry.geoms) if hasattr(geometry, "geoms") else [geometry]
    out = [smooth_line(p, window) for p in parts]
    out = [p for p in out if p is not None and p.length > 0]
    if not out:
        return None
    return MultiLineString(out) if len(out) > 1 else out[0]


def drop_z(geometry):
    """Flatten to 2D — the elevation is GPS-derived and noisier than the fix."""
    return transform(lambda x, y, z=None: (x, y), geometry)


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

BOUNDARY_TYPE = "Land Boundary"


def spur_length(frame: gpd.GeoDataFrame, tolerance: float = 25.0,
                budget_fraction: float = 0.25) -> float:
    """Length of dead-end branches within one survey — the walk to and from it.

    A surveyor walks in to where the boundary starts and out again at the end.
    Those legs are real distance covered but they are not boundary, so they are
    measured here and taken out of the boundary total. The budget is wider than
    the closure test's because this is only measuring, not deciding a shape.
    """
    import closure

    parts = []
    for geometry in frame.geometry:
        if geometry is None:
            continue
        parts.extend(geometry.geoms if hasattr(geometry, "geoms")
                     else [geometry])
    parts = [p for p in parts if p.length > 0]
    if not parts:
        return 0.0

    endpoints = []
    for part in parts:
        endpoints.append(part.coords[0][:2])
        endpoints.append(part.coords[-1][:2])
    labels = closure._cluster_endpoints(endpoints, tolerance)
    edges = [{"a": labels[2 * i], "b": labels[2 * i + 1],
              "length": parts[i].length, "live": True}
             for i in range(len(parts))]
    total = sum(p.length for p in parts)
    closure._prune_spurs(edges, budget_fraction * total)
    return sum(e["length"] for e in edges if not e["live"])


def clans_by_zone(gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """Clans, custodians, surveys and boundary distance per zone.

    Distance counts **boundary only**: surveys that are not land boundaries are
    excluded entirely, and within each survey the dead-end legs walked to reach
    the boundary are taken out.
    """
    frame = gdf.copy()
    frame["length_km"] = frame.geometry.length / 1000
    boundary = frame[frame.get("feature_type", BOUNDARY_TYPE) == BOUNDARY_TYPE]

    spurs = {source: spur_length(group)
             for source, group in boundary.groupby("source_name")}

    def measure(subset: gpd.GeoDataFrame) -> tuple[float, float]:
        walked = subset["length_km"].sum()
        removed = sum(spurs.get(source, 0.0) / 1000
                      for source in subset["source_name"].unique())
        return walked, max(walked - removed, 0.0)

    rows = []
    for zone, group in frame.groupby("zone", sort=True):
        named = group[group["clan"].astype(str).str.strip() != ""]
        in_zone = boundary[boundary.zone == zone]
        walked, net = measure(in_zone)
        rows.append({
            "Zone": zone,
            "Clans": named["clan"].nunique(),
            "Custodians": group["custodian"].nunique(),
            "Surveys": group["source_name"].nunique(),
            "Tracks": len(group),
            "Walked (km)": round(group["length_km"].sum(), 1),
            "Boundary (km)": round(net, 1),
        })

    table = pd.DataFrame(rows)
    named_all = frame[frame["clan"].astype(str).str.strip() != ""]
    walked_all, net_all = measure(boundary)
    table.loc[len(table)] = {
        "Zone": "TOTAL",
        "Clans": named_all["clan"].nunique(),
        "Custodians": frame["custodian"].nunique(),
        "Surveys": frame["source_name"].nunique(),
        "Tracks": len(frame),
        "Walked (km)": round(frame["length_km"].sum(), 1),
        "Boundary (km)": round(net_all, 1),
    }
    return table


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    dataio.add_common_args(parser)
    parser.add_argument("--boundary", type=Path, default=dataio.MCA_BOUNDARY,
                        help="reference boundary to clip against")
    parser.add_argument("--max-distance-km", type=float,
                        default=DEFAULT_MAX_DISTANCE_KM,
                        help="drop track parts further than this from the "
                             "boundary (0 = inside the area)")
    parser.add_argument("--spacing", type=float, default=DEFAULT_SPACING_M,
                        help="metres between points after resampling")
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW,
                        help="moving-average window in points (min 3)")
    parser.add_argument("--no-smooth", action="store_true",
                        help="resample only, skip the moving average")
    parser.add_argument("--out-dir", type=Path, default=dataio.SMOOTHED_DIR,
                        help="where the smoothed GeoPackage is written")
    args = parser.parse_args(argv)

    boundary = dataio.load_boundary(args.boundary)
    if boundary is None:
        print(f"No reference boundary at {args.boundary}")
        return 1

    sources = dataio.load_from_args(args)
    if not sources:
        print(f"\nNothing to smooth — no readable data under {args.raw_dir}.")
        return 0

    merged = dataio.combine(sources)
    metric = merged.gdf.to_crs(dataio.METRIC_CRS)
    metric["geometry"] = metric.geometry.map(drop_z)

    raw_km = metric.geometry.length.sum() / 1000
    raw_features = len(metric)
    raw_points = int(sum(_count_points(g) for g in metric.geometry))

    # 1. Clip
    max_distance_m = args.max_distance_km * 1000
    clipped, dropped_parts, dropped_features = clip_to_boundary(
        metric, boundary, max_distance_m)
    print(f"\nClipped to within {args.max_distance_km:g} km of the MCA "
          f"boundary: dropped {dropped_parts} track part(s), "
          f"{len(dropped_features)} feature(s) removed entirely")
    if dropped_features:
        for index in dropped_features[:10]:
            row = metric.loc[index]
            print(f"    - {row['zone']} / {row['clan'] or '(no clan)'} / "
                  f"{row['custodian']}: {row['name']}")

    clipped_km = clipped.geometry.length.sum() / 1000

    # 2. Resample, reported on its own so the effect of each step is visible.
    window = 0 if args.no_smooth else max(args.window, 0)
    resampled = clipped.copy()
    resampled["geometry"] = resampled.geometry.map(
        lambda g: process_geometry(g, args.spacing, 0))
    resampled = resampled[resampled.geometry.notna()]
    resampled_km = resampled.geometry.length.sum() / 1000

    # 3. Smooth
    if window >= 3:
        smoothed = resampled.copy()
        smoothed["geometry"] = smoothed.geometry.map(
            lambda g: _smooth_geometry(g, window))
        smoothed = smoothed[smoothed.geometry.notna()].copy()
    else:
        smoothed = resampled.copy()

    smooth_km = smoothed.geometry.length.sum() / 1000
    smooth_points = int(sum(_count_points(g) for g in smoothed.geometry))

    print(f"\nResampled to one point every {args.spacing:g} m"
          + (f", then smoothed with a {window}-point moving average" if window >= 3
             else " (no smoothing)"))
    print(f"  features : {raw_features:,} → {len(smoothed):,}")
    print(f"  vertices : {raw_points:,} → {smooth_points:,} "
          f"({smooth_points / raw_points * 100:.0f}% of raw)")
    print(f"  length, step by step:")
    print(f"    raw                {raw_km:9,.1f} km")
    print(f"    after clipping     {clipped_km:9,.1f} km  "
          f"({(clipped_km - raw_km) / raw_km * 100:+.1f}%)")
    print(f"    after resampling   {resampled_km:9,.1f} km  "
          f"({(resampled_km - clipped_km) / clipped_km * 100:+.1f}%)")
    if window >= 3:
        print(f"    after smoothing    {smooth_km:9,.1f} km  "
              f"({(smooth_km - resampled_km) / resampled_km * 100:+.1f}%)")

    # Write
    args.out_dir.mkdir(parents=True, exist_ok=True)
    gpkg = args.out_dir / "mca_tracks_smoothed.gpkg"
    if gpkg.exists():
        gpkg.unlink()

    out = smoothed.to_crs(dataio.WGS84)
    _write(out, gpkg, SMOOTHED_LAYER)
    for zone, group in out.groupby("zone", sort=True):
        _write(group, gpkg, dataio.safe_name(str(zone)))
    print(f"\nWrote {gpkg}")

    table = clans_by_zone(smoothed)
    print("\nClans with data, by zone (after clipping):\n")
    print(table.to_string(index=False))

    report = args.out_dir / "smoothed_summary.md"
    report.write_text(
        "# Smoothed track summary\n\n"
        f"Clipped to within {args.max_distance_km:g} km of the MCA boundary, "
        f"resampled to one point every {args.spacing:g} m"
        + (f", smoothed with a {window}-point moving average.\n\n"
           if window >= 3 else ".\n\n")
        + f"Raw length {raw_km:,.1f} km → smoothed {smooth_km:,.1f} km "
          f"({(smooth_km - raw_km) / raw_km * 100:+.1f}%).\n\n"
        + _markdown_table(table) + "\n",
        encoding="utf-8")
    print(f"Wrote {report}")

    print("\nNext: python scripts/closure.py  → closed / near-closed boundaries")
    return 0


def _markdown_table(frame: pd.DataFrame) -> str:
    """Render a DataFrame as markdown without pulling in tabulate."""
    columns = list(frame.columns)
    lines = ["| " + " | ".join(str(c) for c in columns) + " |",
             "| " + " | ".join("---" for _ in columns) + " |"]
    for _, row in frame.iterrows():
        lines.append("| " + " | ".join(str(row[c]) for c in columns) + " |")
    return "\n".join(lines)


def _write(gdf: gpd.GeoDataFrame, gpkg: Path, layer: str) -> None:
    frame = gdf.copy()
    for column in frame.columns:
        if column == "geometry":
            continue
        if not (pd.api.types.is_numeric_dtype(frame[column])
                or pd.api.types.is_bool_dtype(frame[column])):
            frame[column] = frame[column].astype(str).where(
                frame[column].notna(), None)
    frame.to_file(gpkg, layer=layer, driver="GPKG")


def _count_points(geometry) -> int:
    if geometry is None:
        return 0
    parts = geometry.geoms if hasattr(geometry, "geoms") else [geometry]
    return sum(len(p.coords) for p in parts)


if __name__ == "__main__":
    sys.exit(main())
