import ast
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "lidar_relief" / "USER_GUIDE.md"
MANIFEST = ROOT / "lidar_relief" / "docs" / "images" / "screenshot-manifest.json"


def _registered_algorithm_ids():
    ids = set()
    for path in (ROOT / "lidar_relief" / "algorithms").glob("*_algorithm.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for class_node in (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name.endswith("Algorithm")
        ):
            for method in class_node.body:
                if not isinstance(method, ast.FunctionDef) or method.name != "name":
                    continue
                returns = [
                    node.value.value
                    for node in ast.walk(method)
                    if isinstance(node, ast.Return)
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ]
                if returns:
                    ids.add(f"lidar_relief:{returns[0]}")
    return ids


def _manifest_entries():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["screenshots"]


def test_manifest_covers_every_processing_algorithm():
    entries = _manifest_entries()
    captured = {
        item["feature_id"] for item in entries if item["kind"] == "algorithm-dialog"
    }
    assert captured == _registered_algorithm_ids()


def test_manifest_records_real_qgis_capture_provenance():
    entries = _manifest_entries()
    assert entries
    assert all(item["source"] == "actual-qgis-capture" for item in entries)
    assert all(item["qgis_version"] for item in entries)
    assert all(item["plugin_version"] for item in entries)
    assert all((MANIFEST.parent / item["file"]).is_file() for item in entries)


def test_guide_has_instructions_and_screenshot_for_every_algorithm():
    guide = GUIDE.read_text(encoding="utf-8")
    ids = _registered_algorithm_ids()
    documented = set(re.findall(r"<!-- feature:(lidar_relief:[^ ]+) -->", guide))
    assert documented == ids
    for feature_id in ids:
        marker = f"<!-- feature:{feature_id} -->"
        section = guide.split(marker, 1)[1].split("<!-- feature:", 1)[0]
        assert "**How to use it**" in section
        assert "docs/images/qgis/" in section


def test_readme_and_guide_explain_screenshot_authenticity():
    combined = "\n".join(
        (
            (ROOT / "README.md").read_text(encoding="utf-8"),
            GUIDE.read_text(encoding="utf-8"),
        )
    ).lower()
    assert "actual qgis" in combined
    assert "mockup" in combined
    assert "screenshot-manifest.json" in combined
