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
from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtWidgets import QMainWindow


# Must match the addAlgorithm() calls in lidar_relief/provider.py, and the
# counts quoted in README.md and lidar_relief/metadata.txt. This guard is
# deliberately exact rather than a lower bound: it catches an algorithm that
# silently fails to register (a bad import in provider.py takes the whole
# provider down) as well as one added without updating the user-facing docs.
EXPECTED_ALGORITHM_COUNT = 31
TRI_ALGORITHM_ID = "lidar_relief:terrain_ruggedness_index"


class SmokeIface:
    """Small QgisInterface stand-in for plugin menu lifecycle checks."""

    def __init__(self):
        self.window = QMainWindow()
        self.actions = []

    def mainWindow(self):
        return self.window

    def addPluginToMenu(self, _menu, action):
        self.actions.append(action)

    def removePluginMenu(self, _menu, action):
        self.actions.remove(action)

    def activeLayer(self):
        return None


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
        from lidar_relief.context_help import (
            SETTINGS_GUIDANCE_SEEN,
            SETTINGS_SHOW_GUIDANCE,
        )
        from lidar_relief.menu_contract import (
            ALGORITHM_SHORTCUTS,
            MENU_COMMAND_LABELS,
        )

        settings = QSettings()
        settings.setValue(SETTINGS_GUIDANCE_SEEN, True)
        settings.setValue(SETTINGS_SHOW_GUIDANCE, False)
        iface = SmokeIface()
        plugin = lidar_relief.classFactory(iface)
        plugin.initGui()
        action_labels = {
            action.text() for action in iface.actions if not action.isSeparator()
        }
        expected_labels = {
            *(shortcut.label for shortcut in ALGORITHM_SHORTCUTS),
            *MENU_COMMAND_LABELS,
        }
        if action_labels != expected_labels:
            raise AssertionError(
                f"plugin menu mismatch: expected {sorted(expected_labels)}, "
                f"found {sorted(action_labels)}"
            )
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

        # Every algorithm dialog must offer a route to the documentation.
        # Checked here rather than in pytest because helpUrl() is resolved
        # through the Qt/SIP object, so only a real QGIS runtime proves the
        # mixin is actually in the MRO of the registered instance.
        without_help = sorted(
            algorithm.id()
            for algorithm in provider.algorithms()
            if not algorithm.helpUrl()
        )
        if without_help:
            raise AssertionError(
                f"{len(without_help)} algorithms have no help URL: {without_help}"
            )

        # QGIS must receive parameter-level help through the live SIP objects.
        # This catches an MRO/signature mismatch that pure-Python mixin tests
        # cannot reproduce.
        parameters_without_help = sorted(
            f"{algorithm.id()}:{parameter.name()}"
            for algorithm in provider.algorithms()
            for parameter in algorithm.parameterDefinitions()
            if not parameter.help()
        )
        if parameters_without_help:
            raise AssertionError(
                f"{len(parameters_without_help)} parameters have no contextual "
                f"help: {parameters_without_help}"
            )

        # The guide those URLs point at has to be inside the installed
        # plugin, not merely in the source repository.
        guide = Path(lidar_relief.__file__).parent / "USER_GUIDE.md"
        if not guide.is_file():
            raise AssertionError(
                f"USER_GUIDE.md is missing from the installed plugin at {guide}; "
                "it must ship in the package, not just the repo"
            )

        import processing

        with tempfile.TemporaryDirectory(prefix="lidar-relief-smoke-") as directory:
            input_path = Path(directory) / "input_dem.tif"
            output_path = Path(directory) / "tri.tif"
            named_outputs = Path(directory) / "named"
            recipe_path = Path(directory) / "resolved-recipe.json"
            create_smoke_dem(input_path)
            result = processing.run(
                TRI_ALGORITHM_ID,
                {"INPUT": str(input_path), "OUTPUT": str(output_path)},
            )
            if Path(result["OUTPUT"]) != output_path:
                raise AssertionError("Processing returned an unexpected output path")
            validate_tri_output(output_path)

            batch_result = processing.run(
                "lidar_relief:batch_relief",
                {
                    "INPUT": str(input_path),
                    "PRESET": 1,
                    "RUN_HILLSHADE": False,
                    "RUN_SLRM": False,
                    "RUN_SVF": False,
                    "RUN_SLOPE": True,
                    "RUN_OPENNESS": False,
                    "RUN_MSTP": False,
                    "RUN_VAT": False,
                    "RUN_RED_RELIEF": False,
                    "RUN_LOCAL_DOMINANCE": False,
                    "RUN_ASVF": False,
                    "RUN_E4MSTP": False,
                    "RUN_PCA": False,
                    "OUTPUT_FOLDER": str(named_outputs),
                    "OUTPUT_TEMPLATE": "{dem}_{method}_{preset}",
                    "RECIPE_OUTPUT": str(recipe_path),
                },
            )
            expected_named_output = (
                named_outputs / "input_dem_slope_flat_agricultural.tif"
            )
            if Path(batch_result["SLOPE_OUTPUT"]) != expected_named_output:
                raise AssertionError(
                    "Batch naming template returned an unexpected path"
                )
            if not expected_named_output.is_file() or not recipe_path.is_file():
                raise AssertionError(
                    "Batch named output or resolved recipe was not created"
                )

        plugin.unload()
        plugin = None
        if iface.actions:
            raise AssertionError("plugin menu actions were not removed during unload")

        print(
            f"QGIS {Qgis.QGIS_VERSION}: plugin loaded, "
            f"{len(algorithm_ids)} algorithms registered, TRI and named Batch "
            "Relief recipe workflows executed successfully"
        )
        return 0
    finally:
        if plugin is not None:
            plugin.unload()
        application.exitQgis()
        profile_directory.cleanup()


if __name__ == "__main__":
    sys.exit(main())
