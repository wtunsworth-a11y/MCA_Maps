#!/usr/bin/env python3
"""Who walked, on which days, and how far on each of them.

The record of the work itself, kept apart from the record of the land. Every
figure here comes from the GPS, not from a file name: the date a track was
recorded and the distance along it after smoothing.

Where the dates come from, in order of preference:

1. the `Created` timestamp the recording app writes into each track's
   description — present on most tracks and unambiguous;
2. a date at the start of the track name, which the field team uses as a
   naming convention on some devices;
3. nothing, in which case the track is counted in the distance but reported
   as undated, and named so it can be chased.

The `survey_date` attribute is deliberately not used. It is the date the
archive was collated and delivered, which the field team confirmed, and every
file in a delivery carries the same one.

Usage:
    python scripts/stewards.py
    python scripts/stewards.py --report output/stewards/STEWARD_DAYS.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402
import smooth_tracks  # noqa: E402

# The app writes its metadata as an HTML table; this is the Created row of it.
CREATED = re.compile(r"Created</b></small></td>\s*<td[^>]*>(\d{4}-\d{2}-\d{2})")
NAMED_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def track_date(row: pd.Series) -> str | None:
    """The day a track was recorded, from whichever source carries it."""
    for column in ("desc", "description"):
        value = row.get(column)
        if isinstance(value, str):
            match = CREATED.search(value)
            if match:
                return match.group(1)
    name = row.get("name")
    if isinstance(name, str):
        match = NAMED_DATE.search(name)
        if match:
            return match.group(1)
    return None


def build(tracks: gpd.GeoDataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per steward-day, and per steward: distance and days on the ground."""
    frame = tracks.to_crs(dataio.METRIC_CRS).copy()
    frame["date"] = frame.apply(track_date, axis=1)
    frame["km"] = frame.geometry.length / 1000
    frame["steward"] = frame["steward"].astype(str).str.strip()
    frame.loc[frame.steward.isin(["", "nan", "None"]), "steward"] = "unnamed"

    days = (frame.groupby(["steward", "zone", "clan", "date"], dropna=False)
            .agg(tracks=("km", "size"), km=("km", "sum"))
            .reset_index()
            .sort_values(["steward", "date"]))
    days["km"] = days["km"].round(2)

    boundary = frame[frame.feature_type == smooth_tracks.BOUNDARY_TYPE]
    boundary_km = boundary.groupby("steward")["km"].sum()

    people = []
    for steward, group in frame.groupby("steward"):
        dated = group[group.date.notna()]
        people.append({
            "steward": steward,
            "zones": ", ".join(sorted(set(group.zone.dropna()))),
            "clans": ", ".join(sorted({c for c in group.clan.astype(str)
                                       if c.strip() and c != "nan"})),
            "tracks": int(len(group)),
            "days": int(dated.date.nunique()),
            "undated_tracks": int(group.date.isna().sum()),
            "first": dated.date.min() if len(dated) else None,
            "last": dated.date.max() if len(dated) else None,
            "km": round(group.km.sum(), 2),
            "boundary_km": round(float(boundary_km.get(steward, 0.0)), 2),
            "km_per_day": round(group.km.sum() / dated.date.nunique(), 2)
            if dated.date.nunique() else None,
        })
    stewards = (pd.DataFrame(people)
               .sort_values(["zones", "steward"])
               .reset_index(drop=True))
    return stewards, days


def name_mismatches(tracks: gpd.GeoDataFrame) -> pd.DataFrame:
    """Tracks whose own name credits a different steward from the file's.

    The steward comes from the file name (§4.3), which is the only place it is
    recorded for most surveys. Some devices also write a name onto each track,
    and when the two disagree the file name is not obviously the right one:
    it can mean one steward sent in another's recordings along with their own.

    Nothing is reassigned here. Who walked which track is a question for the
    field, and getting it wrong would put a day's work against the wrong
    person's name. It is reported so it can be asked.
    """
    frame = tracks.to_crs(dataio.METRIC_CRS).copy()
    known = sorted({str(s).strip() for s in frame.steward if str(s).strip()},
                   key=len, reverse=True)
    rows = []
    for _, row in frame.iterrows():
        label = str(row.get("name") or "")
        if not label.strip():
            continue
        mine = str(row.steward).strip()
        for other in known:
            if other == mine or len(other) < 6:
                continue
            if other.lower() in label.lower():
                rows.append({
                    "source_name": row.source_name,
                    "file_steward": mine,
                    "track_name": label.strip(),
                    "credits": other,
                    "clan": row.clan,
                    "zone": row.zone,
                    "km": round(row.geometry.length / 1000, 2),
                })
                break
    return pd.DataFrame(rows)


def _records(frame: pd.DataFrame) -> list[dict]:
    """Rows as plain dicts, with every missing value as null.

    `json.dumps` writes a float NaN as the bare token `NaN`, which Python
    reads back happily and every other JSON parser rejects. The document
    builders are JavaScript, so this has to be cleaned here.
    """
    out = []
    for record in frame.to_dict("records"):
        out.append({key: (None if isinstance(value, float) and pd.isna(value)
                          else None if value is pd.NaT
                          else value.item() if hasattr(value, "item")
                          else value)
                    for key, value in record.items()})
    return out


def _markdown(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_None._"
    columns = list(frame.columns)
    lines = ["| " + " | ".join(str(c) for c in columns) + " |",
             "| " + " | ".join("---" for _ in columns) + " |"]
    for _, row in frame.iterrows():
        lines.append("| " + " | ".join(
            "" if pd.isna(row[c]) else str(row[c]) for c in columns) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gpkg", type=Path,
                        default=dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg")
    parser.add_argument("--layer", default=smooth_tracks.SMOOTHED_LAYER)
    parser.add_argument("--out-dir", type=Path,
                        default=dataio.OUT_DIR / "stewards")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.gpkg.exists():
        print(f"No smoothed data at {args.gpkg}. Run smooth_tracks.py first.")
        return 1

    tracks = gpd.read_file(args.gpkg, layer=args.layer)
    stewards, days = build(tracks)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    mismatched = name_mismatches(tracks)
    if not mismatched.empty:
        mismatched.to_csv(args.out_dir / "name_mismatches.csv", index=False)

    stewards.to_csv(args.out_dir / "stewards.csv", index=False)
    days.to_csv(args.out_dir / "steward_days.csv", index=False)
    (args.out_dir / "stewards.json").write_text(
        json.dumps({"stewards": _records(stewards), "days": _records(days),
                    "mismatches": _records(mismatched)}, indent=1),
        encoding="utf-8")

    dated = days[days.date.notna()]
    print(f"{len(stewards)} steward(s), "
          f"{dated.date.nunique()} distinct day(s) on the ground, "
          f"{int(dated.groupby(['steward', 'date']).ngroups)} steward-days")
    print(f"  recorded {dated.date.min()} to {dated.date.max()}")
    print(f"  {stewards.km.sum():,.0f} km walked, "
          f"{stewards.boundary_km.sum():,.0f} km of it on land boundaries")
    undated = int(stewards.undated_tracks.sum())
    if undated:
        print(f"  {undated} track(s) carry no recoverable date")
    if not mismatched.empty:
        print(f"  {len(mismatched)} track(s) name a different steward from "
              f"their file — {mismatched.km.sum():.1f} km, see "
              f"name_mismatches.csv")
    print(f"\nWrote {args.out_dir}/stewards.csv, steward_days.csv, stewards.json")

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            "# Who walked, and when\n\n"
            f"{len(stewards)} stewards, {int(dated.groupby(['steward', 'date']).ngroups):,} "
            f"steward-days between {dated.date.min()} and {dated.date.max()}.\n\n"
            "Dates are taken from the GPS record, not from file names.\n\n"
            "## By steward\n\n" + _markdown(stewards)
            + "\n\n## Tracks crediting a different steward\n\n"
            + ("None.\n" if mismatched.empty else
               "The steward comes from the file name, which for most surveys "
               "is the only place it is recorded. Where a track's own name "
               "credits somebody else, both are shown here and neither is "
               "changed: who walked which track is a question for the field, "
               "and guessing would put a day's work against the wrong "
               "person's name.\n\n" + _markdown(mismatched))
            + "\n\n## Every steward-day\n\n" + _markdown(days) + "\n",
            encoding="utf-8")
        print(f"Wrote {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
