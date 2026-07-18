from __future__ import annotations

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts import validate_content as validator


def document(section: str, name: str, data: dict) -> validator.ContentDocument:
    return validator.ContentDocument(section, Path("content") / section / name, data)


def valid_documents() -> list[validator.ContentDocument]:
    return [
        document(
            "objects",
            "target.yml",
            {
                "id": "target",
                "slug": "target",
                "domain": "deep_sky",
            },
        ),
        document(
            "equipment",
            "scope.yml",
            {"id": "scope", "slug": "scope", "kind": "scope"},
        ),
        document(
            "equipment",
            "mount.yml",
            {"id": "mount", "slug": "mount", "kind": "mount"},
        ),
        document(
            "equipment",
            "camera.yml",
            {"id": "camera", "slug": "camera", "kind": "camera"},
        ),
        document(
            "equipment",
            "filter.yml",
            {"id": "filter", "slug": "filter", "kind": "filter"},
        ),
        document(
            "locations",
            "location.yml",
            {"id": "location", "slug": "location"},
        ),
        document(
            "images",
            "image.yml",
            {
                "id": "img_20240102_target",
                "date": "2024-01-02",
                "capture_mode": "deep_sky",
                "location_id": "location",
                "targets": ["target"],
                "equipment": {
                    "scope_id": "scope",
                    "mount_id": "mount",
                    "camera_id": "camera",
                    "filter_id": "filter",
                },
                "acquisitions": [
                    {"date": "2024-01-01", "filter_id": "filter"},
                    {"date": "2024-01-02", "filter_id": "filter"},
                ],
            },
        ),
    ]


class YamlLoadingTests(unittest.TestCase):
    def load_text(self, text: str):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "content.yml"
            path.write_text(text, encoding="utf-8")
            return validator.load_yaml(path)

    def test_load_yaml_accepts_unique_keys(self):
        self.assertEqual(self.load_text("id: example\ntitle: Example\n"), {"id": "example", "title": "Example"})

    def test_load_yaml_rejects_duplicate_root_key(self):
        with self.assertRaises(validator.DuplicateKeyError) as context:
            self.load_text("id: first\nid: second\n")

        self.assertIn("duplicate key 'id'", str(context.exception))
        self.assertIn("line 2", str(context.exception))

    def test_load_yaml_rejects_duplicate_nested_key(self):
        with self.assertRaises(validator.DuplicateKeyError):
            self.load_text("equipment:\n  camera_id: first\n  camera_id: second\n")

    def test_load_yaml_normalizes_dates(self):
        self.assertEqual(self.load_text("date: 2024-01-02\n"), {"date": "2024-01-02"})

    def test_load_yaml_rejects_recursive_aliases(self):
        with self.assertRaises(validator.RecursiveAliasError):
            self.load_text("items: &items\n  - *items\n")

    def test_load_yaml_rejects_duplicate_merge_keys(self):
        with self.assertRaises(validator.DuplicateKeyError):
            self.load_text(
                "base: &base\n"
                "  value: first\n"
                "merged:\n"
                "  <<: *base\n"
                "  <<: *base\n"
            )


class GlobalIntegrityTests(unittest.TestCase):
    def test_valid_documents_pass(self):
        self.assertEqual(validator.validate_global_integrity(valid_documents()), [])

    def test_duplicate_ids_and_slugs_report_first_file(self):
        documents = valid_documents()
        documents.append(
            document(
                "objects",
                "z-duplicate.yml",
                {"id": "target", "slug": "target", "domain": "deep_sky"},
            )
        )

        issues = validator.validate_global_integrity(documents)

        self.assertEqual(
            {issue.code for issue in issues if issue.path.name == "z-duplicate.yml"},
            {"duplicate-id", "duplicate-slug"},
        )
        self.assertTrue(
            all(
                "target.yml" in issue.message
                for issue in issues
                if issue.path.name == "z-duplicate.yml"
            )
        )

    def test_missing_references_are_reported_with_field_paths(self):
        documents = valid_documents()
        image = copy.deepcopy(documents[-1].data)
        image["location_id"] = "missing-location"
        image["targets"] = ["missing-target"]
        image["equipment"]["scope_id"] = "missing-scope"
        image["acquisitions"][0]["filter_id"] = "missing-filter"
        documents[-1] = document("images", "image.yml", image)

        issues = validator.validate_global_integrity(documents)
        missing = [issue for issue in issues if issue.code == "missing-reference"]

        self.assertEqual(len(missing), 4)
        self.assertEqual(
            {validator.format_location(issue.location) for issue in missing},
            {
                "location_id",
                "targets[0]",
                "equipment.scope_id",
                "acquisitions[0].filter_id",
            },
        )

    def test_wrong_equipment_kinds_are_reported(self):
        documents = valid_documents()
        image = copy.deepcopy(documents[-1].data)
        image["equipment"]["camera_id"] = "scope"
        image["acquisitions"][0]["filter_id"] = "camera"
        documents[-1] = document("images", "image.yml", image)

        issues = validator.validate_global_integrity(documents)
        wrong_kind = [issue for issue in issues if issue.code == "wrong-equipment-kind"]

        self.assertEqual(len(wrong_kind), 2)
        self.assertEqual(
            {validator.format_location(issue.location) for issue in wrong_kind},
            {"equipment.camera_id", "acquisitions[0].filter_id"},
        )

    def test_target_domain_must_match_capture_mode(self):
        documents = valid_documents()
        documents[0] = document(
            "objects",
            "target.yml",
            {"id": "target", "slug": "target", "domain": "solar_system"},
        )

        issues = validator.validate_global_integrity(documents)

        self.assertIn("target-domain-mismatch", {issue.code for issue in issues})

    def test_invalid_target_domain_is_left_to_schema_validation(self):
        documents = valid_documents()
        documents[0] = document(
            "objects",
            "target.yml",
            {"id": "target", "slug": "target", "domain": "invalid"},
        )

        issues = validator.validate_global_integrity(documents)

        self.assertNotIn("target-domain-mismatch", {issue.code for issue in issues})

    def test_invalid_equipment_kind_is_left_to_schema_validation(self):
        documents = valid_documents()
        documents[3] = document(
            "equipment",
            "camera.yml",
            {"id": "camera", "slug": "camera", "kind": "invalid"},
        )

        issues = validator.validate_global_integrity(documents)

        self.assertNotIn("wrong-equipment-kind", {issue.code for issue in issues})

    def test_image_id_date_must_match_image_date(self):
        documents = valid_documents()
        image = copy.deepcopy(documents[-1].data)
        image["id"] = "img_20240103_target"
        documents[-1] = document("images", "image.yml", image)

        issues = validator.validate_global_integrity(documents)

        self.assertIn("image-id-date-mismatch", {issue.code for issue in issues})

    def test_latest_acquisition_must_match_image_date(self):
        documents = valid_documents()
        image = copy.deepcopy(documents[-1].data)
        image["acquisitions"] = [{"date": "2024-01-01"}]
        documents[-1] = document("images", "image.yml", image)

        issues = validator.validate_global_integrity(documents)

        self.assertIn("acquisition-date-mismatch", {issue.code for issue in issues})

    def test_invalid_acquisition_date_is_left_to_schema_validation(self):
        documents = valid_documents()
        image = copy.deepcopy(documents[-1].data)
        image["acquisitions"] = [{"date": "not-a-date"}]
        documents[-1] = document("images", "image.yml", image)

        issues = validator.validate_global_integrity(documents)

        self.assertNotIn("acquisition-date-mismatch", {issue.code for issue in issues})

    def test_invalid_image_date_does_not_hide_invalid_image_id(self):
        documents = valid_documents()
        image = copy.deepcopy(documents[-1].data)
        image["id"] = "invalid"
        image["date"] = "not-a-date"
        documents[-1] = document("images", "image.yml", image)

        issues = validator.validate_global_integrity(documents)

        self.assertIn("invalid-image-id", {issue.code for issue in issues})

    def test_non_schema_date_format_is_left_to_schema_validation(self):
        documents = valid_documents()
        image = copy.deepcopy(documents[-1].data)
        image["date"] = "20240102"
        documents[-1] = document("images", "image.yml", image)

        issues = validator.validate_global_integrity(documents)

        self.assertNotIn("acquisition-date-mismatch", {issue.code for issue in issues})

    def test_missing_image_id_does_not_hide_acquisition_mismatch(self):
        documents = valid_documents()
        image = copy.deepcopy(documents[-1].data)
        image.pop("id")
        image["acquisitions"] = [{"date": "2024-01-01"}]
        documents[-1] = document("images", "image.yml", image)

        issues = validator.validate_global_integrity(documents)

        self.assertIn("acquisition-date-mismatch", {issue.code for issue in issues})

    def test_solar_image_without_acquisitions_is_allowed(self):
        documents = valid_documents()
        documents[0] = document(
            "objects",
            "target.yml",
            {"id": "target", "slug": "target", "domain": "solar_system"},
        )
        image = copy.deepcopy(documents[-1].data)
        image["capture_mode"] = "solar_system"
        image.pop("acquisitions")
        documents[-1] = document("images", "image.yml", image)

        self.assertEqual(validator.validate_global_integrity(documents), [])

    def test_repeated_acquisition_dates_are_allowed(self):
        documents = valid_documents()
        image = copy.deepcopy(documents[-1].data)
        image["acquisitions"] = [
            {"date": "2024-01-02"},
            {"date": "2024-01-02"},
        ]
        documents[-1] = document("images", "image.yml", image)

        self.assertEqual(validator.validate_global_integrity(documents), [])


class ValidationRunnerTests(unittest.TestCase):
    def create_schemas(self, root: Path) -> Path:
        schemas = root / "schemas"
        schemas.mkdir()
        schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}
        for schema_name in validator.SCHEMA_MAP.values():
            (schemas / schema_name).write_text(json.dumps(schema), encoding="utf-8")
        return schemas

    def create_content(self, root: Path) -> Path:
        content = root / "content"
        for section in validator.SCHEMA_MAP:
            directory = content / section
            directory.mkdir(parents=True)
            (directory / "entry.yml").write_text("{}\n", encoding="utf-8")
        return content

    def test_missing_required_directory_is_an_error(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            schemas = self.create_schemas(root)
            content = root / "content"
            content.mkdir()

            report = validator.run_validation(content, schemas)

        self.assertIn("missing-content-directory", {issue.code for issue in report.errors})

    def test_malformed_yaml_is_reported_without_aborting(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            schemas = self.create_schemas(root)
            content = self.create_content(root)
            (content / "images" / "entry.yml").write_text("id: [\n", encoding="utf-8")

            report = validator.run_validation(content, schemas)

        self.assertIn("yaml-syntax", {issue.code for issue in report.errors})
        self.assertEqual(report.checked_files, 4)

    def test_invalid_schema_is_reported(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            schemas = self.create_schemas(root)
            content = self.create_content(root)
            (schemas / "image.schema.json").write_text("{", encoding="utf-8")

            report = validator.run_validation(content, schemas)

        self.assertIn("invalid-schema", {issue.code for issue in report.errors})

    def test_invalid_utf8_is_reported(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            schemas = self.create_schemas(root)
            content = self.create_content(root)
            (content / "images" / "entry.yml").write_bytes(b"id: \xff\n")

            report = validator.run_validation(content, schemas)

        self.assertIn("invalid-encoding", {issue.code for issue in report.errors})

    def test_schema_invalid_target_does_not_create_missing_reference(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            schemas = self.create_schemas(root)
            content = self.create_content(root)
            object_schema = {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "required": ["title"],
            }
            (schemas / "object.schema.json").write_text(
                json.dumps(object_schema), encoding="utf-8"
            )
            (content / "objects" / "entry.yml").write_text(
                "id: target\ndomain: deep_sky\n", encoding="utf-8"
            )
            (content / "images" / "entry.yml").write_text(
                "id: img_20240101_target\n"
                "date: 2024-01-01\n"
                "capture_mode: deep_sky\n"
                "targets:\n"
                "  - target\n",
                encoding="utf-8",
            )

            report = validator.run_validation(content, schemas)

        self.assertIn("schema", {issue.code for issue in report.errors})
        self.assertNotIn("missing-reference", {issue.code for issue in report.errors})

    def test_main_uses_zero_and_one_exit_codes(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            schemas = self.create_schemas(root)
            content = self.create_content(root)
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                success = validator.main(
                    ["--content-dir", str(content), "--schemas-dir", str(schemas)]
                )

            (content / "images" / "entry.yml").write_text("id: first\nid: second\n", encoding="utf-8")
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                failure = validator.main(
                    ["--content-dir", str(content), "--schemas-dir", str(schemas)]
                )

        self.assertEqual(success, 0)
        self.assertEqual(failure, 1)
        self.assertIn("duplicate-yaml-key", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
