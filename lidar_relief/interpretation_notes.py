"""Structured, dependency-free archaeological interpretation notes."""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone

CONFIDENCE_LEVELS = ("low", "medium", "high")


def create_interpretation_note(
    title: str,
    interpretation: str,
    confidence: str,
    longitude: float,
    latitude: float,
    visualization: str,
) -> dict:
    """Create one WGS84 GeoJSON feature with review-friendly properties."""
    title = str(title).strip()
    interpretation = str(interpretation).strip()
    confidence = str(confidence).strip().lower()
    if not title or not interpretation:
        raise ValueError("A title and interpretation are required.")
    if confidence not in CONFIDENCE_LEVELS:
        raise ValueError(f"Unknown confidence level: {confidence}")
    longitude, latitude = float(longitude), float(latitude)
    if not -180 <= longitude <= 180:
        raise ValueError("Longitude must be between -180 and 180.")
    if not -90 <= latitude <= 90:
        raise ValueError("Latitude must be between -90 and 90.")
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
        "properties": {
            "title": title,
            "interpretation": interpretation,
            "confidence": confidence,
            "visualization": str(visualization).strip(),
            "created_utc": datetime.now(timezone.utc).isoformat(),
        },
    }


def write_interpretation_notes(notes: list[dict], output_path) -> str:
    """Write notes to GeoJSON or CSV according to the destination suffix."""
    path = os.fspath(output_path)
    suffix = os.path.splitext(path)[1].lower()
    if suffix in {".geojson", ".json"}:
        payload = {
            "type": "FeatureCollection",
            "name": "lidar_relief_interpretations",
            "features": notes,
        }
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        return path
    if suffix == ".csv":
        fields = (
            "title",
            "interpretation",
            "confidence",
            "visualization",
            "created_utc",
            "longitude",
            "latitude",
        )
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for note in notes:
                properties = note["properties"]
                longitude, latitude = note["geometry"]["coordinates"]
                writer.writerow(
                    {**properties, "longitude": longitude, "latitude": latitude}
                )
        return path
    raise ValueError("Interpretation notes must use .geojson, .json, or .csv.")
