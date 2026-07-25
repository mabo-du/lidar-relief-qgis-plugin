"""provenance_algorithm.py — Inspect and verify a provenance sidecar.

exports: ProvenanceInspectAlgorithm
used_by: provider.py → loadAlgorithms
rules:
  Read-only. This algorithm never regenerates a raster — it reports what
  a record says and whether the source still matches, and leaves re-running
  to the user, who can see the parameters and set them deliberately.
  Silently re-executing an arbitrary stored parameter set would be a
  worse contract than showing the user what to do.
agent:   claude-opus-5 | anthropic | 2026-07-25 | s_20260725_001 |
         New algorithm completing the provenance feature: outputs now
         carry a sidecar, and this reads one back, prints the parameters
         needed to reproduce the result, and flags a source raster that
         has changed since the record was written.
"""

import json

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputBoolean,
    QgsProcessingOutputString,
    QgsProcessingParameterFile,
    QgsProcessingParameterRasterLayer,
)

from ..provenance import read_sidecar, verify_source


class ProvenanceInspectAlgorithm(QgsProcessingAlgorithm):
    """Show how an output was produced, and check it can be reproduced."""

    INPUT_SIDECAR = "INPUT_SIDECAR"
    SOURCE_DEM = "SOURCE_DEM"
    OUTPUT_SUMMARY = "OUTPUT_SUMMARY"
    OUTPUT_MATCHES = "OUTPUT_MATCHES"

    def name(self):
        return "inspect_provenance"

    def displayName(self):
        return "Inspect Provenance Record"

    def group(self):
        return "LiDAR Relief — Export"

    def groupId(self):
        return "lidar_relief_export"

    def shortHelpString(self):
        return (
            "Reads the provenance sidecar written beside a LiDAR Relief "
            "output and reports the plugin version, algorithm and exact "
            "parameters used to produce it.\n\n"
            "Select either the sidecar itself (*.lidar-relief.json) or the "
            "raster it describes — the sidecar sits next to it.\n\n"
            "Optionally supply the source DEM to verify it has not changed "
            "since the record was written. The check compares file size, a "
            "checksum, raster dimensions and CRS, so you can tell whether "
            "re-running the recorded parameters would actually reproduce "
            "the result.\n\n"
            "Useful for archive deposit, CIfA-compliant reporting, and "
            "picking up someone else's analysis months later."
        )

    def createInstance(self):
        return ProvenanceInspectAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT_SIDECAR,
                "Provenance sidecar, or the output file it describes",
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.SOURCE_DEM,
                "Source DEM to verify against (optional)",
                optional=True,
            )
        )
        self.addOutput(
            QgsProcessingOutputString(self.OUTPUT_SUMMARY, "Provenance summary")
        )
        self.addOutput(
            QgsProcessingOutputBoolean(self.OUTPUT_MATCHES, "Source matches the record")
        )

    def processAlgorithm(self, parameters, context, feedback):
        sidecar_input = self.parameterAsFile(parameters, self.INPUT_SIDECAR, context)
        source_layer = self.parameterAsRasterLayer(parameters, self.SOURCE_DEM, context)

        try:
            record = read_sidecar(sidecar_input)
        except (FileNotFoundError, ValueError) as e:
            raise QgsProcessingException(str(e))

        lines = self._format_record(record)
        matches = True

        if source_layer is not None:
            differences = verify_source(record, source_layer.source())
            lines.append("")
            if differences:
                matches = False
                lines.append("SOURCE VERIFICATION: MISMATCH")
                lines.extend(f"  - {d}" for d in differences)
                lines.append(
                    "  Re-running the recorded parameters on this DEM will "
                    "NOT reproduce the original output."
                )
                for difference in differences:
                    feedback.pushWarning(f"Provenance mismatch: {difference}")
            else:
                lines.append("SOURCE VERIFICATION: MATCH")
                lines.append(
                    "  The DEM is unchanged, so the recorded parameters "
                    "should reproduce the original output."
                )

        summary = "\n".join(lines)
        feedback.pushInfo(summary)

        return {
            self.OUTPUT_SUMMARY: summary,
            self.OUTPUT_MATCHES: matches,
        }

    @staticmethod
    def _format_record(record: dict) -> list:
        """Render a record as readable lines for the Processing log."""
        generator = record.get("generator", {})
        algorithm = record.get("algorithm", {})
        source = record.get("source", {})
        raster = source.get("raster", {})
        checksum = source.get("checksum", {})

        lines = [
            "LiDAR Relief provenance record",
            "=" * 46,
            f"Created:    {record.get('created_utc', 'unknown')}",
            f"Plugin:     {generator.get('plugin', '?')} "
            f"{generator.get('version', '?')}",
            f"Algorithm:  {algorithm.get('name', '?')} ({algorithm.get('id', '?')})",
        ]

        if source:
            lines.append("")
            lines.append("Source")
            lines.append(f"  path:      {source.get('path', 'unknown')}")
            if raster:
                lines.append(
                    f"  grid:      {raster.get('width')} x {raster.get('height')} px"
                )
                lines.append(
                    f"  cell size: {raster.get('cell_size_x')} x "
                    f"{raster.get('cell_size_y')}"
                )
                lines.append(f"  CRS:       {raster.get('crs_authority') or 'none'}")
            if checksum:
                scope = "whole file" if checksum.get("complete") else "prefix"
                lines.append(
                    f"  checksum:  {checksum.get('algorithm')} "
                    f"{str(checksum.get('value'))[:16]}... ({scope})"
                )

        lines.append("")
        lines.append("Parameters used")
        parameters = record.get("parameters", {})
        if parameters:
            for key in sorted(parameters):
                lines.append(f"  {key}: {json.dumps(parameters[key])}")
        else:
            lines.append("  (none recorded)")

        return lines
