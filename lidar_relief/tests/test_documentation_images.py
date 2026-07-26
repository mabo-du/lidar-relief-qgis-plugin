import re
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]


def test_all_markdown_image_files_exist():
    documents = (ROOT / "README.md", ROOT / "lidar_relief" / "USER_GUIDE.md")
    missing = []
    for document in documents:
        text = document.read_text(encoding="utf-8")
        references = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
        references.extend(re.findall(r'<img[^>]+src="([^"]+)"', text))
        for relative in references:
            if relative.startswith(("http://", "https://")):
                continue
            image = (document.parent / relative).resolve()
            if not image.is_file():
                missing.append(f"{document.name}: {relative}")
    assert missing == []


def test_tri_figure_records_direct_algorithm_provenance():
    image_path = ROOT / "lidar_relief" / "docs" / "images" / "tri-synthetic-example.png"
    with Image.open(image_path) as image:
        assert image.info["Software"] == (
            "LiDAR Relief compute_ruggedness documentation generator"
        )
        assert "compute_ruggedness" in image.info["Description"]
