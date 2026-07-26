"""DEM suitability summary and conservative workflow recommendations."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class DemSummary:
    source: str
    width: int
    height: int
    pixel_width: float
    pixel_height: float
    extent: tuple[float, float, float, float]
    crs_name: str
    projected: bool
    linear_units: str
    valid_min: float
    valid_max: float
    valid_mean: float
    valid_stddev: float
    nodata_percent: float
    estimated_memory_mb: float
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class FeatureScale:
    label: str
    metres: float
    pixels: int


@dataclass(frozen=True)
class WorkflowRecommendation:
    start_with: str
    preset_key: str
    preset_label: str
    search_radii: tuple[FeatureScale, ...]
    explanation: str
    caution: str


def _dataset_extent(dataset) -> tuple[float, float, float, float]:
    gt = dataset.GetGeoTransform()
    width, height = dataset.RasterXSize, dataset.RasterYSize
    corners = []
    for col, row in ((0, 0), (width, 0), (0, height), (width, height)):
        x = gt[0] + col * gt[1] + row * gt[2]
        y = gt[3] + col * gt[4] + row * gt[5]
        corners.append((x, y))
    xs, ys = zip(*corners)
    return min(xs), min(ys), max(xs), max(ys)


def _crs_details(projection: str) -> tuple[str, bool, str]:
    if not projection:
        return "Not defined", False, "unknown"
    try:
        from osgeo import osr

        srs = osr.SpatialReference()
        if srs.ImportFromWkt(projection) != 0:
            return "Unrecognised", False, "unknown"
        authority = srs.GetAuthorityName(None)
        code = srs.GetAuthorityCode(None)
        name = f"{authority}:{code}" if authority and code else srs.GetName()
        return (
            name or "Defined CRS",
            bool(srs.IsProjected()),
            (srs.GetLinearUnitsName() or "unknown"),
        )
    except Exception:
        return "Defined CRS", False, "unknown"


def analyse_dataset(dataset, source: str) -> DemSummary:
    """Inspect a GDAL-like dataset without reading it at full resolution."""
    width, height = int(dataset.RasterXSize), int(dataset.RasterYSize)
    if width <= 0 or height <= 0:
        raise ValueError("DEM has no raster cells.")

    gt = dataset.GetGeoTransform()
    pixel_width = math.hypot(gt[1], gt[4])
    pixel_height = math.hypot(gt[2], gt[5])
    if pixel_width <= 0 or pixel_height <= 0:
        raise ValueError("DEM has an invalid zero pixel size.")

    band = dataset.GetRasterBand(1)
    sample_width = min(width, 1024)
    sample_height = min(height, 1024)
    sample = np.asarray(
        band.ReadAsArray(buf_xsize=sample_width, buf_ysize=sample_height),
        dtype=np.float64,
    )
    nodata = band.GetNoDataValue()
    invalid = ~np.isfinite(sample)
    if nodata is not None:
        invalid |= np.isclose(sample, nodata)
    valid = sample[~invalid]
    if valid.size == 0:
        raise ValueError("DEM contains no valid elevation cells in the sample.")

    crs_name, projected, linear_units = _crs_details(dataset.GetProjection())
    warnings = []
    if not dataset.GetProjection():
        warnings.append(
            "No CRS is defined. Assign the correct CRS and Reproject to a local "
            "metric CRS if needed before comparing this DEM with other layers."
        )
    elif not projected:
        warnings.append(
            "The CRS is geographic or could not be confirmed as projected. "
            "Reproject to a local metric CRS before distance-based analysis."
        )
    if abs(pixel_width - pixel_height) / max(pixel_width, pixel_height) > 0.01:
        warnings.append(
            "Pixels are not square. Resample to square pixels for reliable "
            "distance and slope calculations."
        )
    nodata_percent = float(invalid.mean() * 100.0)
    if nodata_percent > 50:
        warnings.append(
            "More than half the sampled cells are nodata; clip to the useful "
            "coverage before expensive processing."
        )

    return DemSummary(
        source=os.path.abspath(source),
        width=width,
        height=height,
        pixel_width=float(pixel_width),
        pixel_height=float(pixel_height),
        extent=_dataset_extent(dataset),
        crs_name=crs_name,
        projected=projected,
        linear_units=linear_units,
        valid_min=float(valid.min()),
        valid_max=float(valid.max()),
        valid_mean=float(valid.mean()),
        valid_stddev=float(valid.std()),
        nodata_percent=nodata_percent,
        estimated_memory_mb=float(width * height * 4 / (1024**2)),
        warnings=tuple(warnings),
    )


def analyse_dem(source: str) -> DemSummary:
    """Open and inspect a raster path with GDAL."""
    from .core.raster_utils import open_raster

    dataset = open_raster(source)
    try:
        return analyse_dataset(dataset, source)
    finally:
        dataset = None


def recommend_workflow(summary: DemSummary) -> WorkflowRecommendation:
    """Return conservative scale guidance from DEM geometry and sampled relief."""
    cellsize = (summary.pixel_width + summary.pixel_height) / 2.0
    relief = summary.valid_max - summary.valid_min
    if relief >= 100 or summary.valid_stddev >= 25:
        preset_key = "upland_steep"
        preset_label = "Upland / Steep"
        explanation = (
            "The sampled elevation range is comparatively large, so the upland "
            "preset is the safer terrain-form starting point."
        )
    else:
        preset_key = "flat_agricultural"
        preset_label = "Flat / Agricultural"
        explanation = (
            "The sampled elevation range is modest, so the flat/agricultural "
            "preset is a conservative starting point. A bare-earth DEM cannot "
            "reliably reveal whether the site is forested or coastal."
        )

    scales = (
        ("Fine features", 2.0),
        ("Small earthworks", 10.0),
        ("Enclosures / broad relief", 50.0),
    )
    radii = tuple(
        FeatureScale(label, metres, max(1, int(round(metres / cellsize))))
        for label, metres in scales
    )
    return WorkflowRecommendation(
        start_with="Visualisation Contact Sheet",
        preset_key=preset_key,
        preset_label=preset_label,
        search_radii=radii,
        explanation=explanation,
        caution=(
            "These are visualisation starting points, not archaeological "
            "identification. Compare complementary outputs and other evidence."
        ),
    )


def format_preflight(
    summary: DemSummary, recommendation: WorkflowRecommendation
) -> str:
    """Render the preflight as readable plain text for QGIS and clipboard use."""
    x_min, y_min, x_max, y_max = summary.extent
    cell_count = summary.width * summary.height
    if cell_count <= 4_000_000:
        workload = "light"
    elif cell_count <= 25_000_000:
        workload = "moderate"
    else:
        workload = "large; clip or use a coarser preview before broad searches"
    lines = [
        "DEM PREFLIGHT",
        f"Source: {summary.source}",
        f"CRS: {summary.crs_name} ({summary.linear_units})",
        (
            f"Grid: {summary.width:,} × {summary.height:,} cells "
            f"({summary.width * summary.height:,} total)"
        ),
        f"Resolution: {summary.pixel_width:g} × {summary.pixel_height:g} map units",
        f"Extent: {x_min:g}, {y_min:g} — {x_max:g}, {y_max:g}",
        (
            f"Sampled elevation: {summary.valid_min:.2f} to "
            f"{summary.valid_max:.2f}; mean {summary.valid_mean:.2f}; "
            f"standard deviation {summary.valid_stddev:.2f}"
        ),
        f"Sampled nodata: {summary.nodata_percent:.1f} percent",
        (
            f"Estimated working size: {summary.estimated_memory_mb:.1f} MiB per "
            "single float raster (algorithms may need several)"
        ),
        f"Full-resolution workload: {workload}",
        "",
        "RECOMMENDATIONS",
        f"Recommended starting workflow: {recommendation.start_with}",
        f"Suggested terrain preset: {recommendation.preset_label}",
        recommendation.explanation,
        "Feature-scale starting radii:",
    ]
    lines.extend(
        f"- {scale.label}: {scale.metres:g} m ≈ {scale.pixels} px"
        for scale in recommendation.search_radii
    )
    if summary.warnings:
        lines.extend(["", "WARNINGS"])
        lines.extend(f"- {warning}" for warning in summary.warnings)
    lines.extend(["", recommendation.caution])
    return "\n".join(lines)
