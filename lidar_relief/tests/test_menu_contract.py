from lidar_relief.menu_contract import ALGORITHM_SHORTCUTS, MENU_COMMAND_LABELS


def test_algorithm_shortcuts_use_registered_provider_ids():
    assert [(item.label, item.algorithm_id) for item in ALGORITHM_SHORTCUTS] == [
        (
            "Create Visualisation Contact Sheet…",
            "lidar_relief:visualisation_contact_sheet",
        ),
        ("Run Batch Relief Visualisation…", "lidar_relief:batch_relief"),
        ("Import and Validate Recipe…", "lidar_relief:recipe_import"),
    ]


def test_menu_exposes_every_quick_win():
    labels = set(MENU_COMMAND_LABELS)
    assert "Open LiDAR Relief Toolbox" in labels
    assert "Inspect Active DEM…" in labels
    assert "Dependency Diagnostics…" in labels
    assert "Recent Recipe…" in labels
    assert "Recent Output Folder…" in labels
    assert "Remember Output Folder…" in labels
    assert "Open User Guide" in labels
    assert "Contextual Help…" in labels


def test_dem_shortcuts_prefill_the_active_raster_only_when_relevant():
    by_id = {item.algorithm_id: item for item in ALGORITHM_SHORTCUTS}
    assert by_id["lidar_relief:visualisation_contact_sheet"].use_active_dem
    assert by_id["lidar_relief:batch_relief"].use_active_dem
    assert not by_id["lidar_relief:recipe_import"].use_active_dem
