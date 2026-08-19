#!/usr/bin/env python3
"""Phase-2 Core withdrawal — executed 2026-08-19, workflow since retired.

The destructive workflow ran successfully on 2026-08-19 (run
32214973867) and was then removed from `.github/workflows`. What remains
testable, and what this module now covers, is:

- the sealed inventory that controlled the operation, and the verifier
  that gated it — both still in the repository and still the record of
  what was authorized;
- the backup verification logic and the partial-deletion evidence path in
  the withdrawal tool, which stay useful and must not silently rot;
- the durable evidence of the completed run;
- the *absence* of any runnable destructive entry point.

The structural tests that inspected the workflow file were removed with
the workflow. Keeping them would have meant either resurrecting a
destructive workflow to satisfy tests, or tests asserting about a file
that does not exist.


The interesting question is not whether it works but what the worst
outcome of a dispatch is.  The answer should be: delete exactly the 21 reviewed files,
after a verified backup, or provide a recoverable state.

Pre-deletion failures delete nothing. Once deletion begins, an interruption
can leave partial state; the workflow records the deleted and surviving sets,
runs post-state verification, and preserves the verified backup for a
separately authorized recovery decision.

That is a structural property. It comes from the inventory path, hashes,
count, remote base and subcommand all being constants rather than inputs,
from the ordering of the gates, and from what is absent. So most of these
tests read the workflow and assert on its shape — checking executable
lines, since the workflow's comments necessarily discuss the dangerous
operations they prevent.

The inventory checks are behavioural: they run the real verifier against
the real committed file and against deliberately corrupted copies.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
INVENTORY = ROOT / "docs" / "repair" / "inventories" / "core-withdrawal-2026-08-19.json"

EXPECTED_FILE_SHA = "ce1e55939c2c10c04c18cb96b2457db802241f9bdfcdf484438f5250ba84e11c"
EXPECTED_SEAL = "3812991fa2ed52e4e3cfcc543c28c3f1769c20a3033c307abdb8085fd1887fd6"
CONFIRMATION = "WITHDRAW-CORE-21-3812991FA2ED52E4"


def _on_block(doc: dict) -> dict:
    return doc.get("on") or doc.get(True)


def _steps(doc: dict) -> list:
    return [s for j in (doc.get("jobs") or {}).values() for s in (j.get("steps") or [])]


def _run_lines(doc: dict) -> list[str]:
    out = []
    for step in _steps(doc):
        for line in str(step.get("run", "")).splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                out.append(stripped)
    return out


# ---------------------------------------------------------------------------
# The committed inventory
# ---------------------------------------------------------------------------

class TestCommittedInventoryIsTheReviewedOne(unittest.TestCase):

    def test_inventory_is_committed(self):
        self.assertTrue(INVENTORY.is_file())

    def test_file_hash_matches(self):
        actual = hashlib.sha256(INVENTORY.read_bytes()).hexdigest()
        self.assertEqual(actual, EXPECTED_FILE_SHA)

    def test_seal_matches_and_recomputes(self):
        from scripts.withdraw_remote_artifacts import _inventory_digest
        inv = json.loads(INVENTORY.read_text())
        self.assertEqual(inv["integrity_sha256"], EXPECTED_SEAL)
        self.assertEqual(
            _inventory_digest(inv["remote_base"], inv["remote_outputs"],
                              inv["files"]),
            EXPECTED_SEAL,
        )

    def test_shape(self):
        inv = json.loads(INVENTORY.read_text())
        self.assertEqual(inv["schema_version"], "1.0.0")
        self.assertEqual(len(inv["files"]), 21)
        self.assertEqual(sum(f["size"] for f in inv["files"]), 63_598)
        self.assertEqual(inv["remote_base"], "/home/agiraces/dmianalysis")
        self.assertEqual(inv["remote_outputs"],
                         "/home/agiraces/dmianalysis/data/outputs")

    def test_composition_and_periods(self):
        inv = json.loads(INVENTORY.read_text())
        names = [f["path"].rsplit("/", 1)[-1] for f in inv["files"]]
        raw = [n for n in names if re.match(r"^dmi_release_\d{4}-\d{2}_core\.json$", n)]
        csv = [n for n in names if n.endswith("-core.csv")]
        parq = [n for n in names if n.endswith("-core.parquet")]
        qa = [n for n in names if n.startswith("qa_report_")]
        self.assertEqual((len(raw), len(csv), len(parq), len(qa)), (6, 5, 5, 5))
        periods = lambda ns: sorted({re.search(r"\d{4}-\d{2}", n).group() for n in ns})
        self.assertEqual(periods(raw),
                         ["2024-11", "2026-03", "2026-04", "2026-05",
                          "2026-06", "2026-07"])
        for group in (csv, parq, qa):
            self.assertEqual(periods(group),
                             ["2026-03", "2026-04", "2026-05", "2026-06",
                              "2026-07"])

    def test_not_resealed(self):
        self.assertNotIn("resealed_at_utc", json.loads(INVENTORY.read_text()))

    def test_real_verifier_passes_on_the_committed_file(self):
        from scripts.verify_withdrawal_inventory import verify
        problems, report = verify(INVENTORY)
        self.assertEqual(problems, [], f"verifier rejected it: {problems}")
        self.assertTrue(report["verified"])


class TestVerifierRejectsTamperedInventories(unittest.TestCase):
    """Every corruption must fail BEFORE any SSH connection.

    Each test isolates ONE layer and asserts the specific message that
    layer produces. That distinction matters more than it looks.

    Mutation testing caught the naive version of this class: the tests
    doctored an inventory and asserted only "some problem was reported".
    But doctoring the file also breaks the file hash and the seal, so a
    problem was always reported — and disabling the Core-scope check
    entirely still passed every test. Eight separate controls were
    unverified while appearing covered.

    So `_verify_isolated` re-seals the doctored document and pins the
    identity constants to it, satisfying the upstream gates honestly, and
    every assertion names the message it expects. If the layer under test
    stops working, its test fails and no other gate can mask it.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.original = json.loads(INVENTORY.read_text())

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, doc) -> Path:
        path = self.dir / "inv.json"
        path.write_text(json.dumps(doc, indent=2) + "\n")
        return path

    def _verify(self, doc):
        """Verification exactly as the workflow runs it."""
        from scripts.verify_withdrawal_inventory import verify
        return verify(self._write(doc))[0]

    def _verify_isolated(self, doc, *, keep_count=False, keep_seal=False):
        """Satisfy every gate except the one under test."""
        from scripts.withdraw_remote_artifacts import _inventory_digest
        from scripts import verify_withdrawal_inventory as module

        doc = copy.deepcopy(doc)
        if not keep_seal:
            doc["integrity_sha256"] = _inventory_digest(
                doc.get("remote_base", ""), doc.get("remote_outputs", ""),
                doc.get("files", []),
            )
        path = self._write(doc)

        saved = (module.EXPECTED_FILE_SHA256,
                 module.EXPECTED_INTEGRITY_SHA256,
                 module.EXPECTED_COUNT,
                 module.EXPECTED_TOTAL_BYTES,
                 module.EXPECTED_REMOTE_BASE,
                 module.EXPECTED_REMOTE_OUTPUTS)
        module.EXPECTED_FILE_SHA256 = hashlib.sha256(path.read_bytes()).hexdigest()
        if not keep_seal:
            module.EXPECTED_INTEGRITY_SHA256 = doc["integrity_sha256"]
        if not keep_count:
            files = doc.get("files", [])
            module.EXPECTED_COUNT = len(files)
            module.EXPECTED_TOTAL_BYTES = sum(
                f["size"] for f in files
                if isinstance(f, dict) and isinstance(f.get("size"), int)
                and not isinstance(f.get("size"), bool) and f["size"] >= 0
            )
        try:
            return module.verify(path)[0]
        finally:
            (module.EXPECTED_FILE_SHA256,
             module.EXPECTED_INTEGRITY_SHA256,
             module.EXPECTED_COUNT,
             module.EXPECTED_TOTAL_BYTES,
             module.EXPECTED_REMOTE_BASE,
             module.EXPECTED_REMOTE_OUTPUTS) = saved

    def _assert_reports(self, problems, needle):
        self.assertTrue(
            any(needle in p for p in problems),
            f"expected a problem mentioning {needle!r}; got: {problems}",
        )

    # -- identity gate ---------------------------------------------------

    def test_any_edit_breaks_the_file_hash(self):
        doc = copy.deepcopy(self.original)
        doc["files"][0]["size"] += 1
        self._assert_reports(self._verify(doc), "file SHA-256")

    def test_identity_gate_returns_before_anything_else(self):
        """A wrong file is rejected on identity, not on its contents."""
        doc = copy.deepcopy(self.original)
        doc["files"] = []
        problems = self._verify(doc)
        self.assertEqual(len(problems), 1, problems)
        self._assert_reports(problems, "file SHA-256")

    # -- integrity gate --------------------------------------------------

    def test_broken_seal_is_rejected(self):
        doc = copy.deepcopy(self.original)
        doc["integrity_sha256"] = "0" * 64
        self._assert_reports(
            self._verify_isolated(doc, keep_seal=True), "seal does not recompute"
        )

    def test_edited_entry_breaks_the_seal(self):
        doc = copy.deepcopy(self.original)
        doc["files"][3]["sha256"] = "b" * 64
        self._assert_reports(
            self._verify_isolated(doc, keep_seal=True), "seal does not recompute"
        )

    # -- shape -----------------------------------------------------------

    def test_wrong_count_is_rejected(self):
        doc = copy.deepcopy(self.original)
        doc["files"] = doc["files"][:20]
        problems = self._verify_isolated(doc, keep_count=True)
        # Two independent checks cover the count: the declared list
        # length and the number of unique paths. Assert on the first
        # specifically, so disabling it is not masked by the second.
        self._assert_reports(problems, "inventory lists 20 file(s)")
        self._assert_reports(problems, "20 unique path(s)")

    def test_extra_entry_is_rejected(self):
        doc = copy.deepcopy(self.original)
        extra = copy.deepcopy(doc["files"][0])
        extra["path"] = extra["path"].replace("2026-03", "2026-08")
        doc["files"].append(extra)
        doc["files"].sort(key=lambda r: r["path"])
        self._assert_reports(self._verify_isolated(doc, keep_count=True),
                             "inventory lists 22 file(s)")

    def test_wrong_remote_base_is_rejected(self):
        doc = copy.deepcopy(self.original)
        doc["remote_base"] = "/home/someone-else"
        self._assert_reports(self._verify_isolated(doc), "remote_base is")

    def test_wrong_schema_version_is_rejected(self):
        doc = copy.deepcopy(self.original)
        doc["schema_version"] = "2.0.0"
        self._assert_reports(self._verify_isolated(doc), "schema_version is")

    def test_unsorted_entries_are_rejected(self):
        doc = copy.deepcopy(self.original)
        doc["files"] = list(reversed(doc["files"]))
        self._assert_reports(self._verify_isolated(doc), "sorted path order")

    def test_resealed_inventory_is_rejected(self):
        doc = copy.deepcopy(self.original)
        doc["resealed_at_utc"] = "2026-08-19T00:00:00Z"
        self._assert_reports(self._verify_isolated(doc), "resealed_at_utc")

    def test_duplicate_entry_is_rejected(self):
        doc = copy.deepcopy(self.original)
        doc["files"].append(copy.deepcopy(doc["files"][0]))
        doc["files"].sort(key=lambda r: r["path"])
        self._assert_reports(self._verify_isolated(doc), "duplicate entry")

    # -- scope -----------------------------------------------------------

    def test_out_of_scope_name_is_rejected(self):
        for name in ("dmi_release_2026-07.json",
                     "dmi_release_2026-07_slack_plus.json",
                     "dmi-2026-07-baseline.csv",
                     "releases.json", "latest.json",
                     "specifications.json", "health.json",
                     "2026-07.html"):
            with self.subTest(name=name):
                doc = copy.deepcopy(self.original)
                doc["files"][0]["path"] = f"{doc['remote_outputs']}/{name}"
                doc["files"].sort(key=lambda r: r["path"])
                self._assert_reports(
                    self._verify_isolated(doc),
                    "does not match any Core artifact class",
                )

    def test_forbidden_marker_is_rejected_independently(self):
        """`_u6` / `_with_ci` are refused by name, not only by pattern."""
        for name in ("dmi_release_2024-11_u6.json",
                     "dmi_release_2024-11_with_ci.json"):
            with self.subTest(name=name):
                doc = copy.deepcopy(self.original)
                doc["files"][0]["path"] = f"{doc['remote_outputs']}/{name}"
                doc["files"].sort(key=lambda r: r["path"])
                self._assert_reports(self._verify_isolated(doc),
                                     "forbidden marker")

    def test_traversal_is_rejected(self):
        doc = copy.deepcopy(self.original)
        doc["files"][0]["path"] = (
            f"{doc['remote_outputs']}/../../etc/dmi_release_2026-07_core.json"
        )
        doc["files"].sort(key=lambda r: r["path"])
        self._assert_reports(self._verify_isolated(doc), "direct child")

    def test_subdirectory_path_is_rejected(self):
        doc = copy.deepcopy(self.original)
        doc["files"][0]["path"] = (
            f"{doc['remote_outputs']}/nested/dmi_release_2026-07_core.json"
        )
        doc["files"].sort(key=lambda r: r["path"])
        self._assert_reports(self._verify_isolated(doc), "direct child")

    def test_path_outside_outputs_is_rejected(self):
        doc = copy.deepcopy(self.original)
        doc["files"][0]["path"] = "/etc/dmi_release_2026-07_core.json"
        doc["files"].sort(key=lambda r: r["path"])
        self._assert_reports(self._verify_isolated(doc), "outside")

    def test_historical_archive_path_is_rejected(self):
        doc = copy.deepcopy(self.original)
        doc["files"][0]["path"] = (
            f"{doc['remote_outputs']}/published/historical/"
            f"dmi_release_2017-10_core.json"
        )
        doc["files"].sort(key=lambda r: r["path"])
        self.assertTrue(self._verify_isolated(doc))

    # -- per-entry field validation --------------------------------------

    def test_negative_or_nonint_size_is_rejected(self):
        for bad in (-1, "12", None, 1.5, True):
            with self.subTest(size=bad):
                doc = copy.deepcopy(self.original)
                doc["files"][0]["size"] = bad
                self._assert_reports(self._verify_isolated(doc),
                                     "nonnegative integer")

    def test_bad_sha256_is_rejected(self):
        for bad in ("ABC", "g" * 64, "A" * 64, "", None, "a" * 63):
            with self.subTest(sha=bad):
                doc = copy.deepcopy(self.original)
                doc["files"][0]["sha256"] = bad
                self._assert_reports(self._verify_isolated(doc),
                                     "lowercase 64-char hex")

    def test_missing_file_is_rejected(self):
        from scripts.verify_withdrawal_inventory import verify
        problems, _ = verify(self.dir / "does-not-exist.json")
        self._assert_reports(problems, "not found")

    def test_unparseable_file_is_rejected(self):
        from scripts import verify_withdrawal_inventory as module
        path = self.dir / "inv.json"
        path.write_text("{ not json")
        saved = module.EXPECTED_FILE_SHA256
        module.EXPECTED_FILE_SHA256 = hashlib.sha256(path.read_bytes()).hexdigest()
        try:
            problems = module.verify(path)[0]
        finally:
            module.EXPECTED_FILE_SHA256 = saved
        self._assert_reports(problems, "not valid JSON")

    def test_the_real_inventory_still_passes_after_all_this(self):
        """Non-vacuity: the genuine file must not be rejected."""
        from scripts.verify_withdrawal_inventory import verify
        self.assertEqual(verify(INVENTORY)[0], [])


# ---------------------------------------------------------------------------
# The workflow
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Backup behaviour
# ---------------------------------------------------------------------------

class TestBackupVerification(unittest.TestCase):
    """The backup must match the inventory exactly, or fail closed."""

    def setUp(self):
        self.inv = json.loads(INVENTORY.read_text())
        self.files = self.inv["files"]

    def _fetched_matching(self) -> dict:
        """Synthetic content whose digests match a doctored inventory."""
        fetched = {}
        files = []
        for record in self.files:
            data = record["path"].encode()
            fetched[record["path"]] = data
            files.append({
                "path": record["path"],
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            })
        return fetched, files

    def test_exact_match_passes(self):
        from scripts.backup_withdrawal_targets import verify_against_inventory
        fetched, files = self._fetched_matching()
        self.assertEqual(verify_against_inventory(fetched, files), [])

    def test_missing_file_fails(self):
        from scripts.backup_withdrawal_targets import verify_against_inventory
        fetched, files = self._fetched_matching()
        fetched.pop(files[0]["path"])
        problems = verify_against_inventory(fetched, files)
        self.assertTrue(any("missing from backup" in p for p in problems))

    def test_extra_file_fails(self):
        from scripts.backup_withdrawal_targets import verify_against_inventory
        fetched, files = self._fetched_matching()
        fetched["/home/agiraces/dmianalysis/data/outputs/surprise.json"] = b"x"
        problems = verify_against_inventory(fetched, files)
        self.assertTrue(any("not in the inventory" in p for p in problems))

    def test_changed_content_fails(self):
        from scripts.backup_withdrawal_targets import verify_against_inventory
        fetched, files = self._fetched_matching()
        fetched[files[0]["path"]] = b"tampered"
        problems = verify_against_inventory(fetched, files)
        self.assertTrue(any("sha256 mismatch" in p or "size mismatch" in p
                            for p in problems))

    def test_archive_is_deterministic(self):
        from scripts.backup_withdrawal_targets import write_archive
        fetched, _files = self._fetched_matching()
        with tempfile.TemporaryDirectory() as tmp:
            a = write_archive(fetched, Path(tmp) / "a.tar.gz")
            b = write_archive(fetched, Path(tmp) / "b.tar.gz")
        self.assertEqual(a, b, "archive digest must not depend on filename")

    def test_backup_derives_paths_only_from_the_inventory(self):
        import ast
        src = (ROOT / "scripts" / "backup_withdrawal_targets.py").read_text()
        docstrings = set()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc:
                    docstrings.add(doc)
        literals = [n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and n.value not in docstrings]
        for bad in ("*", "*.json", "data/outputs/*"):
            self.assertNotIn(bad, literals, "no glob may reach the remote")

    def test_backup_refuses_when_verification_fails(self):
        """`main` must not archive an unverified download."""
        import ast
        src = (ROOT / "scripts" / "backup_withdrawal_targets.py").read_text()
        func = next(n for n in ast.walk(ast.parse(src))
                    if isinstance(n, ast.FunctionDef) and n.name == "main")
        body = ast.get_source_segment(src, func)
        self.assertLess(body.index("verify_against_inventory"),
                        body.index("write_archive"))


# ---------------------------------------------------------------------------
# Documentation templates
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Merge-blocker fixes: pinned checkout, partial-deletion evidence,
# fail-closed public verification, hardened cleanup.
# ---------------------------------------------------------------------------


class TestPartialDeletionPreservesEvidence(unittest.TestCase):
    """A failed deletion must report exactly what it already removed."""

    def _run_delete(self, returncode: int, stdout: str, stderr: str = "boom"):
        """Drive `_remote_delete` with a stubbed subprocess result."""
        import subprocess as sp
        from scripts import withdraw_remote_artifacts as tool

        paths = [f"/base/data/outputs/f{i}.json" for i in range(5)]
        completed = sp.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr=stderr
        )
        original = tool.subprocess.run
        tool.subprocess.run = lambda *a, **k: completed
        import io, contextlib
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                try:
                    tool._remote_delete([], paths)
                    raised = None
                except SystemExit as exc:
                    raised = exc
        finally:
            tool.subprocess.run = original
        return raised, buffer.getvalue(), paths

    def test_partial_failure_reports_what_was_deleted(self):
        stdout = ("removed /base/data/outputs/f0.json\n"
                  "removed /base/data/outputs/f1.json\n")
        raised, printed, _paths = self._run_delete(1, stdout)
        self.assertIsNotNone(raised, "a failed deletion must raise")
        message = str(raised)
        self.assertIn("deleting 2 of 5", message)
        self.assertIn("THE OPERATION IS PARTIAL", message)
        self.assertIn("f0.json", message)
        self.assertIn("f1.json", message)

    def test_partial_failure_reports_what_was_not_deleted(self):
        stdout = "removed /base/data/outputs/f0.json\n"
        raised, _printed, _paths = self._run_delete(1, stdout)
        message = str(raised)
        self.assertIn("not deleted (4)", message)
        self.assertIn("f4.json", message)

    def test_removed_list_is_printed_even_on_failure(self):
        """The captured stdout must reach the log, not be discarded."""
        stdout = "removed /base/data/outputs/f0.json\n"
        _raised, printed, _paths = self._run_delete(1, stdout)
        self.assertIn("removed /base/data/outputs/f0.json", printed)

    def test_failure_tells_the_operator_not_to_improvise(self):
        raised, _printed, _paths = self._run_delete(1, "")
        self.assertIn("separately authorized", str(raised))
        self.assertIn("backup artifact", str(raised))

    def test_success_still_prints_the_removed_list(self):
        stdout = "".join(
            f"removed /base/data/outputs/f{i}.json\n" for i in range(5)
        )
        raised, printed, _paths = self._run_delete(0, stdout)
        self.assertIsNone(raised)
        self.assertIn("f4.json", printed)




# ---------------------------------------------------------------------------
# Retirement: no runnable destructive entry point may remain.
# ---------------------------------------------------------------------------

WORKFLOWS_DIR = ROOT / ".github" / "workflows"
EVIDENCE_DIR = ROOT / "docs" / "repair" / "evidence" / "core-withdrawal-2026-08-19"
WITHDRAWAL_LOG = ROOT / "docs" / "repair" / "REMOTE_WITHDRAWAL_LOG_2026-08-19.md"


class TestPhase2IsRetired(unittest.TestCase):
    """The withdrawal is done; the destructive path must not be dispatchable.

    Retirement is a property of the Actions surface, not of intent. A
    workflow file present in `.github/workflows` is offered in the
    Actions UI whether or not anyone means to use it, so the test is that
    no such file exists — not that it is disabled or commented out.
    """

    def test_the_destructive_workflow_file_is_gone(self):
        self.assertFalse(
            (WORKFLOWS_DIR / "execute_withdrawn_core.yml").exists(),
            "the Phase-2 destructive workflow must not remain dispatchable",
        )

    def test_no_workflow_invokes_the_execute_subcommand(self):
        import yaml as _yaml
        offenders = []
        for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
            doc = _yaml.safe_load(path.read_text())
            for job in (doc.get("jobs") or {}).values():
                for step in (job.get("steps") or []):
                    for line in str(step.get("run", "")).splitlines():
                        stripped = line.strip()
                        if stripped.startswith("#"):
                            continue
                        if "withdraw_remote_artifacts" in stripped and \
                                "execute" in stripped:
                            offenders.append(f"{path.name}: {stripped}")
        self.assertEqual(
            offenders, [],
            f"no workflow may invoke the destructive subcommand: {offenders}",
        )

    def test_no_workflow_uses_the_confirmation_phrase(self):
        """The phrase existed only to authorize the destructive run."""
        offenders = [
            path.name for path in sorted(WORKFLOWS_DIR.glob("*.yml"))
            if CONFIRMATION in path.read_text()
        ]
        self.assertEqual(offenders, [], f"offenders: {offenders}")

    def test_no_workflow_can_delete_or_restore_remote_files(self):
        import yaml as _yaml
        offenders = []
        for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
            doc = _yaml.safe_load(path.read_text())
            for job in (doc.get("jobs") or {}).values():
                for step in (job.get("steps") or []):
                    for line in str(step.get("run", "")).splitlines():
                        stripped = line.strip()
                        if stripped.startswith("#") or "ssh" not in stripped:
                            continue
                        if " rm " in stripped or stripped.endswith(" rm"):
                            offenders.append(f"{path.name}: {stripped}")
        self.assertEqual(offenders, [], f"offenders: {offenders}")

    def test_the_tool_itself_is_retained_for_audit(self):
        """Retiring the workflow must not delete the audited implementation."""
        self.assertTrue(
            (ROOT / "scripts" / "withdraw_remote_artifacts.py").is_file(),
            "the tool is the record of what ran; keep it",
        )

    def test_read_only_verification_remains_available(self):
        self.assertTrue(
            (WORKFLOWS_DIR / "verify_core_withdrawal_public.yml").is_file(),
            "retiring the destructive path must not remove read-only "
            "verification",
        )

    def test_inventory_workflow_remains_available(self):
        self.assertTrue((WORKFLOWS_DIR / "inventory_withdrawn_core.yml").is_file())


class TestDurableEvidenceOfTheCompletedRun(unittest.TestCase):
    """The evidence must record what actually happened, including the 403."""

    EXPECTED_FILES = (
        "pre-execution-verification.json",
        "backup-artifact.json",
        "backup-manifest.json",
        "execution-log.txt",
        "origin-post-check.json",
        "public-http-status.json",
        "operational-surface.json",
    )

    def test_evidence_directory_exists(self):
        self.assertTrue(EVIDENCE_DIR.is_dir())

    def test_every_expected_evidence_file_is_committed(self):
        missing = [f for f in self.EXPECTED_FILES
                   if not (EVIDENCE_DIR / f).is_file()]
        self.assertEqual(missing, [], f"missing evidence: {missing}")

    def test_pre_execution_verification_passed(self):
        doc = json.loads((EVIDENCE_DIR / "pre-execution-verification.json").read_text())
        self.assertTrue(doc["verified"])
        self.assertEqual(doc["problems"], [])
        self.assertEqual(doc["file_sha256"], EXPECTED_FILE_SHA)
        self.assertEqual(doc["integrity_sha256"], EXPECTED_SEAL)
        self.assertEqual(doc["integrity_sha256_recomputed"], EXPECTED_SEAL)
        self.assertEqual(doc["file_count"], 21)
        self.assertEqual(doc["total_bytes"], 63_598)

    def test_origin_post_check_shows_a_complete_withdrawal(self):
        doc = json.loads((EVIDENCE_DIR / "origin-post-check.json").read_text())
        self.assertTrue(doc["all_withdrawn_absent"])
        self.assertTrue(doc["all_operational_present"])
        self.assertEqual(doc["withdrawn_expected_absent"], 21)
        self.assertEqual(doc["withdrawn_still_present"], [])
        self.assertEqual(doc["operational_expected_present"], 15)
        self.assertEqual(doc["operational_missing"], [])
        self.assertEqual(doc["checked_at_utc"], "2026-08-19T04:14:49Z")

    def test_execution_log_records_21_removals(self):
        text = (EVIDENCE_DIR / "execution-log.txt").read_text()
        removed = [ln for ln in text.splitlines() if ln.startswith("removed ")]
        self.assertEqual(len(removed), 21)
        self.assertIn("All 21 sha256 digests verified", text)
        self.assertIn("verified absent", text)

    def test_backup_identity_is_recorded(self):
        doc = json.loads((EVIDENCE_DIR / "backup-artifact.json").read_text())
        self.assertEqual(doc["artifact_id"], "9352027951")
        self.assertEqual(
            doc["archive_sha256"],
            "452a0c2f8d816f2b8fd427bceb9da18f72782a36e23b07e10e4e33a19b19c48a",
        )
        self.assertEqual(
            doc["artifact_digest"],
            "30f35c1e491990db114413f6f05c92894b6a937b8071610eefbb101bbe752d8c",
        )

    def test_backup_manifest_covers_the_21_inventoried_files(self):
        man = json.loads((EVIDENCE_DIR / "backup-manifest.json").read_text())
        inv = json.loads(INVENTORY.read_text())
        self.assertEqual(len(man["files"]), 21)
        self.assertEqual(
            {f["path"] for f in man["files"]},
            {f["path"] for f in inv["files"]},
        )
        for m, i in zip(sorted(man["files"], key=lambda r: r["path"]),
                        sorted(inv["files"], key=lambda r: r["path"])):
            with self.subTest(path=m["path"]):
                self.assertEqual(m["size"], i["size"])
                self.assertEqual(m["sha256"], i["sha256"])

    def test_public_report_records_the_uniform_403(self):
        doc = json.loads((EVIDENCE_DIR / "public-http-status.json").read_text())
        statuses = {row["status"] for row in doc["withdrawn_urls"]}
        self.assertEqual(statuses, {403})
        self.assertEqual(len(doc["inconclusive"]), 21)
        self.assertTrue(doc["origin_absence_confirmed"])

    def test_evidence_contains_no_secret_material(self):
        patterns = ("BEGIN OPENSSH PRIVATE KEY", "BEGIN RSA PRIVATE KEY",
                    "ssh-ed25519 AAAA", "ssh-rsa AAAA",
                    "IFASTNET_SSH_KEY", "IFASTNET_KNOWN_HOSTS")
        for path in sorted(EVIDENCE_DIR.iterdir()):
            text = path.read_text(errors="ignore")
            for pattern in patterns:
                with self.subTest(file=path.name, pattern=pattern):
                    self.assertNotIn(pattern, text)

    def test_no_backup_archive_or_core_file_is_committed(self):
        """The backup contains the withdrawn artifacts; it stays in the run."""
        import subprocess
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True
        ).stdout.split()
        offenders = [
            f for f in tracked
            if f.endswith("core-withdrawal-backup.tar.gz")
            or f.endswith("core-withdrawal-backup.zip")
            or f.endswith("core-withdrawal-evidence.zip")
        ]
        self.assertEqual(offenders, [], f"backup payload committed: {offenders}")

    def test_no_withdrawn_core_artifact_is_committed(self):
        import re as _re
        import subprocess
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True
        ).stdout.split()
        core = _re.compile(
            r"(^|/)(dmi_release_\d{4}-\d{2}_core\.json"
            r"|dmi-\d{4}-\d{2}-core\.(csv|parquet)"
            r"|qa_report_\d{4}-\d{2}_core\.json)$"
        )
        offenders = [
            f for f in tracked
            if core.search(f) and not f.startswith("dmi-v0.1.1")
        ]
        self.assertEqual(offenders, [], f"withdrawn Core file committed: {offenders}")


class TestWithdrawalLogIsAccurate(unittest.TestCase):
    """The durable log must state what happened, including the failure."""

    @classmethod
    def setUpClass(cls):
        cls.text = WITHDRAWAL_LOG.read_text()
        cls.flat = " ".join(cls.text.lower().split())

    def test_log_exists(self):
        self.assertTrue(WITHDRAWAL_LOG.is_file())

    def test_states_the_withdrawal_completed(self):
        self.assertIn("remote-origin withdrawal completed successfully", self.flat)

    def test_records_the_run_id_and_url(self):
        self.assertIn("32214973867", self.text)
        self.assertIn(
            "https://github.com/dmianalysis/dmi/actions/runs/32214973867",
            self.text,
        )

    def test_records_the_origin_check_timestamp(self):
        self.assertIn("2026-08-19T04:14:49Z", self.text)

    def test_records_the_inventory_identity(self):
        self.assertIn(EXPECTED_FILE_SHA, self.text)
        self.assertIn(EXPECTED_SEAL, self.text)
        self.assertIn("63,598", self.text)
        self.assertIn("core-withdrawal-2026-08-19.json", self.text)

    def test_records_the_backup_identity_and_hashes(self):
        for value in (
            "9352027951",
            "30f35c1e491990db114413f6f05c92894b6a937b8071610eefbb101bbe752d8c",
            "452a0c2f8d816f2b8fd427bceb9da18f72782a36e23b07e10e4e33a19b19c48a",
            "8777454ad92e244cb24939bde9386c5d1cd1f7159f4d42d530bc52572b67a022",
        ):
            with self.subTest(value=value[:16]):
                self.assertIn(value, self.text)

    def test_records_the_exact_deletion_and_protection_result(self):
        self.assertIn("21", self.text)
        self.assertIn("15 protected operational", self.flat)
        self.assertIn("no partial deletion", self.flat)

    def test_does_not_claim_automated_http_verification_succeeded(self):
        """The single most important honesty constraint in this log."""
        for claim in ("automated public-http verification passed",
                      "automated verification succeeded",
                      "public verification passed during the run",
                      "http verification succeeded"):
            with self.subTest(claim=claim):
                self.assertNotIn(claim, self.flat)
        self.assertIn("inconclusive", self.flat)
        self.assertIn("uniform http 403", self.flat)

    def test_attributes_the_browser_check_to_the_operator(self):
        self.assertIn("operator attestation", self.flat)
        self.assertIn("normal-browser checks passed", self.flat)

    def test_does_not_invent_browser_check_details(self):
        """No fabricated per-URL timestamps or headers for the browser pass."""
        self.assertIn(
            "no per-url timestamps or response headers were captured",
            self.flat,
        )

    def test_records_that_no_restore_or_purge_occurred(self):
        self.assertIn("no restoration", self.flat)
        self.assertIn("no withdrawn core file was restored", self.flat)
        self.assertIn("no cloudflare purge", self.flat)
        self.assertIn("no purge was required or performed", self.flat)

    def test_records_no_core_implementation(self):
        self.assertIn("unimplemented", self.flat)
        self.assertIn("baseline and slack-plus remained the only operational",
                      self.flat)

    def test_records_the_retirement(self):
        self.assertIn("retired", self.flat)
        self.assertIn("execute_withdrawn_core.yml", self.text)

    def test_distinguishes_the_four_events(self):
        for stage in ("repository cleanup", "production deployment",
                      "remote-origin withdrawal", "cdn / public-cache"):
            with self.subTest(stage=stage):
                self.assertIn(stage, self.flat)

    def test_explains_why_the_run_is_red(self):
        self.assertIn("does not indicate a failed, partial, or unsafe withdrawal",
                      self.flat)


class TestDurableRecordsAreUpdated(unittest.TestCase):
    """No durable document may still say the withdrawal is pending."""

    DOCS = (
        ROOT / "docs" / "known-issues" / "CORE_OUTPUT_WITHDRAWAL.md",
        ROOT / "docs" / "repair" / "REMOTE_WITHDRAWAL.md",
        ROOT / "docs" / "repair" / "V0.1.12_ALIGNMENT_AUDIT.md",
    )

    def test_no_document_presents_the_withdrawal_as_pending(self):
        for path in self.DOCS:
            flat = " ".join(path.read_text().lower().split())
            for phrase in ("neither phase has been authorized or executed",
                           "not authorized, not executed",
                           "remote withdrawal pending explicit authorization"):
                with self.subTest(doc=path.name, phrase=phrase):
                    if phrase not in flat:
                        continue
                    # Permitted only when explicitly marked historical.
                    idx = flat.index(phrase)
                    window = flat[max(0, idx - 260): idx + 260]
                    self.assertTrue(
                        any(m in window for m in
                            ("superseded", "at the time", "previously",
                             "was written")),
                        f"{path.name} still presents the withdrawal as "
                        f"pending: …{window[:220]}…",
                    )

    def test_each_document_records_the_completion(self):
        for path in self.DOCS:
            with self.subTest(doc=path.name):
                self.assertIn("2026-08-19", path.read_text())

    def test_known_issue_record_has_the_executed_section(self):
        text = (ROOT / "docs" / "known-issues"
                / "CORE_OUTPUT_WITHDRAWAL.md").read_text()
        self.assertIn("EXECUTED 2026-08-19", text)
        self.assertIn("32214973867", text)

    def test_runbook_marks_itself_as_the_procedure_of_record(self):
        text = (ROOT / "docs" / "repair" / "REMOTE_WITHDRAWAL.md").read_text()
        self.assertIn("EXECUTED 2026-08-19", text)
        self.assertIn("procedure of record", text)

    def test_audit_has_a_terminal_status_section(self):
        text = (ROOT / "docs" / "repair" / "V0.1.12_ALIGNMENT_AUDIT.md").read_text()
        self.assertIn("Remote-origin withdrawal — executed 2026-08-19", text)


class TestEvidencePathsArePortable(unittest.TestCase):
    """Committed evidence must not cite an author's workstation.

    Two kinds of absolute path appear in this evidence set, and only one
    is a defect:

    * A path under a local scratch directory (`/private/tmp/...`,
      `/Users/...`) was introduced while assembling a report on one
      laptop. It points at nothing any reader can reach and nothing any
      run recorded. That is noise, and it is replaced with the
      repository-relative path to the same content.

    * A path under `/home/runner/...` is what the GitHub Actions run
      itself wrote down about where it read and wrote files. It is that
      run's own record. Rewriting it would improve the appearance of the
      evidence by falsifying it, so it is left exactly as emitted, and
      the committed counterpart is asserted to exist instead.
    """

    WORKSTATION_MARKERS = ("/private/tmp", "/var/folders", "/Users/",
                           "C:\\Users")

    def test_no_evidence_file_cites_an_author_workstation(self):
        offenders = []
        for path in sorted(EVIDENCE_DIR.iterdir()):
            text = path.read_text(errors="ignore")
            for marker in self.WORKSTATION_MARKERS:
                if marker in text:
                    offenders.append(f"{path.name}: {marker}")
        self.assertEqual(
            offenders, [],
            f"committed evidence cites a local workstation: {offenders}",
        )

    def test_reverification_cites_the_committed_origin_report(self):
        doc = json.loads(
            (EVIDENCE_DIR
             / "public-http-status-reverification-2026-08-19.json").read_text()
        )
        source = doc["origin_withdrawal"]["source"]
        self.assertEqual(
            source,
            "docs/repair/evidence/core-withdrawal-2026-08-19/"
            "origin-post-check.json",
        )
        self.assertTrue(
            (ROOT / source).is_file(),
            "the cited evidence path must resolve inside the repository",
        )

    def test_runner_paths_are_retained_with_committed_counterparts(self):
        """Kept verbatim as run provenance -- but each must be followable."""
        cases = [
            ("pre-execution-verification.json", "inventory_path",
             "docs/repair/inventories/core-withdrawal-2026-08-19.json"),
            ("public-http-status.json", "origin_report_source",
             "docs/repair/evidence/core-withdrawal-2026-08-19/"
             "origin-post-check.json"),
        ]
        for filename, key, counterpart in cases:
            with self.subTest(filename=filename):
                doc = json.loads((EVIDENCE_DIR / filename).read_text())
                self.assertTrue(
                    doc[key].startswith("/home/runner/"),
                    "run-emitted path must not be rewritten",
                )
                self.assertTrue(
                    (ROOT / counterpart).is_file(),
                    f"{filename} cites a runner path whose content is not "
                    f"committed at {counterpart}",
                )
                self.assertTrue(
                    doc[key].endswith(Path(counterpart).name),
                    "the runner path and its committed counterpart must "
                    "refer to the same file",
                )

    def test_reverification_records_the_expected_outcome(self):
        doc = json.loads(
            (EVIDENCE_DIR
             / "public-http-status-reverification-2026-08-19.json").read_text()
        )
        self.assertTrue(doc["origin_withdrawal"]["absence_confirmed"])
        self.assertEqual(len(doc["withdrawn_demonstrated"]), 21)
        self.assertEqual(doc["inconclusive"], [])


class TestCacheWordingIsEvidenceBounded(unittest.TestCase):
    """The log may claim what the records show, not universal absence."""

    @classmethod
    def setUpClass(cls):
        cls.flat = " ".join(WITHDRAWAL_LOG.read_text().lower().split())

    def test_claim_is_scoped_to_recorded_verifications(self):
        self.assertIn(
            "no recorded verification observed a withdrawn url returning 200",
            self.flat,
        )

    def test_it_does_not_claim_universal_absence(self):
        """"At any point" asserts more than any record can support."""
        self.assertNotIn(
            "no withdrawn url returned 200 at any point", self.flat,
        )

    def test_it_acknowledges_the_blocked_run_observed_nothing(self):
        self.assertIn("its requests were refused", self.flat)

    def test_purge_status_is_still_recorded(self):
        self.assertIn("no cloudflare purge", self.flat)
        self.assertIn("no purge was required or performed", self.flat)


class TestNoEdgeAllowlistIsRequested(unittest.TestCase):
    """The corrected client reaches the site; no special treatment is asked."""

    def test_verifier_does_not_request_an_allowlist(self):
        src = (ROOT / "scripts" / "verify_public_surface.py").read_text()
        self.assertIn("No edge allowlist is\nrequired or requested", src)

    def test_verifier_does_not_depend_on_being_allowlisted(self):
        src = (ROOT / "scripts" / "verify_public_surface.py").read_text().lower()
        for claim in ("must be allowlisted", "requires an allowlist",
                      "add to the allowlist"):
            with self.subTest(claim=claim):
                self.assertNotIn(claim, src)
