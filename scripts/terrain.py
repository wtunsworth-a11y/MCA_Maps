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


def add_hillshade(axis, target_crs, alpha: float = 0.55,
                  bounds=None) -> bool:
    """Draw the hillshade under everything already on the axes.

    Returns True if terrain was drawn. The axes limits are left untouched, so
    this can be called before or after the data is plotted.

    Pass `bounds` as `(minx, miny, maxx, maxy)` for a map covering one clan
    rather than the whole area. The raster is then cropped to that window
    before it is drawn. Matplotlib otherwise rasterises all six million pixels
    of the full DEM for a map showing a hundredth of it, which for a run of
    one map per clan is most of the wall clock.
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

    if bounds is not None:
        cropped = _crop(band, extent, bounds)
        if cropped is not None:
            band, extent = cropped

    axis.imshow(band, cmap="gray", extent=extent, origin="upper",
                alpha=alpha, zorder=-10, interpolation="bilinear",
                vmin=0, vmax=255)
    return True


def _crop(band, extent, bounds, margin: float = 0.10):
    """The window of the raster covering `bounds`, and its own extent."""
    left, right, bottom, top = extent
    minx, miny, maxx, maxy = bounds
    pad_x = max(maxx - minx, 1.0) * margin
    pad_y = max(maxy - miny, 1.0) * margin
    minx, maxx = minx - pad_x, maxx + pad_x
    miny, maxy = miny - pad_y, maxy + pad_y

    height, width = band.shape
    pixel_x = (right - left) / width
    pixel_y = (top - bottom) / height
    if pixel_x <= 0 or pixel_y <= 0:
        return None

    col0 = max(0, int((minx - left) / pixel_x))
    col1 = min(width, int((maxx - left) / pixel_x) + 1)
    row0 = max(0, int((top - maxy) / pixel_y))
    row1 = min(height, int((top - miny) / pixel_y) + 1)
    if col1 - col0 < 2 or row1 - row0 < 2:
        return None

    return (band[row0:row1, col0:col1],
            (left + col0 * pixel_x, left + col1 * pixel_x,
             top - row1 * pixel_y, top - row0 * pixel_y))
