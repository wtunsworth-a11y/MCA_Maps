#!/usr/bin/env python3
"""Report the sacred sites mapped within clan land.

Sacred sites are recorded differently from land boundaries. The site name sits
in the track's own name rather than the file name, one walk can cover more than
one site, and one site can be walked more than once. So sites are grouped by the
name written on the track, not by file and not by track.

None of these walks close into a ring — every one has open ends across 40–60%
of its length — so **every area here is an estimate**. Two are given:

* **Bridged** — open ends joined with straight lines, the same method used for
  clan boundaries, so the figure is comparable with them.
* **Hull** — the convex hull of the walk, an upper bound on the ground covered.

The true area lies between them. Neither is a surveyed boundary.

Usage:
    python scripts/sacred_sites.py
    python scripts/sacred_sites.py --report output/sacred_sites.md
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402
import polygons as polygon_tools  # noqa: E402
import smooth_tracks  # noqa: E402

# Leading "2025-04-24 12:58" style stamps, and the trailing descriptive text.
TIMESTAMP = re.compile(r"^\s*\d{4}-\d{2}-\d{2}[\sT]*\d{0,2}:?\d{0,2}\s*")
SACRED_TAIL = re.compile(r"\bsacred\b.*", re.IGNORECASE | re.DOTALL)


def site_names(track_name: str) -> list[str]:
    """The sacred site names a track claims to cover.

    A track named "<date> <site> and <site> sacred sites" covers two sites in
    one walk; those cannot be told apart afterwards and are reported jointly.
    Names are parsed only to group the walks — they are not published.
    """
    text = TIMESTAMP.sub("", str(track_name or ""))
    text = SACRED_TAIL.sub("", text)
    text = text.replace("\n", " ").strip(" .,-")
    if not text:
        return []
    parts = re.split(r"\s+and\s+|\s*[/,&]\s*", text, flags=re.IGNORECASE)
    return [p.strip(" .,-").title() for p in parts if p.strip(" .,-")]


def build(tracks: gpd.GeoDataFrame, tolerance: float,
          min_enclosure: float, max_spur: float) -> pd.DataFrame:
    """One row per mapped sacred-site unit, with both area estimates."""
    groups: dict[tuple, list] = {}
    for _, row in tracks.iterrows():
        names = tuple(site_names(row.get("name", ""))) or ("(unnamed)",)
        groups.setdefault(names, []).append(row)

    rows = []
    for names, members in sorted(groups.items()):
        parts = []
        for row in members:
            geometry = row.geometry
            parts.extend(geometry.geoms if hasattr(geometry, "geoms")
                         else [geometry])
        walked = sum(p.length for p in parts)
        built = polygon_tools.survey_polygon(parts, tolerance, min_enclosure,
                                             max_spur)
        hull = unary_union(parts).convex_hull

        rows.append({
            "sites": " + ".join(names),
            "n_sites": len(names),
            "walks": len(members),
            "clan": members[0].get("clan", ""),
            "steward": members[0].get("steward", ""),
            "zone": members[0].get("zone", ""),
            "walked_km": round(walked / 1000, 2),
            "bridged_ha": round(built["area_ha"], 1) if built else None,
            "hull_ha": round(hull.area / 1e4, 1),
            "gap_pct": round(built["gap_pct"], 0) if built else None,
            "geometry": hull,
        })
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=tracks.crs)


def _markdown(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_None._"
    columns = [c for c in frame.columns if c != "geometry"]
    lines = ["| " + " | ".join(columns) + " |",
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
    parser.add_argument("--polygons", type=Path,
                        default=dataio.SMOOTHED_DIR / "mca_polygons.gpkg")
    parser.add_argument("--feature-type", default="Sacred Site")
    parser.add_argument("--tolerance", type=float, default=25.0)
    parser.add_argument("--min-enclosure", type=float, default=0.50)
    parser.add_argument("--max-spur", type=float, default=0.10)
    parser.add_argument("--out", type=Path, default=None,
                        help="write the site hulls to a GeoPackage. Off by "
                             "default and normally left off: the community's "
                             "decision is that sacred sites are reported by "
                             "area only and their locations are not shared.")
    parser.add_argument("--name-sites", action="store_true",
                        help="include individual site names in the report; "
                             "off by default for the same reason")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.gpkg.exists():
        print(f"No smoothed data at {args.gpkg}. Run smooth_tracks.py first.")
        return 1

    tracks = gpd.read_file(args.gpkg, layer=args.layer).to_crs(dataio.METRIC_CRS)
    sites = tracks[tracks.get("feature_type") == args.feature_type]
    if sites.empty:
        print(f"No '{args.feature_type}' features recorded yet.")
        return 0

    table = build(sites, args.tolerance, args.min_enclosure, args.max_spur)

    named = sorted({n for row in table["sites"] for n in row.split(" + ")}
                   - {"(Unnamed)"})
    total_bridged = table["bridged_ha"].fillna(0).sum()
    total_hull = table["hull_ha"].sum()
    footprint = unary_union(table.geometry).area / 1e4

    print(f"\n{len(named)} sacred site(s) across {len(table)} mapped "
          f"unit(s), {int(table.walks.sum())} walk(s)")
    if args.name_sites:
        print(f"  named: {', '.join(named)}")
    columns = [c for c in table.columns
               if c not in ("geometry",) + (() if args.name_sites else ("sites",))]
    print()
    print(table[columns].to_string(index=False))

    print(f"\n  total, bridged estimate : {total_bridged:9,.1f} ha")
    print(f"  total, hull upper bound : {total_hull:9,.1f} ha")
    print(f"  average per mapped unit : {total_bridged / len(table):9,.1f} ha "
          f"bridged / {total_hull / len(table):,.1f} ha hull")
    print(f"  footprint (hulls, overlaps counted once): {footprint:,.1f} ha")

    # Share of the host clan's land.
    share_rows = []
    if args.polygons.exists():
        try:
            clans = gpd.read_file(args.polygons,
                                  layer="clan_polygons").to_crs(dataio.METRIC_CRS)
        except Exception:
            clans = None
        if clans is not None:
            for clan_name, group in table.groupby("clan"):
                match = clans[clans.clan == clan_name]
                if match.empty:
                    continue
                land = match.geometry.iloc[0]
                hulls = unary_union(group.geometry)
                land_ha = land.area / 1e4
                share_rows.append({
                    "clan": clan_name,
                    "clan_land_ha": round(land_ha, 1),
                    "sites_bridged_ha": round(group.bridged_ha.fillna(0).sum(), 1),
                    "sites_hull_ha": round(hulls.area / 1e4, 1),
                    "pct_of_clan_land_bridged":
                        round(group.bridged_ha.fillna(0).sum() / land_ha * 100, 1),
                    "pct_of_clan_land_hull":
                        round(hulls.area / 1e4 / land_ha * 100, 1),
                    "hull_inside_clan_ha":
                        round(hulls.intersection(land).area / 1e4, 1),
                })
    shares = pd.DataFrame(share_rows)
    if not shares.empty:
        print("\nAs a share of the host clan's land:\n")
        print(shares.to_string(index=False))

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        table.to_crs(dataio.WGS84).to_file(args.out, layer="sacred_site_hulls",
                                           driver="GPKG")
        print(f"\nWrote {args.out}")
        print("  NOTE: this file holds sacred site locations. It is "
              "git-ignored and must not be shared.")

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            "# Sacred sites\n\n"
            "**Locations are not shared.** At the community's decision, sacred "
            "sites are reported by area and share of clan land only. This "
            "report carries no coordinates, no map and no site geometry, and "
            "they are withheld from every project file and exported layer.\n\n"
            f"{len(named)} site(s) across {len(table)} mapped unit(s) and "
            f"{int(table.walks.sum())} walk(s).\n\n"
            "Every area is an estimate: none of these walks closes into a ring. "
            "**Bridged** joins the open ends with straight lines (comparable "
            "with the clan boundary figures); **hull** is the convex hull of the "
            "walk, an upper bound. The true area lies between them.\n\n"
            "## Mapped units\n\n"
            + _markdown(table[[c for c in table.columns
                               if c not in ("geometry", "sites", "steward")]])
            + "\n\n"
            f"- **Total, bridged:** {total_bridged:,.1f} ha\n"
            f"- **Total, hull:** {total_hull:,.1f} ha\n"
            f"- **Average per unit:** {total_bridged / len(table):,.1f} ha "
            f"bridged / {total_hull / len(table):,.1f} ha hull\n"
            f"- **Footprint (overlaps once):** {footprint:,.1f} ha\n\n"
            "## Share of clan land\n\n" + _markdown(shares) + "\n",
            encoding="utf-8")
        print(f"Wrote {args.report}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
