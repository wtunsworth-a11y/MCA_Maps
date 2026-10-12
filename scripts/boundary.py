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
    land = ring_geometry(book)
    out = [f"{book['unit']}   written down {book['solved']}",
           f"  {len(book['segments'])} segments, "
           f"{walked / 1000:.2f} km walked, {drawn / 1000:.2f} km drawn"]
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
        mark = "walked" if seg["kind"] == "walked" else "DRAWN "
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
    parser.add_argument("--note", default="")
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
