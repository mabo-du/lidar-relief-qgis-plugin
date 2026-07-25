"""ruggedness.py — Riley Terrain Ruggedness Index (TRI) computation.

exports: compute_ruggedness(dem, cellsize) -> ndarray
used_by: algorithms/ruggedness_algorithm.py → compute_ruggedness
rules:
  Pure NumPy — no QGIS imports.
  Input dem must be float32/float64 with nodata as np.nan.
  Output is float32 in the DEM's ELEVATION units, not a normalised
  index — values scale with vertical relief and raster resolution, so
  TRI rasters from different resolutions are not comparable.
  cellsize is accepted for signature parity with the other core
  algorithms (process_in_tiles passes it positionally) but Riley TRI is
  defined on the 3x3 elevation neighbourhood alone and does not use it.
  Nodata NEIGHBOURS contribute zero difference, so data edges do not
  gain artificial high-ruggedness halos; nodata CENTRES stay nodata.
agent:   claude-opus-5 | anthropic | 2026-07-25 | s_20260725_001 |
         Added the CodeDNA header — this was the only core module
         without one, so an agent doing a manifest-only pass could not
         see its contract. No logic change; the Riley implementation
         verified correct against a hand-computed 3x3 neighbourhood.
"""

import numpy as np


def compute_ruggedness(dem: np.ndarray, cellsize: float) -> np.ndarray:
    """Return Riley Terrain Ruggedness Index values in elevation units.

    Each output pixel is the square root of the summed squared elevation
    differences between the centre cell and its eight neighbours. Nodata
    centre cells remain nodata; nodata neighbours contribute zero so that
    data edges do not acquire artificial high-ruggedness halos.
    """
    if cellsize <= 0:
        raise ValueError("cellsize must be positive")
    if dem.ndim != 2:
        raise ValueError("dem must be a 2D array")

    source = np.asarray(dem, dtype=np.float64)
    padded = np.pad(source, 1, mode="edge")
    centre = padded[1:-1, 1:-1]
    squared_difference_sum = np.zeros(source.shape, dtype=np.float64)

    rows, columns = source.shape
    for row_offset in range(3):
        for column_offset in range(3):
            if row_offset == 1 and column_offset == 1:
                continue
            # Slice bounds hoisted into locals: black formats
            # `a : a + b` with spaces around the colon, which the QGIS
            # plugin scanner rejects as E203. Keeping the expressions
            # simple lets this file satisfy the formatter AND the
            # scanner, instead of having to skip formatting entirely.
            row_end = row_offset + rows
            column_end = column_offset + columns
            neighbour = padded[row_offset:row_end, column_offset:column_end]
            difference = np.where(np.isnan(neighbour), 0.0, neighbour - centre)
            squared_difference_sum += difference * difference

    result = np.sqrt(squared_difference_sum).astype(np.float32)
    result[np.isnan(source)] = np.nan
    return result
