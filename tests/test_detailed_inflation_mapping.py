#!/usr/bin/env python3
"""Mapping-classification tests for the Detailed Inflation Substrate, M1.

Covers prompt section 15 "Mapping" and "Known regression cases":
direct mapping; multi-ELI same-node mapping; no-concordance mapping;
cross-node multi-map detection; unknown ELI/node mapping fails visibly; and
the five named regression UCCs plus the 470311 exception-ledger assertion.

The regression cases run against the committed, pinned concordance and the
committed taxonomy, so they require no external BLS files.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.detailed_inflation_fixtures import write_concordance

from dmi_research.detailed_inflation.basis import BasisEntry
from dmi_research.detailed_inflation.concordance import (
    ConcordanceError,
    load_concordance,
)
from dmi_research.detailed_inflation.mapping import (
    ExceptionReason,
    build_exception_ledger,
    build_mappings,
    classify_ucc,
    summarize_status,
)
from dmi_research.detailed_inflation.taxonomy import (
    MILESTONE_1_AUTOMATIC_STATUSES,
    MappingStatus,
    UnknownEliError,
    load_eli_resolver,
    load_taxonomy,
)

#: The five UCCs prompt section 10 names as expected MULTI_SAME_NODE cases.
REGRESSION_MULTI_SAME_NODE = {
    "270102": "EDUCATION_COMMUNICATION",
    "470111": "MOTOR_FUEL",
    "470113": "MOTOR_FUEL",
    "480100": "TRANSPORT_COMMODITIES_EX_MOTOR_FUEL",
    "490100": "TRANSPORT_SERVICES",
}

#: Prompt section 11 names this UCC as an expected exception-ledger case.
LEDGER_REGRESSION_UCC = "470311"


def basis_entry(
    ucc: str,
    *,
    population: str = "All Consumer Units",
    characteristics_code: str = "01",
    aggregate: float | None = 100.0,
    rse: float | None = 5.0,
    subcategory_code: str = "TRANS",
    domain_label: str = "Transportation",
    item_text: str = "",
) -> BasisEntry:
    """A minimal basis entry. Mapping depends only on the UCC identifier."""
    return BasisEntry(
        ucc=ucc,
        subcategory_code=subcategory_code,
        domain_label=domain_label,
        population=population,
        characteristics_code=characteristics_code,
        series_id=f"CXU{ucc}LB{characteristics_code}01M",
        series_title=item_text or ucc,
        item_text=item_text or ucc,
        display_level=2,
        selectable=True,
        aggregate_expenditure=aggregate,
        mean_expenditure=None,
        rse=rse,
    )


class ResolverTestCase(unittest.TestCase):
    """Binds the committed taxonomy and ELI map."""

    def setUp(self):
        self.nodes = load_taxonomy()
        self.resolver = load_eli_resolver(self.nodes)


class SyntheticConcordanceTestCase(ResolverTestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.concordance = load_concordance(
            write_concordance(
                Path(self._tmp.name),
                [
                    # one destination, one node
                    ("010119", "FA011", "Flour", "Flour"),
                    # several destinations, all the same node
                    ("470111", "TB011", "Gasoline", "Gasoline, unleaded regular"),
                    ("470111", "TB021", "Gasoline", "Gasoline, unleaded premium"),
                    # several destinations spanning two nodes
                    ("999998", "FA011", "Hybrid item", "Flour"),
                    ("999998", "TB011", "Hybrid item", "Gasoline"),
                    # a destination whose prefix the resolver does not know
                    ("999997", "ZZ001", "Unknown item", "Unknown"),
                ],
            )
        )


class TestDirectMapping(SyntheticConcordanceTestCase):
    def test_single_destination_single_node_is_direct(self):
        status, node, nodes, reason = classify_ucc(
            "010119", self.concordance, self.resolver
        )
        self.assertIs(status, MappingStatus.DIRECT)
        self.assertEqual(node, "FOOD")
        self.assertEqual(nodes, ("FOOD",))
        self.assertIsNone(reason)

    def test_direct_mapping_is_not_an_exception(self):
        ledger = build_exception_ledger(
            build_mappings(
                [basis_entry("010119")], self.concordance, self.resolver
            ),
            [basis_entry("010119")],
        )
        self.assertEqual(ledger, [])


class TestMultiSameNodeMapping(SyntheticConcordanceTestCase):
    def test_several_elis_collapsing_to_one_node_is_multi_same_node(self):
        status, node, nodes, reason = classify_ucc(
            "470111", self.concordance, self.resolver
        )
        self.assertIs(status, MappingStatus.MULTI_SAME_NODE)
        self.assertEqual(node, "MOTOR_FUEL")
        self.assertEqual(nodes, ("MOTOR_FUEL",))
        self.assertIsNone(reason)

    def test_multi_same_node_is_resolved_and_not_an_exception(self):
        mappings = build_mappings(
            [basis_entry("470111")], self.concordance, self.resolver
        )
        self.assertEqual(build_exception_ledger(mappings, [basis_entry("470111")]), [])
        self.assertEqual(mappings[0].destination_count, 2)

    def test_expenditure_is_not_split_across_destinations(self):
        """One node receives the whole amount; nothing is renormalized."""
        entries = [basis_entry("470111", aggregate=500.0)]
        mappings = build_mappings(entries, self.concordance, self.resolver)
        summaries = summarize_status(entries, mappings)
        multi = next(
            s for s in summaries if s.status is MappingStatus.MULTI_SAME_NODE
        )
        self.assertEqual(multi.aggregate_expenditure, 500.0)
        self.assertEqual(multi.ucc_count, 1)


class TestNoConcordanceMapping(SyntheticConcordanceTestCase):
    def test_absent_ucc_is_unresolved_with_no_concordance_reason(self):
        status, node, nodes, reason = classify_ucc(
            "123456", self.concordance, self.resolver
        )
        self.assertIs(status, MappingStatus.UNRESOLVED)
        self.assertIsNone(node)
        self.assertEqual(nodes, ())
        self.assertIs(reason, ExceptionReason.NO_CONCORDANCE)

    def test_no_concordance_is_not_treated_as_out_of_scope(self):
        entries = [basis_entry("123456")]
        mappings = build_mappings(entries, self.concordance, self.resolver)
        self.assertIsNot(mappings[0].status, MappingStatus.OUT_OF_SCOPE)
        self.assertIsNot(mappings[0].status, MappingStatus.TRANSFORMED)

    def test_no_concordance_enters_the_exception_ledger_with_its_expenditure(self):
        entries = [basis_entry("123456", aggregate=4321.0)]
        mappings = build_mappings(entries, self.concordance, self.resolver)
        ledger = build_exception_ledger(mappings, entries)
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0].ucc, "123456")
        self.assertIs(ledger[0].reason, ExceptionReason.NO_CONCORDANCE)
        self.assertEqual(ledger[0].all_cu_aggregate_expenditure, 4321.0)


class TestCrossNodeDetection(SyntheticConcordanceTestCase):
    def test_destinations_spanning_nodes_are_unresolved(self):
        status, node, nodes, reason = classify_ucc(
            "999998", self.concordance, self.resolver
        )
        self.assertIs(status, MappingStatus.UNRESOLVED)
        self.assertIsNone(node)
        self.assertEqual(set(nodes), {"FOOD", "MOTOR_FUEL"})
        self.assertIs(reason, ExceptionReason.CROSS_NODE_MULTI_MAP)

    def test_cross_node_case_is_never_silently_assigned_to_one_node(self):
        entries = [basis_entry("999998")]
        mappings = build_mappings(entries, self.concordance, self.resolver)
        self.assertIsNone(mappings[0].node)

    def test_cross_node_case_records_both_destination_nodes_in_the_ledger(self):
        entries = [basis_entry("999998")]
        ledger = build_exception_ledger(
            build_mappings(entries, self.concordance, self.resolver), entries
        )
        self.assertEqual(len(ledger), 1)
        self.assertIs(ledger[0].reason, ExceptionReason.CROSS_NODE_MULTI_MAP)
        self.assertEqual(set(ledger[0].nodes), {"FOOD", "MOTOR_FUEL"})


class TestUnknownEliFailsVisibly(SyntheticConcordanceTestCase):
    def test_unmapped_eli_prefix_raises_rather_than_dropping_expenditure(self):
        with self.assertRaises(UnknownEliError) as caught:
            classify_ucc("999997", self.concordance, self.resolver)
        self.assertIn("ZZ", str(caught.exception))

    def test_build_mappings_propagates_the_failure(self):
        with self.assertRaises(UnknownEliError):
            build_mappings(
                [basis_entry("999997")], self.concordance, self.resolver
            )

    def test_malformed_eli_raises(self):
        for malformed in ("TB01", "tb011", "T1011", "", "TB0111"):
            with self.assertRaises(UnknownEliError, msg=malformed):
                self.resolver.resolve(malformed)

    def test_resolver_has_no_default_node(self):
        self.assertNotIn("ZZ", self.resolver.known_prefixes)


class TestConcordanceIntegrity(ResolverTestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_duplicate_destination_raises(self):
        path = write_concordance(
            Path(self._tmp.name),
            [
                ("010119", "FA011", "Flour", "Flour"),
                ("010119", "FA011", "Flour", "Flour"),
            ],
        )
        with self.assertRaises(ConcordanceError):
            load_concordance(path)

    def test_malformed_ucc_raises(self):
        path = write_concordance(
            Path(self._tmp.name), [("10119", "FA011", "Flour", "Flour")]
        )
        with self.assertRaises(ConcordanceError):
            load_concordance(path)

    def test_missing_concordance_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_concordance(Path(self._tmp.name) / "absent.tsv")


class TestPinnedConcordanceRegressions(ResolverTestCase):
    """Section 15 known regression cases, against the committed concordance."""

    def setUp(self):
        super().setUp()
        self.concordance = load_concordance()

    def test_the_five_named_uccs_classify_as_multi_same_node(self):
        for ucc, expected_node in REGRESSION_MULTI_SAME_NODE.items():
            with self.subTest(ucc=ucc):
                status, node, nodes, reason = classify_ucc(
                    ucc, self.concordance, self.resolver
                )
                self.assertIs(status, MappingStatus.MULTI_SAME_NODE)
                self.assertEqual(node, expected_node)
                self.assertEqual(nodes, (expected_node,))
                self.assertIsNone(reason)

    def test_each_named_ucc_really_has_several_destinations(self):
        for ucc in REGRESSION_MULTI_SAME_NODE:
            with self.subTest(ucc=ucc):
                self.assertGreater(len(self.concordance.destinations(ucc)), 1)

    def test_490100_relies_on_the_transport_service_eli_overrides(self):
        """490100 spans TD ELIs; the TA overrides keep leasing/rental separate.

        This guards the one ELI prefix that is not node-homogeneous.
        """
        self.assertEqual(self.resolver.resolve("TA031"), "TRANSPORT_SERVICES")
        self.assertEqual(self.resolver.resolve("TA041"), "TRANSPORT_SERVICES")
        self.assertEqual(
            self.resolver.resolve("TA011"),
            "TRANSPORT_COMMODITIES_EX_MOTOR_FUEL",
        )

    def test_470311_is_absent_from_the_pinned_concordance(self):
        self.assertIsNone(self.concordance.get(LEDGER_REGRESSION_UCC))

    def test_470311_appears_in_the_exception_ledger(self):
        entries = [basis_entry(LEDGER_REGRESSION_UCC, aggregate=1234.0)]
        ledger = build_exception_ledger(
            build_mappings(entries, self.concordance, self.resolver), entries
        )
        self.assertEqual([e.ucc for e in ledger], [LEDGER_REGRESSION_UCC])
        self.assertIs(ledger[0].reason, ExceptionReason.NO_CONCORDANCE)
        self.assertIs(ledger[0].preliminary_status, MappingStatus.UNRESOLVED)

    def test_every_eli_in_the_pinned_concordance_resolves(self):
        """No silent exclusion: the whole pinned ELI universe is mapped."""
        for eli in sorted(self.concordance.distinct_elis):
            with self.subTest(eli=eli):
                self.assertIn(self.resolver.resolve(eli), self.nodes)

    def test_milestone_1_never_assigns_transformed_or_out_of_scope(self):
        entries = [
            basis_entry(ucc) for ucc in list(REGRESSION_MULTI_SAME_NODE) + ["470311"]
        ]
        for mapping in build_mappings(entries, self.concordance, self.resolver):
            self.assertIn(mapping.status, MILESTONE_1_AUTOMATIC_STATUSES)


if __name__ == "__main__":
    unittest.main()
