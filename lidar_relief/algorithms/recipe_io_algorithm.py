"""recipe_io_algorithm.py — QGIS Processing wrapper for Visualization Recipe I/O.

exports: RecipeExportAlgorithm, RecipeImportAlgorithm
used_by: provider.py → loadAlgorithms
"""

import json
import os

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterString,
    QgsProcessingOutputString,
    QgsProcessingException,
)

from ..recipes import export_recipe, import_recipe, validate_recipe
from ..recent_items import record_recent_recipe
from ..version import get_version
from .help_mixin import HelpUrlMixin


class RecipeExportAlgorithm(HelpUrlMixin, QgsProcessingAlgorithm):
    """Export current algorithm parameters as a shareable JSON recipe."""

    HELP_ANCHOR = "visualization-recipes"

    PARAMETERS = "PARAMETERS"
    NAME = "NAME"
    AUTHOR = "AUTHOR"
    DESCRIPTION = "DESCRIPTION"
    LANDSCAPE_TYPE = "LANDSCAPE_TYPE"
    TAGS = "TAGS"
    OUTPUT = "OUTPUT"
    OUTPUT_VALIDATION = "OUTPUT_VALIDATION"

    def name(self):
        return "recipe_export"

    def displayName(self):
        return "Export Visualization Recipe"

    def group(self):
        return "LiDAR Relief — Export"

    def groupId(self):
        return "lidar_relief_export"

    def shortHelpString(self):
        return (
            "Export current algorithm parameters as a shareable JSON recipe.\n\n"
            "Recipes can be shared via GitHub Gist, attached to publications, "
            "or imported by other users to reproduce your exact visualization "
            "workflow.\n\n"
            "The recipe includes algorithm parameters, terrain context, "
            "tags, and metadata for full reproducibility."
        )

    def createInstance(self):
        return RecipeExportAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterString(
                self.PARAMETERS,
                "Algorithm parameters (JSON)",
                multiLine=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(self.NAME, "Recipe name", optional=True)
        )
        self.addParameter(
            QgsProcessingParameterString(self.AUTHOR, "Author", optional=True)
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.DESCRIPTION, "Description", optional=True, multiLine=True
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.LANDSCAPE_TYPE,
                "Landscape type (flat_agricultural, forested, "
                "upland_steep, coastal, custom)",
                defaultValue="custom",
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.TAGS, "Tags (comma-separated)", optional=True
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT, "Output JSON recipe", fileFilter="JSON (*.json)"
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        params_json = self.parameterAsString(parameters, self.PARAMETERS, context)
        name = self.parameterAsString(parameters, self.NAME, context)
        author = self.parameterAsString(parameters, self.AUTHOR, context)
        description = self.parameterAsString(parameters, self.DESCRIPTION, context)
        landscape_type = self.parameterAsString(
            parameters, self.LANDSCAPE_TYPE, context
        )
        tags_str = self.parameterAsString(parameters, self.TAGS, context)
        output_path = self.parameterAsFileOutput(parameters, self.OUTPUT, context)

        # Parse parameters JSON
        try:
            algorithms = json.loads(params_json) if params_json.strip() else {}
        except json.JSONDecodeError as e:
            raise QgsProcessingException(f"Invalid parameters JSON: {e}")

        tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []

        try:
            recipe_json = export_recipe(
                algorithms=algorithms,
                name=name,
                author=author,
                description=description,
                landscape_type=landscape_type,
                tags=tags,
                plugin_version=get_version(),
            )
        except Exception as e:
            raise QgsProcessingException(f"Recipe export failed: {e}")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(recipe_json)

        record_recent_recipe(output_path)
        return {self.OUTPUT: output_path}


class RecipeImportAlgorithm(HelpUrlMixin, QgsProcessingAlgorithm):
    """Import a visualization recipe JSON file and validate it."""

    INPUT = "INPUT"
    OUTPUT_PARAMETERS = "OUTPUT_PARAMETERS"
    OUTPUT_METADATA = "OUTPUT_METADATA"

    def name(self):
        return "recipe_import"

    def displayName(self):
        return "Import and Validate Visualization Recipe"

    def group(self):
        return "LiDAR Relief — Export"

    def groupId(self):
        return "lidar_relief_export"

    def shortHelpString(self):
        return (
            "Import a visualization recipe JSON file and validate it.\n\n"
            "Validates the recipe structure, checks parameter types, "
            "and outputs the parsed parameters for use in other algorithms."
        )

    def createInstance(self):
        return RecipeImportAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT,
                "Recipe JSON file",
                fileFilter="JSON (*.json)",
            )
        )
        self.addOutput(
            QgsProcessingOutputString(
                self.OUTPUT_PARAMETERS, "Parsed algorithm parameters (JSON)"
            )
        )
        self.addOutput(
            QgsProcessingOutputString(self.OUTPUT_METADATA, "Recipe metadata (JSON)")
        )

    def processAlgorithm(self, parameters, context, feedback):
        file_path = self.parameterAsFile(parameters, self.INPUT, context)

        if not file_path or not os.path.exists(file_path):
            raise QgsProcessingException(f"Recipe file not found: {file_path}")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                recipe_data = import_recipe(f.read())
        except ValueError as e:
            raise QgsProcessingException(str(e))
        except IOError as e:
            raise QgsProcessingException(f"Failed to read recipe file: {e}")

        errors = validate_recipe(recipe_data)
        if errors:
            warning_lines = "\n".join(f"  - {e}" for e in errors)
            feedback.pushWarning("Recipe validation warnings:\n" + warning_lines)

        # Output the parameters as JSON
        params_json = json.dumps(recipe_data.get("algorithms", {}), indent=2)
        meta = {
            "name": recipe_data.get("name", ""),
            "author": recipe_data.get("author", ""),
            "description": recipe_data.get("description", ""),
            "landscape_type": recipe_data.get("landscape_type", ""),
            "tags": recipe_data.get("tags", []),
            "plugin_version": recipe_data.get("plugin_version", ""),
        }
        meta_json = json.dumps(meta, indent=2)

        record_recent_recipe(file_path)
        return {
            self.OUTPUT_PARAMETERS: params_json,
            self.OUTPUT_METADATA: meta_json,
        }
