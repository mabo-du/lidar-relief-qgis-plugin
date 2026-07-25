"""provider.py — QGIS Processing provider for LiDAR Relief plugin.
exports: LidarReliefProvider
used_by: __init__.py → initProcessing (plugin entry point)
rules:
  provider id must be 'lidar_relief'
  provider name must be 'LiDAR Relief'
  loadAlgorithms registers all algorithm classes
"""

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .algorithms.hillshade_algorithm import HillshadeAlgorithm
from .algorithms.slrm_algorithm import SlrmAlgorithm
from .algorithms.svf_algorithm import SvfAlgorithm
from .algorithms.slope_algorithm import SlopeAlgorithm
from .algorithms.ruggedness_algorithm import RuggednessAlgorithm
from .algorithms.batch_algorithm import BatchAlgorithm
from .algorithms.contact_sheet_algorithm import ContactSheetAlgorithm
from .algorithms.openness_algorithm import OpennessAlgorithm
from .algorithms.mstp_algorithm import MstpAlgorithm
from .algorithms.blend_algorithm import BlendAlgorithm
from .algorithms.vat_algorithm import VatAlgorithm
from .algorithms.red_relief_algorithm import RedReliefAlgorithm
from .algorithms.local_dominance_algorithm import LocalDominanceAlgorithm
from .algorithms.asvf_algorithm import AsvfAlgorithm
from .algorithms.e4mstp_algorithm import E4MstpAlgorithm
from .algorithms.pca_algorithm import PcaAlgorithm
from .algorithms.ml_export_algorithm import MlExportAlgorithm
from .algorithms.cog_export_algorithm import CogExportAlgorithm
from .algorithms.field_export_algorithm import FieldExportAlgorithm
from .algorithms.pdf_report_algorithm import PdfReportAlgorithm
from .algorithms.provenance_algorithm import ProvenanceInspectAlgorithm
from .algorithms.recipe_io_algorithm import RecipeExportAlgorithm, RecipeImportAlgorithm
from .algorithms.csf_algorithm import CsfAlgorithm
from .algorithms.pdal_classify_algorithm import PdalClassifyAlgorithm
from .algorithms.temporal_difference_algorithm import TemporalDifferenceAlgorithm
from .algorithms.fusion_algorithm import FusionAlgorithm
from .algorithms.ai_detection_algorithm import AiDetectionAlgorithm
from .algorithms.rvt_algorithm import RvtMultidirectionalHillshadeAlgorithm
from .algorithms.rvt_openness_algorithm import RvtOpennessAlgorithm


from .algorithms.web_viewer_algorithm import WebViewerAlgorithm


class LidarReliefProvider(QgsProcessingProvider):
    """Processing provider that groups all LiDAR Relief algorithms."""

    def id(self):
        return "lidar_relief"

    def name(self):
        return "LiDAR Relief"

    def longName(self):
        return "LiDAR Relief Visualisation Tools"

    def icon(self):
        import os

        icon_path = os.path.join(os.path.dirname(__file__), "resources", "icon.png")
        return QIcon(icon_path)

    def loadAlgorithms(self):
        """Register all algorithm instances.

        Rules:
            Every new algorithm class must be added here.
        """
        self.addAlgorithm(HillshadeAlgorithm())
        self.addAlgorithm(SlrmAlgorithm())
        self.addAlgorithm(SvfAlgorithm())
        self.addAlgorithm(SlopeAlgorithm())
        self.addAlgorithm(RuggednessAlgorithm())
        self.addAlgorithm(BatchAlgorithm())
        self.addAlgorithm(ContactSheetAlgorithm())
        self.addAlgorithm(OpennessAlgorithm())
        self.addAlgorithm(MstpAlgorithm())
        self.addAlgorithm(BlendAlgorithm())
        self.addAlgorithm(VatAlgorithm())
        self.addAlgorithm(RedReliefAlgorithm())
        self.addAlgorithm(LocalDominanceAlgorithm())
        self.addAlgorithm(AsvfAlgorithm())
        self.addAlgorithm(E4MstpAlgorithm())
        self.addAlgorithm(PcaAlgorithm())
        self.addAlgorithm(MlExportAlgorithm())
        self.addAlgorithm(CogExportAlgorithm())
        self.addAlgorithm(FieldExportAlgorithm())
        self.addAlgorithm(PdfReportAlgorithm())
        self.addAlgorithm(ProvenanceInspectAlgorithm())
        self.addAlgorithm(RecipeExportAlgorithm())
        self.addAlgorithm(RecipeImportAlgorithm())
        self.addAlgorithm(CsfAlgorithm())
        self.addAlgorithm(PdalClassifyAlgorithm())
        self.addAlgorithm(TemporalDifferenceAlgorithm())
        self.addAlgorithm(FusionAlgorithm())
        self.addAlgorithm(AiDetectionAlgorithm())
        self.addAlgorithm(RvtMultidirectionalHillshadeAlgorithm())
        self.addAlgorithm(RvtOpennessAlgorithm())
        self.addAlgorithm(WebViewerAlgorithm())
