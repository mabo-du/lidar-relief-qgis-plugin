"""contact_sheet_algorithm.py — QGIS wrapper for the visualisation contact sheet.

exports: ContactSheetAlgorithm
used_by: provider.py → loadAlgorithms
rules:
  Preview only. The DEM is downsampled before any visualisation runs, so
  the sheet returns in seconds; the panels are for CHOOSING a technique,
  never for measurement or interpretation.
  Each panel is stretched independently, so brightness is not comparable
  between panels — only structure is.
agent:   claude-opus-5 | anthropic | 2026-07-25 | s_20260725_001 |
         New algorithm. The plugin had 29 visualisations and no way to
         compare them short of running each one and toggling layers,
         even though the README tells users comparison is the workflow.
"""

import os

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterLayer,
)

from ..core.raster_utils import read_dem_downsampled
from ..export.contact_sheet import (
    build_contact_sheet,
    compute_panels,
    pillow_available,
    visualisation_names,
    write_png,
)
from .help_mixin import HelpUrlMixin


class ContactSheetAlgorithm(HelpUrlMixin, QgsProcessingAlgorithm):
    """Compare several relief visualisations side by side in one image."""

    HELP_ANCHOR = "visualisation-contact-sheet"

    INPUT = "INPUT"
    VISUALISATIONS = "VISUALISATIONS"
    MAX_DIMENSION = "MAX_DIMENSION"
    COLUMNS = "COLUMNS"
    OUTPUT = "OUTPUT"

    # Sensible starting set: one shading, one detrend, one horizon
    # measure, one gradient — the four families a user is choosing between.
    _DEFAULT_SELECTION = [0, 1, 2, 5]

    def name(self):
        return "visualisation_contact_sheet"

    def displayName(self):
        return "Visualisation Contact Sheet"

    def group(self):
        return "LiDAR Relief"

    def groupId(self):
        return "lidar_relief"

    def shortHelpString(self):
        return (
            "Renders several relief visualisations of the same DEM as one "
            "labelled multi-panel PNG, so you can see which technique reveals "
            "the features you are looking for before committing to a full-"
            "resolution run.\n\n"
            "The DEM is downsampled first, so the sheet returns in seconds "
            "even for a large tile. Panels are a visual aid for CHOOSING a "
            "visualisation — they are previews, not analytical output, and "
            "each panel is contrast-stretched independently, so brightness "
            "is not comparable between panels.\n\n"
            "Interpretation should always be done on full-resolution output, "
            "and potential features validated against complementary evidence."
        )

    def createInstance(self):
        return ContactSheetAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT,
                "Input DEM",
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.VISUALISATIONS,
                "Visualisations to include",
                options=visualisation_names(),
                allowMultiple=True,
                defaultValue=self._DEFAULT_SELECTION,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MAX_DIMENSION,
                "Preview size (longest side, pixels)",
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=600,
                minValue=100,
                maxValue=4000,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.COLUMNS,
                "Panels per row",
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=3,
                minValue=1,
                maxValue=6,
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT,
                "Contact sheet",
                fileFilter="PNG image (*.png)",
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        selected = self.parameterAsEnums(parameters, self.VISUALISATIONS, context)
        max_dimension = self.parameterAsInt(parameters, self.MAX_DIMENSION, context)
        columns = self.parameterAsInt(parameters, self.COLUMNS, context)
        output_path = self.parameterAsFileOutput(parameters, self.OUTPUT, context)

        if not selected:
            raise QgsProcessingException(
                "Select at least one visualisation to include in the sheet."
            )

        names = visualisation_names()
        chosen = [names[i] for i in selected if 0 <= i < len(names)]

        feedback.setProgressText(
            f"Reading DEM at preview resolution (max {max_dimension} px)..."
        )
        dem, cellsize = read_dem_downsampled(source.source(), max_dimension)
        feedback.pushInfo(
            f"Preview grid: {dem.shape[1]} x {dem.shape[0]} px at "
            f"{cellsize:.2f} m per cell."
        )

        if not pillow_available():
            feedback.pushInfo(
                "Pillow is not installed, so panels will be unlabelled. They "
                "appear in the order listed in the algorithm dialog. Install "
                "it with `pip install Pillow` for captions."
            )

        panels = compute_panels(dem, cellsize, chosen, feedback)

        if feedback.isCanceled():
            return {}

        if not panels:
            raise QgsProcessingException(
                "No visualisation could be computed — check the Processing log "
                "for the reason each one was skipped."
            )

        feedback.setProgressText("Assembling contact sheet...")
        label_height = 22 if pillow_available() else 0
        sheet = build_contact_sheet(panels, columns=columns, label_height=label_height)

        if not output_path.lower().endswith(".png"):
            output_path = f"{os.path.splitext(output_path)[0]}.png"

        write_png(sheet, output_path)
        feedback.pushInfo(
            f"Wrote {len(panels)}-panel contact sheet ({sheet.shape[1]} x "
            f"{sheet.shape[0]} px) to {output_path}"
        )

        return {self.OUTPUT: output_path}
