"""Tests for parameter-level contextual help without requiring QGIS."""

from lidar_relief.algorithms.help_mixin import HelpUrlMixin
from lidar_relief.algorithms.parameter_help import resolve_parameter_help


class FakeParameter:
    def __init__(self, name, description, help_text=""):
        self._name = name
        self._description = description
        self._help = help_text

    def name(self):
        return self._name

    def description(self):
        return self._description

    def help(self):
        return self._help

    def setHelp(self, text):
        self._help = text


class FakeAlgorithmBase:
    def __init__(self):
        self.added = []

    def name(self):
        return "sky_view_factor"

    def addParameter(self, parameter, createOutput=True):
        self.added.append((parameter, createOutput))
        return "delegated"


class FakeAlgorithm(HelpUrlMixin, FakeAlgorithmBase):
    pass


def test_common_radius_help_explains_scale_tradeoff():
    text = resolve_parameter_help("sky_view_factor", "SEARCH_RADIUS", "Search radius")
    assert "metre" in text.lower()
    assert "small" in text.lower()
    assert "large" in text.lower()


def test_unknown_parameter_gets_useful_fallback():
    text = resolve_parameter_help("future_algorithm", "NEW_OPTION", "New option")
    assert text.startswith("New option.")
    assert "default" in text.lower()


def test_add_parameter_applies_help_and_preserves_qgis_contract():
    algorithm = FakeAlgorithm()
    parameter = FakeParameter("SEARCH_RADIUS", "Search radius")

    result = algorithm.addParameter(parameter, createOutput=False)

    assert result == "delegated"
    assert parameter.help()
    assert algorithm.added == [(parameter, False)]


def test_add_parameter_does_not_replace_explicit_algorithm_help():
    algorithm = FakeAlgorithm()
    parameter = FakeParameter(
        "SPECIAL", "Special setting", "Algorithm-specific explanation."
    )

    algorithm.addParameter(parameter)

    assert parameter.help() == "Algorithm-specific explanation."


def test_add_parameter_tolerates_non_qgis_parameter_objects():
    algorithm = FakeAlgorithm()
    marker = object()

    assert algorithm.addParameter(marker) == "delegated"
    assert algorithm.added == [(marker, True)]
