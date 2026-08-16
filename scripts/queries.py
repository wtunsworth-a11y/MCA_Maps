#!/usr/bin/env python3
"""Generate the field query pack — questions for the survey team, each mapped.

Anything this pipeline cannot settle from the data alone becomes a numbered
query here, with a map showing exactly the ground in question so the discussion
on site can be specific rather than general.

Queries are regenerated from the current data every run. A query that the data
no longer supports simply stops being produced, so the pack never carries a
stale question. Resolved queries should be recorded in docs/METHODS.md §6 and
removed from the generator.

Output: output/queries/QUERIES.md plus one PNG per query.

Usage:
    python scripts/queries.py
    python scripts/queries.py --out-dir output/queries
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

import geopandas as gpd
import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import closure  # noqa: E402
import dataio  # noqa: E402
import terrain  # noqa: E402

HIGHLIGHT = ["#dc2626", "#2563eb", "#059669", "#d97706", "#7c3aed"]
CONTEXT = "#cbd5e1"


# --------------------------------------------------------------------------
# Map rendering
# --------------------------------------------------------------------------

def render(subject_layers: list[tuple[str, gpd.GeoDataFrame]],
           context: gpd.GeoDataFrame | None,
           boundary, out_path: Path, title: str,
           pad_fraction: float = 0.35) -> Path:
    """Draw one query map: the subject in colour, everything else muted."""
    figure, axis = plt.subplots(figsize=(9, 8), dpi=140)
    terrain.add_hillshade(axis, dataio.METRIC_CRS, alpha=0.45)

    if boundary is not None:
        gpd.GeoSeries([boundary], crs=dataio.METRIC_CRS).boundary.plot(
            ax=axis, color="#94a3b8", linewidth=1.0, zorder=0)

    subject = pd.concat([frame for _, frame in subject_layers])
    if subject.empty or not all(map(_finite, subject.total_bounds)):
        # Nothing to frame the view on. Better to skip the map than to raise
        # from deep inside the spatial index on a NaN bounding box.
        plt.close(figure)
        return out_path
    minx, miny, maxx, maxy = subject.total_bounds
    span = max(maxx - minx, maxy - miny, 500)
    pad = span * pad_fraction
    view = (minx - pad, miny - pad, maxx + pad, maxy + pad)

    if context is not None and not context.empty:
        window = context.cx[view[0]:view[2], view[1]:view[3]]
        if not window.empty:
            window.plot(ax=axis, color=CONTEXT, linewidth=0.6, zorder=1)

    handles = []
    for index, (label, frame) in enumerate(subject_layers):
        colour = HIGHLIGHT[index % len(HIGHLIGHT)]
        kind = frame.geom_type.iloc[0] if len(frame) else "LineString"
        if "Polygon" in str(kind):
            frame.plot(ax=axis, facecolor=colour, edgecolor=colour,
                       alpha=0.35, linewidth=1.4, zorder=2 + index)
            handles.append(Patch(facecolor=colour, alpha=0.5, label=label))
        else:
            frame.plot(ax=axis, color=colour, linewidth=1.8, zorder=2 + index)
            handles.append(Line2D([0], [0], color=colour, lw=2, label=label))

    axis.set_xlim(view[0], view[2])
    axis.set_ylim(view[1], view[3])
    axis.set_axis_off()
    axis.set_title(textwrap.fill(title, 62), fontsize=11, pad=10)

    handles.append(Line2D([0], [0], color=CONTEXT, lw=2,
                          label="other surveys nearby"))
    axis.legend(handles=handles, loc="lower left", fontsize=8, frameon=True)

    _scale_bar(axis, view)
    figure.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(out_path, bbox_inches="tight")
    plt.close(figure)
    return out_path


def render_index(numbered: list, tracks: gpd.GeoDataFrame, boundary,
                 out_path: Path) -> Path:
    """One map showing where every query sits, numbered to match the pack."""
    figure, axis = plt.subplots(figsize=(10, 9), dpi=140)
    terrain.add_hillshade(axis, dataio.METRIC_CRS, alpha=0.4)

    if boundary is not None:
        gpd.GeoSeries([boundary], crs=dataio.METRIC_CRS).boundary.plot(
            ax=axis, color="#475569", linewidth=1.2, zorder=1)
    tracks.plot(ax=axis, color=CONTEXT, linewidth=0.7, zorder=2)

    for number, query in numbered:
        subject = pd.concat([frame for _, frame in query["layers"]])
        if subject.empty:
            continue
        centre = subject.union_all().centroid
        axis.plot(centre.x, centre.y, marker="o", markersize=13,
                  markerfacecolor="#fef3c7", markeredgecolor="#b45309",
                  markeredgewidth=1.2, zorder=5)
        axis.annotate(str(number), (centre.x, centre.y), ha="center",
                      va="center", fontsize=7.5, fontweight="bold",
                      color="#7c2d12", zorder=6)

    axis.set_axis_off()
    axis.set_title(f"Where the {len(numbered)} queries are", fontsize=12,
                   pad=10)
    figure.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(out_path, bbox_inches="tight")
    plt.close(figure)
    return out_path


def _finite(value) -> bool:
    return value == value and abs(value) != float("inf")


def _scale_bar(axis, view) -> None:
    """A simple metric scale bar — these maps carry no basemap for scale."""
    width = view[2] - view[0]
    for candidate in (100, 250, 500, 1000, 2000, 5000, 10000, 20000):
        if candidate > width * 0.30:
            length = candidate
            break
    else:
        length = 20000
    # Bottom right: the legend sits bottom left.
    x0 = view[2] - width * 0.05 - length
    y0 = view[1] + (view[3] - view[1]) * 0.06
    axis.plot([x0, x0 + length], [y0, y0], color="#334155", linewidth=2.5,
              solid_capstyle="butt", zorder=10)
    axis.text(x0 + length / 2, y0 + (view[3] - view[1]) * 0.012,
              f"{length / 1000:g} km" if length >= 1000 else f"{length:g} m",
              ha="center", fontsize=8, color="#334155", zorder=10)


# --------------------------------------------------------------------------
# Query builders
# --------------------------------------------------------------------------

def overlap_queries(polys: gpd.GeoDataFrame, clans: gpd.GeoDataFrame,
                    min_pct: float, limit: int) -> list[dict]:
    """One query per clan pair sharing a material share of either's land."""
    import polygons as polygon_tools

    pairs = polygon_tools.overlaps(clans, "clan")
    if pairs.empty:
        return []
    pairs = pairs[(pairs.pct_of_a >= min_pct) | (pairs.pct_of_b >= min_pct)]

    out = []
    for _, row in pairs.head(limit).iterrows():
        a = clans[clans.clan == row.clan_a]
        b = clans[clans.clan == row.clan_b]
        basis_a = sorted(set(polys[polys.clan == row.clan_a].basis))
        basis_b = sorted(set(polys[polys.clan == row.clan_b].basis))
        out.append({
            "category": "Overlapping clan areas",
            "title": f"{row.clan_a} and {row.clan_b} overlap by "
                     f"{row.shared_ha:,.1f} ha",
            "question":
                f"The mapped areas for **{row.clan_a}** and **{row.clan_b}** "
                f"share **{row.shared_ha:,.1f} ha** — {row.pct_of_a}% of "
                f"{row.clan_a}'s area and {row.pct_of_b}% of "
                f"{row.clan_b}'s.\n\n"
                "Is this shared or disputed ground, is one boundary recorded "
                "wrongly, or are these in fact one clan under two names?",
            "note": f"{row.clan_a} area is {'/'.join(basis_a)}; "
                    f"{row.clan_b} area is {'/'.join(basis_b)}. "
                    "Inferred areas are estimates, so an overlap between two "
                    "inferred areas may be an artefact of estimation.",
            "layers": [(f"{row.clan_a}", a), (f"{row.clan_b}", b)],
        })
    return out


def near_closure_queries(tracks: gpd.GeoDataFrame, table: pd.DataFrame,
                         limit: int) -> list[dict]:
    """Surveys a short walk away from completing a boundary."""
    near = table[table.status == "near"].sort_values("gap_pct").head(limit)
    out = []
    for _, row in near.iterrows():
        subject = tracks[tracks.unit == row.source_name]
        out.append({
            "category": "Boundaries close to completion",
            "title": f"{row.clan} ({row.steward}) — {row.gap_m:,.0f} m from "
                     "closing",
            "question":
                f"**{row.clan}**, walked by **{row.steward}** in "
                f"{row.zone}, covers {row.length_km:,.1f} km but the ends do "
                f"not meet: **{row.gap_m:,.0f} m apart**, "
                f"{row.gap_pct}% of the distance walked.\n\n"
                "Can the remaining stretch be walked to close the boundary? "
                "If the gap is deliberate — a river, a road, an agreed open "
                "edge — please say what runs along it.",
            "note": "Until this closes, the clan's area can only be estimated "
                    "by joining the ends with a straight line.",
            "layers": [(f"{row.clan} tracks", subject)],
        })
    return out


def unclosed_queries(tracks: gpd.GeoDataFrame, table: pd.DataFrame,
                     limit: int) -> list[dict]:
    """Surveys too open to give an area at all."""
    worst = table[table.status == "open"].sort_values(
        "gap_pct", ascending=False).head(limit)
    out = []
    for _, row in worst.iterrows():
        subject = tracks[tracks.unit == row.source_name]
        out.append({
            "category": "Boundaries that cannot yet give an area",
            "title": f"{row.clan or '(no clan recorded)'} ({row.steward}) — "
                     f"recorded in {row.chains} separate pieces",
            "question":
                f"**{row.clan or 'This survey'}**, walked by "
                f"**{row.steward}** in {row.zone}, covers "
                f"{row.length_km:,.1f} km but is recorded as "
                f"**{row.chains} disconnected pieces**, needing "
                f"{row.gap_m:,.0f} m of straight-line joins to form a ring "
                f"({row.gap_pct}% of the distance walked).\n\n"
                "Are the missing stretches still to be walked, or were they "
                "walked and not recorded? Should these pieces be treated as "
                "one boundary at all?",
            "note": "No area is reported for this clan while the boundary is "
                    "this open.",
            "layers": [(f"{row.clan or 'survey'} tracks", subject)],
        })
    return out


def feature_type_queries(tracks: gpd.GeoDataFrame) -> list[dict]:
    """Surveys that are not clan land boundaries but sit in the totals."""
    out = []
    # Restricted types are reported in aggregate only and never mapped, so no
    # query is raised for them — a query map would show exactly the locations
    # that are being withheld.
    kinds = set(tracks.feature_type) - {"Land Boundary"} - dataio.RESTRICTED_TYPES
    for feature_type in sorted(kinds):
        subject = tracks[tracks.feature_type == feature_type]
        clan = ", ".join(sorted({c for c in subject.clan if str(c).strip()})) \
            or "no clan recorded"
        steward = ", ".join(sorted(set(subject.steward)))
        out.append({
            "category": "Surveys that are not clan land boundaries",
            "title": f"{feature_type}: {steward}",
            "question":
                f"This survey is recorded as a **{feature_type}**, not a clan "
                f"land boundary — walked by **{steward}** "
                f"({subject.zone.iloc[0]}), {len(subject)} track(s), "
                f"{subject.geometry.length.sum() / 1000:,.1f} km, "
                f"attributed to **{clan}**.\n\n"
                "Should it count towards that clan's mapped land area, be "
                "reported separately, or be excluded from the boundary "
                "figures altogether?",
            "note": "Currently included in the totals. It is tagged by type "
                    "and can be filtered out in one step once decided.",
            "layers": [(feature_type, subject)],
        })
    return out


def date_queries(tracks: gpd.GeoDataFrame) -> list[dict]:
    """The file-name date against the GPS timestamps, as one systemic query.

    This is deliberately not raised per survey. When every survey disagrees the
    same way it is one question about how the files were named, and forty
    near-identical queries would bury the real ones.
    """
    import re

    filed_dates, spans, mismatched = set(), [], 0
    for _, group in tracks.groupby("source_name"):
        stamps = set()
        for value in group.get("name", pd.Series(dtype=str)).astype(str):
            match = re.match(r"\s*(\d{4})-(\d{2})-\d{2}", value)
            if match:
                stamps.add(f"{match.group(1)}-{match.group(2)}")
        if not stamps:
            continue
        spans.append(stamps)
        filed = str(group.survey_date.iloc[0] or "")[:7]
        if filed:
            filed_dates.add(filed)
            if filed not in stamps:
                mismatched += 1

    if not spans or not mismatched:
        return []

    months = sorted({m for s in spans for m in s})
    multi = sum(1 for s in spans if len(s) > 1)

    # Colour the tracks by the year they were actually recorded, which shows
    # whether the survey effort moved across the zones over time.
    by_year: dict[str, list] = {}
    for source, group in tracks.groupby("source_name"):
        stamps = set()
        for value in group.get("name", pd.Series(dtype=str)).astype(str):
            match = re.match(r"\s*(\d{4})", value)
            if match:
                stamps.add(match.group(1))
        if stamps:
            by_year.setdefault(min(stamps), []).append(group)
    layers = [(f"recorded {year}", pd.concat(frames))
              for year, frames in sorted(by_year.items())]

    return [{
        "category": "Dates that disagree",
        "title": f"Every file name is dated {'/'.join(sorted(filed_dates))}, "
                 f"but the tracks span {months[0]} to {months[-1]}",
        "question":
            f"**{mismatched} of {len(spans)} surveys** carry a file-name date "
            f"that does not match the GPS timestamps inside them — in fact "
            f"**none of them match**. File names give "
            f"{'/'.join(sorted(filed_dates))}, while the tracks themselves "
            f"were recorded between **{months[0]}** and **{months[-1]}**. "
            f"{multi} surveys contain tracks recorded across more than one "
            f"month.\n\n"
            "Is the file-name date the date the files were compiled or "
            "submitted, rather than when the boundary was walked? If so we "
            "will take the survey date from the GPS timestamps instead, which "
            "are the only per-track dates available.",
        "note": "Until this is settled the `survey_date` attribute should not "
                "be relied on. Nothing downstream uses it, so no figures "
                "change either way — but it is wrong in the data as it stands.",
        "layers": layers,
    }]


def zone_coverage_queries(tracks: gpd.GeoDataFrame,
                          polys: gpd.GeoDataFrame) -> list[dict]:
    """Zones returning far less mapped area than the walking suggests."""
    out = []
    per_zone = tracks.groupby("zone").agg(
        surveys=("source_name", "nunique"),
        tracks=("geometry", "size"),
        km=("geometry", lambda s: s.length.sum() / 1000))
    areas = polys.groupby("zone").area_ha.sum()

    for zone, row in per_zone.iterrows():
        area = float(areas.get(zone, 0.0))
        per_km = area / row.km if row.km else 0
        typical = (areas.sum() / per_zone.km.sum()) if per_zone.km.sum() else 0
        if typical == 0 or per_km >= typical * 0.25 or row.surveys < 3:
            continue
        subject = tracks[tracks.zone == zone]
        out.append({
            "category": "Zones returning little mapped area",
            "title": f"{zone} — {row.km:,.1f} km walked, only {area:,.1f} ha "
                     "mapped",
            "question":
                f"**{zone}** has {row.surveys} surveys and {row.tracks} tracks "
                f"covering {row.km:,.1f} km, but yields only "
                f"**{area:,.1f} ha** of mapped area — far less per kilometre "
                f"walked than the other zones.\n\n"
                "Is this the full set of surveys for this zone, or is more "
                "still to come? Were these boundaries walked in full?",
            "note": f"Median tracks per survey across all zones is "
                    f"{int(tracks.groupby('source_name').size().median())}; "
                    f"in {zone} it is "
                    f"{int(subject.groupby('source_name').size().median())}.",
            "layers": [(f"{zone} tracks", subject)],
        })
    return out


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tracks", type=Path,
                        default=dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg")
    parser.add_argument("--polygons", type=Path,
                        default=dataio.SMOOTHED_DIR / "mca_polygons.gpkg")
    parser.add_argument("--out-dir", type=Path,
                        default=dataio.OUT_DIR / "queries")
    parser.add_argument("--min-overlap-pct", type=float, default=20.0)
    parser.add_argument("--max-per-category", type=int, default=5)
    args = parser.parse_args(argv)

    if not args.tracks.exists():
        print(f"No smoothed tracks at {args.tracks}. Run smooth_tracks.py.")
        return 1

    tracks = gpd.read_file(args.tracks,
                           layer="tracks_smoothed").to_crs(dataio.METRIC_CRS)
    # closure and polygons are keyed on the joined unit (one clan in one zone),
    # so the tracks need the same key or every lookup here returns nothing.
    tracks["unit"] = dataio.survey_group(tracks)
    polys = gpd.read_file(args.polygons,
                          layer="survey_polygons").to_crs(dataio.METRIC_CRS)
    clans = gpd.read_file(args.polygons,
                          layer="clan_polygons").to_crs(dataio.METRIC_CRS)
    boundary = dataio.load_boundary()
    table = closure.analyse_all(tracks, 25.0, 0.10, 0.10, 100.0, 0.50)

    # Overlapping clan areas and the file-name dates are both settled, so
    # neither is raised any more. Overlaps between clans are a fact of the
    # tenure here, not an error to resolve; and the file-name date is the date
    # the archive was collated and delivered, while the GPS timestamps are when
    # the ground was walked. Both are recorded in docs/METHODS.md §6.
    queries: list[dict] = []
    queries += near_closure_queries(tracks, table, args.max_per_category)
    queries += unclosed_queries(tracks, table, args.max_per_category)
    queries += feature_type_queries(tracks)
    queries += zone_coverage_queries(tracks, polys)

    if not queries:
        print("No open queries — nothing needs the field team.")
        return 0

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for path in args.out_dir.glob("Q*.png"):
        path.unlink()

    lines = [
        "# Field queries — MCA clan boundary mapping", "",
        f"**{len(queries)} queries** raised from the current data "
        f"({tracks.source_name.nunique()} surveys). Each has a map showing the "
        "ground in question.", "",
        "These are questions the data cannot answer on its own. Please mark "
        "each one resolved with a short note, and return the pack.", "",
        "Maps carry no aerial background — they show the recorded walks only, "
        "with a scale bar. Nearby surveys are drawn in grey for orientation.",
        "", "---", "",
    ]

    current_category = None
    for index, query in enumerate(queries, start=1):
        if query["category"] != current_category:
            current_category = query["category"]
            lines += [f"## {current_category}", ""]

        image = args.out_dir / f"Q{index:02d}.png"
        render(query["layers"],
               context=tracks,
               boundary=boundary,
               out_path=image,
               title=f"Q{index:02d}. {query['title']}")

        lines += [
            f"### Q{index:02d}. {query['title']}", "",
            query["question"], "",
            f"> {query['note']}", "",
            f"![Q{index:02d}]({image.name})", "",
            "**Response:**", "", "```", "", "```", "", "---", "",
        ]
        print(f"  Q{index:02d}  {query['title'][:66]}")

    index_map = args.out_dir / "Q00_index.png"
    render_index([(i, q) for i, q in enumerate(queries, start=1)], tracks,
                 boundary, index_map)
    lines.insert(8, f"![Query locations]({index_map.name})\n")
    lines.insert(8, "## Where the queries are\n")
    print(f"  index map: {index_map.name}")

    report = args.out_dir / "QUERIES.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {report} with {len(queries)} queries and maps")
    return 0


if __name__ == "__main__":
    sys.exit(main())
