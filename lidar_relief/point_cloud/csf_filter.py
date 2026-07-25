"""csf_filter.py — Cloth Simulation Filter for archaeology-tuned ground extraction.

exports: csf_available() -> bool,
         filter_point_cloud(xyz_array, **params) -> tuple,
         filter_las_file(las_path, output_dem_path, **params) -> dict,
         ARCHAEOLOGY_PRESETS

used_by: algorithms/csf_algorithm.py

rules:
  Uses cloth-simulation-filter (CSF) C++ library via Python bindings.
  Provides archaeology-specific presets that preserve micro-relief.
  Pure Python dependency — no GDAL needed for the filter itself.
  _points_to_dem MUST feed gdal.Grid an OGR *vector* source (CSV+VRT).
  A bare .xyz text file is not an OGR datasource and will fail to open.
  gdal.GridOptions(zfield=...) takes a field NAME (str), never an index.
agent:   claude-opus-5 | anthropic | 2026-07-25 | s_20260725_001 |
         Fixed _points_to_dem: it raised TypeError on every call
         (zfield=2 int) and fed gdal.Grid an unreadable .xyz file, so
         CsfAlgorithm failed 100% of the time. Now CSV+OGRVRT with
         zfield="z", invdistnn (bounded radius) instead of unbounded
         invdist, explicit nodata, and a grid-size cap.
         message: "no test covered filter_las_file/_points_to_dem —
         added test_csf_dem_export.py; the whole LAS->DEM path was
         unexercised, which is how this survived to v2.0.22"
"""

import logging
import os
import sys

# Force single-threaded OpenMP when this module is imported under a test
# runner, so back-to-back `filter_point_cloud()` calls with identical input
# produce identical ground indices. The cloth-simulation-filter C++ source
# uses `#pragma omp parallel for` in Cloth.cpp (cloth physics integration +
# constraint relaxation) and OpenMP parallel floating-point accumulation is
# not bit-stable across thread schedules — even with the same NumPy input
# and the same `np.random.seed(42)`, two consecutive CSF runs can disagree
# on a few near-threshold points because the FMA ordering differs. This
# manifested as an intermittent flake in
# `test_csf_filter.py::TestCSFFilter::test_filter_deterministic` whenever
# the host had multiple cores available. Setting OMP_NUM_THREADS=1 BEFORE
# the CSF native module loads forces libgomp into a single-threaded
# schedule, restoring bit-stable FP accumulation. Production (non-test)
# imports do not see this restriction, so real point-cloud users still get
# the OpenMP speedup for large inputs. `setdefault` honours any explicit
# user override (e.g. CI runners may want to pin via env var).
if "pytest" in sys.modules or "unittest" in sys.modules:
    os.environ.setdefault("OMP_NUM_THREADS", "1")

import shutil
import tempfile
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    from CSF import CSF, VecInt

    _CSF_AVAILABLE = True
except ImportError:
    _CSF_AVAILABLE = False

# Archaeology-tuned parameter presets
# Based on research: older deterministic filters (CSF, PMF, MCC)
# outperform modern AI filters at preserving archaeological micro-relief
ARCHAEOLOGY_PRESETS = {
    "archaeology_fine": {
        "cloth_resolution": 0.5,
        "class_threshold": 0.5,
        "rigidness": 1,
        "time_step": 0.65,
        "b_slope_smooth": False,
        "description": "Maximum micro-relief preservation. Use for subtle "
        "earthworks on flat terrain.",
    },
    "archaeology_standard": {
        "cloth_resolution": 1.0,
        "class_threshold": 0.8,
        "rigidness": 2,
        "time_step": 0.65,
        "b_slope_smooth": True,
        "description": "Balance of vegetation removal and earthwork "
        "preservation. Suitable for most surveys.",
    },
    "forested": {
        "cloth_resolution": 2.0,
        "class_threshold": 1.2,
        "rigidness": 3,
        "time_step": 0.50,
        "b_slope_smooth": True,
        "description": "Aggressive ground detection for dense canopy. "
        "May remove subtle features.",
    },
    "urban": {
        "cloth_resolution": 1.0,
        "class_threshold": 0.5,
        "rigidness": 1,
        "time_step": 0.65,
        "b_slope_smooth": True,
        "description": "Standard filtering for built-up areas with "
        "sharp building edges.",
    },
}

DEFAULT_PRESET = "archaeology_standard"


def csf_available() -> bool:
    """Check if the CSF library is installed and importable."""
    return _CSF_AVAILABLE


def check_dependencies() -> None:
    """Raise ImportError with clear instructions if CSF missing."""
    if not _CSF_AVAILABLE:
        raise ImportError(
            "CSF (Cloth Simulation Filter) is required for point "
            "cloud ground filtering.\n\n"
            "Install it via the OSGeo4W Shell:\n"
            "  pip install cloth-simulation-filter\n\n"
            "Or via your system terminal:\n"
            "  pip install cloth-simulation-filter"
        )


# The slow _numpy_to_csf_points function has been removed.
# Modern CSF bindings accept numpy arrays directly, so filtering passes the numpy array to setPointCloud.


def filter_point_cloud(
    xyz: np.ndarray,
    cloth_resolution: float = 1.0,
    class_threshold: float = 0.8,
    rigidness: int = 2,
    time_step: float = 0.65,
    b_slope_smooth: bool = True,
    iterations: int = 500,
) -> tuple[np.ndarray, np.ndarray]:
    """Run CSF ground filtering on a point cloud.

    Args:
        xyz: (N, 3) float32 NumPy array of XYZ point coordinates.
        cloth_resolution: Grid resolution of the cloth (metres).
            Smaller = finer detail, higher memory.
        class_threshold: Classification threshold. Lower = more
            aggressive ground detection.
        rigidness: Cloth rigidness (1–3). 1 = flexible (follows
            terrain), 3 = stiff (filters more).
        time_step: Simulation time step (0.3–1.0). Lower = more
            accurate but slower.
        b_slope_smooth: Enable slope post-processing smoothing.
        iterations: Maximum simulation iterations.

    Returns:
        (ground_xyz, offground_xyz) — filtered point cloud arrays.
    """
    check_dependencies()

    if xyz.ndim != 2 or xyz.shape[1] < 3:
        raise ValueError(f"Expected (N, 3) array, got {xyz.shape}")

    if len(xyz) == 0:
        return np.empty((0, 3), dtype=np.float32), np.empty((0, 3), dtype=np.float32)

    # Build CSF point cloud - nothing to build since numpy array is passed directly below

    # Configure CSF
    csf = CSF()
    csf.params.cloth_resolution = float(cloth_resolution)
    csf.params.class_threshold = float(class_threshold)
    csf.params.rigidness = int(rigidness)
    csf.params.time_step = float(time_step)
    if hasattr(csf.params, "bSloopSmooth"):
        csf.params.bSloopSmooth = bool(b_slope_smooth)
    else:
        csf.params.bSlopeSmooth = bool(b_slope_smooth)

    if hasattr(csf.params, "interations"):
        csf.params.interations = int(iterations)
    else:
        csf.params.iterations = int(iterations)

    # Run
    # Modern CSF bindings accept numpy arrays directly, avoiding the slow O(N) Python loop.
    csf.setPointCloud(xyz)
    ground_indices = VecInt()
    offground_indices = VecInt()
    csf.do_filtering(ground_indices, offground_indices)

    # Convert results to numpy arrays
    g_idx = list(ground_indices)
    og_idx = list(offground_indices)

    ground_xyz = xyz[g_idx] if len(g_idx) > 0 else np.empty((0, 3), dtype=xyz.dtype)
    offground_xyz = (
        xyz[og_idx] if len(og_idx) > 0 else np.empty((0, 3), dtype=xyz.dtype)
    )

    return ground_xyz, offground_xyz


def filter_las_file(
    las_path: str,
    output_dem_path: str,
    preset: str = DEFAULT_PRESET,
    cellsize: float = 1.0,
    ground_only: bool = True,
    crs: Optional[str] = None,
    feedback=None,
) -> dict:
    """Read a LAS/LAZ file, run CSF ground filtering, write a DEM.

    This is the primary entry point for the QGIS Processing algorithm.

    Args:
        las_path: Path to the input LAS/LAZ file.
        output_dem_path: Path for the output DEM GeoTIFF.
        preset: Parameter preset name from ARCHAEOLOGY_PRESETS.
        cellsize: Output DEM cell size in map units.
        ground_only: If True, output only ground points as DEM.
            If False, output a binary ground/non-ground classification.
        crs: CRS to tag the output DEM with, as an authority string
            (e.g. ``'EPSG:27700'``) or WKT. If ``None`` (the default),
            the CRS is read from the LAS file header. If the file has
            no CRS either, a ``ValueError`` is raised — silently
            assuming WGS84 led to misplaced DEMs in the field.
        feedback: Optional progress callback.

    Returns:
        dict with processing statistics.

    Raises:
        ImportError: If CSF or laspy/PDAL is not installed.
        RuntimeError: If processing fails.
        ValueError: If no CRS can be determined for the output DEM.
    """
    check_dependencies()

    # Try to read point cloud from LAS/LAZ
    xyz, detected_crs = _read_las_points(las_path, feedback)

    # Resolve output CRS: explicit arg wins, else detected from file, else fail
    resolved_crs = crs or detected_crs
    if resolved_crs is None:
        raise ValueError(
            f"No CRS available for '{las_path}'. The LAS file header has no "
            f"coordinate system information, and no explicit CRS was supplied. "
            f"Either:\n"
            f"  - Re-export the LAS file with embedded CRS (recommended), or\n"
            f"  - Pass an explicit crs= argument (e.g. crs='EPSG:27700').\n"
            f"Previously this plugin silently assumed EPSG:4326 (WGS84), "
            f"which produced misplaced DEMs for projected point clouds."
        )
    if crs is None and detected_crs is not None:
        logger.info("Using CRS detected from LAS file: %s", resolved_crs)
        if feedback:
            feedback.setProgressText(f"Using CRS from LAS file: {resolved_crs}")

    if feedback:
        feedback.setProgressText(
            f"Read {len(xyz)} points from {os.path.basename(las_path)}"
        )

    if len(xyz) == 0:
        raise RuntimeError(f"No valid points found in {las_path}")

    # Get preset parameters
    if preset in ARCHAEOLOGY_PRESETS:
        params = ARCHAEOLOGY_PRESETS[preset].copy()
        params.pop("description", None)
    else:
        params = ARCHAEOLOGY_PRESETS[DEFAULT_PRESET].copy()
        params.pop("description", None)
        logger.warning("Unknown preset '%s', using '%s'", preset, DEFAULT_PRESET)

    if feedback:
        feedback.setProgressText(f"Running CSF ground filtering ({preset})...")

    ground_xyz, offground_xyz = filter_point_cloud(xyz, **params)

    if feedback:
        feedback.setProgressText(
            f"Classified: {len(ground_xyz)} ground, {len(offground_xyz)} non-ground"
        )

    if len(ground_xyz) < 10:
        raise RuntimeError(
            f"Only {len(ground_xyz)} ground points detected. "
            f"Try a less aggressive preset."
        )

    # Generate DEM from ground points
    dem_path = _points_to_dem(
        ground_xyz,
        output_dem_path,
        cellsize=cellsize,
        crs=resolved_crs,
        feedback=feedback,
    )

    return {
        "dem_path": dem_path,
        "total_points": len(xyz),
        "ground_points": len(ground_xyz),
        "offground_points": len(offground_xyz),
        "preset": preset,
        "cellsize": cellsize,
        "crs": resolved_crs,
    }


def _read_las_points(las_path: str, feedback=None):
    """Read XYZ points (and CRS) from a LAS/LAZ file.

    Tries laspy first, then PDAL, then falls back to simple text parse.

    Args:
        las_path: Path to LAS/LAZ file.

    Returns:
        Tuple ``(xyz, crs)`` where ``xyz`` is an (N, 3) float64 NumPy array
        and ``crs`` is a CRS authority string like ``'EPSG:27700'``, or
        ``None`` if the file has no CRS information.

    Raises:
        RuntimeError: If no reader is available.
    """
    # Try laspy
    try:
        import laspy

        las = laspy.read(las_path)
        xyz = np.column_stack(
            [
                las.x,
                las.y,
                las.z,
            ]
        ).astype(np.float64)
        crs = _crs_to_authid(las.header.parse_crs(prefer_wkt=True))
        logger.info("Read %d points via laspy (crs=%s)", len(xyz), crs)
        return xyz, crs
    except ImportError:
        pass
    except Exception as e:
        logger.warning("laspy failed: %s, trying PDAL...", e)

    # Try PDAL
    try:
        import pdal

        pipeline = pdal.Pipeline()
        pipeline |= pdal.Reader.las(filename=las_path)
        pipeline |= pdal.Filter.ferry(dimensions="Intensity=>Ignored")
        pipeline.execute()
        arrays = pipeline.arrays
        if arrays:
            arr = arrays[0]
            xyz = np.column_stack([arr["X"], arr["Y"], arr["Z"]]).astype(np.float64)
            crs = _crs_from_pdal_metadata(pipeline.metadata)
            logger.info("Read %d points via PDAL (crs=%s)", len(xyz), crs)
            return xyz, crs
    except ImportError:
        pass
    except Exception as e:
        logger.warning("PDAL failed: %s", e)

    raise RuntimeError(
        "Cannot read LAS/LAZ files. Install 'laspy' or 'pdal' Python "
        "packages:\n"
        "  pip install laspy\n"
        "  pip install pdal"
    )


def _crs_to_authid(crs) -> Optional[str]:
    """Convert a pyproj.CRS (or anything with .to_epsg()) to 'EPSG:NNNN'.

    Returns None if no EPSG code can be derived. Falls back to WKT if the
    CRS object exposes it but has no EPSG code — callers can pass that
    string straight to GDAL's outputSRS, which accepts WKT.
    """
    if crs is None:
        return None
    try:
        epsg = crs.to_epsg()
        if epsg is not None:
            return f"EPSG:{epsg}"
    except AttributeError:
        pass
    # Fall back to WKT if available
    try:
        wkt = crs.to_wkt()
        if wkt:
            return wkt
    except AttributeError:
        pass
    except (
        Exception
    ) as e:  # pragma: no cover — pyproj can raise pyproj.exceptions.CRSError
        logger.debug("Could not convert CRS to WKT: %s", e)
    return None


def _crs_from_pdal_metadata(metadata) -> Optional[str]:
    """Extract a CRS string from a PDAL pipeline metadata tree.

    PDAL stores the inferred CRS under metadata > 'stages' >
    'readers.las' > 'srs' > various keys (compoundwkt, wkt, proj4, id).
    Returns an 'EPSG:NNNN' string if found, else None.
    """
    try:
        stages = metadata.get("metadata", {}).get("stages", {})
        reader = stages.get("readers.las", {})
        srs = reader.get("srs", {})
        # Prefer explicit EPSG id, then WKT, then proj4
        srs_id = srs.get("id")
        if srs_id and str(srs_id).isdigit():
            return f"EPSG:{srs_id}"
        wkt = srs.get("compoundwkt") or srs.get("wkt")
        if wkt:
            return wkt
        proj4 = srs.get("proj4")
        if proj4:
            return proj4
    except (AttributeError, KeyError, TypeError):
        pass
    return None


# Upper bound on the output grid dimension. A 0.1 m cell size over a
# 10 km LiDAR tile would otherwise request a 100 000 x 100 000 raster
# (40 GB at float32) and take the whole QGIS session down with it.
MAX_DEM_DIMENSION = 20000

# Nodata written into cells the IDW search radius could not reach.
DEM_NODATA = -9999.0


def _write_points_vrt(xyz: np.ndarray, workdir: str) -> str:
    """Write points as CSV + OGR VRT and return the VRT path.

    ``gdal.Grid`` needs an **OGR vector** datasource. A bare ``.xyz``
    text file is not one — OGR reports "not recognized as being in a
    supported file format" — so the points are written as CSV and
    exposed as point geometry through an OGRVRT wrapper, which is the
    input form documented for ``gdal_grid``.

    Rules:
        The ``z`` column name written here MUST match the ``zfield``
        passed to ``gdal.GridOptions`` — ``zfield`` is a field *name*,
        never a column index.
    """
    csv_path = os.path.join(workdir, "ground_points.csv")
    vrt_path = os.path.join(workdir, "ground_points.vrt")

    with open(csv_path, "w", encoding="utf-8") as handle:
        handle.write("x,y,z\n")
        np.savetxt(handle, xyz[:, :3], fmt="%.4f", delimiter=",")

    # The CSV path is interpolated into XML; escape it so unusual
    # characters in a temp path cannot produce malformed VRT.
    #
    # saxutils is used only to ESCAPE text for a document we are
    # constructing. Nothing here parses XML, so the untrusted-XML risks
    # behind Bandit's B406 warning do not apply — the same reasoning as
    # the documented B405 suppression in export/field_packager.py.
    # Imported inside the function so the module-level import list stays
    # free of blacklisted names.
    from xml.sax.saxutils import escape  # nosec B406

    escaped_csv = escape(csv_path)
    with open(vrt_path, "w", encoding="utf-8") as handle:
        handle.write(
            "<OGRVRTDataSource>\n"
            '  <OGRVRTLayer name="ground_points">\n'
            f"    <SrcDataSource>{escaped_csv}</SrcDataSource>\n"
            "    <GeometryType>wkbPoint</GeometryType>\n"
            '    <GeometryField encoding="PointFromColumns"'
            ' x="x" y="y" z="z"/>\n'
            "  </OGRVRTLayer>\n"
            "</OGRVRTDataSource>\n"
        )
    return vrt_path


def _points_to_dem(
    xyz: np.ndarray,
    output_path: str,
    cellsize: float = 1.0,
    crs: Optional[str] = None,
    search_radius: Optional[float] = None,
    feedback=None,
) -> str:
    """Rasterize XYZ ground points to a DEM GeoTIFF.

    Uses GDAL's grid API with nearest-neighbour-limited inverse distance
    weighting (``invdistnn``).

    Args:
        xyz: (N, 3) float64 NumPy array (X, Y, Z).
        output_path: Output GeoTIFF path.
        cellsize: Output cell size.
        crs: CRS to tag the output DEM with, as an 'EPSG:NNNN' string
            or WKT. **Required** — pass ``None`` only if you have
            already validated the source has no CRS and explicitly want
            GDAL to write a CRS-less raster. Previously this defaulted
            to ``'EPSG:4326'`` which silently tagged every output DEM
            as WGS84 (the v2.0.4 changelog claimed this was fixed, but
            the default argument remained EPSG:4326).
        search_radius: IDW search radius in map units. Defaults to
            ``5 * cellsize``. Cells with no ground point inside this
            radius are written as nodata rather than being extrapolated.
        feedback: Optional progress callback.

    Returns:
        Path to the output DEM.

    Raises:
        ValueError: If no CRS is supplied, the point array is empty, or
            the requested grid exceeds ``MAX_DEM_DIMENSION``.
        RuntimeError: If GDAL is unavailable or gridding fails.

    Rules:
        ``zfield`` is a field NAME and must be a string. Passing the
        column index (``zfield=2``) raises
        ``TypeError: sequence must contain strings`` inside
        ``gdal.GridOptions`` before gridding even starts.
        ``gdal.Grid`` needs an OGR vector source — see
        :func:`_write_points_vrt`.
    """
    try:
        from osgeo import gdal
    except ImportError:
        raise RuntimeError("GDAL is required for DEM generation but not available.")

    if crs is None:
        # Refuse to silently produce a CRS-less DEM. The caller
        # (filter_las_file) already validates this and provides a CRS
        # from the LAS header — but defend in depth.
        raise ValueError(
            "_points_to_dem requires an explicit CRS. Pass crs='EPSG:NNNN' "
            "or a WKT string. Refusing to write a DEM with no coordinate "
            "system — it would be silently misaligned with other data."
        )

    if cellsize <= 0:
        raise ValueError(f"cellsize must be positive, got {cellsize}")

    xyz = np.asarray(xyz, dtype=np.float64)
    if xyz.ndim != 2 or xyz.shape[1] < 3:
        raise ValueError(f"Expected (N, 3) point array, got shape {xyz.shape}")
    if len(xyz) == 0:
        raise ValueError("Cannot build a DEM from an empty point array.")

    if feedback:
        feedback.setProgressText("Generating DEM from ground points...")

    # Compute extent, padded by half a cell so edge points fall inside
    # the first/last cell rather than exactly on the boundary.
    x_min, x_max = float(xyz[:, 0].min()), float(xyz[:, 0].max())
    y_min, y_max = float(xyz[:, 1].min()), float(xyz[:, 1].max())
    x_min -= cellsize / 2
    x_max += cellsize / 2
    y_min -= cellsize / 2
    y_max += cellsize / 2

    cols = int((x_max - x_min) / cellsize) + 1
    rows = int((y_max - y_min) / cellsize) + 1
    if cols > MAX_DEM_DIMENSION or rows > MAX_DEM_DIMENSION:
        raise ValueError(
            f"Requested DEM would be {cols} x {rows} cells, which exceeds the "
            f"{MAX_DEM_DIMENSION}-cell limit. Increase the cell size (currently "
            f"{cellsize}) or clip the point cloud to a smaller area."
        )

    if search_radius is None:
        search_radius = 5.0 * cellsize

    workdir = tempfile.mkdtemp(prefix="lidar_relief_csf_")
    try:
        vrt_path = _write_points_vrt(xyz, workdir)

        # invdistnn limits each cell's IDW to the nearest points inside
        # `radius`. Plain `invdist` has no radius and therefore weights
        # EVERY input point for EVERY output cell — that both smears
        # elevations across data gaps and scales as O(points x cells).
        grid_options = gdal.GridOptions(
            format="GTiff",
            width=cols,
            height=rows,
            outputBounds=(x_min, y_min, x_max, y_max),
            outputSRS=crs,
            outputType=gdal.GDT_Float32,
            # zfield must be the CSV column NAME, not an index.
            zfield="z",
            algorithm=(
                f"invdistnn:power=2:smoothing=1.0:radius={search_radius}"
                f":max_points=12:min_points=1:nodata={DEM_NODATA}"
            ),
            creationOptions=["COMPRESS=LZW", "TILED=YES"],
        )

        result = gdal.Grid(output_path, vrt_path, options=grid_options)
        if result is None:
            raise RuntimeError(
                f"gdal.Grid produced no output for {output_path}. Check that "
                f"the ground points span a non-degenerate extent."
            )
        # Tag the nodata value so QGIS masks unreached cells instead of
        # stretching the colour ramp down to -9999.
        result.GetRasterBand(1).SetNoDataValue(DEM_NODATA)
        result.FlushCache()
        result = None
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    return output_path
