#!/usr/bin/env python3
"""Test each clan's surveys separately and combined.

A clan is often walked by several custodians, and the pipeline treats each
survey on its own. That is right when the surveys are independent accounts of
the same boundary, and wrong when they are complementary arcs of one — three
people each walking the stretch nearest them.

Nituri showed why it matters: three surveys with gaps of 89%, 118% and 229%
yield no area at all, but combined they close to 46% and give 5,124 ha. So
every multi-survey clan is now tested both ways and the two results reported
side by side.

Combining is **not** applied automatically. Whether several surveys describe one
boundary is a question about the clan, not about the geometry, and only the
field team can answer it. What this produces is the evidence for asking: how
much the gap improves, whether the walkers duplicate each other or complement
each other, and what area appears if they are combined.

The duplication test matters. If custodians largely re-walk the same line, the
surveys are independent accounts and combining them is meaningless. If they
barely overlap, they are complementary and combining is likely right.

Usage:
    python scripts/clan_combine.py
    python scripts/clan_combine.py --report output/clan_combine_report.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
import closure  # noqa: E402
import dataio  # noqa: E402
import polygons as polygon_tools  # noqa: E402
import smooth_tracks  # noqa: E402


def parts_of(frame: gpd.GeoDataFrame) -> list:
    out = []
    for geometry in frame.geometry:
        if geometry is None:
            continue
        out.extend(geometry.geoms if hasattr(geometry, "geoms") else [geometry])
    return out


def duplication(frame: gpd.GeoDataFrame, distance_m: float) -> float:
    """Share of walked distance running alongside another custodian's track.

    High means the custodians re-walked the same line — independent accounts of
    one boundary. Low means they walked different stretches, which is what a
    single boundary split between them looks like.
    """
    walks = {name: unary_union(list(group.geometry))
             for name, group in frame.groupby("custodian")}
    if len(walks) < 2:
        return 0.0
    total = shared = 0.0
    for name, geometry in walks.items():
        others = unary_union([g for other, g in walks.items() if other != name])
        total += geometry.length
        shared += geometry.intersection(others.buffer(distance_m)).length
    return shared / total * 100 if total else 0.0


def compare(tracks: gpd.GeoDataFrame, tolerance: float, threshold: float,
            max_spur: float, min_enclosure: float, max_gap: float,
            overlap_m: float) -> tuple[pd.DataFrame, gpd.GeoDataFrame]:
    """Per clan: the separate results, and what combining would give."""
    rows, geometries = [], []

    for clan, group in tracks.groupby("clan"):
        if not str(clan).strip():
            continue
        surveys = group.source_name.nunique()
        if surveys < 2:
            continue

        separate = []
        for _, survey in group.groupby("source_name"):
            outcome = closure.analyse_survey(parts_of(survey), tolerance,
                                             threshold, max_spur,
                                             min_enclosure)
            built = polygon_tools.survey_polygon(parts_of(survey), tolerance,
                                                 min_enclosure, max_spur)
            usable = (built is not None
                      and (built["basis"] == "surveyed"
                           or built["gap_pct"] <= max_gap * 100))
            separate.append({
                "status": outcome["status"],
                "gap_pct": outcome["ratio"] * 100 if outcome["ratio"] else None,
                "area_ha": built["area_ha"] if usable else 0.0,
                "usable": usable,
            })

        combined_parts = parts_of(group)
        combined = closure.analyse_survey(combined_parts, tolerance, threshold,
                                          max_spur, min_enclosure)
        combined_built = polygon_tools.survey_polygon(
            combined_parts, tolerance, min_enclosure, max_spur)
        combined_usable = (combined_built is not None
                           and (combined_built["basis"] == "surveyed"
                                or combined_built["gap_pct"] <= max_gap * 100))

        separate_area = sum(s["area_ha"] for s in separate)
        combined_area = combined_built["area_ha"] if combined_usable else 0.0
        gaps = [s["gap_pct"] for s in separate if s["gap_pct"] is not None]

        rows.append({
            "zone": group.zone.iloc[0],
            "clan": clan,
            "custodians": group.custodian.nunique(),
            "surveys": surveys,
            "walked_km": round(group.geometry.length.sum() / 1000, 2),
            "duplication_pct": round(duplication(group, overlap_m), 1),
            "best_gap_separate": round(min(gaps), 1) if gaps else None,
            "gap_combined": round(combined["ratio"] * 100, 1)
                            if combined["ratio"] is not None else None,
            "usable_separate": sum(1 for s in separate if s["usable"]),
            "area_separate_ha": round(separate_area, 1),
            "area_combined_ha": round(combined_area, 1),
            "area_gained_ha": round(combined_area - separate_area, 1),
        })

        if combined_usable:
            geometries.append({
                "clan": clan, "zone": group.zone.iloc[0],
                "custodians": group.custodian.nunique(),
                "surveys": surveys,
                "basis": combined_built["basis"],
                "walked_km": round(combined_built["walked_km"], 2),
                "area_ha": round(combined_built["area_ha"], 1),
                "gap_pct": round(combined_built["gap_pct"], 1),
                "geometry": combined_built["geometry"],
            })

    table = pd.DataFrame(rows).sort_values("area_gained_ha", ascending=False)
    frame = (gpd.GeoDataFrame(geometries, geometry="geometry",
                              crs=dataio.METRIC_CRS)
             if geometries else gpd.GeoDataFrame(columns=["clan", "geometry"],
                                                 geometry="geometry",
                                                 crs=dataio.METRIC_CRS))
    return table, frame


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
    parser.add_argument("--out", type=Path,
                        default=dataio.SMOOTHED_DIR / "mca_clan_combined.gpkg")
    parser.add_argument("--tolerance", type=float, default=25.0)
    parser.add_argument("--threshold", type=float, default=0.10)
    parser.add_argument("--max-spur", type=float, default=0.10)
    parser.add_argument("--min-enclosure", type=float, default=0.50)
    parser.add_argument("--max-gap", type=float, default=0.50)
    parser.add_argument("--overlap-buffer", type=float, default=20.0,
                        help="metres within which two custodians count as "
                             "having walked the same line")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.gpkg.exists():
        print(f"No smoothed data at {args.gpkg}. Run smooth_tracks.py first.")
        return 1

    tracks = gpd.read_file(args.gpkg, layer=args.layer).to_crs(dataio.METRIC_CRS)
    table, frame = compare(tracks, args.tolerance, args.threshold,
                           args.max_spur, args.min_enclosure, args.max_gap,
                           args.overlap_buffer)

    if table.empty:
        print("No clan has more than one survey — nothing to combine.")
        return 0

    gained = table[table.area_gained_ha > 0]
    print(f"\n{len(table)} clan(s) have more than one survey; combining would "
          f"change the area for {len(gained)}\n")
    print(table.to_string(index=False))

    if not gained.empty:
        print(f"\nTotal area that only appears when surveys are combined: "
              f"{gained.area_gained_ha.sum():,.1f} ha")

    complementary = table[table.duplication_pct < 10]
    print(f"\n{len(complementary)} clan(s) show under 10% duplication between "
          "custodians — the pattern of one boundary split between walkers "
          "rather than independent accounts of it")

    if not frame.empty:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        if args.out.exists():
            args.out.unlink()
        frame.to_crs(dataio.WGS84).to_file(args.out, layer="clan_combined",
                                           driver="GPKG")
        print(f"\nWrote {args.out} ({len(frame)} combined polygon(s))")

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            "# Clans tested separately and combined\n\n"
            "Each clan walked by more than one custodian, assessed both as "
            "separate surveys and as one boundary.\n\n"
            "**Nothing here is applied automatically.** Whether several "
            "surveys describe one boundary is a question about the clan, not "
            "the geometry. This is the evidence for asking.\n\n"
            "`duplication_pct` is the share of walked distance running within "
            f"{args.overlap_buffer:g} m of another custodian's track. High "
            "means they re-walked the same line — independent accounts, so "
            "combining is meaningless. Low means they walked different "
            "stretches, which is what one boundary split between walkers looks "
            "like.\n\n"
            + _markdown(table) + "\n\n"
            + (f"Total area appearing only when combined: "
               f"**{gained.area_gained_ha.sum():,.1f} ha**\n"
               if not gained.empty else ""),
            encoding="utf-8")
        print(f"Wrote {args.report}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
