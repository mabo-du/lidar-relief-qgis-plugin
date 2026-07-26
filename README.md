<p align="center">
  <img src="docs/brand/project-lockup.svg" alt="Dig:Tools" width="720">
</p>

# LiDAR Relief Visualization Plugin — v2.1

[![QGIS Plugin](https://img.shields.io/badge/QGIS-3%20%7C%204-589632?logo=qgis&logoColor=white)](https://plugins.qgis.org/plugins/lidar_relief/)
[![Version](https://img.shields.io/badge/release-2.1.2-C28B22)](https://github.com/dig-tools/lidar-relief-qgis-plugin/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Tests](https://github.com/dig-tools/lidar-relief-qgis-plugin/actions/workflows/tests.yml/badge.svg)](https://github.com/dig-tools/lidar-relief-qgis-plugin/actions/workflows/tests.yml)

A QGIS Processing plugin for advanced archaeological terrain visualization from
Digital Elevation Models (DEMs). Provides **31 algorithms** covering LiDAR
relief visualization, multi-temporal change detection, multi-sensor fusion,
AI feature detection, point cloud ground filtering, and export/publishing —
all within QGIS. Core terrain tools have no dependencies beyond QGIS's bundled
libraries; specialized capabilities clearly identify their optional packages.

📖 **[Read the User Guide](lidar_relief/USER_GUIDE.md)** — every algorithm
explained, with guidance on choosing between them. The guide also ships inside
the plugin, and every algorithm dialog in QGIS has a **Help** button that opens
it at the relevant section.

![Synthetic DEM and Terrain Ruggedness Index result](lidar_relief/docs/images/tri-synthetic-example.png)

*Verified algorithm output, not a mocked result or a QGIS screenshot. The
left panel is a deterministic synthetic DEM and the right panel is calculated
directly by the plugin's current `compute_ruggedness` implementation. The vivid
`terrain` and `magma` colour ramps are presentation styling; the TRI values are
unaltered. Rebuild it with
`python scripts/generate_tri_documentation_image.py`. It remains a controlled
visual aid, not an archaeological classification.*

## Quick start

1. Install **LiDAR Relief Visualization** from QGIS Plugin Manager.
2. Load a projected DEM whose horizontal and vertical units are metres. If you
   load a geographic (lat/lon) DEM, or one with non-square pixels, the plugin
   warns you in the Processing log before it starts — cell sizes in degrees
   make slope, SVF, openness, and every search radius meaningless.
3. Open **Processing Toolbox → LiDAR Relief**.
4. Run **Visualisation Contact Sheet** to see several techniques over your own
   ground in seconds, then start with **Batch Relief Visualisation** and the
   closest landscape preset, or **Terrain Ruggedness Index (TRI)** for local
   elevation contrast.
5. Compare multiple visualizations and validate potential features against
   complementary evidence before interpretation.

The **Plugins → LiDAR Relief** menu also provides DEM preflight guidance,
favorite tools and recipes, recent outputs, synchronized raster comparison,
interpretation notes, study-area bookmarks, dependency diagnostics, and a
redacted support bundle.

## Features

### Terrain Visualization and Analysis

The plugin integrates directly into the QGIS Processing Toolbox and provides
the following terrain visualization algorithms:

- **Multi-directional Hillshade**: Blends multiple illumination angles to
  eliminate the directional bias of traditional single-light-source hillshades.
- **RVT Multi-directional Hillshade**: Reference implementation from the
  rvt-py (Relief Visualization Toolbox) package. Useful for cross-validating
  results against any other RVT installation (QGIS, R, standalone).
- **Simple Local Relief Model (SLRM)**: Removes macro-topography to isolate
  micro-relief features like ancient ditches, walls, and mounds.
- **Sky-View Factor (SVF)**: Computes the proportion of the sky visible from
  each pixel. Concave features (pits, ditches) appear dark, convex features
  (ridges, mounds) appear bright. Includes 1D look-ahead noise filter.
- **Anisotropic Sky-View Factor (ASVF)**: Directionally weighted SVF for
  simulating anisotropic lighting conditions.
- **Topographic Openness (Positive/Negative)**: Highlights ridges/crests
  (positive) or valleys/pits (negative).
- **RVT Topographic Openness**: Reference implementation from the `rvt-py`
  Relief Visualization Toolbox, exposing the same Positive/Negative modes,
  search directions, and search radius as the native implementation for
  cross-validation against other RVT installations.
- **Local Dominance**: Horizon-scanning ray trace identifying locally dominant
  or dominated pixels.
- **Multi-Scale Topographic Position (MSTP)**: DEV at Broad/Meso/Local scales
  mapped to RGB false-colour.
- **Enhanced 4-Scale Topographic Position (e4MSTP)**: Advanced composite
  combining Openness, LD, Slope, dual-scale SVF, and MSTP.
- **Visualization for Archaeological Topography (VAT)**: Multi-indicator
  composite blending Hillshade, Slope, and Positive Openness.
- **Simple Red Relief**: Patent-free RRIM analogue blending openness and slope.
- **PCA RGB Composite**: Principal Component Analysis across 16+ directional
  hillshades for linear feature detection.
- **ML-Ready VRT Export**: Normalized multi-band composites for direct CNN input.
- **Slope** (degrees and percent), **Blend Visualizations** (Multiply, Screen,
  Overlay), **Batch Relief Visualisation** (single-pass multi-algorithm with
  terrain presets).
- **Terrain Ruggedness Index (TRI)**: Riley 3×3 local elevation contrast for
  mapping scarps, banks, rough ground, stone spreads, and quarrying.
- **Visualisation Contact Sheet**: Renders several visualisations of the same
  DEM as one labelled multi-panel image, so you can see which technique reveals
  your features before committing to a full-resolution run. The DEM is
  downsampled first, so a sheet returns in seconds.

Search radii on Sky-View Factor, Openness, ASVF, SLRM and RVT Openness can be
given in **metres** as well as pixels. Archaeological features have a
real-world size, and a 20 px radius means 20 m on a 1 m DEM but only 5 m on
0.25 m LiDAR — every run reports its radius in both units in the log.

### Export and publishing

- **Cloud-Optimized GeoTIFF (COG) Export**: Convert any algorithm output to a
  COG with interactive MapLibre GL JS web viewer. Upload to GitHub Pages, S3,
  or any static host — stakeholders can explore visualizations without GIS.
- **Field Survey Export (QField/Mergin)**: Package rasters and anomaly
  detections as GeoPackage + QGIS project for mobile ground-truthing. Includes
  structured archaeological schema (feature type, confidence, field status).
- **PDF Report Generator**: CIfA-compliant PDF reports with full parameter
  provenance, statistics, histogram, and certification.
- **Visualization Recipes**: Share algorithm parameters as JSON files —
  community-driven preset sharing beyond the 4 built-in presets. Batch Relief
  can save the successfully resolved settings from a run as a recipe.
- **Named Batch Outputs**: Create a complete output set using safe templates
  built from the DEM, method, preset, and run date.
- **Interpretation Notes**: Record a map-centre observation, confidence, and
  active visualization as WGS84 GeoJSON or CSV.
- **Provenance Sidecars**: Every terrain output is written with a
  `<output>.lidar-relief.json` recording the plugin version, algorithm, exact
  parameters, source path, source checksum, CRS and cell size. The **Inspect
  Provenance Record** algorithm reads one back and verifies the source DEM has
  not changed since — so a result can be audited or regenerated months later,
  by someone else.

### Point-cloud processing

- **CSF Ground Filter**: Generate archaeology-optimized DEMs directly from
  LAS/LAZ files using the Cloth Simulation Filter, with presets tuned to
  preserve subtle earthworks.
- **PDAL Classification Pipelines**: PMF-based ground filtering with
  archaeology-specific parameter configurations.

### Advanced analysis

- **Multi-temporal Change Detection**: Probabilistic DEM of Difference (DoD)
  with propagated RMSE-based Level of Detection masking. Detect erosion,
  deposition, and newly revealed features from repeat LiDAR surveys.
- **Multi-Sensor Fusion**: Co-register Sentinel-2 multispectral bands with
  LiDAR relief. Four fusion recipes combining topographic and spectral data
  (Terrain+CIR, Crop Marks, Erosion Risk, Bare Earth Composite).
- **Synchronized Raster Comparison**: Review two loaded rasters side by side
  with linked pan and zoom, without changing their source data.
- **Study-Area Bookmarks**: Save and restore named map extents with their CRS.
- **Advanced e4MSTP Controls**: Tune openness, Local Dominance, MSTP scales,
  and tile size while canonical defaults preserve previous output.

### AI and machine learning

- **AI Feature Detection**: Load your own ONNX models and run inference on
  plugin visualizations. The model type is detected automatically from its
  output signature. Plugin acts as inference engine only — bring your own
  pre-trained model.
  - *Object detection* (YOLOv5/v7/v8/v11, SSD) → bounding-box polygons, with
    tiled processing, NMS and confidence filtering.
  - *Semantic segmentation* (U-Net, SegFormer, DeepLab) → a class-index raster
    plus per-class polygons carrying area, pixel count and mean confidence.
    Usually the better fit for archaeology, where ditches, banks and field
    systems are linear or areal rather than box-shaped.

### GPU acceleration

- **CuPy Compute Backend**: Optional GPU acceleration for the horizon-scanning
  algorithms. Tick **Use GPU acceleration** on **Sky-View Factor** or
  **Topographic Openness**; the plugin detects CUDA automatically and falls
  back to NumPy — logging why — when CuPy is absent, the driver is unusable, or
  SVF noise removal is enabled (that filter is CPU-only). GPU and CPU walk the
  same horizon rays, so results agree to float precision rather than being
  merely similar.

## Installation

### Method 1: QGIS Plugin Manager (Recommended)

1. Open **Plugins → Manage and Install Plugins…**.
2. Search for **LiDAR Relief Visualization** in **All**.
3. Select it and click **Install Plugin**.
4. Algorithms appear in the **Processing Toolbox** under `LiDAR Relief`,
   `LiDAR Relief — Export`, `LiDAR Relief — Point Cloud`,
   `LiDAR Relief — Temporal`, `LiDAR Relief — Fusion`, and
   `LiDAR Relief — AI/ML`.

### Method 2: Install from a Release ZIP

1. Download `lidar_relief.zip` from the latest
   **[GitHub release](https://github.com/dig-tools/lidar-relief-qgis-plugin/releases)**.
2. Open **Plugins → Manage and Install Plugins… → Install from ZIP**.
3. Select the downloaded archive and click **Install Plugin**.

### Method 3: Manual Installation (For Developers)
Copy or symlink the `lidar_relief` directory into your QGIS plugins folder:
- **Windows**: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
- **Linux**: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
- **macOS**: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`

### Optional Dependencies

Most features work with QGIS's built-in libraries. Optional features
require additional Python packages installed via the OSGeo4W Shell:

| Feature | Package | Install command |
|---------|---------|----------------|
| COG Export | `rio-cogeo` | `pip install rio-cogeo` |
| PDF Reports | `reportlab` | `pip install reportlab` |
| CSF Ground Filter | `cloth-simulation-filter` | `pip install cloth-simulation-filter` |
| Temporal Analysis | `xarray`, `rioxarray` | `pip install xarray rioxarray` |
| Multi-Sensor Fusion | `rasterio`, `rioxarray` | `pip install rasterio rioxarray` |
| AI Detection | `onnxruntime` | `pip install onnxruntime` |
| GPU Acceleration | `cupy-cuda12x` | `pip install cupy-cuda12x` |
| LAS/LAZ input | `laspy` or `pdal` | `pip install laspy` |
| RVT Relief Toolbox | `rvt-py` | `pip install rvt-py` |

All optional features degrade gracefully with clear error messages pointing
to the correct install command.

### Troubleshooting

- If the plugin is missing, clear any search filters and ensure **Settings →
  Plugin Repositories → QGIS Official Plugin Repository** is enabled.
- If an optional tool reports a missing package, install it into the Python
  environment used by QGIS (OSGeo4W Shell on Windows), then restart QGIS.
- When reporting a problem, include the QGIS version, operating system, plugin
  version, input raster CRS/resolution, and the full Processing log at the
  [issue tracker](https://github.com/dig-tools/lidar-relief-qgis-plugin/issues).

### Interpreter requirements for the test suite

Several test modules begin with `pytest.importorskip(...)`, so an interpreter
missing an optional package **skips those modules silently** and still reports
a green run. `test_golden_regression.py` gates the entire rvt-py
cross-validation suite this way, and seven modules depend on GDAL. A run
reporting more than a handful of skips is an incomplete run, not a healthy one.

`./test.sh` installs what it can and prints a warning naming anything that will
be skipped. To set an interpreter up by hand:

```bash
pip install rvt-py laspy rio-cogeo reportlab xarray rioxarray \
            onnxruntime rasterio cloth-simulation-filter
# GDAL's Python bindings must match the system libgdal exactly:
pip install "gdal==$(gdal-config --version)"
```

A fully equipped interpreter runs the suite with only CUDA- and PDAL-gated
tests skipped. QGIS itself is not needed — `core/` is pure NumPy/GDAL, and CI
runs the QGIS-dependent smoke test inside the official QGIS container.

### Security and dependency auditing

The repository keeps a focused inventory of directly installed Python
dependencies in `requirements-audit.txt`. To reproduce the automated security
checks locally:

```bash
semgrep scan --config auto --error lidar_relief scripts
pip-audit -r requirements-audit.txt --no-deps --disable-pip
```

The dependency audit intentionally checks direct packages only. Transitive
dependencies are resolved by the supported QGIS/Python environment, while GDAL
must remain aligned with the version and native bindings supplied by QGIS.

### Runtime smoke test for developers

The repository includes `scripts/qgis_smoke_test.py`, which loads the plugin
in a headless QGIS session, verifies all algorithms are registered, executes
TRI against a synthetic DEM, exercises named Batch Relief output and resolved
recipe export, validates the results, and unloads cleanly. CI runs this test
inside the official QGIS container on every change.

### Documentation image policy

Documentation must not present mockups or AI-generated imagery as plugin
output. The only raster figure currently used in this README and the shipped
guide is generated from a deterministic synthetic DEM by the current plugin
core. Its PNG metadata records the generator, and automated tests verify the
file, provenance fields, and every local Markdown image reference.

## Architecture

The plugin separates QGIS UI bindings from the mathematical core:

- **`core/`**: Pure NumPy/GDAL algorithms. Designed to run headless and be
  fully testable without a QGIS instance.
- **`algorithms/`**: Thin `QgsProcessingAlgorithm` wrappers connecting QGIS
  user inputs to the core engine.
- **`export/`**: COG, GeoPackage, PDF, and web viewer generators.
- **`recipes/`**: JSON-based visualization recipe I/O.
- **`point_cloud/`**: CSF and PDAL ground filtering pipelines.
- **`temporal/`**: Multi-temporal DEM difference.
- **`fusion/`**: LiDAR + multispectral fusion.
- **`ml/`**: ONNX inference engine.
- **`gpu/`**: CuPy acceleration backend.

All raster I/O uses optimized GDAL chunking (`process_in_tiles`) to process
massive DEMs without exhausting system memory.

## License

This project is licensed under the MIT License.
