"""test_scale.py — Tests for resolution-aware radius handling.

exports: (test functions)
used_by: pytest runner
rules:
  Guards the two halves of the resolution trap: core/scale.py converting
  a real-world distance into pixels, and core/presets.py returning radii
  that track the DEM's cell size.
  The backwards-compatibility test matters most — get_preset(name) with
  no cellsize must still return the exact pixel numbers it returned
  before presets moved to metres, or saved workflows change silently.
"""

import pytest

from lidar_relief.core.presets import PRESETS, get_preset
from lidar_relief.core.scale import (
    METRES,
    PIXELS,
    RADIUS_UNIT_OPTIONS,
    RADIUS_UNIT_VALUES,
    describe_radius,
    radius_to_pixels,
    resolve_radius,
)


class _RecordingFeedback:
    def __init__(self):
        self.info = []
        self.warnings = []

    def pushInfo(self, message):
        self.info.append(message)

    def pushWarning(self, message):
        self.warnings.append(message)


class TestRadiusToPixels:
    """Converting a user-supplied radius into whole pixels."""

    def test_pixels_pass_through(self):
        assert radius_to_pixels(20, PIXELS, 0.25) == 20
        assert radius_to_pixels(20, PIXELS, 4.0) == 20

    @pytest.mark.parametrize(
        "metres,cellsize,expected",
        [
            (20.0, 1.0, 20),  # 1 m DEM: metres and pixels coincide
            (20.0, 0.25, 80),  # sub-metre LiDAR needs 4x the pixels
            (20.0, 2.0, 10),  # coarse DEM needs fewer
            (20.0, 0.5, 40),
        ],
    )
    def test_metres_scale_with_cellsize(self, metres, cellsize, expected):
        """The whole point: 20 m stays 20 m at any resolution."""
        assert radius_to_pixels(metres, METRES, cellsize) == expected

    def test_never_returns_zero(self):
        """A sub-pixel radius would make the horizon scan sample nothing."""
        assert radius_to_pixels(0.1, METRES, 10.0) == 1

    def test_respects_minimum(self):
        assert radius_to_pixels(1.0, METRES, 10.0, minimum=2) == 2

    def test_respects_maximum(self):
        assert radius_to_pixels(1000.0, METRES, 0.1, maximum=500) == 500

    def test_rejects_bad_units(self):
        with pytest.raises(ValueError, match="units must be"):
            radius_to_pixels(10, "furlongs", 1.0)

    def test_rejects_bad_cellsize(self):
        with pytest.raises(ValueError, match="cellsize must be positive"):
            radius_to_pixels(10, METRES, 0.0)

    def test_unit_options_and_values_align(self):
        """The enum labels and the internal values must stay in step."""
        assert len(RADIUS_UNIT_OPTIONS) == len(RADIUS_UNIT_VALUES)
        assert RADIUS_UNIT_VALUES[0] == PIXELS, (
            "pixels must stay at index 0 — it is the default that keeps "
            "saved Processing models behaving as before"
        )


class TestDescribeRadius:
    """The log line that makes the resolution trap visible."""

    def test_reports_both_units(self):
        text = describe_radius(20, 0.25)
        assert "20 px" in text
        assert "5.0 m" in text

    def test_resolve_radius_pushes_the_description(self):
        feedback = _RecordingFeedback()
        resolve_radius(20, PIXELS, 0.25, "SVF search radius", feedback)
        assert any("SVF search radius" in m and "5.0 m" in m for m in feedback.info)

    def test_resolve_radius_warns_on_expensive_radius(self):
        """Horizon cost grows with the square of the radius."""
        feedback = _RecordingFeedback()
        resolve_radius(100.0, METRES, 0.1, "SVF search radius", feedback)
        assert any("will be slow" in m for m in feedback.warnings)

    def test_resolve_radius_works_without_feedback(self):
        assert resolve_radius(20, PIXELS, 1.0, "x", None) == 20


class TestPresetScaling:
    """Presets must describe real-world distances, not pixel counts."""

    def test_default_cellsize_is_backwards_compatible(self):
        """get_preset(name) must return the historical pixel numbers.

        These are the values the presets shipped with through v2.0.22.
        If this test fails, existing users' batch output changes.
        """
        historical = {
            "flat_agricultural": (20, 15, 20, 10, 20),
            "forested": (10, 5, 12, 5, 15),
            "upland_steep": (5, 5, 8, 5, 10),
            "coastal": (15, 10, 25, 15, 30),
        }
        for name, (svf, opns, slrm, ld_min, ld_max) in historical.items():
            preset = get_preset(name)
            assert preset["svf"]["search_radius"] == svf, name
            assert preset["openness"]["search_radius"] == opns, name
            assert preset["slrm"]["trend_radius"] == slrm, name
            assert preset["local_dominance"]["min_rad"] == ld_min, name
            assert preset["local_dominance"]["max_rad"] == ld_max, name

    def test_radii_scale_on_sub_metre_dem(self):
        """0.25 m LiDAR: the same real distance needs 4x the pixels."""
        coarse = get_preset("flat_agricultural", 1.0)
        fine = get_preset("flat_agricultural", 0.25)
        assert fine["svf"]["search_radius"] == coarse["svf"]["search_radius"] * 4
        assert fine["slrm"]["trend_radius"] == coarse["slrm"]["trend_radius"] * 4

    def test_radii_shrink_on_coarse_dem(self):
        coarse = get_preset("flat_agricultural", 2.0)
        assert coarse["svf"]["search_radius"] == 10

    def test_non_distance_fields_are_not_scaled(self):
        """Direction counts and observer height are not distances."""
        for cellsize in (0.25, 1.0, 4.0):
            preset = get_preset("coastal", cellsize)
            assert preset["svf"]["num_directions"] == 32
            assert preset["openness"]["num_directions"] == 32
            assert preset["svf"]["noise_level"] == 1
            assert preset["local_dominance"]["observer_height"] == 2.0

    def test_local_dominance_radii_stay_ordered(self):
        """min_rad < max_rad must hold even when both round together."""
        for cellsize in (0.1, 1.0, 5.0, 20.0, 100.0):
            ld = get_preset("upland_steep", cellsize)["local_dominance"]
            assert ld["min_rad"] < ld["max_rad"], f"degenerate at {cellsize} m"

    def test_metre_keys_are_removed_from_output(self):
        """Callers index search_radius, not search_radius_m."""
        preset = get_preset("forested", 0.5)
        assert "search_radius_m" not in preset["svf"]
        assert "trend_radius_m" not in preset["slrm"]

    def test_source_presets_are_not_mutated(self):
        """get_preset returns a deep copy — the canonical dict is metres."""
        get_preset("forested", 0.25)
        assert "search_radius_m" in PRESETS["forested"]["svf"]
        assert PRESETS["forested"]["svf"]["search_radius_m"] == 10.0

    def test_rejects_unknown_context(self):
        with pytest.raises(ValueError, match="Unknown preset context"):
            get_preset("volcanic", 1.0)

    def test_rejects_bad_cellsize(self):
        with pytest.raises(ValueError, match="cellsize must be positive"):
            get_preset("forested", -1.0)
