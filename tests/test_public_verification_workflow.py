#!/usr/bin/env python3
"""The read-only public-verification workflow.

It replaced the only legitimate reason to re-run the retired destructive
workflow: re-checking the public surface. Its value depends entirely on
it being incapable of anything else, so these tests are about absence —
no secrets, no environment, no transfer tools, no mutation, and no input
that could redirect what it checks.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "verify_core_withdrawal_public.yml"


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


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestPublicVerificationWorkflow(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.raw = WORKFLOW.read_text()
        cls.doc = yaml.safe_load(cls.raw)
        cls.lines = _run_lines(cls.doc)
        cls.script = "\n".join(cls.lines)
        cls.steps = _steps(cls.doc)

    def test_workflow_exists(self):
        self.assertTrue(WORKFLOW.is_file())

    # -- manual only -----------------------------------------------------

    def test_workflow_dispatch_is_the_only_trigger(self):
        self.assertEqual(sorted(_on_block(self.doc).keys()),
                         ["workflow_dispatch"])

    def test_merging_does_not_run_it(self):
        on = _on_block(self.doc)
        for trigger in ("push", "pull_request", "pull_request_target",
                        "schedule", "workflow_call", "release",
                        "repository_dispatch", "workflow_run"):
            with self.subTest(trigger=trigger):
                self.assertNotIn(trigger, on)

    def test_it_takes_no_inputs(self):
        dispatch = _on_block(self.doc)["workflow_dispatch"]
        inputs = (dispatch or {}).get("inputs") if dispatch else None
        self.assertIn(
            inputs, (None, {}),
            "an input is a lever to change what is verified",
        )

    # -- read-only -------------------------------------------------------

    def test_permissions_are_contents_read(self):
        self.assertEqual(self.doc.get("permissions"), {"contents": "read"})

    def test_no_job_widens_permissions(self):
        for name, job in self.doc["jobs"].items():
            with self.subTest(job=name):
                self.assertNotIn("permissions", job)

    def test_no_environment_is_referenced(self):
        """Naming one would associate it with the production credential scope."""
        for name, job in self.doc["jobs"].items():
            with self.subTest(job=name):
                self.assertNotIn("environment", job)

    def test_no_secret_is_referenced(self):
        self.assertNotIn("secrets.", self.raw)

    def test_credentials_are_not_persisted_by_checkout(self):
        checkout = next(s for s in self.steps
                        if "actions/checkout" in str(s.get("uses", "")))
        self.assertIs(checkout["with"].get("persist-credentials"), False)

    # -- no remote mutation ----------------------------------------------

    def test_no_transfer_or_shell_tooling(self):
        invocation = re.compile(r"(^|[|;&]\s*|\$\(\s*)(ssh|scp|sftp|rsync)\s")
        offenders = [ln for ln in self.lines if invocation.search(ln)]
        self.assertEqual(offenders, [], f"offenders: {offenders}")

    def test_no_withdrawal_tool_invocation(self):
        offenders = [ln for ln in self.lines
                     if "withdraw_remote_artifacts" in ln]
        self.assertEqual(offenders, [])

    def test_no_deletion_restore_purge_or_deploy(self):
        for token in ("rm ", "prepare_deployment", "purge", "cloudflare",
                      "restore", "curl -X", "-X POST", "-X DELETE"):
            offenders = [ln for ln in self.lines if token in ln.lower()]
            with self.subTest(token=token):
                self.assertEqual(offenders, [], f"offenders: {offenders}")

    # -- fixed invocation ------------------------------------------------

    def test_it_runs_the_corrected_verifier(self):
        self.assertIn("scripts.verify_public_surface", self.script)

    def test_the_invocation_is_fixed(self):
        call = next(ln for ln in self.lines
                    if "verify_public_surface" in ln)
        for interpolation in ("github.event.inputs", "${{ inputs"):
            with self.subTest(pattern=interpolation):
                self.assertNotIn(interpolation, call)

    def test_it_supplies_the_committed_origin_report(self):
        self.assertIn("--origin-report", self.script)
        self.assertIn("origin-post-check.json", self.script)

    def test_the_origin_report_it_references_is_committed(self):
        path = ROOT / ("docs/repair/evidence/core-withdrawal-2026-08-19/"
                       "origin-post-check.json")
        self.assertTrue(path.is_file(), f"missing: {path}")

    # -- artifacts and guards --------------------------------------------

    def test_it_uploads_explicitly_named_reports(self):
        upload = next(s for s in self.steps
                      if "upload-artifact" in str(s.get("uses", "")))
        paths = [p.strip() for p in str(upload["with"]["path"]).splitlines()
                 if p.strip()]
        self.assertEqual(len(paths), 2)
        for path in paths:
            with self.subTest(path=path):
                self.assertNotIn("*", path)
                self.assertTrue(path.endswith(".json"))
        self.assertEqual(upload["with"]["if-no-files-found"], "error")

    def test_short_timeout(self):
        for name, job in self.doc["jobs"].items():
            with self.subTest(job=name):
                self.assertLessEqual(job["timeout-minutes"], 15)

    def test_concurrency_avoids_parallel_runs(self):
        conc = self.doc.get("concurrency")
        self.assertIsInstance(conc, dict)
        self.assertTrue(conc.get("group"))
        self.assertIs(conc.get("cancel-in-progress"), False)

    def test_no_step_echoes_a_secret_like_value(self):
        offenders = [
            ln for ln in self.lines
            if re.search(r"\b(echo|printf|cat)\b", ln)
            and re.search(r"secrets\.|IFASTNET|PRIVATE KEY", ln)
        ]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
