#!/usr/bin/env python3
"""End-to-end validation against the authoritative BLS extracts.

Covers prompt section 14 "Validation targets". These assertions are the only
ones that exercise the real Consumer Expenditure files, so they are skipped
unless those files are present. The files are multi-hundred-megabyte BLS
publications and are never committed to this repository; see
``docs/research/DETAILED_INFLATION_SUBSTRATE.md`` for how to obtain them.

Attribution: source data are published by the U.S. Bureau of Labor Statistics.
"""

from __future__ import annotations

import unittest

from tests.detailed_inflation_fixtures import (
    EXTERNAL_SOURCES,
    external_sources_available,
)

from dmi_research.detailed_inflation.audit import EXPECTED_BASELINES, run_audit
from dmi_research.detailed_inflation.taxonomy import MappingStatus

#: Section 14 states the shares "to within rounding". A twentieth of a
#: percentage point is far tighter than a shift caused by a real basis or
#: concordance change, and looser than float noise.
SHARE_TOLERANCE_PCT = 0.05


@unittest.skipUnless(
    external_sources_available(),
    "Authoritative BLS CE extracts are not present; see the research README.",
)
class TestMilestone1Baselines(unittest.TestCase):
    result = None

    @classmethod
    def setUpClass(cls):
        cls.result = run_audit(
            series_path=EXTERNAL_SOURCES["series"],
            data_path=EXTERNAL_SOURCES["data"],
            items_path=EXTERNAL_SOURCES["items"],
            aspects_path=EXTERNAL_SOURCES["aspects"],
        )

    @property
    def summary(self) -> dict:
        return type(self).result.summary

    def test_active_ucc_count_is_337(self):
        self.assertEqual(
            self.summary["active_ucc_count"],
            EXPECTED_BASELINES["active_ucc_count"],
        )

    def test_the_basis_is_identical_across_all_six_populations(self):
        basis = type(self).result.basis
        populations = sorted({e.population for e in basis.entries})
        self.assertEqual(len(populations), 6)
        universes = {
            population: frozenset(
                e.ucc for e in basis.for_population(population)
            )
            for population in populations
        }
        self.assertEqual(len(set(universes.values())), 1)

    def test_parent_reconciliation_passes_within_publication_rounding(self):
        recon = self.summary["reconciliation"]
        self.assertTrue(recon["passed"], recon["failures"])
        self.assertEqual(recon["checks"], 24)

    def test_mapping_expenditure_shares_match_section_14(self):
        derived = self.summary["mapping_expenditure_share_pct"]
        for key, expected in EXPECTED_BASELINES["expenditure_share_pct"].items():
            with self.subTest(status=key):
                self.assertAlmostEqual(
                    derived[key], expected, delta=SHARE_TOLERANCE_PCT
                )

    def test_no_cross_node_multi_map_cases_exist(self):
        self.assertFalse(self.summary["cross_node_multi_map_found"])
        self.assertEqual(
            self.summary["exceptions_by_reason"]["CROSS_NODE_MULTI_MAP"][
                "ucc_count"
            ],
            0,
        )

    def test_the_five_multi_same_node_cases_are_exactly_those_in_section_10(self):
        cases = {case["ucc"] for case in self.summary["multi_same_node_cases"]}
        self.assertEqual(
            cases, {"270102", "470111", "470113", "480100", "490100"}
        )

    def test_high_rse_expenditure_shares_match_section_14(self):
        derived = self.summary["high_rse_expenditure_share_pct"]
        expected_all = EXPECTED_BASELINES["high_rse_expenditure_share_pct"]
        for population, expected in expected_all.items():
            with self.subTest(population=population):
                self.assertAlmostEqual(
                    derived[population], expected, delta=SHARE_TOLERANCE_PCT
                )

    def test_high_rse_burden_falls_hardest_on_the_lowest_quintile(self):
        derived = self.summary["high_rse_expenditure_share_pct"]
        self.assertGreater(derived["Q1"], derived["Q5"])
        self.assertGreater(derived["Q1"], derived["All Consumer Units"])

    def test_section_11_exception_cases_all_appear_in_the_ledger(self):
        ledger_uccs = {
            entry.ucc for entry in type(self).result.summary["_ledger"]
        }
        for ucc in (
            "190903",
            "190904",
            "200900",
            "450351",
            "470311",
            "510110",
            "510901",
            "510902",
            "520110",
            "850300",
            "950024",
        ):
            with self.subTest(ucc=ucc):
                self.assertIn(ucc, ledger_uccs)

    def test_suppression_is_reported_as_missing_and_never_zero_filled(self):
        missing = self.summary["missing_data"]
        aggregate = missing["missing_aggregate_by_population"]
        rse = missing["missing_rse_by_population"]
        self.assertEqual(set(aggregate), set(rse))
        for population, count in aggregate.items():
            with self.subTest(population=population):
                self.assertGreater(count, 0)
                # BLS suppresses the aggregate and its RSE together.
                self.assertEqual(count, rse[population])

    def test_no_ucc_is_left_without_a_mapping_status(self):
        for mapping in type(self).result.mappings:
            with self.subTest(ucc=mapping.ucc):
                self.assertIsInstance(mapping.status, MappingStatus)

    def test_milestone_1_assigns_no_transformed_or_out_of_scope_status(self):
        assigned = {m.status for m in type(self).result.mappings}
        self.assertNotIn(MappingStatus.TRANSFORMED, assigned)
        self.assertNotIn(MappingStatus.OUT_OF_SCOPE, assigned)


if __name__ == "__main__":
    unittest.main()
