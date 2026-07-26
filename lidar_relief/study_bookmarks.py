"""CRS-aware named map extents stored in QGIS settings."""

from __future__ import annotations

import json

SETTINGS_BOOKMARKS = "lidar_relief/study_bookmarks"
MAX_BOOKMARKS = 50


def _settings(settings=None):
    if settings is not None:
        return settings
    from qgis.PyQt.QtCore import QSettings

    return QSettings()


def list_bookmarks(settings=None) -> list[dict]:
    """Return valid bookmark records, newest first."""
    settings = _settings(settings)
    raw = settings.value(SETTINGS_BOOKMARKS, "[]")
    try:
        records = json.loads(raw) if isinstance(raw, str) else list(raw or [])
    except (TypeError, ValueError):
        records = []
    valid = []
    for record in records:
        try:
            name = str(record["name"]).strip()
            extent = [float(value) for value in record["extent"]]
            crs = str(record["crs"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if (
            name
            and crs
            and len(extent) == 4
            and extent[0] < extent[2]
            and extent[1] < extent[3]
            and name not in {item["name"] for item in valid}
        ):
            valid.append({"name": name, "extent": extent, "crs": crs})
    valid = valid[:MAX_BOOKMARKS]
    settings.setValue(SETTINGS_BOOKMARKS, json.dumps(valid, ensure_ascii=False))
    return valid


def save_bookmark(name, extent, crs: str, settings=None) -> None:
    """Save or replace one named extent."""
    settings = _settings(settings)
    name, crs = str(name).strip(), str(crs).strip()
    values = [float(value) for value in extent]
    if not name:
        raise ValueError("Bookmark name cannot be blank.")
    if len(values) != 4 or values[0] >= values[2] or values[1] >= values[3]:
        raise ValueError("Bookmark extent must be xmin, ymin, xmax, ymax.")
    if not crs:
        raise ValueError("Bookmark CRS cannot be blank.")
    records = [item for item in list_bookmarks(settings) if item["name"] != name]
    records.insert(0, {"name": name, "extent": values, "crs": crs})
    settings.setValue(
        SETTINGS_BOOKMARKS,
        json.dumps(records[:MAX_BOOKMARKS], ensure_ascii=False),
    )


def remove_bookmark(name: str, settings=None) -> None:
    settings = _settings(settings)
    records = [item for item in list_bookmarks(settings) if item["name"] != name]
    settings.setValue(SETTINGS_BOOKMARKS, json.dumps(records, ensure_ascii=False))


def rename_bookmark(old_name: str, new_name: str, settings=None) -> None:
    settings = _settings(settings)
    records = list_bookmarks(settings)
    match = next((item for item in records if item["name"] == old_name), None)
    if match is None:
        raise ValueError(f"Unknown bookmark: {old_name}")
    remove_bookmark(old_name, settings)
    save_bookmark(new_name, match["extent"], match["crs"], settings)
