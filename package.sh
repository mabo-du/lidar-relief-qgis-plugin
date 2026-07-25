#!/bin/bash
set -e

# Extract version from metadata.txt
VERSION=$(grep '^version=' lidar_relief/metadata.txt | cut -d'=' -f2)

# Sanity check: ensure metadata.txt version matches the top entry of
# CHANGELOG.md. The two have drifted in the past, causing users to see
# the wrong changelog when installing a new version.
CHANGELOG_TOP=$(grep -E '^##\s+\[' CHANGELOG.md | grep -v 'Unreleased' | head -1 | sed -E 's/^## \[([0-9.]+)\].*$/\1/')
if [ -n "$CHANGELOG_TOP" ] && [ "$CHANGELOG_TOP" != "$VERSION" ]; then
    echo "ERROR: metadata.txt version ($VERSION) does not match top CHANGELOG.md entry ($CHANGELOG_TOP)"
    echo "Please update both files to the same version before packaging."
    exit 1
fi

ZIP_NAME="lidar_relief_v${VERSION}.zip"

echo "Packaging LiDAR Relief Visualization Plugin v${VERSION}..."

# Remove old zip if it exists
if [ -f "$ZIP_NAME" ]; then
    rm "$ZIP_NAME"
fi

# NOTE: this script used to copy CHANGELOG.md and USER_GUIDE.md into
# lidar_relief/ before zipping, then delete them again. That made the LOCAL
# zip contain documentation the RELEASED zip did not, because CI publishes
# through `qgis-plugin-ci release`, which builds its archive from
# `git archive` — tracked files only, so temporary copies were invisible to
# it. Every published release from 2.0 onwards therefore shipped without the
# documentation this script was carefully adding.
#
# Both paths now agree, without any copying:
#   - USER_GUIDE.md is tracked at lidar_relief/USER_GUIDE.md, so it is in
#     the archive by virtue of being a plugin file.
#   - CHANGELOG.md is NOT shipped as a file by either path. It does not need
#     to be: qgis-plugin-ci injects its content into metadata.txt's
#     `changelog=` field, which is what QGIS Plugin Manager actually renders.
#
# If you add another document for users, track it under lidar_relief/ rather
# than copying it in here, or the two paths will diverge again.

# Zip the plugin folder, excluding tests, pycache, hidden files, etc.
zip -r "$ZIP_NAME" lidar_relief/ \
    -x "lidar_relief/tests/*" \
    -x "lidar_relief/tests" \
    -x "*/__pycache__/*" \
    -x "*/.pytest_cache/*" \
    -x "*/.*" \
    -x "*.pyc"

echo ""
echo "Successfully created $ZIP_NAME!"
echo "This file can be uploaded to the QGIS Plugin Repository or attached to a GitHub Release."
