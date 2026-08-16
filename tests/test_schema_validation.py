#!/usr/bin/env python3
"""Regression tests: published outputs validate against their JSON schemas.

Covers:
- schemas/releases.schema.json                <- data/outputs/releases.json
                                             <- data/outputs/latest.json
- schemas/dmi_output.schema.json              <- every dmi_release_YYYY-MM[_slack_plus].json
- schemas/specifications.schema.json          <- data/outputs/specifications.json

The releases and specifications schemas are 3.0.0 / 0.3.0 respectively after
Phase 4 (Core removal + honest baseline-only historical entries). The
dmi_output schema was rewritten in Phase 4 to match the output actually
produced by scripts/compute_dmi.py.

Historical experimental artifacts (dmi_release_*_u6.json,
dmi_release_*_with_ci.json) are intentionally excluded from validation:
they predate the current schema and are not part of the published contract.
"""

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = ROOT / "schemas"
OUTPUTS_DIR = ROOT / "data" / "outputs"


def _load(path: Path):
    with path.open() as f:
        return json.load(f)


def _validator(schema_filename: str) -> Draft202012Validator:
    schema = _load(SCHEMAS_DIR / schema_filename)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _format_errors(errors: list) -> str:
    lines = []
    for err in errors:
        lines.append(f"  path={list(err.absolute_path)}: {err.message}")
    return "\n".join(lines)


class TestSchemasEnforceConstVersion(unittest.TestCase):
    """The public schemas must pin schema_version with `const`, not `pattern`.

    Regex acceptance would let a mispublished manifest advertising an
    unsupported version (e.g. `2.0.0`) sneak through validation. `const`
    fails closed.
    """

    def test_releases_schema_pins_version_with_const(self):
        schema = _load(SCHEMAS_DIR / "releases.schema.json")
        prop = schema["properties"]["schema_version"]
        self.assertEqual(prop.get("const"), "3.0.0",
            "releases.schema.json must pin schema_version with const=3.0.0")
        self.assertNotIn("pattern", prop,
            "releases.schema.json schema_version must not use pattern")

    def test_specifications_schema_pins_version_with_const(self):
        schema = _load(SCHEMAS_DIR / "specifications.schema.json")
        prop = schema["properties"]["schema_version"]
        self.assertEqual(prop.get("const"), "0.3.0",
            "specifications.schema.json must pin schema_version with const=0.3.0")
        self.assertNotIn("pattern", prop,
            "specifications.schema.json schema_version must not use pattern")


class TestReleasesManifestSchema(unittest.TestCase):
    def setUp(self):
        self.validator = _validator("releases.schema.json")

    def test_releases_json_validates(self):
        instance = _load(OUTPUTS_DIR / "releases.json")
        errors = sorted(self.validator.iter_errors(instance),
                        key=lambda e: list(e.absolute_path))
        if errors:
            self.fail(f"releases.json fails schema:\n{_format_errors(errors)}")

    def test_latest_json_validates(self):
        instance = _load(OUTPUTS_DIR / "latest.json")
        errors = sorted(self.validator.iter_errors(instance),
                        key=lambda e: list(e.absolute_path))
        if errors:
            self.fail(f"latest.json fails schema:\n{_format_errors(errors)}")

    def test_no_release_entry_advertises_core(self):
        for name in ("releases.json", "latest.json"):
            instance = _load(OUTPUTS_DIR / name)
            for release in instance["releases"]:
                self.assertNotIn(
                    "core", release.get("spec_urls", {}),
                    f"{name}: {release['release_id']} still advertises Core spec_urls",
                )

    def test_baseline_only_historical_entries_have_no_slack_plus(self):
        """Historical (2025-12..2026-02) entries never had Slack-Plus artifacts;
        they must not falsely advertise them."""
        historical = {"2025-12", "2026-01", "2026-02"}
        instance = _load(OUTPUTS_DIR / "releases.json")
        for release in instance["releases"]:
            if release["release_id"] in historical:
                self.assertNotIn(
                    "slack_plus", release.get("spec_urls", {}),
                    f"{release['release_id']}: historical baseline-only "
                    f"release must not advertise slack_plus",
                )

    def test_schema_version_is_exactly_3_0_0(self):
        """v0.1.12 pins the releases schema to 3.0.0 (const, not regex)."""
        from scripts.schema_versions import RELEASES_SCHEMA_VERSION

        self.assertEqual(RELEASES_SCHEMA_VERSION, "3.0.0",
            "central RELEASES_SCHEMA_VERSION constant drifted from 3.0.0")
        for name in ("releases.json", "latest.json"):
            instance = _load(OUTPUTS_DIR / name)
            self.assertEqual(
                instance["schema_version"], "3.0.0",
                f"{name}: schema_version must be exactly '3.0.0' "
                f"(got {instance['schema_version']!r})",
            )

    def test_release_note_is_top_level_field(self):
        """release_note must be a top-level field of each release entry."""
        for name in ("releases.json", "latest.json"):
            instance = _load(OUTPUTS_DIR / name)
            for release in instance["releases"]:
                self.assertIn(
                    "release_note", release,
                    f"{name}: {release['release_id']} missing top-level "
                    f"release_note",
                )
                self.assertTrue(
                    release["release_note"].startswith("/data/outputs/releases/"),
                    f"{name}: {release['release_id']} release_note "
                    f"{release['release_note']!r} does not look like a "
                    f"release-note URL",
                )

    def test_no_spec_urls_block_carries_release_note(self):
        """Under schema 3.0.0 no spec_urls block may nest a release_note key."""
        for name in ("releases.json", "latest.json"):
            instance = _load(OUTPUTS_DIR / name)
            for release in instance["releases"]:
                for spec_id, block in release.get("spec_urls", {}).items():
                    self.assertNotIn(
                        "release_note", block,
                        f"{name}: {release['release_id']}.{spec_id} still "
                        f"nests a release_note key",
                    )


class TestDmiOutputSchema(unittest.TestCase):
    def setUp(self):
        self.validator = _validator("dmi_output.schema.json")

    @classmethod
    def _standard_release_files(cls) -> list[Path]:
        """All raw releases matching the current output contract.

        Excludes experimental variants (_u6, _with_ci) that predate the
        current schema and are not part of the published contract.
        """
        files = []
        for p in sorted(OUTPUTS_DIR.glob("dmi_release_*.json")):
            stem = p.stem.replace("dmi_release_", "")
            # Only accept YYYY-MM or YYYY-MM_slack_plus
            parts = stem.split("_", 1)
            if len(parts) == 1:
                pass  # bare YYYY-MM
            elif len(parts) == 2 and parts[1] == "slack_plus":
                pass  # YYYY-MM_slack_plus
            else:
                continue  # skip experimental variants
            files.append(p)
        return files

    def test_at_least_one_release_present(self):
        self.assertGreater(len(self._standard_release_files()), 0)

    def test_all_standard_release_files_validate(self):
        failures = {}
        for path in self._standard_release_files():
            instance = _load(path)
            errors = sorted(self.validator.iter_errors(instance),
                            key=lambda e: list(e.absolute_path))
            if errors:
                failures[path.name] = _format_errors(errors)
        if failures:
            report = "\n\n".join(f"{name}:\n{errs}" for name, errs in failures.items())
            self.fail(f"{len(failures)} release file(s) fail dmi_output schema:\n\n{report}")


class TestSpecificationsManifestSchema(unittest.TestCase):
    def setUp(self):
        self.validator = _validator("specifications.schema.json")

    def test_specifications_json_validates(self):
        instance = _load(OUTPUTS_DIR / "specifications.json")
        errors = sorted(self.validator.iter_errors(instance),
                        key=lambda e: list(e.absolute_path))
        if errors:
            self.fail(f"specifications.json fails schema:\n{_format_errors(errors)}")

    def test_no_core_spec_id_present(self):
        instance = _load(OUTPUTS_DIR / "specifications.json")
        spec_ids = {s["spec_id"] for s in instance["specifications"]}
        self.assertNotIn("core", spec_ids,
            "specifications.json still contains a Core entry")

    def test_schema_version_is_exactly_0_3_0(self):
        """v0.1.12 pins the specifications schema to 0.3.0 (const, not regex)."""
        from scripts.schema_versions import SPECIFICATIONS_SCHEMA_VERSION

        self.assertEqual(SPECIFICATIONS_SCHEMA_VERSION, "0.3.0",
            "central SPECIFICATIONS_SCHEMA_VERSION constant drifted from 0.3.0")
        instance = _load(OUTPUTS_DIR / "specifications.json")
        self.assertEqual(
            instance["schema_version"], "0.3.0",
            f"specifications.json schema_version must be exactly '0.3.0' "
            f"(got {instance['schema_version']!r})",
        )


if __name__ == "__main__":
    unittest.main()
