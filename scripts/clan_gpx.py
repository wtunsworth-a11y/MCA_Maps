#!/usr/bin/env python3
"""One GPX file per clan, to hand back to the Clan Stewards who walked it.

This is the survey going home. A steward loads their clan's file onto the
phone or handheld they mapped with, and sees on the ground exactly what the
office sees: the line they walked, and the places where the line stops.

Each file holds three kinds of thing, and they are kept apart deliberately:

* **Tracks** — one per steward, named for them, exactly as recorded after
  smoothing. This is what was walked.
* **Gap tracks** — the straight lines between the loose ends, each named
  `GAP 1 OF 4 - NOT WALKED - 2.3 km`. Nobody walked these. They exist so the
  gap is visible as a line on the screen rather than as an absence, which is
  much harder to see.
* **Waypoints** — a pair at each gap, `GAP 1 START` and `GAP 1 END`. These
  are the useful part: a steward can navigate straight to the point where the
  walking stopped and carry on from there.

Gaps shorter than `--min-gap` (100 m by default) are left out. Two track ends
that close are, for anyone standing there, the same place: sending a steward
to walk 30 m they have already walked wastes their time and buries the gaps
that matter under a list of ones that do not. Of 221 gaps in the current data,
186 clear 100 m and those account for 266.6 of the 268.3 km.

Nothing is invented. A gap line is not a proposed boundary and says so in its
name and description; it is only the shortest line between two ends that have
not been joined on the ground.

Sacred sites are excluded, as everywhere else.

Usage:
    python scripts/clan_gpx.py
    python scripts/clan_gpx.py --out-dir output/gpx --only Tuoko
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

import geopandas as gpd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import closure  # noqa: E402
import dataio  # noqa: E402
import polygons as polygon_tools  # noqa: E402

CREATOR = "MCA Maps — Managalas clan boundary survey"


def parts_of(frame: gpd.GeoDataFrame) -> list:
    out = []
    for geometry in frame.geometry:
        if geometry is None:
            continue
        out.extend(geometry.geoms if hasattr(geometry, "geoms") else [geometry])
    return out


def _segment(line) -> str:
    points = "".join(
        f'      <trkpt lat="{y:.7f}" lon="{x:.7f}"/>\n'
        for x, y, *_ in line.coords)
    return f"    <trkseg>\n{points}    </trkseg>\n"


def _track(name: str, description: str, lines: list, kind: str) -> str:
    body = "".join(_segment(line) for line in lines)
    return (f"  <trk>\n"
            f"    <name>{escape(name)}</name>\n"
            f"    <desc>{escape(description)}</desc>\n"
            f"    <type>{escape(kind)}</type>\n"
            f"{body}"
            f"  </trk>\n")


def _waypoint(name: str, description: str, x: float, y: float,
              symbol: str) -> str:
    return (f'  <wpt lat="{y:.7f}" lon="{x:.7f}">\n'
            f"    <name>{escape(name)}</name>\n"
            f"    <desc>{escape(description)}</desc>\n"
            f"    <sym>{escape(symbol)}</sym>\n"
            f"  </wpt>\n")


def build(clan: str, zone: str, group: gpd.GeoDataFrame, bridges: list,
          stamp: str, skipped: int = 0) -> str:
    """The GPX document for one clan, as text.

    Waypoints come first, then tracks: GPX 1.1 fixes that order, and readers
    that validate will reject a file that gets it wrong.
    """
    metric = group.to_crs(dataio.METRIC_CRS)
    walked_km = metric.geometry.length.sum() / 1000
    gap_km = sum(b.length for b in bridges) / 1000

    summary = (f"{clan}, {zone}. {walked_km:.1f} km walked"
               + (f"; {gap_km:.1f} km still to walk in {len(bridges)} gap"
                  f"{'' if len(bridges) == 1 else 's'}" if bridges
                  else "; the boundary closes")
               + (f". {skipped} join(s) under the marking threshold are not "
                  f"shown." if skipped else ""))

    wgs = group.to_crs(dataio.WGS84)
    gap_lines = (gpd.GeoSeries(bridges, crs=dataio.METRIC_CRS)
                 .to_crs(dataio.WGS84).tolist() if bridges else [])
    gap_metres = [b.length for b in bridges]

    waypoints, tracks = [], []

    for index, (line, length) in enumerate(zip(gap_lines, gap_metres), start=1):
        label = f"GAP {index} OF {len(gap_lines)}"
        note = (f"{length / 1000:.2f} km not walked. This straight line is "
                f"not a boundary — it joins the two ends so the shape can be "
                f"closed on paper. {clan}, {zone}.")
        (x1, y1), (x2, y2) = line.coords[0][:2], line.coords[-1][:2]
        waypoints.append(_waypoint(f"{label} START", note, x1, y1, "Flag"))
        waypoints.append(_waypoint(f"{label} END", note, x2, y2, "Flag"))
        tracks.append(_track(f"{label} - NOT WALKED - {length / 1000:.2f} km",
                             note, [line], "not-walked"))

    for steward, walk in wgs.groupby("steward", sort=True):
        name = str(steward).strip() or "unnamed"
        distance = (walk.to_crs(dataio.METRIC_CRS).geometry.length.sum() / 1000)
        tracks.append(_track(
            f"{clan} - {name}",
            f"Walked by {name}. {distance:.1f} km, {len(walk)} track(s), "
            f"recorded on the ground. {clan}, {zone}.",
            parts_of(walk), "walked-boundary"))

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="' + escape(CREATOR) + '"\n'
        '     xmlns="http://www.topografix.com/GPX/1/1"\n'
        '     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n'
        '     xsi:schemaLocation="http://www.topografix.com/GPX/1/1 '
        'http://www.topografix.com/GPX/1/1/gpx.xsd">\n'
        "  <metadata>\n"
        f"    <name>{escape(clan)} — clan land boundary</name>\n"
        f"    <desc>{escape(summary)}</desc>\n"
        f"    <time>{stamp}</time>\n"
        "  </metadata>\n"
        + "".join(waypoints) + "".join(tracks)
        + "</gpx>\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gpkg", type=Path,
                        default=dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg")
    parser.add_argument("--out-dir", type=Path,
                        default=dataio.OUT_DIR / "gpx")
    parser.add_argument("--tolerance", type=float,
                        default=closure.DEFAULT_TOLERANCE_M)
    parser.add_argument("--min-enclosure", type=float, default=0.50)
    parser.add_argument("--max-spur", type=float, default=0.10)
    parser.add_argument("--min-gap", type=float, default=100.0,
                        help="gaps shorter than this many metres are not "
                             "marked; two ends that close are the same place "
                             "to anyone standing there")
    parser.add_argument("--only", default=None,
                        help="only write files for clans matching this text")
    args = parser.parse_args(argv)

    if not args.gpkg.exists():
        print(f"No smoothed data at {args.gpkg}. Run smooth_tracks.py first.")
        return 1

    tracks = gpd.read_file(args.gpkg, layer="tracks_smoothed")
    tracks = dataio.publishable(tracks)
    tracks = tracks[tracks.clan.astype(str).str.strip() != ""]
    tracks["_unit"] = dataio.survey_group(tracks)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for old in args.out_dir.glob("*.gpx"):
        old.unlink()

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    written, total_gaps, total_gap_km, total_skipped = 0, 0, 0.0, 0

    for unit, group in tracks.groupby("_unit", sort=True):
        clan = str(group.clan.iloc[0])
        zone = str(group.zone.iloc[0])
        if args.only and args.only.lower() not in clan.lower():
            continue

        metric = group.to_crs(dataio.METRIC_CRS)
        built = polygon_tools.survey_polygon(
            parts_of(metric), args.tolerance, args.min_enclosure,
            args.max_spur)
        found = (built.get("bridges") or []) if built else []
        bridges = [b for b in found if b.length >= args.min_gap]
        skipped = len(found) - len(bridges)

        text = build(clan, zone, group, bridges, stamp, skipped)
        path = args.out_dir / f"{dataio.safe_name(unit)}.gpx"
        path.write_text(text, encoding="utf-8")

        written += 1
        total_gaps += len(bridges)
        total_skipped += skipped
        gap_km = sum(b.length for b in bridges) / 1000
        total_gap_km += gap_km
        print(f"  {clan:16s} {zone:8s} "
              f"{metric.geometry.length.sum() / 1000:6.1f} km walked, "
              + (f"{len(bridges)} gap(s) totalling {gap_km:.1f} km"
                 if bridges else "closes — no gaps"))

    print(f"\nWrote {written} GPX file(s) to {args.out_dir}")
    print(f"  {total_gaps} gap(s) marked, {total_gap_km:,.1f} km still to walk")
    print(f"  {total_skipped} join(s) under {args.min_gap:.0f} m not marked")
    print("  each gap carries START and END waypoints to navigate to")
    # More than the bridge total in the polygon layer, and deliberately so:
    # that layer holds only the surveys complete enough to give an area, and a
    # clan whose walk is too open for that still needs to know where its gaps
    # are — arguably more than anyone.
    print("  (includes surveys too open to give an area, which the polygon "
          "layer excludes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
