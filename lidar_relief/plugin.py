"""plugin.py — Main plugin class and discoverability menu.
exports: LidarReliefPlugin
used_by: __init__.py → classFactory
rules:
  Register the Processing provider in initGui(), remove in unload().
  Never perform heavy computation here — this is a lifecycle manager only.
"""

import os

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QTimer

try:  # QAction moved from QtWidgets in Qt 5 to QtGui in Qt 6.
    from qgis.PyQt.QtGui import QAction
except ImportError:  # pragma: no cover - exercised by the QGIS 3 smoke test
    from qgis.PyQt.QtWidgets import QAction

from .context_help import (
    MENU_LABEL,
    should_show_guidance,
    show_context_help,
)
from .menu_contract import ALGORITHM_SHORTCUTS, BATCH_PRESET_INDEX
from .recent_items import (
    favorite_algorithms,
    favorite_recipes,
    recent_output_folders,
    recent_recipes,
    clear_recent_output_folders,
    clear_recent_recipes,
    record_output_folder,
    record_result_paths,
    set_favorite_algorithms,
    set_favorite_recipes,
)


class LidarReliefPlugin:
    """Main QGIS plugin class that registers the Processing provider.

    Rules:
        initGui() and unload() are called by QGIS lifecycle.
        Provider must be stored as instance attribute for clean unload.
    """

    def __init__(self, iface):
        """Initialise the plugin.

        Args:
            iface: QgisInterface — the QGIS application interface.
        """
        self.iface = iface
        self.provider = None
        self.context_help_action = None
        self.menu_actions = []
        self._loaded = False

    def initGui(self):
        """Register the LiDAR Relief Processing provider with QGIS."""
        from .provider import LidarReliefProvider

        self.provider = LidarReliefProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)
        self._loaded = True
        if self.iface is not None:
            self._add_action("Open LiDAR Relief Toolbox", self.openProcessingToolbox)
            self._add_separator()
            for shortcut in ALGORITHM_SHORTCUTS:
                self._add_action(
                    shortcut.label,
                    lambda _checked=False, item=shortcut: self.runAlgorithmShortcut(
                        item
                    ),
                )
            self._add_separator()
            self._add_action("Inspect Active DEM…", self.inspectDem)
            self._add_action("Dependency Diagnostics…", self.showDiagnostics)
            self._add_separator()
            self._add_action("Recent Recipe…", self.openRecentRecipe)
            self._add_action("Recent Output Folder…", self.openRecentOutputFolder)
            self._add_action("Remember Output Folder…", self.rememberOutputFolder)
            self._add_separator()
            self._add_action("Favorite Tool or Recipe…", self.openFavorite)
            self._add_action("Manage Favorites…", self.manageFavorites)
            self._add_action("Manage Recent Items…", self.manageRecentItems)
            self._add_separator()
            self._add_action("Compare Raster Layers…", self.compareRasters)
            self._add_action(
                "Record Interpretation Note…", self.recordInterpretationNote
            )
            self._add_separator()
            self._add_action("Study Area Bookmarks…", self.manageStudyBookmarks)
            self._add_action("Create Support Bundle…", self.createSupportBundle)
            self._add_separator()
            self._add_action("Open User Guide", self.openUserGuide)
            self.context_help_action = self._add_action(
                "Contextual Help…", self.showContextHelp
            )
            self.context_help_action.setToolTip(
                "Explain the ? help available beside LiDAR Relief settings"
            )
            if should_show_guidance():
                QTimer.singleShot(0, lambda: self._loaded and self.showContextHelp())

    def _add_action(self, label, callback):
        """Create, connect, and register one owned plugin-menu action."""
        action = QAction(label, self.iface.mainWindow())
        action.triggered.connect(callback)
        self.iface.addPluginToMenu(MENU_LABEL, action)
        self.menu_actions.append(action)
        return action

    def _add_separator(self):
        action = QAction(self.iface.mainWindow())
        action.setSeparator(True)
        self.iface.addPluginToMenu(MENU_LABEL, action)
        self.menu_actions.append(action)
        return action

    def _parent(self):
        return self.iface.mainWindow() if self.iface is not None else None

    def _active_dem(self):
        from .plugin_ui import active_raster_source

        return active_raster_source(self.iface)

    def _run_algorithm(self, algorithm_id, parameters=None):
        """Open a native Processing dialog and remember returned output folders."""
        import processing

        results = processing.execAlgorithmDialog(algorithm_id, parameters or {})
        if isinstance(results, dict):
            record_result_paths(results)
            recipe_path = results.get("RECIPE_OUTPUT")
            if recipe_path:
                from .recent_items import record_recent_recipe

                record_recent_recipe(recipe_path)
        return results

    def runAlgorithmShortcut(self, shortcut):
        """Open a configured native Processing dialog from the plugin menu."""
        parameters = {}
        if shortcut.use_active_dem:
            source = self._active_dem()
            if source:
                parameters["INPUT"] = source
        try:
            return self._run_algorithm(shortcut.algorithm_id, parameters)
        except Exception as exc:
            from .plugin_ui import show_error

            show_error(self._parent(), "Could not open Processing tool", exc)
            return None

    def openProcessingToolbox(self):
        from .plugin_ui import trigger_processing_toolbox

        return trigger_processing_toolbox(self.iface)

    def inspectDem(self):
        """Inspect the active/selected DEM and offer the recommended next dialog."""
        from .plugin_ui import choose_dem_source, show_dem_preflight, show_error

        source = choose_dem_source(self.iface, self._parent())
        if not source:
            return None
        try:
            next_action, recommendation = show_dem_preflight(source, self._parent())
        except Exception as exc:
            show_error(self._parent(), "DEM preflight failed", exc)
            return None
        algorithm_ids = {
            "contact_sheet": "lidar_relief:visualisation_contact_sheet",
            "batch_relief": "lidar_relief:batch_relief",
        }
        if next_action in algorithm_ids:
            tool_parameters = {"INPUT": source}
            if next_action == "batch_relief":
                preset_index = BATCH_PRESET_INDEX.get(recommendation.preset_key)
                if preset_index is not None:
                    tool_parameters["PRESET"] = preset_index
            try:
                return self._run_algorithm(algorithm_ids[next_action], tool_parameters)
            except Exception as exc:
                show_error(self._parent(), "Could not open Processing tool", exc)
        return None

    def showDiagnostics(self):
        from .plugin_ui import show_diagnostics, show_error

        try:
            return show_diagnostics(self._parent())
        except Exception as exc:
            show_error(self._parent(), "Dependency diagnostics failed", exc)
            return None

    def openRecentRecipe(self):
        from .plugin_ui import choose_recent

        recipe = choose_recent(
            recent_recipes(), "LiDAR Relief — Recent recipes", self._parent()
        )
        if recipe:
            return self._run_algorithm("lidar_relief:recipe_import", {"INPUT": recipe})
        return None

    def openRecentOutputFolder(self):
        from .plugin_ui import choose_recent, open_local_path

        folder = choose_recent(
            recent_output_folders(),
            "LiDAR Relief — Recent output folders",
            self._parent(),
        )
        return open_local_path(folder) if folder else False

    def rememberOutputFolder(self):
        from .plugin_ui import choose_output_folder

        folder = choose_output_folder(self._parent())
        if folder:
            record_output_folder(folder)
        return folder

    def _available_algorithms(self):
        if self.provider is None:
            return []
        return sorted(
            (
                (f"{self.provider.id()}:{algorithm.name()}", algorithm.displayName())
                for algorithm in self.provider.algorithms()
            ),
            key=lambda item: item[1].casefold(),
        )

    def openFavorite(self):
        from .plugin_ui import choose_favorite

        labels = dict(self._available_algorithms())
        tools = [(item, labels.get(item, item)) for item in favorite_algorithms()]
        selected = choose_favorite(tools, favorite_recipes(), self._parent())
        if not selected:
            return None
        kind, value = selected
        if kind == "recipe":
            return self._run_algorithm("lidar_relief:recipe_import", {"INPUT": value})
        parameters = {}
        source = self._active_dem()
        if source:
            parameters["INPUT"] = source
        return self._run_algorithm(value, parameters)

    def manageFavorites(self):
        from .plugin_ui import manage_favorites_dialog

        result = manage_favorites_dialog(
            self._available_algorithms(),
            recent_recipes(),
            (favorite_algorithms(), favorite_recipes()),
            self._parent(),
        )
        if result is not None:
            set_favorite_algorithms(result[0])
            set_favorite_recipes(result[1])
        return result

    def manageRecentItems(self):
        from .plugin_ui import manage_recent_dialog

        recipes = recent_recipes()
        outputs = recent_output_folders()
        result = manage_recent_dialog(recipes, outputs, self._parent())
        if result is None:
            return None
        kept_recipes, kept_outputs = map(set, result)
        clear_recent_recipes()
        clear_recent_output_folders()
        for recipe in reversed(recipes):
            if recipe in kept_recipes:
                from .recent_items import record_recent_recipe

                record_recent_recipe(recipe)
        for folder in reversed(outputs):
            if folder in kept_outputs:
                record_output_folder(folder)
        return result

    def compareRasters(self):
        from .plugin_ui import show_raster_comparison

        return show_raster_comparison(self.iface, self._parent())

    def recordInterpretationNote(self):
        from qgis.core import (
            QgsCoordinateReferenceSystem,
            QgsCoordinateTransform,
            QgsProject,
        )

        from .interpretation_notes import (
            create_interpretation_note,
            write_interpretation_notes,
        )
        from .plugin_ui import (
            choose_interpretation_output,
            interpretation_note_dialog,
            show_error,
        )

        active_layer = self.iface.activeLayer()
        visualization = active_layer.name() if active_layer is not None else ""
        values = interpretation_note_dialog(visualization, self._parent())
        if values is None:
            return None
        output_path = choose_interpretation_output(self._parent())
        if not output_path:
            return None
        try:
            canvas = self.iface.mapCanvas()
            transform = QgsCoordinateTransform(
                canvas.mapSettings().destinationCrs(),
                QgsCoordinateReferenceSystem("EPSG:4326"),
                QgsProject.instance(),
            )
            point = transform.transform(canvas.center())
            note = create_interpretation_note(
                longitude=point.x(),
                latitude=point.y(),
                **values,
            )
            write_interpretation_notes([note], output_path)
            record_output_folder(output_path)
            return output_path
        except Exception as exc:
            show_error(self._parent(), "Could not save interpretation note", exc)
            return None

    def manageStudyBookmarks(self):
        from qgis.core import (
            QgsCoordinateReferenceSystem,
            QgsRectangle,
            QgsReferencedRectangle,
        )

        from .plugin_ui import show_error, study_bookmark_dialog
        from .study_bookmarks import (
            list_bookmarks,
            remove_bookmark,
            rename_bookmark,
            save_bookmark,
        )

        bookmarks = list_bookmarks()
        command = study_bookmark_dialog(bookmarks, self._parent())
        if not command:
            return None
        try:
            canvas = self.iface.mapCanvas()
            if command[0] == "save":
                extent = canvas.extent()
                crs = canvas.mapSettings().destinationCrs()
                save_bookmark(
                    command[1],
                    (
                        extent.xMinimum(),
                        extent.yMinimum(),
                        extent.xMaximum(),
                        extent.yMaximum(),
                    ),
                    crs.authid() or crs.toWkt(),
                )
            elif command[0] == "rename":
                rename_bookmark(command[1], command[2])
            elif command[0] == "remove":
                remove_bookmark(command[1])
            else:
                bookmark = next(
                    item for item in bookmarks if item["name"] == command[1]
                )
                crs = QgsCoordinateReferenceSystem(bookmark["crs"])
                if not crs.isValid():
                    crs.createFromWkt(bookmark["crs"])
                canvas.setReferencedExtent(
                    QgsReferencedRectangle(
                        QgsRectangle(*bookmark["extent"]),
                        crs,
                    )
                )
                canvas.refresh()
            return command
        except Exception as exc:
            show_error(self._parent(), "Study area bookmark failed", exc)
            return None

    def createSupportBundle(self):
        from qgis.core import Qgis

        from .dem_preflight import analyse_dem, format_preflight, recommend_workflow
        from .diagnostics import format_diagnostics
        from .plugin_ui import choose_support_bundle_output, show_error
        from .support_bundle import create_support_bundle
        from .version import get_version

        output_path = choose_support_bundle_output(self._parent())
        if not output_path:
            return None
        try:
            preflight = ""
            source = self._active_dem()
            if source:
                summary = analyse_dem(source)
                preflight = format_preflight(summary, recommend_workflow(summary))
            create_support_bundle(
                output_path,
                diagnostics=format_diagnostics(qgis_version=Qgis.QGIS_VERSION),
                plugin_version=get_version(),
                preflight=preflight,
            )
            record_output_folder(output_path)
            return output_path
        except Exception as exc:
            show_error(self._parent(), "Support bundle failed", exc)
            return None

    def openUserGuide(self):
        from .plugin_ui import open_local_path, show_error

        guide = os.path.join(os.path.dirname(__file__), "USER_GUIDE.md")
        if not open_local_path(guide):
            show_error(self._parent(), "Could not open user guide", guide)

    def showContextHelp(self):
        """Open the contextual-help introduction and preference control."""
        return show_context_help(self._parent())

    def unload(self):
        """Unregister the Processing provider on plugin unload."""
        self._loaded = False
        if self.iface is not None:
            for action in self.menu_actions:
                self.iface.removePluginMenu(MENU_LABEL, action)
                action.deleteLater()
        self.menu_actions = []
        self.context_help_action = None
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
