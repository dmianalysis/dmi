#!/usr/bin/env python3
"""Research-firewall tests for the Detailed Inflation Substrate, Milestone 1.

Covers prompt section 15 "Research firewall": a Milestone-1 audit run must not
create or modify files under ``data/outputs/`` or ``deploy/data/outputs/``.

The guard is tested two ways: the path check is exercised directly, and a real
end-to-end audit run over synthetic sources is fingerprinted against both
operational trees before and after.
"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from tests.detailed_inflation_fixtures import (
    write_concordance,
    write_minimal_sources,
)

from dmi_research.detailed_inflation import (
    FORBIDDEN_OUTPUT_ROOTS,
    RESEARCH_OUTPUT_ROOT,
)
from dmi_research.detailed_inflation.audit import (
    ResearchFirewallError,
    assert_research_output_dir,
    run_audit,
    write_artifacts,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def fingerprint(root: Path) -> dict[str, str]:
    """Content hash of every file under ``root``, keyed by relative path."""
    if not root.is_dir():
        return {}
    prints: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            prints[str(path.relative_to(root))] = digest
    return prints


class TestForbiddenRoots(unittest.TestCase):
    def test_both_operational_trees_are_declared_forbidden(self):
        self.assertEqual(
            set(FORBIDDEN_OUTPUT_ROOTS), {"data/outputs", "deploy/data/outputs"}
        )

    def test_research_root_is_not_inside_a_forbidden_tree(self):
        for forbidden in FORBIDDEN_OUTPUT_ROOTS:
            self.assertFalse(RESEARCH_OUTPUT_ROOT.startswith(forbidden + "/"))
            self.assertNotEqual(RESEARCH_OUTPUT_ROOT, forbidden)


class TestOutputDirGuard(unittest.TestCase):
    def test_forbidden_root_itself_is_rejected(self):
        for forbidden in FORBIDDEN_OUTPUT_ROOTS:
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(ResearchFirewallError):
                    assert_research_output_dir(REPO_ROOT / forbidden)

    def test_directory_inside_a_forbidden_root_is_rejected(self):
        for forbidden in FORBIDDEN_OUTPUT_ROOTS:
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(ResearchFirewallError):
                    assert_research_output_dir(
                        REPO_ROOT / forbidden / "detailed_inflation"
                    )

    def test_traversal_back_into_a_forbidden_root_is_rejected(self):
        with self.assertRaises(ResearchFirewallError):
            assert_research_output_dir(
                REPO_ROOT / "data" / "research" / ".." / ".." / "data" / "outputs"
            )

    def test_the_research_directory_is_allowed(self):
        resolved = assert_research_output_dir(
            REPO_ROOT / RESEARCH_OUTPUT_ROOT / "audit_2024"
        )
        self.assertTrue(str(resolved).endswith("detailed_inflation/audit_2024"))

    def test_a_temporary_directory_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                assert_research_output_dir(Path(tmp)), Path(tmp).resolve()
            )

    def test_a_similarly_named_sibling_is_not_confused_for_a_forbidden_root(self):
        # "data/outputs_research" must not match "data/outputs" by prefix.
        with tempfile.TemporaryDirectory() as tmp:
            sibling = Path(tmp) / "data" / "outputs_research"
            sibling.mkdir(parents=True)
            assert_research_output_dir(sibling, repo_root=Path(tmp))


class TestAuditRunTouchesNothingOperational(unittest.TestCase):
    """End-to-end: run the audit for real, then diff both operational trees."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.sources = write_minimal_sources(self.tmp)
        self.concordance = write_concordance(
            self.tmp,
            [
                ("010119", "FA011", "Flour", "Flour"),
                ("020219", "FA021", "Bread", "White bread"),
                ("470111", "TB011", "Gasoline", "Gasoline, unleaded regular"),
                ("470111", "TB021", "Gasoline", "Gasoline, unleaded premium"),
            ],
        )

    def run_full_audit(self, output_dir: Path):
        result = run_audit(
            series_path=self.sources["series"],
            data_path=self.sources["data"],
            items_path=self.sources["items"],
            aspects_path=self.sources["aspects"],
            concordance_path=self.concordance,
        )
        return write_artifacts(result, output_dir)

    def test_operational_trees_are_byte_identical_after_a_run(self):
        trees = [REPO_ROOT / forbidden for forbidden in FORBIDDEN_OUTPUT_ROOTS]
        before = [fingerprint(tree) for tree in trees]

        written = self.run_full_audit(self.tmp / "research_out")
        self.assertTrue(written)

        after = [fingerprint(tree) for tree in trees]
        for tree, snapshot_before, snapshot_after in zip(trees, before, after):
            self.assertEqual(
                snapshot_before,
                snapshot_after,
                f"the Milestone 1 audit modified files under {tree}",
            )

    def test_artifacts_land_only_in_the_requested_research_directory(self):
        output_dir = self.tmp / "research_out"
        written = self.run_full_audit(output_dir)
        for path in written:
            self.assertEqual(path.parent, output_dir.resolve())

    def test_writing_to_an_operational_tree_is_refused_before_any_file_is_made(self):
        target = REPO_ROOT / "data" / "outputs" / "detailed_inflation_smoke"
        with self.assertRaises(ResearchFirewallError):
            self.run_full_audit(target)
        self.assertFalse(target.exists())

    def test_the_audit_emits_the_full_artifact_set(self):
        written = self.run_full_audit(self.tmp / "research_out")
        self.assertEqual(
            {path.name for path in written},
            {
                "audit_summary.json",
                "active_ucc_basis.csv",
                "parent_reconciliation.csv",
                "ucc_mapping_audit.csv",
                "mapping_status_summary.csv",
                "rse_audit.csv",
                "exception_ledger.csv",
            },
        )

    def test_the_audit_declares_itself_research_only(self):
        result = run_audit(
            series_path=self.sources["series"],
            data_path=self.sources["data"],
            items_path=self.sources["items"],
            aspects_path=self.sources["aspects"],
            concordance_path=self.concordance,
        )
        self.assertEqual(result.summary["status"], "RESEARCH_ONLY")
        self.assertIn("WITHDRAWN", result.summary["core_dmi"])


if __name__ == "__main__":
    unittest.main()
