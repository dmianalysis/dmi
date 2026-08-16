#!/usr/bin/env python3
"""Regression coverage for withdrawal-tooling safety posture (§10).

The withdrawal tooling has two components:

1. ``scripts/withdraw_remote_artifacts.py`` — the two-phase mutating
   tool. Phase 1 (``inventory``) is read-only SSH enumeration + hashing
   into a local reviewed JSON file. Phase 2 (``execute``) re-verifies
   sha256 digests on the remote before deleting, and refuses to delete
   anything not present in the reviewed inventory.

2. ``scripts/inventory_withdrawn_artifacts.py`` — the read-only local
   companion that lists what withdrawn artifacts still sit in the
   working tree, with zero side effects.

§10 demands both components stay "inventory-first, no execution":

- The mutating tool MUST expose two subcommands (``inventory`` and
  ``execute``); the ``inventory`` subcommand MUST NOT accept a
  ``--confirm`` flag; the ``execute`` subcommand MUST require
  ``--confirm`` and MUST refuse to delete unless every inventory entry's
  sha256 re-verifies on the remote; the delete step MUST be preceded
  by a protected-pattern refusal that rejects Baseline / Slack-Plus /
  legacy-unsuffixed names; SSH invocation MUST use
  ``StrictHostKeyChecking=yes`` and a scoped ``UserKnownHostsFile``.

- The read-only Python tool MUST NOT contain any mutating verb
  (``rm``, ``rename``, ``unlink``, ``rmtree``, ``open(..., 'w')``,
  ``os.remove``, ``shutil`` mutation calls); its argparse surface
  MUST NOT expose a ``--confirm`` or ``--execute`` style flag;
  running it against an empty temporary directory MUST succeed and
  produce a zero-match report.

Together the tests prevent a future refactor from silently turning the
inventory helper into a mutator, from collapsing the two phases into
one, or from removing the hash-verification gate on execute.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REMOTE_TOOL = REPO_ROOT / "scripts" / "withdraw_remote_artifacts.py"
LOCAL_INVENTORY_TOOL = REPO_ROOT / "scripts" / "inventory_withdrawn_artifacts.py"


class TestRemoteWithdrawalToolIsTwoPhase(unittest.TestCase):

    def setUp(self):
        self.assertTrue(REMOTE_TOOL.exists(), f"{REMOTE_TOOL} missing")
        self.src = REMOTE_TOOL.read_text()

    def test_defines_two_subcommands(self):
        # Both `inventory` and `execute` must be registered subcommands.
        for name in ("inventory", "execute"):
            self.assertRegex(
                self.src,
                rf'sub\.add_parser\(\s*["\']{name}["\']',
                f"§10: '{name}' subcommand must be registered.",
            )

    def test_inventory_subcommand_has_no_confirm_or_execute_flag(self):
        # Parse the module and inspect only the argparse calls attached
        # to the inventory subparser.
        tree = ast.parse(self.src)
        offenders: list[str] = []
        # Look for `p_inv.add_argument("--confirm"|"--execute"|...)`.
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr != "add_argument":
                continue
            if not isinstance(func.value, ast.Name):
                continue
            if func.value.id != "p_inv":
                continue
            if not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                flag = first.value.lstrip("-").lower()
                for banned in ("confirm", "execute", "delete", "remove"):
                    if banned in flag:
                        offenders.append(first.value)
        self.assertEqual(
            offenders, [],
            f"§10: inventory subcommand must not expose a mutating flag "
            f"(found: {offenders}).",
        )

    def test_execute_subcommand_requires_confirm_flag(self):
        # The `execute` subparser must declare a --confirm flag AND the
        # command must refuse to run without it.
        self.assertRegex(
            self.src,
            r'p_exec\.add_argument\(\s*["\']--confirm["\']',
            "§10: execute must expose a --confirm flag.",
        )
        self.assertRegex(
            self.src,
            r'if not args\.confirm\s*:',
            "§10: execute must gate mutation behind an args.confirm check.",
        )

    def test_execute_verifies_sha256_before_deletion(self):
        # The re-hash call must occur before the delete call, and the
        # delete must not be reachable if any digest mismatched.
        rehash_idx = self.src.find("_remote_rehash(")
        mismatch_idx = self.src.find("mismatches")
        delete_idx = self.src.find("_remote_delete(")
        self.assertGreater(rehash_idx, 0, "§10: _remote_rehash call missing.")
        self.assertGreater(mismatch_idx, 0, "§10: mismatch handling missing.")
        self.assertGreater(delete_idx, 0, "§10: _remote_delete call missing.")
        self.assertLess(
            rehash_idx, delete_idx,
            "§10: sha256 re-hash must run before deletion.",
        )
        self.assertLess(
            mismatch_idx, delete_idx,
            "§10: mismatch check must precede deletion.",
        )

    def test_execute_refuses_when_inventory_missing(self):
        # Structural check: SystemExit on missing inventory is present.
        self.assertRegex(
            self.src,
            r'raise\s+SystemExit\(\s*f?["\'][^"\']*inventory not found',
            "§10: execute must raise SystemExit if inventory file is missing.",
        )

    def test_protected_pattern_guard_present(self):
        # The belt-and-suspenders regex list must include Baseline,
        # Slack-Plus, and legacy-unsuffixed CSV/Parquet patterns.
        self.assertIn(
            r"^dmi_release_[0-9]{4}-[0-9]{2}\.json$", self.src,
        )
        self.assertIn(
            r"^dmi_release_[0-9]{4}-[0-9]{2}_slack_plus\.json$", self.src,
        )
        self.assertIn(
            r"^dmi-[0-9]{4}-[0-9]{2}-baseline\.(csv|parquet)$", self.src,
        )
        self.assertIn(
            r"^dmi-[0-9]{4}-[0-9]{2}-slack_plus\.(csv|parquet)$", self.src,
        )
        self.assertRegex(
            self.src,
            r'raise\s+SystemExit\(\s*[^)]*protected or out-of-scope',
            "§10: protected-pattern guard must raise SystemExit.",
        )

    def test_ssh_uses_strict_host_verification(self):
        self.assertIn('"StrictHostKeyChecking=yes"', self.src)
        self.assertIn('UserKnownHostsFile=', self.src)

    def test_withdrawn_patterns_never_match_baseline_or_slack_plus(self):
        # Import the module's patterns directly and verify none of them
        # would fnmatch a protected artifact name.
        import fnmatch
        import importlib
        sys.path.insert(0, str(REPO_ROOT))
        try:
            mod = importlib.import_module(
                "scripts.withdraw_remote_artifacts",
            )
        finally:
            sys.path.pop(0)

        forbidden = [
            "dmi_release_2026-07.json",
            "dmi_release_2026-07_slack_plus.json",
            "dmi-2026-07-baseline.csv",
            "dmi-2026-07-slack_plus.parquet",
            "dmi-2026-01.csv",
            "dmi-2026-01.parquet",
        ]
        for pat in mod.WITHDRAWN_PATTERNS:
            for name in forbidden:
                self.assertFalse(
                    fnmatch.fnmatch(name, pat),
                    f"§10: WITHDRAWN_PATTERNS glob {pat!r} would match "
                    f"protected artifact {name!r}",
                )

    def test_refuse_protected_rejects_baseline(self):
        # Direct invocation: feeding a baseline path into
        # _refuse_protected must raise SystemExit.
        import importlib
        sys.path.insert(0, str(REPO_ROOT))
        try:
            mod = importlib.import_module(
                "scripts.withdraw_remote_artifacts",
            )
        finally:
            sys.path.pop(0)

        records = [
            {"path": "/home/agiraces/dmianalysis/data/outputs/"
                     "dmi_release_2026-07.json",
             "size": 1, "sha256": "x" * 64},
        ]
        with self.assertRaises(SystemExit):
            mod._refuse_protected(records, "/home/agiraces/dmianalysis")

    def test_refuse_protected_rejects_out_of_base(self):
        import importlib
        sys.path.insert(0, str(REPO_ROOT))
        try:
            mod = importlib.import_module(
                "scripts.withdraw_remote_artifacts",
            )
        finally:
            sys.path.pop(0)

        records = [
            {"path": "/etc/passwd", "size": 1, "sha256": "y" * 64},
        ]
        with self.assertRaises(SystemExit):
            mod._refuse_protected(records, "/home/agiraces/dmianalysis")

    def test_refuse_protected_accepts_valid_withdrawn(self):
        import importlib
        sys.path.insert(0, str(REPO_ROOT))
        try:
            mod = importlib.import_module(
                "scripts.withdraw_remote_artifacts",
            )
        finally:
            sys.path.pop(0)

        records = [
            {"path": "/home/agiraces/dmianalysis/data/outputs/"
                     "dmi_release_2024-11_core.json",
             "size": 1, "sha256": "z" * 64},
        ]
        # Must NOT raise.
        mod._refuse_protected(records, "/home/agiraces/dmianalysis")


class TestPythonLocalInventoryToolIsReadOnly(unittest.TestCase):

    def setUp(self):
        self.assertTrue(
            LOCAL_INVENTORY_TOOL.exists(),
            f"{LOCAL_INVENTORY_TOOL} missing",
        )
        self.src = LOCAL_INVENTORY_TOOL.read_text()

    def test_source_contains_no_mutating_verbs(self):
        forbidden = [
            r"\bos\.remove\b",
            r"\bos\.unlink\b",
            r"\.unlink\(",
            r"\bshutil\.rmtree\b",
            r"\bshutil\.move\b",
            r"\bshutil\.copy\b",
            r"\bopen\([^)]*['\"][wa]",
            r"\.write_text\b",
            r"\.write_bytes\b",
            r"\bsubprocess\.",
        ]
        for pattern in forbidden:
            self.assertIsNone(
                re.search(pattern, self.src),
                f"§10: local inventory tool contains forbidden mutating "
                f"token matching {pattern!r}",
            )

    def test_argparse_exposes_no_execute_or_confirm_flag(self):
        add_arg_calls = re.findall(
            r"add_argument\(\s*['\"]([^'\"]+)['\"]",
            self.src,
        )
        for token in ("execute", "confirm", "delete", "remove", "commit"):
            offenders = [f for f in add_arg_calls if token in f.lower()]
            self.assertEqual(
                offenders, [],
                f"§10: local inventory tool must not expose --{token} flag "
                f"via argparse (found: {offenders}).",
            )

    def test_running_against_empty_dir_succeeds_and_reports_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(LOCAL_INVENTORY_TOOL),
                 "--root", tmp, "--json"],
                capture_output=True, text=True, check=True,
            )
            report = json.loads(result.stdout)
            self.assertEqual(report["match_count"], 0)
            self.assertEqual(report["matches"], [])

    def test_running_against_seeded_dir_finds_only_withdrawn_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "dmi_release_2026-01_core.json").write_text("{}")
            (tmp_path / "qa_report_2026-02_core.json").write_text("{}")
            (tmp_path / "dmi_release_2026-01.json").write_text("{}")
            (tmp_path / "dmi_release_2026-01_slack_plus.json").write_text("{}")
            (tmp_path / "README.md").write_text("nothing to see")

            result = subprocess.run(
                [sys.executable, str(LOCAL_INVENTORY_TOOL),
                 "--root", tmp, "--json"],
                capture_output=True, text=True, check=True,
            )
            report = json.loads(result.stdout)
            self.assertEqual(
                sorted(report["matches"]),
                sorted([
                    "dmi_release_2026-01_core.json",
                    "qa_report_2026-02_core.json",
                ]),
                "§10: inventory must match only withdrawn patterns.",
            )

    def test_excluded_dirs_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for excluded in (".git", "deploy", "node_modules"):
                sub = tmp_path / excluded
                sub.mkdir()
                (sub / "dmi_release_2026-01_core.json").write_text("{}")

            result = subprocess.run(
                [sys.executable, str(LOCAL_INVENTORY_TOOL),
                 "--root", tmp, "--json"],
                capture_output=True, text=True, check=True,
            )
            report = json.loads(result.stdout)
            self.assertEqual(
                report["match_count"], 0,
                "§10: matches under excluded dirs must be skipped.",
            )


if __name__ == "__main__":
    unittest.main()
