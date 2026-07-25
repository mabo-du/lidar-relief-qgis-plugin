"""test_verify_published.py — Tests for the post-release publication check.

exports: (test functions)
used_by: pytest runner
rules:
  Never hits the network. The parsing and decision logic is what can rot;
  the HTTP call is exercised for real by the release workflow itself.
  The check must degrade to "unknown" rather than "published" whenever it
  cannot answer — reporting a release as live when it is not is the exact
  failure this script exists to prevent.
"""

import os
import sys

import pytest

# scripts/ is not a package; add it to the path the same way CI invokes it.
_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_SCRIPTS = os.path.join(_REPO_ROOT, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

verify_published = pytest.importorskip("verify_published")


def _repository_xml(entries):
    """Build a plugins.xml resembling the real repository response."""
    items = "\n".join(
        f'  <pyqgis_plugin name="{name}" version="{version}">\n'
        f"    <file_name>{file_name}</file_name>\n"
        f"    <qgis_minimum_version>3.0</qgis_minimum_version>\n"
        f"  </pyqgis_plugin>"
        for name, version, file_name in entries
    )
    return f'<?xml version="1.0"?>\n<plugins>\n{items}\n</plugins>\n'


class TestPublishedVersions:
    """Extracting the served versions of one plugin."""

    def test_finds_the_plugin_by_slug(self):
        xml = _repository_xml(
            [
                ("LiDAR Relief Visualization", "2.0.22", "lidar_relief.2.0.22.zip"),
                ("Something Else", "9.9.9", "something_else.9.9.9.zip"),
            ]
        )
        assert verify_published.published_versions(xml, "lidar_relief") == ["2.0.22"]

    def test_ignores_a_plugin_with_a_similar_prefix(self):
        """`lidar_relief_extras` must not be mistaken for `lidar_relief`."""
        xml = _repository_xml([("Extras", "1.0.0", "lidar_relief_extras.1.0.0.zip")])
        assert verify_published.published_versions(xml, "lidar_relief") == []

    def test_collects_multiple_versions(self):
        xml = _repository_xml(
            [
                ("LiDAR Relief", "2.0.22", "lidar_relief.2.0.22.zip"),
                ("LiDAR Relief", "2.1.0", "lidar_relief.2.1.0.zip"),
            ]
        )
        found = verify_published.published_versions(xml, "lidar_relief")
        assert sorted(found) == ["2.0.22", "2.1.0"]

    def test_malformed_xml_returns_empty(self):
        assert verify_published.published_versions("<not xml", "lidar_relief") == []

    def test_empty_repository_returns_empty(self):
        assert verify_published.published_versions(_repository_xml([]), "x") == []


class TestCheck:
    """The published / not-published decision."""

    def _patch_fetch(self, monkeypatch, xml=None, exc=None):
        def fake(*_args, **_kwargs):
            if exc is not None:
                raise exc
            return xml

        monkeypatch.setattr(verify_published, "fetch_repository_xml", fake)

    def test_reports_published(self, monkeypatch):
        self._patch_fetch(
            monkeypatch,
            _repository_xml([("LiDAR Relief", "2.1.1", "lidar_relief.2.1.1.zip")]),
        )
        published, message = verify_published.check("2.1.1")
        assert published is True
        assert "live" in message

    def test_reports_not_published_and_names_the_current_version(self, monkeypatch):
        self._patch_fetch(
            monkeypatch,
            _repository_xml([("LiDAR Relief", "2.0.22", "lidar_relief.2.0.22.zip")]),
        )
        published, message = verify_published.check("2.1.1")
        assert published is False
        assert "2.1.1 is NOT being served" in message
        assert "still offering v2.0.22" in message
        assert "moderates" in message, "must explain the likely cause"

    def test_network_failure_is_not_reported_as_published(self, monkeypatch):
        """An unreachable repository must never read as success."""
        self._patch_fetch(monkeypatch, exc=OSError("connection refused"))
        published, message = verify_published.check("2.1.1")
        assert published is False
        assert "says nothing about the release" in message

    def test_absent_plugin_is_distinguished_from_absent_version(self, monkeypatch):
        self._patch_fetch(monkeypatch, _repository_xml([]))
        published, message = verify_published.check("2.1.1")
        assert published is False
        assert "No versions" in message


class TestExitCodes:
    """CLI behaviour, which the workflow depends on."""

    def test_default_is_advisory(self, monkeypatch, capsys):
        monkeypatch.setattr(
            verify_published,
            "fetch_repository_xml",
            lambda *a, **k: _repository_xml(
                [("LiDAR Relief", "2.0.22", "lidar_relief.2.0.22.zip")]
            ),
        )
        monkeypatch.setattr(sys, "argv", ["verify_published.py", "2.1.1"])
        assert verify_published.main() == 0, (
            "a pending release must not fail the job — moderation latency "
            "would otherwise turn every release red"
        )
        assert "::warning" in capsys.readouterr().out

    def test_strict_flag_fails_when_absent(self, monkeypatch):
        monkeypatch.setattr(
            verify_published,
            "fetch_repository_xml",
            lambda *a, **k: _repository_xml(
                [("LiDAR Relief", "2.0.22", "lidar_relief.2.0.22.zip")]
            ),
        )
        monkeypatch.setattr(sys, "argv", ["verify_published.py", "2.1.1", "--strict"])
        assert verify_published.main() == 1

    def test_leading_v_is_tolerated(self, monkeypatch, capsys):
        monkeypatch.setattr(
            verify_published,
            "fetch_repository_xml",
            lambda *a, **k: _repository_xml(
                [("LiDAR Relief", "2.1.1", "lidar_relief.2.1.1.zip")]
            ),
        )
        monkeypatch.setattr(sys, "argv", ["verify_published.py", "v2.1.1"])
        assert verify_published.main() == 0
        assert "::notice" in capsys.readouterr().out
