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
