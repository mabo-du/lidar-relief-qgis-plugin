import numpy as np

from lidar_relief.dem_preflight import (
    DemSummary,
    analyse_dataset,
    format_preflight,
    recommend_workflow,
)


class FakeBand:
    def __init__(self, array, nodata=-9999.0):
        self.array = np.asarray(array, dtype=np.float32)
        self.nodata = nodata

    def GetNoDataValue(self):
        return self.nodata

    def ReadAsArray(self, **_kwargs):
        return self.array.copy()

    def DataType(self):
        return 6


class FakeDataset:
    RasterXSize = 4
    RasterYSize = 3

    def __init__(self, array, projection=""):
        self.band = FakeBand(array)
        self.projection = projection

    def GetRasterBand(self, index):
        assert index == 1
        return self.band

    def GetGeoTransform(self):
        return (100.0, 0.5, 0.0, 200.0, 0.0, -0.5)

    def GetProjection(self):
        return self.projection


def test_analyse_dataset_reports_geometry_statistics_and_nodata():
    dataset = FakeDataset([[10, 11, -9999, 12], [10, 13, -9999, 12], [11, 14, 15, 12]])
    summary = analyse_dataset(dataset, "/tmp/example.tif")

    assert summary.width == 4
    assert summary.height == 3
    assert summary.pixel_width == 0.5
    assert summary.pixel_height == 0.5
    assert summary.extent == (100.0, 198.5, 102.0, 200.0)
    assert summary.valid_min == 10
    assert summary.valid_max == 15
    assert summary.nodata_percent == 16.666666666666664
    assert summary.warnings


def test_recommendations_scale_radii_to_dem_resolution():
    summary = DemSummary(
        source="/tmp/fine.tif",
        width=1000,
        height=1000,
        pixel_width=0.25,
        pixel_height=0.25,
        extent=(0, 0, 250, 250),
        crs_name="EPSG:2154",
        projected=True,
        linear_units="metre",
        valid_min=100,
        valid_max=112,
        valid_mean=105,
        valid_stddev=2,
        nodata_percent=0,
        estimated_memory_mb=4,
        warnings=(),
    )
    recommendation = recommend_workflow(summary)

    assert recommendation.preset_key == "flat_agricultural"
    assert recommendation.start_with == "Visualisation Contact Sheet"
    assert recommendation.search_radii[0].pixels == 8
    assert recommendation.search_radii[0].metres == 2
    assert "archaeological identification" in recommendation.caution.lower()


def test_rugged_relief_selects_upland_preset():
    summary = DemSummary(
        source="upland.tif",
        width=100,
        height=100,
        pixel_width=1,
        pixel_height=1,
        extent=(0, 0, 100, 100),
        crs_name="EPSG:27700",
        projected=True,
        linear_units="metre",
        valid_min=100,
        valid_max=260,
        valid_mean=170,
        valid_stddev=35,
        nodata_percent=0,
        estimated_memory_mb=0.04,
        warnings=(),
    )
    assert recommend_workflow(summary).preset_key == "upland_steep"


def test_preflight_text_contains_practical_next_steps():
    summary = analyse_dataset(FakeDataset([[1, 2], [3, 4]]), "dem.tif")
    text = format_preflight(summary, recommend_workflow(summary))
    assert "DEM PREFLIGHT" in text
    assert "Resolution:" in text
    assert "Estimated working size" in text
    assert "Full-resolution workload:" in text
    assert "Recommended starting workflow" in text
    assert "Reproject" in text
