#!/usr/bin/env python3
"""Detailed Inflation Substrate v0.1, Milestone 2 -- scope resolution tests.

Covers spec sections 5 (governing constraints), 7 (Track B), 13 (scope-rule
registry), 15 (ELI->node semantic validation), 16 (suppression policy),
18 (resolution output) and 19 (reconciliation).

The registry and semantic tests run anywhere, because their inputs are pinned
in this repository. The resolution tests need the authoritative BLS Consumer
Expenditure extracts and are skipped when those are absent.

Attribution: source data are published by the U.S. Bureau of Labor Statistics.
"""

from __future__ import annotations

import ast
import csv
import json
import tempfile
import unittest
from pathlib import Path

from tests.detailed_inflation_fixtures import (
    EXTERNAL_SOURCES,
    external_sources_available,
    write_concordance,
)

from dmi_research.detailed_inflation.audit import ResearchFirewallError, run_audit
from dmi_research.detailed_inflation.basis import Basis, ReconciliationResult
from dmi_research.detailed_inflation.concordance import (
    DEFAULT_CONCORDANCE_PATH,
    load_concordance,
)
from dmi_research.detailed_inflation.provenance import (
    PROVENANCE_CSV_COLUMNS,
    CpiAdjustmentStatus,
    PublicationReason,
    PumdMembership,
    UccProvenanceClass,
    UccProvenanceError,
    build_ucc_provenance,
    classify_ucc_provenance,
    concordance_only_evidence,
    load_provenance_classes,
    verify_against_registry,
)
from dmi_research.detailed_inflation.resolution import (
    ALL_CU,
    POPULATIONS,
    RECONCILIATION_BUCKETS,
    RESOLUTION_CSV_COLUMNS,
    ResolutionError,
    ResolutionState,
    TrackADisposition,
    build_resolution,
    build_suppression_bounds,
    track_a_disposition,
    write_artifacts,
)
from dmi_research.detailed_inflation.scope_rules import (
    SCOPE_RULES_PATH,
    EvidenceStrength,
    ReviewStatus,
    RuleType,
    ScopeRuleError,
    SuppressionStatus,
    TrackBTreatment,
    UnknownUccError,
    load_scope_rules,
)
from dmi_research.detailed_inflation.semantics import (
    NODE_TO_BLS_MAJOR_GROUPS,
    ReviewResult,
    build_semantic_validation,
    load_eli_descriptions,
)
from dmi_research.detailed_inflation.sources import load_items
from dmi_research.detailed_inflation.taxonomy import (
    MappingStatus,
    load_eli_resolver,
    load_taxonomy,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFINITION_NODES = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _unresolved_citation(reference):
    """Return why ``reference`` does not name a real test, or None if it does.

    The registry cites its evidence as ``path/to/module.py::Class::method``.
    Checking only that the module exists is not enough: a citation naming a
    class or method that was never written reads exactly like a verified one,
    which is the failure this whole check exists to prevent. So the target is
    resolved by parsing the module rather than by trusting the string.
    """
    module, _, qualname = str(reference).partition("::")
    if not qualname:
        return "no test named within the module"
    path = REPO_ROOT / module
    if not path.is_file():
        return f"module {module} does not exist"

    tree = ast.parse(path.read_text(encoding="utf-8"))
    scope = tree.body
    for part in qualname.split("::"):
        for node in scope:
            if isinstance(node, DEFINITION_NODES) and node.name == part:
                scope = node.body
                break
        else:
            defined = sorted(
                node.name for node in scope if isinstance(node, DEFINITION_NODES)
            )
            return f"{part} is not defined there (found {defined})"
    return None


def _resolve_registry_citation(reference):
    """Return the record a ``file.json :: dotted.path`` citation names, or None.

    Provenance evidence cites another pinned registry rather than a test, so the
    citation is resolved by walking the JSON. A pointer that merely looks
    plausible reads exactly like a checked one, which is the whole risk of
    grading a claim VERIFIED on the strength of a reference.
    """
    module, _, dotted = (part.strip() for part in reference.partition("::"))
    path = REPO_ROOT / module
    if not dotted or not path.is_file():
        return None
    node = json.loads(path.read_text(encoding="utf-8"))
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


#: Milestone 1 found 58 exception UCCs carrying this much All-CU expenditure
#: out of a 6,836,520 ($M) basis. Milestone 2 must resolve exactly these.
EXPECTED_EXCEPTION_COUNT = 58
EXPECTED_EXCEPTION_ALL_CU = 1_326_642.0
EXPECTED_ALL_CU_BASIS = 6_836_520.0


def _mutated_registry(mutate) -> Path:
    """Write a copy of the pinned registry with ``mutate`` applied."""
    payload = json.loads(SCOPE_RULES_PATH.read_text(encoding="utf-8"))
    mutate(payload)
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(payload, handle)
    handle.close()
    return Path(handle.name)


class TestScopeRuleRegistry(unittest.TestCase):
    """Spec sections 5 and 13."""

    @classmethod
    def setUpClass(cls):
        cls.registry = load_scope_rules()

    def test_claims_every_exception_exactly_once(self):
        claimed = [ucc for rule in self.registry.rules for ucc in rule.source_uccs]
        self.assertEqual(len(claimed), EXPECTED_EXCEPTION_COUNT)
        self.assertEqual(
            len(set(claimed)),
            EXPECTED_EXCEPTION_COUNT,
            "a UCC claimed by two rules would be double counted",
        )

    def test_materiality_sums_to_the_milestone_1_exception_total(self):
        total = sum(rule.materiality_all_cu for rule in self.registry.rules)
        self.assertAlmostEqual(total, EXPECTED_EXCEPTION_ALL_CU, places=1)

    def test_rule_type_implies_final_status(self):
        expected = {
            RuleType.EXCLUDE: MappingStatus.OUT_OF_SCOPE,
            RuleType.REPLACE: MappingStatus.TRANSFORMED,
            RuleType.COMBINE: MappingStatus.TRANSFORMED,
            RuleType.REASSIGN: MappingStatus.TRANSFORMED,
            RuleType.RETAIN: MappingStatus.DIRECT,
            RuleType.UNRESOLVED: MappingStatus.UNRESOLVED,
        }
        for rule in self.registry.rules:
            self.assertIs(rule.final_status, expected[rule.rule_type], rule.rule_id)

    def test_exclusions_cite_authoritative_sources(self):
        """Section 5.2: nothing is excluded without a published BLS basis."""
        for rule in self.registry.rules_of_type(RuleType.EXCLUDE):
            self.assertTrue(rule.authoritative_basis, rule.rule_id)
            self.assertTrue(rule.source_document_titles, rule.rule_id)
            for source_id in rule.authoritative_basis:
                self.assertIn(source_id, self.registry.sources, rule.rule_id)

    def test_unresolved_cites_no_authority(self):
        """An unresolved item must not appear to rest on evidence."""
        for rule in self.registry.rules_of_type(RuleType.UNRESOLVED):
            self.assertEqual(rule.authoritative_basis, (), rule.rule_id)

    def test_weak_evidence_never_excludes(self):
        for rule in self.registry.rules:
            if rule.evidence_strength is EvidenceStrength.WEAK:
                self.assertIsNot(rule.rule_type, RuleType.EXCLUDE, rule.rule_id)

    def test_candidate_nodes_are_never_applied(self):
        """Section 5.3: a research lead is not a mapping."""
        for rule in self.registry.rules:
            if rule.rule_type not in (RuleType.EXCLUDE, RuleType.UNRESOLVED):
                continue
            for ucc in rule.source_uccs:
                self.assertIsNone(rule.resolved_node_for(ucc), f"{rule.rule_id}/{ucc}")

    def test_applied_rules_resolve_to_a_real_taxonomy_node(self):
        nodes = load_taxonomy()
        for rule in self.registry.rules:
            if rule.rule_type in (RuleType.EXCLUDE, RuleType.UNRESOLVED):
                continue
            for ucc in rule.source_uccs:
                self.assertIn(rule.resolved_node_for(ucc), nodes, rule.rule_id)

    def test_proposed_rules_state_their_blocker(self):
        for rule in self.registry.rules:
            if rule.review_status is ReviewStatus.PROPOSED:
                self.assertTrue(rule.review_blocker, rule.rule_id)
                self.assertFalse(rule.is_applicable, rule.rule_id)

    def test_shelter_rules_are_not_yet_accepted(self):
        """The Track-A shelter rule is held pending PUMD benchmark validation."""
        shelter = [
            "OS_CPI_MORTGAGE_INTEREST_AND_CHARGES_v0_1",
            "OS_CPI_RESIDENTIAL_PROPERTY_TAX_v0_1",
            "OS_CPI_OWNER_STRUCTURE_INVESTMENT_v0_1",
            "RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1",
        ]
        for rule_id in shelter:
            self.assertIs(
                self.registry.rule_by_id(rule_id).review_status,
                ReviewStatus.PROPOSED,
                f"{rule_id} must not be accepted before the shelter rule is settled",
            )

    def test_combine_rules_state_a_formula(self):
        for rule in self.registry.rules_of_type(RuleType.COMBINE):
            self.assertTrue(rule.transformation_formula, rule.rule_id)

    def test_unknown_ucc_raises(self):
        with self.assertRaises(UnknownUccError):
            self.registry.rule_for("000000")


class TestScopeRuleRegistryRejectsDefects(unittest.TestCase):
    """The loader must fail loudly rather than accept a broken registry."""

    def _assert_rejected(self, mutate, fragment):
        path = _mutated_registry(mutate)
        try:
            with self.assertRaises(ScopeRuleError) as caught:
                load_scope_rules(path)
            self.assertIn(fragment, str(caught.exception))
        finally:
            path.unlink()

    def test_double_claimed_ucc_is_rejected(self):
        """The stolen UCC keeps its label so double-claiming is the only defect."""

        def mutate(payload):
            victim, thief = payload["rules"][0], payload["rules"][1]
            thief["source_uccs"].append(victim["source_uccs"][0])
            thief["source_labels"].append(victim["source_labels"][0])

        self._assert_rejected(mutate, "claimed")

    def test_exclusion_without_authority_is_rejected(self):
        def mutate(payload):
            for rule in payload["rules"]:
                if rule["rule_type"] == "EXCLUDE":
                    rule["authoritative_basis"] = []
                    return

        self._assert_rejected(mutate, "authoritative")

    def test_rule_type_final_status_mismatch_is_rejected(self):
        def mutate(payload):
            payload["rules"][0]["final_status"] = "OUT_OF_SCOPE"

        self._assert_rejected(mutate, "final_status")

    def test_material_suppression_without_disposition_is_rejected(self):
        def mutate(payload):
            for rule in payload["rules"]:
                if rule["suppression_status"] == "MATERIAL":
                    rule.pop("suppression_disposition")
                    return

        self._assert_rejected(mutate, "suppression_disposition")

    def test_track_b_retention_without_price_index_is_rejected(self):
        """Section 7 requires the needed price indexes to be identified."""

        def mutate(payload):
            for rule in payload["rules"]:
                if rule["track_b"]["treatment"] == "RETAIN_CURRENT_PAYMENT":
                    rule["track_b"]["price_index_needed"] = []
                    return

        self._assert_rejected(mutate, "price_index_needed")

    def test_broken_reconciliation_is_rejected(self):
        def mutate(payload):
            payload["coverage"]["reconciliation_all_cu"]["unresolved"] += 1000.0

        self._assert_rejected(mutate, "reconcil")

    def test_validation_test_naming_a_missing_module_is_rejected(self):
        def mutate(payload):
            payload["rules"][0]["validation_test"] = (
                "tests/research/test_never_written.py::test_something"
            )

        self._assert_rejected(mutate, "does not exist")


class TestTrackB(unittest.TestCase):
    """Spec section 7. Track B is a comparison, not a methodology change."""

    @classmethod
    def setUpClass(cls):
        cls.registry = load_scope_rules()

    def test_every_ucc_has_a_track_b_treatment(self):
        for rule in self.registry.rules:
            for ucc in rule.source_uccs:
                self.assertIsInstance(rule.track_b_for(ucc), TrackBTreatment)

    def test_non_housing_rules_are_not_applicable(self):
        for rule_id in (
            "TR_TRIP_FOOD_ALCOHOL_v0_1",
            "OS_CPI_VEHICLE_FINANCE_CHARGES_v0_1",
            "TR_VEHICLE_REGISTRATION_FEES_v0_1",
            "TR_EV_CHARGING_v0_1",
        ):
            rule = self.registry.rule_by_id(rule_id)
            self.assertIs(rule.track_b_treatment, TrackBTreatment.NOT_APPLICABLE)

    def test_per_ucc_override_applies(self):
        rule = self.registry.rule_by_id("UNRESOLVED_v0_2")
        self.assertIs(rule.track_b_for("450351"), TrackBTreatment.NOT_APPLICABLE)
        self.assertIs(rule.track_b_for("340915"), TrackBTreatment.UNRESOLVED)

    def test_capital_acquisition_is_excluded_from_both_tracks(self):
        """The one exclusion a payments concept also makes."""
        rule = self.registry.rule_by_id("OS_CPI_CAPITAL_IMPROVEMENT_v0_1")
        self.assertIs(rule.rule_type, RuleType.EXCLUDE)
        self.assertIs(
            rule.track_b_treatment, TrackBTreatment.EXCLUDE_CAPITAL_ACQUISITION
        )

    def test_mortgage_interest_diverges_between_tracks(self):
        """The central Track-A/Track-B concept difference."""
        rule = self.registry.rule_by_id("OS_CPI_MORTGAGE_INTEREST_AND_CHARGES_v0_1")
        self.assertIs(rule.final_status, MappingStatus.OUT_OF_SCOPE)
        self.assertIs(rule.track_b_treatment, TrackBTreatment.RETAIN_CURRENT_PAYMENT)
        self.assertTrue(rule.track_b_price_index_needed)


class TestStructuralEvidence(unittest.TestCase):
    """The registry's ``structural_evidence`` claims, checked against the data.

    These claims carry the milestone's main analytical finding, so they are
    verified here rather than taken on trust from the prose that records them.
    Every assertion below reads the pinned concordance, which is committed, so
    these tests run without the external BLS extracts.
    """

    @classmethod
    def setUpClass(cls):
        cls.registry = load_scope_rules()
        cls.evidence = cls.registry.structural_evidence
        cls.concordance = load_concordance()
        cls.resolver = load_eli_resolver(load_taxonomy())

    def test_owner_renter_counterpart_structure(self):
        """OWNER_RENTER_COUNTERPART_TEST.

        Casey (2010) Appendix B note 4 says renter UCCs are paired with
        homeowner UCCs to compute rental-equivalence adjustments. If that
        governs the concordance, then each claimed pair maps to the same
        destination, and each owner UCC with no renter counterpart is unmapped.
        """
        claim = self.evidence["OWNER_RENTER_COUNTERPART_TEST"]

        pairs = (
            ("240112", "240111"),
            ("240122", "240121"),
            ("240212", "240211"),
            ("240222", "240221"),
            ("240312", "240311"),
            ("240322", "240321"),
            ("320612", "320611"),
            ("320625", "320624"),
            ("320632", "320631"),
            ("230142", "230141"),
            ("230112", "230150"),
            ("220121", "350110"),
        )
        for owner, renter in pairs:
            owner_entry = self.concordance.get(owner)
            renter_entry = self.concordance.get(renter)
            self.assertIsNotNone(owner_entry, f"{owner} should be mapped")
            self.assertIsNotNone(renter_entry, f"{renter} should be mapped")
            self.assertEqual(
                owner_entry.elis,
                renter_entry.elis,
                f"{owner} and {renter} are claimed as a counterpart pair, so "
                f"they must share a destination",
            )
            self.assertIn(owner, claim["result_owned_dwellings"])
            self.assertIn(renter, claim["result_owned_dwellings"])

        # The eight owner UCCs the exclusion rule rests on: unmapped because
        # the CE renter branch has no code expressing the same concept.
        rule = self.registry.rule_by_id("OS_CPI_OWNER_STRUCTURE_INVESTMENT_v0_1")
        self.assertEqual(len(rule.source_uccs), 8)
        for ucc in rule.source_uccs:
            self.assertIsNone(
                self.concordance.get(ucc),
                f"{ucc} is claimed to have no renter counterpart, so it must "
                f"be absent from the concordance",
            )
            self.assertIn(ucc, claim["result_owned_dwellings"])

    def test_owner_renter_counterexception_is_disclosed(self):
        """The one case that does not fit is recorded, not suppressed."""
        claim = self.evidence["OWNER_RENTER_COUNTERPART_TEST"]
        entry = self.concordance.get("340911")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.elis, ("HP090",))
        self.assertIn("340911", claim["known_exception_to_the_pattern"])
        self.assertIn("HP090", claim["known_exception_to_the_pattern"])

    def test_rented_dwelling_branch_has_exactly_three_unmapped_codes(self):
        claim = self.evidence["OWNER_RENTER_COUNTERPART_TEST"]
        for ucc in ("230144", "990920", "790690"):
            self.assertIsNone(self.concordance.get(ucc))
            self.assertIn(ucc, claim["result_rented_dwellings"])

    def test_trip_food_allocation_is_node_invariant(self):
        """TRIP_FOOD_NODE_INVARIANCE.

        BLS does not publish the factors that allocate vacation food across
        food expenditure classes. The reassignment is defensible anyway only
        if every possible destination lands on the same DMI node, so that the
        unpublished weights cannot change the node total.
        """
        by_prefix: dict[str, set[str]] = {}
        for entry in self.concordance.entries.values():
            for eli in entry.elis:
                by_prefix.setdefault(eli[:2], set()).add(self.resolver.resolve(eli))

        food_prefixes = {p for p in by_prefix if p.startswith("F")}
        alcohol_prefixes = {"FW", "FX"}
        self.assertTrue(food_prefixes)
        self.assertTrue(alcohol_prefixes <= food_prefixes)

        for prefix in sorted(food_prefixes - alcohol_prefixes):
            self.assertEqual(
                by_prefix[prefix],
                {"FOOD"},
                f"ELI prefix {prefix} would let the unpublished BLS allocation "
                f"move expenditure off node FOOD",
            )
        for prefix in sorted(alcohol_prefixes):
            self.assertEqual(by_prefix[prefix], {"ALCOHOLIC_BEVERAGES"})

    def test_vehicle_registration_combine_destination(self):
        """VEHICLE_REGISTRATION_COMBINE_IDENTITY, concordance side only.

        The record-level 510115 = 520110 + 950024 identity is asserted from CE
        Interview PUMD microdata, which is not distributed with this
        repository, so it is not reproduced here. What is checkable is the
        claim the COMBINE rule actually depends on: that the successor code
        resolves to a single destination, TF011.
        """
        claim = self.evidence["VEHICLE_REGISTRATION_COMBINE_IDENTITY"]
        self.assertEqual(claim["reproduced_by_test"], False)

        entry = self.concordance.get("510115")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.elis, ("TF011",))
        self.assertIn("TF011", claim["corroboration"])

        rule = self.registry.rule_by_id("TR_VEHICLE_REGISTRATION_FEES_v0_1")
        self.assertIs(rule.rule_type, RuleType.COMBINE)
        self.assertEqual(set(rule.source_uccs), {"520110", "950024"})
        for ucc in rule.source_uccs:
            self.assertIsNone(
                self.concordance.get(ucc),
                f"{ucc} is a Milestone-1 exception and must be unmapped",
            )

    def test_ev_charging_node_and_disjointness(self):
        """TR_EV_CHARGING_v0_1.

        Spec section 11 forbids assigning EV charging by analogy. The scope
        claim rests on BLS's own ELI definition, so it is checked against the
        pinned Appendix 2 text rather than against the sibling gasoline codes.
        """
        rule = self.registry.rule_by_id("TR_EV_CHARGING_v0_1")
        self.assertEqual(rule.source_uccs, ("470311",))
        self.assertEqual(rule.output_eli, "TB022")

        # BLS names electricity as an alternative motor fuel. Without this the
        # rule would be an analogy from the neighbouring gasoline codes.
        descriptions = load_eli_descriptions()
        definition = descriptions["TB022"]["definition"].lower()
        self.assertIn("electric", definition)
        self.assertIn("consumer automobiles", definition)

        # The destination node follows from the ELI, not from our preference.
        self.assertEqual(self.resolver.resolve("TB022"), "MOTOR_FUEL")
        self.assertEqual(rule.resolved_node_for("470311"), "MOTOR_FUEL")

        # Home charging is a different ELI on a different node, so the
        # away-from-home restriction is what keeps the two from colliding.
        self.assertEqual(self.resolver.resolve("HF011"), "HOUSEHOLD_ENERGY")

        # 470311 is unmapped while the codes that do carry TB022's weight are
        # mapped. That asymmetry is the rule's whole reason for existing.
        self.assertIsNone(self.concordance.get("470311"))
        for ucc in ("470111", "470113"):
            entry = self.concordance.get(ucc)
            self.assertIsNotNone(entry)
            self.assertIn(
                "TB022",
                entry.elis,
                f"{ucc} is claimed to carry TB022's weight under concordance "
                f"trailer note (1)",
            )

    def test_vehicle_finance_uccs_are_unmapped(self):
        """OS_CPI_VEHICLE_FINANCE_CHARGES_v0_1.

        The CPI excludes interest and finance charges outright, so every
        member must be absent from the concordance and the rule must cite that
        exclusion rather than infer it.
        """
        rule = self.registry.rule_by_id("OS_CPI_VEHICLE_FINANCE_CHARGES_v0_1")
        self.assertEqual(len(rule.source_uccs), 4)
        self.assertIs(rule.final_status, MappingStatus.OUT_OF_SCOPE)
        self.assertIs(rule.evidence_strength, EvidenceStrength.STRONG)
        for ucc in rule.source_uccs:
            self.assertIsNone(self.concordance.get(ucc))
        for label in rule.source_labels:
            self.assertIn("finance charge", label.lower())

    def test_owned_vacation_branch_is_wholly_unmapped(self):
        """RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1.

        The REPLACE treatment rests on the *whole* owned-vacation branch being
        unmapped. A single mapped member would mean BLS treats the branch
        item-by-item and would undercut the rule.
        """
        rule = self.registry.rule_by_id("RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1")
        self.assertEqual(len(rule.source_uccs), 15)
        self.assertIs(rule.rule_type, RuleType.REPLACE)
        for ucc in rule.source_uccs:
            self.assertIsNone(self.concordance.get(ucc))
        for label in rule.source_labels:
            self.assertIn(
                "owned vacation",
                label.lower(),
                "every member must be an owned-vacation code",
            )

    def test_capital_improvement_unmapped_on_all_tenures(self):
        """OS_CPI_CAPITAL_IMPROVEMENT_v0_1.

        Tenure cannot explain this exclusion, because the concept is unmapped
        for renters, owners and vacation homes alike. That is what
        distinguishes it from the owner-structure exclusion.
        """
        rule = self.registry.rule_by_id("OS_CPI_CAPITAL_IMPROVEMENT_v0_1")
        self.assertIn("990920", rule.source_uccs)  # renter
        self.assertIn("990930", rule.source_uccs)  # owner
        self.assertIn("990940", rule.source_uccs)  # owned vacation
        for ucc in rule.source_uccs:
            self.assertIsNone(self.concordance.get(ucc))
        self.assertIs(rule.final_status, MappingStatus.OUT_OF_SCOPE)
        self.assertIs(
            rule.track_b_treatment, TrackBTreatment.EXCLUDE_CAPITAL_ACQUISITION
        )

    def test_every_rule_names_a_test_that_exists(self):
        """A rule may not cite validation it does not have.

        The registry previously named a test module that had never been
        written, which is how a claim can look verified while being unchecked.
        """
        for rule in self.registry.rules:
            self.assertTrue(
                rule.validation_test, f"{rule.rule_id} names no validation test"
            )
            unresolved = _unresolved_citation(rule.validation_test)
            self.assertIsNone(
                unresolved, f"{rule.rule_id} cites {rule.validation_test}: {unresolved}"
            )

    def test_unreproduced_claims_say_so(self):
        """A claim no test reproduces must not look like one that a test does."""
        for name, claim in self.evidence.items():
            reproduced = claim.get("reproduced_by_test")
            self.assertIsInstance(
                reproduced, bool, f"{name} must state whether a test reproduces it"
            )
            if reproduced:
                self.assertTrue(
                    claim.get("validation_test"),
                    f"{name} claims reproduction but names no test",
                )
            else:
                self.assertTrue(
                    claim.get("not_reproduced_reason"),
                    f"{name} is not reproduced and must say why",
                )

    def test_citation_resolver_rejects_fabricated_targets(self):
        """The guard above is only worth having if it can fail.

        A checker that accepts everything is indistinguishable from no checker,
        so each way a citation can be wrong is exercised here against this very
        module.
        """
        real = (
            "tests/test_detailed_inflation_milestone_2.py"
            "::TestStructuralEvidence::test_ev_charging_node_and_disjointness"
        )
        self.assertIsNone(_unresolved_citation(real))

        for bad in (
            # A real module and class, but a method nobody wrote.
            "tests/test_detailed_inflation_milestone_2.py"
            "::TestStructuralEvidence::test_never_written",
            # A real module, but a class nobody wrote.
            "tests/test_detailed_inflation_milestone_2.py"
            "::TestNeverWritten::test_ev_charging_node_and_disjointness",
            # No module at all -- the original defect.
            "tests/research/test_never_written.py::TestX::test_y",
            # A module with no test named inside it.
            "tests/test_detailed_inflation_milestone_2.py",
        ):
            self.assertIsNotNone(
                _unresolved_citation(bad), f"{bad} should not resolve"
            )

    def test_structural_evidence_citations_resolve(self):
        """Section 13 evidence blocks are held to the same standard as rules.

        A block may cite several tests, and every one of them must name a test
        that exists, or the block's ``reproduced_by_test`` flag is worthless.
        """
        for name, claim in self.evidence.items():
            cited = claim.get("validation_test") or []
            if isinstance(cited, str):
                cited = [cited]
            for reference in cited:
                unresolved = _unresolved_citation(reference)
                self.assertIsNone(
                    unresolved, f"{name} cites {reference}: {unresolved}"
                )


class TestUccProvenanceClasses(unittest.TestCase):
    """The published CE item file is not the whole CPI-relevant UCC universe.

    Milestone 1 keyed its basis on ``cx.item`` and treated a missing UCC as
    fatal. That is right for the basis, but the concordance names 17 UCCs
    ``cx.item`` does not contain, and every one resolves to a live DMI node.
    These tests hold the classification to its two sources so the omission
    cannot be reintroduced silently.
    """

    @classmethod
    def setUpClass(cls):
        cls.registry = load_provenance_classes()
        cls.concordance = load_concordance()
        cls.roster = cls.registry["concordance_only_uccs"]["roster"]
        cls.correspondence = cls.registry["shelter_rental_equivalence_correspondence"]

    def test_classes_partition_the_union(self):
        """Derived from synthetic inputs: one class each, nothing dropped."""
        with tempfile.TemporaryDirectory() as tmp:
            path = write_concordance(
                Path(tmp),
                [
                    ("010119", "FA011", "In both", "Flour"),
                    ("999999", "FA011", "Concordance only", "Flour"),
                ],
            )
            concordance = load_concordance(path)

        # "FOODTOTL" is an aggregate rollup, not a UCC, and must not be counted.
        report = classify_ucc_provenance(
            concordance, ["010119", "020219", "FOODTOTL"]
        )
        classes = {row.ucc: row.provenance_class for row in report.rows}
        self.assertEqual(
            classes,
            {
                "010119": UccProvenanceClass.DIRECT_CONCORDANCE_UCC,
                "020219": UccProvenanceClass.PUBLISHED_CE_UCC,
                "999999": UccProvenanceClass.CONCORDANCE_ONLY_UCC,
            },
        )
        self.assertEqual(report.counts["published_ce_universe"], 2)
        self.assertEqual(report.counts["union"], 3)
        self.assertEqual(
            sum(report.counts[member.value] for member in UccProvenanceClass),
            report.counts["union"],
            "the three classes must exhaust the union with no double counting",
        )

    def test_pinned_counts_are_internally_consistent(self):
        """The pinned counts must add up before they are compared to anything."""
        counts = self.registry["counts"]
        self.assertEqual(
            counts["DIRECT_CONCORDANCE_UCC"] + counts["PUBLISHED_CE_UCC"],
            counts["published_ce_universe"],
        )
        self.assertEqual(
            counts["DIRECT_CONCORDANCE_UCC"] + counts["CONCORDANCE_ONLY_UCC"],
            counts["concordance_universe"],
        )
        self.assertEqual(
            counts["published_ce_universe"] + counts["CONCORDANCE_ONLY_UCC"],
            counts["union"],
        )

    def test_concordance_only_roster_is_well_formed(self):
        counts = self.registry["counts"]
        self.assertEqual(len(self.roster), counts["CONCORDANCE_ONLY_UCC"])
        scales = self.registry["evidence_scales"]
        seen = set()
        for item in self.roster:
            self.assertRegex(item["ucc"], r"^[0-9]{6}$")
            self.assertNotIn(item["ucc"], seen, "duplicate roster entry")
            seen.add(item["ucc"])
            self.assertTrue(item["elis"], f"{item['ucc']} names no ELI")
            self.assertTrue(item["dmi_node"], f"{item['ucc']} names no DMI node")
            self.assertTrue(item["note"], f"{item['ucc']} carries no note")
            # Each of the three claims must be stated, and stated on its own
            # declared scale. A roster entry that simply omitted one would let
            # the reader supply the missing value from the class name, which is
            # the inference this split exists to block.
            for field in (
                "publication_reason",
                "pumd_membership",
                "cpi_adjustment_status",
            ):
                self.assertIn(
                    field, item, f"{item['ucc']} does not state {field}"
                )
                self.assertIn(
                    item[field],
                    scales[field],
                    f"{item['ucc']} uses a {field} outside the declared scale",
                )

    def test_roster_is_drawn_from_the_pinned_concordance(self):
        """Every roster member must really be a concordance UCC.

        This half of the claim needs no external file, so it is checked even
        where ``cx.item`` is unavailable.
        """
        for item in self.roster:
            entry = self.concordance.get(item["ucc"])
            self.assertIsNotNone(
                entry, f"{item['ucc']} is not in the pinned concordance at all"
            )
            self.assertEqual(tuple(item["elis"]), entry.elis)
            self.assertEqual(item["concordance_title"], entry.ucc_title)
            self.assertEqual(item["ce_source"], entry.ce_source)

    def test_shelter_correspondence_sits_on_the_right_side_of_each_universe(self):
        """The amendment's premise, checked rather than assumed.

        The CPI concordance uses 910104-910107; the 9100xx/9101xx addenda it
        does not use are the published counterparts. If a published counterpart
        turned up in the concordance, it would not be a counterpart at all.
        """
        pairs = self.correspondence["pairs"]
        self.assertEqual(len(pairs), 4)
        for pair in pairs:
            normative = pair["concordance_only_ucc"]
            published = pair["published_ce_ucc"]
            entry = self.concordance.get(normative)
            self.assertIsNotNone(
                entry, f"{normative} must be a concordance UCC to be the input"
            )
            self.assertIn(pair["eli"], entry.elis)
            self.assertIsNone(
                self.concordance.get(published),
                f"{published} is claimed to be a published-only counterpart, "
                f"but the concordance maps it",
            )
            self.assertIn(
                normative,
                {item["ucc"] for item in self.roster},
                f"{normative} must also appear in the concordance-only roster",
            )

    def test_shelter_correspondence_is_labelled_inference_not_bls_mapping(self):
        """The user's instruction: high-confidence DMI inference, not BLS mapping."""
        self.assertEqual(self.correspondence["claim_type"], "DMI_INFERENCE")
        self.assertTrue(self.correspondence["explicit_warning"])
        self.assertEqual(
            self.correspondence["normative_input_class"],
            UccProvenanceClass.CONCORDANCE_ONLY_UCC.value,
        )
        self.assertTrue(self.correspondence["normative_input_rationale"])

    def test_published_addenda_anomaly_is_recorded_not_hidden(self):
        """910103 is titled 'annual' where its three siblings say 'monthly'.

        The anomaly must stay visible and must not be quietly presented as a
        blocker on Track A, because 910107 is the normative input.
        """
        anomaly = self.correspondence["published_addenda_anomaly"]
        self.assertEqual(anomaly["status"], "UNRESOLVED")
        self.assertEqual(anomaly["ucc"], "910103")
        self.assertFalse(anomaly["blocking"])
        self.assertTrue(anomaly["why_not_blocking"])

        titles = {
            pair["published_ce_ucc"]: pair["published_title"].lower()
            for pair in self.correspondence["pairs"]
        }
        self.assertIn("annual", titles["910103"])
        for ucc in ("910050", "910101", "910102"):
            self.assertIn("monthly", titles[ucc])
            self.assertNotIn("annual", titles[ucc])

    def test_count_drift_is_rejected(self):
        """A changed concordance vintage must error, not reclassify in silence."""
        with tempfile.TemporaryDirectory() as tmp:
            path = write_concordance(
                Path(tmp), [("010119", "FA011", "In both", "Flour")]
            )
            report = classify_ucc_provenance(load_concordance(path), ["010119"])

        with self.assertRaises(UccProvenanceError):
            verify_against_registry(report, self.registry)

    def test_classification_authorizes_no_expenditure(self):
        """§5: this artifact is descriptive and must say so."""
        consumer = self.registry["consumer_of_this_artifact"]
        self.assertIn("authorizes no expenditure", consumer["note"])
        self.assertEqual(self.registry["status"], "RESEARCH_ONLY")

    @unittest.skipUnless(external_sources_available(), "needs BLS cx.item")
    def test_derived_partition_matches_the_registry(self):
        """The whole claim, end to end, against the authoritative item file."""
        report = build_ucc_provenance(
            self.concordance,
            load_items(EXTERNAL_SOURCES["items"]),
            resolver=load_eli_resolver(load_taxonomy()),
        )
        for key, expected in self.registry["counts"].items():
            if isinstance(expected, int):
                self.assertEqual(report.counts[key], expected, f"count {key}")
        self.assertEqual(
            sorted(report.uccs_in(UccProvenanceClass.CONCORDANCE_ONLY_UCC)),
            sorted(item["ucc"] for item in self.roster),
        )

    @unittest.skipUnless(external_sources_available(), "needs BLS cx.item")
    def test_every_hidden_ucc_resolves_to_a_live_dmi_node(self):
        """Nothing in this class is safely ignorable.

        If some of the 17 resolved nowhere, omitting them would be defensible.
        None of them does.
        """
        report = build_ucc_provenance(
            self.concordance,
            load_items(EXTERNAL_SOURCES["items"]),
            resolver=load_eli_resolver(load_taxonomy()),
        )
        for row in report.by_class(UccProvenanceClass.CONCORDANCE_ONLY_UCC):
            self.assertTrue(
                row.dmi_node, f"{row.ucc} would be dropped with no node to miss"
            )

    @unittest.skipUnless(external_sources_available(), "needs BLS cx.item")
    def test_published_shelter_counterparts_match_cx_item_titles(self):
        """The recorded titles, and the annual/monthly anomaly, come from source."""
        items = load_items(EXTERNAL_SOURCES["items"])
        published = {}
        for (_subcategory, code), record in items.items():
            published.setdefault(code, record.item_text)

        for pair in self.correspondence["pairs"]:
            ucc = pair["published_ce_ucc"]
            self.assertIn(ucc, published, f"{ucc} is not published in cx.item")
            self.assertEqual(
                published[ucc],
                pair["published_title"],
                f"{ucc} title drifted from cx.item",
            )
            self.assertNotIn(
                pair["concordance_only_ucc"],
                published,
                "a CONCORDANCE_ONLY_UCC must be absent from cx.item by definition",
            )


class TestProvenanceClassIsNotAnEvidenceClaim(unittest.TestCase):
    """Source-file membership, PUMD availability and CPI adjustment are three
    separate claims and must be separately gradeable.

    The class was called ``CPI_ADJUSTED_PUMD_UCC``. Membership of it was
    established purely by set difference: in the concordance, absent from
    ``cx.item``. That evidence supports neither "is in the PUMD" nor "the CPI
    adjusts it", yet the name asserted both, so any consumer reading the class
    inherited two unverified claims for free.
    """

    @classmethod
    def setUpClass(cls):
        cls.registry = load_provenance_classes()
        cls.concordance = load_concordance()
        cls.roster = cls.registry["concordance_only_uccs"]["roster"]
        cls.evidence = concordance_only_evidence(cls.registry)

    def test_the_class_names_only_what_set_membership_shows(self):
        """The rename, and the reason for it, are both on the record."""
        self.assertEqual(
            UccProvenanceClass.CONCORDANCE_ONLY_UCC.value, "CONCORDANCE_ONLY_UCC"
        )
        self.assertEqual(
            {member.value for member in UccProvenanceClass},
            {
                "DIRECT_CONCORDANCE_UCC",
                "PUBLISHED_CE_UCC",
                "CONCORDANCE_ONLY_UCC",
            },
        )
        scope = self.registry["scope_of_the_classification"]
        self.assertTrue(scope["what_it_proves"])
        self.assertTrue(scope["what_it_does_not_prove"])
        self.assertIn("CPI_ADJUSTED_PUMD_UCC", scope["naming_history"])

    def test_the_three_claims_are_graded_on_declared_scales(self):
        """A claim with no scale cannot be audited."""
        scales = self.registry["evidence_scales"]
        self.assertTrue(scales["note"])
        self.assertEqual(
            set(scales) - {"note"},
            {"pumd_membership", "cpi_adjustment_status", "publication_reason"},
        )
        for field, enum in (
            ("pumd_membership", PumdMembership),
            ("cpi_adjustment_status", CpiAdjustmentStatus),
            ("publication_reason", PublicationReason),
        ):
            self.assertEqual(
                set(scales[field]),
                {member.value for member in enum},
                f"{field} scale drifted from the code",
            )
            for value, definition in scales[field].items():
                self.assertTrue(definition, f"{field}/{value} is undefined")

    def test_pumd_membership_is_not_inferred_from_the_class(self):
        """The core requirement: membership does not imply PUMD availability.

        If the roster asserted VERIFIED across the board, the split would be
        cosmetic. Exactly one of the 17 carries a cited observation.
        """
        verified = [
            item["ucc"]
            for item in self.roster
            if item["pumd_membership"] == PumdMembership.VERIFIED.value
        ]
        not_verified = [
            item["ucc"]
            for item in self.roster
            if item["pumd_membership"] == PumdMembership.NOT_VERIFIED.value
        ]
        self.assertEqual(len(verified) + len(not_verified), len(self.roster))
        self.assertTrue(
            not_verified,
            "if every concordance-only UCC were PUMD-verified, the old name "
            "would have been accurate and this split unnecessary",
        )
        self.assertEqual(
            len(verified),
            1,
            "exactly one concordance-only UCC carries a cited PUMD observation; "
            "if this grows, check that each new citation resolves",
        )
        for ucc in verified:
            evidence = self.evidence[ucc]["pumd_membership_evidence"]
            self.assertTrue(evidence["observation"], f"{ucc} cites no observation")
            # The citation must land on a real registry record, not merely look
            # like one. A VERIFIED grade rests entirely on this pointer.
            target = _resolve_registry_citation(evidence["citation"])
            self.assertIsNotNone(
                target,
                f"{ucc} PUMD evidence cites {evidence['citation']}, which does "
                f"not resolve",
            )
            self.assertIn(ucc, json.dumps(target))
            # And the grade must not overstate what the citation supports.
            self.assertFalse(evidence["reproduced_by_test"])
            self.assertTrue(evidence["reproducibility_caveat"])

    def test_unverified_pumd_membership_is_not_a_claim_of_absence(self):
        """NOT_VERIFIED must read as silence, not as a negative finding."""
        scales = self.registry["evidence_scales"]["pumd_membership"]
        self.assertIn("does not claim either way", scales["NOT_VERIFIED"])
        for item in self.roster:
            if item["pumd_membership"] != PumdMembership.NOT_VERIFIED.value:
                continue
            self.assertNotIn(
                "pumd_membership_evidence",
                item,
                f"{item['ucc']} is NOT_VERIFIED yet carries evidence",
            )

    def test_cpi_adjustment_inferences_are_labelled_as_dmi_readings(self):
        """An INFERRED status must say whose inference it is.

        The four shelter inputs are the only ones asserted at all, and only as a
        DMI reading of BLS titles. A BLS statement would be VERIFIED, and none
        is claimed.
        """
        inferred = [
            item
            for item in self.roster
            if item["cpi_adjustment_status"] == CpiAdjustmentStatus.INFERRED.value
        ]
        self.assertTrue(inferred, "the fixture must exercise an inferred status")
        for item in inferred:
            evidence = item["cpi_adjustment_evidence"]
            self.assertEqual(evidence["claim_type"], "DMI_INFERENCE")
            self.assertTrue(evidence["basis"])
            self.assertTrue(
                evidence["limit"], f"{item['ucc']} states no limit on the inference"
            )
        self.assertFalse(
            [
                item["ucc"]
                for item in self.roster
                if item["cpi_adjustment_status"] == CpiAdjustmentStatus.VERIFIED.value
            ],
            "no BLS statement of a CPI adjustment has been located, so nothing "
            "may be recorded as VERIFIED",
        )

    def test_ce_source_is_not_treated_as_pumd_evidence(self):
        """CE SOURCE = I names the instrument, not the microdata dictionary.

        This was the tempting shortcut: all four shelter inputs are Interview
        codes, so it would be easy to read 'I' as proof of PUMD reachability.
        """
        note = self.registry["concordance_only_uccs"]["ce_source_is_not_pumd_evidence"]
        self.assertTrue(note)
        shelter = {"910104", "910105", "910106", "910107"}
        for item in self.roster:
            if item["ucc"] not in shelter:
                continue
            self.assertEqual(item["ce_source"], "I")
            self.assertEqual(
                item["pumd_membership"],
                PumdMembership.NOT_VERIFIED.value,
                f"{item['ucc']} is an Interview code, which is not evidence of "
                f"PUMD membership",
            )
            self.assertTrue(item["pumd_membership_note"])

    def test_shelter_provenance_keeps_both_sides_on_the_right_side(self):
        """§B: the concordance inputs and the published counterparts.

        Restated here against the class enum rather than the correspondence
        block, so a rename in one place cannot drift from the other.
        """
        correspondence = self.registry["shelter_rental_equivalence_correspondence"]
        result = correspondence["structural_result"]
        self.assertEqual(
            sorted(result["concordance_only"]),
            ["910104", "910105", "910106", "910107"],
        )
        self.assertEqual(
            sorted(result["published_ce"]),
            ["910050", "910101", "910102", "910103"],
        )
        self.assertTrue(result["note"])
        roster_uccs = {item["ucc"] for item in self.roster}
        for ucc in result["concordance_only"]:
            self.assertIn(ucc, roster_uccs)
            self.assertIsNotNone(self.concordance.get(ucc))
        for ucc in result["published_ce"]:
            self.assertNotIn(ucc, roster_uccs)
            self.assertIsNone(self.concordance.get(ucc))

    def test_the_csv_surfaces_all_three_claims_beside_the_class(self):
        """A consumer reading the artifact must see the evidence, not infer it."""
        for column in (
            "provenance_class",
            "publication_reason",
            "pumd_membership",
            "cpi_adjustment_status",
        ):
            self.assertIn(column, PROVENANCE_CSV_COLUMNS)

    def test_absent_evidence_defaults_to_the_weakest_reading(self):
        """Silence must not be resolved in either direction.

        A concordance-only UCC with no registry record is unverified and unknown,
        never verified and never a claim of absence.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = write_concordance(
                Path(tmp),
                [
                    ("010119", "FA011", "In both", "Flour"),
                    ("999999", "FA011", "Concordance only", "Flour"),
                ],
            )
            report = classify_ucc_provenance(load_concordance(path), ["010119"])

        rows = {row.ucc: row for row in report.rows}
        hidden = rows["999999"]
        self.assertIs(hidden.provenance_class, UccProvenanceClass.CONCORDANCE_ONLY_UCC)
        self.assertIs(hidden.pumd_membership, PumdMembership.NOT_VERIFIED)
        self.assertIs(hidden.cpi_adjustment_status, CpiAdjustmentStatus.UNKNOWN)
        self.assertIs(hidden.publication_reason, PublicationReason.UNDOCUMENTED)
        # A published UCC has no non-publication to explain.
        self.assertIs(
            rows["010119"].publication_reason, PublicationReason.NOT_APPLICABLE
        )

    def test_evidence_never_alters_the_partition(self):
        """The class is structural, so supplying evidence cannot move a UCC."""
        with tempfile.TemporaryDirectory() as tmp:
            path = write_concordance(
                Path(tmp),
                [
                    ("010119", "FA011", "In both", "Flour"),
                    ("999999", "FA011", "Concordance only", "Flour"),
                ],
            )
            concordance = load_concordance(path)

        without = classify_ucc_provenance(concordance, ["010119"])
        with_evidence = classify_ucc_provenance(
            concordance,
            ["010119"],
            evidence={
                "999999": {
                    "pumd_membership": PumdMembership.VERIFIED.value,
                    "cpi_adjustment_status": CpiAdjustmentStatus.VERIFIED.value,
                    "publication_reason": PublicationReason.PUBFLAG_1.value,
                }
            },
        )
        self.assertEqual(without.counts, with_evidence.counts)
        self.assertEqual(
            [row.provenance_class for row in without.rows],
            [row.provenance_class for row in with_evidence.rows],
        )
        graded = next(row for row in with_evidence.rows if row.ucc == "999999")
        self.assertIs(graded.pumd_membership, PumdMembership.VERIFIED)

    def test_the_overclaiming_name_is_gone_from_active_use(self):
        """Repo-wide sweep. The old name may survive only as migration prose.

        Renaming the enum member is not enough: a stale key in an artifact, a
        doc table or a test fixture would keep the discredited claim in
        circulation. Occurrences are therefore allowed only where the text is
        explaining that the name was wrong.
        """
        allowed = {
            Path("dmi_research/detailed_inflation/provenance.py"),
            Path("registry/research/ucc_provenance_classes_v0_1.json"),
            Path("tests/test_detailed_inflation_milestone_2.py"),
            Path("docs/research/DETAILED_INFLATION_MILESTONE_2.md"),
        }
        searched = 0
        offenders = []
        for pattern in ("*.py", "*.json", "*.md", "*.csv", "*.tsv", "*.yml", "*.yaml"):
            for path in REPO_ROOT.rglob(pattern):
                if any(
                    part in {".git", ".venv", "node_modules", "__pycache__"}
                    for part in path.parts
                ):
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                searched += 1
                if "CPI_ADJUSTED_PUMD" not in text and "cpi_adjusted_pumd" not in text:
                    continue
                relative = path.relative_to(REPO_ROOT)
                if relative not in allowed:
                    offenders.append(str(relative))
        self.assertGreater(searched, 50, "the sweep did not actually read the repo")
        self.assertEqual(
            [], sorted(offenders), "the overclaiming name is still in active use"
        )

    def test_the_migration_prose_explains_the_rename(self):
        """An allowed occurrence must be an explanation, not a leftover.

        Whitelisting a file is only defensible if the text there says why the
        name was withdrawn.
        """
        module = (
            REPO_ROOT / "dmi_research/detailed_inflation/provenance.py"
        ).read_text(encoding="utf-8")
        self.assertIn("CPI_ADJUSTED_PUMD_UCC", module)
        self.assertIn("An earlier version of this module called", module)
        history = self.registry["scope_of_the_classification"]["naming_history"]
        self.assertIn("CPI_ADJUSTED_PUMD_UCC", history)
        self.assertIn("renames it CONCORDANCE_ONLY_UCC", history)


class TestConcordanceSourceColumn(unittest.TestCase):
    """The CE SOURCE column, documented and held to its documentation.

    The column was carried through the loader from Milestone 1 without ever
    being defined. A field nobody can interpret is a field that will eventually
    be interpreted wrongly, so the definition now lives in the provenance
    sidecar and the data is checked against it.
    """

    @classmethod
    def setUpClass(cls):
        cls.concordance = load_concordance()
        cls.block = cls.concordance.provenance["ce_source_column"]

    def test_every_documented_code_is_defined(self):
        self.assertEqual(set(self.block["codes"]), {"I", "D"})
        for code, definition in self.block["codes"].items():
            self.assertTrue(definition, f"code {code} has no definition")
        self.assertEqual(self.block["bls_column_name"], "CE SOURCE")

    def test_no_ucc_uses_an_undocumented_source_code(self):
        documented = set(self.block["codes"])
        for entry in self.concordance.entries.values():
            self.assertIn(
                entry.ce_source,
                documented,
                f"{entry.ucc} carries CE SOURCE {entry.ce_source!r}, which the "
                f"provenance sidecar does not define",
            )

    def test_ce_source_is_single_valued_per_ucc(self):
        """The loader keeps the first value seen; that is only safe if unique.

        ``load_concordance`` collapses 624 rows to 507 UCCs with ``setdefault``
        on this column. Were a UCC to carry both I and D, one would be silently
        discarded, so the invariant is checked against the raw rows rather than
        against the collapsed result, which could not reveal the conflict.
        """
        by_ucc: dict = {}
        with open(DEFAULT_CONCORDANCE_PATH, encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                by_ucc.setdefault(row["ucc"], set()).add(row["ce_source"])
        conflicts = {ucc: sorted(v) for ucc, v in by_ucc.items() if len(v) > 1}
        self.assertEqual(conflicts, {})
        self.assertTrue(self.block["single_valued_per_ucc"])

    def test_observed_counts_match_the_artifact(self):
        expected = self.block["observed_counts"]["distinct_uccs"]
        actual: dict = {}
        for entry in self.concordance.entries.values():
            actual[entry.ce_source] = actual.get(entry.ce_source, 0) + 1
        self.assertEqual(actual, expected)

    def test_shelter_inputs_are_interview_codes(self):
        """The sidecar's stated reason for carrying the column at all."""
        for ucc in ("910104", "910105", "910106", "910107"):
            self.assertEqual(self.concordance.get(ucc).ce_source, "I")

    def test_unverified_url_says_so(self):
        """bls.gov refused the fetch, so the field must not imply verification."""
        provenance = self.concordance.provenance
        self.assertTrue(provenance["source_page_url"].startswith("https://www.bls.gov/"))
        self.assertIn("403", provenance["source_page_url_note"])


class TestSemanticValidation(unittest.TestCase):
    """Spec section 15."""

    @classmethod
    def setUpClass(cls):
        cls.rows, cls.summary = build_semantic_validation()

    def test_no_eli_is_semantically_divergent(self):
        divergent = [
            row.eli for row in self.rows if row.review_result is ReviewResult.DIVERGENT
        ]
        self.assertEqual(
            divergent,
            [],
            "an ELI whose DMI node contradicts its own BLS major group is a "
            "mapping defect, not a judgement call",
        )

    def test_every_undescribed_eli_is_structurally_explained(self):
        self.assertEqual(
            self.summary["elis_without_bls_description_unexplained"],
            [],
            "an ELI absent from the BLS Appendix 2 descriptions must be "
            "explained by BLS's own title text, not waved through",
        )

    def test_expectations_cover_the_whole_taxonomy(self):
        self.assertEqual(set(NODE_TO_BLS_MAJOR_GROUPS), set(load_taxonomy()))

    def test_every_reviewed_eli_resolves_to_a_taxonomy_node(self):
        nodes = load_taxonomy()
        for row in self.rows:
            self.assertIn(row.dmi_node, nodes, row.eli)


class TestSuppressionBounds(unittest.TestCase):
    """Spec section 16 arithmetic, on synthetic inputs."""

    @staticmethod
    def _basis(*, active, missing, sum_active, parent):
        return Basis(
            entries=[],
            reconciliations=[
                ReconciliationResult(
                    subcategory_code="TESTDOM",
                    domain_label="Test",
                    population=ALL_CU,
                    active_ucc_count=active,
                    missing_aggregate_count=missing,
                    sum_active_ucc_aggregate=sum_active,
                    published_parent_aggregate=parent,
                    parent_series_id="CXUTESTDOMLB0101M",
                )
            ],
        )

    def test_bound_is_the_parent_gap_plus_rounding(self):
        basis = self._basis(active=5, missing=1, sum_active=900.0, parent=1000.0)
        bound = build_suppression_bounds(basis)[(ALL_CU, "TESTDOM")]
        self.assertEqual(bound.residual, 100.0)
        # 4 published leaves -> 0.5 * 1.0 * (4 + 1) = 2.5
        self.assertAlmostEqual(bound.rounding_bound, 2.5)
        self.assertAlmostEqual(bound.upper_bound, 102.5)

    def test_negative_residual_floors_at_zero(self):
        """Published children may exceed the parent by a rounding artifact."""
        basis = self._basis(active=5, missing=1, sum_active=1002.0, parent=1000.0)
        bound = build_suppression_bounds(basis)[(ALL_CU, "TESTDOM")]
        self.assertEqual(bound.residual, -2.0)
        self.assertAlmostEqual(bound.upper_bound, 2.5)
        self.assertGreaterEqual(bound.upper_bound, 0.0)

    def test_unpublished_parent_leaves_the_bound_unknown(self):
        """Absent a published parent, the suppressed total is not bounded."""
        basis = self._basis(active=5, missing=1, sum_active=900.0, parent=None)
        bound = build_suppression_bounds(basis)[(ALL_CU, "TESTDOM")]
        self.assertIsNone(bound.residual)
        self.assertIsNone(bound.upper_bound)


class TestTrackADispositionModel(unittest.TestCase):
    """A proposed disposition must not be representable as an effective one.

    These tests need no BLS extract. They are about the shape of the data model,
    and the original defect was a shape error: ``m2_track_a_status`` was assigned
    ``rule.final_status`` unconditionally, so the registry's *argument* about
    where shelter expenditure belongs was recorded as a *decision* that it was
    already there.
    """

    RESOLUTION_SOURCE = REPO_ROOT / "dmi_research/detailed_inflation/resolution.py"

    def _disposition(self, **overrides):
        base = {
            "proposed_status": MappingStatus.OUT_OF_SCOPE,
            "effective_status": MappingStatus.OUT_OF_SCOPE,
            "resolution_state": ResolutionState.EFFECTIVE,
            "review_status": ReviewStatus.ACCEPTED,
        }
        base.update(overrides)
        return TrackADisposition(**base)

    def test_an_accepted_rule_is_in_force(self):
        disposition = self._disposition()
        self.assertIs(disposition.effective_status, MappingStatus.OUT_OF_SCOPE)
        self.assertTrue(disposition.is_effective)

    def test_a_proposed_status_cannot_be_recorded_as_effective(self):
        """The exact defect, now unconstructable.

        A PROPOSED rule proposing OUT_OF_SCOPE is precisely the shelter case.
        Building the disposition that the old code built must raise.
        """
        with self.assertRaises(ResolutionError) as caught:
            self._disposition(review_status=ReviewStatus.PROPOSED)
        self.assertIn("ACCEPTED", str(caught.exception))

    def test_a_pending_disposition_holds_nothing_in_force(self):
        disposition = self._disposition(
            effective_status=MappingStatus.UNRESOLVED,
            resolution_state=ResolutionState.PENDING,
            review_status=ReviewStatus.PROPOSED,
        )
        self.assertIs(disposition.proposed_status, MappingStatus.OUT_OF_SCOPE)
        self.assertIs(disposition.effective_status, MappingStatus.UNRESOLVED)
        self.assertFalse(disposition.is_effective)

    def test_a_pending_disposition_must_actually_propose_something(self):
        """PENDING and OPEN are not interchangeable.

        Without this, a rule that decided nothing could be filed as "blocked on
        a prerequisite", which would understate the genuinely open gap.
        """
        with self.assertRaises(ResolutionError) as caught:
            self._disposition(
                proposed_status=MappingStatus.UNRESOLVED,
                effective_status=MappingStatus.UNRESOLVED,
                resolution_state=ResolutionState.PENDING,
                review_status=ReviewStatus.PROPOSED,
            )
        self.assertIn("OPEN", str(caught.exception))

    def test_an_open_disposition_must_propose_nothing(self):
        with self.assertRaises(ResolutionError) as caught:
            self._disposition(
                effective_status=MappingStatus.UNRESOLVED,
                resolution_state=ResolutionState.OPEN,
                review_status=ReviewStatus.OPEN,
            )
        self.assertIn("PENDING, not OPEN", str(caught.exception))

    def test_a_not_in_force_disposition_cannot_carry_a_live_effective_status(self):
        with self.assertRaises(ResolutionError) as caught:
            self._disposition(
                resolution_state=ResolutionState.PENDING,
                review_status=ReviewStatus.PROPOSED,
            )
        self.assertIn("must be UNRESOLVED", str(caught.exception))

    def test_unresolved_can_never_be_effective(self):
        """UNRESOLVED is the absence of a disposition, not a destination."""
        with self.assertRaises(ResolutionError):
            self._disposition(
                proposed_status=MappingStatus.UNRESOLVED,
                effective_status=MappingStatus.UNRESOLVED,
            )

    def test_the_gate_maps_every_review_status_correctly(self):
        """Spec section 5.4, over the pinned registry rather than a fixture."""
        registry = load_scope_rules()
        for rule in registry.rules:
            disposition = track_a_disposition(rule)
            self.assertIs(disposition.proposed_status, rule.final_status)
            if rule.final_status is MappingStatus.UNRESOLVED:
                self.assertIs(disposition.resolution_state, ResolutionState.OPEN)
            elif rule.is_applicable:
                self.assertIs(disposition.resolution_state, ResolutionState.EFFECTIVE)
                self.assertIs(disposition.effective_status, rule.final_status)
            else:
                self.assertIs(disposition.resolution_state, ResolutionState.PENDING)
                self.assertIs(disposition.effective_status, MappingStatus.UNRESOLVED)

    def test_no_status_is_effective_without_an_applicable_accepted_rule(self):
        """The converse, stated as its own claim.

        Iterating the registry and checking each rule's mapping is not the same
        as checking that nothing else can become effective. This asserts the
        second: an effective disposition implies an applicable ACCEPTED rule.
        """
        registry = load_scope_rules()
        effective = [r for r in registry.rules if track_a_disposition(r).is_effective]
        self.assertTrue(effective, "the fixture must exercise at least one live rule")
        for rule in effective:
            self.assertIs(rule.review_status, ReviewStatus.ACCEPTED)
            self.assertTrue(rule.is_applicable)
        for rule in registry.rules:
            if rule.review_status is not ReviewStatus.ACCEPTED:
                self.assertFalse(
                    track_a_disposition(rule).is_effective,
                    f"{rule.rule_id} is {rule.review_status.value} yet in force",
                )

    def test_final_status_is_only_read_through_the_disposition_gate(self):
        """No second code path may promote ``final_status`` to an effective one.

        The invariants above constrain :class:`TrackADisposition`, but they say
        nothing about a caller that bypasses it. The defect was exactly such a
        bypass, so this parses the module and requires every read of
        ``rule.final_status`` to sit inside ``track_a_disposition``, which cannot
        return an effective status without consulting the review state.
        """
        tree = ast.parse(self.RESOLUTION_SOURCE.read_text(encoding="utf-8"))
        gate = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "track_a_disposition"
        )
        inside_gate = {
            id(node)
            for node in ast.walk(gate)
            if isinstance(node, ast.Attribute) and node.attr == "final_status"
        }
        self.assertTrue(inside_gate, "the gate no longer reads final_status at all")

        stray = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr == "final_status"
            and id(node) not in inside_gate
        ]
        self.assertEqual(
            [],
            [f"line {node.lineno}" for node in stray],
            "final_status is read outside track_a_disposition; an effective "
            "status may only be derived where the review status is checked",
        )

    def test_the_resolution_row_exposes_no_ambiguous_status_field(self):
        """The old name is gone, not merely deprecated.

        ``m2_track_a_status`` never said whose claim it carried. Leaving it in
        place as an alias would let existing consumers keep reading a proposed
        status as an effective one, which is the whole defect.
        """
        self.assertNotIn("m2_track_a_status", RESOLUTION_CSV_COLUMNS)
        for field in (
            "proposed_track_a_status",
            "effective_track_a_status",
            "review_status",
            "resolution_state",
        ):
            self.assertIn(field, RESOLUTION_CSV_COLUMNS)


@unittest.skipUnless(
    external_sources_available(),
    "Authoritative BLS CE extracts are not present; see the research README.",
)
class TestResolution(unittest.TestCase):
    """Spec sections 16, 18 and 19 against the authoritative extracts."""

    @classmethod
    def setUpClass(cls):
        cls.audit = run_audit(
            series_path=EXTERNAL_SOURCES["series"],
            data_path=EXTERNAL_SOURCES["data"],
            items_path=EXTERNAL_SOURCES["items"],
            aspects_path=EXTERNAL_SOURCES["aspects"],
        )
        cls.registry = load_scope_rules()
        cls.resolution = build_resolution(
            basis=cls.audit.basis,
            mappings=cls.audit.mappings,
            registry=cls.registry,
        )

    def test_resolves_every_milestone_1_exception(self):
        self.assertEqual(len(self.resolution.rows), EXPECTED_EXCEPTION_COUNT)
        exceptions = {
            m.ucc
            for m in self.audit.mappings
            if m.status is MappingStatus.UNRESOLVED
        }
        self.assertEqual({row.ucc for row in self.resolution.rows}, exceptions)

    def test_output_columns_match_the_specification(self):
        self.assertEqual(
            RESOLUTION_CSV_COLUMNS,
            (
                "ucc",
                "label",
                "domain",
                "all_cu_expenditure",
                "q1_expenditure",
                "q2_expenditure",
                "q3_expenditure",
                "q4_expenditure",
                "q5_expenditure",
                "m1_status",
                "proposed_track_a_status",
                "effective_track_a_status",
                "review_status",
                "resolution_state",
                "track_a_rule_id",
                "track_a_node",
                "track_b_treatment",
                "evidence_strength",
                "suppression_status",
                "notes",
            ),
        )
        for row in self.resolution.rows:
            self.assertEqual(len(row.as_csv_row()), len(RESOLUTION_CSV_COLUMNS))

    def test_milestone_1_status_is_preserved(self):
        """Section 18: the Milestone-1 ledger stays a historical artifact."""
        for row in self.resolution.rows:
            self.assertIs(row.m1_status, MappingStatus.UNRESOLVED)

    def test_no_expenditure_disappears(self):
        """Section 19.1, in every population."""
        self.assertEqual(len(self.resolution.reconciliations), len(POPULATIONS))
        for recon in self.resolution.reconciliations:
            self.assertAlmostEqual(
                recon.residual,
                0.0,
                places=6,
                msg=f"{recon.population} loses {recon.residual} of expenditure",
            )

    def test_all_cu_basis_matches_milestone_1(self):
        recon = next(
            r for r in self.resolution.reconciliations if r.population == ALL_CU
        )
        self.assertAlmostEqual(recon.ce_observed_basis, EXPECTED_ALL_CU_BASIS, places=1)

    def test_exception_expenditure_matches_milestone_1(self):
        recon = next(
            r for r in self.resolution.reconciliations if r.population == ALL_CU
        )
        # Every bucket except ``retained`` holds exception expenditure, and only
        # exception expenditure. Summing the four is the same claim the old
        # three-bucket sum made, now that pending shelter rules are carried
        # separately instead of being folded into an accepted bucket.
        exception_total = sum(
            getattr(recon, bucket)
            for bucket in RECONCILIATION_BUCKETS
            if bucket != "retained"
        )
        self.assertAlmostEqual(exception_total, EXPECTED_EXCEPTION_ALL_CU, places=1)

    def test_suppressed_cells_are_blank_not_zero(self):
        """Section 16: no suppressed observation may be coerced to zero."""
        suppressed = 0
        for row in self.resolution.rows:
            csv_row = row.as_csv_row()
            for offset, population in enumerate(POPULATIONS):
                cell = csv_row[3 + offset]
                if row.expenditure_by_population[population] is None:
                    suppressed += 1
                    self.assertEqual(cell, "", f"{row.ucc}/{population}")
                else:
                    self.assertNotEqual(cell, "", f"{row.ucc}/{population}")
        self.assertGreater(
            suppressed, 0, "the fixture must actually exercise suppression"
        )

    def test_declared_suppression_status_is_reproduced(self):
        """The registry declares; the computation verifies."""
        for rule_id, exposure in self.resolution.rule_exposure.items():
            self.assertIs(
                self.registry.rule_by_id(rule_id).suppression_status,
                exposure.status,
                f"{rule_id} declares a suppression status the data do not support",
            )

    def test_rules_without_suppressed_members_are_none(self):
        for rule_id, exposure in self.resolution.rule_exposure.items():
            if not exposure.suppressed_cells:
                self.assertIs(exposure.status, SuppressionStatus.NONE, rule_id)

    def test_suppression_is_bounded_from_published_parents(self):
        for recon in self.resolution.reconciliations:
            self.assertGreater(recon.suppressed_leaf_count, 0)
            self.assertLess(
                recon.suppressed_upper_bound_pct_of_basis,
                0.05,
                f"{recon.population} suppression is no longer negligible",
            )

    def test_replacement_accounting_is_reported_separately(self):
        """Section 19.2: removed and replacement amounts are distinct."""
        report = self.resolution.replacement_accounting
        self.assertIn("RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1", report)
        block = report["RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1"]
        self.assertGreater(
            block["removed_owner_outlay"][ALL_CU]["observed_removed_expenditure"], 0.0
        )
        self.assertIsNone(
            block["replacement_expenditure"],
            "the replacement amount must stay unset until the Track-A shelter "
            "rule and its PUMD benchmark validation are complete",
        )
        self.assertEqual(block["status"], "PENDING")

    def test_no_index_or_weights_are_produced(self):
        summary = self.resolution.summary
        self.assertFalse(summary["index_computed"])
        self.assertFalse(summary["weights_normalized"])
        self.assertEqual(summary["core_dmi"], "WITHDRAWN_AND_UNIMPLEMENTED")

    def test_registry_must_claim_exactly_the_exception_set(self):
        """Substituting a UCC keeps the registry internally consistent but
        no longer covers the Milestone-1 exception set, which must be fatal."""

        def mutate(payload):
            rule = payload["rules"][0]
            rule["source_uccs"][0] = "199999"
            rule["output_uccs"][0] = "199999"
            rule["output_node"]["199999"] = rule["output_node"].pop("190903")

        path = _mutated_registry(mutate)
        try:
            registry = load_scope_rules(path)  # must still load cleanly
            self.assertIn("199999", registry.covered_uccs)
            with self.assertRaises(ResolutionError) as caught:
                build_resolution(
                    basis=self.audit.basis,
                    mappings=self.audit.mappings,
                    registry=registry,
                )
            self.assertIn("199999", str(caught.exception))
            self.assertIn("190903", str(caught.exception))
        finally:
            path.unlink()

    def test_refuses_to_write_into_operational_outputs(self):
        for forbidden in ("data/outputs/milestone_2", "deploy/data/outputs"):
            with self.assertRaises(ResearchFirewallError):
                write_artifacts(self.resolution, self.registry, Path(forbidden))


@unittest.skipUnless(
    external_sources_available(),
    "Authoritative BLS CE extracts are not present; see the research README.",
)
class TestProposedDispositionsDoNotEnterTheAccounting(unittest.TestCase):
    """Section 19.1 over the pinned extracts, on the effective statuses only.

    The four shelter-coupled rules propose to exclude or transform roughly a
    sixth of the detailed basis. Until their PUMD prerequisite is met, none of
    that may appear as an accepted exclusion or an accepted transformation.
    """

    @classmethod
    def setUpClass(cls):
        cls.audit = run_audit(
            series_path=EXTERNAL_SOURCES["series"],
            data_path=EXTERNAL_SOURCES["data"],
            items_path=EXTERNAL_SOURCES["items"],
            aspects_path=EXTERNAL_SOURCES["aspects"],
        )
        cls.registry = load_scope_rules()
        cls.resolution = build_resolution(
            basis=cls.audit.basis,
            mappings=cls.audit.mappings,
            registry=cls.registry,
        )
        cls.all_cu = next(
            r for r in cls.resolution.reconciliations if r.population == ALL_CU
        )

    def _observed(self, rows, population=ALL_CU):
        return sum(
            row.expenditure_by_population[population] or 0.0
            for row in rows
        )

    def _rows_of(self, rule_id):
        return [r for r in self.resolution.rows if r.track_a_rule_id == rule_id]

    def test_every_row_states_both_claims(self):
        for row in self.resolution.rows:
            rule = self.registry.rule_by_id(row.track_a_rule_id)
            self.assertIs(row.proposed_track_a_status, rule.final_status)
            self.assertEqual(row.review_status, rule.review_status.value)
            if rule.is_applicable and rule.final_status is not MappingStatus.UNRESOLVED:
                self.assertIs(row.effective_track_a_status, rule.final_status)
                self.assertIs(row.resolution_state, ResolutionState.EFFECTIVE)
            else:
                self.assertIs(
                    row.effective_track_a_status,
                    MappingStatus.UNRESOLVED,
                    f"{row.ucc} is governed by a rule that is not in force",
                )

    def test_proposed_shelter_rules_are_pending_not_accepted(self):
        """The defect, at the row level, over every affected UCC."""
        proposed = [
            r
            for r in self.registry.rules
            if r.review_status is ReviewStatus.PROPOSED
        ]
        self.assertEqual(len(proposed), 4, "the four shelter rules are the fixture")
        for rule in proposed:
            for row in self._rows_of(rule.rule_id):
                self.assertIs(row.resolution_state, ResolutionState.PENDING)
                self.assertIsNot(
                    row.effective_track_a_status, MappingStatus.OUT_OF_SCOPE
                )
                self.assertIsNot(
                    row.effective_track_a_status, MappingStatus.TRANSFORMED
                )

    def test_pending_and_open_are_distinguished(self):
        """A blocked disposition and an absent one are different facts."""
        pending = {
            r.ucc for r in self.resolution.rows
            if r.resolution_state is ResolutionState.PENDING
        }
        open_rows = {
            r.ucc for r in self.resolution.rows
            if r.resolution_state is ResolutionState.OPEN
        }
        self.assertEqual(pending & open_rows, set())
        self.assertTrue(pending, "the fixture must exercise the pending bucket")
        self.assertTrue(open_rows, "the fixture must exercise the open bucket")
        for ucc in open_rows:
            rule = self.registry.rule_for(ucc)
            self.assertIs(rule.final_status, MappingStatus.UNRESOLVED)
        for ucc in pending:
            rule = self.registry.rule_for(ucc)
            self.assertIsNot(rule.final_status, MappingStatus.UNRESOLVED)

    def test_five_buckets_reconcile_in_every_population(self):
        """The accounting identity, restated over the corrected buckets."""
        self.assertEqual(len(self.resolution.reconciliations), len(POPULATIONS))
        for recon in self.resolution.reconciliations:
            self.assertAlmostEqual(
                recon.sum_of_buckets,
                recon.ce_observed_basis,
                places=6,
                msg=f"{recon.population} does not reconcile",
            )
            self.assertAlmostEqual(recon.residual, 0.0, places=6)

    def test_each_bucket_holds_exactly_its_rows(self):
        """Bucket totals are not free parameters.

        Each is reproduced here from the rows themselves, so a bucket cannot be
        made to balance by moving expenditure into the wrong one.
        """
        expected = {
            "accepted_transformed": [
                r for r in self.resolution.rows
                if r.resolution_state is ResolutionState.EFFECTIVE
                and r.effective_track_a_status is MappingStatus.TRANSFORMED
            ],
            "accepted_out_of_scope": [
                r for r in self.resolution.rows
                if r.resolution_state is ResolutionState.EFFECTIVE
                and r.effective_track_a_status is MappingStatus.OUT_OF_SCOPE
            ],
            "pending_proposed": [
                r for r in self.resolution.rows
                if r.resolution_state is ResolutionState.PENDING
            ],
            "unresolved_open": [
                r for r in self.resolution.rows
                if r.resolution_state is ResolutionState.OPEN
            ],
        }
        for population in POPULATIONS:
            recon = next(
                r for r in self.resolution.reconciliations if r.population == population
            )
            for bucket, rows in expected.items():
                self.assertAlmostEqual(
                    getattr(recon, bucket),
                    self._observed(rows, population),
                    places=6,
                    msg=f"{population}/{bucket}",
                )

    def test_accepted_buckets_exclude_all_proposed_expenditure(self):
        """The literal claim: what is proposed is not counted as accepted.

        The three PROPOSED exclusion rules argue for a large exclusion. The
        accepted out-of-scope total must equal the ACCEPTED exclusions alone,
        with none of that argued amount folded in.
        """
        accepted_exclusions = [
            row
            for rule in self.registry.rules
            if rule.is_applicable and rule.final_status is MappingStatus.OUT_OF_SCOPE
            for row in self._rows_of(rule.rule_id)
        ]
        self.assertAlmostEqual(
            self.all_cu.accepted_out_of_scope,
            self._observed(accepted_exclusions),
            places=6,
        )
        proposed_exclusions = [
            row
            for rule in self.registry.rules
            if not rule.is_applicable
            and rule.final_status is MappingStatus.OUT_OF_SCOPE
            for row in self._rows_of(rule.rule_id)
        ]
        argued = self._observed(proposed_exclusions)
        self.assertGreater(argued, 0.0, "the fixture must exercise a proposed exclusion")
        self.assertAlmostEqual(
            self.all_cu.pending_proposed - argued,
            self._observed(
                [
                    row
                    for rule in self.registry.rules
                    if not rule.is_applicable
                    and rule.final_status is MappingStatus.TRANSFORMED
                    for row in self._rows_of(rule.rule_id)
                ]
            ),
            places=6,
        )

    def test_pending_expenditure_is_material_and_reported(self):
        """A pending bucket that were empty would prove nothing.

        The point of the correction is that the pending share is large: it must
        be visible in the artifact rather than absorbed into accepted buckets.
        """
        self.assertGreater(
            self.all_cu.pct_of_basis("pending_proposed"),
            self.all_cu.pct_of_basis("accepted_transformed")
            + self.all_cu.pct_of_basis("accepted_out_of_scope"),
            "the pending share is larger than the effective one; if this ever "
            "reverses, check that the shelter rules were legitimately accepted",
        )

    def test_headline_is_arithmetically_consistent_with_the_reconciliation(self):
        headline = self.resolution.summary["headline"]
        for recon in self.resolution.reconciliations:
            entry = headline["by_population"][recon.population]
            self.assertAlmostEqual(
                entry["ce_observed_basis"], round(recon.ce_observed_basis, 1), places=1
            )
            for bucket in RECONCILIATION_BUCKETS:
                if bucket == "retained":
                    self.assertNotIn(bucket, entry)
                    continue
                self.assertAlmostEqual(
                    entry[bucket]["expenditure"], round(getattr(recon, bucket), 1),
                    places=1,
                )
            # The four derived quantities must be the sums they claim to be.
            self.assertAlmostEqual(
                entry["effective_now"]["expenditure"],
                entry["accepted_transformed"]["expenditure"]
                + entry["accepted_out_of_scope"]["expenditure"],
                places=1,
            )
            self.assertAlmostEqual(
                entry["with_a_proposed_disposition"]["expenditure"],
                entry["effective_now"]["expenditure"]
                + entry["pending_proposed"]["expenditure"],
                places=1,
            )
            self.assertAlmostEqual(
                entry["milestone_1_unexplained"]["expenditure"],
                entry["with_a_proposed_disposition"]["expenditure"]
                + entry["unresolved_open"]["expenditure"],
                places=1,
            )

    def test_headline_does_not_claim_the_gap_is_closed(self):
        """Section 2 prose must not read the open share as the whole remainder.

        Reporting only the fall from 19.4052% to 0.1602% would imply Track A is
        settled. The statement has to name the pending share in the same breath.
        """
        statement = self.resolution.summary["headline"]["statement"]
        all_cu = self.resolution.summary["headline"]["by_population"][ALL_CU]
        pending = all_cu["pending_proposed"]["pct_of_basis"]
        self.assertIn(f"{pending:.4f}%", statement)
        self.assertIn("not yet effective", statement)
        self.assertIn(
            f"{all_cu['unresolved_open']['pct_of_basis']:.4f}%", statement
        )
        self.assertIn(
            f"{all_cu['milestone_1_unexplained']['pct_of_basis']:.4f}%", statement
        )

    def test_summary_reports_proposed_and_effective_counts_separately(self):
        summary = self.resolution.summary
        self.assertNotIn("track_a_status_counts", summary)
        proposed = summary["track_a_proposed_status_counts"]
        effective = summary["track_a_effective_status_counts"]
        states = summary["resolution_state_counts"]
        self.assertEqual(sum(proposed.values()), EXPECTED_EXCEPTION_COUNT)
        self.assertEqual(sum(effective.values()), EXPECTED_EXCEPTION_COUNT)
        self.assertEqual(sum(states.values()), EXPECTED_EXCEPTION_COUNT)
        # If the two count sets were identical the distinction would be vacuous.
        self.assertNotEqual(proposed, effective)
        self.assertEqual(
            effective["UNRESOLVED"],
            states["PENDING"] + states["OPEN"],
            "everything not in force must read as UNRESOLVED in effect",
        )

    def test_replacement_accounting_agrees_with_the_effective_model(self):
        """Section 19.2 may not report a removal that has not happened."""
        block = self.resolution.replacement_accounting[
            "RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1"
        ]
        self.assertEqual(block["status"], ResolutionState.PENDING.value)
        self.assertEqual(block["review_status"], ReviewStatus.PROPOSED.value)
        self.assertEqual(block["proposed_track_a_status"], "TRANSFORMED")
        self.assertEqual(block["effective_track_a_status"], "UNRESOLVED")
        self.assertIsNone(block["replacement_expenditure"])
        self.assertTrue(block["removed_outlay_is_still_in_the_basis"])
        # And the outlay it describes is genuinely still counted, in pending.
        removed = block["removed_owner_outlay"][ALL_CU][
            "observed_removed_expenditure"
        ]
        rows = self._rows_of("RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1")
        self.assertAlmostEqual(removed, self._observed(rows), places=1)
        self.assertLessEqual(removed, self.all_cu.pending_proposed + 1e-6)

    def test_unresolved_ledger_lists_open_rows_only(self):
        """A pending shelter UCC is not a research lead.

        Its effective status is UNRESOLVED too, so a ledger keyed on the
        effective status alone would silently grow from the 11 genuinely
        undecided codes to all 44 not in force.
        """
        with tempfile.TemporaryDirectory() as tmp:
            written = write_artifacts(
                self.resolution, self.registry, Path(tmp) / "research"
            )
            ledger = next(p for p in written if p.name.startswith("unresolved_ledger"))
            with ledger.open(encoding="utf-8") as handle:
                uccs = [row["ucc"] for row in csv.DictReader(handle)]
        self.assertEqual(
            sorted(uccs),
            sorted(
                r.ucc
                for r in self.resolution.rows
                if r.resolution_state is ResolutionState.OPEN
            ),
        )
        self.assertNotIn(
            "220311",
            uccs,
            "a pending shelter UCC must not be listed as an open research lead",
        )

    def test_making_an_accepted_exclusion_proposed_moves_it_out_of_accepted(self):
        """Mutation test: the accounting must be sensitive to review status.

        Under the original defect this assertion was unreachable, because
        ``rule.final_status`` was written into the accounting whatever the review
        status said. Flipping one ACCEPTED exclusion to PROPOSED must move its
        expenditure from ``accepted_out_of_scope`` into ``pending_proposed``,
        leaving the basis untouched.
        """
        target = "OS_CPI_CAPITAL_IMPROVEMENT_v0_1"
        baseline = self._observed(self._rows_of(target))
        self.assertGreater(baseline, 0.0)

        def mutate(payload):
            for rule in payload["rules"]:
                if rule["rule_id"] == target:
                    rule["review_status"] = "PROPOSED"
                    rule["review_blocker"] = (
                        "synthetic blocker introduced by the mutation test"
                    )
                    return
            raise AssertionError(f"{target} is no longer in the registry")

        path = _mutated_registry(mutate)
        try:
            mutated = build_resolution(
                basis=self.audit.basis,
                mappings=self.audit.mappings,
                registry=load_scope_rules(path),
            )
        finally:
            path.unlink()

        after = next(r for r in mutated.reconciliations if r.population == ALL_CU)
        self.assertAlmostEqual(
            after.accepted_out_of_scope,
            self.all_cu.accepted_out_of_scope - baseline,
            places=6,
            msg="a PROPOSED rule is still being counted as an accepted exclusion",
        )
        self.assertAlmostEqual(
            after.pending_proposed,
            self.all_cu.pending_proposed + baseline,
            places=6,
        )
        self.assertAlmostEqual(after.residual, 0.0, places=6)
        self.assertAlmostEqual(
            after.ce_observed_basis, self.all_cu.ce_observed_basis, places=6
        )
        # The rule still argues for exclusion; only its force has changed.
        for row in mutated.rows:
            if row.track_a_rule_id == target:
                self.assertIs(row.proposed_track_a_status, MappingStatus.OUT_OF_SCOPE)
                self.assertIs(row.resolution_state, ResolutionState.PENDING)


if __name__ == "__main__":
    unittest.main()
