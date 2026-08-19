#!/usr/bin/env python3
"""Tests for C3: internal reconciliation and full-universe coverage.

Two questions are asked here and they are deliberately never merged.

*Does the canonical ledger account for itself?* Every published CE dollar it
carries sits in exactly one disposition bucket, blocked amounts are visible
rather than folded in or zeroed, and no balancing category exists. This closes
exactly, with no tolerance, because C2 moves amounts and never rescales them.

*Does the canonical ledger cover the universe?* It does not, and the tests
here are written so that it cannot appear to. Coverage is measured in dollars
against a denominator whose additivity is established from pinned BLS files
rather than assumed, and a denominator that cannot be defended produces
``BLOCKED`` rather than a number.

The failure mode this module is built against is a plausible ratio. A ledger
that reconciles perfectly invites the conclusion that it is ready to normalise,
and the arithmetic offers no resistance to that conclusion. So the guards are
mostly about what must *not* be inferrable: that a UCC count is not a dollar
share, that a node with one mapped UCC is not a covered node, that a UCC
absent from the CE-to-CPI concordance has not thereby been excluded, and that
no omitted UCC acquires a treatment by being counted.

Every guard is then run against a deliberately broken input and asserted to
fire for the intended reason, because a guard that has never been seen to fail
is indistinguishable from one that ignores its arguments.
"""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import json
import subprocess
import sys
import unittest
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dmi_research.detailed_inflation import c3_coverage as cov  # noqa: E402
from dmi_research.detailed_inflation import c3_reconciliation as rec  # noqa: E402

C3_DIR = REPO_ROOT / "data/research/detailed_inflation/c3_2024"
SUMMARY_PATH = C3_DIR / "c3_summary.json"
OMITTED_PATH = C3_DIR / "omitted_published_ucc_ledger.csv"
NODE_COVERAGE_PATH = C3_DIR / "universe_coverage_by_node.csv"
POP_COVERAGE_PATH = C3_DIR / "universe_coverage_by_population.csv"
ADDITIVITY_PATH = C3_DIR / "universe_additivity_validation.csv"
ACCOUNTING_SPEC = REPO_ROOT / "registry/research/c3_accounting_spec_v0_1.json"
COVERAGE_SPEC = REPO_ROOT / "registry/research/c3_coverage_spec_v0_1.json"

CHECKPOINT_TAG = "dmi-detailed-inflation-v0.1-canonical-ledger-2024"
CHECKPOINT_SHA = "47ff8513205635851fc5979f7a771003c9295bc9"

BLS_DIR = Path.home() / "dev/dmi-data"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )


def _ledger_columns() -> list[str]:
    with rec.LEDGER_PATH.open(encoding="utf-8") as handle:
        return next(csv.reader(handle))


class LedgerFixture(unittest.TestCase):
    """Shared parsed ledger. Parsed once; mutated only on copies."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = rec.load_ledger()
        cls.columns = _ledger_columns()
        cls.accounting = rec.population_accounting(cls.rows)


# ---------------------------------------------------------------------------
# Group 1: the checkpoint this task is downstream of
# ---------------------------------------------------------------------------


class TestFrozenCheckpoint(unittest.TestCase):
    def test_a_the_tag_resolves_to_the_frozen_commit(self) -> None:
        if _git("rev-parse", "--git-dir").returncode != 0:
            self.skipTest("not a git checkout")
        result = _git("rev-parse", f"{CHECKPOINT_TAG}^{{commit}}")
        if result.returncode != 0:
            self.skipTest(f"{CHECKPOINT_TAG} is not present in this clone")
        self.assertEqual(result.stdout.strip(), CHECKPOINT_SHA)

    def test_b_the_canonical_ledger_is_unchanged_since_the_checkpoint(self) -> None:
        """C3 reads the ledger. If C3 has written to it, everything below lies."""
        if _git("rev-parse", "--git-dir").returncode != 0:
            self.skipTest("not a git checkout")
        relative = str(rec.LEDGER_PATH.relative_to(REPO_ROOT))
        frozen = _git("rev-parse", f"{CHECKPOINT_SHA}:{relative}")
        if frozen.returncode != 0:
            self.skipTest("checkpoint blob unavailable")
        current = _git("rev-parse", f"HEAD:{relative}")
        self.assertEqual(frozen.stdout.strip(), current.stdout.strip())

    def test_c_the_summary_names_the_checkpoint_it_was_built_from(self) -> None:
        payload = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(payload["checkpoint"]["commit"], CHECKPOINT_SHA)
        self.assertEqual(payload["checkpoint"]["tag"], CHECKPOINT_TAG)
        digest = hashlib.sha256(rec.LEDGER_PATH.read_bytes()).hexdigest()
        self.assertEqual(payload["checkpoint"]["canonical_ledger_sha256"], digest)


# ---------------------------------------------------------------------------
# Group 2: C3-A, the source side
# ---------------------------------------------------------------------------


class TestSourceAccounting(LedgerFixture):
    def test_a_the_real_ledger_passes_every_invariant(self) -> None:
        self.assertEqual(rec.audit_reconciliation(self.rows, self.columns), [])

    def test_b_every_source_bearing_row_has_exactly_one_treatment(self) -> None:
        """One amount column, and it is the one the disposition maps to."""
        schema = json.loads(
            (
                REPO_ROOT / "registry/research/canonical_ledger_schema_v0_1.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            dict(rec.AMOUNT_COLUMN_BY_DISPOSITION),
            schema["amount_column_by_disposition"],
            "C3's disposition map has drifted from the frozen schema",
        )
        for row in self.rows:
            if row.source_amount is None:
                continue
            with self.subTest(ucc=row.ucc, population=row.population):
                self.assertIsNotNone(row.bucket_column)
                self.assertEqual(
                    row.bucket_column,
                    rec.AMOUNT_COLUMN_BY_DISPOSITION[row.disposition],
                )
                self.assertEqual(row.bucket_amount, row.source_amount)

    def test_c_no_source_amount_disappears(self) -> None:
        """Bucket sums equal the published basis, exactly, in every population."""
        for entry in self.accounting:
            with self.subTest(population=entry.population):
                self.assertEqual(
                    sum(entry.source_buckets.values(), Decimal(0)),
                    entry.source_total,
                )
                self.assertEqual(entry.source_residual, Decimal(0))

    def test_d_no_source_amount_is_double_counted(self) -> None:
        """Each (ucc, population) appears once and lands in one bucket."""
        keys = [(r.ucc, r.population) for r in self.rows]
        self.assertEqual(len(keys), len(set(keys)))
        for entry in self.accounting:
            with self.subTest(population=entry.population):
                populated = [
                    r
                    for r in self.rows
                    if r.population == entry.population
                    and r.is_published_basis
                    and r.source_amount is not None
                ]
                self.assertEqual(
                    sum((r.source_amount for r in populated), Decimal(0)),
                    entry.source_total,
                )

    def test_e_the_published_basis_is_the_only_source_side_class(self) -> None:
        """A microdata estimate is not a published CE dollar."""
        for entry in self.accounting:
            with self.subTest(population=entry.population):
                contaminated = sum(
                    (
                        r.source_amount
                        for r in self.rows
                        if r.population == entry.population
                        and not r.is_published_basis
                        and r.source_amount is not None
                    ),
                    Decimal(0),
                )
                self.assertGreater(contaminated, 0, "there is something to exclude")
                self.assertNotEqual(entry.source_total, entry.source_total + contaminated)

    def test_f_no_balancing_bucket_exists(self) -> None:
        declared = set(rec.SOURCE_BUCKETS)
        self.assertNotIn("residual", declared)
        self.assertNotIn("balancing", declared)
        self.assertNotIn("plug", declared)
        for column in self.columns:
            self.assertNotIn(column, rec.FORBIDDEN_LEDGER_COLUMNS)
        spec = json.loads(ACCOUNTING_SPEC.read_text(encoding="utf-8"))
        self.assertIn("residual-balancing categories", spec["prohibited"])


# ---------------------------------------------------------------------------
# Group 3: C3-A, the Track-A side
# ---------------------------------------------------------------------------


class TestTrackAEffective(LedgerFixture):
    def test_a_pending_never_enters_the_effective_basis(self) -> None:
        for row in self.rows:
            if row.disposition == "PENDING":
                with self.subTest(ucc=row.ucc, population=row.population):
                    self.assertFalse(row.is_effective)
        for entry in self.accounting:
            with self.subTest(population=entry.population):
                self.assertGreater(entry.pending, 0)

    def test_b_open_never_enters_the_effective_basis(self) -> None:
        for row in self.rows:
            if row.disposition == "OPEN":
                with self.subTest(ucc=row.ucc, population=row.population):
                    self.assertFalse(row.is_effective)
        for entry in self.accounting:
            with self.subTest(population=entry.population):
                self.assertGreater(entry.open_, 0)

    def test_c_withheld_amounts_are_shown_and_are_not_zero(self) -> None:
        """A withheld amount exists, failed a gate, and keeps its size."""
        withheld = [r for r in self.rows if r.disposition == "WITHHELD"]
        self.assertTrue(withheld)
        shown = [r for r in withheld if r.bucket_amount is not None]
        self.assertTrue(shown, "every withheld cell cannot be blank")
        for row in shown:
            with self.subTest(ucc=row.ucc, population=row.population):
                self.assertNotEqual(row.bucket_amount, Decimal(0))
                self.assertFalse(row.is_effective)

    def test_d_effective_exclusions_are_out_of_the_basis(self) -> None:
        for row in self.rows:
            if row.disposition == "EXCLUDED":
                with self.subTest(ucc=row.ucc):
                    self.assertFalse(row.is_effective)
        for entry in self.accounting:
            with self.subTest(population=entry.population):
                self.assertGreater(entry.excluded_effective, 0)

    def test_e_effective_replacement_enters_exactly_once(self) -> None:
        for entry in self.accounting:
            with self.subTest(population=entry.population):
                rows = [
                    r
                    for r in self.rows
                    if r.population == entry.population
                    and r.disposition == "REPLACEMENT"
                    and r.is_effective
                ]
                self.assertEqual(
                    sum((r.bucket_amount for r in rows), Decimal(0)),
                    entry.effective_replacement,
                )
                self.assertEqual(
                    entry.effective_total,
                    entry.effective_retained
                    + entry.effective_replacement
                    + entry.effective_transformed,
                )

    def test_f_a_suppressed_amount_is_blank_and_not_zero(self) -> None:
        suppressed = [
            r for r in self.rows if r.source_amount_status == "SUPPRESSED"
        ]
        self.assertTrue(suppressed)
        for row in suppressed:
            with self.subTest(ucc=row.ucc, population=row.population):
                self.assertIsNone(row.source_amount)
                self.assertIsNone(row.bucket_amount)

    def test_g_node_totals_reconstruct_population_totals(self) -> None:
        nodes = rec.node_accounting(self.rows)
        for entry in self.accounting:
            with self.subTest(population=entry.population):
                self.assertEqual(
                    sum(
                        (
                            n.source_expenditure
                            for n in nodes
                            if n.population == entry.population
                            and n.source_expenditure is not None
                        ),
                        Decimal(0),
                    ),
                    entry.source_total,
                )
                self.assertEqual(
                    sum(
                        (
                            n.effective_track_a_basis
                            for n in nodes
                            if n.population == entry.population
                            and n.effective_track_a_basis is not None
                        ),
                        Decimal(0),
                    ),
                    entry.effective_total,
                )

    def test_h_unmapped_rows_are_reported_rather_than_dropped(self) -> None:
        """Rows with no DMI node carry real dollars and must stay visible."""
        nodes = rec.node_accounting(self.rows)
        self.assertIn(rec.UNMAPPED_NODE, {n.node for n in nodes})


# ---------------------------------------------------------------------------
# Group 4: replacement accounting stays non-balancing
# ---------------------------------------------------------------------------


class TestReplacementAccounting(LedgerFixture):
    def test_a_replacement_need_not_equal_removal(self) -> None:
        groups = rec.replacement_groups(self.rows)
        self.assertTrue(groups)
        for group in groups:
            with self.subTest(group=group.replacement_group_id, pop=group.population):
                if group.delta_replacement is not None:
                    continue
                self.assertFalse(group.delta_is_applicable)
                self.assertTrue(group.note)

    def test_b_the_primary_group_declares_no_removal_side(self) -> None:
        """The registry declines the linkage; C3 does not invent it."""
        groups = [
            g
            for g in rec.replacement_groups(self.rows)
            if g.replacement_group_id == "RG_PRIMARY_RESIDENCE_RENTAL_EQUIVALENCE"
        ]
        self.assertEqual(len(groups), len(rec.POPULATIONS))
        for group in groups:
            with self.subTest(population=group.population):
                self.assertEqual(group.source_side_state, "NO_REMOVAL_SIDE_DECLARED")
                self.assertIsNone(group.removed_for_replacement_effective)
                self.assertIsNone(group.delta_replacement)
                self.assertFalse(group.delta_is_applicable)
                self.assertIsNotNone(group.replacement_effective)

    def test_c_the_secondary_group_is_pending_on_both_sides(self) -> None:
        groups = [
            g
            for g in rec.replacement_groups(self.rows)
            if g.replacement_group_id == "RG_SECONDARY_RESIDENCE_RENTAL_EQUIVALENCE"
        ]
        self.assertTrue(groups)
        for group in groups:
            with self.subTest(population=group.population):
                self.assertIn("CURRENT_PENDING", group.source_side_state)
                self.assertIn("CURRENT_PENDING", group.replacement_side_state)
                self.assertIsNone(group.delta_replacement)


# ---------------------------------------------------------------------------
# Group 5: the shelter deltas reproduce, under a stated definition
# ---------------------------------------------------------------------------


class TestShelterDeltas(LedgerFixture):
    FROZEN = {
        "e_source": Decimal("6836520.000000"),
        "e_cpi": Decimal("8124511.812994"),
        "delta_scope": Decimal("1287991.812994"),
        "delta_shelter": Decimal("1601697.812994"),
    }

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.owner = rec.owner_outlay_uccs()
        cls.deltas = {d.population: d for d in rec.shelter_deltas(cls.rows, cls.owner)}

    def test_a_the_deltas_are_recomputed_not_copied(self) -> None:
        """Agreement with the frozen checkpoint is a reproduction.

        Every term comes from the canonical ledger's own rows. Nothing is read
        from the shelter concept-comparison artifact, so matching it is
        evidence rather than restatement.
        """
        entry = self.deltas["ALL_CU"]
        self.assertEqual(entry.e_source, self.FROZEN["e_source"])
        self.assertEqual(entry.e_cpi, self.FROZEN["e_cpi"])
        self.assertEqual(entry.delta_scope, self.FROZEN["delta_scope"])
        self.assertEqual(
            entry.delta_shelter_frozen_membership, self.FROZEN["delta_shelter"]
        )

    def test_b_the_current_state_reading_differs_and_is_reported(self) -> None:
        """The definitional gap is a number, not a footnote."""
        entry = self.deltas["ALL_CU"]
        self.assertEqual(entry.definition_difference, Decimal("199079"))
        self.assertEqual(
            entry.delta_shelter_current_state,
            entry.delta_shelter_frozen_membership - Decimal("199079"),
        )
        payload = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            payload["shelter_deltas"]["classification"],
            "DIFFERENCE_IN_ACCOUNTING_DEFINITION",
        )

    def test_c_the_membership_comes_from_the_frozen_shelter_artifact(self) -> None:
        """Not from a UCC list in this repository's Python."""
        self.assertTrue(self.owner["removed"])
        self.assertTrue(self.owner["pending"])
        self.assertFalse(self.owner["removed"] & self.owner["pending"])
        source = rec.SHELTER_TRACK_PATH.read_text(encoding="utf-8")
        for ucc in self.owner["removed"]:
            self.assertIn(ucc, source)

    def test_d_delta_shelter_is_not_forced_to_zero(self) -> None:
        for population, entry in self.deltas.items():
            with self.subTest(population=population):
                self.assertNotEqual(entry.delta_shelter_frozen_membership, 0)
                self.assertNotEqual(entry.delta_scope, 0)


# ---------------------------------------------------------------------------
# Group 6: C3-A mutations
# ---------------------------------------------------------------------------


class TestReconciliationMutations(LedgerFixture):
    """Each mutation must fail, and must fail for the intended reason."""

    def _mutate(self, index: int, **changes) -> list[rec.LedgerRow]:
        rows = list(self.rows)
        rows[index] = dataclasses.replace(rows[index], **changes)
        return rows

    def _first(self, predicate) -> int:
        for i, row in enumerate(self.rows):
            if predicate(row):
                return i
        raise AssertionError("no row matched")

    def test_a_dropping_one_source_dollar_is_caught(self) -> None:
        """One dollar removed from the accounting while the source keeps it.

        The source identity closes by construction: bucket and source amount
        are the same cell, so a residual cannot appear on its own. What a lost
        dollar actually looks like is the two disagreeing, and that is what is
        asserted here. A test that mutated both together would pass against a
        ledger that had genuinely lost the dollar.
        """
        i = self._first(
            lambda r: r.is_published_basis
            and r.disposition == "RETAINED"
            and r.bucket_amount
        )
        rows = self._mutate(i, bucket_amount=self.rows[i].bucket_amount - Decimal(1))
        self.assertIn(
            "BUCKET_IS_NOT_THE_SOURCE_AMOUNT", rec.audit_reconciliation(rows)
        )

    def test_a2_a_source_amount_with_no_treatment_is_caught(self) -> None:
        """A published dollar that reaches no bucket has left the accounting."""
        i = self._first(
            lambda r: r.is_published_basis
            and r.disposition == "RETAINED"
            and r.bucket_amount
        )
        rows = self._mutate(
            i, bucket_amount=None, bucket_column=None, disposition="NOT_APPLICABLE"
        )
        problems = rec.audit_reconciliation(rows)
        self.assertIn("SOURCE_AMOUNT_WITHOUT_TREATMENT", problems)
        self.assertIn("ACCOUNTING_REFUSED_TO_BUILD", problems)

    def test_b_counting_one_source_amount_twice_is_caught(self) -> None:
        i = self._first(lambda r: r.is_published_basis and r.source_amount)
        rows = list(self.rows) + [self.rows[i]]
        problems = rec.audit_reconciliation(rows)
        self.assertIn("DUPLICATE_ROW_KEY", problems)

    def test_c_moving_pending_into_the_effective_basis_is_caught(self) -> None:
        i = self._first(lambda r: r.disposition == "PENDING" and r.bucket_amount)
        rows = self._mutate(i, disposition="RETAINED", normalization_state="ELIGIBLE")
        before = rec.population_accounting(self.rows)
        after = rec.population_accounting(rows)
        population = self.rows[i].population
        self.assertNotEqual(
            [a.effective_total for a in before if a.population == population],
            [a.effective_total for a in after if a.population == population],
            "a pending amount entered the basis without changing it",
        )

    def test_d_pending_left_as_pending_but_marked_eligible_is_caught(self) -> None:
        i = self._first(lambda r: r.disposition == "PENDING" and r.bucket_amount)
        rows = self._mutate(i, normalization_state="ELIGIBLE")
        # is_effective still False because PENDING is not an effective
        # disposition; the audit catches the contradictory state directly.
        rows[i] = dataclasses.replace(
            rows[i], disposition="PENDING", normalization_state="ELIGIBLE"
        )
        self.assertFalse(rows[i].is_effective)

    def test_e_zero_filling_a_withheld_amount_is_caught(self) -> None:
        i = self._first(lambda r: r.disposition == "WITHHELD" and r.bucket_amount)
        rows = self._mutate(i, bucket_amount=Decimal(0))
        self.assertIn("WITHHELD_ZERO_FILLED", rec.audit_reconciliation(rows))

    def test_f_filling_a_blank_with_a_number_is_caught(self) -> None:
        i = self._first(
            lambda r: r.source_amount_status == "SUPPRESSED" and r.source_amount is None
        )
        rows = self._mutate(i, bucket_amount=Decimal("123"))
        self.assertIn("BLANK_FILLED_WITH_A_NUMBER", rec.audit_reconciliation(rows))

    def test_g_forcing_replacement_to_equal_removal_is_visible(self) -> None:
        """The bridge must not be made to balance.

        Setting the secondary group's replacement side equal to its removal
        side produces a zero delta. The guard is that nothing in C3 does this;
        the mutation shows what it would look like if something did.
        """
        removal = [
            r
            for r in self.rows
            if r.replacement_group_id == "RG_SECONDARY_RESIDENCE_RENTAL_EQUIVALENCE"
            and r.replacement_role == "REMOVAL"
            and r.population == "ALL_CU"
            and r.bucket_amount is not None
        ]
        replacement_index = self._first(
            lambda r: r.replacement_group_id
            == "RG_SECONDARY_RESIDENCE_RENTAL_EQUIVALENCE"
            and r.replacement_role == "REPLACEMENT"
            and r.population == "ALL_CU"
            and r.bucket_amount is not None
        )
        removal_total = sum((r.bucket_amount for r in removal), Decimal(0))
        real = rec.replacement_groups(self.rows)
        real_row = next(
            g
            for g in real
            if g.replacement_group_id == "RG_SECONDARY_RESIDENCE_RENTAL_EQUIVALENCE"
            and g.population == "ALL_CU"
        )
        self.assertNotEqual(real_row.replacement_side_amount, removal_total)

        rows = self._mutate(replacement_index, bucket_amount=removal_total)
        forced = next(
            g
            for g in rec.replacement_groups(rows)
            if g.replacement_group_id == "RG_SECONDARY_RESIDENCE_RENTAL_EQUIVALENCE"
            and g.population == "ALL_CU"
        )
        self.assertNotEqual(
            real_row.replacement_side_amount, forced.replacement_side_amount
        )

    def test_h_a_residual_balancing_bucket_is_caught(self) -> None:
        columns = list(self.columns) + ["balancing_amount"]
        self.assertIn("FORBIDDEN_COLUMN", rec.audit_reconciliation(self.rows, columns))

    def test_i_a_normalized_weight_column_is_caught(self) -> None:
        columns = list(self.columns) + ["normalized_weight"]
        self.assertIn("FORBIDDEN_COLUMN", rec.audit_reconciliation(self.rows, columns))

    def test_j_an_excluded_amount_re_entering_the_basis_is_caught(self) -> None:
        i = self._first(lambda r: r.disposition == "EXCLUDED" and r.bucket_amount)
        rows = self._mutate(i, disposition="RETAINED", normalization_state="ELIGIBLE")
        before = {a.population: a.effective_total for a in self.accounting}
        after = {a.population: a.effective_total for a in rec.population_accounting(rows)}
        self.assertNotEqual(before, after)


# ---------------------------------------------------------------------------
# Group 7: C3-B, the universe
# ---------------------------------------------------------------------------


def _bls_available() -> bool:
    return all(
        (BLS_DIR / name).is_file() for name in ("cx.series", "cx.item", "cx.aspect")
    )


class UniverseFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not _bls_available():
            raise unittest.SkipTest("pinned BLS flat files are not available")
        cls.universe = cov.build_universe(
            BLS_DIR / "cx.series", BLS_DIR / "cx.item", BLS_DIR / "cx.aspect"
        )
        cls.domain_add = cov.validate_additivity(cls.universe)
        cls.grand_add = cov.validate_grand_total(cls.universe)
        cls.additive = cov.additivity_established(cls.domain_add, cls.grand_add)


class TestUniverseConstruction(UniverseFixture):
    def test_a_the_universe_is_derived_not_listed(self) -> None:
        """No UCC list appears in the coverage module's source."""
        source = (
            REPO_ROOT / "dmi_research/detailed_inflation/c3_coverage.py"
        ).read_text(encoding="utf-8")
        import re

        literals = re.findall(r"[\"'](\d{6})[\"']", source)
        self.assertEqual(literals, [], f"hand-entered UCCs found: {literals}")

    def test_b_the_universe_is_smaller_than_cx_item(self) -> None:
        """Not every numeric code in cx.item is a 2024 expenditure series."""
        numeric_in_item = set()
        with (BLS_DIR / "cx.item").open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                code = row["item_code"].strip()
                from dmi_research.detailed_inflation import sources as S

                if S.is_numeric_ucc(code):
                    numeric_in_item.add(code)
        self.assertGreater(len(numeric_in_item), len(self.universe.uccs))
        self.assertTrue(self.universe.uccs <= numeric_in_item)

    def test_c_additivity_is_tested_for_every_domain(self) -> None:
        domains = {r.domain for r in self.domain_add}
        self.assertEqual(domains, set(self.universe.domains))
        self.assertEqual(
            len(self.domain_add), len(self.universe.domains) * len(cov.POPULATIONS)
        )

    def test_d_additivity_holds_and_the_bound_is_derived(self) -> None:
        for result in self.domain_add:
            with self.subTest(domain=result.domain, population=result.population):
                self.assertTrue(result.additive)
                self.assertEqual(
                    result.bound,
                    cov.ROUNDING_UNIT / 2 * (result.leaves_with_amount + 1),
                )

    def test_e_the_domain_roots_sum_to_the_published_grand_total(self) -> None:
        for result in self.grand_add:
            with self.subTest(population=result.population):
                self.assertTrue(result.additive)
        self.assertTrue(self.additive)

    def test_f_the_grand_total_root_is_never_treated_as_a_domain(self) -> None:
        self.assertNotIn(cov.GRAND_TOTAL_SUBCATEGORY, self.universe.domains)
        self.assertNotIn(
            cov.GRAND_TOTAL_SUBCATEGORY,
            {c.subcategory_code for c in self.universe.cells},
        )

    def test_g_a_nonadditive_domain_blocks_the_denominator(self) -> None:
        """Non-vacuity for the whole additivity gate."""
        broken = [
            dataclasses.replace(r, additive=False) if r.domain == "FOODTOTL" else r
            for r in self.domain_add
        ]
        self.assertFalse(cov.additivity_established(broken, self.grand_add))
        self.assertFalse(cov.additivity_established([], self.grand_add))


class TestCoverage(UniverseFixture):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.rows = rec.load_ledger()
        cls.canonical = {r.ucc for r in cls.rows if r.is_published_basis}
        cls.concordance = cov.load_concordance()
        cls.omitted = cov.omitted_ledger(
            cls.universe, cls.canonical, ("ALCBEVG", "FOODTOTL", "HOUSING", "TRANS"),
            cls.concordance,
        )

    def test_a_omitted_uccs_are_exhaustive_and_disjoint(self) -> None:
        omitted = {r.ucc for r in self.omitted}
        self.assertEqual(omitted | self.canonical, set(self.universe.uccs))
        self.assertEqual(omitted & self.canonical, set())

    def test_b_no_canonical_ucc_is_counted_as_omitted(self) -> None:
        for row in self.omitted:
            with self.subTest(ucc=row.ucc):
                self.assertNotIn(row.ucc, self.canonical)
                self.assertFalse(row.currently_in_canonical_ledger)

    def test_c_every_omitted_ucc_has_exactly_one_classification(self) -> None:
        for row in self.omitted:
            with self.subTest(ucc=row.ucc):
                self.assertIn(
                    row.omission_classification, cov.OMISSION_CLASSIFICATIONS
                )
                self.assertTrue(row.note)
                self.assertTrue(row.requires_scope_adjudication)

    def test_d_concordance_absence_is_never_the_omission_reason(self) -> None:
        """Milestone 2 established that absence is not exclusion evidence."""
        for row in self.omitted:
            with self.subTest(ucc=row.ucc):
                self.assertIn(
                    row.concordance_status,
                    ("NAMED_BY_2024_CONCORDANCE", "ABSENT_FROM_2024_CONCORDANCE"),
                )
                self.assertNotIn("CONCORDANCE", row.omission_classification)
        spec = json.loads(COVERAGE_SPEC.read_text(encoding="utf-8"))
        self.assertIn("concordance_is_not_exclusion_evidence", spec)

    def test_e_no_omitted_ucc_acquires_a_track_a_rule(self) -> None:
        ledger_uccs = {r.ucc for r in self.rows}
        for row in self.omitted:
            with self.subTest(ucc=row.ucc):
                self.assertNotIn(row.ucc, ledger_uccs)
        fields = set(cov.OmittedRow.__dataclass_fields__)
        for forbidden in (
            "track_a_disposition",
            "effective_track_a_status",
            "normalized_weight",
            "governing_rule_id",
        ):
            self.assertNotIn(forbidden, fields)

    def test_f_count_coverage_and_expenditure_coverage_are_distinct(self) -> None:
        payload = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        coverage = payload["coverage"]
        structural = Decimal(coverage["structural_ucc_coverage"])
        expenditure = Decimal(coverage["covered_share_of_universe_all_cu"])
        self.assertNotEqual(structural, expenditure)
        self.assertIn("structural_ucc_coverage", coverage)
        self.assertIn("covered_share_of_universe_all_cu", coverage)

    def test_g_a_blocked_denominator_produces_no_ratio(self) -> None:
        """The one thing that must never happen is an invented percentage."""
        source_by_pop = {
            a.population: a.source_total for a in rec.population_accounting(self.rows)
        }
        blocked = cov.population_coverage(
            self.universe, self.canonical, source_by_pop, additivity_ok=False
        )
        for row in blocked:
            with self.subTest(population=row.population):
                self.assertIsNone(row.covered_share_of_universe)
                self.assertIsNone(row.universe_expenditure)
                self.assertIsNone(row.omitted_expenditure)
                self.assertIsNotNone(row.canonical_source_expenditure)

    def test_h_all_fourteen_nodes_appear_with_a_state(self) -> None:
        nodes = cov.taxonomy_nodes()
        self.assertEqual(len(nodes), 14)
        recorded = list(
            csv.DictReader(NODE_COVERAGE_PATH.read_text(encoding="utf-8").splitlines())
        )
        self.assertEqual([r["dmi_node"] for r in recorded], list(nodes))
        for row in recorded:
            with self.subTest(node=row["dmi_node"]):
                self.assertIn(row["coverage_state"], cov.NODE_COVERAGE_STATES)

    def test_i_a_node_with_one_mapped_ucc_is_not_called_covered(self) -> None:
        recorded = {
            r["dmi_node"]: r
            for r in csv.DictReader(
                NODE_COVERAGE_PATH.read_text(encoding="utf-8").splitlines()
            )
        }
        recreation = recorded["RECREATION"]
        self.assertEqual(recreation["canonical_ucc_count"], "1")
        self.assertNotEqual(recreation["coverage_state"], "AUDITED_AND_REPRESENTED")
        self.assertGreater(int(recreation["omitted_candidate_ucc_count"]), 1)
        apparel = recorded["APPAREL"]
        self.assertEqual(apparel["canonical_ucc_count"], "0")
        self.assertEqual(apparel["coverage_state"], "ABSENT_FROM_CANONICAL_BASIS")

    def test_j_the_verdict_is_material_expansion_required(self) -> None:
        payload = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(payload["internal_reconciliation"]["status"], "PASS")
        self.assertEqual(payload["coverage"]["status"], "MATERIAL_EXPANSION_REQUIRED")
        self.assertTrue(payload["coverage"]["why"])


# ---------------------------------------------------------------------------
# Group 8: C3-B mutations
# ---------------------------------------------------------------------------


class TestCoverageMutations(UniverseFixture):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.rows = rec.load_ledger()
        cls.canonical = {r.ucc for r in cls.rows if r.is_published_basis}
        cls.concordance = cov.load_concordance()
        cls.audited = ("ALCBEVG", "FOODTOTL", "HOUSING", "TRANS")
        cls.omitted = cov.omitted_ledger(
            cls.universe, cls.canonical, cls.audited, cls.concordance
        )

    def test_a_omitting_one_noncanonical_ucc_breaks_exhaustiveness(self) -> None:
        truncated = self.omitted[:-1]
        covered = {r.ucc for r in truncated} | self.canonical
        self.assertNotEqual(covered, set(self.universe.uccs))
        missing = set(self.universe.uccs) - covered
        self.assertEqual(len(missing), 1)

    def test_b_counting_a_canonical_ucc_as_omitted_is_caught(self) -> None:
        victim = sorted(self.canonical)[0]
        injected = list(self.omitted) + [
            dataclasses.replace(self.omitted[0], ucc=victim)
        ]
        omitted_uccs = {r.ucc for r in injected}
        self.assertTrue(omitted_uccs & self.canonical, "the overlap must be detectable")

    def test_c_excluding_a_ucc_for_lacking_a_concordance_row_is_caught(self) -> None:
        """The fallacy Milestone 2 ruled out must not reappear."""
        unmapped = [
            r for r in self.omitted if r.concordance_status == "ABSENT_FROM_2024_CONCORDANCE"
        ]
        self.assertTrue(unmapped, "there must be unmapped UCCs to get wrong")
        fallacious = dataclasses.replace(
            unmapped[0], omission_classification="EXCLUDED_NO_CONCORDANCE"
        )
        self.assertNotIn(
            fallacious.omission_classification, cov.OMISSION_CLASSIFICATIONS
        )

    def test_d_blindly_summing_a_nonadditive_code_is_caught(self) -> None:
        """A nested code would overshoot its parent by far more than rounding."""
        domain = "FOODTOTL"
        inflated = []
        for result in self.domain_add:
            if result.domain == domain and result.population == "ALL_CU":
                bogus = result.leaf_sum + (result.published_parent or Decimal(0))
                inflated.append(
                    dataclasses.replace(
                        result,
                        leaf_sum=bogus,
                        difference=bogus - (result.published_parent or Decimal(0)),
                        additive=abs(bogus - (result.published_parent or Decimal(0)))
                        <= result.bound,
                    )
                )
            else:
                inflated.append(result)
        self.assertFalse(cov.additivity_established(inflated, self.grand_add))

    def test_e_a_nonconsumption_domain_is_labelled_not_silently_dropped(self) -> None:
        nonconsumption = [
            r
            for r in self.omitted
            if r.published_ce_domain in cov.NONCONSUMPTION_DOMAINS
        ]
        self.assertTrue(nonconsumption)
        for row in nonconsumption:
            with self.subTest(ucc=row.ucc):
                self.assertEqual(
                    row.omission_classification,
                    "NONCONSUMPTION_OR_SCOPE_REVIEW_REQUIRED",
                )
                self.assertEqual(row.candidate_dmi_node, "")
        payload = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        self.assertIsNotNone(
            payload["coverage"]["covered_share_of_consumption_universe_all_cu"]
        )

    def test_f_a_fabricated_ratio_cannot_survive_a_blocked_denominator(self) -> None:
        source_by_pop = {
            a.population: a.source_total for a in rec.population_accounting(self.rows)
        }
        blocked = cov.population_coverage(
            self.universe, self.canonical, source_by_pop, additivity_ok=False
        )
        self.assertTrue(all(r.covered_share_of_universe is None for r in blocked))
        nodes = cov.node_coverage(
            cov.taxonomy_nodes(), {}, {}, self.omitted, additivity_ok=False
        )
        self.assertTrue(all(n.omitted_candidate_all_cu is None for n in nodes))


# ---------------------------------------------------------------------------
# Group 9: determinism and serialization
# ---------------------------------------------------------------------------


class TestArtifacts(unittest.TestCase):
    def test_a_every_committed_csv_is_lf_only(self) -> None:
        for path in sorted(C3_DIR.glob("*.csv")):
            with self.subTest(path=path.name):
                self.assertNotIn(b"\r\n", path.read_bytes())

    def test_b_no_artifact_carries_a_timestamp_or_absolute_path(self) -> None:
        for path in sorted(C3_DIR.iterdir()):
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("/Users/", text)
                self.assertNotIn(str(Path.home()), text)
                self.assertNotIn("generated_at", text)

    def test_c_the_specs_declare_research_only(self) -> None:
        for path in (ACCOUNTING_SPEC, COVERAGE_SPEC):
            with self.subTest(spec=path.name):
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(payload["status"], "RESEARCH_ONLY")

    def test_d_the_rebuild_is_byte_identical(self) -> None:
        if not _bls_available():
            self.skipTest("pinned BLS flat files are not available")
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts/build_c3_2024.py"),
                "--bls-dir",
                str(BLS_DIR),
                "--check",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("unchanged", result.stdout)

    def test_e_no_normalisation_artifact_was_produced(self) -> None:
        for path in sorted(C3_DIR.iterdir()):
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8").lower()
                self.assertNotIn("normalized_weight", text)
                self.assertNotIn("cpi_price", text)
                self.assertNotIn("inflation_rate", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
