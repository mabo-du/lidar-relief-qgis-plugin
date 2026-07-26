"""Optional in-QGIS introduction to parameter-level contextual help."""

from __future__ import annotations

SETTINGS_SHOW_GUIDANCE = "lidar_relief/context_help/show_guidance"
SETTINGS_GUIDANCE_SEEN = "lidar_relief/context_help/guidance_seen"
MENU_LABEL = "&LiDAR Relief"


def guidance_text() -> tuple[str, str]:
    """Return the stable, testable title and explanatory copy."""
    return (
        "LiDAR Relief contextual help",
        (
            "Every setting now includes a plain-language explanation.\n\n"
            "In a LiDAR Relief Processing dialog, look for QGIS's contextual "
            "help beside a parameter (usually a ? icon, tooltip, or help panel, "
            "depending on your QGIS version). It explains units, feature scale, "
            "quality-versus-speed trade-offs, and a safe starting point.\n\n"
            "For a broader explanation of an algorithm, use the Help button at "
            "the bottom of its Processing dialog."
        ),
    )


def should_show_guidance(settings=None) -> bool:
    """Return whether first-run or explicitly enabled startup help is due."""
    if settings is None:
        from qgis.PyQt.QtCore import QSettings

        settings = QSettings()
    seen = settings.value(SETTINGS_GUIDANCE_SEEN, False, type=bool)
    repeat = settings.value(SETTINGS_SHOW_GUIDANCE, False, type=bool)
    return not seen or repeat


def show_context_help(parent=None, settings=None) -> bool:
    """Show guidance and persist whether it should appear at startup.

    Returns the checkbox state after the dialog closes. Imports are local so
    the plugin's pure-Python tests do not require a QGIS runtime.
    """
    from qgis.PyQt.QtCore import QSettings
    from qgis.PyQt.QtWidgets import QCheckBox, QMessageBox

    settings = settings or QSettings()
    enabled = settings.value(SETTINGS_SHOW_GUIDANCE, False, type=bool)
    title, text = guidance_text()

    dialog = QMessageBox(parent)
    dialog.setIcon(QMessageBox.Information)
    dialog.setWindowTitle(title)
    dialog.setText(text)
    dialog.setStandardButtons(QMessageBox.Ok)

    checkbox = QCheckBox("Show this introduction again when QGIS starts")
    checkbox.setChecked(enabled)
    dialog.setCheckBox(checkbox)
    dialog.exec()

    enabled = checkbox.isChecked()
    settings.setValue(SETTINGS_GUIDANCE_SEEN, True)
    settings.setValue(SETTINGS_SHOW_GUIDANCE, enabled)
    return enabled
