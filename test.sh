#!/bin/bash
set -e

# Pin OpenMP to one thread for the whole test run.
#
# cloth-simulation-filter parallelises its cloth physics with
# `#pragma omp parallel for`, and OpenMP floating-point accumulation is not
# associative, so thread scheduling changes the result. Measured on identical
# input: ground-point counts of 16, 16, 14, 16 across four runs multi-threaded,
# versus 12 identical runs single-threaded. That is what makes
# test_csf_filter.py::TestCSFFilter::test_filter_deterministic flaky.
#
# csf_filter.py already calls os.environ.setdefault("OMP_NUM_THREADS", "1")
# when imported under a test runner, but that is inherently fragile: libgomp
# reads the variable when the OpenMP runtime initialises, so the setdefault
# only works if nothing has pulled OpenMP in first. Setting it here — before
# the interpreter starts — removes the ordering question entirely, and covers
# the release workflow, which runs this script rather than the tests.yml job
# that has its own guard.
#
# This affects the TEST environment only. Real users keep multi-threaded CSF
# and its speed; the non-determinism is inherent to the library, which is why
# the test asserts approximate rather than exact agreement.
export OMP_NUM_THREADS=1

echo "=== Installing Optional Test Dependencies ==="
pip install rio-cogeo reportlab xarray rioxarray \
    "Pillow==12.3.0" "onnxruntime==1.27.0" "onnx==1.22.0" 2>/dev/null || true
pip install cloth-simulation-filter 2>/dev/null || true
# rvt-py gates the ENTIRE golden-regression suite (test_golden_regression.py
# does `pytest.importorskip("rvt")` at module scope) and laspy gates the
# LAS->DEM integration test. Without them those modules report as "skipped",
# which reads like a healthy run — that is how a 100%-failing CSF code path
# and three GPU defects survived to v2.0.22. See "Interpreter requirements"
# in README.md.
pip install rvt-py laspy 2>/dev/null || true

# GDAL's Python bindings must match the libgdal on this machine EXACTLY —
# an unpinned `pip install gdal` grabs the newest release and aborts with
# "Python bindings of GDAL X require at least libgdal X". Derive the version
# from gdal-config. In the QGIS CI container osgeo is already present, so
# this is a no-op there.
if ! python3 -c "import osgeo" 2>/dev/null; then
    if command -v gdal-config >/dev/null 2>&1; then
        GDAL_VERSION="$(gdal-config --version)"
        echo "--- osgeo missing; installing gdal==${GDAL_VERSION} to match libgdal ---"
        pip install "gdal==${GDAL_VERSION}" 2>/dev/null || \
            echo "(gdal build failed — install libgdal-dev, or run the suite" \
                 "under an interpreter that already provides osgeo)"
    else
        echo "(gdal-config not found — GDAL-dependent tests will be skipped)"
    fi
fi

echo "=== Verifying the interpreter can actually run the whole suite ==="
# A skip count above ~5 means missing dependencies are hiding tests rather
# than the suite being green. Report it loudly instead of letting a
# partially-skipped run look like a pass.
python3 - <<'PYCHECK'
import importlib
import sys

required = {
    "osgeo": "GDAL — gates 7 test modules",
    "rvt": "rvt-py — gates the whole golden-regression suite",
    "rasterio": "rasterio — gates fusion tests",
    "rioxarray": "rioxarray — gates temporal tests",
}
missing = []
for module, why in required.items():
    try:
        importlib.import_module(module)
    except ImportError:
        missing.append(f"  - {module}: {why}")

if missing:
    print("WARNING: these tests will be SILENTLY SKIPPED, not run:")
    print("\n".join(missing))
    print(f"Interpreter: {sys.executable}")
else:
    print(f"OK — all gating dependencies present ({sys.executable})")
PYCHECK

echo "=== Running Code Formatter (ruff --check, read-only) ==="
# Use --check instead of auto-format so test.sh never modifies tracked files
# in CI. Drift is logged as a warning but does not block; run
# `ruff format lidar_relief/` locally before committing if you want autofix.
#
# NOTE: the conflict this comment used to describe was misdiagnosed. It
# blamed W503 (line break BEFORE a binary operator), but the scanner
# profile below leaves W503 in flake8's default ignore list, so ruff's
# operator placement is fine. The real clash was E203 — black-style
# formatting of a slice such as `a[i : i + n]` puts a space before the
# colon, which the scanner DOES flag. Two files were therefore left
# permanently unformatted. Both have since been rewritten to hoist slice
# bounds into locals, so the whole tree now satisfies the formatter and
# the scanner at once. If you add a computed slice, assign its bounds to
# locals first and this stays true.
python3 -m ruff format lidar_relief/ --check || echo "(format drift detected; informational only)"

echo "=== Running Linter (ruff check, no --fix) ==="
# Also read-only: no --fix so test.sh never auto-mutates tracked files.
# Findings here are informational only — the actual lint gate for the
# QGIS plugin scanner is `flake8 --isolated --select=W503,E402,E203`,
# which is run separately. Ruff's default rule set (E/F line) reports
# style opinions that the scanner doesn't enforce; surfacing them as
# warnings without blocking CI keeps the developer experience alive
# without risking the publish pipeline.
python3 -m ruff check lidar_relief/ || echo "(ruff check findings reported; informational only)"

echo "=== Running Comprehensive Linter (flake8 --isolated, mirrors QGIS scanner profile) ==="
# Mirrors plugins.qgis.org scanner exactly: enable W504 (line break AFTER
# binary operator) and explicitly ignore cosmetic visual-indent rules
# (#E117 over-indented, #E128 under-indented continuation, #E124 closing
# bracket mismatch, #E201 whitespace after '(') that the scanner does
# NOT enforce but default flake8 does. Net effect: CI failure mirrors
# scanner failure on the rules the scanner actually checks.
python3 -m flake8 --isolated --max-line-length=200     --extend-select=W504 --extend-ignore=E117,E128,E124,E201     lidar_relief/

echo "=== Running Unit Tests (pytest) ==="
python3 -m pytest lidar_relief/tests/ -v --tb=short

echo "=== Verifying CHANGELOG.md covers metadata.txt version ==="
# Local-dev safety net for the same guard CI runs in release.yml.  When this
# fails, the offending metadata.txt bump needs a matching `## [<version>]`
# header in CHANGELOG.md before tagging the release.  Pre-commit hook
# (.pre-commit-config.yaml) catches this on `git commit` too — this is
# belt-and-suspenders for devs who run `./test.sh` directly without
# `pre-commit install`.
python3 scripts/check_changelog.py

echo "✅ All tests and linting passed successfully!"
