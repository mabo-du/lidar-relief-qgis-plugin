import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _png_text_metadata(path):
    metadata = {}
    with path.open("rb") as stream:
        assert stream.read(8) == b"\x89PNG\r\n\x1a\n"
        while True:
            length_bytes = stream.read(4)
            if not length_bytes:
                break
            length = struct.unpack(">I", length_bytes)[0]
            chunk_type = stream.read(4)
            chunk_data = stream.read(length)
            stream.read(4)  # CRC is validated by image tooling at generation time.
            if chunk_type == b"tEXt":
                keyword, value = chunk_data.split(b"\0", 1)
                metadata[keyword.decode("latin-1")] = value.decode("latin-1")
            if chunk_type == b"IEND":
                break
    return metadata


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
    metadata = _png_text_metadata(image_path)
    assert metadata["Software"] == (
        "LiDAR Relief compute_ruggedness documentation generator"
    )
    assert "compute_ruggedness" in metadata["Description"]
