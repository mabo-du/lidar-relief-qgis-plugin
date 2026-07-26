"""Pure workflow helpers shared by QGIS dialogs and Processing algorithms."""

from __future__ import annotations

import os
import re
import string
from datetime import date

from .recipes import export_recipe

DEFAULT_OUTPUT_TEMPLATE = "{dem}_{method}"
OUTPUT_TEMPLATE_FIELDS = frozenset({"dem", "method", "preset", "date"})


def _safe_component(value: str) -> str:
    value = re.sub(r"[^\w.-]+", "_", str(value), flags=re.UNICODE)
    return value.strip("._") or "output"


def render_output_filename(
    template: str,
    source_path: str,
    method: str,
    preset: str,
    run_date: date | None = None,
) -> str:
    """Render one safe GeoTIFF name without allowing path traversal."""
    template = (template or DEFAULT_OUTPUT_TEMPLATE).strip()
    if "/" in template or "\\" in template:
        raise ValueError("Output naming templates cannot contain folder separators.")
    fields = {
        field_name
        for _literal, field_name, _format, _conversion in string.Formatter().parse(
            template
        )
        if field_name
    }
    unknown = fields - OUTPUT_TEMPLATE_FIELDS
    if unknown:
        raise ValueError(f"Unknown output naming field: {sorted(unknown)[0]}")
    values = {
        "dem": _safe_component(os.path.splitext(os.path.basename(source_path))[0]),
        "method": _safe_component(method),
        "preset": _safe_component(preset or "manual"),
        "date": (run_date or date.today()).isoformat(),
    }
    rendered = _safe_component(template.format(**values))
    return rendered if rendered.lower().endswith(".tif") else f"{rendered}.tif"


def _algorithm_recipe(task: str, config: dict) -> dict:
    mappings = {
        "svf": {
            "search_radius": "svf_radius",
            "num_directions": "svf_num_directions",
            "noise_level": "svf_noise",
        },
        "openness": {
            "search_radius": "openness_radius",
            "num_directions": "openness_num_directions",
        },
        "slrm": {"trend_radius": "slrm_radius"},
        "local_dominance": {
            "min_radius": "ld_min_rad",
            "max_radius": "ld_max_rad",
            "observer_height": "ld_observer_height",
        },
        "mstp": {
            "local_radius": "mstp_local",
            "meso_radius": "mstp_meso",
            "broad_radius": "mstp_broad",
        },
        "asvf": {
            "azimuth": "asvf_dir",
            "anisotropy": "asvf_weight",
        },
    }
    return {
        public_name: config[internal_name]
        for public_name, internal_name in mappings.get(task, {}).items()
        if internal_name in config
    }


def batch_recipe_json(
    tasks: list[str],
    config: dict,
    preset_key: str | None,
    plugin_version: str,
    source_name: str,
) -> str:
    """Serialize resolved Batch Relief settings as an importable recipe."""
    dem_name = os.path.splitext(os.path.basename(source_name))[0]
    return export_recipe(
        algorithms={task: _algorithm_recipe(task, config) for task in tasks},
        name=f"{dem_name} — Batch Relief",
        description="Resolved settings saved after a successful Batch Relief run.",
        landscape_type=preset_key or "custom",
        batch_preset=preset_key or "manual",
        plugin_version=plugin_version,
    )
