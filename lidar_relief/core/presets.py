"""presets.py — Research-validated parameter presets by archaeological terrain context.
exports: PRESETS dict, get_preset(context_name, cellsize) -> dict
used_by: algorithms/batch_algorithm.py
rules: Data-only module plus one conversion. No image computation.
  Distances are stored in METRES because archaeological features have a
  real-world size. get_preset converts them to pixels for the requested
  cell size. Storing pixels made every preset silently wrong on any DEM
  that was not exactly 1 m — a "20 px" search radius is 20 m at 1 m
  resolution but 5 m on the 0.25 m LiDAR common in UK/NL archaeology.
  get_preset returns a deep copy so callers can mutate it without
  corrupting the canonical preset.
  Counts and heights are NOT distances: num_directions is unitless and
  observer_height is already a real-world height. Neither is scaled.
agent:   claude-opus-5 | anthropic | 2026-07-25 | s_20260725_001 |
         Converted the stored radii from pixels to metres and added the
         cellsize argument. cellsize defaults to 1.0, so get_preset(name)
         returns exactly the pixel numbers it always did — existing
         callers and tests are unaffected — while batch_algorithm now
         passes the DEM's real cell size and gets correctly scaled radii.
         message: "the metre values are literally the old pixel values
         reinterpreted at 1 m, which is the resolution the presets were
         originally tuned at — so this preserves intent, not just numbers"
"""

import copy

from .scale import METRES, radius_to_pixels


# Distances in METRES. See module rules.
PRESETS = {
    "flat_agricultural": {
        "svf": {"search_radius_m": 20.0, "num_directions": 16, "noise_level": 1},
        "openness": {"search_radius_m": 15.0, "num_directions": 16},
        "slrm": {"trend_radius_m": 20.0},
        "local_dominance": {
            "min_rad_m": 10.0,
            "max_rad_m": 20.0,
            "observer_height": 1.7,
        },
    },
    "forested": {
        "svf": {"search_radius_m": 10.0, "num_directions": 16, "noise_level": 3},
        "openness": {"search_radius_m": 5.0, "num_directions": 16},
        "slrm": {"trend_radius_m": 12.0},
        "local_dominance": {
            "min_rad_m": 5.0,
            "max_rad_m": 15.0,
            "observer_height": 1.5,
        },
    },
    "upland_steep": {
        "svf": {"search_radius_m": 5.0, "num_directions": 16, "noise_level": 2},
        "openness": {"search_radius_m": 5.0, "num_directions": 16},
        "slrm": {"trend_radius_m": 8.0},
        "local_dominance": {
            "min_rad_m": 5.0,
            "max_rad_m": 10.0,
            "observer_height": 1.0,
        },
    },
    "coastal": {
        "svf": {"search_radius_m": 15.0, "num_directions": 32, "noise_level": 1},
        "openness": {"search_radius_m": 10.0, "num_directions": 32},
        "slrm": {"trend_radius_m": 25.0},
        "local_dominance": {
            "min_rad_m": 15.0,
            "max_rad_m": 30.0,
            "observer_height": 2.0,
        },
    },
}

# Maps the metre-valued key in PRESETS to the pixel-valued key callers
# expect back from get_preset.
_DISTANCE_KEYS = {
    ("svf", "search_radius_m"): "search_radius",
    ("openness", "search_radius_m"): "search_radius",
    ("slrm", "trend_radius_m"): "trend_radius",
    ("local_dominance", "min_rad_m"): "min_rad",
    ("local_dominance", "max_rad_m"): "max_rad",
}


def get_preset(context_name: str, cellsize: float = 1.0) -> dict:
    """Return parameter values for a terrain context, scaled to ``cellsize``.

    Args:
        context_name: One of the keys of ``PRESETS``.
        cellsize: DEM cell size in map units. Defaults to 1.0, which
            reproduces the historical pixel values exactly.

    Returns:
        A deep copy with all distances converted to whole pixels under
        their original key names (``search_radius``, ``trend_radius``,
        ``min_rad``, ``max_rad``).

    Raises:
        ValueError: If the context is unknown or cellsize <= 0.

    Rules:
        Local Dominance needs min_rad < max_rad. On a very coarse DEM
        both can round to the same pixel count, so max_rad is nudged up
        to keep the ray non-degenerate.
    """
    if context_name not in PRESETS:
        raise ValueError(
            f"Unknown preset context: {context_name!r}. "
            f"Valid options: {list(PRESETS.keys())}"
        )
    if cellsize <= 0:
        raise ValueError(f"cellsize must be positive, got {cellsize}")

    preset = copy.deepcopy(PRESETS[context_name])

    for (group, metre_key), pixel_key in _DISTANCE_KEYS.items():
        metres = preset[group].pop(metre_key)
        preset[group][pixel_key] = radius_to_pixels(metres, METRES, cellsize)

    ld = preset["local_dominance"]
    if ld["max_rad"] <= ld["min_rad"]:
        ld["max_rad"] = ld["min_rad"] + 1

    return preset
