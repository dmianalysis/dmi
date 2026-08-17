#!/usr/bin/env python3
"""Tests for the 2024 CE Interview PUMD / LB01 benchmark (Phase B, B16).

Three kinds of test live here and they are deliberately distinguishable.

*Unit tests* run on a synthetic consumer-unit universe small enough that every
expected number is derived by hand in the test itself rather than copied from a
run. They need no microdata and no external file.

*Mutation tests* break one methodological decision at a time - the quintile
rule, the weight variable, the annualization factor, the roster, the exclusion
of the four shelter UCCs - and assert that the break is detected. Each one
first asserts that the unmutated computation is correct, so the mutation is
shown to be the thing that moved the answer. A mutation test that would pass
against a broken implementation is worthless, and several of these fixtures
exist only to make the mutation and the truth differ.

*Artifact tests* read what the benchmark actually wrote and check the frozen
disciplines: the roster on disk still hashes to what the acceptance rule pins,
no threshold moved between the failed v0.1 run and the passing v0.2 run, no
amount was ever produced for 910104-910107, and nothing operational was
touched.

Integration tests against the real microdata skip cleanly when the PUMD
archive is absent, which is the normal case in CI. Everything else runs.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dmi_research.detailed_inflation import pumd  # noqa: E402
from dmi_research.detailed_inflation import pumd_benchmark as bench  # noqa: E402

# The Phase-A checkpoint. Phase B may not move it.
FROZEN_TAG = "dmi-detailed-inflation-v0.1-m2-corrected"
FROZEN_COMMIT = "e6402097eacd45c536a30a0ae9c9476fc2bfc76d"

SPEC_PATH = REPO_ROOT / "registry/research/pumd_lb01_benchmark_spec_v0_1.json"
OUTPUT_DIR = REPO_ROOT / "data/research/detailed_inflation/pumd_benchmark_2024"
SUPERSEDED_DIR = OUTPUT_DIR / "superseded" / "roster_v0_1"
MILESTONE_1 = REPO_ROOT / "data/research/detailed_inflation/audit_2024"
MILESTONE_2 = REPO_ROOT / "data/research/detailed_inflation/milestone_2"


# ==========================================================================
# Synthetic universe
# ==========================================================================
#
# Five consumer units, all interviewed in the middle of the year so every
# MO_SCOPE is 3 and the population weight is FINLWT21 * 3 / 12 = FINLWT21 / 4.
# Final weights are deliberately UNEQUAL and replicate weights are deliberately
# NOT proportional to them, because equal weights would make the "unweighted
# aggregation" and "wrong weight variable" mutations produce the right answer
# by accident.
#
#   unit  FINLWT21  income    quintile  WTREP*  cost(111111)  cost(222222)
#   U1        1000    10,000        Q1     500          10.0           0.5
#   U2        2000    40,000        Q2    2000          20.0           0.5
#   U3        3000    70,000        Q3    4500          30.0           0.5
#   U4        4000   120,000        Q4    4000          40.0           0.5
#   U5        5000   200,000        Q5   10000          50.0           0.5
#
# All-CU denominator      = 15000 / 4                      = 3750
# All-CU numerator 111111 = 1000*10 + ... + 5000*50        = 550000
# All-CU mean      111111 = 550000 / 3750                  = 146.666...
# Q1..Q5 means     111111 = 40, 80, 120, 160, 200
# All-CU mean      222222 = 0.5 * 15000 / 3750             = 2.0
#
# Every replicate carries the same per-unit multiplier, so all 44 replicate
# means coincide and the BRR standard error collapses to the distance between
# the replicate mean and the point estimate - a number the test can state.
#
#   replicate denominator = 21000 / 4                      = 5250
#   replicate numerator   = 500*10 + ... + 10000*50        = 840000
#   replicate mean        = 840000 / 5250                  = 160
#   standard error        = |160 - 146.666...|             = 13.333...

_SYNTHETIC = (
    ("U1", 1000.0, 10_000.0, 500.0, 10.0),
    ("U2", 2000.0, 40_000.0, 2000.0, 20.0),
    ("U3", 3000.0, 70_000.0, 4500.0, 30.0),
    ("U4", 4000.0, 120_000.0, 4000.0, 40.0),
    ("U5", 5000.0, 200_000.0, 10000.0, 50.0),
)

ALL_CU_MEAN = 550_000.0 / 3750.0
QUINTILE_MEANS = {"Q1": 40.0, "Q2": 80.0, "Q3": 120.0, "Q4": 160.0, "Q5": 200.0}
ALL_CU_STANDARD_ERROR = abs(840_000.0 / 5250.0 - ALL_CU_MEAN)
SMALL_UCC_MEAN = 2.0

LARGE_UCC = "111111"
SMALL_UCC = "222222"


def make_units() -> list[pumd.ConsumerUnit]:
    return [
        pumd.ConsumerUnit(
            newid=newid,
            quarter_role=pumd.MIDDLE_QUARTER,
            interview_month=5,
            final_weight=weight,
            income_before_taxes=income,
            replicate_weights=(replicate,) * pumd.REPLICATE_WEIGHT_COUNT,
        )
        for newid, weight, income, replicate, _cost in _SYNTHETIC
    ]


def make_records() -> list[pumd.ExpenditureRecord]:
    records = []
    for newid, _weight, _income, _replicate, cost in _SYNTHETIC:
        records.append(
            pumd.ExpenditureRecord(
                newid=newid,
                ucc=LARGE_UCC,
                cost=cost,
                reference_year=pumd.BENCHMARK_YEAR,
                reference_month=6,
            )
        )
        records.append(
            pumd.ExpenditureRecord(
                newid=newid,
                ucc=SMALL_UCC,
                cost=0.5,
                reference_year=pumd.BENCHMARK_YEAR,
                reference_month=6,
            )
        )
    return records


def make_skewed_units() -> list[pumd.ConsumerUnit]:
    """Ten units whose published-limit quintiles are nothing like sample fifths.

    Under the published 2024 lower limits six of these land in Q1, none in Q2
    and none in Q4. Under an unweighted fifths split exactly two land in each.
    The fixture exists so that the quintile mutation cannot pass by accident.
    """
    incomes = (
        5_000.0,
        8_000.0,
        12_000.0,
        20_000.0,
        25_000.0,
        28_000.0,
        60_000.0,
        70_000.0,
        200_000.0,
        300_000.0,
    )
    return [
        pumd.ConsumerUnit(
            newid=f"S{index}",
            quarter_role=pumd.MIDDLE_QUARTER,
            interview_month=5,
            final_weight=1000.0 + 100.0 * index,
            income_before_taxes=income,
            replicate_weights=(1000.0,) * pumd.REPLICATE_WEIGHT_COUNT,
        )
        for index, income in enumerate(incomes)
    ]


def make_roster() -> list[bench.RosterEntry]:
    return [
        bench.RosterEntry(
            ucc=LARGE_UCC,
            published_title="Synthetic large item",
            dmi_node="SYNTHETIC_NODE",
            domain_label="Housing",
            stub_title="Synthetic large item",
            annualization_factor=1,
            magnitude_stratum="LARGE",
            all_cu_published_mean=ALL_CU_MEAN,
            all_cu_published_rse=9.09,
            selection_rank_in_cell=1,
            cell_size=3,
        ),
        bench.RosterEntry(
            ucc=SMALL_UCC,
            published_title="Synthetic small item",
            dmi_node="SYNTHETIC_NODE",
            domain_label="Housing",
            stub_title="Synthetic small item",
            annualization_factor=1,
            magnitude_stratum="SMALL",
            all_cu_published_mean=SMALL_UCC_MEAN,
            all_cu_published_rse=None,
            selection_rank_in_cell=1,
            cell_size=3,
        ),
    ]


def make_basis_rows() -> list[dict[str, str]]:
    """Published cells that agree exactly with the synthetic PUMD estimates."""
    published = {
        LARGE_UCC: {
            "01": ALL_CU_MEAN,
            "02": QUINTILE_MEANS["Q1"],
            "03": QUINTILE_MEANS["Q2"],
            "04": QUINTILE_MEANS["Q3"],
            "05": QUINTILE_MEANS["Q4"],
            "06": QUINTILE_MEANS["Q5"],
        },
        SMALL_UCC: {code: SMALL_UCC_MEAN for code in bench.REQUIRED_CHARACTERISTICS},
    }
    rows = []
    for ucc, cells in published.items():
        for code, value in cells.items():
            rows.append(
                {
                    "ucc": ucc,
                    "characteristics_code": code,
                    "item_text": f"Synthetic {ucc}",
                    "domain_label": "Housing",
                    "mean_expenditure": repr(value),
                    "rse": "9.09" if ucc == LARGE_UCC else "",
                }
            )
    return rows


def make_spec(roster: list[bench.RosterEntry]) -> bench.BenchmarkSpec:
    """The real frozen thresholds, pinned to the synthetic roster."""
    rule = json.loads(SPEC_PATH.read_text(encoding="utf-8"))["acceptance_rule"]
    return bench.BenchmarkSpec(
        spec_version="synthetic",
        roster_version=bench.ROSTER_VERSION,
        roster_hash=bench.roster_hash(roster),
        estimand=bench.ESTIMAND,
        population_tolerance_pct=float(rule["population_tolerance_pct"]),
        quintile_population_tolerance_pct=float(
            rule["quintile_population_tolerance_pct"]
        ),
        median_abs_pct_error_max=float(rule["median_abs_pct_error_max"]),
        p75_abs_pct_error_max=float(rule["p75_abs_pct_error_max"]),
        p90_abs_pct_error_max=float(rule["p90_abs_pct_error_max"]),
        per_ucc_abs_pct_error_max=float(rule["per_ucc_abs_pct_error_max"]),
        per_ucc_pass_fraction_min=float(rule["per_ucc_pass_fraction_min"]),
        mean_signed_pct_error_abs_max=float(rule["mean_signed_pct_error_abs_max"]),
        small_value_absolute_floor=float(rule["small_value_absolute_floor"]),
        small_value_abs_diff_max=float(rule["small_value_abs_diff_max"]),
        excluded_from_calibration=bench.EXCLUDED_FROM_CALIBRATION,
    )


def make_population_comparisons() -> list[bench.PopulationComparison]:
    """Population comparison rows that agree exactly, so only UCC error moves."""
    return [
        bench.PopulationComparison(
            population=bench.LABSTAT_POPULATION_BY_CODE[code],
            characteristics_code=code,
            published_consumer_units_thousands=1.0,
            pumd_consumer_units_thousands=1.0,
            absolute_difference=0.0,
            percentage_difference=0.0,
            published_mean_income_before_taxes=50_000.0,
            pumd_mean_income_before_taxes=50_000.0,
            income_percentage_difference=0.0,
        )
        for code in bench.REQUIRED_CHARACTERISTICS
    ]


def fingerprint(root: Path) -> dict[str, str]:
    if not root.is_dir():
        return {}
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


# ==========================================================================
# Schema validation
# ==========================================================================


class TestSchemaValidation(unittest.TestCase):
    def test_stub_entry_rejects_a_ucc_that_is_not_six_digits(self):
        for bad in ("CONSUNIT", "12345", "1234567", "12a456"):
            with self.subTest(ucc=bad):
                with self.assertRaises(pumd.PumdSchemaError):
                    pumd.StubEntry(bad, "t", 1, "I", 1, "EXPEND")

    def test_stub_entry_rejects_an_undocumented_annualization_factor(self):
        for bad in (0, 2, 3, 12):
            with self.subTest(factor=bad):
                with self.assertRaises(pumd.PumdSchemaError):
                    pumd.StubEntry("111111", "t", 1, "I", bad, "EXPEND")

    def test_stub_entry_accepts_the_signed_asset_factors(self):
        # The 2024 files carry a sign to the left of the digit; eleven ASSETS
        # rows are negative. The magnitude is what annualizes.
        for factor in (1, 4, -1, -4):
            with self.subTest(factor=factor):
                entry = pumd.StubEntry("111111", "t", 1, "I", factor, "ASSETS")
                self.assertEqual(entry.factor, factor)

    def test_consumer_unit_rejects_an_out_of_range_interview_month(self):
        for month in (0, 13, -1):
            with self.subTest(month=month):
                with self.assertRaises(pumd.PumdSchemaError):
                    pumd.ConsumerUnit(
                        "U", pumd.MIDDLE_QUARTER, month, 1.0, 1.0, (0.0,) * 44
                    )

    def test_consumer_unit_requires_exactly_forty_four_replicate_weights(self):
        for count in (0, 43, 45):
            with self.subTest(count=count):
                with self.assertRaises(pumd.PumdSchemaError):
                    pumd.ConsumerUnit(
                        "U", pumd.MIDDLE_QUARTER, 5, 1.0, 1.0, (0.0,) * count
                    )

    def test_a_missing_fmli_column_is_refused_rather_than_defaulted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fmli.csv"
            # NEWID and QINTRVMO present, FINLWT21 absent.
            path.write_text("NEWID,QINTRVMO,FINCBTXM\n1,5,100\n", encoding="utf-8")
            with self.assertRaises(pumd.PumdSchemaError) as caught:
                pumd.read_fmli(path, pumd.MIDDLE_QUARTER)
            self.assertIn(pumd.FINAL_WEIGHT_VARIABLE, str(caught.exception))

    def test_a_missing_mtbi_column_is_refused_rather_than_defaulted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mtbi.csv"
            path.write_text("NEWID,UCC,COST\n1,111111,10\n", encoding="utf-8")
            with self.assertRaises(pumd.PumdSchemaError) as caught:
                pumd.read_mtbi(path)
            self.assertIn("REF_YR", str(caught.exception))

    def test_an_unknown_quarter_role_is_refused_rather_than_assumed_middle(self):
        with self.assertRaises(pumd.PumdSchemaError):
            pumd.months_in_scope("SIXTH_QUARTER", 5)

    def test_a_blank_weight_is_zero_and_not_an_error(self):
        # "IF REPS_A(i) > 0 THEN ... ELSE REPS_B(i) = 0" - the BLS program.
        self.assertEqual(pumd._float_or_zero(""), 0.0)
        self.assertEqual(pumd._float_or_zero("   "), 0.0)
        self.assertEqual(pumd._float_or_zero(None), 0.0)
        self.assertEqual(pumd._float_or_zero(" 12.5 "), 12.5)


# ==========================================================================
# Joins
# ==========================================================================


class TestJoins(unittest.TestCase):
    def test_a_duplicate_newid_within_one_fmli_quarter_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fmli.csv"
            header = ",".join(
                ("NEWID", "QINTRVMO", pumd.FINAL_WEIGHT_VARIABLE, pumd.INCOME_VARIABLE)
                + pumd._REPLICATE_COLUMNS
            )
            row = "{newid},5,1000,50000" + ",1000" * 44
            path.write_text(
                header
                + "\n"
                + row.format(newid="A")
                + "\n"
                + row.format(newid="A")
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(pumd.PumdSchemaError) as caught:
                pumd.read_fmli(path, pumd.MIDDLE_QUARTER)
            self.assertIn("duplicate NEWID", str(caught.exception))

    def test_an_mtbi_record_with_no_matching_fmli_record_is_detected(self):
        units = make_units()
        records = make_records() + [
            pumd.ExpenditureRecord("GHOST", LARGE_UCC, 99.0, pumd.BENCHMARK_YEAR, 6)
        ]
        populations = pumd.population_estimates(units)
        with self.assertRaises(pumd.PumdSchemaError) as caught:
            pumd.weighted_ucc_means(units, records, populations, {})
        self.assertIn("GHOST", str(caught.exception))

    def test_the_unmutated_join_produces_no_orphans(self):
        units = make_units()
        populations = pumd.population_estimates(units)
        estimates = pumd.weighted_ucc_means(
            units, make_records(), populations, {LARGE_UCC: 1, SMALL_UCC: 1}
        )
        self.assertIn((LARGE_UCC, pumd.ALL_CONSUMER_UNITS), estimates)


# ==========================================================================
# Calendar-year eligibility
# ==========================================================================


class TestCalendarYearEligibility(unittest.TestCase):
    def test_only_the_benchmark_reference_year_is_eligible(self):
        self.assertTrue(pumd.is_in_benchmark_year(2024))
        self.assertFalse(pumd.is_in_benchmark_year(2023))
        self.assertFalse(pumd.is_in_benchmark_year(2025))

    def test_reference_month_does_not_restrict_eligibility(self):
        # The BLS program filters on REF_YR alone. REF_MO is carried for
        # inspection; a December 2024 reference month is as eligible as June.
        for month in range(1, 13):
            self.assertTrue(pumd.is_in_benchmark_year(2024))

    def test_out_of_year_rows_are_dropped_at_read_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mtbi.csv"
            path.write_text(
                "NEWID,UCC,COST,REF_YR,REF_MO\n"
                "A,111111,10,2023,11\n"
                "A,111111,20,2024,1\n"
                "A,111111,30,2025,2\n",
                encoding="utf-8",
            )
            records = pumd.read_mtbi(path)
            self.assertEqual([r.cost for r in records], [20.0])

    def test_the_roster_filter_never_alters_a_surviving_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mtbi.csv"
            path.write_text(
                "NEWID,UCC,COST,REF_YR,REF_MO\n"
                "A,111111,10,2024,3\n"
                "A,222222,20,2024,3\n",
                encoding="utf-8",
            )
            everything = pumd.read_mtbi(path)
            restricted = pumd.read_mtbi(path, keep_uccs=frozenset({LARGE_UCC}))
            self.assertEqual(len(everything), 2)
            self.assertEqual(restricted, [r for r in everything if r.ucc == LARGE_UCC])


# ==========================================================================
# Weighting: MO_SCOPE and the final weight
# ==========================================================================


class TestWeighting(unittest.TestCase):
    def test_first_quarter_months_in_scope_follow_the_bls_program(self):
        # IF FIRSTQTR THEN MO_SCOPE = (QINTRVMO - 1)
        expected = {1: 0, 2: 1, 3: 2, 4: 3}
        for month, months in expected.items():
            with self.subTest(month=month):
                self.assertEqual(
                    pumd.months_in_scope(pumd.FIRST_QUARTER, month), months
                )

    def test_a_january_first_quarter_interview_contributes_nothing(self):
        # It reports only on the previous calendar year. MO_SCOPE is 0, not 3.
        self.assertEqual(pumd.months_in_scope(pumd.FIRST_QUARTER, 1), 0)
        self.assertEqual(pumd.population_weight(9999.0, 0), 0.0)

    def test_fifth_quarter_months_in_scope_follow_the_bls_program(self):
        # ELSE IF LASTQTR THEN MO_SCOPE = (4 - QINTRVMO)
        for month, months in {1: 3, 2: 2, 3: 1, 4: 0}.items():
            with self.subTest(month=month):
                self.assertEqual(
                    pumd.months_in_scope(pumd.FIFTH_QUARTER, month), months
                )

    def test_middle_quarters_are_wholly_in_scope(self):
        for month in range(1, 13):
            self.assertEqual(pumd.months_in_scope(pumd.MIDDLE_QUARTER, month), 3)

    def test_the_population_weight_is_finlwt21_times_mo_scope_over_twelve(self):
        self.assertAlmostEqual(pumd.population_weight(1200.0, 3), 300.0)
        self.assertAlmostEqual(pumd.population_weight(1200.0, 1), 100.0)
        self.assertAlmostEqual(pumd.population_weight(1200.0, 0), 0.0)

    def test_a_non_positive_final_weight_contributes_nothing(self):
        self.assertEqual(pumd.population_weight(0.0, 3), 0.0)
        self.assertEqual(pumd.population_weight(-500.0, 3), 0.0)

    def test_the_full_sample_weight_leads_its_forty_four_replicates(self):
        unit = make_units()[0]
        weights = pumd.population_weights(unit)
        self.assertEqual(len(weights), pumd.REPLICATE_WEIGHT_COUNT + 1)
        self.assertAlmostEqual(weights[0], 1000.0 * 3 / 12)
        self.assertAlmostEqual(weights[1], 500.0 * 3 / 12)

    def test_the_synthetic_population_is_the_hand_computed_one(self):
        estimates = pumd.population_estimates(make_units())
        self.assertAlmostEqual(
            estimates[pumd.ALL_CONSUMER_UNITS].consumer_units, 15000.0 / 4
        )
        for label, weight in zip(pumd.QUINTILE_LABELS, (1000, 2000, 3000, 4000, 5000)):
            with self.subTest(quintile=label):
                self.assertAlmostEqual(
                    estimates[label].consumer_units, weight / 4.0
                )

    def test_consumer_units_are_reported_in_thousands(self):
        estimates = pumd.population_estimates(make_units())
        self.assertAlmostEqual(
            estimates[pumd.ALL_CONSUMER_UNITS].consumer_units_thousands, 3.75
        )


# ==========================================================================
# Quintile assignment, boundaries and degenerate income
# ==========================================================================


class TestQuintileAssignment(unittest.TestCase):
    LIMITS = pumd.PUBLISHED_QUINTILE_LOWER_LIMITS_2024

    def test_the_published_2024_limits_are_the_ones_bls_printed(self):
        self.assertEqual(self.LIMITS, (29932.0, 57452.0, 94511.0, 155925.0))

    def test_income_below_the_first_limit_is_the_bottom_quintile(self):
        self.assertEqual(pumd.assign_quintile(0.0), "Q1")
        self.assertEqual(pumd.assign_quintile(29931.99), "Q1")

    def test_income_exactly_at_a_lower_limit_falls_in_the_higher_quintile(self):
        # That is what "lower limit" means, and it is the only tie rule that
        # makes the published limits partition the income line.
        for index, limit in enumerate(self.LIMITS):
            with self.subTest(limit=limit):
                self.assertEqual(
                    pumd.assign_quintile(limit), pumd.QUINTILE_LABELS[index + 1]
                )
                self.assertEqual(
                    pumd.assign_quintile(limit - 0.01), pumd.QUINTILE_LABELS[index]
                )

    def test_income_above_the_top_limit_is_the_top_quintile(self):
        self.assertEqual(pumd.assign_quintile(1e9), "Q5")

    def test_zero_and_negative_income_land_in_the_bottom_quintile(self):
        # CE income before taxes can be negative for a self-employed CU with a
        # business loss. It belongs in Q1, not in an error.
        self.assertEqual(pumd.assign_quintile(0.0), "Q1")
        self.assertEqual(pumd.assign_quintile(-25_000.0), "Q1")

    def test_a_missing_income_field_is_read_as_zero_and_lands_in_q1(self):
        self.assertEqual(pumd.assign_quintile(pumd._float_or_zero("")), "Q1")

    def test_the_wrong_number_of_limits_is_refused(self):
        for limits in ((1.0, 2.0, 3.0), (1.0, 2.0, 3.0, 4.0, 5.0), ()):
            with self.subTest(limits=limits):
                with self.assertRaises(pumd.PumdSchemaError):
                    pumd.assign_quintile(100.0, limits)

    def test_unsorted_limits_are_refused_rather_than_silently_sorted(self):
        with self.assertRaises(pumd.PumdSchemaError):
            pumd.assign_quintile(100.0, (57452.0, 29932.0, 94511.0, 155925.0))

    def test_the_reconstruction_is_diagnostic_and_never_assigns(self):
        rows = bench.reconstruct_boundaries(make_skewed_units())
        self.assertEqual({row.used_for_assignment for row in rows}, {"published"})
        self.assertEqual(
            [row.published_lower_limit for row in rows], list(self.LIMITS)
        )


# ==========================================================================
# Estimation: annualization, the mean identity, and BRR
# ==========================================================================


class TestEstimation(unittest.TestCase):
    def setUp(self):
        self.units = make_units()
        self.records = make_records()
        self.populations = pumd.population_estimates(self.units)

    def means(self, factors):
        return pumd.weighted_ucc_means(
            self.units, self.records, self.populations, factors
        )

    def test_the_all_cu_mean_is_the_hand_computed_one(self):
        estimate = self.means({LARGE_UCC: 1})[(LARGE_UCC, pumd.ALL_CONSUMER_UNITS)]
        self.assertAlmostEqual(estimate.mean, ALL_CU_MEAN)

    def test_every_quintile_mean_is_the_hand_computed_one(self):
        estimates = self.means({LARGE_UCC: 1})
        for label, expected in QUINTILE_MEANS.items():
            with self.subTest(quintile=label):
                self.assertAlmostEqual(estimates[(LARGE_UCC, label)].mean, expected)

    def test_a_consumer_unit_with_no_record_still_sits_in_the_denominator(self):
        # This is what makes the estimand a mean over all consumer units and
        # not a mean over purchasers. Drop U5's record and the All-CU mean must
        # fall by exactly U5's contribution, with the denominator unchanged.
        records = [r for r in self.records if not (r.newid == "U5" and r.ucc == LARGE_UCC)]
        estimates = pumd.weighted_ucc_means(
            self.units, records, self.populations, {LARGE_UCC: 1}
        )
        expected = (550_000.0 - 5000.0 * 50.0) / 3750.0
        self.assertAlmostEqual(estimates[(LARGE_UCC, pumd.ALL_CONSUMER_UNITS)].mean, expected)
        self.assertNotIn("Q5", [key[1] for key in estimates if key[0] == LARGE_UCC])

    def test_the_annualization_factor_multiplies_the_mean(self):
        one = self.means({LARGE_UCC: 1})[(LARGE_UCC, pumd.ALL_CONSUMER_UNITS)].mean
        four = self.means({LARGE_UCC: 4})[(LARGE_UCC, pumd.ALL_CONSUMER_UNITS)].mean
        self.assertAlmostEqual(four, one * 4.0)

    def test_a_ucc_with_no_stated_factor_defaults_to_one(self):
        stated = self.means({LARGE_UCC: 1})[(LARGE_UCC, pumd.ALL_CONSUMER_UNITS)].mean
        omitted = self.means({})[(LARGE_UCC, pumd.ALL_CONSUMER_UNITS)].mean
        self.assertAlmostEqual(stated, omitted)

    def test_the_brr_standard_error_is_the_documented_formula(self):
        # SE = SQRT((1/44) * SUM (MEAN_r - MEAN)**2). Every replicate mean of
        # this fixture is 160, so the SE collapses to |160 - 146.666...|.
        estimate = self.means({LARGE_UCC: 1})[(LARGE_UCC, pumd.ALL_CONSUMER_UNITS)]
        self.assertAlmostEqual(estimate.standard_error, ALL_CU_STANDARD_ERROR)

    def test_the_standard_error_formula_divides_by_the_replicate_count(self):
        # Not by n-1. The BLS formula has no finite-population correction.
        self.assertAlmostEqual(pumd._standard_error(0.0, [1.0, -1.0]), 1.0)
        self.assertAlmostEqual(pumd._standard_error(10.0, [10.0] * 44), 0.0)

    def test_the_relative_standard_error_is_a_percentage_of_the_mean(self):
        estimate = self.means({LARGE_UCC: 1})[(LARGE_UCC, pumd.ALL_CONSUMER_UNITS)]
        self.assertAlmostEqual(
            estimate.relative_standard_error_pct,
            100.0 * ALL_CU_STANDARD_ERROR / ALL_CU_MEAN,
        )

    def test_reporting_records_counts_the_contributing_rows(self):
        estimates = self.means({LARGE_UCC: 1})
        self.assertEqual(estimates[(LARGE_UCC, pumd.ALL_CONSUMER_UNITS)].reporting_records, 5)
        self.assertEqual(estimates[(LARGE_UCC, "Q3")].reporting_records, 1)


# ==========================================================================
# The benchmark, end to end on the synthetic universe
# ==========================================================================


class TestBenchmarkOnSyntheticData(unittest.TestCase):
    def setUp(self):
        self.units = make_units()
        self.records = make_records()
        self.roster = make_roster()
        self.basis = make_basis_rows()
        self.spec = make_spec(self.roster)
        self.comparisons = make_population_comparisons()

    def run_it(self, roster=None, units=None, records=None):
        results, _ = bench.run_benchmark(
            roster or self.roster,
            units or self.units,
            records or self.records,
            self.basis,
            self.spec,
        )
        return results

    def test_a_perfectly_reproducing_source_passes(self):
        results = self.run_it()
        summary = bench.summarize(results, self.comparisons, self.roster, self.spec)
        self.assertEqual(summary.benchmark_status, "PASS")
        self.assertEqual(summary.failed_criteria, ())
        self.assertEqual(summary.pass_fraction, 1.0)
        self.assertAlmostEqual(summary.max_abs_pct_error, 0.0)

    def test_every_result_carries_the_lb01_estimand_and_its_units(self):
        results = self.run_it()
        self.assertEqual({r.estimand for r in results}, {bench.ESTIMAND})
        self.assertEqual({r.estimand_units for r in results}, {bench.ESTIMAND_UNITS})

    def test_every_roster_ucc_is_compared_in_every_lb01_population(self):
        results = self.run_it()
        self.assertEqual(len(results), len(self.roster) * 6)
        for entry in self.roster:
            populations = {r.population for r in results if r.ucc == entry.ucc}
            self.assertEqual(
                populations, set(bench.LABSTAT_POPULATION_BY_CODE.values())
            )

    def test_a_cell_below_the_small_value_floor_is_judged_on_absolute_difference(self):
        results = self.run_it()
        small = [r for r in results if r.ucc == SMALL_UCC]
        large = [r for r in results if r.ucc == LARGE_UCC]
        self.assertEqual({r.judged_on for r in small}, {"ABSOLUTE_DIFFERENCE"})
        self.assertEqual({r.judged_on for r in large}, {"PERCENTAGE_DIFFERENCE"})

    def test_small_value_cells_are_kept_out_of_the_percentage_distribution(self):
        # The spec says such cells are judged on absolute difference "instead".
        # If their percentages leaked into the distribution, publication
        # rounding of a two-dollar mean would dominate a statistic meant to
        # describe reproduction quality.
        results = self.run_it()
        summary = bench.summarize(results, self.comparisons, self.roster, self.spec)
        self.assertEqual(summary.absolute_judged_count, 6)
        self.assertEqual(summary.percentage_judged_count, 6)
        self.assertEqual(
            summary.percentage_judged_count + summary.absolute_judged_count,
            summary.comparison_count,
        )

    def test_small_value_cells_still_count_towards_the_pass_fraction(self):
        # Excluded from the percentage distribution is not excluded from
        # judgement. Move one small-value published cell far enough that the
        # absolute-difference test fails, and the pass fraction must drop.
        moved = [
            {**row, "mean_expenditure": "9.0"}
            if row["ucc"] == SMALL_UCC and row["characteristics_code"] == "02"
            else row
            for row in self.basis
        ]
        results, _ = bench.run_benchmark(
            self.roster, self.units, self.records, moved, self.spec
        )
        summary = bench.summarize(results, self.comparisons, self.roster, self.spec)
        failed = [r for r in results if r.benchmark_status == "FAIL"]
        self.assertEqual([(r.ucc, r.population) for r in failed], [(SMALL_UCC, "Q1")])
        self.assertAlmostEqual(summary.pass_fraction, 11 / 12)
        # ... and the failing cell contributed no percentage to the tail.
        self.assertEqual(summary.percentage_judged_count, 6)

    def test_the_whole_roster_is_run_even_when_a_ucc_reproduces_badly(self):
        broken = [
            row
            if row["ucc"] != LARGE_UCC or row["characteristics_code"] != "04"
            else {**row, "mean_expenditure": "1.0"}
            for row in self.basis
        ]
        results, _ = bench.run_benchmark(
            self.roster, self.units, self.records, broken, self.spec
        )
        self.assertEqual(len(results), len(self.roster) * 6)
        self.assertEqual(
            sum(1 for r in results if r.benchmark_status == "FAIL"), 1
        )

    def test_a_roster_ucc_with_no_published_cell_is_refused(self):
        thinned = [row for row in self.basis if row["characteristics_code"] != "05"]
        with self.assertRaises(bench.RosterError) as caught:
            bench.run_benchmark(self.roster, self.units, self.records, thinned, self.spec)
        self.assertIn("missing", str(caught.exception))

    def test_a_roster_ucc_with_no_pumd_record_is_refused_not_zero_filled(self):
        records = [r for r in self.records if r.ucc != SMALL_UCC]
        with self.assertRaises(pumd.PumdSchemaError):
            bench.run_benchmark(self.roster, self.units, records, self.basis, self.spec)

    def test_the_percentile_helper_is_nearest_rank(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        self.assertEqual(bench.percentile(values, 0.0), 1.0)
        self.assertEqual(bench.percentile(values, 0.5), 3.0)
        self.assertEqual(bench.percentile(values, 1.0), 5.0)
        with self.assertRaises(ValueError):
            bench.percentile([], 0.5)


# ==========================================================================
# Mutation tests
# ==========================================================================


class TestMutationUnweightedQuintileSplit(unittest.TestCase):
    """Splitting the sample into unweighted fifths must not go undetected."""

    @staticmethod
    def unweighted_fifth_limits(units):
        """MUTATION: quintile limits from equal-count sample fifths."""
        incomes = sorted(unit.income_before_taxes for unit in units)
        count = len(incomes)
        return tuple(incomes[round(count * share / 5)] for share in (1, 2, 3, 4))

    def setUp(self):
        self.units = make_skewed_units()
        self.mutated = self.unweighted_fifth_limits(self.units)

    def test_the_mutation_really_does_differ_from_the_published_rule(self):
        # Without this the rest of the class could pass vacuously.
        self.assertNotEqual(
            tuple(self.mutated), pumd.PUBLISHED_QUINTILE_LOWER_LIMITS_2024
        )

    def test_the_published_rule_does_not_produce_equal_sized_quintiles(self):
        # Real income quintiles of a real sample are not equal-count groups of
        # interviews, and the fixture is built so this is unmistakable.
        counts = {label: 0 for label in pumd.QUINTILE_LABELS}
        for unit in self.units:
            counts[pumd.assign_quintile(unit.income_before_taxes)] += 1
        self.assertEqual(counts["Q1"], 6)
        self.assertEqual(counts["Q2"], 0)
        self.assertEqual(counts["Q4"], 0)

    def test_the_unweighted_split_produces_a_different_population(self):
        truth = pumd.population_estimates(self.units)
        broken = pumd.population_estimates(self.units, self.mutated)
        self.assertAlmostEqual(
            truth[pumd.ALL_CONSUMER_UNITS].consumer_units,
            broken[pumd.ALL_CONSUMER_UNITS].consumer_units,
            msg="the mutation must not move the total, only its division",
        )
        differing = [
            label
            for label in pumd.QUINTILE_LABELS
            if abs(truth[label].consumer_units - broken[label].consumer_units) > 1e-9
        ]
        self.assertTrue(differing, "the unweighted split changed no quintile at all")

    def test_the_reconstruction_is_reported_but_never_used(self):
        # reconstruct_quintile_limits is a weighted-rank guess at an algorithm
        # BLS does not publish. It must stay diagnostic.
        derived = pumd.reconstruct_quintile_limits(self.units)
        estimates = pumd.population_estimates(self.units)
        by_published = pumd.population_estimates(
            self.units, pumd.PUBLISHED_QUINTILE_LOWER_LIMITS_2024
        )
        for label in pumd.QUINTILE_LABELS:
            self.assertAlmostEqual(
                estimates[label].consumer_units, by_published[label].consumer_units
            )
        self.assertEqual(len(derived), 4)


class TestMutationWrongWeightVariable(unittest.TestCase):
    """Using a replicate weight, or no weight, in place of FINLWT21."""

    def setUp(self):
        self.units = make_units()
        self.records = make_records()

    def mean_with(self, units):
        populations = pumd.population_estimates(units)
        estimates = pumd.weighted_ucc_means(
            units, self.records, populations, {LARGE_UCC: 1}
        )
        return estimates[(LARGE_UCC, pumd.ALL_CONSUMER_UNITS)].mean

    def test_the_declared_weight_variable_is_the_bls_final_weight(self):
        self.assertEqual(pumd.FINAL_WEIGHT_VARIABLE, "FINLWT21")
        self.assertEqual(pumd.INCOME_VARIABLE, "FINCBTXM")

    def test_the_unmutated_mean_is_correct(self):
        self.assertAlmostEqual(self.mean_with(self.units), ALL_CU_MEAN)

    def test_substituting_the_first_replicate_weight_changes_the_answer(self):
        mutated = [
            pumd.ConsumerUnit(
                newid=unit.newid,
                quarter_role=unit.quarter_role,
                interview_month=unit.interview_month,
                final_weight=unit.replicate_weights[0],
                income_before_taxes=unit.income_before_taxes,
                replicate_weights=unit.replicate_weights,
            )
            for unit in self.units
        ]
        self.assertAlmostEqual(self.mean_with(mutated), 160.0)
        self.assertNotAlmostEqual(self.mean_with(mutated), ALL_CU_MEAN, places=6)

    def test_unweighted_aggregation_changes_the_answer(self):
        # Every CU counted once. With unequal true weights this cannot agree.
        mutated = [
            pumd.ConsumerUnit(
                newid=unit.newid,
                quarter_role=unit.quarter_role,
                interview_month=unit.interview_month,
                final_weight=1.0,
                income_before_taxes=unit.income_before_taxes,
                replicate_weights=(1.0,) * pumd.REPLICATE_WEIGHT_COUNT,
            )
            for unit in self.units
        ]
        self.assertAlmostEqual(self.mean_with(mutated), 120.0)
        self.assertNotAlmostEqual(self.mean_with(mutated), ALL_CU_MEAN, places=6)

    def test_dropping_the_mo_scope_adjustment_changes_the_answer(self):
        # MUTATION: population weight = FINLWT21 / QNUM, ignoring MO_SCOPE.
        # A first-quarter January interview would then be counted in full.
        january = pumd.ConsumerUnit(
            "J", pumd.FIRST_QUARTER, 1, 4000.0, 10_000.0, (0.0,) * 44
        )
        self.assertEqual(pumd.population_weights(january)[0], 0.0)
        self.assertNotEqual(4000.0 / pumd.QNUM, 0.0)


class TestMutationWrongAnnualizationFactor(unittest.TestCase):
    def setUp(self):
        self.units = make_units()
        self.records = make_records()
        self.roster = make_roster()
        self.basis = make_basis_rows()
        self.spec = make_spec(self.roster)
        self.comparisons = make_population_comparisons()

    def mutate_factor(self, factor):
        return [
            bench.RosterEntry(
                **{**asdict(entry), "annualization_factor": factor}
            )
            if entry.ucc == LARGE_UCC
            else entry
            for entry in self.roster
        ]

    def test_the_unmutated_factor_passes(self):
        results, _ = bench.run_benchmark(
            self.roster, self.units, self.records, self.basis, self.spec
        )
        summary = bench.summarize(results, self.comparisons, self.roster, self.spec)
        self.assertEqual(summary.benchmark_status, "PASS")

    def test_a_factor_of_four_where_one_is_correct_fails_the_benchmark(self):
        mutated = self.mutate_factor(4)
        spec = bench.BenchmarkSpec(
            **{**asdict(self.spec), "roster_hash": bench.roster_hash(mutated)}
        )
        results, _ = bench.run_benchmark(
            mutated, self.units, self.records, self.basis, spec
        )
        summary = bench.summarize(results, self.comparisons, mutated, spec)
        self.assertEqual(summary.benchmark_status, "FAIL")
        self.assertIn("median_abs_pct_error_max", summary.failed_criteria)
        self.assertAlmostEqual(summary.max_abs_pct_error, 300.0)

    def test_the_factor_change_moves_the_roster_hash(self):
        self.assertNotEqual(
            bench.roster_hash(self.roster), bench.roster_hash(self.mutate_factor(4))
        )


class TestMutationRosterAlteration(unittest.TestCase):
    def setUp(self):
        self.roster = make_roster()
        self.spec = make_spec(self.roster)
        self.units = make_units()
        self.records = make_records()
        self.basis = make_basis_rows()
        self.comparisons = make_population_comparisons()
        self.results, _ = bench.run_benchmark(
            self.roster, self.units, self.records, self.basis, self.spec
        )

    def summarize_with(self, roster):
        return bench.summarize(self.results, self.comparisons, roster, self.spec)

    def test_the_unaltered_roster_summarizes(self):
        self.assertEqual(self.summarize_with(self.roster).benchmark_status, "PASS")

    def test_dropping_a_ucc_is_refused(self):
        with self.assertRaises(bench.RosterError) as caught:
            self.summarize_with(self.roster[:1])
        self.assertIn("roster has changed", str(caught.exception))

    def test_adding_a_ucc_is_refused(self):
        extra = bench.RosterEntry(
            **{**asdict(self.roster[0]), "ucc": "333333"}
        )
        with self.assertRaises(bench.RosterError):
            self.summarize_with(list(self.roster) + [extra])

    def test_changing_a_selection_field_is_refused(self):
        for field, value in (
            ("dmi_node", "OTHER_NODE"),
            ("magnitude_stratum", "MEDIUM"),
            ("annualization_factor", 4),
            ("all_cu_published_mean", 999.0),
        ):
            with self.subTest(field=field):
                altered = [
                    bench.RosterEntry(**{**asdict(self.roster[0]), field: value}),
                    self.roster[1],
                ]
                with self.assertRaises(bench.RosterError):
                    self.summarize_with(altered)

    def test_reordering_the_roster_is_not_a_change(self):
        # The hash is over the UCC-sorted content, so order carries no meaning.
        self.assertEqual(
            bench.roster_hash(self.roster), bench.roster_hash(list(reversed(self.roster)))
        )

    def test_a_roster_version_that_disagrees_with_the_rule_is_refused(self):
        spec = bench.BenchmarkSpec(**{**asdict(self.spec), "roster_version": "v0.1"})
        with self.assertRaises(bench.RosterError) as caught:
            bench.summarize(self.results, self.comparisons, self.roster, spec)
        self.assertIn("roster version", str(caught.exception))


class TestMutationShelterUccAsBenchmark(unittest.TestCase):
    """The four Milestone-2 shelter UCCs must not reach the benchmark."""

    def test_the_excluded_set_is_exactly_the_four_shelter_uccs(self):
        self.assertEqual(
            bench.EXCLUDED_FROM_CALIBRATION, ("910104", "910105", "910106", "910107")
        )

    def test_constructing_a_roster_entry_for_one_is_refused(self):
        for ucc in bench.EXCLUDED_FROM_CALIBRATION:
            with self.subTest(ucc=ucc):
                with self.assertRaises(bench.RosterError) as caught:
                    bench.RosterEntry(
                        ucc=ucc,
                        published_title="Owned dwellings",
                        dmi_node="SHELTER",
                        domain_label="Housing",
                        stub_title="Owned dwellings",
                        annualization_factor=1,
                        magnitude_stratum="LARGE",
                        all_cu_published_mean=1000.0,
                        all_cu_published_rse=1.0,
                        selection_rank_in_cell=0,
                        cell_size=1,
                    )
                self.assertIn("never enter the benchmark roster", str(caught.exception))

    def test_run_benchmark_refuses_one_even_if_the_constructor_is_bypassed(self):
        # Defence in depth: forge an entry past __post_init__ and prove the
        # second guard is live rather than decorative.
        forged = object.__new__(bench.RosterEntry)
        for field, value in asdict(make_roster()[0]).items():
            object.__setattr__(forged, field, value)
        object.__setattr__(forged, "ucc", "910104")
        with self.assertRaises(bench.RosterError) as caught:
            bench.run_benchmark(
                [forged], make_units(), make_records(), make_basis_rows(), make_spec(make_roster())
            )
        self.assertIn("910104", str(caught.exception))

    def test_eligibility_skips_one_even_if_it_were_misclassified(self):
        # If a future artifact wrongly called 910104 a DIRECT_CONCORDANCE_UCC,
        # the eligibility rule must still refuse it.
        stub = {
            "910104": pumd.StubEntry("910104", "Owned dwellings", 1, "I", 1, "EXPEND")
        }
        provenance = [
            {
                "ucc": "910104",
                "provenance_class": bench.REQUIRED_PROVENANCE_CLASS,
                "ce_source": bench.REQUIRED_CE_SOURCE,
                "dmi_node": "SHELTER",
            }
        ]
        basis = [
            {
                "ucc": "910104",
                "characteristics_code": code,
                "item_text": "Owned dwellings",
                "domain_label": "Housing",
                "mean_expenditure": "1000.0",
                "rse": "1.0",
            }
            for code in bench.REQUIRED_CHARACTERISTICS
        ]
        self.assertEqual(
            bench.eligible_candidates(provenance, basis, [], stub, stub), []
        )

    def test_a_spec_that_excludes_a_different_set_is_refused(self):
        payload = asdict(make_spec(make_roster()))
        for wrong in ((), ("910104",), ("910104", "910105", "910106")):
            with self.subTest(excluded=wrong):
                with self.assertRaises(ValueError):
                    bench.BenchmarkSpec(
                        **{**payload, "excluded_from_calibration": wrong}
                    )

    def test_a_spec_with_a_different_estimand_is_refused(self):
        payload = asdict(make_spec(make_roster()))
        with self.assertRaises(ValueError) as caught:
            bench.BenchmarkSpec(
                **{**payload, "estimand": "AGGREGATE_ANNUAL_EXPENDITURE"}
            )
        self.assertIn("estimand", str(caught.exception))


# ==========================================================================
# Roster selection
# ==========================================================================


class TestRosterSelection(unittest.TestCase):
    """The selection rule must depend only on published inputs."""

    NODE = "SYNTHETIC_NODE"

    def build(self, count=9, **overrides):
        provenance, basis, interview, integrated = [], [], {}, {}
        for index in range(count):
            ucc = f"{100000 + index}"
            mean = float(1000 - 50 * index)
            provenance.append(
                {
                    "ucc": ucc,
                    "provenance_class": bench.REQUIRED_PROVENANCE_CLASS,
                    "ce_source": bench.REQUIRED_CE_SOURCE,
                    "dmi_node": self.NODE,
                    **overrides.get(ucc, {}),
                }
            )
            interview[ucc] = pumd.StubEntry(ucc, f"Item {index}", 1, "I", 1, "EXPEND")
            integrated[ucc] = pumd.StubEntry(ucc, f"Item {index}", 1, "I", 1, "EXPEND")
            for code in bench.REQUIRED_CHARACTERISTICS:
                basis.append(
                    {
                        "ucc": ucc,
                        "characteristics_code": code,
                        "item_text": f"Item {index}",
                        "domain_label": "Housing",
                        "mean_expenditure": repr(mean),
                        "rse": "5.00",
                    }
                )
        return provenance, basis, interview, integrated

    def test_a_full_pool_yields_one_ucc_per_node_and_stratum(self):
        provenance, basis, interview, integrated = self.build(9)
        roster = bench.select_roster(provenance, basis, [], interview, integrated)
        self.assertEqual(len(roster), 3)
        self.assertEqual(
            sorted(entry.magnitude_stratum for entry in roster),
            sorted(bench.MAGNITUDE_STRATA),
        )

    def test_the_strata_are_equal_count_terciles_of_the_pool(self):
        provenance, basis, interview, integrated = self.build(9)
        candidates = bench.eligible_candidates(
            provenance, basis, [], interview, integrated
        )
        strata = bench.assign_magnitude_strata(candidates)
        counts = {stratum: 0 for stratum in bench.MAGNITUDE_STRATA}
        for stratum in strata.values():
            counts[stratum] += 1
        self.assertEqual(counts, {"LARGE": 3, "MEDIUM": 3, "SMALL": 3})

    def test_the_largest_published_mean_is_in_the_large_stratum(self):
        provenance, basis, interview, integrated = self.build(9)
        candidates = bench.eligible_candidates(
            provenance, basis, [], interview, integrated
        )
        self.assertEqual(candidates[0].all_cu_published_mean, 1000.0)
        self.assertEqual(
            bench.assign_magnitude_strata(candidates)[candidates[0].ucc], "LARGE"
        )

    def test_the_median_member_of_each_cell_is_taken(self):
        provenance, basis, interview, integrated = self.build(9)
        roster = bench.select_roster(provenance, basis, [], interview, integrated)
        self.assertEqual({entry.selection_rank_in_cell for entry in roster}, {1})
        self.assertEqual({entry.cell_size for entry in roster}, {3})

    def test_selection_is_deterministic(self):
        args = self.build(9)
        first = bench.select_roster(args[0], args[1], [], args[2], args[3])
        second = bench.select_roster(args[0], args[1], [], args[2], args[3])
        self.assertEqual(bench.roster_hash(first), bench.roster_hash(second))

    def test_a_concordance_only_ucc_is_not_eligible(self):
        provenance, basis, interview, integrated = self.build(9)
        provenance[0]["provenance_class"] = "CONCORDANCE_ONLY_UCC"
        candidates = bench.eligible_candidates(
            provenance, basis, [], interview, integrated
        )
        self.assertNotIn(provenance[0]["ucc"], {c.ucc for c in candidates})

    def test_a_diary_sourced_ucc_is_not_eligible(self):
        provenance, basis, interview, integrated = self.build(9)
        provenance[0]["ce_source"] = "D"
        candidates = bench.eligible_candidates(
            provenance, basis, [], interview, integrated
        )
        self.assertNotIn(provenance[0]["ucc"], {c.ucc for c in candidates})

    def test_the_integrated_stub_and_not_the_interview_stub_decides_the_survey(self):
        # This is the v0.1 defect. The Interview stub codes essentially every
        # row I, so testing it proves nothing; LB01 is an integrated table and
        # the integrated file is what names the supplying survey.
        provenance, basis, interview, integrated = self.build(9)
        target = provenance[0]["ucc"]
        integrated[target] = pumd.StubEntry(target, "Item 0", 1, "D", 1, "EXPEND")
        candidates = bench.eligible_candidates(
            provenance, basis, [], interview, integrated
        )
        self.assertNotIn(target, {c.ucc for c in candidates})
        self.assertEqual(interview[target].survey, "I")

    def test_a_ucc_absent_from_the_integrated_stub_is_not_eligible(self):
        provenance, basis, interview, integrated = self.build(9)
        target = provenance[0]["ucc"]
        del integrated[target]
        candidates = bench.eligible_candidates(
            provenance, basis, [], interview, integrated
        )
        self.assertNotIn(target, {c.ucc for c in candidates})

    def test_a_non_expenditure_section_is_not_eligible(self):
        for section in ("ADDENDA", "ASSETS", "CUCHARS", "INCOME"):
            with self.subTest(section=section):
                provenance, basis, interview, integrated = self.build(9)
                target = provenance[0]["ucc"]
                interview[target] = pumd.StubEntry(
                    target, "Item 0", 1, "I", 1, section
                )
                candidates = bench.eligible_candidates(
                    provenance, basis, [], interview, integrated
                )
                self.assertNotIn(target, {c.ucc for c in candidates})

    def test_a_milestone_1_exception_ucc_is_not_eligible(self):
        provenance, basis, interview, integrated = self.build(9)
        target = provenance[0]["ucc"]
        candidates = bench.eligible_candidates(
            provenance, basis, [target], interview, integrated
        )
        self.assertNotIn(target, {c.ucc for c in candidates})

    def test_a_ucc_without_a_published_mean_in_every_population_is_not_eligible(self):
        provenance, basis, interview, integrated = self.build(9)
        target = provenance[0]["ucc"]
        thinned = [
            row
            for row in basis
            if not (row["ucc"] == target and row["characteristics_code"] == "06")
        ]
        candidates = bench.eligible_candidates(
            provenance, thinned, [], interview, integrated
        )
        self.assertNotIn(target, {c.ucc for c in candidates})

    def test_a_suppressed_published_mean_is_not_eligible(self):
        provenance, basis, interview, integrated = self.build(9)
        target = provenance[0]["ucc"]
        blanked = [
            {**row, "mean_expenditure": "  "}
            if row["ucc"] == target and row["characteristics_code"] == "03"
            else row
            for row in basis
        ]
        candidates = bench.eligible_candidates(
            provenance, blanked, [], interview, integrated
        )
        self.assertNotIn(target, {c.ucc for c in candidates})

    def test_a_node_spanning_all_three_strata_is_retained(self):
        # Positive control for the test below. With twelve candidates the
        # strata are indices 0-3 LARGE, 4-7 MEDIUM, 8-11 SMALL, so giving a
        # second node one member of each keeps it.
        provenance, basis, interview, integrated = self.build(12)
        for index in (3, 7, 11):
            provenance[index]["dmi_node"] = "OTHER_NODE"
        roster = bench.select_roster(provenance, basis, [], interview, integrated)
        self.assertEqual({entry.dmi_node for entry in roster}, {self.NODE, "OTHER_NODE"})
        self.assertEqual(len(roster), 6)

    def test_a_node_missing_one_stratum_is_dropped_whole(self):
        # Losing a single candidate can cost a node its full-stratum coverage,
        # and the rule then drops the node entirely, taking its other two
        # eligible UCCs with it. That is what happened to
        # EDUCATION_COMMUNICATION when the Diary-sourced 690119 was
        # disqualified: the node had exactly one eligible MEDIUM candidate.
        provenance, basis, interview, integrated = self.build(12)
        for index in (3, 7, 11):
            provenance[index]["dmi_node"] = "OTHER_NODE"
        provenance[7]["dmi_node"] = self.NODE  # remove OTHER_NODE's only MEDIUM
        roster = bench.select_roster(provenance, basis, [], interview, integrated)
        self.assertEqual({entry.dmi_node for entry in roster}, {self.NODE})
        self.assertEqual(len(roster), 3)

    def test_a_pool_where_no_node_spans_all_three_strata_is_refused(self):
        provenance, basis, interview, integrated = self.build(9)
        for index in (6, 7, 8):
            provenance[index]["dmi_node"] = "OTHER_NODE"
        with self.assertRaises(bench.RosterError) as caught:
            bench.select_roster(provenance, basis, [], interview, integrated)
        self.assertIn("magnitude strata", str(caught.exception))

    def test_a_pool_too_small_to_stratify_is_refused(self):
        provenance, basis, interview, integrated = self.build(2)
        with self.assertRaises(bench.RosterError):
            bench.select_roster(provenance, basis, [], interview, integrated)


# ==========================================================================
# Artifacts on disk
# ==========================================================================


class TestFrozenArtifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec_payload = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        cls.spec = bench.BenchmarkSpec.from_json(SPEC_PATH)
        cls.roster_rows = read_csv(OUTPUT_DIR / "benchmark_roster.csv")
        cls.results = read_csv(OUTPUT_DIR / "benchmark_results.csv")
        cls.summary = json.loads(
            (OUTPUT_DIR / "benchmark_summary.json").read_text(encoding="utf-8")
        )

    def rebuilt_roster(self):
        """Rebuild RosterEntry objects from the committed roster CSV."""
        return [
            bench.RosterEntry(
                ucc=row["ucc"],
                published_title=row["published_title"],
                dmi_node=row["dmi_node"],
                domain_label=row["domain_label"],
                stub_title=row["stub_title"],
                annualization_factor=int(row["annualization_factor"]),
                magnitude_stratum=row["magnitude_stratum"],
                all_cu_published_mean=float(row["all_cu_published_mean"]),
                all_cu_published_rse=(
                    float(row["all_cu_published_rse"])
                    if row["all_cu_published_rse"]
                    else None
                ),
                selection_rank_in_cell=int(row["selection_rank_in_cell"]),
                cell_size=int(row["cell_size"]),
            )
            for row in self.roster_rows
        ]

    def test_the_roster_on_disk_still_hashes_to_what_the_rule_pins(self):
        self.assertEqual(bench.roster_hash(self.rebuilt_roster()), self.spec.roster_hash)

    def test_the_roster_version_matches_the_selection_rule_in_code(self):
        self.assertEqual(self.spec.roster_version, bench.ROSTER_VERSION)

    def test_the_summary_reports_the_same_roster_the_rule_pins(self):
        self.assertEqual(self.summary["roster_hash"], self.spec.roster_hash)
        self.assertEqual(self.summary["roster_size"], len(self.roster_rows))
        self.assertEqual(self.summary["roster_version"], bench.ROSTER_VERSION)

    def test_the_declared_roster_size_matches_the_roster(self):
        self.assertEqual(
            self.spec_payload["roster_selection_rule"]["size"], len(self.roster_rows)
        )

    def test_the_roster_spans_several_nodes_domains_and_magnitudes(self):
        nodes = {row["dmi_node"] for row in self.roster_rows}
        domains = {row["domain_label"] for row in self.roster_rows}
        strata = {row["magnitude_stratum"] for row in self.roster_rows}
        self.assertGreaterEqual(len(nodes), 3)
        self.assertIn("Housing", domains)
        self.assertIn("Transportation", domains)
        self.assertEqual(strata, set(bench.MAGNITUDE_STRATA))

    def test_no_threshold_moved_between_the_failed_and_the_passing_run(self):
        # The v0.1 run FAILED. If any tolerance had been loosened afterwards to
        # obtain a PASS, this comparison would catch it.
        superseded = json.loads(
            (SUPERSEDED_DIR / "pumd_lb01_benchmark_spec_v0_1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            superseded["acceptance_rule"], self.spec_payload["acceptance_rule"]
        )
        self.assertEqual(self.spec_payload["threshold_change_log"], [])
        self.assertEqual(self.spec_payload["thresholds_unchanged_since"], "v0.1")

    def test_the_failed_v0_1_run_is_preserved_unaltered(self):
        superseded_summary = json.loads(
            (SUPERSEDED_DIR / "benchmark_summary.json").read_text(encoding="utf-8")
        )
        self.assertEqual(superseded_summary["benchmark_status"], "FAIL")
        for name in (
            "benchmark_roster.csv",
            "benchmark_results.csv",
            "population_validation.csv",
            "quintile_reconstruction.csv",
        ):
            with self.subTest(artifact=name):
                self.assertTrue((SUPERSEDED_DIR / name).is_file())

    def test_the_spec_discloses_which_thresholds_were_blind(self):
        disclosure = self.spec_payload["precommitment_disclosure"]
        self.assertEqual(
            set(disclosure["not_blind"]),
            {"population_tolerance_pct", "quintile_population_tolerance_pct"},
        )
        rule_keys = set(self.spec_payload["acceptance_rule"])
        self.assertEqual(
            set(disclosure["blind"]) | set(disclosure["not_blind"]), rule_keys
        )

    def test_every_result_row_carries_the_lb01_estimand_and_units(self):
        self.assertEqual({row["estimand"] for row in self.results}, {bench.ESTIMAND})
        self.assertEqual(
            {row["estimand_units"] for row in self.results}, {bench.ESTIMAND_UNITS}
        )

    def test_every_roster_ucc_is_compared_in_all_six_populations(self):
        expected = set(bench.LABSTAT_POPULATION_BY_CODE.values())
        for row in self.roster_rows:
            with self.subTest(ucc=row["ucc"]):
                populations = {
                    result["population"]
                    for result in self.results
                    if result["ucc"] == row["ucc"]
                }
                self.assertEqual(populations, expected)

    def test_no_ucc_was_dropped_between_the_roster_and_the_results(self):
        self.assertEqual(
            {row["ucc"] for row in self.roster_rows},
            {row["ucc"] for row in self.results},
        )

    def test_the_reported_status_agrees_with_the_reported_criteria(self):
        failed = self.summary["failed_criteria"]
        self.assertEqual(
            self.summary["benchmark_status"], "PASS" if not failed else "FAIL"
        )

    def test_the_summary_status_is_one_of_the_declared_verdicts(self):
        self.assertIn(self.summary["benchmark_status"], {"PASS", "FAIL", "BLOCKED"})


class TestNoShelterAmountWasEverWritten(unittest.TestCase):
    """910104-910107 keep pumd_quantitative_usability = NOT_ESTABLISHED.

    No annual or quintile expenditure estimate may be calculated, printed,
    saved or reported for them by this task. They may appear only as the
    declared exclusion.
    """

    def test_no_shelter_ucc_appears_in_any_roster_row(self):
        for directory in (OUTPUT_DIR, SUPERSEDED_DIR):
            rows = read_csv(directory / "benchmark_roster.csv")
            for row in rows:
                self.assertNotIn(row["ucc"], bench.EXCLUDED_FROM_CALIBRATION)

    def test_no_shelter_ucc_appears_in_any_result_row(self):
        for directory in (OUTPUT_DIR, SUPERSEDED_DIR):
            rows = read_csv(directory / "benchmark_results.csv")
            self.assertTrue(rows)
            for row in rows:
                self.assertNotIn(row["ucc"], bench.EXCLUDED_FROM_CALIBRATION)

    def test_the_summary_names_them_only_as_the_exclusion(self):
        for directory in (OUTPUT_DIR, SUPERSEDED_DIR):
            payload = json.loads(
                (directory / "benchmark_summary.json").read_text(encoding="utf-8")
            )
            excluded = payload.pop("excluded_from_calibration")
            self.assertEqual(tuple(excluded), bench.EXCLUDED_FROM_CALIBRATION)
            remainder = json.dumps(payload)
            for ucc in bench.EXCLUDED_FROM_CALIBRATION:
                self.assertNotIn(ucc, remainder)

    def test_the_csv_artifacts_never_mention_them_anywhere(self):
        for directory in (OUTPUT_DIR, SUPERSEDED_DIR):
            for path in sorted(directory.glob("*.csv")):
                text = path.read_text(encoding="utf-8")
                for ucc in bench.EXCLUDED_FROM_CALIBRATION:
                    with self.subTest(path=path.name, ucc=ucc):
                        self.assertNotIn(ucc, text)

    def test_the_spec_says_their_usability_is_unresolved_not_established(self):
        payload = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        rationale = payload["exclusion_rationale"]["why"]
        self.assertIn("NOT_ESTABLISHED", rationale)
        self.assertIn("CONCORDANCE_ONLY_UCC", rationale)


# ==========================================================================
# Firewall and frozen state
# ==========================================================================


class TestResearchFirewall(unittest.TestCase):
    FORBIDDEN = ("data/outputs", "deploy/data/outputs")

    def test_the_pumd_modules_import_nothing_operational(self):
        for module in (pumd, bench):
            source = Path(module.__file__).read_text(encoding="utf-8")
            for forbidden in ("dmi_calculator", "deploy/", "data/outputs"):
                with self.subTest(module=module.__name__, token=forbidden):
                    self.assertNotIn(f"import {forbidden}", source)
                    self.assertNotIn(f"from {forbidden}", source)

    def test_importing_the_benchmark_does_not_pull_in_the_calculator(self):
        # Checked in a clean interpreter: within this process other test
        # modules will already have imported the calculator, which says
        # nothing about the benchmark's own import graph.
        probe = (
            "import sys; sys.path.insert(0, %r);"
            "from dmi_research.detailed_inflation import pumd_benchmark;"
            "print(','.join(m for m in sys.modules if 'dmi_calculator' in m))"
            % str(REPO_ROOT)
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(result.stdout.strip(), "")

    def test_a_full_synthetic_run_touches_no_operational_tree(self):
        trees = [REPO_ROOT / name for name in self.FORBIDDEN]
        before = [fingerprint(tree) for tree in trees]

        roster = make_roster()
        spec = make_spec(roster)
        results, _ = bench.run_benchmark(
            roster, make_units(), make_records(), make_basis_rows(), spec
        )
        summary = bench.summarize(results, make_population_comparisons(), roster, spec)
        with tempfile.TemporaryDirectory() as tmp:
            bench.write_csv(
                Path(tmp) / "results.csv",
                tuple(asdict(results[0])),
                [asdict(r) for r in results],
            )
            self.assertTrue((Path(tmp) / "results.csv").is_file())
        self.assertEqual(summary.benchmark_status, "PASS")

        after = [fingerprint(tree) for tree in trees]
        for tree, snapshot_before, snapshot_after in zip(trees, before, after):
            self.assertEqual(
                snapshot_before, snapshot_after, f"the benchmark modified {tree}"
            )

    def test_a_full_synthetic_run_leaves_the_milestone_artifacts_untouched(self):
        trees = [MILESTONE_1, MILESTONE_2]
        before = [fingerprint(tree) for tree in trees]
        roster = make_roster()
        spec = make_spec(roster)
        bench.run_benchmark(roster, make_units(), make_records(), make_basis_rows(), spec)
        after = [fingerprint(tree) for tree in trees]
        for tree, snapshot_before, snapshot_after in zip(trees, before, after):
            self.assertEqual(
                snapshot_before,
                snapshot_after,
                f"the benchmark modified the frozen Milestone artifacts in {tree}",
            )

    def test_the_benchmark_writes_only_under_the_research_root(self):
        from dmi_research.detailed_inflation import RESEARCH_OUTPUT_ROOT

        script = (REPO_ROOT / "scripts/benchmark_pumd_2024.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(RESEARCH_OUTPUT_ROOT, script)
        for forbidden in self.FORBIDDEN:
            self.assertNotIn(forbidden, script)

    def test_the_phase_a_checkpoint_has_not_moved(self):
        try:
            resolved = subprocess.run(
                ["git", "rev-list", "-n", "1", FROZEN_TAG],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:  # pragma: no cover - git absent
            self.skipTest("git is not available")
        if resolved.returncode != 0:
            self.skipTest(f"tag {FROZEN_TAG} is not present in this clone")
        self.assertEqual(resolved.stdout.strip(), FROZEN_COMMIT)


# ==========================================================================
# Integration against the real microdata, skipped when absent
# ==========================================================================


class TestAgainstRealMicrodata(unittest.TestCase):
    def setUp(self):
        if not pumd.pumd_is_available():
            self.skipTest(
                "2024 CE Interview PUMD not present; set "
                f"{pumd.PUMD_DIR_ENV} to run the integration tests"
            )
        self.directory = pumd.locate_interview_csv_dir()

    def test_a_missing_archive_is_reported_and_never_silently_skipped_in_code(self):
        # This one runs whether or not the archive is present.
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(pumd.PumdDataUnavailable):
                pumd.locate_interview_csv_dir(tmp)
            self.assertFalse(pumd.pumd_is_available(tmp))

    def test_every_quarter_file_reads_with_the_documented_key(self):
        for fmli_name, _mtbi, role in pumd.QUARTER_FILES:
            with self.subTest(file=fmli_name):
                units = pumd.read_fmli(self.directory / fmli_name, role)
                self.assertTrue(units)
                self.assertEqual(len(units), len({u.newid for u in units}))

    def test_the_all_cu_population_reproduces_the_published_count(self):
        payload = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        target = payload["population_validation"][
            "published_targets_2024_consumer_units_thousands"
        ]["All Consumer Units"]
        units = pumd.read_all_fmli(self.directory)
        estimates = pumd.population_estimates(units)
        observed = estimates[pumd.ALL_CONSUMER_UNITS].consumer_units_thousands
        spec = bench.BenchmarkSpec.from_json(SPEC_PATH)
        self.assertLessEqual(
            abs(100.0 * (observed - target) / target), spec.population_tolerance_pct
        )


class TestMissingArchiveHandling(unittest.TestCase):
    """These run in CI, where the microdata are absent."""

    def test_an_unset_environment_variable_raises_rather_than_returns_empty(self):
        with self.assertRaises(pumd.PumdDataUnavailable) as caught:
            pumd.locate_interview_csv_dir("/nonexistent/pumd/directory")
        self.assertIn("does not exist", str(caught.exception))

    def test_a_directory_missing_a_quarter_is_reported_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "fmli241x.csv").write_text("x", encoding="utf-8")
            with self.assertRaises(pumd.PumdDataUnavailable) as caught:
                pumd.locate_interview_csv_dir(tmp)
            self.assertIn("mtbi241x.csv", str(caught.exception))

    def test_availability_is_reported_as_false_and_not_raised(self):
        self.assertFalse(pumd.pumd_is_available("/nonexistent/pumd/directory"))


if __name__ == "__main__":
    unittest.main()
