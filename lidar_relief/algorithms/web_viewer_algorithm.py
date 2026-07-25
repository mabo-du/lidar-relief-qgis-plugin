"""web_viewer_algorithm.py — Standalone Web Viewer Export Algorithm.

exports: WebViewerAlgorithm
used_by: provider.py
rules:
  - Provide a standalone entry point for regenerating the MapLibre web viewer.
  - Properly auto-detect the center if explicit coordinates are not provided.
  - Warn if input is not a valid COG.
  - Handle safe copy of COG if output directory differs from input.
"""

import os
import shutil

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterString,
    QgsProcessingParameterNumber,
    QgsProcessingParameterBoolean,
    QgsProcessingException,
)
from qgis.PyQt.QtGui import QIcon

from ..export.web_viewer import generate_web_viewer
from ..export.cog_exporter import validate_cog
from .help_mixin import HelpUrlMixin


class WebViewerAlgorithm(HelpUrlMixin, QgsProcessingAlgorithm):
    """Standalone algorithm to generate a 3D Web Viewer from an existing COG."""

    INPUT = "INPUT"
    OUTPUT_DIR = "OUTPUT_DIR"
    TITLE = "TITLE"
    DESCRIPTION = "DESCRIPTION"
    CENTER_LON = "CENTER_LON"
    CENTER_LAT = "CENTER_LAT"
    ZOOM = "ZOOM"
    DARK_MODE = "DARK_MODE"
    OPACITY = "OPACITY"

    def group(self):
        return "LiDAR Relief — Export"

    def groupId(self):
        return "lidar_relief_export"

    def name(self):
        return "webviewer"

    def displayName(self):
        return "Export Web Viewer"

    def shortHelpString(self):
        return (
            "Generates an interactive MapLibre 3D Web Viewer for an existing "
            "Cloud-Optimized GeoTIFF (COG).\n\n"
            "This standalone tool is useful if you already have a COG and want "
            "to create or customize a viewer without re-exporting the raster.\n\n"
            "Leave the center coordinates blank to auto-detect the map center "
            "from the raster bounds."
        )

    def icon(self):
        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "resources", "icon.png"
        )
        return QIcon(icon_path)

    def createInstance(self):
        return WebViewerAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT, "Input Cloud Optimized GeoTIFF (COG)"
            )
        )
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_DIR,
                "Output Directory (Optional, defaults to COG folder)",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.TITLE, "Map Title", defaultValue="LiDAR Relief Viewer"
            )
        )
        self.addParameter(
            QgsProcessingParameterString(self.DESCRIPTION, "Description", optional=True)
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.CENTER_LON,
                "Center Longitude (Leave blank to auto-detect)",
                type=QgsProcessingParameterNumber.Type.Double,
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.CENTER_LAT,
                "Center Latitude (Leave blank to auto-detect)",
                type=QgsProcessingParameterNumber.Type.Double,
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.ZOOM,
                "Initial Zoom Level",
                type=QgsProcessingParameterNumber.Type.Double,
                defaultValue=12.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.DARK_MODE, "Dark Mode Theme", defaultValue=True
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.OPACITY,
                "Layer Opacity (0.0 - 1.0)",
                type=QgsProcessingParameterNumber.Type.Double,
                defaultValue=1.0,
                minValue=0.0,
                maxValue=1.0,
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        layer = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        if layer is None:
            raise QgsProcessingException("Invalid input raster layer")

        source_path = layer.source()
        if not source_path or not os.path.isfile(source_path):
            raise QgsProcessingException("Input layer must be a file-based raster.")

        # 1. Output Directory Fallback
        output_dir = self.parameterAsString(parameters, self.OUTPUT_DIR, context)
        if not output_dir:
            output_dir = os.path.dirname(source_path)

        os.makedirs(output_dir, exist_ok=True)

        # 2. Extract configuration
        title = self.parameterAsString(parameters, self.TITLE, context)
        description = self.parameterAsString(parameters, self.DESCRIPTION, context)
        zoom = self.parameterAsDouble(parameters, self.ZOOM, context)
        dark_mode = self.parameterAsBoolean(parameters, self.DARK_MODE, context)
        opacity = self.parameterAsDouble(parameters, self.OPACITY, context)

        # 3. Handle Center coordinates safely (P4.2)
        lon_raw = parameters.get(self.CENTER_LON)
        lat_raw = parameters.get(self.CENTER_LAT)

        # Check raw parameter dict for None or empty string to ensure explicit passing
        if lon_raw not in (None, "") and lat_raw not in (None, ""):
            center = (
                self.parameterAsDouble(parameters, self.CENTER_LON, context),
                self.parameterAsDouble(parameters, self.CENTER_LAT, context),
            )
        else:
            center = None

        # 4. COG Validation
        validation_result = validate_cog(source_path)
        if not validation_result.get("valid", False):
            error_msg = validation_result.get("error")
            if not error_msg:
                reasons = []
                if not validation_result.get("tiled", True):
                    reasons.append("not tiled")
                max_dim = max(
                    validation_result.get("width", 0),
                    validation_result.get("height", 0),
                )
                if max_dim > 1024 and validation_result.get("overview_count", 1) == 0:
                    reasons.append("missing overviews")
                error_msg = (
                    " and ".join(reasons)
                    if reasons
                    else "does not meet COG requirements"
                )

            feedback.pushWarning(
                f"Input raster is not a valid COG: {error_msg}. "
                "The web viewer may be slow, broken, or fail to load. "
                "It is highly recommended to use the COG Export algorithm first."
            )

        # 5. File Co-location logic (P4.3)
        dest_path = os.path.join(output_dir, os.path.basename(source_path))
        if os.path.abspath(dest_path) != os.path.abspath(source_path):
            # Refuse to silently overwrite an existing file at dest_path.
            # Previously shutil.copy2 would clobber any existing file
            # without warning — a data-loss risk if the user pointed
            # the output directory at a folder containing important data.
            if os.path.exists(dest_path):
                raise QgsProcessingException(
                    f"A file already exists at the destination path: {dest_path}. "
                    f"Remove it or choose a different output directory. "
                    f"(The plugin refuses to silently overwrite files.)"
                )
            feedback.pushInfo(f"Copying COG to output directory: {output_dir}")
            shutil.copy2(source_path, dest_path)

        # 6. Generate Viewer
        feedback.pushInfo("Generating web viewer...")
        results = generate_web_viewer(
            cog_path=dest_path,
            output_dir=output_dir,
            title=title,
            description=description,
            center=center,
            zoom=zoom,
            dark_mode=dark_mode,
            opacity=opacity,
        )

        feedback.pushInfo(
            f"Web viewer generated successfully at: {results['index_html']}"
        )
        return {"OUTPUT_DIR": output_dir, "INDEX_HTML": results["index_html"]}
