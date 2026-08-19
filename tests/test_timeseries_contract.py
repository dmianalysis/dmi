#!/usr/bin/env python3
"""Regression coverage for the public-timeseries contract (§7).

Public-timeseries invariants:

- The shipped `data/outputs/published/dmi_timeseries.json` MUST validate
  against `schemas/dmi_timeseries_schema.json`.
- The schema MUST NOT allow the withdrawn `CORE_CPI` spec (nor the
  Slack-Plus `U6` variant) in `metadata.specification`. The public
  timeseries is Baseline-only.
- The shipped instance MUST NOT carry any observation whose fields
  imply the withdrawn Core spec (there is no observation-level spec
  field today; this test freezes that contract).
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft7Validator

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schemas" / "dmi_timeseries_schema.json"
INSTANCE_PATH = ROOT / "data" / "outputs" / "published" / "dmi_timeseries.json"


class TestShippedInstanceValidatesAgainstSchema(unittest.TestCase):

    def test_dmi_timeseries_validates(self):
        schema = json.loads(SCHEMA_PATH.read_text())
        Draft7Validator.check_schema(schema)
        instance = json.loads(INSTANCE_PATH.read_text())
        validator = Draft7Validator(schema)
        errors = sorted(
            validator.iter_errors(instance),
            key=lambda e: list(e.absolute_path),
        )
        if errors:
            summaries = [
                f"path={list(e.absolute_path)[:5]}: {e.message[:200]}"
                for e in errors[:10]
            ]
            self.fail(
                f"{INSTANCE_PATH.name} fails its schema in {len(errors)} "
                f"place(s):\n  " + "\n  ".join(summaries)
            )


class TestSchemaLocksOutRetiredSpecs(unittest.TestCase):

    def setUp(self):
        self.schema = json.loads(SCHEMA_PATH.read_text())

    def test_metadata_specification_is_baseline_const(self):
        spec = (
            self.schema["properties"]["metadata"]["properties"]["specification"]
        )
        # The tightened contract pins the spec to a single legal value via
        # JSON-Schema `const`, so an accidental `CORE_CPI` or `U6` string
        # would fail validation.
        self.assertEqual(
            spec.get("const"), "BASELINE",
            "§7: metadata.specification must be pinned to const 'BASELINE'.",
        )
        # And the old permissive enum must be gone entirely.
        self.assertNotIn(
            "enum", spec,
            "§7: the CORE_CPI-permitting enum must be removed.",
        )

    def test_schema_text_forbids_core_cpi_and_u6(self):
        # Defense in depth: raw text of the schema must not still list
        # CORE_CPI or U6 as legal specifications anywhere. Comments and
        # descriptions may still MENTION Core in the negative (e.g. to
        # document the withdrawal); those mentions include the word
        # "withdrawn" or "NOT" nearby, so we only fail on the exact
        # capitalised enum tokens.
        text = SCHEMA_PATH.read_text()
        self.assertNotIn('"CORE_CPI"', text, "§7: CORE_CPI must not appear as a legal value.")
        self.assertNotIn('"U6"', text, "§7: U6 must not appear as a legal value.")

    def test_top_level_forbids_additional_properties(self):
        self.assertIs(
            self.schema.get("additionalProperties"), False,
            "§7: top-level additionalProperties must be false to prevent silent drift.",
        )

    def test_observation_permits_weights_vintage_but_forbids_extras(self):
        obs = self.schema["definitions"]["observation"]
        self.assertIs(obs.get("additionalProperties"), False)
        self.assertIn("weights_vintage", obs["properties"])
        self.assertEqual(obs["properties"]["weights_vintage"]["type"], "integer")


class TestShippedInstanceIsBaselineOnly(unittest.TestCase):

    def test_no_observation_carries_a_core_or_slack_plus_label(self):
        instance = json.loads(INSTANCE_PATH.read_text())
        for obs in instance["observations"]:
            for key, value in obs.items():
                text = f"{key}={value!r}"
                self.assertNotIn(
                    "core", text.lower(),
                    f"§7: observation carries a Core-labeled field: {text}",
                )
                self.assertNotIn(
                    "slack_plus", text.lower(),
                    f"§7: observation carries a Slack-Plus label: {text}",
                )
                self.assertNotIn(
                    "u6", text.lower(),
                    f"§7: observation carries a U-6 label: {text}",
                )

    def test_metadata_does_not_advertise_a_retired_spec(self):
        instance = json.loads(INSTANCE_PATH.read_text())
        spec = instance.get("metadata", {}).get("specification")
        # The current writer does not emit this field; if a future writer
        # ever does, it must be exactly BASELINE.
        if spec is not None:
            self.assertEqual(spec, "BASELINE")


if __name__ == "__main__":
    unittest.main()
