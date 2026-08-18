#!/usr/bin/env python3
"""Tests for deferred release-note generation (Baseline + Slack-Plus)."""

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
        ],
        "robustness_assessment": {
            "pressure_tilt_sign_consistent": True,
            "stress_group_consistent": True,
            "notes": [],
        },
    }


class TestReleaseNoteHtml(unittest.TestCase):
    def test_renders_two_spec_table_without_warning_when_consistent(self):
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
        self.assertNotIn("Core (U-3, core CPI)", html)
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


def baseline_only_specifications_manifest():
    """A per-period manifest for a baseline-only (historical) release."""
    return {
        "reference_period": "2025-12",
        "specifications": [
            {
                "spec_id": "baseline",
                "metrics": {
                    "dmi_median": 7.06,
                    "dmi_stress": 7.18,
                    "slack": 4.4,
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


class TestReleaseNoteHtmlNoFabrication(unittest.TestCase):
    """§4: the generator must never invent rows for specs not supplied."""

    def test_baseline_only_manifest_renders_no_slack_plus_or_core(self):
        html = generate_release_note_html(
            reference_period="2025-12",
            metrics={
                "dmi_median": 7.06,
                "dmi_stress": 7.18,
                "income_pressure_spread": 0.22,
                "income_pressure_tilt": 0.22,
                "most_pressured_group": "Q1",
                "least_pressured_group": "Q5",
                "unemployment": 4.4,
            },
            summary="Baseline-only historical period.",
            specifications=baseline_only_specifications_manifest(),
            published_at="2026-01-15",
        )
        self.assertNotIn("Slack+", html)
        self.assertNotIn("Core", html)
        self.assertNotIn("core CPI", html)
        # Single-spec periods should be titled "Specification", not
        # "Robustness across specifications", and must omit the warning.
        self.assertIn("<h2>Specification</h2>", html)
        self.assertNotIn("Robustness across specifications", html)
        # The CSS `.robustness-warning` class is always defined in the
        # <style> block; the rendered alert element itself must be absent.
        self.assertNotIn('robustness-warning" role="alert', html)

    def test_h1_uses_period_only_not_spec_suffix(self):
        html = generate_release_note_html(
            reference_period="2026-07",
            metrics=BASELINE_METRICS,
            specifications=specifications_manifest(),
        )
        self.assertIn("<h1>DMI Release: 2026-07</h1>", html)
        self.assertNotIn("2026-07-baseline", html)
        self.assertNotIn("2026-07-slack_plus", html)


class TestOnDiskReleaseNotes(unittest.TestCase):
    """§4: the files actually shipped under data/outputs/releases/ must
    match the repaired generator contract for every advertised release."""

    HISTORICAL = {"2025-12", "2026-01", "2026-02"}

    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parent.parent
        cls.releases_dir = root / "data" / "outputs" / "releases"
        cls.releases = json.loads(
            (root / "data" / "outputs" / "releases.json").read_text()
        )["releases"]

    def test_no_release_note_contains_withdrawn_core_spec(self):
        for release in self.releases:
            path = self.releases_dir / f"{release['release_id']}.html"
            with self.subTest(release=release["release_id"]):
                text = path.read_text()
                self.assertNotIn("Core (U-3, core CPI)", text)
                self.assertNotIn("core CPI", text)

    def test_historical_notes_have_no_slack_plus_row(self):
        for release in self.releases:
            rid = release["release_id"]
            if rid not in self.HISTORICAL:
                continue
            path = self.releases_dir / f"{rid}.html"
            with self.subTest(release=rid):
                self.assertNotIn("Slack+", path.read_text())

    def test_modern_notes_have_both_baseline_and_slack_plus_rows(self):
        for release in self.releases:
            rid = release["release_id"]
            if rid in self.HISTORICAL:
                continue
            path = self.releases_dir / f"{rid}.html"
            with self.subTest(release=rid):
                text = path.read_text()
                self.assertIn("Baseline (U-3, headline CPI)", text)
                self.assertIn("Slack+ (U-6, headline CPI)", text)

    def test_h1_titles_are_period_only(self):
        for release in self.releases:
            rid = release["release_id"]
            path = self.releases_dir / f"{rid}.html"
            with self.subTest(release=rid):
                self.assertIn(f"<h1>DMI Release: {rid}</h1>", path.read_text())


if __name__ == "__main__":
    unittest.main()
