from lidar_relief.diagnostics import Capability, format_diagnostics, probe_capabilities


def test_probe_failures_become_unavailable_instead_of_escaping():
    def broken():
        raise RuntimeError("driver missing")

    capabilities = probe_capabilities(
        {
            "Working": ("available", lambda: True),
            "Missing": ("install it", lambda: False),
            "Broken": ("repair it", broken),
        }
    )

    assert capabilities == [
        Capability("Working", True, "available"),
        Capability("Missing", False, "install it"),
        Capability("Broken", False, "repair it (driver missing)"),
    ]


def test_diagnostics_are_copy_friendly_and_actionable():
    text = format_diagnostics(
        [
            Capability("GPU acceleration", False, "Install CuPy with CUDA support"),
            Capability("PDF reports", True, "ReportLab"),
        ],
        plugin_version="2.1.2",
        qgis_version="3.34.2",
        python_version="3.10.12",
    )
    assert "LiDAR Relief 2.1.2" in text
    assert "QGIS 3.34.2" in text
    assert "GPU acceleration: unavailable" in text
    assert "Install CuPy" in text
    assert "PDF reports: available" in text
