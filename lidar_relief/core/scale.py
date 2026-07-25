"""scale.py — Convert real-world distances to pixel radii.

exports: RADIUS_UNIT_OPTIONS, PIXELS, METRES,
         radius_to_pixels(value, units, cellsize, minimum, maximum) -> int,
         describe_radius(pixels, cellsize) -> str,
         PERFORMANCE_WARNING_PIXELS

used_by: algorithms/svf_algorithm.py, algorithms/openness_algorithm.py,
         algorithms/asvf_algorithm.py, algorithms/slrm_algorithm.py,
         algorithms/rvt_openness_algorithm.py, algorithms/batch_algorithm.py
         core/presets.py → radius_to_pixels

rules:
  Pure Python/NumPy — no QGIS, no GDAL.
  A search radius expressed in PIXELS is resolution-dependent: 20 px is
  20 m on a 1 m DEM but 5 m on a 0.25 m DEM. Archaeological features have
  a real-world size, so any parameter describing feature scale should be
  convertible to and reported in metres.
  radius_to_pixels always returns at least `minimum` (default 1) — a
  sub-pixel radius would otherwise silently become a no-op ray of length
  zero.
agent:   claude-opus-5 | anthropic | 2026-07-25 | s_20260725_001 |
         New module. Five algorithms exposed radius only in pixels and
         core/presets.py hard-coded pixel radii that are only correct on
         a 1 m DEM, so the "research-validated" landscape presets
         silently mis-scaled on sub-metre LiDAR — the common case in UK
         and NL archaeology.
"""

PIXELS = "pixels"
METRES = "metres"

# Order matters: index 0 is the default in the Processing enum, and
# keeping PIXELS first preserves the behaviour of saved Processing models
# and scripts written before the metres option existed.
RADIUS_UNIT_OPTIONS = [
    "Pixels (resolution-dependent)",
    "Metres (map units)",
]
RADIUS_UNIT_VALUES = [PIXELS, METRES]

# Horizon-scanning cost grows with the square of the radius. Past this
# many pixels a single tile takes long enough that the user probably
# meant metres, or should resample the DEM first.
PERFORMANCE_WARNING_PIXELS = 200


def radius_to_pixels(
    value: float,
    units: str,
    cellsize: float,
    minimum: int = 1,
    maximum: int = None,
) -> int:
    """Convert a radius given in pixels or metres into whole pixels.

    Args:
        value: The radius as the user supplied it.
        units: Either ``PIXELS`` or ``METRES``.
        cellsize: Pixel size in map units (must be > 0).
        minimum: Smallest permitted result. Defaults to 1 — a zero radius
            means the horizon scan samples nothing.
        maximum: Optional clamp, e.g. to keep a tile's halo manageable.

    Returns:
        Radius in whole pixels.

    Raises:
        ValueError: If ``units`` is unrecognised or ``cellsize`` <= 0.

    Rules:
        Rounds to nearest, then clamps. Never returns 0.
    """
    if units not in (PIXELS, METRES):
        raise ValueError(f"units must be {PIXELS!r} or {METRES!r}, got {units!r}")
    if cellsize <= 0:
        raise ValueError(f"cellsize must be positive, got {cellsize}")

    if units == PIXELS:
        pixels = int(round(value))
    else:
        pixels = int(round(value / cellsize))

    pixels = max(minimum, pixels)
    if maximum is not None:
        pixels = min(maximum, pixels)
    return pixels


def describe_radius(pixels: int, cellsize: float) -> str:
    """Render a radius in both units, for the Processing log.

    Making the real-world size visible is the cheapest defence against
    the resolution trap: a user who asked for 20 px on a 0.25 m DEM sees
    "20 px = 5.0 m" and can tell immediately that it is too small for
    the earthwork they are looking for.
    """
    return f"{pixels} px = {pixels * cellsize:.1f} m (cell size {cellsize:g} m)"


def resolve_radius(
    value: float,
    units: str,
    cellsize: float,
    label: str,
    feedback=None,
    minimum: int = 1,
    maximum: int = None,
) -> int:
    """Convert a radius and report the result through ``feedback``.

    Convenience wrapper used by the Processing algorithms so every one of
    them reports scale the same way.

    Args:
        value: Radius as supplied by the user.
        units: ``PIXELS`` or ``METRES``.
        cellsize: Pixel size in map units.
        label: Human-readable parameter name for the log line.
        feedback: Optional QGIS feedback object.
        minimum: Smallest permitted result.
        maximum: Optional clamp.

    Returns:
        Radius in whole pixels.
    """
    pixels = radius_to_pixels(value, units, cellsize, minimum=minimum, maximum=maximum)

    if feedback is not None:
        push_info = getattr(feedback, "pushInfo", None)
        if callable(push_info):
            push_info(f"{label}: {describe_radius(pixels, cellsize)}")

        if pixels > PERFORMANCE_WARNING_PIXELS:
            push_warning = getattr(feedback, "pushWarning", None) or push_info
            if callable(push_warning):
                push_warning(
                    f"{label} is {pixels} px, which will be slow — horizon "
                    f"scanning cost grows with the square of the radius. "
                    f"Consider resampling the DEM to a coarser cell size "
                    f"instead of scanning further in pixels."
                )

    return pixels
