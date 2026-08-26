#!/usr/bin/env python3
"""Turn the walked tracks into polygons, and measure where clans overlap.

Two kinds of polygon come out of this:

* **Surveyed** — the tracks already ring the land, so the polygon is exactly
  what was walked. Nothing is inferred.
* **Inferred** — the tracks stop short, so the open ends are bridged with
  straight lines and the resulting ring is taken as an estimate. The bridged
  distance is recorded on every one of these as `gap_pct`, because a polygon
  closed across 5% of its perimeter is worth far more than one closed across
  60%.

Keeping the two apart matters: an inferred polygon is a working estimate of
the area a clan mapped, not a boundary anyone agreed to. The output layer
carries a `basis` column so the distinction survives into QGIS, and the
overlap report can be filtered to surveyed polygons alone.

Overlaps between clans are then reported pairwise — shared area, and what
share of each clan's own polygon that represents — under two readings:

* **Strict** — every square metre two polygons share. This is the exact
  measurement and the one the totals are built from.
* **Beyond tolerance** — the same overlap with any strip narrower than
  `--overlap-tolerance` (100 m by default) removed. Where two walked lines run
  within 100 m of each other, the ground between them is not a competing claim:
  it is GPS error, thick bush, and one steward taking the near side of a ridge
  and another the far side. Only overlap wide enough to survive that is
  reported as contested land.

Usage:
    python scripts/polygons.py
    python scripts/polygons.py --max-gap 0.25 --surveyed-only
    python scripts/polygons.py --report output/polygon_report.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString
from shapely.ops import polygonize, unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
import closure  # noqa: E402
import dataio  # noqa: E402
import terrain  # noqa: E402
import smooth_tracks  # noqa: E402

DEFAULT_MAX_GAP = 0.50
# Two lines recorded within this distance of each other are the same line as
# far as the ground is concerned. Set from the field: GPS fixes land 10 m
# apart, the canopy displaces them further, and a boundary followed on foot
# wanders around terrain. The community's judgement, recorded in
# docs/METHODS.md, is that 100 m is inconsequential here.
OVERLAP_TOLERANCE_M = 100.0


RESOLUTIONS_PATH = (dataio.REPO_ROOT / "data" / "reference"
                    / "gap_resolutions.gpkg")


def adopted_segments(unit: str | None = None):
    """Boundary segments derived rather than walked, by survey unit.

    Two kinds, and the difference matters:

    `river_routed` — the field says the boundary follows a river that cannot
    be walked, so the line is traced along the modelled drainage (§4.13b). The
    shape is as good as a 30 m DEM and no better.

    `agreed_straight` — the field says this stretch is a straight line and the
    clan is content with it. That is not an inference the pipeline made; it is
    an answer the clan gave, and it is boundary.

    Both are added to the network before the enclosed area is worked out, so
    the boundary takes the right shape however the survey is assembled and the
    remaining bridging is computed around lines that are already in place.

    Neither is ever counted as walked distance. Nobody walked them.
    """
    if not RESOLUTIONS_PATH.exists():
        return {} if unit is None else []
    try:
        frame = gpd.read_file(RESOLUTIONS_PATH).to_crs(dataio.METRIC_CRS)
    except Exception:
        return {} if unit is None else []
    if unit is not None:
        return [g for u, g in zip(frame.unit, frame.geometry) if u == unit]
    out: dict = {}
    for key, geometry in zip(frame.unit, frame.geometry):
        out.setdefault(key, []).append(geometry)
    return out


def adopted_frame(unit: str | None = None):
    """The adopted segments with their kind and note, for maps and tables."""
    if not RESOLUTIONS_PATH.exists():
        return None
    try:
        frame = gpd.read_file(RESOLUTIONS_PATH).to_crs(dataio.METRIC_CRS)
    except Exception:
        return None
    return frame if unit is None else frame[frame.unit == unit]


def adopt_segment(unit: str, line, kind: str, note: str,
                  detail: dict | None = None):
    """Keep a derived line as part of that clan's boundary.

    Stored as geometry against the survey unit, not against a gap number.
    Numbering is a property of one assembly of the survey — Manuvoora's gaps
    are numbered differently for one steward's walk and for two joined — so a
    number would stop meaning what it meant as soon as another steward's
    tracks arrived. The line itself does not move.

    One resolution per stretch: re-adopting the same stretch replaces what was
    there, or a re-run would stack two copies of the same river on top of
    itself. Sameness is judged by Hausdorff distance, not by proximity — a
    44 m join that starts at the end of a 2.5 km river route sits zero metres
    from it and is not remotely the same line. Proximity deleted that river
    route once.
    """
    import pandas as pd

    detail = detail or {}
    row = gpd.GeoDataFrame(
        [{"unit": unit, "kind": kind, "note": note,
          "straight_km": detail.get("straight_km"),
          "routed_km": detail.get("routed_km"),
          "snap_start_m": detail.get("snap_start_m"),
          "snap_end_m": detail.get("snap_end_m"),
          "source": detail.get("source", ""),
          "geometry": line}],
        geometry="geometry", crs=dataio.METRIC_CRS)

    if RESOLUTIONS_PATH.exists():
        existing = gpd.read_file(RESOLUTIONS_PATH).to_crs(dataio.METRIC_CRS)
        keep = existing[~(
            (existing.unit == unit)
            & (existing.kind == kind)
            & existing.geometry.apply(
                lambda g: g.hausdorff_distance(line) < 50))]
        row = gpd.GeoDataFrame(pd.concat([keep, row], ignore_index=True),
                               geometry="geometry", crs=dataio.METRIC_CRS)

    RESOLUTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    row.to_crs(dataio.WGS84).to_file(RESOLUTIONS_PATH,
                                     layer="gap_resolutions", driver="GPKG")
    return RESOLUTIONS_PATH


def survey_polygon(parts: list, tolerance: float, min_enclosure: float,
                   max_spur: float) -> dict | None:
    """Build the best polygon available for one survey's tracks."""
    parts = [p for p in parts if p is not None and p.length > 0]
    if not parts:
        return None

    total = sum(p.length for p in parts)
    endpoints = []
    for part in parts:
        endpoints.append(part.coords[0][:2])
        endpoints.append(part.coords[-1][:2])
    labels = closure._cluster_endpoints(endpoints, tolerance)
    positions: dict = {}
    for index, label in enumerate(labels):
        positions.setdefault(label, endpoints[index])

    snapped = _snapped_lines(parts, positions, labels)

    # Already a ring? Judge that on the primary ring alone — a multipolygon's
    # perimeters sum, so a mesh of slivers would clear the threshold on total
    # perimeter while enclosing almost nothing.
    primary = _largest(snapped)
    enclosed = _enclosed(snapped)
    if primary is not None and primary.length >= min_enclosure * total:
        return {"geometry": enclosed, "basis": "surveyed", "gap_m": 0.0,
                "gap_pct": 0.0, "walked_km": total / 1000,
                "area_ha": enclosed.area / 1e4, "bridges": []}

    # Otherwise bridge the open ends and try again.
    edges = [{"a": labels[2 * i], "b": labels[2 * i + 1],
              "length": parts[i].length, "live": True}
             for i in range(len(parts))]
    closure._prune_spurs(edges, max_spur * total)
    live = [e for e in edges if e["live"]] or edges

    chains = closure._chains(live, positions)
    bridges, gap = _bridges(chains)
    if not bridges:
        return None

    bridged = _enclosed(snapped + bridges)
    if bridged is None:
        return None

    return {"geometry": bridged, "basis": "inferred", "gap_m": gap,
            "gap_pct": gap / total * 100 if total else None,
            "walked_km": total / 1000, "area_ha": bridged.area / 1e4,
            "bridges": bridges}


def _snapped_lines(parts, positions, labels) -> list:
    out = []
    for index, part in enumerate(parts):
        coordinates = [tuple(c[:2]) for c in part.coords]
        coordinates[0] = positions[labels[2 * index]]
        coordinates[-1] = positions[labels[2 * index + 1]]
        if len(set(coordinates)) >= 2:
            out.append(LineString(coordinates))
    return out


def _enclosed(lines: list, min_share: float = 0.02):
    """Every substantial area the lines enclose, not just the biggest one.

    A clan can hold more than one parcel, and several stewards joined into one
    survey routinely describe two or three. Taking only the largest polygon
    silently discarded the rest — Wohukol lost an entire northern parcel that
    way, and the loss looked like joining being harmful when it was this
    function throwing ground away.

    Slivers below `min_share` of the largest are dropped: those are the small
    incidental loops where a track crosses itself, not parcels.
    """
    if not lines:
        return None
    try:
        polygons = [p for p in polygonize(unary_union(lines)) if p.area > 0]
    except Exception:
        return None
    if not polygons:
        return None

    largest = max(p.area for p in polygons)
    kept = [p for p in polygons if p.area >= largest * min_share]
    if len(kept) == 1:
        return kept[0]
    # Union rather than collect: where the pieces overlap — which happens when
    # a bridged ring still crosses itself — a MultiPolygon of them would count
    # the shared ground twice and report an area the walk never enclosed.
    return unary_union(kept)


def _largest(lines: list):
    """The single biggest enclosed polygon — used where one ring is meant."""
    if not lines:
        return None
    try:
        polygons = list(polygonize(unary_union(lines)))
    except Exception:
        return None
    return max(polygons, key=lambda p: p.area) if polygons else None


def _bridges(chains: list[dict]):
    """Straight lines joining the open pieces into one ring, and their length.

    These lines are **not boundary**. They are where the receiver was switched
    off at the end of one walk and on again somewhere else, and the straight
    line across is this pipeline's guess at what lies between. They are drawn
    apart from the walked line on every map and counted apart in every table.

    The order the pieces are joined in, and which way round each one is taken,
    comes from `closure.order_chains` — get the direction wrong and the
    bridges cross, giving a bow-tie that encloses two slivers instead of the
    ground actually walked around.
    """
    open_chains = [c for c in chains if not c["closed"] and len(c["ends"]) == 2]
    if not open_chains:
        return [], 0.0

    if len(open_chains) == 1:
        a, b = open_chains[0]["ends"]
        line = LineString([a, b])
        return [line], line.length

    ends = [c["ends"] for c in open_chains]
    order = closure.order_chains(open_chains)

    bridges, total = [], 0.0
    for position, (index, flip) in enumerate(order):
        exit_point = ends[index][1 - flip]
        next_index, next_flip = order[(position + 1) % len(order)]
        entry_point = ends[next_index][next_flip]
        line = LineString([exit_point, entry_point])
        bridges.append(line)
        total += line.length
    return bridges, total


# --------------------------------------------------------------------------
# Overlaps
# --------------------------------------------------------------------------

def clan_polygons(polygons: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """One polygon per clan, dissolving the surveys recorded for it."""
    named = polygons[polygons["clan"].astype(str).str.strip() != ""].copy()
    if named.empty:
        return named
    merged = named.dissolve(by="clan", aggfunc={"area_ha": "sum"},
                            as_index=False)
    merged["area_ha"] = (merged.geometry.area / 1e4).round(1)
    return merged


def beyond_tolerance(shared, tolerance: float = OVERLAP_TOLERANCE_M):
    """The part of a shared area that is wider than `tolerance` throughout.

    A morphological opening: erode by half the tolerance, then dilate back.
    What survives is every point that sits inside a disc of radius
    `tolerance`/2 lying wholly within the shared area — that is, the ground
    that is at least `tolerance` across. A sliver between two lines recorded
    50 m apart disappears; a genuinely shared block comes back essentially
    unchanged.

    This is the geometric form of the field rule: if the two recorded lines
    are less than 100 m apart, there is no overlap to discuss.
    """
    if shared is None or shared.is_empty or tolerance <= 0:
        return shared
    try:
        opened = shared.buffer(-tolerance / 2).buffer(tolerance / 2)
    except Exception:
        return shared
    if opened.is_empty:
        return opened
    # Dilation can push the result past the original edge on a concave corner,
    # so clip it back — the answer must be a subset of what is actually shared.
    return opened.intersection(shared)


def overlaps(frame: gpd.GeoDataFrame, label: str,
             tolerance: float = OVERLAP_TOLERANCE_M) -> pd.DataFrame:
    """Pairwise shared area between every pair of polygons that touch.

    Reported twice: strictly, and with slivers narrower than `tolerance`
    removed. The strict figure is the exact measurement; the tolerant one is
    what the field would recognise as two clans claiming the same ground.
    """
    rows = []
    records = frame.reset_index(drop=True)
    for i in range(len(records)):
        a = records.iloc[i]
        for j in range(i + 1, len(records)):
            b = records.iloc[j]
            if not a.geometry.intersects(b.geometry):
                continue
            piece = a.geometry.intersection(b.geometry)
            shared = piece.area
            if shared <= 0:
                continue
            wide = beyond_tolerance(piece, tolerance).area
            rows.append({
                f"{label}_a": a[label],
                f"{label}_b": b[label],
                "shared_ha": round(shared / 1e4, 1),
                "pct_of_a": round(shared / a.geometry.area * 100, 1),
                "pct_of_b": round(shared / b.geometry.area * 100, 1),
                "beyond_tol_ha": round(wide / 1e4, 1),
                "beyond_tol_pct_of_a": round(wide / a.geometry.area * 100, 1),
                "beyond_tol_pct_of_b": round(wide / b.geometry.area * 100, 1),
                "verdict": "overlap" if wide > 0 else "within tolerance",
            })
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values("shared_ha", ascending=False)
    return out


def shared_lines(tracks: gpd.GeoDataFrame,
                 tolerance: float = OVERLAP_TOLERANCE_M) -> pd.DataFrame:
    """Where two clans' recorded lines run along each other.

    The mirror image of the overlap report. An overlap says two clans claim
    the same ground; a shared line says they walked the same edge, and that is
    agreement rather than dispute. Both matter for the same question, and a
    pair can show one without the other — Deari and Nui share almost their
    whole recorded line and enclose no contested ground at all.

    Reported as the length of each clan's own line that runs within
    `tolerance` of the other's, in each direction, because the two are rarely
    equal: a short boundary can sit entirely along a long one.
    """
    named = tracks[tracks["clan"].astype(str).str.strip() != ""]
    lines = {clan: unary_union(list(group.geometry))
             for clan, group in named.groupby("clan")}

    # Each clan's line is widened once and reused. Buffering inside the pair
    # loop meant widening the same 45-track boundary forty times over, and on
    # this data that alone took longer than the rest of the pipeline.
    widened: dict = {}

    def reach(clan):
        if clan not in widened:
            widened[clan] = lines[clan].buffer(tolerance)
        return widened[clan]

    rows = []
    keys = sorted(lines)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            ga, gb = lines[a], lines[b]
            if ga.distance(gb) > tolerance:
                continue
            near_a = ga.intersection(reach(b)).length
            near_b = gb.intersection(reach(a)).length
            if near_a <= 0 and near_b <= 0:
                continue
            rows.append({
                "clan_a": a, "clan_b": b,
                "shared_km": round(max(near_a, near_b) / 1000, 2),
                "pct_of_a": round(near_a / ga.length * 100, 1),
                "pct_of_b": round(near_b / gb.length * 100, 1),
            })
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values("shared_km", ascending=False)
    return out


def contested_layer(clans: gpd.GeoDataFrame,
                    tolerance: float = OVERLAP_TOLERANCE_M):
    """Every piece of ground two clans both claim, as its own map layer.

    Carries both readings so QGIS can style them apart: `verdict` separates
    the pieces wide enough to be a real competing claim from the slivers that
    are two stewards describing the same line.
    """
    rows = []
    records = clans.reset_index(drop=True)
    for i in range(len(records)):
        a = records.iloc[i]
        for j in range(i + 1, len(records)):
            b = records.iloc[j]
            if not a.geometry.intersects(b.geometry):
                continue
            piece = a.geometry.intersection(b.geometry)
            if piece.is_empty or piece.area <= 0:
                continue
            wide = beyond_tolerance(piece, tolerance)
            rows.append({
                "clan_a": a.clan, "clan_b": b.clan,
                "shared_ha": round(piece.area / 1e4, 1),
                "beyond_tol_ha": round(wide.area / 1e4, 1),
                "verdict": "overlap" if wide.area > 0 else "within tolerance",
                "geometry": piece,
            })
    if not rows:
        return None
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=clans.crs)


def _render(polygons: gpd.GeoDataFrame, boundary, out_path: Path) -> None:
    """Draw the mapped areas, keeping walked and inferred visually distinct."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    figure, axis = plt.subplots(figsize=(11, 10), dpi=150)
    has_terrain = terrain.add_hillshade(axis, dataio.METRIC_CRS, alpha=0.5)

    if boundary is not None:
        gpd.GeoSeries([boundary], crs=dataio.METRIC_CRS).plot(
            ax=axis, facecolor="none" if has_terrain else "#f1f5f9",
            edgecolor="#475569" if has_terrain else "#94a3b8",
            linewidth=1.2, zorder=0)

    inferred = polygons[polygons.basis == "inferred"]
    surveyed = polygons[polygons.basis == "surveyed"]
    if len(inferred):
        inferred.plot(ax=axis, facecolor="#fbbf24", edgecolor="#b45309",
                      linewidth=0.6, alpha=0.45, zorder=1)
    if len(surveyed):
        surveyed.plot(ax=axis, facecolor="#2563eb", edgecolor="#1e3a8a",
                      linewidth=0.9, alpha=0.60, zorder=2)

    axis.set_axis_off()
    axis.set_title(
        f"Areas mapped from clan boundary walks\n"
        f"{len(surveyed)} walked rings, {len(inferred)} inferred "
        f"({polygons.area_ha.sum():,.0f} ha total)",
        fontsize=13, pad=14)
    axis.legend(handles=[
        Patch(facecolor="#2563eb", alpha=0.6, edgecolor="#1e3a8a",
              label="Surveyed — tracks close the ring"),
        Patch(facecolor="#fbbf24", alpha=0.45, edgecolor="#b45309",
              label="Inferred — open ends bridged"),
        Patch(facecolor="none", edgecolor="#475569", label="MCA boundary"),
    ], loc="lower left", fontsize=9, frameon=True)
    figure.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(out_path, bbox_inches="tight")
    plt.close(figure)


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
    parser.add_argument("--out", type=Path,
                        default=dataio.SMOOTHED_DIR / "mca_polygons.gpkg")
    parser.add_argument("--tolerance", type=float,
                        default=closure.DEFAULT_TOLERANCE_M)
    parser.add_argument("--min-enclosure", type=float, default=0.50)
    parser.add_argument("--max-spur", type=float, default=0.10)
    parser.add_argument("--max-gap", type=float, default=DEFAULT_MAX_GAP,
                        help="drop inferred polygons bridged across more than "
                             "this share of the distance walked")
    parser.add_argument("--surveyed-only", action="store_true",
                        help="keep only polygons that were actually walked")
    parser.add_argument("--overlap-tolerance", type=float,
                        default=OVERLAP_TOLERANCE_M,
                        help="two recorded lines this close together are "
                             "treated as the same line, so shared ground "
                             "narrower than this is not counted as overlap")
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--map", type=Path, default=None,
                        help="render a PNG of the mapped areas")
    args = parser.parse_args(argv)

    if not args.gpkg.exists():
        print(f"No smoothed data at {args.gpkg}. Run smooth_tracks.py first.")
        return 1

    gdf = gpd.read_file(args.gpkg, layer=args.layer).to_crs(dataio.METRIC_CRS)

    gdf = gdf.assign(_unit=dataio.survey_group(gdf))
    resolutions = adopted_segments()
    if resolutions:
        print(f"\n  {sum(len(v) for v in resolutions.values())} derived "
              f"segment(s) adopted for {len(resolutions)} clan(s) — river "
              f"lines the field says the boundary follows but nobody can walk")
    records, bridge_rows = [], []
    for source, group in gdf.groupby("_unit", sort=True):
        parts = []
        for geometry in group.geometry:
            if geometry is None:
                continue
            parts.extend(geometry.geoms if hasattr(geometry, "geoms")
                         else [geometry])
        derived = resolutions.get(source, [])
        built = survey_polygon(parts + derived, args.tolerance,
                               args.min_enclosure, args.max_spur)
        if derived:
            built["derived_km"] = round(
                sum(d.length for d in derived) / 1000, 2)
        if built is None:
            continue
        first = group.iloc[0]
        stewards = sorted({str(c) for c in group.steward if str(c).strip()})
        for bridge in built.get("bridges") or []:
            bridge_rows.append({
                "zone": first.get("zone", ""), "clan": first.get("clan", ""),
                "source_name": source,
                "length_m": round(bridge.length, 1),
                "geometry": bridge,
            })
        records.append({
            "zone": first.get("zone", ""), "clan": first.get("clan", ""),
            "steward": ", ".join(stewards),
            "stewards": len(stewards),
            "surveys": int(group.source_name.nunique()),
            "source_name": source,
            "basis": built["basis"],
            "walked_km": round(built["walked_km"], 2),
            "area_ha": round(built["area_ha"], 1),
            "gap_m": round(built["gap_m"], 1),
            "gap_pct": None if built["gap_pct"] is None else round(built["gap_pct"], 1),
            "bridges": len(built.get("bridges") or []),
            "derived_km": built.get("derived_km", 0.0),
            "geometry": built["geometry"],
        })

    if not records:
        print("No polygons could be built.")
        return 1

    polygons = gpd.GeoDataFrame(records, geometry="geometry",
                                crs=dataio.METRIC_CRS)

    dropped = polygons[(polygons.basis == "inferred")
                       & (polygons.gap_pct > args.max_gap * 100)]
    polygons = polygons.drop(dropped.index)
    if args.surveyed_only:
        polygons = polygons[polygons.basis == "surveyed"]

    surveyed = polygons[polygons.basis == "surveyed"]
    inferred = polygons[polygons.basis == "inferred"]

    print(f"\nBuilt {len(polygons)} polygon(s) from {gdf.source_name.nunique()} "
          f"surveys")
    print(f"  surveyed (walked ring)  {len(surveyed):3d}  "
          f"{surveyed.area_ha.sum():11,.1f} ha")
    print(f"  inferred (gap bridged)  {len(inferred):3d}  "
          f"{inferred.area_ha.sum():11,.1f} ha")
    if len(dropped):
        print(f"  dropped, gap too wide   {len(dropped):3d}  "
              f"(over {args.max_gap:.0%} of the walk)")

    footprint = unary_union(polygons.geometry).area / 1e4
    print(f"\n  combined footprint (overlaps counted once): {footprint:,.1f} ha")
    print(f"  sum of polygons                            : "
          f"{polygons.area_ha.sum():,.1f} ha")
    print(f"  → overlap between polygons                 : "
          f"{polygons.area_ha.sum() - footprint:,.1f} ha")

    boundary = dataio.load_boundary()
    if boundary is not None:
        inside = unary_union(polygons.geometry).intersection(boundary).area / 1e4
        print(f"\n  of that footprint, inside the MCA          : "
              f"{inside:,.1f} ha "
              f"({inside / (boundary.area / 1e4) * 100:.1f}% of the MCA's "
              f"{boundary.area / 1e4:,.0f} ha)")

    by_zone = (polygons.groupby("zone")
               .agg(polygons=("area_ha", "size"),
                    area_ha=("area_ha", "sum"))
               .round(1))
    print("\nMapped area by zone:\n")
    print(by_zone.to_string())

    clans = clan_polygons(polygons)
    print(f"\n{len(clans)} clan polygon(s) after dissolving by clan")

    clan_overlaps = overlaps(clans, "clan", args.overlap_tolerance)
    survey_overlaps = overlaps(polygons.assign(
        label=polygons.clan.astype(str) + " / " + polygons.steward.astype(str)),
        "label", args.overlap_tolerance)

    agreed = shared_lines(gdf, args.overlap_tolerance)
    if not agreed.empty:
        print(f"\nClan pairs walking the same line "
              f"(within {args.overlap_tolerance:.0f} m): {len(agreed)}\n")
        print(agreed.head(12).to_string(index=False))

    print(f"\nClan-to-clan overlaps: {len(clan_overlaps)} pair(s)")
    if not clan_overlaps.empty:
        real = clan_overlaps[clan_overlaps.verdict == "overlap"]
        print(f"  strict                          "
              f"{len(clan_overlaps):3d} pair(s), "
              f"{clan_overlaps.shared_ha.sum():9,.0f} ha")
        print(f"  beyond {args.overlap_tolerance:.0f} m tolerance          "
              f"{len(real):3d} pair(s), "
              f"{clan_overlaps.beyond_tol_ha.sum():9,.0f} ha")
        print(f"  within tolerance (not overlap)  "
              f"{len(clan_overlaps) - len(real):3d} pair(s)\n")
        print(clan_overlaps.head(20).to_string(index=False))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        args.out.unlink()
    polygons.to_crs(dataio.WGS84).to_file(args.out, layer="survey_polygons",
                                          driver="GPKG")
    if not clans.empty:
        clans.to_crs(dataio.WGS84).to_file(args.out, layer="clan_polygons",
                                           driver="GPKG")
    # The bridges go out as their own layer, never merged into the boundary.
    # They are where the receiver was off, not where anyone walked, and a map
    # that cannot tell them apart from a walked line is misleading.
    if bridge_rows:
        bridges = gpd.GeoDataFrame(bridge_rows, geometry="geometry",
                                   crs=dataio.METRIC_CRS)
        bridges = bridges[bridges.source_name.isin(polygons.source_name)]
        if not bridges.empty:
            bridges.to_crs(dataio.WGS84).to_file(
                args.out, layer="inferred_bridges", driver="GPKG")
            print(f"\n  {len(bridges)} inferred bridge(s), "
                  f"{bridges.length.sum() / 1000:,.1f} km of straight line "
                  f"nobody walked, written as their own layer")

    contested = contested_layer(clans, args.overlap_tolerance)
    if contested is not None and not contested.empty:
        contested.to_crs(dataio.WGS84).to_file(args.out, layer="clan_overlaps",
                                               driver="GPKG")
    print(f"\nWrote {args.out}")

    if args.map:
        _render(polygons, boundary, args.map)
        print(f"Wrote {args.map}")

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            "# Mapped areas and clan overlaps\n\n"
            f"- **Surveyed polygons:** {len(surveyed)}, "
            f"{surveyed.area_ha.sum():,.1f} ha\n"
            f"- **Inferred polygons:** {len(inferred)}, "
            f"{inferred.area_ha.sum():,.1f} ha\n"
            f"- **Combined footprint:** {footprint:,.1f} ha\n\n"
            "## Mapped area by zone\n\n" + _markdown(by_zone.reset_index())
            + "\n\n## Clan-to-clan overlaps\n\n"
            + f"Reported twice. `shared_ha` is the exact area two clans both "
              f"claim. `beyond_tol_ha` is the same area with every strip "
              f"narrower than {args.overlap_tolerance:.0f} m removed: where "
              f"two recorded lines run closer than that, the ground between "
              f"them is survey imprecision rather than a competing claim, and "
              f"the pair is marked `within tolerance`.\n\n"
            + _markdown(clan_overlaps)
            + "\n\n## Clans walking the same line\n\n"
            + f"Where two clans' recorded lines run within "
              f"{args.overlap_tolerance:.0f} m of each other. This is "
              f"agreement on a shared edge, not a dispute, and it is not "
              f"visible in the overlap table above.\n\n"
            + _markdown(agreed)
            + "\n\n## Survey-to-survey overlaps\n\n"
            + _markdown(survey_overlaps.head(60))
            + "\n\n## Every polygon\n\n"
            + _markdown(polygons.drop(columns="geometry")) + "\n",
            encoding="utf-8")
        print(f"Wrote {args.report}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
