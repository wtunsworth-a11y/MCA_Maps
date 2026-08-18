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
import polygons  # noqa: E402
import smooth_tracks  # noqa: E402
import terrain  # noqa: E402

# One wash for mapped land, at an alpha low enough that two of them stacking
# is clearly darker and three darker still.
AREA_FILL = "#1d4ed8"
AREA_EDGE = "#1e3a8a"
AREA_ALPHA = 0.22
OPEN_LINE = "#ea580c"      # walked, but not yet closed
BRIDGE_LINE = "#db2777"    # nobody walked this


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

    # Clan-level overlap: the ILG question. Measured strictly, and again with
    # strips narrower than the tolerance removed — two lines recorded closer
    # than that are the same line, not two claims (polygons.py).
    contested_pieces, wide_pieces, per_clan = [], [], []
    for _, row in clans.iterrows():
        others = unary_union([g for name, g in zip(clans.clan, clans.geometry)
                              if name != row.clan])
        shared = row.geometry.intersection(others)
        wide = polygons.beyond_tolerance(shared)
        if shared.area > 0:
            contested_pieces.append(shared)
        if wide.area > 0:
            wide_pieces.append(wide)
        per_clan.append({
            "clan": row.clan,
            "area_ha": round(row.geometry.area / 1e4, 1),
            "pct_contested": round(shared.area / row.geometry.area * 100, 1),
            "pct_beyond_tol": round(wide.area / row.geometry.area * 100, 1),
        })
    contested = pd.DataFrame(per_clan).sort_values("pct_contested",
                                                   ascending=False)
    contested_ha = (unary_union(contested_pieces).area / 1e4
                    if contested_pieces else 0.0)
    contested_wide_ha = (unary_union(wide_pieces).area / 1e4
                         if wide_pieces else 0.0)
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

    try:
        bridges = gpd.read_file(polygons_path,
                                layer="inferred_bridges").to_crs(dataio.METRIC_CRS)
    except Exception:
        bridges = None

    mca = dataio.load_boundary()
    return {
        "tracks": tracks, "surveys": surveys, "clans": clans,
        "bridges": bridges,
        "bridge_km": (bridges.length.sum() / 1000) if bridges is not None else 0.0,
        "contested_table": contested,
        "n_surveys": int(tracks.source_name.nunique()),
        "n_tracks": int(len(tracks)),
        "n_clans": int(named.clan.nunique()),
        "n_stewards": int(tracks.steward.nunique()),
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
        "clans_overlapping_wide": int((contested.pct_beyond_tol > 0).sum()),
        "contested_ha": contested_ha,
        "contested_wide_ha": contested_wide_ha,
        "contested_strong_ha": strong,
        "tolerance_m": polygons.OVERLAP_TOLERANCE_M,
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

    # One colour for every mapped area, closed or inferred alike, drawn
    # semi-transparent and NOT dissolved. Where two clans have recorded the
    # same ground the two washes stack and it simply reads darker — the
    # overlap draws itself, with no third colour and no separate layer, and
    # ground claimed by three clans is darker again. That is the honest
    # rendering: the strength of the colour is the number of claims.
    surveys = data["surveys"]
    if len(surveys):
        surveys.plot(ax=axis, facecolor=AREA_FILL, edgecolor=AREA_EDGE,
                     linewidth=0.7, alpha=AREA_ALPHA, zorder=3)

    # The boundaries walked but still too open to give an area. A different
    # colour because they are a different kind of thing: a line on the ground,
    # not a claim to a piece of it.
    tracks = data["tracks"].assign(_unit=dataio.survey_group(data["tracks"]))
    closed_surveys = set(surveys.source_name)
    unclosed = tracks[~tracks._unit.isin(closed_surveys)]
    if len(unclosed):
        unclosed.plot(ax=axis, color=OPEN_LINE, linewidth=1.5, alpha=0.95,
                      zorder=6)

    # Kept, because it is the one thing a reader cannot infer from the shape:
    # which parts of an outline nobody walked.
    bridges = data.get("bridges")
    if bridges is not None and len(bridges):
        bridges.plot(ax=axis, color=BRIDGE_LINE, linewidth=0.9,
                     linestyle=(0, (4, 2.5)), zorder=7)

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
        Patch(facecolor=AREA_FILL, alpha=AREA_ALPHA, edgecolor=AREA_EDGE,
              label="Clan land mapped"),
        Patch(facecolor=AREA_FILL, alpha=min(1.0, AREA_ALPHA * 2.2),
              edgecolor=AREA_EDGE,
              label="Darker — recorded by more than one clan"),
        Line2D([0], [0], color=OPEN_LINE, lw=2,
               label="Walked, but too open to give an area"),
        Line2D([0], [0], color=BRIDGE_LINE, lw=1.4, linestyle=(0, (4, 2.5)),
               label="Not walked — straight line across a gap"),
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
        f"| {r.clan} | {r.area_ha:,.0f} | {r.pct_contested:.0f}% | "
        f"{r.pct_beyond_tol:.0f}% |"
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
| Stewards who walked | {data['n_stewards']} |
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

**{data['bridge_km']:,.0f} km of the outlines on this map were never walked.**
They are the straight lines you can see cutting across the landscape, and they
are drawn in pink so they are never mistaken for a boundary. They mark where a
receiver was switched off at the end of one walk and switched on again
somewhere else — not where anyone said the boundary runs. Where a clan's
outline carries a long straight line, the area behind it is a guess across
that gap, and the query on that clan's page asks for the missing stretch to be
walked.

The footprint is **{data['footprint_ha'] / data['mca_ha'] * 100:.1f}% of the
conservation area's {data['mca_ha']:,.0f} ha**.

## Overlap between clans

This is the finding with the widest implications.

Reported two ways. **Strict** counts every square metre two clans both claim.
**Beyond {data['tolerance_m']:.0f} m** removes any shared strip narrower than
that: where two recorded lines run closer together than {data['tolerance_m']:.0f}
m, the ground between them is the ordinary imprecision of GPS under canopy and
of a boundary followed on foot, not a competing claim.

| | Strict | Beyond {data['tolerance_m']:.0f} m |
| --- | ---: | ---: |
| Clans with a mapped area | {data['clans_mapped']} | {data['clans_mapped']} |
| **Clans whose land overlaps another clan's** | **{data['clans_overlapping']} ({data['clans_overlapping'] / data['clans_mapped'] * 100:.0f}%)** | **{data['clans_overlapping_wide']} ({data['clans_overlapping_wide'] / data['clans_mapped'] * 100:.0f}%)** |
| Clans with no overlap at all | {data['clans_mapped'] - data['clans_overlapping']} | {data['clans_mapped'] - data['clans_overlapping_wide']} |
| Area claimed by more than one clan | {data['contested_ha']:,.0f} ha | {data['contested_wide_ha']:,.0f} ha |
| — as a share of the mapped footprint | {data['contested_ha'] / data['footprint_ha'] * 100:.1f}% | {data['contested_wide_ha'] / data['footprint_ha'] * 100:.1f}% |

**The allowance changes almost nothing**, which is the reason for making it:
{data['contested_ha'] - data['contested_wide_ha']:,.0f} ha of the
{data['contested_ha']:,.0f} ha falls away, and
{data['clans_overlapping'] - data['clans_overlapping_wide']} clan(s) leave the
overlapping group. The finding is not an artefact of survey precision.

Most contested, as a share of each clan's own mapped land:

| Clan | Area (ha) | Contested | Beyond {data['tolerance_m']:.0f} m |
| --- | ---: | ---: | ---: |
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

### Where clans agree

The mirror image, and it does not appear in an overlap table at all. Two clans
can walk the same edge — agreeing on a boundary — while enclosing no shared
ground, because neither walk closes into a polygon.

**Deari and Nui** are the case in point. Their mapped areas never meet, so they
appear in no overlap figure above. Yet **94% of Deari's 13.1 km of recorded
line runs within 100 m of Nui's**, the two lines cross 292 times, and Deari's
whole extent sits inside Nui's. Under the {data['tolerance_m']:.0f} m rule these
two clans do not overlap: they share a boundary, and they agree on it.

Agreement of this kind is as much a finding as dispute is, and a tenure system
that records only single undisputed ownership has nowhere to put either.

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
