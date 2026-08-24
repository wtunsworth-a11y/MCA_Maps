#!/usr/bin/env python3
"""A numbered map of one clan's gaps, to ask the field what each one is.

A gap in a boundary can be any of several things, and only the field knows
which: ground not yet walked, ground that cannot be walked, or a straight line
the clan is content with. Those need opposite treatment — one is a job for a
steward, one is a job for an editor, one is already finished — and until they
are told apart the pipeline treats them all as unfinished survey.

This is the question put in a form somebody can answer: the clan's walked line
in grey, every gap drawn in pink and **numbered**, with a table of lengths.
The reply comes back as "gap 3 is the Jarahe gorge, join it straight" and goes
into data/reference/field_notes.json against that number.

Usage:
    python scripts/gap_map.py --clan Manuvoora
    python scripts/gap_map.py --clan Manuvoora --out output/queries/manuvoora_gaps.png
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
from shapely.ops import unary_union  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402
import polygons as polygon_tools  # noqa: E402
import terrain  # noqa: E402

WALK_COLOUR = "#334155"
GAP_COLOUR = "#db2777"
RIVER_COLOUR = "#0e7490"
AGREED_COLOUR = "#15803d"
JOINED_COLOUR = "#7c3aed"


def parts_of(frame: gpd.GeoDataFrame) -> list:
    out = []
    for geometry in frame.geometry:
        if geometry is None:
            continue
        out.extend(geometry.geoms if hasattr(geometry, "geoms") else [geometry])
    return out


def water_share(line, streams, tolerance: float = 100.0) -> float:
    """How much of a gap follows a watercourse in the terrain model.

    Corroboration only. The modelled drainage is derived from a 30 m DEM, not
    surveyed, so a high share is a reason to ask whether the gap is a river —
    never a reason to assert that it is.
    """
    if streams is None or line.length <= 0:
        return 0.0
    return line.intersection(streams.buffer(tolerance)).length / line.length * 100


def render(clan: str, zone: str, group: gpd.GeoDataFrame, bridges: list,
           streams, out_path: Path, derived=None) -> Path:
    figure, axis = plt.subplots(figsize=(10, 8.5), dpi=130)

    own = unary_union(list(group.geometry))
    minx, miny, maxx, maxy = own.bounds
    pad = max(maxx - minx, maxy - miny) * 0.12
    window = (minx - pad, miny - pad, maxx + pad, maxy + pad)
    terrain.add_hillshade(axis, dataio.METRIC_CRS, alpha=0.45, bounds=window)
    axis.set_xlim(window[0], window[2])
    axis.set_ylim(window[1], window[3])

    group.plot(ax=axis, color=WALK_COLOUR, linewidth=1.3, zorder=4)
    kinds = set()
    if derived is not None and len(derived):
        for kind, colour in (("river_routed", RIVER_COLOUR),
                             ("agreed_straight", AGREED_COLOUR),
                             ("end_joined", JOINED_COLOUR)):
            rows = derived[derived["kind"] == kind]
            if rows.empty:
                continue
            kinds.add(kind)
            rows.plot(ax=axis, color=colour, linewidth=1.8, zorder=5)

    ordered = sorted(bridges, key=lambda b: -b.length)
    rows = []
    for number, bridge in enumerate(ordered, start=1):
        gpd.GeoSeries([bridge], crs=dataio.METRIC_CRS).plot(
            ax=axis, color=GAP_COLOUR, linewidth=2.0, linestyle=(0, (5, 3)),
            zorder=6)
        point = bridge.interpolate(0.5, normalized=True)
        axis.annotate(str(number), (point.x, point.y), fontsize=11,
                      fontweight="bold", color="white", ha="center",
                      va="center", zorder=8,
                      bbox=dict(boxstyle="circle,pad=0.32",
                                facecolor=GAP_COLOUR, edgecolor="white",
                                linewidth=1.2))
        rows.append((number, bridge.length / 1000,
                     water_share(bridge, streams)))

    axis.set_axis_off()
    total = sum(r[1] for r in rows)
    axis.set_title(
        f"{clan} — {zone}: what is each gap?\n"
        f"{group.geometry.length.sum() / 1000:.1f} km walked, "
        f"{total:.1f} km in {len(rows)} gaps nobody walked",
        fontsize=12, pad=10)

    legend = [Line2D([0], [0], color=WALK_COLOUR, lw=2, label="Walked")]
    if "river_routed" in kinds:
        legend.append(Line2D([0], [0], color=RIVER_COLOUR, lw=2,
                             label="River line — from the terrain model, "
                                   "not walked"))
    if "agreed_straight" in kinds:
        legend.append(Line2D([0], [0], color=AGREED_COLOUR, lw=2,
                             label="Straight line the clan agrees to"))
    if "end_joined" in kinds:
        legend.append(Line2D([0], [0], color=JOINED_COLOUR, lw=2,
                             label="Open ends joined by hand — not walked"))
    legend.append(Line2D([0], [0], color=GAP_COLOUR, lw=2, linestyle=(0, (5, 3)),
                         label="Gap — nobody walked this"))
    for number, km, share in rows:
        legend.append(Line2D([0], [0], color="none",
                             label=f"  {number}.  {km:.2f} km"
                                   + (f"  ({share:.0f}% on modelled water)"
                                      if share >= 10 else "")))
    # Upper left: the gaps themselves are what the reader needs unobstructed,
    # and a legend that covers three of them defeats the point of numbering.
    axis.legend(handles=legend, loc="upper left", fontsize=8.5, frameon=True,
                handlelength=1.6, framealpha=0.92)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(out_path, bbox_inches="tight")
    plt.close(figure)
    return out_path, rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clan", required=True)
    parser.add_argument("--steward", default=None,
                        help="one steward's walk on its own. Use this when "
                             "the field annotated a printout of a single "
                             "steward's map: the gaps in the joined survey "
                             "include the lines joining one steward's walk to "
                             "another's, which are not features on the ground")
    parser.add_argument("--gpkg", type=Path,
                        default=dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--tolerance", type=float, default=25.0)
    parser.add_argument("--min-enclosure", type=float, default=0.50)
    parser.add_argument("--max-spur", type=float, default=0.10)
    args = parser.parse_args(argv)

    tracks = gpd.read_file(args.gpkg,
                           layer="tracks_smoothed").to_crs(dataio.METRIC_CRS)
    tracks = dataio.publishable(tracks)
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
        unit = f"{unit} — {group.steward.iloc[0]}"
    derived = polygon_tools.adopted_frame(match._unit.iloc[0])
    derived_lines = (list(derived.geometry) if derived is not None
                     and not derived.empty else [])
    built = polygon_tools.survey_polygon(parts_of(group) + derived_lines,
                                         args.tolerance,
                                         args.min_enclosure, args.max_spur)
    bridges = (built.get("bridges") or []) if built else []
    if not bridges:
        print(f"{unit}: no gaps — the boundary closes.")
        return 0

    try:
        streams = unary_union(list(
            gpd.read_file(dataio.REPO_ROOT / "data" / "reference" / "hydro"
                          / "streams.gpkg").to_crs(dataio.METRIC_CRS).geometry))
    except Exception:
        streams = None

    out = args.out or (dataio.OUT_DIR / "queries"
                       / f"{dataio.safe_name(unit)}_gaps.png")
    path, rows = render(group.clan.iloc[0],
                        (group.zone.iloc[0] if not args.steward
                         else f"{group.zone.iloc[0]}, {group.steward.iloc[0]}"),
                        group, bridges, streams, out, derived)

    print(f"{unit}: {len(rows)} gaps, "
          f"{sum(r[1] for r in rows):.2f} km nobody walked\n")
    print(f"  {'gap':>3}  {'km':>6}  on modelled water")
    for number, km, share in rows:
        print(f"  {number:>3}  {km:6.2f}  {share:15.0f}%")
    print(f"\nWrote {path}")
    print("\nAsk the field what each numbered gap is: not yet walked, "
          "impassable, or an agreed straight line.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
