#!/usr/bin/env python3
"""Headless QGIS runtime smoke test for the packaged plugin."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import numpy as np
from osgeo import gdal, osr
from qgis.core import QgsApplication, Qgis


# Must match the addAlgorithm() calls in lidar_relief/provider.py, and the
# counts quoted in README.md and lidar_relief/metadata.txt. This guard is
# deliberately exact rather than a lower bound: it catches an algorithm that
# silently fails to register (a bad import in provider.py takes the whole
# provider down) as well as one added without updating the user-facing docs.
EXPECTED_ALGORITHM_COUNT = 31
TRI_ALGORITHM_ID = "lidar_relief:terrain_ruggedness_index"


def create_smoke_dem(path: Path) -> None:
    """Create a small projected DEM with one locally prominent cell."""
    driver = gdal.GetDriverByName("GTiff")
    dataset = driver.Create(str(path), 5, 5, 1, gdal.GDT_Float32)
    if dataset is None:
        raise RuntimeError("GDAL could not create the smoke-test DEM")
    dataset.SetGeoTransform((500000.0, 1.0, 0.0, 6000000.0, 0.0, -1.0))
    spatial_reference = osr.SpatialReference()
    spatial_reference.ImportFromEPSG(28355)
    dataset.SetProjection(spatial_reference.ExportToWkt())
    elevations = np.zeros((5, 5), dtype=np.float32)
    elevations[2, 2] = 2.0
    dataset.GetRasterBand(1).WriteArray(elevations)
    dataset.FlushCache()
    dataset = None


def validate_tri_output(path: Path) -> None:
    """Confirm QGIS produced a finite, non-trivial TRI raster."""
    dataset = gdal.Open(str(path), gdal.GA_ReadOnly)
    if dataset is None:
        raise RuntimeError("TRI output was not created")
    values = dataset.GetRasterBand(1).ReadAsArray()
    dataset = None
    if values.shape != (5, 5):
        raise AssertionError(f"unexpected TRI output shape: {values.shape}")
    if not np.isfinite(values).all():
        raise AssertionError("TRI output contains non-finite values")
    if float(values.max()) <= 0.0:
        raise AssertionError("TRI output contains no ruggedness signal")


def main() -> int:
    """Load, exercise, and cleanly unload the plugin in QGIS."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    profile_directory = tempfile.TemporaryDirectory(prefix="qgis-smoke-profile-")
    os.environ["QGIS_CUSTOM_CONFIG_PATH"] = profile_directory.name
    QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", "/usr"), True)
    application = QgsApplication([], False)
    plugin = None
    try:
        application.initQgis()
        from processing.core.Processing import Processing

        Processing.initialize()
        import lidar_relief

        plugin = lidar_relief.classFactory(None)
        plugin.initGui()
        provider = QgsApplication.processingRegistry().providerById("lidar_relief")
        if provider is None:
            raise AssertionError("LiDAR Relief Processing provider was not registered")

        algorithm_ids = {algorithm.id() for algorithm in provider.algorithms()}
        if len(algorithm_ids) != EXPECTED_ALGORITHM_COUNT:
            raise AssertionError(
                f"expected {EXPECTED_ALGORITHM_COUNT} algorithms, "
                f"found {len(algorithm_ids)}"
            )
        if TRI_ALGORITHM_ID not in algorithm_ids:
            raise AssertionError("Terrain Ruggedness Index was not registered")

        import processing

        with tempfile.TemporaryDirectory(prefix="lidar-relief-smoke-") as directory:
            input_path = Path(directory) / "input_dem.tif"
            output_path = Path(directory) / "tri.tif"
            create_smoke_dem(input_path)
            result = processing.run(
                TRI_ALGORITHM_ID,
                {"INPUT": str(input_path), "OUTPUT": str(output_path)},
            )
            if Path(result["OUTPUT"]) != output_path:
                raise AssertionError("Processing returned an unexpected output path")
            validate_tri_output(output_path)

        print(
            f"QGIS {Qgis.QGIS_VERSION}: plugin loaded, "
            f"{len(algorithm_ids)} algorithms registered, TRI executed successfully"
        )
        return 0
    finally:
        if plugin is not None:
            plugin.unload()
        application.exitQgis()
        profile_directory.cleanup()


if __name__ == "__main__":
    sys.exit(main())
