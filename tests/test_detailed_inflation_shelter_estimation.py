#!/usr/bin/env python3
"""Tests for the shelter estimation and its adjudication (Phases C2-C6).

The estimates themselves are not the interesting thing to test. Arithmetic
that reproduces four published LABSTAT series to within a few percent is
already checked by the artifact it wrote. What needs testing is the set of
disciplines that make those numbers mean something, because each of them is a
discipline that would still look fine if it had quietly stopped holding.

*The plan cannot be edited after the fact without that being visible.* The
runner refuses to start unless the specification is committed and every pinned
module digest still matches. A test mutates a digest and asserts the refusal.

*A missing estimate is not a zero.* 910106 has no records at all in the first
quintile. A pipeline that reported 0.00 there would look tidier and would be
lying. Tests assert the null survives the dataclass, the CSV and the JSON.

*No ratio is ever applied.* The counterpart comparison computes estimate over
published. Nothing multiplies by it. A test feeds a deliberately absurd
published value and asserts the estimate is unchanged.

*Usability and precision stay apart.* The frozen plan forbade the relative
standard error from becoming a usability rule. Tests assert that the usability
tests never read an RSE, and that a cell can be simultaneously BENCHMARKED and
LOW quality, which is the combination the separation exists to permit.

*The pairing is measured, not assumed.* Synthetic records with a known
relation must be labelled with that relation, and - the part that matters -
records with no relation must not be labelled with one.
"""

from __future__ import annotations

import ast
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dmi_research.detailed_inflation import pumd  # noqa: E402
from dmi_research.detailed_inflation import shelter_estimation as est  # noqa: E402
from dmi_research.detailed_inflation import shelter_adjudication as adj  # noqa: E402

SHELTER_DIR = REPO_ROOT / "data/research/detailed_inflation/shelter_2024"
SPEC_PATH = REPO_ROOT / "registry/research/shelter_estimation_spec_v0_1.json"
ESTIMATES_PATH = SHELTER_DIR / "shelter_estimates_2024.csv"
SUMMARY_PATH = SHELTER_DIR / "shelter_estimation_summary.json"
ADJUDICATION_PATH = SHELTER_DIR / "shelter_adjudication_2024.json"


def _record(newid: str, ucc: str, cost: float, month: int = 1):
    return pumd.ExpenditureRecord(
        newid=newid, ucc=ucc, cost=cost, reference_year=2024, reference_month=month
    )


def _cell(
    ucc: str = "910104",
    population: str = "ALL_CU",
    status: str = est.ESTIMATED,
    mean: float | None = 100.0,
    rse: float | None = 5.0,
    replicates_at_zero: int | None = 0,
    records: int = 10,
):
    return est.ShelterCell(
        ucc=ucc,
        population=population,
        cell_status=status,
        unweighted_record_count=records,
        reporting_consumer_units=records,
        weighted_population=1000.0,
        annual_mean_per_consumer_unit=mean,
        annual_aggregate_dollars=None if mean is None else mean * 1000.0,
        standard_error=None if mean is None or rse is None else mean * rse / 100.0,
        relative_standard_error_pct=rse,
        interval_low=None if mean is None else mean * 0.9,
        interval_high=None if mean is None else mean * 1.1,
        replicate_min=None if mean is None else mean * 0.9,
        replicate_max=None if mean is None else mean * 1.1,
        replicates_at_zero=replicates_at_zero,
    )


# --------------------------------------------------------------------------


class TestTheFrozenPlan(unittest.TestCase):
    """The specification says the thirteen things it was required to say."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))

    def test_a_the_thirteen_required_items_are_present(self) -> None:
        required = {
            "source archive and hash": lambda s: s["source_archive"]["sha256"],
            "estimator version": lambda s: s["estimator"]["frozen_commit"],
            "annualization method": lambda s: s["method"]["annualization"]["rule"],
            "population denominator": lambda s: s["method"]["population_denominator"],
            "quintile assignment": lambda s: s["method"]["quintile_assignment"][
                "lower_limits"
            ],
            "final weight": lambda s: s["method"]["final_weight"],
            "replicate weights": lambda s: s["method"]["replicate_weights"],
            "BRR method": lambda s: s["method"]["brr"]["formula"],
            "the four UCCs": lambda s: s["uccs"]["track_a_inputs"],
            "UCC to shelter concept": lambda s: s["uccs"]["interpretation"],
            "estimands and units": lambda s: s["estimands"],
            "quality diagnostics": lambda s: s["required_quality_diagnostics"],
            "empty and thin cells": lambda s: s["empty_and_missing_cells"]["rule"],
            "prohibition on scaling": lambda s: s["estimator"]["prohibited_here"],
        }
        for label, get in required.items():
            with self.subTest(item=label):
                self.assertTrue(get(self.spec), f"{label} is missing or empty")

    def test_b_every_estimand_states_its_units(self) -> None:
        for name, body in self.spec["estimands"].items():
            with self.subTest(estimand=name):
                self.assertIn("units", body)
                self.assertTrue(body["units"].strip())

    def test_c_the_pairing_is_not_promoted_to_a_bls_crosswalk(self) -> None:
        correspondence = self.spec["uccs"]["correspondence"]
        self.assertEqual(correspondence["claim_type"], "DMI_INFERENCE")
        self.assertIn("this_is_not_a_bls_crosswalk", correspondence)

    def test_d_the_four_shelter_uccs_are_the_track_a_inputs(self) -> None:
        self.assertEqual(
            sorted(self.spec["uccs"]["track_a_inputs"]), sorted(est.SHELTER_UCCS)
        )

    def test_e_substituting_a_counterpart_value_is_prohibited(self) -> None:
        prohibited = " ".join(self.spec["estimator"]["prohibited_here"]).lower()
        self.assertIn("substituting a published counterpart", prohibited)
        forbidden = self.spec["uccs"]["correspondence"][
            "what_the_pairing_may_not_be_used_for"
        ]
        joined = " ".join(forbidden).lower()
        self.assertIn("910107", joined)
        self.assertIn("910103", joined)

    def test_f_the_plan_records_what_had_already_been_seen(self) -> None:
        block = self.spec["frozen_before_any_amount_was_computed"]
        self.assertIn("what_had_already_been_seen_when_this_was_written", block)

    def test_g_the_rse_flag_is_declared_warning_only(self) -> None:
        flag = self.spec["thin_cells"]["high_rse_is_informational"]
        self.assertEqual(flag["status"], "WARNING_ONLY")
        self.assertIn("not", flag["explicitly_not"].lower())


class TestTheEstimatorCannotBeChangedSilently(unittest.TestCase):
    def test_a_matching_digests_are_accepted(self) -> None:
        spec = est.load_spec()
        est.assert_estimator_untouched(spec)

    def test_b_a_changed_digest_is_refused(self) -> None:
        spec = json.loads(json.dumps(est.load_spec()))
        name = est.PINNED_MODULES[0]
        spec["estimator"]["pinned_module_digests"][name] = "0" * 64
        with self.assertRaises(est.ShelterEstimationError) as caught:
            est.assert_estimator_untouched(spec)
        self.assertIn(name, str(caught.exception))

    def test_c_a_dropped_pin_is_refused(self) -> None:
        spec = json.loads(json.dumps(est.load_spec()))
        spec["estimator"]["pinned_module_digests"].pop(est.PINNED_MODULES[0])
        with self.assertRaises(est.ShelterEstimationError):
            est.assert_estimator_untouched(spec)

    def test_d_the_pinned_set_covers_the_modules_that_do_the_arithmetic(self) -> None:
        self.assertIn("dmi_research/detailed_inflation/pumd.py", est.PINNED_MODULES)


class TestAMissingEstimateIsNotAZero(unittest.TestCase):
    def test_a_a_cell_with_no_records_carries_nulls(self) -> None:
        cell = _cell(status=est.NO_RECORDS, mean=None, rse=None, records=0)
        self.assertIsNone(cell.annual_mean_per_consumer_unit)
        self.assertIsNone(cell.standard_error)

    def test_b_the_dataclass_refuses_a_no_records_cell_with_an_amount(self) -> None:
        with self.assertRaises(ValueError):
            est.ShelterCell(
                ucc="910106",
                population="Q1",
                cell_status=est.NO_RECORDS,
                unweighted_record_count=0,
                reporting_consumer_units=0,
                weighted_population=1000.0,
                annual_mean_per_consumer_unit=0.0,
                annual_aggregate_dollars=0.0,
                standard_error=0.0,
                relative_standard_error_pct=0.0,
                interval_low=0.0,
                interval_high=0.0,
                replicate_min=0.0,
                replicate_max=0.0,
                replicates_at_zero=0,
            )

    def test_c_the_emitted_csv_leaves_the_empty_cell_blank(self) -> None:
        rows = [
            line.split(",")
            for line in ESTIMATES_PATH.read_text(encoding="utf-8").splitlines()[1:]
        ]
        empty = [r for r in rows if r[0] == "910106" and r[1] == "Q1"]
        self.assertEqual(len(empty), 1, "expected exactly one 910106/Q1 row")
        self.assertEqual(empty[0][2], est.NO_RECORDS)
        self.assertEqual(empty[0][6], "", "the mean must be blank, not 0")

    def test_d_the_emitted_json_carries_null_not_zero(self) -> None:
        summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        cell = summary["shelter_estimates"]["910106/Q1"]
        self.assertEqual(cell["cell_status"], est.NO_RECORDS)
        self.assertIsNone(cell["annual_mean_per_consumer_unit"])

    def test_e_the_plan_binds_downstream_accounting_to_the_null(self) -> None:
        spec = est.load_spec()
        self.assertIn(
            "unresolved", spec["empty_and_missing_cells"]["downstream_obligation"]
        )


class TestNoRatioIsEverApplied(unittest.TestCase):
    def test_a_the_estimate_is_unchanged_by_an_absurd_published_value(self) -> None:
        cells = [_cell(ucc="910050", mean=1554.417207)]
        spec = json.loads(json.dumps(est.load_spec()))
        spec["counterpart_validation"]["published_targets_2024"]["values"]["910050"][
            "01"
        ] = 1
        comparisons = est.compare_counterparts(cells, spec)
        self.assertEqual(len(comparisons), 1)
        self.assertAlmostEqual(comparisons[0].estimated_mean, 1554.417207, places=9)
        self.assertAlmostEqual(comparisons[0].ratio, 1554.417207, places=6)

    def test_b_the_reported_estimate_is_the_cell_mean_exactly(self) -> None:
        cells = [_cell(ucc="910101", mean=63.377531)]
        comparisons = est.compare_counterparts(cells, est.load_spec())
        self.assertEqual(
            comparisons[0].estimated_mean, cells[0].annual_mean_per_consumer_unit
        )

    def test_c_no_shelter_ucc_appears_in_the_counterpart_comparison(self) -> None:
        cells = [_cell(ucc=u) for u in est.SHELTER_UCCS]
        self.assertEqual(est.compare_counterparts(cells, est.load_spec()), [])


class TestTheAssertedPairingIsMeasured(unittest.TestCase):
    def test_a_an_exact_twelve_times_relation_is_recognised(self) -> None:
        records = []
        for i in range(20):
            records.append(_record(f"cu{i}", "910050", 100.0 + i))
            records.append(_record(f"cu{i}", "910104", 12.0 * (100.0 + i)))
        s = adj.measure_pair(records, "910050", "910104")
        self.assertEqual(s.relation, adj.TWELVE_TIMES)
        self.assertEqual(s.exact_twelve_keys, 20)

    def test_b_a_weeks_owned_relation_is_recognised(self) -> None:
        records = []
        for i, weeks in enumerate([1, 1, 1, 2, 2, 4, 7]):
            records.append(_record(f"cu{i}", "910103", 5200.0))
            records.append(_record(f"cu{i}", "910107", 5200.0 * weeks / 52.0))
        s = adj.measure_pair(records, "910103", "910107")
        self.assertEqual(s.relation, adj.WEEKS_OWNED_SHARE)
        self.assertEqual(s.week_tally, {1: 3, 2: 2, 4: 1, 7: 1})

    def test_c_unrelated_amounts_are_not_given_a_relation(self) -> None:
        records = []
        for i, factor in enumerate([1.31, 2.06, 3.35, 4.09, 0.13, 1.77, 2.9]):
            records.append(_record(f"cu{i}", "910102", 250.0 + i))
            records.append(_record(f"cu{i}", "910106", factor * (250.0 + i)))
        s = adj.measure_pair(records, "910102", "910106")
        self.assertEqual(s.relation, adj.NO_CLEAN_RELATION)

    def test_d_twelve_times_is_not_reported_as_weeks(self) -> None:
        records = [
            _record("cu0", "910050", 100.0),
            _record("cu0", "910104", 1200.0),
        ]
        s = adj.measure_pair(records, "910050", "910104")
        self.assertEqual(s.relation, adj.TWELVE_TIMES)

    def test_e_keys_present_on_only_one_side_are_counted_not_dropped(self) -> None:
        records = [
            _record("cu0", "910102", 100.0),
            _record("cu1", "910102", 100.0),
            _record("cu0", "910106", 200.0),
        ]
        s = adj.measure_pair(records, "910102", "910106")
        self.assertEqual(s.rows_published, 2)
        self.assertEqual(s.rows_concordance, 1)
        self.assertEqual(s.shared_keys, 1)
        self.assertEqual(s.published_only_keys, 1)

    def test_f_a_zero_denominator_is_excluded_from_ratios_only(self) -> None:
        records = [
            _record("cu0", "910050", 0.0),
            _record("cu0", "910104", 0.0),
            _record("cu1", "910050", 10.0),
            _record("cu1", "910104", 120.0),
        ]
        s = adj.measure_pair(records, "910050", "910104")
        self.assertEqual(s.shared_keys, 2)
        self.assertEqual(s.comparable_keys, 1)

    def test_g_the_month_is_part_of_the_key(self) -> None:
        records = [
            _record("cu0", "910050", 100.0, month=1),
            _record("cu0", "910104", 1200.0, month=2),
        ]
        s = adj.measure_pair(records, "910050", "910104")
        self.assertEqual(s.shared_keys, 0)


class TestUsabilityAndPrecisionStayApart(unittest.TestCase):
    def test_a_a_benchmarked_ucc_may_have_low_quality(self) -> None:
        """The combination the separation exists to permit."""
        cells = [
            _cell(ucc="910107", population=p, rse=40.0, replicates_at_zero=0)
            for p in pumd.POPULATIONS
        ]
        structure = adj.measure_pair(
            [
                _record("cu0", "910103", 5200.0),
                _record("cu0", "910107", 100.0),
            ],
            "910103",
            "910107",
        )
        verdict = adj.adjudicate_ucc("910107", cells, structure, {})
        self.assertEqual(verdict.pumd_quantitative_usability, adj.BENCHMARKED)
        self.assertEqual(verdict.pumd_estimate_quality, adj.QUALITY_LOW)

    def test_b_a_high_rse_alone_does_not_withhold_usability(self) -> None:
        low = [_cell(ucc="910107", population=p, rse=99.0) for p in pumd.POPULATIONS]
        high = [_cell(ucc="910107", population=p, rse=1.0) for p in pumd.POPULATIONS]
        structure = adj.measure_pair(
            [_record("cu0", "910103", 5200.0), _record("cu0", "910107", 100.0)],
            "910103",
            "910107",
        )
        a = adj.adjudicate_ucc("910107", low, structure, {})
        b = adj.adjudicate_ucc("910107", high, structure, {})
        self.assertEqual(
            a.pumd_quantitative_usability, b.pumd_quantitative_usability
        )

    def test_c_the_usability_tests_never_read_a_relative_standard_error(self) -> None:
        """Non-vacuity: mutate only the RSE and assert the tests do not move."""
        structure = adj.measure_pair(
            [_record("cu0", "910103", 5200.0), _record("cu0", "910107", 100.0)],
            "910103",
            "910107",
        )
        findings = set()
        for rse in (0.1, 5.0, 24.9, 25.1, 500.0):
            cells = [
                _cell(ucc="910107", population=p, rse=rse) for p in pumd.POPULATIONS
            ]
            verdict = adj.adjudicate_ucc("910107", cells, structure, {})
            findings.add(
                tuple((t.name, t.passed, t.finding) for t in verdict.tests)
            )
        self.assertEqual(len(findings), 1, "an RSE changed a usability test")

    def test_d_a_degenerate_replicate_set_does_move_usability(self) -> None:
        structure = adj.measure_pair(
            [_record("cu0", "910103", 5200.0), _record("cu0", "910107", 100.0)],
            "910103",
            "910107",
        )
        sound = [_cell(ucc="910107", population=p) for p in pumd.POPULATIONS]
        degenerate = [
            _cell(ucc="910107", population=p, replicates_at_zero=20)
            for p in pumd.POPULATIONS
        ]
        self.assertEqual(
            adj.adjudicate_ucc("910107", sound, structure, {})
            .pumd_quantitative_usability,
            adj.BENCHMARKED,
        )
        self.assertEqual(
            adj.adjudicate_ucc("910107", degenerate, structure, {})
            .pumd_quantitative_usability,
            adj.NOT_ESTABLISHED,
        )

    def test_e_track_a_cannot_admit_a_ucc_that_is_not_benchmarked(self) -> None:
        with self.assertRaises(ValueError):
            adj.UccAdjudication(
                ucc="910106",
                pumd_membership="VERIFIED",
                pumd_quantitative_usability=adj.NOT_ESTABLISHED,
                pumd_estimate_quality=adj.QUALITY_HIGH,
                per_population_quality={},
                tests=(),
                pair_relation=adj.NO_CLEAN_RELATION,
                counterpart_all_cu_ratio=None,
                counterpart_consistent=None,
                track_a_admissible=True,
                basis="",
            )

    def test_f_the_quality_bands_are_ordered_worst_last(self) -> None:
        self.assertEqual(
            adj.worst_quality(
                [adj.QUALITY_HIGH, adj.QUALITY_UNUSABLE, adj.QUALITY_MODERATE]
            ),
            adj.QUALITY_UNUSABLE,
        )
        self.assertEqual(
            adj.worst_quality([adj.QUALITY_HIGH, adj.QUALITY_HIGH]),
            adj.QUALITY_HIGH,
        )

    def test_g_an_empty_cell_is_unusable_not_high(self) -> None:
        self.assertEqual(
            adj.cell_quality(_cell(status=est.NO_RECORDS, mean=None, rse=None)),
            adj.QUALITY_UNUSABLE,
        )

    def test_h_a_cell_with_a_zero_replicate_is_degenerate(self) -> None:
        self.assertTrue(adj.cell_is_degenerate(_cell(replicates_at_zero=1)))
        self.assertFalse(adj.cell_is_degenerate(_cell(replicates_at_zero=0)))


class TestTheEmittedAdjudication(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(ADJUDICATION_PATH.read_text(encoding="utf-8"))

    def test_a_all_four_shelter_uccs_are_adjudicated(self) -> None:
        self.assertEqual(
            sorted(self.payload["adjudication"]), sorted(est.SHELTER_UCCS)
        )

    def test_b_the_verdicts_are_not_uniform(self) -> None:
        """The prompt forbade assuming one status applies to all four."""
        states = {
            v["pumd_quantitative_usability"]
            for v in self.payload["adjudication"].values()
        }
        self.assertGreater(len(states), 1)

    def test_c_the_usability_enum_stayed_two_state(self) -> None:
        for ucc, verdict in self.payload["adjudication"].items():
            with self.subTest(ucc=ucc):
                self.assertIn(
                    verdict["pumd_quantitative_usability"],
                    (adj.BENCHMARKED, adj.NOT_ESTABLISHED),
                )

    def test_d_every_ucc_carries_a_separate_quality_field(self) -> None:
        for ucc, verdict in self.payload["adjudication"].items():
            with self.subTest(ucc=ucc):
                self.assertIn(verdict["pumd_estimate_quality"], adj.QUALITY_ORDER)
                self.assertEqual(
                    sorted(verdict["per_population_quality"]),
                    sorted(pumd.POPULATIONS),
                )

    def test_e_a_withheld_ucc_is_absent_from_track_a(self) -> None:
        for ucc, verdict in self.payload["adjudication"].items():
            with self.subTest(ucc=ucc):
                if verdict["pumd_quantitative_usability"] != adj.BENCHMARKED:
                    self.assertNotIn(ucc, self.payload["track_a_admitted"])

    def test_f_the_published_item_texts_are_recorded_verbatim(self) -> None:
        self.assertEqual(
            self.payload["published_item_text"]["910103"],
            "Estimated annual rental value of timeshare",
        )
        for ucc in ("910050", "910101", "910102"):
            with self.subTest(ucc=ucc):
                self.assertIn("monthly", self.payload["published_item_text"][ucc])

    def test_g_the_timeshare_pair_is_recorded_as_a_different_estimand(self) -> None:
        verdict = self.payload["adjudication"]["910107"]
        self.assertEqual(verdict["pair_relation"], adj.WEEKS_OWNED_SHARE)
        warnings = " ".join(verdict["warnings"]).lower()
        self.assertIn("not the same estimand", warnings)

    def test_h_a_counterpart_that_failed_its_description_is_not_hidden(self) -> None:
        consistency = self.payload["counterpart_ratio_consistency"]
        failed = [u for u, e in consistency.items() if not e["consistent"]]
        self.assertTrue(failed, "expected the 910103 inconsistency to be recorded")
        for ucc in failed:
            with self.subTest(ucc=ucc):
                verdict = self.payload["adjudication"][adj.CONCORDANCE_OF[ucc]]
                self.assertFalse(verdict["counterpart_consistent"])
                self.assertTrue(verdict["warnings"])


class TestResearchFirewall(unittest.TestCase):
    def test_a_no_shelter_artifact_sits_outside_the_research_tree(self) -> None:
        for path in (
            ESTIMATES_PATH,
            SUMMARY_PATH,
            ADJUDICATION_PATH,
            SPEC_PATH,
        ):
            with self.subTest(path=path.name):
                relative = path.relative_to(REPO_ROOT).as_posix()
                self.assertTrue(
                    relative.startswith("data/research/")
                    or relative.startswith("registry/research/"),
                    f"{relative} is outside the research tree",
                )

    SHELTER_MODULES = (
        "dmi_research/detailed_inflation/shelter_estimation.py",
        "dmi_research/detailed_inflation/shelter_adjudication.py",
        "scripts/estimate_shelter_2024.py",
        "scripts/adjudicate_shelter_2024.py",
    )

    def test_b_nothing_imports_the_production_calculator(self) -> None:
        """Checked on the parse tree, not on the text.

        A substring scan would fire on this task's own docstrings, which say
        in prose that they do not touch the calculator. Scanning the imports
        asks the question that matters instead of a question that happens to
        be easy.
        """
        for relative in self.SHELTER_MODULES:
            tree = ast.parse((REPO_ROOT / relative).read_text(encoding="utf-8"))
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
            with self.subTest(module=relative):
                self.assertFalse(
                    {m for m in imported if m.split(".")[0] == "dmi_calculator"},
                    f"{relative} imports the production calculator",
                )

    def test_b2_no_string_literal_names_a_production_output_path(self) -> None:
        """Docstrings excluded, because prose about the firewall is not a breach."""
        for relative in self.SHELTER_MODULES:
            tree = ast.parse((REPO_ROOT / relative).read_text(encoding="utf-8"))
            docstrings = {
                id(node.body[0].value)
                for node in ast.walk(tree)
                if isinstance(
                    node,
                    (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                )
                and node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            }
            literals = [
                node.value
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ]
            for token in ("data/outputs", "deploy/data/outputs"):
                with self.subTest(module=relative, token=token):
                    self.assertFalse(
                        [text for text in literals if token in text],
                        f"{relative} names {token} outside a docstring",
                    )

    def test_b3_every_path_the_modules_write_to_is_under_research(self) -> None:
        """Non-vacuity: the walk must actually have found the output paths."""
        found = 0
        for module in (est, adj):
            for name in dir(module):
                value = getattr(module, name)
                if not isinstance(value, Path):
                    continue
                try:
                    relative = value.relative_to(REPO_ROOT).as_posix()
                except ValueError:
                    continue
                found += 1
                with self.subTest(module=module.__name__, constant=name):
                    self.assertTrue(
                        relative.startswith("data/research/")
                        or relative.startswith("registry/research/")
                        or relative == ".",
                        f"{module.__name__}.{name} points at {relative}",
                    )
        self.assertGreaterEqual(found, 4, "the constant walk found nothing to check")

    def test_c_the_artifacts_declare_themselves_research_only(self) -> None:
        for path in (SUMMARY_PATH, ADJUDICATION_PATH, SPEC_PATH):
            with self.subTest(path=path.name):
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(payload["status"], "RESEARCH_ONLY")


if __name__ == "__main__":
    unittest.main(verbosity=2)
