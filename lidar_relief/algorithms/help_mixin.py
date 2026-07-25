"""help_mixin.py — Gives every algorithm a Help button linking to the guide.

exports: HelpUrlMixin, USER_GUIDE_URL
used_by: every class in algorithms/ [cascade]

rules:
  Mix in BEFORE QgsProcessingAlgorithm so helpUrl() resolves here.
  helpUrl() must never raise and must always return a usable URL — QGIS
  calls it while building the algorithm dialog, and an exception there
  breaks the dialog rather than merely losing a link.
  HELP_ANCHOR must match a real heading in lidar_relief/USER_GUIDE.md.
  GitHub derives an anchor by lowercasing the heading, dropping anything
  that is not alphanumeric/space/hyphen, and replacing spaces with
  hyphens. test_help_urls.py checks every anchor against the actual
  headings in the guide, so a renamed section fails the suite rather
  than silently producing a dead link.
agent:   claude-opus-5 | anthropic | 2026-07-25 | s_20260725_001 |
         New mixin. All 30 algorithms had shortHelpString, but none
         implemented helpUrl, so no algorithm dialog offered a route to
         the user guide. The guide was also absent from the published
         zip, which meant a user working inside QGIS had no path to it
         at all short of finding the GitHub repository unprompted.
"""

# Points at the default branch rather than a tag: the guide describes the
# plugin as it currently is, and a user on an older build following this
# link still lands on documentation that is a superset of their version.
USER_GUIDE_URL = (
    "https://github.com/dig-tools/lidar-relief-qgis-plugin"
    "/blob/main/lidar_relief/USER_GUIDE.md"
)


class HelpUrlMixin:
    """Adds a Help button to an algorithm's dialog.

    Set ``HELP_ANCHOR`` on a subclass to deep-link to that algorithm's
    section of the user guide. Leave it unset to link to the top of the
    guide, which is still far better than no link.
    """

    HELP_ANCHOR = ""

    def helpUrl(self) -> str:
        """Return the documentation URL QGIS shows as a Help link."""
        anchor = getattr(self, "HELP_ANCHOR", "") or ""
        if anchor:
            return f"{USER_GUIDE_URL}#{anchor}"
        return USER_GUIDE_URL

    def shortDescription(self) -> str:
        """One-line summary used in listings that have no room for help text."""
        return self.displayName()
