"""Thin QGIS/Qt presentation helpers for the plugin menu."""

from __future__ import annotations

import os


def active_raster_source(iface) -> str:
    """Return the active local raster source, or an empty string."""
    if iface is None:
        return ""
    layer = iface.activeLayer()
    if layer is None:
        return ""
    try:
        from qgis.core import QgsRasterLayer

        if not isinstance(layer, QgsRasterLayer) or not layer.isValid():
            return ""
        source = layer.source().split("|", 1)[0]
        return source if os.path.exists(source) else ""
    except (AttributeError, RuntimeError, TypeError):
        return ""


def choose_dem_source(iface, parent=None) -> str:
    """Prefer the active raster and otherwise offer a raster file picker."""
    source = active_raster_source(iface)
    if source:
        return source
    from qgis.PyQt.QtWidgets import QFileDialog

    source, _selected_filter = QFileDialog.getOpenFileName(
        parent,
        "Select a DEM for preflight",
        "",
        "Raster datasets (*.tif *.tiff *.vrt *.img *.asc);;All files (*)",
    )
    return source


def show_report_dialog(title: str, text: str, parent=None, extra_buttons=()):
    """Show a selectable report with Copy plus optional action buttons."""
    from qgis.PyQt.QtWidgets import (
        QApplication,
        QDialog,
        QDialogButtonBox,
        QPlainTextEdit,
        QPushButton,
        QVBoxLayout,
    )

    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.resize(760, 580)
    layout = QVBoxLayout(dialog)
    report = QPlainTextEdit(dialog)
    report.setReadOnly(True)
    report.setPlainText(text)
    layout.addWidget(report)

    buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=dialog)
    copy_button = QPushButton("Copy", dialog)
    buttons.addButton(copy_button, QDialogButtonBox.ActionRole)
    copy_button.clicked.connect(
        lambda: QApplication.clipboard().setText(report.toPlainText())
    )
    selected = {"value": None}
    for label, value in extra_buttons:
        button = QPushButton(label, dialog)
        buttons.addButton(button, QDialogButtonBox.ActionRole)

        def choose(_checked=False, selected_value=value):
            selected["value"] = selected_value
            dialog.accept()

        button.clicked.connect(choose)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.exec()
    return selected["value"]


def show_dem_preflight(source: str, parent=None):
    """Analyse a DEM and show recommendations; return an optional next action."""
    from .dem_preflight import analyse_dem, format_preflight, recommend_workflow

    summary = analyse_dem(source)
    recommendation = recommend_workflow(summary)
    return show_report_dialog(
        "LiDAR Relief — DEM preflight",
        format_preflight(summary, recommendation),
        parent,
        (
            ("Open Contact Sheet", "contact_sheet"),
            ("Open Batch Relief", "batch_relief"),
        ),
    )


def show_diagnostics(parent=None):
    """Show a copy-friendly support and optional-capability report."""
    from qgis.core import Qgis

    from .diagnostics import format_diagnostics

    return show_report_dialog(
        "LiDAR Relief — Dependency diagnostics",
        format_diagnostics(qgis_version=Qgis.QGIS_VERSION),
        parent,
    )


def choose_recent(items: list[str], title: str, parent=None) -> str:
    """Let the user choose one existing recent path."""
    if not items:
        from qgis.PyQt.QtWidgets import QMessageBox

        QMessageBox.information(parent, title, "There are no recent items yet.")
        return ""
    from qgis.PyQt.QtWidgets import QInputDialog

    labels = [f"{os.path.basename(item) or item} — {item}" for item in items]
    label, accepted = QInputDialog.getItem(
        parent, title, "Choose an item:", labels, 0, False
    )
    if not accepted:
        return ""
    return items[labels.index(label)]


def open_local_path(path: str) -> bool:
    """Open a local file or directory with the operating system."""
    from qgis.PyQt.QtCore import QUrl
    from qgis.PyQt.QtGui import QDesktopServices

    return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(path)))


def choose_output_folder(parent=None) -> str:
    """Prompt for a folder the user wants available in recent outputs."""
    from qgis.PyQt.QtWidgets import QFileDialog

    return QFileDialog.getExistingDirectory(parent, "Remember output folder")


def show_error(parent, title: str, error) -> None:
    """Show a concise user-facing error without exposing a traceback."""
    from qgis.PyQt.QtWidgets import QMessageBox

    QMessageBox.warning(parent, title, str(error))


def trigger_processing_toolbox(iface) -> bool:
    """Open QGIS's Processing toolbox using its stable desktop action name."""
    if iface is None:
        return False
    try:
        from qgis.PyQt.QtGui import QAction
    except ImportError:  # pragma: no cover - QGIS 3 uses Qt 5
        from qgis.PyQt.QtWidgets import QAction

    main_window = iface.mainWindow()
    for object_name in ("mProcessingToolboxAction", "mActionShowProcessingToolbox"):
        action = main_window.findChild(QAction, object_name)
        if action is not None:
            action.trigger()
            return True
    try:
        iface.messageBar().pushInfo(
            "LiDAR Relief",
            "Open Processing → Toolbox and search for “LiDAR Relief”.",
        )
    except (AttributeError, RuntimeError):
        pass
    return False
