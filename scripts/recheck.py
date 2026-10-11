#!/usr/bin/env python3
"""Re-examine an approved clan against everything in the raw archives.

A map that has been approved was approved on what the pipeline chose to
show: the published layer, with sacred sites withheld, drawn only where
the closing step used it. This rebuilds the boundary from the raw files
instead and reports whether the approved figure survives.

Usage:
    python scripts/recheck.py --clan Sukandi
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chord_map  # noqa: E402
import dataio  # noqa: E402
import everything_map as em  # noqa: E402
import polygons as polygon_tools  # noqa: E402


def _flatten(rows: list) -> list:
    out = []
    for row in rows:
        geometry = row["geometry"]
        out.extend(geometry.geoms if hasattr(geometry, "geoms")
                   else [geometry])
    return [p for p in out if p is not None and p.length > 0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clan", required=True)
    parser.add_argument("--site-length", type=float, default=500.0)
    args = parser.parse_args(argv)

    tracks = gpd.read_file(dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg",
                           layer="tracks_smoothed").to_crs(dataio.METRIC_CRS)
    published = dataio.publishable(tracks.copy(), quiet=True)
    published["_unit"] = dataio.survey_group(published)
    match = published[published.clan.astype(str).str.lower()
                      .str.startswith(args.clan.lower())]
    if match.empty:
        print(f"No published survey matching {args.clan!r}.")
        return 1
    unit = match._unit.iloc[0]
    group = published[published._unit == unit]

    approved = polygon_tools.survey_polygon(
        chord_map.parts_of(group), 25.0, 0.50, 0.10,
        derived=polygon_tools.adopted_segments(unit), unit=unit)

    found = em.recordings(args.clan)
    sites = [r for r in found if r["geometry"].length < args.site_length]
    lines = [r for r in found if r["geometry"].length >= args.site_length]
    sacred = [r for r in found if any(em.SACRED.search(t) for t in r["text"])]
    raw_km = sum(r["geometry"].length for r in found) / 1000
    pub_km = group.geometry.length.sum() / 1000

    print(f"{unit}\n")
    print(f"  approved           {approved['area_ha']:9,.0f} ha  "
          f"basis {approved['basis']}, "
          f"{len(approved['bridges'])} drawn line(s)")
    print(f"  published          {pub_km:9.1f} km in {len(group)} recordings")
    print(f"  raw archives       {raw_km:9.1f} km in {len(found)} recordings")
    print(f"     hidden from the map: {raw_km - pub_km:.1f} km")
    print(f"     {len(lines)} boundary stretches, {len(sites)} marked places")
    print(f"     {len(sacred)} recording(s) with sacred or tambu wording, "
          f"{sum(r['geometry'].length for r in sacred) / 1000:.1f} km")

    # Rebuild from the smoothed layer, not the raw geometry. Raw tracks
    # carry the GPS jitter that smoothing exists to remove, and a polygon
    # built on them is measuring the jitter: Manuvoora came out at 467 ha
    # against its approved 1,058 for that reason alone, which says nothing
    # about Manuvoora. What is being tested here is what the *filter*
    # hides, so the comparison has to hold everything else steady.
    everything = tracks.copy()
    everything["_unit"] = dataio.survey_group(everything)
    whole = everything[everything._unit == unit]
    withheld = whole.loc[~whole.index.isin(group.index)]

    def build(frame, label):
        parts = chord_map.parts_of(frame)
        if not parts:
            print(f"  {label:34s} nothing to build")
            return
        built = polygon_tools.survey_polygon(
            parts, 25.0, 0.50, 0.10,
            derived=polygon_tools.adopted_segments(unit), unit=unit)
        if not built:
            print(f"  {label:34s} no polygon")
            return
        delta = built["area_ha"] - approved["area_ha"]
        print(f"  {label:34s} {built['area_ha']:9,.0f} ha  "
              f"{delta:+8,.0f}  basis {built['basis']}, "
              f"{len(built['bridges'])} drawn")

    print(f"\n  withheld by the sacred-site filter: {len(withheld)} "
          f"recording(s), {withheld.geometry.length.sum() / 1000:.1f} km")
    print("  rebuilt with the filter lifted:")
    build(group, "as approved")
    build(whole, "including the withheld")

    if sacred:
        print("\n  what the sacred recordings say:")
        for row in sacred:
            print(f"    {row['geometry'].length:7.0f} m")
            for line in row["text"]:
                if em.SACRED.search(line):
                    print(f"        {line[:96]}")

    names = sorted({em.who(r) for r in lines})
    if len(names) > 2:
        print(f"\n  steward name recorded {len(names)} ways: "
              f"{', '.join(names)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
