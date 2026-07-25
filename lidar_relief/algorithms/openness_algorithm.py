"""openness_algorithm.py — QGIS Processing wrapper for Topographic Openness.
exports: OpennessAlgorithm
used_by: provider.py → loadAlgorithms
rules:
  all raster I/O through core.raster_utils
  check feedback.isCanceled() between major steps
  USE_GPU is advisory — core.openness falls back to NumPy when
  CuPy/CUDA is missing, so this parameter must never fail a run.
agent:   claude-opus-5 | anthropic | 2026-07-25 | s_20260725_001 |
         Exposed the GPU toggle (the CuPy backend was previously
         unreachable from anywhere in the plugin).
"""

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterEnum,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
)

from ..core.raster_utils import (
    get_cell_size_from_path,
    process_in_tiles,
)
from ..core.openness import topographic_openness
from ..core.scale import RADIUS_UNIT_OPTIONS, RADIUS_UNIT_VALUES, resolve_radius
from ..styling import ReliefLayerPostProcessor
from .provenance_mixin import ProvenanceMixin


class OpennessAlgorithm(ProvenanceMixin, QgsProcessingAlgorithm):
    """Topographic Openness from a DEM raster layer."""

    INPUT = "INPUT"
    OPENNESS_TYPE = "OPENNESS_TYPE"
    NUM_DIRECTIONS = "NUM_DIRECTIONS"
    SEARCH_RADIUS = "SEARCH_RADIUS"
    RADIUS_UNITS = "RADIUS_UNITS"
    USE_GPU = "USE_GPU"
    OUTPUT = "OUTPUT"

    def name(self):
        return "topographic_openness"

    def displayName(self):
        return "Topographic Openness"

    def group(self):
        return "LiDAR Relief"

    def groupId(self):
        return "lidar_relief"

    def shortHelpString(self):
        return (
            "Generates Topographic Openness (Positive or Negative). "
            "Positive Openness highlights convex features like mounds and ridges. "
            "Negative Openness highlights concave features like pits and ditches."
        )

    def createInstance(self):
        return OpennessAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT,
                "Input DEM",
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.OPENNESS_TYPE,
                "Openness Type",
                options=["Positive (Convex)", "Negative (Concave)"],
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.NUM_DIRECTIONS,
                "Search Directions",
                options=["8 (fast)", "16 (standard)", "32 (quality)"],
                defaultValue=1,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SEARCH_RADIUS,
                "Search Radius",
                type=QgsProcessingParameterNumber.Type.Double,
                defaultValue=20,
                minValue=0.1,
                maxValue=1000,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.RADIUS_UNITS,
                "Search radius units",
                options=RADIUS_UNIT_OPTIONS,
                defaultValue=0,  # index 0 → pixels, preserving old behaviour
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.USE_GPU,
                "Use GPU acceleration (CuPy/CUDA) if available",
                defaultValue=False,
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUTPUT,
                "Openness output",
            )
        )

    @staticmethod
    def _resolve_gpu_request(requested: bool, feedback) -> bool:
        """Decide whether to run on the GPU and explain the decision.

        Rules:
            Never raise. A user who ticks the box on a machine without
            CuPy must still get their result — just on the CPU.
        """
        if not requested:
            return False

        from ..gpu.compute_backend import cupy_available

        if not cupy_available():
            feedback.pushInfo(
                "GPU acceleration requested but CuPy/CUDA is not available. "
                "Running on the CPU. To enable it, install CuPy for your "
                "CUDA version (e.g. `pip install cupy-cuda12x`) into the "
                "Python environment QGIS uses, then restart QGIS."
            )
            return False

        feedback.pushInfo("Using the CuPy GPU backend for Topographic Openness.")
        return True

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        type_idx = self.parameterAsEnum(parameters, self.OPENNESS_TYPE, context)
        dir_idx = self.parameterAsEnum(parameters, self.NUM_DIRECTIONS, context)
        radius_value = self.parameterAsDouble(parameters, self.SEARCH_RADIUS, context)
        units_idx = self.parameterAsEnum(parameters, self.RADIUS_UNITS, context)
        use_gpu = self.parameterAsBoolean(parameters, self.USE_GPU, context)
        output_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        is_negative = type_idx == 1
        num_dirs = [8, 16, 32][dir_idx]
        use_gpu = self._resolve_gpu_request(use_gpu, feedback)

        cellsize = get_cell_size_from_path(source.source())
        radius = resolve_radius(
            radius_value,
            RADIUS_UNIT_VALUES[units_idx],
            cellsize,
            "Openness search radius",
            feedback,
        )

        feedback.setProgressText(
            f"Computing Openness ({num_dirs} dirs, r={radius}) in tiles..."
        )

        process_in_tiles(
            source_path=source.source(),
            output_path=output_path,
            algorithm_func=topographic_openness,
            halo_size=radius,
            tile_size=2048,
            feedback=feedback,
            num_directions=num_dirs,
            search_radius=radius,
            is_negative=is_negative,
            use_gpu=use_gpu,
        )

        if feedback.isCanceled():
            return {}

        self.record_provenance(
            output_path,
            parameters={
                "openness_type": "negative" if is_negative else "positive",
                "num_directions": num_dirs,
                "search_radius_pixels": radius,
                "search_radius_input": radius_value,
                "radius_units": RADIUS_UNIT_VALUES[units_idx],
                "cell_size": cellsize,
                "use_gpu": use_gpu,
            },
            source_path=source.source(),
            feedback=feedback,
        )

        if context.willLoadLayerOnCompletion(output_path):
            details = context.layerToLoadOnCompletionDetails(output_path)
            details.setPostProcessor(
                ReliefLayerPostProcessor(self.displayName(), stretch_type="stddev")
            )

        return {self.OUTPUT: output_path}
