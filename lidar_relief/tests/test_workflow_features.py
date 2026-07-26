import json

import pytest

from lidar_relief.workflow_features import (
    batch_recipe_json,
    render_output_filename,
)


def test_output_template_expands_safe_documented_fields():
    assert (
        render_output_filename(
            "{dem}_{method}_{preset}",
            "/data/Mont Auxois DEM.tif",
            "sky-view factor",
            "flat/agricultural",
        )
        == "Mont_Auxois_DEM_sky-view_factor_flat_agricultural.tif"
    )


def test_output_template_rejects_unknown_fields_and_path_traversal():
    with pytest.raises(ValueError, match="Unknown output naming field"):
        render_output_filename("{dem}_{radius}", "dem.tif", "svf", "flat")
    with pytest.raises(ValueError, match="folder"):
        render_output_filename("../{dem}", "dem.tif", "svf", "flat")


def test_output_template_uses_a_nonempty_fallback():
    assert render_output_filename("", "dem.tif", "svf", "") == "dem_svf.tif"


def test_batch_recipe_records_only_enabled_tasks_and_resolved_values():
    content = batch_recipe_json(
        tasks=["svf", "slrm"],
        config={
            "svf_radius": 40,
            "svf_num_directions": 16,
            "svf_noise": 1,
            "slrm_radius": 80,
        },
        preset_key="forested",
        plugin_version="2.1.2",
        source_name="alesia-dem.tif",
    )
    recipe = json.loads(content)
    assert recipe["name"] == "alesia-dem — Batch Relief"
    assert recipe["batch_preset"] == "forested"
    assert recipe["algorithms"] == {
        "svf": {
            "search_radius": 40,
            "num_directions": 16,
            "noise_level": 1,
        },
        "slrm": {"trend_radius": 80},
    }
