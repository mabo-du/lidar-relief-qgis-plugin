# LiDAR Relief Plugin User Guide — v2.1

## Introduction
The LiDAR Relief QGIS Plugin provides archaeologically optimized terrain
visualization tools. It allows you to process Digital Elevation Models (DEMs)
into highly readable formats to identify subtle micro-topography such as
ancient ditches, walls, mounds, and paths.

**v2.0 expanded the plugin from a pure visualization tool into a complete
prospection platform**, adding point cloud processing, multi-temporal change
detection, multi-sensor fusion, AI feature detection, and professional
export/publishing capabilities.

**v2.1 makes the toolbox easier to navigate and its results easier to trust.**
A Visualisation Contact Sheet renders several techniques side by side so you
can pick one before committing to a full run; search radii can be given in
metres rather than pixels, so a setting means the same thing on a 0.25 m and a
2 m DEM; AI segmentation models now produce class rasters and polygons; and
every terrain output is written with a provenance sidecar recording exactly
how it was made.

## Quick start

1. Install the plugin from **Plugins → Manage and Install Plugins…** by
   searching for **LiDAR Relief Visualization**.
2. Load a projected DEM. Metric horizontal and vertical units are strongly
   recommended so radii, slopes, and relief values remain interpretable. From
   v2.1 the plugin warns in the Processing log if your DEM uses a geographic
   (latitude/longitude) CRS or has non-square pixels, both of which make
   distance-based results meaningless.
3. Open **Processing Toolbox → LiDAR Relief**.
4. Hover over or use QGIS's contextual-help control for any setting to see a
   plain-language explanation and practical starting guidance.
5. Not sure which visualization suits your landscape? Run **Visualisation
   Contact Sheet** first. It renders several techniques over the same ground
   as one labelled image in a few seconds.
6. For an initial survey, run **Batch Relief Visualisation** with the landscape
   preset closest to your study area.
7. Inspect several complementary outputs. No single visualization or automated
   detection should be treated as an archaeological classification.
8. Record the input dataset, CRS, resolution, parameters, plugin version, and
   outputs. Provenance sidecars now capture most of this automatically;
   Visualization Recipes and PDF reports also assist reproducibility.

### Contextual parameter help

Every LiDAR Relief processing setting includes contextual help covering what it
changes, expected units, and practical considerations such as scale,
performance, or safe starting values. Depending on your QGIS version, this help
may appear beside the setting as a `?`, in a tooltip, or in the processing
dialog's help panel.

An optional short introduction explains where to find this help the first time
the plugin starts. Select **Show this introduction again when QGIS starts** if
you want it repeated. You can reopen it at any time from **Plugins → LiDAR
Relief → Contextual Help…**. The processing dialog's **Help** button still
opens the complete algorithm guide.

### LiDAR Relief menu

The **Plugins → LiDAR Relief** menu collects the best starting workflows:

- **Open LiDAR Relief Toolbox** opens QGIS's Processing toolbox.
- **Create Visualisation Contact Sheet…** and **Run Batch Relief
  Visualisation…** open native Processing dialogs and prefill the active DEM
  when possible.
- **Inspect Active DEM…** reports CRS, resolution, dimensions, coverage,
  sampled elevation and nodata statistics, approximate memory, and practical
  starting scales. If no local raster is active, it asks you to choose one.
- **Dependency Diagnostics…** reports which optional GPU, point-cloud, AI,
  export, temporal, and fusion capabilities are available. Use **Copy** to
  include the report in a support request.
- **Recent Recipe…** reopens successfully imported or exported recipes.
- **Recent Output Folder…** opens output locations returned by menu-launched
  workflows. **Remember Output Folder…** adds any other working folder.
- **Favorite Tool or Recipe…** opens a saved favorite. **Manage Favorites…**
  selects tools and recent recipes to pin, while **Manage Recent Items…**
  removes history entries without deleting the files themselves.
- **Compare Raster Layers…** opens two loaded rasters in synchronized,
  non-destructive map views.
- **Record Interpretation Note…** records the map-centre location with a title,
  interpretation, confidence, and visualization as WGS84 GeoJSON or CSV.
- **Study Area Bookmarks…** saves and restores named extents together with
  their CRS. **Create Support Bundle…** writes redacted diagnostics and, when
  a DEM is active, its preflight report to a ZIP suitable for a bug report.
- **Open User Guide** opens this complete guide.

Preflight recommendations are conservative visualisation starting points. A
bare-earth DEM cannot determine land cover or prove that a feature is
archaeological; compare complementary outputs and independent evidence.

![TRI applied to a labelled synthetic archaeological landscape](docs/images/tri-synthetic-example.png)

*The synthetic example demonstrates algorithm response under controlled
conditions. Real anomalies require contextual interpretation and, where
appropriate, field validation.*

---

## Algorithm Reference

### Terrain Visualization and Analysis

| Algorithm | Description | Best For |
|-----------|-------------|----------|
| **Multi-directional Hillshade** | Blends illumination from 4+ sun azimuths | General prospection, ridge-and-furrow |
| **Simple Local Relief Model (SLRM)** | Removes macro-topography using trend radius | Barrows, mounds, platforms |
| **Sky-View Factor (SVF)** | Diffuse illumination simulation | General prospection, ditches |
| **Anisotropic SVF (ASVF)** | Directionally weighted SVF | Linear features perpendicular to light |
| **Topographic Openness** | Positive = ridges, Negative = valleys | Stone walls (positive), ditches (negative) |
| **RVT Multi-directional Hillshade** | rvt-py reference implementation | Cross-validating against other RVT installs |
| **RVT Topographic Openness** | rvt-py reference implementation | Cross-validating against other RVT installs |
| **Local Dominance** | Mean depression angle, in degrees | Subtle barrows, hollow ways |
| **Multi-Scale TP (MSTP)** | DEV at Broad/Meso/Local → RGB | Complex multi-period landscapes |
| **Enhanced 4-MSTP (e4MSTP)** | 4-step composite (LD+Openness+Slope+SVF+MSTP) | Flat terrain, alluvial plains |
| **VAT Composite** | Hillshade + Slope + Openness blend | European heritage base maps |
| **Simple Red Relief** | Patent-free RRIM analogue | Tropical/Mesoamerican surveys |
| **PCA Composite** | PCA of 16+ directional hillshades | Ridge-and-furrow, Roman roads |
| **Slope** | Degrees and percent | Terrain analysis |
| **Terrain Ruggedness Index (TRI)** | Riley 3×3 local elevation contrast | Scarps, banks, stone spreads, quarrying, rough ground |
| **Blend Visualizations** | Multiply, Screen, Overlay modes | Custom composites |
| **Batch Relief Visualisation** | Multi-algorithm single-pass | Survey workflow efficiency |
| **Visualisation Contact Sheet** | Several techniques as one labelled image | Choosing a visualization before a full run |
| **ML-Ready VRT Export** | Normalized multi-band composites | CNN/LiDAR training datasets |

#### Choosing a search radius

Sky-View Factor, Topographic Openness, ASVF, SLRM and RVT Openness accept
their radius in either **pixels** or **metres**. Pixels remain the default so
existing Processing models keep working, but metres are usually what you
actually mean: archaeological features have a real-world size, whereas a
20-pixel radius is 20 m on a 1 m DEM and only 5 m on 0.25 m LiDAR.

Whichever you choose, the Processing log reports the radius both ways, for
example `SVF search radius: 80 px = 20.0 m (cell size 0.25 m)`. If that
real-world figure looks too small for the earthwork you are hunting, the
setting is wrong regardless of how reasonable the pixel count looked.

#### Visualisation Contact Sheet

Renders several visualizations of the same DEM as a single labelled
multi-panel PNG, so you can see which technique reveals your features before
committing to a full-resolution run.

The DEM is downsampled before anything is computed, so a sheet returns in
seconds even for a large tile. Choose the visualizations to include, the
preview size, and how many panels per row.

Two things to keep in mind:

- Panels are **previews for choosing a technique**, not analytical output.
  Interpret on full-resolution results.
- Each panel is contrast-stretched independently, so **brightness is not
  comparable between panels** — only structure is.

Panel captions require `Pillow`. Without it the sheet still renders, with
panels in the order listed in the algorithm dialog.

#### Terrain Ruggedness Index (TRI)

TRI measures how strongly each DEM cell differs from its eight immediate
neighbours. Values are expressed in the DEM's elevation units: zero indicates
locally flat terrain, while larger values indicate stronger local relief.

Use TRI to screen for abrupt microtopographic changes such as banks, scarps,
stone spreads, quarry edges, erosion, and disturbed ground. Compare results
only between DEMs with similar resolution and vertical units, because changing
the cell size changes the neighbourhood represented by the 3×3 window. TRI is
a prospection aid, not an archaeological classification; verify anomalies
against other visualizations and field evidence.

---

### Export and publishing

#### Export to Cloud-Optimized GeoTIFF (COG)

Converts any algorithm output to a cloud-optimized GeoTIFF with internal
tiling and overviews. Optionally generates an interactive MapLibre GL JS
web viewer that can be uploaded to GitHub Pages, Netlify, S3, or any static
host.

**Workflow:**
1. Run any relief algorithm (e.g., SVF)
2. Run **Export to Cloud-Optimized GeoTIFF (COG)** on the output
3. Select a compression profile (DEFLATE, LZW, ZSTD, or raw)
4. Check "Generate interactive web viewer"
5. Upload both the `.tif` and the viewer folder to a web host

**Requirements:** `rio-cogeo` Python package (`pip install rio-cogeo`)

#### Package for Field Survey (QField/Mergin)

Packages relief rasters and anomaly detection points into a GeoPackage with
structured archaeological schema, plus a QGIS project file that opens directly
in QField on mobile devices.

**GeoPackage schema fields:**
- `anomaly_id` — Unique identifier
- `detection_method` — How the anomaly was detected (svf, hillshade, manual, etc.)
- `confidence` — Detection confidence 0.0–1.0
- `feature_type` — Interpreted type (barrow, ditch, platform, etc.)
- `field_status` — Validation status (pending, confirmed, rejected, uncertain)
- `observer`, `photo_path`, `notes`, `timestamp`

**Workflow:**
1. Create anomaly points (either manually or from AI detection)
2. Run **Package for Field Survey (QField/Mergin)**
3. Copy the output directory to your mobile device
4. Open the `.qgs` file in QField
5. Navigate to each anomaly and update the field_status

#### Generate PDF Report

Creates a CIfA-compliant PDF report documenting:
- Title page with site/project metadata
- Full algorithm parameter documentation
- Input DEM metadata (CRS, resolution, extent)
- Band statistics with percentile values (P5, P25, P50, P75, P95)
- Histogram chart
- Certification section

**Requirements:** `reportlab` Python package (`pip install reportlab`)

#### Visualization Recipes

Export any set of algorithm parameters as a JSON recipe file that can be
shared via GitHub Gist, attached to publications, or imported by other
users. Recipes include versioned schema, type validation, and metadata
(name, author, description, tags, landscape type).

**Example use case:**
1. Optimize SVF parameters for barrow detection on chalk downland
2. Export as `barrow_chalk.json`
3. Share with colleagues or publish alongside your paper
4. Anyone can import your recipe and reproduce your exact visualization

#### Provenance sidecars

Every terrain output is written with a companion JSON file named after it —
`svf_output.tif.lidar-relief.json`. You do not need to enable anything.

Each record captures:
- Plugin version and algorithm
- The parameters **actually used**, including the resolved pixel radius as
  well as the metres you typed
- Source raster path, a checksum, CRS, grid size and cell size
- A UTC timestamp

Where a recipe describes *what you intended*, a sidecar records *what
happened* — to a specific file, on a specific day, from a specific input.

**Inspect Provenance Record** reads one back and prints it. Point it at either
the sidecar or the raster it describes. Optionally supply the source DEM and
it will verify the DEM has not changed since, comparing file size, checksum,
dimensions and CRS, and telling you plainly whether re-running the recorded
parameters would still reproduce the result.

Useful for archive deposit, CIfA-compliant reporting, and picking up your own
analysis — or a colleague's — months later.

Writing a sidecar can never fail the run that produced the raster; if the
location is unwritable, you get a log note and your output.

---

### GPU acceleration

Sky-View Factor and Topographic Openness have a **Use GPU acceleration**
checkbox. With CuPy installed against a working CUDA driver, the horizon scan
runs on the GPU; GPU and CPU walk the same horizon rays, so results agree to
floating-point precision rather than merely being similar.

Ticking the box can never fail a run. Without CuPy, with a broken driver, or
with SVF noise removal enabled (that filter is CPU-only), the algorithm falls
back to NumPy and logs the reason.

**Requirements:** `cupy-cuda12x` matching your CUDA version
(`pip install cupy-cuda12x`)

---

### Point-cloud processing

#### CSF Ground Filter (LAS/LAZ → DEM)

Generate a DEM directly from raw LiDAR point clouds using the Cloth
Simulation Filter (CSF), with presets specifically tuned for archaeology.

**Presets:**

| Preset | Description | Use Case |
|--------|-------------|----------|
| Archaeology Fine | Maximum micro-relief preservation | Subtle earthworks on flat terrain |
| Archaeology Standard | Balanced vegetation removal | Most surveys |
| Forested | Aggressive ground detection | Dense canopy |
| Urban | Standard filtering | Built-up areas |

**Requirements:** `cloth-simulation-filter` Python package
(`pip install cloth-simulation-filter`) + `laspy` for LAS/LAZ reading
(`pip install laspy`)

---

### Multi-temporal change detection

Compute a probabilistic DEM of Difference (DoD) between two temporally
separated DEMs to detect landscape change.

**How it works:**
1. Load two DEMs: older (baseline) and newer (repeat survey)
2. Co-register to identical grid (reproject if needed)
3. Compute: `DoD = DEM_new - DEM_old`
4. Propagate vertical error: `σ = sqrt(RMSE_old² + RMSE_new²)`
5. Apply Level of Detection: changes below `1.96 × σ` are masked as noise

**Outputs:**
- Signed DoD raster (metres) — positive = deposition/fill,
  negative = erosion/cut
- Significance mask (0=no change, 1=erosion, 2=deposition)
- Volume report with cut/fill totals

**Requirements:** `xarray` and `rioxarray`
(`pip install xarray rioxarray`)

---

### Multi-sensor fusion

Co-register Sentinel-2 multispectral bands with LiDAR relief and apply
blend recipes.

**Recipes:**

| Recipe | LiDAR Layer | Satellite Bands | Effect |
|--------|-------------|-----------------|--------|
| Terrain + CIR | SVF (luminance) | B8, B4, B3 (CIR) | Topography + vegetation |
| Crop Mark Enhancement | Local Dominance | B4, B3, B2 (true colour) | Buried features |
| Erosion Risk | Slope | B11, B8, B4 (SWIR+NIR) | Soil moisture + slope |
| Bare Earth Composite | SLRM | B11, B12, B4 | Vegetation-free prospection |

**Requirements:** `rasterio` and `rioxarray`
(`pip install rasterio rioxarray`)

---

### AI feature detection

Run object detection or semantic segmentation on plugin visualizations
using your own pre-trained ONNX model. The plugin is an inference engine
only — you supply the trained model.

**Supported model types.** The type is detected automatically from the
model's output signature; you do not select it.

| Type | Recognised by | Output |
|------|---------------|--------|
| **Object detection** (YOLOv5/v7/v8/v11, SSD) | A 3-D `(N, boxes, attrs)` output, or several output tensors | Bounding-box polygons with class and confidence |
| **Semantic segmentation** (U-Net, SegFormer, DeepLab) | A single 4-D `(N, C, H, W)` output | A class-index raster **and** per-class polygons carrying area, pixel count and mean confidence |

Instance segmentation (Mask R-CNN and similar) is **not** supported. Earlier
versions of this guide listed it; that was never implemented.

**Which should you use?** For archaeology, segmentation is usually the better
fit. Ditches, banks, field systems and hollow ways are linear or areal, and a
bounding box around a 400 m field boundary conveys very little. Detection
suits compact, countable features such as barrows or shell mounds.

**Workflow:**
1. Train a model externally (PyTorch, Ultralytics, etc.)
2. Export to ONNX format
3. Create a `labels.json` file with class names. Either a list, or an
   object keyed by class index — for segmentation, index 0 is treated as
   background and is excluded from the polygon output.
4. In QGIS, run **AI Feature Detection (ONNX Model)**
5. Results are written as a GeoPackage vector layer. Segmentation models can
   additionally write the class-index raster, which is the primary evidence —
   the polygons are derived from it and are lossy at feature boundaries.

**Segmentation settings worth knowing:**
- *Confidence threshold* — pixels whose winning class scores below this become
  background, rather than asserting a class the model was unsure about.
- *Minimum segment size* — drops polygons below this pixel count. Single-pixel
  speckle is model noise, not archaeology. If you get a populated class raster
  but no polygons, this is set too high.

The raster is normalised against whole-raster percentiles before inference, so
tiles are consistent with one another and the resulting map has no seams from
tiles being scaled in isolation.

**Requirements:** `onnxruntime` (`pip install onnxruntime`)

---

## Batch Processing

The **Batch Relief Visualisation** tool runs multiple algorithms in a single
pass. Choose from 4 research-validated terrain presets or use manual settings:

- **Flat / Agricultural**: Optimized for ploughed-out features in low-relief
  terrain. SVF radius 20 m, openness 15 m, SLRM radius 20 m,
  LD observer height 1.7 m.
- **Forested**: Dense canopy where ground points are sparse. SVF radius 10 m,
  openness 5 m, SLRM radius 12 m, LD observer height 1.5 m.
- **Upland / Steep**: Prevents steep slopes from overpowering micro-relief.
  SVF radius 5 m, openness 5 m, SLRM radius 8 m.
- **Coastal**: Broad search radii for dune/estuarine modifications.
  SVF radius 15 m, openness 10 m, SLRM radius 25 m,
  LD observer height 2.0 m.

Preset distances are defined in **metres** and converted using your DEM's cell
size, so a preset means the same real-world thing at any resolution. The log
reports the converted pixel values at the start of each run.

Set **Optional named-output folder** to create a complete, consistently named
result set. The template accepts `{dem}`, `{method}`, `{preset}`, and `{date}`;
for example, `{dem}_{method}_{date}`. Folder separators and unknown fields are
rejected. Set **Optional saved recipe for this run** to preserve the resolved
settings after a successful run, including pixel values calculated from a
metre-based preset.

The e4MSTP dialog also exposes its component scales under QGIS's advanced
parameters. Leaving them unchanged reproduces the canonical implementation:
openness radius 10, Local Dominance radii 10–20, MSTP radii 3–20–100, and tile
size 1024 pixels.

> Before v2.1 these distances were stored as pixel counts, which made the
> presets correct only on a 1 m DEM — on 0.25 m LiDAR every preset radius was
> silently a quarter of its intended size. If you have batch output from an
> earlier version on a non-1 m DEM, it was computed at a different scale than
> the figures above imply.

---

## Best Practices

1. **CRS**: Ensure your DEM is projected in a metric CRS (UTM or local grid),
   not geographic (degrees in latitude/longitude). The plugin warns you in the
   Processing log if it is not, and also if your pixels are not square — but
   the warning is advisory, so read the log rather than assuming silence.
2. **Pick a technique first**: Run the Contact Sheet before a full-resolution
   run. It costs seconds and often saves a wasted half-hour.
3. **Start with Batch**: Use the Batch tool with a matching terrain preset.
4. **Think in metres**: Set search radii in metres and sanity-check the
   real-world figure the log reports against the size of the feature you are
   looking for.
5. **Iterate**: If features are too faint, increase search radii. If too noisy,
   decrease them.
6. **SVF Noise**: Enable noise reduction for DEMs with point-cloud noise
   or complex topography. Note this filter is CPU-only, so it overrides the
   GPU checkbox.
7. **e4MSTP**: Prepare for longer processing — it computes 7 underlying
   algorithms.
8. **Export**: Use COG export for sharing with non-GIS stakeholders.
9. **Field validation**: Use the Field Survey Export for ground-truthing.
10. **Reproducibility**: Keep the provenance sidecar with any output you
    publish or deposit, and export a Visualization Recipe alongside it.
11. **AI models**: The plugin is an inference engine only — train models
    externally in PyTorch/Ultralytics and export to ONNX. Prefer segmentation
    over detection for linear and areal features.

---

## Optional Dependencies

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
| Contact sheet panel captions | `Pillow` | `pip install Pillow` |

## Getting help and reporting problems

When reporting an issue, include your operating system, QGIS version, plugin
version, the full Processing log, input CRS and raster resolution, and the
smallest dataset or steps that reproduce the problem. Do not attach sensitive
site coordinates or restricted heritage data to a public issue.

- [Issue tracker](https://github.com/dig-tools/lidar-relief-qgis-plugin/issues)
- [Source and releases](https://github.com/dig-tools/lidar-relief-qgis-plugin)
- [Official QGIS listing](https://plugins.qgis.org/plugins/lidar_relief/)

All features degrade gracefully with clear error messages if a dependency
is missing.
