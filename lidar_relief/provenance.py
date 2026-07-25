"""provenance.py — Write and read the sidecar that records how an output was made.

exports: SIDECAR_SUFFIX, PROVENANCE_VERSION,
         build_record(algorithm_id, parameters, source_path, output_path, **extra) -> dict,
         write_sidecar(output_path, record) -> str,
         read_sidecar(path) -> dict,
         sidecar_path_for(output_path) -> str,
         file_checksum(path, max_bytes) -> dict,
         describe_raster(path) -> dict,
         verify_source(record, source_path) -> list

used_by: algorithms/* (via ProvenanceMixin),
         algorithms/provenance_algorithm.py

rules:
  Pure stdlib + GDAL. No QGIS imports, so this is testable headless.
  Writing a sidecar must NEVER fail the run that produced the raster.
  Provenance is an aid; losing it is annoying, losing the user's
  half-hour of processing because a metadata file could not be written
  is not acceptable. Callers use write_sidecar_safe.
  Checksums are of a BOUNDED prefix of the source file, recorded
  alongside the byte count that was hashed. Hashing a 40 GB LiDAR
  mosaic on every run would cost more than the analysis. A prefix hash
  plus size and mtime is enough to detect "this is a different file",
  which is the actual question being asked.
agent:   claude-opus-5 | anthropic | 2026-07-25 | s_20260725_001 |
         New module. The plugin already had shareable JSON recipes and a
         PDF report claiming CIfA-compliant parameter provenance, but a
         raster on disk carried no record of how it was produced, so
         results could not be audited or regenerated.
"""

import datetime
import hashlib
import json
import logging
import os

from .version import get_version

logger = logging.getLogger(__name__)

# Appended to the output filename, e.g. svf.tif -> svf.tif.lidar-relief.json.
# Suffix rather than extension replacement so the sidecar sorts next to
# its raster and cannot collide with a second output of another type.
SIDECAR_SUFFIX = ".lidar-relief.json"

PROVENANCE_VERSION = "1.0.0"

# Bytes of the source file fed to the checksum. See module rules.
CHECKSUM_MAX_BYTES = 64 * 1024 * 1024


def sidecar_path_for(output_path: str) -> str:
    """Return the sidecar path that belongs to an output file."""
    return f"{output_path}{SIDECAR_SUFFIX}"


def file_checksum(path: str, max_bytes: int = CHECKSUM_MAX_BYTES) -> dict:
    """Hash a bounded prefix of a file, with the size and mtime.

    Args:
        path: File to fingerprint.
        max_bytes: Maximum number of bytes to read.

    Returns:
        dict with ``algorithm``, ``value``, ``bytes_hashed``, ``complete``
        (whether the whole file was hashed), ``size_bytes`` and
        ``modified_utc``. Returns ``{}`` if the file cannot be read.
    """
    try:
        size = os.path.getsize(path)
        mtime = os.path.getmtime(path)
    except OSError as exc:
        logger.warning("Cannot stat %s for provenance: %s", path, exc)
        return {}

    digest = hashlib.sha256()
    read = 0
    try:
        with open(path, "rb") as handle:
            while read < max_bytes:
                chunk = handle.read(min(1024 * 1024, max_bytes - read))
                if not chunk:
                    break
                digest.update(chunk)
                read += len(chunk)
    except OSError as exc:
        logger.warning("Cannot read %s for provenance: %s", path, exc)
        return {}

    return {
        "algorithm": "sha256",
        "value": digest.hexdigest(),
        "bytes_hashed": read,
        "complete": read >= size,
        "size_bytes": size,
        "modified_utc": datetime.datetime.fromtimestamp(
            mtime, tz=datetime.timezone.utc
        ).isoformat(),
    }


def describe_raster(path: str) -> dict:
    """Record the grid a raster sits on, for reproducibility checks.

    Returns:
        dict with dimensions, band count, cell size, geotransform, CRS
        and nodata. Empty dict if the file is not a readable raster.
    """
    try:
        from osgeo import gdal, osr
    except ImportError:  # pragma: no cover - GDAL is a hard dependency
        return {}

    try:
        dataset = gdal.Open(path, gdal.GA_ReadOnly)
    except RuntimeError:
        return {}
    if dataset is None:
        return {}

    try:
        geotransform = dataset.GetGeoTransform()
        projection = dataset.GetProjection()

        crs_authority = None
        if projection:
            srs = osr.SpatialReference()
            if srs.ImportFromWkt(projection) == 0:
                code = srs.GetAuthorityCode(None)
                name = srs.GetAuthorityName(None)
                if code and name:
                    crs_authority = f"{name}:{code}"

        band = dataset.GetRasterBand(1)
        return {
            "width": dataset.RasterXSize,
            "height": dataset.RasterYSize,
            "band_count": dataset.RasterCount,
            "geotransform": [float(v) for v in geotransform],
            "cell_size_x": abs(float(geotransform[1])),
            "cell_size_y": abs(float(geotransform[5])),
            "crs_authority": crs_authority,
            "crs_wkt": projection or None,
            "nodata": band.GetNoDataValue() if band is not None else None,
        }
    finally:
        dataset = None


def build_record(
    algorithm_id: str,
    parameters: dict,
    source_path: str = None,
    output_path: str = None,
    algorithm_name: str = None,
    extra: dict = None,
) -> dict:
    """Assemble the provenance record for one algorithm run.

    Args:
        algorithm_id: Processing algorithm name, e.g. ``sky_view_factor``.
        parameters: The parameter values actually used — resolved, not
            raw. A radius given in metres must be recorded in BOTH the
            units the user typed and the pixels that were computed, or
            the record cannot be replayed.
        source_path: Input raster path.
        output_path: Output path this record describes.
        algorithm_name: Human-readable algorithm name.
        extra: Any additional fields to merge in.

    Returns:
        A JSON-serialisable dict.
    """
    record = {
        "provenance_version": PROVENANCE_VERSION,
        "generator": {
            "plugin": "LiDAR Relief Visualization",
            "version": get_version(),
        },
        "algorithm": {
            "id": algorithm_id,
            "name": algorithm_name or algorithm_id,
        },
        "parameters": _jsonable(parameters or {}),
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    if source_path:
        record["source"] = {
            "path": os.path.abspath(source_path),
            "checksum": file_checksum(source_path),
            "raster": describe_raster(source_path),
        }
    if output_path:
        record["output"] = {
            "path": os.path.abspath(output_path),
            "filename": os.path.basename(output_path),
        }
    if extra:
        record.update(_jsonable(extra))

    return record


def write_sidecar(output_path: str, record: dict) -> str:
    """Write a provenance record beside its output file.

    Returns:
        The sidecar path.

    Raises:
        OSError: If the file cannot be written. Callers that must not
            fail should use :func:`write_sidecar_safe`.
    """
    path = sidecar_path_for(output_path)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, sort_keys=False)
        handle.write("\n")
    return path


def write_sidecar_safe(output_path: str, record: dict, feedback=None):
    """Write a sidecar, swallowing any failure.

    Rules:
        Never raise. See the module rules — provenance must not be able
        to destroy the result it describes.

    Returns:
        The sidecar path, or ``None`` if writing failed.
    """
    try:
        path = write_sidecar(output_path, record)
    except Exception as exc:
        logger.warning("Could not write provenance sidecar: %s", exc)
        if feedback is not None:
            push = getattr(feedback, "pushInfo", None)
            if callable(push):
                push(f"(Could not write provenance sidecar: {exc})")
        return None

    if feedback is not None:
        push = getattr(feedback, "pushInfo", None)
        if callable(push):
            push(f"Provenance: {os.path.basename(path)}")
    return path


def read_sidecar(path: str) -> dict:
    """Load a provenance record.

    Args:
        path: Either the sidecar itself or the output file it describes.

    Returns:
        The parsed record.

    Raises:
        FileNotFoundError: If no sidecar exists.
        ValueError: If the file is not a valid provenance record.
    """
    candidate = path
    if not path.endswith(SIDECAR_SUFFIX):
        candidate = sidecar_path_for(path)
        if not os.path.exists(candidate) and os.path.exists(path):
            # The caller may have passed a JSON file under another name.
            candidate = path

    if not os.path.exists(candidate):
        raise FileNotFoundError(
            f"No provenance sidecar found at {candidate}. Outputs produced "
            f"before provenance recording was added will not have one."
        )

    with open(candidate, "r", encoding="utf-8") as handle:
        try:
            record = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Sidecar is not valid JSON: {candidate} ({exc})") from exc

    if not isinstance(record, dict) or "provenance_version" not in record:
        raise ValueError(
            f"{candidate} is not a LiDAR Relief provenance record "
            f"(missing 'provenance_version')."
        )
    return record


def verify_source(record: dict, source_path: str) -> list:
    """Check a source raster still matches what a record describes.

    Args:
        record: A provenance record.
        source_path: The raster to check against it.

    Returns:
        List of human-readable difference descriptions. Empty means the
        source matches.
    """
    differences = []
    recorded = record.get("source") or {}
    if not recorded:
        return ["The record does not name a source raster."]

    recorded_checksum = recorded.get("checksum") or {}
    actual_checksum = file_checksum(source_path)

    if recorded_checksum and actual_checksum:
        if recorded_checksum.get("size_bytes") != actual_checksum.get("size_bytes"):
            differences.append(
                f"File size differs: recorded "
                f"{recorded_checksum.get('size_bytes')} bytes, "
                f"found {actual_checksum.get('size_bytes')}."
            )
        elif recorded_checksum.get("value") != actual_checksum.get("value"):
            differences.append(
                "Checksum differs — the source file's contents have changed."
            )

    recorded_raster = recorded.get("raster") or {}
    actual_raster = describe_raster(source_path)
    for field, label in (
        ("width", "width"),
        ("height", "height"),
        ("crs_authority", "CRS"),
    ):
        if field in recorded_raster and field in actual_raster:
            if recorded_raster[field] != actual_raster[field]:
                differences.append(
                    f"Raster {label} differs: recorded "
                    f"{recorded_raster[field]!r}, found {actual_raster[field]!r}."
                )

    return differences


def _jsonable(value):
    """Coerce values into something json.dump can handle.

    QGIS hands back enums, QVariants and numpy scalars; a sidecar that
    raises TypeError mid-write is worse than one with a stringified
    value, so unknown types degrade to repr rather than exploding.
    """
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, bool, int, float)) or value is None:
        return value
    # numpy scalars and anything else with a Python equivalent
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _jsonable(item())
        except Exception as exc:
            # .item() exists on plenty of objects that are not numpy
            # scalars and will raise here. Falling through to repr() is
            # the intended behaviour, but log it so a parameter that
            # silently became a string is traceable.
            logger.debug(
                "Could not unwrap %s via .item(), falling back to repr: %s",
                type(value).__name__,
                exc,
            )
    return repr(value)
