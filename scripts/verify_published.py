#!/usr/bin/env python3
"""verify_published.py — Confirm a release actually reached QGIS users.

exports: fetch_repository_xml(qgis_version, timeout) -> str,
         published_versions(xml_text, plugin_slug) -> list[str],
         check(version, plugin_slug, ...) -> tuple[bool, str]

used_by: .github/workflows/release.yml (post-publish verification),
         developers, manually, to answer "did that release land?"

rules:
  Read-only and side-effect free — this only ever performs a GET.
  A missing version is NOT treated as a build failure. plugins.qgis.org
  moderates uploads, so a legitimate release can sit unapproved for days;
  failing the job would train people to ignore a red tick. It emits a
  GitHub warning annotation and a step summary instead, which is loud
  enough to notice and honest about what it does and does not know.
  Never let a network problem fail the caller either: an unreachable
  repository says nothing about the release.
agent:   claude-opus-5 | anthropic | 2026-07-25 | s_20260725_001 |
         New script. The v2.1.0 release job reported success and logged
         "Plugin uploaded on plugins.qgis.org", yet the public repository
         kept serving 2.0.22 — the version was accepted but never became
         installable, and nothing anywhere said so. v2.1.1 was then
         rejected with a bare HTTP 400 whose body qgis-plugin-ci
         discards. Both failure modes were invisible; this makes the
         published state explicit at the end of every release.
"""

import argparse
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET  # nosec B405 — parses only the response we fetched

REPOSITORY_URL = "https://plugins.qgis.org/plugins/plugins.xml"

# The repository filters by target QGIS version. This plugin declares
# qgisMinimumVersion=3.0, so any modern 3.x listing includes it.
DEFAULT_QGIS_VERSION = "3.34"

DEFAULT_PLUGIN_SLUG = "lidar_relief"


def fetch_repository_xml(
    qgis_version: str = DEFAULT_QGIS_VERSION, timeout: int = 45
) -> str:
    """Fetch the public plugin repository listing.

    Raises:
        urllib.error.URLError: If the repository cannot be reached.
    """
    url = f"{REPOSITORY_URL}?qgis={qgis_version}"
    request = urllib.request.Request(
        url, headers={"User-Agent": "lidar-relief-release-check"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        return response.read().decode("utf-8", errors="replace")


def published_versions(xml_text: str, plugin_slug: str = DEFAULT_PLUGIN_SLUG) -> list:
    """Return every version of ``plugin_slug`` the repository is serving.

    Matches on the packaged file name (``<plugin_slug>.<version>.zip``)
    rather than the display name, because the display name contains
    spaces and changes more freely than the slug does.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    versions = []
    for plugin in root.iter():
        if not plugin.tag.endswith("pyqgis_plugin"):
            continue
        file_name = plugin.findtext("file_name") or ""
        if not file_name.startswith(f"{plugin_slug}."):
            continue
        version = plugin.get("version")
        if version:
            versions.append(version)
    return versions


def check(
    version: str,
    plugin_slug: str = DEFAULT_PLUGIN_SLUG,
    qgis_version: str = DEFAULT_QGIS_VERSION,
) -> tuple:
    """Determine whether ``version`` is installable by QGIS users.

    Returns:
        ``(is_published, message)``. ``is_published`` is False both when
        the version is genuinely absent and when the check could not be
        performed — the message distinguishes the two.
    """
    try:
        xml_text = fetch_repository_xml(qgis_version)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return False, (
            f"Could not reach {REPOSITORY_URL} to verify publication ({exc}). "
            f"This says nothing about the release itself — check the plugin "
            f"page manually."
        )

    versions = published_versions(xml_text, plugin_slug)
    if not versions:
        return False, (
            f"No versions of '{plugin_slug}' appear in the public repository "
            f"listing at all. Either the slug is wrong or the plugin is not "
            f"published."
        )

    if version in versions:
        return True, (
            f"v{version} is live on plugins.qgis.org and installable from "
            f"QGIS Plugin Manager."
        )

    newest = sorted(versions)[-1]
    return False, (
        f"v{version} is NOT being served by plugins.qgis.org — the public "
        f"repository is still offering v{newest}.\n"
        f"\n"
        f"The upload can succeed while the version stays invisible: "
        f"plugins.qgis.org moderates new versions, and an unapproved one is "
        f"visible only to the plugin owner when logged in.\n"
        f"\n"
        f"What to do:\n"
        f"  1. Log in at https://plugins.qgis.org/plugins/{plugin_slug}/ and "
        f"check the version list for a pending entry.\n"
        f"  2. Check the account email for a rejection or approval notice.\n"
        f"  3. A later upload may be refused with HTTP 400 while an earlier "
        f"version is still pending, so resolve the queue before tagging "
        f"again.\n"
        f"\n"
        f"The GitHub release is unaffected — users can still install the "
        f"zip from the releases page."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Check whether a released version is actually being served by "
            "plugins.qgis.org. Always exits 0 unless --strict is given."
        )
    )
    parser.add_argument("version", help="Version to look for, e.g. 2.1.1")
    parser.add_argument("--plugin-slug", default=DEFAULT_PLUGIN_SLUG)
    parser.add_argument("--qgis-version", default=DEFAULT_QGIS_VERSION)
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Exit non-zero when the version is not published. Off by "
            "default so moderation latency does not turn every release red."
        ),
    )
    args = parser.parse_args()

    published, message = check(
        args.version.lstrip("v"), args.plugin_slug, args.qgis_version
    )

    if published:
        print(f"::notice title=Published::{message}")
        print(f"PUBLISHED: {message}")
    else:
        # One-line annotation for the run header, full text for the log.
        first_line = message.splitlines()[0]
        print(f"::warning title=Not yet published::{first_line}")
        print(f"NOT PUBLISHED: {message}")

    return 1 if (args.strict and not published) else 0


if __name__ == "__main__":
    sys.exit(main())
