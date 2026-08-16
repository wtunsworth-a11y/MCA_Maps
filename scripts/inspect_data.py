#!/usr/bin/env python3
"""Stage 1 — look at what is actually in the raw archives.

Prints a profile of every layer found: feature count, geometry types, native
CRS, extent, and a per-column summary with fill rates. Run this before
rendering anything, so surprises show up here rather than on a map.

Usage:
    python scripts/inspect_data.py
    python scripts/inspect_data.py --only survey_2026 --max-columns 40
    python scripts/inspect_data.py --report output/data_profile.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402


def profile_layer(layer: dataio.Layer, max_columns: int) -> list[str]:
    """Build a human-readable profile of one layer as markdown lines."""
    gdf = layer.gdf
    minx, miny, maxx, maxy = gdf.total_bounds
    lines = [
        f"## {layer.name}",
        "",
        f"- **Source:** `{_relative(layer.source)}`",
        f"- **Features:** {len(gdf):,}",
        f"- **Geometry:** {', '.join(layer.geom_types)}",
        f"- **Native CRS:** {layer.source_crs or 'none declared'}",
        f"- **Extent (WGS84):** {miny:.5f}, {minx:.5f} → {maxy:.5f}, {maxx:.5f}",
        f"- **Attributes:** {len(gdf.columns) - 1}",
        "",
    ]

    attributes = [c for c in gdf.columns if c != "geometry"]
    if not attributes:
        lines += ["_No attribute columns._", ""]
        return lines

    lines += ["| Column | Type | Filled | Unique | Example |",
              "| --- | --- | --- | --- | --- |"]
    for column in attributes[:max_columns]:
        series = gdf[column]
        filled = series.notna().sum()
        pct = filled / len(gdf) * 100 if len(gdf) else 0.0
        unique = series.nunique(dropna=True)
        example = _example(series)
        lines.append(
            f"| `{column}` | {series.dtype} | {filled:,} ({pct:.0f}%) "
            f"| {unique:,} | {example} |"
        )
    if len(attributes) > max_columns:
        lines.append(f"| _… {len(attributes) - max_columns} more columns_ "
                     "| | | | |")
    lines.append("")

    invalid = int((~gdf.geometry.is_valid).sum())
    if invalid:
        lines += [f"> {invalid:,} geometries fail an OGC validity check. "
                  "QGIS will still draw them, but buffers and overlays may "
                  "misbehave until they are repaired.", ""]
    return lines


def _overview(layer: dataio.Layer) -> list[str]:
    """Cross-layer counts, from the attributes the file names encode."""
    gdf = layer.gdf
    lines = ["## Overview", ""]

    for column, title in (("zone", "Zone"), ("feature_type", "Type")):
        if column not in gdf.columns:
            continue
        counts = gdf[column].fillna("(none)").value_counts().sort_index()
        lines += [f"| {title} | Features | Surveys |", "| --- | ---: | ---: |"]
        for value, count in counts.items():
            surveys = gdf.loc[gdf[column].fillna("(none)") == value,
                              "source_name"].nunique()
            lines.append(f"| {value} | {count:,} | {surveys} |")
        lines.append("")

    if "clan" in gdf.columns:
        clans_seen = {c for c in gdf["clan"].dropna() if str(c).strip()}
        custodians = {c for c in gdf.get("custodian", pd.Series(dtype=str))
                      .dropna() if str(c).strip()}
        lines += [f"- **Distinct clans:** {len(clans_seen)}",
                  f"- **Distinct custodians:** {len(custodians)}",
                  f"- **Source surveys:** {gdf['source_name'].nunique()}", ""]
    return lines


def quality_report(layer: dataio.Layer, outlier_factor: float) -> list[str]:
    """Flag the things worth a human look before any of this becomes a map.

    None of these are corrected automatically — whether a stray track is a
    test recording or a real remote parcel is a judgement for whoever knows
    the survey, not for this script.
    """
    import difflib

    gdf = layer.gdf
    lines = ["## Data quality checks", ""]
    findings = 0

    # Features whose own name says they are not real survey records.
    name_columns = [c for c in ("name", "cmt", "desc") if c in gdf.columns]
    if name_columns:
        joined = pd.Series("", index=gdf.index)
        for column in name_columns:
            joined = joined + " " + gdf[column].fillna("").astype(str)
        suspect = gdf[joined.str.contains(r"\btest\b|\bdemo\b|\bdummy\b",
                                          case=False, na=False)]
        if len(suspect):
            findings += 1
            lines += [f"**{len(suspect)} feature(s) named as test data.** "
                      "Likely worth excluding before publishing:", ""]
            lines += _finding_table(suspect)

    # Features sitting far from everything else. Measured in Web Mercator so
    # the distances are metres and no "centroid of a geographic CRS" warning
    # is raised; at this scale the projection distortion is irrelevant.
    centroids = gdf.geometry.to_crs(dataio.WEB_MERCATOR).centroid
    mid_x, mid_y = centroids.x.median(), centroids.y.median()
    distance = ((centroids.x - mid_x) ** 2 + (centroids.y - mid_y) ** 2) ** 0.5
    typical = distance.median()
    if typical > 0:
        outliers = gdf[distance > typical * outlier_factor]
        if len(outliers):
            findings += 1
            lines += ["", f"**{len(outliers)} feature(s) far from the main "
                      f"survey area** (more than {outlier_factor:g}× the "
                      "median distance from its centre):", ""]
            lines += _finding_table(outliers)

    # Clan names that look like spellings of each other.
    if "clan" in gdf.columns:
        names = sorted({str(c) for c in gdf["clan"].dropna() if str(c).strip()})
        pairs, seen = [], set()
        for name in names:
            for other in difflib.get_close_matches(name, names, n=3, cutoff=0.8):
                key = tuple(sorted((name, other)))
                if other != name and key not in seen:
                    seen.add(key)
                    pairs.append(key)
        if pairs:
            findings += 1
            lines += ["", f"**{len(pairs)} pair(s) of similar clan names.** "
                      "These may be spelling variants of one clan, or genuinely "
                      "distinct — worth confirming:", "",
                      "| | |", "| --- | --- |"]
            lines += [f"| `{a}` | `{b}` |" for a, b in pairs]

    if not findings:
        lines += ["Nothing flagged.", ""]
    lines.append("")
    return lines


def _finding_table(rows) -> list[str]:
    columns = [c for c in ("zone", "clan", "custodian", "name", "source_name")
               if c in rows.columns]
    if not columns:
        columns = [c for c in rows.columns if c != "geometry"][:4]
    out = ["| " + " | ".join(columns) + " |",
           "| " + " | ".join("---" for _ in columns) + " |"]
    for _, row in rows.head(15).iterrows():
        cells = [str(row[c]).replace("|", "\\|")[:45] for c in columns]
        out.append("| " + " | ".join(cells) + " |")
    if len(rows) > 15:
        out.append(f"| _… {len(rows) - 15} more_ |" + " |" * (len(columns) - 1))
    out.append("")
    return out


def _example(series: pd.Series) -> str:
    non_null = series.dropna()
    if non_null.empty:
        return "—"
    value = str(non_null.iloc[0]).replace("|", "\\|").replace("\n", " ")
    return f"`{value[:40]}`" if len(value) <= 40 else f"`{value[:40]}…`"


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(dataio.REPO_ROOT))
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    dataio.add_common_args(parser)
    parser.add_argument("--max-columns", type=int, default=25,
                        help="how many attribute columns to profile per layer")
    parser.add_argument("--report", type=Path, default=None,
                        help="also write the profile to this markdown file")
    parser.add_argument("--summary", action="store_true",
                        help="only the cross-layer summary and quality checks")
    parser.add_argument("--outlier-factor", type=float, default=3.0,
                        help="how far from the survey centre counts as an "
                             "outlier, as a multiple of the median distance")
    args = parser.parse_args(argv)

    if not args.raw_dir.exists():
        print(f"No raw data directory at {args.raw_dir}")
        return 1

    layers = dataio.load_from_args(args)
    if not layers:
        print(f"\nNothing found under {args.raw_dir} yet.\n"
              "Copy your zip archives in there and re-run this script.")
        return 0

    total = sum(len(layer.gdf) for layer in layers)
    lines = ["# Raw data profile", "",
             f"{len(layers)} layer(s), {total:,} features in total.", ""]

    combined = dataio.combine(layers)
    if combined is not None:
        lines += _overview(combined)
        lines += quality_report(combined, args.outlier_factor)

    if not args.summary:
        for layer in layers:
            lines += profile_layer(layer, args.max_columns)

    report = "\n".join(lines)
    print("\n" + report)

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
        print(f"Wrote {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
