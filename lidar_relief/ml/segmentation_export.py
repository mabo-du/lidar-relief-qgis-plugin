"""segmentation_export.py — Write segmentation label maps as raster and polygons.

exports: write_label_raster(labels, path, geo_transform, projection, nodata) -> str,
         polygonise_labels(labels, geo_transform, projection, output_path,
                           labels_map, confidence, min_area_pixels,
                           background_class) -> int

used_by: algorithms/ai_detection_algorithm.py

rules:
  GDAL/OGR only — no QGIS imports, so this is testable headless.
  Polygons are what an archaeologist actually works with in GIS; the
  label raster is kept alongside as the primary evidence, because the
  vectorisation is lossy at feature boundaries.
  The background class is EXCLUDED from the polygon output by default.
  Emitting one enormous polygon covering every unclassified pixel makes
  the layer unusable.
agent:   claude-opus-5 | anthropic | 2026-07-25 | s_20260725_001 |
         New module supporting semantic segmentation, which the ML
         detector detected but never post-processed (SUPPORTED_MODEL_TYPES
         had a single entry and U-Net models silently returned zero
         detections). Polygons suit archaeology far better than boxes —
         ditches, banks and field systems are linear and areal, so a
         bounding box around a 400 m boundary conveys almost nothing.
"""

import logging

import numpy as np

logger = logging.getLogger(__name__)

# Written into cells that carry no class, so QGIS masks them rather than
# rendering the background as a solid block.
LABEL_NODATA = 255


def write_label_raster(
    labels: np.ndarray,
    output_path: str,
    geo_transform,
    projection: str,
    background_class: int = 0,
) -> str:
    """Write a class-index map to a GeoTIFF.

    Args:
        labels: 2D uint8 class indices.
        output_path: Output .tif path.
        geo_transform: GDAL geotransform of the source raster.
        projection: WKT projection of the source raster.
        background_class: Class written as nodata.

    Returns:
        The path written.

    Raises:
        ValueError: If ``labels`` is not 2D.
        RuntimeError: If the raster cannot be created.
    """
    from osgeo import gdal

    if labels.ndim != 2:
        raise ValueError(f"Expected a 2D label map, got shape {labels.shape}")

    rows, cols = labels.shape
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(
        output_path,
        cols,
        rows,
        1,
        gdal.GDT_Byte,
        options=["COMPRESS=LZW", "TILED=YES"],
    )
    if ds is None:
        raise RuntimeError(f"Failed to create label raster: {output_path}")

    if geo_transform is not None:
        ds.SetGeoTransform(geo_transform)
    if projection:
        ds.SetProjection(projection)

    out = labels.copy()
    out[labels == background_class] = LABEL_NODATA

    band = ds.GetRasterBand(1)
    band.SetNoDataValue(float(LABEL_NODATA))
    band.WriteArray(out)
    band.FlushCache()
    ds = None

    return output_path


def polygonise_labels(
    labels: np.ndarray,
    geo_transform,
    projection: str,
    output_path: str,
    labels_map=None,
    confidence: np.ndarray = None,
    min_area_pixels: int = 10,
    background_class: int = 0,
    feedback=None,
) -> int:
    """Vectorise a label map into a GeoPackage of class polygons.

    Args:
        labels: 2D uint8 class indices.
        geo_transform: GDAL geotransform of the source raster.
        projection: WKT projection. Required — a CRS-less output would be
            misplaced against every other layer.
        output_path: Output .gpkg path.
        labels_map: Optional list of class names, indexed by class id.
        confidence: Optional per-pixel confidence, averaged per polygon.
        min_area_pixels: Drop polygons smaller than this. Single-pixel
            speckle is model noise, not archaeology.
        background_class: Class to omit from the output.
        feedback: Optional progress callback.

    Returns:
        Number of polygons written.

    Raises:
        ValueError: If ``projection`` is empty.
        RuntimeError: If the GeoPackage cannot be created.
    """
    from osgeo import gdal, ogr, osr

    if not projection:
        raise ValueError(
            "Input raster has no CRS. Refusing to write segmentation polygons "
            "with an unknown coordinate system — they would be misplaced by "
            "potentially hundreds of kilometres. Assign a CRS to the raster "
            "first."
        )

    srs = osr.SpatialReference()
    srs.ImportFromWkt(projection)

    driver = ogr.GetDriverByName("GPKG")
    vector_ds = driver.CreateDataSource(output_path)
    if vector_ds is None:
        raise RuntimeError(f"Failed to create GeoPackage: {output_path}")

    layer = vector_ds.CreateLayer("segments", srs, ogr.wkbPolygon)
    layer.CreateField(ogr.FieldDefn("class_id", ogr.OFTInteger))
    layer.CreateField(ogr.FieldDefn("class_name", ogr.OFTString))
    layer.CreateField(ogr.FieldDefn("area_m2", ogr.OFTReal))
    layer.CreateField(ogr.FieldDefn("pixel_count", ogr.OFTInteger))
    layer.CreateField(ogr.FieldDefn("mean_confidence", ogr.OFTReal))

    pixel_area = abs(geo_transform[1] * geo_transform[5]) if geo_transform else 1.0

    written = 0
    class_ids = [int(c) for c in np.unique(labels) if int(c) != background_class]

    for class_id in class_ids:
        if feedback is not None and getattr(feedback, "isCanceled", bool)():
            break

        mask = (labels == class_id).astype(np.uint8)

        # GDAL polygonises from a raster band, so stage the per-class mask
        # in memory rather than round-tripping through disk.
        mem_driver = gdal.GetDriverByName("MEM")
        mask_ds = mem_driver.Create(
            "", labels.shape[1], labels.shape[0], 1, gdal.GDT_Byte
        )
        if geo_transform is not None:
            mask_ds.SetGeoTransform(geo_transform)
        mask_ds.SetProjection(projection)
        mask_band = mask_ds.GetRasterBand(1)
        mask_band.WriteArray(mask)

        temp_ds = ogr.GetDriverByName("Memory").CreateDataSource("polys")
        temp_layer = temp_ds.CreateLayer("polys", srs, ogr.wkbPolygon)
        temp_layer.CreateField(ogr.FieldDefn("value", ogr.OFTInteger))

        # Pass the mask as its own validity mask so only value==1 regions
        # are traced; otherwise GDAL also emits the zero background.
        gdal.Polygonize(mask_band, mask_band, temp_layer, 0, [], callback=None)

        class_name = _class_name(labels_map, class_id)

        for feature in temp_layer:
            geometry = feature.GetGeometryRef()
            if geometry is None:
                continue
            area = geometry.GetArea()
            pixel_count = int(round(area / pixel_area)) if pixel_area else 0
            if pixel_count < min_area_pixels:
                continue

            out_feature = ogr.Feature(layer.GetLayerDefn())
            out_feature.SetGeometry(geometry.Clone())
            out_feature.SetField("class_id", class_id)
            out_feature.SetField("class_name", class_name)
            out_feature.SetField("area_m2", float(area))
            out_feature.SetField("pixel_count", pixel_count)
            if confidence is not None:
                out_feature.SetField(
                    "mean_confidence",
                    float(np.mean(confidence[labels == class_id])),
                )
            layer.CreateFeature(out_feature)
            written += 1

        temp_ds = None
        mask_ds = None

    vector_ds.FlushCache()
    vector_ds = None

    return written


def _class_name(labels_map, class_id: int) -> str:
    """Resolve a class index to a name, falling back to ``class_<n>``."""
    if labels_map and 0 <= class_id < len(labels_map):
        return str(labels_map[class_id])
    return f"class_{class_id}"
