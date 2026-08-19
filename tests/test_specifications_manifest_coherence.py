#!/usr/bin/env python3
"""Regression tests: specifications.json must be internally coherent.

These tests would have caught the mixed-value state introduced by merge
commit 45e2682 (see docs/repair/SPECIFICATIONS_JSON_INVESTIGATION.md).

The tests operate on a synthesised in-memory manifest to lock in the
invariants; they are intentionally decoupled from any specific reference
period so they remain valid across future releases.

Invariants enforced (all mandatory):
  I1. `reference_period` matches the period segment of every
      `specifications[*].release_json` path.
  I2. Each spec's `metrics.slack` equals the referenced release's
      `dmi_by_group[0].slack`.
  I3. Each spec's `metrics.slack_measure` equals the referenced release's
      `parameters.slack_measure`.
  I4. Each spec's numeric summary metrics (`dmi_median`, `dmi_stress`,
      `income_pressure_spread`, `income_pressure_tilt`,
      `most_pressured_group`, `least_pressured_group`) equal the
      referenced release's `summary_metrics` values.
"""

import copy
import json
import re
import tempfile
import unittest
from pathlib import Path

from scripts.build_specifications_manifest import build_specifications_manifest


NUMERIC_METRIC_KEYS = (
    "dmi_median",
    "dmi_stress",
    "income_pressure_spread",
    "income_pressure_tilt",
    "most_pressured_group",
    "least_pressured_group",
)

PERIOD_IN_PATH = re.compile(r"dmi_release_(\d{4}-\d{2})(?:_[a-z_]+)?\.json$")


def _release(slack: float, slack_measure: str, dmi_median: float) -> dict:
    """Minimal release-file dict conforming to the fields the manifest reads."""
    return {
        "parameters": {
            "slack_measure": slack_measure,
            "weights_year": 2023,
        },
        "dmi_by_group": [{"slack": slack}],
        "summary_metrics": {
            "dmi_median": dmi_median,
            "dmi_stress": dmi_median + 0.05,
            "income_pressure_spread": 0.18,
            "income_pressure_tilt": -0.17,
            "most_pressured_group": "Q4",
            "least_pressured_group": "Q1",
        },
    }


def _consistent_releases(reference_period: str) -> dict:
    return {
        "baseline": _release(slack=4.1, slack_measure="u3", dmi_median=7.52),
        "slack_plus": _release(slack=7.9, slack_measure="u6", dmi_median=11.32),
    }


def _period_from_release_json(release_json: str) -> str:
    match = PERIOD_IN_PATH.search(release_json)
    if not match:
        raise AssertionError(f"release_json path missing period: {release_json}")
    return match.group(1)


def _assert_manifest_coherent(testcase: unittest.TestCase, manifest: dict,
                              releases_by_spec: dict) -> None:
    ref_period = manifest["reference_period"]
    for entry in manifest["specifications"]:
        spec_id = entry["spec_id"]
        path_period = _period_from_release_json(entry["release_json"])
        # I1
        testcase.assertEqual(path_period, ref_period,
            f"{spec_id}: release_json period {path_period!r} != "
            f"reference_period {ref_period!r}")
        source = releases_by_spec[spec_id]
        metrics = entry["metrics"]
        # I2
        testcase.assertEqual(metrics["slack"], source["dmi_by_group"][0]["slack"],
            f"{spec_id}: metrics.slack != source dmi_by_group[0].slack")
        # I3
        testcase.assertEqual(metrics["slack_measure"], source["parameters"]["slack_measure"],
            f"{spec_id}: metrics.slack_measure != source parameters.slack_measure")
        # I4
        for key in NUMERIC_METRIC_KEYS:
            testcase.assertEqual(metrics[key], source["summary_metrics"][key],
                f"{spec_id}: metrics.{key} != source summary_metrics.{key}")


class TestSpecificationsManifestCoherence(unittest.TestCase):
    def test_freshly_built_manifest_is_coherent(self):
        releases = _consistent_releases("2026-07")
        manifest = build_specifications_manifest(
            reference_period="2026-07",
            output_dir=Path("data/outputs"),
            releases_by_spec=releases,
        )
        _assert_manifest_coherent(self, manifest, releases)

    def test_detector_flags_stale_reference_period(self):
        """Simulates the 45e2682 defect: 2026-07 metrics with 2026-06 reference_period."""
        releases = _consistent_releases("2026-07")
        manifest = build_specifications_manifest(
            reference_period="2026-07",
            output_dir=Path("data/outputs"),
            releases_by_spec=releases,
        )
        manifest = copy.deepcopy(manifest)
        manifest["reference_period"] = "2026-06"  # simulate stale merge outcome
        with self.assertRaises(AssertionError):
            _assert_manifest_coherent(self, manifest, releases)

    def test_detector_flags_stale_slack_value(self):
        """Simulates the 45e2682 defect: stale slack=4.2 grafted onto a 2026-07 baseline."""
        releases = _consistent_releases("2026-07")
        manifest = build_specifications_manifest(
            reference_period="2026-07",
            output_dir=Path("data/outputs"),
            releases_by_spec=releases,
        )
        manifest = copy.deepcopy(manifest)
        # Corrupt the manifest's baseline slack to a stale June value:
        for entry in manifest["specifications"]:
            if entry["spec_id"] == "baseline":
                entry["metrics"]["slack"] = 4.2
        with self.assertRaises(AssertionError):
            _assert_manifest_coherent(self, manifest, releases)

    def test_detector_flags_release_json_period_mismatch(self):
        """Simulates a release_json path pointing at a different period than reference_period."""
        releases = _consistent_releases("2026-07")
        manifest = build_specifications_manifest(
            reference_period="2026-07",
            output_dir=Path("data/outputs"),
            releases_by_spec=releases,
        )
        manifest = copy.deepcopy(manifest)
        for entry in manifest["specifications"]:
            if entry["spec_id"] == "baseline":
                entry["release_json"] = "/data/outputs/dmi_release_2026-06.json"
        with self.assertRaises(AssertionError):
            _assert_manifest_coherent(self, manifest, releases)

    def test_writer_reads_slack_from_referenced_release(self):
        """Guards against future regressions where the writer stops sourcing slack from the release."""
        releases = _consistent_releases("2026-07")
        # Change the source-of-truth slack; the manifest must follow.
        releases["baseline"]["dmi_by_group"][0]["slack"] = 4.05
        manifest = build_specifications_manifest(
            reference_period="2026-07",
            output_dir=Path("data/outputs"),
            releases_by_spec=releases,
        )
        for entry in manifest["specifications"]:
            if entry["spec_id"] == "baseline":
                self.assertEqual(entry["metrics"]["slack"], 4.05)


if __name__ == "__main__":
    unittest.main()
