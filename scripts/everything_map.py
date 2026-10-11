#!/usr/bin/env python3
"""Every recording a clan made, with every word typed about it.

The chord maps are drawn from the published layer, which is the walk with
the sacred sites taken out, and from the parts of it the closing step
chose to use. Three kinds of thing therefore never reach the eye:

* recordings withheld because they are tagged as sacred sites;
* walked line the polygon does not enclose;
* text the stewards typed into a field nothing reads — `cmt`, `desc`,
  and on the KML-derived files `Name` and `description` as well.

That last one decides the other two. Sukandi's sacred sites were caught
because Millinton Beso typed the words into `name`; Graham Ekiawa's went
into `desc`, so Mungaikol's sacred site is published and carrying an
outer boundary. The classifier reads one field out of six.

This draws the lot, from the raw archives rather than the published
layer, so a survey can be looked at as the steward left it.

Usage:
    python scripts/everything_map.py --clan Rondi
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
import sqlite3
import tempfile
import os
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from shapely.geometry import box  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402
import terrain  # noqa: E402

# The recording app writes its own statistics into the same fields the
# steward types into, in whichever units the phone was set to. Anything
# that is a label from that block, or a bare number with a unit on it, is
# the app talking.
STATS = re.compile(
    r"^(Activity|Distance|Created|Max\.?|Pace|Energy|Points|All\b|Avg\.?|"
    r"Track time|Min\.?|Elevation|Uphill|Downhill|Flat|Moving|Total|Speed|"
    r"Walking|Running|Cycling|nan)\b", re.I)
NUMERIC = re.compile(
    r"^[-+]?[\d.,]+\s*"
    r"(m|km|mi|ft|m/s|km/h|mi/h|KJ|kcal|%|min/km|min/mile|min/mi)?$", re.I)
CLOCK = re.compile(r"^\d{1,3}:\d{2}(:\d{2})?\s*(min/km|min/mile|min/mi)?$")
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]?[\d:]*$")
# A null date read out of an empty column. It is not something anybody
# typed, and printing it as a place name says a steward named somewhere
# "NaT".
EMPTY = {"nat", "nan", "none", "null", "<na>", "-", "0"}
SACRED = re.compile(r"sacred|secret\s*s?i?ght|tambu|taboo|tabu|spirit|"
                    r"burial|graveyard|skull|forbidden|holy|holly|masalai",
                    re.I)
SKIP = {"fid", "geom", "line", "locus_activity", "id", "ogc_fid",
        "tessellate", "extrude", "visibility", "layer", "path"}

# An inference the clan has agreed, against one still waiting on them.
# Every adopted segment carries its reasoning; the ones that have been
# put to the people who know the ground say so in it.
CONFIRMED = re.compile(r"\bagreed\b|\bconfirmed\b|clan has (agreed|said)",
                       re.I)


def typed_text(values: dict) -> list:
    """Every line a person typed, from whichever field they typed it into."""
    out = []
    for key, value in values.items():
        if key.lower() in SKIP or value in (None, ""):
            continue
        text = re.sub(r"<br\s*/?>", "\n", str(value))
        text = re.sub(r"<[^>]+>", "\n", text)
        for line in text.split("\n"):
            line = " ".join(line.split())
            if not line or line in out:
                continue
            if (STATS.match(line) or NUMERIC.match(line)
                    or CLOCK.match(line) or TIMESTAMP.match(line)
                    or line.strip().lower() in EMPTY):
                continue
            out.append(line)
    return out


def _read_row_by_row(path: str):
    """Read a geopackage a row at a time, skipping the broken ones.

    A single recording with one point in it stops geopandas loading the
    whole file, and the pipeline's own repair never sees these because it
    works on what loaded. Riribudeh has one. Reading the blobs directly
    loses that row and keeps the other fifty.
    """
    import struct
    from shapely import wkb

    try:
        db = sqlite3.connect(path)
        tables = [r[0] for r in db.execute(
            "select table_name from gpkg_contents where data_type='features'")]
    except Exception:
        return None

    rows, dropped = [], 0
    for table in tables:
        columns = [r[1] for r in db.execute(f'pragma table_info("{table}")')]
        if "geom" not in columns:
            continue
        others = [c for c in columns if c != "geom"]
        picked = ",".join(f'"{c}"' for c in others + ["geom"])
        for record in db.execute(f'select {picked} from "{table}"'):
            blob = record[-1]
            if not blob:
                continue
            try:
                # GeoPackage binary: "GP", version, flags, srs_id, envelope
                flags = blob[3]
                envelope = (0, 32, 48, 48, 64)[(flags >> 1) & 0x07]
                geometry = wkb.loads(bytes(blob[8 + envelope:]))
                if geometry.is_empty:
                    continue
            except Exception:
                dropped += 1
                continue
            rows.append(dict(zip(others, record[:-1]), geometry=geometry))
    db.close()
    if dropped:
        print(f"  ({dropped} unreadable recording(s) skipped in "
              f"{Path(path).name})")
    if not rows:
        return None
    frame = gpd.GeoDataFrame(rows, geometry="geometry", crs=dataio.WGS84)
    return frame.to_crs(dataio.METRIC_CRS)


def source_files(clan: str) -> set:
    """The raw files the published layer says this clan came from.

    Matching raw filenames against the clan's name misses them. Manuvoora
    is spelled `manuvuoora` in one of its two files, so a name match found
    only Egobeyas Kuarisi's walk and lost Granville Nepo's entirely — and
    then reported the raw archives as holding less than the published
    layer. The pipeline already reconciles those spellings; the published
    layer records which file each recording came from, so ask it.
    """
    try:
        tracks = gpd.read_file(dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg",
                               layer="tracks_smoothed")
    except Exception:
        return set()
    if "source_name" not in tracks.columns:
        return set()
    want = tracks[tracks.clan.astype(str).str.lower()
                  .str.startswith(clan.lower())]
    return {str(v).lower() for v in want.source_name if str(v) != "nan"}


def recordings(clan: str) -> list:
    """Every feature in every raw archive belonging to this clan."""
    sources = source_files(clan)
    found = []
    for archive in sorted(dataio.RAW_DIR.glob("*.zip")):
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                if not member.lower().endswith((".gpkg", ".sqlite")):
                    continue
                folder = Path(member).parent.name or Path(member).stem
                stem = Path(member).stem.lower()
                if stem not in sources and clan.lower() not in (
                        f"{folder} {Path(member).name}".lower()):
                    continue
                with tempfile.NamedTemporaryFile(suffix=".gpkg",
                                                 delete=False) as handle:
                    handle.write(zf.read(member))
                    path = handle.name
                try:
                    try:
                        frame = gpd.read_file(path).to_crs(dataio.METRIC_CRS)
                    except Exception:
                        frame = _read_row_by_row(path)
                        if frame is None or frame.empty:
                            raise
                    names = [c for c in frame.columns if c != "geometry"]
                    with sqlite3.connect(path) as db:
                        db.execute("select 1")
                    for position, row in frame.iterrows():
                        if row.geometry is None or row.geometry.is_empty:
                            continue
                        values = {k: row.get(k) for k in names}
                        record = {
                            "folder": folder,
                            "file": Path(member).name,
                            "row": position + 1,
                            "text": typed_text(values),
                            "geometry": row.geometry,
                        }
                        # the walker, if the file itself carries one
                        for key in ("steward", "Steward"):
                            if key in values:
                                record[key] = values[key]
                        found.append(record)
                finally:
                    os.unlink(path)
    return found


MEMBER = re.compile(r"clan\s+member|^\s*\d{4}-\d{2}-\d{2}", re.I)


def walkers_by_file() -> dict:
    """Which steward each source file belongs to.

    The raw archives carry no steward column — the pipeline derives it,
    mostly from the filename, and resolves the spelling variants while it
    is there. Reading the free text instead found Rondi's walkers and
    missed Manuvoora's, Gumuyude's and Riribudeh's, so four maps said
    "unattributed" about surveys that name their walker in the filename.
    """
    try:
        tracks = gpd.read_file(dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg",
                               layer="tracks_smoothed")
    except Exception:
        return {}
    out: dict = {}
    for source, group in tracks.groupby("source_name"):
        names = sorted({str(v) for v in group.steward
                        if str(v).strip() not in ("", "nan", "None")})
        if names:
            out[str(source).lower()] = ", ".join(names)[:28]
    return out


def who(row: dict) -> str:
    """The person who walked it."""
    known = walkers_by_file().get(Path(row.get("file", "")).stem.lower())
    if known:
        return known
    for key in ("steward", "Steward"):
        value = row.get(key)
        if value and str(value).strip() not in ("", "nan", "None"):
            return " ".join(str(value).split())[:28]
    for line in row["text"]:
        if "clan member" in line.lower():
            cut = re.split(r"clan\s+member", line, flags=re.I)[0]
            cut = re.sub(r"^\s*\d{4}-\d{2}-\d{2}[\s\d:]*", "", cut)
            if cut.strip():
                return " ".join(cut.split())[:28]
    return "unattributed"


def describe(row: dict) -> str:
    """What the steward called this place, without their own name on it."""
    for line in row["text"]:
        if MEMBER.search(line) and "clan member" in line.lower():
            continue
        text = re.sub(r"^\s*\d{4}-\d{2}-\d{2}[\s\d:]*", "", line).strip()
        if not text or "clan member" in text.lower():
            continue
        if re.search(r"original (clan )?(land )?boundary|boundary mapping",
                     text, re.I):
            return ""
        return text[:58]
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clan", required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--site-length", type=float, default=500.0,
                        help="a recording shorter than this is a place, "
                             "not a stretch of boundary")
    args = parser.parse_args(argv)
    site_length = args.site_length

    found = recordings(args.clan)
    if not found:
        print(f"Nothing in the raw archives matching {args.clan!r}.")
        return 1

    total = sum(r["geometry"].length for r in found) / 1000
    flagged = [r for r in found if any(SACRED.search(t) for t in r["text"])]
    print(f"{args.clan}: {len(found)} recordings, {total:.1f} km raw")
    print(f"  {len(flagged)} carrying sacred or tambu wording, "
          f"{sum(r['geometry'].length for r in flagged) / 1000:.1f} km\n")
    site_length = args.site_length
    for index, row in enumerate(found, 1):
        mark = "SACRED?" if row in flagged else "       "
        print(f"  {index:2d} {mark} {row['geometry'].length:7.0f} m")
        for line in row["text"]:
            print(f"        {line[:104]}")

    # What the pipeline made of it, drawn behind the data so the two can
    # be compared. A map of the recordings alone cannot show whether the
    # boundary follows them.
    built = None
    derived: list = []
    derived_rows: list = []
    try:
        import chord_map
        import polygons as polygon_tools
        published = gpd.read_file(
            dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg",
            layer="tracks_smoothed").to_crs(dataio.METRIC_CRS)
        published = dataio.publishable(published, quiet=True)
        published["_unit"] = dataio.survey_group(published)
        match = published[published.clan.astype(str).str.lower()
                          .str.startswith(args.clan.lower())]
        if not match.empty:
            unit = match._unit.iloc[0]
            group = published[published._unit == unit]
            frame = polygon_tools.adopted_frame(unit)
            derived_rows = ([] if frame is None or frame.empty else
                            [(r.geometry, r["kind"], r["note"])
                             for _, r in frame.iterrows()])
            derived = [row[0] for row in derived_rows]
            built = polygon_tools.survey_polygon(
                chord_map.parts_of(group), 25.0, 0.50, 0.10,
                derived=derived, unit=unit)
    except Exception as error:
        print(f"  (could not build the polygon: {error})")

    walked_union = unary_union([r["geometry"] for r in found])
    shapes = unary_union([r["geometry"] for r in found]
                         + ([built["geometry"]] if built else []))
    minx, miny, maxx, maxy = shapes.bounds
    pad = max(maxx - minx, maxy - miny) * 0.10
    window = (minx - pad, miny - pad, maxx + pad, maxy + pad)

    figure, axis = plt.subplots(figsize=(11, 9.5), dpi=125)
    terrain.add_hillshade(axis, dataio.METRIC_CRS, alpha=0.36, bounds=window)
    try:
        streams = gpd.read_file(dataio.REFERENCE_DIR / "hydro"
                                / "streams.gpkg").to_crs(dataio.METRIC_CRS)
        streams = streams[streams.intersects(box(*window))]
        if not streams.empty:
            streams.plot(ax=axis, color="#7dd3fc", linewidth=1.1, zorder=1)
    except Exception:
        pass

    if built is not None:
        gpd.GeoSeries([built["geometry"]], crs=dataio.METRIC_CRS).plot(
            ax=axis, color="#1d4ed8", alpha=0.13, edgecolor="none", zorder=2)
        # Chaining recorded walks together is not the same as asserting
        # a line nobody walked, and the map must not say it is. A chord
        # replaced by the steward's own track between the same two
        # points adds no claim about where the boundary runs; a line
        # drawn along a river or a ridge does. Gumuyude's six adopted
        # segments are 2,127 m, of which 1,883 m is Philip Igai's own
        # footsteps traced back into a line — calling all of it inferred
        # would send the clan to confirm two kilometres of their own
        # steward's walking.
        #
        # The test is measurable: how much of the segment has walked
        # line beside it.
        for segment, kind, note in derived_rows:
            share = (segment.intersection(walked_union.buffer(30)).length
                     / segment.length if segment.length else 0)
            if share >= 0.80:
                axis.plot(*segment.xy, color="#0d9488", lw=3.0, zorder=6)
            else:
                axis.plot(*segment.xy, color="#f59e0b", lw=3.0, zorder=6,
                          linestyle=(0, (7, 2)))
        for bridge in built["bridges"]:
            axis.plot(*bridge.xy, color="#db2777", lw=2.4,
                      linestyle=(0, (5, 3)), zorder=7)

    # A short recording in the middle of a survey is a feature the steward
    # stopped to mark, not a stretch of boundary, and what he wrote on it
    # is its name. Those get drawn as places with their names against
    # them; the long lines are the boundary and need no label.
    # Sacred wording decides first, whatever the length. Sukandi's three
    # sacred sites are 1.4, 3.8 and 6.4 km of perimeter; judged on length
    # alone they read as boundary and were drawn as boundary.
    sites = [r for r in found
             if r["geometry"].length < site_length and r not in flagged]
    lines = [r for r in found
             if r["geometry"].length >= site_length and r not in flagged]

    walkers = sorted({who(r) for r in lines + sites})
    palette = ["#1f2937", "#1d4ed8", "#047857", "#b45309"]
    colours = {name: palette[i % len(palette)]
               for i, name in enumerate(walkers)}

    for row in lines:
        geometry = row["geometry"]
        for part in (geometry.geoms if hasattr(geometry, "geoms")
                     else [geometry]):
            axis.plot(*part.xy, color=colours.get(who(row), "#1f2937"),
                      lw=1.9, zorder=4, alpha=0.85)

    for row in flagged:
        geometry = row["geometry"]
        for part in (geometry.geoms if hasattr(geometry, "geoms")
                     else [geometry]):
            axis.plot(*part.xy, color="#c026d3", lw=2.8, zorder=6)
        if geometry.length >= site_length:
            spot = geometry.interpolate(0.5, normalized=True)
            axis.annotate(describe(row) or "sacred", (spot.x, spot.y),
                          xytext=(spot.x, spot.y
                                  + (window[3] - window[1]) * 0.04),
                          ha="center", fontsize=9, color="#c026d3",
                          zorder=10, arrowprops=dict(arrowstyle="-",
                                                     color="#c026d3", lw=0.9))

    placed = []
    for row in sorted(sites, key=lambda r: -r["geometry"].length):
        sacred = row in flagged
        colour = "#c026d3" if sacred else "#ea580c"
        geometry = row["geometry"]
        # The walking, not only the dot. A short recording is still a
        # steward walking: 452 m at garegummara hill was being drawn as
        # one point with nothing under it, so a stretch of Dusi's walk
        # looked like bare ground.
        for part in (geometry.geoms if hasattr(geometry, "geoms")
                     else [geometry]):
            axis.plot(*part.xy, color=colours.get(who(row), "#1f2937"),
                      lw=1.9, zorder=4, alpha=0.85)
        spot = geometry.interpolate(0.5, normalized=True)
        axis.plot(spot.x, spot.y, "o", ms=9, mfc=colour, mec="white",
                  mew=1.4, zorder=8)
        label = describe(row)
        if not label:
            continue
        # one label per place: the pair walked the same sites twice
        if any(spot.distance(q) < site_length * 1.6 for q in placed):
            continue
        placed.append(spot)
        step = (window[2] - window[0]) * 0.055
        axis.annotate(label, (spot.x, spot.y),
                      xytext=(spot.x + step, spot.y + step * 0.45),
                      fontsize=8.5, color=colour, ha="left", zorder=10,
                      arrowprops=dict(arrowstyle="-", color=colour, lw=0.8))

    axis.set_xlim(window[0], window[2])
    axis.set_ylim(window[1], window[3])
    axis.set_aspect("equal")
    axis.set_axis_off()
    # The area stays in the legend, and stays described as what it is.
    # The polygon encloses a number of hectares; it does not say the clan
    # owns them. Chords will move as they are corrected, overlaps with
    # neighbours have not been measured, and disputes are the thing this
    # survey exists to surface rather than something to be settled by a
    # figure printed large at the top of a map.
    axis.set_title(
        f"{args.clan} — mapping progress\n"
        + f"{len(found)} recordings, {total:.1f} km walked  ·  "
        + f"{len(lines)} stretch{'' if len(lines) == 1 else 'es'} of "
          f"boundary, {len(sites)} "
          f"place{'' if len(sites) == 1 else 's'} marked along it"
        + (f", {len(flagged)} sacred" if flagged else ""),
        fontsize=13, pad=10)
    handles = []
    if built is not None:
        from matplotlib.patches import Patch
        handles.append(Patch(
            facecolor="#1d4ed8", alpha=0.13,
            label=f"{built['area_ha']:,.0f} ha enclosed by the mapping so "
                  f"far ({built['basis']})"))
    handles += [Line2D([0], [0], color=colours[name], lw=1.9, label=name)
                for name in walkers]
    def walked_share(segment):
        if not segment.length:
            return 0.0
        return (segment.intersection(walked_union.buffer(30)).length
                / segment.length)

    chained = [r for r in derived_rows if walked_share(r[0]) >= 0.80]
    asserted = [r for r in derived_rows if walked_share(r[0]) < 0.80]
    if chained:
        handles.append(Line2D(
            [0], [0], color="#0d9488", lw=3.0,
            label=f"Recorded walks chained into one line — "
                  f"{sum(r[0].length for r in chained) / 1000:.2f} km "
                  f"(the ground is walked)"))
    if asserted:
        handles.append(Line2D(
            [0], [0], color="#f59e0b", lw=3.0, linestyle=(0, (7, 2)),
            label=f"Inferred where nobody walked — "
                  f"{sum(r[0].length for r in asserted) / 1000:.2f} km, "
                  f"for the clan to confirm"))
    if built is not None and built["bridges"]:
        handles.append(Line2D(
            [0], [0], color="#db2777", lw=2.4, linestyle=(0, (5, 3)),
            label=f"Still to walk — {len(built['bridges'])} gap(s), "
                  f"{sum(b.length for b in built['bridges']) / 1000:.2f} km"))
    handles += [
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#ea580c",
               markeredgecolor="white", markersize=9,
               label=f"A place the steward walked and marked — {len(sites)}"
                     + (f", {sum(1 for r in sites if not describe(r))} "
                        f"not yet named"
                        if any(not describe(r) for r in sites) else "")),
        Line2D([0], [0], color="#c026d3", lw=2.8,
               label="Its description mentions a sacred site or tambu"),
        Line2D([0], [0], color="#7dd3fc", lw=1.1,
               label="Watercourse, from the terrain model"),
    ]
    # Outside the frame. A legend long enough to need reading is long
    # enough to cover the thing it describes.
    axis.legend(handles=handles, loc="upper left", fontsize=9,
                bbox_to_anchor=(1.01, 1.0), borderaxespad=0, frameon=False)
    axis.annotate(
        "Area enclosed by the mapping to date. Not a statement of what the "
        "clan owns:\nboundaries not yet confirmed will move, and overlaps "
        "with neighbours are not yet measured.",
        xy=(0.0, -0.035), xycoords="axes fraction", ha="left", va="top",
        fontsize=8.5, color="#4b5563")

    span = window[2] - window[0]
    bar = 1000 if span > 4000 else 500
    x0 = window[0] + span * 0.05
    y0 = window[1] + (window[3] - window[1]) * 0.05
    axis.plot([x0, x0 + bar], [y0, y0], color="#111827", lw=3)
    axis.annotate(f"{bar / 1000:g} km", (x0 + bar / 2, y0), xytext=(0, 7),
                  textcoords="offset points", ha="center", fontsize=9)

    out = args.out or (dataio.OUT_DIR / "queries"
                       / f"{dataio.safe_name(args.clan)}_everything.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(out, bbox_inches="tight")
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
