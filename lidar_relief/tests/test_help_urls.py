"""test_help_urls.py — Guards the in-QGIS route to the user guide.

exports: (test functions)
used_by: pytest runner
rules:
  Every algorithm must offer a Help link, and every anchor must point at a
  heading that really exists in lidar_relief/USER_GUIDE.md. A dead anchor
  silently drops the reader at the top of the document, which is exactly
  the sort of rot nobody notices — so it fails here instead.
  These tests parse SOURCE rather than importing the algorithms, because
  the algorithm modules import qgis, which is unavailable outside a QGIS
  runtime. The QGIS smoke test covers the live behaviour.
"""

import glob
import os
import re

import pytest

ALGORITHMS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "algorithms"
)
GUIDE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "USER_GUIDE.md"
)

# Modules in algorithms/ that are not themselves algorithms.
NON_ALGORITHM_MODULES = {"__init__.py", "help_mixin.py", "provenance_mixin.py"}


def _algorithm_sources():
    for path in sorted(glob.glob(os.path.join(ALGORITHMS_DIR, "*.py"))):
        if os.path.basename(path) in NON_ALGORITHM_MODULES:
            continue
        yield path, open(path, encoding="utf-8").read()


def _github_anchor(heading: str) -> str:
    """Slugify a Markdown heading the way GitHub does.

    Lowercase, strip anything that is not alphanumeric/space/hyphen, then
    replace runs of spaces with single hyphens.
    """
    text = heading.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s+", "-", text).strip("-")


@pytest.fixture(scope="module")
def guide_anchors():
    """Every anchor GitHub will generate for the shipped user guide."""
    assert os.path.exists(GUIDE_PATH), (
        f"USER_GUIDE.md must ship inside the plugin directory so it is "
        f"included in the released zip; expected it at {GUIDE_PATH}"
    )
    anchors = set()
    for line in open(GUIDE_PATH, encoding="utf-8"):
        match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if match:
            anchors.add(_github_anchor(match.group(2)))
    return anchors


class TestGuideIsShipped:
    """The guide has to be inside the plugin package, not just the repo."""

    def test_guide_lives_inside_the_plugin_directory(self):
        assert os.path.exists(GUIDE_PATH)

    def test_guide_is_not_empty(self):
        assert os.path.getsize(GUIDE_PATH) > 5000

    def test_guide_has_anchors(self, guide_anchors):
        assert len(guide_anchors) > 10


class TestEveryAlgorithmHasHelp:
    """No algorithm should leave the user without a route to the docs."""

    def test_every_algorithm_class_mixes_in_help(self):
        missing = []
        for path, src in _algorithm_sources():
            for match in re.finditer(r"^class (\w+)\(([^)]*)\):", src, re.M):
                cls, bases = match.groups()
                if "QgsProcessingAlgorithm" in bases and "HelpUrlMixin" not in bases:
                    missing.append(f"{os.path.basename(path)}::{cls}")
        assert not missing, (
            "these algorithms have no Help link — add HelpUrlMixin: "
            + ", ".join(missing)
        )

    def test_every_algorithm_still_has_short_help(self):
        """shortHelpString is the text shown beside the parameters."""
        missing = [
            os.path.basename(path)
            for path, src in _algorithm_sources()
            if "def shortHelpString" not in src
        ]
        assert not missing, f"missing shortHelpString: {missing}"


class TestAnchorsResolve:
    """Deep links must land on a real section."""

    def test_declared_anchors_exist_in_the_guide(self, guide_anchors):
        broken = []
        for path, src in _algorithm_sources():
            for anchor in re.findall(r'HELP_ANCHOR\s*=\s*"([^"]*)"', src):
                if anchor and anchor not in guide_anchors:
                    broken.append(f"{os.path.basename(path)} -> #{anchor}")
        assert not broken, (
            "these HELP_ANCHOR values do not match any heading in "
            "USER_GUIDE.md, so the link would silently land at the top of "
            "the page:\n  " + "\n  ".join(sorted(broken))
        )

    def test_at_least_the_major_sections_are_deep_linked(self):
        """A link to the guide's top is a fallback, not the goal."""
        anchored = sum(
            1
            for _path, src in _algorithm_sources()
            if re.search(r'HELP_ANCHOR\s*=\s*"[^"]+"', src)
        )
        assert anchored >= 12, (
            f"only {anchored} algorithms deep-link into the guide; most "
            f"should point at their own section"
        )


class TestHelpUrlConstruction:
    """The mixin itself, which is importable without QGIS."""

    def test_url_without_anchor(self):
        from lidar_relief.algorithms.help_mixin import USER_GUIDE_URL, HelpUrlMixin

        class Plain(HelpUrlMixin):
            pass

        assert Plain().helpUrl() == USER_GUIDE_URL

    def test_url_with_anchor(self):
        from lidar_relief.algorithms.help_mixin import USER_GUIDE_URL, HelpUrlMixin

        class Anchored(HelpUrlMixin):
            HELP_ANCHOR = "choosing-a-search-radius"

        assert Anchored().helpUrl() == f"{USER_GUIDE_URL}#choosing-a-search-radius"

    def test_url_points_at_the_shipped_guide_path(self):
        from lidar_relief.algorithms.help_mixin import USER_GUIDE_URL

        assert USER_GUIDE_URL.endswith("lidar_relief/USER_GUIDE.md"), (
            "the help URL must match where USER_GUIDE.md actually lives, "
            "otherwise every Help button 404s"
        )

    def test_helpurl_never_raises_on_odd_anchor(self):
        """QGIS calls helpUrl while building the dialog; it must not throw."""
        from lidar_relief.algorithms.help_mixin import USER_GUIDE_URL, HelpUrlMixin

        class NoneAnchor(HelpUrlMixin):
            HELP_ANCHOR = None

        assert NoneAnchor().helpUrl() == USER_GUIDE_URL
