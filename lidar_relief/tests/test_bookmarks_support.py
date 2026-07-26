import json
import os
import zipfile

from lidar_relief.study_bookmarks import (
    list_bookmarks,
    remove_bookmark,
    rename_bookmark,
    save_bookmark,
)
from lidar_relief.support_bundle import create_support_bundle, redact_sensitive_text


class FakeSettings:
    def __init__(self):
        self.values = {}

    def value(self, key, defaultValue=None, **_kwargs):
        return self.values.get(key, defaultValue)

    def setValue(self, key, value):
        self.values[key] = value


def test_bookmarks_save_rename_remove_and_preserve_crs():
    settings = FakeSettings()
    save_bookmark("Alésia", (1, 2, 3, 4), "EPSG:2154", settings)
    assert list_bookmarks(settings) == [
        {"name": "Alésia", "extent": [1.0, 2.0, 3.0, 4.0], "crs": "EPSG:2154"}
    ]
    rename_bookmark("Alésia", "Mont Auxois", settings)
    assert list_bookmarks(settings)[0]["name"] == "Mont Auxois"
    remove_bookmark("Mont Auxois", settings)
    assert list_bookmarks(settings) == []


def test_bookmarks_reject_blank_names_and_invalid_extents():
    settings = FakeSettings()
    for name, extent in (("", (1, 2, 3, 4)), ("bad", (3, 2, 1, 4))):
        try:
            save_bookmark(name, extent, "EPSG:2154", settings)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid bookmark was accepted")


def test_support_redaction_masks_secret_assignments():
    text = (
        f"token=abc123 password: hunter2 ordinary=value "
        f"path={os.path.expanduser('~')}/survey"
    )
    redacted = redact_sensitive_text(text)
    assert "abc123" not in redacted
    assert "hunter2" not in redacted
    assert "ordinary=value" in redacted
    assert os.path.expanduser("~") not in redacted
    assert "<HOME>/survey" in redacted


def test_support_bundle_contains_manifest_and_optional_preflight(tmp_path):
    output = tmp_path / "support.zip"
    create_support_bundle(
        output,
        diagnostics="QGIS: 3.34\ntoken=secret",
        plugin_version="2.1.2",
        preflight="DEM is projected",
    )
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {
            "diagnostics.txt",
            "manifest.json",
            "dem-preflight.txt",
        }
        assert "secret" not in archive.read("diagnostics.txt").decode()
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["plugin_version"] == "2.1.2"
