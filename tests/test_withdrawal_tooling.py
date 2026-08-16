#!/usr/bin/env python3
"""Regression coverage for withdrawal-tooling safety posture (§10).

The withdrawal tooling has two components:

1. ``scripts/withdraw_core_artifacts.sh`` — the mutating tool that,
   when explicitly authorised, removes withdrawn Core / U-6 / with_ci
   artifacts from the live remote site over SSH.

2. ``scripts/inventory_withdrawn_artifacts.py`` — the read-only local
   companion that lists what withdrawn artifacts still sit in the
   working tree, with zero side effects.

§10 demands both components stay "inventory-first, no execution":

- The shell tool MUST refuse to run when invoked without an explicit
  flag; MUST support ``--dry-run`` as a listing mode; MUST require
  ``--confirm`` for any mutation; and MUST keep the Baseline /
  Slack-Plus safety guard around the delete step.

- The Python tool MUST NOT contain any mutating verb (``rm``, ``rename``,
  ``unlink``, ``rmtree``, ``open(..., 'w')``, ``os.remove``, ``shutil``
  mutation calls); its argparse surface MUST NOT expose a ``--confirm``
  or ``--execute`` style flag; running it against an empty temporary
  directory MUST succeed and produce a zero-match report.

Together the tests prevent a future refactor from silently turning the
inventory helper into a mutator or removing the shell tool's safety
gates.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SHELL_TOOL = REPO_ROOT / "scripts" / "withdraw_core_artifacts.sh"
PY_TOOL = REPO_ROOT / "scripts" / "inventory_withdrawn_artifacts.py"


class TestShellWithdrawalToolSafetyPosture(unittest.TestCase):

    def setUp(self):
        self.assertTrue(SHELL_TOOL.exists(), f"{SHELL_TOOL} missing")
        self.src = SHELL_TOOL.read_text()

    def test_tool_is_executable(self):
        self.assertTrue(
            os.access(SHELL_TOOL, os.X_OK),
            "§10: withdrawal tool must be executable so the documented "
            "runbook works without a chmod step.",
        )

    def test_refuses_to_run_without_a_flag(self):
        # Structural check on the source so we don't need the SSH env
        # variables set (which the tool checks after flag parsing).
        self.assertRegex(
            self.src,
            r'if\s*\[\s*"\$CONFIRM"\s*!=\s*"yes"\s*\]\s*&&'
            r'\s*\[\s*"\$DRY_RUN"\s*!=\s*"yes"\s*\]\s*;\s*then',
            "§10: tool must refuse to run when neither --dry-run nor "
            "--confirm is supplied.",
        )
        self.assertIn(
            "exit 1", self.src,
            "§10: the no-flag branch must exit non-zero.",
        )

    def test_supports_dry_run_and_confirm_flags(self):
        for flag_case in ("--dry-run) DRY_RUN=", "--confirm) CONFIRM="):
            self.assertIn(
                flag_case, self.src,
                f"§10: tool must expose {flag_case.split(')')[0]}.",
            )

    def test_dry_run_never_reaches_delete(self):
        # The `-delete` action MUST only appear after the DRY_RUN=yes
        # guard has been checked and passed. Assert both that -delete
        # exists (real deletion is possible when --confirm is set) and
        # that it appears AFTER the dry-run early-exit block.
        dry_run_exit_idx = self.src.find('if [ "$DRY_RUN" = "yes" ]')
        delete_idx = self.src.find("-delete")
        self.assertGreater(dry_run_exit_idx, 0, "§10: dry-run guard missing")
        self.assertGreater(delete_idx, 0, "§10: delete action missing (execute mode broken)")
        self.assertLess(
            dry_run_exit_idx, delete_idx,
            "§10: -delete must appear only AFTER the dry-run early-exit.",
        )

    def test_baseline_slack_plus_safety_guard_present(self):
        # The belt-and-suspenders guard aborts the delete if any
        # Baseline or Slack-Plus artifact somehow slipped into the
        # match list.
        self.assertIn("dmi_release_[0-9]{4}-[0-9]{2}\\.json", self.src)
        self.assertIn("_slack_plus\\.json", self.src)
        self.assertIn(
            "ABORT: match list unexpectedly contains", self.src,
            "§10: Baseline/Slack-Plus safety abort message missing.",
        )

    def test_find_expression_never_matches_baseline_or_slack_plus(self):
        # Extract every -name glob and assert none of them would match
        # a Baseline or Slack-Plus filename.
        globs = re.findall(r"-name\s+['\"]([^'\"]+)['\"]", self.src)
        self.assertGreater(len(globs), 0, "no -name globs found in tool")
        forbidden = [
            "dmi_release_2026-07.json",
            "dmi_release_2026-07_slack_plus.json",
            "dmi-2026-07-baseline.csv",
            "dmi-2026-07-slack_plus.parquet",
        ]
        import fnmatch
        for glob in globs:
            for name in forbidden:
                self.assertFalse(
                    fnmatch.fnmatch(name, glob),
                    f"§10: glob {glob!r} would match protected artifact "
                    f"{name!r}",
                )

    def test_requires_ssh_credentials_before_touching_remote(self):
        for var in ("DMI_REMOTE_HOST", "DMI_REMOTE_USER", "DMI_REMOTE_KEY"):
            self.assertIn(
                f'"${{{var}:?', self.src,
                f"§10: {var} must be required (parameter-expansion :? form).",
            )


class TestPythonInventoryToolIsReadOnly(unittest.TestCase):

    def setUp(self):
        self.assertTrue(PY_TOOL.exists(), f"{PY_TOOL} missing")
        self.src = PY_TOOL.read_text()

    def test_source_contains_no_mutating_verbs(self):
        # Grep the source for anything that could remove or overwrite a
        # file. `os.remove`, `os.unlink`, `Path.unlink`, `shutil.rmtree`,
        # `shutil.move`, `shutil.copy`, `open(..., 'w')`, `.write_text`,
        # `.write_bytes`, and the `rm` shell verb are all forbidden.
        # We allow `sys.stdout.write` (stdout is not a file we care
        # about) by scoping the regex.
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
            r"\bsubprocess\.",  # no shelling out either
        ]
        for pattern in forbidden:
            self.assertIsNone(
                re.search(pattern, self.src),
                f"§10: inventory tool contains forbidden mutating token "
                f"matching {pattern!r}",
            )

    def test_argparse_exposes_no_execute_or_confirm_flag(self):
        # The tool must never grow a mutating CLI surface. Inspect only
        # actual `add_argument` calls (the docstring is allowed to
        # discuss forbidden flags in its rationale).
        add_arg_calls = re.findall(
            r"add_argument\(\s*['\"]([^'\"]+)['\"]",
            self.src,
        )
        for token in ("execute", "confirm", "delete", "remove", "commit"):
            offenders = [f for f in add_arg_calls if token in f.lower()]
            self.assertEqual(
                offenders, [],
                f"§10: inventory tool must not expose --{token} flag "
                f"via argparse (found: {offenders}).",
            )

    def test_running_against_empty_dir_succeeds_and_reports_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(PY_TOOL), "--root", tmp, "--json"],
                capture_output=True, text=True, check=True,
            )
            report = json.loads(result.stdout)
            self.assertEqual(report["match_count"], 0)
            self.assertEqual(report["matches"], [])

    def test_running_against_seeded_dir_finds_only_withdrawn_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Seed: two withdrawn + two protected + one unrelated file.
            (tmp_path / "dmi_release_2026-01_core.json").write_text("{}")
            (tmp_path / "qa_report_2026-02_core.json").write_text("{}")
            (tmp_path / "dmi_release_2026-01.json").write_text("{}")            # Baseline
            (tmp_path / "dmi_release_2026-01_slack_plus.json").write_text("{}")  # Slack+
            (tmp_path / "README.md").write_text("nothing to see")

            result = subprocess.run(
                [sys.executable, str(PY_TOOL), "--root", tmp, "--json"],
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
        # `.git` and `deploy` are excluded so the inventory is not
        # polluted by staging or version-control mirrors.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for excluded in (".git", "deploy", "node_modules"):
                sub = tmp_path / excluded
                sub.mkdir()
                (sub / "dmi_release_2026-01_core.json").write_text("{}")

            result = subprocess.run(
                [sys.executable, str(PY_TOOL), "--root", tmp, "--json"],
                capture_output=True, text=True, check=True,
            )
            report = json.loads(result.stdout)
            self.assertEqual(
                report["match_count"], 0,
                "§10: matches under excluded dirs must be skipped.",
            )


if __name__ == "__main__":
    unittest.main()
