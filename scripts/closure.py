#!/usr/bin/env python3
"""Work out which clan boundaries close into a polygon, and which nearly do.

A boundary is rarely a single track. Surveyors walk it in several sessions, so
one survey holds a handful of track parts that together should ring the land.
Closure therefore has to be judged per survey, after chaining those parts —
looking at any one track in isolation says nothing.

Parts are joined where their ends fall within a snapping tolerance of each
other (tracks recorded on different days never share an exact coordinate).
That gives each survey a shape:

* **Closed** — the parts chain into a loop with no loose ends.
* **Near closure** — one chain with two loose ends, and the straight-line gap
  between them is under a set share of the distance walked (10% by default).
* **Open** — one chain, but the gap is wider than that.
* **Fragmented** — the parts do not chain into a single run, so there is no
  meaningful pair of "open ends" to measure.

Because the closed/open split moves with the snapping tolerance, the report
also shows how the totals shift across a range of tolerances.

Usage:
    python scripts/closure.py
    python scripts/closure.py --tolerance 50 --threshold 0.15
    python scripts/closure.py --report output/closure_report.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString
from shapely.ops import polygonize, unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402
import smooth_tracks  # noqa: E402

DEFAULT_TOLERANCE_M = 25.0
DEFAULT_THRESHOLD = 0.10
SENSITIVITY_TOLERANCES = (10.0, 25.0, 50.0, 100.0)


class _Groups:
    """Minimal union-find, used to cluster endpoints and connect parts."""

    def __init__(self):
        self.parent: dict = {}

    def add(self, item):
        self.parent.setdefault(item, item)

    def find(self, item):
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != root:
            self.parent[item], item = root, self.parent[item]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _cluster_endpoints(endpoints: list[tuple[float, float]], tolerance: float):
    """Group endpoints that sit within tolerance of each other."""
    groups = _Groups()
    for index in range(len(endpoints)):
        groups.add(index)
    for i in range(len(endpoints)):
        xi, yi = endpoints[i]
        for j in range(i + 1, len(endpoints)):
            xj, yj = endpoints[j]
            if (xi - xj) ** 2 + (yi - yj) ** 2 <= tolerance ** 2:
                groups.union(i, j)
    return [groups.find(i) for i in range(len(endpoints))]


def analyse_survey(parts: list, tolerance: float, threshold: float,
                   max_spur: float = 0.10,
                   min_enclosure: float = 0.50,
                   derived: list | None = None) -> dict:
    """Classify one survey's track parts as closed, near, open or fragmented.

    Surveyors walk in to where the boundary starts and out again at the end,
    so a survey is often a ring or a line with short dead-end spurs hanging
    off it. Those spurs are pruned first — up to `max_spur` of the total
    distance — otherwise every one of them would read as an extra "open end"
    and hide the shape underneath.
    """
    walked = [p for p in parts if p is not None and p.length > 0]
    derived = [d for d in (derived or []) if d is not None and d.length > 0]
    parts = walked + derived
    if not parts:
        return {"status": "empty", "length_m": 0.0, "gap_m": None,
                "ratio": None, "parts": 0, "components": 0}

    # Derived segments shape the boundary but are not walked distance, so the
    # length reported is the walk and the geometry worked on is everything.
    walked_length = sum(p.length for p in walked)
    total_length = sum(p.length for p in parts)

    # Every part contributes its two ends; clustering them tells us which parts
    # meet, and each part becomes an edge between two clustered nodes.
    endpoints = []
    for part in parts:
        endpoints.append(part.coords[0][:2])
        endpoints.append(part.coords[-1][:2])
    labels = _cluster_endpoints(endpoints, tolerance)

    positions: dict = {}
    for index, label in enumerate(labels):
        positions.setdefault(label, endpoints[index])

    edges = [{"a": labels[2 * i], "b": labels[2 * i + 1],
              "length": parts[i].length, "live": True}
             for i in range(len(parts))]

    _prune_spurs(edges, max_spur * total_length)
    live = [e for e in edges if e["live"]]
    if not live:
        live = edges
    spur_m = sum(e["length"] for e in edges if not e["live"])
    ring_length = sum(e["length"] for e in live)

    chains = _chains(live, positions)
    result = {"length_m": walked_length, "parts": len(walked),
              "derived_m": round(total_length - walked_length, 1),
              "ring_m": ring_length, "spur_m": round(spur_m, 1),
              "components": len(chains), "gap_m": None, "ratio": None,
              "area_ha": None}

    # Whether the walk encloses ground is a geometric question, not a
    # connectivity one: walking a line out and back makes a cycle in the graph
    # but rings nothing. Snap the ends together, see what area the tracks
    # actually enclose, and compare it with what they enclose once the closing
    # step has drawn its lines. If those lines add nothing, they were not
    # carrying the boundary. `closes_on_its_own` has the reasoning and the
    # measurements; the same call decides the polygon layer's `surveyed`, so
    # this report and that layer cannot disagree.
    snapped = _snapped_lines(parts, positions, labels)
    enclosed = _enclosed_shape(snapped)
    bridges, _ = bridges_for(chains)
    bridged = _enclosed_shape(snapped + bridges) if bridges else enclosed
    if closes_on_its_own(enclosed, bridged, min_enclosure):
        result["status"] = "closed"
        result["gap_m"] = 0.0
        result["ratio"] = 0.0
        result["area_ha"] = round(enclosed.area / 1e4, 1)
        return result

    # The gap to close is the straight-line distance still to be walked to
    # turn the recorded pieces into one closed ring. For a survey in a single
    # piece that is exactly the distance between its two open ends — the
    # definition asked for — and it extends naturally to a survey recorded in
    # several pieces, where every join counts.
    gap = _closing_gap(chains)
    result["gap_m"] = gap
    result["ratio"] = gap / ring_length if ring_length else None

    if result["ratio"] is not None and result["ratio"] <= threshold:
        result["status"] = "near"
    else:
        result["status"] = "open"

    if len(chains) > 1:
        result["detail"] = f"{len(chains)} disconnected pieces"
    return result


def _chains(edges: list[dict], positions: dict) -> list[dict]:
    """Reduce the live edges to connected pieces, each with its two open ends.

    A piece that already forms a loop has no open ends and is marked closed.
    A piece with more than two open ends keeps the pair furthest apart, which
    is the span the rest of the ring has to reach around.
    """
    groups = _Groups()
    for edge in edges:
        groups.add(edge["a"])
        groups.add(edge["b"])
    for edge in edges:
        groups.union(edge["a"], edge["b"])

    members: dict = {}
    for edge in edges:
        members.setdefault(groups.find(edge["a"]), []).append(edge)

    chains = []
    for root, group_edges in members.items():
        degree: dict = {}
        for edge in group_edges:
            degree[edge["a"]] = degree.get(edge["a"], 0) + 1
            degree[edge["b"]] = degree.get(edge["b"], 0) + 1
        loose = [n for n, c in degree.items() if c == 1]
        length = sum(e["length"] for e in group_edges)

        if len(loose) < 2:
            # A piece with no free ends walks back over itself. It encloses
            # nothing (that was already tested geometrically), so span it by
            # its two most distant nodes instead.
            nodes = list({n for e in group_edges for n in (e["a"], e["b"])})
            loose = _furthest_pair(nodes, positions) if len(nodes) >= 2 else nodes * 2
        if len(loose) > 2:
            best, pair = -1.0, (loose[0], loose[1])
            for i in range(len(loose)):
                for j in range(i + 1, len(loose)):
                    x1, y1 = positions[loose[i]]
                    x2, y2 = positions[loose[j]]
                    d = (x1 - x2) ** 2 + (y1 - y2) ** 2
                    if d > best:
                        best, pair = d, (loose[i], loose[j])
            loose = list(pair)
        chains.append({"ends": [positions[n] for n in loose],
                       "closed": False, "length": length})
    return chains


def _snapped_lines(parts: list, positions: dict, labels: list) -> list:
    """The tracks with their ends pulled onto the clustered nodes."""
    snapped = []
    for index, part in enumerate(parts):
        coordinates = [tuple(c[:2]) for c in part.coords]
        coordinates[0] = positions[labels[2 * index]]
        coordinates[-1] = positions[labels[2 * index + 1]]
        if len({coordinates[0], *coordinates}) >= 2:
            snapped.append(LineString(coordinates))
    return snapped


def _enclosed_shape(lines: list, min_share: float = 0.02):
    """Every substantial area the lines enclose, not just the biggest one.

    All of them, because a clan can hold more than one parcel and the question
    here is how much ground the tracks ring in total. Slivers below
    `min_share` of the largest are the incidental loops where a track crosses
    itself, and are dropped.
    """
    if not lines:
        return None
    try:
        rings = [p for p in polygonize(unary_union(lines)) if p.area > 0]
    except Exception:
        return None
    if not rings:
        return None
    largest = max(p.area for p in rings)
    return unary_union([p for p in rings if p.area >= largest * min_share])


def _furthest_pair(nodes: list, positions: dict) -> list:
    best, pair = -1.0, [nodes[0], nodes[-1]]
    for i in range(len(nodes)):
        x1, y1 = positions[nodes[i]]
        for j in range(i + 1, len(nodes)):
            x2, y2 = positions[nodes[j]]
            d = (x1 - x2) ** 2 + (y1 - y2) ** 2
            if d > best:
                best, pair = d, [nodes[i], nodes[j]]
    return pair


def _distance(a, b) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _tour_cost(order: list[tuple[int, int]], ends: list) -> float:
    """Total straight-line distance bridging an ordered, oriented ring."""
    total = 0.0
    for position, (index, flip) in enumerate(order):
        exit_point = ends[index][1 - flip]
        next_index, next_flip = order[(position + 1) % len(order)]
        total += _distance(exit_point, ends[next_index][next_flip])
    return total


def order_chains(chains: list[dict], passes: int = 200) -> list[tuple[int, int]]:
    """Decide what order to join the recorded pieces in, and which way round.

    A survey arrives as several disconnected pieces, because the receiver was
    switched off at the end of one day's walk and on again somewhere else.
    Joining them into a ring is two decisions: the order to visit the pieces
    in, and **which end of each piece to enter by** — that is, whether to
    take the piece forwards or reversed.

    Get the orientation wrong and the bridges cross each other, producing a
    bow-tie: a figure-of-eight that encloses two small lobes where the real
    boundary encloses one large area. Tuoko showed this plainly — two straight
    lines crossing in the middle of the clan's land, and an area that was the
    sum of two triangles rather than the ground walked around.

    So this is a travelling-salesman tour over the pieces, and it is solved
    the way those are: nearest-neighbour to start, then 2-opt, which reverses
    a run of pieces whenever that shortens the bridging. In Euclidean space a
    tour that crosses itself is never the shortest one, so a 2-opt local
    optimum has no crossing bridges left — the bow-tie unties itself.

    Returns `[(chain index, entered at end 0 or 1), ...]` in ring order.
    """
    count = len(chains)
    ends = [c["ends"] for c in chains]
    if count <= 1:
        return [(0, 0)] if count else []

    # Nearest open end first, which is where this started and remains a good
    # place to begin from.
    order = [(0, 0)]
    used = {0}
    while len(order) < count:
        index, flip = order[-1]
        cursor = ends[index][1 - flip]
        best = None
        for candidate in range(count):
            if candidate in used:
                continue
            for entry in (0, 1):
                distance = _distance(cursor, ends[candidate][entry])
                if best is None or distance < best[0]:
                    best = (distance, candidate, entry)
        order.append((best[1], best[2]))
        used.add(best[1])

    # 2-opt: reversing a run of pieces flips each one's direction as well as
    # their order, which is exactly the move that unties a crossing.
    cost = _tour_cost(order, ends)
    for _ in range(passes):
        improved = False
        for i in range(count):
            for j in range(i + 1, count):
                candidate = (order[:i]
                             + [(k, 1 - f) for k, f in reversed(order[i:j + 1])]
                             + order[j + 1:])
                candidate_cost = _tour_cost(candidate, ends)
                if candidate_cost < cost - 1e-6:
                    order, cost, improved = candidate, candidate_cost, True
        if not improved:
            break
    return order


def loose_end_bridges(parts: list, tolerance: float, max_spur: float = 0.10):
    """Join the recorded pieces by their nearest open ends.

    The earlier method reduced each connected piece to two designated ends and
    then toured between those. That joins pieces in the order they were
    *recorded* rather than by what is closest on the ground, and where a piece
    has more than two loose ends it took the furthest-apart pair — so a 21 km
    piece of Manuvoora was presented to the tour as something with ends 8.3 km
    apart, and the ring had to bridge accordingly.

    This works on the loose ends themselves. Every end that nothing else joins
    is a candidate, and the shortest available join is taken first: pieces are
    connected to their nearest neighbour until the network is in one piece,
    then the remaining ends are paired nearest-first to close the ring.

    Direction stops mattering, which is the other half of the problem. There
    is no "start" and "end" to get backwards — an end is an end, and a line
    recorded in reverse joins exactly as well as one recorded forwards.

    **This is not what the pipeline uses, and the measurements say why.**
    Tested across all 49 surveys it more than halves the bridging — 273.6 km
    down to 127.2 km — and destroys the boundary doing it. It encloses less
    ground on 48 of the 49, and Egobeyas Kuarisi's walk goes from 968 ha to
    nothing at all.

    The reason is that the nearest pair of open ends is usually the two ends
    of the same out-and-back leg. Joining those closes a small loop and leaves
    the outer ring open, so the walk rings nothing: Rondi came out as 428
    slivers totalling 5 ha in place of 1,563 ha. Shortest total bridging and a
    boundary that encloses the land are different objectives, and where they
    disagree the long joins are the ones doing the work.

    Kept because the result is worth having on the record, and because the
    defect it was written to fix is real — see `_chains`, which hands the tour
    the *furthest-apart* pair of a component's loose ends.

    Returns `(bridges, total_length)`.
    """
    from shapely.geometry import LineString

    parts = [p for p in parts if p is not None and p.length > 0]
    if len(parts) < 2:
        return [], 0.0

    endpoints = []
    for part in parts:
        endpoints.append(part.coords[0][:2])
        endpoints.append(part.coords[-1][:2])
    labels = _cluster_endpoints(endpoints, tolerance)
    positions: dict = {}
    for index, label in enumerate(labels):
        positions.setdefault(label, endpoints[index])

    edges = [{"a": labels[2 * i], "b": labels[2 * i + 1],
              "length": parts[i].length, "live": True}
             for i in range(len(parts))]
    _prune_spurs(edges, max_spur * sum(p.length for p in parts))
    live = [e for e in edges if e["live"]] or edges

    groups = _Groups()
    for edge in live:
        groups.add(edge["a"])
        groups.add(edge["b"])
        groups.union(edge["a"], edge["b"])

    degree: dict = {}
    for edge in live:
        degree[edge["a"]] = degree.get(edge["a"], 0) + 1
        degree[edge["b"]] = degree.get(edge["b"], 0) + 1
    open_ends = [node for node, count in degree.items() if count == 1]

    bridges, total = [], 0.0

    def join(first, second):
        nonlocal total
        line = LineString([positions[first], positions[second]])
        bridges.append(line)
        total += line.length
        groups.union(first, second)
        degree[first] = degree.get(first, 0) + 1
        degree[second] = degree.get(second, 0) + 1

    # Shortest join first, always between pieces that are not yet connected.
    while True:
        available = [n for n in open_ends if degree.get(n, 0) == 1]
        best = None
        for i in range(len(available)):
            for j in range(i + 1, len(available)):
                first, second = available[i], available[j]
                if groups.find(first) == groups.find(second):
                    continue
                x1, y1 = positions[first]
                x2, y2 = positions[second]
                distance = ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5
                if best is None or distance < best[0]:
                    best = (distance, first, second)
        if best is None:
            break
        join(best[1], best[2])

    # One piece now. Close the ring on whatever ends are still open, again
    # taking the shortest join each time.
    while True:
        available = [n for n in open_ends if degree.get(n, 0) == 1]
        if len(available) < 2:
            break
        best = None
        for i in range(len(available)):
            for j in range(i + 1, len(available)):
                x1, y1 = positions[available[i]]
                x2, y2 = positions[available[j]]
                distance = ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5
                if best is None or distance < best[0]:
                    best = (distance, available[i], available[j])
        join(best[1], best[2])

    return bridges, total


def bridges_for(chains: list[dict]):
    """Straight lines joining the open pieces into one ring, and their length.

    The order the pieces are joined in, and which way round each one is taken,
    comes from `order_chains` — get the direction wrong and the bridges cross,
    giving a bow-tie that encloses two slivers instead of the ground actually
    walked around.
    """
    open_chains = [c for c in chains if not c["closed"] and len(c["ends"]) == 2]
    if not open_chains:
        return [], 0.0

    if len(open_chains) == 1:
        a, b = open_chains[0]["ends"]
        line = LineString([a, b])
        return [line], line.length

    ends = [c["ends"] for c in open_chains]
    order = order_chains(open_chains)

    bridges, total = [], 0.0
    for position, (index, flip) in enumerate(order):
        exit_point = ends[index][1 - flip]
        next_index, next_flip = order[(position + 1) % len(order)]
        entry_point = ends[next_index][next_flip]
        line = LineString([exit_point, entry_point])
        bridges.append(line)
        total += line.length
    return bridges, total




# A survey counts as closed when the closing step's lines add no more than
# this share of the ground to what the tracks enclose by themselves.
#
# The exact value decides nothing in this dataset. Measured across all 51
# surveys the shares are sharply split: six sit at 0.93 or above (four of them
# at 0.98+), and the next one down is 0.43. Anything between those two would
# sort the surveys identically. 0.10 is chosen to say what is meant — that the
# drawn lines added next to nothing — rather than to place the boundary.
CLOSED_TOLERANCE = 0.10


def closes_on_its_own(enclosed, bridged, min_enclosure: float) -> bool:
    """Do the tracks enclose the ground, or does the inference supply it?

    The test this replaces asked a different question: is the largest ring's
    perimeter at least half of everything walked? That is a question about
    distance, and it gets the answer wrong in both directions.

    It fails a closed survey for being thoroughly walked. Rondi's tracks
    enclose 1,563 ha in a single ring of 29.47 km, and the pipeline called it
    inferred and drew 12.43 km of line across it that changed the area by
    nothing at all — the bridged figure is 1,563 ha too. It failed because the
    steward walked 59 km in 62 pieces to map that 29.5 km boundary, and half
    of 59 km is 29.49 km. It missed by twenty metres, and it missed because
    the steward had walked their own land. The more ground a steward covers
    inside the boundary, the further the old rule pushed their survey from
    being called closed.

    It can also pass a survey that encloses nothing, which is why the rule it
    replaces looked at one ring rather than all of them: a mesh of slivers
    where a track crosses itself has a long perimeter and no area.

    So ask about ground instead. `enclosed` is what the tracks ring unaided;
    `bridged` is what they ring once the closing step has drawn its lines. If
    the drawn lines add no more than `CLOSED_TOLERANCE` of the ground, they
    were not carrying the boundary, and the survey is closed however the
    closing step chose to describe it. A sliver mesh fails the same test,
    because there the drawn lines supply nearly all of it.

    The share can exceed 1: a bridge that cuts a corner encloses less than the
    tracks do on their own. Asingi comes out at 1.014.

    Where a survey passes, the polygon returned is the one the tracks enclose,
    not the bridged one. Nothing inferred is kept in it.

    `min_enclosure` is honoured as a floor and can only tighten this, never
    loosen it, so a caller cannot ask for a survey to be called closed on less
    ground than the tracks actually ring.
    """
    if enclosed is None or enclosed.area <= 0:
        return False
    if bridged is None or bridged.area <= 0:
        return True
    share = enclosed.area / bridged.area
    return share >= max(1.0 - CLOSED_TOLERANCE, min_enclosure)


def _closing_gap(chains: list[dict]) -> float:
    """Straight-line distance still needed to join the pieces into one ring.

    The pieces are ordered and oriented by `order_chains`, so the figure is
    the shortest joining that ordering finds rather than the first one tried.
    It remains an upper bound on the true minimum, so a survey is never
    reported as closer to closure than it really is.
    """
    open_chains = [c for c in chains if not c["closed"] and c["ends"]]
    if not open_chains:
        return 0.0
    if len(open_chains) == 1:
        return _distance(*open_chains[0]["ends"])
    return _tour_cost(order_chains(open_chains),
                      [c["ends"] for c in open_chains])


def _count_components(edges: list[dict]) -> int:
    groups = _Groups()
    for edge in edges:
        groups.add(edge["a"])
        groups.add(edge["b"])
    for edge in edges:
        groups.union(edge["a"], edge["b"])
    nodes = {n for e in edges for n in (e["a"], e["b"])}
    return len({groups.find(n) for n in nodes})


def _prune_spurs(edges: list[dict], budget: float) -> None:
    """Drop short dead-end branches, within a total length budget.

    The budget is cumulative, not per-branch: without that, a survey made of
    many short legs can have almost all of itself pruned away one leg at a
    time, leaving a stub that trivially looks like a closed ring.
    """
    spent = 0.0
    while True:
        degree: dict = {}
        for edge in edges:
            if not edge["live"]:
                continue
            degree[edge["a"]] = degree.get(edge["a"], 0) + 1
            degree[edge["b"]] = degree.get(edge["b"], 0) + 1

        candidates = [e for e in edges if e["live"]
                      and spent + e["length"] <= budget
                      and (degree.get(e["a"], 0) == 1
                           or degree.get(e["b"], 0) == 1)
                      and e["a"] != e["b"]]
        if not candidates:
            return
        # Shortest first, so a genuine boundary leg is never taken before a
        # clearly incidental stub.
        candidates.sort(key=lambda e: e["length"])
        candidates[0]["live"] = False
        spent += candidates[0]["length"]


def _chain_gap(edges: list[dict], positions: dict) -> float:
    """Total straight-line distance needed to link disconnected chains."""
    groups = _Groups()
    for edge in edges:
        groups.add(edge["a"])
        groups.add(edge["b"])
    for edge in edges:
        groups.union(edge["a"], edge["b"])

    clusters: dict = {}
    for node in {n for e in edges for n in (e["a"], e["b"])}:
        clusters.setdefault(groups.find(node), []).append(node)

    roots = list(clusters)
    if len(roots) < 2:
        return 0.0

    total, joined = 0.0, {roots[0]}
    while len(joined) < len(roots):
        best, best_root = None, None
        for root in roots:
            if root in joined:
                continue
            for node in clusters[root]:
                x1, y1 = positions[node]
                for other in joined:
                    for node2 in clusters[other]:
                        x2, y2 = positions[node2]
                        d = ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5
                        if best is None or d < best:
                            best, best_root = d, root
        total += best or 0.0
        joined.add(best_root)
    return total


def analyse_all(gdf: gpd.GeoDataFrame, tolerance: float,
                threshold: float, max_spur: float = 0.10,
                min_length: float = 100.0,
                min_enclosure: float = 0.50) -> pd.DataFrame:
    """Run the closure test over every survey in the layer."""
    gdf = gdf.assign(_unit=dataio.survey_group(gdf))
    rows = []
    for source, group in gdf.groupby("_unit", sort=True):
        parts = []
        for geometry in group.geometry:
            if geometry is None:
                continue
            parts.extend(geometry.geoms if hasattr(geometry, "geoms")
                         else [geometry])
        outcome = analyse_survey(parts, tolerance, threshold, max_spur,
                                 min_enclosure,
                                 derived=dataio.adopted_segments(source))
        if outcome["length_m"] < min_length:
            outcome["status"] = "too short"
            outcome["detail"] = f"only {outcome['length_m']:.0f} m walked"
        first = group.iloc[0]
        stewards = sorted({str(c) for c in group.steward if str(c).strip()})
        rows.append({
            "zone": first.get("zone", ""),
            "clan": first.get("clan", ""),
            "steward": ", ".join(stewards),
            "stewards": len(stewards),
            "source_name": source,
            "tracks": outcome["parts"],
            "length_km": round(outcome["length_m"] / 1000, 2),
            "derived_km": round(outcome.get("derived_m", 0.0) / 1000, 2),
            "gap_m": None if outcome["gap_m"] is None else round(outcome["gap_m"], 1),
            "gap_pct": None if outcome["ratio"] is None else round(outcome["ratio"] * 100, 1),
            "area_ha": outcome.get("area_ha"),
            "chains": outcome.get("components", 1),
            "status": outcome["status"],
            "detail": outcome.get("detail", ""),
        })
    return pd.DataFrame(rows).sort_values(["zone", "clan", "steward"])


def _markdown(frame: pd.DataFrame) -> str:
    columns = list(frame.columns)
    lines = ["| " + " | ".join(str(c) for c in columns) + " |",
             "| " + " | ".join("---" for _ in columns) + " |"]
    for _, row in frame.iterrows():
        cells = ["" if pd.isna(row[c]) else str(row[c]) for c in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gpkg", type=Path,
                        default=dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg",
                        help="smoothed GeoPackage to analyse")
    parser.add_argument("--layer", default=smooth_tracks.SMOOTHED_LAYER,
                        help="layer within the GeoPackage")
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE_M,
                        help="metres within which two track ends count as "
                             "joined")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help="gap/length ratio counted as near closure")
    parser.add_argument("--min-enclosure", type=float, default=0.50,
                        help="share of the walk that the enclosed ring's "
                             "perimeter must account for to count as closed")
    parser.add_argument("--min-length", type=float, default=100.0,
                        help="surveys shorter than this many metres are "
                             "reported as too short to assess")
    parser.add_argument("--max-spur", type=float, default=0.10,
                        help="prune dead-end branches up to this fraction of "
                             "the survey's total walked distance")
    parser.add_argument("--report", type=Path, default=None,
                        help="write the full per-survey table here")
    args = parser.parse_args(argv)

    if not args.gpkg.exists():
        print(f"No smoothed data at {args.gpkg}.\n"
              "Run scripts/smooth_tracks.py first.")
        return 1

    gdf = gpd.read_file(args.gpkg, layer=args.layer).to_crs(dataio.METRIC_CRS)
    table = analyse_all(gdf, args.tolerance, args.threshold, args.max_spur,
                        args.min_length, args.min_enclosure)

    counts = table["status"].value_counts()
    total = len(table)
    closed = int(counts.get("closed", 0))
    near = int(counts.get("near", 0))
    open_ = int(counts.get("open", 0))
    fragmented = int(counts.get("fragmented", 0))
    too_short = int(counts.get("too short", 0))

    print(f"\n{total} surveys, joined at a {args.tolerance:g} m tolerance, "
          f"near-closure threshold {args.threshold:.0%}\n")
    print(f"  Closed polygons     {closed:3d}  ({closed / total:.0%})")
    print(f"  Near closure        {near:3d}  ({near / total:.0%})")
    print(f"  Open                {open_:3d}  ({open_ / total:.0%})")
    if fragmented:
        print(f"  Fragmented          {fragmented:3d}  ({fragmented / total:.0%})")
    if too_short:
        print(f"  Too short to assess {too_short:3d}  ({too_short / total:.0%})")
    print(f"  {'':18s}{'':3s}  ── closed or near: "
          f"{closed + near} of {total} ({(closed + near) / total:.0%})")

    by_zone = (table.assign(n=1)
               .pivot_table(index="zone", columns="status", values="n",
                            aggfunc="sum", fill_value=0))
    print("\nBy zone:\n")
    print(by_zone.to_string())

    print(f"\nSensitivity to the joining tolerance:\n")
    print(f"  {'tolerance':>10s}  {'closed':>7s}  {'near':>6s}  "
          f"{'open':>6s}  {'frag':>6s}")
    sensitivity = []
    for tolerance in SENSITIVITY_TOLERANCES:
        alt = analyse_all(gdf, tolerance, args.threshold, args.max_spur,
                          args.min_length, args.min_enclosure)
        counts_alt = alt["status"].value_counts()
        row = {"tolerance_m": tolerance,
               "closed": int(counts_alt.get("closed", 0)),
               "near": int(counts_alt.get("near", 0)),
               "open": int(counts_alt.get("open", 0)),
               "fragmented": int(counts_alt.get("fragmented", 0))}
        sensitivity.append(row)
        print(f"  {tolerance:8.0f} m  {row['closed']:7d}  {row['near']:6d}  "
              f"{row['open']:6d}  {row['fragmented']:6d}")

    if near:
        print("\nNear closure — smallest gaps first:\n")
        near_rows = (table[table.status == "near"]
                     .sort_values("gap_pct")
                     [["zone", "clan", "steward", "length_km", "gap_m",
                       "gap_pct"]])
        print(near_rows.to_string(index=False))

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            "# Boundary closure\n\n"
            f"{total} surveys, parts joined at {args.tolerance:g} m, "
            f"near-closure threshold {args.threshold:.0%}.\n\n"
            f"- **Closed polygons:** {closed}\n"
            f"- **Near closure:** {near}\n"
            f"- **Open:** {open_}\n"
            f"- **Fragmented:** {fragmented}\n\n"
            "## Sensitivity to joining tolerance\n\n"
            + _markdown(pd.DataFrame(sensitivity)) + "\n\n"
            "## Every survey\n\n" + _markdown(table) + "\n",
            encoding="utf-8")
        print(f"\nWrote {args.report}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
