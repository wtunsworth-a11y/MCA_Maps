#!/usr/bin/env python3
"""Adopt a gap as an agreed straight line, because the clan says it is one.

Most gaps are unfinished survey and the pipeline is right to say so. Some are
not: the field comes back and says *that stretch is a straight line and we are
content with it* — a gorge you cannot walk into, a ridge crest with nothing to
follow, a stretch two clans have already settled between them.

That answer is boundary. It is not the pipeline guessing across a gap, and it
should not keep being reported as something a steward still has to walk. This
records it as what it is: a line the clan gave us, kept apart from walked line
because nobody walked it, and kept apart from inference because nobody
inferred it.

Usage:
    python scripts/adopt_gap.py --clan Manuvoora --steward Granville --gap 1 \\
        --note "Gorge at the Jarahe waterfall; the clan joins it straight."
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402
import polygons as polygon_tools  # noqa: E402


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
    parser.add_argument("--steward", default=None,
                        help="number the gaps as one steward's walk shows "
                             "them, which is how the field saw them if that "
                             "is the map they annotated")
    parser.add_argument("--gap", type=int, required=True,
                        help="which numbered gap, as shown by gap_map.py")
    parser.add_argument("--note", required=True,
                        help="what this stretch is, in the field's words")
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

    unit = match._unit.iloc[0]
    group = tracks[tracks._unit == unit]
    if args.steward:
        group = group[group.steward.astype(str).str.lower()
                      .str.contains(args.steward.lower())]
        if group.empty:
            print(f"No steward matching {args.steward!r} in {unit}.")
            return 1

    derived = polygon_tools.adopted_segments(unit)
    built = polygon_tools.survey_polygon(parts_of(group) + derived,
                                         25.0, 0.50, 0.10)
    bridges = sorted((built.get("bridges") or []), key=lambda b: -b.length)
    if not 1 <= args.gap <= len(bridges):
        print(f"Gap {args.gap} does not exist; there are {len(bridges)}.")
        return 1
    line = bridges[args.gap - 1]

    path = polygon_tools.adopt_segment(
        unit, line, "agreed_straight", args.note,
        {"straight_km": round(line.length / 1000, 2),
         "source": "a straight line the clan is content with, given in the "
                   "field; not walked and not inferred"})

    print(f"Gap {args.gap} — {line.length / 1000:.2f} km — adopted as an "
          f"agreed straight line.")
    print(f"  {args.note}")
    print(f"\nWritten to {path}. It joins this clan's boundary network "
          f"however the survey is assembled, and adds no walked distance, "
          f"because nobody walked it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
