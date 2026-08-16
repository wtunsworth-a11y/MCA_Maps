"""Draw the Copernicus DEM hillshade behind a matplotlib map.

The hillshade is stored in EPSG:4326, but the maps are drawn in whatever CRS
suits them — Web Mercator for tiled output, UTM 55S for anything measured. So
the raster is reprojected to the axes' CRS on the way in, and cached per CRS
because reprojecting a 2000×2400 raster for every map is otherwise the slowest
part of a run.

Everything here is best-effort. If the DEM has not been fetched, or rasterio is
missing, the map simply draws without terrain rather than failing.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HILLSHADE_PATH = REPO_ROOT / "data" / "reference" / "dem" / "mca_hillshade.tif"
DEM_PATH = REPO_ROOT / "data" / "reference" / "dem" / "mca_dem.tif"

_cache: dict = {}
_warned = False


def available() -> bool:
    return HILLSHADE_PATH.exists()


def _load(target_crs: str):
    """Reproject the hillshade into the target CRS, cached per CRS."""
    key = str(target_crs)
    if key in _cache:
        return _cache[key]

    import numpy as np
    import rasterio
    from rasterio.warp import calculate_default_transform, reproject, Resampling

    with rasterio.open(HILLSHADE_PATH) as handle:
        if str(handle.crs) == key:
            band = handle.read(1)
            bounds = handle.bounds
            _cache[key] = (band, (bounds.left, bounds.right,
                                  bounds.bottom, bounds.top))
            return _cache[key]

        transform, width, height = calculate_default_transform(
            handle.crs, target_crs, handle.width, handle.height,
            *handle.bounds)
        destination = np.zeros((height, width), dtype="uint8")
        reproject(source=rasterio.band(handle, 1), destination=destination,
                  src_transform=handle.transform, src_crs=handle.crs,
                  dst_transform=transform, dst_crs=target_crs,
                  resampling=Resampling.bilinear, dst_nodata=255)

        left, top = transform * (0, 0)
        right, bottom = transform * (width, height)
        _cache[key] = (destination, (left, right, bottom, top))
        return _cache[key]


def add_hillshade(axis, target_crs, alpha: float = 0.55) -> bool:
    """Draw the hillshade under everything already on the axes.

    Returns True if terrain was drawn. The axes limits are left untouched, so
    this can be called before or after the data is plotted.
    """
    global _warned
    if not available():
        if not _warned:
            print("  (no terrain: run scripts/fetch_dem.py)")
            _warned = True
        return False

    try:
        band, extent = _load(target_crs)
    except Exception as exc:
        if not _warned:
            print(f"  (no terrain: {type(exc).__name__})")
            _warned = True
        return False

    axis.imshow(band, cmap="gray", extent=extent, origin="upper",
                alpha=alpha, zorder=-10, interpolation="bilinear",
                vmin=0, vmax=255)
    return True
