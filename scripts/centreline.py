"""A central line through a thicket of walked track.

Where a steward has quartered the same ground over and over there is no
single recorded line to follow, and a straight chord across it says the
boundary is somewhere nobody walked. Neither is true. The line that is
true is the middle of the walking.

Taken as the medial axis of the corridor the walking occupies: buffer the
tracks, take the Voronoi diagram of the corridor's own outline, keep the
ridges that lie inside it, and walk the shortest path along them between
the two points where the boundary enters and leaves.
"""
from __future__ import annotations

import networkx as nx
import numpy as np
from scipy.spatial import Voronoi
from shapely.geometry import LineString, Point
from shapely.ops import unary_union


def _densify(ring, step: float):
    out = []
    length = ring.length
    n = max(int(length / step), 8)
    for i in range(n):
        p = ring.interpolate(i / n, normalized=True)
        out.append((p.x, p.y))
    return out


def centreline(tracks, entry: Point, exit_: Point,
               width: float = 22.0, step: float = 6.0):
    """The middle of `tracks`, from `entry` to `exit_`."""
    corridor = unary_union([t.buffer(width) for t in tracks])
    if corridor.geom_type == "MultiPolygon":
        corridor = max(corridor.geoms, key=lambda g: g.area)

    points = _densify(corridor.exterior, step)
    for hole in corridor.interiors:
        points += _densify(hole, step)
    diagram = Voronoi(np.array(points))

    inner = corridor.buffer(-0.5)
    graph = nx.Graph()
    for (a, b) in diagram.ridge_vertices:
        if a < 0 or b < 0:
            continue
        pa = tuple(diagram.vertices[a])
        pb = tuple(diagram.vertices[b])
        edge = LineString([pa, pb])
        if not inner.contains(edge):
            continue
        graph.add_edge(pa, pb, weight=edge.length)

    if not graph.number_of_nodes():
        raise ValueError("no medial axis found inside the corridor")

    def nearest(point):
        return min(graph.nodes, key=lambda n: (n[0] - point.x) ** 2
                   + (n[1] - point.y) ** 2)

    start, finish = nearest(entry), nearest(exit_)
    # The axis can come in several pieces; work in the one holding both.
    if not nx.has_path(graph, start, finish):
        for piece in nx.connected_components(graph):
            sub = graph.subgraph(piece)
            if sub.number_of_nodes() < 4:
                continue
            s = min(sub.nodes, key=lambda n: (n[0] - entry.x) ** 2
                    + (n[1] - entry.y) ** 2)
            f = min(sub.nodes, key=lambda n: (n[0] - exit_.x) ** 2
                    + (n[1] - exit_.y) ** 2)
            if nx.has_path(sub, s, f):
                graph, start, finish = sub, s, f
                break
        else:
            raise ValueError("entry and exit are not joined in the axis")

    path = nx.shortest_path(graph, start, finish, weight="weight")
    line = LineString([entry.coords[0]] + path + [exit_.coords[0]])

    # The medial axis is jagged where the corridor outline is. Resample and
    # average, the same way the tracks themselves are smoothed.
    n = max(int(line.length / 10), 4)
    pts = [line.interpolate(i / n, normalized=True) for i in range(n + 1)]
    xs = np.array([p.x for p in pts])
    ys = np.array([p.y for p in pts])
    k = np.ones(3) / 3
    xs[1:-1] = np.convolve(xs, k, mode="same")[1:-1]
    ys[1:-1] = np.convolve(ys, k, mode="same")[1:-1]
    return LineString(np.column_stack([xs, ys])).simplify(1.5)
