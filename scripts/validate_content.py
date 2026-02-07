#!/usr/bin/env python3
"""Validate YAML content files against JSON Schema definitions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Missing dependency: pyyaml. Install with `pip install pyyaml jsonschema`."
    ) from exc

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Missing dependency: jsonschema. Install with `pip install pyyaml jsonschema`."
    ) from exc


SCHEMA_MAP = {
    "images": "image.schema.json",
    "objects": "object.schema.json",
    "equipment": "equipment.schema.json",
    "setups": "setup.schema.json",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def yaml_files_in(directory: Path) -> list[Path]:
    files = list(directory.glob("*.yml")) + list(directory.glob("*.yaml"))
    return sorted(files)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate content YAML files against local JSON Schemas."
    )
    parser.add_argument(
        "--content-dir",
        default="content",
        help="Directory containing images/objects/equipment/setups YAML folders.",
    )
    parser.add_argument(
        "--schemas-dir",
        default="schemas",
        help="Directory containing *.schema.json files.",
    )
    args = parser.parse_args()

    content_dir = Path(args.content_dir)
    schemas_dir = Path(args.schemas_dir)

    has_errors = False
    checked_files = 0

    for section, schema_name in SCHEMA_MAP.items():
        schema_path = schemas_dir / schema_name
        if not schema_path.exists():
            print(f"ERROR: schema not found: {schema_path}")
            has_errors = True
            continue

        section_dir = content_dir / section
        if not section_dir.exists():
            print(f"WARN: content directory not found, skipping: {section_dir}")
            continue

        schema = load_json(schema_path)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())

        files = yaml_files_in(section_dir)
        if not files:
            print(f"WARN: no YAML files found in {section_dir}")
            continue

        for file_path in files:
            checked_files += 1
            data = load_yaml(file_path)
            errors = sorted(validator.iter_errors(data), key=lambda err: list(err.path))
            if not errors:
                continue

            has_errors = True
            print(f"\nERROR: {file_path}")
            for err in errors:
                if err.path:
                    location = ".".join(str(token) for token in err.path)
                else:
                    location = "<root>"
                print(f"  - {location}: {err.message}")

    if has_errors:
        print(f"\nValidation failed. Checked {checked_files} file(s).")
        return 1

    print(f"Validation passed. Checked {checked_files} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
