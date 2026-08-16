#!/usr/bin/env python3
"""Cross-cutting regression coverage for the v0.1.12 repair (§13).

Sections §1–§12 each fix a specific defect and ship focused tests for
that fix. §13 adds the *cross-cutting* invariants: repository-wide
sweeps that would catch a Core-artifact resurrection, an auto-merge
regression, or a broken manifest URL even if the offending change
lands in a file that wasn't touched by any of §1–§12 individually.

These tests are deliberately conservative:
- They only inspect files under the active repository tree; the frozen
  v0.1.10 archival package at `dmi-v0.1.10-deployment/` is excluded, in
  line with the audit's "identified as archival and excluded from
  v0.1.12 build inputs" disposition.
- They only assert invariants for which the repair spec already
  established a positive contract elsewhere; nothing new is invented.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

ROOT = Path(__file__).resolve().parent.parent


# Directories excluded from all sweeps (archival / vendored / VCS).
EXCLUDED_DIRS: frozenset[str] = frozenset({
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "deploy",
    # v0.1.10 archival package: frozen at that release, quarantined
    # per docs/repair/V0.1.12_ALIGNMENT_AUDIT.md; must not be modified
    # by v0.1.12 repair and must not count against v0.1.12 invariants.
    "dmi-v0.1.10-deployment",
})


def _under_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in path.parts)


class TestConceptNoteRemainsRemoved(unittest.TestCase):
    """§1: the unpublished concept note file must not resurface."""

    OFFENDER_NAMES = (
        "DMI_Concept_Note_v0.4.6_final_v3.1_August_2026.md",
    )

    def test_no_offender_file_exists_anywhere(self):
        for name in self.OFFENDER_NAMES:
            for hit in ROOT.rglob(name):
                if _under_excluded(hit.relative_to(ROOT)):
                    continue
                self.fail(
                    f"§1: unpublished concept note {name!r} has been "
                    f"re-added at {hit}"
                )


class TestNoAutoMergeInAnyWorkflow(unittest.TestCase):
    """§6 broadened: no workflow may auto-merge or auto-close a PR."""

    @unittest.skipIf(yaml is None, "PyYAML not available")
    def test_no_workflow_calls_gh_pr_merge(self):
        wf_dir = ROOT / ".github" / "workflows"
        offenders: list[str] = []
        for wf in wf_dir.glob("*.yml"):
            doc = yaml.safe_load(wf.read_text())
            # Get jobs regardless of the "on: True" PyYAML quirk.
            jobs = doc.get("jobs", {}) if isinstance(doc, dict) else {}
            for job_name, job in jobs.items():
                for step in (job.get("steps", []) or []):
                    run = step.get("run", "") or ""
                    if "gh pr merge" in run:
                        offenders.append(
                            f"{wf.name}::{job_name}::{step.get('name')!r}"
                        )
        self.assertEqual(
            offenders, [],
            "§6/§13: no workflow may call `gh pr merge`; found in: "
            f"{offenders}",
        )

    def test_no_workflow_step_name_mentions_auto_merge(self):
        wf_dir = ROOT / ".github" / "workflows"
        offenders: list[str] = []
        for wf in wf_dir.glob("*.yml"):
            for line in wf.read_text().splitlines():
                lower = line.lower()
                if "name:" in lower and (
                    "auto-merge" in lower or "automerge" in lower
                ):
                    offenders.append(f"{wf.name}: {line.strip()}")
        self.assertEqual(
            offenders, [],
            f"§6/§13: no workflow step may be named auto-merge*; "
            f"found: {offenders}",
        )


class TestManifestsContainNoRetiredArtifacts(unittest.TestCase):
    """§3/§7/§8 broadened: no shipped manifest may advertise a
    withdrawn Core / U-6 / with_ci endpoint or filename."""

    RETIRED_URL_TOKENS = (
        "_core.json",
        "_core.csv",
        "_core.parquet",
        "_u6.json",
        "_u6.csv",
        "_u6.parquet",
    )

    MANIFESTS = (
        "data/outputs/latest.json",
        "data/outputs/releases.json",
        "data/outputs/specifications.json",
        "web/health.json",
    )

    def test_no_shipped_manifest_carries_retired_urls(self):
        for rel in self.MANIFESTS:
            path = ROOT / rel
            if not path.exists():
                continue
            raw = path.read_text()
            for token in self.RETIRED_URL_TOKENS:
                self.assertNotIn(
                    token, raw,
                    f"§13: shipped manifest {rel} carries retired "
                    f"artifact token {token!r}.",
                )


class TestNoDirectCoreOutputInActiveTree(unittest.TestCase):
    """§10 broadened: outside archives and withdrawal docs, no source
    file should have a `_core.` filename either."""

    def test_no_active_source_file_has_core_output_name(self):
        # Filenames like `dmi_release_*_core.json` in the active tree
        # would be a red flag. Docs that reference the withdrawal by
        # name (e.g., in prose) are fine; actual output files are not.
        offenders: list[str] = []
        for path in ROOT.rglob("dmi_release_*_core.*"):
            rel = path.relative_to(ROOT)
            if _under_excluded(rel):
                continue
            offenders.append(str(rel))
        for path in ROOT.rglob("dmi-*-core.*"):
            rel = path.relative_to(ROOT)
            if _under_excluded(rel):
                continue
            offenders.append(str(rel))
        self.assertEqual(
            offenders, [],
            "§13: no `*_core.*` output files may live outside the "
            f"frozen v0.1.10 archive; found: {offenders}",
        )


class TestVersionStringsAgree(unittest.TestCase):
    """§11 broadened: the human-facing release version must be
    consistent across CITATION.cff and CHANGELOG.md."""

    def test_cff_version_matches_changelog_top_entry(self):
        cff = (ROOT / "CITATION.cff").read_text()
        changelog = (ROOT / "CHANGELOG.md").read_text()
        # Grab the first `## [X.Y.Z]` in the changelog (skip Unreleased).
        top = None
        for line in changelog.splitlines():
            stripped = line.strip()
            if stripped.startswith("## [") and "unreleased" not in stripped.lower():
                # Extract "0.1.12" from "## [0.1.12]" or "## [0.1.12] - ...".
                inner = stripped.split("[", 1)[1].split("]", 1)[0]
                top = inner.strip()
                break
        self.assertIsNotNone(
            top, "CHANGELOG.md has no versioned entry to check against.",
        )
        self.assertIn(
            f"version: {top}", cff,
            f"§13: CITATION.cff `version` must match CHANGELOG top "
            f"entry ({top!r}).",
        )


if __name__ == "__main__":
    unittest.main()
