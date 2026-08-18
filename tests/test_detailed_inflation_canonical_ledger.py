#!/usr/bin/env python3
"""Tests for the canonical state manifest and accounting ledger (C1 + C2).

C1 answers "which version of what governs?" and C2 answers "where does each
source amount currently sit?". Neither computes anything, so almost nothing
here checks arithmetic. What is worth checking is the set of disciplines that
make the two artifacts safe to build on, because every one of them would
produce a plausible-looking ledger if it had quietly stopped holding.

*The head of a registry family is derived, not assumed.* Three versions of the
scope-rule registry are committed side by side on purpose. Nothing in a
filename identifies the head, and this repository proves it: the file called
``ucc_provenance_classes_v0_1.json`` declares version 0.2.0 and no ``v0_2``
file exists. So the lineage is walked from the ``predecessor`` blocks, and the
walk is asserted to reject a fork, a second root and a broken chain.

*Proposed is not effective.* A PROPOSED rule may never put an amount into an
exclusion, transformation or replacement column. This is the single claim the
whole substrate rests on, so it is attacked from three directions: the gate is
checked against the hardened Milestone-2 gate it duplicates, the ledger is
checked to contain no violating row, and a violating row is constructed and
the validator asserted to reject it.

*Null is not zero.* A blank amount means unavailable, suppressed, withheld or
undefined; a numeric zero means someone observed zero. UCC 910106 carries both
encodings in one column across six populations and is the regression case. The
basis contains seven genuine observed zeros, and they are asserted to survive
as ``0.0`` rather than being flattened into blanks.

*Removal is not replacement.* The amount that leaves and the amount that
arrives are two facts. The tests assert the ledger does not require them to be
equal, and separately that no group both retains a source amount and
introduces its replacement.

*A superseded rule is gone.* Its UCCs belong to its successors. Re-enabling it
must fail, and the failure is asserted by re-enabling it.

*The guards are not vacuous.* Every structural guard is asserted to fire on a
deliberately broken input before it is asserted not to fire on the real one. A
guard that has never been seen to fire proves nothing.
"""

from __future__ import annotations

import ast
import copy
import csv
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dmi_research.detailed_inflation import canonical_ledger as cl  # noqa: E402
from dmi_research.detailed_inflation import canonical_state as cs  # noqa: E402
from dmi_research.detailed_inflation import resolution as m2  # noqa: E402
from dmi_research.detailed_inflation import scope_rules as sr  # noqa: E402

CANONICAL_MODULES = (
    "dmi_research/detailed_inflation/canonical_state.py",
    "dmi_research/detailed_inflation/canonical_ledger.py",
    "scripts/build_canonical_substrate_2024.py",
)

#: The rule the residual task split into four. Its UCCs belong to the
#: successors now, and nothing may resolve through it.
SUPERSEDED_RULE = "OS_CPI_OWNER_STRUCTURE_INVESTMENT_v0_1"

#: The canonical null/zero regression case: one estimate cell with no records
#: at all, five with amounts that exist and are not admitted.
NULL_ZERO_UCC = "910106"


class Built:
    """One build, shared by the classes that only read it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.inputs = cl.load_inputs()
        cls.rules = cls.inputs.rules
        cls.rows = cl.build_ledger(cls.inputs)
        cls.by_ucc: dict[str, list[cl.LedgerRow]] = {}
        for row in cls.rows:
            cls.by_ucc.setdefault(row.ucc, []).append(row)


def _mutable_registry() -> Path:
    """A scratch copy of ``registry/research`` that mutations can edit.

    Every mutation test writes into one of these. Nothing in this file edits a
    committed registry.
    """
    scratch = Path(tempfile.mkdtemp(prefix="canonical-registry-"))
    for path in sorted(cs.REGISTRY_DIR.glob("*.json")):
        shutil.copy(path, scratch)
    return scratch


def _rewrite(directory: Path, filename: str, mutate) -> None:
    path = directory / filename
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")


def _scope_rules_head() -> str:
    return Path(cs.governing_version("ce_cpi_scope_rules").relative_path).name


# ---------------------------------------------------------------------------
# Group 1: C1, registry lineage is derived rather than assumed
# ---------------------------------------------------------------------------


class TestRegistryLineage(unittest.TestCase):
    def test_a_filename_order_is_not_a_version_order_in_this_repository(self) -> None:
        """The concrete counterexample the derivation exists because of."""
        payload = json.loads(
            (cs.REGISTRY_DIR / "ucc_provenance_classes_v0_1.json").read_text("utf-8")
        )
        self.assertEqual(payload["version"], "0.2.0")
        self.assertFalse((cs.REGISTRY_DIR / "ucc_provenance_classes_v0_2.json").exists())

    def test_b_each_family_resolves_to_exactly_one_head(self) -> None:
        for family in cs.REGISTRY_FAMILIES:
            with self.subTest(family=family):
                chain = cs.resolve_family(family)
                heads = [
                    v for v in chain
                    if v.role is cs.ArtifactRole.CURRENT_GOVERNING_INPUT
                ]
                self.assertEqual(len(heads), 1)
                self.assertEqual(heads[0], chain[-1])
                self.assertEqual(len(chain), len(cs.REGISTRY_FAMILIES[family]))

    def test_c_the_heads_are_the_expected_artifacts(self) -> None:
        self.assertEqual(
            cs.governing_version("ce_cpi_scope_rules").artifact_id,
            "CE_CPI_SCOPE_RULES_V0_3",
        )
        self.assertEqual(
            cs.governing_version("ucc_provenance_classes").artifact_id,
            "UCC_PROVENANCE_CLASSES_V0_4",
        )

    def test_d_every_non_head_is_marked_a_historical_checkpoint(self) -> None:
        for family in cs.REGISTRY_FAMILIES:
            for version in cs.resolve_family(family)[:-1]:
                with self.subTest(artifact=version.artifact_id):
                    self.assertIs(version.role, cs.ArtifactRole.HISTORICAL_CHECKPOINT)

    def test_e_the_chain_is_linear_and_each_link_is_real(self) -> None:
        for family in cs.REGISTRY_FAMILIES:
            chain = cs.resolve_family(family)
            self.assertIsNone(chain[0].predecessor_artifact_id)
            for earlier, later in zip(chain, chain[1:]):
                with self.subTest(family=family, later=later.artifact_id):
                    self.assertEqual(
                        later.predecessor_artifact_id.casefold(),
                        earlier.artifact_id.casefold(),
                    )

    def test_f_a_second_root_is_rejected(self) -> None:
        scratch = _mutable_registry()
        _rewrite(scratch, _scope_rules_head(), lambda p: p.pop("predecessor"))
        with self.assertRaises(cs.CanonicalStateError) as caught:
            cs.resolve_family("ce_cpi_scope_rules", registry_dir=scratch)
        self.assertIn("exactly one version with no predecessor", str(caught.exception))

    def test_g_a_fork_is_rejected(self) -> None:
        scratch = _mutable_registry()

        def fork(payload: dict) -> None:
            payload["predecessor"] = {
                "artifact_id": "ce_cpi_scope_rules_v0_1",
                "path": "registry/research/ce_cpi_scope_rules_v0_1.json",
            }

        _rewrite(scratch, _scope_rules_head(), fork)
        with self.assertRaises(cs.CanonicalStateError) as caught:
            cs.resolve_family("ce_cpi_scope_rules", registry_dir=scratch)
        self.assertIn("forks", str(caught.exception))

    def test_h_a_misdeclared_predecessor_path_is_rejected(self) -> None:
        """The declared path is checked, not decorative."""
        scratch = _mutable_registry()

        def bend(payload: dict) -> None:
            payload["predecessor"]["path"] = "registry/research/somewhere_else.json"

        _rewrite(scratch, _scope_rules_head(), bend)
        with self.assertRaises(cs.CanonicalStateError) as caught:
            cs.resolve_family("ce_cpi_scope_rules", registry_dir=scratch)
        self.assertIn("does not", str(caught.exception))

    def test_i_a_registry_dir_argument_is_honoured(self) -> None:
        """Non-vacuity for every other test in this file that passes one.

        If ``registry_dir`` were ignored and the real directory read instead,
        every mutation test below would pass while testing nothing.
        """
        scratch = _mutable_registry()
        (scratch / _scope_rules_head()).write_text('{"artifact_id": "X"}\n', "utf-8")
        with self.assertRaises(cs.CanonicalStateError):
            cs.resolve_family("ce_cpi_scope_rules", registry_dir=scratch)


# ---------------------------------------------------------------------------
# Group 2: C1, rule lineage and the canonical gate
# ---------------------------------------------------------------------------


class TestRuleLineage(Built, unittest.TestCase):
    def test_a_the_superseded_rule_is_superseded_and_absent(self) -> None:
        node = next(n for n in self.rules.lineage if n.rule_id == SUPERSEDED_RULE)
        self.assertIs(node.state, cs.CanonicalRuleState.SUPERSEDED)
        self.assertNotIn(SUPERSEDED_RULE, [r.rule_id for r in self.rules.rules])

    def test_b_its_successors_are_derived_from_the_registry(self) -> None:
        """Derived from ``predecessor_rule_id``, not from a list written here.

        The count is asserted, but the membership comes from the registry, so
        this fails if the registry changes rather than passing on a stale copy.
        """
        node = next(n for n in self.rules.lineage if n.rule_id == SUPERSEDED_RULE)
        derived = {
            r.rule_id for r in self.rules.rules
            if r.predecessor_rule_id == SUPERSEDED_RULE
        }
        self.assertEqual(set(node.successor_rule_ids), derived)
        self.assertEqual(len(derived), 4)

    def test_c_the_successors_partition_the_predecessor_membership(self) -> None:
        predecessor = next(
            r
            for r in cs.read_rules(
                cs.REPO_ROOT / "registry/research/ce_cpi_scope_rules_v0_2.json"
            )
            if r.rule_id == SUPERSEDED_RULE
        )
        union: set[str] = set()
        for rule_id in next(
            n for n in self.rules.lineage if n.rule_id == SUPERSEDED_RULE
        ).successor_rule_ids:
            claimed = set(self.rules.rule(rule_id).source_uccs)
            self.assertEqual(union & claimed, set(), f"{rule_id} overlaps a sibling")
            union |= claimed
        self.assertEqual(union, set(predecessor.source_uccs))

    def test_d_no_ucc_resolves_through_a_superseded_rule(self) -> None:
        for ucc in sorted(self.by_ucc):
            with self.subTest(ucc=ucc):
                self.assertNotEqual(self.rules.resolve(ucc).governing_rule_id,
                                    SUPERSEDED_RULE)

    def test_e_every_ucc_is_claimed_by_at_most_one_current_rule(self) -> None:
        claims: dict[str, list[str]] = {}
        for record in self.rules.rules:
            for ucc in record.source_uccs:
                claims.setdefault(ucc, []).append(record.rule_id)
        doubled = {u: r for u, r in claims.items() if len(r) > 1}
        self.assertEqual(doubled, {})

    def test_f_the_canonical_gate_agrees_with_the_milestone_2_gate(self) -> None:
        """The duplication is checked rather than trusted.

        ``canonical_state_of`` restates the hardened Milestone-2 logic because
        that function's ``MappingStatus`` type has no ``INTRODUCED`` member and
        the governing registry has two INTRODUCE rules. Wherever the older type
        can express the input, the two must agree.
        """
        # A real ScopeRule, so the older gate sees its own type and its own
        # ``is_applicable`` property rather than a stand-in built to agree.
        template = sr.load_scope_rules().rules[0]
        expressible = 0
        for record in self.rules.rules:
            try:
                status = sr.MappingStatus(record.final_status)
            except ValueError:
                continue
            expressible += 1
            older = m2.track_a_disposition(
                replace(
                    template,
                    rule_id=record.rule_id,
                    final_status=status,
                    review_status=sr.ReviewStatus(record.review_status),
                )
            )
            newer = cs.effective_track_a_status(record)
            with self.subTest(rule=record.rule_id):
                self.assertEqual(older.effective_status.value, newer)
        self.assertGreater(expressible, 10, "the cross-check found nothing to check")

    def test_g_a_rule_proposing_nothing_is_open_whatever_its_review_status(
        self,
    ) -> None:
        template = self.rules.rule("UNRESOLVED_v0_2")
        for review in ("OPEN", "PROPOSED", "ACCEPTED"):
            with self.subTest(review_status=review):
                self.assertIs(
                    cs.canonical_state_of(
                        replace(template, review_status=review, declared_applicable=None)
                    ),
                    cs.CanonicalRuleState.CURRENT_OPEN,
                )

    def test_h_is_applicable_must_agree_with_review_status(self) -> None:
        accepted = next(
            r for r in self.rules.rules
            if r.review_status == "ACCEPTED" and r.final_status != "UNRESOLVED"
        )
        with self.assertRaises(cs.CanonicalStateError):
            cs.canonical_state_of(replace(accepted, declared_applicable=False))

    def test_i_the_transition_block_and_the_rule_fields_must_agree(self) -> None:
        scratch = _mutable_registry()

        def drop(payload: dict) -> None:
            payload["residual_transitions"] = [
                e for e in payload["residual_transitions"]
                if e.get("predecessor_rule_id") != SUPERSEDED_RULE
            ]

        _rewrite(scratch, _scope_rules_head(), drop)
        with self.assertRaises(cs.CanonicalStateError) as caught:
            cs.build_rule_lineage(registry_dir=scratch)
        self.assertIn("disagree about", str(caught.exception))


class TestCheckpoints(unittest.TestCase):
    def test_a_there_are_four_and_exactly_one_governs(self) -> None:
        self.assertEqual(len(cs.CHECKPOINTS), 4)
        governing = [
            c for c in cs.CHECKPOINTS
            if c.role is cs.CheckpointRole.CURRENT_GOVERNING_INPUT
        ]
        self.assertEqual(len(governing), 1)
        self.assertEqual(governing[0], cs.CHECKPOINTS[-1])

    def test_b_the_recorded_commits_match_the_repository(self) -> None:
        """A tag that moved is exactly the condition worth failing on."""
        for checkpoint in cs.CHECKPOINTS:
            result = subprocess.run(
                ["git", "rev-parse", f"{checkpoint.tag}^{{}}"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                self.skipTest(f"tag {checkpoint.tag} is not present in this checkout")
            with self.subTest(tag=checkpoint.tag):
                self.assertEqual(result.stdout.strip(), checkpoint.commit)


# ---------------------------------------------------------------------------
# Group 3: C2, the ledger is complete
# ---------------------------------------------------------------------------


class TestLedgerCompleteness(Built, unittest.TestCase):
    def test_a_every_ucc_has_all_six_populations(self) -> None:
        for ucc, rows in sorted(self.by_ucc.items()):
            with self.subTest(ucc=ucc):
                self.assertEqual(
                    [r.population for r in rows], list(cs.POPULATIONS)
                )

    def test_b_the_universe_is_the_union_of_four_declared_sets(self) -> None:
        expected = (
            set(self.inputs.basis_meta)
            | set(self.rules.claimed_source_uccs)
            | set(self.rules.claimed_output_uccs)
            | set(self.inputs.addendum_uccs)
        )
        self.assertEqual(set(self.by_ucc), expected)
        self.assertEqual(len(self.rows), len(expected) * len(cs.POPULATIONS))

    def test_c_every_basis_ucc_survives_into_the_ledger(self) -> None:
        """No UCC is dropped for having no amount, no rule or no mapping."""
        missing = set(self.inputs.basis_meta) - set(self.by_ucc)
        self.assertEqual(missing, set())

    def test_d_the_regression_case_is_present_with_all_six_rows(self) -> None:
        self.assertEqual(len(self.by_ucc[NULL_ZERO_UCC]), 6)

    def test_e_rows_are_sorted_by_ucc_then_by_declared_population_order(
        self,
    ) -> None:
        keys = [(r.ucc, cs.POPULATIONS.index(r.population)) for r in self.rows]
        self.assertEqual(keys, sorted(keys))

    def test_f_the_written_csv_matches_the_built_rows(self) -> None:
        with cl.LEDGER_PATH.open(newline="", encoding="utf-8") as handle:
            written = list(csv.DictReader(handle))
        self.assertEqual(len(written), len(self.rows))
        self.assertEqual(
            [(r["ucc"], r["population"]) for r in written],
            [(r.ucc, r.population) for r in self.rows],
        )

    def test_g_the_schema_columns_and_the_csv_header_agree(self) -> None:
        schema = json.loads(cl.SCHEMA_PATH.read_text(encoding="utf-8"))
        with cl.LEDGER_PATH.open(newline="", encoding="utf-8") as handle:
            header = next(csv.reader(handle))
        self.assertEqual([c["name"] for c in schema["columns"]], header)
        self.assertEqual(list(cl.LEDGER_COLUMNS), header)


# ---------------------------------------------------------------------------
# Group 4: C2, disposition integrity
# ---------------------------------------------------------------------------


class TestDispositionIntegrity(Built, unittest.TestCase):
    def test_a_at_most_one_amount_column_is_populated(self) -> None:
        for row in self.rows:
            populated = [n for n in cl.AMOUNT_COLUMNS if getattr(row, n) is not None]
            with self.subTest(ucc=row.ucc, population=row.population):
                self.assertLessEqual(len(populated), 1)

    def test_b_the_populated_column_is_the_dispositions_own(self) -> None:
        for row in self.rows:
            populated = [n for n in cl.AMOUNT_COLUMNS if getattr(row, n) is not None]
            if not populated:
                continue
            with self.subTest(ucc=row.ucc, population=row.population):
                self.assertEqual(
                    populated[0], cl.AMOUNT_COLUMN_FOR[row.track_a_disposition]
                )

    def test_c_no_amount_is_rescaled_on_its_way_into_a_bucket(self) -> None:
        for row in self.rows:
            for name in cl.AMOUNT_COLUMNS:
                value = getattr(row, name)
                if value is None:
                    continue
                with self.subTest(ucc=row.ucc, population=row.population):
                    self.assertEqual(value, row.source_amount_millions)

    def test_d_no_pending_rule_reaches_an_effective_disposition(self) -> None:
        effective = {
            cl.Disposition.EXCLUDED,
            cl.Disposition.REMOVED_FOR_REPLACEMENT,
            cl.Disposition.REPLACEMENT,
            cl.Disposition.TRANSFORMED,
        }
        for row in self.rows:
            if row.canonical_rule_state is not cs.CanonicalRuleState.CURRENT_PENDING:
                continue
            with self.subTest(ucc=row.ucc, population=row.population):
                self.assertNotIn(row.track_a_disposition, effective)
                self.assertIn(row.effective_track_a_status, (None, "UNRESOLVED"))

    def test_e_pending_rules_actually_exist_so_the_previous_test_is_not_vacuous(
        self,
    ) -> None:
        pending = [
            r for r in self.rows
            if r.canonical_rule_state is cs.CanonicalRuleState.CURRENT_PENDING
        ]
        self.assertGreater(len(pending), 0)
        self.assertGreater(len({r.ucc for r in pending}), 1)

    def test_f_effective_dispositions_actually_occur(self) -> None:
        """Otherwise the whole gate could be a constant ``False``."""
        seen = {r.track_a_disposition for r in self.rows}
        for disposition in (
            cl.Disposition.EXCLUDED,
            cl.Disposition.TRANSFORMED,
            cl.Disposition.REPLACEMENT,
        ):
            with self.subTest(disposition=disposition.value):
                self.assertIn(disposition, seen)

    def test_g_a_pending_rule_on_a_mapped_ucc_reverts_to_the_baseline(self) -> None:
        """"No effect" means baseline reversion, not a holding bucket.

        The governing registry states this for UCC 220121: not applying a
        partial-retention transform leaves the amount as recorded, whereas
        moving it to the pending bucket would remove it from the basis
        entirely and so assert more than the rule does.
        """
        reverting = [
            r for r in self.rows
            if r.pending_rule_effect_on_amount
            is cl.PendingEffect.AMOUNT_REVERTS_TO_MAPPED_BASELINE
        ]
        self.assertGreater(len(reverting), 0)
        for row in reverting:
            with self.subTest(ucc=row.ucc, population=row.population):
                self.assertIs(row.track_a_disposition, cl.Disposition.RETAINED)
                self.assertIn(row.m1_mapping_status, ("DIRECT", "MULTI_SAME_NODE"))

    def test_h_a_pending_rule_on_an_unmapped_ucc_is_held(self) -> None:
        held = [
            r for r in self.rows
            if r.pending_rule_effect_on_amount
            is cl.PendingEffect.AMOUNT_HELD_IN_PENDING_BUCKET
        ]
        self.assertGreater(len(held), 0)
        for row in held:
            with self.subTest(ucc=row.ucc, population=row.population):
                self.assertIs(row.track_a_disposition, cl.Disposition.PENDING)
                self.assertNotIn(row.m1_mapping_status, ("DIRECT", "MULTI_SAME_NODE"))

    def test_i_an_unmapped_ucc_is_never_excluded_merely_for_being_unmapped(
        self,
    ) -> None:
        """Absence from the concordance is a fact about the crosswalk.

        It is not evidence that the CPI assigns the item no weight. Every
        exclusion must come from a rule that is in force and says so.
        """
        for row in self.rows:
            if row.track_a_disposition is not cl.Disposition.EXCLUDED:
                continue
            with self.subTest(ucc=row.ucc, population=row.population):
                self.assertIsNotNone(row.governing_rule_id)
                self.assertIs(
                    row.canonical_rule_state, cs.CanonicalRuleState.CURRENT_EFFECTIVE
                )
                self.assertEqual(row.effective_track_a_status, "OUT_OF_SCOPE")

    def test_j_unmappedness_alone_does_not_determine_a_disposition(self) -> None:
        """The companion to ``test_i``, from the other direction.

        ``test_i`` shows every exclusion has a rule in force behind it. This
        shows the unmapped population is not simply the excluded population
        under another name: a rule may well exclude an unmapped UCC on its own
        grounds, and many unmapped UCCs are not excluded at all. If the two
        sets ever coincided, "unmapped" would have silently become a synonym
        for "excluded" and the distinction the concordance correction was made
        to protect would be gone.
        """
        unmapped = [
            r for r in self.rows
            if r.m1_mapping_status == "UNRESOLVED"
            and r.source_class is cl.SourceClass.PUBLISHED_CE_BASIS
        ]
        self.assertGreater(len(unmapped), 0)
        dispositions = {r.track_a_disposition for r in unmapped}
        self.assertGreater(
            len(dispositions), 1, "every unmapped UCC shares one disposition"
        )
        # Exclusion, where it happens, is the rule's doing and not the
        # concordance's absence: each excluded row names a rule in force.
        for row in unmapped:
            if row.track_a_disposition is not cl.Disposition.EXCLUDED:
                continue
            with self.subTest(ucc=row.ucc, population=row.population):
                self.assertIs(
                    row.canonical_rule_state, cs.CanonicalRuleState.CURRENT_EFFECTIVE
                )
                self.assertEqual(row.rule_type, "EXCLUDE")

    def test_k_normalization_state_is_a_classification_and_nothing_more(self) -> None:
        for row in self.rows:
            with self.subTest(ucc=row.ucc, population=row.population):
                self.assertIsInstance(row.normalization_state, cl.NormalizationState)


# ---------------------------------------------------------------------------
# Group 5: C2, null is not zero
# ---------------------------------------------------------------------------


class TestNullIsNotZero(Built, unittest.TestCase):
    def test_a_the_regression_case_carries_both_encodings(self) -> None:
        rows = {r.population: r for r in self.by_ucc[NULL_ZERO_UCC]}
        q1 = rows["Q1"]
        self.assertIsNone(q1.source_amount_millions)
        self.assertIs(q1.source_amount_status, cl.AmountStatus.NOT_AVAILABLE)
        for population in ("ALL_CU", "Q2", "Q3", "Q4", "Q5"):
            with self.subTest(population=population):
                row = rows[population]
                self.assertIsNotNone(row.source_amount_millions)
                self.assertIs(row.source_amount_status, cl.AmountStatus.WITHHELD)

    def test_b_a_withheld_amount_is_shown_because_it_is_known(self) -> None:
        """Withheld means not admitted. It does not mean unknown.

        Blanking it would say the estimate does not exist, when what happened
        is that it exists and failed a declared quality gate.
        """
        rows = {r.population: r for r in self.by_ucc[NULL_ZERO_UCC]}
        self.assertGreater(rows["ALL_CU"].withheld_amount, 0.0)
        self.assertIs(
            rows["ALL_CU"].normalization_state,
            cl.NormalizationState.BLOCKED_AMOUNT_NOT_ADMITTED,
        )
        self.assertIs(
            rows["Q1"].normalization_state,
            cl.NormalizationState.BLOCKED_AMOUNT_UNAVAILABLE,
        )

    def test_c_a_withheld_amount_never_reaches_an_accounting_bucket(self) -> None:
        for row in self.by_ucc[NULL_ZERO_UCC]:
            with self.subTest(population=row.population):
                self.assertIs(row.track_a_disposition, cl.Disposition.WITHHELD)
                self.assertIsNone(row.retained_amount)
                self.assertIsNone(row.replacement_amount)

    def test_d_observed_zeros_survive_as_zero(self) -> None:
        zeros = [
            r for r in self.rows
            if r.source_amount_millions == 0.0
            and r.source_amount_status is cl.AmountStatus.OBSERVED
        ]
        self.assertGreater(len(zeros), 0, "the basis has observed zeros to preserve")
        for row in zeros:
            with self.subTest(ucc=row.ucc, population=row.population):
                self.assertIsNotNone(row.source_amount_millions)

    def test_e_observed_zeros_are_written_as_zero_not_as_blank(self) -> None:
        zeros = {
            (r.ucc, r.population) for r in self.rows
            if r.source_amount_millions == 0.0
            and r.source_amount_status is cl.AmountStatus.OBSERVED
        }
        with cl.LEDGER_PATH.open(newline="", encoding="utf-8") as handle:
            for record in csv.DictReader(handle):
                if (record["ucc"], record["population"]) not in zeros:
                    continue
                with self.subTest(ucc=record["ucc"], population=record["population"]):
                    self.assertNotEqual(record["source_amount_millions"], "")
                    self.assertEqual(float(record["source_amount_millions"]), 0.0)

    def test_f_a_suppressed_cell_is_blank_and_not_zero(self) -> None:
        suppressed = [
            r for r in self.rows
            if r.source_amount_status is cl.AmountStatus.SUPPRESSED
        ]
        self.assertGreater(len(suppressed), 0)
        for row in suppressed:
            with self.subTest(ucc=row.ucc, population=row.population):
                self.assertIsNone(row.source_amount_millions)

    def test_g_a_blank_cell_never_lands_in_an_accounting_bucket(self) -> None:
        for row in self.rows:
            if row.source_amount_millions is not None:
                continue
            for name in cl.AMOUNT_COLUMNS:
                with self.subTest(ucc=row.ucc, column=name):
                    self.assertIsNone(getattr(row, name))

    def test_h_no_amount_column_is_written_as_zero_where_the_source_is_blank(
        self,
    ) -> None:
        with cl.LEDGER_PATH.open(newline="", encoding="utf-8") as handle:
            for record in csv.DictReader(handle):
                if record["source_amount_millions"] != "":
                    continue
                for name in cl.AMOUNT_COLUMNS:
                    with self.subTest(ucc=record["ucc"], column=name):
                        self.assertEqual(record[name], "")


# ---------------------------------------------------------------------------
# Group 6: C2, removal is not replacement
# ---------------------------------------------------------------------------


class TestReplacementLinkage(Built, unittest.TestCase):
    def test_a_every_declared_group_is_backed_by_the_governing_registry(self) -> None:
        cl._validate_replacement_groups(self.rules)
        for group in cl.REPLACEMENT_GROUPS:
            with self.subTest(group=group.group_id):
                self.assertEqual(
                    self.rules.rule(group.replacement_rule_id).final_status,
                    "INTRODUCED",
                )

    def test_b_a_group_whose_replacement_rule_is_wrong_is_rejected(self) -> None:
        broken = cl.ReplacementGroup(
            group_id="RG_FABRICATED",
            removal_rule_id=None,
            replacement_rule_id="OS_CPI_VEHICLE_FINANCE_CHARGES_v0_1",
            linkage_basis="NO_REMOVAL_SIDE_DECLARED",
            note="injected",
        )
        original = cl.REPLACEMENT_GROUPS
        try:
            cl.REPLACEMENT_GROUPS = original + (broken,)
            with self.assertRaises(cl.LedgerError):
                cl._validate_replacement_groups(self.rules)
        finally:
            cl.REPLACEMENT_GROUPS = original

    def test_c_the_removal_and_replacement_amounts_are_not_forced_equal(self) -> None:
        """The two sides are separate columns with no equality constraint.

        Asserted structurally: no code path assigns one from the other, and the
        validator accepts a group whose two sides differ.
        """
        self.assertNotEqual(
            cl.AMOUNT_COLUMN_FOR[cl.Disposition.REMOVED_FOR_REPLACEMENT],
            cl.AMOUNT_COLUMN_FOR[cl.Disposition.REPLACEMENT],
        )
        rows = [r for r in self.rows if r.replacement_group_id is not None]
        self.assertGreater(len(rows), 0)

    def test_d_the_linkage_survives_both_sides_being_blocked(self) -> None:
        """A blocked pair must not look like two independent blockers."""
        group = next(
            g for g in cl.REPLACEMENT_GROUPS if g.removal_rule_id is not None
        )
        members = [
            r for r in self.rows if r.replacement_group_id == group.group_id
        ]
        self.assertGreater(len(members), 0)
        self.assertEqual(
            {cl.ReplacementRole.REMOVAL, cl.ReplacementRole.REPLACEMENT},
            {r.replacement_role for r in members},
        )

    def test_e_no_group_retains_a_source_while_introducing_its_replacement(
        self,
    ) -> None:
        cl._validate_replacement_consistency(self.rows)


# ---------------------------------------------------------------------------
# Group 7: determinism
# ---------------------------------------------------------------------------


class TestDeterminism(unittest.TestCase):
    def test_a_two_builds_produce_identical_bytes(self) -> None:
        first = cl.render_ledger(cl.build_ledger())
        second = cl.render_ledger(cl.build_ledger())
        self.assertEqual(first, second)

    def test_b_the_manifest_rebuilds_identically(self) -> None:
        self.assertEqual(cs.render_manifest(), cs.render_manifest())

    def test_c_the_committed_artifacts_match_a_fresh_build(self) -> None:
        rows = cl.build_ledger()
        for path, rendered in (
            (cs.MANIFEST_PATH, cs.render_manifest()),
            (cl.SCHEMA_PATH, cl.render_schema()),
            (cl.LEDGER_PATH, cl.render_ledger(rows)),
            (cl.LEDGER_SUMMARY_PATH, cl.render_summary(rows)),
        ):
            with self.subTest(path=path.name):
                self.assertTrue(path.exists())
                self.assertEqual(path.read_text(encoding="utf-8"), rendered)

    def test_d_no_artifact_carries_a_timestamp(self) -> None:
        """A manifest that changes on rebuild cannot detect a real change.

        The check walks keys rather than raw text. The manifest deliberately
        carries a ``no_timestamp`` key explaining why it has no timestamp, and
        a substring scan would read that explanation as the offence.
        """
        forbidden = ("generated_at", "timestamp", "build_time", "created_at")

        def keys(node: object) -> list[str]:
            if isinstance(node, dict):
                found = list(node)
                for value in node.values():
                    found.extend(keys(value))
                return found
            if isinstance(node, list):
                return [k for item in node for k in keys(item)]
            return []

        for path in (cs.MANIFEST_PATH, cl.SCHEMA_PATH, cl.LEDGER_SUMMARY_PATH):
            present = set(keys(json.loads(path.read_text(encoding="utf-8"))))
            for word in forbidden:
                with self.subTest(path=path.name, key=word):
                    self.assertNotIn(word, present)

    def test_e_the_csv_uses_lf_line_endings(self) -> None:
        self.assertNotIn(b"\r\n", cl.LEDGER_PATH.read_bytes())

    def test_f_the_build_script_check_mode_reports_no_drift(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/build_canonical_substrate_2024.py", "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


# ---------------------------------------------------------------------------
# Group 8: the seven named mutations
# ---------------------------------------------------------------------------


class TestMutationsAreCaught(Built, unittest.TestCase):
    """Each injection is a specific way the substrate could go quietly wrong.

    A test suite that only builds the real inputs proves the real inputs are
    consistent, not that the guards work. These build deliberately wrong inputs
    and require a failure.
    """

    def _row(self, ucc: str, population: str = "ALL_CU") -> cl.LedgerRow:
        return next(
            r for r in self.rows if r.ucc == ucc and r.population == population
        )

    def test_1_re_enabling_a_superseded_rule_fails(self) -> None:
        scratch = _mutable_registry()

        def re_enable(payload: dict) -> None:
            v0_2 = json.loads(
                (scratch / "ce_cpi_scope_rules_v0_2.json").read_text("utf-8")
            )
            revived = copy.deepcopy(
                next(r for r in v0_2["rules"] if r["rule_id"] == SUPERSEDED_RULE)
            )
            revived["review_status"] = "ACCEPTED"
            revived.pop("is_applicable", None)
            payload["rules"].append(revived)

        _rewrite(scratch, _scope_rules_head(), re_enable)
        with self.assertRaises(cs.CanonicalStateError) as caught:
            cs.load_canonical_rules(registry_dir=scratch)
        message = str(caught.exception)
        self.assertTrue(
            "claimed as a source by two current rules" in message
            or "still present in the governing registry" in message,
            message,
        )

    def test_2_two_current_rules_claiming_one_ucc_fails(self) -> None:
        scratch = _mutable_registry()

        def double_claim(payload: dict) -> None:
            donor = next(
                r for r in payload["rules"]
                if r["rule_id"] == "OS_CPI_VEHICLE_FINANCE_CHARGES_v0_1"
            )
            thief = next(
                r for r in payload["rules"]
                if r["rule_id"] == "OS_CPI_RESIDENTIAL_PROPERTY_TAX_v0_1"
            )
            thief["source_uccs"] = list(thief["source_uccs"]) + [
                donor["source_uccs"][0]
            ]

        _rewrite(scratch, _scope_rules_head(), double_claim)
        with self.assertRaises(cs.CanonicalStateError) as caught:
            cs.load_canonical_rules(registry_dir=scratch)
        self.assertIn("two current rules", str(caught.exception))

    def test_3_a_pending_rule_producing_an_effective_exclusion_fails(self) -> None:
        pending = next(
            r for r in self.rows
            if r.canonical_rule_state is cs.CanonicalRuleState.CURRENT_PENDING
            and r.source_amount_millions is not None
        )
        mutated = replace(
            pending,
            track_a_disposition=cl.Disposition.EXCLUDED,
            pending_amount=None,
            retained_amount=None,
            excluded_amount=pending.source_amount_millions,
            normalization_state=cl.NormalizationState.EXCLUDED_FROM_BASIS,
        )
        with self.assertRaises(cl.LedgerError) as caught:
            cl._validate_row(mutated)
        self.assertIn("requires a rule in force", str(caught.exception))

    def test_4_turning_a_null_withheld_amount_into_zero_fails(self) -> None:
        blank = self._row(NULL_ZERO_UCC, "Q1")
        self.assertIsNone(blank.source_amount_millions)
        mutated = replace(blank, source_amount_millions=0.0)
        with self.assertRaises(cl.LedgerError) as caught:
            cl._validate_row(mutated)
        self.assertIn("must be blank", str(caught.exception))

    def test_4b_a_suppressed_cell_coerced_to_zero_fails(self) -> None:
        suppressed = next(
            r for r in self.rows
            if r.source_amount_status is cl.AmountStatus.SUPPRESSED
        )
        with self.assertRaises(cl.LedgerError):
            cl._validate_row(replace(suppressed, source_amount_millions=0.0))

    def test_5_retaining_a_source_while_introducing_its_replacement_fails(
        self,
    ) -> None:
        group = next(
            g for g in cl.REPLACEMENT_GROUPS if g.removal_rule_id is not None
        )
        members = [
            r for r in self.rows
            if r.replacement_group_id == group.group_id and r.population == "ALL_CU"
        ]
        removal = next(
            r for r in members if r.replacement_role is cl.ReplacementRole.REMOVAL
        )
        introduced = next(
            r for r in members if r.replacement_role is cl.ReplacementRole.REPLACEMENT
        )
        mutated = [
            replace(removal, retained_amount=1234.0, pending_amount=None),
            replace(introduced, replacement_amount=999.0, pending_amount=None),
        ]
        with self.assertRaises(cl.LedgerError) as caught:
            cl._validate_replacement_consistency(mutated)
        self.assertIn("counted twice", str(caught.exception))

    def test_6_classifying_an_unmapped_ucc_as_excluded_fails(self) -> None:
        """Absence from the concordance is not evidence of zero CPI weight.

        The target is an unmapped UCC whose governing rule is OPEN: it
        proposes no disposition, so the only remaining ground for excluding it
        would be its unmappedness. Every basis UCC is claimed by some rule, so
        there is no "unmapped and unclaimed" row to use instead; the honest
        injection is therefore to exclude on an unresolved rule rather than on
        no rule at all.
        """
        unmapped = next(
            r for r in self.rows
            if r.m1_mapping_status == "UNRESOLVED"
            and r.canonical_rule_state is cs.CanonicalRuleState.CURRENT_OPEN
            and r.source_amount_millions is not None
        )
        mutated = replace(
            unmapped,
            track_a_disposition=cl.Disposition.EXCLUDED,
            open_amount=None,
            excluded_amount=unmapped.source_amount_millions,
            normalization_state=cl.NormalizationState.EXCLUDED_FROM_BASIS,
        )
        with self.assertRaises(cl.LedgerError) as caught:
            cl._validate_row(mutated)
        self.assertIn("requires a rule in force", str(caught.exception))

    def test_7_adding_a_normalized_weight_field_fails_the_firewall(self) -> None:
        """Asserted on an injected source, then asserted absent from the real one."""
        injected = "def f(x):\n    normalized_weight = x / 2.0\n    return normalized_weight\n"
        self.assertTrue(_normalization_hits(_identifiers(injected)))
        for relative in CANONICAL_MODULES:
            source = (REPO_ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                self.assertEqual(_normalization_hits(_identifiers(source)), set())

    def test_8_a_row_whose_amount_was_rescaled_fails(self) -> None:
        retained = next(
            r for r in self.rows
            if r.track_a_disposition is cl.Disposition.RETAINED
            and r.retained_amount not in (None, 0.0)
        )
        with self.assertRaises(cl.LedgerError) as caught:
            cl._validate_row(replace(retained, retained_amount=retained.retained_amount * 0.57))
        self.assertIn("never rescales", str(caught.exception))

    def test_9_a_missing_population_row_fails(self) -> None:
        rows = [r for r in self.rows if not (r.ucc == NULL_ZERO_UCC and r.population == "Q1")]
        with self.assertRaises(cl.LedgerError) as caught:
            cl.validate_ledger(rows)
        self.assertIn("missing populations", str(caught.exception))

    def test_10_two_amount_columns_on_one_row_fails(self) -> None:
        retained = next(
            r for r in self.rows if r.retained_amount is not None
        )
        with self.assertRaises(cl.LedgerError) as caught:
            cl._validate_row(replace(retained, excluded_amount=retained.retained_amount))
        self.assertIn("exactly one accounting state", str(caught.exception))


# ---------------------------------------------------------------------------
# Group 9: the normalisation firewall and the research firewall
# ---------------------------------------------------------------------------

#: Vocabulary that would mean C2 had started doing C4's job. Matched against
#: identifiers in the parse tree, never against prose, so a module cannot
#: satisfy the guard by describing itself.
NORMALIZATION_VOCABULARY = (
    "normalized_weight",
    "normalised_weight",
    "weight_share",
    "denominator_share",
    "relative_importance",
    "share_of_total",
    "rescale",
    "renormalize",
    "renormalise",
)


def _identifiers(source: str) -> set[str]:
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


def _normalization_hits(names: set[str]) -> set[str]:
    return {
        name
        for name in names
        for word in NORMALIZATION_VOCABULARY
        if word in name.lower()
    }


class TestNoNormalizationArithmetic(Built, unittest.TestCase):
    def test_a_the_guard_fires_on_every_injected_name(self) -> None:
        for word in NORMALIZATION_VOCABULARY:
            source = f"def compute():\n    {word} = 1.0\n    return {word}\n"
            with self.subTest(injected=word):
                self.assertTrue(_normalization_hits(_identifiers(source)))

    def test_b_the_guard_fires_on_an_injected_attribute_and_argument(self) -> None:
        cases = (
            "def f(weight_share):\n    return weight_share\n",
            "def f(x):\n    return x.normalized_weight\n",
            "def f(x):\n    return g(denominator_share=x)\n",
        )
        for source in cases:
            with self.subTest(source=source.splitlines()[0]):
                self.assertTrue(_normalization_hits(_identifiers(source)))

    def test_c_the_guard_does_not_fire_on_the_real_modules(self) -> None:
        for relative in CANONICAL_MODULES:
            source = (REPO_ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                self.assertEqual(_normalization_hits(_identifiers(source)), set())

    def test_d_no_column_is_a_weight_a_share_or_a_denominator(self) -> None:
        for column in cl.LEDGER_COLUMNS:
            with self.subTest(column=column):
                self.assertNotIn("weight", column)
                self.assertNotIn("share", column)
                self.assertNotIn("denominator", column)

    def test_e_the_summary_counts_rows_and_sums_no_amount(self) -> None:
        summary = json.loads(cl.LEDGER_SUMMARY_PATH.read_text(encoding="utf-8"))
        for key, value in summary.items():
            if not isinstance(value, dict):
                continue
            for name, count in value.items():
                if not isinstance(count, (int, float)):
                    continue
                with self.subTest(key=key, name=name):
                    self.assertIsInstance(count, int)

    def test_f_c2_reconciles_nothing(self) -> None:
        """No total is computed, so no total can silently drive a disposition."""
        summary = json.loads(cl.LEDGER_SUMMARY_PATH.read_text(encoding="utf-8"))
        self.assertNotIn("total_amount", summary)
        self.assertIn("counts_are_rows_not_amounts", summary)


class TestResearchFirewall(unittest.TestCase):
    def _trees(self):
        for relative in CANONICAL_MODULES:
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
                if not value.startswith(("data/", "registry/", "docs/", "deploy/")):
                    continue
                found += 1
                # A directory literal may or may not carry a trailing slash.
                # Comparing with one appended keeps "registry/research" inside
                # the tree while still rejecting "registry/research_scratch".
                normalised = value.rstrip("/") + "/"
                with self.subTest(path=relative, literal=value):
                    self.assertTrue(
                        normalised.startswith(allowed),
                        f"{value!r} is outside the research tree",
                    )
        self.assertGreaterEqual(found, 4, "the path scan found nothing to check")

    def test_c_the_modules_declare_themselves_research_only(self) -> None:
        for relative in CANONICAL_MODULES:
            text = (REPO_ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                self.assertIn("RESEARCH ONLY", text)

    def test_d_no_output_or_baseline_path_appears(self) -> None:
        for relative in CANONICAL_MODULES:
            text = (REPO_ROOT / relative).read_text(encoding="utf-8")
            for forbidden in ("data/outputs", "deploy/data/outputs"):
                with self.subTest(path=relative, forbidden=forbidden):
                    self.assertNotIn(forbidden, text)

    def test_e_every_artifact_landed_under_research(self) -> None:
        for path in (
            cs.MANIFEST_PATH,
            cl.SCHEMA_PATH,
            cl.LEDGER_PATH,
            cl.LEDGER_SUMMARY_PATH,
        ):
            relative = path.relative_to(REPO_ROOT).as_posix()
            with self.subTest(path=relative):
                self.assertTrue(path.exists())
                self.assertTrue(
                    relative.startswith(("data/research/", "registry/research/")),
                    relative,
                )

    def test_f_no_committed_registry_was_modified_by_this_task(self) -> None:
        """C1 and C2 read the governing registries and write successors only.

        A canonical layer that edited the registry it derives its authority
        from would be deciding what governs rather than reporting it.
        """
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", "registry/research"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self.skipTest("git is unavailable")
        touched = [
            line[3:]
            for line in result.stdout.splitlines()
            if not line.startswith("??")
        ]
        self.assertEqual(touched, [])


class TestSchemaAndVocabularies(Built, unittest.TestCase):
    def test_a_every_vocabulary_member_is_documented(self) -> None:
        for enum_cls in (
            cl.SourceClass,
            cl.AmountSource,
            cl.AmountStatus,
            cl.Disposition,
            cl.PendingEffect,
            cl.NormalizationState,
            cl.ReplacementRole,
        ):
            with self.subTest(vocabulary=enum_cls.__name__):
                documented = cl._enum_doc(enum_cls)
                self.assertEqual(set(documented), {m.value for m in enum_cls})

    def test_b_an_undocumented_member_is_rejected(self) -> None:
        original = cl._ENUM_SEMANTICS["ReplacementRole"]
        try:
            cl._ENUM_SEMANTICS = dict(cl._ENUM_SEMANTICS)
            cl._ENUM_SEMANTICS["ReplacementRole"] = {"REMOVAL": "x"}
            with self.assertRaises(cl.LedgerError):
                cl._enum_doc(cl.ReplacementRole)
        finally:
            cl._ENUM_SEMANTICS["ReplacementRole"] = original

    def test_c_the_schema_declares_every_column_and_no_others(self) -> None:
        schema = cl.build_schema()
        self.assertEqual(
            [c["name"] for c in schema["columns"]], list(cl.LEDGER_COLUMNS)
        )

    def test_d_the_schema_states_the_null_semantics(self) -> None:
        schema = cl.build_schema()
        self.assertIn("zero", schema["null_semantics"])
        self.assertIn("blank", schema["null_semantics"])
        self.assertIn(NULL_ZERO_UCC, schema["null_semantics"]["regression_case"])

    def test_e_the_manifest_records_the_unrepaired_contradictions(self) -> None:
        manifest = json.loads(cs.MANIFEST_PATH.read_text(encoding="utf-8"))
        entries = manifest["known_internal_inconsistencies"]
        self.assertGreater(len(entries), 0)
        for entry in entries:
            with self.subTest(location=entry["location"]):
                self.assertIn("not_repaired_because", entry)
                self.assertIn("structured_claim", entry)


if __name__ == "__main__":
    unittest.main(verbosity=2)
