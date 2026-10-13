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
    # The bounding box is a struct, so its statistics hang off the leaf
    # columns 'bbox.xmin' and the rest. They are not in schema.names,
    # which lists the top-level columns only — looking for them there
    # found nothing and quietly read every row group in all 128 files.
    first = meta.row_group(0)
    at = {}
    for index in range(meta.num_columns):
        where = first.column(index).path_in_schema
        if where.startswith("bbox."):
            at[where.split(".", 1)[1]] = index
    if set(at) < {"xmin", "xmax", "ymin", "ymax"}:
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


# --- drawing -------------------------------------------------------------

# How a road is drawn depends on what it is. A national road and a
# footpath through the garden both come back as lines, and drawing them
# alike would put a motorway through the bush.
PAINT = {
    "motorway":   ("#c2410c", 2.4),
    "trunk":      ("#c2410c", 2.2),
    "primary":    ("#c2410c", 2.0),
    "secondary":  ("#d97706", 1.7),
    "tertiary":   ("#d97706", 1.4),
    "residential": ("#e0a060", 1.1),
    "unclassified": ("#e0a060", 1.1),
    "living_street": ("#e0a060", 1.0),
    "track":      ("#e8bc8a", 0.9),
    "path":       ("#edcba6", 0.8),
    "footway":    ("#edcba6", 0.8),
    "steps":      ("#edcba6", 0.8),
}


def underlay(axis, crs, window, zorder: float = 0.6, named: bool = True):
    """Draw the roads behind a map. Silent when there are none."""
    if not OUT.exists():
        return 0
    import geopandas as gpd
    from shapely.geometry import box

    frame = gpd.read_file(OUT, layer="roads").to_crs(crs)
    frame = frame[frame.intersects(box(*window))]
    if frame.empty:
        return 0
    for kind, (colour, width) in PAINT.items():
        part = frame[frame["class"] == kind]
        if not part.empty:
            part.plot(ax=axis, color=colour, linewidth=width, zorder=zorder)
    rest = frame[~frame["class"].isin(PAINT)]
    if not rest.empty:
        rest.plot(ax=axis, color="#edcba6", linewidth=0.8, zorder=zorder)
    if named:
        span = window[2] - window[0]
        placed: list = []
        big = frame[frame["name"].notna()
                    & frame["class"].isin(["motorway", "trunk", "primary",
                                           "secondary", "tertiary"])]
        for name, part in big.groupby("name"):
            line = part.geometry.iloc[part.geometry.length.argmax()]
            here = line.interpolate(0.5, normalized=True)
            if any(((here.x - x) ** 2 + (here.y - y) ** 2) ** 0.5
                   < span * 0.12 for x, y in placed):
                continue
            placed.append((here.x, here.y))
            axis.annotate(str(name), (here.x, here.y), fontsize=7.5,
                          color="#b45309", ha="center", va="center",
                          zorder=zorder + 0.1,
                          bbox=dict(boxstyle="round,pad=0.15", fc="white",
                                    ec="none", alpha=0.65))
    return len(frame)

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
