#!/usr/bin/env python3
"""Tests for the residual Track-A shelter adjudication (Phase B).

This task moved 199,079 million dollars from a pending bucket to an accepted
one and left everything else where it was. Almost none of that is worth
testing directly. What is worth testing is the set of disciplines that made
the move legitimate, because every one of them would still produce this same
table if it had quietly stopped holding.

*Evidence carries a vintage, and the vintage is load-bearing.* A primary BLS
source that describes a procedure BLS used in 2010 does not authorise applying
that procedure's number to 2024. The whole task turns on that distinction, so
it is asserted rather than assumed: no rule may reach ACCEPTED while citing
HISTORICAL_ONLY evidence, and the registry is checked to actually contain
HISTORICAL_ONLY records so the assertion is not vacuous.

*A broad rule that combined four concepts was split, and the split is exact.*
The four successors must partition the predecessor's membership with no
overlap and no gap, and their materialities must sum to the predecessor's.
Otherwise "splitting a rule" becomes a way to lose money quietly.

*The absent factor is not approximated.* The historical 43 percent is not
merely unapplied, it is absent from the module's parse tree, so it cannot be
one edit away from use.

*Two different limitations stay two.* The secondary-residence rules are
blocked by an unpublished parameter and by a degenerate variance estimator.
Clearing either alone leaves them blocked on the other, and the artifacts must
say so in a form a machine can read.

*Nothing was balanced.* The forbidden-vocabulary guard is asserted to fire on
each name the task named, and then asserted not to fire on the real module.
A guard that never fires proves nothing.

*The predecessors survive unedited.* Every v0.2 rule that carries into v0.3
must be byte-equal to its v0.2 self, apart from an additive review block.
"""

from __future__ import annotations

import ast
import csv
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dmi_research.detailed_inflation import pumd  # noqa: E402
from dmi_research.detailed_inflation import shelter_residuals as res  # noqa: E402

RESIDUAL_MODULES = (
    "dmi_research/detailed_inflation/shelter_residuals.py",
    "scripts/build_shelter_residuals_2024.py",
)


class BuiltOnce:
    """One build, shared by the classes that only read it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.basis = res.load_basis()
        cls.predecessor_rules = res.load_predecessor_rules()
        cls.predecessor_provenance = res.load_predecessor_provenance()
        cls.summary = res.load_accounting_summary()
        cls.matrix = res.build_ucc_matrix(cls.basis)
        cls.before_after = res.build_before_after(cls.summary, cls.basis)
        cls.verdict = res.build_verdict(cls.basis, cls.before_after)
        cls.evidence = res.build_evidence_registry()
        cls.v0_3 = res.build_scope_rules_v0_3(cls.predecessor_rules, cls.basis)
        cls.v0_4 = res.build_provenance_v0_4(cls.predecessor_provenance)
        cls.rules_v0_3 = {r["rule_id"]: r for r in cls.v0_3["rules"]}
        cls.rules_v0_2 = {
            r["rule_id"]: r for r in cls.predecessor_rules["rules"]
        }


# ---------------------------------------------------------------------------
# Group 1: the predecessors survive
# ---------------------------------------------------------------------------


class TestPreservation(BuiltOnce, unittest.TestCase):
    def test_a_the_successors_are_different_files(self) -> None:
        pairs = (
            (res.SCOPE_RULES_V0_2_PATH, res.SCOPE_RULES_V0_3_PATH),
            (res.PROVENANCE_V0_3_PATH, res.PROVENANCE_V0_4_PATH),
        )
        for predecessor, successor in pairs:
            with self.subTest(successor=successor.name):
                self.assertNotEqual(predecessor, successor)
                self.assertTrue(predecessor.exists())
                self.assertTrue(successor.exists())

    def test_b_no_milestone_path_is_written_by_this_task(self) -> None:
        """The frozen paths must not appear as write targets.

        Checked against the module's own write calls rather than against a
        string scan, because the module names the predecessor paths legitimately
        when it reads them.
        """
        frozen = {
            "registry/research/ce_cpi_scope_rules_v0_2.json",
            "registry/research/ucc_provenance_classes_v0_3.json",
        }
        source = Path(res.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        written: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name not in ("write_text", "write_json", "open"):
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    written.add(arg.value)
        self.assertEqual(written & frozen, set())

    def test_c_every_v0_2_rule_survives_into_v0_3(self) -> None:
        carried = set(self.rules_v0_2) - {res.PREDECESSOR_STRUCTURE_RULE}
        self.assertTrue(carried.issubset(set(self.rules_v0_3)))
        self.assertNotIn(res.PREDECESSOR_STRUCTURE_RULE, self.rules_v0_3)

    def test_d_a_carried_rule_body_is_unedited_apart_from_an_added_review(
        self,
    ) -> None:
        """The strongest preservation check available in memory.

        Editing a predecessor rule in place while writing it to a new path
        would satisfy every path-based test and would still be the thing the
        task forbids. So each carried body is compared field by field.
        """
        annotated = 0
        for rule_id in set(self.rules_v0_2) - {res.PREDECESSOR_STRUCTURE_RULE}:
            before = self.rules_v0_2[rule_id]
            after = dict(self.rules_v0_3[rule_id])
            if "residual_review" in after:
                annotated += 1
                after.pop("residual_review")
            with self.subTest(rule_id=rule_id):
                self.assertEqual(before, after)
        self.assertEqual(
            annotated, 2, "exactly the two secondary-residence rules are annotated"
        )

    def test_e_the_predecessor_is_named_and_located(self) -> None:
        for payload, path in (
            (self.v0_3, "registry/research/ce_cpi_scope_rules_v0_2.json"),
            (self.v0_4, "registry/research/ucc_provenance_classes_v0_3.json"),
        ):
            with self.subTest(path=path):
                self.assertEqual(payload["predecessor"]["path"], path)

    def test_f_the_milestone_artifacts_are_untouched_on_disk(self) -> None:
        """The residual artifacts live in their own directory, not the old one."""
        milestone = REPO_ROOT / "data/research/detailed_inflation/shelter_2024"
        residual = res.RESIDUALS_DIR
        self.assertNotEqual(milestone, residual)
        for path in (
            res.UCC_MATRIX_PATH,
            res.BEFORE_AFTER_PATH,
            res.RULE_TRANSITIONS_PATH,
            res.VERDICT_PATH,
        ):
            with self.subTest(path=path.name):
                self.assertEqual(path.parent, residual)


# ---------------------------------------------------------------------------
# Group 2: evidence carries a vintage and the vintage decides
# ---------------------------------------------------------------------------


class TestEvidenceVintage(BuiltOnce, unittest.TestCase):
    def test_a_every_record_declares_a_known_vintage(self) -> None:
        for record in res.EVIDENCE:
            with self.subTest(evidence_id=record.evidence_id):
                self.assertIn(record.vintage_class, res.VINTAGE_CLASSES)

    def test_b_an_unknown_vintage_is_rejected_at_construction(self) -> None:
        """Non-vacuity for the test above."""
        with self.assertRaises(ValueError):
            res.Evidence(
                evidence_id="SYNTHETIC",
                issue="owner_maintenance",
                claim="none",
                vintage_class="PROBABLY_FINE",
                source_title="none",
                source_locator="none",
                source_date="none",
                quoted_passage="none",
                establishes="none",
                does_not_establish="none",
            )

    def test_c_evidence_ids_are_unique(self) -> None:
        ids = [record.evidence_id for record in res.EVIDENCE]
        self.assertEqual(len(ids), len(set(ids)))

    def test_d_every_cited_id_resolves(self) -> None:
        known = {record.evidence_id for record in res.EVIDENCE}
        cited: set[str] = set()
        for rule in res.SUCCESSOR_RULES:
            cited.update(rule.evidence_ids)
        for spec in res.HELD_RULE_UPDATES:
            cited.update(spec["evidence_ids"])  # type: ignore[arg-type]
        for item in res.OPEN_ITEMS:
            cited.update(item["evidence_ids"])  # type: ignore[arg-type]
        self.assertTrue(cited)
        self.assertEqual(cited - known, set())

    def test_e_no_accepted_rule_rests_on_historical_evidence(self) -> None:
        """The rule the whole task exists to enforce."""
        historical = {
            record.evidence_id
            for record in res.EVIDENCE
            if record.vintage_class == "HISTORICAL_ONLY"
        }
        for rule in res.SUCCESSOR_RULES:
            if rule.successor_status != "ACCEPTED":
                continue
            with self.subTest(rule_id=rule.rule_id):
                self.assertEqual(set(rule.evidence_ids) & historical, set())

    def test_f_historical_evidence_exists_and_is_cited_somewhere(self) -> None:
        """Non-vacuity for the test above.

        If the registry happened to hold no HISTORICAL_ONLY records at all,
        the check above would pass without meaning anything.
        """
        counts = self.evidence["counts_by_vintage"]
        self.assertGreater(counts["HISTORICAL_ONLY"], 0)
        cited_by_pending = {
            eid
            for spec in res.HELD_RULE_UPDATES
            for eid in spec["evidence_ids"]  # type: ignore[union-attr]
        }
        historical = {
            record.evidence_id
            for record in res.EVIDENCE
            if record.vintage_class == "HISTORICAL_ONLY"
        }
        self.assertTrue(cited_by_pending & historical)

    def test_g_an_accepted_rule_cites_current_evidence(self) -> None:
        current = {
            record.evidence_id
            for record in res.EVIDENCE
            if record.vintage_class == "CURRENT_2024_COMPATIBLE"
        }
        for rule in res.SUCCESSOR_RULES:
            if rule.successor_status != "ACCEPTED":
                continue
            with self.subTest(rule_id=rule.rule_id):
                self.assertTrue(set(rule.evidence_ids) & current)

    def test_h_every_record_says_what_it_does_not_establish(self) -> None:
        """A source's limits are as load-bearing as its claims here."""
        for record in res.EVIDENCE:
            with self.subTest(evidence_id=record.evidence_id):
                self.assertTrue(record.does_not_establish.strip())
                self.assertTrue(record.source_locator.strip())

    def test_h2_a_record_that_cites_a_document_quotes_it(self) -> None:
        """And a record that found nothing quotes nothing.

        The second half is the one that matters. A NOT_FOUND record asserts
        that a search returned nothing; a passage attached to it would be a
        quotation of a document that was not found. A DMI_INFERENCE record may
        carry text, because what it carries is our own reasoning rather than a
        source, and it is labelled as such in its title.
        """
        quoting = (
            "CURRENT_2024_COMPATIBLE",
            "CURRENT_BUT_NONNUMERIC",
            "HISTORICAL_ONLY",
        )
        checked = 0
        for record in res.EVIDENCE:
            with self.subTest(evidence_id=record.evidence_id):
                if record.vintage_class == "NOT_FOUND":
                    self.assertFalse(
                        record.quoted_passage.strip(),
                        "a passage is quoted from a document not found",
                    )
                elif record.vintage_class in quoting:
                    checked += 1
                    self.assertTrue(record.quoted_passage.strip())
                    self.assertTrue(record.source_date.strip())
        self.assertGreaterEqual(checked, 10)

    def test_i_the_casey_source_is_classed_historical(self) -> None:
        casey = [
            record
            for record in res.EVIDENCE
            if record.evidence_id.startswith("CASEY_")
        ]
        self.assertTrue(casey)
        for record in casey:
            with self.subTest(evidence_id=record.evidence_id):
                self.assertEqual(record.vintage_class, "HISTORICAL_ONLY")

    def test_j_a_dmi_inference_is_labelled_as_ours(self) -> None:
        inferences = [
            record
            for record in res.EVIDENCE
            if record.vintage_class == "DMI_INFERENCE"
        ]
        self.assertTrue(inferences)
        for record in inferences:
            with self.subTest(evidence_id=record.evidence_id):
                self.assertIn("DMI", record.source_title)


# ---------------------------------------------------------------------------
# Group 3: the split is exact
# ---------------------------------------------------------------------------


class TestOwnerStructureSplit(BuiltOnce, unittest.TestCase):
    def setUp(self) -> None:
        self.predecessor = self.rules_v0_2[res.PREDECESSOR_STRUCTURE_RULE]

    def test_a_the_successors_partition_the_predecessor_membership(self) -> None:
        was = list(self.predecessor["source_uccs"])
        now: list[str] = []
        for rule in res.SUCCESSOR_RULES:
            now.extend(rule.source_uccs)
        self.assertEqual(len(now), len(set(now)), "a UCC is claimed twice")
        self.assertEqual(set(now), set(was), "the split gained or lost a UCC")

    def test_b_the_materialities_sum_to_the_predecessor(self) -> None:
        for population in pumd.POPULATIONS:
            total = sum(
                self.basis[(ucc, population)] or 0.0
                for rule in res.SUCCESSOR_RULES
                for ucc in rule.source_uccs
            )
            was = sum(
                self.basis[(ucc, population)] or 0.0
                for ucc in self.predecessor["source_uccs"]
            )
            with self.subTest(population=population):
                self.assertAlmostEqual(total, was, places=6)

    def test_c_every_successor_names_its_predecessor(self) -> None:
        for rule in res.SUCCESSOR_RULES:
            with self.subTest(rule_id=rule.rule_id):
                self.assertEqual(
                    rule.predecessor_rule_id, res.PREDECESSOR_STRUCTURE_RULE
                )
                self.assertEqual(rule.predecessor_status, "PROPOSED")
                self.assertNotEqual(rule.rule_id, res.PREDECESSOR_STRUCTURE_RULE)

    def test_d_exactly_one_successor_cleared(self) -> None:
        accepted = [
            rule
            for rule in res.SUCCESSOR_RULES
            if rule.successor_status == "ACCEPTED"
        ]
        self.assertEqual(len(accepted), 1)
        self.assertTrue(accepted[0].numerical_treatment_computable)
        self.assertIsNone(accepted[0].blocker_kind)

    def test_e_every_held_successor_states_a_known_blocker(self) -> None:
        for rule in res.SUCCESSOR_RULES:
            if rule.successor_status == "ACCEPTED":
                continue
            with self.subTest(rule_id=rule.rule_id):
                self.assertIn(rule.blocker_kind, res.BLOCKER_KINDS)
                self.assertFalse(self.rules_v0_3[rule.rule_id]["is_applicable"])

    def test_e2_a_parameter_blocker_means_the_arithmetic_is_unavailable(
        self,
    ) -> None:
        """The two fields are not the same claim and must not be conflated.

        These three successors are exclusions, so their arithmetic is trivially
        available: the amount is known and removing it is subtraction. What
        blocks them is the concept, not the number, and recording computable
        as true is the honest answer. A rule blocked on an unpublished
        parameter is the opposite case, and there the number really is missing.
        """
        for rule in res.SUCCESSOR_RULES:
            if rule.blocker_kind == "BLOCKED_BY_UNPUBLISHED_PARAMETER":
                with self.subTest(rule_id=rule.rule_id):
                    self.assertFalse(rule.numerical_treatment_computable)
        for spec in res.HELD_RULE_UPDATES:
            if spec["blocker_kind"] == "BLOCKED_BY_UNPUBLISHED_PARAMETER":
                with self.subTest(rule_id=spec["rule_id"]):
                    self.assertFalse(spec["numerical_treatment_computable"])

    def test_e3_computable_arithmetic_does_not_make_a_rule_effective(
        self,
    ) -> None:
        """The field that decides effect is the status, never computability."""
        for rule in res.SUCCESSOR_RULES:
            if rule.successor_status == "ACCEPTED":
                continue
            with self.subTest(rule_id=rule.rule_id):
                self.assertEqual(rule.effect_state, "PENDING")
                self.assertFalse(self.rules_v0_3[rule.rule_id]["is_applicable"])

    def test_f_the_held_blockers_are_not_all_the_same_reason(self) -> None:
        """Splitting for the sake of splitting would leave one shared blocker."""
        kinds = {
            rule.blocker_kind
            for rule in res.SUCCESSOR_RULES
            if rule.blocker_kind
        }
        self.assertGreaterEqual(len(kinds), 2)

    def test_g_the_falsified_criterion_is_recorded_not_deleted(self) -> None:
        block = self.v0_3["falsified_predecessor_criterion"]
        self.assertEqual(block["verdict"], "FALSIFIED")
        self.assertIn("counterpart", block["criterion"].lower())
        known = {record.evidence_id for record in res.EVIDENCE}
        self.assertIn(block["evidence_id"], known)

    def test_h_no_successor_relies_on_the_falsified_criterion_alone(self) -> None:
        falsified = self.v0_3["falsified_predecessor_criterion"]["evidence_id"]
        for rule in res.SUCCESSOR_RULES:
            if rule.successor_status != "ACCEPTED":
                continue
            with self.subTest(rule_id=rule.rule_id):
                self.assertNotEqual(list(rule.evidence_ids), [falsified])

    def test_i_the_matrix_answers_every_required_column(self) -> None:
        required = (
            "ucc",
            "label",
            "all_cu_expenditure",
            "q1_expenditure",
            "q2_expenditure",
            "q3_expenditure",
            "q4_expenditure",
            "q5_expenditure",
            "current_proposed_treatment",
            "bls_concept",
            "cpi_scope_treatment",
            "evidence_source",
            "evidence_vintage",
            "allocation_factor",
            "factor_provenance",
            "final_research_disposition",
            "unresolved_reason",
        )
        rows = list(csv.DictReader(res.UCC_MATRIX_PATH.open(encoding="utf-8")))
        self.assertTrue(rows)
        for column in required:
            with self.subTest(column=column):
                self.assertIn(column, rows[0])
                self.assertTrue(
                    all(row[column].strip() for row in rows),
                    f"{column} is blank on some row",
                )

    def test_j_the_matrix_covers_the_predecessor_and_nothing_else(self) -> None:
        rows = list(csv.DictReader(res.UCC_MATRIX_PATH.open(encoding="utf-8")))
        self.assertEqual(
            {row["ucc"] for row in rows},
            set(self.predecessor["source_uccs"]),
        )

    def test_k_the_matrix_distinguishes_more_than_one_concept(self) -> None:
        """The finding was that one rule held several concepts. Assert it shows."""
        rows = list(csv.DictReader(res.UCC_MATRIX_PATH.open(encoding="utf-8")))
        self.assertGreaterEqual(len({row["category"] for row in rows}), 4)
        self.assertGreaterEqual(
            len({row["final_research_disposition"] for row in rows}), 2
        )

    def test_l_the_categories_the_task_named_are_all_accounted_for(self) -> None:
        coverage = self.verdict["b4_category_coverage"]
        named = set(coverage["in_this_matrix"]) | set(coverage["elsewhere"])
        self.assertGreaterEqual(len(named), 7)
        rows = list(csv.DictReader(res.UCC_MATRIX_PATH.open(encoding="utf-8")))
        self.assertEqual(
            {row["category"] for row in rows}, set(coverage["in_this_matrix"])
        )


# ---------------------------------------------------------------------------
# Group 4: the insurance factor is absent, not merely unapplied
# ---------------------------------------------------------------------------


class TestHomeownersInsurance(BuiltOnce, unittest.TestCase):
    RULE_ID = "TR_CPI_HOMEOWNERS_INSURANCE_CONTENTS_PORTION_v0_1"

    def test_a_the_outcome_is_c_and_says_so(self) -> None:
        rule = self.rules_v0_3[self.RULE_ID]
        self.assertEqual(rule["b5_outcome"], "C")
        self.assertEqual(
            self.verdict["issue_outcomes"]["homeowners_insurance"]["b5_outcome"],
            "C",
        )

    def test_b_no_factor_is_stored_on_the_rule(self) -> None:
        rule = self.rules_v0_3[self.RULE_ID]
        self.assertIsNone(rule["factor_applied"])
        self.assertFalse(rule["is_applicable"])
        self.assertEqual(rule["review_status"], "PROPOSED")
        self.assertEqual(
            rule["blocker_kind"], "BLOCKED_BY_UNPUBLISHED_PARAMETER"
        )

    def test_c_the_historical_factor_is_absent_from_the_parse_tree(self) -> None:
        """Not applied is not enough. It must not be sitting there as a number.

        The 43 percent may be quoted in a passage of evidence, because that is
        what the historical source says. It may not exist as a numeric literal
        the code could reach.
        """
        for relative in RESIDUAL_MODULES:
            tree = ast.parse(
                (REPO_ROOT / relative).read_text(encoding="utf-8")
            )
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(
                    node.value, (int, float)
                ) and not isinstance(node.value, bool):
                    with self.subTest(path=relative, value=node.value):
                        self.assertNotIn(
                            float(node.value), (0.43, 43.0, 0.5, 50.0)
                        )

    def test_d_no_emitted_artifact_carries_an_applied_factor(self) -> None:
        for path in (
            res.SCOPE_RULES_V0_3_PATH,
            res.PROVENANCE_V0_4_PATH,
            res.EVIDENCE_PATH,
            res.VERDICT_PATH,
        ):
            payload = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(path=path.name):
                self._assert_no_applied_factor(payload, path.name)

    def _assert_no_applied_factor(self, node, where: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                lowered = key.lower()
                if "factor" in lowered and isinstance(value, (int, float)):
                    self.fail(f"{where}: {key} holds a numeric factor {value}")
                self._assert_no_applied_factor(value, where)
        elif isinstance(node, list):
            for item in node:
                self._assert_no_applied_factor(item, where)

    def test_e_the_concept_is_established_even_though_the_number_is_not(
        self,
    ) -> None:
        """Outcome C is a pair of claims and both halves need asserting."""
        rule = self.rules_v0_3[self.RULE_ID]
        self.assertEqual(rule["evidence_strength"], "STRONG_CONCEPT_NO_PARAMETER")
        self.assertFalse(rule["numerical_treatment_computable"])
        current = {
            record.evidence_id
            for record in res.EVIDENCE
            if record.vintage_class
            in ("CURRENT_2024_COMPATIBLE", "CURRENT_BUT_NONNUMERIC")
        }
        self.assertTrue(set(rule["evidence_ids"]) & current)

    def test_f_one_hundred_percent_retention_is_flagged_not_endorsed(
        self,
    ) -> None:
        """The task forbids treating full retention as the settled answer."""
        item = next(
            entry
            for entry in self.verdict["open_items"]
            if entry["open_item_id"] == "HOMEOWNERS_INSURANCE_UPPER_BOUND"
        )
        self.assertEqual(item["action_taken"], "NONE")
        self.assertEqual(list(item["uccs"]), ["220121"])
        self.assertIn("upper bound", item["finding"].lower())

    def test_g_the_supersession_is_recorded_as_a_finding(self) -> None:
        """Outcome A is excluded affirmatively, not merely left unproven."""
        record = next(
            r
            for r in res.EVIDENCE
            if r.evidence_id == "INSURANCE_NAIC_METHOD_SINCE_2025"
        )
        self.assertIn(
            record.vintage_class,
            ("CURRENT_2024_COMPATIBLE", "CURRENT_BUT_NONNUMERIC"),
        )
        self.assertIn("2025", record.quoted_passage)


# ---------------------------------------------------------------------------
# Group 5: two limitations stay two
# ---------------------------------------------------------------------------


class TestSecondaryResidence(BuiltOnce, unittest.TestCase):
    RULE_IDS = (
        "RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1",
        "TA_OWNER_RENTAL_EQUIVALENCE_SECONDARY_v0_1",
    )

    def test_a_both_rules_carry_two_distinct_blockers(self) -> None:
        for rule_id in self.RULE_IDS:
            review = self.rules_v0_3[rule_id]["residual_review"]
            blockers = review["blockers"]
            with self.subTest(rule_id=rule_id):
                self.assertEqual(len(blockers), 2)
                self.assertEqual(
                    len({b["blocker_kind"] for b in blockers}), 2
                )
                self.assertEqual(
                    len({b["uncertainty_kind"] for b in blockers}), 2
                )

    def test_b_the_two_blockers_are_a_parameter_and_a_sampling_problem(
        self,
    ) -> None:
        for rule_id in self.RULE_IDS:
            blockers = self.rules_v0_3[rule_id]["residual_review"]["blockers"]
            with self.subTest(rule_id=rule_id):
                self.assertEqual(
                    {b["uncertainty_kind"] for b in blockers},
                    {"PARAMETER", "SAMPLING"},
                )

    def test_c_each_blocker_declares_the_other_does_not_subsume_it(self) -> None:
        for rule_id in self.RULE_IDS:
            blockers = self.rules_v0_3[rule_id]["residual_review"]["blockers"]
            ids = {b["blocker_id"] for b in blockers}
            with self.subTest(rule_id=rule_id):
                for blocker in blockers:
                    self.assertIn(blocker["independent_of"], ids - {blocker["blocker_id"]})

    def test_d_each_blocker_states_what_would_clear_it(self) -> None:
        for rule_id in self.RULE_IDS:
            for blocker in self.rules_v0_3[rule_id]["residual_review"]["blockers"]:
                with self.subTest(rule_id=rule_id, blocker=blocker["blocker_id"]):
                    self.assertTrue(blocker["what_would_clear_it"].strip())

    def test_e_neither_rule_changed_status(self) -> None:
        for rule_id in self.RULE_IDS:
            review = self.rules_v0_3[rule_id]["residual_review"]
            with self.subTest(rule_id=rule_id):
                self.assertFalse(review["status_changed"])
                self.assertEqual(review["review_status"], "PROPOSED")
                self.assertEqual(
                    self.rules_v0_3[rule_id]["review_status"], "PROPOSED"
                )
                self.assertFalse(self.rules_v0_3[rule_id]["is_applicable"])

    def test_f_the_910106_defect_is_still_attached_to_910106_alone(self) -> None:
        for rule_id in self.RULE_IDS:
            blockers = self.rules_v0_3[rule_id]["residual_review"]["blockers"]
            sampling = next(
                b for b in blockers if b["uncertainty_kind"] == "SAMPLING"
            )
            with self.subTest(rule_id=rule_id):
                self.assertEqual(sampling["affects_uccs"], ["910106"])

    def test_g_the_missing_factor_is_not_derived_from_anything(self) -> None:
        """The task lists four forbidden derivations by name."""
        record = next(
            r
            for r in res.EVIDENCE
            if r.evidence_id == "SECONDARY_CONSUMPTION_FACTOR_CURRENT_VINTAGE"
        )
        self.assertEqual(record.vintage_class, "NOT_FOUND")
        outcome = self.verdict["issue_outcomes"]["secondary_residence"]
        self.assertEqual(outcome["outcome"], "BLOCKED_BY_UNPUBLISHED_PARAMETER")

    def test_h_declining_the_rule_made_the_reported_gap_larger(self) -> None:
        """Evidence decided this, not effect. Asserting the direction proves it.

        Accepting the replacement rule would have removed 12,620 million from
        the basis with nothing entering in its place, enlarging the reported
        understatement. A module that was quietly optimising the gap downward
        would have taken that acceptance.
        """
        spec = next(
            item
            for item in res.HELD_RULE_UPDATES
            if item["rule_id"] == "RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1"
        )
        self.assertIn("enlarg", str(spec["track_a_effect"]).lower())
        self.assertEqual(spec["successor_status"], "PROPOSED")


# ---------------------------------------------------------------------------
# Group 6: nothing was balanced
# ---------------------------------------------------------------------------


FORBIDDEN_VOCABULARY = (
    "rescale",
    "normalize_to_total",
    "normalise_to_total",
    "balancing_factor",
    "scaling_factor",
    "residual_allocation",
    "residual_allocator",
    "normalize_to_source",
    "calibration_ratio",
    "historical_factor_as_current",
    "fudge",
)


def _identifiers(source: str) -> set[str]:
    """Identifiers in the parse tree, not words in the text.

    A module whose prose says it does not rescale must not thereby satisfy a
    test that it does not rescale.
    """
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            names.add(node.arg)
    return names


def _hits(names: set[str]) -> set[str]:
    return {
        name
        for name in names
        for word in FORBIDDEN_VOCABULARY
        if word in name.lower()
    }


class TestNoBalancing(BuiltOnce, unittest.TestCase):
    def test_a_the_guard_fires_on_every_injected_name(self) -> None:
        """Non-vacuity, asserted first so a broken guard cannot pass silently."""
        for word in FORBIDDEN_VOCABULARY:
            source = f"def compute():\n    {word} = 1.0\n    return {word}\n"
            with self.subTest(injected=word):
                self.assertTrue(_hits(_identifiers(source)))

    def test_b_the_guard_fires_on_an_injected_attribute_and_argument(
        self,
    ) -> None:
        cases = (
            "def f(balancing_factor):\n    return balancing_factor\n",
            "def f(x):\n    return x.residual_allocation\n",
            "def f(x):\n    return g(normalize_to_total=x)\n",
            "def apply_historical_factor_as_current(x):\n    return x\n",
        )
        for source in cases:
            with self.subTest(source=source.splitlines()[0]):
                self.assertTrue(_hits(_identifiers(source)))

    def test_c_the_guard_does_not_fire_on_the_real_modules(self) -> None:
        for relative in RESIDUAL_MODULES:
            source = (REPO_ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                self.assertEqual(_hits(_identifiers(source)), set())

    def test_d_the_two_deltas_did_not_move(self) -> None:
        for row in self.before_after:
            if row.quantity not in ("delta_scope", "delta_shelter"):
                continue
            with self.subTest(population=row.population, quantity=row.quantity):
                self.assertEqual(row.change, 0.0)

    def test_e_the_deltas_are_still_large(self) -> None:
        """A zero delta would mean the gap had been closed rather than reported."""
        lookup = {
            (row.population, row.quantity): row for row in self.before_after
        }
        for population in pumd.POPULATIONS:
            source = lookup[(population, "e_source")].after
            for quantity in ("delta_scope", "delta_shelter"):
                row = lookup[(population, quantity)]
                with self.subTest(population=population, quantity=quantity):
                    self.assertGreater(abs(row.after), 0.05 * source)

    def test_f_the_move_is_inert_by_construction_not_by_tuning(self) -> None:
        """The promoted amount goes between two buckets outside the CPI basis.

        That is why the deltas cannot move. Asserting the promotion is large
        and non-zero rules out the alternative explanation, which is that
        nothing happened at all.
        """
        promoted = res._promoted_amount(self.basis, "ALL_CU")
        self.assertGreater(promoted, 0.0)
        lookup = {
            (row.population, row.quantity): row for row in self.before_after
        }
        out_of_scope = lookup[("ALL_CU", "accepted_out_of_scope")]
        pending = lookup[("ALL_CU", "pending_proposed")]
        self.assertAlmostEqual(out_of_scope.change, promoted, places=6)
        self.assertAlmostEqual(pending.change, -promoted, places=6)
        self.assertIn("accepted_out_of_scope", res.BUCKETS_OUTSIDE_CPI_BASIS)
        self.assertIn("pending_proposed", res.BUCKETS_OUTSIDE_CPI_BASIS)

    def test_g_the_buckets_that_feed_the_cpi_basis_did_not_move(self) -> None:
        for row in self.before_after:
            if row.quantity not in (
                "retained",
                "accepted_transformed",
                "rental_equivalence_introduced",
                "e_cpi",
                "e_source",
            ):
                continue
            with self.subTest(population=row.population, quantity=row.quantity):
                self.assertEqual(row.change, 0.0)

    def test_h_a_broken_identity_is_rejected(self) -> None:
        """Mutation. The identity checker must actually be able to fail."""
        entry = {
            "retained": 40.0,
            "accepted_transformed": 10.0,
            "accepted_out_of_scope": 30.0,
            "pending_proposed": 15.0,
            "unresolved_open": 5.0,
            "e_source": 100.0,
            "rental_equivalence_introduced": 900.0,
            "e_cpi": 950.0,
            "delta_scope": 850.0,
        }
        res._check_identities("SYNTHETIC", entry)
        for field, delta in (
            ("retained", 1.0),
            ("e_cpi", -1.0),
            ("delta_scope", 1.0),
        ):
            broken = dict(entry)
            broken[field] += delta
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    res._check_identities("SYNTHETIC", broken)

    def test_i_equalising_the_bases_is_not_what_the_checker_asks(self) -> None:
        """Non-vacuity for the test above.

        The synthetic entry it accepts has a CPI basis 9.5 times its source
        basis. A checker that demanded the two agree would be the exact defect
        the task forbids, and would also have passed the mutation test.
        """
        entry = {
            "retained": 40.0,
            "accepted_transformed": 10.0,
            "accepted_out_of_scope": 30.0,
            "pending_proposed": 15.0,
            "unresolved_open": 5.0,
            "e_source": 100.0,
            "rental_equivalence_introduced": 900.0,
            "e_cpi": 950.0,
            "delta_scope": 850.0,
        }
        res._check_identities("SYNTHETIC", entry)
        self.assertEqual(entry["e_cpi"] / entry["e_source"], 9.5)

    def test_j_the_verdict_does_not_claim_the_gap_shrank(self) -> None:
        text = self.verdict["no_balancing"].lower()
        self.assertIn("byte-identical", text)
        self.assertEqual(
            self.verdict["quantities_unchanged_by_this_task"],
            {
                "e_source": 0.0,
                "e_cpi": 0.0,
                "delta_scope": 0.0,
                "delta_shelter": 0.0,
            },
        )


# ---------------------------------------------------------------------------
# Group 7: the research firewall
# ---------------------------------------------------------------------------


class TestResearchFirewall(unittest.TestCase):
    def _trees(self):
        for relative in RESIDUAL_MODULES:
            path = REPO_ROOT / relative
            self.assertTrue(path.exists(), relative)
            yield relative, ast.parse(path.read_text(encoding="utf-8"))

    def test_a_nothing_imports_the_production_calculator(self) -> None:
        forbidden = ("dmi_calculator", "deploy")
        for relative, tree in self._trees():
            for node in ast.walk(tree):
                modules: list[str] = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [node.module or ""]
                for module in modules:
                    with self.subTest(path=relative, module=module):
                        self.assertNotIn(module.split(".")[0], forbidden)

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
                if not value.startswith(
                    ("data/", "registry/", "docs/", "deploy/")
                ):
                    continue
                found += 1
                with self.subTest(path=relative, literal=value):
                    self.assertTrue(
                        value.startswith(allowed),
                        f"{value!r} is outside the research tree",
                    )
        self.assertGreaterEqual(found, 4, "the path scan found nothing to check")

    def test_c_the_modules_declare_themselves_research_only(self) -> None:
        for relative in RESIDUAL_MODULES:
            text = (REPO_ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                self.assertIn("RESEARCH ONLY", text)

    def test_d_no_output_or_baseline_path_appears(self) -> None:
        for relative in RESIDUAL_MODULES:
            text = (REPO_ROOT / relative).read_text(encoding="utf-8")
            for forbidden in ("data/outputs", "deploy/data/outputs"):
                with self.subTest(path=relative, forbidden=forbidden):
                    self.assertNotIn(forbidden, text)

    def test_e_the_artifacts_all_landed_under_research(self) -> None:
        for path in (
            res.UCC_MATRIX_PATH,
            res.BEFORE_AFTER_PATH,
            res.RULE_TRANSITIONS_PATH,
            res.VERDICT_PATH,
            res.EVIDENCE_PATH,
            res.SCOPE_RULES_V0_3_PATH,
            res.PROVENANCE_V0_4_PATH,
        ):
            relative = path.relative_to(REPO_ROOT).as_posix()
            with self.subTest(path=relative):
                self.assertTrue(path.exists())
                self.assertTrue(
                    relative.startswith(("data/research/", "registry/research/")),
                    relative,
                )

    def test_f_this_task_computed_no_index_and_normalised_no_weight(self) -> None:
        """Scanned on what this task wrote, not on what it carried forward.

        The successor registry copies predecessor rule bodies verbatim, and one
        of them has a track_b field named price_index_needed. Scanning the copy
        would fail on the predecessor's vocabulary and would push toward
        editing a frozen rule to satisfy a test, which is the thing preservation
        exists to prevent.
        """
        for path in (res.VERDICT_PATH, res.EVIDENCE_PATH):
            flat = json.dumps(
                json.loads(path.read_text(encoding="utf-8"))
            ).lower()
            with self.subTest(path=path.name):
                for forbidden in (
                    "inflation_rate",
                    "price_index",
                    "index_value",
                    "normalised_weight",
                    "normalized_weight",
                ):
                    self.assertNotIn(forbidden, flat)

    def test_f2_the_rules_this_task_added_carry_no_index_vocabulary(
        self,
    ) -> None:
        """Companion to the test above, aimed at what this task actually wrote."""
        v3 = json.loads(res.SCOPE_RULES_V0_3_PATH.read_text(encoding="utf-8"))
        added = {rule.rule_id for rule in res.SUCCESSOR_RULES}
        added.add("TR_CPI_HOMEOWNERS_INSURANCE_CONTENTS_PORTION_v0_1")
        bodies = [r for r in v3["rules"] if r["rule_id"] in added]
        self.assertEqual(len(bodies), len(added))
        flat = json.dumps(bodies).lower()
        for forbidden in (
            "inflation_rate",
            "price_index",
            "index_value",
            "normalised_weight",
            "normalized_weight",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, flat)

    def test_g_the_eleven_unresolved_uccs_were_not_touched(self) -> None:
        """Solving them is explicitly not this task's business either."""
        v2 = json.loads(res.SCOPE_RULES_V0_2_PATH.read_text(encoding="utf-8"))
        v3 = json.loads(res.SCOPE_RULES_V0_3_PATH.read_text(encoding="utf-8"))

        def unresolved(registry) -> list[str]:
            rule = next(
                r
                for r in registry["rules"]
                if r["rule_id"].startswith("UNRESOLVED")
            )
            return list(rule["source_uccs"])

        was = unresolved(v2)
        self.assertEqual(len(was), 11)
        self.assertEqual(unresolved(v3), was)

        claimed = {
            ucc
            for rule in res.SUCCESSOR_RULES
            for ucc in rule.source_uccs
        }
        self.assertEqual(claimed & set(was), set())

    def test_h_the_verdict_declares_a_known_status(self) -> None:
        self.assertIn(
            json.loads(res.VERDICT_PATH.read_text(encoding="utf-8"))[
                "residual_shelter_status"
            ],
            ("PASS", "PARTIAL", "BLOCKED"),
        )


if __name__ == "__main__":
    unittest.main()
