#!/usr/bin/env python3
"""One map per clan walked by more than one custodian.

Walkers of a clan are joined into a single survey, which is right when they
each walked a different stretch of one boundary. Where instead they each walked
the whole ring, joining them can produce a *smaller* area than either walk gave
on its own — the two rings cross, and the largest polygon the combined network
encloses is the overlap rather than the whole.

These maps make that visible. Each shows every walker's line in its own colour,
the area each walk gives on its own, and the area the joined survey gives. Where
the joined outline sits inside the separate ones, joining has cost ground.

Output: output/clans/<clan>.png, plus a table of what joining gained or cost.

Usage:
    python scripts/clan_maps.py
    python scripts/clan_maps.py --all
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
from matplotlib.patches import Patch  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402
import polygons as polygon_tools  # noqa: E402
import terrain  # noqa: E402

WALKER_COLOURS = ["#dc2626", "#2563eb", "#059669", "#d97706", "#7c3aed",
                  "#0891b2"]


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


def render(clan: str, group: gpd.GeoDataFrame, result: dict,
           out_path: Path) -> Path:
    figure, axis = plt.subplots(figsize=(9, 7.5), dpi=140)
    terrain.add_hillshade(axis, dataio.METRIC_CRS, alpha=0.4)

    handles = []
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
            ax=axis, facecolor="none", edgecolor="#111827", linewidth=2.2,
            zorder=5)
        handles.append(Patch(facecolor="none", edgecolor="#111827",
                             label=f"Joined survey — "
                                   f"{result['joined_ha']:,.0f} ha"))

    # The hillshade covers the whole survey area, so the axes must be pinned to
    # this clan or matplotlib autoscales out to the full raster.
    frames = [group.total_bounds]
    for info in result["separate"].values():
        if info["geometry"] is not None:
            frames.append(info["geometry"].bounds)
    if result["joined"] is not None:
        frames.append(result["joined"]["geometry"].bounds)
    minx = min(b[0] for b in frames); miny = min(b[1] for b in frames)
    maxx = max(b[2] for b in frames); maxy = max(b[3] for b in frames)
    pad = max(maxx - minx, maxy - miny, 400) * 0.15
    axis.set_xlim(minx - pad, maxx + pad)
    axis.set_ylim(miny - pad, maxy + pad)

    change = result["joined_ha"] - result["separate_ha"]
    if result["separate_ha"] > 0:
        verdict = (f"joining costs {abs(change):,.0f} ha"
                   if change < -1 else
                   f"joining adds {change:,.0f} ha" if change > 1
                   else "joining changes little")
    else:
        verdict = f"joining yields {result['joined_ha']:,.0f} ha where no walk closed alone"

    axis.set_axis_off()
    axis.set_title(f"{clan} — {len(result['separate'])} walkers\n"
                   f"separately {result['separate_ha']:,.0f} ha, "
                   f"joined {result['joined_ha']:,.0f} ha — {verdict}",
                   fontsize=11, pad=10)
    axis.legend(handles=handles, loc="lower left", fontsize=8, frameon=True)
    figure.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(out_path, bbox_inches="tight")
    plt.close(figure)
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gpkg", type=Path,
                        default=dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg")
    parser.add_argument("--out-dir", type=Path,
                        default=dataio.OUT_DIR / "clans")
    parser.add_argument("--tolerance", type=float, default=25.0)
    parser.add_argument("--min-enclosure", type=float, default=0.50)
    parser.add_argument("--max-spur", type=float, default=0.10)
    parser.add_argument("--max-gap", type=float, default=0.50)
    parser.add_argument("--all", action="store_true",
                        help="also map clans walked by a single custodian")
    args = parser.parse_args(argv)

    if not args.gpkg.exists():
        print(f"No smoothed data at {args.gpkg}. Run smooth_tracks.py first.")
        return 1

    tracks = gpd.read_file(args.gpkg,
                           layer="tracks_smoothed").to_crs(dataio.METRIC_CRS)
    tracks = tracks[tracks.clan.astype(str).str.strip() != ""]
    tracks["unit"] = dataio.survey_group(tracks)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for old in args.out_dir.glob("*.png"):
        old.unlink()

    rows = []
    for unit, group in tracks.groupby("unit", sort=True):
        walkers = group.custodian.nunique()
        if walkers < 2 and not args.all:
            continue
        clan = group.clan.iloc[0]
        result = assess(group, args.tolerance, args.min_enclosure,
                        args.max_spur, args.max_gap)
        path = args.out_dir / f"{dataio.safe_name(unit)}.png"
        render(clan, group, result, path)
        rows.append({
            "clan": clan, "zone": group.zone.iloc[0], "walkers": walkers,
            "walked_km": round(group.geometry.length.sum() / 1000, 2),
            "separate_ha": round(result["separate_ha"], 1),
            "joined_ha": round(result["joined_ha"], 1),
            "change_ha": round(result["joined_ha"] - result["separate_ha"], 1),
            "map": path.name,
        })
        print(f"  {clan}: separate {result['separate_ha']:,.0f} ha → "
              f"joined {result['joined_ha']:,.0f} ha")

    table = pd.DataFrame(rows).sort_values("change_ha")
    table.to_csv(args.out_dir / "joining_effect.csv", index=False)
    harmed = table[table.change_ha < -1]
    print(f"\n{len(table)} clan(s) with more than one walker")
    print(f"  joining costs area for {len(harmed)}, "
          f"totalling {abs(harmed.change_ha.sum()):,.0f} ha")
    print(f"  joining gains area for {(table.change_ha > 1).sum()}")
    print(f"\nWrote {len(table)} map(s) to {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
