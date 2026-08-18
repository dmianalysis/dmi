#!/usr/bin/env python3
"""Tests for the Track-A / Track-B shelter construction (Phase D).

The amounts are not the interesting thing to test. What needs testing is the
set of disciplines that keep the amounts honest, because every one of them
would still produce a plausible-looking table if it had quietly stopped
holding.

*The accounting is not forced to balance.* Replacing owner outlays with an
imputed rental flow changes the size of the basis by 1.6 trillion dollars. The
temptation is to make that go away. Tests assert that delta_shelter is large
and non-zero, that no scaling or residual-allocation term exists anywhere in
the module, and that the only sums checked are each total against its own
parts.

*A PROPOSED rule moves nothing.* Not the expenditure it claims, not the
buckets, not the tracks. Tests flip a held verdict to accepted in a synthetic
copy, observe the amounts move, and then assert that under the real verdicts
they sit in the pending bucket instead.

*A withheld estimate is not zero.* 910106 failed adjudication and its first
quintile has no records at all. Tests assert the gap is reported with a size
where one exists and left blank where none does, in the dataclass, the CSV and
the JSON.

*Nothing is removed merely for being housing-associated.* Utilities and renter
rent are priced separately by the CPI and must survive a change in owner
shelter treatment. That failure would be silent, so it gets a test.

*Track B is a payments concept, and only that.* Tests assert that no artifact
calls it the Household Cost Index.

*The predecessors survive.* Milestone 2's registries are read and never
written. Tests assert the successor paths differ from the predecessor paths,
that every v0.1 rule survives into v0.2, and that no evidence grade moved.
"""

from __future__ import annotations

import ast
import csv
import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dmi_research.detailed_inflation import pumd  # noqa: E402
from dmi_research.detailed_inflation import shelter_estimation as est  # noqa: E402
from dmi_research.detailed_inflation import shelter_adjudication as adj  # noqa: E402
from dmi_research.detailed_inflation import shelter_tracks as tracks  # noqa: E402

SHELTER_DIR = REPO_ROOT / "data/research/detailed_inflation/shelter_2024"


def _inputs():
    """Everything the Phase-D builder reads, loaded once per test class."""
    registry = tracks.load_scope_rules()
    adjudication = json.loads(adj.ADJUDICATION_PATH.read_text(encoding="utf-8"))
    reconciliation = tracks.load_reconciliation()
    aggregates = tracks.load_shelter_aggregates()
    basis = tracks.load_basis()
    verdicts = tracks.adjudicate_rules(registry, adjudication, aggregates, basis)
    return registry, adjudication, reconciliation, aggregates, basis, verdicts


class BuiltOnce:
    """One build, shared by the classes that only read it."""

    @classmethod
    def setUpClass(cls) -> None:
        (
            cls.registry,
            cls.adjudication,
            cls.reconciliation,
            cls.aggregates,
            cls.basis,
            cls.verdicts,
        ) = _inputs()
        cls.track_a, cls.track_b = tracks.build_tracks(
            cls.registry, cls.verdicts, cls.aggregates, cls.basis, cls.adjudication
        )
        cls.accounting = tracks.build_accounting(
            cls.reconciliation,
            cls.verdicts,
            cls.registry,
            cls.aggregates,
            cls.basis,
            cls.adjudication,
        )
        cls.audit = tracks.build_double_counting_audit(
            cls.registry, cls.verdicts, cls.aggregates, cls.basis, cls.adjudication
        )


# ---------------------------------------------------------------------------
# Group 1: the accounting does not balance and is not made to
# ---------------------------------------------------------------------------


class TestAccountingIsNotForcedToBalance(BuiltOnce, unittest.TestCase):
    def test_a_delta_shelter_is_large_and_nonzero_in_every_population(self) -> None:
        """The gap is the finding. A zero here would mean it had been closed."""
        for population, entry in self.accounting.items():
            with self.subTest(population=population):
                self.assertNotEqual(entry.delta_shelter, 0.0)
                self.assertGreater(
                    abs(entry.delta_shelter),
                    0.05 * entry.e_source,
                    "delta_shelter is suspiciously close to zero relative to "
                    "the basis, which is what a balancing step would produce",
                )

    def test_b_delta_shelter_equals_its_two_terms_and_nothing_else(self) -> None:
        for population, entry in self.accounting.items():
            with self.subTest(population=population):
                self.assertAlmostEqual(
                    entry.delta_shelter,
                    entry.rental_equivalence_introduced - entry.owner_outlays_removed,
                    places=6,
                )

    def test_c_the_source_buckets_reconstruct_the_milestone_2_basis(self) -> None:
        for population, entry in self.accounting.items():
            with self.subTest(population=population):
                parts = (
                    entry.retained
                    + entry.accepted_transformed
                    + entry.accepted_out_of_scope
                    + entry.pending_proposed
                    + entry.unresolved_open
                )
                self.assertAlmostEqual(parts, entry.e_source, places=6)
                self.assertAlmostEqual(
                    entry.e_source,
                    self.reconciliation[population]["ce_observed_basis"],
                    places=6,
                )

    def test_d_the_cpi_basis_equals_what_was_put_into_it(self) -> None:
        for population, entry in self.accounting.items():
            with self.subTest(population=population):
                self.assertAlmostEqual(
                    entry.e_cpi,
                    entry.retained
                    + entry.accepted_transformed
                    + entry.rental_equivalence_introduced,
                    places=6,
                )
                self.assertAlmostEqual(
                    entry.delta_scope, entry.e_cpi - entry.e_source, places=6
                )

    def test_e_a_fabricated_balance_is_rejected(self) -> None:
        """Mutation. Move one bucket so the parts no longer make the whole.

        The check exists to catch a bucket going astray, not to certify that
        the two bases agree. This asserts it fires.
        """
        entry = self.accounting["ALL_CU"]
        with self.assertRaises(tracks.ShelterTrackError):
            replace(entry, retained=entry.retained + 1000.0)
        with self.assertRaises(tracks.ShelterTrackError):
            replace(entry, e_cpi=entry.e_source)

    def test_f_equalising_the_two_bases_is_not_what_the_checks_ask(self) -> None:
        """Non-vacuity for the test above.

        A checker that merely demanded e_cpi == e_source would also reject the
        mutation, and would be the exact defect Phase D forbids. Construct an
        entry whose bases differ enormously but whose parts are internally
        consistent, and assert it is accepted.
        """
        entry = tracks.PopulationAccounting(
            population="SYNTHETIC",
            e_source=100.0,
            retained=40.0,
            accepted_transformed=10.0,
            accepted_out_of_scope=30.0,
            pending_proposed=15.0,
            unresolved_open=5.0,
            rental_equivalence_introduced=900.0,
            rental_equivalence_withheld=None,
            owner_outlays_removed=30.0,
            e_cpi=950.0,
            delta_scope=850.0,
            delta_shelter=870.0,
            secondary_residence_outlays_removed_without_replacement=0.0,
        )
        self.assertEqual(entry.e_cpi / entry.e_source, 9.5)

    def test_g_no_balancing_vocabulary_appears_in_the_module(self) -> None:
        """No rescaling, renormalisation, residual allocation or fudge factor.

        Checked on identifiers in the parse tree rather than on the text, so
        that the module's own prose saying it does not rescale cannot satisfy
        the test.
        """
        source = tracks.__file__
        tree = ast.parse(Path(source).read_text(encoding="utf-8"))
        forbidden = (
            "rescale",
            "renormalise",
            "renormalize",
            "normalise",
            "normalize",
            "balancing_factor",
            "residual_allocation",
            "fudge",
            "calibrat",
        )
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.arg):
                names.add(node.arg)
        for name in sorted(names):
            for word in forbidden:
                self.assertNotIn(
                    word,
                    name.lower(),
                    f"identifier {name!r} suggests a balancing step",
                )


# ---------------------------------------------------------------------------
# Group 2: a PROPOSED rule moves nothing
# ---------------------------------------------------------------------------


class TestPendingRulesHaveNoEffect(BuiltOnce, unittest.TestCase):
    HELD = (
        "OS_CPI_OWNER_STRUCTURE_INVESTMENT_v0_1",
        "RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1",
        tracks.TRACK_A_SECONDARY_RULE_ID,
    )

    def test_a_the_held_rules_are_the_expected_three(self) -> None:
        held = sorted(
            r for r, v in self.verdicts.items() if v.review_status != tracks.ACCEPTED
        )
        self.assertEqual(held, sorted(self.HELD))

    def test_b_every_held_rule_states_a_blocker(self) -> None:
        for rule_id in self.HELD:
            with self.subTest(rule=rule_id):
                verdict = self.verdicts[rule_id]
                self.assertFalse(verdict.is_applicable)
                self.assertEqual(verdict.resolution_state, tracks.PENDING)
                self.assertTrue(verdict.blocker)
                self.assertGreater(len(verdict.blocker or ""), 80)

    def test_c_held_expenditure_sits_in_the_pending_bucket(self) -> None:
        by_id = tracks.rules_by_id(self.registry)
        for population, entry in self.accounting.items():
            with self.subTest(population=population):
                expected = sum(
                    tracks.rule_materiality(by_id[r])[population]
                    for r in tracks.PENDING_RULE_IDS
                    if self.verdicts[r].review_status != tracks.ACCEPTED
                )
                self.assertAlmostEqual(entry.pending_proposed, expected, places=6)

    def test_d_held_uccs_are_neither_retained_nor_removed_in_track_a(self) -> None:
        by_disposition = {row.ucc: row.disposition for row in self.track_a}
        by_id = tracks.rules_by_id(self.registry)
        for rule_id in ("OS_CPI_OWNER_STRUCTURE_INVESTMENT_v0_1",
                        "RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1"):
            for ucc in by_id[rule_id]["source_uccs"]:
                with self.subTest(rule=rule_id, ucc=ucc):
                    self.assertEqual(
                        by_disposition[ucc],
                        tracks.PENDING_NEITHER_APPLIED_NOR_REVERSED,
                    )

    def test_e_injection_accepting_a_held_rule_would_move_the_money(self) -> None:
        """Non-vacuity. The bucket is not empty because the rule is trivial.

        Flip one held verdict to accepted in a synthetic copy and rebuild. If
        the amounts do not move, then the tests above prove nothing about
        PROPOSED status and everything about the rule claiming nothing.
        """
        rule_id = "OS_CPI_OWNER_STRUCTURE_INVESTMENT_v0_1"
        held = self.verdicts[rule_id]
        forced = dict(self.verdicts)
        forced[rule_id] = replace(
            held,
            review_status=tracks.ACCEPTED,
            resolution_state=tracks.EFFECTIVE,
            is_applicable=True,
            blocker=None,
        )
        moved = tracks.build_accounting(
            self.reconciliation,
            forced,
            self.registry,
            self.aggregates,
            self.basis,
            self.adjudication,
        )
        real = self.accounting["ALL_CU"]
        counterfactual = moved["ALL_CU"]
        claimed = held.materiality_all_cu
        self.assertGreater(claimed, 0.0)
        self.assertAlmostEqual(
            real.pending_proposed - counterfactual.pending_proposed, claimed, places=6
        )
        self.assertAlmostEqual(
            counterfactual.accepted_out_of_scope - real.accepted_out_of_scope,
            claimed,
            places=6,
        )

    def test_f_a_verdict_may_not_be_accepted_while_carrying_a_blocker(self) -> None:
        held = self.verdicts["OS_CPI_OWNER_STRUCTURE_INVESTMENT_v0_1"]
        with self.assertRaises(tracks.ShelterTrackError):
            replace(
                held,
                review_status=tracks.ACCEPTED,
                resolution_state=tracks.EFFECTIVE,
                is_applicable=True,
            )

    def test_g_an_evidence_grade_may_not_move_in_this_task(self) -> None:
        for verdict in self.verdicts.values():
            with self.subTest(rule=verdict.rule_id):
                self.assertFalse(verdict.evidence_strength_changed)
        with self.assertRaises(tracks.ShelterTrackError):
            replace(
                self.verdicts[tracks.TRACK_A_PRIMARY_RULE_ID],
                evidence_strength_changed=True,
            )

    def test_h_each_rule_answers_all_six_phase_d_questions(self) -> None:
        for rule_id, verdict in self.verdicts.items():
            with self.subTest(rule=rule_id):
                self.assertEqual(len(verdict.questions), 6)
                for question in verdict.questions:
                    self.assertTrue(question.question.endswith("?"))
                    self.assertTrue(question.answer)
                    self.assertGreater(len(question.finding), 40)


# ---------------------------------------------------------------------------
# Group 3: a withheld estimate is not a zero
# ---------------------------------------------------------------------------


class TestWithheldIsNotZero(BuiltOnce, unittest.TestCase):
    def test_a_910106_is_withheld_from_track_a(self) -> None:
        self.assertIn("910106", self.adjudication["track_a_withheld"])
        dispositions = {
            row.ucc: row.disposition
            for row in self.track_a
            if row.component == "RENTAL_EQUIVALENCE"
        }
        self.assertEqual(dispositions["910106"], tracks.WITHHELD)

    def test_b_the_withheld_amount_is_reported_not_absorbed(self) -> None:
        entry = self.accounting["ALL_CU"]
        self.assertIsNotNone(entry.rental_equivalence_withheld)
        self.assertGreater(entry.rental_equivalence_withheld or 0.0, 0.0)
        self.assertNotIn(
            entry.rental_equivalence_withheld,
            (entry.rental_equivalence_introduced,),
            "the withheld amount was added to the introduced amount",
        )

    def test_c_a_cell_with_no_records_stays_blank_rather_than_zero(self) -> None:
        """Q1 of 910106 has no records at all. That is not an amount of zero."""
        self.assertIsNone(self.accounting["Q1"].rental_equivalence_withheld)
        rows = list(csv.DictReader(tracks.COMPARISON_PATH.open(newline="")))
        cell = [
            r
            for r in rows
            if r["population"] == "Q1" and r["quantity"] == "rental_equivalence_withheld"
        ]
        self.assertEqual(len(cell), 1)
        self.assertEqual(cell[0]["millions"], "")

    def test_d_the_introduced_amount_contains_only_admitted_uccs(self) -> None:
        entry = self.accounting["ALL_CU"]
        primary = self.aggregates[("910104", "ALL_CU")]
        self.assertAlmostEqual(
            entry.rental_equivalence_introduced, primary or 0.0, places=6
        )

    def test_e_outlays_removed_without_replacement_are_counted_not_netted(
        self,
    ) -> None:
        """Owned-vacation financing leaves under an accepted rule.

        Its replacement is PENDING. The amount is reported as a gap; it is not
        subtracted from anything to make the gap disappear.
        """
        entry = self.accounting["ALL_CU"]
        stranded = entry.secondary_residence_outlays_removed_without_replacement
        self.assertGreater(stranded, 0.0)
        self.assertAlmostEqual(
            entry.delta_shelter,
            entry.rental_equivalence_introduced - entry.owner_outlays_removed,
            places=6,
            msg="the stranded amount was netted into delta_shelter",
        )


# ---------------------------------------------------------------------------
# Group 4: nothing is removed merely for being housing-associated
# ---------------------------------------------------------------------------


class TestSurvivalOfSeparatelyPricedCosts(BuiltOnce, unittest.TestCase):
    def _row(self, category: str):
        rows = [r for r in self.audit if r.category == category]
        self.assertEqual(len(rows), 1, category)
        return rows[0]

    def test_a_the_audit_covers_all_nine_required_categories(self) -> None:
        required = {
            "primary_residence_owner_shelter",
            "mortgage_interest_and_home_equity_interest",
            "residential_property_tax",
            "owner_repairs_improvements_structure_investment",
            "homeowners_insurance_primary_residence",
            "secondary_and_vacation_residence_costs",
            "renter_rent_and_renter_related_costs",
            "utilities",
            "rental_equivalence_addenda_910104_910107",
        }
        self.assertEqual({row.category for row in self.audit}, required)

    def test_b_utilities_survive_track_a(self) -> None:
        row = self._row("utilities")
        self.assertEqual(row.track_a_disposition, tracks.RETAINED)
        self.assertEqual(row.track_b_disposition, tracks.RETAINED)
        self.assertGreater(row.all_cu_expenditure or 0.0, 0.0)

    def test_c_renter_rent_survives_track_a(self) -> None:
        row = self._row("renter_rent_and_renter_related_costs")
        self.assertEqual(row.track_a_disposition, tracks.RETAINED)
        self.assertGreater(row.all_cu_expenditure or 0.0, 0.0)

    def test_d_no_shelter_rule_claims_a_utility_or_renter_ucc(self) -> None:
        """The structural reason the two tests above pass.

        A disposition is a statement about a rule's membership. If a shelter
        rule claimed one of these UCCs, RETAINED would be wrong even though
        the audit row said it.
        """
        claimed: set[str] = set()
        by_id = tracks.rules_by_id(self.registry)
        for rule_id in tracks.PENDING_RULE_IDS:
            claimed.update(by_id[rule_id]["source_uccs"])
        protected = set(tracks.UTILITY_UCCS) | set(tracks.RENTER_SHELTER_UCCS)
        self.assertEqual(claimed & protected, set())

    def test_e_every_removed_ucc_is_removed_by_a_named_effective_rule(self) -> None:
        for row in self.track_a:
            if row.disposition not in (
                tracks.REMOVED_OUT_OF_SCOPE,
                tracks.REMOVED_FOR_REPLACEMENT,
            ):
                continue
            with self.subTest(ucc=row.ucc):
                self.assertIsNotNone(row.rule_id)
                verdict = self.verdicts[row.rule_id or ""]
                self.assertEqual(verdict.review_status, tracks.ACCEPTED)

    def test_f_no_source_outlay_survives_track_a_against_its_own_rule(self) -> None:
        """The other half of the audit instruction.

        Every UCC claimed by a rule that is EFFECTIVE and removing must be
        gone from Track A. A retained row under such a rule would be the
        silent duplication the audit exists to prevent.
        """
        by_id = tracks.rules_by_id(self.registry)
        removed = {row.ucc for row in self.track_a if row.disposition.startswith("REMOVED")}
        for rule_id, verdict in self.verdicts.items():
            if not verdict.is_applicable or rule_id not in tracks.PENDING_RULE_IDS:
                continue
            for ucc in by_id[rule_id]["source_uccs"]:
                with self.subTest(rule=rule_id, ucc=ucc):
                    self.assertIn(ucc, removed)

    def test_g_the_audit_flags_its_open_items_explicitly(self) -> None:
        open_categories = {row.category for row in self.audit if row.is_open_item}
        self.assertEqual(
            open_categories,
            {
                "owner_repairs_improvements_structure_investment",
                "homeowners_insurance_primary_residence",
                "secondary_and_vacation_residence_costs",
            },
        )

    def test_h_homeowners_insurance_is_retained_whole_and_flagged(self) -> None:
        """The Casey 43 percent factor is recorded and deliberately not used."""
        row = self._row("homeowners_insurance_primary_residence")
        self.assertEqual(row.track_a_disposition, tracks.RETAINED)
        self.assertTrue(row.is_open_item)
        self.assertIn("43%", row.double_counting_finding)
        retained = tracks._sum_basis(
            tracks.HOMEOWNERS_INSURANCE_PRIMARY, self.basis, "ALL_CU"
        )
        self.assertAlmostEqual(row.all_cu_expenditure or 0.0, retained or 0.0, places=6)


# ---------------------------------------------------------------------------
# Group 5: Track B is a payments concept and only that
# ---------------------------------------------------------------------------


class TestTrackBIsNotTheHouseholdCostIndex(BuiltOnce, unittest.TestCase):
    def test_a_track_b_retains_every_owner_outlay(self) -> None:
        outlays = [r for r in self.track_b if r.component == "OWNER_OUTLAY"]
        self.assertGreater(len(outlays), 30)
        for row in outlays:
            with self.subTest(ucc=row.ucc):
                self.assertEqual(row.disposition, tracks.RETAINED)

    def test_b_track_b_introduces_no_rental_equivalence(self) -> None:
        for row in self.track_b:
            if row.component == "RENTAL_EQUIVALENCE":
                with self.subTest(ucc=row.ucc):
                    self.assertEqual(row.disposition, "NOT_INTRODUCED")

    def test_c_the_two_tracks_differ_on_the_rows_the_rules_touch(self) -> None:
        a = {row.ucc: row.disposition for row in self.track_a}
        b = {row.ucc: row.disposition for row in self.track_b}
        self.assertEqual(set(a), set(b))
        differing = {ucc for ucc in a if a[ucc] != b[ucc]}
        self.assertGreater(len(differing), 0)

    def test_d_no_artifact_claims_track_b_reproduces_the_hci(self) -> None:
        disclaimer = tracks.TRACK_B_IS_NOT_THE_HCI.lower()
        self.assertIn("is not the bls household cost index", disclaimer)
        for path in (
            tracks.ACCOUNTING_PATH,
            tracks.RULE_ADJUDICATION_PATH,
            tracks.PAYMENTS_TRACK_PATH,
            tracks.SCOPE_RULES_V0_2_PATH,
        ):
            text = path.read_text(encoding="utf-8").lower()
            with self.subTest(path=path.name):
                for claim in (
                    "reproduces the household cost index",
                    "reproduces the hci",
                    "implements the household cost index",
                    "is the household cost index",
                ):
                    self.assertNotIn(claim, text)


# ---------------------------------------------------------------------------
# Group 6: the predecessors survive and the successors carry lineage
# ---------------------------------------------------------------------------


class TestRegistryVersioning(unittest.TestCase):
    def setUp(self) -> None:
        self.v1 = json.loads(
            tracks.SCOPE_RULES_V0_1_PATH.read_text(encoding="utf-8")
        )
        self.v2 = json.loads(
            tracks.SCOPE_RULES_V0_2_PATH.read_text(encoding="utf-8")
        )

    def test_a_the_successor_is_a_different_file(self) -> None:
        self.assertNotEqual(
            tracks.SCOPE_RULES_V0_1_PATH, tracks.SCOPE_RULES_V0_2_PATH
        )
        self.assertNotEqual(
            tracks.PROVENANCE_V0_1_PATH, tracks.PROVENANCE_V0_3_PATH
        )
        self.assertTrue(tracks.SCOPE_RULES_V0_1_PATH.exists())
        self.assertTrue(tracks.PROVENANCE_V0_1_PATH.exists())

    def test_b_the_predecessor_version_is_recorded(self) -> None:
        self.assertEqual(self.v1["version"], "0.1.0")
        self.assertEqual(self.v2["version"], "0.2.0")
        self.assertEqual(self.v2["predecessor"]["version"], self.v1["version"])
        self.assertEqual(
            self.v2["predecessor"]["path"],
            "registry/research/ce_cpi_scope_rules_v0_1.json",
        )

    def test_c_every_v0_1_rule_survives_into_v0_2(self) -> None:
        was = {r["rule_id"] for r in self.v1["rules"]}
        now = {r["rule_id"] for r in self.v2["rules"]}
        self.assertTrue(was.issubset(now))
        self.assertEqual(
            now - was,
            {tracks.TRACK_A_PRIMARY_RULE_ID, tracks.TRACK_A_SECONDARY_RULE_ID},
        )

    def test_d_no_evidence_grade_changed_between_versions(self) -> None:
        was = {r["rule_id"]: r.get("evidence_strength") for r in self.v1["rules"]}
        for rule in self.v2["rules"]:
            if rule["rule_id"] not in was:
                continue
            with self.subTest(rule=rule["rule_id"]):
                self.assertEqual(rule.get("evidence_strength"), was[rule["rule_id"]])

    def test_e_no_ucc_membership_changed_between_versions(self) -> None:
        was = {r["rule_id"]: list(r.get("source_uccs", [])) for r in self.v1["rules"]}
        for rule in self.v2["rules"]:
            if rule["rule_id"] not in was:
                continue
            with self.subTest(rule=rule["rule_id"]):
                self.assertEqual(
                    list(rule.get("source_uccs", [])), was[rule["rule_id"]]
                )

    def test_f_every_reviewed_rule_is_listed_and_only_two_moved(self) -> None:
        """A review that concludes 'no change' is still a review.

        All four appear. The two that stayed PROPOSED are marked
        status_changed false and must still carry a blocker, so the reason
        they did not move is recorded rather than left to inference.
        """
        reviews = self.v2["rule_reviews_from_v0_1"]
        self.assertEqual(
            {r["rule_id"] for r in reviews}, set(tracks.PENDING_RULE_IDS)
        )
        moved = {r["rule_id"] for r in reviews if r["status_changed"]}
        self.assertEqual(
            moved,
            {
                "OS_CPI_MORTGAGE_INTEREST_AND_CHARGES_v0_1",
                "OS_CPI_RESIDENTIAL_PROPERTY_TAX_v0_1",
            },
        )
        for review in reviews:
            with self.subTest(rule=review["rule_id"]):
                self.assertGreater(len(review["evidence"]), 100)
                if review["status_changed"]:
                    self.assertIsNone(review["remaining_blocker"])
                    self.assertEqual(review["to"]["review_status"], tracks.ACCEPTED)
                else:
                    self.assertEqual(review["from"], review["to"])
                    self.assertTrue(review["remaining_blocker"])

    def test_i_no_evidence_grade_moved_in_any_review(self) -> None:
        for review in self.v2["rule_reviews_from_v0_1"]:
            with self.subTest(rule=review["rule_id"]):
                self.assertEqual(
                    review["from"]["evidence_strength"],
                    review["to"]["evidence_strength"],
                )

    def test_g_the_provenance_successor_records_a_non_uniform_promotion(self) -> None:
        provenance = json.loads(
            tracks.PROVENANCE_V0_3_PATH.read_text(encoding="utf-8")
        )
        moved = {t["ucc"] for t in provenance["usability_transitions_from_v0_1"]}
        self.assertEqual(moved, {"910104", "910105", "910107"})
        self.assertNotIn(
            "910106", moved, "910106 was promoted despite failing adjudication"
        )
        roster = {
            entry["ucc"]: entry
            for entry in provenance["concordance_only_uccs"]["roster"]
            if entry["ucc"] in est.SHELTER_UCCS
        }
        self.assertEqual(len(roster), 4)
        self.assertFalse(roster["910106"]["track_a_admissible"])
        self.assertEqual(
            roster["910106"]["pumd_quantitative_usability"], adj.NOT_ESTABLISHED
        )

    def test_h_quality_and_usability_remain_separate_fields(self) -> None:
        """910107 is BENCHMARKED and LOW at once. That is the point."""
        provenance = json.loads(
            tracks.PROVENANCE_V0_3_PATH.read_text(encoding="utf-8")
        )
        entry = next(
            e
            for e in provenance["concordance_only_uccs"]["roster"]
            if e["ucc"] == "910107"
        )
        self.assertEqual(entry["pumd_quantitative_usability"], adj.BENCHMARKED)
        self.assertEqual(entry["pumd_estimate_quality"], "LOW")
        self.assertTrue(entry["track_a_admissible"])


# ---------------------------------------------------------------------------
# Group 7: the artifacts on disk say what the objects in memory say
# ---------------------------------------------------------------------------


class TestArtifactsAgreeWithTheBuild(BuiltOnce, unittest.TestCase):
    def test_a_the_comparison_csv_reproduces_the_accounting(self) -> None:
        rows = list(csv.DictReader(tracks.COMPARISON_PATH.open(newline="")))
        seen = {(r["population"], r["quantity"]): r["millions"] for r in rows}
        for population, entry in self.accounting.items():
            for quantity in ("e_source", "e_cpi", "delta_scope", "delta_shelter"):
                with self.subTest(population=population, quantity=quantity):
                    self.assertAlmostEqual(
                        float(seen[(population, quantity)]),
                        getattr(entry, quantity),
                        places=4,
                    )

    def test_b_the_track_csvs_reproduce_the_tracks(self) -> None:
        for path, built in (
            (tracks.CPI_TRACK_PATH, self.track_a),
            (tracks.PAYMENTS_TRACK_PATH, self.track_b),
        ):
            rows = list(csv.DictReader(path.open(newline="")))
            with self.subTest(path=path.name):
                self.assertEqual(len(rows), len(built))
                self.assertEqual(
                    [r["disposition"] for r in rows],
                    [r.disposition for r in built],
                )

    def test_c_the_accounting_summary_names_the_held_rules(self) -> None:
        summary = json.loads(tracks.ACCOUNTING_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            sorted(summary["rules_held"]),
            sorted(TestPendingRulesHaveNoEffect.HELD),
        )
        self.assertIn(
            tracks.TRACK_A_PRIMARY_RULE_ID,
            summary["rules_effective_in_this_accounting"],
            "the largest rule accepted in this task is missing from the summary",
        )

    def test_d_every_population_appears_in_every_artifact(self) -> None:
        self.assertEqual(set(self.accounting), set(pumd.POPULATIONS))
        summary = json.loads(tracks.ACCOUNTING_PATH.read_text(encoding="utf-8"))
        self.assertEqual(set(summary["by_population"]), set(pumd.POPULATIONS))

    def test_e_units_are_stated(self) -> None:
        summary = json.loads(tracks.ACCOUNTING_PATH.read_text(encoding="utf-8"))
        self.assertIn("millions", summary["units"])
        self.assertIn("2024", summary["units"])


# ---------------------------------------------------------------------------
# Group 8: research firewall
# ---------------------------------------------------------------------------


PHASE_D_MODULES = (
    "dmi_research/detailed_inflation/shelter_tracks.py",
    "scripts/build_shelter_tracks_2024.py",
)


class TestResearchFirewall(unittest.TestCase):
    def _trees(self):
        for relative in PHASE_D_MODULES:
            path = REPO_ROOT / relative
            self.assertTrue(path.exists(), relative)
            yield relative, ast.parse(path.read_text(encoding="utf-8"))

    def test_a_nothing_imports_the_production_calculator(self) -> None:
        """Checked on the parse tree, not on the text.

        A substring scan would fire on these modules' own docstrings, which
        say in prose that they do not touch the calculator. Scanning the
        imports asks the question that matters instead of the one that is easy.
        """
        forbidden = ("dmi_calculator", "deploy")
        for relative, tree in self._trees():
            for node in ast.walk(tree):
                modules: list[str] = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [node.module or ""]
                for module in modules:
                    root = module.split(".")[0]
                    with self.subTest(path=relative, module=module):
                        self.assertNotIn(root, forbidden)

    def test_b_every_written_path_lives_under_research(self) -> None:
        allowed = ("data/research/", "registry/research/", "docs/research/")
        found = 0
        for relative, tree in self._trees():
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(
                    node.value, str
                ):
                    continue
                value = node.value
                if "/" not in value or value.startswith("http"):
                    continue
                if not value.startswith(("data/", "registry/", "docs/", "deploy/")):
                    continue
                found += 1
                with self.subTest(path=relative, literal=value):
                    self.assertTrue(
                        value.startswith(allowed),
                        f"{value!r} is outside the research tree",
                    )
        self.assertGreaterEqual(found, 4, "the path scan found nothing to check")

    def test_c_the_modules_declare_themselves_research_only(self) -> None:
        for relative in PHASE_D_MODULES:
            text = (REPO_ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                self.assertIn("RESEARCH ONLY", text)

    def test_d_no_output_or_baseline_path_is_written(self) -> None:
        for relative in PHASE_D_MODULES:
            text = (REPO_ROOT / relative).read_text(encoding="utf-8")
            for forbidden in ("data/outputs", "deploy/data/outputs"):
                with self.subTest(path=relative, forbidden=forbidden):
                    self.assertNotIn(forbidden, text)

    def test_e_the_artifacts_all_landed_under_research(self) -> None:
        for path in (
            tracks.CPI_TRACK_PATH,
            tracks.PAYMENTS_TRACK_PATH,
            tracks.COMPARISON_PATH,
            tracks.DOUBLE_COUNTING_PATH,
            tracks.RULE_ADJUDICATION_PATH,
            tracks.ACCOUNTING_PATH,
            tracks.SCOPE_RULES_V0_2_PATH,
            tracks.PROVENANCE_V0_3_PATH,
        ):
            relative = path.relative_to(REPO_ROOT).as_posix()
            with self.subTest(path=relative):
                self.assertTrue(path.exists())
                self.assertTrue(
                    relative.startswith(("data/research/", "registry/research/")),
                    relative,
                )

    def test_f_this_task_computed_no_index_and_normalised_no_weight(self) -> None:
        """Phase D8. Checked on what the artifacts contain, not on intent."""
        for path in (tracks.ACCOUNTING_PATH, tracks.RULE_ADJUDICATION_PATH):
            payload = json.loads(path.read_text(encoding="utf-8"))
            flat = json.dumps(payload).lower()
            with self.subTest(path=path.name):
                for forbidden in (
                    "inflation_rate",
                    "price_index",
                    "index_value",
                    "normalised_weight",
                    "normalized_weight",
                ):
                    self.assertNotIn(forbidden, flat)

    def test_g_the_eleven_open_uccs_were_not_touched(self) -> None:
        """Phase D7. Solving them is explicitly not this task's business.

        Comparing the unresolved bucket to its own source would be
        tautological, since the accounting copies the field straight across.
        What can actually go wrong is a rule written here quietly claiming one
        of the eleven, which would resolve it as a side effect. So the check
        is on membership.
        """
        v1 = json.loads(tracks.SCOPE_RULES_V0_1_PATH.read_text(encoding="utf-8"))
        v2 = json.loads(tracks.SCOPE_RULES_V0_2_PATH.read_text(encoding="utf-8"))

        def unresolved(registry) -> list[str]:
            rule = next(
                r for r in registry["rules"] if r["rule_id"].startswith("UNRESOLVED")
            )
            return list(rule["source_uccs"])

        was = unresolved(v1)
        self.assertEqual(len(was), 11)
        self.assertEqual(unresolved(v2), was)

        added = {
            ucc
            for rule in v2["rules"]
            if rule["rule_id"] in v2["rules_added_in_v0_2"]
            for ucc in rule["source_uccs"]
        }
        self.assertEqual(added & set(was), set())


if __name__ == "__main__":
    unittest.main()
