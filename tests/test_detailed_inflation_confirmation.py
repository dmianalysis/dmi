#!/usr/bin/env python3
"""Tests for the frozen-estimator confirmation gate (Phase B of the shelter task).

The confirmation exists to answer one question: does the estimator frozen at
95111fd still reproduce published LB01 values on UCCs that played no part in
building it? A confirmation that quietly re-tuned anything would answer a
different and worthless question, so most of what is tested here is not
arithmetic but the absence of freedom.

Four disciplines are checked structurally.

*The acceptance rule is inherited, not restated.* :func:`confirmation_spec`
must return a spec identical to the frozen one in every field except the
roster hash. The test enumerates the fields rather than spot-checking two of
them, so adding a threshold to :class:`BenchmarkSpec` without adding it to
:data:`THRESHOLD_FIELDS` is itself caught.

*The confirmation set is disjoint from the development set.* No UCC may appear
in both, and the four shelter UCCs may appear in neither.

*The set is the whole remainder, not a sample.* Included plus development must
equal the frozen eligible pool exactly. There is no room for a UCC to have
been dropped.

*The universe ledger is a partition.* Every UCC is accounted for exactly once,
under the first reason that applies, and the ledger's notion of eligibility is
checked against the frozen function rather than assumed to match it.

Mutation tests then break each of those disciplines in turn and assert the
break is detected, because a guard that would pass against a broken
implementation is not a guard.
"""

from __future__ import annotations

import csv
import dataclasses
import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dmi_research.detailed_inflation import pumd  # noqa: E402
from dmi_research.detailed_inflation import pumd_benchmark as bench  # noqa: E402
from dmi_research.detailed_inflation import pumd_confirmation as confirm  # noqa: E402

FROZEN_SPEC_PATH = REPO_ROOT / "registry/research/pumd_lb01_benchmark_spec_v0_1.json"
CONFIRM_SPEC_PATH = REPO_ROOT / "registry/research/pumd_lb01_confirmation_spec_v0_1.json"
OUTPUT_DIR = REPO_ROOT / "data/research/detailed_inflation/pumd_confirmation_2024"
UNIVERSE_PATH = OUTPUT_DIR / "candidate_universe.csv"
BENCHMARK_DIR = REPO_ROOT / "data/research/detailed_inflation/pumd_benchmark_2024"
MILESTONE_1 = REPO_ROOT / "data/research/detailed_inflation/audit_2024"
MILESTONE_2 = REPO_ROOT / "data/research/detailed_inflation/milestone_2"
STUB_DIR = Path.home() / "dev/dmi-data/pumd/2024/docs/stubs/stubs"

#: The Phase-B checkpoint the confirmation runs against. The confirmation may
#: not move it.
FROZEN_TAG = "dmi-detailed-inflation-v0.1-pumd-benchmark-2024"
FROZEN_COMMIT = "95111fd675f2d0287e5cc89398411e3322ad65a3"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


# ==========================================================================
# Synthetic universe for the construction tests
# ==========================================================================
#
# Twelve eligible UCCs in one node, plus six that fail one eligibility test
# each. The node spans all three strata, so the frozen development rule takes
# three of the twelve and the confirmation must take the other nine. Nine and
# three are different numbers on purpose: a confirmation roster that
# accidentally equalled the development roster, or the whole pool, would be
# visible immediately.


class SyntheticUniverse:
    NODE = "SYNTHETIC_NODE"

    def __init__(self):
        self.provenance: list[dict[str, str]] = []
        self.basis: list[dict[str, str]] = []
        self.interview: dict[str, pumd.StubEntry] = {}
        self.integrated: dict[str, pumd.StubEntry] = {}
        self.exceptions: list[str] = []
        self._mean = 1200.0

    def add(
        self,
        ucc: str,
        *,
        provenance_class: str = bench.REQUIRED_PROVENANCE_CLASS,
        ce_source: str = bench.REQUIRED_CE_SOURCE,
        node: str | None = None,
        interview_section: str | None = "EXPEND",
        integrated_section: str | None = "EXPEND",
        integrated_survey: str = "I",
        factor: int = 1,
        codes=bench.REQUIRED_CHARACTERISTICS,
        mean: float | None = None,
        blank_mean: bool = False,
        is_exception: bool = False,
    ) -> None:
        value = self._mean if mean is None else mean
        self._mean -= 50.0
        self.provenance.append(
            {
                "ucc": ucc,
                "provenance_class": provenance_class,
                "ce_source": ce_source,
                "dmi_node": node or self.NODE,
            }
        )
        if interview_section is not None:
            self.interview[ucc] = pumd.StubEntry(
                ucc, f"Item {ucc}", 1, "I", factor, interview_section
            )
        if integrated_section is not None:
            self.integrated[ucc] = pumd.StubEntry(
                ucc, f"Item {ucc}", 1, integrated_survey, factor, integrated_section
            )
        for code in codes:
            self.basis.append(
                {
                    "ucc": ucc,
                    "characteristics_code": code,
                    "item_text": f"Item {ucc}",
                    "domain_label": "Housing",
                    "mean_expenditure": "" if blank_mean else repr(value),
                    "rse": "5.00",
                }
            )
        if is_exception:
            self.exceptions.append(ucc)

    @property
    def args(self):
        return (
            self.provenance,
            self.basis,
            self.exceptions,
            self.interview,
            self.integrated,
        )


def synthetic() -> SyntheticUniverse:
    universe = SyntheticUniverse()
    for index in range(12):
        universe.add(f"{100000 + index}")
    universe.add("900001", provenance_class="CONCORDANCE_ONLY_UCC")
    universe.add("900002", ce_source="D")
    universe.add("900003", is_exception=True)
    universe.add("900004", interview_section="ADDENDA")
    universe.add("900005", integrated_survey="D")
    universe.add("900006", codes=("01", "02", "03"))
    return universe


# ==========================================================================
# Construction of the confirmation set
# ==========================================================================


class TestConfirmationSetConstruction(unittest.TestCase):
    def setUp(self):
        self.universe = synthetic()
        self.ledger = confirm.classify_universe(*self.universe.args)
        self.roster = confirm.confirmation_roster(*self.universe.args)
        self.development = bench.select_roster(*self.universe.args)
        self.pool = bench.eligible_candidates(*self.universe.args)

    def test_a_the_pool_and_development_roster_are_what_the_fixture_intends(self):
        # Assert the fixture before asserting anything about the thing under
        # test, so a fixture that stopped discriminating is caught here.
        self.assertEqual(len(self.pool), 12)
        self.assertEqual(len(self.development), 3)

    def test_b_confirmation_is_the_whole_remainder(self):
        self.assertEqual(len(self.roster), 9)
        confirmation = {entry.ucc for entry in self.roster}
        development = {entry.ucc for entry in self.development}
        eligible = {candidate.ucc for candidate in self.pool}
        self.assertEqual(confirmation | development, eligible)

    def test_c_confirmation_and_development_are_disjoint(self):
        confirmation = {entry.ucc for entry in self.roster}
        development = {entry.ucc for entry in self.development}
        self.assertEqual(confirmation & development, set())

    def test_d_the_ledger_partitions_the_universe(self):
        self.assertEqual(len(self.ledger), len(self.universe.provenance))
        self.assertEqual(
            len({row.ucc for row in self.ledger}), len(self.universe.provenance)
        )
        included = sum(1 for row in self.ledger if row.status == confirm.INCLUDED)
        excluded = sum(1 for row in self.ledger if row.status == confirm.EXCLUDED)
        self.assertEqual(included + excluded, len(self.ledger))
        self.assertEqual(included, len(self.roster))
        self.assertEqual(sum(confirm.exclusion_tally(self.ledger).values()), excluded)

    def test_e_every_exclusion_reason_is_one_of_the_declared_reasons(self):
        for row in self.ledger:
            if row.status == confirm.EXCLUDED:
                self.assertIn(row.exclusion_reason, confirm.EXCLUSION_REASONS)

    def test_f_each_eligibility_failure_is_attributed_to_its_own_reason(self):
        reasons = {row.ucc: row.exclusion_reason for row in self.ledger}
        self.assertEqual(reasons["900001"], "NOT_DIRECT_CONCORDANCE_UCC")
        self.assertEqual(reasons["900002"], "CE_SOURCE_NOT_INTERVIEW")
        self.assertEqual(reasons["900003"], "MILESTONE_1_EXCEPTION")
        self.assertEqual(reasons["900004"], "INTERVIEW_STUB_SECTION_NOT_EXPEND")
        self.assertEqual(reasons["900005"], "INTEGRATED_STUB_SURVEY_NOT_INTERVIEW")
        self.assertEqual(reasons["900006"], "INCOMPLETE_LB01_PUBLICATION")

    def test_g_the_construction_is_deterministic(self):
        again = confirm.confirmation_roster(*self.universe.args)
        self.assertEqual(bench.roster_hash(self.roster), bench.roster_hash(again))
        self.assertEqual(
            [entry.ucc for entry in self.roster], [entry.ucc for entry in again]
        )

    def test_h_shelter_uccs_can_never_enter_the_confirmation_roster(self):
        universe = synthetic()
        for ucc in bench.EXCLUDED_FROM_CALIBRATION:
            universe.add(ucc)
        ledger = confirm.classify_universe(*universe.args)
        roster = confirm.confirmation_roster(*universe.args)
        self.assertEqual(
            {entry.ucc for entry in roster} & set(bench.EXCLUDED_FROM_CALIBRATION), set()
        )
        reasons = {row.ucc: row.exclusion_reason for row in ledger}
        for ucc in bench.EXCLUDED_FROM_CALIBRATION:
            self.assertEqual(reasons[ucc], "MILESTONE_2_SHELTER_UCC")

    def test_i_an_unresolved_annualization_factor_is_excluded_not_guessed(self):
        universe = synthetic()
        universe.add("900007", factor=4)
        ledger = confirm.classify_universe(*universe.args)
        roster = confirm.confirmation_roster(*universe.args)
        reasons = {row.ucc: row.exclusion_reason for row in ledger}
        self.assertEqual(reasons["900007"], "UNRESOLVED_ANNUALIZATION_TRANSFORMATION")
        self.assertNotIn("900007", {entry.ucc for entry in roster})

    def test_j_strata_labels_come_from_the_frozen_stratification(self):
        strata = bench.assign_magnitude_strata(self.pool)
        for entry in self.roster:
            self.assertEqual(entry.magnitude_stratum, strata[entry.ucc])

    def test_k_node_completeness_is_not_required_of_a_confirmation_ucc(self):
        # The development rule drops a node that does not span all three
        # strata. That device exists to balance a fifteen-UCC roster and must
        # not silently shrink the confirmation set.
        universe = synthetic()
        universe.add("800001", node="THIN_NODE", mean=25.0)
        roster = confirm.confirmation_roster(*universe.args)
        development = bench.select_roster(*universe.args)
        self.assertNotIn("THIN_NODE", {entry.dmi_node for entry in development})
        self.assertIn("800001", {entry.ucc for entry in roster})


# ==========================================================================
# The acceptance rule is inherited, not restated
# ==========================================================================


class TestAcceptanceRuleIsInherited(unittest.TestCase):
    def setUp(self):
        self.frozen = bench.BenchmarkSpec.from_json(FROZEN_SPEC_PATH)
        self.roster = confirm.confirmation_roster(*synthetic().args)
        self.spec = confirm.confirmation_spec(self.frozen, self.roster)

    def test_a_every_field_except_the_roster_hash_is_unchanged(self):
        for field in dataclasses.fields(bench.BenchmarkSpec):
            if field.name == "roster_hash":
                continue
            with self.subTest(field=field.name):
                self.assertEqual(
                    getattr(self.spec, field.name), getattr(self.frozen, field.name)
                )

    def test_b_the_declared_threshold_list_covers_every_non_hash_field(self):
        # If a threshold is ever added to BenchmarkSpec, this fails until it is
        # added to THRESHOLD_FIELDS, so the enumeration cannot fall behind.
        declared = set(confirm.THRESHOLD_FIELDS)
        actual = {
            field.name
            for field in dataclasses.fields(bench.BenchmarkSpec)
            if field.name != "roster_hash"
        }
        self.assertEqual(declared, actual)

    def test_c_the_roster_hash_is_repointed(self):
        self.assertEqual(self.spec.roster_hash, bench.roster_hash(self.roster))
        self.assertNotEqual(self.spec.roster_hash, self.frozen.roster_hash)

    def test_d_the_confirmation_refuses_a_spec_that_is_not_v0_2(self):
        stale = dataclasses.replace(self.frozen, spec_version="v0.1")
        with self.assertRaises(confirm.ConfirmationError):
            confirm.confirmation_spec(stale, self.roster)

    def test_e_the_confirmation_refuses_a_stale_roster_rule_version(self):
        stale = dataclasses.replace(self.frozen, roster_version="v0.1")
        with self.assertRaises(confirm.ConfirmationError):
            confirm.confirmation_spec(stale, self.roster)

    def test_f_a_loosened_threshold_is_visible_as_an_inequality(self):
        # Mutation: the guard above must actually discriminate.
        loosened = dataclasses.replace(self.frozen, median_abs_pct_error_max=99.0)
        mutated = confirm.confirmation_spec(loosened, self.roster)
        self.assertNotEqual(
            mutated.median_abs_pct_error_max, self.frozen.median_abs_pct_error_max
        )
        differing = [
            field.name
            for field in dataclasses.fields(bench.BenchmarkSpec)
            if field.name != "roster_hash"
            and getattr(mutated, field.name) != getattr(self.frozen, field.name)
        ]
        self.assertEqual(differing, ["median_abs_pct_error_max"])


# ==========================================================================
# Mutation: the ledger must not be allowed to drift from the frozen rule
# ==========================================================================


class TestLedgerAgreesWithTheFrozenEligibilityRule(unittest.TestCase):
    def test_a_agreement_is_checked_and_not_assumed(self):
        universe = synthetic()
        roster = confirm.confirmation_roster(*universe.args)
        self.assertEqual(len(roster), 9)

    def test_b_a_ledger_that_disagrees_raises_rather_than_reporting(self):
        universe = synthetic()
        original = confirm._exclusion_reason

        def mutated(row, *args, **kwargs):
            # Drop one genuinely eligible UCC by inventing a reason for it.
            if row["ucc"] == "100005":
                return "MILESTONE_1_EXCEPTION"
            return original(row, *args, **kwargs)

        confirm._exclusion_reason = mutated
        try:
            with self.assertRaises(confirm.ConfirmationError) as caught:
                confirm.confirmation_roster(*universe.args)
            self.assertIn("100005", str(caught.exception))
        finally:
            confirm._exclusion_reason = original

    def test_c_a_ledger_that_admits_an_ineligible_ucc_raises(self):
        universe = synthetic()
        original = confirm._exclusion_reason

        def mutated(row, *args, **kwargs):
            if row["ucc"] == "900002":  # Diary-sourced, must stay out
                return ""
            return original(row, *args, **kwargs)

        confirm._exclusion_reason = mutated
        try:
            with self.assertRaises(confirm.ConfirmationError) as caught:
                confirm.confirmation_roster(*universe.args)
            self.assertIn("900002", str(caught.exception))
        finally:
            confirm._exclusion_reason = original


# ==========================================================================
# The frozen artifacts on disk
# ==========================================================================


class TestFrozenConfirmationArtifacts(unittest.TestCase):
    def setUp(self):
        if not CONFIRM_SPEC_PATH.exists():
            self.skipTest("the confirmation specification has not been frozen yet")
        self.payload = json.loads(CONFIRM_SPEC_PATH.read_text(encoding="utf-8"))

    def test_a_the_spec_pins_the_phase_b_estimator(self):
        estimator = self.payload["frozen_estimator"]
        self.assertEqual(estimator["commit"], FROZEN_COMMIT)
        self.assertEqual(estimator["tag"], FROZEN_TAG)
        self.assertEqual(estimator["roster_selection_rule_version"], bench.ROSTER_VERSION)

    def test_b_the_estimator_modules_are_unedited_since_the_freeze(self):
        for module, digest in self.payload["frozen_estimator"]["module_sha256"].items():
            with self.subTest(module=module):
                self.assertEqual(confirm.file_digest(REPO_ROOT / module), digest)

    def test_c_the_frozen_benchmark_spec_is_unedited_since_the_freeze(self):
        self.assertEqual(
            confirm.file_digest(FROZEN_SPEC_PATH),
            self.payload["frozen_benchmark_spec"]["file_sha256"],
        )

    def test_d_no_threshold_was_changed_for_the_confirmation(self):
        self.assertEqual(self.payload["acceptance_rule"]["thresholds_changed_for_confirmation"], [])
        frozen = json.loads(FROZEN_SPEC_PATH.read_text(encoding="utf-8"))["acceptance_rule"]
        stated = self.payload["acceptance_rule"]
        for key, value in frozen.items():
            if key in stated:
                with self.subTest(threshold=key):
                    self.assertEqual(stated[key], value)

    def test_e_the_spec_pins_the_archive_digest_from_the_source_registry(self):
        registry = json.loads(
            (REPO_ROOT / "registry/research/pumd_2024_interview_source_v0_1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            self.payload["pumd_source"]["archive_sha256"],
            registry["archives"]["INTRVW24"]["sha256"],
        )

    def test_f_the_universe_ledger_matches_the_digest_the_spec_pins(self):
        self.assertTrue(UNIVERSE_PATH.exists())
        self.assertEqual(
            confirm.file_digest(UNIVERSE_PATH),
            self.payload["candidate_universe"]["ledger_sha256"],
        )

    def test_g_the_ledger_accounts_for_every_ucc_exactly_once(self):
        rows = read_csv(UNIVERSE_PATH)
        universe = self.payload["candidate_universe"]
        self.assertEqual(len(rows), universe["total_uccs"])
        self.assertEqual(len({row["ucc"] for row in rows}), universe["total_uccs"])
        included = [r for r in rows if r["status"] == confirm.INCLUDED]
        excluded = [r for r in rows if r["status"] == confirm.EXCLUDED]
        self.assertEqual(len(included), universe["included_count"])
        self.assertEqual(len(excluded), universe["excluded_count"])
        self.assertEqual(len(included) + len(excluded), universe["total_uccs"])
        self.assertEqual(sum(universe["exclusions_by_reason"].values()), len(excluded))

    def test_h_the_included_set_is_the_confirmation_roster(self):
        rows = read_csv(UNIVERSE_PATH)
        included = {r["ucc"] for r in rows if r["status"] == confirm.INCLUDED}
        entries = {row["ucc"] for row in self.payload["confirmation_roster"]["entries"]}
        self.assertEqual(included, entries)
        self.assertEqual(len(entries), self.payload["confirmation_roster"]["size"])

    def test_i_the_confirmation_roster_is_disjoint_from_the_development_roster(self):
        development = {
            row["ucc"] for row in read_csv(BENCHMARK_DIR / "benchmark_roster.csv")
        }
        confirmation = {
            row["ucc"] for row in self.payload["confirmation_roster"]["entries"]
        }
        self.assertEqual(development & confirmation, set())
        self.assertEqual(len(development), 15)

    def test_j_no_shelter_ucc_appears_in_the_confirmation_roster(self):
        confirmation = {
            row["ucc"] for row in self.payload["confirmation_roster"]["entries"]
        }
        self.assertEqual(confirmation & set(bench.EXCLUDED_FROM_CALIBRATION), set())
        self.assertEqual(
            self.payload["excluded_from_calibration"],
            list(bench.EXCLUDED_FROM_CALIBRATION),
        )
        ledger = read_csv(UNIVERSE_PATH)
        by_ucc = {row["ucc"]: row for row in ledger}
        for ucc in bench.EXCLUDED_FROM_CALIBRATION:
            self.assertEqual(by_ucc[ucc]["exclusion_reason"], "MILESTONE_2_SHELTER_UCC")

    def test_k_the_comparison_count_is_six_populations_per_ucc(self):
        roster = self.payload["confirmation_roster"]
        self.assertEqual(
            roster["comparison_count"],
            roster["size"] * len(bench.REQUIRED_CHARACTERISTICS),
        )


# ==========================================================================
# The confirmation result on disk
# ==========================================================================


class TestConfirmationResult(unittest.TestCase):
    SUMMARY = OUTPUT_DIR / "confirmation_summary.json"
    RESULTS = OUTPUT_DIR / "confirmation_results.csv"

    def setUp(self):
        if not self.SUMMARY.exists():
            self.skipTest("the confirmation has not been run yet")
        self.summary = json.loads(self.SUMMARY.read_text(encoding="utf-8"))
        self.results = read_csv(self.RESULTS)
        self.spec = json.loads(CONFIRM_SPEC_PATH.read_text(encoding="utf-8"))

    def test_a_the_verdict_is_emitted_and_agrees_with_the_frozen_rule(self):
        self.assertIn(self.summary["confirmation_status"], ("PASS", "FAIL", "BLOCKED"))
        # The confirmation verdict is whatever the frozen summarize returned.
        # It is not computed a second time here or anywhere else.
        self.assertEqual(
            self.summary["confirmation_status"], self.summary["benchmark_status"]
        )

    def test_b_it_ran_against_the_frozen_v0_2_acceptance_rule(self):
        frozen = json.loads(FROZEN_SPEC_PATH.read_text(encoding="utf-8"))
        self.assertEqual(self.summary["spec_version"], frozen["spec_version"])
        self.assertEqual(self.summary["spec_version"], "v0.2")
        self.assertEqual(self.summary["roster_version"], bench.ROSTER_VERSION)
        self.assertEqual(self.summary["thresholds_changed_for_confirmation"], [])
        self.assertEqual(self.summary["frozen_estimator_commit"], FROZEN_COMMIT)

    def test_c_it_ran_against_the_roster_the_spec_froze(self):
        self.assertEqual(
            self.summary["roster_hash"], self.spec["confirmation_roster"]["roster_hash"]
        )
        self.assertNotEqual(
            self.summary["roster_hash"], self.summary["development_roster_hash"]
        )
        self.assertEqual(
            self.summary["roster_size"], self.spec["confirmation_roster"]["size"]
        )

    def test_d_every_frozen_ucc_was_run_and_none_was_dropped(self):
        frozen = {row["ucc"] for row in self.spec["confirmation_roster"]["entries"]}
        run = {row["ucc"] for row in self.results}
        self.assertEqual(run, frozen)
        self.assertEqual(
            len(self.results), self.spec["confirmation_roster"]["comparison_count"]
        )
        self.assertEqual(self.summary["comparison_count"], len(self.results))

    def test_e_every_ucc_was_compared_on_all_six_populations(self):
        seen: dict[str, set[str]] = {}
        for row in self.results:
            seen.setdefault(row["ucc"], set()).add(row["population"])
        expected = set(bench.LABSTAT_POPULATION_BY_CODE.values())
        for ucc, populations in seen.items():
            with self.subTest(ucc=ucc):
                self.assertEqual(populations, expected)

    def test_f_no_failing_ucc_was_removed_from_the_summary(self):
        # The pass fraction must be recomputable from the full result file,
        # including everything that failed.
        passes = sum(1 for row in self.results if row["benchmark_status"] == "PASS")
        self.assertAlmostEqual(
            self.summary["pass_fraction"], passes / len(self.results), places=12
        )
        self.assertLess(passes, len(self.results), "a run with no failure at all "
                        "would make this test vacuous; investigate before relaxing it")

    def test_g_no_shelter_ucc_appears_in_the_results(self):
        run = {row["ucc"] for row in self.results}
        self.assertEqual(run & set(bench.EXCLUDED_FROM_CALIBRATION), set())

    def test_h_the_results_are_disjoint_from_the_development_benchmark(self):
        development = {
            row["ucc"] for row in read_csv(BENCHMARK_DIR / "benchmark_results.csv")
        }
        run = {row["ucc"] for row in self.results}
        self.assertEqual(development & run, set())

    def test_i_small_value_cells_are_reported_and_not_silently_dropped(self):
        outcome = self.summary["small_value_outcome"]
        absolute = [r for r in self.results if r["judged_on"] == "ABSOLUTE_DIFFERENCE"]
        self.assertEqual(outcome["count"], len(absolute))
        self.assertEqual(
            self.summary["absolute_judged_count"] + self.summary["percentage_judged_count"],
            len(self.results),
        )
        self.assertEqual(outcome["pass_count"] + outcome["fail_count"], outcome["count"])

    def test_j_the_reported_metrics_are_recomputable_from_the_result_file(self):
        comparable = sorted(
            abs(float(row["percentage_difference"]))
            for row in self.results
            if row["judged_on"] == "PERCENTAGE_DIFFERENCE" and row["percentage_difference"]
        )
        self.assertEqual(len(comparable), self.summary["percentage_judged_count"])
        self.assertAlmostEqual(
            self.summary["median_abs_pct_error"], bench.percentile(comparable, 0.50), places=9
        )
        self.assertAlmostEqual(
            self.summary["p90_abs_pct_error"], bench.percentile(comparable, 0.90), places=9
        )
        self.assertAlmostEqual(self.summary["max_abs_pct_error"], comparable[-1], places=9)


# ==========================================================================
# Preservation: the confirmation may not disturb the Phase-B checkpoint
# ==========================================================================


class TestPhaseBIsPreserved(unittest.TestCase):
    def test_a_the_phase_b_benchmark_still_reports_pass(self):
        summary = json.loads(
            (BENCHMARK_DIR / "benchmark_summary.json").read_text(encoding="utf-8")
        )
        self.assertEqual(summary["benchmark_status"], "PASS")
        self.assertEqual(summary["failed_criteria"], [])
        self.assertEqual(summary["comparison_count"], 90)
        self.assertEqual(summary["roster_size"], 15)
        self.assertEqual(summary["roster_version"], "v0.2")

    def test_b_the_superseded_v0_1_failure_is_still_a_failure(self):
        path = BENCHMARK_DIR / "superseded/roster_v0_1/benchmark_summary.json"
        summary = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(summary["benchmark_status"], "FAIL")
        self.assertEqual(summary["roster_size"], 18)
        self.assertEqual(summary["comparison_count"], 108)

    def test_c_the_freeze_tag_points_at_the_phase_b_commit(self):
        resolved = subprocess.run(
            ["git", "rev-list", "-n", "1", FROZEN_TAG],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if resolved.returncode != 0:
            self.skipTest(f"tag {FROZEN_TAG} is not present in this clone")
        self.assertEqual(resolved.stdout.strip(), FROZEN_COMMIT)

    def test_d_the_phase_b_roster_still_hashes_to_what_its_spec_pins(self):
        spec = json.loads(FROZEN_SPEC_PATH.read_text(encoding="utf-8"))
        rows = read_csv(BENCHMARK_DIR / "benchmark_roster.csv")
        roster = [
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
            for row in rows
        ]
        self.assertEqual(bench.roster_hash(roster), spec["roster_hash"])


# ==========================================================================
# Firewall
# ==========================================================================


class TestResearchFirewall(unittest.TestCase):
    FORBIDDEN_ROOTS = ("data/outputs", "deploy/data/outputs")

    def test_a_the_confirmation_writes_nothing_operational(self):
        for root in self.FORBIDDEN_ROOTS:
            directory = REPO_ROOT / root
            if not directory.exists():
                continue
            for path in directory.rglob("*"):
                if path.is_file():
                    with self.subTest(path=str(path)):
                        self.assertNotIn("confirmation", path.name.lower())
                        self.assertNotIn("pumd", path.name.lower())

    def test_b_the_confirmation_modules_import_nothing_operational(self):
        forbidden = ("dmi_calculator", "deploy", "scripts.prepare_deployment")
        for module in (
            "dmi_research/detailed_inflation/pumd_confirmation.py",
            "scripts/confirm_pumd_2024.py",
        ):
            text = (REPO_ROOT / module).read_text(encoding="utf-8")
            for name in forbidden:
                with self.subTest(module=module, forbidden=name):
                    self.assertNotIn(f"import {name}", text)
                    self.assertNotIn(f"from {name}", text)

    def test_c_the_confirmation_writes_only_under_research_roots(self):
        text = (REPO_ROOT / "scripts/confirm_pumd_2024.py").read_text(encoding="utf-8")
        self.assertIn('"data/research/detailed_inflation/pumd_confirmation_2024"', text)
        self.assertNotIn("data/outputs", text)
        self.assertNotIn("deploy/data", text)


# ==========================================================================
# Against the real 2024 artifacts, skipped when the stub files are absent
# ==========================================================================


class TestAgainstRealArtifacts(unittest.TestCase):
    def setUp(self):
        if not (STUB_DIR / "CE-HG-Inter-2024.txt").exists():
            self.skipTest("2024 hierarchical grouping files not present")
        if not CONFIRM_SPEC_PATH.exists():
            self.skipTest("the confirmation specification has not been frozen yet")
        self.payload = json.loads(CONFIRM_SPEC_PATH.read_text(encoding="utf-8"))
        interview = pumd.read_stub_file(STUB_DIR / "CE-HG-Inter-2024.txt")
        integrated = pumd.read_stub_file(STUB_DIR / "CE-HG-Integ-2024.txt")
        provenance = read_csv(MILESTONE_2 / "ucc_provenance_classes_2024.csv")
        basis = read_csv(MILESTONE_1 / "active_ucc_basis.csv")
        exceptions = [row["ucc"] for row in read_csv(MILESTONE_1 / "exception_ledger.csv")]
        self.args = (provenance, basis, exceptions, interview, integrated)

    def test_a_the_roster_still_hashes_to_what_the_spec_pinned(self):
        roster = confirm.confirmation_roster(*self.args)
        self.assertEqual(
            bench.roster_hash(roster),
            self.payload["confirmation_roster"]["roster_hash"],
        )

    def test_b_the_universe_ledger_still_hashes_to_what_the_spec_pinned(self):
        universe = confirm.classify_universe(*self.args)
        self.assertEqual(
            confirm.universe_hash(universe),
            self.payload["candidate_universe"]["ledger_content_hash"],
        )

    def test_c_confirmation_plus_development_accounts_for_the_eligible_pool(self):
        pool = {c.ucc for c in bench.eligible_candidates(*self.args)}
        development = {e.ucc for e in bench.select_roster(*self.args)}
        confirmation = {e.ucc for e in confirm.confirmation_roster(*self.args)}
        self.assertEqual(confirmation & development, set())
        self.assertTrue(confirmation <= pool)
        # Anything eligible but in neither roster must be held out for a
        # reason the confirmation adds, and must be named as such. Asserting
        # the remainder is empty would be weaker: it would pass silently if a
        # UCC were dropped for no recorded reason.
        ledger = {row.ucc: row for row in confirm.classify_universe(*self.args)}
        for ucc in sorted(pool - development - confirmation):
            with self.subTest(ucc=ucc):
                self.assertIn(
                    ledger[ucc].exclusion_reason, confirm.CONFIRMATION_ADDED_REASONS
                )

    def test_d_all_58_milestone_1_exceptions_appear_in_the_ledger(self):
        exceptions = {row["ucc"] for row in read_csv(MILESTONE_1 / "exception_ledger.csv")}
        ledger = {row.ucc: row for row in confirm.classify_universe(*self.args)}
        self.assertEqual(len(exceptions), 58)
        for ucc in exceptions:
            with self.subTest(ucc=ucc):
                self.assertIn(ucc, ledger)
                self.assertEqual(ledger[ucc].status, confirm.EXCLUDED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
