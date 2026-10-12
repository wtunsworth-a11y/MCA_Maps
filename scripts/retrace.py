#!/usr/bin/env python3
"""Build the boundary by retracing the walked line, not by pairing ends.

The closing step in use chooses, for the survey as a whole, which free
ends to join so that everything strings into one ring. That makes every
chord depend on every other: Natang's 68 m repair moved a chord four
kilometres away from 803 m to 1,723 m, and nothing in the corner being
worked on could have predicted it.

This does what the reviewer asked for instead. The walked line is known.
Follow it; where it breaks, join to where it continues; and only where
nothing continues is a line drawn that nobody walked. Each break is
answered by its own nearest continuation, so repairing one cannot move
another.

Three things fall out of doing it this way rather than as a graph of
recorded parts:

* `unary_union` nodes every crossing exactly, so a line that ends on
  another line's middle is no longer invisible, and the hand-entered
  nodes for T-junctions are not needed;
* a stretch recorded twice merges into one, so duplicate saves stop
  inverting the topology;
* two stewards who walked the same boundary merge too, instead of
  arriving as two sets of fragments to be stitched.

What is enclosed is then asked of the geometry — every face the lines
bound — rather than of a single ring the survey may not form.

Usage:
    python scripts/retrace.py --clan Natang
    python scripts/retrace.py --all
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point
from shapely.ops import linemerge, polygonize, unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402
import chord_map  # noqa: E402
import polygons as polygon_tools  # noqa: E402

# How far apart two ends of one walk may be and still be the same place.
# The same 25 m the rest of the pipeline uses.
TOUCHING = 25.0

# A face smaller than this is a track crossing itself, not land.
MIN_FACE_M2 = 2_000.0


def _chains(parts: list) -> list:
    """The walked line as maximal chains, noded at every crossing."""
    merged = linemerge(unary_union([p for p in parts if p.length > 0]))
    out = merged.geoms if hasattr(merged, "geoms") else [merged]
    return [g for g in out if g.length > 0]


def weld(chains: list, tolerance: float = TOUCHING) -> list:
    """Join every end that stops within reach of a line that carries on.

    Declaring such an end "not free" is not enough — it leaves the two
    lines unconnected, and the enclosure then finds nothing. The join has
    to be drawn: from the end to the nearest point *on* the other line,
    which also puts a node there. That is the T-junction that was
    invisible to endpoint clustering, and it is what made Juaiko's and
    Natang's lobes read as dead ends.
    """
    lines = list(chains)
    for _ in range(3):
        welds = []
        network = unary_union(lines)
        for line in lines:
            for end in (Point(line.coords[0][:2]),
                        Point(line.coords[-1][:2])):
                others = [other for other in lines
                          if other is not line
                          and other.distance(end) <= tolerance]
                if not others:
                    continue
                target = min(others, key=lambda o: o.distance(end))
                onto = target.interpolate(target.project(end))
                if end.distance(onto) > 0.01:
                    welds.append(LineString([end, onto]))
        if not welds:
            break
        lines = _chains(lines + welds)
    return lines


def _free_ends(chains: list, tolerance: float = TOUCHING) -> list:
    """Points where the walked line stops and nothing carries on."""
    loose = []
    for chain in chains:
        for end in (Point(chain.coords[0][:2]),
                    Point(chain.coords[-1][:2])):
            others = [other for other in chains
                      if other is not chain and other.distance(end) <= 0.01]
            if not others:
                loose.append(end)
    return _dedupe(loose, tolerance)


def _dedupe(points: list, tolerance: float) -> list:
    out: list = []
    for point in points:
        if all(point.distance(other) > tolerance for other in out):
            out.append(point)
    return out


def joins(free: list, reach: float | None = None) -> list:
    """Join each loose end to the nearest other, nearest pair first.

    Local by construction. A join is decided by the two ends it joins and
    by nothing else in the survey, so closing one break cannot move
    another — which is the whole point of doing it this way.
    """
    remaining = list(free)
    drawn = []
    while len(remaining) >= 2:
        best = None
        for i in range(len(remaining)):
            for j in range(i + 1, len(remaining)):
                gap = remaining[i].distance(remaining[j])
                if best is None or gap < best[0]:
                    best = (gap, i, j)
        gap, i, j = best
        if reach is not None and gap > reach:
            break
        drawn.append(LineString([remaining[i], remaining[j]]))
        for index in sorted((i, j), reverse=True):
            remaining.pop(index)
    return drawn


def retrace(parts: list, derived: list | None = None) -> dict | None:
    """The boundary, retraced."""
    lines = _chains(list(parts) + list(derived or []))
    if not lines:
        return None
    lines = weld(lines)
    free = _free_ends(lines)
    drawn = joins(free)
    faces = [f for f in polygonize(unary_union(lines + drawn))
             if f.area >= MIN_FACE_M2]
    if not faces:
        return None
    land = unary_union(faces)
    walked = unary_union(lines)
    return {
        "geometry": land,
        "area_ha": land.area / 1e4,
        "walked_km": sum(line.length for line in lines) / 1000,
        "bridges": drawn,
        "gap_km": sum(line.length for line in drawn) / 1000,
        # Of the line drawn, how much is over ground nobody walked. That
        # is the only part anyone has to go back for.
        "unwalked_km": sum(
            line.length - line.intersection(walked.buffer(10)).length
            for line in drawn) / 1000,
        "faces": len(faces),
    }


def _load():
    published = gpd.read_file(dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg",
                              layer="tracks_smoothed").to_crs(dataio.METRIC_CRS)
    published = dataio.publishable(published, quiet=True)
    published["_unit"] = dataio.survey_group(published)
    return published


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clan")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)

    published = _load()
    units = sorted(set(published._unit.dropna()))
    if args.clan:
        units = [u for u in units
                 if u.lower().startswith(args.clan.lower())]
        if not units:
            print(f"No survey matching {args.clan!r}.")
            return 1
    elif not args.all:
        parser.print_help()
        return 1

    print(f"{'survey':26s} {'now':>9s} {'retraced':>9s} "
          f"{'gaps':>6s} {'km drawn':>9s} {'km unwalked':>12s}")
    total_now = total_new = 0.0
    for unit in units:
        group = published[published._unit == unit]
        parts = chord_map.parts_of(group)
        frame = polygon_tools.adopted_frame(unit)
        derived = ([] if frame is None or frame.empty
                   else list(frame.geometry))
        before = polygon_tools.survey_polygon(parts, 25.0, 0.50, 0.10,
                                              derived=derived, unit=unit)
        after = retrace(parts, derived)
        now = before["area_ha"] if before else 0.0
        new = after["area_ha"] if after else 0.0
        total_now += now
        total_new += new
        print(f"{unit:26s} {now:9.1f} {new:9.1f} "
              f"{(len(after['bridges']) if after else 0):6d} "
              f"{(after['gap_km'] if after else 0):9.2f} "
              f"{(after['unwalked_km'] if after else 0):12.2f}")
    if len(units) > 1:
        print(f"{'TOTAL':26s} {total_now:9.1f} {total_new:9.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
