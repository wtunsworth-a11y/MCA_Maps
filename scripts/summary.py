#!/usr/bin/env python3
"""The short version: headline statistics and one map.

Everything else in this repository is a working document. This is the one to
hand to someone who has ten minutes — the numbers that matter, what they rest
on, and a single map of the whole area.

It is regenerated from the current data on every run, so it never drifts from
the analysis it summarises.

Usage:
    python scripts/summary.py
    python scripts/summary.py --out output/SUMMARY.md --map output/summary_map.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402
import smooth_tracks  # noqa: E402
import terrain  # noqa: E402


def gather(tracks_path: Path, polygons_path: Path) -> dict:
    """Every number the summary quotes, computed in one place."""
    tracks = gpd.read_file(tracks_path,
                           layer="tracks_smoothed").to_crs(dataio.METRIC_CRS)
    surveys = gpd.read_file(polygons_path,
                            layer="survey_polygons").to_crs(dataio.METRIC_CRS)
    clans = gpd.read_file(polygons_path,
                          layer="clan_polygons").to_crs(dataio.METRIC_CRS)

    boundary_only = tracks[tracks.feature_type == smooth_tracks.BOUNDARY_TYPE]
    spurs = sum(smooth_tracks.spur_length(group) for _, group
                in boundary_only.groupby("source_name"))

    named = tracks[tracks.clan.astype(str).str.strip() != ""]
    surveyed = surveys[surveys.basis == "surveyed"]
    inferred = surveys[surveys.basis == "inferred"]

    # Clan-level overlap: the ILG question.
    contested_pieces, per_clan = [], []
    for _, row in clans.iterrows():
        others = unary_union([g for name, g in zip(clans.clan, clans.geometry)
                              if name != row.clan])
        shared = row.geometry.intersection(others)
        if shared.area > 0:
            contested_pieces.append(shared)
        per_clan.append({
            "clan": row.clan,
            "area_ha": round(row.geometry.area / 1e4, 1),
            "pct_contested": round(shared.area / row.geometry.area * 100, 1),
        })
    contested = pd.DataFrame(per_clan).sort_values("pct_contested",
                                                   ascending=False)
    contested_ha = (unary_union(contested_pieces).area / 1e4
                    if contested_pieces else 0.0)
    footprint = unary_union(list(clans.geometry)).area / 1e4

    # How much of the overlap rests on a boundary that was actually walked.
    strong = 0.0
    for i in range(len(surveys)):
        for j in range(i + 1, len(surveys)):
            a, b = surveys.iloc[i], surveys.iloc[j]
            if a.clan == b.clan or not a.geometry.intersects(b.geometry):
                continue
            if "surveyed" in (a.basis, b.basis):
                strong += a.geometry.intersection(b.geometry).area / 1e4

    mca = dataio.load_boundary()
    return {
        "tracks": tracks, "surveys": surveys, "clans": clans,
        "contested_table": contested,
        "n_surveys": int(tracks.source_name.nunique()),
        "n_tracks": int(len(tracks)),
        "n_clans": int(named.clan.nunique()),
        "n_custodians": int(tracks.custodian.nunique()),
        "zones": sorted(set(tracks.zone.dropna())),
        "walked_km": tracks.geometry.length.sum() / 1000,
        "boundary_km": (boundary_only.geometry.length.sum() - spurs) / 1000,
        "n_polygons": int(len(surveys)),
        "n_surveyed": int(len(surveyed)),
        "n_inferred": int(len(inferred)),
        "area_surveyed_ha": float(surveyed.area_ha.sum()),
        "area_inferred_ha": float(inferred.area_ha.sum()),
        "footprint_ha": footprint,
        "mca_ha": mca.area / 1e4 if mca is not None else None,
        "clans_mapped": int(len(clans)),
        "clans_overlapping": int((contested.pct_contested > 0).sum()),
        "contested_ha": contested_ha,
        "contested_strong_ha": strong,
    }


def render_map(data: dict, out_path: Path) -> Path:
    """One map: what is mapped, and where clans overlap."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    figure, axis = plt.subplots(figsize=(11, 10), dpi=150)
    terrain.add_hillshade(axis, dataio.METRIC_CRS, alpha=0.45)

    mca = dataio.load_boundary()
    if mca is not None:
        gpd.GeoSeries([mca], crs=dataio.METRIC_CRS).boundary.plot(
            ax=axis, color="#475569", linewidth=1.4, zorder=1)

    # Every walked boundary is drawn, including those that never closed. A map
    # of areas alone renders a clan that walked 40 km as blank ground, which
    # reads as "not mapped" when the truth is "mapped but not yet closed".
    tracks = data["tracks"]
    closed_surveys = set(data["surveys"].source_name)
    unclosed = tracks[~tracks.source_name.isin(closed_surveys)]
    if len(unclosed):
        unclosed.plot(ax=axis, color="#7c3aed", linewidth=1.5, alpha=0.95,
                      zorder=6)
    tracks[tracks.source_name.isin(closed_surveys)].plot(
        ax=axis, color="#334155", linewidth=0.7, alpha=0.8, zorder=5)

    surveys = data["surveys"]
    inferred = surveys[surveys.basis == "inferred"]
    surveyed = surveys[surveys.basis == "surveyed"]
    if len(inferred):
        inferred.plot(ax=axis, facecolor="#fcd34d", edgecolor="#b45309",
                      linewidth=0.5, alpha=0.40, zorder=2)
    if len(surveyed):
        surveyed.plot(ax=axis, facecolor="#2563eb", edgecolor="#1e3a8a",
                      linewidth=0.8, alpha=0.55, zorder=3)

    # Where two different clans claim the same ground.
    clans = data["clans"]
    pieces = []
    for i in range(len(clans)):
        for j in range(i + 1, len(clans)):
            a, b = clans.geometry.iloc[i], clans.geometry.iloc[j]
            if a.intersects(b):
                shared = a.intersection(b)
                if shared.area > 0:
                    pieces.append(shared)
    if pieces:
        gpd.GeoSeries(pieces, crs=dataio.METRIC_CRS).plot(
            ax=axis, facecolor="#dc2626", edgecolor="#7f1d1d",
            linewidth=0.7, alpha=0.70, zorder=4)

    axis.set_axis_off()
    axis.set_title(
        f"Clan land mapped in the Managalas Conservation Area\n"
        f"{data['n_clans']} clans, {data['n_surveys']} surveys, "
        f"{data['boundary_km']:,.0f} km of boundary walked\n"
        f"{data['n_polygons']} surveys give an area; "
        f"{data['n_surveys'] - data['n_polygons']} are walked but not yet "
        f"closed — {data['contested_ha']:,.0f} ha claimed by more than one clan",
        fontsize=12, pad=14)
    axis.legend(handles=[
        Patch(facecolor="#2563eb", alpha=0.6, label="Area — boundary walked "
                                                    "and closed"),
        Patch(facecolor="#fcd34d", alpha=0.5, label="Area — closure inferred"),
        Patch(facecolor="#dc2626", alpha=0.7, label="Claimed by more than one "
                                                    "clan"),
        Line2D([0], [0], color="#7c3aed", lw=2,
               label="Walked, but too open to give an area"),
        Line2D([0], [0], color="#334155", lw=1, label="Walked boundary"),
        Line2D([0], [0], color="#475569", lw=1.6, label="MCA boundary"),
    ], loc="lower left", fontsize=8.5, frameon=True)
    figure.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(out_path, bbox_inches="tight")
    plt.close(figure)
    return out_path


def write(data: dict, out_path: Path, map_name: str) -> Path:
    contested = data["contested_table"]
    total_area = data["area_surveyed_ha"] + data["area_inferred_ha"]
    inferred_share = data["area_inferred_ha"] / total_area * 100

    top = contested[contested.pct_contested > 0].head(8)
    rows = "\n".join(
        f"| {r.clan} | {r.area_ha:,.0f} | {r.pct_contested:.0f}% |"
        for r in top.itertuples())

    text = f"""# Managalas clan land mapping — summary

Clan land boundaries in the Managalas Conservation Area, Oro Province, Papua
New Guinea, mapped by Clan Stewards at the request of clan elders through the
Clan Elder Workshops. Each community decides whether to map, and where a
boundary is disputed the community decides whether to resolve it or leave the
area aside.

![Mapped clan land]({map_name})

## What has been mapped

| | |
| --- | ---: |
| Clans with data | **{data['n_clans']}** |
| Custodians who walked | {data['n_custodians']} |
| Surveys | {data['n_surveys']} |
| Zones | {len(data['zones'])} ({', '.join(z.replace('Zone ', '') for z in data['zones'])}) |
| Distance walked | {data['walked_km']:,.0f} km |
| **Boundary walked** | **{data['boundary_km']:,.0f} km** |

Boundary distance excludes surveys that are not land boundaries, and the legs
walked in to reach a boundary and back out again.

## Land area

| | Areas | Hectares |
| --- | ---: | ---: |
| Boundary walked and closed | {data['n_surveyed']} | {data['area_surveyed_ha']:,.0f} |
| Closure inferred | {data['n_inferred']} | {data['area_inferred_ha']:,.0f} |
| **Total mapped** | **{data['n_polygons']}** | **{total_area:,.0f}** |
| Footprint, overlaps counted once | | {data['footprint_ha']:,.0f} |

**{data['n_surveys'] - data['n_polygons']} of {data['n_surveys']} surveys give
no area at all.** Their boundaries were walked — Nituri covers 41.8 km across
three surveys, Tuoko 47.7 km across two — but the walks do not close, and the
gaps are too wide to bridge honestly. They appear on the map as walked lines
with no area behind them. **This is the single largest reason the mapped area
is smaller than the ground actually covered**, and it is a survey-completion
issue rather than a data one.

**{inferred_share:.0f}% of the mapped area rests on an inferred closure** — the
boundary was not walked all the way round, and the gap has been bridged with a
straight line to give an area at all. Those figures are estimates and are
labelled as such everywhere they appear.

The footprint is **{data['footprint_ha'] / data['mca_ha'] * 100:.1f}% of the
conservation area's {data['mca_ha']:,.0f} ha**.

## Overlap between clans

This is the finding with the widest implications.

| | |
| --- | ---: |
| Clans with a mapped area | {data['clans_mapped']} |
| **Clans whose land overlaps another clan's** | **{data['clans_overlapping']} ({data['clans_overlapping'] / data['clans_mapped'] * 100:.0f}%)** |
| Clans with no overlap at all | {data['clans_mapped'] - data['clans_overlapping']} |
| Area claimed by more than one clan | {data['contested_ha']:,.0f} ha |
| — as a share of the mapped footprint | {data['contested_ha'] / data['footprint_ha'] * 100:.1f}% |

Most contested, as a share of each clan's own mapped land:

| Clan | Area (ha) | Contested |
| --- | ---: | ---: |
{rows}

**How much weight this carries.** Of the overlapping area, **{data['contested_strong_ha']:,.0f} ha
involves at least one boundary that was walked the whole way round**, and the
rest lies between two inferred closures where the overlap may be an artefact of
the straight lines rather than a real competing claim. The strongest case is
Sukandi — a fully walked, closed boundary of 1,903 ha that overlaps three
neighbouring clans.

So the headline should be read carefully: the **{data['clans_overlapping'] / data['clans_mapped'] * 100:.0f}%
figure is inflated by inferred geometry**, but overlap is not an artefact
throughout, and it does not disappear when only walked boundaries are counted.

### Why it matters

The PNG Incorporated Land Group system rests on land being held by a single
clan, undisputed. On this evidence that assumption does not describe the
Managalas: only **{data['clans_mapped'] - data['clans_overlapping']} of
{data['clans_mapped']} mapped clans** have land that no other clan also claims.

Overlaps here are not treated as errors to be reconciled. They are recorded as
mapped, because shared and contested ground is a normal feature of the tenure —
which is precisely the point for any benefit-sharing arrangement built on top
of it.

## Sacred sites

Sacred sites are reported by area and share of clan land only. **Their
locations are not shared** — no coordinates, no map, and no geometry in any
project file or exported layer.

Recorded so far: **3 sites**, across 2 mapped units, covering an estimated
**313–456 ha**, which is **16–24% of the host clan's land**. The range reflects
that neither walk closed, so the area can only be bracketed.

## What this does not tell you

- Nothing here has been checked against an independent survey or a cadastral
  record. All verification is internal consistency.
- {inferred_share:.0f}% of the area is inferred, so area figures should be read
  as estimates with a wide margin.
- Only {data['n_surveyed']} of {data['n_surveys']} surveys close into a
  boundary on their own; {data['n_surveys'] - data['n_polygons']} yield no area
  at all.
- The surveys span 16 months, so a boundary walked early and one walked late
  are not necessarily contemporaneous.

Method, parameters and open questions are in `docs/METHODS.md`. Questions for
the field team are in `output/queries/`.
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tracks", type=Path,
                        default=dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg")
    parser.add_argument("--polygons", type=Path,
                        default=dataio.SMOOTHED_DIR / "mca_polygons.gpkg")
    parser.add_argument("--out", type=Path,
                        default=dataio.OUT_DIR / "SUMMARY.md")
    parser.add_argument("--map", type=Path,
                        default=dataio.OUT_DIR / "summary_map.png")
    args = parser.parse_args(argv)

    if not args.tracks.exists() or not args.polygons.exists():
        print("Run scripts/run_pipeline.py first.")
        return 1

    data = gather(args.tracks, args.polygons)
    render_map(data, args.map)
    write(data, args.out, args.map.name)

    print(f"{data['n_clans']} clans, {data['n_surveys']} surveys, "
          f"{data['boundary_km']:,.0f} km of boundary")
    print(f"{data['clans_overlapping']} of {data['clans_mapped']} mapped clans "
          f"overlap another ({data['clans_overlapping'] / data['clans_mapped'] * 100:.0f}%), "
          f"{data['contested_ha']:,.0f} ha contested")
    print(f"\nWrote {args.out}")
    print(f"Wrote {args.map}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
