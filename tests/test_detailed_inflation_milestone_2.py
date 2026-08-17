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

import json
import tempfile
import unittest
from pathlib import Path

from tests.detailed_inflation_fixtures import (
    EXTERNAL_SOURCES,
    external_sources_available,
)

from dmi_research.detailed_inflation.audit import ResearchFirewallError, run_audit
from dmi_research.detailed_inflation.basis import Basis, ReconciliationResult
from dmi_research.detailed_inflation.concordance import load_concordance
from dmi_research.detailed_inflation.resolution import (
    ALL_CU,
    POPULATIONS,
    RESOLUTION_CSV_COLUMNS,
    ResolutionError,
    build_resolution,
    build_suppression_bounds,
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
)
from dmi_research.detailed_inflation.taxonomy import (
    MappingStatus,
    load_eli_resolver,
    load_taxonomy,
)

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
        def mutate(payload):
            payload["rules"][1]["source_uccs"].append(
                payload["rules"][0]["source_uccs"][0]
            )

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
                "m2_track_a_status",
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
        exception_total = recon.transformed + recon.out_of_scope + recon.unresolved
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


if __name__ == "__main__":
    unittest.main()
