"""QGIS --code script: validate normal desktop plugin loading and exit."""

import os
from pathlib import Path

from qgis.PyQt.QtCore import QTimer
from qgis.core import QgsApplication, Qgis
import qgis.utils


PLUGIN_ID = "lidar_relief"
# Keep in step with scripts/qgis_smoke_test.py, provider.py, README.md and
# lidar_relief/metadata.txt.
EXPECTED_ALGORITHM_COUNT = 31
iface = qgis.utils.iface
if iface is None:
    raise RuntimeError("QGIS desktop interface is unavailable")

if not qgis.utils.loadPlugin(PLUGIN_ID):
    raise RuntimeError("QGIS plugin loader could not discover lidar_relief")
if not qgis.utils.startPlugin(PLUGIN_ID):
    raise RuntimeError("QGIS plugin loader could not start lidar_relief")

provider = QgsApplication.processingRegistry().providerById(PLUGIN_ID)
if provider is None:
    raise RuntimeError("LiDAR Relief provider was not registered in QGIS Desktop")
algorithm_count = len(provider.algorithms())
if algorithm_count != EXPECTED_ALGORITHM_COUNT:
    raise RuntimeError(
        f"expected {EXPECTED_ALGORITHM_COUNT} algorithms, found {algorithm_count}"
    )

message = (
    f"QGIS Desktop {Qgis.QGIS_VERSION}: normal plugin loader registered "
    f"{algorithm_count} algorithms"
)
print(message, flush=True)


def finish() -> None:
    """Persist success and close QGIS cleanly."""
    if result_path := os.environ.get("QGIS_SMOKE_RESULT"):
        Path(result_path).write_text(message + "\n", encoding="utf-8")
    iface.mainWindow().close()


QTimer.singleShot(1000, finish)
