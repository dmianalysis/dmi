#!/usr/bin/env python3
"""RSE-audit tests for the Detailed Inflation Substrate, Milestone 1.

Covers prompt section 15 "RSE":
24.99 is not high-RSE; 25.00 is high-RSE; a missing RSE is reported as
missing, not zero; and high-RSE shares are computed from expenditure amounts,
not from UCC counts.
"""

from __future__ import annotations

import unittest

from tests.test_detailed_inflation_mapping import basis_entry

from dmi_research.detailed_inflation.rse import (
    COMBINED_DOMAIN_LABEL,
    HIGH_RSE_THRESHOLD,
    build_rse_audit,
    is_high_rse,
)


class TestThreshold(unittest.TestCase):
    def test_threshold_is_25(self):
        self.assertEqual(HIGH_RSE_THRESHOLD, 25.0)

    def test_24_99_is_not_high_rse(self):
        self.assertFalse(is_high_rse(24.99))

    def test_25_00_is_high_rse(self):
        self.assertTrue(is_high_rse(25.00))

    def test_the_boundary_is_inclusive(self):
        self.assertTrue(is_high_rse(HIGH_RSE_THRESHOLD))
        self.assertFalse(is_high_rse(HIGH_RSE_THRESHOLD - 0.01))

    def test_missing_rse_is_not_high_rse(self):
        self.assertFalse(is_high_rse(None))

    def test_zero_rse_is_not_high_rse(self):
        self.assertFalse(is_high_rse(0.0))

    def test_threshold_is_configurable_without_changing_the_rule(self):
        self.assertTrue(is_high_rse(30.0, threshold=30.0))
        self.assertFalse(is_high_rse(29.99, threshold=30.0))


class TestMissingIsNotZero(unittest.TestCase):
    def setUp(self):
        self.entries = [
            basis_entry("010119", aggregate=100.0, rse=5.0),
            basis_entry("020219", aggregate=None, rse=None),
            basis_entry("030319", aggregate=200.0, rse=40.0),
        ]
        self.summary = next(
            s
            for s in build_rse_audit(self.entries)
            if s.subcategory_code == COMBINED_DOMAIN_LABEL
        )

    def test_missing_rse_is_counted_separately(self):
        self.assertEqual(self.summary.missing_rse_count, 1)

    def test_missing_rse_is_not_counted_as_high(self):
        self.assertEqual(self.summary.high_rse_ucc_count, 1)

    def test_missing_rse_is_not_counted_as_low(self):
        """A missing RSE must not be silently absorbed into the low bucket."""
        low = (
            self.summary.active_ucc_count
            - self.summary.high_rse_ucc_count
            - self.summary.missing_rse_count
        )
        self.assertEqual(low, 1)

    def test_missing_aggregate_is_counted_separately(self):
        self.assertEqual(self.summary.missing_aggregate_count, 1)

    def test_suppressed_aggregate_does_not_inflate_the_denominator(self):
        self.assertEqual(self.summary.total_aggregate_expenditure, 300.0)


class TestSharesAreExpenditureWeighted(unittest.TestCase):
    """One large low-RSE item and many tiny high-RSE ones.

    A count-weighted share would report 75%; the expenditure-weighted share is
    3%. The two are deliberately far apart so a regression cannot pass.
    """

    def setUp(self):
        self.entries = [
            basis_entry("100000", aggregate=970.0, rse=1.0),
            basis_entry("200000", aggregate=10.0, rse=25.0),
            basis_entry("300000", aggregate=10.0, rse=60.0),
            basis_entry("400000", aggregate=10.0, rse=99.0),
        ]
        self.summary = next(
            s
            for s in build_rse_audit(self.entries)
            if s.subcategory_code == COMBINED_DOMAIN_LABEL
        )

    def test_high_rse_count_is_three_of_four(self):
        self.assertEqual(self.summary.high_rse_ucc_count, 3)
        self.assertEqual(self.summary.active_ucc_count, 4)

    def test_share_is_expenditure_weighted_not_count_weighted(self):
        self.assertAlmostEqual(
            self.summary.high_rse_expenditure_share_pct, 3.0
        )
        self.assertNotAlmostEqual(
            self.summary.high_rse_expenditure_share_pct, 75.0
        )

    def test_high_rse_expenditure_is_the_sum_of_flagged_amounts(self):
        self.assertEqual(self.summary.high_rse_aggregate_expenditure, 30.0)

    def test_high_rse_records_are_flagged_not_removed(self):
        self.assertEqual(self.summary.total_aggregate_expenditure, 1000.0)


class TestAuditShape(unittest.TestCase):
    def setUp(self):
        self.entries = [
            basis_entry(
                "010119",
                population="All Consumer Units",
                characteristics_code="01",
                subcategory_code="FOODTOTL",
                domain_label="Food",
                aggregate=100.0,
                rse=30.0,
            ),
            basis_entry(
                "470111",
                population="All Consumer Units",
                characteristics_code="01",
                subcategory_code="TRANS",
                domain_label="Transportation",
                aggregate=300.0,
                rse=1.0,
            ),
            basis_entry(
                "010119",
                population="Q1",
                characteristics_code="02",
                subcategory_code="FOODTOTL",
                domain_label="Food",
                aggregate=50.0,
                rse=30.0,
            ),
            basis_entry(
                "470111",
                population="Q1",
                characteristics_code="02",
                subcategory_code="TRANS",
                domain_label="Transportation",
                aggregate=50.0,
                rse=40.0,
            ),
        ]
        self.summaries = build_rse_audit(self.entries)

    def test_each_population_gets_per_domain_and_combined_rows(self):
        for population in ("All Consumer Units", "Q1"):
            scoped = [s for s in self.summaries if s.population == population]
            self.assertEqual(
                {s.subcategory_code for s in scoped},
                {"FOODTOTL", "TRANS", COMBINED_DOMAIN_LABEL},
            )

    def test_combined_row_covers_every_domain(self):
        combined = next(
            s
            for s in self.summaries
            if s.population == "All Consumer Units"
            and s.subcategory_code == COMBINED_DOMAIN_LABEL
        )
        self.assertEqual(combined.active_ucc_count, 2)
        self.assertEqual(combined.total_aggregate_expenditure, 400.0)
        self.assertAlmostEqual(combined.high_rse_expenditure_share_pct, 25.0)

    def test_shares_are_reported_per_population_not_pooled(self):
        shares = {
            s.population: s.high_rse_expenditure_share_pct
            for s in self.summaries
            if s.subcategory_code == COMBINED_DOMAIN_LABEL
        }
        self.assertAlmostEqual(shares["All Consumer Units"], 25.0)
        self.assertAlmostEqual(shares["Q1"], 100.0)

    def test_a_population_with_no_published_expenditure_reports_zero_not_nan(self):
        summaries = build_rse_audit(
            [basis_entry("010119", aggregate=None, rse=None)]
        )
        combined = next(
            s for s in summaries if s.subcategory_code == COMBINED_DOMAIN_LABEL
        )
        self.assertEqual(combined.total_aggregate_expenditure, 0.0)
        self.assertEqual(combined.high_rse_expenditure_share_pct, 0.0)


if __name__ == "__main__":
    unittest.main()
