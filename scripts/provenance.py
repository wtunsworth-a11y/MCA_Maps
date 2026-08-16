#!/usr/bin/env python3
"""Record what produced a set of results, so they can be reproduced later.

Written for the point where this work becomes a paper. Figures and tables get
regenerated many times before publication, and the version of GEOS or pysheds
that produced a particular number is exactly the thing nobody writes down and
everybody later needs.

Each run stamps: the library versions, the git commit, the input archives with
their sizes and checksums, the parameters in force, and the headline results.
Written to `output/PROVENANCE.md` and `output/provenance.json` — the first to
read, the second to diff between runs.

Checksums matter most. If a figure changes between runs, the first question is
whether the data changed or the code did, and comparing archive digests answers
it immediately.

Usage:
    python scripts/provenance.py
    python scripts/provenance.py --json output/provenance.json
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import platform
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402

PACKAGES = ("geopandas", "shapely", "pyogrio", "rasterio", "pysheds", "numpy",
            "pandas", "matplotlib", "folium", "scipy", "contextily")

# Everything the results depend on that came from outside this repository.
SOURCES = [
    {
        "name": "Copernicus DEM GLO-30",
        "used_for": "terrain, drainage and ridgelines",
        "access": "https://copernicus-dem-30m.s3.amazonaws.com",
        "licence": "Free, worldwide, non-exclusive (ESA/Copernicus)",
        "citation": "European Space Agency, Sinergise (2021). Copernicus "
                    "Global Digital Elevation Model. Distributed by "
                    "OpenTopography. https://doi.org/10.5069/G9028PQB",
    },
    {
        "name": "World Database on Protected Areas — Managalas "
                "Conservation Area",
        "used_for": "the MCA reference boundary and the 10 km clip",
        "access": "supplied as KML (WDPAID 555651673, WDPA_PID 555651673)",
        "licence": "WDPA terms of use — check before republishing the polygon",
        "citation": "UNEP-WCMC and IUCN. Protected Planet: The World "
                    "Database on Protected Areas (WDPA). Cambridge, UK. "
                    "www.protectedplanet.net",
    },
    {
        "name": "Clan boundary GPS surveys",
        "used_for": "everything else",
        "access": "supplied directly as zip archives per zone",
        "licence": "Not established — see the sensitivity note in "
                   "docs/METHODS.md",
        "citation": "Field surveys by clan custodians, Oro Province, Papua "
                    "New Guinea, 2025–2026",
    },
]

METHOD_CITATIONS = [
    "O'Callaghan, J.F. & Mark, D.M. (1984). The extraction of drainage "
    "networks from digital elevation data. Computer Vision, Graphics and "
    "Image Processing 28(3), 323–344. — D8 flow routing.",
    "Barnes, R., Lehman, C. & Mulla, D. (2014). Priority-flood: an optimal "
    "depression-filling and watershed-labeling algorithm. Computers & "
    "Geosciences 62, 117–127. — depression filling.",
    "Weiss, A. (2001). Topographic position and landforms analysis. ESRI "
    "User Conference poster. — the ridge test.",
    "Bartos, M. (2020). pysheds: simple and fast watershed delineation in "
    "Python. https://doi.org/10.5281/zenodo.3822494",
]


def versions() -> dict:
    out = {"python": sys.version.split()[0], "platform": platform.platform()}
    for package in PACKAGES:
        try:
            out[package] = metadata.version(package)
        except Exception:
            out[package] = None
    try:
        import shapely
        out["geos"] = shapely.geos_version_string
    except Exception:
        pass
    try:
        import rasterio
        out["gdal"] = rasterio.__gdal_version__
    except Exception:
        pass
    return out


def git_state() -> dict:
    def run(*command):
        try:
            return subprocess.run(command, capture_output=True, text=True,
                                  cwd=dataio.REPO_ROOT,
                                  check=True).stdout.strip()
        except Exception:
            return None

    dirty = run("git", "status", "--porcelain")
    return {
        "commit": run("git", "rev-parse", "HEAD"),
        "branch": run("git", "rev-parse", "--abbrev-ref", "HEAD"),
        "clean": dirty == "" if dirty is not None else None,
    }


def inputs(raw_dir: Path) -> list[dict]:
    """Every source archive, with a digest so changes are detectable."""
    out = []
    for archive in sorted(raw_dir.rglob("*.zip")):
        digest = hashlib.sha256()
        with archive.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        out.append({
            "file": archive.name,
            "bytes": archive.stat().st_size,
            "sha256": digest.hexdigest()[:16],
        })
    return out


def results() -> dict:
    """The headline numbers, read back from what the pipeline actually wrote."""
    import geopandas as gpd

    out: dict = {}
    tracks = dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg"
    if tracks.exists():
        frame = gpd.read_file(tracks,
                              layer="tracks_smoothed").to_crs(dataio.METRIC_CRS)
        out["surveys"] = int(frame.source_name.nunique())
        out["tracks"] = int(len(frame))
        out["clans"] = int(frame[frame.clan.astype(str).str.strip() != ""]
                           .clan.nunique())
        out["custodians"] = int(frame.custodian.nunique())
        out["zones"] = sorted(set(frame.zone.dropna()))
        out["smoothed_km"] = round(frame.geometry.length.sum() / 1000, 1)

    polygons = dataio.SMOOTHED_DIR / "mca_polygons.gpkg"
    if polygons.exists():
        frame = gpd.read_file(polygons, layer="survey_polygons")
        out["polygons"] = int(len(frame))
        out["polygons_surveyed"] = int((frame.basis == "surveyed").sum())
        out["area_ha_total"] = round(float(frame.area_ha.sum()), 1)
        out["area_ha_surveyed"] = round(
            float(frame[frame.basis == "surveyed"].area_ha.sum()), 1)
    return out


def parameters() -> dict:
    import closure
    import polygons as polygon_tools
    import smooth_tracks

    return {
        "clip_distance_km": smooth_tracks.DEFAULT_MAX_DISTANCE_KM,
        "resample_spacing_m": smooth_tracks.DEFAULT_SPACING_M,
        "smoothing_window_points": smooth_tracks.DEFAULT_WINDOW,
        "closure_tolerance_m": closure.DEFAULT_TOLERANCE_M,
        "near_closure_threshold": closure.DEFAULT_THRESHOLD,
        "max_inferred_gap": polygon_tools.DEFAULT_MAX_GAP,
        "metric_crs": dataio.METRIC_CRS,
        "storage_crs": dataio.WGS84,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw-dir", type=Path, default=dataio.RAW_DIR)
    parser.add_argument("--out", type=Path,
                        default=dataio.OUT_DIR / "PROVENANCE.md")
    parser.add_argument("--json", type=Path,
                        default=dataio.OUT_DIR / "provenance.json")
    args = parser.parse_args(argv)

    record = {
        "versions": versions(),
        "git": git_state(),
        "inputs": inputs(args.raw_dir),
        "parameters": parameters(),
        "results": results(),
        "sources": SOURCES,
        "method_citations": METHOD_CITATIONS,
    }

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")

    git = record["git"]
    lines = [
        "# Provenance", "",
        "What produced the current results. Regenerated on every pipeline run "
        "— no date is recorded here on purpose, since the commit and the input "
        "checksums identify a run far more reliably than a timestamp.", "",
        "## Code", "",
        f"- **Commit:** `{git.get('commit') or 'unknown'}`",
        f"- **Branch:** `{git.get('branch') or 'unknown'}`",
        f"- **Working tree clean:** {git.get('clean')}", "",
        "## Environment", "",
        "| Component | Version |", "| --- | --- |",
    ]
    for name, value in record["versions"].items():
        if value:
            lines.append(f"| {name} | {value} |")

    lines += ["", "## Input archives", "",
              "| Archive | Bytes | SHA-256 (first 16) |",
              "| --- | ---: | --- |"]
    for item in record["inputs"]:
        lines.append(f"| {item['file']} | {item['bytes']:,} | "
                     f"`{item['sha256']}` |")
    lines += ["",
              "If a figure changes between runs, compare these digests first: "
              "they say immediately whether the data moved or the code did.",
              ""]

    lines += ["## Parameters in force", "", "| Parameter | Value |",
              "| --- | --- |"]
    for name, value in record["parameters"].items():
        lines.append(f"| `{name}` | {value} |")

    lines += ["", "## Results produced", "", "| Measure | Value |",
              "| --- | --- |"]
    for name, value in record["results"].items():
        shown = ", ".join(value) if isinstance(value, list) else value
        lines.append(f"| {name} | {shown} |")

    lines += ["", "## Data sources", ""]
    for source in record["sources"]:
        lines += [f"**{source['name']}**", "",
                  f"- Used for: {source['used_for']}",
                  f"- Access: {source['access']}",
                  f"- Licence: {source['licence']}",
                  f"- Cite as: {source['citation']}", ""]

    lines += ["## Methods to cite", ""]
    lines += [f"- {c}" for c in record["method_citations"]]
    lines.append("")

    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {args.out}")
    print(f"Wrote {args.json}")
    print(f"\ncommit {git.get('commit', '?')[:12] if git.get('commit') else '?'}"
          f" | clean: {git.get('clean')} | "
          f"{len(record['inputs'])} archive(s) | "
          f"{record['results'].get('surveys', '?')} surveys")
    return 0


if __name__ == "__main__":
    sys.exit(main())
