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
        idx = self.text.find("**2. Official Core CPI**")
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
        self.assertIn("intended, not", self.lower)
        self.assertIn("unvalidated", self.lower)

    def test_states_work_required_before_core_returns(self):
        self.assertIn("work required before core can return", self.lower)
        self.assertIn("finer expenditure mapping", self.lower)

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

    def test_no_workflow_references_the_quarantine(self):
        for path in (ROOT / ".github" / "workflows").glob("*.yml"):
            with self.subTest(workflow=path.name):
                self.assertNotIn("quarantine", path.read_text())

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
