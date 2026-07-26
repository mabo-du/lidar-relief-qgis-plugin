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
    """Return the selected next action and the computed recommendation."""
    from .dem_preflight import analyse_dem, format_preflight, recommend_workflow

    summary = analyse_dem(source)
    recommendation = recommend_workflow(summary)
    action = show_report_dialog(
        "LiDAR Relief — DEM preflight",
        format_preflight(summary, recommendation),
        parent,
        (
            ("Open Contact Sheet", "contact_sheet"),
            ("Open Batch Relief", "batch_relief"),
        ),
    )
    return action, recommendation


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


def choose_favorite(algorithms, recipes, parent=None):
    """Choose a saved algorithm or recipe and return its kind and value."""
    items = [
        (f"Tool — {label}", "algorithm", algorithm_id)
        for algorithm_id, label in algorithms
    ]
    items.extend(
        (f"Recipe — {os.path.basename(path)}", "recipe", path) for path in recipes
    )
    if not items:
        from qgis.PyQt.QtWidgets import QMessageBox

        QMessageBox.information(
            parent,
            "LiDAR Relief — Favorites",
            "There are no favorites yet. Use Manage Favorites to add some.",
        )
        return None
    from qgis.PyQt.QtWidgets import QInputDialog

    labels = [item[0] for item in items]
    label, accepted = QInputDialog.getItem(
        parent, "LiDAR Relief — Favorites", "Open:", labels, 0, False
    )
    return items[labels.index(label)][1:] if accepted else None


def _checkable_list(title, items, selected, parent):
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListWidget
    from qgis.PyQt.QtWidgets import QListWidgetItem, QVBoxLayout

    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.resize(680, 520)
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("Tick the items to keep as favorites.", dialog))
    listing = QListWidget(dialog)
    for value, label in items:
        item = QListWidgetItem(label, listing)
        item.setData(Qt.UserRole, value)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if value in selected else Qt.Unchecked)
    layout.addWidget(listing)
    buttons = QDialogButtonBox(
        QDialogButtonBox.Save | QDialogButtonBox.Cancel, parent=dialog
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if not dialog.exec():
        return None
    return [
        listing.item(index).data(Qt.UserRole)
        for index in range(listing.count())
        if listing.item(index).checkState() == Qt.Checked
    ]


def manage_favorites_dialog(algorithms, recipes, selected, parent=None):
    """Edit favorite tools and recipes in two small native dialogs."""
    tool_values = _checkable_list(
        "LiDAR Relief — Favorite tools",
        algorithms,
        set(selected[0]),
        parent,
    )
    if tool_values is None:
        return None
    recipe_values = _checkable_list(
        "LiDAR Relief — Favorite recipes",
        [(path, os.path.basename(path)) for path in recipes],
        set(selected[1]),
        parent,
    )
    return None if recipe_values is None else (tool_values, recipe_values)


def manage_recent_dialog(recipes, outputs, parent=None):
    """Choose which recent recipes and output folders should be retained."""
    kept_recipes = _checkable_list(
        "LiDAR Relief — Recent recipes",
        [(path, path) for path in recipes],
        set(recipes),
        parent,
    )
    if kept_recipes is None:
        return None
    kept_outputs = _checkable_list(
        "LiDAR Relief — Recent output folders",
        [(path, path) for path in outputs],
        set(outputs),
        parent,
    )
    return None if kept_outputs is None else (kept_recipes, kept_outputs)


def show_raster_comparison(iface, parent=None):
    """Show two loaded rasters in synchronized, read-only map canvases."""
    from qgis.core import QgsProject, QgsRasterLayer
    from qgis.gui import QgsMapCanvas
    from qgis.PyQt.QtWidgets import (
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QHBoxLayout,
        QMessageBox,
        QVBoxLayout,
    )

    layers = [
        layer
        for layer in QgsProject.instance().mapLayers().values()
        if isinstance(layer, QgsRasterLayer) and layer.isValid()
    ]
    if len(layers) < 2:
        QMessageBox.information(
            parent,
            "LiDAR Relief — Raster comparison",
            "Load at least two raster layers before opening comparison.",
        )
        return None

    chooser = QDialog(parent)
    chooser.setWindowTitle("LiDAR Relief — Choose comparison layers")
    form = QFormLayout(chooser)
    left_choice, right_choice = QComboBox(chooser), QComboBox(chooser)
    for layer in layers:
        left_choice.addItem(layer.name(), layer.id())
        right_choice.addItem(layer.name(), layer.id())
    right_choice.setCurrentIndex(1)
    form.addRow("Left:", left_choice)
    form.addRow("Right:", right_choice)
    buttons = QDialogButtonBox(
        QDialogButtonBox.Open | QDialogButtonBox.Cancel, parent=chooser
    )
    buttons.accepted.connect(chooser.accept)
    buttons.rejected.connect(chooser.reject)
    form.addRow(buttons)
    if not chooser.exec():
        return None

    selected = (
        QgsProject.instance().mapLayer(left_choice.currentData()),
        QgsProject.instance().mapLayer(right_choice.currentData()),
    )
    dialog = QDialog(parent)
    dialog.setWindowTitle(f"LiDAR Relief — {selected[0].name()} ↔ {selected[1].name()}")
    dialog.resize(1200, 650)
    layout = QVBoxLayout(dialog)
    canvases_layout = QHBoxLayout()
    left_canvas, right_canvas = QgsMapCanvas(dialog), QgsMapCanvas(dialog)
    destination_crs = iface.mapCanvas().mapSettings().destinationCrs()
    extent = iface.mapCanvas().extent()
    for canvas, layer in zip((left_canvas, right_canvas), selected):
        canvas.setDestinationCrs(destination_crs)
        canvas.setLayers([layer])
        canvas.setExtent(extent)
        canvases_layout.addWidget(canvas)
    layout.addLayout(canvases_layout)
    close_buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=dialog)
    close_buttons.rejected.connect(dialog.reject)
    layout.addWidget(close_buttons)
    syncing = {"active": False}

    def sync(source, target):
        if syncing["active"]:
            return
        syncing["active"] = True
        target.setExtent(source.extent())
        target.refresh()
        syncing["active"] = False

    left_canvas.extentsChanged.connect(lambda: sync(left_canvas, right_canvas))
    right_canvas.extentsChanged.connect(lambda: sync(right_canvas, left_canvas))
    dialog.exec()
    return selected


def interpretation_note_dialog(visualization: str, parent=None):
    """Collect the descriptive fields for one interpretation note."""
    from qgis.PyQt.QtWidgets import (
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QLineEdit,
        QTextEdit,
    )

    dialog = QDialog(parent)
    dialog.setWindowTitle("LiDAR Relief — Interpretation note")
    dialog.resize(520, 360)
    form = QFormLayout(dialog)
    title = QLineEdit(dialog)
    description = QTextEdit(dialog)
    confidence = QComboBox(dialog)
    confidence.addItems(["low", "medium", "high"])
    confidence.setCurrentText("medium")
    layer = QLineEdit(visualization, dialog)
    form.addRow("Title:", title)
    form.addRow("Interpretation:", description)
    form.addRow("Confidence:", confidence)
    form.addRow("Visualization:", layer)
    buttons = QDialogButtonBox(
        QDialogButtonBox.Save | QDialogButtonBox.Cancel, parent=dialog
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if not dialog.exec():
        return None
    return {
        "title": title.text(),
        "interpretation": description.toPlainText(),
        "confidence": confidence.currentText(),
        "visualization": layer.text(),
    }


def choose_interpretation_output(parent=None):
    """Choose an interoperable interpretation-note destination."""
    from qgis.PyQt.QtWidgets import QFileDialog

    path, _selected = QFileDialog.getSaveFileName(
        parent,
        "Export interpretation note",
        "lidar-relief-interpretation.geojson",
        "GeoJSON (*.geojson);;CSV (*.csv)",
    )
    return path


def study_bookmark_dialog(bookmarks, parent=None):
    """Collect one bookmark-management command."""
    from qgis.PyQt.QtWidgets import QInputDialog, QMessageBox

    actions = ["Save current extent", "Go to", "Rename", "Remove"]
    action, accepted = QInputDialog.getItem(
        parent,
        "LiDAR Relief — Study area bookmarks",
        "Action:",
        actions,
        0,
        False,
    )
    if not accepted:
        return None
    if action == "Save current extent":
        name, accepted = QInputDialog.getText(
            parent, "Save study area", "Bookmark name:"
        )
        return ("save", name) if accepted else None
    if not bookmarks:
        QMessageBox.information(
            parent,
            "LiDAR Relief — Study area bookmarks",
            "There are no saved study areas yet.",
        )
        return None
    names = [item["name"] for item in bookmarks]
    name, accepted = QInputDialog.getItem(
        parent, f"{action} study area", "Bookmark:", names, 0, False
    )
    if not accepted:
        return None
    if action == "Rename":
        new_name, accepted = QInputDialog.getText(
            parent, "Rename study area", "New name:", text=name
        )
        return ("rename", name, new_name) if accepted else None
    return ("goto" if action == "Go to" else "remove", name)


def choose_support_bundle_output(parent=None):
    """Choose a ZIP destination for a redacted support bundle."""
    from qgis.PyQt.QtWidgets import QFileDialog

    path, _selected = QFileDialog.getSaveFileName(
        parent,
        "Create LiDAR Relief support bundle",
        "lidar-relief-support.zip",
        "ZIP archive (*.zip)",
    )
    return path


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
