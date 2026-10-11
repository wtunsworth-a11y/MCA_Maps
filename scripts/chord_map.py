#!/usr/bin/env python3
"""A numbered map of the lines the pipeline drew across one clan's boundary.

The working map for going through a survey with someone who knows the ground.
Every line the closing step drew is numbered, longest first, and sorted into
two kinds by a measurement rather than a guess:

**Gap** — the line crosses ground nobody walked. Only the field can close it.

**Ends to tie** — walked line runs alongside the whole way. The boundary there
is recorded; the recording simply stopped and restarted along a stretch the
steward had already covered, and only the ends need joining. We can do that
ourselves — but see the warning below.

The test is how much of each line has walked line within `--tolerance` of it.
Kasaki's four lines were 100% covered and were not gaps at all; Juaiko's
longest was 12% covered and is 917 m of real fieldwork.

**Tying is only safe when it closes the survey outright.** A tie from a loose
end to a point part-way along another piece makes a T-junction, which uses up
two free ends and creates none. Close every one and the survey needs no
bridging at all (Kasaki). Leave one over and the closing step has nothing to
read, and draws a chord somewhere else instead — Gumuyude grew a false 793 m
line that way, then a 1,945 m one.

Usage:
    python scripts/chord_map.py --clan Gumuyude
    python scripts/chord_map.py --clan Juaiko --out output/queries/juaiko.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402
import polygons as polygon_tools  # noqa: E402
import terrain  # noqa: E402

GAP = "#db2777"
TIE = "#15803d"
WATER = "#7dd3fc"

# Numbers have to survive a fix. A chord discussed as "number 3" is still
# number 3 next time, a chord that has been closed simply disappears from the
# list, and anything newly drawn takes the next free number. Renumbering from
# the top each run makes the previous conversation useless.
REGISTER = dataio.REPO_ROOT / "data" / "reference" / "chord_numbers.json"


def numbering(unit: str, bridges: list, record: bool = True) -> dict:
    """Stable numbers for this clan's drawn lines, kept between runs.

    Matched on where a line is, not on how long it is or where it sits in the
    order: a fix next door can change both. A line within 100 m of one seen
    before, by Hausdorff distance, is taken to be that line.

    `record=False` for anything speculative. The numbers are what the survey
    is discussed by — "fix chord 1", "chord 6 is fixed" — so a render of a
    proposal that is then rejected must not leave its numbers behind. One
    did: a throwaway proposal map issued 9 and 10 to lines that were never
    accepted, and the next real run found nothing it recognised and renamed
    the whole survey 11, 12, 13 in the middle of a conversation about 5, 6,
    7 and 8.
    """
    import json

    book = {}
    if REGISTER.exists():
        try:
            book = json.loads(REGISTER.read_text(encoding="utf-8"))
        except Exception:
            book = {}
    seen = book.get(unit, {})

    from shapely import wkt
    known = {}
    for number, text in seen.items():
        try:
            known[int(number)] = wkt.loads(text)
        except Exception:
            continue

    out, taken = {}, set()
    for index, line in enumerate(bridges):
        match = None
        for number, old in known.items():
            if number in taken:
                continue
            if old.hausdorff_distance(line) < 100:
                match = number
                break
        if match is not None:
            out[index] = match
            taken.add(match)
    nxt = max(list(known) + [0]) + 1
    for index in range(len(bridges)):
        if index not in out:
            out[index] = nxt
            nxt += 1

    if record:
        book[unit] = {str(out[i]): bridges[i].wkt for i in range(len(bridges))}
        REGISTER.parent.mkdir(parents=True, exist_ok=True)
        REGISTER.write_text(json.dumps(book, indent=1) + "\n",
                            encoding="utf-8")
    return out


def parts_of(frame: gpd.GeoDataFrame) -> list:
    out = []
    for geometry in frame.geometry:
        if geometry is None:
            continue
        out.extend(geometry.geoms if hasattr(geometry, "geoms") else [geometry])
    return [p for p in out if p.length > 0]


def classify(unit: str, bridges: list, walked, tolerance: float,
             cut: float, record: bool = True):
    """Each drawn line, with how much of it already has walked line beside it."""
    ordered = sorted(bridges, key=lambda b: -b.length)
    numbers = numbering(unit, ordered, record=record)
    rows = []
    for index, line in enumerate(ordered):
        near = line.intersection(walked.buffer(tolerance)).length / line.length
        rows.append({"n": numbers[index], "line": line, "share": near * 100,
                     "kind": "gap" if near < cut else "tie"})
    return rows


def render(unit: str, group: gpd.GeoDataFrame, built: dict, rows: list,
           derived, out_path: Path, tolerance: float) -> Path:
    figure, axis = plt.subplots(figsize=(10, 8.5), dpi=150)
    walked = unary_union(parts_of(group))
    minx, miny, maxx, maxy = unary_union(
        [built["geometry"], walked]).bounds
    pad = max(maxx - minx, maxy - miny) * 0.09
    window = (minx - pad, miny - pad, maxx + pad, maxy + pad)
    terrain.add_hillshade(axis, dataio.METRIC_CRS, alpha=0.42, bounds=window)
    axis.set_xlim(window[0], window[2])
    axis.set_ylim(window[1], window[3])

    # Water, for somewhere to stand. The Clan Stewards describe boundaries by
    # rivers — down the Salm to the Makamata fall, along the Baraje — so the
    # drainage is the context that means something here. It is modelled from
    # the 30 m DEM, not surveyed, so it is drawn faintly and named as such.
    try:
        streams = gpd.read_file(dataio.REPO_ROOT / "data" / "reference"
                                / "hydro" / "streams.gpkg").to_crs(
                                    dataio.METRIC_CRS)
        from shapely.geometry import box
        streams = streams[streams.intersects(box(*window))]
        if not streams.empty:
            streams.plot(ax=axis, color=WATER, linewidth=1.1, zorder=1,
                         alpha=0.9)
    except Exception:
        streams = None

    gpd.GeoSeries([built["geometry"]], crs=dataio.METRIC_CRS).plot(
        ax=axis, color="#1d4ed8", alpha=0.15, edgecolor="none", zorder=2)
    group.plot(ax=axis, color="#1f2937", linewidth=1.3, zorder=5)
    if derived is not None and len(derived):
        derived.plot(ax=axis, color="#7c3aed", linewidth=1.8, zorder=6)

    for row in rows:
        colour = GAP if row["kind"] == "gap" else TIE
        gpd.GeoSeries([row["line"]], crs=dataio.METRIC_CRS).plot(
            ax=axis, color=colour, linewidth=2.6, linestyle=(0, (5, 3)),
            zorder=7)
        point = row["line"].interpolate(0.5, normalized=True)
        axis.annotate(str(row["n"]), (point.x, point.y), fontsize=10.5,
                      fontweight="bold", color="white", ha="center",
                      va="center", zorder=9,
                      bbox=dict(boxstyle="circle,pad=0.30", facecolor=colour,
                                edgecolor="white", linewidth=1.2))

    x0 = window[0] + (window[2] - window[0]) * 0.06
    y0 = window[1] + (window[3] - window[1]) * 0.04
    axis.plot([x0, x0 + 1000], [y0, y0], color="#111827", lw=3, zorder=10)
    axis.annotate("1 km", (x0 + 500, y0), xytext=(0, 7),
                  textcoords="offset points", ha="center", fontsize=9,
                  zorder=10)
    axis.set_axis_off()

    drawn = sum(r["line"].length for r in rows) / 1000
    gaps = [r for r in rows if r["kind"] == "gap"]
    axis.set_title(
        f"{unit}: the drawn lines, numbered\n"
        f"{group.geometry.length.sum() / 1000:.1f} km walked  ·  "
        f"{built['area_ha']:,.0f} ha  ·  {drawn:.2f} km drawn, "
        f"{sum(r['line'].length for r in gaps) / 1000:.2f} km of it real gap",
        fontsize=12.5, pad=10)

    # Listed outside the frame: a legend long enough to need numbering is a
    # legend long enough to cover the thing it describes.
    handles = [Patch(facecolor="#1d4ed8", alpha=0.15,
                     label=f"Land as mapped — {built['area_ha']:,.0f} ha"),
               Line2D([0], [0], color="#1f2937", lw=2, label="Walked")]
    if streams is not None and not streams.empty:
        handles.append(Line2D([0], [0], color=WATER, lw=1.6,
                              label="Watercourse, from the terrain model"))
    if derived is not None and len(derived):
        handles.append(Line2D([0], [0], color="#7c3aed", lw=1.8,
                              label="Boundary derived, not walked"))
    for row in rows:
        colour = GAP if row["kind"] == "gap" else TIE
        handles.append(Line2D(
            [0], [0], color=colour, lw=2.4, linestyle=(0, (5, 3)),
            label=f"{row['n']}.  {row['line'].length:5.0f} m — "
                  + ("gap" if row["kind"] == "gap" else "ends to tie")
                  + f", {row['share']:.0f}% has walked line within "
                    f"{tolerance:.0f} m"))
    axis.legend(handles=handles, loc="upper left",
                bbox_to_anchor=(1.01, 1.0), fontsize=8.5, frameon=False)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(out_path, bbox_inches="tight")
    plt.close(figure)
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clan", required=True)
    parser.add_argument("--gpkg", type=Path,
                        default=dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--tolerance", type=float, default=50.0,
                        help="how close walked line has to be to count as "
                             "running alongside (default 50 m)")
    parser.add_argument("--cut", type=float, default=0.50,
                        help="share below which a line counts as a real gap")
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
    derived = polygon_tools.adopted_frame(unit)
    built = polygon_tools.survey_polygon(
        parts_of(group), 25.0, 0.50, 0.10,
        derived=polygon_tools.adopted_segments(unit), unit=unit)
    if not built:
        print(f"{unit}: no polygon could be built.")
        return 1
    bridges = built.get("bridges") or []
    if not bridges:
        print(f"{unit}: nothing drawn — the boundary closes on the walk.")
        return 0

    walked = unary_union(parts_of(group))
    rows = classify(unit, bridges, walked, args.tolerance, args.cut)
    out = args.out or (dataio.OUT_DIR / "queries"
                       / f"{dataio.safe_name(unit)}_chords.png")
    render(unit, group, built, rows, derived, out, args.tolerance)

    gaps = [r for r in rows if r["kind"] == "gap"]
    ties = [r for r in rows if r["kind"] == "tie"]
    print(f"{unit}: {built['area_ha']:,.0f} ha, "
          f"{group.geometry.length.sum() / 1000:.1f} km walked\n")
    print(f"  {'#':>2} {'length':>8}  {'beside walked line':>19}  what it is")
    for row in rows:
        print(f"  {row['n']:>2} {row['line'].length:7.0f} m  "
              f"{row['share']:17.0f}%  "
              + ("GAP — needs walking" if row["kind"] == "gap"
                 else "ends to tie"))
    print(f"\n  {len(gaps)} real gap(s), "
          f"{sum(r['line'].length for r in gaps) / 1000:.2f} km")
    print(f"  {len(ties)} to tie, "
          f"{sum(r['line'].length for r in ties) / 1000:.2f} km")
    if ties:
        print("\n  Tying helps only if it closes the survey outright. "
              "Leave one end\n  over and the closing step draws a chord "
              "somewhere else instead.")
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
