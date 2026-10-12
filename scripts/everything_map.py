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
import textwrap
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
from shapely.geometry import Point, box  # noqa: E402
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


def _lines_from_wkb(body: bytes):
    """Read a line geometry by hand, dropping any part with one point.

    A MultiLineString holding a single one-point part cannot be loaded
    at all — not by geopandas, not by shapely — so one bad fix in a
    recording takes the whole file with it. Kasaki is one file holding
    one row, and that row is 15.1 km of boundary; the pipeline repaired
    it at smoothing time and the raw reader could not open it.

    This walks the WKB itself and keeps the parts that are lines.
    """
    import struct
    from shapely.geometry import LineString, MultiLineString

    def read_line(data, at):
        order = "<" if data[at] == 1 else ">"
        kind = struct.unpack_from(order + "I", data, at + 1)[0]
        dims = 2 + (1 if kind // 1000 in (1, 3) else 0)                  + (1 if kind // 1000 in (2, 3) else 0)
        count = struct.unpack_from(order + "I", data, at + 5)[0]
        at += 9
        points = []
        for _ in range(count):
            values = struct.unpack_from(order + f"{dims}d", data, at)
            points.append(values[:2])
            at += 8 * dims
        return (LineString(points) if len(points) >= 2 else None), at

    try:
        order = "<" if body[0] == 1 else ">"
        kind = struct.unpack_from(order + "I", body, 1)[0]
        base = kind % 1000
        if base == 2:
            line, _ = read_line(body, 0)
            return line
        if base == 5:
            count = struct.unpack_from(order + "I", body, 5)[0]
            at, parts = 9, []
            for _ in range(count):
                line, at = read_line(body, at)
                if line is not None:
                    parts.append(line)
            return MultiLineString(parts) if parts else None
    except Exception:
        return None
    return None


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
                body = bytes(blob[8 + envelope:])
                try:
                    geometry = wkb.loads(body)
                except Exception:
                    geometry = _lines_from_wkb(body)
                if geometry is None or geometry.is_empty:
                    dropped += 1
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


def resolve_unit(clan: str) -> str | None:
    """The one survey unit this name means.

    `Murai` is two clans — Zone 2 and Zone 7B, eight kilometres apart,
    different stewards — and matching on the name drew both on one map
    with one clan's polygon. Rule 11: never match by a typed name.
    """
    try:
        tracks = gpd.read_file(dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg",
                               layer="tracks_smoothed")
    except Exception:
        return None
    tracks["_unit"] = dataio.survey_group(tracks)
    named = tracks[tracks.clan.astype(str).str.lower()
                   .str.startswith(clan.lower())]
    if named.empty:
        return None
    units = sorted({str(u) for u in named._unit})
    if len(units) > 1:
        exact = [u for u in units if u.split(" — ")[0].lower() == clan.lower()]
        if len(exact) != 1:
            raise SystemExit(
                f"{clan!r} means more than one survey — "
                + ", ".join(units) + ". Name one of them.")
        return exact[0]
    return units[0]


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
    unit = resolve_unit(clan)
    if unit is None:
        return set()
    tracks["_unit"] = dataio.survey_group(tracks)
    want = tracks[tracks._unit == unit]
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
                # Only the files this survey actually came from. No
                # fallback to the name: that is what put two clans
                # called Murai on one map.
                if Path(member).stem.lower() not in sources:
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


def description_of(row: dict) -> str:
    """Everything the steward wrote about this recording, as one piece.

    `describe` returns a short label for the map. This returns the whole
    of it, including the `cmt` field, which is where Philip Jukaro put
    Juaiko's boundary description and the clan's history and which no
    map has ever shown.
    """
    kept = []
    for line in row["text"]:
        body = re.sub(r"^\s*\d{4}-\d{2}-\d{2}[\s\d:oO]*", "", line).strip()
        if not body or len(body) < 4:
            continue
        if body in kept:
            continue
        kept.append(body)
    joined = "  ".join(kept)
    return joined if len(joined) > 30 else ""


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
    parser.add_argument("--zoom", type=int, default=None,
                        help="frame the map on one numbered gap")
    parser.add_argument("--window", type=float, nargs=4, default=None,
                        metavar=("X0", "Y0", "X1", "Y1"),
                        help="frame the map on these metric-CRS bounds")
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
    # Judge an adopted segment against the smoothed layer it was derived
    # from, not the raw tracks: the two differ by several metres and the
    # comparison is then measuring the smoothing.
    try:
        import chord_map as _cm
        _pub = gpd.read_file(dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg",
                             layer="tracks_smoothed").to_crs(dataio.METRIC_CRS)
        _pub = dataio.publishable(_pub, quiet=True)
        _pub["_unit"] = dataio.survey_group(_pub)
        _mine = _pub[_pub.clan.astype(str).str.lower()
                     .str.startswith(args.clan.lower())]
        if not _mine.empty:
            walked_union = unary_union(_cm.parts_of(
                _pub[_pub._unit == _mine._unit.iloc[0]]))
    except Exception:
        pass
    shapes = unary_union([r["geometry"] for r in found]
                         + ([built["geometry"]] if built else []))
    minx, miny, maxx, maxy = shapes.bounds
    pad = max(maxx - minx, maxy - miny) * 0.10
    window = (minx - pad, miny - pad, maxx + pad, maxy + pad)

    if args.window:
        window = tuple(args.window)

    # Frame on one gap when asked. A 1,274 ha clan drawn on one page puts
    # a 35 m gap inside the width of its own label.
    if (args.zoom is not None and args.window is None
            and built is not None and built["bridges"]):
        import chord_map as _zm
        _order = sorted(built["bridges"], key=lambda b: -b.length)
        _nums = _zm.numbering(unit, _order, record=False)
        _want = [b for i, b in enumerate(_order)
                 if _nums[i] == args.zoom]
        if not _want:
            print(f"  (no gap numbered {args.zoom}; have {sorted(_nums.values())})")
        else:
            x0, y0, x1, y1 = _want[0].bounds
            reach = max(x1 - x0, y1 - y0, 200.0) * 0.85
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            window = (mx - reach, my - reach, mx + reach, my + reach)

    # Anything the steward wrote is numbered on the map and printed in
    # full beneath it. Juaiko's boundary description — "Follow the Salm
    # river down to Hiefiruna and follow up-stream Ujai river to
    # sinigir" — was in the file all along and never reached a map.
    spoken = [r for r in found if description_of(r)]
    spoken.sort(key=lambda r: -r["geometry"].length)
    told = {id(r): n for n, r in enumerate(spoken, 1)}

    panel = []
    for row in spoken:
        body = description_of(row)
        panel.append(f"{told[id(row)]}.  {row['geometry'].length:,.0f} m — "
                     f"{body}")
    wrapped: list = []
    for entry in panel:
        lines = textwrap.wrap(entry, 150, subsequent_indent="     ")
        wrapped.extend(lines)
        wrapped.append("")
    text_height = 0.17 * len(wrapped) if wrapped else 0

    # Three bands down the page: the map, then the caveat, then the words
    # the stewards typed. The caveat used to be hung off the axes and the
    # panel off the figure, so on a clan with a lot of notes they landed on
    # top of each other.
    figure_height = 9.5 + text_height
    caveat_band = 0.42
    axis_floor = (text_height + caveat_band) / figure_height
    figure = plt.figure(figsize=(11, figure_height), dpi=125)
    axis = figure.add_axes([0.02, axis_floor, 0.96,
                            1 - axis_floor - 0.03])
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
            share = (segment.intersection(walked_union.buffer(10)).length
                     / segment.length if segment.length else 0)
            if share >= 0.80:
                axis.plot(*segment.xy, color="#0d9488", lw=3.0, zorder=6)
            else:
                axis.plot(*segment.xy, color="#f59e0b", lw=3.0, zorder=6,
                          linestyle=(0, (7, 2)))
        # Numbered, so a gap can be named and discussed. The numbers
        # come from the shared register, so they survive between runs:
        # a closed gap disappears and a new one takes the next number.
        import chord_map as _cm
        gap_order = sorted(built["bridges"], key=lambda b: -b.length)
        gap_numbers = _cm.numbering(unit, gap_order)
        for index, bridge in enumerate(gap_order):
            axis.plot(*bridge.xy, color="#db2777", lw=2.4,
                      linestyle=(0, (5, 3)), zorder=7)
            middle = bridge.interpolate(0.5, normalized=True)
            (ax0, ay0), (ax1, ay1) = (bridge.coords[0][:2],
                                      bridge.coords[-1][:2])
            dx, dy = ax1 - ax0, ay1 - ay0
            span = (dx * dx + dy * dy) ** 0.5 or 1.0
            step = (window[2] - window[0]) * 0.030
            spot = None
            for reach in range(1, 10):
                for sign in (1, -1):
                    here = Point(middle.x - dy / span * step * reach * sign,
                                 middle.y + dx / span * step * reach * sign)
                    if built["geometry"].contains(here):
                        continue
                    if min(walked_union.distance(here),
                           min(b.distance(here) for b in gap_order)) >= step:
                        spot = here
                        break
                if spot is not None:
                    break
            if spot is None:
                spot = Point(middle.x - dy / span * step,
                             middle.y + dx / span * step)
            axis.annotate(str(gap_numbers[index]), (middle.x, middle.y),
                          xytext=(spot.x, spot.y), fontsize=10.5,
                          fontweight="bold", color="white", ha="center",
                          va="center", zorder=10,
                          arrowprops=dict(arrowstyle="-", color="#db2777",
                                          lw=1.1, shrinkA=6, shrinkB=1),
                          bbox=dict(boxstyle="circle,pad=0.30",
                                    facecolor="#db2777", edgecolor="white",
                                    linewidth=1.2))

    # A short recording in the middle of a survey is a feature the steward
    # stopped to mark, not a stretch of boundary, and what he wrote on it
    # is its name. Those get drawn as places with their names against
    # them; the long lines are the boundary and need no label.
    # Sacred wording decides first, whatever the length. Sukandi's three
    # sacred sites are 1.4, 3.8 and 6.4 km of perimeter; judged on length
    # alone they read as boundary and were drawn as boundary.
    # A place is a recording that comes back to where it started: the
    # steward walked round something and stopped. A stretch goes
    # somewhere. Length alone called 452 m of Dusi's boundary walk at
    # garegummara hill a point, because it was under 500 m.
    def is_a_place(row):
        geometry = row["geometry"]
        if geometry.length <= 0:
            return True
        ends = []
        for part in (geometry.geoms if hasattr(geometry, "geoms")
                     else [geometry]):
            ends += [Point(part.coords[0][:2]), Point(part.coords[-1][:2])]
        spread = max(a.distance(b) for a in ends for b in ends)
        return (spread / geometry.length) < 0.35

    sites = [r for r in found if r not in flagged and is_a_place(r)]
    lines = [r for r in found if r not in flagged and not is_a_place(r)]

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
        # Ten metres: the spread between two stewards walking the same
        # boundary. We measured a pair at median 3 m and 90th percentile
        # 12 m, so a tighter threshold calls one steward's walk "not
        # walked" because the other's line is the reference — Sahirut's
        # 217 m scored 36% at 5 m with Solomon Makanisa's track under
        # 88% of it. Thirty metres goes the other way and measures
        # nearness rather than coverage: Riribudeh's 48 m straight join
        # is 100% at 30 m and 66% at 10 m, and nobody walked that span.
        return (segment.intersection(walked_union.buffer(10)).length
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
        for index, bridge in enumerate(gap_order):
            handles.append(Line2D(
                [0], [0], color="none",
                label=f"      {gap_numbers[index]}.  {bridge.length:,.0f} m"))
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
        xy=(0.02, axis_floor - 0.06 / figure_height),
        xycoords="figure fraction", ha="left", va="top",
        fontsize=8.5, color="#4b5563")

    for row in spoken:
        geometry = row["geometry"]
        here = geometry.interpolate(0.5, normalized=True)
        axis.annotate(str(told[id(row)]), (here.x, here.y), fontsize=8.5,
                      fontweight="bold", color="white", ha="center",
                      va="center", zorder=11,
                      bbox=dict(boxstyle="circle,pad=0.22",
                                facecolor="#111827", edgecolor="white",
                                linewidth=1.0))

    if wrapped:
        figure.text(0.02, text_height / figure_height, "\n".join(wrapped),
                    fontsize=7.6, va="top", ha="left", family="monospace",
                    color="#111827")

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
