#!/usr/bin/env python3
"""A record of what was tried on each clan, and what it did.

Fifty clans are in hand and about a hundred and fifty are coming. The
work so far has been one argument per gap, and the same arguments keep
coming round: a chord drawn across walked line, a dead end that was not
a dead end, a walk saved twice. The fixes are not interchangeable — the
node that put Juaiko's gap 1 back on the walking cost Natang 450 m of
extra chord — so "which fix" has to be answered from evidence rather
than from whichever one worked last time.

This keeps that evidence. A case is one fault on one survey: what the
gap looked like before anything was done, which approach was tried, what
it did to the measurable state of the whole clan, and whether it was
kept. Nothing here applies a fix to anything; it only records.

The point of the signature is matching. Two chords that cross the walked
line are not the same problem if one sits on a piece with a single free
end and the other on a piece with three. Recording the shape means the
next clan's gap can be put beside the cases already settled instead of
being argued from the beginning.

Usage:
    python scripts/cases.py --list
    python scripts/cases.py --shape --clan Natang --gap 4
    python scripts/cases.py --match --clan Natang --gap 4

    python scripts/cases.py --open  --clan Natang --gap 3 \\
        --fault "68 m chord across a lobe, crosses the walk"
    # ... make the change ...
    python scripts/cases.py --close --clan Natang \\
        --approach node_crossing --kept yes \\
        --note "Closed gap 3; turned gap 1 from 803 m into 1,723 m."
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402
import chord_map  # noqa: E402
import closure  # noqa: E402
import polygons as polygon_tools  # noqa: E402

REGISTER = dataio.REPO_ROOT / "data" / "reference" / "cases.json"

README = [
    "What was tried on each clan, and what it did.",
    "",
    "A case is one fault on one survey: the shape of the gap before",
    "anything was done, the approach tried, what it did to the whole",
    "clan, and whether it was kept. Written by scripts/cases.py.",
    "",
    "Nothing here is applied to anything. It is the evidence for",
    "choosing an approach on the next clan, so that a decision made",
    "once does not have to be argued again from the beginning.",
    "",
    "'kept: no' is as useful as 'kept: yes' and must not be deleted.",
]


# --------------------------------------------------------------- loading


def _survey(clan: str):
    """The survey unit, its walked parts and its adopted segments."""
    published = gpd.read_file(dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg",
                              layer="tracks_smoothed").to_crs(dataio.METRIC_CRS)
    published = dataio.publishable(published, quiet=True)
    published["_unit"] = dataio.survey_group(published)
    match = published[published.clan.astype(str).str.lower()
                      == clan.lower()]
    if match.empty:
        match = published[published.clan.astype(str).str.lower()
                          .str.startswith(clan.lower())]
        units = sorted(set(match._unit))
        if len(units) > 1:
            raise SystemExit(f"{clan!r} matches {len(units)} surveys: "
                             + ", ".join(units))
    if match.empty:
        raise SystemExit(f"No clan matching {clan!r}.")
    unit = match._unit.iloc[0]
    group = published[published._unit == unit]
    frame = polygon_tools.adopted_frame(unit)
    derived = [] if frame is None or frame.empty else list(frame.geometry)
    return unit, chord_map.parts_of(group), derived


def state(clan: str) -> dict:
    """The measurable state of one survey, as it stands right now.

    Everything here is a number the next run can be compared against,
    and nothing here is a judgement.
    """
    unit, parts, derived = _survey(clan)
    built = polygon_tools.survey_polygon(parts, 25.0, 0.50, 0.10,
                                         derived=derived, unit=unit)
    walked = unary_union(parts)
    if not built:
        return {"unit": unit, "area_ha": None, "basis": None,
                "walked_km": round(sum(p.length for p in parts) / 1000, 3)}
    gaps = sorted(built["bridges"], key=lambda b: -b.length)
    return {
        "unit": unit,
        "area_ha": round(built["area_ha"], 1),
        "basis": built["basis"],
        "walked_km": round(built["walked_km"], 3),
        "derived_km": round(built["derived_km"], 3),
        "gaps": len(gaps),
        "gap_km": round(sum(g.length for g in gaps) / 1000, 3),
        # The rule we keep coming back to: a boundary line that crosses
        # the walked line is always wrong. Counting them is how we tell
        # a repair that worked from one that only moved the trouble.
        "gaps_crossing_walk": sum(1 for g in gaps if g.crosses(walked)),
        "longest_gap_m": round(max((g.length for g in gaps), default=0)),
    }


# -------------------------------------------------------------- the shape


def _graph(unit, parts, derived, tolerance=25.0):
    """The survey as the closing step sees it, not as the files arrive.

    It has to be the same graph or the answer is about a different
    survey: the nodes added for crossings, one copy of each stretch
    where duplicates are collapsed, and the dead ends pruned. Built
    from the raw parts instead, Natang's two pieces came back as one
    and the free-end counts were wrong in both.
    """
    parts = closure.extended_parts(unit, list(parts) + list(derived))
    endpoints = []
    for part in parts:
        endpoints.append(part.coords[0][:2])
        endpoints.append(part.coords[-1][:2])
    labels = closure._cluster_endpoints(endpoints, tolerance)
    positions: dict = {}
    for index, label in enumerate(labels):
        positions.setdefault(label, endpoints[index])
    keep = (closure.distinct_indices(parts)
            if closure.approved_fix(unit, "collapse_duplicates")
            else list(range(len(parts))))
    edges = [{"a": labels[2 * i], "b": labels[2 * i + 1],
              "length": parts[i].length, "live": True} for i in keep]
    closure._prune_spurs(
        edges, closure.spur_limit(unit, 0.10)
        * sum(parts[i].length for i in keep))
    live = [e for e in edges if e["live"]] or edges
    return positions, [(e["a"], e["b"], e["length"]) for e in live]


def shape(clan: str, number: int) -> dict:
    """What this gap looks like, in the terms that decide the fix.

    Not "how long is it" — that is the least useful thing about a gap.
    Whether it crosses the walk, whether the steward already walked a
    route between its own two ends, and how many free ends the piece it
    attaches to has: those are what separated Juaiko's gap 1 from
    Natang's gap 3, which look identical on a map.
    """
    import networkx as nx

    unit, parts, derived = _survey(clan)
    built = polygon_tools.survey_polygon(parts, 25.0, 0.50, 0.10,
                                         derived=derived, unit=unit)
    if not built or not built["bridges"]:
        raise SystemExit(f"{unit} has no gaps.")
    order = sorted(built["bridges"], key=lambda b: -b.length)
    numbers = chord_map.numbering(unit, order, record=False)
    wanted = [g for i, g in enumerate(order) if numbers[i] == number]
    if not wanted:
        raise SystemExit(f"No gap {number} on {unit}; have "
                         + ", ".join(str(n) for n in sorted(numbers.values())))
    gap = wanted[0]
    walked = unary_union(parts)
    hit = gap.intersection(walked)
    crossings = (len(hit.geoms) if hasattr(hit, "geoms")
                 else (0 if hit.is_empty else 1))

    # Is there already a walked route between this gap's own two ends? If
    # there is, the gap is not a gap: it is a line drawn over ground the
    # steward covered, and the fix is topological rather than a question
    # for the field.
    positions, edges = _graph(unit, parts, derived)
    graph = nx.Graph()
    for a, b, length in edges:
        if graph.has_edge(a, b) and graph[a][b]["weight"] <= length:
            continue
        graph.add_edge(a, b, weight=length)
    ends = [Point(gap.coords[0][:2]), Point(gap.coords[-1][:2])]
    nodes = [min(graph.nodes,
                 key=lambda n, e=e: Point(positions[n]).distance(e))
             for e in ends]
    detour = None
    if nodes[0] != nodes[1] and nx.has_path(graph, *nodes):
        detour = round(nx.shortest_path_length(graph, *nodes, weight="weight"))

    # How many free ends has the piece at each end of the gap? One is a
    # tail the ring must enter and leave by; three means the closing step
    # is choosing two of them and discarding the rest.
    groups = closure._Groups()
    for a, b, _ in edges:
        groups.add(a)
        groups.add(b)
    for a, b, _ in edges:
        groups.union(a, b)
    degree: dict = {}
    for a, b, _ in edges:
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1
    free_by_root: dict = {}
    for node, count in degree.items():
        if count == 1:
            free_by_root.setdefault(groups.find(node), []).append(node)

    return {
        "unit": unit,
        "gap": number,
        "length_m": round(gap.length),
        "crosses_walk": bool(gap.crosses(walked)),
        "crossings": crossings,
        "within_10m_pct": round(
            gap.intersection(walked.buffer(10)).length / gap.length * 100, 1)
        if gap.length else None,
        # A walked route between the gap's own ends, and how far round it
        # goes. 2,685 m round a 98 m break is Juaiko's gap 1.
        "walked_route_m": detour,
        "detour_ratio": round(detour / gap.length, 1)
        if detour and gap.length else None,
        "free_ends_on_piece": [len(free_by_root.get(groups.find(n), []))
                               for n in nodes],
        "same_piece": groups.find(nodes[0]) == groups.find(nodes[1]),
        "ends": [[round(e.x), round(e.y)] for e in ends],
    }


def similar(one: dict, other: dict) -> bool:
    """Whether two gap shapes are the same kind of problem."""
    if one.get("crosses_walk") != other.get("crosses_walk"):
        return False
    if one.get("same_piece") != other.get("same_piece"):
        return False
    a = sorted(one.get("free_ends_on_piece") or [])
    b = sorted(other.get("free_ends_on_piece") or [])
    if a != b:
        return False
    # A short break with a long way round is a different animal from a
    # gap with no walked route at all, whatever its length.
    return (bool(one.get("walked_route_m")) == bool(other.get("walked_route_m")))


# ------------------------------------------------------------- the register


def load() -> dict:
    if not REGISTER.exists():
        return {"_README": README, "cases": [], "open": {}}
    try:
        book = json.loads(REGISTER.read_text(encoding="utf-8"))
    except ValueError:
        return {"_README": README, "cases": [], "open": {}}
    book.setdefault("cases", [])
    book.setdefault("open", {})
    book["_README"] = README
    return book


def save(book: dict) -> None:
    REGISTER.parent.mkdir(parents=True, exist_ok=True)
    REGISTER.write_text(json.dumps(book, indent=1, ensure_ascii=False) + "\n",
                        encoding="utf-8")


def _table(book: dict) -> str:
    rows = book.get("cases", [])
    if not rows:
        return "No cases recorded yet."
    out = [f"{len(rows)} case(s)", ""]
    for case in rows:
        before, after = case.get("before", {}), case.get("after", {})
        kept = "kept" if case.get("kept") else "WITHDRAWN"
        out.append(f"{case['on']}  {case['unit']}  gap {case.get('gap', '-')}"
                   f"  —  {case['approach']}  [{kept}]")
        out.append(f"    fault: {case.get('fault', '')}")
        sh = case.get("shape") or {}
        if sh:
            out.append(
                f"    shape: {sh.get('length_m')} m, "
                f"crosses the walk {sh.get('crossings', 0)}x, "
                f"{sh.get('within_10m_pct')}% within 10 m, "
                f"walked route between its ends "
                f"{sh.get('walked_route_m') or 'none'}"
                + (f" ({sh.get('detour_ratio')}x)"
                   if sh.get("detour_ratio") else "")
                + f", free ends on the piece {sh.get('free_ends_on_piece')}")
        for key, label in (("area_ha", "area ha"), ("gaps", "gaps"),
                           ("gap_km", "gap km"),
                           ("gaps_crossing_walk", "gaps crossing the walk"),
                           ("longest_gap_m", "longest gap m")):
            if key in before or key in after:
                out.append(f"    {label:24s} {before.get(key)}  ->  "
                           f"{after.get(key)}")
        for line in (case.get("note") or "").splitlines():
            out.append(f"    {line}")
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clan")
    parser.add_argument("--gap", type=int)
    parser.add_argument("--fault", default="")
    parser.add_argument("--approach")
    parser.add_argument("--note", default="")
    parser.add_argument("--kept", choices=["yes", "no"])
    parser.add_argument("--open", action="store_true",
                        help="record the state and the gap's shape before a "
                             "change")
    parser.add_argument("--close", action="store_true",
                        help="record the state after it, and file the case")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--shape", action="store_true")
    parser.add_argument("--match", action="store_true",
                        help="cases already settled on a gap of this shape")
    args = parser.parse_args(argv)

    book = load()

    if args.list:
        print(_table(book))
        return 0

    if args.shape or args.match:
        if not args.clan or args.gap is None:
            print("--shape and --match need --clan and --gap.")
            return 1
        sh = shape(args.clan, args.gap)
        print(json.dumps(sh, indent=1))
        if args.match:
            like = [c for c in book["cases"]
                    if c.get("shape") and similar(sh, c["shape"])]
            print(f"\n{len(like)} case(s) of the same shape:")
            for case in like:
                note = (case.get("note") or "").splitlines()
                kept = "kept" if case.get("kept") else "WITHDRAWN"
                print(f"  {case['unit']} gap {case.get('gap')}: "
                      f"{case['approach']} [{kept}] — "
                      f"{note[0] if note else ''}")
        return 0

    if args.open:
        if not args.clan:
            print("--open needs --clan.")
            return 1
        before = state(args.clan)
        entry = {"unit": before["unit"], "gap": args.gap,
                 "fault": args.fault, "before": before}
        if args.gap is not None:
            entry["shape"] = shape(args.clan, args.gap)
        book["open"][before["unit"]] = entry
        save(book)
        print(f"opened a case on {before['unit']}"
              + (f", gap {args.gap}" if args.gap is not None else ""))
        print(json.dumps(before, indent=1))
        return 0

    if args.close:
        if not args.clan or not args.approach:
            print("--close needs --clan and --approach.")
            return 1
        after = state(args.clan)
        entry = book["open"].pop(after["unit"], None)
        if entry is None:
            print(f"No open case on {after['unit']}. Use --open first.")
            return 1
        entry.update({"on": date.today().isoformat(),
                      "approach": args.approach,
                      "kept": args.kept != "no",
                      "note": args.note,
                      "after": after})
        book["cases"].append(entry)
        save(book)
        print(_table({"cases": [entry]}))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
