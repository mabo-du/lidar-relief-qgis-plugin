"""provenance_mixin.py — Shared provenance recording for Processing algorithms.

exports: ProvenanceMixin
used_by: algorithms/svf_algorithm.py, algorithms/openness_algorithm.py,
         algorithms/slrm_algorithm.py, algorithms/asvf_algorithm.py,
         algorithms/ruggedness_algorithm.py, algorithms/slope_algorithm.py,
         algorithms/hillshade_algorithm.py

rules:
  Mix in BEFORE QgsProcessingAlgorithm so the helper resolves first.
  record_provenance must never raise — it is called after the real work
  is finished and an exception there would discard a completed result.
  Record RESOLVED parameters, not raw dialog values: the pixel radius
  that was actually computed, not just the metres the user typed.
  Otherwise the record cannot be replayed on a different DEM.
agent:   claude-opus-5 | anthropic | 2026-07-25 | s_20260725_001 |
         New mixin so every raster algorithm records how its output was
         made without each wrapper growing its own copy of the logic.
"""

from ..provenance import build_record, write_sidecar_safe


class ProvenanceMixin:
    """Adds a one-call provenance sidecar to a Processing algorithm."""

    def record_provenance(
        self,
        output_path: str,
        parameters: dict,
        source_path: str = None,
        feedback=None,
        extra: dict = None,
    ):
        """Write a sidecar describing this run.

        Args:
            output_path: The file that was produced.
            parameters: Resolved parameter values (see module rules).
            source_path: Input raster path, if there was one.
            feedback: Optional QGIS feedback object.
            extra: Extra fields to merge into the record.

        Returns:
            The sidecar path, or ``None`` if it could not be written.
        """
        if not output_path:
            return None
        try:
            record = build_record(
                algorithm_id=self.name(),
                algorithm_name=self.displayName(),
                parameters=parameters,
                source_path=source_path,
                output_path=output_path,
                extra=extra,
            )
        except Exception:
            # build_record touches GDAL and the filesystem; a failure here
            # must not cost the user their finished raster.
            return None
        return write_sidecar_safe(output_path, record, feedback)
