"""Repository-level checks for reproducible security scanning policy."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = ROOT / "requirements-audit.txt"
WORKFLOW = ROOT / ".github" / "workflows" / "security.yml"


def _pinned_requirements():
    lines = [
        line.strip()
        for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return dict(line.split("==", 1) for line in lines)


def test_audit_manifest_is_exact_and_covers_direct_dependencies():
    requirements = _pinned_requirements()
    assert set(requirements) == {
        "numpy",
        "scipy",
        "Pillow",
        "onnx",
        "onnxruntime",
        "rio-cogeo",
        "reportlab",
        "xarray",
        "rioxarray",
        "rasterio",
        "cloth-simulation-filter",
        "laspy",
        "rvt-py",
    }
    assert requirements["Pillow"] == "12.3.0"
    assert requirements["onnx"] == "1.22.0"
    assert requirements["onnxruntime"] == "1.27.0"


def test_gdal_is_deliberately_qgis_managed():
    requirements = REQUIREMENTS.read_text(encoding="utf-8")
    assert "GDAL is supplied by QGIS" in requirements
    assert not re.search(r"(?im)^gdal[=<>]", requirements)


def test_security_workflow_runs_both_scanners_and_pins_actions():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "semgrep scan" in workflow
    assert "requirements-audit.txt" in workflow
    assert "pypa/gh-action-pip-audit@" in workflow
    action_refs = re.findall(r"uses:\s*[^@\s]+@([^\s#]+)", workflow)
    assert action_refs
    assert all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in action_refs)


def test_verified_urllib_finding_has_narrow_semgrep_suppression():
    source = (ROOT / "scripts" / "verify_published.py").read_text(encoding="utf-8")
    rule = (
        "python.lang.security.audit.dynamic-urllib-use-detected."
        "dynamic-urllib-use-detected"
    )
    matching_lines = [
        line for line in source.splitlines() if "urllib.request.urlopen" in line
    ]
    assert len(matching_lines) == 1
    assert f"nosemgrep: {rule}" in matching_lines[0]
