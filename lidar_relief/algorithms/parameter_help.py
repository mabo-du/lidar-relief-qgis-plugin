"""Plain-language help for LiDAR Relief Processing parameters.

This module deliberately has no QGIS imports, so its wording and fallback
behaviour can be tested in an ordinary Python environment.
"""

from __future__ import annotations


EXACT_HELP = {
    "INPUT": (
        "Select the source raster. For terrain visualisations this should be a "
        "bare-earth DEM in a projected CRS, with horizontal and vertical units "
        "in metres. The source is read-only and is not modified."
    ),
    "INPUTS": (
        "Select one or more source rasters. They should use compatible "
        "projected coordinate systems, cell sizes, extents, and elevation units."
    ),
    "SOURCE_DEM": (
        "Select the original bare-earth DEM used to create the result. It is "
        "used for provenance and validation and will not be modified."
    ),
    "SEARCH_RADIUS": (
        "Sets the terrain neighbourhood examined around each cell. In metre "
        "mode, start near the expected feature width: small radii emphasise "
        "fine banks and ditches, while large radii reveal broader landforms but "
        "can suppress small details. Larger values also take longer to process."
    ),
    "RADIUS": (
        "Controls the real-world scale of features emphasised by the operation. "
        "Use a value near the width of the feature of interest; smaller values "
        "retain fine detail and larger values describe broader terrain context."
    ),
    "RADIUS_UNITS": (
        "Choose metres for results that remain comparable between DEMs with "
        "different resolutions. Pixel units are useful for reproducing an older "
        "workflow but change their real-world meaning when cell size changes."
    ),
    "NUM_DIRECTIONS": (
        "Number of compass directions sampled around each cell. More directions "
        "reduce directional artefacts and produce smoother results, but require "
        "more processing time. The default is a dependable first choice."
    ),
    "DIRECTIONS": (
        "Number of illumination or viewing directions. Higher values reduce "
        "directional bias at the cost of longer processing time."
    ),
    "AZIMUTHS": (
        "Comma-separated light directions in degrees clockwise from north. "
        "Using several evenly spaced directions reduces the chance that a "
        "linear feature disappears because it is parallel to one light source."
    ),
    "ALTITUDE": (
        "Height of the simulated light above the horizon, in degrees. Low "
        "angles strengthen subtle relief but exaggerate noise; higher angles "
        "give gentler, less directional shading. Around 35° is a useful start."
    ),
    "CELLSIZE": (
        "Output DEM pixel size in map units, normally metres. A smaller cell "
        "captures more detail but increases memory, file size, and processing "
        "time. Do not choose a resolution finer than the point spacing supports."
    ),
    "NOISE_LEVEL": (
        "Select how aggressively small elevation variations are treated as "
        "noise. Use low filtering for clean archaeological LiDAR and increase it "
        "only when speckle or surface roughness obscures coherent features."
    ),
    "USE_GPU": (
        "Uses a compatible GPU when available. This changes performance, not "
        "the intended interpretation of the result. Leave disabled if GPU "
        "drivers or memory are uncertain."
    ),
    "PRESET": (
        "Applies a tested group of starting values for a landscape type. A "
        "preset is a starting point, not an archaeological classification; "
        "inspect the preview and adjust scales for the feature size."
    ),
    "LANDSCAPE_TYPE": (
        "Choose the setting closest to the terrain and vegetation context. It "
        "changes visualisation scales and defaults, not the underlying DEM."
    ),
    "VISUALISATIONS": (
        "Select the techniques to compare. Combining complementary methods is "
        "safer than interpreting a feature visible in only one rendering."
    ),
    "MAX_DIMENSION": (
        "Maximum preview width or height in pixels. Lower values return a quick "
        "comparison; higher values preserve more detail but use more memory."
    ),
    "COLUMNS": (
        "Number of panels placed across the comparison sheet. This affects only "
        "the report layout, not the visualisation calculations."
    ),
    "OPACITY": (
        "Controls how strongly the upper layer contributes to the blend. Zero "
        "hides it and one shows its full contribution; 0.5 is an even blend."
    ),
    "BLEND_MODE": (
        "Determines how the two raster values are combined. Different modes "
        "emphasise highlights, shadows, or contrast; compare modes and avoid "
        "treating colour or brightness alone as archaeological evidence."
    ),
    "CONFIDENCE": (
        "Statistical confidence threshold used to distinguish likely change "
        "from measurement uncertainty. Higher confidence is more conservative "
        "and reports fewer changes."
    ),
    "RMSE_OLD": (
        "Vertical root-mean-square error of the older DEM, in metres. Use survey "
        "metadata rather than guessing; it directly affects change significance."
    ),
    "RMSE_NEW": (
        "Vertical root-mean-square error of the newer DEM, in metres. Use survey "
        "metadata rather than guessing; it directly affects change significance."
    ),
    "TILE_SIZE": (
        "Processing tile width in pixels. Larger tiles may be faster but require "
        "more memory; reduce this value if QGIS runs out of memory."
    ),
    "OUTPUT": (
        "Choose where QGIS will write the result. A temporary output is useful "
        "for exploration; save a GeoTIFF when the result must be retained."
    ),
    "OUTPUT_DIR": (
        "Choose a folder for the generated files. Existing unrelated files are "
        "left untouched; use a new folder when you want a self-contained export."
    ),
}


def _pattern_help(name: str) -> str | None:
    """Return practical help for recurring families of parameter names."""
    if name.startswith("OUTPUT") or name.endswith("_OUTPUT"):
        return EXACT_HELP["OUTPUT"]
    if name.startswith("INPUT") or name.endswith("_LAYER"):
        return EXACT_HELP["INPUT"]
    if "RADIUS" in name or name.endswith("_RAD") or name.endswith("_RADII"):
        return EXACT_HELP["RADIUS"]
    if "DIRECTION" in name:
        return EXACT_HELP["DIRECTIONS"]
    if name.startswith("RUN_"):
        return (
            "Enable this option to include the named visualisation in the batch. "
            "Disabling it saves processing time and does not affect other outputs."
        )
    if name.endswith("_FILE") or name.endswith("_SIDECAR"):
        return (
            "Select the referenced file. Its format and coordinate system must "
            "match the accompanying inputs; the file is read-only."
        )
    if "FORMAT" in name or "PROFILE" in name or "RESAMPLING" in name:
        return (
            "Choose the output or processing profile. The default balances "
            "compatibility, quality, and file size for most QGIS workflows."
        )
    if "THRESHOLD" in name or "CONFIDENCE" in name:
        return (
            "Controls how selective the operation is. Higher thresholds usually "
            "return fewer, stronger candidates; compare results and validate "
            "against independent evidence."
        )
    if name.startswith("INCLUDE_") or name.startswith("GENERATE_"):
        return (
            "Enable this to include the named optional item. It may increase "
            "processing time or output size but does not alter the source data."
        )
    return None


def resolve_parameter_help(
    algorithm_name: str, parameter_name: str, description: str
) -> str:
    """Return non-empty, plain-language help for a Processing parameter."""
    del algorithm_name  # Reserved for future algorithm-specific overrides.
    name = (parameter_name or "").upper()
    if name in EXACT_HELP:
        return EXACT_HELP[name]
    patterned = _pattern_help(name)
    if patterned:
        return patterned
    label = (description or parameter_name or "This setting").strip().rstrip(".")
    return (
        f"{label}. This option changes how the operation is configured. "
        "The default is a safe starting point; change it deliberately, preview "
        "the result, and record non-default values for reproducibility."
    )
