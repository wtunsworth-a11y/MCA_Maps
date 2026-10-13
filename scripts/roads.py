#!/usr/bin/env python3
"""Roads and tracks for the background of a clan map.

Every tile server and every OpenStreetMap endpoint is refused by this
environment's network policy, so the usual way of putting roads behind a
map is closed. Amazon S3 is not refused, and Overture Maps publish the
OpenStreetMap road network there as GeoParquet, free and openly licensed.

Overture's transportation theme is 72 GB in 128 files. Nothing like that
is downloaded. Each file carries a footer listing, for every row group in
it, the smallest box containing that group's geometry; reading the footers
is a few hundred kilobytes of range requests, and only the row groups whose
box touches the Managalas is read in full. That is normally two or three
groups, a few tens of megabytes, once.

The result is written once to data/reference/osm/roads.gpkg and read from
disk after that, so the maps keep working whether or not the network does.

Usage:
    python scripts/roads.py --fetch
    python scripts/roads.py --fetch --theme base --type infrastructure
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402

BUCKET = "https://overturemaps-us-west-2.s3.amazonaws.com/"
RELEASE = "2026-09-23.1"
OUT = dataio.REFERENCE_DIR / "osm" / "roads.gpkg"

# The Managalas and a margin, in degrees. Nothing outside this is read.
AREA = (147.80, -9.60, 148.80, -8.90)


def keys(theme: str, kind: str) -> list[str]:
    prefix = f"release/{RELEASE}/theme={theme}/type={kind}/"
    reply = requests.get(BUCKET, params={"list-type": "2", "prefix": prefix},
                         timeout=120)
    reply.raise_for_status()
    space = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
    tree = ET.fromstring(reply.text)
    return [node.find("s:Key", space).text
            for node in tree.findall("s:Contents", space)]


def wanted_groups(handle, area):
    """Which row groups of one file hold anything inside the area."""
    west, south, east, north = area
    meta = handle.metadata
    names = meta.schema.names
    try:
        at = {part: names.index(f"bbox.{part}")
              for part in ("xmin", "xmax", "ymin", "ymax")}
    except ValueError:
        return list(range(meta.num_row_groups))
    found = []
    for index in range(meta.num_row_groups):
        group = meta.row_group(index)
        box = {part: group.column(where).statistics for part, where in at.items()}
        if any(stat is None for stat in box.values()):
            found.append(index)
            continue
        if (box["xmin"].min <= east and box["xmax"].max >= west
                and box["ymin"].min <= north and box["ymax"].max >= south):
            found.append(index)
    return found


def fetch(theme: str, kind: str, area, columns: list[str]):
    import fsspec
    import pyarrow.parquet as pq

    store = fsspec.filesystem("https")
    rows = []
    files = keys(theme, kind)
    print(f"{len(files)} file(s) in {theme}/{kind}; reading footers")
    for number, key in enumerate(files, 1):
        with store.open(BUCKET + key) as stream:
            handle = pq.ParquetFile(stream)
            groups = wanted_groups(handle, area)
            if not groups:
                continue
            print(f"  {number:3d}/{len(files)}  {len(groups)} row group(s) "
                  f"touch the area")
            table = handle.read_row_groups(groups, columns=columns)
            rows.append(table)
    if not rows:
        return None
    import pyarrow as pa
    return pa.concat_tables(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--theme", default="transportation")
    parser.add_argument("--type", dest="kind", default="segment")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)

    if not args.fetch:
        print(f"{args.out}: "
              + ("present" if args.out.exists() else "not fetched yet"))
        return 0

    columns = ["id", "geometry", "bbox", "subtype", "class", "names"]
    table = fetch(args.theme, args.kind, AREA, columns)
    if table is None:
        print("Nothing found in the area.")
        return 1

    import geopandas as gpd
    import shapely
    west, south, east, north = AREA
    frame = gpd.GeoDataFrame(
        {"id": table.column("id").to_pylist(),
         "subtype": table.column("subtype").to_pylist(),
         "class": table.column("class").to_pylist(),
         "name": [None if n is None else n.get("primary")
                  for n in table.column("names").to_pylist()]},
        geometry=shapely.from_wkb(table.column("geometry").to_pylist()),
        crs="EPSG:4326")
    frame = frame.cx[west:east, south:north]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_file(args.out, layer="roads", driver="GPKG")
    print(f"\n{len(frame):,} feature(s) written to {args.out}")
    print(frame["class"].value_counts().head(20).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
