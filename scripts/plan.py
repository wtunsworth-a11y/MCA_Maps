#!/usr/bin/env python3
"""An order for a clan's repairs that does not set off a cascade.

Closing a chord has moved a chord four kilometres away, twice, on two
different clans. The reason is that the chords are not objects: they are
the leftover of a solve that runs over the whole survey, so any change
to the input re-solves everything.

Two rules fall out of that, and this puts them in order.

**Settle the pieces that force invention first.** Where a piece of the
survey has fewer than two attachments, the closing step cannot enter and
leave it by ends it has, so it invents them. Those inventions are the
only chords that move. Everything else is stable. Natang's 68 m repair
moved an 803 m chord to 1,723 m because a piece hung on by one free end;
Ambunkol's three repairs moved 2,848 m of chord to 4,175 m because a
loop hangs on by none.

**Then close the breaks, and check each one.** A repair is only a repair
if nothing else moved. This applies each step in turn and reports what
happened to every other chord, so a step that pays for itself by
lengthening another is visible before it is kept rather than after.

It changes nothing. It prints the order and the arithmetic.

Usage:
    python scripts/plan.py --clan Ambunkol
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points, unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402
import chord_map  # noqa: E402
import closure  # noqa: E402
import polygons as polygon_tools  # noqa: E402
import realgap  # noqa: E402


def pieces(unit: str, parts: list, derived: list):
    """The connected pieces of a survey, as the closing step sees them."""
    all_parts = closure.extended_parts(unit, list(parts)) + list(derived)
    endpoints = []
    for part in all_parts:
        endpoints.append(part.coords[0][:2])
        endpoints.append(part.coords[-1][:2])
    labels = closure._cluster_endpoints(endpoints, 25.0)
    positions: dict = {}
    for index, label in enumerate(labels):
        positions.setdefault(label, endpoints[index])
    keep = (closure.distinct_indices(all_parts)
            if closure.approved_fix(unit, "collapse_duplicates")
            else list(range(len(all_parts))))
    edges = [{"a": labels[2 * i], "b": labels[2 * i + 1],
              "length": all_parts[i].length, "live": True, "i": i}
             for i in keep]
    closure._prune_spurs(
        edges, closure.spur_limit(unit, 0.10)
        * sum(all_parts[i].length for i in keep))
    live = [e for e in edges if e["live"]] or edges
    groups = closure._Groups()
    for edge in live:
        groups.add(edge["a"])
        groups.add(edge["b"])
    for edge in live:
        groups.union(edge["a"], edge["b"])
    held: dict = {}
    for edge in live:
        held.setdefault(groups.find(edge["a"]), []).append(edge)
    out = []
    for root, group in held.items():
        degree: dict = {}
        for edge in group:
            degree[edge["a"]] = degree.get(edge["a"], 0) + 1
            degree[edge["b"]] = degree.get(edge["b"], 0) + 1
        loose = [n for n, c in degree.items() if c == 1]
        out.append({
            "root": root,
            "length": sum(e["length"] for e in group),
            "free_ends": len(loose),
            "geometry": unary_union([all_parts[e["i"]] for e in group]),
        })
    return sorted(out, key=lambda p: -p["length"])


def attachments(piece, others, how_many: int = 2, apart: float = 300.0):
    """Where a piece comes closest to the rest, at separated places."""
    rest = unary_union([o["geometry"] for o in others])
    line = piece["geometry"]
    samples = []
    for step in range(0, 2001):
        here = line.interpolate(step / 2000, normalized=True)
        samples.append((rest.distance(here), here))
    samples.sort(key=lambda s: s[0])
    chosen, found = [], []
    for gap, here in samples:
        if any(here.distance(other) < apart for other in chosen):
            continue
        chosen.append(here)
        onto = nearest_points(here, rest)[1]
        found.append(LineString([here, onto]))
        if len(found) >= how_many:
            break
    return found


def state(unit, parts, derived):
    built = polygon_tools.survey_polygon(parts, 25.0, 0.50, 0.10,
                                         derived=derived, unit=unit)
    if not built:
        return None
    walked = unary_union(parts)
    chords = sorted(built["bridges"], key=lambda b: -b.length)
    unwalked = [c.length - c.intersection(walked.buffer(10)).length
                for c in chords]
    unwalked += [d.length - d.intersection(walked.buffer(10)).length
                 for d in derived]
    return {"area_ha": built["area_ha"],
            "chords": [round(c.length) for c in chords],
            "visits": sum(1 for u in unwalked if u > 50),
            "walk_km": sum(u for u in unwalked if u > 50) / 1000}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clan", required=True)
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
    parts = chord_map.parts_of(published[published._unit == unit])
    frame = polygon_tools.adopted_frame(unit)
    derived = [] if frame is None or frame.empty else list(frame.geometry)

    print(f"{unit}\n")
    here = state(unit, parts, derived)
    print(f"as it stands   {here['area_ha']:7.1f} ha  "
          f"{len(here['chords'])} chords {here['chords']}  "
          f"{here['visits']} visits  {here['walk_km']:.2f} km to walk\n")

    found = pieces(unit, parts, derived)
    print("pieces of the survey, and how many ends they are held on by:")
    for piece in found:
        mark = "  <-- forces the closing step to invent" \
            if piece["free_ends"] < 2 else ""
        print(f"   {piece['length']:7.0f} m   {piece['free_ends']} free "
              f"end(s){mark}")

    steps = []
    for piece in found:
        if piece["free_ends"] >= 2:
            continue
        others = [p for p in found if p is not piece]
        if not others:
            continue
        want = 2 - piece["free_ends"]
        for line in attachments(piece, others, want):
            steps.append(("attach a piece held on by "
                          f"{piece['free_ends']} end(s)", line))

    built = polygon_tools.survey_polygon(parts, 25.0, 0.50, 0.10,
                                         derived=derived, unit=unit)
    order = sorted(built["bridges"], key=lambda b: -b.length)
    numbers = chord_map.numbering(unit, order, record=False)
    walked = unary_union(parts)
    for index, chord in enumerate(order):
        if not chord.crosses(walked):
            continue
        got = realgap.real_gap(parts, chord)
        if not got or got["break_m"] >= chord.length - 1:
            continue
        for line in got["breaks"]:
            steps.append((f"the {got['break_m']:.0f} m break behind "
                          f"chord {numbers[index]}", line))

    if not steps:
        print("\nnothing to propose.")
        return 0

    print(f"\nin this order, each step measured on the whole clan:\n")
    print(f"{'#':>2s}  {'step':48s} {'ha':>8s} {'chords':>7s} "
          f"{'visits':>7s} {'km':>6s}")
    print(f"{'':2s}  {'':48s} {here['area_ha']:8.1f} "
          f"{len(here['chords']):7d} {here['visits']:7d} "
          f"{here['walk_km']:6.2f}")
    running = list(derived)
    for n, (what, line) in enumerate(steps, 1):
        running = running + [line]
        after = state(unit, parts, running)
        note = ""
        if len(after["chords"]) >= len(here["chords"]):
            note = "  no fewer chords"
        if after["walk_km"] > here["walk_km"] + 0.001:
            note += "  MORE to walk"
        print(f"{n:2d}  {what[:48]:48s} {after['area_ha']:8.1f} "
              f"{len(after['chords']):7d} {after['visits']:7d} "
              f"{after['walk_km']:6.2f}{note}")
        here = after
    print("\nNothing has been applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
