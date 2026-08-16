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
