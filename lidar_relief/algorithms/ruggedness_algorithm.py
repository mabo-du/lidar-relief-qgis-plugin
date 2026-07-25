"""QGIS Processing wrapper for Terrain Ruggedness Index."""

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
)

from ..core.raster_utils import process_in_tiles
from ..core.ruggedness import compute_ruggedness
from ..styling import ReliefLayerPostProcessor
from .provenance_mixin import ProvenanceMixin


class RuggednessAlgorithm(ProvenanceMixin, QgsProcessingAlgorithm):
    """Riley 3x3 Terrain Ruggedness Index."""

    INPUT = "INPUT"
    OUTPUT = "OUTPUT"

    def name(self):
        return "terrain_ruggedness_index"

    def displayName(self):
        return "Terrain Ruggedness Index (TRI)"

    def group(self):
        return "LiDAR Relief"

    def groupId(self):
        return "lidar_relief"

    def shortHelpString(self):
        return (
            "Computes the Riley 3×3 Terrain Ruggedness Index from a DEM. "
            "Higher values identify stronger local elevation contrasts, "
            "helping reveal scarps, banks, stone spreads, quarrying, rough "
            "ground, and other microtopographic changes. Output values use "
            "the DEM's elevation units and are sensitive to raster resolution."
        )

    def createInstance(self):
        return RuggednessAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(self.INPUT, "Input DEM"))
        self.addParameter(
            QgsProcessingParameterRasterDestination(self.OUTPUT, "TRI output")
        )

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        output_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        feedback.setProgressText("Computing Terrain Ruggedness Index in tiles...")
        process_in_tiles(
            source_path=source.source(),
            output_path=output_path,
            algorithm_func=compute_ruggedness,
            halo_size=1,
            tile_size=2048,
            feedback=feedback,
        )

        if feedback.isCanceled():
            return {}

        self.record_provenance(
            output_path,
            parameters={"method": "riley_3x3"},
            source_path=source.source(),
            feedback=feedback,
        )

        if context.willLoadLayerOnCompletion(output_path):
            details = context.layerToLoadOnCompletionDetails(output_path)
            details.setPostProcessor(
                ReliefLayerPostProcessor(self.displayName(), stretch_type="stddev")
            )
        return {self.OUTPUT: output_path}
