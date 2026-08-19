#!/usr/bin/env python3
"""Phase-2 Core withdrawal: the only workflow that destroys data.

The interesting question is not whether it works but what the worst
outcome of a dispatch is. The answer must be: delete exactly the 21
reviewed files, after a verified backup, or delete nothing.

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
WORKFLOW = ROOT / ".github" / "workflows" / "execute_withdrawn_core.yml"
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

@unittest.skipIf(yaml is None, "PyYAML not available")
class TestPhase2WorkflowShape(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.raw = WORKFLOW.read_text()
        cls.doc = yaml.safe_load(cls.raw)
        cls.lines = _run_lines(cls.doc)
        cls.script = "\n".join(cls.lines)
        cls.steps = _steps(cls.doc)
        cls.names = [str(s.get("name", "")) for s in cls.steps]

    # -- triggers --------------------------------------------------------

    def test_workflow_dispatch_is_the_only_trigger(self):
        self.assertEqual(sorted(_on_block(self.doc).keys()),
                         ["workflow_dispatch"])

    def test_no_automatic_or_callable_trigger(self):
        on = _on_block(self.doc)
        for trigger in ("push", "pull_request", "pull_request_target",
                        "schedule", "workflow_call", "release",
                        "repository_dispatch", "workflow_run"):
            with self.subTest(trigger=trigger):
                self.assertNotIn(trigger, on)

    def test_merging_the_pr_does_nothing(self):
        """No trigger fires on merge."""
        on = _on_block(self.doc)
        self.assertNotIn("push", on)

    # -- permissions -----------------------------------------------------

    def test_permissions_read_only(self):
        self.assertEqual(self.doc.get("permissions"), {"contents": "read"})

    def test_no_job_or_step_widens_permissions(self):
        for name, job in self.doc["jobs"].items():
            with self.subTest(job=name):
                self.assertNotIn("permissions", job)
        for step in self.steps:
            with self.subTest(step=step.get("name")):
                self.assertNotIn("permissions", step)

    # -- ref restriction -------------------------------------------------

    def test_only_main_may_run(self):
        self.assertIn("refs/heads/main", self.script)
        guard = next(ln for ln in self.lines if "GITHUB_REF" in ln)
        self.assertIn("refs/heads/main", guard)

    def test_ref_guard_is_the_first_step(self):
        self.assertIn("ref", self.names[0].lower())

    def test_checkout_pins_main(self):
        checkout = next(s for s in self.steps
                        if "actions/checkout" in str(s.get("uses", "")))
        self.assertEqual(str(checkout["with"]["ref"]), "refs/heads/main")

    # -- confirmation ----------------------------------------------------

    def test_confirmation_input_is_required(self):
        inputs = _on_block(self.doc)["workflow_dispatch"]["inputs"]
        self.assertIn("confirmation", inputs)
        self.assertTrue(inputs["confirmation"]["required"])

    def test_confirmation_phrase_is_exact(self):
        self.assertEqual(self.doc["env"]["CONFIRMATION_PHRASE"], CONFIRMATION)
        self.assertIn(CONFIRMATION, self.raw)

    def test_confirmation_is_the_only_input(self):
        inputs = _on_block(self.doc)["workflow_dispatch"]["inputs"]
        self.assertEqual(sorted(inputs.keys()), ["confirmation"])

    def test_confirmation_cannot_select_anything(self):
        """It must never appear in a path, command or inventory position."""
        for line in self.lines:
            if "inputs.confirmation" not in line and "SUPPLIED" not in line:
                continue
            with self.subTest(line=line[:60]):
                for token in ("--inventory", "python -m", "scripts/",
                              "docs/repair", "rm ", "ssh "):
                    self.assertNotIn(token, line)

    # -- pinned constants ------------------------------------------------

    def test_constants_are_pinned_in_the_workflow(self):
        env = self.doc["env"]
        self.assertEqual(env["EXPECTED_FILE_SHA256"], EXPECTED_FILE_SHA)
        self.assertEqual(env["EXPECTED_INTEGRITY_SHA256"], EXPECTED_SEAL)
        self.assertEqual(str(env["EXPECTED_COUNT"]), "21")
        self.assertEqual(env["EXPECTED_REMOTE_BASE"],
                         "/home/agiraces/dmianalysis")
        self.assertIn("core-withdrawal-2026-08-19.json", env["INVENTORY_PATH"])

    def test_workflow_constants_match_the_verifier_module(self):
        from scripts import verify_withdrawal_inventory as v
        env = self.doc["env"]
        self.assertEqual(v.EXPECTED_FILE_SHA256, env["EXPECTED_FILE_SHA256"])
        self.assertEqual(v.EXPECTED_INTEGRITY_SHA256,
                         env["EXPECTED_INTEGRITY_SHA256"])
        self.assertEqual(str(v.EXPECTED_COUNT), str(env["EXPECTED_COUNT"]))
        self.assertEqual(v.EXPECTED_REMOTE_BASE, env["EXPECTED_REMOTE_BASE"])
        self.assertEqual(v.INVENTORY_PATH, env["INVENTORY_PATH"])

    def test_no_input_can_choose_a_path_or_subcommand(self):
        for line in self.lines:
            if "github.event.inputs" not in line:
                continue
            with self.subTest(line=line[:60]):
                self.assertIn("SUPPLIED", line)

    # -- the command -----------------------------------------------------

    def test_execute_appears_exactly_once(self):
        calls = [ln for ln in self.lines
                 if "scripts.withdraw_remote_artifacts" in ln]
        self.assertEqual(len(calls), 1, f"expected one call, got {calls}")
        self.assertIn("execute", calls[0])

    def test_the_command_is_exactly_the_reviewed_one(self):
        idx = next(i for i, ln in enumerate(self.lines)
                   if "scripts.withdraw_remote_artifacts" in ln)
        joined = " ".join(self.lines[idx:idx + 3])
        self.assertIn("execute", joined)
        self.assertIn(
            "--inventory docs/repair/inventories/core-withdrawal-2026-08-19.json",
            joined,
        )
        self.assertIn("--confirm", joined)

    def test_inventory_and_reseal_are_not_executable_paths(self):
        for forbidden in ("withdraw_remote_artifacts inventory",
                          "withdraw_remote_artifacts reseal"):
            offenders = [ln for ln in self.lines if forbidden in ln]
            with self.subTest(token=forbidden):
                self.assertEqual(offenders, [])

    def test_no_remote_rediscovery(self):
        offenders = [ln for ln in self.lines
                     if "find " in ln and "-name" in ln]
        self.assertEqual(offenders, [])

    # -- ordering: backup before delete ----------------------------------

    def _index(self, needle: str) -> int:
        return next(i for i, n in enumerate(self.names)
                    if needle.lower() in n.lower())

    def test_verification_precedes_credentials(self):
        self.assertLess(self._index("Verify the sealed inventory"),
                        self._index("Install deployment key"))

    def test_backup_precedes_execute(self):
        self.assertLess(self._index("Back up exactly"),
                        self._index("Execute the reviewed withdrawal"))

    def test_backup_upload_precedes_execute(self):
        self.assertLess(self._index("Upload the verified backup"),
                        self._index("Execute the reviewed withdrawal"))

    def test_upload_success_is_asserted_before_execute(self):
        self.assertLess(self._index("Assert the backup upload succeeded"),
                        self._index("Execute the reviewed withdrawal"))
        guard = next(s for s in self.steps
                     if "Assert the backup upload" in str(s.get("name")))
        self.assertIn("artifact-id", str(guard["run"]))
        self.assertIn("exit 1", str(guard["run"]))

    def test_backup_upload_fails_the_job_if_no_files(self):
        upload = next(s for s in self.steps
                      if str(s.get("name", "")).startswith("Upload the verified backup"))
        self.assertEqual(upload["with"]["if-no-files-found"], "error")
        self.assertGreaterEqual(int(upload["with"]["retention-days"]), 30)

    def test_execute_step_has_no_continue_on_error(self):
        step = next(s for s in self.steps
                    if "Execute the reviewed withdrawal" in str(s.get("name")))
        self.assertNotIn("continue-on-error", step)

    def test_post_checks_follow_execute(self):
        for label in ("Verify origin state", "Verify the public surface"):
            with self.subTest(step=label):
                self.assertGreater(self._index(label),
                                   self._index("Execute the reviewed withdrawal"))

    # -- SSH posture -----------------------------------------------------

    def test_key_installed_via_canonical_helper(self):
        self.assertIn("scripts/install_deploy_key.sh", self.script)

    def test_pinned_host_material_is_installed(self):
        self.assertIn("scripts.install_known_hosts", self.script)

    def test_no_ssh_keyscan(self):
        self.assertEqual([ln for ln in self.lines if "ssh-keyscan" in ln], [])

    def test_no_key_written_inline(self):
        offenders = [ln for ln in self.lines
                     if "IFASTNET_SSH_KEY" in ln and (">" in ln or "tee" in ln)]
        self.assertEqual(offenders, [])

    def test_runner_temp_used_not_workspace(self):
        self.assertIn("runner.temp", self.raw)
        for line in self.lines:
            if "dmi_withdrawal_key" in line or "dmi_known_hosts" in line:
                with self.subTest(line=line[:60]):
                    self.assertNotIn("$GITHUB_WORKSPACE", line)

    def test_tool_enforces_identities_only_strict_and_pinned_hosts(self):
        src = (ROOT / "scripts" / "withdraw_remote_artifacts.py").read_text()
        self.assertIn('"IdentitiesOnly=yes"', src)
        self.assertIn('"StrictHostKeyChecking=yes"', src)
        self.assertIn("UserKnownHostsFile=", src)
        self.assertNotIn("StrictHostKeyChecking=no", src)

    def test_ssh_argv_order_and_content(self):
        """Behavioural: build the real argv."""
        from scripts.withdraw_remote_artifacts import _ssh_command
        with tempfile.TemporaryDirectory() as tmp:
            key = Path(tmp) / "k"
            key.write_text("x")
            argv = _ssh_command("h", "u", "1394", key, Path(tmp) / "kh")
        self.assertIn("IdentitiesOnly=yes", argv)
        self.assertIn("StrictHostKeyChecking=yes", argv)
        self.assertTrue(any(a.startswith("UserKnownHostsFile=") for a in argv))

    # -- artifacts and secrets -------------------------------------------

    def test_uploads_name_explicit_files_only(self):
        for step in self.steps:
            if "upload-artifact" not in str(step.get("uses", "")):
                continue
            paths = [p.strip() for p in str(step["with"]["path"]).splitlines()
                     if p.strip()]
            with self.subTest(step=step.get("name")):
                self.assertTrue(paths)
                for path in paths:
                    self.assertNotIn("*", path)
                    self.assertNotIn("dmi_withdrawal_key", path)
                    self.assertNotIn("dmi_known_hosts", path)
                    self.assertNotEqual(path.rstrip("/"), "${{ runner.temp }}")

    def test_evidence_artifact_contents_are_the_named_set(self):
        upload = next(s for s in self.steps
                      if "core-withdrawal-evidence" in str(s.get("with", {}).get("name", "")))
        paths = str(upload["with"]["path"])
        for required in ("core-withdrawal-2026-08-19.json",
                         "backup-manifest.json",
                         "pre-execution-verification.json",
                         "execution-log.txt",
                         "origin-post-check.json",
                         "public-http-status.json",
                         "operational-surface.json"):
            with self.subTest(item=required):
                self.assertIn(required, paths)

    def test_no_secret_is_echoed(self):
        offenders = []
        for line in self.lines:
            if not re.search(r"\b(echo|printf|cat)\b", line):
                continue
            if re.search(r"secrets\.|IFASTNET_SSH_KEY|IFASTNET_KNOWN_HOSTS"
                         r"|DMI_KNOWN_HOSTS_DATA", line):
                offenders.append(line)
        self.assertEqual(offenders, [])

    def test_secrets_scoped_to_steps(self):
        self.assertNotIn("secrets.", str(self.doc.get("env", {})))
        for name, job in self.doc["jobs"].items():
            with self.subTest(job=name):
                self.assertNotIn("secrets.", str(job.get("env", {})))

    def test_private_key_reaches_exactly_one_step(self):
        exposing = [str(s.get("name")) for s in self.steps
                    if "IFASTNET_SSH_KEY" in str(s.get("env", {}))]
        self.assertEqual(len(exposing), 1, exposing)

    # -- guards ----------------------------------------------------------

    def test_concurrency_does_not_cancel(self):
        conc = self.doc["concurrency"]
        self.assertIs(conc["cancel-in-progress"], False)
        self.assertTrue(conc["group"])

    def test_short_timeout(self):
        for name, job in self.doc["jobs"].items():
            with self.subTest(job=name):
                self.assertLessEqual(job["timeout-minutes"], 20)

    def test_environment_is_referenced(self):
        job = self.doc["jobs"]["execute-withdrawal"]
        self.assertEqual(job.get("environment"), "core-withdrawal")

    def test_environment_naming_is_documented_as_insufficient(self):
        """Naming an environment does not itself require a reviewer."""
        self.assertIn("does NOT by itself require a reviewer", self.raw)

    def test_cleanup_always_runs_and_is_local(self):
        cleanup = [s for s in self.steps
                   if str(s.get("if", "")).strip() == "always()"
                   and "credential" in str(s.get("name", "")).lower()]
        self.assertTrue(cleanup)
        script = str(cleanup[0]["run"])
        self.assertIn("shred -u", script)
        for token in ("ssh", "rsync", "scp", "withdraw_remote_artifacts"):
            with self.subTest(token=token):
                self.assertNotIn(token, script)


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

class TestDocumentationTemplates(unittest.TestCase):

    TEMPLATES = ROOT / "docs" / "repair" / "templates"

    def test_templates_exist(self):
        self.assertTrue((self.TEMPLATES / "REMOTE_WITHDRAWAL_LOG_TEMPLATE.md").is_file())
        self.assertTrue((self.TEMPLATES / "CORE_OUTPUT_WITHDRAWAL_UPDATE_TEMPLATE.md").is_file())

    def test_templates_do_not_claim_execution(self):
        for path in self.TEMPLATES.glob("*.md"):
            text = path.read_text()
            with self.subTest(template=path.name):
                self.assertIn("TEMPLATE", text)
                self.assertIn("<", text, "placeholders must remain unfilled")

    def test_templates_distinguish_the_four_states(self):
        text = (self.TEMPLATES / "REMOTE_WITHDRAWAL_LOG_TEMPLATE.md").read_text().lower()
        for stage in ("repository cleanup", "production deployment",
                      "remote-origin withdrawal", "cdn-cache removal"):
            with self.subTest(stage=stage):
                self.assertIn(stage, text)

    def test_template_records_the_required_facts(self):
        text = (self.TEMPLATES / "REMOTE_WITHDRAWAL_LOG_TEMPLATE.md").read_text()
        self.assertIn(EXPECTED_SEAL, text)
        self.assertIn(EXPECTED_FILE_SHA, text)
        self.assertIn("core-withdrawal-backup", text)
        self.assertIn("Cloudflare", text)

    def test_evidence_record_still_says_unexecuted(self):
        """Until a real run, the durable record must not claim otherwise."""
        text = (ROOT / "docs" / "known-issues"
                / "CORE_OUTPUT_WITHDRAWAL.md").read_text().lower()
        self.assertIn("neither phase has been authorized or executed", text)
        self.assertIn("remote withdrawal pending explicit authorization", text)

    def test_no_document_yet_claims_the_withdrawal_happened(self):
        """This PR adds capability, not a completed operation."""
        for path in (ROOT / "docs" / "known-issues" / "CORE_OUTPUT_WITHDRAWAL.md",
                     ROOT / "docs" / "repair" / "REMOTE_WITHDRAWAL.md"):
            lowered = path.read_text().lower()
            with self.subTest(doc=path.name):
                for claim in ("withdrawal complete",
                              "core artifacts were deleted",
                              "withdrawal has been executed"):
                    self.assertNotIn(claim, lowered)

    def test_no_withdrawal_log_has_been_created(self):
        """A log file would imply a run happened."""
        logs = list((ROOT / "docs" / "repair").glob("REMOTE_WITHDRAWAL_LOG_*.md"))
        self.assertEqual(
            logs, [],
            f"a withdrawal log exists but no run has occurred: {logs}",
        )


if __name__ == "__main__":
    unittest.main()
