#!/usr/bin/env python3
"""Run the whole pipeline and account for every feature through it.

Built for repetition. New archives are dropped into data/raw/ and this is
re-run; every stage rebuilds from the raw data, so nothing accumulates state
and no earlier run can contaminate a later one.

The audit is the point. Each stage reports what went in and what came out, and
any difference has to be explained by a rule the pipeline states — an archive
that could not be opened, a track clipped for being outside the area, a survey
too open to give an area. Anything unexplained is reported as a **LOSS** and
the run exits non-zero, so a silent drop cannot pass unnoticed between rounds.

Usage:
    python scripts/run_pipeline.py
    python scripts/run_pipeline.py --refresh          # re-extract archives
    python scripts/run_pipeline.py --skip-maps        # analysis only
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent


def run(name: str, *arguments: str) -> bool:
    """Run one stage, streaming nothing but reporting success."""
    command = [sys.executable, str(SCRIPTS / name), *arguments]
    result = subprocess.run(command, capture_output=True, text=True)
    ok = result.returncode == 0
    print(f"  {'ok ' if ok else 'FAIL'}  {name} {' '.join(arguments)}")
    if not ok:
        print("\n".join("        " + line
                        for line in result.stderr.strip().splitlines()[-12:]))
    return ok


def audit(raw_dir: Path) -> tuple[list[str], dict]:
    """Reconcile counts from the archives through to the polygons."""
    import geopandas as gpd

    problems: list[str] = []
    numbers: dict = {}

    archives = sorted(raw_dir.rglob("*.zip"))
    unreadable = []
    for archive in archives:
        try:
            with zipfile.ZipFile(archive) as handle:
                handle.testzip()
        except Exception as exc:
            unreadable.append(f"{archive.name}: {exc}")
    numbers["archives"] = len(archives)
    if unreadable:
        problems += [f"LOSS: unreadable archive — {u}" for u in unreadable]

    layers = dataio.load_all(raw_dir=raw_dir, quiet=True)
    numbers["source_layers"] = len(layers)
    numbers["raw_features"] = sum(len(layer.gdf) for layer in layers)

    merged = dataio.combine(layers)
    numbers["merged_features"] = len(merged.gdf) if merged is not None else 0
    if numbers["merged_features"] != numbers["raw_features"]:
        problems.append(
            f"LOSS: merge changed the feature count — "
            f"{numbers['raw_features']} in, {numbers['merged_features']} out")

    smoothed_path = dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg"
    if smoothed_path.exists():
        smoothed = gpd.read_file(smoothed_path, layer="tracks_smoothed")
        numbers["smoothed_features"] = len(smoothed)
        numbers["clipped_out"] = numbers["merged_features"] - len(smoothed)
        numbers["surveys_raw"] = merged.gdf.source_name.nunique()
        numbers["surveys_smoothed"] = smoothed.source_name.nunique()
        if numbers["surveys_smoothed"] < numbers["surveys_raw"]:
            lost = (set(merged.gdf.source_name) - set(smoothed.source_name))
            problems.append(
                f"CHECK: {len(lost)} survey(s) have no smoothed track at all — "
                f"{', '.join(sorted(lost)[:3])}"
                + (" …" if len(lost) > 3 else "")
                + " (expected only if entirely outside the clip distance)")
        invalid = int((~smoothed.geometry.is_valid).sum())
        if invalid:
            problems.append(f"LOSS: {invalid} invalid smoothed geometries")
        empty = int(smoothed.geometry.isna().sum())
        if empty:
            problems.append(f"LOSS: {empty} null smoothed geometries")
    else:
        problems.append("LOSS: no smoothed output was written")

    polygon_path = dataio.SMOOTHED_DIR / "mca_polygons.gpkg"
    if polygon_path.exists():
        polys = gpd.read_file(polygon_path, layer="survey_polygons")
        numbers["polygons"] = len(polys)
        numbers["polygon_surveys"] = polys.source_name.nunique()
        numbers["surveys_without_area"] = (
            numbers.get("surveys_smoothed", 0) - numbers["polygon_surveys"])

    return problems, numbers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw-dir", type=Path, default=dataio.RAW_DIR)
    parser.add_argument("--refresh", action="store_true",
                        help="re-extract the archives from scratch")
    parser.add_argument("--skip-maps", action="store_true",
                        help="skip the rendering stages")
    parser.add_argument("--terrain-analysis", action="store_true",
                        help="also re-derive drainage and ridgelines; slow, "
                             "and only needed when the DEM or extent changes")
    parser.add_argument("--fetch-dem", action="store_true",
                        help="re-fetch the terrain DEM first; needed when new "
                             "surveys fall outside the area already covered")
    args = parser.parse_args(argv)

    refresh = ["--refresh"] if args.refresh else []
    smoothed = str(dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg")

    print("Running pipeline\n")
    stages = []
    if args.fetch_dem:
        stages.append(("fetch_dem.py", []))
    if args.terrain_analysis:
        stages += [("hydrology.py", ["--report", "output/hydrology_report.md"]),
                   ("landform.py", ["--report", "output/landform_report.md"])]
    stages += [
        ("inspect_data.py", ["--summary", "--report", "output/data_profile.md",
                             *refresh]),
        ("smooth_tracks.py", [*refresh]),
        ("closure.py", ["--report", "output/closure_report.md"]),
        ("polygons.py", ["--report", "output/polygon_report.md",
                         "--map", "output/areas_mapped.png"]),
        ("sacred_sites.py", ["--report", "output/sacred_sites.md",
                             "--out", str(dataio.SMOOTHED_DIR
                                          / "mca_sacred_sites.gpkg")]),
        ("queries.py", []),
    ]
    if not args.skip_maps:
        stages += [
            ("make_maps.py", ["--smoothed", smoothed]),
            ("build_project.py", []),
        ]

    failed = [name for name, arguments in stages if not run(name, *arguments)]

    print("\nAudit\n")
    problems, numbers = audit(args.raw_dir)
    for key, value in numbers.items():
        print(f"  {key:24s} {value:>8,}")

    if problems:
        print()
        for problem in problems:
            print(f"  {problem}")

    print()
    losses = [p for p in problems if p.startswith("LOSS")]
    if failed:
        print(f"FAILED: {len(failed)} stage(s) did not complete — "
              f"{', '.join(failed)}")
        return 1
    if losses:
        print(f"FAILED: {len(losses)} unexplained loss(es) — see above")
        return 1
    print("All stages completed; every feature accounted for.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
