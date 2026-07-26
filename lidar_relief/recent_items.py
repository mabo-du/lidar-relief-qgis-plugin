"""Bounded QSettings history for recipes and output folders."""

from __future__ import annotations

import os
from collections.abc import Iterable

MAX_RECENT_ITEMS = 8
SETTINGS_RECENT_RECIPES = "lidar_relief/recent/recipes"
SETTINGS_RECENT_OUTPUTS = "lidar_relief/recent/output_folders"
_PROCESSING_SENTINELS = {"", "TEMPORARY_OUTPUT", "memory:"}


def _settings(settings=None):
    if settings is not None:
        return settings
    from qgis.PyQt.QtCore import QSettings

    return QSettings()


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item]
    return []


def _normalise(path) -> str:
    try:
        value = os.fspath(path)
    except TypeError:
        return ""
    if value in _PROCESSING_SENTINELS or value.startswith("memory:"):
        return ""
    return os.path.abspath(os.path.expanduser(value))


def _record(path: str, key: str, settings, validator) -> None:
    normalised = _normalise(path)
    if not normalised or not validator(normalised):
        return
    existing = [
        item
        for item in _as_list(settings.value(key, []))
        if item != normalised and validator(item)
    ]
    settings.setValue(key, [normalised, *existing][:MAX_RECENT_ITEMS])


def _recent(key: str, settings, validator) -> list[str]:
    found = []
    for item in _as_list(settings.value(key, [])):
        normalised = _normalise(item)
        if normalised and validator(normalised) and normalised not in found:
            found.append(normalised)
    found = found[:MAX_RECENT_ITEMS]
    settings.setValue(key, found)
    return found


def record_recent_recipe(path, settings=None) -> None:
    """Record a successfully read or written JSON recipe."""
    settings = _settings(settings)
    _record(path, SETTINGS_RECENT_RECIPES, settings, os.path.isfile)


def recent_recipes(settings=None) -> list[str]:
    """Return existing recent recipe files, newest first."""
    settings = _settings(settings)
    return _recent(SETTINGS_RECENT_RECIPES, settings, os.path.isfile)


def record_output_folder(path, settings=None) -> None:
    """Record a directory, or the parent directory of an output file."""
    settings = _settings(settings)
    normalised = _normalise(path)
    if not normalised:
        return
    folder = normalised if os.path.isdir(normalised) else os.path.dirname(normalised)
    _record(folder, SETTINGS_RECENT_OUTPUTS, settings, os.path.isdir)


def recent_output_folders(settings=None) -> list[str]:
    """Return existing recent output directories, newest first."""
    settings = _settings(settings)
    return _recent(SETTINGS_RECENT_OUTPUTS, settings, os.path.isdir)


def _walk_values(value) -> Iterable:
    if isinstance(value, dict):
        for nested in value.values():
            yield from _walk_values(nested)
    elif isinstance(value, (list, tuple, set)):
        for nested in value:
            yield from _walk_values(nested)
    else:
        yield value


def record_result_paths(results, settings=None) -> None:
    """Record parent folders from a Processing result dictionary."""
    settings = _settings(settings)
    for value in _walk_values(results or {}):
        if isinstance(value, (str, os.PathLike)):
            record_output_folder(value, settings)
