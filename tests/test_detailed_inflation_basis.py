#!/usr/bin/env python3
"""Accounting-basis tests for the Detailed Inflation Substrate, Milestone 1.

Covers prompt section 15 "Accounting basis":
parent/child aggregates are not double-counted; selected active numeric UCCs
reconcile to parent aggregates; duplicate UCC inclusion fails.
"""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tests.detailed_inflation_fixtures import write_minimal_sources

from dmi_research.detailed_inflation.basis import (
    BLS_AGGREGATE_ROUNDING_UNIT,
    DuplicateUccError,
    ReconciliationResult,
    build_basis,
    find_parent_series,
)
from dmi_research.detailed_inflation.sources import (
    load_aspects,
    load_data,
    load_items,
    load_series,
    select_target_series,
)


class BasisTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = write_minimal_sources(Path(self._tmp.name))
        self.all_series = load_series(self.paths["series"])
        self.target_series = select_target_series(self.all_series)
        self.items = load_items(self.paths["items"])
        self.aspects = load_aspects(self.paths["aspects"])
        self.data = load_data(self.paths["data"])
        self.basis = build_basis(
            self.target_series, self.items, self.aspects, self.data
        )

    def reconciliation(self, population: str, subcategory: str):
        return next(
            r
            for r in self.basis.reconciliations
            if r.population == population and r.subcategory_code == subcategory
        )


class TestNoDoubleCounting(BasisTestCase):
    def test_descriptive_parents_are_excluded_from_the_basis(self):
        uccs = {entry.ucc for entry in self.basis.entries}
        for descriptive in ("FOODTOTL", "FOODHOME", "TRANS"):
            self.assertNotIn(descriptive, uccs)

    def test_basis_contains_only_numeric_uccs(self):
        for entry in self.basis.entries:
            self.assertRegex(entry.ucc, r"^[0-9]{6}$")

    def test_intermediate_parent_would_double_the_sum_if_included(self):
        """FOODHOME carries the same 300 as the FOODTOTL root.

        The fixture places a descriptive intermediate aggregate alongside its
        numeric children precisely so this test fails loudly if the selection
        rule ever admits descriptive rows.
        """
        recon = self.reconciliation("All Consumer Units", "FOODTOTL")
        self.assertEqual(recon.sum_active_ucc_aggregate, 300.0)
        self.assertEqual(recon.published_parent_aggregate, 300.0)
        self.assertEqual(recon.active_ucc_count, 2)

    def test_each_ucc_appears_once_per_population(self):
        for population in {e.population for e in self.basis.entries}:
            uccs = [e.ucc for e in self.basis.for_population(population)]
            self.assertEqual(len(uccs), len(set(uccs)), population)

    def test_the_same_ucc_may_appear_across_populations(self):
        appearances = [e for e in self.basis.entries if e.ucc == "010119"]
        self.assertEqual(
            {e.population for e in appearances}, {"All Consumer Units", "Q1"}
        )


class TestParentReconciliation(BasisTestCase):
    def test_every_domain_population_pair_reconciles(self):
        self.assertTrue(self.basis.reconciliations)
        self.assertEqual(self.basis.failed_reconciliations(), [])

    def test_parent_is_the_series_whose_item_code_is_its_subcategory(self):
        parent = find_parent_series(self.target_series, "FOODTOTL", "01")
        self.assertIsNotNone(parent)
        self.assertEqual(parent.series_id, "CXUFOODTOTLLB0101M")
        self.assertEqual(parent.item_code, parent.subcategory_code)

    def test_suppressed_leaf_is_excluded_from_the_sum_not_zero_filled(self):
        recon = self.reconciliation("Q1", "FOODTOTL")
        self.assertEqual(recon.active_ucc_count, 2)
        self.assertEqual(recon.missing_aggregate_count, 1)
        self.assertEqual(recon.published_leaf_count, 1)
        self.assertEqual(recon.sum_active_ucc_aggregate, 40.0)
        self.assertEqual(recon.absolute_difference, 0.0)

    def test_percent_difference_is_reported_alongside_absolute(self):
        recon = self.reconciliation("All Consumer Units", "TRANS")
        self.assertEqual(recon.absolute_difference, 0.0)
        self.assertEqual(recon.percent_difference, 0.0)


class TestRoundingBound(unittest.TestCase):
    """The gate is the worst case of publication rounding, not a percentage.

    A one-unit residual is 0.0001% of a large parent and 0.015% of a small
    one, so a single percentage threshold cannot separate rounding from error.
    """

    @staticmethod
    def result(
        *, leaves: int, missing: int = 0, summed: float, parent: float
    ) -> ReconciliationResult:
        return ReconciliationResult(
            subcategory_code="ALCBEVG",
            domain_label="Alcoholic beverages",
            population="Q1",
            active_ucc_count=leaves,
            missing_aggregate_count=missing,
            sum_active_ucc_aggregate=summed,
            published_parent_aggregate=parent,
            parent_series_id="CXUALCBEVGLB0102M",
        )

    def test_bound_is_half_a_unit_per_published_figure(self):
        recon = self.result(leaves=5, summed=6602.0, parent=6603.0)
        # five published leaves plus one published parent
        self.assertEqual(recon.rounding_bound(), 3.0)

    def test_suppressed_leaves_do_not_widen_the_bound(self):
        recon = self.result(leaves=5, missing=2, summed=6602.0, parent=6603.0)
        self.assertEqual(recon.published_leaf_count, 3)
        self.assertEqual(recon.rounding_bound(), 2.0)

    def test_one_unit_residual_on_a_small_base_is_rounding_not_error(self):
        recon = self.result(leaves=5, summed=6602.0, parent=6603.0)
        self.assertTrue(recon.within_rounding())
        # The same residual is far outside any 0.01% percentage tolerance.
        self.assertGreater(abs(recon.percent_difference), 0.01)

    def test_residual_beyond_the_bound_fails(self):
        recon = self.result(leaves=5, summed=6607.0, parent=6603.0)
        self.assertEqual(recon.absolute_difference, 4.0)
        self.assertGreater(abs(recon.absolute_difference), recon.rounding_bound())
        self.assertFalse(recon.within_rounding())

    def test_a_double_counted_leaf_exceeds_the_bound_by_orders_of_magnitude(self):
        recon = self.result(leaves=5, summed=6602.0 + 1200.0, parent=6603.0)
        self.assertFalse(recon.within_rounding())

    def test_bound_scales_with_the_rounding_unit(self):
        recon = self.result(leaves=5, summed=6602.0, parent=6603.0)
        self.assertEqual(recon.rounding_bound(BLS_AGGREGATE_ROUNDING_UNIT), 3.0)
        self.assertEqual(recon.rounding_bound(0.0), 0.0)

    def test_missing_parent_cannot_silently_pass(self):
        recon = ReconciliationResult(
            subcategory_code="ALCBEVG",
            domain_label="Alcoholic beverages",
            population="Q1",
            active_ucc_count=5,
            missing_aggregate_count=0,
            sum_active_ucc_aggregate=6602.0,
            published_parent_aggregate=None,
            parent_series_id=None,
        )
        self.assertIsNone(recon.absolute_difference)
        self.assertFalse(recon.within_rounding())


class TestDuplicateUccRejection(BasisTestCase):
    def test_duplicate_ucc_in_one_population_raises(self):
        duplicated = list(self.target_series)
        original = next(
            r
            for r in duplicated
            if r.item_code == "010119" and r.characteristics_code == "01"
        )
        # A second series row for the same UCC and population, as a mangled
        # source extract or a botched pre-filter would produce.
        duplicated.append(replace(original, series_id=original.series_id + "X"))

        with self.assertRaises(DuplicateUccError) as caught:
            build_basis(duplicated, self.items, self.aspects, self.data)
        self.assertIn("010119", str(caught.exception))

    def test_same_ucc_in_a_different_population_is_not_a_duplicate(self):
        uccs = [
            e.ucc for e in self.basis.entries if e.characteristics_code == "02"
        ]
        self.assertIn("010119", uccs)
        self.assertEqual(len(uccs), len(set(uccs)))

    def test_ucc_absent_from_cx_item_raises_rather_than_being_dropped(self):
        items = dict(self.items)
        del items[("FOODTOTL", "010119")]
        with self.assertRaises(KeyError) as caught:
            build_basis(self.target_series, items, self.aspects, self.data)
        self.assertIn("010119", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
