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
        """Re-hash, then compare, then delete — in that order.

        Scoped to the body of `cmd_execute`. An earlier version of this
        test searched whole-file substring offsets, which made it
        sensitive to unrelated docstring edits and blind to whether the
        ordering held inside the function that actually runs.
        """
        func = next(
            n for n in ast.walk(ast.parse(self.src))
            if isinstance(n, ast.FunctionDef) and n.name == "cmd_execute"
        )
        body = ast.get_source_segment(self.src, func) or ""
        self.assertIn("_remote_rehash(", body,
                      "§10: _remote_rehash call missing from execute.")
        self.assertIn("_remote_delete(", body,
                      "§10: _remote_delete call missing from execute.")
        self.assertIn("mismatches", body,
                      "§10: mismatch handling missing from execute.")
        self.assertLess(
            body.index("_remote_rehash("), body.index("_remote_delete("),
            "§10: sha256 re-hash must run before deletion.",
        )
        self.assertLess(
            body.index("mismatches"), body.index("_remote_delete("),
            "§10: mismatch check must precede deletion.",
        )
        # The delete must be unreachable when a mismatch was recorded:
        # the guard raises rather than merely logging.
        guard = body[body.index("mismatches"):body.index("_remote_delete(")]
        self.assertIn(
            "raise SystemExit", guard,
            "§10: a digest mismatch must abort the run, not just warn.",
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


# ---------------------------------------------------------------------------
# Round-3 §10 / §14: BEHAVIORAL coverage of the Core-withdrawal scope.
#
# The tests above this point are largely structural (they read the
# source and assert on its shape). Structural tests could not have
# caught the defect this section exists for: the tool's patterns
# classified `_u6.json` and `_with_ci.json` as Core and omitted
# `qa_report_*_core.json`, and every structural test still passed.
#
# These tests therefore exercise the real guard function and the real
# pattern sets against concrete remote-path records.
# ---------------------------------------------------------------------------

from scripts.withdraw_remote_artifacts import (  # noqa: E402
    CORE_NAME_REGEXES,
    NON_CORE_REGEXES,
    WITHDRAWN_PATTERNS,
    _inventory_digest,
    _refuse_protected,
    cmd_execute,
    cmd_reseal,
)
import argparse as _argparse  # noqa: E402
import fnmatch as _fnmatch  # noqa: E402

REMOTE_BASE = "/home/agiraces/dmianalysis"
REMOTE_OUTPUTS = f"{REMOTE_BASE}/data/outputs"


def _rec(name: str, sha: str = "a" * 64, size: int = 10) -> dict:
    """One inventory record for a file directly under data/outputs."""
    return {"path": f"{REMOTE_OUTPUTS}/{name}", "size": size, "sha256": sha}


class TestCoreInventoryScope(unittest.TestCase):
    """The inventory may contain ONLY Core artifacts."""

    def test_core_qa_reports_are_in_scope(self):
        """§10: `qa_report_*_core.json` was omitted by the old tool."""
        self.assertTrue(
            any(
                _fnmatch.fnmatch("qa_report_2026-03_core.json", pat)
                for pat in WITHDRAWN_PATTERNS
            ),
            "§10: qa_report_*_core.json must be inside the Core "
            "withdrawal scope; the historical tool omitted it.",
        )
        # And it must survive the guard, not merely match a pattern.
        _refuse_protected(
            [_rec("qa_report_2026-03_core.json")], REMOTE_BASE
        )

    def test_every_core_artifact_class_is_accepted(self):
        _refuse_protected(
            [
                _rec("dmi_release_2026-03_core.json"),
                _rec("dmi-2026-03-core.csv"),
                _rec("dmi-2026-03-core.parquet"),
                _rec("qa_report_2026-03_core.json"),
            ],
            REMOTE_BASE,
        )

    def test_u6_files_are_never_in_scope(self):
        """§10 + controlling decision: U-6 files are NOT Core."""
        self.assertFalse(
            any(
                _fnmatch.fnmatch("dmi_release_2024-11_u6.json", pat)
                for pat in WITHDRAWN_PATTERNS
            ),
            "§10: _u6 must not match any Core withdrawal pattern.",
        )
        with self.assertRaises(SystemExit) as ctx:
            _refuse_protected(
                [_rec("dmi_release_2024-11_u6.json")], REMOTE_BASE
            )
        self.assertIn("not Core", str(ctx.exception))

    def test_with_ci_files_are_never_in_scope(self):
        """§10 + controlling decision: with-CI files are NOT Core."""
        self.assertFalse(
            any(
                _fnmatch.fnmatch("dmi_release_2024-11_with_ci.json", pat)
                for pat in WITHDRAWN_PATTERNS
            ),
            "§10: _with_ci must not match any Core withdrawal pattern.",
        )
        with self.assertRaises(SystemExit) as ctx:
            _refuse_protected(
                [_rec("dmi_release_2024-11_with_ci.json")], REMOTE_BASE
            )
        self.assertIn("not Core", str(ctx.exception))

    def test_non_core_refusal_survives_a_pattern_regression(self):
        """Defence in depth.

        Even if a future edit re-added `_u6` to WITHDRAWN_PATTERNS, the
        guard must still refuse it. This is asserted directly against
        the guard so the protection does not depend on the match
        patterns being correct.
        """
        for name in (
            "dmi_release_2024-11_u6.json",
            "dmi_release_2024-11_with_ci.json",
            "dmi-2024-11_u6.csv",
        ):
            with self.subTest(name=name):
                with self.assertRaises(SystemExit):
                    _refuse_protected([_rec(name)], REMOTE_BASE)

    def test_baseline_and_slack_plus_are_refused(self):
        for name in (
            "dmi_release_2026-07.json",
            "dmi_release_2026-07_slack_plus.json",
            "dmi-2026-07-baseline.csv",
            "dmi-2026-07-slack_plus.parquet",
            "dmi-2026-01.csv",
        ):
            with self.subTest(name=name):
                with self.assertRaises(SystemExit):
                    _refuse_protected([_rec(name)], REMOTE_BASE)

    def test_manifests_and_release_notes_are_refused(self):
        """§10: manifests, release notes must never be in the inventory."""
        for name in (
            "releases.json",
            "latest.json",
            "specifications.json",
            "health.json",
            "2026-07.html",
        ):
            with self.subTest(name=name):
                with self.assertRaises(SystemExit):
                    _refuse_protected([_rec(name)], REMOTE_BASE)

    def test_unexpected_names_fail_closed(self):
        """Scope is an allow-list, not a deny-list.

        An unrecognised name must be refused because it does not
        positively match a Core pattern — not silently accepted.
        """
        for name in (
            "random_file.json",
            "dmi_release_2026-07_core.json.bak",
            "notes.txt",
            "dmi_core_release.json",
        ):
            with self.subTest(name=name):
                with self.assertRaises(SystemExit):
                    _refuse_protected([_rec(name)], REMOTE_BASE)

    def test_historical_directory_paths_are_refused(self):
        """§10: historical directories are out of scope."""
        rec = {
            "path": f"{REMOTE_OUTPUTS}/published/historical/"
                    f"dmi_release_2017-10.json",
            "size": 10,
            "sha256": "b" * 64,
        }
        with self.assertRaises(SystemExit):
            _refuse_protected([rec], REMOTE_BASE)

    def test_paths_outside_remote_base_are_refused(self):
        rec = {
            "path": "/etc/dmi_release_2026-03_core.json",
            "size": 10,
            "sha256": "c" * 64,
        }
        with self.assertRaises(SystemExit) as ctx:
            _refuse_protected([rec], REMOTE_BASE)
        self.assertIn("outside remote_base", str(ctx.exception))

    def test_core_and_non_core_regex_sets_are_disjoint(self):
        """No name may be both Core and non-Core."""
        core = [re.compile(p) for p in CORE_NAME_REGEXES]
        non_core = [re.compile(p) for p in NON_CORE_REGEXES]
        for name in (
            "dmi_release_2024-11_core.json",
            "dmi-2024-11-core.csv",
            "dmi-2024-11-core.parquet",
            "qa_report_2024-11_core.json",
        ):
            with self.subTest(name=name):
                self.assertTrue(any(rx.match(name) for rx in core))
                self.assertFalse(any(rx.search(name) for rx in non_core))


class TestExactInventoryConsumption(unittest.TestCase):
    """Phase 2 must consume the reviewed inventory, not rediscover targets."""

    def test_execute_never_reruns_find(self):
        """§10: no target rediscovery at deletion time.

        `cmd_execute` must not call the enumeration helper. Asserted on
        the parsed call graph rather than a substring so a renamed or
        reformatted call cannot slip through.
        """
        tree = ast.parse(REMOTE_TOOL.read_text())
        func = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "cmd_execute"
        )
        called = {
            n.func.id
            for n in ast.walk(func)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        self.assertNotIn(
            "_remote_find_and_hash", called,
            "§10: execute must not re-enumerate remote targets; it must "
            "consume the exact reviewed inventory.",
        )

    def test_only_inventory_module_enumerates(self):
        """`find` may appear only in the phase-1 enumeration helper."""
        tree = ast.parse(REMOTE_TOOL.read_text())
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if node.name in ("_remote_find_and_hash",):
                continue
            body = ast.get_source_segment(
                REMOTE_TOOL.read_text(), node
            ) or ""
            if "find " in body and "-name" in body:
                offenders.append(node.name)
        self.assertEqual(
            offenders, [],
            f"§10: only the phase-1 enumerator may build a remote find "
            f"expression; offenders: {offenders}",
        )

    def test_integrity_hash_is_recorded_and_covers_the_file_list(self):
        a = _inventory_digest(
            REMOTE_BASE, REMOTE_OUTPUTS,
            [_rec("dmi_release_2026-03_core.json")],
        )
        b = _inventory_digest(
            REMOTE_BASE, REMOTE_OUTPUTS,
            [_rec("dmi_release_2026-03_core.json"),
             _rec("dmi_release_2026-04_core.json")],
        )
        self.assertNotEqual(
            a, b, "digest must change when the reviewed list changes",
        )

    def test_integrity_hash_detects_a_swapped_path(self):
        a = _inventory_digest(
            REMOTE_BASE, REMOTE_OUTPUTS,
            [_rec("dmi_release_2026-03_core.json")],
        )
        b = _inventory_digest(
            REMOTE_BASE, REMOTE_OUTPUTS,
            [_rec("dmi_release_2026-04_core.json")],
        )
        self.assertNotEqual(a, b)

    def test_integrity_hash_is_stable_for_the_same_decision(self):
        recs = [_rec("dmi_release_2026-03_core.json")]
        self.assertEqual(
            _inventory_digest(REMOTE_BASE, REMOTE_OUTPUTS, recs),
            _inventory_digest(REMOTE_BASE, REMOTE_OUTPUTS, recs),
        )

    def test_integrity_hash_ignores_generation_timestamp(self):
        """The digest identifies the decision, not the run."""
        recs = [_rec("dmi_release_2026-03_core.json")]
        d1 = _inventory_digest(REMOTE_BASE, REMOTE_OUTPUTS, recs)
        inv = {
            "generated_at_utc": "2026-01-01T00:00:00Z",
            "remote_base": REMOTE_BASE,
            "remote_outputs": REMOTE_OUTPUTS,
            "files": recs,
        }
        d2 = _inventory_digest(
            inv["remote_base"], inv["remote_outputs"], inv["files"]
        )
        self.assertEqual(d1, d2)


class TestExecuteFailsClosedWithoutTouchingRemote(unittest.TestCase):
    """Phase 2's gates must fire before any SSH I/O.

    None of these tests can contact a remote: no DMI_REMOTE_* variables
    are set, so if a gate did NOT fire first the run would fail with a
    missing-env error instead. Each test asserts on the specific
    refusal message, which proves which gate stopped it.
    """

    def _write(self, tmp: Path, inventory: dict) -> Path:
        path = tmp / "inv.json"
        path.write_text(json.dumps(inventory, indent=2))
        return path

    def test_missing_confirm_is_refused_before_any_ssh(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), {
                "remote_base": REMOTE_BASE,
                "remote_outputs": REMOTE_OUTPUTS,
                "files": [_rec("dmi_release_2026-03_core.json")],
                "integrity_sha256": "irrelevant",
            })
            args = _argparse.Namespace(inventory=str(path), confirm=False)
            with self.assertRaises(SystemExit) as ctx:
                cmd_execute(args)
            self.assertIn("--confirm", str(ctx.exception))
            self.assertIn("No files were touched", str(ctx.exception))

    def test_default_namespace_is_non_mutating(self):
        """§14: default invocation is non-mutating.

        Parsing `execute` without `--confirm` must yield confirm=False,
        so the default path is the refusal path.
        """
        from scripts.withdraw_remote_artifacts import main as _main
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), {
                "remote_base": REMOTE_BASE,
                "files": [_rec("dmi_release_2026-03_core.json")],
                "integrity_sha256": "x",
            })
            with self.assertRaises(SystemExit) as ctx:
                _main(["execute", "--inventory", str(path)])
            self.assertIn("--confirm", str(ctx.exception))

    def test_empty_inventory_deletes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), {
                "remote_base": REMOTE_BASE,
                "files": [],
                "integrity_sha256": "x",
            })
            args = _argparse.Namespace(inventory=str(path), confirm=True)
            self.assertEqual(cmd_execute(args), 0)


class TestReseal(unittest.TestCase):
    """`reseal` re-approves a pruned inventory without touching the remote."""

    def test_reseal_updates_the_digest_to_match_pruned_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = [
                _rec("dmi_release_2026-03_core.json"),
                _rec("dmi_release_2026-04_core.json"),
            ]
            inv = {
                "remote_base": REMOTE_BASE,
                "remote_outputs": REMOTE_OUTPUTS,
                "files": files,
                "integrity_sha256": _inventory_digest(
                    REMOTE_BASE, REMOTE_OUTPUTS, files
                ),
            }
            path = Path(tmp) / "inv.json"
            path.write_text(json.dumps(inv, indent=2))

            # Reviewer prunes one entry.
            inv["files"] = files[:1]
            path.write_text(json.dumps(inv, indent=2))

            cmd_reseal(_argparse.Namespace(inventory=str(path)))
            resealed = json.loads(path.read_text())
            self.assertEqual(
                resealed["integrity_sha256"],
                _inventory_digest(REMOTE_BASE, REMOTE_OUTPUTS, files[:1]),
            )

    def test_reseal_refuses_out_of_scope_entries(self):
        """Reseal must not be a way to smuggle non-Core paths through."""
        with tempfile.TemporaryDirectory() as tmp:
            files = [_rec("dmi_release_2024-11_u6.json")]
            path = Path(tmp) / "inv.json"
            path.write_text(json.dumps({
                "remote_base": REMOTE_BASE,
                "remote_outputs": REMOTE_OUTPUTS,
                "files": files,
            }, indent=2))
            with self.assertRaises(SystemExit) as ctx:
                cmd_reseal(_argparse.Namespace(inventory=str(path)))
            self.assertIn("not Core", str(ctx.exception))

    def test_reseal_does_not_import_or_call_delete(self):
        tree = ast.parse(REMOTE_TOOL.read_text())
        func = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "cmd_reseal"
        )
        called = {
            n.func.id
            for n in ast.walk(func)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        for forbidden in ("_remote_delete", "_remote_rehash",
                          "_remote_find_and_hash", "_load_ssh_config"):
            self.assertNotIn(
                forbidden, called,
                f"reseal must be local-only; it called {forbidden}",
            )


class TestPostDeletionVerification(unittest.TestCase):
    """§10: every inventoried path is verified absent after deletion."""

    def test_execute_verifies_absence_after_delete(self):
        src = REMOTE_TOOL.read_text()
        tree = ast.parse(src)
        func = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "cmd_execute"
        )
        called = [
            n.func.id
            for n in ast.walk(func)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        ]
        self.assertIn(
            "_remote_existing", called,
            "§10: execute must verify every inventoried path afterward.",
        )
        body = ast.get_source_segment(src, func) or ""
        self.assertLess(
            body.index("_remote_delete"), body.index("_remote_existing"),
            "verification must come after deletion.",
        )

    def test_survivors_cause_a_failure(self):
        src = ast.get_source_segment(
            REMOTE_TOOL.read_text(),
            next(
                n for n in ast.walk(ast.parse(REMOTE_TOOL.read_text()))
                if isinstance(n, ast.FunctionDef) and n.name == "cmd_execute"
            ),
        ) or ""
        self.assertIn("survivors", src)
        self.assertIn("post-deletion verification failed", src)
