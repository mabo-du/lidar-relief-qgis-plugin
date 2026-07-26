"""Capture genuine LiDAR Relief UI screenshots from QGIS Desktop.

Run inside a QGIS environment:

    QGIS_PLUGINPATH=. qgis --code scripts/capture_qgis_documentation.py

The script uses a deterministic synthetic DEM, opens the plugin's real native
dialogs, captures them, writes a provenance manifest, and closes QGIS.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import processing
import qgis.utils
from osgeo import gdal, osr
from qgis.PyQt.QtCore import QPoint, QSettings, QTimer
from qgis.PyQt.QtWidgets import QApplication, QDialog, QMenu
from qgis.core import QgsApplication, QgsProject, QgsRasterLayer, Qgis


ROOT = Path(os.environ.get("LIDAR_RELIEF_REPO", Path.cwd())).resolve()
OUTPUT = ROOT / "lidar_relief" / "docs" / "images" / "qgis"
MANIFEST = OUTPUT.parent / "screenshot-manifest.json"
PLUGIN_ID = "lidar_relief"
DEMO_DEM = Path("/tmp/lidar-relief-documentation-dem.tif")
iface = qgis.utils.iface
entries: list[dict[str, str]] = []
failures: list[str] = []


def _create_demo_dem(path: Path) -> None:
    """Create a deterministic, non-sensitive DEM for the documentation."""
    size = 420
    y, x = np.mgrid[-1.0 : 1.0 : complex(size), -1.0 : 1.0 : complex(size)]
    terrain = 145.0 + 9.0 * x - 4.0 * y + 2.2 * np.sin(2.5 * x + 1.7 * y)
    mound = 2.8 * np.exp(-((x + 0.35) ** 2 + (y - 0.12) ** 2) / 0.012)
    ring_radius = np.hypot(x - 0.27, y + 0.16)
    ring = -1.4 * np.exp(-((ring_radius - 0.22) ** 2) / 0.0012)
    bank = 1.0 * np.exp(-((y - 0.18 * np.sin(5.0 * x) - 0.35) ** 2) / 0.001)
    furrows = 0.28 * np.sin(70.0 * (0.88 * x + 0.22 * y))
    mask = (x > -0.1) & (y > 0.15)
    data = (terrain + mound + ring + bank + furrows * mask).astype("float32")

    driver = gdal.GetDriverByName("GTiff")
    dataset = driver.Create(str(path), size, size, 1, gdal.GDT_Float32)
    dataset.SetGeoTransform((700000.0, 1.0, 0.0, 5930000.0, 0.0, -1.0))
    spatial_ref = osr.SpatialReference()
    spatial_ref.ImportFromEPSG(28355)
    dataset.SetProjection(spatial_ref.ExportToWkt())
    band = dataset.GetRasterBand(1)
    band.WriteArray(data)
    band.SetNoDataValue(-9999.0)
    band.FlushCache()
    dataset.FlushCache()
    dataset = None


def _save_widget(widget, filename: str, feature_id: str, title: str, kind: str) -> None:
    """Save one real Qt widget capture and append its provenance entry."""
    path = OUTPUT / filename
    image = widget.grab()
    if image.isNull() or not image.save(str(path), "PNG"):
        failures.append(f"could not capture {feature_id}")
        return
    from lidar_relief.version import get_version

    entries.append(
        {
            "file": f"qgis/{filename}",
            "kind": kind,
            "feature_id": feature_id,
            "title": title,
            "source": "actual-qgis-capture",
            "qgis_version": Qgis.QGIS_VERSION,
            "plugin_version": get_version(),
            "captured_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
            "demo_data": "deterministic synthetic DEM; no real site coordinates",
        }
    )


def _dialog_parameters(algorithm) -> dict:
    """Supply the synthetic DEM to compatible raster inputs for clearer dialogs."""
    parameters = {}
    for parameter in algorithm.parameterDefinitions():
        name = parameter.name()
        if parameter.type() == "raster" or name in {
            "INPUT",
            "DEM",
            "OLDER_DEM",
            "NEWER_DEM",
            "LIDAR",
        }:
            parameters[name] = str(DEMO_DEM)
    return parameters


def _capture_algorithm_dialogs(algorithms, index=0) -> None:
    if index >= len(algorithms):
        QTimer.singleShot(200, _capture_workflow_dialogs)
        return
    algorithm = algorithms[index]
    algorithm_id = f"{PLUGIN_ID}:{algorithm.name()}"
    try:
        dialog = processing.createAlgorithmDialog(
            algorithm_id, _dialog_parameters(algorithm)
        )
        dialog.resize(1040, 780)
        dialog.show()
        dialog.raise_()

        def capture_and_continue():
            filename = f"algorithm-{algorithm.name().replace('_', '-')}.png"
            _save_widget(
                dialog,
                filename,
                algorithm_id,
                algorithm.displayName(),
                "algorithm-dialog",
            )
            dialog.close()
            dialog.deleteLater()
            QTimer.singleShot(
                80, lambda: _capture_algorithm_dialogs(algorithms, index + 1)
            )

        QTimer.singleShot(220, capture_and_continue)
    except Exception as exc:
        failures.append(f"{algorithm_id}: {exc}")
        QTimer.singleShot(80, lambda: _capture_algorithm_dialogs(algorithms, index + 1))


def _capture_modal(
    feature_id: str,
    title: str,
    filename: str,
    invoke,
    continuation,
) -> None:
    """Capture a blocking native dialog while its real event loop is active."""

    def grab_and_close():
        widget = QApplication.activeModalWidget() or QApplication.activeWindow()
        if widget is None:
            failures.append(f"no active dialog for {feature_id}")
        else:
            _save_widget(widget, filename, feature_id, title, "workflow-dialog")
            if isinstance(widget, QDialog):
                widget.reject()
            else:
                widget.close()

    QTimer.singleShot(260, grab_and_close)
    try:
        invoke()
    except Exception as exc:
        failures.append(f"{feature_id}: {exc}")
    QTimer.singleShot(100, continuation)


def _capture_workflow_dialogs(index=0) -> None:
    from lidar_relief.context_help import show_context_help
    from lidar_relief.plugin_ui import (
        _checkable_list,
        interpretation_note_dialog,
        show_dem_preflight,
        show_diagnostics,
        show_raster_comparison,
        study_bookmark_dialog,
    )

    algorithms = [
        (f"{PLUGIN_ID}:{item.name()}", item.displayName())
        for item in QgsApplication.processingRegistry()
        .providerById(PLUGIN_ID)
        .algorithms()
    ]
    workflows = (
        (
            "menu:contextual-help",
            "Contextual parameter help",
            "workflow-contextual-help.png",
            lambda: show_context_help(iface.mainWindow()),
        ),
        (
            "menu:dem-preflight",
            "DEM preflight",
            "workflow-dem-preflight.png",
            lambda: show_dem_preflight(str(DEMO_DEM), iface.mainWindow()),
        ),
        (
            "menu:dependency-diagnostics",
            "Dependency diagnostics",
            "workflow-dependency-diagnostics.png",
            lambda: show_diagnostics(iface.mainWindow()),
        ),
        (
            "menu:favorites",
            "Favorite tools",
            "workflow-favorites.png",
            lambda: _checkable_list(
                "LiDAR Relief — Favorite tools",
                algorithms,
                set(),
                iface.mainWindow(),
            ),
        ),
        (
            "menu:raster-comparison",
            "Raster comparison",
            "workflow-raster-comparison.png",
            lambda: show_raster_comparison(iface, iface.mainWindow()),
        ),
        (
            "menu:interpretation-note",
            "Interpretation note",
            "workflow-interpretation-note.png",
            lambda: interpretation_note_dialog(
                "Synthetic archaeological DEM", iface.mainWindow()
            ),
        ),
        (
            "menu:study-area-bookmarks",
            "Study area bookmarks",
            "workflow-study-area-bookmarks.png",
            lambda: study_bookmark_dialog([], iface.mainWindow()),
        ),
    )
    if index >= len(workflows):
        QTimer.singleShot(200, _capture_plugin_menu)
        return
    feature_id, title, filename, invoke = workflows[index]
    _capture_modal(
        feature_id,
        title,
        filename,
        invoke,
        lambda: _capture_workflow_dialogs(index + 1),
    )


def _capture_plugin_menu() -> None:
    """Capture the actual QGIS canvas with the populated plugin menu open."""
    iface.messageBar().clearWidgets()
    plugin_menu = next(
        (
            menu
            for menu in iface.mainWindow().findChildren(QMenu)
            if "LiDAR Relief" in menu.title()
        ),
        None,
    )
    if plugin_menu is None:
        failures.append("could not find LiDAR Relief plugin menu")
        _finish()
        return
    plugin_menu.popup(iface.mainWindow().mapToGlobal(QPoint(390, 80)))

    def grab():
        screen = QApplication.primaryScreen()
        pixmap = screen.grabWindow(0)
        path = OUTPUT / "qgis-plugin-menu.png"
        if pixmap.isNull() or not pixmap.save(str(path), "PNG"):
            failures.append("could not capture plugin menu")
        else:
            from lidar_relief.version import get_version

            entries.append(
                {
                    "file": "qgis/qgis-plugin-menu.png",
                    "kind": "qgis-workspace",
                    "feature_id": "menu:plugin-overview",
                    "title": "LiDAR Relief menu in QGIS Desktop",
                    "source": "actual-qgis-capture",
                    "qgis_version": Qgis.QGIS_VERSION,
                    "plugin_version": get_version(),
                    "captured_at": datetime.now(timezone.utc)
                    .replace(microsecond=0)
                    .isoformat(),
                    "demo_data": "deterministic synthetic DEM; no real site coordinates",
                }
            )
        plugin_menu.close()
        _finish()

    QTimer.singleShot(300, grab)


def _finish() -> None:
    entries.sort(key=lambda item: (item["kind"], item["feature_id"]))
    MANIFEST.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "capture_script": "scripts/capture_qgis_documentation.py",
                "screenshots": entries,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    result = {
        "captured": len(entries),
        "failures": failures,
        "manifest": str(MANIFEST),
    }
    print(json.dumps(result, indent=2), flush=True)
    result_path = os.environ.get("QGIS_CAPTURE_RESULT")
    if result_path:
        Path(result_path).write_text(json.dumps(result), encoding="utf-8")
    QgsProject.instance().clear()
    iface.mainWindow().close()


def _start() -> None:
    if iface is None:
        raise RuntimeError("QGIS Desktop interface is unavailable")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    QSettings().setValue("lidar_relief/context_help/guidance_seen", True)
    QSettings().setValue("lidar_relief/context_help/show_guidance", False)
    if not qgis.utils.loadPlugin(PLUGIN_ID):
        raise RuntimeError("QGIS could not discover the LiDAR Relief plugin")
    if not qgis.utils.startPlugin(PLUGIN_ID):
        raise RuntimeError("QGIS could not start the LiDAR Relief plugin")
    provider = QgsApplication.processingRegistry().providerById(PLUGIN_ID)
    if provider is None:
        raise RuntimeError("LiDAR Relief provider was not registered")

    _create_demo_dem(DEMO_DEM)
    first_layer = QgsRasterLayer(str(DEMO_DEM), "Synthetic archaeological DEM")
    second_layer = QgsRasterLayer(str(DEMO_DEM), "Synthetic comparison DEM")
    if not first_layer.isValid() or not second_layer.isValid():
        raise RuntimeError("documentation DEM could not be loaded")
    QgsProject.instance().addMapLayers([first_layer, second_layer])
    iface.setActiveLayer(first_layer)
    iface.mapCanvas().setExtent(first_layer.extent())
    iface.mapCanvas().refresh()
    iface.mainWindow().resize(1500, 920)
    iface.mainWindow().showMaximized()

    algorithms = sorted(provider.algorithms(), key=lambda item: item.displayName())
    QTimer.singleShot(500, lambda: _capture_algorithm_dialogs(algorithms))


QTimer.singleShot(0, _start)
