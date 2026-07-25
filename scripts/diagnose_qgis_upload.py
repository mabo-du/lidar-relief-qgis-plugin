#!/usr/bin/env python3
"""diagnose_qgis_upload.py — Upload to plugins.qgis.org and SHOW the response.

exports: upload(archive, package_name, token, timeout) -> tuple[int, str],
         describe_response(status, body) -> str,
         main() -> int

used_by: .github/workflows/diagnose-qgis-upload.yml

rules:
  Replicates qgis-plugin-ci's upload_plugin_to_osgeo_with_token EXACTLY —
  same URL shape, same Bearer header, same single "package" multipart
  field. If that function changes, change this to match, or a diagnosis
  here will not describe the real release path.
  The whole point is the response BODY. qgis-plugin-ci calls
  raise_for_status() and then logs only the status line, so every
  rejection arrives as a bare "HTTP Error 400" with no reason. Always
  print the body, on success and on failure.
  NEVER print the token or the request headers. Only ever echo what the
  server sent back.
  This performs a real upload. A success here publishes the version —
  there is no dry-run endpoint. That is intentional: the fastest way to
  learn whether a package is acceptable is to offer it.
agent:   claude-opus-5 | anthropic | 2026-07-25 | s_20260725_001 |
         Added after v2.1.1 was refused three times with an
         uninformative HTTP 400. Read qgis-plugin-ci's release.py to
         copy the request faithfully; it discards response.text, which
         is why the cause was unknowable from CI logs and why 2.0.16
         and 2.0.17 both fell back to manual web-form uploads.
"""

import argparse
import json
import os
import sys

QGIS_PLUGINS_REPO_URL = "https://plugins.qgis.org"

# Fields the QGIS plugin registry has historically rejected, with the
# shape of the fix. Used to turn a raw error into something actionable.
KNOWN_FIELD_HINTS = {
    "tags": (
        "The registry caps how many tags a plugin may declare. This repo hit "
        "that at 43 tags in v2.0.18; the fix was trimming to ~5 broad terms."
    ),
    "about": (
        "Try shortening the about= block in lidar_relief/metadata.txt. It is "
        "the longest free-text field and was extended in the failing version."
    ),
    "description": (
        "Shorten description= in lidar_relief/metadata.txt — it is a "
        "single-line summary, not a prose block."
    ),
    "icon": (
        "Check lidar_relief/resources/icon.png is a real PNG the registry can "
        "decode. It was previously a JPEG carrying a .png extension."
    ),
    "version": (
        "This version may already exist on the registry, including as an "
        "unapproved pending upload. Check the version list while logged in."
    ),
    "changelog": (
        "qgis-plugin-ci injects CHANGELOG.md into metadata.txt's changelog= "
        "field at release time, so this can be far longer than the source file."
    ),
}


def upload(archive: str, package_name: str, token: str, timeout: int = 120) -> tuple:
    """POST the archive exactly as qgis-plugin-ci does.

    Returns:
        ``(status_code, body_text)``.

    Raises:
        RuntimeError: If the request could not be made at all.
    """
    import requests

    post_url = f"{QGIS_PLUGINS_REPO_URL}/plugins/api/{package_name}/version/add/"
    headers = {"Authorization": f"Bearer {token}"}

    print(f"POST {post_url}")
    print(f"     archive: {archive} ({os.path.getsize(archive):,} bytes)")
    print("     auth: Bearer <redacted>")
    print()

    try:
        with open(archive, "rb") as handle:
            response = requests.post(
                post_url,
                files={"package": handle},
                headers=headers,
                timeout=timeout,
            )
    except Exception as exc:  # noqa: BLE001 - report anything, never crash silently
        raise RuntimeError(f"Request could not be completed: {exc}") from exc

    return response.status_code, response.text


def describe_response(status: int, body: str) -> str:
    """Render the server's answer, pulling out field errors where present."""
    lines = [f"HTTP {status}", "=" * 60]

    parsed = None
    try:
        parsed = json.loads(body)
    except (ValueError, TypeError):
        pass

    if parsed is not None:
        lines.append(json.dumps(parsed, indent=2, sort_keys=True)[:4000])
    else:
        text = (body or "").strip()
        lines.append(text[:4000] if text else "(empty response body)")

    if 200 <= status < 300:
        lines.append("")
        lines.append("Accepted. The version may still need approval before it")
        lines.append("becomes publicly installable — verify with:")
        lines.append("  python3 scripts/verify_published.py <version>")
        return "\n".join(lines)

    # Surface any field name the server named, matched against known causes.
    haystack = (body or "").lower()
    hits = [field for field in KNOWN_FIELD_HINTS if field in haystack]
    if hits:
        lines.append("")
        lines.append("Fields named in the response:")
        for field in hits:
            lines.append(f"  - {field}: {KNOWN_FIELD_HINTS[field]}")
    else:
        lines.append("")
        lines.append("The response named no field this script recognises.")
        lines.append("Read the body above; if it is empty or generic, upload the")
        lines.append("same zip through the plugins.qgis.org web form, which")
        lines.append("renders validation errors that the API does not return.")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Upload a plugin archive to plugins.qgis.org and print the full "
            "server response. Performs a REAL upload."
        )
    )
    parser.add_argument("archive", help="Path to the plugin .zip")
    parser.add_argument("--package-name", default="lidar_relief")
    parser.add_argument(
        "--token-env",
        default="QGIS_TOKEN",
        help="Environment variable holding the plugins.qgis.org API token.",
    )
    args = parser.parse_args()

    token = os.environ.get(args.token_env, "").strip()
    if not token:
        print(
            f"No token found in ${args.token_env}. Set the secret before "
            f"running this diagnostic.",
            file=sys.stderr,
        )
        return 2

    if not os.path.isfile(args.archive):
        print(f"Archive not found: {args.archive}", file=sys.stderr)
        return 2

    try:
        status, body = upload(args.archive, args.package_name, token)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(describe_response(status, body))
    return 0 if 200 <= status < 300 else 1


if __name__ == "__main__":
    sys.exit(main())
