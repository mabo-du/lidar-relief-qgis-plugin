"""Redacted, deterministic support-bundle creation."""

from __future__ import annotations

import json
import os
import platform
import re
import zipfile
from datetime import datetime, timezone

_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|token|password|secret)\s*([:=])\s*([^\s,;]+)"
)


def redact_sensitive_text(text: str) -> str:
    """Mask common secret assignments while preserving diagnostic structure."""
    redacted = _SECRET_ASSIGNMENT.sub(r"\1\2<REDACTED>", str(text))
    home = os.path.expanduser("~")
    if home and home != "/":
        redacted = redacted.replace(home, "<HOME>")
    return redacted


def create_support_bundle(
    output_path,
    diagnostics: str,
    plugin_version: str,
    preflight: str = "",
) -> str:
    """Create a compact ZIP suitable for attaching to an issue."""
    path = os.fspath(output_path)
    manifest = {
        "format": "lidar-relief-support-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "plugin_version": plugin_version,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "diagnostics.txt", redact_sensitive_text(diagnostics).rstrip() + "\n"
        )
        archive.writestr(
            "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
        )
        if preflight:
            archive.writestr(
                "dem-preflight.txt", redact_sensitive_text(preflight).rstrip() + "\n"
            )
    return path
