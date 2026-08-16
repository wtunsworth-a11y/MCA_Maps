#!/usr/bin/env python3
"""One map per clan, for the page that goes back to that clan.

Every clan gets a map, because every clan gets a page in the report and a
page without a picture is not much use in a discussion under a tree.

Each map shows:

* every custodian's walk in its own colour, and the area that walk gives on
  its own (dashed);
* the survey those walks combine into, outlined in a **dotted** line — dotted
  so it never covers the walkers' own lines, which is the data;
* every stretch of that outline **nobody walked**, in pink. These are where
  the receiver was switched off at the end of one walk and on again somewhere
  else; the straight line across is this pipeline's guess, not a boundary,
  and it is marked as such on every map it appears on;
* the **names** of the neighbouring clans, placed where each neighbour lies.

Neighbouring boundaries are named but never drawn. This page goes back to the
clan it is about, and putting another clan's line on it — with the ground
between shaded as claimed by both — makes a picture of a dispute out of a
survey that is in most cases simply unfinished. What two surveys share is
reported in a table, where it can be read with the figure for how much of
each boundary has yet to be walked.

Walkers of a clan are joined into a single survey, which is right when they
each walked a different stretch of one boundary. Where instead they each
walked the whole ring, joining can produce a *smaller* area than either walk
gave alone — the two rings cross, and the largest polygon the combined network
encloses is the overlap rather than the whole. Where the joined outline sits
inside the separate ones, that is what has happened, and the map says so.

Output: output/clans/<clan>.png, plus a table of what joining gained or cost.

Usage:
    python scripts/clan_maps.py
    python scripts/clan_maps.py --multi-walker-only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from shapely.geometry import Point, box  # noqa: E402
from shapely.ops import nearest_points, unary_union  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402
import polygons as polygon_tools  # noqa: E402
import terrain  # noqa: E402

# No red among the walkers: red is the contested ground and pink is the line
# nobody walked, and a walker's line must not be confused with either.
WALKER_COLOURS = ["#2563eb", "#059669", "#d97706", "#7c3aed", "#0891b2",
                  "#4d7c0f"]
BRIDGE_COLOUR = "#db2777"
# Dotted, not solid: a solid outline at the same weight as a walker's line
# hides the walker's line underneath it, which is exactly the data the map
# exists to show.
JOINED_STYLE = dict(linestyle=(0, (1.5, 3.5)), linewidth=1.7,
                    edgecolor="#111827")
# Drawn *under* the walkers' lines: where the joined survey follows a walk,
# the walker's colour should win, and the dotted black should only be visible
# where the survey bridges ground nobody walked. That is the honest reading.
JOINED_ZORDER = 3.5


def parts_of(frame: gpd.GeoDataFrame) -> list:
    out = []
    for geometry in frame.geometry:
        if geometry is None:
            continue
        out.extend(geometry.geoms if hasattr(geometry, "geoms") else [geometry])
    return out


def assess(group: gpd.GeoDataFrame, tolerance: float, min_enclosure: float,
           max_spur: float, max_gap: float) -> dict:
    """What each walk gives alone, and what the joined survey gives."""
    separate = {}
    for source, walk in group.groupby("source_name"):
        built = polygon_tools.survey_polygon(parts_of(walk), tolerance,
                                             min_enclosure, max_spur)
        usable = built and (built["basis"] == "surveyed"
                            or built["gap_pct"] <= max_gap * 100)
        separate[walk.custodian.iloc[0]] = {
            "geometry": built["geometry"] if usable else None,
            "area_ha": built["area_ha"] if usable else 0.0,
            "basis": built["basis"] if built else None,
            "gap_pct": built["gap_pct"] if built else None,
            "walked_km": walk.geometry.length.sum() / 1000,
        }

    joined = polygon_tools.survey_polygon(parts_of(group), tolerance,
                                          min_enclosure, max_spur)
    joined_ok = joined and (joined["basis"] == "surveyed"
                            or joined["gap_pct"] <= max_gap * 100)
    return {
        "separate": separate,
        "separate_ha": sum(v["area_ha"] for v in separate.values()),
        "joined": joined if joined_ok else None,
        "joined_ha": joined["area_ha"] if joined_ok else 0.0,
    }


def neighbours(clan: str, own, clan_polygons: gpd.GeoDataFrame | None,
               overlap_tolerance: float) -> list[dict]:
    """The clans whose mapped land runs into this one's, and by how much."""
    if clan_polygons is None or own is None or clan_polygons.empty:
        return []
    out = []
    for _, row in clan_polygons.iterrows():
        if row.clan == clan or not row.geometry.intersects(own):
            continue
        piece = row.geometry.intersection(own)
        if piece.is_empty or piece.area <= 0:
            continue
        wide = polygon_tools.beyond_tolerance(piece, overlap_tolerance)
        out.append({"clan": row.clan, "geometry": row.geometry,
                    "shared": piece, "shared_ha": piece.area / 1e4,
                    "beyond_tol_ha": wide.area / 1e4})
    return sorted(out, key=lambda n: -n["shared_ha"])


def clan_lines(tracks: gpd.GeoDataFrame) -> dict:
    """Each clan's tracks unioned into one geometry, and buffered once.

    Built once for the whole run. Doing it inside the per-clan loop meant
    unioning every other clan's tracks 46 times over, which was most of the
    time a full render took.
    """
    lines = {}
    for clan, frame in tracks.groupby("clan"):
        lines[clan] = unary_union(list(frame.geometry))
    return lines


def adjacent_lines(clan: str, group: gpd.GeoDataFrame, lines: dict,
                   buffers: dict, tolerance: float) -> dict:
    """Other clans whose recorded lines run alongside this clan's.

    A clan whose walk does not close has no polygon and so no neighbours in
    the overlap sense, yet its line may run beside another clan's for its
    whole length. Deari and Nui are the case in point. Without this the map
    for such a clan shows the clan alone, which is the least useful thing it
    could show.
    """
    own = lines.get(clan) or unary_union(list(group.geometry))
    reach = _buffered(clan, own, buffers, tolerance)
    # Only the stretch near this clan is drawn. A neighbour's line in full can
    # be twenty times longer and sit ten kilometres away, which pushes the map
    # out until this clan is a smudge in the corner.
    #
    # A bounding box, not a buffer: buffering a 45-track boundary by a
    # kilometre took ninety seconds per clan, and the result is only ever used
    # to keep the map local, which a box does exactly as well.
    minx, miny, maxx, maxy = own.bounds
    view = box(minx - 1000, miny - 1000, maxx + 1000, maxy + 1000)

    out = {}
    for other, line in lines.items():
        if other == clan or not line.intersects(reach):
            continue
        shared = line.intersection(reach).length
        if shared < max(500.0, 0.05 * own.length):
            continue  # a passing touch, not a shared edge
        out[other] = {
            "geometry": line.intersection(view),
            "shared_km": shared / 1000,
            "pct_of_own": own.intersection(
                _buffered(other, line, buffers, tolerance)).length
            / own.length * 100,
        }
    return out


def _buffered(clan: str, line, cache: dict, tolerance: float):
    """One clan's line, widened by the tolerance — computed once per run."""
    if clan not in cache:
        cache[clan] = line.buffer(tolerance)
    return cache[clan]


def _neighbour_labels(near: list[dict], alongside: dict | None, own,
                      window) -> list[tuple]:
    """Where to write each neighbouring clan's name on this clan's map.

    At the point on the neighbour nearest this clan's own work, so the name
    sits on the side the neighbour is actually on. Names falling outside the
    map are pulled to the edge nearest them rather than dropped, since a
    neighbour off the top of the page is still a neighbour.
    """
    minx, miny, maxx, maxy = window
    inset_x = (maxx - minx) * 0.06
    inset_y = (maxy - miny) * 0.06

    sources = {n["clan"]: n["geometry"] for n in near}
    for name, info in (alongside or {}).items():
        sources.setdefault(name, info["geometry"])

    placed = []
    for name, geometry in sorted(sources.items()):
        try:
            point = nearest_points(geometry, own)[0]
        except Exception:
            continue
        x = min(max(point.x, minx + inset_x), maxx - inset_x)
        y = min(max(point.y, miny + inset_y), maxy - inset_y)
        placed.append([name, x, y])

    # Neighbours often meet a clan at the same corner, which stacks three
    # names on top of each other and makes all of them unreadable. Nudge each
    # one clear of the last.
    gap = (maxy - miny) * 0.045
    placed.sort(key=lambda item: item[2])
    for index in range(1, len(placed)):
        previous, current = placed[index - 1], placed[index]
        if (abs(current[1] - previous[1]) < (maxx - minx) * 0.18
                and current[2] - previous[2] < gap):
            current[2] = previous[2] + gap
    return [(name, Point(x, min(y, maxy - inset_y))) for name, x, y in placed]


def _window(group: gpd.GeoDataFrame, result: dict, near: list[dict],
            alongside: dict | None) -> tuple[float, float, float, float]:
    """The map's extent: this clan's own work, plus a margin.

    Neighbours no longer widen the window. Their names are placed on the map
    but their boundaries are not drawn, so the map stays about the clan whose
    page it is.
    """
    frames = [tuple(group.total_bounds)]
    for info in result["separate"].values():
        if info["geometry"] is not None:
            frames.append(info["geometry"].bounds)
    if result["joined"] is not None:
        frames.append(result["joined"]["geometry"].bounds)
    minx = min(b[0] for b in frames); miny = min(b[1] for b in frames)
    maxx = max(b[2] for b in frames); maxy = max(b[3] for b in frames)
    pad = max(maxx - minx, maxy - miny, 400) * 0.18
    return minx - pad, miny - pad, maxx + pad, maxy + pad


def render(clan: str, group: gpd.GeoDataFrame, result: dict,
           out_path: Path, near: list[dict], overlap_tolerance: float,
           alongside: dict | None = None) -> Path:
    # 110 dpi is about 1.6× the size these are placed at in the Word document,
    # which is enough to stay sharp in print. Higher looks no better on the
    # page and pushes a 47-map document past what anyone can email.
    figure, axis = plt.subplots(figsize=(9, 7.5), dpi=110)

    # The window this map covers, worked out before anything is drawn so the
    # hillshade can be cropped to it. The axes must be pinned to it too, or
    # matplotlib autoscales out to the full raster.
    minx, miny, maxx, maxy = _window(group, result, near, alongside)
    terrain.add_hillshade(axis, dataio.METRIC_CRS, alpha=0.4,
                          bounds=(minx, miny, maxx, maxy))
    axis.set_xlim(minx, maxx)
    axis.set_ylim(miny, maxy)

    handles = []

    # Neighbouring clans are named, not drawn. Rendering another clan's
    # boundary on this clan's page puts a line on paper that clan never
    # agreed to, next to ground shaded as claimed by both — which is a
    # picture of a dispute, and this survey is not that. The name says who
    # the neighbour is and where; anything more is for their own page.
    own = unary_union(list(group.geometry))
    for name, point in _neighbour_labels(near, alongside, own,
                                         (minx, miny, maxx, maxy)):
        axis.annotate(name, (point.x, point.y), fontsize=8,
                      color="#475569", ha="center", va="center", zorder=8,
                      bbox=dict(boxstyle="round,pad=0.18", facecolor="white",
                                edgecolor="none", alpha=0.65))

    # Each walk's own area, outlined so overlapping ones stay readable.
    for index, (custodian, info) in enumerate(sorted(result["separate"].items())):
        colour = WALKER_COLOURS[index % len(WALKER_COLOURS)]
        if info["geometry"] is not None:
            gpd.GeoSeries([info["geometry"]], crs=dataio.METRIC_CRS).plot(
                ax=axis, facecolor=colour, edgecolor=colour, alpha=0.16,
                linewidth=1.6, linestyle="--", zorder=2)
        walk = group[group.custodian == custodian]
        walk.plot(ax=axis, color=colour, linewidth=1.6, zorder=4)
        handles.append(Line2D(
            [0], [0], color=colour, lw=2,
            label=f"{custodian} — {info['walked_km']:.1f} km, "
                  + (f"{info['area_ha']:,.0f} ha alone"
                     if info["area_ha"] else "no area alone")))

    if result["joined"] is not None:
        gpd.GeoSeries([result["joined"]["geometry"]],
                      crs=dataio.METRIC_CRS).plot(
            ax=axis, facecolor="none", zorder=JOINED_ZORDER, **JOINED_STYLE)
        label = ("Boundary taken" if len(result["separate"]) < 2
                 else "Joined survey")
        handles.append(Line2D([0], [0], color=JOINED_STYLE["edgecolor"],
                              lw=JOINED_STYLE["linewidth"],
                              linestyle=JOINED_STYLE["linestyle"],
                              label=f"{label} — {result['joined_ha']:,.0f} ha"))

        # The straight lines nobody walked, drawn on top of everything and in
        # a colour used for nothing else. A reader must never mistake one for
        # a boundary: it is where the receiver was switched off at the end of
        # one walk and on again somewhere else.
        bridges = result["joined"].get("bridges") or []
        if bridges:
            gpd.GeoSeries(bridges, crs=dataio.METRIC_CRS).plot(
                ax=axis, color=BRIDGE_COLOUR, linewidth=1.8,
                linestyle=(0, (5, 3)), zorder=7)
            handles.append(Line2D(
                [0], [0], color=BRIDGE_COLOUR, lw=1.8, linestyle=(0, (5, 3)),
                label=f"Not walked — straight line across a gap "
                      f"({result['joined']['gap_m'] / 1000:.1f} km)"))

    axis.set_axis_off()
    axis.set_title(
        f"{clan} — {_headline(result, near, overlap_tolerance, alongside)}",
        fontsize=11, pad=10)
    axis.legend(handles=handles, loc="lower left", fontsize=8, frameon=True)
    figure.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(out_path, bbox_inches="tight")
    plt.close(figure)
    compress(out_path)
    return out_path


def compress(path: Path, colours: int = 192) -> Path:
    """Quantise the PNG's palette. Same picture, about a third less file.

    A hillshaded map is a few line colours over a grey relief, so 192 colours
    lose nothing visible. It matters because these maps are embedded one per
    clan in a Word document that has to survive being emailed.
    """
    try:
        from PIL import Image
        with Image.open(path) as image:
            image.convert("RGB").quantize(colors=colours).save(
                path, optimize=True)
    except Exception:
        pass  # a larger file is not worth failing a render over
    return path


def _headline(result: dict, near: list[dict], overlap_tolerance: float,
              alongside: dict | None = None) -> str:
    """The one line above the map: what it shows, and what is still missing.

    Deliberately plain. This page goes back to the clan it is about, and a
    heading that counts up who else claims their ground reads as an accusation
    before anybody has said a word. Where the survey is unfinished the heading
    says *incomplete*, which is what it is; the neighbours' names are on the
    map, and what the two surveys share is in the table.
    """
    walkers = len(result["separate"])
    who = "1 walker" if walkers == 1 else f"{walkers} walkers"

    if not result["joined_ha"]:
        line = (f"{who} — survey incomplete: the walk does not yet close, and "
                "too much is missing to give an area")
    elif walkers < 2:
        line = f"{who}, {result['joined_ha']:,.0f} ha"
    else:
        change = result["joined_ha"] - result["separate_ha"]
        if result["separate_ha"] > 0:
            verdict = (f"joining costs {abs(change):,.0f} ha" if change < -1
                       else f"joining adds {change:,.0f} ha" if change > 1
                       else "joining changes little")
        else:
            verdict = (f"joining yields {result['joined_ha']:,.0f} ha where no "
                       "walk closed alone")
        line = (f"{who}\nseparately "
                f"{result['separate_ha']:,.0f} ha, joined "
                f"{result['joined_ha']:,.0f} ha — {verdict}")

    if result["joined"] and result["joined"].get("gap_m"):
        share = result["joined"]["gap_m"] / (result["joined"]["walked_km"] * 10)
        line += (f"\nincomplete: {result['joined']['gap_m'] / 1000:.1f} km of "
                 f"the outline has not been walked ({share:.0f}%, in pink)")

    names = sorted({n["clan"] for n in near} | set(alongside or {}))
    if names:
        shown = ", ".join(names[:5]) + (" …" if len(names) > 5 else "")
        line += f"\nneighbouring clans: {shown}"
    return line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gpkg", type=Path,
                        default=dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg")
    parser.add_argument("--polygons", type=Path,
                        default=dataio.SMOOTHED_DIR / "mca_polygons.gpkg")
    parser.add_argument("--out-dir", type=Path,
                        default=dataio.OUT_DIR / "clans")
    parser.add_argument("--tolerance", type=float, default=25.0)
    parser.add_argument("--min-enclosure", type=float, default=0.50)
    parser.add_argument("--max-spur", type=float, default=0.10)
    parser.add_argument("--max-gap", type=float, default=0.50)
    parser.add_argument("--overlap-tolerance", type=float,
                        default=polygon_tools.OVERLAP_TOLERANCE_M)
    parser.add_argument("--multi-walker-only", action="store_true",
                        help="map only the clans walked by more than one "
                             "custodian (the joining comparison alone)")
    args = parser.parse_args(argv)

    if not args.gpkg.exists():
        print(f"No smoothed data at {args.gpkg}. Run smooth_tracks.py first.")
        return 1

    tracks = gpd.read_file(args.gpkg,
                           layer="tracks_smoothed").to_crs(dataio.METRIC_CRS)
    tracks = tracks[tracks.clan.astype(str).str.strip() != ""]
    tracks["unit"] = dataio.survey_group(tracks)

    clan_polygons = None
    if args.polygons.exists():
        try:
            clan_polygons = gpd.read_file(
                args.polygons, layer="clan_polygons").to_crs(dataio.METRIC_CRS)
        except Exception:
            clan_polygons = None

    lines, buffers = clan_lines(tracks), {}

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for old in args.out_dir.glob("*.png"):
        old.unlink()

    rows = []
    for unit, group in tracks.groupby("unit", sort=True):
        walkers = group.custodian.nunique()
        if walkers < 2 and args.multi_walker_only:
            continue
        clan = group.clan.iloc[0]
        result = assess(group, args.tolerance, args.min_enclosure,
                        args.max_spur, args.max_gap)
        own = result["joined"]["geometry"] if result["joined"] else None
        near = neighbours(clan, own, clan_polygons, args.overlap_tolerance)
        alongside = adjacent_lines(clan, group, lines, buffers,
                                   args.overlap_tolerance)
        path = args.out_dir / f"{dataio.safe_name(unit)}.png"
        render(clan, group, result, path, near, args.overlap_tolerance,
               alongside)
        rows.append({
            "clan": clan, "zone": group.zone.iloc[0], "walkers": walkers,
            "walked_km": round(group.geometry.length.sum() / 1000, 2),
            "separate_ha": round(result["separate_ha"], 1),
            "joined_ha": round(result["joined_ha"], 1),
            "change_ha": round(result["joined_ha"] - result["separate_ha"], 1),
            "neighbours": len(near),
            "alongside": ", ".join(sorted(alongside)),
            "map": path.name,
        })
        print(f"  {clan}: {walkers} walker(s), "
              f"{result['joined_ha']:,.0f} ha, {len(near)} neighbour(s), "
              f"{len(alongside)} line(s) alongside")

    table = pd.DataFrame(rows).sort_values("change_ha")
    table.to_csv(args.out_dir / "joining_effect.csv", index=False)
    multi = table[table.walkers > 1]
    harmed = multi[multi.change_ha < -1]
    print(f"\n{len(table)} map(s) written to {args.out_dir}")
    print(f"  {len(multi)} clan(s) walked by more than one custodian")
    print(f"  joining costs area for {len(harmed)}, "
          f"totalling {abs(harmed.change_ha.sum()):,.0f} ha")
    print(f"  joining gains area for {(multi.change_ha > 1).sum()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
