"""cog_export_algorithm.py — QGIS Processing wrapper for COG Web Export.

exports: CogExportAlgorithm
used_by: provider.py → loadAlgorithms

rules:
  Takes an existing raster layer and converts to Cloud-Optimized GeoTIFF.
  Optionally generates an interactive MapLibre HTML viewer alongside.
  All dependencies are optional — clear error if rio-cogeo not installed.
"""

import os

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterString,
    QgsProcessingParameterFileDestination,
    QgsProcessingOutputString,
    QgsProcessingException,
)

from ..export.cog_exporter import convert_to_cog, cog_is_supported
from ..export.web_viewer import generate_web_viewer
from .help_mixin import HelpUrlMixin

# Available COG compression profiles
COG_PROFILES = ["deflate", "lzw", "zstd", "raw"]


class CogExportAlgorithm(HelpUrlMixin, QgsProcessingAlgorithm):
    """Export a raster to Cloud-Optimized GeoTIFF (COG) with optional
    interactive web viewer."""

    HELP_ANCHOR = "export-to-cloud-optimized-geotiff-cog"

    INPUT = "INPUT"
    COG_PROFILE = "COG_PROFILE"
    OVERVIEW_RESAMPLING = "OVERVIEW_RESAMPLING"
    GENERATE_VIEWER = "GENERATE_VIEWER"
    VIEWER_TITLE = "VIEWER_TITLE"
    VIEWER_DARK = "VIEWER_DARK"
    OUTPUT_COG = "OUTPUT_COG"
    OUTPUT_VIEWER_DIR = "OUTPUT_VIEWER_DIR"
    OUTPUT_VALIDATION = "OUTPUT_VALIDATION"

    RESAMPLING_METHODS = ["nearest", "bilinear", "cubic", "average", "lanczos"]

    def name(self):
        return "cog_export"

    def displayName(self):
        return "Export to Cloud-Optimized GeoTIFF (COG)"

    def group(self):
        return "LiDAR Relief — Export"

    def groupId(self):
        return "lidar_relief_export"

    def shortHelpString(self):
        return (
            "Converts any raster to a Cloud-Optimized GeoTIFF (COG) for "
            "efficient web delivery.\n\n"
            "Optionally generates an interactive MapLibre GL JS web viewer "
            "that can be uploaded to GitHub Pages or any static hosting.\n\n"
            "COGs can be streamed efficiently over HTTP without a tile server."
        )

    def createInstance(self):
        return CogExportAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterRasterLayer(self.INPUT, "Input raster layer")
        )

        self.addParameter(
            QgsProcessingParameterEnum(
                self.COG_PROFILE,
                "COG compression profile",
                options=COG_PROFILES,
                defaultValue=0,  # deflate
            )
        )

        self.addParameter(
            QgsProcessingParameterEnum(
                self.OVERVIEW_RESAMPLING,
                "Overview resampling method",
                options=self.RESAMPLING_METHODS,
                defaultValue=1,  # bilinear
            )
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.GENERATE_VIEWER,
                "Generate interactive web viewer (HTML + config)",
                defaultValue=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterString(
                self.VIEWER_TITLE,
                "Web viewer title",
                defaultValue="LiDAR Relief Visualization",
                optional=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.VIEWER_DARK,
                "Use dark theme for web viewer",
                defaultValue=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_COG,
                "Output Cloud-Optimized GeoTIFF",
                fileFilter="GeoTIFF (*.tif)",
            )
        )

        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_VIEWER_DIR,
                "Output directory for web viewer (optional)",
                fileFilter="Directory (*)",
                optional=True,
            )
        )

        self.addOutput(
            QgsProcessingOutputString(self.OUTPUT_VALIDATION, "COG validation result")
        )

    def processAlgorithm(self, parameters, context, feedback):
        # Check if rio-cogeo is available
        if not cog_is_supported():
            raise QgsProcessingException(
                "Cloud-Optimized GeoTIFF export requires 'rio-cogeo'.\n\n"
                "Install it via the OSGeo4W Shell:\n"
                "  pip install rio-cogeo\n\n"
                "Restart QGIS after installation."
            )

        source = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException("No input raster layer specified.")
        if source.width() * source.height() > 50000 * 50000:
            raise QgsProcessingException(
                "Raster is too large (> 2.5 billion pixels). Please clip the raster first."
            )

        cog_profile_idx = self.parameterAsEnum(parameters, self.COG_PROFILE, context)
        resampling_idx = self.parameterAsEnum(
            parameters, self.OVERVIEW_RESAMPLING, context
        )
        generate_viewer = self.parameterAsBoolean(
            parameters, self.GENERATE_VIEWER, context
        )
        viewer_title = self.parameterAsString(parameters, self.VIEWER_TITLE, context)
        viewer_dark = self.parameterAsBoolean(parameters, self.VIEWER_DARK, context)

        output_cog_path = self.parameterAsFileOutput(
            parameters, self.OUTPUT_COG, context
        )
        output_viewer_dir = self.parameterAsFileOutput(
            parameters, self.OUTPUT_VIEWER_DIR, context
        )

        # Use default viewer dir next to COG if not specified
        if not output_viewer_dir:
            output_viewer_dir = os.path.dirname(output_cog_path)

        source_path = source.source()
        profile_name = COG_PROFILES[cog_profile_idx]
        resampling = self.RESAMPLING_METHODS[resampling_idx]

        feedback.setProgressText("Converting to Cloud-Optimized GeoTIFF...")

        # Convert to COG
        try:
            cog_result = convert_to_cog(
                input_path=source_path,
                output_path=output_cog_path,
                profile=profile_name,
                overview_resampling=resampling,
            )
        except Exception as e:
            raise QgsProcessingException(f"COG conversion failed: {e}")

        # Validate
        if not cog_result.get("valid", False):
            feedback.pushWarning(
                "COG validation produced warnings — file may not be fully optimized."
            )

        feedback.pushInfo(
            f"COG created: {cog_result['size_bytes'] / 1024:.0f} KB, "
            f"profile={cog_result['profile']}"
        )

        # Generate web viewer
        viewer_result = {}
        if generate_viewer:
            feedback.setProgressText("Generating interactive web viewer...")

            try:
                viewer_result = generate_web_viewer(
                    cog_path=output_cog_path,
                    output_dir=output_viewer_dir,
                    title=viewer_title or "LiDAR Relief Visualization",
                    dark_mode=viewer_dark,
                    attribution="LiDAR Relief Visualization QGIS Plugin",
                )
                feedback.pushInfo(
                    f"Web viewer generated: {viewer_result['index_html']}"
                )
            except Exception as e:
                feedback.reportError(f"Web viewer generation failed: {e}", False)

        # Validation string for output
        validation_info = (
            f"COG validation: {'PASSED' if cog_result.get('valid') else 'WARNINGS'}\n"
            f"Size: {cog_result['size_bytes'] / 1024:.0f} KB\n"
            f"Profile: {cog_result['profile']}\n"
        )
        if viewer_result:
            validation_info += (
                f"Web viewer: {viewer_result.get('index_html', 'N/A')}\n"
                f"Config: {viewer_result.get('config_json', 'N/A')}\n"
            )
        validation_info += (
            "\nTo publish:\n"
            "1. Upload both the .tif and the viewer folder to any static host\n"
            "   (GitHub Pages, Netlify, S3, etc.)\n"
            "2. The COG must be served via HTTPS with CORS headers\n"
            "3. Open index.html in a browser"
        )

        return {
            self.OUTPUT_COG: output_cog_path,
            self.OUTPUT_VIEWER_DIR: output_viewer_dir,
            self.OUTPUT_VALIDATION: validation_info,
        }
