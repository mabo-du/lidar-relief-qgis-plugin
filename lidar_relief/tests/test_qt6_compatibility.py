"""Static guards for Qt6-compatible scoped enum usage."""

import re
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]

UNSCOPED_ENUMS = (
    r"\bQMessageBox\.(?:Information|Ok)\b",
    r"\bQDialogButtonBox\.(?:Close|Save|Cancel|Open|ActionRole)\b",
    r"\bQt\.(?:UserRole|ItemIsUserCheckable|Checked|Unchecked)\b",
    r"\bQgsProcessingParameterDefinition\.FlagAdvanced\b",
)


def test_plugin_uses_qt6_scoped_enums():
    violations = []
    for path in PLUGIN_ROOT.rglob("*.py"):
        if "tests" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(source.splitlines(), start=1):
            for pattern in UNSCOPED_ENUMS:
                if re.search(pattern, line):
                    violations.append(
                        f"{path.relative_to(PLUGIN_ROOT)}:{line_number}: {line}"
                    )

    assert not violations, "Unscoped Qt/QGIS enums remain:\n" + "\n".join(violations)
