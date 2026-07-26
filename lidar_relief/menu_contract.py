"""Stable labels and Processing IDs used by the LiDAR Relief plugin menu."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AlgorithmShortcut:
    label: str
    algorithm_id: str
    use_active_dem: bool = False


ALGORITHM_SHORTCUTS = (
    AlgorithmShortcut(
        "Create Visualisation Contact Sheet…",
        "lidar_relief:visualisation_contact_sheet",
        True,
    ),
    AlgorithmShortcut(
        "Run Batch Relief Visualisation…",
        "lidar_relief:batch_relief",
        True,
    ),
    AlgorithmShortcut(
        "Import and Validate Recipe…",
        "lidar_relief:recipe_import",
    ),
)

MENU_COMMAND_LABELS = (
    "Open LiDAR Relief Toolbox",
    "Inspect Active DEM…",
    "Dependency Diagnostics…",
    "Recent Recipe…",
    "Recent Output Folder…",
    "Remember Output Folder…",
    "Open User Guide",
    "Contextual Help…",
)
