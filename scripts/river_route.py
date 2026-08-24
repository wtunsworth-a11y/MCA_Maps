#!/usr/bin/env python3
"""Route a gap along the river instead of straight across it.

Where the field says a boundary follows a river that cannot be walked, a
straight line between the two ends is the wrong shape — the river bends and
the boundary bends with it. This traces the modelled drainage between the two
ends instead.

**The result is modelled, not surveyed.** The drainage comes from a 30 m DEM
(§4.11), so the line is as good as that model and no better: it will sit
within a pixel or two of the real channel on a well-incised river and can
wander on a flat one. It is written as its own `river_routed` kind, kept apart
from walked line and from straight-line inference alike, and every map and
document that shows it says where it came from.

It is offered because the alternative is worse. A straight line across a
kilometre of river claims a boundary nobody walked *and* a shape the river
does not have; this claims a boundary nobody walked but at least the shape the
terrain says the water takes.

Usage:
    python scripts/river_route.py --clan Manuvoora --steward Egobeyas --gap 1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import closure  # noqa: E402
import dataio  # noqa: E402
import polygons as polygon_tools  # noqa: E402

STREAMS_PATH = dataio.REPO_ROOT / "data" / "reference" / "hydro" / "streams.gpkg"


def _graph(streams: gpd.GeoDataFrame):
    """The stream network as a weighted graph of its own vertices."""
    import networkx as nx

    graph = nx.Graph()
    for geometry in streams.geometry:
        if geometry is None or geometry.is_empty:
            continue
        for line in (geometry.geoms if hasattr(geometry, "geoms")
                     else [geometry]):
            coords = [tuple(round(v, 2) for v in c[:2]) for c in line.coords]
            for first, second in zip(coords, coords[1:]):
                if first == second:
                    continue
                weight = ((first[0] - second[0]) ** 2
                          + (first[1] - second[1]) ** 2) ** 0.5
                graph.add_edge(first, second, weight=weight)
    return graph


def route(gap, streams: gpd.GeoDataFrame, max_snap: float = 400.0):
    """The river path between a gap's two ends, or None if there isn't one.

    Returns `(line, detail)`. `detail` records how far each end had to be
    snapped to reach the modelled channel and how much longer the routed line
    is than the straight one — both are how a reader judges whether to trust
    it.
    """
    import networkx as nx
    from shapely.geometry import LineString

    start = tuple(gap.coords[0][:2])
    end = tuple(gap.coords[-1][:2])

    window = gap.buffer(max(gap.length, 1000.0))
    nearby = streams[streams.intersects(window)]
    if nearby.empty:
        return None, {"reason": "no modelled watercourse near this gap"}

    graph = _graph(nearby)
    if graph.number_of_nodes() < 2:
        return None, {"reason": "modelled watercourse too sparse here"}

    nodes = list(graph.nodes)

    def nearest(point):
        best, best_distance = None, None
        for node in nodes:
            distance = ((node[0] - point[0]) ** 2
                        + (node[1] - point[1]) ** 2) ** 0.5
            if best_distance is None or distance < best_distance:
                best, best_distance = node, distance
        return best, best_distance

    from_node, from_snap = nearest(start)
    to_node, to_snap = nearest(end)
    if max(from_snap, to_snap) > max_snap:
        return None, {"reason": f"nearest modelled channel is "
                                f"{max(from_snap, to_snap):.0f} m away, "
                                f"beyond the {max_snap:.0f} m limit",
                      "snap_m": round(max(from_snap, to_snap))}

    try:
        path = nx.shortest_path(graph, from_node, to_node, weight="weight")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None, {"reason": "the two ends are not connected along the "
                                "modelled drainage"}

    coords = [start] + [tuple(p) for p in path] + [end]
    line = LineString(coords)
    return line, {
        "straight_km": round(gap.length / 1000, 2),
        "routed_km": round(line.length / 1000, 2),
        "longer_by": round(line.length / gap.length, 2) if gap.length else None,
        "snap_start_m": round(from_snap),
        "snap_end_m": round(to_snap),
    }


def parts_of(frame: gpd.GeoDataFrame) -> list:
    out = []
    for geometry in frame.geometry:
        if geometry is None:
            continue
        out.extend(geometry.geoms if hasattr(geometry, "geoms") else [geometry])
    return [p for p in out if p.length > 0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clan", required=True)
    parser.add_argument("--steward", default=None)
    parser.add_argument("--gap", type=int, required=True,
                        help="which numbered gap, as shown by gap_map.py")
    parser.add_argument("--gpkg", type=Path,
                        default=dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg")
    args = parser.parse_args(argv)

    tracks = gpd.read_file(args.gpkg,
                           layer="tracks_smoothed").to_crs(dataio.METRIC_CRS)
    tracks = dataio.publishable(tracks, quiet=True)
    tracks["_unit"] = dataio.survey_group(tracks)
    match = tracks[tracks.clan.astype(str).str.lower() == args.clan.lower()]
    if match.empty:
        print(f"No clan matching {args.clan!r}.")
        return 1
    group = tracks[tracks._unit == match._unit.iloc[0]]
    if args.steward:
        group = group[group.steward.astype(str).str.lower()
                      .str.contains(args.steward.lower())]

    built = polygon_tools.survey_polygon(parts_of(group), 25.0, 0.50, 0.10)
    bridges = sorted((built.get("bridges") or []), key=lambda b: -b.length)
    if not 1 <= args.gap <= len(bridges):
        print(f"Gap {args.gap} does not exist; there are {len(bridges)}.")
        return 1
    gap = bridges[args.gap - 1]

    if not STREAMS_PATH.exists():
        print("No modelled drainage. Run scripts/hydrology.py first.")
        return 1
    streams = gpd.read_file(STREAMS_PATH).to_crs(dataio.METRIC_CRS)

    line, detail = route(gap, streams)
    if line is None:
        print(f"Gap {args.gap} cannot be routed along the river: "
              f"{detail.get('reason')}")
        return 1

    print(f"Gap {args.gap} routed along the modelled river:")
    for key, value in detail.items():
        print(f"  {key:14s} {value}")
    print("\nThis line is modelled from the 30 m DEM, not surveyed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
