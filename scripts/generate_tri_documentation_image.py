#!/usr/bin/env python3
"""Generate the documented TRI figure directly from the plugin core."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lidar_relief.core.ruggedness import compute_ruggedness  # noqa: E402

DEFAULT_OUTPUT = Path("lidar_relief/docs/images/tri-synthetic-example.png")


def synthetic_archaeological_dem(size: int = 256) -> np.ndarray:
    """Return a deterministic DEM containing labelled idealized features."""
    rows, columns = np.mgrid[0:size, 0:size]
    dem = 18.0 + columns * 0.012 + rows * 0.004

    mound_distance = np.hypot(columns - 78, rows - 104)
    dem += 1.25 * np.exp(-((mound_distance / 11.0) ** 2))

    ring_distance = np.hypot(columns - 166, rows - 113)
    dem -= 0.72 * np.exp(-(((ring_distance - 32.0) / 3.2) ** 2))

    bank_centre = 187.0 - 15.0 * np.sin(columns / 31.0)
    dem += 0.55 * np.exp(-(((rows - bank_centre) / 3.2) ** 2))

    furrow_mask = columns >= 116
    furrows = 0.14 * np.sin((columns + rows * 0.28) * np.pi / 6.0)
    dem += np.where(furrow_mask, furrows, 0.0)
    return dem.astype(np.float32)


def generate(output: Path) -> None:
    """Render the synthetic DEM and the actual Riley TRI implementation."""
    dem = synthetic_archaeological_dem()
    tri = compute_ruggedness(dem, cellsize=1.0)

    plt.style.use("dark_background")
    figure, axes = plt.subplots(1, 2, figsize=(16, 7))
    figure.subplots_adjust(
        left=0.06,
        right=0.94,
        bottom=0.12,
        top=0.84,
        wspace=0.34,
    )
    figure.patch.set_facecolor("#202124")
    figure.suptitle(
        "LiDAR Relief — verified synthetic TRI output",
        fontsize=20,
        fontweight="bold",
    )

    dem_image = axes[0].imshow(dem, cmap="terrain")
    axes[0].set_title("Deterministic synthetic archaeological DEM")
    axes[0].text(36, 96, "mound", color="white", weight="bold")
    axes[0].text(154, 112, "ring ditch", color="white", weight="bold")
    axes[0].text(34, 177, "sinuous bank", color="white", weight="bold")
    axes[0].text(166, 211, "ridge-and-furrow", color="white", weight="bold")
    figure.colorbar(dem_image, ax=axes[0], label="Elevation (m)", shrink=0.78)

    tri_image = axes[1].imshow(tri, cmap="magma", vmin=0)
    axes[1].set_title("Plugin compute_ruggedness result (Riley 3×3)")
    figure.colorbar(
        tri_image,
        ax=axes[1],
        label="Local elevation contrast (m)",
        shrink=0.78,
    )
    for axis in axes:
        axis.set_xlabel("Easting cell")
        axis.set_ylabel("Northing cell")

    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(
        output,
        dpi=160,
        facecolor=figure.get_facecolor(),
        metadata={
            "Software": "LiDAR Relief compute_ruggedness documentation generator",
            "Description": (
                "Deterministic synthetic DEM and direct output from "
                "lidar_relief.core.ruggedness.compute_ruggedness"
            ),
        },
    )
    plt.close(figure)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    generate(args.output)
    print(f"Wrote verified TRI documentation figure: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
