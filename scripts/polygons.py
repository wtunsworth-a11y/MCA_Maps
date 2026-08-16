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
share of each clan's own polygon that represents.

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
                "area_ha": enclosed.area / 1e4}

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
            "walked_km": total / 1000, "area_ha": bridged.area / 1e4}


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

    A clan can hold more than one parcel, and several walkers joined into one
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
    from shapely.geometry import MultiPolygon
    return MultiPolygon(kept)


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
    """Straight lines joining the open pieces into one ring, and their length."""
    open_chains = [c for c in chains if not c["closed"] and len(c["ends"]) == 2]
    if not open_chains:
        return [], 0.0

    if len(open_chains) == 1:
        a, b = open_chains[0]["ends"]
        return [LineString([a, b])], LineString([a, b]).length

    remaining = list(open_chains)
    current = remaining.pop(0)
    start, cursor = current["ends"][0], current["ends"][1]
    bridges, total = [], 0.0

    while remaining:
        best, best_index, best_exit = None, 0, None
        for index, chain in enumerate(remaining):
            for entry, exit_ in ((0, 1), (1, 0)):
                x, y = chain["ends"][entry]
                d = ((cursor[0] - x) ** 2 + (cursor[1] - y) ** 2) ** 0.5
                if best is None or d < best:
                    best, best_index, best_exit = d, index, exit_
        chain = remaining.pop(best_index)
        entry_point = chain["ends"][1 - best_exit]
        bridges.append(LineString([cursor, entry_point]))
        total += best or 0.0
        cursor = chain["ends"][best_exit]

    bridges.append(LineString([cursor, start]))
    total += ((cursor[0] - start[0]) ** 2 + (cursor[1] - start[1]) ** 2) ** 0.5
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


def overlaps(frame: gpd.GeoDataFrame, label: str) -> pd.DataFrame:
    """Pairwise shared area between every pair of polygons that touch."""
    rows = []
    records = frame.reset_index(drop=True)
    for i in range(len(records)):
        a = records.iloc[i]
        for j in range(i + 1, len(records)):
            b = records.iloc[j]
            if not a.geometry.intersects(b.geometry):
                continue
            shared = a.geometry.intersection(b.geometry).area
            if shared <= 0:
                continue
            rows.append({
                f"{label}_a": a[label],
                f"{label}_b": b[label],
                "shared_ha": round(shared / 1e4, 1),
                "pct_of_a": round(shared / a.geometry.area * 100, 1),
                "pct_of_b": round(shared / b.geometry.area * 100, 1),
            })
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values("shared_ha", ascending=False)
    return out


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
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--map", type=Path, default=None,
                        help="render a PNG of the mapped areas")
    args = parser.parse_args(argv)

    if not args.gpkg.exists():
        print(f"No smoothed data at {args.gpkg}. Run smooth_tracks.py first.")
        return 1

    gdf = gpd.read_file(args.gpkg, layer=args.layer).to_crs(dataio.METRIC_CRS)

    gdf = gdf.assign(_unit=dataio.survey_group(gdf))
    records = []
    for source, group in gdf.groupby("_unit", sort=True):
        parts = []
        for geometry in group.geometry:
            if geometry is None:
                continue
            parts.extend(geometry.geoms if hasattr(geometry, "geoms")
                         else [geometry])
        built = survey_polygon(parts, args.tolerance, args.min_enclosure,
                               args.max_spur)
        if built is None:
            continue
        first = group.iloc[0]
        custodians = sorted({str(c) for c in group.custodian if str(c).strip()})
        records.append({
            "zone": first.get("zone", ""), "clan": first.get("clan", ""),
            "custodian": ", ".join(custodians),
            "walkers": len(custodians),
            "surveys": int(group.source_name.nunique()),
            "source_name": source,
            "basis": built["basis"],
            "walked_km": round(built["walked_km"], 2),
            "area_ha": round(built["area_ha"], 1),
            "gap_m": round(built["gap_m"], 1),
            "gap_pct": None if built["gap_pct"] is None else round(built["gap_pct"], 1),
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

    clan_overlaps = overlaps(clans, "clan")
    survey_overlaps = overlaps(polygons.assign(
        label=polygons.clan.astype(str) + " / " + polygons.custodian.astype(str)),
        "label")

    print(f"\nClan-to-clan overlaps: {len(clan_overlaps)} pair(s)\n")
    if not clan_overlaps.empty:
        print(clan_overlaps.head(20).to_string(index=False))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        args.out.unlink()
    polygons.to_crs(dataio.WGS84).to_file(args.out, layer="survey_polygons",
                                          driver="GPKG")
    if not clans.empty:
        clans.to_crs(dataio.WGS84).to_file(args.out, layer="clan_polygons",
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
            + "\n\n## Clan-to-clan overlaps\n\n" + _markdown(clan_overlaps)
            + "\n\n## Survey-to-survey overlaps\n\n"
            + _markdown(survey_overlaps.head(60))
            + "\n\n## Every polygon\n\n"
            + _markdown(polygons.drop(columns="geometry")) + "\n",
            encoding="utf-8")
        print(f"Wrote {args.report}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
