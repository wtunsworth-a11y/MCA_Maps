#!/usr/bin/env python3
"""What arrived in a clan's folder, and what became of every metre of it.

Seven stages of this pipeline may discard data and not one of them says
so: a single bad row stops a whole file loading, smoothing removes
several kilometres, the sacred-site filter withholds recordings, the
classifier reads one field of six, de-duplication and spur pruning drop
whole chains, the closing step picks which line to use, and derived line
is counted as geometry but not as drawn. By the time a map exists there
is no way to tell "the steward did not walk it" from "we lost it".

The ledger closes that. It starts where the clan's data started — the
folder it was uploaded in — and follows it through, stage by stage, with
the arithmetic made to balance. Anything unaccounted for is printed as
unaccounted for rather than quietly going missing.

Identity comes from the folder, never from a typed name. Zone 2, 3, 7B
and 8 give each clan its own folder; Zone 6, Zone 6 Sahirut and Zone 7A
have no folders at all, and for those the ledger says so rather than
pretending the grouping is as safe.

**Nothing is withheld here.** The sacred-site rule governs what is
shared — the documents, the exported layers, the clan maps — not what
the people deciding are allowed to see. Mungaikol's boundary turns on a
line titled as a sacred site, and Sukandi's sacred perimeters run
alongside its boundary; neither can be judged by someone shown only the
remainder. So this tool, `everything_map` and `recheck` read the raw
archives and list the sacred recordings in full. Withholding happens
once, on the way out.

Usage:
    python scripts/ledger.py --clan Manuvoora
    python scripts/ledger.py --all
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

import geopandas as gpd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chord_map  # noqa: E402
import closure  # noqa: E402
import dataio  # noqa: E402
import everything_map as em  # noqa: E402
import polygons as polygon_tools  # noqa: E402
import report_data  # noqa: E402

FOLDERLESS = "no folder — identity is from the filename alone"


def _names_the_place(row) -> str:
    """The line that says what the place is, not who walked it.

    Sukandi's sacred sites are named in `name` — Mitakin, Birezama,
    Bijanuri — while the steward note on the same recording carries only
    "Melinton Beso. Sukadi Clan member.". Taking the first field that had
    anything in it reported the walker and hid the site.
    """
    lines = []
    for key in ("name", "desc", "cmt", "Name", "description"):
        value = row.get(key)
        if value in (None, "") or str(value) == "nan":
            continue
        lines.extend(em.typed_text({key: value}))
    for line in lines:
        if em.SACRED.search(line):
            return line[:90]
    return (lines[0][:90] if lines else "")


def uploads() -> dict:
    """Every file as it arrived, keyed by the folder it arrived in."""
    out: dict = defaultdict(list)
    for archive in sorted(dataio.RAW_DIR.glob("*.zip")):
        with zipfile.ZipFile(archive) as handle:
            for member in handle.namelist():
                if member.endswith("/"):
                    continue
                if not member.lower().endswith(
                        (".gpkg", ".sqlite", ".kml", ".kmz", ".gpx", ".csv")):
                    continue
                folder = Path(member).parent.as_posix()
                key = (archive.name,
                       folder if folder not in ("", ".") else FOLDERLESS)
                out[key].append(member)
    return out


def ledger(clan: str) -> dict:
    """One clan, from its upload folder to its finished boundary."""
    tracks = gpd.read_file(dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg",
                           layer="tracks_smoothed").to_crs(dataio.METRIC_CRS)
    tracks["_unit"] = dataio.survey_group(tracks)
    mine = tracks[tracks.clan.astype(str).str.lower()
                  .str.startswith(clan.lower())]
    if mine.empty:
        return {"clan": clan, "error": "nothing published under this name"}
    unit = mine._unit.iloc[0]
    whole = tracks[tracks._unit == unit]

    sources = {str(v) for v in whole.source_name if str(v) != "nan"}
    where = [(archive, folder, files)
             for (archive, folder), files in uploads().items()
             if any(Path(f).stem in sources for f in files)]

    arrived = em.recordings(clan)
    raw_km = sum(r["geometry"].length for r in arrived) / 1000

    published = dataio.publishable(whole.copy(), quiet=True)
    withheld = whole.loc[~whole.index.isin(published.index)]

    parts = chord_map.parts_of(published)
    frame = polygon_tools.adopted_frame(unit)
    rows = ([] if frame is None or frame.empty
            else [(r.geometry, r["kind"], r["note"]) for _, r in frame.iterrows()])
    built = polygon_tools.survey_polygon(
        parts, 25.0, 0.50, 0.10,
        derived=[r[0] for r in rows], unit=unit)

    distinct = closure.distinct_indices(parts) if parts else []
    duplicate_km = (sum(p.length for p in parts) -
                    sum(parts[i].length for i in distinct)) / 1000

    settled = [r for r in rows if em.CONFIRMED.search(r[2] or "")]
    pending = [r for r in rows if not em.CONFIRMED.search(r[2] or "")]
    gaps = (built or {}).get("bridges") or []

    return {
        "clan": clan,
        "unit": unit,
        "uploaded_in": [{"archive": a, "folder": f, "files": sorted(
            Path(x).name for x in files)} for a, f, files in where],
        "folder_is_safe": all(f != FOLDERLESS for _, f, _ in where),
        "arrived": {"recordings": len(arrived), "km": round(raw_km, 1)},
        "smoothing_removed_km": round(
            raw_km - whole.geometry.length.sum() / 1000, 1),
        "withheld_as_sacred": {
            "recordings": len(withheld),
            "km": round(withheld.geometry.length.sum() / 1000, 1),
            # Listed, not merely counted. Withholding is for what gets
            # shared; it is not a reason to keep the people deciding in
            # the dark, and Mungaikol and Sukandi both turn on how the
            # sacred sites and the land boundary sit against each other.
            "detail": [
                {"km": round(r.geometry.length / 1000, 2),
                 "said": _names_the_place(r)}
                for _, r in withheld.iterrows()],
        },
        "reached_the_polygon_km": round(
            published.geometry.length.sum() / 1000, 1),
        "duplicate_recordings_km": round(duplicate_km, 1),
        "boundary": None if not built else {
            "area_ha": round(built["area_ha"]),
            "basis": built["basis"],
            "walked_km": round(built["walked_km"], 1),
            "inferred_confirmed_km": round(
                sum(r[0].length for r in settled) / 1000, 2),
            "inferred_unconfirmed_km": round(
                sum(r[0].length for r in pending) / 1000, 2),
            "still_to_walk_km": round(
                sum(g.length for g in gaps) / 1000, 2),
            "still_to_walk_count": len(gaps),
        },
        "unexplained_recordings": sum(
            1 for r in arrived if not em.describe(r)),
    }


def show(entry: dict) -> None:
    if entry.get("error"):
        print(f"{entry['clan']}: {entry['error']}")
        return
    print(f"\n=== {entry['unit']}")
    for place in entry["uploaded_in"]:
        print(f"  uploaded in   {place['folder']}")
        print(f"                [{place['archive']}]")
        for name in place["files"]:
            print(f"                  {name}")
    if not entry["folder_is_safe"]:
        print("  WARNING       this archive has no folders; the clan is "
              "identified by filename alone")
    a = entry["arrived"]
    print(f"\n  arrived       {a['recordings']:3d} recordings, "
          f"{a['km']:6.1f} km")
    print(f"  smoothing     {-entry['smoothing_removed_km']:6.1f} km")
    w = entry["withheld_as_sacred"]
    print(f"  withheld      {-w['km']:6.1f} km  "
          f"({w['recordings']} sacred recording(s))")
    for item in w.get("detail", []):
        print(f"                  {item['km']:5.2f} km  {item['said']}")
    print(f"  = reached the polygon  {entry['reached_the_polygon_km']:6.1f} km")
    if entry["duplicate_recordings_km"]:
        print(f"      of which duplicated recordings: "
              f"{entry['duplicate_recordings_km']:.1f} km")
    b = entry["boundary"]
    if not b:
        print("  no boundary could be built")
        return
    print(f"\n  boundary      {b['area_ha']:,} ha  ({b['basis']})")
    print(f"      walked                      {b['walked_km']:6.1f} km")
    print(f"      inferred, confirmed         "
          f"{b['inferred_confirmed_km']:6.2f} km")
    print(f"      inferred, NOT confirmed     "
          f"{b['inferred_unconfirmed_km']:6.2f} km")
    print(f"      still to walk               "
          f"{b['still_to_walk_km']:6.2f} km  "
          f"({b['still_to_walk_count']} gap(s))")
    if entry["unexplained_recordings"]:
        print(f"\n  {entry['unexplained_recordings']} recording(s) with "
              f"nothing written about them")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clan")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)

    if args.all:
        tracks = gpd.read_file(
            dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg",
            layer="tracks_smoothed")
        names = sorted({str(c) for c in tracks.clan if str(c).strip()
                        and str(c) != "nan"})
    elif args.clan:
        names = [args.clan]
    else:
        parser.error("give --clan or --all")

    entries = []
    for name in names:
        try:
            entry = ledger(name)
        except Exception as error:
            entry = {"clan": name, "error": f"{type(error).__name__}: {error}"}
        entries.append(entry)
        show(entry)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(entries, indent=1, ensure_ascii=False)
                             + "\n", encoding="utf-8")
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
