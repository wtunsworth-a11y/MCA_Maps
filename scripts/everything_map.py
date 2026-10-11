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
SACRED = re.compile(r"sacred|secret\s*s?i?ght|tambu|taboo|tabu|spirit|"
                    r"burial|graveyard|skull|forbidden|holy|holly|masalai",
                    re.I)
SKIP = {"fid", "geom", "line", "locus_activity", "id", "ogc_fid",
        "tessellate", "extrude", "visibility", "layer", "path"}


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
                    or CLOCK.match(line) or TIMESTAMP.match(line)):
                continue
            out.append(line)
    return out


def recordings(clan: str) -> list:
    """Every feature in every raw archive belonging to this clan."""
    found = []
    for archive in sorted(dataio.RAW_DIR.glob("*.zip")):
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                if not member.lower().endswith((".gpkg", ".sqlite")):
                    continue
                folder = Path(member).parent.name or Path(member).stem
                if clan.lower() not in f"{folder} {Path(member).name}".lower():
                    continue
                with tempfile.NamedTemporaryFile(suffix=".gpkg",
                                                 delete=False) as handle:
                    handle.write(zf.read(member))
                    path = handle.name
                try:
                    frame = gpd.read_file(path).to_crs(dataio.METRIC_CRS)
                    names = [c for c in frame.columns if c != "geometry"]
                    with sqlite3.connect(path) as db:
                        db.execute("select 1")
                    for position, row in frame.iterrows():
                        if row.geometry is None or row.geometry.is_empty:
                            continue
                        values = {k: row.get(k) for k in names}
                        found.append({
                            "folder": folder,
                            "file": Path(member).name,
                            "row": position + 1,
                            "text": typed_text(values),
                            "geometry": row.geometry,
                        })
                finally:
                    os.unlink(path)
    return found


MEMBER = re.compile(r"clan\s+member|^\s*\d{4}-\d{2}-\d{2}", re.I)


def who(row: dict) -> str:
    """The person, from whichever line carries their name."""
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
    for index, row in enumerate(found, 1):
        mark = "SACRED?" if row in flagged else "       "
        print(f"  {index:2d} {mark} {row['geometry'].length:7.0f} m")
        for line in row["text"]:
            print(f"        {line[:104]}")

    shapes = unary_union([r["geometry"] for r in found])
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

    # A short recording in the middle of a survey is a feature the steward
    # stopped to mark, not a stretch of boundary, and what he wrote on it
    # is its name. Those get drawn as places with their names against
    # them; the long lines are the boundary and need no label.
    sites = [r for r in found if r["geometry"].length < site_length]
    lines = [r for r in found if r["geometry"].length >= site_length]

    walkers = sorted({who(r) for r in lines})
    palette = ["#1f2937", "#1d4ed8", "#047857", "#b45309"]
    colours = {name: palette[i % len(palette)]
               for i, name in enumerate(walkers)}

    for row in lines:
        geometry = row["geometry"]
        for part in (geometry.geoms if hasattr(geometry, "geoms")
                     else [geometry]):
            axis.plot(*part.xy, color=colours.get(who(row), "#1f2937"),
                      lw=1.9, zorder=4, alpha=0.85)

    placed = []
    for row in sorted(sites, key=lambda r: -r["geometry"].length):
        sacred = row in flagged
        colour = "#c026d3" if sacred else "#ea580c"
        geometry = row["geometry"]
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
    axis.set_title(f"{args.clan} — everything in the raw files: "
                   f"{len(found)} recordings, {total:.1f} km\n"
                   f"{len(lines)} stretches of boundary and {len(sites)} "
                   f"places marked along it", fontsize=13, pad=10)
    handles = [Line2D([0], [0], color=colours[name], lw=1.9, label=name)
               for name in walkers]
    handles += [
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#ea580c",
               markeredgecolor="white", markersize=9,
               label="A place the steward stopped to mark"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#c026d3",
               markeredgecolor="white", markersize=9,
               label="Its description mentions a sacred site or tambu"),
        Line2D([0], [0], color="#7dd3fc", lw=1.1,
               label="Watercourse, from the terrain model"),
    ]
    axis.legend(handles=handles, loc="lower left", fontsize=9,
                framealpha=0.94)
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
