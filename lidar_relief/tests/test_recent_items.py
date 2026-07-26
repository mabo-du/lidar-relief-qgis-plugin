from lidar_relief.recent_items import (
    MAX_RECENT_ITEMS,
    recent_output_folders,
    recent_recipes,
    record_output_folder,
    record_recent_recipe,
    record_result_paths,
)


class FakeSettings:
    def __init__(self):
        self.values = {}

    def value(self, key, defaultValue=None, **_kwargs):
        return self.values.get(key, defaultValue)

    def setValue(self, key, value):
        self.values[key] = value


def test_recipe_history_is_deduplicated_newest_first_and_bounded(tmp_path):
    settings = FakeSettings()
    paths = []
    for index in range(MAX_RECENT_ITEMS + 2):
        path = tmp_path / f"recipe-{index}.json"
        path.write_text("{}", encoding="utf-8")
        paths.append(path)
        record_recent_recipe(path, settings)

    record_recent_recipe(paths[-3], settings)
    found = recent_recipes(settings)
    assert found[0] == str(paths[-3].resolve())
    assert len(found) == MAX_RECENT_ITEMS
    assert len(found) == len(set(found))


def test_missing_recipe_entries_are_pruned(tmp_path):
    settings = FakeSettings()
    missing = tmp_path / "missing.json"
    settings.values["lidar_relief/recent/recipes"] = [str(missing)]
    assert recent_recipes(settings) == []


def test_result_files_record_their_parent_folders(tmp_path):
    settings = FakeSettings()
    first = tmp_path / "outputs-a"
    second = tmp_path / "outputs-b"
    first.mkdir()
    second.mkdir()

    record_result_paths(
        {"A": str(first / "one.tif"), "B": [str(second / "two.png")]},
        settings,
    )

    assert recent_output_folders(settings) == [
        str(second.resolve()),
        str(first.resolve()),
    ]


def test_output_folder_accepts_files_or_directories(tmp_path):
    settings = FakeSettings()
    folder = tmp_path / "outputs"
    folder.mkdir()
    file_path = folder / "result.tif"
    file_path.write_bytes(b"")

    record_output_folder(folder, settings)
    record_output_folder(file_path, settings)
    assert recent_output_folders(settings) == [str(folder.resolve())]


def test_history_ignores_processing_sentinels():
    settings = FakeSettings()
    record_result_paths({"OUTPUT": "TEMPORARY_OUTPUT"}, settings)
    assert recent_output_folders(settings) == []
