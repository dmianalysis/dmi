"""Release summaries across a month with no published DMI observation.

October 2026 has no DMI: its 12-month CPI base month, October 2025, was
never published. The November 2026 summary is therefore compared with
September 2026. It must say so, report the difference since September
rather than a monthly change, leave the ``*_delta_mom`` facts empty and
apply none of the monthly thresholds. Consecutive releases must be
summarised exactly as before.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from scripts.compute_dmi import (
    THRESHOLDS,
    build_release_summary,
    load_unavailable_periods,
)

ROOT = Path(__file__).resolve().parents[1]
RELEASES = ROOT / "data" / "outputs" / "releases.json"
SCHEMA = json.loads((ROOT / "schemas" / "releases.schema.json").read_text())

MOM_FIELDS = {"median_delta_mom", "stress_delta_mom", "spread_delta_mom",
              "tilt_delta_mom", "unemployment_delta_mom"}
SINCE_FIELDS = {"median_delta_since_comparison", "stress_delta_since_comparison",
                "spread_delta_since_comparison", "tilt_delta_since_comparison",
                "unemployment_delta_since_comparison"}
NONCONSECUTIVE_FIELDS = SINCE_FIELDS | {
    "comparison_release_id", "comparison_months_elapsed", "unavailable_release_ids"}

#: Words the monthly classifier produces. None may describe a change
#: across a gap, and none may imply a one-month movement.
THRESHOLD_WORDS = ("slightly", "modestly", "sharply", "materially", "noticeably",
                   "edged", "little changed", "prior month", "month-over-month",
                   "month over month", "continued", "remained")

LABELS = {"2026-09": "September 2026", "2026-11": "November 2026",
          "2026-01": "January 2026", "2025-12": "December 2025",
          "2025-11": "November 2025", "2026-08": "August 2026"}


def release(release_id, median=7.0, stress=7.2, spread=0.30, tilt=-0.10, unemployment=4.2):
    return {
        "release_id": release_id,
        "data_through_label": LABELS[release_id],
        "metrics": {
            "dmi_median": median, "dmi_stress": stress,
            "income_pressure_spread": spread, "income_pressure_tilt": tilt,
            "most_pressured_group": "Q5", "least_pressured_group": "Q1",
            "unemployment": unemployment,
        },
    }


class _FactsValidator:
    """Validate summary_facts inside a real 3.1.0 manifest.

    The committed manifest is re-declared as 3.1.0 and the facts are put
    on a copy of its newest entry, so they are checked by the same
    version-aware rules releases.json is.
    """

    def __init__(self, version="3.1.0"):
        self.version = version
        self.validator = Draft202012Validator(SCHEMA)
        self.base = json.loads(RELEASES.read_text())

    def _doc(self, facts):
        doc = json.loads(json.dumps(self.base))
        doc["schema_version"] = self.version
        doc["releases"][0]["summary_facts"] = facts
        return doc

    def is_valid(self, facts):
        return self.validator.is_valid(self._doc(facts))

    def iter_errors(self, facts):
        return self.validator.iter_errors(self._doc(facts))


def entry_validator(version="3.1.0"):
    return _FactsValidator(version)


class TestConsecutiveUnchanged(unittest.TestCase):

    def test_every_published_summary_reproduces(self):
        releases = sorted(json.loads(RELEASES.read_text())["releases"],
                          key=lambda r: r["release_id"])
        self.assertGreaterEqual(len(releases), 10)
        for prior, current in zip([None] + releases[:-1], releases):
            with self.subTest(release=current["release_id"]):
                facts, text = build_release_summary(
                    {k: current[k] for k in ("release_id", "data_through_label", "metrics")},
                    prior,
                )
                self.assertEqual(text, current["summary"])
                self.assertEqual(facts, current["summary_facts"])
                self.assertEqual(list(facts), list(current["summary_facts"]))

    def test_consecutive_uses_monthly_fields_and_thresholds(self):
        facts, text = build_release_summary(
            release("2026-01", median=7.40, spread=0.40),
            release("2025-12", median=7.00, spread=0.30),
        )
        self.assertTrue(MOM_FIELDS <= set(facts))
        self.assertFalse(NONCONSECUTIVE_FIELDS & set(facts))
        self.assertEqual(facts["overall_direction"], "rose_sharply")
        self.assertIn("rose sharply in January 2026", text)
        self.assertIn("from the prior month", text)
        self.assertEqual(entry_validator().is_valid(facts), True)

    def test_year_boundary_is_consecutive(self):
        facts, _ = build_release_summary(release("2026-01"), release("2025-12"))
        self.assertNotEqual(facts["overall_direction"], "nonconsecutive")


class TestNonconsecutive(unittest.TestCase):

    def summarise(self, **current):
        return build_release_summary(
            release("2026-11", **current),
            release("2026-09", median=7.00, stress=7.20, spread=0.30, unemployment=4.2),
        )

    def test_names_the_comparison_period_and_reports_the_difference(self):
        facts, text = self.summarise(median=7.40, spread=0.25, unemployment=4.4)
        self.assertTrue(text.startswith(
            "Compared with September 2026, the most recent earlier published release, "
            "the November 2026 DMI Median increased by 0.40 points, to 7.40."), text)
        self.assertIn("the Income Pressure Spread narrowed by 0.05 points, to 0.25", text)
        self.assertIn("Unemployment was 4.4%, compared with 4.2% in September 2026.", text)
        self.assertIn("These are differences over two months, not a monthly change.", text)

    def test_notes_october_2026_and_why(self):
        _, text = self.summarise()
        self.assertIn(
            "October 2026 has no published DMI observation because the required "
            "official CPI comparison data are unavailable.", text)

    def test_uses_distinct_fields_and_no_monthly_fields(self):
        facts, _ = self.summarise(median=6.90)
        self.assertFalse(MOM_FIELDS & set(facts))
        self.assertTrue(NONCONSECUTIVE_FIELDS <= set(facts))
        self.assertNotIn("spread_direction", facts)
        self.assertEqual(facts["overall_direction"], "nonconsecutive")
        self.assertEqual(facts["comparison_release_id"], "2026-09")
        self.assertEqual(facts["comparison_months_elapsed"], 2)
        self.assertEqual(facts["unavailable_release_ids"], ["2026-10"])
        self.assertAlmostEqual(facts["median_delta_since_comparison"], -0.10)
        self.assertTrue(entry_validator().is_valid(facts),
                        list(entry_validator().iter_errors(facts)))

    def test_no_threshold_classification_at_any_size(self):
        """From far below the smallest threshold to far above the largest."""
        for delta in (0.0, 0.001, -0.04, 0.10, -0.25, 0.5, -3.0):
            for spread_delta in (0.0, 0.01, -0.05, 0.2):
                with self.subTest(delta=delta, spread_delta=spread_delta):
                    facts, text = self.summarise(median=7.0 + delta,
                                                 spread=0.30 + spread_delta)
                    lowered = text.lower()
                    for word in THRESHOLD_WORDS:
                        self.assertNotIn(word, lowered)
                    for value in facts.values():
                        if not isinstance(value, str):
                            continue
                        self.assertNotIn(value, {
                            "little_changed", "edged_up", "edged_down",
                            "rose_modestly", "fell_modestly", "rose_sharply",
                            "fell_sharply"})

    def test_direction_words_follow_the_sign(self):
        _, up = self.summarise(median=7.25, spread=0.35)
        _, down = self.summarise(median=6.75, spread=0.25)
        _, flat = self.summarise(median=7.001, spread=0.302)
        self.assertIn("DMI Median increased by 0.25 points", up)
        self.assertIn("Spread widened by 0.05 points", up)
        self.assertIn("DMI Median decreased by 0.25 points", down)
        self.assertIn("Spread narrowed by 0.05 points", down)
        self.assertIn("DMI Median was unchanged at 7.00, to two decimal places", flat)
        self.assertIn("Spread was unchanged at 0.30, to two decimal places", flat)

    def test_no_value_is_attributed_to_the_missing_month(self):
        """No interpolation, annualisation or per-month split."""
        facts, text = self.summarise(median=7.40)
        self.assertNotIn("0.20", text)      # half of the 0.40 difference
        self.assertNotIn("per month", text.lower())
        self.assertNotIn("annual", text.lower())
        # Only the two endpoints and their difference appear.
        self.assertEqual(set(re.findall(r"\d+\.\d+", text)),
                         {"0.40", "7.40", "0.30", "4.2"})
        for key in facts:
            self.assertNotIn("2026-10", key)

    def test_longer_gap_lists_every_missing_month(self):
        facts, text = build_release_summary(release("2026-11"), release("2026-08"),
                                            unavailable_reasons={})
        self.assertEqual(facts["comparison_months_elapsed"], 3)
        self.assertEqual(facts["unavailable_release_ids"], ["2026-09", "2026-10"])
        self.assertIn("September 2026 has no published DMI observation.", text)
        self.assertIn("October 2026 has no published DMI observation.", text)
        self.assertIn("differences over three months", text)

    def test_gap_across_a_year_boundary(self):
        facts, text = build_release_summary(release("2026-01"), release("2025-11"),
                                            unavailable_reasons={})
        self.assertEqual(facts["unavailable_release_ids"], ["2025-12"])
        self.assertIn("Compared with November 2025", text)

    def test_october_2026_is_documented_in_the_registry(self):
        reasons = load_unavailable_periods()
        self.assertEqual(reasons["2026-10"],
                         "the required official CPI comparison data are unavailable")
        published = {r["release_id"] for r in json.loads(RELEASES.read_text())["releases"]}
        self.assertFalse(set(reasons) & published,
                         "a period documented as unavailable is published")


class TestSchemaKeepsTheFieldsApart(unittest.TestCase):

    def test_monthly_and_nonconsecutive_facts_are_both_valid(self):
        validator = entry_validator()
        mom, _ = build_release_summary(release("2026-09"), release("2026-08"))
        gap, _ = build_release_summary(release("2026-11"), release("2026-09"))
        self.assertTrue(validator.is_valid(mom))
        self.assertTrue(validator.is_valid(gap))

    def test_schema_rejects_an_unknown_fact(self):
        """Non-vacuity: the facts schema still forbids undeclared fields."""
        gap, _ = build_release_summary(release("2026-11"), release("2026-09"))
        gap["median_delta_two_month"] = 0.1
        self.assertFalse(entry_validator().is_valid(gap))

    def test_schema_rejects_a_one_month_comparison_count(self):
        gap, _ = build_release_summary(release("2026-11"), release("2026-09"))
        gap["comparison_months_elapsed"] = 1
        self.assertFalse(entry_validator().is_valid(gap))


if __name__ == "__main__":
    unittest.main()
