#!/usr/bin/env python3
"""Validate YAML content files against schemas and project-wide invariants."""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Missing dependency: pyyaml. Install with `pip install pyyaml jsonschema`."
    ) from exc

try:
    from jsonschema import Draft202012Validator, FormatChecker
    from jsonschema.exceptions import SchemaError
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Missing dependency: jsonschema. Install with `pip install pyyaml jsonschema`."
    ) from exc


SCHEMA_MAP = {
    "images": "image.schema.json",
    "objects": "object.schema.json",
    "equipment": "equipment.schema.json",
    "locations": "location.schema.json",
}

IMAGE_ID_PATTERN = re.compile(
    r"^img_(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})_[a-z0-9][a-z0-9_-]*$"
)
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class ContentDocument:
    section: str
    path: Path
    data: Any


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    path: Path
    message: str
    location: tuple[str | int, ...] = ()


@dataclass(frozen=True)
class ValidationReport:
    checked_files: int
    errors: list[ValidationIssue]


class DuplicateKeyError(yaml.YAMLError):
    def __init__(self, key: Any, first_mark: Any, second_mark: Any) -> None:
        self.key = key
        self.first_mark = first_mark
        self.second_mark = second_mark
        super().__init__(str(self))

    def __str__(self) -> str:
        return (
            f"duplicate key {self.key!r} at line {self.second_mark.line + 1}, "
            f"column {self.second_mark.column + 1}; first defined at line "
            f"{self.first_mark.line + 1}, column {self.first_mark.column + 1}"
        )


class RecursiveAliasError(ValueError):
    pass


class UniqueKeySafeLoader(yaml.SafeLoader):
    def construct_mapping(self, node: Any, deep: bool = False) -> Any:
        if not isinstance(node, yaml.MappingNode):
            return super().construct_mapping(node, deep=deep)

        seen: dict[Any, Any] = {}
        for key_node, _ in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                key = "<<"
            else:
                key = self.construct_object(key_node, deep=False)
            try:
                first_mark = seen.get(key)
            except TypeError:
                continue

            if first_mark is not None:
                raise DuplicateKeyError(key, first_mark, key_node.start_mark)
            seen[key] = key_node.start_mark

        return super().construct_mapping(node, deep=deep)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("schema root must be a JSON object")
    return data


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return normalize_yaml_types(yaml.load(handle, Loader=UniqueKeySafeLoader))


def normalize_yaml_types(value: Any, ancestors: set[int] | None = None) -> Any:
    if ancestors is None:
        ancestors = set()

    if isinstance(value, dict):
        identity = id(value)
        if identity in ancestors:
            raise RecursiveAliasError("recursive YAML aliases are not supported")
        ancestors.add(identity)
        try:
            return {
                key: normalize_yaml_types(item, ancestors)
                for key, item in value.items()
            }
        finally:
            ancestors.remove(identity)
    if isinstance(value, list):
        identity = id(value)
        if identity in ancestors:
            raise RecursiveAliasError("recursive YAML aliases are not supported")
        ancestors.add(identity)
        try:
            return [normalize_yaml_types(item, ancestors) for item in value]
        finally:
            ancestors.remove(identity)
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    return value


def yaml_files_in(directory: Path) -> list[Path]:
    files = list(directory.glob("*.yml")) + list(directory.glob("*.yaml"))
    return sorted(files)


def issue_sort_key(issue: ValidationIssue) -> tuple[str, tuple[str, ...], str, str]:
    return (
        str(issue.path),
        tuple(str(token) for token in issue.location),
        issue.code,
        issue.message,
    )


def format_location(location: tuple[str | int, ...]) -> str:
    if not location:
        return "<root>"

    result = ""
    for token in location:
        if isinstance(token, int):
            result += f"[{token}]"
        elif result:
            result += f".{token}"
        else:
            result = token
    return result


def format_issue(issue: ValidationIssue) -> str:
    return (
        f"ERROR [{issue.code}] {issue.path}:{format_location(issue.location)}: "
        f"{issue.message}"
    )


def load_validators(
    schemas_dir: Path,
) -> tuple[dict[str, Draft202012Validator], list[ValidationIssue]]:
    validators: dict[str, Draft202012Validator] = {}
    issues: list[ValidationIssue] = []

    for section, schema_name in SCHEMA_MAP.items():
        schema_path = schemas_dir / schema_name
        if not schema_path.is_file():
            issues.append(
                ValidationIssue("missing-schema", schema_path, "schema file not found")
            )
            continue

        try:
            schema = load_json(schema_path)
            Draft202012Validator.check_schema(schema)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            ValueError,
            SchemaError,
        ) as exc:
            issues.append(
                ValidationIssue("invalid-schema", schema_path, str(exc).splitlines()[0])
            )
            continue

        validators[section] = Draft202012Validator(
            schema, format_checker=FormatChecker()
        )

    return validators, issues


def schema_issues(
    document: ContentDocument, validator: Draft202012Validator
) -> list[ValidationIssue]:
    errors = sorted(
        validator.iter_errors(document.data),
        key=lambda error: tuple(str(token) for token in error.absolute_path),
    )
    return [
        ValidationIssue(
            "schema",
            document.path,
            error.message,
            tuple(error.absolute_path),
        )
        for error in errors
    ]


def build_unique_indexes(
    documents: Sequence[ContentDocument],
) -> tuple[dict[str, dict[str, ContentDocument]], list[ValidationIssue]]:
    id_indexes: dict[str, dict[str, ContentDocument]] = {
        section: {} for section in SCHEMA_MAP
    }
    slug_indexes: dict[str, dict[str, ContentDocument]] = {
        section: {} for section in ("objects", "equipment", "locations")
    }
    issues: list[ValidationIssue] = []

    for document in sorted(documents, key=lambda item: str(item.path)):
        identifier = document.data.get("id")
        if isinstance(identifier, str):
            first = id_indexes[document.section].get(identifier)
            if first is None:
                id_indexes[document.section][identifier] = document
            else:
                issues.append(
                    ValidationIssue(
                        "duplicate-id",
                        document.path,
                        f"duplicate {document.section} id {identifier!r}; first defined in {first.path}",
                        ("id",),
                    )
                )

        if document.section not in slug_indexes:
            continue

        slug = document.data.get("slug")
        if not isinstance(slug, str):
            continue

        first = slug_indexes[document.section].get(slug)
        if first is None:
            slug_indexes[document.section][slug] = document
        else:
            issues.append(
                ValidationIssue(
                    "duplicate-slug",
                    document.path,
                    f"duplicate {document.section} slug {slug!r}; first defined in {first.path}",
                    ("slug",),
                )
            )

    return id_indexes, issues


def validate_image_references(
    documents: Sequence[ContentDocument],
    id_indexes: dict[str, dict[str, ContentDocument]],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    objects = id_indexes["objects"]
    equipment = id_indexes["equipment"]
    locations = id_indexes["locations"]

    for document in documents:
        if document.section != "images":
            continue

        image = document.data
        location_id = image.get("location_id")
        if isinstance(location_id, str) and location_id not in locations:
            issues.append(
                ValidationIssue(
                    "missing-reference",
                    document.path,
                    f"unknown location id {location_id!r}",
                    ("location_id",),
                )
            )

        capture_mode = image.get("capture_mode")
        targets = image.get("targets")
        if isinstance(targets, list):
            for index, target_id in enumerate(targets):
                if not isinstance(target_id, str):
                    continue
                target = objects.get(target_id)
                if target is None:
                    issues.append(
                        ValidationIssue(
                            "missing-reference",
                            document.path,
                            f"unknown object id {target_id!r}",
                            ("targets", index),
                        )
                    )
                else:
                    target_domain = target.data.get("domain")
                    valid_domains = {"deep_sky", "solar_system"}
                    if capture_mode not in valid_domains or target_domain not in valid_domains:
                        continue
                    if target_domain == capture_mode:
                        continue
                    issues.append(
                        ValidationIssue(
                            "target-domain-mismatch",
                            document.path,
                            f"image capture_mode {capture_mode!r} does not match object {target_id!r} domain {target_domain!r}",
                            ("targets", index),
                        )
                    )

        image_equipment = image.get("equipment")
        if isinstance(image_equipment, dict):
            expected_kinds = {
                "scope_id": "scope",
                "mount_id": "mount",
                "camera_id": "camera",
                "filter_id": "filter",
            }
            for field, expected_kind in expected_kinds.items():
                equipment_id = image_equipment.get(field)
                if not isinstance(equipment_id, str):
                    continue
                referenced = equipment.get(equipment_id)
                location = ("equipment", field)
                if referenced is None:
                    issues.append(
                        ValidationIssue(
                            "missing-reference",
                            document.path,
                            f"unknown equipment id {equipment_id!r}",
                            location,
                        )
                    )
                else:
                    actual_kind = referenced.data.get("kind")
                    valid_kinds = {"scope", "mount", "camera", "filter"}
                    if actual_kind not in valid_kinds or actual_kind == expected_kind:
                        continue
                    issues.append(
                        ValidationIssue(
                            "wrong-equipment-kind",
                            document.path,
                            f"expected equipment kind {expected_kind!r}, got {actual_kind!r}",
                            location,
                        )
                    )

        acquisitions = image.get("acquisitions")
        if isinstance(acquisitions, list):
            for index, acquisition in enumerate(acquisitions):
                if not isinstance(acquisition, dict):
                    continue
                filter_id = acquisition.get("filter_id")
                if not isinstance(filter_id, str):
                    continue
                referenced = equipment.get(filter_id)
                location = ("acquisitions", index, "filter_id")
                if referenced is None:
                    issues.append(
                        ValidationIssue(
                            "missing-reference",
                            document.path,
                            f"unknown equipment id {filter_id!r}",
                            location,
                        )
                    )
                else:
                    actual_kind = referenced.data.get("kind")
                    valid_kinds = {"scope", "mount", "camera", "filter"}
                    if actual_kind not in valid_kinds or actual_kind == "filter":
                        continue
                    issues.append(
                        ValidationIssue(
                            "wrong-equipment-kind",
                            document.path,
                            f"expected equipment kind 'filter', got {actual_kind!r}",
                            location,
                        )
                    )

    return issues


def validate_image_dates(documents: Sequence[ContentDocument]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for document in documents:
        if document.section != "images":
            continue

        image_id = document.data.get("id")
        image_date = document.data.get("date")
        parsed_image_date: datetime.date | None = None
        if isinstance(image_date, str) and DATE_PATTERN.fullmatch(image_date):
            try:
                parsed_image_date = datetime.date.fromisoformat(image_date)
            except ValueError:
                pass

        if isinstance(image_id, str):
            match = IMAGE_ID_PATTERN.fullmatch(image_id)
            if match is None:
                issues.append(
                    ValidationIssue(
                        "invalid-image-id",
                        document.path,
                        "image id must follow img_YYYYMMDD_name",
                        ("id",),
                    )
                )
            else:
                try:
                    id_date = datetime.date(
                        int(match.group("year")),
                        int(match.group("month")),
                        int(match.group("day")),
                    ).isoformat()
                except ValueError:
                    issues.append(
                        ValidationIssue(
                            "invalid-image-id-date",
                            document.path,
                            "image id contains an invalid calendar date",
                            ("id",),
                        )
                    )
                else:
                    if (
                        parsed_image_date is not None
                        and id_date != parsed_image_date.isoformat()
                    ):
                        issues.append(
                            ValidationIssue(
                                "image-id-date-mismatch",
                                document.path,
                                f"image id date {id_date!r} does not match image date {image_date!r}",
                                ("date",),
                            )
                        )

        acquisitions = document.data.get("acquisitions")
        if (
            parsed_image_date is None
            or not isinstance(acquisitions, list)
            or not acquisitions
        ):
            continue

        acquisition_dates: list[datetime.date] = []
        invalid_acquisition_date = False
        for acquisition in acquisitions:
            if not isinstance(acquisition, dict):
                invalid_acquisition_date = True
                break
            acquisition_date = acquisition.get("date")
            if (
                not isinstance(acquisition_date, str)
                or not DATE_PATTERN.fullmatch(acquisition_date)
            ):
                invalid_acquisition_date = True
                break
            try:
                acquisition_dates.append(datetime.date.fromisoformat(acquisition_date))
            except ValueError:
                invalid_acquisition_date = True
                break

        if acquisition_dates and not invalid_acquisition_date:
            latest_date = max(acquisition_dates).isoformat()
            if latest_date != image_date:
                issues.append(
                    ValidationIssue(
                        "acquisition-date-mismatch",
                        document.path,
                        f"latest acquisition date {latest_date!r} does not match image date {image_date!r}",
                        ("date",),
                    )
                )

    return issues


def validate_global_integrity(
    documents: Sequence[ContentDocument],
) -> list[ValidationIssue]:
    id_indexes, issues = build_unique_indexes(documents)
    issues.extend(validate_image_references(documents, id_indexes))
    issues.extend(validate_image_dates(documents))
    return sorted(issues, key=issue_sort_key)


def run_validation(content_dir: Path, schemas_dir: Path) -> ValidationReport:
    validators, issues = load_validators(schemas_dir)
    parsed_documents: list[ContentDocument] = []
    checked_files = 0

    for section in SCHEMA_MAP:
        section_dir = content_dir / section
        if not section_dir.is_dir():
            issues.append(
                ValidationIssue(
                    "missing-content-directory",
                    section_dir,
                    "required content directory not found",
                )
            )
            continue

        files = yaml_files_in(section_dir)
        if not files:
            issues.append(
                ValidationIssue(
                    "empty-content-directory",
                    section_dir,
                    "required content directory contains no YAML files",
                )
            )
            continue

        validator = validators.get(section)
        for file_path in files:
            checked_files += 1
            try:
                data = load_yaml(file_path)
            except DuplicateKeyError as exc:
                issues.append(
                    ValidationIssue("duplicate-yaml-key", file_path, str(exc))
                )
                continue
            except RecursiveAliasError as exc:
                issues.append(
                    ValidationIssue("recursive-yaml-alias", file_path, str(exc))
                )
                continue
            except yaml.YAMLError as exc:
                mark = getattr(exc, "problem_mark", None)
                position = ""
                if mark is not None:
                    position = f" at line {mark.line + 1}, column {mark.column + 1}"
                problem = getattr(exc, "problem", None) or str(exc).splitlines()[0]
                issues.append(
                    ValidationIssue(
                        "yaml-syntax", file_path, f"invalid YAML{position}: {problem}"
                    )
                )
                continue
            except UnicodeError as exc:
                issues.append(
                    ValidationIssue(
                        "invalid-encoding",
                        file_path,
                        f"content must be valid UTF-8: {exc}",
                    )
                )
                continue
            except OSError as exc:
                issues.append(ValidationIssue("io", file_path, str(exc)))
                continue

            document = ContentDocument(section, file_path, data)
            if isinstance(data, dict):
                parsed_documents.append(document)

            if validator is None:
                continue

            document_issues = schema_issues(document, validator)
            issues.extend(document_issues)

    issues.extend(validate_global_integrity(parsed_documents))
    return ValidationReport(checked_files, sorted(issues, key=issue_sort_key))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate content schemas and project-wide data integrity."
    )
    parser.add_argument(
        "--content-dir",
        default="content",
        help="Directory containing images/objects/equipment/locations YAML folders.",
    )
    parser.add_argument(
        "--schemas-dir",
        default="schemas",
        help="Directory containing *.schema.json files.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_validation(Path(args.content_dir), Path(args.schemas_dir))

    if report.errors:
        for issue in report.errors:
            print(format_issue(issue), file=sys.stderr)
        print(
            f"Validation failed with {len(report.errors)} error(s). "
            f"Checked {report.checked_files} file(s).",
            file=sys.stderr,
        )
        return 1

    print(f"Validation passed. Checked {report.checked_files} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
