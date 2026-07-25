"""fusion_algorithm.py — QGIS Processing wrapper for Multi-Sensor Fusion.

exports: FusionAlgorithm
used_by: provider.py → loadAlgorithms
"""

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFile,
    QgsProcessingParameterRasterDestination,
    QgsProcessingException,
)

from ..fusion.sentinel_fusion import (
    fusion_available,
    apply_fusion_recipe,
    FUSION_RECIPES,
)
from .help_mixin import HelpUrlMixin

RECIPE_NAMES = list(FUSION_RECIPES.keys())
RECIPE_LABELS = [f"{r['name']} — {r['description']}" for r in FUSION_RECIPES.values()]


class FusionAlgorithm(HelpUrlMixin, QgsProcessingAlgorithm):
    """Fuse LiDAR relief with multispectral satellite imagery."""

    HELP_ANCHOR = "multi-sensor-fusion"

    LIDAR_LAYER = "LIDAR_LAYER"
    S2_B4_RED = "S2_B4_RED"
    S2_B3_GREEN = "S2_B3_GREEN"
    S2_B2_BLUE = "S2_B2_BLUE"
    S2_B8_NIR = "S2_B8_NIR"
    S2_B11_SWIR = "S2_B11_SWIR"
    RECIPE = "RECIPE"
    OUTPUT = "OUTPUT"

    def name(self):
        return "multi_sensor_fusion"

    def displayName(self):
        return "Multi-Sensor Fusion (LiDAR + Sentinel-2)"

    def group(self):
        return "LiDAR Relief — Fusion"

    def groupId(self):
        return "lidar_relief_fusion"

    def shortHelpString(self):
        recipe_list = "\n".join(
            f"  - {r['name']}: {r['description']}" for r in FUSION_RECIPES.values()
        )
        return (
            "Fuse LiDAR relief visualizations with Sentinel-2 multispectral "
            "bands into a single RGB composite.\n\n"
            "Available recipes:\n"
            f"{recipe_list}\n\n"
            "Note: All Sentinel-2 bands must be co-registered to the "
            "LiDAR layer's CRS and resolution before use. Use the "
            "'Co-register Bands' tool if needed."
        )

    def createInstance(self):
        return FusionAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterRasterLayer(self.LIDAR_LAYER, "LiDAR relief layer")
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.S2_B4_RED,
                "Sentinel-2 Band 4 (Red, 10m) — required",
                fileFilter="GeoTIFF (*.tif)",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.S2_B3_GREEN,
                "Sentinel-2 Band 3 (Green, 10m) — required",
                fileFilter="GeoTIFF (*.tif)",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.S2_B2_BLUE,
                "Sentinel-2 Band 2 (Blue, 10m) — optional",
                fileFilter="GeoTIFF (*.tif)",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.S2_B8_NIR,
                "Sentinel-2 Band 8 (NIR, 10m) — optional",
                fileFilter="GeoTIFF (*.tif)",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.S2_B11_SWIR,
                "Sentinel-2 Band 11 (SWIR, 20m) — optional",
                fileFilter="GeoTIFF (*.tif)",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.RECIPE,
                "Fusion recipe",
                options=RECIPE_LABELS,
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(self.OUTPUT, "Fused output")
        )

    def processAlgorithm(self, parameters, context, feedback):
        if not fusion_available():
            raise QgsProcessingException(
                "Multi-sensor fusion requires 'rasterio' and 'rioxarray'."
            )

        lidar = self.parameterAsRasterLayer(parameters, self.LIDAR_LAYER, context)
        recipe_idx = self.parameterAsEnum(parameters, self.RECIPE, context)
        recipe_name = RECIPE_NAMES[recipe_idx]

        # Collect provided S2 band paths
        s2_paths = {}
        for param_name, band_name in [
            (self.S2_B4_RED, "B4"),
            (self.S2_B3_GREEN, "B3"),
            (self.S2_B2_BLUE, "B2"),
            (self.S2_B8_NIR, "B8"),
            (self.S2_B11_SWIR, "B11"),
        ]:
            path = self.parameterAsFile(parameters, param_name, context)
            if path:
                s2_paths[band_name] = path

        output_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        feedback.setProgressText(f"Applying fusion recipe: {recipe_name}...")

        try:
            result = apply_fusion_recipe(
                lidar_path=lidar.source(),
                s2_paths=s2_paths,
                recipe_name=recipe_name,
                output_path=output_path,
            )
        except Exception as e:
            raise QgsProcessingException(f"Fusion failed: {e}")

        feedback.pushInfo(
            f"Fusion complete: {result['output_path']}\n"
            f"Recipe: {result['recipe']}\n"
            f"Blend: {result['blend_mode']}\n"
            f"Bands: {', '.join(result['bands_used'])}"
        )

        return {self.OUTPUT: output_path}
