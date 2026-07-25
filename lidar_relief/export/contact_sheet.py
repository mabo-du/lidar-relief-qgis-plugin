"""contact_sheet.py — Multi-panel comparison image of several visualisations.

exports: VISUALISATIONS, visualisation_names(),
         compute_panels(dem, cellsize, names, feedback) -> list[tuple[str, ndarray]],
         normalise_panel(array) -> ndarray,
         build_contact_sheet(panels, columns, gutter, label_height) -> ndarray,
         write_png(rgb, path) -> str,
         pillow_available() -> bool

used_by: algorithms/contact_sheet_algorithm.py

rules:
  No QGIS imports — GDAL only for the PNG write, so this is testable
  headless.
  Panels are a PREVIEW. The caller is expected to hand in an already
  downsampled DEM: running a full-resolution Sky-View Factor for a
  thumbnail would take minutes for no benefit, and the point of the
  sheet is to choose a visualisation quickly.
  Labels use Pillow when it is importable and are skipped otherwise —
  Pillow is not guaranteed inside every QGIS Python. The sheet must
  still be produced without it, because unlabelled panels in a known
  order are far more useful than no sheet at all.
  Every panel is normalised INDEPENDENTLY. These images are for visual
  comparison, never for measurement — the plugin's real algorithms
  produce the quantitative output.
agent:   claude-opus-5 | anthropic | 2026-07-25 | s_20260725_001 |
         New module. The plugin ships 29 algorithms and the README tells
         users to "compare multiple visualizations", but offered no way
         to do that except running them one at a time and toggling
         layers.
"""

import logging

import numpy as np

from ..core.blend import simple_red_relief
from ..core.hillshade import multidirectional_hillshade
from ..core.local_dominance import compute_local_dominance
from ..core.mstp import multi_scale_topographic_position
from ..core.openness import topographic_openness
from ..core.ruggedness import compute_ruggedness
from ..core.slope import compute_slope
from ..core.slrm import simple_local_relief_model
from ..core.svf import sky_view_factor
from ..core.vat import compute_vat

logger = logging.getLogger(__name__)

# Panel background and label colours (RGB).
_BACKGROUND = (24, 24, 24)
_LABEL_TEXT = (245, 245, 245)


def _hillshade(dem, cellsize):
    return multidirectional_hillshade(dem, cellsize)


def _slrm(dem, cellsize):
    return simple_local_relief_model(dem, radius=max(2, int(round(10.0 / cellsize))))


def _svf(dem, cellsize):
    return sky_view_factor(dem, cellsize, num_directions=16, search_radius=10)


def _openness_pos(dem, cellsize):
    return topographic_openness(dem, cellsize, num_directions=16, search_radius=10)


def _openness_neg(dem, cellsize):
    return topographic_openness(
        dem, cellsize, num_directions=16, search_radius=10, is_negative=True
    )


def _slope(dem, cellsize):
    return compute_slope(dem, cellsize, units="degrees")


def _tri(dem, cellsize):
    return compute_ruggedness(dem, cellsize)


def _local_dominance(dem, cellsize):
    return compute_local_dominance(dem, cellsize)


def _vat(dem, cellsize):
    return compute_vat(dem, cellsize, svf_radius=10, openness_radius=10)


def _red_relief(dem, cellsize):
    return simple_red_relief(dem, cellsize, slrm_radius=10)


def _mstp(dem, cellsize):
    # Radii in pixels, scaled so the three scales stay separated even on
    # a small preview tile.
    return multi_scale_topographic_position(
        dem, local_radius=3, meso_radius=12, broad_radius=40
    )


# Ordered so the cheapest, most generally useful visualisations come
# first — a user who limits the sheet to four panels gets a sensible set.
VISUALISATIONS = [
    ("Multi-directional Hillshade", _hillshade, False),
    ("Simple Local Relief Model", _slrm, False),
    ("Sky-View Factor", _svf, False),
    ("Positive Openness", _openness_pos, False),
    ("Negative Openness", _openness_neg, False),
    ("Slope (degrees)", _slope, False),
    ("Terrain Ruggedness Index", _tri, False),
    ("Local Dominance", _local_dominance, False),
    ("VAT composite", _vat, False),
    ("Simple Red Relief", _red_relief, False),
    ("MSTP (RGB)", _mstp, True),
]


def visualisation_names() -> list:
    """Return the display names, in sheet order."""
    return [name for name, _fn, _is_rgb in VISUALISATIONS]


def pillow_available() -> bool:
    """Whether panel labels can be drawn."""
    try:
        from PIL import ImageDraw  # noqa: F401

        return True
    except ImportError:
        return False


def compute_panels(dem: np.ndarray, cellsize: float, names, feedback=None) -> list:
    """Run the requested visualisations over a (small) DEM.

    Args:
        dem: 2D float32 DEM, nodata as NaN. Should already be downsampled.
        cellsize: Cell size of ``dem`` in map units.
        names: Display names to include, from :func:`visualisation_names`.
        feedback: Optional QGIS feedback object.

    Returns:
        List of ``(label, array)``. A visualisation that raises is
        skipped with a warning rather than failing the whole sheet —
        one unavailable optional dependency should not cost the user
        the other ten panels.
    """
    wanted = {n: i for i, n in enumerate(names)}
    panels = []

    for name, func, _is_rgb in VISUALISATIONS:
        if name not in wanted:
            continue
        if feedback is not None and getattr(feedback, "isCanceled", bool)():
            break
        if feedback is not None:
            push = getattr(feedback, "setProgressText", None)
            if callable(push):
                push(f"Contact sheet: computing {name}...")
        try:
            panels.append((name, func(dem, cellsize)))
        except Exception as exc:  # pragma: no cover - depends on optional deps
            logger.warning("Contact sheet panel %r failed: %s", name, exc)
            if feedback is not None:
                push_warn = getattr(feedback, "pushWarning", None) or getattr(
                    feedback, "pushInfo", None
                )
                if callable(push_warn):
                    push_warn(f"Skipping '{name}': {exc}")

    panels.sort(key=lambda item: wanted[item[0]])
    return panels


def _stretch_to_uint8(array: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Linearly stretch ``[lo, hi]`` to 0-255, tolerating NaN.

    Rules:
        NaN must be neutralised BEFORE the uint8 cast. Casting NaN to an
        integer type is undefined — NumPy emits "invalid value
        encountered in cast" and fills in whatever the hardware returns.
        Callers overwrite those cells afterwards, so the values never
        reach the image, but the warning is noise and the intermediate
        state is garbage. Map NaN to the low end instead.
    """
    scaled = (array - lo) / (hi - lo)
    scaled = np.nan_to_num(scaled, nan=0.0, posinf=1.0, neginf=0.0)
    return np.clip(scaled * 255.0, 0, 255).astype(np.uint8)


def normalise_panel(array: np.ndarray) -> np.ndarray:
    """Scale one visualisation to an 8-bit RGB panel.

    Uses a 2nd–98th percentile stretch, which is what makes faint
    archaeological relief visible; a plain min/max stretch lets a single
    outlier cell flatten everything else to mid-grey.

    Args:
        array: 2D float array, or a 3D (rows, cols, 3) RGB composite.

    Returns:
        uint8 array of shape (rows, cols, 3).
    """
    if array.ndim == 3:
        rgb = array
        if rgb.dtype == np.uint8:
            return rgb
        finite = np.isfinite(rgb)
        out = np.zeros(rgb.shape, dtype=np.uint8)
        if finite.any():
            lo, hi = np.percentile(rgb[finite], [2, 98])
            if hi > lo:
                out = _stretch_to_uint8(rgb, lo, hi)
        return out

    finite_mask = np.isfinite(array)
    grey = np.zeros(array.shape, dtype=np.uint8)
    if finite_mask.any():
        lo, hi = np.percentile(array[finite_mask], [2, 98])
        if hi > lo:
            grey = _stretch_to_uint8(array, lo, hi)
        else:
            grey = np.full(array.shape, 127, dtype=np.uint8)
    # NaN cells render as background rather than black, so nodata is
    # distinguishable from genuinely low values.
    grey[~finite_mask] = _BACKGROUND[0]
    return np.dstack([grey, grey, grey])


def build_contact_sheet(
    panels,
    columns: int = 3,
    gutter: int = 8,
    label_height: int = 22,
) -> np.ndarray:
    """Tile normalised panels into one labelled RGB mosaic.

    Args:
        panels: List of ``(label, array)`` from :func:`compute_panels`.
        columns: Panels per row.
        gutter: Pixels between panels.
        label_height: Strip reserved under each panel for its caption.
            Set to 0 to omit captions entirely.

    Returns:
        uint8 array of shape (rows, cols, 3).

    Raises:
        ValueError: If no panels were supplied.

    Rules:
        Every panel must already be the same shape — they all come from
        the same DEM, so this is a programming error if it fails.
    """
    if not panels:
        raise ValueError("No panels to render — select at least one visualisation.")

    columns = max(1, int(columns))
    images = [normalise_panel(array) for _label, array in panels]

    heights = {img.shape[0] for img in images}
    widths = {img.shape[1] for img in images}
    if len(heights) != 1 or len(widths) != 1:
        raise ValueError(
            f"Panels have inconsistent shapes (heights={heights}, widths={widths}); "
            "they must all derive from the same DEM window."
        )

    panel_h = images[0].shape[0]
    panel_w = images[0].shape[1]
    rows = (len(images) + columns - 1) // columns

    cell_h = panel_h + label_height
    sheet_h = rows * cell_h + (rows + 1) * gutter
    sheet_w = columns * panel_w + (columns + 1) * gutter

    sheet = np.zeros((sheet_h, sheet_w, 3), dtype=np.uint8)
    sheet[:, :] = _BACKGROUND

    for index, image in enumerate(images):
        row, col = divmod(index, columns)
        top = gutter + row * (cell_h + gutter)
        left = gutter + col * (panel_w + gutter)
        sheet[top : top + panel_h, left : left + panel_w] = image  # noqa: E203

    if label_height > 0:
        _draw_labels(sheet, panels, columns, gutter, panel_h, panel_w, label_height)

    return sheet


def _draw_labels(sheet, panels, columns, gutter, panel_h, panel_w, label_height):
    """Caption each panel, if Pillow is importable.

    Rules:
        Never raise. A sheet without captions is still useful; a
        traceback is not.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        logger.info(
            "Pillow is not installed, so contact sheet panels are unlabelled. "
            "Install it with `pip install Pillow` for captions."
        )
        return

    try:
        image = Image.fromarray(sheet)
        draw = ImageDraw.Draw(image)
        cell_h = panel_h + label_height

        for index, (label, _array) in enumerate(panels):
            row, col = divmod(index, columns)
            top = gutter + row * (cell_h + gutter)
            left = gutter + col * (panel_w + gutter)
            draw.text(
                (left + 2, top + panel_h + 4),
                f"{index + 1}. {label}",
                fill=_LABEL_TEXT,
            )

        sheet[:, :, :] = np.asarray(image)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not draw contact sheet labels: %s", exc)


def write_png(rgb: np.ndarray, path: str) -> str:
    """Write an RGB array to PNG.

    Uses GDAL's in-memory driver plus CreateCopy because the PNG driver
    is copy-only. GDAL is already a hard dependency, so this keeps the
    image write free of any optional package.

    Args:
        rgb: uint8 array of shape (rows, cols, 3).
        path: Output .png path.

    Returns:
        The path written.
    """
    from osgeo import gdal

    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError(f"Expected an (rows, cols, 3) RGB array, got {rgb.shape}")

    rows, cols, _ = rgb.shape
    mem_driver = gdal.GetDriverByName("MEM")
    mem_ds = mem_driver.Create("", cols, rows, 3, gdal.GDT_Byte)
    for b in range(3):
        mem_ds.GetRasterBand(b + 1).WriteArray(rgb[:, :, b])

    png_driver = gdal.GetDriverByName("PNG")
    if png_driver is None:
        raise RuntimeError("This GDAL build has no PNG driver.")
    out = png_driver.CreateCopy(path, mem_ds, strict=0)
    if out is None:
        raise RuntimeError(f"Failed to write contact sheet PNG: {path}")

    out = None
    mem_ds = None
    return path
