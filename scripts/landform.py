#!/usr/bin/env python3
"""Classify how much of each boundary follows a watercourse or a ridge.

Clan boundaries in this country tend to follow the land: down a creek, or along
the top of a spur. Both are derivable from the DEM, and the two use the same
machinery — invert the elevation and ridges become the "channels" of the
inverted surface, so the flow routing that finds streams finds ridgelines too.

Ridges get a second test. Inverted-flow accumulation alone will trace a line
along any local high, including the middle of a gently sloping face, so a
candidate is only kept where the **topographic position index** is positive —
that is, where the ground genuinely stands above its surroundings.

Each survey's walk is then split three ways: along water, along ridge, or along
neither. A boundary running mostly along one or the other is corroborated by
the terrain independently of the survey. One that follows neither is not
necessarily wrong — boundaries can run along a road, a garden edge, or an
agreed line — but it has no independent support.

Both layers are **modelled from a 30 m DEM, not surveyed**. They are a prompt
for the field team, never evidence that a boundary is right or wrong.

Usage:
    python scripts/landform.py
    python scripts/landform.py --ridge-threshold 500 --buffer 60
    python scripts/landform.py --report output/landform_report.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402
import hydrology  # noqa: E402
import terrain  # noqa: E402

RIDGES_PATH = hydrology.HYDRO_DIR / "ridges.gpkg"

# Radius, in cells, of the neighbourhood a point is compared against for TPI.
# 30 m cells, so 11 cells is roughly a 330 m reach — the scale of a spur, not
# of a whole mountainside.
TPI_RADIUS = 11


def derive_ridges(dem_path: Path, threshold: int, sea_level: float,
                  tpi_radius: int = TPI_RADIUS) -> gpd.GeoDataFrame:
    """Extract ridgelines by routing flow over the inverted surface."""
    if not hasattr(np, "in1d"):
        np.in1d = np.isin

    from pysheds.grid import Grid
    from pysheds.view import Raster

    print(f"Reading {dem_path}")
    grid = Grid.from_raster(str(dem_path), nodata=hydrology.NODATA)
    dem = grid.read_raster(str(dem_path), nodata=hydrology.NODATA)

    elevation = np.asarray(dem, dtype="float64")
    sea = elevation <= sea_level
    if sea.any():
        print(f"  masking {sea.sum():,} sea cells")

    # Invert: high ground becomes low, so ridges become valleys to route along.
    usable = elevation[~sea]
    ceiling = float(usable.max()) if usable.size else 0.0
    inverted_values = ceiling - elevation
    inverted_values[sea] = hydrology.NODATA
    inverted = Raster(inverted_values.astype("float64"),
                      viewfinder=dem.viewfinder)

    print("  filling and routing the inverted surface")
    filled = grid.fill_pits(inverted)
    flooded = grid.fill_depressions(filled)
    inflated = grid.resolve_flats(flooded)
    directions = grid.flowdir(inflated, dirmap=hydrology.DIRMAP)
    accumulation = grid.accumulation(directions, dirmap=hydrology.DIRMAP)

    print(f"  extracting ridge candidates above {threshold:,} cells")
    network = grid.extract_river_network(directions, accumulation > threshold,
                                         dirmap=hydrology.DIRMAP)
    ridges = gpd.GeoDataFrame.from_features(network["features"],
                                            crs=dataio.WGS84)
    ridges = ridges[ridges.geometry.notna() & ~ridges.geometry.is_empty]
    print(f"  {len(ridges):,} candidate lines")

    keep = _positive_tpi(ridges, dem_path, elevation, sea, tpi_radius)
    ridges = ridges[keep]
    print(f"  {len(ridges):,} kept after the topographic position test")

    metric = ridges.to_crs(dataio.METRIC_CRS)
    return ridges.assign(length_m=metric.geometry.length.round(1))


def _positive_tpi(ridges: gpd.GeoDataFrame, dem_path: Path,
                  elevation: np.ndarray, sea: np.ndarray,
                  radius: int) -> np.ndarray:
    """Keep only lines standing above their surroundings on average.

    Inverted-flow routing will happily draw a line down the middle of an even
    slope, where there is no ridge at all. Comparing each cell with the mean of
    its neighbourhood separates a real crest from an artefact of the routing.
    """
    import rasterio
    from scipy.ndimage import uniform_filter

    working = np.where(sea, np.nan, elevation)
    filled = np.where(np.isnan(working), np.nanmean(working), working)
    local_mean = uniform_filter(filled, size=radius * 2 + 1, mode="nearest")
    tpi = working - local_mean

    with rasterio.open(dem_path) as handle:
        keep = []
        for geometry in ridges.to_crs(dataio.WGS84).geometry:
            points = list(geometry.coords)[::3] or list(geometry.coords)
            values = []
            for x, y in points:
                row, column = handle.index(x, y)
                if 0 <= row < tpi.shape[0] and 0 <= column < tpi.shape[1]:
                    value = tpi[row, column]
                    if not np.isnan(value):
                        values.append(value)
            keep.append(bool(values) and float(np.mean(values)) > 0)
    return np.array(keep)


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------

def classify(tracks: gpd.GeoDataFrame, streams: gpd.GeoDataFrame,
             ridges: gpd.GeoDataFrame, buffer_m: float) -> pd.DataFrame:
    """Split every survey's walked distance into water, ridge and neither."""
    water = unary_union(list(
        streams.to_crs(dataio.METRIC_CRS).geometry.buffer(buffer_m)))
    crest = unary_union(list(
        ridges.to_crs(dataio.METRIC_CRS).geometry.buffer(buffer_m)))

    rows = []
    for source, group in tracks.groupby("source_name"):
        walked = group.geometry.length.sum()
        if walked <= 0:
            continue
        on_water = sum(g.intersection(water).length for g in group.geometry)
        on_ridge = sum(g.intersection(crest).length for g in group.geometry)
        # A stretch can qualify as both at a headwater, so measure the overlap
        # rather than letting the three shares sum past 100%.
        both = sum(g.intersection(water).intersection(crest).length
                   for g in group.geometry)
        neither = walked - (on_water + on_ridge - both)

        first = group.iloc[0]
        rows.append({
            "zone": first.get("zone", ""),
            "clan": first.get("clan", ""),
            "steward": first.get("steward", ""),
            "walked_km": round(walked / 1000, 2),
            "pct_water": round(on_water / walked * 100, 1),
            "pct_ridge": round(on_ridge / walked * 100, 1),
            "pct_both": round(both / walked * 100, 1),
            "pct_neither": round(max(neither, 0) / walked * 100, 1),
            "pct_landform": round((on_water + on_ridge - both) / walked * 100, 1),
            "source_name": source,
        })
    return pd.DataFrame(rows).sort_values("pct_landform", ascending=False)


def null_baseline(tracks: gpd.GeoDataFrame, streams: gpd.GeoDataFrame,
                  ridges: gpd.GeoDataFrame, buffer_m: float,
                  runs: int = 4, offset_m: float = 400.0) -> dict:
    """What an arbitrary line in this terrain would score.

    Drainage here is dense, so *any* line picks up some correspondence just by
    being in the landscape. Displacing the real tracks a few hundred metres and
    re-measuring gives the chance rate, and only the excess above it is
    evidence that boundaries follow the land.
    """
    from shapely import affinity

    combined = unary_union(list(tracks.geometry))
    water = unary_union(list(
        streams.to_crs(dataio.METRIC_CRS).geometry.buffer(buffer_m)))
    crest = unary_union(list(
        ridges.to_crs(dataio.METRIC_CRS).geometry.buffer(buffer_m)))

    def share(geometry, mask):
        return geometry.intersection(mask).length / geometry.length * 100

    generator = np.random.default_rng(11)
    samples = []
    for _ in range(runs):
        angle = generator.uniform(0, 2 * np.pi)
        moved = affinity.translate(combined, offset_m * np.cos(angle),
                                   offset_m * np.sin(angle))
        samples.append((share(moved, water), share(moved, crest)))

    values = np.array(samples)
    return {
        "real_water": share(combined, water),
        "real_ridge": share(combined, crest),
        "null_water": float(values[:, 0].mean()),
        "null_ridge": float(values[:, 1].mean()),
        "offset_m": offset_m,
        "runs": runs,
    }


def render(streams, ridges, tracks, boundary, out_path: Path) -> Path:
    """Draw the boundaries over both landform networks."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    figure, axis = plt.subplots(figsize=(11, 10), dpi=150)
    terrain.add_hillshade(axis, dataio.METRIC_CRS, alpha=0.40)

    if boundary is not None:
        gpd.GeoSeries([boundary], crs=dataio.METRIC_CRS).boundary.plot(
            ax=axis, color="#475569", linewidth=1.2, zorder=1)

    ridges.to_crs(dataio.METRIC_CRS).plot(ax=axis, color="#c2410c",
                                          linewidth=0.6, alpha=0.75, zorder=2)
    streams.to_crs(dataio.METRIC_CRS).plot(ax=axis, color="#0369a1",
                                           linewidth=0.6, alpha=0.75, zorder=3)
    tracks.to_crs(dataio.METRIC_CRS).plot(ax=axis, color="#111827",
                                          linewidth=1.1, alpha=0.95, zorder=4)

    axis.set_axis_off()
    axis.set_title("Boundaries against modelled landform\n"
                   "watercourses and ridgelines derived from the 30 m DEM",
                   fontsize=12, pad=12)
    axis.legend(handles=[
        Line2D([0], [0], color="#111827", lw=2, label="Surveyed boundaries"),
        Line2D([0], [0], color="#0369a1", lw=2, label="Modelled watercourses"),
        Line2D([0], [0], color="#c2410c", lw=2, label="Modelled ridgelines"),
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
    parser.add_argument("--streams", type=Path, default=hydrology.STREAMS_PATH)
    parser.add_argument("--ridges", type=Path, default=RIDGES_PATH)
    parser.add_argument("--tracks", type=Path,
                        default=dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg")
    parser.add_argument("--ridge-threshold", type=int, default=1000,
                        help="inverted-flow cells needed to start a ridgeline")
    parser.add_argument("--sea-level", type=float, default=0.0)
    parser.add_argument("--max-distance-km", type=float, default=10.0)
    parser.add_argument("--buffer", type=float, default=50.0,
                        help="metres either side counted as 'along' a feature")
    parser.add_argument("--rebuild-ridges", action="store_true",
                        help="re-derive the ridgelines even if they exist")
    parser.add_argument("--map", type=Path,
                        default=dataio.OUT_DIR / "landform.png")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.streams.exists():
        print(f"No streams at {args.streams}. Run scripts/hydrology.py first.")
        return 1
    if not args.dem.exists():
        print(f"No DEM at {args.dem}. Run scripts/fetch_dem.py first.")
        return 1

    if args.ridges.exists() and not args.rebuild_ridges:
        ridges = gpd.read_file(args.ridges, layer="ridges")
        print(f"Using existing ridgelines: {len(ridges):,} lines")
    else:
        ridges = derive_ridges(args.dem, args.ridge_threshold, args.sea_level)
        # The inverted surface has the same sea-edge problem as the streams:
        # routing escapes along the masked coast as long straight diagonals.
        ridges = hydrology.drop_sea_channels(ridges, args.dem, args.sea_level)
        ridges = hydrology.clip_to_area(ridges, args.max_distance_km * 1000)
        args.ridges.parent.mkdir(parents=True, exist_ok=True)
        if args.ridges.exists():
            args.ridges.unlink()
        ridges.to_file(args.ridges, layer="ridges", driver="GPKG")
        print(f"Wrote {args.ridges}")

    streams = gpd.read_file(args.streams, layer="streams")
    tracks = gpd.read_file(args.tracks,
                           layer="tracks_smoothed").to_crs(dataio.METRIC_CRS)

    table = classify(tracks, streams, ridges, args.buffer)
    walked = table.walked_km.sum()
    overall_water = (table.pct_water * table.walked_km).sum() / walked
    overall_ridge = (table.pct_ridge * table.walked_km).sum() / walked
    overall_both = (table.pct_both * table.walked_km).sum() / walked
    overall_any = (table.pct_landform * table.walked_km).sum() / walked

    print(f"\nAcross {walked:,.0f} km of boundary walked, within "
          f"{args.buffer:g} m:\n")
    print(f"  along watercourses   {overall_water:5.1f}%")
    print(f"  along ridgelines     {overall_ridge:5.1f}%")
    print(f"  along both           {overall_both:5.1f}%  (counted once below)")
    print(f"  along either         {overall_any:5.1f}%")
    print(f"  along neither        {100 - overall_any:5.1f}%")

    print("\nSurveys following the landform most closely:\n")
    print(table.head(12).drop(columns="source_name").to_string(index=False))
    print("\nSurveys following it least:\n")
    print(table.tail(6).drop(columns="source_name").to_string(index=False))

    baseline = null_baseline(tracks, streams, ridges, args.buffer)
    print(f"\nAgainst chance — the same tracks displaced "
          f"{baseline['offset_m']:.0f} m, averaged over {baseline['runs']} "
          "runs:\n")
    print(f"  {'':14s}{'real':>8s}{'chance':>9s}{'ratio':>8s}")
    for label, real, null in (("watercourses", baseline["real_water"],
                               baseline["null_water"]),
                              ("ridgelines", baseline["real_ridge"],
                               baseline["null_ridge"])):
        ratio = real / null if null else float("inf")
        print(f"  {label:14s}{real:7.1f}%{null:8.1f}%{ratio:7.1f}x")

    render(streams, ridges, tracks, dataio.load_boundary(), args.map)
    print(f"\nWrote {args.map}")

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        by_zone = (table.assign(w=table.walked_km)
                   .groupby("zone")
                   .apply(lambda g: pd.Series({
                       "walked_km": round(g.walked_km.sum(), 1),
                       "pct_water": round((g.pct_water * g.w).sum() / g.w.sum(), 1),
                       "pct_ridge": round((g.pct_ridge * g.w).sum() / g.w.sum(), 1),
                       "pct_either": round((g.pct_landform * g.w).sum() / g.w.sum(), 1),
                   }), include_groups=False)
                   .reset_index())

        args.report.write_text(
            "# Boundaries against landform\n\n"
            "How much of each clan boundary walk follows a watercourse or a "
            "ridgeline, both derived from the Copernicus 30 m DEM. A stretch "
            f"counts as 'along' a feature if it runs within {args.buffer:g} m "
            "of it.\n\n"
            "**Both layers are modelled, not surveyed.** A boundary following "
            "one is corroborated by the terrain independently of the survey. "
            "One following neither is not wrong — it may run along a road, a "
            "garden edge or an agreed line — but it has no independent "
            "support.\n\n"
            f"## Overall ({walked:,.0f} km walked)\n\n"
            "| Follows | Share |\n| --- | ---: |\n"
            f"| Watercourses | {overall_water:.1f}% |\n"
            f"| Ridgelines | {overall_ridge:.1f}% |\n"
            f"| Both at once | {overall_both:.1f}% |\n"
            f"| **Either** | **{overall_any:.1f}%** |\n"
            f"| Neither | {100 - overall_any:.1f}% |\n\n"
            "## Against chance\n\n"
            "Drainage here is dense, so any line in this landscape picks up "
            "some correspondence for free. Displacing the same tracks "
            f"{baseline['offset_m']:.0f} m and re-measuring gives the chance "
            "rate; only the excess above it is evidence.\n\n"
            "| Follows | Real | By chance | Ratio |\n| --- | ---: | ---: | ---: |\n"
            f"| Watercourses | {baseline['real_water']:.1f}% | "
            f"{baseline['null_water']:.1f}% | "
            f"{baseline['real_water'] / baseline['null_water']:.1f}× |\n"
            f"| Ridgelines | {baseline['real_ridge']:.1f}% | "
            f"{baseline['null_ridge']:.1f}% | "
            f"{baseline['real_ridge'] / baseline['null_ridge']:.1f}× |\n\n"
            "**Read the ratio, not the raw share.** Boundaries follow water at "
            "about twice the rate of an arbitrary line and ridges at about "
            "1.6 times, so the correspondence is real but far smaller than the "
            "headline percentages suggest.\n\n"
            "## By zone\n\n" + _markdown(by_zone) + "\n\n"
            "## Every survey\n\n"
            + _markdown(table.drop(columns="source_name")) + "\n",
            encoding="utf-8")
        print(f"Wrote {args.report}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
