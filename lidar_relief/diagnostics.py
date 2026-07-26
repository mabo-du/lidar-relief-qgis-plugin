"""Safe optional-capability diagnostics for support and troubleshooting."""

from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Callable

from .version import get_version


@dataclass(frozen=True)
class Capability:
    name: str
    available: bool
    detail: str


def probe_capabilities(
    probes: dict[str, tuple[str, Callable[[], bool]]] | None = None,
) -> list[Capability]:
    """Run guarded capability probes; a broken optional package is non-fatal."""
    if probes is None:
        from .export.cog_exporter import cog_is_supported
        from .export.contact_sheet import pillow_available
        from .export.report_generator import reportlab_available
        from .fusion.sentinel_fusion import fusion_available
        from .gpu.compute_backend import cupy_available
        from .ml.detector import onnx_available
        from .point_cloud.csf_filter import csf_available
        from .point_cloud.pdal_pipeline import pdal_available
        from .temporal.dem_difference import xarray_available

        def core_raster_available():
            import numpy  # noqa: F401
            from osgeo import gdal  # noqa: F401

            return True

        probes = {
            "Core raster engine": ("NumPy and GDAL", core_raster_available),
            "GPU acceleration": ("CuPy with a working CUDA runtime", cupy_available),
            "CSF ground filtering": (
                "Install cloth-simulation-filter",
                csf_available,
            ),
            "PDAL point-cloud pipeline": (
                "Install PDAL Python bindings",
                pdal_available,
            ),
            "AI/ONNX detection": ("Install onnxruntime", onnx_available),
            "Cloud-Optimized GeoTIFF": ("Install rio-cogeo", cog_is_supported),
            "PDF reports": ("Install ReportLab", reportlab_available),
            "Temporal DEM comparison": (
                "Install xarray and rioxarray",
                xarray_available,
            ),
            "LiDAR/Sentinel fusion": (
                "Install rasterio, xarray, and rioxarray",
                fusion_available,
            ),
            "Labelled contact sheets": ("Install Pillow", pillow_available),
        }

    found = []
    for name, (detail, probe) in probes.items():
        try:
            available = bool(probe())
        except Exception as exc:
            available = False
            detail = f"{detail} ({exc})"
        found.append(Capability(name, available, detail))
    return found


def format_diagnostics(
    capabilities: list[Capability] | None = None,
    *,
    plugin_version: str | None = None,
    qgis_version: str = "unknown",
    python_version: str | None = None,
) -> str:
    """Create a plain-text report suitable for copying into a support issue."""
    capabilities = capabilities if capabilities is not None else probe_capabilities()
    plugin_version = plugin_version or get_version()
    python_version = python_version or platform.python_version()
    lines = [
        f"LiDAR Relief {plugin_version}",
        f"QGIS {qgis_version}",
        f"Python {python_version}",
        f"Platform {platform.platform()}",
        "",
        "Capabilities",
    ]
    for capability in capabilities:
        state = "available" if capability.available else "unavailable"
        lines.append(f"- {capability.name}: {state} — {capability.detail}")
    return "\n".join(lines)
