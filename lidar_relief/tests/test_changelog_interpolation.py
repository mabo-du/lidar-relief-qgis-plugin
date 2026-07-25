"""test_changelog_interpolation.py — Guards the '%' trap in CHANGELOG.md.

exports: (test functions)
used_by: pytest runner
rules:
  qgis-plugin-ci injects CHANGELOG.md into metadata.txt's `changelog=`
  field at release time. The QGIS plugin registry parses that file with
  configparser's BasicInterpolation, where '%' is a control character, so
  a bare '%' anywhere in the changelog makes the whole metadata.txt
  unparseable. The registry then refuses the upload with an HTTP 400
  whose body qgis-plugin-ci discards — a release that fails with no
  stated reason.
  This is invisible locally: the source CHANGELOG.md is valid Markdown
  and every other gate passes. Only the real upload surfaces it, which is
  why v2.1.1 burned three release attempts on the phrase "an 84% reduction".
  Hence a test rather than a convention.
"""

import configparser
import os
import sys

import pytest

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_SCRIPTS = os.path.join(_REPO_ROOT, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

check_changelog = pytest.importorskip("check_changelog")

from pathlib import Path  # noqa: E402

CHANGELOG = Path(_REPO_ROOT) / "CHANGELOG.md"


class TestRealChangelog:
    """The shipped changelog must survive metadata injection."""

    def test_changelog_exists(self):
        assert CHANGELOG.is_file()

    def test_no_interpolation_hazards(self):
        hazards = check_changelog.find_interpolation_hazards(CHANGELOG)
        assert not hazards, (
            "CHANGELOG.md contains a bare '%'. When qgis-plugin-ci injects it "
            "into metadata.txt the QGIS registry cannot parse the file and "
            "refuses the upload with an unexplained HTTP 400. Write 'percent' "
            f"instead. Offending lines: {hazards}"
        )

    def test_changelog_survives_configparser_interpolation(self):
        """End-to-end proof, using the same parser the registry uses."""
        parser = configparser.ConfigParser()
        parser.read_string(
            "[general]\nchangelog=\n"
            + "\n".join(
                f"    {line}"
                for line in CHANGELOG.read_text(encoding="utf-8").splitlines()
            )
        )
        # Reading the value is what triggers interpolation.
        assert parser.get("general", "changelog") is not None


class TestHazardDetection:
    """The detector itself."""

    def _write(self, tmp_path, text):
        path = tmp_path / "CHANGELOG.md"
        path.write_text(text, encoding="utf-8")
        return path

    def test_flags_a_bare_percent(self, tmp_path):
        path = self._write(tmp_path, "- Reduced size by 84% with no loss.\n")
        hazards = check_changelog.find_interpolation_hazards(path)
        assert len(hazards) == 1
        assert hazards[0][0] == 1

    def test_accepts_an_escaped_percent(self, tmp_path):
        path = self._write(tmp_path, "- Reduced size by 84%% with no loss.\n")
        assert check_changelog.find_interpolation_hazards(path) == []

    def test_accepts_an_interpolation_reference(self, tmp_path):
        """`%(name)s` is valid interpolation syntax, not a hazard."""
        path = self._write(tmp_path, "- Uses %(version)s here.\n")
        assert check_changelog.find_interpolation_hazards(path) == []

    def test_clean_changelog_passes(self, tmp_path):
        path = self._write(tmp_path, "## [1.0.0]\n\n- Added a thing.\n")
        assert check_changelog.find_interpolation_hazards(path) == []

    def test_reports_every_offending_line(self, tmp_path):
        path = self._write(tmp_path, "- 10% here\n- fine\n- 20% there\n")
        hazards = check_changelog.find_interpolation_hazards(path)
        assert [n for n, _ in hazards] == [1, 3]

    def test_one_report_per_line(self, tmp_path):
        """Several hazards on one line should not spam the output."""
        path = self._write(tmp_path, "- 10% and 20% and 30%\n")
        assert len(check_changelog.find_interpolation_hazards(path)) == 1

    def test_missing_file_is_not_an_error(self, tmp_path):
        assert check_changelog.find_interpolation_hazards(tmp_path / "nope.md") == []

    def test_percent_at_end_of_line_is_flagged(self, tmp_path):
        """A trailing '%' has nothing following it, so it is still invalid."""
        path = self._write(tmp_path, "- Coverage rose to 100%\n")
        assert len(check_changelog.find_interpolation_hazards(path)) == 1


class TestConfigParserBehaviourIsAsAssumed:
    """Pin the behaviour this whole guard is premised on."""

    def _parse(self, value):
        parser = configparser.ConfigParser()
        parser.read_string(f"[general]\nchangelog={value}\n")
        return parser.get("general", "changelog")

    def test_bare_percent_raises(self):
        with pytest.raises(configparser.InterpolationSyntaxError):
            self._parse("reduced by 84% overall")

    def test_escaped_percent_is_fine(self):
        assert self._parse("reduced by 84%% overall") == "reduced by 84% overall"
