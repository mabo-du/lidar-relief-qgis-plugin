"""csf_algorithm.py — QGIS Processing wrapper for CSF ground filtering.

exports: CsfAlgorithm
used_by: provider.py → loadAlgorithms
"""

import os

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFile,
    QgsProcessingParameterEnum,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingOutputString,
    QgsProcessingException,
)

from ..point_cloud.csf_filter import (
    csf_available,
    filter_las_file,
    ARCHAEOLOGY_PRESETS,
)
from .help_mixin import HelpUrlMixin

PRESET_NAMES = list(ARCHAEOLOGY_PRESETS.keys())
PRESET_LABELS = [
    f"{name} — {ARCHAEOLOGY_PRESETS[name]['description']}" for name in PRESET_NAMES
]


class CsfAlgorithm(HelpUrlMixin, QgsProcessingAlgorithm):
    """Generate a DEM from LAS/LAZ using archaeology-tuned CSF ground filtering."""

    HELP_ANCHOR = "csf-ground-filter-laslaz-dem"

    INPUT = "INPUT"
    PRESET = "PRESET"
    CELLSIZE = "CELLSIZE"
    OUTPUT = "OUTPUT"
    OUTPUT_STATS = "OUTPUT_STATS"

    def name(self):
        return "csf_ground_filter"

    def displayName(self):
        return "CSF Ground Filter (LAS/LAZ → DEM)"

    def group(self):
        return "LiDAR Relief — Point Cloud"

    def groupId(self):
        return "lidar_relief_point_cloud"

    def shortHelpString(self):
        return (
            "Classify ground points from a LAS/LAZ point cloud using the "
            "Cloth Simulation Filter (CSF), then generate a DEM.\n\n"
            "The CSF is specifically tuned for archaeological applications — "
            "it preserves subtle earthworks that standard filters classify "
            "as noise.\n\n"
            "Four presets are available:\n"
            "  - Archaeology Fine: Maximum micro-relief preservation\n"
            "  - Archaeology Standard: Balance of vegetation removal\n"
            "    and earthwork preservation\n"
            "  - Forested: Aggressive ground detection for dense canopy\n"
            "  - Urban: Standard filtering for built-up areas"
        )

    def createInstance(self):
        return CsfAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT,
                "Input LAS/LAZ file",
                fileFilter="LiDAR data (*.las *.laz)",
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.PRESET,
                "Ground filtering preset",
                options=PRESET_LABELS,
                defaultValue=1,  # archaeology_standard
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.CELLSIZE,
                "Output DEM cell size (map units)",
                type=QgsProcessingParameterNumber.Type.Double,
                defaultValue=1.0,
                minValue=0.1,
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUTPUT,
                "Output DEM",
            )
        )
        self.addOutput(
            QgsProcessingOutputString(self.OUTPUT_STATS, "Processing statistics")
        )

    def processAlgorithm(self, parameters, context, feedback):
        if not csf_available():
            raise QgsProcessingException(
                "CSF filter requires the 'cloth-simulation-filter' package.\n\n"
                "Install it via the OSGeo4W Shell:\n"
                "  pip install cloth-simulation-filter"
            )

        las_path = self.parameterAsFile(parameters, self.INPUT, context)
        if not las_path or not os.path.exists(las_path):
            raise QgsProcessingException(f"LAS file not found: {las_path}")

        from qgis.core import QgsVectorLayer

        vlayer = QgsVectorLayer(las_path, "las", "ogr")
        if vlayer.isValid() and vlayer.featureCount() > 50000000:
            raise QgsProcessingException(
                "Point cloud is too large (> 50 million points). Please clip the data first."
            )
        elif (
            not vlayer.isValid()
            and os.path.getsize(las_path) > 1.5 * 1024 * 1024 * 1024
        ):
            raise QgsProcessingException(
                "Point cloud file is too large (> 1.5 GB). Please clip the data first."
            )

        preset_idx = self.parameterAsEnum(parameters, self.PRESET, context)
        preset = PRESET_NAMES[preset_idx]
        cellsize = self.parameterAsDouble(parameters, self.CELLSIZE, context)
        output_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        feedback.setProgressText("Processing point cloud...")

        try:
            result = filter_las_file(
                las_path=las_path,
                output_dem_path=output_path,
                preset=preset,
                cellsize=cellsize,
                feedback=feedback,
            )
        except Exception as e:
            raise QgsProcessingException(f"CSF filtering failed: {e}")

        stats = (
            f"Total points: {result['total_points']}\n"
            f"Ground points: {result['ground_points']}\n"
            f"Non-ground points: {result['offground_points']}\n"
            f"Preset: {result['preset']}\n"
            f"Cell size: {result['cellsize']}m\n"
        )
        feedback.pushInfo(stats)

        # Apply auto-styling post-processor so the output DEM is rendered
        # with a contrast stretch in QGIS, not as a raw grey raster.
        # The v2.0.4 changelog promised "output layers are now auto-styled
        # correctly" but CSF/DoD/PDAL outputs were missed.
        if context.willLoadLayerOnCompletion(output_path):
            from ..styling import ReliefLayerPostProcessor

            details = context.layerToLoadOnCompletionDetails(output_path)
            details.setPostProcessor(
                ReliefLayerPostProcessor(self.displayName(), stretch_type="stddev")
            )

        return {
            self.OUTPUT: output_path,
            self.OUTPUT_STATS: stats,
        }
