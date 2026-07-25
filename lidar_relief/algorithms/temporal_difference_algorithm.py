"""temporal_difference_algorithm.py — QGIS Processing wrapper for DoD.

exports: TemporalDifferenceAlgorithm
used_by: provider.py → loadAlgorithms
"""

import os

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFileDestination,
    QgsProcessingOutputString,
    QgsProcessingException,
)

from ..temporal.dem_difference import compute_dod, xarray_available
from .help_mixin import HelpUrlMixin


class TemporalDifferenceAlgorithm(HelpUrlMixin, QgsProcessingAlgorithm):
    """Compute a probabilistic DEM of Difference (DoD) between two DEMs."""

    HELP_ANCHOR = "multi-temporal-change-detection"

    DEM_OLD = "DEM_OLD"
    DEM_NEW = "DEM_NEW"
    RMSE_OLD = "RMSE_OLD"
    RMSE_NEW = "RMSE_NEW"
    CONFIDENCE = "CONFIDENCE"
    OUTPUT_DIR = "OUTPUT_DIR"
    OUTPUT_STATS = "OUTPUT_STATS"

    def name(self):
        return "temporal_difference"

    def displayName(self):
        return "Multi-temporal Change Detection (DEM of Difference)"

    def group(self):
        return "LiDAR Relief — Temporal"

    def groupId(self):
        return "lidar_relief_temporal"

    def shortHelpString(self):
        return (
            "Compute a probabilistic DEM of Difference (DoD) between two "
            "temporally separated DEMs of the same area.\n\n"
            "The DoD uses propagated vertical error (RMSE) to establish a "
            "Level of Detection (LoD) threshold, masking noise while "
            "revealing statistically significant elevation changes.\n\n"
            "Outputs:\n"
            "  - Signed DoD raster (metres)\n"
            "  - Significance mask (1=erosion, 2=deposition)\n"
            "  - Cut/fill volume report\n\n"
            "Requires xarray and rioxarray."
        )

    def createInstance(self):
        return TemporalDifferenceAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterRasterLayer(self.DEM_OLD, "Older DEM (baseline)")
        )
        self.addParameter(
            QgsProcessingParameterRasterLayer(self.DEM_NEW, "Newer DEM (repeat survey)")
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.RMSE_OLD,
                "Older DEM vertical RMSE (metres)",
                type=QgsProcessingParameterNumber.Type.Double,
                defaultValue=0.15,
                minValue=0.01,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.RMSE_NEW,
                "Newer DEM vertical RMSE (metres)",
                type=QgsProcessingParameterNumber.Type.Double,
                defaultValue=0.15,
                minValue=0.01,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.CONFIDENCE,
                "Confidence level (1.96=95%, 2.58=99%)",
                type=QgsProcessingParameterNumber.Type.Double,
                defaultValue=1.96,
                minValue=1.0,
                maxValue=3.5,
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_DIR,
                "Output directory",
                fileFilter="Directory (*)",
            )
        )
        self.addOutput(
            QgsProcessingOutputString(self.OUTPUT_STATS, "Change statistics")
        )

    def processAlgorithm(self, parameters, context, feedback):
        if not xarray_available():
            raise QgsProcessingException(
                "Multi-temporal analysis requires 'xarray' and 'rioxarray'.\n\n"
                "Install via OSGeo4W Shell:\n"
                "  pip install xarray rioxarray"
            )

        old_raster = self.parameterAsRasterLayer(parameters, self.DEM_OLD, context)
        new_raster = self.parameterAsRasterLayer(parameters, self.DEM_NEW, context)

        rmse_old = self.parameterAsDouble(parameters, self.RMSE_OLD, context)
        rmse_new = self.parameterAsDouble(parameters, self.RMSE_NEW, context)
        confidence = self.parameterAsDouble(parameters, self.CONFIDENCE, context)
        output_dir = self.parameterAsFileOutput(parameters, self.OUTPUT_DIR, context)

        if not output_dir:
            output_dir = os.path.join(
                os.path.dirname(old_raster.source()),
                "change_detection",
            )

        os.makedirs(output_dir, exist_ok=True)

        feedback.setProgressText("Loading and aligning DEMs...")

        try:
            result = compute_dod(
                dem_old_path=old_raster.source(),
                dem_new_path=new_raster.source(),
                output_dir=output_dir,
                rmse_old=rmse_old,
                rmse_new=rmse_new,
                confidence_level=confidence,
                project_name="temporal",
            )
        except Exception as e:
            raise QgsProcessingException(f"DoD computation failed: {e}")

        vr = result["volume_report"]
        stats = (
            f"Propagated error: {result['propagated_error']}m\n"
            f"LoD threshold: {result['threshold']}m\n"
            f"Total pixels: {result['total_pixels']:,}\n"
            f"Significant changes: {result['significant_pixels']:,} "
            f"({100 * result['significant_pixels'] / max(result['total_pixels'], 1):.1f}%)\n"
            f"  Erosion (cut): {result['negative_change_pixels']:,} pixels\n"
            f"  Deposition (fill): {result['positive_change_pixels']:,} pixels\n"
            f"Cut volume: {vr['cut_volume_m3']:,.1f} m³\n"
            f"Fill volume: {vr['fill_volume_m3']:,.1f} m³\n"
            f"Net volume: {vr['net_volume_m3']:,.1f} m³\n"
            f"\nOutputs:\n  DoD: {result['dod_path']}\n"
            f"  Mask: {result['mask_path']}\n"
        )
        feedback.pushInfo(stats)

        # Note: the v2.0.4 changelog promised "output layers are now
        # auto-styled correctly" but DoD outputs a directory containing
        # two rasters (DoD + mask), so the standard
        # ReliefLayerPostProcessor pattern (designed for a single output
        # raster) doesn't apply. The user will need to manually apply a
        # diverging colour ramp to the DoD and a categorical ramp to the
        # mask.
        feedback.pushInfo(
            "Tip: apply a diverging colour ramp (red-white-blue) to the DoD "
            "raster, and a categorical ramp (erosion=red, no change=white, "
            "deposition=blue) to the mask raster for best visualisation."
        )

        return {self.OUTPUT_DIR: output_dir, self.OUTPUT_STATS: stats}
