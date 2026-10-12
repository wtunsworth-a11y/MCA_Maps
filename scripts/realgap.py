#!/usr/bin/env python3
"""For a chord, the smallest set of breaks that would make it unnecessary.

A chord that crosses the walked line is always wrong — there is walked
line on the other side of it, so the ground it spans is not unwalked.
That has been caught by eye each time, clan by clan, and it should not
be: it is measurable.

What this asks is the useful question. Take a chord's two ends. Allowing
the boundary to step across a break wherever two recordings stop near
each other, what is the cheapest way round, counting only the breaks and
not the walking? The answer is the real gap — the metres nobody walked —
and the chord is the difference between that and a straight line.

Ambunkol's chord 3 is 286 m. The route round the bay the steward walked
needs one step of 53 m. That is the gap; the other 233 m is walked
ground the graph could not see.

Breaks are counted two ways, because a recording can stop beside
another line as well as beside another end: end to end, and end to the
nearest point on a line it stops short of. The second is the T-junction
that endpoint clustering cannot see.

Usage:
    python scripts/realgap.py --clan Ambunkol
    python scripts/realgap.py --clan Ambunkol --gap 3
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from shapely.geometry import LineString, Point
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402
import chord_map  # noqa: E402
import closure  # noqa: E402
import polygons as polygon_tools  # noqa: E402

# How far apart two recordings may stop and still be considered a break
# the boundary could step across rather than a different part of the
# clan. Beyond this it is not a break, it is unwalked ground.
REACH = 600.0


def _nodes(parts, tolerance=25.0):
    endpoints = []
    for part in parts:
        endpoints.append(part.coords[0][:2])
        endpoints.append(part.coords[-1][:2])
    labels = closure._cluster_endpoints(endpoints, tolerance)
    positions: dict = {}
    for index, label in enumerate(labels):
        positions.setdefault(label, endpoints[index])
    return labels, positions


def routes(parts, reach: float = REACH):
    """A graph whose cost is metres nobody walked."""
    import networkx as nx

    labels, positions = _nodes(parts)
    graph = nx.Graph()
    for node, point in positions.items():
        graph.add_node(node, pos=point)
    # Walking is free.
    for index, part in enumerate(parts):
        a, b = labels[2 * index], labels[2 * index + 1]
        if a != b:
            graph.add_edge(a, b, cost=0.0, kind="walked",
                           length=part.length)
    # A break costs what it spans.
    nodes = list(positions)
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            a, b = nodes[i], nodes[j]
            gap = Point(positions[a]).distance(Point(positions[b]))
            if gap > reach:
                continue
            if graph.has_edge(a, b) and graph[a][b]["cost"] == 0:
                continue
            graph.add_edge(a, b, cost=gap, kind="break", length=gap)
    # And an end that stops beside a line, rather than beside another end,
    # can step onto it — the T-junction.
    for node, point in positions.items():
        here = Point(point)
        for index, part in enumerate(parts):
            a, b = labels[2 * index], labels[2 * index + 1]
            if node in (a, b):
                continue
            gap = part.distance(here)
            if gap > reach or gap <= 0.01:
                continue
            onto = min((a, b), key=lambda n: Point(positions[n]).distance(here))
            if graph.has_edge(node, onto) and graph[node][onto]["cost"] <= gap:
                continue
            graph.add_edge(node, onto, cost=gap, kind="break", length=gap)
    return graph, positions


def real_gap(parts, chord, reach: float = REACH):
    """The cheapest way round a chord, counting only what nobody walked."""
    import networkx as nx

    graph, positions = routes(parts, reach)
    if not graph.number_of_nodes():
        return None
    ends = [Point(chord.coords[0][:2]), Point(chord.coords[-1][:2])]
    start, finish = (min(graph.nodes,
                         key=lambda n, e=e: Point(positions[n]).distance(e))
                     for e in ends)
    if start == finish or not nx.has_path(graph, start, finish):
        return None
    path = nx.shortest_path(graph, start, finish, weight="cost")
    breaks, walked = [], 0.0
    for a, b in zip(path, path[1:]):
        edge = graph[a][b]
        if edge["kind"] == "break":
            breaks.append(LineString([positions[a], positions[b]]))
        else:
            walked += edge["length"]
    return {"breaks": breaks,
            "break_m": sum(b.length for b in breaks),
            "walked_m": walked,
            "chord_m": chord.length}


def main(argv: list[str] | None = None) -> int:
    import geopandas as gpd

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clan", required=True)
    parser.add_argument("--gap", type=int)
    parser.add_argument("--reach", type=float, default=REACH)
    args = parser.parse_args(argv)

    published = gpd.read_file(dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg",
                              layer="tracks_smoothed").to_crs(dataio.METRIC_CRS)
    published = dataio.publishable(published, quiet=True)
    published["_unit"] = dataio.survey_group(published)
    match = published[published.clan.astype(str).str.lower()
                      == args.clan.lower()]
    if match.empty:
        print(f"No clan matching {args.clan!r}.")
        return 1
    unit = match._unit.iloc[0]
    group = published[published._unit == unit]
    parts = chord_map.parts_of(group)
    frame = polygon_tools.adopted_frame(unit)
    derived = [] if frame is None or frame.empty else list(frame.geometry)
    built = polygon_tools.survey_polygon(parts, 25.0, 0.50, 0.10,
                                         derived=derived, unit=unit)
    if not built or not built["bridges"]:
        print(f"{unit} has no chords.")
        return 0
    order = sorted(built["bridges"], key=lambda b: -b.length)
    numbers = chord_map.numbering(unit, order, record=False)
    walked = unary_union(parts)

    print(f"{unit}\n")
    print(f"{'chord':>6s} {'drawn':>8s} {'crosses':>8s} "
          f"{'real gap':>9s} {'steps':>6s} {'walked instead':>15s}")
    for index, chord in enumerate(order):
        if args.gap is not None and numbers[index] != args.gap:
            continue
        found = real_gap(parts, chord, args.reach)
        crosses = "yes" if chord.crosses(walked) else ""
        if not found or found["break_m"] >= chord.length - 1:
            print(f"{numbers[index]:6d} {chord.length:8.0f} {crosses:>8s} "
                  f"{'the chord':>9s}")
            continue
        print(f"{numbers[index]:6d} {chord.length:8.0f} {crosses:>8s} "
              f"{found['break_m']:9.0f} {len(found['breaks']):6d} "
              f"{found['walked_m']:15.0f}")
        for piece in sorted(found["breaks"], key=lambda b: -b.length):
            a, b = piece.coords[0], piece.coords[-1]
            print(f"         step {piece.length:6.0f} m  "
                  f"({a[0]:.0f},{a[1]:.0f}) -> ({b[0]:.0f},{b[1]:.0f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
