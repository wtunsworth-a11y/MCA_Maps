#!/usr/bin/env python3
"""Mark a clan's map as approved, and record what is left to do on it.

Clan by clan, the chord map is looked at with someone who knows the ground,
the chords are discussed, what can be fixed is fixed, and what is left is
written down. This records the end of that: the map as approved, the date it
was approved, and the work still outstanding.

An approved map does not move afterwards. The file is copied out of
output/queries, which is rebuilt whenever anything is re-run, into
output/clans/approved, which is not. A map that changes after it was agreed
is not an approved map, and the clan page would be showing something nobody
had seen.

The outstanding items go on the clan's page under "To complete this map",
in the order given.

Usage:
    python scripts/approve.py --clan Gumuyude \\
        --todo "Walk the 652 m gap on the northern shoulder" \\
        --todo "Confirm with the clan what the notch on the north-east is"
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path

import geopandas as gpd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402

REGISTER = dataio.REPO_ROOT / "data" / "reference" / "approved.json"
APPROVED_DIR = dataio.OUT_DIR / "clans" / "approved"


def load() -> dict:
    if not REGISTER.exists():
        return {}
    try:
        return json.loads(REGISTER.read_text(encoding="utf-8"))
    except Exception:
        return {}


def approved(unit: str | None = None):
    """What has been approved, for the report to read."""
    book = load()
    return book if unit is None else book.get(unit)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clan", required=True)
    parser.add_argument("--todo", action="append", default=[],
                        help="one thing still to be done; repeat for each")
    parser.add_argument("--map", type=Path, default=None,
                        help="the map approved (default: this clan's chord map)")
    parser.add_argument("--withdraw", action="store_true",
                        help="remove an approval, if the map has moved on")
    args = parser.parse_args(argv)

    tracks = gpd.read_file(dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg",
                           layer="tracks_smoothed")
    tracks = dataio.publishable(tracks, quiet=True)
    tracks["_unit"] = dataio.survey_group(tracks)
    match = tracks[tracks.clan.astype(str).str.lower() == args.clan.lower()]
    if match.empty:
        print(f"No clan matching {args.clan!r}.")
        return 1
    unit = match._unit.iloc[0]

    book = load()
    if args.withdraw:
        if book.pop(unit, None) is None:
            print(f"{unit} was not approved.")
            return 1
        REGISTER.write_text(json.dumps(book, indent=1, ensure_ascii=False)
                            + "\n", encoding="utf-8")
        print(f"Approval withdrawn for {unit}.")
        return 0

    source = args.map or (dataio.OUT_DIR / "queries"
                          / f"{dataio.safe_name(unit)}_chords.png")
    # The map kept is the one that was reviewed. Since the review moved
    # to everything_map — all the recordings, the four categories, the
    # area as mapping progress — that is the map to keep, and the chord
    # map is only a fallback for clans reviewed before the change.
    if args.map is None:
        # everything_map names its file after the clan, not the unit —
        # `Murai_Z2_everything.png`, not `Murai_Z2_Zone_2_everything.png`.
        # Looking only for the unit's spelling sent both Murai surveys to
        # the chord-map fallback, which does not exist, and neither was
        # recorded.
        for candidate in (dataio.OUT_DIR / "queries"
                          / f"{args.clan.replace(' ', '_')}_everything.png",
                          dataio.OUT_DIR / "queries"
                          / f"{dataio.safe_name(args.clan)}_everything.png",
                          dataio.OUT_DIR / "queries"
                          / f"{dataio.safe_name(unit)}_everything.png"):
            if candidate.exists():
                source = candidate
                break
    if not source.exists():
        print(f"No map at {source}. Run scripts/chord_map.py first.")
        return 1
    APPROVED_DIR.mkdir(parents=True, exist_ok=True)
    kept = APPROVED_DIR / f"{dataio.safe_name(unit)}.png"
    shutil.copyfile(source, kept)

    book[unit] = {"on": date.today().isoformat(),
                  "map": kept.name,
                  "todo": args.todo}
    REGISTER.write_text(json.dumps(book, indent=1, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(f"{unit}: map approved {book[unit]['on']}, kept as {kept}")
    if args.todo:
        print("To complete this map:")
        for item in args.todo:
            print(f"  - {item}")
    else:
        print("Nothing outstanding recorded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
