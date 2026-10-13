#!/usr/bin/env python3
"""A clan's boundary, written down once and then edited piece by piece.

Everything until now has recomputed the boundary from the raw tracks on
every run. A repair was never a change to the boundary — it was another
input to a solve that then re-decided the whole ring, which is why
closing a 68 m break on Natang moved a chord four kilometres away, and
why "fixed is fixed" has been impossible to honour. There was nothing in
the system able to hold a decision.

So the solve happens once and the answer is written down: the boundary
as an ordered run of numbered segments, each one either walked line or
line nobody walked, each with its own identity and its own history.
After that the file is the boundary. The area comes from it, the maps
come from it, the documents come from it. Editing segment 7 changes
segment 7 and nothing else, because nothing else is derived from
anything.

The segments come from the geometry rather than from the solver's
workings: the ring is followed round and cut wherever it stops lying on
walked line and wherever it returns to it. That makes the record
independent of how the ring was arrived at, and readable as a list.

Usage:
    python scripts/boundary.py --clan Ambunkol --solve
    python scripts/boundary.py --clan Ambunkol --list
    python scripts/boundary.py --clan Ambunkol --replace s7 --with-wkt "..."
    python scripts/boundary.py --clan Ambunkol --replace s7 --delete
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import geopandas as gpd
from shapely import wkt as shapely_wkt
from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.ops import linemerge, polygonize, unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402
import chord_map  # noqa: E402
import polygons as polygon_tools  # noqa: E402
import off_boundary  # noqa: E402

STORE = dataio.REPO_ROOT / "data" / "boundaries"

# A point on the ring is on walked line if the walking is within this of
# it. The same ten metres the rest of the work uses: two stewards on one
# boundary sit a median 3 m and a 90th percentile 12 m apart.
ON_WALKED = 10.0

# Step along the ring. Fine enough to put a cut within a few metres of
# where the line leaves the walking, coarse enough to keep the list short.
STEP = 5.0

# A run shorter than this is noise where the ring grazes the walking, not
# a segment anyone would discuss.
MIN_SEGMENT = 25.0


def path(unit: str) -> Path:
    return STORE / f"{dataio.safe_name(unit)}.json"


def load(unit: str) -> dict | None:
    where = path(unit)
    if not where.exists():
        return None
    return json.loads(where.read_text(encoding="utf-8"))


def save(book: dict) -> Path:
    STORE.mkdir(parents=True, exist_ok=True)
    where = path(book["unit"])
    where.write_text(json.dumps(book, indent=1, ensure_ascii=False) + "\n",
                     encoding="utf-8")
    return where


def _rings(geometry):
    out = []
    for piece in (geometry.geoms if hasattr(geometry, "geoms")
                  else [geometry]):
        out.append(LineString(piece.exterior.coords))
        for hole in piece.interiors:
            out.append(LineString(hole.coords))
    return out


def cut(ring: LineString, walked, step: float = STEP):
    """Follow the ring and cut it wherever it leaves or rejoins the walking."""
    n = max(int(ring.length / step), 8)
    marks = []
    for i in range(n + 1):
        here = ring.interpolate(i / n, normalized=True)
        marks.append(walked.distance(here) <= ON_WALKED)
    runs, start = [], 0
    for i in range(1, len(marks)):
        if marks[i] != marks[i - 1]:
            runs.append((start / n, i / n, marks[i - 1]))
            start = i
    runs.append((start / n, 1.0, marks[-1]))
    # A ring that never leaves the walking is one segment, not n of them.
    if len(runs) == 1:
        return [(ring, runs[0][2])]
    out = []
    for a, b, on in runs:
        piece = _slice(ring, a, b)
        if piece is None:
            continue
        out.append((piece, on))
    # Sweep up the slivers where the ring grazes the walking.
    merged = []
    for piece, on in out:
        if merged and (on == merged[-1][1] or piece.length < MIN_SEGMENT):
            joined = linemerge([merged[-1][0], piece])
            if isinstance(joined, LineString):
                merged[-1] = (joined, merged[-1][1])
                continue
        merged.append((piece, on))
    return merged


def _slice(ring: LineString, a: float, b: float):
    from shapely.ops import substring
    piece = substring(ring, a * ring.length, b * ring.length)
    if piece.is_empty or piece.length <= 0:
        return None
    return piece if isinstance(piece, LineString) else None


def solve(clan: str) -> dict:
    """Run the solver once and write the answer down."""
    published = gpd.read_file(dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg",
                              layer="tracks_smoothed").to_crs(dataio.METRIC_CRS)
    published = dataio.publishable(published, quiet=True)
    published["_unit"] = dataio.survey_group(published)
    match = published[published.clan.astype(str).str.lower() == clan.lower()]
    if match.empty:
        raise SystemExit(f"No clan matching {clan!r}.")
    unit = match._unit.iloc[0]
    group = published[published._unit == unit]
    parts = chord_map.parts_of(group)
    # Walking the reviewer has said is not boundary — somebody arriving
    # at a place and marking it rather than walking an edge. It is left
    # out here, where the boundary is written down, and nowhere else:
    # the recordings keep their length, their map and their words.
    kept = off_boundary.drop(unit, parts)
    if len(kept) != len(parts):
        gone = sum(p.length for p in parts) - sum(p.length for p in kept)
        print(f"  {len(parts) - len(kept)} recording(s), {gone:,.0f} m, are "
              f"marked not-boundary for this survey and are left out.")
        parts = kept
    frame = polygon_tools.adopted_frame(unit)
    derived = [] if frame is None or frame.empty else list(frame.geometry)
    built = polygon_tools.survey_polygon(parts, 25.0, 0.50, 0.10,
                                         derived=derived, unit=unit)
    if not built:
        raise SystemExit(f"{unit} does not close; nothing to write down.")
    walked = unary_union(parts)

    stewards = sorted({str(s) for s in group.steward.dropna()})
    segments, number = [], 0
    for index, ring in enumerate(_rings(built["geometry"])):
        for piece, on in cut(ring, walked):
            number += 1
            who = ""
            if on:
                middle = piece.interpolate(0.5, normalized=True)
                near = [(r.geometry.distance(middle), str(r.steward))
                        for _, r in group.iterrows()
                        if r.geometry is not None]
                if near:
                    who = min(near)[1]
            segments.append({
                "id": f"s{number}",
                "ring": index,
                "kind": "walked" if on else "drawn",
                "steward": who,
                "length_m": round(piece.length, 1),
                "wkt": piece.wkt,
                "history": [f"written down from the first solve, "
                            f"{date.today().isoformat()}"],
            })
    book = {
        "unit": unit,
        "solved": date.today().isoformat(),
        "_README": [
            "This file is the boundary. It is not rebuilt from the tracks.",
            "",
            "Each segment is walked line or line nobody walked, in the order",
            "they run round the boundary. Editing one segment changes that",
            "segment and nothing else. The area, the maps and the documents",
            "are read from here.",
            "",
            "Written once by scripts/boundary.py --solve. Do not re-solve a",
            "boundary that has been edited: it would throw the edits away.",
        ],
        "stewards": stewards,
        "segments": segments,
    }
    return book


def ring_geometry(book: dict):
    """What the stored segments enclose."""
    lines = [shapely_wkt.loads(s["wkt"]) for s in book["segments"]]
    faces = [f for f in polygonize(unary_union(lines)) if f.area > 0]
    if not faces:
        return None
    return unary_union(faces)


def open_ends(book: dict, tolerance: float = 1.0):
    """Segment ends that nothing else meets. An open ring has no area."""
    ends = []
    for seg in book["segments"]:
        line = shapely_wkt.loads(seg["wkt"])
        ends.append((seg["id"], Point(line.coords[0][:2])))
        ends.append((seg["id"], Point(line.coords[-1][:2])))
    loose = []
    for seg_id, point in ends:
        touching = sum(1 for other, where in ends
                       if (other, where) is not (seg_id, point)
                       and point.distance(where) <= tolerance)
        if touching < 2:          # itself, and at least one neighbour
            loose.append((seg_id, point))
    return loose


def summary(book: dict) -> str:
    walked = sum(s["length_m"] for s in book["segments"]
                 if s["kind"] == "walked")
    drawn = sum(s["length_m"] for s in book["segments"]
                if s["kind"] == "drawn")
    implied = sum(s["length_m"] for s in book["segments"]
                  if s["kind"] == "implied")
    land = ring_geometry(book)
    out = [f"{book['unit']}   written down {book['solved']}",
           f"  {len(book['segments'])} segments, "
           f"{walked / 1000:.2f} km walked, {drawn / 1000:.2f} km still to "
           f"walk, {implied / 1000:.2f} km implied"]
    # An edit can leave the ring open, and saying "0.0 ha" for that is no
    # use to anybody. Say where it is open.
    loose = open_ends(book)
    if loose:
        out.append(f"  THE RING IS OPEN in {len(loose)} place(s) — no area "
                   f"until it is closed")
        for seg_id, point in loose:
            out.append(f"     {seg_id} has a free end at "
                       f"{point.x:.0f}E {point.y:.0f}N")
    else:
        out.append(f"  {(land.area / 1e4) if land else 0:,.1f} ha enclosed")
    out.append("")
    for seg in book["segments"]:
        mark = {"walked": "walked", "implied": "implied",
                "drawn": "TO WALK"}.get(seg["kind"], seg["kind"])
        who = f"  {seg['steward']}" if seg.get("steward") else ""
        out.append(f"  {seg['id']:>5s}  {mark}  {seg['length_m']:8.0f} m{who}")
        for line in seg.get("history", [])[1:]:
            out.append(f"            {line}")
    return "\n".join(out)


def to_gpx(book: dict, only_drawn: bool = False) -> str:
    """The stored boundary as GPX, one track per segment.

    This is what goes back to the steward. Each segment keeps its number,
    so a man can be sent to walk s4 rather than handed the whole clan and
    left to work out which part anyone meant. The drawn segments are the
    ones that need him; the walked ones go too, so he can see his own
    line either side of the stretch he is being asked about.
    """
    import xml.sax.saxutils as esc

    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<gpx version="1.1" creator="MCA_Maps boundary.py" '
           'xmlns="http://www.topografix.com/GPX/1/1">',
           f"  <metadata><name>{esc.escape(book['unit'])}</name>"
           f"<desc>Boundary as stored {book['solved']}. "
           f"Segments marked DRAWN were not walked by anyone.</desc>"
           f"</metadata>"]
    for seg in book["segments"]:
        if only_drawn and seg["kind"] != "drawn":
            continue
        line = shapely_wkt.loads(seg["wkt"])
        name = (f"{seg['id']} — {seg['kind'].upper()} "
                f"{seg['length_m']:.0f} m"
                + (f" — {seg['steward']}" if seg.get("steward") else ""))
        out.append(f"  <trk><name>{esc.escape(name)}</name><trkseg>")
        wgs = gpd.GeoSeries([line], crs=dataio.METRIC_CRS).to_crs(4326).iloc[0]
        for x, y in wgs.coords:
            out.append(f'    <trkpt lat="{y:.7f}" lon="{x:.7f}"/>')
        out.append("  </trkseg></trk>")
    out.append("</gpx>")
    return "\n".join(out)


def draw(book: dict, out: Path):
    """The stored boundary, with every segment carrying its number.

    The map and the list have to be the same thing. A reviewer saying
    "s4 is wrong" and an editor changing s4 must be looking at the same
    object, which is what has been missing: until now a gap could be
    pointed at on a map and then be a different gap by the next run.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    import terrain

    lines = [(s, shapely_wkt.loads(s["wkt"])) for s in book["segments"]]
    land = ring_geometry(book)
    shapes = unary_union([g for _, g in lines])
    # Every metre the stewards walked, loaded before the window is set so
    # that walking the line has left out is on the page rather than off it.
    every: list = []
    try:
        published = gpd.read_file(
            dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg",
            layer="tracks_smoothed").to_crs(dataio.METRIC_CRS)
        published = dataio.publishable(published, quiet=True)
        published["_unit"] = dataio.survey_group(published)
        every = chord_map.parts_of(published[published._unit == book["unit"]])
    except Exception:
        every = []
    x0, y0, x1, y1 = unary_union([shapes] + every).bounds if every \
        else shapes.bounds
    pad = max(x1 - x0, y1 - y0) * 0.10
    window = (x0 - pad, y0 - pad, x1 + pad, y1 + pad)

    figure = plt.figure(figsize=(16, 13.8), dpi=200)
    axis = figure.add_axes([0.02, 0.05, 0.74, 0.90])
    terrain.add_hillshade(axis, dataio.METRIC_CRS, alpha=0.34, bounds=window)
    try:
        import roads as road_tools
        road_tools.underlay(axis, dataio.METRIC_CRS, window)
    except Exception:
        pass
    # Every metre the stewards walked, drawn behind the stored line. A map
    # of the boundary alone cannot show what the boundary has left out,
    # and on Ginangi it left out 9.2 km.
    missed = 0.0
    if every:
        gpd.GeoSeries(every, crs=dataio.METRIC_CRS).plot(
            ax=axis, color="#94a3b8", linewidth=1.0, zorder=1.5)
        off = unary_union(every).difference(shapes.buffer(25))
        missed = off.length
        if missed > 50:
            gpd.GeoSeries([off], crs=dataio.METRIC_CRS).plot(
                ax=axis, color="#0d9488", linewidth=2.0, zorder=1.8)
    if land is not None:
        gpd.GeoSeries([land], crs=dataio.METRIC_CRS).plot(
            ax=axis, color="#1d4ed8", alpha=0.13, edgecolor="none", zorder=2)
    paint = {"walked": ("#1f2937", 2.2, "-"),
             "implied": ("#f59e0b", 3.0, (0, (7, 2))),
             "drawn": ("#db2777", 2.8, (0, (5, 3)))}
    for seg, line in lines:
        colour, width, dash = paint.get(seg["kind"], paint["drawn"])
        axis.plot(*line.xy, color=colour, lw=width, linestyle=dash,
                  zorder=5 if seg["kind"] == "walked" else 6)
    step = (window[2] - window[0]) * 0.035
    # Labels have to clear each other as well as the lines. s16 and s12
    # are 60 m apart on Ambunkol and one marker sat on top of the other,
    # so a segment could be seen but not named — which is the whole point
    # of numbering them.
    placed: list = []
    # Shortest first: a small segment has less room to put its marker, so
    # it chooses before the long ones have taken the space.
    for seg, line in sorted(lines, key=lambda pair: pair[1].length):
        middle = line.interpolate(0.5, normalized=True)
        (ax0, ay0), (ax1, ay1) = line.coords[0][:2], line.coords[-1][:2]
        dx, dy = ax1 - ax0, ay1 - ay0
        span = (dx * dx + dy * dy) ** 0.5 or 1.0
        spot = None
        for reach in range(1, 9):
            for sign in (1, -1):
                here = Point(middle.x - dy / span * step * reach * sign,
                             middle.y + dx / span * step * reach * sign)
                if land is not None and land.contains(here):
                    continue
                if min(g.distance(here) for _, g in lines) < step * 0.8:
                    continue
                if any(here.distance(taken) < step * 0.95
                       for taken in placed):
                    continue
                spot = here
                break
            if spot is not None:
                break
        if spot is None:
            spot = Point(middle.x - dy / span * step,
                         middle.y + dx / span * step)
        placed.append(spot)
        colour = paint.get(seg["kind"], paint["drawn"])[0]
        axis.annotate(seg["id"], (middle.x, middle.y),
                      xytext=(spot.x, spot.y), fontsize=9.5,
                      fontweight="bold", color="white", ha="center",
                      va="center", zorder=10,
                      arrowprops=dict(arrowstyle="-", color=colour, lw=1.0,
                                      shrinkA=6, shrinkB=1),
                      bbox=dict(boxstyle="circle,pad=0.26",
                                facecolor=colour, edgecolor="white",
                                linewidth=1.1))
    axis.set_xlim(window[0], window[2])
    axis.set_ylim(window[1], window[3])
    axis.set_xticks([])
    axis.set_yticks([])
    for side in axis.spines.values():
        side.set_visible(False)
    walked = sum(s["length_m"] for s in book["segments"]
                 if s["kind"] == "walked")
    drawn = sum(s["length_m"] for s in book["segments"]
                if s["kind"] == "drawn")
    implied = sum(s["length_m"] for s in book["segments"]
                  if s["kind"] == "implied")
    handles = [
        plt.Rectangle((0, 0), 1, 1, facecolor="#1d4ed8", alpha=0.13,
                      edgecolor="none",
                      label=f"{(land.area / 1e4) if land else 0:,.0f} ha "
                            f"enclosed by the stored boundary"),
        Line2D([0], [0], color="#1f2937", lw=2.2,
               label=f"Walked — {walked / 1000:.2f} km"),
        Line2D([0], [0], color="#f59e0b", lw=3.0, linestyle=(0, (7, 2)),
               label=f"Implied — settled here, not a journey — "
                     f"{implied / 1000:.2f} km"),
        Line2D([0], [0], color="#db2777", lw=2.8, linestyle=(0, (5, 3)),
               label=f"Still to walk — {drawn / 1000:.2f} km"),
    ]
    if missed > 50:
        handles.append(Line2D([0], [0], color="#0d9488", lw=2.0,
                              label=f"Walked, but not on the stored line — "
                                    f"{missed / 1000:.2f} km"))
    for seg in book["segments"]:
        if seg["kind"] != "drawn":
            continue
        handles.append(Line2D([0], [0], color="none",
                              label=f"      {seg['id']}  "
                                    f"{seg['length_m']:,.0f} m"))
    axis.legend(handles=handles, loc="upper left", fontsize=9,
                bbox_to_anchor=(1.01, 1.0), borderaxespad=0, frameon=False)
    axis.set_title(f"{book['unit']} — the boundary as stored\n"
                   f"{len(book['segments'])} segments, written down "
                   f"{book['solved']}; each one edited on its own",
                   fontsize=12)
    span = window[2] - window[0]
    bar = 1000 if span > 4000 else 500
    bx = window[0] + span * 0.05
    by = window[1] + (window[3] - window[1]) * 0.05
    axis.plot([bx, bx + bar], [by, by], color="#111827", lw=3)
    axis.annotate(f"{bar / 1000:g} km", (bx + bar / 2, by), xytext=(0, 7),
                  textcoords="offset points", ha="center", fontsize=9)
    out.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(out, bbox_inches="tight")
    plt.close(figure)
    return out


def follow_walk(book: dict, seg_id: str, parts: list, note: str = ""):
    """Replace a drawn segment with the walking it was cutting across.

    The segment becomes the run of recordings the steward actually made
    between its two ends, with whatever break is left in it kept as its
    own drawn segment. Nothing outside the replacement is touched, and
    the new pieces take fresh numbers — a segment that goes, goes.
    """
    import realgap

    found = [s for s in book["segments"] if s["id"] == seg_id]
    if not found:
        raise SystemExit(f"No segment {seg_id}.")
    seg = found[0]
    line = shapely_wkt.loads(seg["wkt"])
    got = realgap.real_gap(parts, line)
    if not got or got["break_m"] >= line.length:
        raise SystemExit(f"{seg_id}: no cheaper way round. Nothing done.")

    used = {int(s["id"][1:]) for s in book["segments"] if s["id"][1:].isdigit()}
    next_id = max(used) + 1
    when = date.today().isoformat()
    made = []
    for piece, kind in got["route"]:
        made.append({
            "id": f"s{next_id}",
            "ring": seg.get("ring", 0),
            "kind": kind,
            "steward": seg.get("steward", "") if kind == "walked" else "",
            "length_m": round(piece.length, 1),
            "wkt": piece.wkt,
            "history": [
                f"{when}: put in place of {seg_id}, which was "
                f"{seg['length_m']:.0f} m nobody walked"
                + (f" — {note}" if note else "")],
        })
        next_id += 1
    # The run has to start and finish exactly where the segment it
    # replaces did, or the ring comes apart. The walked recordings end a
    # few metres off the ring's own corners, so the first and last pieces
    # are carried to meet them.
    head = shapely_wkt.loads(made[0]["wkt"])
    if Point(head.coords[0][:2]).distance(Point(line.coords[0][:2])) > 0.01:
        head = LineString([line.coords[0][:2]] + list(head.coords))
        made[0]["wkt"] = head.wkt
        made[0]["length_m"] = round(head.length, 1)
    tail = shapely_wkt.loads(made[-1]["wkt"])
    if Point(tail.coords[-1][:2]).distance(Point(line.coords[-1][:2])) > 0.01:
        tail = LineString(list(tail.coords) + [line.coords[-1][:2]])
        made[-1]["wkt"] = tail.wkt
        made[-1]["length_m"] = round(tail.length, 1)

    at = book["segments"].index(seg)
    book["segments"] = (book["segments"][:at] + made
                        + book["segments"][at + 1:])
    return seg, made


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clan", required=True)
    parser.add_argument("--solve", action="store_true")
    parser.add_argument("--resolve", action="store_true",
                        help="throw away the stored boundary and solve again")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--replace", metavar="ID")
    parser.add_argument("--with-wkt")
    parser.add_argument("--delete", action="store_true")
    parser.add_argument("--follow-walk", metavar="ID",
                        help="replace a drawn segment with the walking it "
                             "cuts across")
    parser.add_argument("--kind", metavar="ID",
                        help="change what a segment is, not where it runs")
    parser.add_argument("--as", dest="as_kind",
                        choices=["walked", "implied", "drawn"],
                        help="with --kind: walked, implied or drawn")
    parser.add_argument("--note", default="")
    parser.add_argument("--map", dest="map_to", type=Path,
                        help="draw the stored boundary, segments numbered")
    parser.add_argument("--gpx", type=Path,
                        help="write the stored boundary out for a GPS")
    parser.add_argument("--only-drawn", action="store_true",
                        help="with --gpx, only the stretches nobody walked")
    args = parser.parse_args(argv)

    if args.solve or args.resolve:
        published = gpd.read_file(
            dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg",
            layer="tracks_smoothed").to_crs(dataio.METRIC_CRS)
        published = dataio.publishable(published, quiet=True)
        published["_unit"] = dataio.survey_group(published)
        match = published[published.clan.astype(str).str.lower()
                          == args.clan.lower()]
        unit = match._unit.iloc[0] if not match.empty else None
        if unit and load(unit) and not args.resolve:
            print(f"{unit} already has a stored boundary. Editing it keeps "
                  f"the history; --resolve throws it away.")
            return 1
        book = solve(args.clan)
        where = save(book)
        print(summary(book))
        print(f"\nWritten to {where}")
        return 0

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
    book = load(unit)
    if book is None:
        print(f"{unit} has no stored boundary yet. Run --solve.")
        return 1

    if args.follow_walk:
        group = published[published._unit == unit]
        parts = chord_map.parts_of(group)
        gone, made = follow_walk(book, args.follow_walk, parts, args.note)
        save(book)
        walked = sum(m["length_m"] for m in made if m["kind"] == "walked")
        drawn = sum(m["length_m"] for m in made if m["kind"] == "drawn")
        print(f"{args.follow_walk} ({gone['length_m']:.0f} m drawn) replaced "
              f"by {len(made)} segment(s): {walked:.0f} m walked, "
              f"{drawn:.0f} m still drawn\n")
        print(summary(book))
        return 0

    if args.kind:
        found = [s for s in book["segments"] if s["id"] == args.kind]
        if not found:
            print(f"No segment {args.kind}.")
            return 1
        if not args.as_kind:
            print("--kind needs --as walked|implied|drawn.")
            return 1
        seg = found[0]
        was = seg["kind"]
        if was == args.as_kind:
            print(f"{args.kind} is already {was}.")
            return 0
        seg["history"].append(
            f"{date.today().isoformat()}: was {was}, now {args.as_kind}"
            + (f" — {args.note}" if args.note else ""))
        seg["kind"] = args.as_kind
        save(book)
        print(f"{args.kind} ({seg['length_m']:.0f} m) {was} -> "
              f"{args.as_kind}. The line itself is untouched.\n")
        print(summary(book))
        return 0

    if args.replace:
        found = [s for s in book["segments"] if s["id"] == args.replace]
        if not found:
            print(f"No segment {args.replace}.")
            return 1
        seg = found[0]
        when = date.today().isoformat()
        if args.delete:
            book["segments"] = [s for s in book["segments"]
                                if s["id"] != args.replace]
            print(f"{args.replace} removed ({seg['length_m']:.0f} m).")
        else:
            if not args.with_wkt:
                print("--replace needs --with-wkt or --delete.")
                return 1
            line = shapely_wkt.loads(args.with_wkt)
            seg["history"].append(
                f"{when}: was {seg['length_m']:.0f} m {seg['kind']}"
                + (f" — {args.note}" if args.note else ""))
            seg["wkt"] = line.wkt
            seg["length_m"] = round(line.length, 1)
            print(f"{args.replace} is now {seg['length_m']:.0f} m.")
        save(book)
        print()
        print(summary(book))
        return 0

    if args.map_to:
        print(f"Wrote {draw(book, args.map_to)}")
        return 0

    if args.gpx:
        args.gpx.parent.mkdir(parents=True, exist_ok=True)
        args.gpx.write_text(to_gpx(book, args.only_drawn), encoding="utf-8")
        n = sum(1 for s in book["segments"]
                if not args.only_drawn or s["kind"] == "drawn")
        print(f"Wrote {n} segment(s) to {args.gpx}")
        return 0

    print(summary(book))
    return 0


if __name__ == "__main__":
    sys.exit(main())
