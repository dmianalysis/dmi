#!/usr/bin/env python3
"""Tests for deferred three-spec release-note generation."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_specifications_manifest import metrics_from_release
from scripts.compute_dmi import generate_release_note_html
from scripts.compute_dmi_release import load_prior_release


BASELINE_METRICS = {
    "dmi_median": 8.56,
    "dmi_stress": 8.63,
    "income_pressure_spread": 0.20,
    "income_pressure_tilt": 0.10,
    "most_pressured_group": "Q1",
    "least_pressured_group": "Q5",
    "unemployment": 4.3,
}


def specifications_manifest():
    return {
        "reference_period": "2026-07",
        "specifications": [
            {
                "spec_id": "baseline",
                "metrics": {
                    "dmi_median": 8.56,
                    "dmi_stress": 8.63,
                    "slack": 4.3,
                    "slack_measure": "u3",
                },
            },
            {
                "spec_id": "slack_plus",
                "metrics": {
                    "dmi_median": 12.36,
                    "dmi_stress": 12.43,
                    "slack": 8.1,
                    "slack_measure": "u6",
                },
            },
            {
                "spec_id": "core",
                "metrics": {
                    "dmi_median": 8.56,
                    "dmi_stress": 8.63,
                    "slack": 4.3,
                    "slack_measure": "u3",
                },
            },
        ],
        "robustness_assessment": {
            "pressure_tilt_sign_consistent": True,
            "stress_group_consistent": True,
            "notes": [],
        },
    }


class TestReleaseNoteHtml(unittest.TestCase):
    def test_renders_three_spec_table_without_warning_when_consistent(self):
        html = generate_release_note_html(
            reference_period="2026-07",
            metrics=BASELINE_METRICS,
            summary="Summary text.",
            specifications=specifications_manifest(),
            published_at="2026-08-15",
        )

        self.assertIn("Robustness across specifications", html)
        self.assertIn("Baseline (U-3, headline CPI)", html)
        self.assertIn("Slack+ (U-6, headline CPI)", html)
        self.assertIn("Core (U-3, core CPI)", html)
        self.assertIn("12.36", html)
        self.assertIn("8.1% (U-6)", html)
        self.assertIn("Published:</strong> 2026-08-15", html)
        self.assertNotIn("robustness-warning\" role=\"alert", html)

    def test_renders_warning_when_either_robustness_flag_is_false(self):
        specifications = copy.deepcopy(specifications_manifest())
        specifications["robustness_assessment"][
            "stress_group_consistent"
        ] = False

        html = generate_release_note_html(
            reference_period="2026-07",
            metrics=BASELINE_METRICS,
            specifications=specifications,
        )

        self.assertIn("robustness-warning\" role=\"alert", html)
        self.assertIn("not consistent across all three specifications", html)

    def test_rejects_manifest_for_another_period(self):
        specifications = specifications_manifest()
        specifications["reference_period"] = "2026-06"
        with self.assertRaises(ValueError):
            generate_release_note_html(
                reference_period="2026-07",
                metrics=BASELINE_METRICS,
                specifications=specifications,
            )

    def test_specification_metrics_include_numeric_slack(self):
        release = {
            "parameters": {"slack_measure": "u6"},
            "dmi_by_group": [{"slack": 8.1}],
            "summary_metrics": {
                "dmi_median": 12.36,
                "dmi_stress": 12.43,
                "income_pressure_spread": 0.20,
                "income_pressure_tilt": 0.10,
                "most_pressured_group": "Q1",
                "least_pressured_group": "Q5",
            },
        }

        metrics = metrics_from_release(release)
        self.assertEqual(metrics["slack"], 8.1)
        self.assertEqual(metrics["slack_measure"], "u6")

    def test_prior_release_excludes_future_periods(self):
        manifest = {
            "releases": [
                {"release_id": "2026-06"},
                {"release_id": "2026-02"},
                {"release_id": "2026-01"},
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            releases_path = Path(temp_dir) / "releases.json"
            releases_path.write_text(json.dumps(manifest))
            prior = load_prior_release("2026-03", releases_path)

        self.assertEqual(prior["release_id"], "2026-02")


if __name__ == "__main__":
    unittest.main()
