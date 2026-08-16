#!/usr/bin/env python3
"""Fetch the Copernicus 30 m DEM covering the survey area.

The Copernicus GLO-30 DEM is published on AWS S3 as cloud-optimised GeoTIFF in
1° tiles, open data and needing no credentials. Because the tiles are COGs they
can be read with HTTP range requests, so only the window covering the data is
transferred rather than whole degrees.

Two products are written to data/reference/dem/:

* `mca_dem.tif`       — elevation in metres, cropped to the data extent
* `mca_hillshade.tif` — a shaded relief render of it, for use as a backdrop

Both are derived and git-ignored: re-run this script to rebuild them. Nothing
else in the pipeline requires them, so a run without network access still works
— the maps simply draw without terrain behind them.

Usage:
    python scripts/fetch_dem.py
    python scripts/fetch_dem.py --pad 0.05 --azimuth 315 --altitude 45
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataio  # noqa: E402

S3_BASE = "https://copernicus-dem-30m.s3.amazonaws.com"
DEM_DIR = dataio.REFERENCE_DIR / "dem"
DEM_PATH = DEM_DIR / "mca_dem.tif"
HILLSHADE_PATH = DEM_DIR / "mca_hillshade.tif"


def tile_name(lat: int, lon: int) -> str:
    """Copernicus tile id from the integer degree of its south-west corner."""
    ns = f"S{abs(lat):02d}" if lat < 0 else f"N{lat:02d}"
    ew = f"W{abs(lon):03d}" if lon < 0 else f"E{lon:03d}"
    return f"Copernicus_DSM_COG_10_{ns}_00_{ew}_00_DEM"


def tiles_for(bounds: tuple[float, float, float, float]) -> list[str]:
    minx, miny, maxx, maxy = bounds
    return [tile_name(lat, lon)
            for lat in range(math.floor(miny), math.ceil(maxy))
            for lon in range(math.floor(minx), math.ceil(maxx))]


def data_bounds(pad: float) -> tuple[float, float, float, float]:
    """The extent of the surveys and the MCA boundary together, padded."""
    import geopandas as gpd

    frames = []
    smoothed = dataio.SMOOTHED_DIR / "mca_tracks_smoothed.gpkg"
    if smoothed.exists():
        frames.append(gpd.read_file(smoothed, layer="tracks_smoothed"))
    if dataio.MCA_BOUNDARY.exists():
        frames.append(gpd.read_file(dataio.MCA_BOUNDARY))
    if not frames:
        raise SystemExit("Nothing to bound the DEM by — run smooth_tracks.py.")

    boxes = [frame.to_crs(dataio.WGS84).total_bounds for frame in frames]
    return (min(b[0] for b in boxes) - pad, min(b[1] for b in boxes) - pad,
            max(b[2] for b in boxes) + pad, max(b[3] for b in boxes) + pad)


def fetch(bounds: tuple[float, float, float, float]) -> Path:
    """Read the covering tiles' windows and merge them into one raster."""
    import rasterio
    from rasterio.merge import merge
    from rasterio.windows import from_bounds

    names = tiles_for(bounds)
    print(f"Covering tiles: {', '.join(names)}")

    datasets, profile = [], None
    for name in names:
        url = f"{S3_BASE}/{name}/{name}.tif"
        try:
            handle = rasterio.open(url)
        except Exception as exc:
            print(f"  ! {name}: unreachable ({type(exc).__name__})")
            continue

        window = from_bounds(*bounds, transform=handle.transform)
        window = window.intersection(
            rasterio.windows.Window(0, 0, handle.width, handle.height))
        if window.width < 1 or window.height < 1:
            handle.close()
            continue

        data = handle.read(1, window=window)
        transform = handle.window_transform(window)
        profile = handle.profile | {
            "height": data.shape[0], "width": data.shape[1],
            "transform": transform, "driver": "GTiff",
            "compress": "deflate", "predictor": 2, "tiled": True,
        }
        datasets.append((data, transform, profile))
        print(f"  read {name}: {data.shape[1]}×{data.shape[0]} px")
        handle.close()

    if not datasets:
        raise SystemExit("No DEM tiles could be read. Is the network reachable?")

    DEM_DIR.mkdir(parents=True, exist_ok=True)

    if len(datasets) == 1:
        data, transform, profile = datasets[0]
        with rasterio.open(DEM_PATH, "w", **profile) as out:
            out.write(data, 1)
    else:
        # Write each window out, then let rasterio merge handle the mosaic.
        parts = []
        for index, (data, transform, profile) in enumerate(datasets):
            part = DEM_DIR / f"_part{index}.tif"
            with rasterio.open(part, "w", **profile) as out:
                out.write(data, 1)
            parts.append(part)
        opened = [rasterio.open(p) for p in parts]
        mosaic, transform = merge(opened)
        profile = opened[0].profile | {
            "height": mosaic.shape[1], "width": mosaic.shape[2],
            "transform": transform, "compress": "deflate", "predictor": 2,
            "tiled": True,
        }
        with rasterio.open(DEM_PATH, "w", **profile) as out:
            out.write(mosaic[0], 1)
        for handle in opened:
            handle.close()
        for part in parts:
            part.unlink()

    return DEM_PATH


def hillshade(dem_path: Path, azimuth: float, altitude: float,
              exaggeration: float) -> Path:
    """Standard shaded relief, written as a single-band 8-bit raster."""
    import rasterio

    with rasterio.open(dem_path) as handle:
        elevation = handle.read(1).astype("float64")
        profile = handle.profile
        # Pixel size in metres: the DEM is in degrees, so convert using the
        # latitude at the raster's centre.
        centre_lat = handle.bounds.bottom + (handle.bounds.top
                                             - handle.bounds.bottom) / 2
        x_metres = abs(handle.transform.a) * 111_320 * math.cos(
            math.radians(centre_lat))
        y_metres = abs(handle.transform.e) * 110_540

    nodata = profile.get("nodata")
    if nodata is not None:
        elevation = np.where(elevation == nodata, np.nan, elevation)
    elevation = elevation * exaggeration

    dy, dx = np.gradient(elevation, y_metres, x_metres)
    slope = np.arctan(np.hypot(dx, dy))
    aspect = np.arctan2(-dx, dy)

    azimuth_rad = math.radians(360.0 - azimuth + 90.0)
    altitude_rad = math.radians(altitude)

    shaded = (np.sin(altitude_rad) * np.cos(slope)
              + np.cos(altitude_rad) * np.sin(slope)
              * np.cos(azimuth_rad - aspect))
    shaded = np.clip((shaded + 1) / 2 * 255, 0, 255)
    shaded = np.nan_to_num(shaded, nan=255).astype("uint8")

    profile.update(dtype="uint8", count=1, nodata=None, compress="deflate",
                   predictor=2, tiled=True)
    with rasterio.open(HILLSHADE_PATH, "w", **profile) as out:
        out.write(shaded, 1)
    return HILLSHADE_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pad", type=float, default=0.03,
                        help="degrees of margin around the data extent")
    parser.add_argument("--azimuth", type=float, default=315.0,
                        help="light direction for the hillshade")
    parser.add_argument("--altitude", type=float, default=45.0,
                        help="light elevation for the hillshade")
    parser.add_argument("--exaggeration", type=float, default=1.5,
                        help="vertical exaggeration for the hillshade")
    args = parser.parse_args(argv)

    bounds = data_bounds(args.pad)
    print("Extent: %.4f %.4f %.4f %.4f" % bounds)

    dem = fetch(bounds)
    size_mb = dem.stat().st_size / 1e6
    print(f"\nWrote {dem} ({size_mb:.1f} MB)")

    import rasterio
    with rasterio.open(dem) as handle:
        band = handle.read(1)
        valid = band[band != (handle.nodata if handle.nodata is not None else -9999)]
        print(f"  {handle.width}×{handle.height} px, {handle.crs}, "
              f"elevation {valid.min():.0f}–{valid.max():.0f} m")

    shade = hillshade(dem, args.azimuth, args.altitude, args.exaggeration)
    print(f"Wrote {shade} ({shade.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
