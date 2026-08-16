#!/usr/bin/env python3
"""Source-parsing tests for the Detailed Inflation Substrate, Milestone 1.

Covers prompt section 15 "Source parsing":
whitespace normalization, numeric-UCC detection, 2024-active-series logic,
quintile population identification, and annual-period handling.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.detailed_inflation_fixtures import write_minimal_sources

from dmi_research.detailed_inflation.sources import (
    ANNUAL_PERIOD,
    ASPECT_AGGREGATE,
    ASPECT_RSE,
    POPULATIONS,
    is_numeric_ucc,
    load_aspects,
    load_data,
    load_items,
    load_series,
    select_target_series,
)


class TestWhitespaceNormalization(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.paths = write_minimal_sources(Path(self._tmp.name))
        self.addCleanup(self._tmp.cleanup)

    def test_series_fields_are_stripped(self):
        records = load_series(self.paths["series"])
        record = next(r for r in records if r.item_code == "010119")
        self.assertEqual(record.series_id, "CXU010119LB0101M")
        self.assertEqual(record.category_code, "EXPEND")
        self.assertEqual(record.subcategory_code, "FOODTOTL")
        self.assertEqual(record.item_code, "010119")

    def test_item_codes_are_stripped_so_joins_are_exact(self):
        items = load_items(self.paths["items"])
        self.assertIn(("FOODTOTL", "010119"), items)
        self.assertEqual(
            items[("FOODTOTL", "010119")].item_text,
            "Flour and prepared flour mixes",
        )

    def test_padded_data_values_parse(self):
        values = load_data(self.paths["data"])
        self.assertAlmostEqual(values["CXU010119LB0101M"].value, 12.5)


class TestNumericUccDetection(unittest.TestCase):
    def test_six_digit_codes_are_uccs(self):
        for code in ("010119", "470111", "000000"):
            self.assertTrue(is_numeric_ucc(code), code)

    def test_descriptive_aggregates_are_not_uccs(self):
        for code in ("FOODTOTL", "FOODHOME", "BAKERY", "TRANS", "ALCBEVG"):
            self.assertFalse(is_numeric_ucc(code), code)

    def test_wrong_length_is_not_a_ucc(self):
        for code in ("01011", "0101190", "", "01011a"):
            self.assertFalse(is_numeric_ucc(code), code)


class TestTargetSeriesSelection(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.paths = write_minimal_sources(Path(self._tmp.name))
        self.series = load_series(self.paths["series"])
        self.addCleanup(self._tmp.cleanup)

    def test_selection_is_metadata_driven_not_an_id_list(self):
        selected = select_target_series(self.series)
        self.assertTrue(selected)
        for record in selected:
            self.assertEqual(record.category_code, "EXPEND")
            self.assertEqual(record.demographics_code, "LB01")
            self.assertIn(record.subcategory_code, {"FOODTOTL", "TRANS"})

    def test_series_inactive_in_2024_are_excluded(self):
        selected = select_target_series(self.series, year=2024)
        self.assertNotIn("019999", {r.item_code for r in selected})

    def test_series_active_in_2019_are_included_for_2019(self):
        selected = select_target_series(self.series, year=2019)
        self.assertIn("019999", {r.item_code for r in selected})

    def test_other_ce_domains_are_excluded(self):
        selected = select_target_series(self.series)
        self.assertNotIn("APPAREL", {r.subcategory_code for r in selected})

    def test_other_demographic_sets_are_excluded(self):
        selected = select_target_series(self.series)
        self.assertEqual({r.demographics_code for r in selected}, {"LB01"})

    def test_quintile_populations_are_identified(self):
        selected = select_target_series(self.series)
        populations = {r.population for r in selected}
        self.assertEqual(populations, {"All Consumer Units", "Q1"})

    def test_population_codes_cover_all_cu_plus_five_quintiles(self):
        self.assertEqual(
            POPULATIONS,
            {
                "01": "All Consumer Units",
                "02": "Q1",
                "03": "Q2",
                "04": "Q3",
                "05": "Q4",
                "06": "Q5",
            },
        )

    def test_empty_selection_raises_rather_than_returning_nothing(self):
        with self.assertRaises(ValueError):
            select_target_series(self.series, subcategory_codes=["NOSUCH"])


class TestAnnualPeriodHandling(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.paths = write_minimal_sources(Path(self._tmp.name))
        self.addCleanup(self._tmp.cleanup)

    def test_only_annual_2024_aspects_are_loaded(self):
        aspects = load_aspects(self.paths["aspects"], year=2024)
        for record in aspects.values():
            self.assertEqual(record.year, 2024)
            self.assertEqual(record.period, ANNUAL_PERIOD)
        self.assertNotIn(
            999999.0, {record.value for record in aspects.values()}
        )
        self.assertNotIn(
            888888.0, {record.value for record in aspects.values()}
        )

    def test_only_requested_aspect_types_are_loaded(self):
        aspects = load_aspects(
            self.paths["aspects"], aspect_types=(ASPECT_AGGREGATE,)
        )
        self.assertEqual(
            {aspect_type for _, aspect_type in aspects}, {ASPECT_AGGREGATE}
        )

    def test_monthly_data_rows_are_excluded(self):
        values = load_data(self.paths["data"], year=2024)
        for record in values.values():
            self.assertEqual(record.period, ANNUAL_PERIOD)
            self.assertEqual(record.year, 2024)


class TestSuppressionMarkers(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.paths = write_minimal_sources(Path(self._tmp.name))
        self.addCleanup(self._tmp.cleanup)

    def test_suppressed_values_load_as_none_not_zero(self):
        aspects = load_aspects(self.paths["aspects"])
        suppressed = aspects[("CXU020219LB0102M", ASPECT_AGGREGATE)]
        self.assertIsNone(suppressed.value)
        self.assertIsNotNone(
            aspects[("CXU010119LB0102M", ASPECT_RSE)].value,
            "a published RSE must not be treated as suppressed",
        )

    def test_missing_source_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_series(Path(self._tmp.name) / "does-not-exist.tsv")


if __name__ == "__main__":
    unittest.main()
