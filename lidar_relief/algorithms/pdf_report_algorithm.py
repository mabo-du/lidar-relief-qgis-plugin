"""pdf_report_algorithm.py — QGIS Processing wrapper for PDF Report Generator.

exports: PdfReportAlgorithm
used_by: provider.py → loadAlgorithms
"""

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterString,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterBoolean,
    QgsProcessingException,
)

from ..export.report_generator import generate_report, reportlab_available
from ..version import get_version
from .help_mixin import HelpUrlMixin


class PdfReportAlgorithm(HelpUrlMixin, QgsProcessingAlgorithm):
    """Generate a CIfA-compliant PDF report for a raster algorithm output."""

    HELP_ANCHOR = "generate-pdf-report"

    INPUT = "INPUT"
    ALGORITHM_NAME = "ALGORITHM_NAME"
    AUTHOR = "AUTHOR"
    SITE_NAME = "SITE_NAME"
    INCLUDE_HISTOGRAM = "INCLUDE_HISTOGRAM"
    OUTPUT_PDF = "OUTPUT_PDF"

    def name(self):
        return "pdf_report"

    def displayName(self):
        return "Generate PDF Report (CIfA-compliant)"

    def group(self):
        return "LiDAR Relief — Export"

    def groupId(self):
        return "lidar_relief_export"

    def shortHelpString(self):
        return (
            "Generates a CIfA-compliant PDF report for any raster "
            "visualization output.\n\n"
            "The report includes:\n"
            "- Title page with site and processing metadata\n"
            "- Full algorithm parameter documentation\n"
            "- Input DEM metadata (CRS, resolution, extent)\n"
            "- Band statistics with percentile values\n"
            "- Optional histogram chart\n"
            "- Certification section for commercial archaeology\n"
        )

    def createInstance(self):
        return PdfReportAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT, "Input raster layer (algorithm output)"
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.ALGORITHM_NAME,
                "Algorithm name for report",
                defaultValue="",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.AUTHOR,
                "Report author / organisation",
                defaultValue="",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.SITE_NAME,
                "Site or project name",
                defaultValue="",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.INCLUDE_HISTOGRAM,
                "Include Histogram",
                defaultValue=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_PDF,
                "Output PDF report",
                fileFilter="PDF (*.pdf)",
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        if not reportlab_available():
            raise QgsProcessingException(
                "PDF report generation requires 'reportlab'.\n\n"
                "Install it via the OSGeo4W Shell:\n"
                "  pip install reportlab"
            )

        raster = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        if raster is None:
            raise QgsProcessingException("No input raster specified.")

        alg_name = self.parameterAsString(parameters, self.ALGORITHM_NAME, context)
        author = self.parameterAsString(parameters, self.AUTHOR, context)
        site_name = self.parameterAsString(parameters, self.SITE_NAME, context)
        include_histogram = self.parameterAsBoolean(
            parameters, self.INCLUDE_HISTOGRAM, context
        )
        output_path = self.parameterAsFileOutput(parameters, self.OUTPUT_PDF, context)

        if not alg_name:
            alg_name = raster.name()

        # Build metadata from raster layer
        crs = raster.crs()
        extent = raster.extent()
        meta = {
            "crs": crs.authid() if crs else "Unknown",
            "resolution": (
                f"{raster.rasterUnitsPerPixelX():.4f} × "
                f"{raster.rasterUnitsPerPixelY():.4f} map units"
            ),
            "extent": (
                extent.xMinimum(),
                extent.yMinimum(),
                extent.xMaximum(),
                extent.yMaximum(),
            ),
            "source_dem": raster.source(),
        }

        feedback.setProgressText("Computing statistics and generating PDF...")

        try:
            result = generate_report(
                raster_path=raster.source(),
                output_path=output_path,
                algorithm_name=alg_name,
                algorithm_params={},
                plugin_version=get_version(),
                metadata=meta,
                title=f"LiDAR Relief Visualization — {alg_name}",
                author=author,
                site_name=site_name,
                include_histogram=include_histogram,
                include_stats=True,
            )
        except Exception as e:
            raise QgsProcessingException(f"PDF generation failed: {e}")

        feedback.pushInfo(
            f"PDF report generated: {result['output_path']}\n"
            f"Pages: {result['page_count']}\n"
            f"Size: {result['size_bytes'] / 1024:.0f} KB"
        )

        return {self.OUTPUT_PDF: output_path}
