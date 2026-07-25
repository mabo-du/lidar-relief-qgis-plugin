"""dem_difference.py — Multi-temporal DEM change detection with probabilistic DoD.

exports: compute_dod(dem_old_path, dem_new_path, **kwargs) -> dict
         compute_dod_xarray(dem_old, dem_new, **kwargs) -> dict
         load_dem(path) -> xr.DataArray

used_by: algorithms/temporal_difference_algorithm.py

rules:
  Uses xarray + rioxarray for labeled array operations.
  Probabilistic Level of Detection (LoD) masks noise using propagated RMSE.
  All dependencies are optional — check availability before calling.
  Use rio.write_crs(..., inplace=True) to stamp a CRS. rio.set_crs() is
  deprecated AND returns a copy, so its result is silently discarded.
agent:   claude-opus-5 | anthropic | 2026-07-25 | s_20260725_001 |
         Replaced the dead ["crs","transform"] loop (loop variable was
         never used; set_crs called twice, result discarded both times)
         with write_crs(inplace=True). Clears the FutureWarning the
         test suite was emitting and survives set_crs removal.
"""

import logging
import os

import numpy as np

logger = logging.getLogger(__name__)

try:
    import xarray as xr
    import rioxarray

    _XARRAY_AVAILABLE = True
except ImportError:
    _XARRAY_AVAILABLE = False


def xarray_available() -> bool:
    """Check if xarray and rioxarray are installed."""
    return _XARRAY_AVAILABLE


def check_dependencies() -> None:
    """Raise ImportError with clear instructions if xarray missing."""
    if not _XARRAY_AVAILABLE:
        raise ImportError(
            "Multi-temporal change detection requires 'xarray' and "
            "'rioxarray'.\n\n"
            "Install them via the OSGeo4W Shell:\n"
            "  pip install xarray rioxarray\n"
        )


def load_dem(path: str, band: int = 1) -> "xr.DataArray":
    """Load a DEM raster into an xarray DataArray with spatial coordinates.

    Args:
        path: Path to the DEM GeoTIFF.
        band: Raster band to load (default 1).

    Returns:
        xarray DataArray with 'x' and 'y' coordinate dims and CRS metadata.

    Raises:
        RuntimeError: If the file cannot be opened.
    """
    check_dependencies()

    try:
        da = rioxarray.open_rasterio(path, band_as_variable=False)
    except Exception as e:
        raise RuntimeError(f"Cannot open DEM: {path}: {e}") from e

    # Select band and squeeze if single-band
    if da.sizes.get("band", 0) > 1:
        da = da.isel(band=band - 1)

    # Remove band dim if present
    if "band" in da.dims:
        da = da.squeeze("band")

    da.name = os.path.splitext(os.path.basename(path))[0]
    return da


def _resolve_resampling(method):
    """Convert a string resampling method name to a rasterio.enums.Resampling.

    Older rioxarray versions accept string names directly; newer versions
    require the enum value. This helper handles both by always returning
    the enum value.
    """
    from rasterio.enums import Resampling

    if hasattr(method, "name"):
        # Already a Resampling enum value
        return method
    resampling_map = {
        "nearest": Resampling.nearest,
        "bilinear": Resampling.bilinear,
        "cubic": Resampling.cubic,
        "cubic_spline": Resampling.cubic_spline,
        "lanczos": Resampling.lanczos,
        "average": Resampling.average,
        "mode": Resampling.mode,
        "max": Resampling.max,
        "min": Resampling.min,
        "med": Resampling.med,
        "q1": Resampling.q1,
        "q3": Resampling.q3,
        "sum": Resampling.sum,
        "rms": Resampling.rms,
    }
    result = resampling_map.get(method)
    if result is None:
        raise ValueError(
            f"Unknown resampling method '{method}'. "
            f"Valid options: {list(resampling_map.keys())}"
        )
    return result


def compute_dod(
    dem_old_path: str,
    dem_new_path: str,
    output_dir: str,
    rmse_old: float = 0.15,
    rmse_new: float = 0.15,
    confidence_level: float = 1.96,
    align_method: str = "bilinear",
    project_name: str = "change_detection",
) -> dict:
    """Compute a probabilistic DEM of Difference (DoD) between two DEMs.

    Args:
        dem_old_path: Path to the older DEM (GeoTIFF).
        dem_new_path: Path to the newer DEM (GeoTIFF).
        output_dir: Directory for output rasters.
        rmse_old: Vertical RMSE of the older DEM (metres).
        rmse_new: Vertical RMSE of the newer DEM (metres).
        confidence_level: Z-score for significance threshold
            (1.96 = 95% confidence, 2.58 = 99% confidence).
        align_method: Resampling method for alignment
            ('bilinear', 'cubic', 'nearest').
        project_name: Prefix for output filenames.

    Returns:
        dict with paths to output rasters and summary statistics.
    """
    check_dependencies()
    os.makedirs(output_dir, exist_ok=True)

    # Load DEMs
    dem_old = load_dem(dem_old_path)
    dem_new = load_dem(dem_new_path)

    return compute_dod_xarray(
        dem_old=dem_old,
        dem_new=dem_new,
        output_dir=output_dir,
        rmse_old=rmse_old,
        rmse_new=rmse_new,
        confidence_level=confidence_level,
        align_method=align_method,
        project_name=project_name,
    )


def compute_dod_xarray(
    dem_old: "xr.DataArray",
    dem_new: "xr.DataArray",
    output_dir: str,
    rmse_old: float = 0.15,
    rmse_new: float = 0.15,
    confidence_level: float = 1.96,
    align_method: str = "bilinear",
    project_name: str = "change_detection",
) -> dict:
    """Compute probabilistic DEM of Difference from xarray DataArrays.

    The DoD methodology:
        1. Align new DEM to old DEM grid (reproject if needed)
        2. DoD = DEM_new - DEM_old
        3. Propagated error: sigma = sqrt(RMSE_old² + RMSE_new²)
        4. LoD threshold: |DoD| > confidence_level × sigma
        5. Output: DoD raster + significance mask + volume report

    Args:
        dem_old: xarray DataArray of the older DEM.
        dem_new: xarray DataArray of the newer DEM.
        output_dir: Directory for output rasters.
        rmse_old: Vertical RMSE of older DEM.
        rmse_new: Vertical RMSE of newer DEM.
        confidence_level: Z-score for significance.
        align_method: Resampling method.
        project_name: Prefix for output filenames.

    Returns:
        dict with:
            - 'dod_path': path to the signed DoD raster
            - 'mask_path': path to the significance mask (byte)
            - 'volume_report': dict of cut/fill volumes
            - 'propagated_error': propagated RMSE
            - 'threshold': LoD threshold used
            - 'significant_pixels': count of significant changes
            - 'total_pixels': total valid pixels
    """
    check_dependencies()

    import rioxarray  # noqa: F401 — registers .rio accessor on xarray objects

    # Align new DEM to old DEM grid
    # Step 1: reproject CRS if needed (reproject_match only aligns
    #         grid/extent/resolution — it does NOT reproject between CRSes)
    if dem_old.rio.crs != dem_new.rio.crs:
        logger.info(
            "CRS mismatch: %s → %s. Step 1: reprojecting CRS...",
            dem_new.rio.crs,
            dem_old.rio.crs,
        )
        dem_new = dem_new.rio.reproject(dem_old.rio.crs)

    # Step 2: align grid extent and resolution.
    # Convert string method name to Resampling enum (older rioxarray
    # accepted strings, newer versions require the enum).
    resolved_method = _resolve_resampling(align_method)
    logger.info("Aligning grid extent and resolution...")
    dem_new_aligned = dem_new.rio.reproject_match(dem_old, resampling=resolved_method)

    # Fill nodata with NaN for safe arithmetic
    dem_old_filled = dem_old.copy()
    dem_new_filled = dem_new_aligned.copy()

    if hasattr(dem_old_filled, "rio") and dem_old_filled.rio.nodata is not None:
        dem_old_filled = dem_old_filled.where(
            dem_old_filled != dem_old_filled.rio.nodata
        )
    if hasattr(dem_new_filled, "rio") and dem_new_filled.rio.nodata is not None:
        dem_new_filled = dem_new_filled.where(
            dem_new_filled != dem_new_filled.rio.nodata
        )

    # Compute DoD
    dod = dem_new_filled - dem_old_filled

    # Propagated error
    propagated_error = np.sqrt(rmse_old**2 + rmse_new**2)
    threshold = confidence_level * propagated_error

    # Significance mask
    # 0 = no significant change, 1 = negative change (erosion/cut),
    # 2 = positive change (deposition/fill),
    # 255 = nodata (NaN DoD — where either input DEM had nodata).
    #
    # NOTE: The previous implementation used nodata=0 on the mask raster,
    # which collided with the 'no significant change' sentinel value.
    # Downstream tools treated all stable terrain as missing data. We
    # now use 255 as the nodata sentinel and ensure NaN cells get 255
    # rather than being silently classified as 'no change'.
    #
    # Use uint8 (not int8) because 255 is out of range for signed int8.
    # Older numpy versions silently wrapped 255 to -1; numpy 1.24+
    # emits a DeprecationWarning and numpy 2.0+ will raise.
    nan_mask = np.isnan(dod)
    mask = xr.where(nan_mask, np.uint8(255), np.uint8(0))
    mask = xr.where(dod < -threshold, np.uint8(1), mask)
    mask = xr.where(dod > threshold, np.uint8(2), mask)

    # Statistics — exclude NaN cells from the denominator.
    valid_mask = ~nan_mask
    total_pixels = int(valid_mask.sum().values)
    significant = int(((mask > 0) & (mask < 255)).sum().values)
    neg_changes = int((mask == 1).sum().values)
    pos_changes = int((mask == 2).sum().values)

    # Volume estimates (metres³ assuming CRS units are metres)
    # Cell area from geotransform
    if hasattr(dod, "rio"):
        transform = dod.rio.transform()
        # Handle both affine.Affine objects and standard GDAL 6-element tuples
        if hasattr(transform, "a") and hasattr(transform, "e"):
            cell_area = abs(transform.a * transform.e)
        elif len(transform) >= 6:
            # GDAL transform: (origin_x, pixel_width, rotation_x, origin_y, rotation_y, pixel_height)
            cell_area = abs(transform[1] * transform[5])
        else:
            cell_area = abs(transform[0] * transform[4])
    else:
        cell_area = 1.0

    # Cut volume (negative change) and fill volume (positive change).
    # Only sum cells that exceed the LoD threshold — the previous code
    # included sub-threshold noise in the volume totals, which made the
    # 'probabilistic' mask meaningless for volumetric reporting.
    dod_valid = dod.where(~np.isnan(dod), 0)
    # Apply the significance mask: only count significant changes.
    sig_neg = dod_valid.where(mask == 1, 0)
    sig_pos = dod_valid.where(mask == 2, 0)
    cut_volume = float(abs(sig_neg).sum().values * cell_area)
    fill_volume = float(sig_pos.sum().values * cell_area)
    net_volume = fill_volume - cut_volume

    # Write outputs
    dod_path = os.path.join(output_dir, f"{project_name}_dod.tif")
    mask_path = os.path.join(output_dir, f"{project_name}_mask.tif")

    # Set CRS and nodata for export
    dod_out = dod.copy()
    mask_out = mask.copy()

    # Stamp the source CRS onto both outputs.
    #
    # The previous version looped over ["crs", "transform"] without ever
    # using the loop variable — so it just called set_crs twice — and
    # `rio.set_crs()` returns a NEW object by default, meaning the result
    # was discarded either way. It also emits a FutureWarning and is
    # slated for removal from rioxarray. `write_crs(inplace=True)` is the
    # supported API and actually mutates the object we go on to write.
    for name, data_array in (("DoD", dod_out), ("mask", mask_out)):
        if not hasattr(data_array, "rio"):
            continue
        try:
            data_array.rio.write_crs(dem_old.rio.crs, inplace=True)
        except Exception as e:
            logger.warning("Failed to set CRS on %s output: %s", name, e)

    # Write using rioxarray
    try:
        dod_out.rio.to_raster(
            dod_path, dtype="float32", nodata=np.nan, compress="LZW", tiled=True
        )
        # Use uint8 (not int8) so 255 fits — int8 range is -128..127.
        # Use nodata=255 (not 0) so the 'no change' sentinel (0) is
        # preserved as a real value rather than treated as missing.
        mask_out.rio.to_raster(
            mask_path, dtype="uint8", nodata=255, compress="LZW", tiled=True
        )
    except Exception as e:
        logger.warning("rioxarray write failed, trying GDAL: %s", e)
        # Fallback: write via GDAL
        _write_array_via_gdal(dod, dod_path, "float32", dem_old)
        _write_array_via_gdal(
            mask.astype(np.uint8), mask_path, "uint8", dem_old, nodata=255
        )

    volume_report = {
        "cut_volume_m3": round(cut_volume, 1),
        "fill_volume_m3": round(fill_volume, 1),
        "net_volume_m3": round(net_volume, 1),
        "cell_area_m2": round(cell_area, 4),
        "propagated_error_m": round(propagated_error, 4),
        "lod_threshold_m": round(threshold, 4),
    }

    return {
        "dod_path": dod_path,
        "mask_path": mask_path,
        "volume_report": volume_report,
        "total_pixels": total_pixels,
        "significant_pixels": significant,
        "negative_change_pixels": neg_changes,
        "positive_change_pixels": pos_changes,
        "propagated_error": round(propagated_error, 4),
        "threshold": round(threshold, 4),
    }


def _write_array_via_gdal(
    data: "xr.DataArray",
    path: str,
    dtype: str,
    template: "xr.DataArray",
    nodata: float | None = None,
) -> None:
    """Fallback raster write using GDAL when rioxarray fails.

    Args:
        data: xarray DataArray to write.
        path: Output raster path.
        dtype: 'float32' or 'uint8'.
        template: DataArray whose CRS/transform to copy.
        nodata: Override the nodata value. For uint8 masks we use 255.
    """
    from osgeo import gdal

    rows, cols = data.shape
    if dtype == "float32":
        gdal_dtype = gdal.GDT_Float32
        default_nodata = -9999.0
    else:
        gdal_dtype = gdal.GDT_Byte
        default_nodata = 255
    effective_nodata = nodata if nodata is not None else default_nodata

    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(
        path,
        cols,
        rows,
        1,
        gdal_dtype,
        options=["COMPRESS=LZW", "TILED=YES"],
    )
    if ds is None:
        raise RuntimeError(f"Failed to create raster: {path}")

    if hasattr(template, "rio"):
        try:
            ds.SetGeoTransform(template.rio.transform().to_gdal())
        except Exception as e:
            logger.warning("Could not set GeoTransform: %s", e)
        # Set projection only if the template has a real CRS. Previously
        # if template.rio.crs was None, SetProjection received the
        # literal string 'None', which is invalid WKT.
        template_crs = template.rio.crs if hasattr(template.rio, "crs") else None
        if template_crs is not None:
            try:
                if hasattr(template_crs, "to_wkt"):
                    wkt = template_crs.to_wkt()
                else:
                    wkt = str(template_crs)
                if wkt and wkt != "None":
                    ds.SetProjection(wkt)
            except Exception as e:
                logger.warning("Could not set projection: %s", e)

    band = ds.GetRasterBand(1)
    values = data.values
    if np.issubdtype(values.dtype, np.floating):
        nan_mask = np.isnan(values)
        values = values.copy()
        values[nan_mask] = effective_nodata
        band.SetNoDataValue(float(effective_nodata))
    elif gdal_dtype == gdal.GDT_Byte:
        # For byte masks, replace NaN-derived sentinel (255) explicitly.
        band.SetNoDataValue(float(effective_nodata))

    band.WriteArray(values)
    band.FlushCache()
    ds = None
