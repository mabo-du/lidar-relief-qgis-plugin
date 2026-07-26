import csv
import json

import pytest

from lidar_relief.interpretation_notes import (
    create_interpretation_note,
    write_interpretation_notes,
)


def test_interpretation_note_is_structured_and_geojson_ready():
    note = create_interpretation_note(
        title="Possible bank",
        interpretation="Curving low earthwork",
        confidence="medium",
        longitude=4.49,
        latitude=47.54,
        visualization="SLRM",
    )
    assert note["type"] == "Feature"
    assert note["geometry"] == {"type": "Point", "coordinates": [4.49, 47.54]}
    assert note["properties"]["confidence"] == "medium"


def test_interpretation_note_rejects_invalid_confidence_and_coordinates():
    with pytest.raises(ValueError, match="confidence"):
        create_interpretation_note("A", "B", "certain", 4.0, 47.0, "SVF")
    with pytest.raises(ValueError, match="Longitude"):
        create_interpretation_note("A", "B", "high", 200, 47.0, "SVF")


def test_notes_export_to_geojson_and_csv(tmp_path):
    note = create_interpretation_note("Bank", "Possible bank", "low", 4, 47, "SVF")
    geojson = tmp_path / "notes.geojson"
    csv_path = tmp_path / "notes.csv"

    write_interpretation_notes([note], geojson)
    write_interpretation_notes([note], csv_path)

    assert json.loads(geojson.read_text(encoding="utf-8"))["features"] == [note]
    with csv_path.open(newline="", encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))
    assert row["title"] == "Bank"
    assert row["longitude"] == "4.0"
