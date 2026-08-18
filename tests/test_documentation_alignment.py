#!/usr/bin/env python3
"""Regression coverage for documentation-alignment invariants (§12).

Active documentation must not silently regress into contradicting the
shipped v0.1.12 reality (two operational specifications, no Core, no
auto-merge, no retired endpoints). This test file freezes the specific
claims that were repaired in §12 so a well-meaning future edit that
adds "Core" back to a workflow description, or reintroduces
`dmi_timeseries_2010_2024.json` as an operational endpoint, fails at
CI time.

Scope: only the docs that describe *current operational behaviour*.
Design docs (`DMI_v0.1_PDD.md`, `DMI_v0.1_Implementation_Spec.md`) are
allowed to describe the original three-spec design as long as they
carry a v0.1.12 status banner.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestOperationalDocsMatchShippedReality(unittest.TestCase):

    def _read(self, rel: str) -> str:
        return (ROOT / rel).read_text()

    def test_release_calendar_does_not_claim_core_computation(self):
        text = self._read("docs/RELEASE_CALENDAR.md")
        self.assertNotIn(
            "baseline, slack-plus, core", text,
            "§12: RELEASE_CALENDAR must not list Core as an active spec.",
        )
        self.assertNotIn(
            "baseline / slack-plus / core", text,
            "§12: RELEASE_CALENDAR must not list Core in the pipeline description.",
        )

    def test_release_calendar_does_not_claim_auto_merge(self):
        text = self._read("docs/RELEASE_CALENDAR.md")
        # "auto-merge" MAY appear in the negative form (e.g. "auto-merge
        # was removed" / "auto-merge currently disabled"), but the bare
        # affirmative claim "auto-merges it on success" must be gone.
        self.assertNotIn(
            "auto-merges it on success", text,
            "§12: RELEASE_CALENDAR must not claim the pipeline auto-merges.",
        )

    def test_deployment_workflows_does_not_claim_core_computation(self):
        text = self._read("docs/deployment-workflows.md")
        # Reject the specific affirmative claim.
        self.assertNotIn(
            "**Baseline**, **Slack-Plus**, and **Core** specifications", text,
            "§12: deployment-workflows must not list Core as computed.",
        )
        self.assertNotIn(
            "Baseline / Slack-Plus / Core outputs", text,
            "§12: deployment-workflows must not list Core as an output type.",
        )

    def test_deployment_guide_uses_current_timeseries_path(self):
        text = self._read("docs/DEPLOYMENT_GUIDE.md")
        # The current Baseline-only timeseries path must be present.
        self.assertIn(
            "/data/outputs/published/dmi_timeseries.json", text,
            "§12: DEPLOYMENT_GUIDE must reference the current "
            "Baseline-only timeseries path.",
        )

    def test_design_docs_carry_v0112_status_banner(self):
        # These are design documents that legitimately describe the
        # original three-spec architecture, but they must warn the
        # reader up front that v0.1.12 diverges.
        for rel in (
            "docs/DMI_v0.1_PDD.md",
            "docs/DMI_v0.1_Implementation_Spec.md",
        ):
            text = self._read(rel)
            self.assertIn(
                "v0.1.12 STATUS BANNER", text,
                f"§12: {rel} must carry the v0.1.12 status banner.",
            )
            self.assertIn(
                "Core is withdrawn", text,
                f"§12: {rel} banner must state Core is withdrawn.",
            )

    def test_methodology_note_banner_covers_appendix_b(self):
        # The v0.1.12 status banner must warn readers that Appendix B's
        # historical-backfill recipes are not carried forward.
        text = self._read("docs/DMI_Methodology_Note.md")
        self.assertIn("Appendix B", text)
        self.assertIn("dmi_timeseries_2010_2024.json", text)
        # And the current Baseline-only path must appear somewhere in
        # the doc so a reader following the appendix has the correct
        # forward reference.
        self.assertIn(
            "data/outputs/published/dmi_timeseries.json", text,
            "§12: methodology note must reference the current "
            "Baseline-only timeseries path.",
        )


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Round-3 §12 / §13 / §14: documentation must not present withdrawn work as
# operational, and status records must not carry superseded claims.
#
# §12 is explicit that "the status banner alone is insufficient because the
# body still presents the withdrawn construction and results as usable".
# The tests above check that banners EXIST. These check the body.
# ---------------------------------------------------------------------------

import json as _json
import re as _re

METHODOLOGY = ROOT / "docs" / "DMI_Methodology_Note.md"
AUDIT = ROOT / "docs" / "repair" / "V0.1.12_ALIGNMENT_AUDIT.md"
PR_DRAFT = ROOT / "docs" / "repair" / "PR_BODY_DRAFT.md"
CORE_WITHDRAWAL = ROOT / "docs" / "repair" / "CORE_WITHDRAWAL.md"
DMI_OUTPUT_SCHEMA = ROOT / "schemas" / "dmi_output.schema.json"


class TestMethodologyNoteBodyDoesNotPresentCoreAsCurrent(unittest.TestCase):
    """§12: active prose must not present the withdrawn Core as usable."""

    @classmethod
    def setUpClass(cls):
        cls.text = METHODOLOGY.read_text()

    def test_data_dictionary_lists_only_current_specification_values(self):
        """§12: `CORE_CPI` must not appear as a current specification value.

        The Appendix A data dictionary is a reference table with no
        historical framing, so anything listed there reads as current. Its
        `specification` row is pinned against the shipped schema enum.
        """
        schema = _json.loads(DMI_OUTPUT_SCHEMA.read_text())
        enum = schema["properties"]["specification"]["enum"]
        allowed = {v for v in enum if isinstance(v, str)}
        self.assertEqual(
            allowed, {"baseline", "slack_plus"},
            "schema enum changed; update this test deliberately",
        )

        row = next(
            (line for line in self.text.splitlines()
             if line.startswith("| `specification`")),
            None,
        )
        self.assertIsNotNone(
            row, "Appendix A specification row not found"
        )
        # The example column must not offer a withdrawn/renamed value.
        example_col = row.rsplit("|", 2)[-2]
        self.assertNotIn(
            "CORE_CPI", example_col,
            "§12: CORE_CPI must not be offered as a current "
            "specification value.",
        )
        self.assertIn("baseline", example_col)
        self.assertIn("slack_plus", example_col)

    def test_no_active_recipe_generates_retired_outputs(self):
        """§12: must not instruct readers to generate retired outputs."""
        offenders = []
        for lineno, line in enumerate(self.text.splitlines(), 1):
            stripped = line.strip()
            # Only executable recipe lines, not prose naming the retired
            # entry points in order to say they are retired.
            if not stripped.startswith("./venv/bin/python") and \
                    not stripped.startswith("python -m"):
                continue
            for retired in ("compute_dmi_with_ci", "compute_dmi_core",
                            "compute_dmi_u6"):
                if retired in stripped:
                    offenders.append(f"line {lineno}: {stripped}")
        self.assertEqual(
            offenders, [],
            f"§12: the note must not instruct readers to run retired "
            f"generators: {offenders}",
        )

    def test_confidence_intervals_are_not_claimed_as_current_contract(self):
        """§12: CIs must not be presented as part of the v0.1.12 contract."""
        # Every mention of confidence intervals in a heading must carry a
        # disclaimer nearby.
        lines = self.text.splitlines()
        offenders = []
        for i, line in enumerate(lines):
            if not line.startswith("#"):
                continue
            if "confidence interval" not in line.lower():
                continue
            window = " ".join(lines[i:i + 8]).lower()
            if not any(marker in window for marker in (
                "not part of", "not available", "withdrawn", "retired",
                "not re-validated", "historical",
            )):
                offenders.append(line.strip())
        self.assertEqual(
            offenders, [],
            f"§12: confidence-interval section(s) lack a v0.1.12 "
            f"disclaimer: {offenders}",
        )

    def test_latest_with_ci_is_never_described_as_emitted(self):
        """§7/§12: the note must not describe latest_with_ci as live.

        The note previously stated latest_with_ci "is emitted only when a
        _with_ci.json happens to exist", which became false when §7
        retired the key.
        """
        for phrase in (
            "`latest_with_ci` is emitted",
            "latest_with_ci is emitted",
        ):
            self.assertNotIn(
                phrase, self.text,
                f"§7/§12: {phrase!r} is no longer true; the endpoint is "
                f"retired.",
            )

    def test_core_section_body_is_labelled_historical(self):
        """§12: retained legacy results must sit in a labelled section."""
        idx = self.text.find("### 5.2 Core CPI Alternative")
        self.assertGreater(idx, 0, "§5.2 not found")
        # The withdrawal banner must precede the numeric results.
        results_idx = self.text.find("**Results (Nov 2024)**", idx)
        self.assertGreater(results_idx, idx)
        banner = self.text[idx:results_idx]
        self.assertIn(
            "WITHDRAWN", banner,
            "§12: the food-only result must be preceded by an "
            "unmistakable withdrawal label.",
        )
        self.assertIn("historical", banner.lower())

    def test_core_is_not_recommended_as_a_sensitivity_analysis(self):
        """§12: no active prose recommends Core as operational."""
        # A "When to Use" heading with no historical qualifier would read
        # as a live recommendation.
        for match in _re.finditer(r"\*\*When to Use\*\*", self.text):
            start = max(0, match.start() - 1200)
            window = self.text[start:match.start()]
            if "Core" not in window:
                continue
            self.fail(
                "§12: an unqualified '**When to Use**' block follows Core "
                "discussion; it must be framed historically."
            )

    def test_future_core_matches_the_concept_note_definition(self):
        """§12: future Core must state food AND energy, and finer mapping."""
        idx = self.text.find("**2. Distribution-aware Core**")
        self.assertGreater(idx, 0, "Future Work Core item not found")
        block = self.text[idx:idx + 1400].lower()
        self.assertIn(
            "energy", block,
            "§12: future Core discussion must state energy exclusion.",
        )
        self.assertIn(
            "finer", block,
            "§12: future Core discussion must state that a finer mapping "
            "is required.",
        )
        self.assertTrue(
            "unimplemented" in block or "not scheduled" in block,
            "§12: future Core must be marked unimplemented/unscheduled.",
        )


class TestCoreWithdrawalRationaleIsComplete(unittest.TestCase):
    """§11: the rationale document must state each required point."""

    @classmethod
    def setUpClass(cls):
        cls.text = CORE_WITHDRAWAL.read_text()
        cls.lower = cls.text.lower()

    def test_document_exists_and_is_distinct_from_the_evidence_record(self):
        self.assertTrue(CORE_WITHDRAWAL.is_file())
        evidence = ROOT / "docs" / "known-issues" / "CORE_OUTPUT_WITHDRAWAL.md"
        self.assertTrue(evidence.is_file())
        self.assertNotEqual(
            CORE_WITHDRAWAL.read_text(), evidence.read_text(),
            "§11: the rationale must be a distinct document.",
        )

    def test_states_what_was_withdrawn(self):
        self.assertIn("what was withdrawn", self.lower)
        self.assertIn("_core.json", self.lower)

    def test_states_why_the_former_implementation_was_invalid(self):
        self.assertIn("byte-identical", self.lower)

    def test_states_food_excluded_but_not_all_energy(self):
        """§11: 'that it excluded food but not all energy'."""
        self.assertIn(
            "excluded food, but not all energy", self.lower,
            "§11: the document must state that the former construction "
            "excluded food but not all energy.",
        )

    def test_states_eight_category_mapping_cannot_implement_core(self):
        """§11: 'the eight-category mapping cannot implement the intended
        definition'."""
        self.assertIn(
            "eight-category mapping cannot implement", self.lower,
            "§11: the document must state that the eight-category "
            "mapping cannot implement the intended definition.",
        )

    def test_states_core_remains_intended_not_operational(self):
        self.assertIn("intended work, not", self.lower)
        self.assertIn("non-operational", self.lower)
        self.assertIn("unvalidated", self.lower)
        self.assertIn("unimplemented", self.lower)

    def test_states_work_required_before_core_returns(self):
        self.assertIn("work required before core can return", self.lower)
        self.assertIn("finer-grained cpi components", self.lower)

    def test_states_outputs_must_not_be_reinterpreted_or_renamed(self):
        self.assertIn("not renamed", self.lower)

    def test_points_at_the_evidence_record_and_remote_procedure(self):
        self.assertIn("CORE_OUTPUT_WITHDRAWAL.md", self.text)
        self.assertIn("REMOTE_WITHDRAWAL.md", self.text)

    def test_distinguishes_u6_and_with_ci_as_not_core(self):
        """Controlling decision: U-6 / with-CI are not Core."""
        self.assertIn("are **not** core outputs", self.lower)
        self.assertIn("quarantine", self.lower)

    def test_eight_categories_listed_match_the_actual_mapping(self):
        """A stated category list that drifts from the data is a new defect."""
        weights = _json.loads(
            (ROOT / "data" / "curated"
             / "weights_by_group_latest.json").read_text()
        )
        actual = sorted({r["category_id"] for r in weights["rows"]})
        self.assertEqual(
            len(actual), 8,
            "the mapping no longer has eight categories; the rationale "
            "document's claim must be revisited deliberately.",
        )
        for category in actual:
            with self.subTest(category=category):
                self.assertIn(
                    category, self.text,
                    f"§11: category {category} is in the mapping but not "
                    f"listed in the rationale document.",
                )


class TestStatusRecordsCarryNoSupersededClaims(unittest.TestCase):
    """§13: the audit and PR draft must not assert stale status."""

    @classmethod
    def setUpClass(cls):
        cls.audit = AUDIT.read_text()
        cls.draft = PR_DRAFT.read_text()

    def _current_claim_lines(self, text: str):
        """Lines that assert present-tense status, excluding round-scoped
        historical sections.

        Historical round summaries are legitimate; a superseded claim
        presented as the CURRENT expectation is not. Lines inside a
        block explicitly scoped to an earlier round are skipped.
        """
        out = []
        historical = False
        for lineno, line in enumerate(text.splitlines(), 1):
            low = line.lower()
            if low.startswith("#"):
                historical = bool(
                    _re.search(r"round[- ](1|2|one|two)\b", low)
                )
            out.append((lineno, line, historical))
        return out

    def test_no_document_claims_the_branch_is_unpushed(self):
        for name, text in (("audit", self.audit), ("draft", self.draft)):
            with self.subTest(doc=name):
                for phrase in (
                    "has not been pushed",
                    "not yet been pushed",
                    "not been pushed",
                    "branch is local only",
                ):
                    self.assertNotIn(
                        phrase, text.lower(),
                        f"§13: {name} must not claim the branch is "
                        f"unpushed.",
                    )

    def test_no_document_claims_the_live_site_is_updated(self):
        for name, text in (("audit", self.audit), ("draft", self.draft)):
            with self.subTest(doc=name):
                for phrase in (
                    "live site has been updated",
                    "live site is updated",
                    "deployed to production",
                    "deployment complete",
                    "site is live with",
                ):
                    self.assertNotIn(
                        phrase, text.lower(),
                        f"§13: {name} must not claim deployment "
                        f"occurred.",
                    )

    def test_no_document_claims_remote_withdrawal_occurred(self):
        for name, text in (("audit", self.audit), ("draft", self.draft)):
            with self.subTest(doc=name):
                for phrase in (
                    "remote withdrawal complete",
                    "remote artifacts have been deleted",
                    "core artifacts were deleted from the remote",
                    "withdrawal has been executed",
                ):
                    self.assertNotIn(
                        phrase, text.lower(),
                        f"§13: {name} must not claim remote withdrawal "
                        f"occurred.",
                    )

    def test_no_document_claims_a_tag_or_release_was_created(self):
        for name, text in (("audit", self.audit), ("draft", self.draft)):
            with self.subTest(doc=name):
                for phrase in (
                    "tag has been created",
                    "release has been published",
                    "github release created",
                ):
                    self.assertNotIn(
                        phrase, text.lower(),
                        f"§13: {name} must not claim tagging/publication.",
                    )

    def test_no_document_presents_46_tests_as_the_current_expectation(self):
        """§13: '46 tests are the current expected result' must be gone."""
        offenders = []
        for name, text in (("audit", self.audit), ("draft", self.draft)):
            for lineno, line, historical in self._current_claim_lines(text):
                if historical:
                    continue
                low = line.lower()
                if not _re.search(r"\b46\s+(passed|tests)", low):
                    continue
                # A line that explicitly frames 46 as a past round is fine.
                if _re.search(r"round[- ]?1|round[- ]?one|superseded|"
                              r"historical|at the time|previously", low):
                    continue
                offenders.append(f"{name}:{lineno}: {line.strip()}")
        self.assertEqual(
            offenders, [],
            f"§13: 46 tests must not be presented as the current expected "
            f"result: {offenders}",
        )

    def test_no_document_implies_all_manifests_share_schema_3_0_0(self):
        """§13: the version split must be stated, not flattened."""
        for name, text in (("audit", self.audit), ("draft", self.draft)):
            with self.subTest(doc=name):
                for phrase in (
                    "all manifests use schema 3.0.0",
                    "all manifests at 3.0.0",
                    "every manifest uses schema 3.0.0",
                    "all three manifests use schema 3.0.0",
                ):
                    self.assertNotIn(
                        phrase, text.lower(),
                        f"§13: {name} must not imply every manifest "
                        f"shares 3.0.0.",
                    )

    def test_version_split_is_stated_explicitly(self):
        """§13: releases/latest 3.0.0; specifications 0.3.0."""
        for name, text in (("audit", self.audit), ("draft", self.draft)):
            with self.subTest(doc=name):
                self.assertIn("3.0.0", text)
                self.assertIn(
                    "0.3.0", text,
                    f"§13: {name} must state the specifications.json "
                    f"contract version explicitly.",
                )

    def test_version_split_matches_the_shipped_manifests(self):
        """The documented split must equal reality."""
        outputs = ROOT / "data" / "outputs"
        self.assertEqual(
            _json.loads((outputs / "releases.json").read_text())
            ["schema_version"], "3.0.0",
        )
        self.assertEqual(
            _json.loads((outputs / "latest.json").read_text())
            ["schema_version"], "3.0.0",
        )
        self.assertEqual(
            _json.loads((outputs / "specifications.json").read_text())
            ["schema_version"], "0.3.0",
        )

    def test_no_document_describes_the_retired_shell_tool_as_current(self):
        """§13: withdraw_core_artifacts.sh no longer exists."""
        self.assertFalse(
            (ROOT / "scripts" / "withdraw_core_artifacts.sh").exists(),
            "the shell tool should be retired",
        )
        offenders = []
        for name, text in (("audit", self.audit), ("draft", self.draft)):
            for lineno, line, historical in self._current_claim_lines(text):
                if historical:
                    continue
                if "withdraw_core_artifacts.sh" not in line:
                    continue
                low = line.lower()
                if any(m in low for m in (
                    "retired", "replaced", "superseded", "removed",
                    "historical", "previously",
                )):
                    continue
                offenders.append(f"{name}:{lineno}: {line.strip()}")
        self.assertEqual(
            offenders, [],
            f"§13: the retired shell tool must not be described as the "
            f"current tool: {offenders}",
        )


class TestQuarantineIsDocumentedAndNotDeployable(unittest.TestCase):
    """§8: the quarantine must be labelled, and unreachable by any writer."""

    QUARANTINE = ROOT / "data" / "quarantine" / "pre_v0.1.12"
    LEGACY_FILES = (
        "dmi_release_2024-11_u6.json",
        "dmi_release_2024-11_with_ci.json",
    )

    @classmethod
    def setUpClass(cls):
        cls.readme = (cls.QUARANTINE / "README.md").read_text()
        cls.lower = cls.readme.lower()

    def test_the_two_files_are_quarantined_under_their_real_names(self):
        """§13: the residual files must be named exactly, not approximately."""
        for name in self.LEGACY_FILES:
            with self.subTest(name=name):
                self.assertTrue(
                    (self.QUARANTINE / name).is_file(),
                    f"§8: {name} must be quarantined under its original "
                    f"filename (provenance preserved).",
                )

    def test_they_are_gone_from_the_active_output_directory(self):
        for name in self.LEGACY_FILES:
            with self.subTest(name=name):
                self.assertFalse(
                    (ROOT / "data" / "outputs" / name).exists(),
                    f"§8: {name} must not remain in data/outputs/.",
                )

    def test_quarantine_is_outside_the_builder_walked_tree(self):
        """§8: no deployment package may discover it."""
        self.assertNotIn(
            "outputs", self.QUARANTINE.relative_to(ROOT).parts,
            "§8: the quarantine must live outside data/outputs/.",
        )

    def test_readme_states_they_are_historical_evidence(self):
        self.assertIn("historical", self.lower)

    def test_readme_states_they_are_not_v0112_operational_outputs(self):
        self.assertIn("not", self.lower)
        self.assertIn("current release surface", self.lower)

    def test_readme_states_they_are_not_core(self):
        self.assertIn("are not part of the withdrawn", self.lower)

    def test_readme_states_remote_disposition_is_outside_authorization(self):
        """§8: the required statement about remote disposition."""
        self.assertIn(
            "outside the core-withdrawal authorization", self.lower,
            "§8: the README must state that their remote disposition is "
            "outside the Core-withdrawal authorization.",
        )

    def test_no_manifest_references_the_quarantine(self):
        for name in ("releases.json", "latest.json", "specifications.json"):
            manifest = (ROOT / "data" / "outputs" / name).read_text()
            with self.subTest(manifest=name):
                self.assertNotIn("quarantine", manifest)
                for legacy in self.LEGACY_FILES:
                    self.assertNotIn(legacy, manifest)

    def test_health_json_does_not_reference_the_quarantine(self):
        health = (ROOT / "web" / "health.json").read_text()
        self.assertNotIn("quarantine", health)
        for legacy in self.LEGACY_FILES:
            self.assertNotIn(legacy, health)

    def test_no_workflow_stages_or_publishes_the_quarantine(self):
        """§8: no workflow may discover or publish the quarantine.

        Scoped to staging and upload verbs rather than to the word
        itself: a CI guard that ASSERTS the quarantine is absent from
        deployment necessarily mentions it, and forbidding the mention
        would mean the repository gets "safer" by deleting the check
        that proves it is safe.
        """
        staging_verbs = ("rsync", "cp ", "--output-dir", "copytree")
        for path in (ROOT / ".github" / "workflows").glob("*.yml"):
            text = path.read_text()
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("#") or "quarantine" not in stripped:
                    continue
                with self.subTest(workflow=path.name, line=stripped[:60]):
                    for verb in staging_verbs:
                        self.assertNotIn(
                            verb, stripped,
                            f"§8: {path.name} appears to stage the "
                            f"quarantine: {stripped}",
                        )

    def test_committed_deploy_tree_does_not_contain_the_quarantine(self):
        deploy = ROOT / "deploy"
        self.assertFalse((deploy / "data" / "quarantine").exists())
        for legacy in self.LEGACY_FILES:
            matches = list(deploy.rglob(legacy))
            self.assertEqual(
                matches, [],
                f"§8: {legacy} must never be staged.",
            )

    def test_frozen_v0110_package_still_holds_its_own_copies(self):
        """The frozen archive is untouched: it keeps its originals.

        This is the counterpart to the quarantine move — the repair must
        not have reached into the frozen package to relocate anything.
        """
        frozen = ROOT / "dmi-v0.1.10-deployment" / "data" / "outputs"
        if not frozen.is_dir():
            self.skipTest("frozen v0.1.10 package not present")
        for legacy in self.LEGACY_FILES:
            with self.subTest(name=legacy):
                self.assertTrue(
                    (frozen / legacy).is_file(),
                    f"§8: the frozen v0.1.10 package must still contain "
                    f"its own {legacy}; it must not be modified.",
                )


class TestCoreForwardPathIsNotSelfContradictory(unittest.TestCase):
    """§6: the forward path must not require finer components and then
    prescribe an aggregate series as the input.

    The previous text got the requirement right — a distribution-aware
    Core needs finer quintile-level CPI components — and then, two bullets
    later, said to use the aggregate BLS Core CPI series as the Core
    inflation input. Those cannot both hold: `CUSR0000SA0L1E` is a single
    national index, so using it would produce identical Core inflation for
    every quintile and collapse the distributional index into a national
    one.
    """

    DOCS = {
        "methodology": ROOT / "docs" / "DMI_Methodology_Note.md",
        "withdrawal": ROOT / "docs" / "repair" / "CORE_WITHDRAWAL.md",
    }

    def _text(self, key):
        return self.DOCS[key].read_text()

    def test_no_document_prescribes_the_aggregate_series_as_the_input(self):
        for key in self.DOCS:
            with self.subTest(doc=key):
                lowered = self._text(key).lower()
                for phrase in (
                    "then: use the bls core cpi",
                    "use the bls core cpi series (`cusr0000sa0l1e`) rather than",
                    "source a food-and-energy-excluded cpi-u\n   series",
                ):
                    self.assertNotIn(
                        phrase, lowered,
                        f"§6: {key} prescribes an aggregate series as the "
                        f"quintile-specific Core input.",
                    )

    def test_both_documents_state_the_aggregate_cannot_be_the_input(self):
        for key in self.DOCS:
            with self.subTest(doc=key):
                lowered = self._text(key).lower()
                self.assertIn(
                    "cusr0000sa0l1e", lowered,
                    f"§6: {key} must name the aggregate series in order to "
                    f"rule it out explicitly.",
                )
                self.assertTrue(
                    "cannot be the price input" in lowered
                    or "cannot itself produce" in lowered
                    or "cannot be the quintile" in lowered
                    or "never as the quintile-specific" in lowered,
                    f"§6: {key} must state that the aggregate series "
                    f"cannot produce quintile-specific Core inflation.",
                )

    def test_both_documents_permit_it_only_as_a_validation_benchmark(self):
        for key in self.DOCS:
            with self.subTest(doc=key):
                self.assertIn(
                    "validation benchmark", self._text(key).lower(),
                    f"§6: {key} must record the legitimate use of the "
                    f"official aggregate series.",
                )

    def test_both_documents_require_finer_components(self):
        for key in self.DOCS:
            with self.subTest(doc=key):
                lowered = self._text(key).lower()
                self.assertIn("finer", lowered)
                for term in ("energy", "motor fuel"):
                    self.assertIn(term, lowered, f"§6: {key} missing {term}")

    def test_both_documents_require_matching_quintile_weights(self):
        for key in self.DOCS:
            with self.subTest(doc=key):
                lowered = self._text(key).lower()
                self.assertIn(
                    "quintile", lowered,
                    f"§6: {key} must require quintile-level weights for "
                    f"the finer components.",
                )
                self.assertIn(
                    "renormaliz", lowered,
                    f"§6: {key} must state the renormalization rule.",
                )

    def test_renormalization_is_scoped_within_each_quintile(self):
        for key in self.DOCS:
            with self.subTest(doc=key):
                lowered = self._text(key).lower()
                self.assertIn(
                    "within each quintile", lowered,
                    f"§6: {key} must say retained weights are renormalized "
                    f"WITHIN each quintile; renormalizing across the "
                    f"population would erase the distributional signal.",
                )

    def test_withdrawal_doc_requires_a_versioned_specification(self):
        lowered = self._text("withdrawal").lower()
        self.assertIn(
            "versioned specification", lowered,
            "§6: the excluded series and renormalization rule must be "
            "enumerated in a future versioned specification.",
        )

    def test_core_is_marked_unscheduled_and_non_operational(self):
        for key in self.DOCS:
            with self.subTest(doc=key):
                lowered = self._text(key).lower()
                self.assertTrue(
                    "not scheduled" in lowered or "unscheduled" in lowered,
                    f"§6: {key} must mark Core unscheduled.",
                )
                self.assertIn("unvalidated", lowered)
                self.assertIn("unimplemented", lowered)

    def test_no_core_implementation_was_added(self):
        """§6: 'Do not implement Core as part of this repair.'"""
        from scripts.release_evidence import OPERATIONAL_SPECS
        self.assertNotIn("core", OPERATIONAL_SPECS)
        self.assertFalse(
            (ROOT / "scripts" / "compute_dmi_core.py").exists(),
            "§6: Core must remain unimplemented.",
        )
        spec = _json.loads(
            (ROOT / "data" / "outputs" / "specifications.json").read_text()
        )
        ids = [e["spec_id"] for e in spec["specifications"]]
        self.assertEqual(sorted(ids), ["baseline", "slack_plus"])


class TestArchivalHistoricalRecordsStayArchival(unittest.TestCase):
    """§8: the 167 income_pressure_gap records are archival, not published.

    They may remain. What must hold is that they are excluded from the
    routine deployment, are not advertised by any canonical manifest, and
    that the read-only compatibility handling which still reads the
    legacy key is documented as such.
    """

    LEGACY_KEY = "income_pressure_gap"
    ARCHIVE = ROOT / "data" / "outputs" / "published" / "historical"

    def test_the_archive_exists_and_is_non_trivial(self):
        """Non-vacuity: without records, the exclusions below prove nothing."""
        records = sorted(self.ARCHIVE.glob("dmi_release_*.json"))
        self.assertGreater(
            len(records), 100,
            "expected the historical archive to hold the legacy records",
        )

    def test_archive_is_excluded_from_the_deployment_tree(self):
        self.assertFalse(
            (ROOT / "deploy" / "data" / "outputs" / "published"
             / "historical").exists(),
            "§8: the historical archive must not be staged for deployment.",
        )

    def test_no_deployed_file_carries_the_legacy_key(self):
        offenders = [
            str(p.relative_to(ROOT / "deploy"))
            for p in (ROOT / "deploy").rglob("*.json")
            if self.LEGACY_KEY in p.read_text(errors="ignore")
        ]
        self.assertEqual(
            offenders, [],
            f"§8: the legacy key must not reach the deployed surface: "
            f"{offenders}",
        )

    def test_no_canonical_current_output_carries_the_legacy_key(self):
        offenders = [
            p.name for p in (ROOT / "data" / "outputs").glob("*.json")
            if self.LEGACY_KEY in p.read_text(errors="ignore")
        ]
        self.assertEqual(offenders, [], f"§8: {offenders}")

    def test_no_manifest_advertises_an_archival_record(self):
        for name in ("releases.json", "latest.json"):
            manifest = _json.loads(
                (ROOT / "data" / "outputs" / name).read_text()
            )
            for release in manifest["releases"]:
                urls = [release.get("release_note", "")]
                for block in (release.get("spec_urls") or {}).values():
                    urls.extend((block or {}).values())
                for url in urls:
                    with self.subTest(manifest=name, url=url):
                        self.assertNotIn(
                            "published/historical", str(url),
                            f"§8: {name} advertises an archival record.",
                        )

    def test_health_json_does_not_advertise_the_archive(self):
        health = (ROOT / "web" / "health.json").read_text()
        self.assertNotIn("published/historical", health)

    def test_compatibility_handling_is_documented_where_it_lives(self):
        """§8: read-only legacy handling may remain if clearly documented."""
        consumers = [
            ROOT / "web" / "wp-plugins" / "dmi-release-data" / "dmi_release_data.php",
            ROOT / "web" / "wp-plugins" / "dmi-latest-info" / "dmi_latest_info.php",
        ]
        for path in consumers:
            if not path.is_file():
                continue
            text = path.read_text()
            if self.LEGACY_KEY not in text:
                continue
            with self.subTest(consumer=path.name):
                self.assertIn(
                    "Legacy", text,
                    f"§8: {path.name} reads the legacy key without saying "
                    f"it is legacy compatibility handling.",
                )

    def test_compatibility_handling_is_read_only(self):
        """The consumers must read the legacy key, never write it."""
        for path in sorted((ROOT / "web" / "wp-plugins").rglob("*.php")):
            text = path.read_text()
            if self.LEGACY_KEY not in text:
                continue
            with self.subTest(consumer=path.name):
                self.assertNotIn(
                    f"'{self.LEGACY_KEY}' =>", text,
                    f"§8: {path.name} writes the legacy key.",
                )

    def test_no_active_writer_emits_the_legacy_key(self):
        """§8: nothing in the active pipeline may produce it."""
        import ast
        offenders = []
        for path in sorted((ROOT / "scripts").glob("*.py")):
            tree = ast.parse(path.read_text())
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef,
                                     ast.FunctionDef, ast.AsyncFunctionDef)):
                    doc = ast.get_docstring(node, clean=False)
                    if doc:
                        docstrings.add(doc)
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Constant)
                        and isinstance(node.value, str)):
                    continue
                if node.value in docstrings:
                    continue
                # `dmi_income_pressure_gap` is the legacy raw-file key the
                # rebuild tool READS in order to verify derived metrics.
                if node.value == self.LEGACY_KEY:
                    offenders.append(path.name)
        self.assertEqual(
            offenders, [],
            f"§8: active writers must not emit the legacy key: {offenders}",
        )


class TestPrDraftDescribesTheFinalBranch(unittest.TestCase):
    """§8: the PR draft must describe the final state, not a chronology."""

    @classmethod
    def setUpClass(cls):
        cls.text = PR_DRAFT.read_text()
        cls.lower = cls.text.lower()

    def test_no_stale_local_only_or_unpushed_claim(self):
        for phrase in ("local only", "no push", "not been pushed",
                       "not yet been pushed", "has not been pushed"):
            with self.subTest(phrase=phrase):
                self.assertNotIn(
                    phrase, self.lower,
                    f"§8: the branch is pushed; {phrase!r} is stale.",
                )

    def test_no_fixed_test_count_presented_as_current(self):
        """§8: counts go stale; point at the snapshot instead."""
        offenders = _re.findall(r"\*\*\d+ passed", self.text)
        self.assertEqual(
            offenders, [],
            f"§8: the draft must not quote a fixed test count as current: "
            f"{offenders}",
        )

    def test_no_obsolete_doi_or_date_released_placeholder_claim(self):
        for phrase in ("date-released marked placeholder",
                       "`date-released` marked placeholder",
                       "placeholder pending"):
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, self.lower)

    def test_citation_claims_match_the_actual_file(self):
        import yaml as _yaml
        cff = _yaml.safe_load((ROOT / "CITATION.cff").read_text())
        self.assertNotIn("doi", cff)
        self.assertNotIn("date-released", cff)
        self.assertIn("no** `doi`", self.text)

    def test_it_states_merge_invokes_the_single_deployment_workflow(self):
        self.assertIn("deploy_production.yml", self.text)
        self.assertIn(
            "merging this pr **will deploy to the live site**", self.lower,
            "§8: the draft must state plainly that merge deploys.",
        )

    def test_it_distinguishes_the_four_stages(self):
        for stage in ("pr preparation", "merge to `main`",
                      "production deployment", "remote artifact withdrawal"):
            with self.subTest(stage=stage):
                self.assertIn(stage, self.lower)

    def test_it_states_withdrawal_is_separately_authorized_and_unexecuted(self):
        self.assertIn("not authorized, not executed", self.lower)
        self.assertIn(
            "merging this pr does not run it", self.lower,
            "§8: the draft must separate merge from withdrawal.",
        )

    PASTE_MARKER = "<!-- ==================== PASTE FROM HERE ==================== -->"

    def _pasteable(self) -> str:
        self.assertIn(
            self.PASTE_MARKER, self.text,
            "the document must mark where the pasteable body begins.",
        )
        return self.text.split(self.PASTE_MARKER, 1)[1]

    def _relative_links(self, text: str):
        return [
            (label, target)
            for label, target in _re.findall(r"\[([^\]]*)\]\(([^)]+)\)", text)
            if not target.startswith(("http://", "https://", "#", "mailto:"))
        ]

    def test_pasteable_body_has_no_repository_relative_link(self):
        """§3 (cleanup): a relative link breaks when pasted into a PR.

        GitHub resolves a relative Markdown link in a PR body against the
        repository root, not against the file the text was copied from,
        so `(CORE_WITHDRAWAL.md)` — correct while reading
        docs/repair/ — points at a nonexistent top-level file once
        pasted. Plain backticked repository paths are used instead: they
        survive the paste and stay valid after the branch is merged and
        deleted, which an absolute branch URL would not.
        """
        offenders = self._relative_links(self._pasteable())
        self.assertEqual(
            offenders, [],
            f"§3: the pasteable PR body must contain no repository-"
            f"relative Markdown link: {offenders}",
        )

    def test_no_relative_link_anywhere_in_the_document(self):
        offenders = self._relative_links(self.text)
        self.assertEqual(offenders, [], f"§3: {offenders}")

    def test_referenced_paths_still_exist_in_the_repository(self):
        """Plain paths are not linked, so verify them explicitly."""
        for path in (
            "docs/repair/V0.1.12_ALIGNMENT_AUDIT.md",
            "docs/repair/CORE_WITHDRAWAL.md",
            "docs/repair/REMOTE_WITHDRAWAL.md",
            ".github/workflows/deploy_production.yml",
        ):
            with self.subTest(path=path):
                self.assertIn(f"`{path}`", self.text)
                self.assertTrue(
                    (ROOT / path).exists(),
                    f"§3: the draft cites {path}, which does not exist.",
                )

    def test_link_scan_is_not_vacuous(self):
        """The regex must actually find the links the document does have."""
        all_links = _re.findall(r"\[([^\]]*)\]\(([^)]+)\)", self.text)
        self.assertGreater(
            len(all_links), 0,
            "no Markdown links found at all; the relative-link checks "
            "above would pass for the wrong reason.",
        )


class TestPrDraftDisclosesTheStagingUpdate(unittest.TestCase):
    """§3 (cleanup): the U-6 staging fetch must be disclosed."""

    ADDED = {"2026-04": "8.2", "2026-05": "8.1",
             "2026-06": "7.9", "2026-07": "7.9"}

    @staticmethod
    def _flat(text: str) -> str:
        """Prose with line wrapping collapsed.

        These documents are hard-wrapped, so a sentence like "no
        previously staged period was modified" is split across lines.
        Asserting on the raw text would make the check depend on where
        the wrap happens to fall rather than on what the document says.
        """
        return " ".join(text.lower().split())

    @classmethod
    def setUpClass(cls):
        cls.draft = PR_DRAFT.read_text()
        cls.audit = AUDIT.read_text()

    def test_both_documents_identify_the_series(self):
        for name, text in (("draft", self.draft), ("audit", self.audit)):
            with self.subTest(doc=name):
                self.assertIn("LNS13327709", text)

    def test_both_documents_record_every_period_and_value(self):
        for name, text in (("draft", self.draft), ("audit", self.audit)):
            for period, value in self.ADDED.items():
                with self.subTest(doc=name, period=period):
                    row = _re.search(
                        rf"\|\s*{_re.escape(period)}\s*\|\s*{_re.escape(value)}\s*\|",
                        text,
                    )
                    self.assertIsNotNone(
                        row,
                        f"§3: {name} must record {period} = {value}.",
                    )

    def test_both_documents_state_published_releases_were_unchanged(self):
        for name, text in (("draft", self.draft), ("audit", self.audit)):
            flat = self._flat(text)
            with self.subTest(doc=name):
                self.assertIn("exactly match", flat)
                self.assertTrue(
                    "published raw releases were left unchanged" in flat
                    or "no published raw release was altered" in flat,
                    f"§3: {name} must state the published raw releases "
                    f"were unchanged.",
                )

    def test_both_documents_state_no_prior_period_was_modified(self):
        for name, text in (("draft", self.draft), ("audit", self.audit)):
            with self.subTest(doc=name):
                self.assertIn(
                    "no previously staged period was modified",
                    self._flat(text),
                )

    def test_both_documents_state_no_production_host_was_contacted(self):
        for name, text in (("draft", self.draft), ("audit", self.audit)):
            with self.subTest(doc=name):
                self.assertIn(
                    "no production host was contacted", self._flat(text),
                    f"§3: {name} must state that the fetch reached the BLS "
                    f"public API only.",
                )

    def test_both_documents_state_it_closes_the_offline_gap(self):
        for name, text in (("draft", self.draft), ("audit", self.audit)):
            with self.subTest(doc=name):
                self.assertIn("offline-staging gap", self._flat(text))

    def test_both_documents_state_the_fetch_was_unintended(self):
        for name, text in (("draft", self.draft), ("audit", self.audit)):
            with self.subTest(doc=name):
                self.assertIn("unintended", self._flat(text))

    def test_the_disclosure_matches_the_actual_staged_file(self):
        """The claim must equal what is on disk."""
        staged = {
            r["period"]: r["value"]
            for r in _json.loads(
                (ROOT / "data" / "staging"
                 / "slack_u6_2025_2026.json").read_text()
            )
        }
        for period, value in self.ADDED.items():
            with self.subTest(period=period):
                self.assertEqual(
                    staged.get(period), float(value),
                    f"§3: the disclosure claims {period}={value} but the "
                    f"staged file holds {staged.get(period)}.",
                )

    def test_the_values_match_the_published_releases(self):
        """The central claim: nothing published was contradicted."""
        for period, value in self.ADDED.items():
            raw = (ROOT / "data" / "outputs"
                   / f"dmi_release_{period}_slack_plus.json")
            if not raw.is_file():
                continue
            with self.subTest(period=period):
                published = _json.loads(raw.read_text())["dmi_by_group"][0]["slack"]
                self.assertEqual(
                    float(value), float(published),
                    f"§3: staged {period}={value} contradicts the "
                    f"published release value {published}.",
                )


class TestPrDraftStatesThePreMergeSecretRequirement(unittest.TestCase):
    """§3 (cleanup): the external pre-merge requirement must be explicit."""

    @classmethod
    def setUpClass(cls):
        cls.text = PR_DRAFT.read_text()
        cls.lower = cls.text.lower()

    def test_it_names_the_secret(self):
        self.assertIn("IFASTNET_KNOWN_HOSTS", self.text)

    def test_it_requires_independently_verified_material(self):
        self.assertIn("independently verified", self.lower)

    def test_it_names_the_port(self):
        self.assertIn("1394", self.text)

    def test_it_states_merging_triggers_deployment(self):
        self.assertIn("automatically triggers production deployment",
                      self.lower)

    def test_it_states_deployment_fails_closed_without_the_secret(self):
        self.assertIn("fails closed", self.lower)
        self.assertIn("nothing is uploaded", self.lower)

    def test_it_appears_as_a_checklist_item(self):
        checklist = self.text[self.text.index("## Reviewer checklist"):]
        self.assertIn("IFASTNET_KNOWN_HOSTS", checklist)

    def test_the_failure_claim_matches_the_implementation(self):
        """The draft says it fails closed; prove the code does."""
        from scripts.install_known_hosts import HostPinError, install
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "known_hosts"
            with self.assertRaises(HostPinError):
                install("ssh.example.org", "1394", target)
            self.assertFalse(target.exists())

    def test_it_is_not_a_chronological_accumulation(self):
        """No per-round sections describing superseded states."""
        round_headings = _re.findall(
            r"^#{1,3}\s+Round[ -]\d", self.text, flags=_re.MULTILINE
        )
        self.assertEqual(
            round_headings, [],
            f"§8: the draft must describe the final branch, not accumulate "
            f"a round-by-round history: {round_headings}",
        )

    def test_it_states_the_deliberate_version_split(self):
        self.assertIn("3.0.0", self.text)
        self.assertIn("0.3.0", self.text)
        self.assertIn("separately versioned contract", self.lower)

    def test_it_states_core_is_not_implemented(self):
        self.assertIn("core is **not**\nimplemented", self.lower)
        self.assertIn("unscheduled, unimplemented, unvalidated", self.lower)


class TestWithdrawalDocsDistinguishTheThreeStates(unittest.TestCase):
    """§8: local cleanup, deployment, and remote withdrawal are distinct."""

    RUNBOOK = ROOT / "docs" / "repair" / "REMOTE_WITHDRAWAL.md"
    EVIDENCE = ROOT / "docs" / "known-issues" / "CORE_OUTPUT_WITHDRAWAL.md"

    def test_runbook_states_it_is_unauthorized_and_unexecuted(self):
        lowered = self.RUNBOOK.read_text().lower()
        self.assertIn("not authorized, not executed", lowered)

    def test_runbook_separates_the_three_states(self):
        lowered = self.RUNBOOK.read_text().lower()
        for phrase in ("local repository cleanup", "production deployment",
                       "remote artifact withdrawal"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, lowered)
        self.assertIn("complete", lowered)
        self.assertIn("has not occurred", lowered)

    def test_runbook_says_merging_does_not_trigger_withdrawal(self):
        lowered = self.RUNBOOK.read_text().lower()
        self.assertIn("merging the pr does not run it", lowered)

    def test_evidence_record_no_longer_uses_stale_future_tense(self):
        lowered = self.EVIDENCE.read_text().lower()
        for phrase in ("will be regenerated in phase 4",
                       "will be prepared as a repository artifact",
                       "will be examined by regression tests added in phase 2"):
            with self.subTest(phrase=phrase):
                self.assertNotIn(
                    phrase, lowered,
                    f"§8: {phrase!r} describes work that has since been "
                    f"done; it must reflect the actual state.",
                )

    def test_evidence_record_points_at_the_current_tooling(self):
        text = self.EVIDENCE.read_text()
        self.assertIn("withdraw_remote_artifacts.py", text)
        self.assertNotIn(
            "scripts/withdraw_core_remote.sh` (or equivalent) in Phase 7",
            text,
            "§8: the record must name the tool that exists.",
        )

    def test_manifest_claim_matches_reality(self):
        """The record says manifests no longer carry Core; verify it."""
        for name in ("releases.json", "latest.json"):
            manifest = _json.loads(
                (ROOT / "data" / "outputs" / name).read_text()
            )
            for release in manifest["releases"]:
                with self.subTest(manifest=name, release=release["release_id"]):
                    self.assertNotIn("core", release.get("spec_urls", {}))
