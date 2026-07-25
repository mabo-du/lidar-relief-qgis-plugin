"""raster_utils.py — GDAL raster I/O utilities for LiDAR Relief plugin.
exports: DemData, read_dem_to_array(path, feedback) -> DemData,
         write_array_to_raster(array, path, geotransform, projection, nodata),
         get_cell_size(geotransform) -> float, apply_nodata_mask(input, output, nodata) -> ndarray,
         process_in_tiles(source, output, algorithm_func, halo_size, ...) -> None,
         check_dem_geometry(dataset, feedback) -> list[str],
         FALLBACK_NODATA
used_by: algorithms/hillshade_algorithm.py → read_dem_to_array, write_array_to_raster
         algorithms/slrm_algorithm.py → read_dem_to_array, write_array_to_raster
         algorithms/svf_algorithm.py → read_dem_to_array, write_array_to_raster
         algorithms/slope_algorithm.py → read_dem_to_array, write_array_to_raster
         algorithms/batch_algorithm.py → read_dem_to_array, write_array_to_raster
rules:
  All raster I/O MUST go through GDAL — never raw file operations.
  NoData values must be converted to np.nan before processing.
  Output arrays must have nodata re-applied before writing.
  Never write a float band containing NaN without tagging a nodata
  value — QGIS folds untagged NaN into layer statistics and the
  contrast stretch collapses. When the source has no nodata, fall back
  to FALLBACK_NODATA.
  No QGIS imports — only GDAL and NumPy. Feedback objects are duck-typed.
agent:   claude-opus-5 | anthropic | 2026-07-25 | s_20260725_001 |
         process_in_tiles wrote bare NaN with no nodata tag whenever the
         source DEM had no nodata value (common for LiDAR-derived
         GeoTIFFs); write_array_to_raster already had the -9999
         fallback, so the two writers disagreed. Added the same
         fallback plus check_dem_geometry(), which warns on geographic
         CRS and non-square pixels for every tiled algorithm at once.
         message: "nothing validated that the DEM is projected in
         metres even though the README requires it — a lat/lon DEM
         silently yields ~90 deg slope everywhere"
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional

import numpy as np
from osgeo import gdal

logger = logging.getLogger(__name__)

# Suppress GDAL printing errors to stderr; we handle them ourselves.

# Nodata written when the source raster declares none but the result
# still contains NaN (edges, masked cells, all-NaN neighbourhoods).
FALLBACK_NODATA = -9999.0

# Default concurrency for tiled processing. Small on purpose — see
# resolve_worker_count for the measurements behind this number.
DEFAULT_TILE_WORKERS = 2

# Warn when |pixel width| and |pixel height| differ by more than this
# fraction. get_cell_size() averages the two, so anisotropic pixels
# bias every distance-based algorithm (SVF, openness, slope).
PIXEL_ASPECT_TOLERANCE = 0.01


# Attribute used to remember which warnings a given feedback object has
# already seen. Batch Relief Visualisation calls process_in_tiles a dozen
# times per run, and repeating the same CRS warning twelve times buries
# the actual progress output.
_WARNED_ATTR = "_lidar_relief_seen_warnings"


def open_raster(source_path: str, access=gdal.GA_ReadOnly):
    """Open a raster, raising ValueError whichever GDAL error mode is active.

    GDAL has two error conventions and the plugin has to work under both.
    With the legacy mode ``gdal.Open`` returns ``None`` on failure; once
    ``gdal.UseExceptions()`` has been called — which QGIS does, and which
    is the default from GDAL 4 — it raises ``RuntimeError`` instead. Code
    that only checks ``if dataset is None`` therefore never reaches its
    own error message on a modern stack; the user gets a bare GDAL
    traceback rather than the hint about paths and permissions.

    Args:
        source_path: Raster path.
        access: ``gdal.GA_ReadOnly`` or ``gdal.GA_Update``.

    Returns:
        An open GDAL dataset.

    Raises:
        ValueError: If the raster cannot be opened, in either mode.
    """
    try:
        dataset = gdal.Open(source_path, access)
    except RuntimeError as exc:
        raise ValueError(f"Cannot open raster: {source_path} ({exc})") from exc
    if dataset is None:
        raise ValueError(f"Cannot open raster: {source_path}")
    return dataset


def _push_warning(feedback, message: str) -> None:
    """Send a warning to a QGIS feedback object, whatever vintage it is.

    ``QgsProcessingFeedback.pushWarning`` only exists from QGIS 3.16, and
    tests pass in lightweight stubs. Degrade to ``pushInfo`` and then to
    silence rather than breaking a run over a diagnostic message.

    Repeats are suppressed per feedback object. QGIS feedback objects are
    SIP-wrapped C++ objects that may reject attribute assignment; when
    that happens the message is still delivered, just not deduplicated.
    """
    if feedback is None:
        return

    try:
        seen = getattr(feedback, _WARNED_ATTR, None)
        if seen is None:
            seen = set()
            setattr(feedback, _WARNED_ATTR, seen)
        if message in seen:
            return
        seen.add(message)
    except (AttributeError, TypeError):
        # Not settable — deliver every time rather than staying silent.
        pass

    for method_name in ("pushWarning", "pushInfo", "setProgressText"):
        method = getattr(feedback, method_name, None)
        if callable(method):
            method(message)
            return


def check_dem_geometry(dataset, feedback=None) -> list:
    """Warn about DEM geometry that will silently corrupt results.

    Two conditions matter for every distance-based relief algorithm:

    1. **Geographic CRS.** Cell size then comes out in degrees, so a
       10 m DEM reports a cell size around 0.0001. Slope saturates near
       90 deg, and SVF/openness search radii cover centimetres instead
       of metres. The output looks plausible but is meaningless.
    2. **Non-square pixels.** :func:`get_cell_size` averages the X and Y
       pixel sizes, so anisotropic rasters bias every horizon distance.

    Neither condition is fatal, so this reports rather than raises — the
    user may be deliberately experimenting. Returns the warnings so
    callers (and tests) can assert on them.

    Args:
        dataset: An open GDAL dataset.
        feedback: Optional QGIS feedback object.

    Returns:
        List of warning strings (empty when the DEM looks sound).
    """
    warnings = []

    projection = dataset.GetProjection()
    if projection:
        try:
            from osgeo import osr

            srs = osr.SpatialReference()
            if srs.ImportFromWkt(projection) == 0 and srs.IsGeographic():
                warnings.append(
                    "Input DEM uses a geographic CRS "
                    f"({srs.GetAttrValue('GEOGCS') or 'lat/lon'}), so its cell "
                    "size is measured in degrees, not metres. Distance-based "
                    "results (slope, SVF, openness, local dominance, search "
                    "radii) will be numerically meaningless. Reproject the DEM "
                    "to a projected CRS in metres (Raster > Projections > Warp) "
                    "before running this algorithm."
                )
        except Exception as exc:  # pragma: no cover — osr ships with gdal
            # A CRS we cannot interpret is not a reason to abort the run;
            # the geometry check is advisory. Log it rather than swallowing
            # it silently, so an unreadable projection is still traceable.
            logger.debug("Could not inspect CRS for geographic check: %s", exc)
    else:
        warnings.append(
            "Input DEM has no coordinate reference system. Results cannot be "
            "aligned with other data — assign a projected CRS in metres first."
        )

    geotransform = dataset.GetGeoTransform()
    pixel_width = abs(geotransform[1])
    pixel_height = abs(geotransform[5])
    if pixel_width > 0 and pixel_height > 0:
        aspect = abs(pixel_width - pixel_height) / max(pixel_width, pixel_height)
        if aspect > PIXEL_ASPECT_TOLERANCE:
            warnings.append(
                f"Input DEM has non-square pixels ({pixel_width:g} x "
                f"{pixel_height:g} map units). This plugin uses a single "
                f"averaged cell size ({(pixel_width + pixel_height) / 2.0:g}), "
                "which biases every distance-based result. Resample to square "
                "pixels for accurate output."
            )

    for message in warnings:
        _push_warning(feedback, message)
    return warnings


@dataclass
class DemData:
    """Container for DEM raster data and metadata.

    Rules:
        array is always float32 with nodata pixels set to np.nan.
        nodata_mask is a boolean array: True where original data was nodata.
    """

    array: np.ndarray
    nodata: Optional[float]
    nodata_mask: np.ndarray
    geotransform: tuple
    projection: str
    x_size: int
    y_size: int


def read_dem_to_array(source_path: str, feedback=None) -> DemData:
    """Read a DEM raster file into a NumPy float32 array via GDAL.

    Args:
        source_path: File path to the raster dataset.
        feedback: Optional QGIS feedback object for progress reporting.

    Returns:
        DemData with elevation values as float32, nodata pixels as np.nan.

    Raises:
        ValueError: If the raster cannot be opened or has no bands.

    Rules:
        Always reads band 1 only.
        Always casts to float32 for consistent arithmetic.
        Nodata values are replaced with np.nan for safe neighbourhood operations.
    """
    dataset = open_raster(source_path)

    band = dataset.GetRasterBand(1)
    if band is None:
        raise ValueError(f"Raster has no bands: {source_path}")

    nodata = band.GetNoDataValue()
    geotransform = dataset.GetGeoTransform()
    projection = dataset.GetProjection()
    x_size = dataset.RasterXSize
    y_size = dataset.RasterYSize

    if feedback:
        feedback.setProgressText("Reading DEM raster...")

    array = band.ReadAsArray().astype(np.float32)

    # Build nodata mask and replace with NaN
    if nodata is not None:
        nodata_mask = np.isclose(array, nodata, atol=1e-5, rtol=0.0) | np.isnan(array)
    else:
        nodata_mask = np.isnan(array)

    array[nodata_mask] = np.nan

    # Clean up GDAL objects
    band = None
    dataset = None

    return DemData(
        array=array,
        nodata=nodata,
        nodata_mask=nodata_mask,
        geotransform=geotransform,
        projection=projection,
        x_size=x_size,
        y_size=y_size,
    )


def write_array_to_raster(
    array: np.ndarray,
    output_path: str,
    geotransform: tuple,
    projection: str,
    nodata: Optional[float] = None,
) -> None:
    """Write a NumPy array to a GeoTIFF file via GDAL.

    Args:
        array: 2D NumPy array to write.
        output_path: Output file path (.tif).
        geotransform: GDAL geotransform tuple (6 elements).
        projection: WKT projection string.
        nodata: NoData value to set on the output band.

    Rules:
        Always writes as GeoTIFF with LZW compression.
        np.nan values in the array are written as the nodata value.
        FlushCache is called to ensure complete disk write.
    """
    if array.ndim == 3:
        y_size, x_size, bands = array.shape
    else:
        y_size, x_size = array.shape
        bands = 1

    # Determine output data type
    if array.dtype == np.uint8:
        gdal_dtype = gdal.GDT_Byte
    else:
        gdal_dtype = gdal.GDT_Float32

    driver = gdal.GetDriverByName("GTiff")

    creation_options = ["COMPRESS=LZW", "TILED=YES"]
    if bands == 3:
        creation_options.append("PHOTOMETRIC=RGB")

    out_dataset = driver.Create(
        output_path,
        x_size,
        y_size,
        bands,
        gdal_dtype,
        options=creation_options,
    )
    if out_dataset is None:
        raise ValueError(
            f"Failed to create output raster via GDAL: {output_path}. "
            "Please check disk space, write permissions, or folder existence."
        )

    out_dataset.SetGeoTransform(geotransform)
    out_dataset.SetProjection(projection)

    out_band = None
    if bands == 1:
        out_band = out_dataset.GetRasterBand(1)

        # Replace NaN with nodata value before writing
        write_array = array.copy()
        if nodata is not None:
            nan_mask = np.isnan(write_array)
            write_array[nan_mask] = nodata
            out_band.SetNoDataValue(float(nodata))
        elif np.any(np.isnan(write_array)):
            # If no nodata was specified but we have NaN, use -9999
            nan_mask = np.isnan(write_array)
            write_array[nan_mask] = -9999.0
            out_band.SetNoDataValue(-9999.0)

        out_band.WriteArray(write_array)
    else:
        for b in range(bands):
            out_band = out_dataset.GetRasterBand(b + 1)
            write_array = array[:, :, b].copy()

            # RGB images don't typically use nodata in the same way,
            # but if it's not uint8 we should handle NaN
            if array.dtype != np.uint8:
                if nodata is not None:
                    nan_mask = np.isnan(write_array)
                    write_array[nan_mask] = nodata
                    out_band.SetNoDataValue(float(nodata))
            elif nodata is not None:
                # For uint8, if nodata is provided, just set it
                out_band.SetNoDataValue(float(nodata))

            out_band.WriteArray(write_array)

    out_dataset.FlushCache()

    # Clean up
    out_band = None
    out_dataset = None


def get_cell_size(geotransform: tuple) -> float:
    """Extract the pixel size (cell size) from a GDAL geotransform.

    Args:
        geotransform: GDAL geotransform tuple (originX, pixelW, rot, originY, rot, pixelH).

    Returns:
        Cell size in map units (average of |pixelW| and |pixelH|).

    Rules:
        Returns absolute value — cell size is always positive.
        Averages X and Y pixel sizes for non-square pixels.
    """
    pixel_width = abs(geotransform[1])
    pixel_height = abs(geotransform[5])
    return (pixel_width + pixel_height) / 2.0


def get_cell_size_from_path(source_path: str) -> float:
    """Open a raster just far enough to read its cell size.

    The Processing wrappers need the cell size *before* they start work,
    so they can convert a radius given in metres into pixels and size the
    tile halo accordingly. Going through GDAL rather than
    ``QgsRasterLayer.rasterUnitsPerPixelX()`` keeps this testable without
    a QGIS instance.

    Args:
        source_path: Path to a raster GDAL can open.

    Returns:
        Cell size in map units (mean of |pixel width| and |pixel height|).

    Raises:
        ValueError: If the raster cannot be opened.
    """
    dataset = open_raster(source_path)
    try:
        return get_cell_size(dataset.GetGeoTransform())
    finally:
        dataset = None


def read_dem_downsampled(source_path: str, max_dimension: int = 800):
    """Read a DEM at reduced resolution for preview work.

    GDAL does the decimation during the read, so a 20 000 x 20 000 tile
    never lands in memory at full size.

    Args:
        source_path: Raster path.
        max_dimension: Longest output side in pixels.

    Returns:
        ``(array, effective_cellsize)`` — float32 with nodata as NaN, and
        the cell size of the DOWNSAMPLED grid, which is what any
        distance-based algorithm run on it must use.

    Raises:
        ValueError: If the raster cannot be opened.

    Rules:
        Returning the scaled cell size is the whole point. Running a
        10 px search radius on a decimated grid with the ORIGINAL cell
        size would silently misreport every distance.
    """
    dataset = open_raster(source_path)

    try:
        x_size = dataset.RasterXSize
        y_size = dataset.RasterYSize
        band = dataset.GetRasterBand(1)
        nodata = band.GetNoDataValue()
        cellsize = get_cell_size(dataset.GetGeoTransform())

        scale = max(1.0, max(x_size, y_size) / float(max_dimension))
        out_x = max(1, int(round(x_size / scale)))
        out_y = max(1, int(round(y_size / scale)))

        array = band.ReadAsArray(
            0, 0, x_size, y_size, buf_xsize=out_x, buf_ysize=out_y
        ).astype(np.float32)

        if nodata is not None:
            mask = np.isclose(array, nodata, atol=1e-5, rtol=0.0) | np.isnan(array)
        else:
            mask = np.isnan(array)
        array[mask] = np.nan

        # The decimated grid covers the same ground with fewer cells.
        effective_cellsize = cellsize * (x_size / out_x)
        return array, effective_cellsize
    finally:
        dataset = None


def apply_nodata_mask(
    input_array: np.ndarray,
    output_array: np.ndarray,
    nodata_mask: np.ndarray,
) -> np.ndarray:
    """Propagate nodata from input to output array.

    Args:
        input_array: Original DEM array (used for reference only).
        output_array: Computed result array.
        nodata_mask: Boolean mask — True where input was nodata.

    Returns:
        Output array with nodata pixels set to np.nan.

    Rules:
        Nodata propagation must happen AFTER algorithm computation.
        Original nodata pixels must always remain nodata in output.
    """
    result = output_array.copy()
    result[nodata_mask] = np.nan
    return result


def resolve_worker_count(max_workers: Optional[int] = None) -> int:
    """Decide how many tiles to compute concurrently.

    Args:
        max_workers: Explicit worker count. ``None`` picks the default,
            ``1`` forces the serial path, ``0`` or negative also mean 1.

    Returns:
        Worker count, at least 1.

    Rules:
        The default is deliberately small, and NOT derived from the core
        count. Tiled relief work is MEMORY-BANDWIDTH bound, not CPU
        bound — the horizon scan streams a 16 MB array hundreds of times
        per tile, so extra cores just wait on RAM.

        Measured on a 16-core machine (speedup vs serial):

            2048px tiles, 8 tiles   2w 1.5x   4w 1.7x   8w 1.7x
            3000x3000 DEM, 1024px   2w 1.44x  4w 1.33x  8w 1.16x

        Note the second row gets WORSE past two workers. Processes were
        measured too and behaved the same as threads, confirming the
        ceiling is the memory bus rather than the GIL. Two workers
        captures most of the available gain on both shapes while keeping
        peak memory at two haloed tiles; more is a gamble that can lose.
    """
    if max_workers is not None:
        return max(1, int(max_workers))
    cpu_count = os.cpu_count() or 1
    return max(1, min(DEFAULT_TILE_WORKERS, cpu_count))


def _tile_windows(x_size: int, y_size: int, tile_size: int):
    """Yield ``(x, y, win_x_size, win_y_size)`` for every interior tile."""
    for y in range(0, y_size, tile_size):
        for x in range(0, x_size, tile_size):
            yield x, y, min(tile_size, x_size - x), min(tile_size, y_size - y)


def _read_tile(band, window, halo_size, x_size, y_size, nodata):
    """Read one haloed block and return it with its nodata mask and crop box.

    Returns:
        ``(block, block_nodata_mask, crop)`` where ``crop`` is
        ``(top, bottom, left, right)`` locating the interior inside the
        haloed block.

    Rules:
        GDAL band objects are NOT thread-safe. This must only be called
        from the thread that owns the dataset.
    """
    x, y, win_x_size, win_y_size = window

    read_x = max(0, x - halo_size)
    read_y = max(0, y - halo_size)
    read_x_size = min(x_size - read_x, win_x_size + (x - read_x) + halo_size)
    read_y_size = min(y_size - read_y, win_y_size + (y - read_y) + halo_size)

    block = band.ReadAsArray(read_x, read_y, read_x_size, read_y_size).astype(
        np.float32
    )

    if nodata is not None:
        block_nodata_mask = np.isclose(block, nodata, atol=1e-5, rtol=0.0) | np.isnan(
            block
        )
    else:
        block_nodata_mask = np.isnan(block)

    block[block_nodata_mask] = np.nan

    crop_top = y - read_y
    crop_left = x - read_x
    crop = (crop_top, crop_top + win_y_size, crop_left, crop_left + win_x_size)

    return block, block_nodata_mask, crop


def _finish_tile(
    result_block, block_nodata_mask, crop, out_bands, gdal_dtype, output_nodata
):
    """Crop the halo off a computed block and re-apply nodata.

    Pure array work — safe to call from a worker thread.
    """
    crop_top, crop_bottom, crop_left, crop_right = crop

    if result_block.ndim == 3:
        interior = result_block[crop_top:crop_bottom, crop_left:crop_right, :]
    else:
        interior = result_block[crop_top:crop_bottom, crop_left:crop_right]

    interior_nodata_mask = block_nodata_mask[crop_top:crop_bottom, crop_left:crop_right]
    if interior.ndim == 3:
        for b in range(out_bands):
            band_slice = interior[:, :, b]
            band_slice[interior_nodata_mask] = (
                0 if gdal_dtype == gdal.GDT_Byte else np.nan
            )
    else:
        interior[interior_nodata_mask] = 0 if gdal_dtype == gdal.GDT_Byte else np.nan

    if output_nodata is not None:
        interior[np.isnan(interior)] = output_nodata

    return interior


def _delete_partial_output(output_path: str) -> None:
    """Remove a half-written raster after cancellation."""
    if not os.path.exists(output_path):
        return
    try:
        gdal.GetDriverByName("GTiff").Delete(output_path)
    except Exception:
        try:
            os.remove(output_path)
        except OSError:
            pass


def process_in_tiles(
    source_path: str,
    output_path: str,
    algorithm_func,
    halo_size: int,
    tile_size: int = 2048,
    feedback=None,
    max_workers: Optional[int] = None,
    **kwargs,
) -> None:
    """Process a large DEM in tiles to conserve memory.

    Args:
        source_path: Input DEM path.
        output_path: Output raster path.
        algorithm_func: Callable algorithm (e.g. sky_view_factor).
        halo_size: Margin around each tile in pixels to prevent edge effects.
        tile_size: Processing block size (interior pixels).
        feedback: QGIS feedback object for progress and cancellation.
        max_workers: Tiles to compute concurrently. ``None`` uses
            :func:`resolve_worker_count`; ``1`` forces the serial path.
        **kwargs: Extra arguments passed to algorithm_func.

    Rules:
        Reads blocks of (tile_size + 2*halo_size).
        Writes interior blocks of (tile_size).
        Respects dataset boundaries.
        The output band always carries a nodata value for float output —
        FALLBACK_NODATA when the source declares none.
        ALL GDAL I/O happens on the calling thread. Only algorithm_func
        and the array cropping run in workers, because neither GDAL
        datasets nor bands are thread-safe. Tiles are handled in batches
        of `workers` so peak memory stays bounded and cancellation has a
        natural checkpoint between batches.
        Threads, not processes: several callers pass locally-defined
        closures (slrm_wrapper, asvf_wrapper, the batch wrappers) which
        cannot be pickled, and measurement showed processes gave no more
        speedup than threads on this memory-bound workload anyway.
    """
    dataset = open_raster(source_path)

    band = dataset.GetRasterBand(1)
    nodata = band.GetNoDataValue()
    x_size = dataset.RasterXSize
    y_size = dataset.RasterYSize
    geotransform = dataset.GetGeoTransform()
    cellsize = get_cell_size(geotransform)

    # Surface CRS/pixel-geometry problems before spending minutes on a
    # result the user cannot trust.
    check_dem_geometry(dataset, feedback)

    # First, test the algorithm on a small 1x1 block to get output dtype and bands
    test_out = algorithm_func(np.zeros((3, 3), dtype=np.float32), cellsize, **kwargs)
    if test_out.ndim == 3:
        out_bands = test_out.shape[2]
    else:
        out_bands = 1

    if test_out.dtype == np.uint8:
        gdal_dtype = gdal.GDT_Byte
    else:
        gdal_dtype = gdal.GDT_Float32

    driver = gdal.GetDriverByName("GTiff")
    creation_options = ["COMPRESS=LZW", "TILED=YES"]
    if out_bands == 3:
        creation_options.append("PHOTOMETRIC=RGB")

    out_dataset = driver.Create(
        output_path, x_size, y_size, out_bands, gdal_dtype, options=creation_options
    )
    if out_dataset is None:
        raise ValueError(
            f"Failed to create output raster via GDAL process_in_tiles: {output_path}. "
            "Please check disk space, write permissions, or folder existence."
        )
    out_dataset.SetGeoTransform(geotransform)
    out_dataset.SetProjection(dataset.GetProjection())

    # Float outputs must always declare a nodata value. Algorithms emit
    # NaN at masked cells regardless of whether the SOURCE had a nodata
    # tag; writing those NaNs into an untagged band leaves QGIS to fold
    # them into layer statistics, which flattens the contrast stretch.
    output_nodata = None
    if gdal_dtype != gdal.GDT_Byte:
        output_nodata = float(nodata) if nodata is not None else FALLBACK_NODATA
        for b in range(out_bands):
            out_dataset.GetRasterBand(b + 1).SetNoDataValue(output_nodata)

    windows = list(_tile_windows(x_size, y_size, tile_size))
    total_tiles = len(windows)
    tiles_done = 0
    workers = resolve_worker_count(max_workers)

    def compute(window):
        """Read is done by the caller; this part is thread-safe."""
        block, block_nodata_mask, crop = window[1]
        result_block = algorithm_func(block, cellsize, **kwargs)
        return _finish_tile(
            result_block,
            block_nodata_mask,
            crop,
            out_bands,
            gdal_dtype,
            output_nodata,
        )

    def write(window, interior):
        x, y = window[0][0], window[0][1]
        if out_bands == 1:
            out_dataset.GetRasterBand(1).WriteArray(interior, x, y)
        else:
            for b in range(out_bands):
                out_dataset.GetRasterBand(b + 1).WriteArray(interior[:, :, b], x, y)

    def cancel():
        nonlocal band, out_dataset, dataset
        band = None
        out_dataset = None
        dataset = None
        _delete_partial_output(output_path)

    # Tiles are handled in batches of `workers`. Reads and writes stay on
    # this thread (GDAL is not thread-safe); only the algorithm runs
    # concurrently. Batching bounds peak memory to `workers` haloed
    # blocks and gives cancellation a checkpoint between batches.
    executor = ThreadPoolExecutor(max_workers=workers) if workers > 1 else None
    try:
        for batch_start in range(0, total_tiles, workers):
            if feedback and feedback.isCanceled():
                cancel()
                return

            batch = windows[batch_start : batch_start + workers]  # noqa: E203

            # Read this batch serially.
            prepared = []
            for window in batch:
                prepared.append(
                    (
                        window,
                        _read_tile(band, window, halo_size, x_size, y_size, nodata),
                    )
                )

            # Compute concurrently (or inline when workers == 1).
            if executor is None:
                interiors = [compute(item) for item in prepared]
            else:
                interiors = list(executor.map(compute, prepared))

            # Write serially, in tile order.
            for (window, _read), interior in zip(prepared, interiors):
                write((window, _read), interior)

            tiles_done += len(batch)
            if feedback:
                feedback.setProgress(int(100 * tiles_done / total_tiles))
    finally:
        if executor is not None:
            executor.shutdown(wait=True)

    if out_dataset is not None:
        out_dataset.FlushCache()
    out_dataset = None
    dataset = None
