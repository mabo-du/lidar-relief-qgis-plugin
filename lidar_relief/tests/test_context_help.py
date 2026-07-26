"""Pure-Python checks for the optional contextual-help introduction."""

from lidar_relief.context_help import (
    MENU_LABEL,
    SETTINGS_GUIDANCE_SEEN,
    SETTINGS_SHOW_GUIDANCE,
    guidance_text,
    should_show_guidance,
)


class FakeSettings:
    def __init__(self, values=None):
        self.values = values or {}

    def value(self, key, defaultValue=None, **_kwargs):
        return self.values.get(key, defaultValue)


def test_guidance_explains_parameter_and_algorithm_help():
    title, text = guidance_text()
    assert "contextual help" in title.lower()
    assert "?" in text
    assert "tooltip" in text.lower()
    assert "help button" in text.lower()
    assert "safe starting point" in text.lower()


def test_settings_key_is_plugin_scoped_and_stable():
    assert SETTINGS_SHOW_GUIDANCE == "lidar_relief/context_help/show_guidance"
    assert SETTINGS_GUIDANCE_SEEN == "lidar_relief/context_help/guidance_seen"
    assert MENU_LABEL == "&LiDAR Relief"


def test_guidance_is_first_run_only_by_default():
    assert should_show_guidance(FakeSettings()) is True
    assert should_show_guidance(FakeSettings({SETTINGS_GUIDANCE_SEEN: True})) is False


def test_user_can_explicitly_request_startup_guidance():
    settings = FakeSettings(
        {SETTINGS_GUIDANCE_SEEN: True, SETTINGS_SHOW_GUIDANCE: True}
    )
    assert should_show_guidance(settings) is True
