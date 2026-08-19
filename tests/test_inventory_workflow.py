#!/usr/bin/env python3
"""The Phase-1 inventory workflow must be incapable of deleting anything.

Why the tests are shaped this way
---------------------------------
This workflow holds production SSH credentials, so the interesting
question is not "does it work" but "what is the worst thing a dispatch of
it can do". The answer must be: enumerate files and write a JSON report.

That property is structural, not behavioural — it comes from the
subcommand being a literal rather than an input, from the permission
scope, and from what is absent. So these tests read the workflow and
assert on its shape, checking executable lines rather than the whole
file: the workflow's own comments explain why `execute` is not reachable,
and a naive substring scan would flag that explanation as the danger it
describes.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is a repo dependency
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "inventory_withdrawn_core.yml"


def _on_block(doc: dict) -> dict:
    """PyYAML parses a top-level ``on:`` key as the boolean ``True``."""
    return doc.get("on") or doc.get(True)


def _steps(doc: dict) -> list:
    return [
        step
        for job in (doc.get("jobs") or {}).values()
        for step in (job.get("steps") or [])
    ]


def _run_lines(doc: dict) -> list[str]:
    """Every executable line of every ``run:`` block, comments removed."""
    lines: list[str] = []
    for step in _steps(doc):
        for line in str(step.get("run", "")).splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                lines.append(stripped)
    return lines


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestInventoryWorkflowShape(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.raw = WORKFLOW.read_text()
        cls.doc = yaml.safe_load(cls.raw)
        cls.run_lines = _run_lines(cls.doc)
        cls.script = "\n".join(cls.run_lines)

    # -- trigger surface -------------------------------------------------

    def test_workflow_exists(self):
        self.assertTrue(WORKFLOW.is_file())

    def test_workflow_dispatch_is_the_only_trigger(self):
        on = _on_block(self.doc)
        self.assertEqual(
            sorted(on.keys()), ["workflow_dispatch"],
            "a workflow holding production credentials must run only when "
            "a human dispatches it.",
        )

    def test_no_automatic_trigger_of_any_kind(self):
        on = _on_block(self.doc)
        for trigger in ("push", "pull_request", "pull_request_target",
                        "schedule", "release", "workflow_call",
                        "repository_dispatch", "workflow_run"):
            with self.subTest(trigger=trigger):
                self.assertNotIn(trigger, on)

    def test_dispatch_takes_no_inputs(self):
        """No input means no lever to change what it runs."""
        dispatch = _on_block(self.doc)["workflow_dispatch"]
        inputs = (dispatch or {}).get("inputs") if dispatch else None
        self.assertIn(
            inputs, (None, {}),
            "the inventory takes no parameters; an input is a way to "
            "influence the command.",
        )

    # -- permissions -----------------------------------------------------

    def test_permissions_are_read_only(self):
        self.assertEqual(self.doc.get("permissions"), {"contents": "read"})

    def test_no_job_widens_permissions(self):
        for name, job in self.doc["jobs"].items():
            with self.subTest(job=name):
                self.assertNotIn("permissions", job)

    def test_no_write_scope_anywhere_in_the_file(self):
        for scope in ("contents: write", "packages:", "deployments:",
                      "id-token:", "pull-requests: write", "issues: write"):
            with self.subTest(scope=scope):
                self.assertNotIn(scope, self.raw)

    # -- concurrency and timeout -----------------------------------------

    def test_concurrency_group_prevents_simultaneous_runs(self):
        conc = self.doc.get("concurrency")
        self.assertIsInstance(conc, dict)
        self.assertTrue(conc.get("group"))
        self.assertIs(
            conc.get("cancel-in-progress"), False,
            "queue rather than cancel: an in-flight SSH session should "
            "finish cleanly.",
        )

    def test_job_has_a_short_timeout(self):
        for name, job in self.doc["jobs"].items():
            with self.subTest(job=name):
                timeout = job.get("timeout-minutes")
                self.assertIsNotNone(timeout)
                self.assertLessEqual(timeout, 15)

    # -- the command it runs ---------------------------------------------

    def test_inventory_is_the_only_withdrawal_subcommand(self):
        calls = [
            ln for ln in self.run_lines
            if "scripts.withdraw_remote_artifacts" in ln
        ]
        self.assertEqual(
            len(calls), 1,
            f"exactly one invocation of the withdrawal tool expected; "
            f"found {calls}",
        )
        self.assertIn("inventory", calls[0])

    def test_the_subcommand_is_a_literal_not_a_variable(self):
        """A parameterised subcommand could be steered to `execute`."""
        call = next(
            ln for ln in self.run_lines
            if "scripts.withdraw_remote_artifacts" in ln
        )
        after = call.split("scripts.withdraw_remote_artifacts", 1)[1].strip()
        subcommand = after.split()[0]
        self.assertEqual(subcommand, "inventory")
        for interpolation in ("${{", "$(", "${", "$INPUT", "$MODE"):
            with self.subTest(pattern=interpolation):
                self.assertNotIn(
                    interpolation, subcommand,
                    "the subcommand must not be interpolated from anything.",
                )

    def test_execute_and_reseal_are_absent_from_executable_lines(self):
        for forbidden in ("execute", "reseal", "--confirm"):
            offenders = [ln for ln in self.run_lines if forbidden in ln]
            with self.subTest(token=forbidden):
                self.assertEqual(
                    offenders, [],
                    f"{forbidden!r} must not appear in any executable "
                    f"line: {offenders}",
                )

    def test_no_transfer_or_remote_deletion_capability(self):
        for forbidden in ("rsync", "scp ", "sftp ", "rm ", "rm -"):
            offenders = [ln for ln in self.run_lines if forbidden in ln]
            with self.subTest(token=forbidden):
                self.assertEqual(offenders, [], f"{forbidden!r}: {offenders}")

    def test_no_direct_ssh_invocation(self):
        """All SSH goes through the tool, which enforces the pinning.

        Matches ``ssh`` in COMMAND position — line start, or after a
        pipe, ``&&``, ``;`` or ``$(`` — rather than as a substring. The
        pre-upload guard greps for ``ssh-rsa`` and ``ssh-ed25519`` to
        make sure no key material is published, and a substring match
        would flag that guard as the risk it exists to prevent.
        """
        invocation = re.compile(r"(^|[|;&]\s*|\$\(\s*)ssh\s")
        offenders = [ln for ln in self.run_lines if invocation.search(ln)]
        self.assertEqual(offenders, [], f"unexpected ssh usage: {offenders}")

    def test_ssh_invocation_detector_is_not_vacuous(self):
        """The detector must actually recognise an ssh command."""
        invocation = re.compile(r"(^|[|;&]\s*|\$\(\s*)ssh\s")
        for sample in ("ssh user@host 'ls'",
                       "cat f | ssh user@host 'cat > x'",
                       "OUT=$(ssh user@host 'ls')"):
            with self.subTest(sample=sample):
                self.assertTrue(invocation.search(sample))
        for benign in ("grep -qE 'ssh-rsa |ssh-ed25519 ' \"$INV\"",
                       "ssh-keygen -y -f key"):
            with self.subTest(benign=benign):
                self.assertFalse(invocation.search(benign))

    def test_no_ssh_keyscan(self):
        self.assertEqual(
            [ln for ln in self.run_lines if "ssh-keyscan" in ln], [],
            "host trust must come from the pinned secret, never a scan.",
        )

    # -- key handling ----------------------------------------------------

    def test_key_installed_via_the_canonical_helper(self):
        self.assertIn("scripts/install_deploy_key.sh", self.script)

    def test_key_is_never_written_inline(self):
        offenders = [
            ln for ln in self.run_lines
            if "IFASTNET_SSH_KEY" in ln and (">" in ln or "tee" in ln)
        ]
        self.assertEqual(offenders, [], f"inline key write: {offenders}")

    def test_helper_exists_and_is_executable(self):
        import os
        helper = ROOT / "scripts" / "install_deploy_key.sh"
        self.assertTrue(helper.is_file())
        self.assertTrue(os.access(helper, os.X_OK))

    def test_key_is_written_to_runner_temp_not_the_workspace(self):
        """A key in the workspace could be picked up by upload-artifact."""
        call = next(
            ln for ln in self.run_lines if "install_deploy_key.sh" in ln
        ) + " " + self.script
        self.assertIn("runner.temp", self.raw)
        self.assertNotIn("~/.ssh/dmi_withdrawal_key", self.script)

    # -- environment mapping ---------------------------------------------

    def test_secrets_are_scoped_to_the_steps_that_need_them(self):
        """No workflow-level or job-level secret exposure."""
        self.assertNotIn("secrets.", str(self.doc.get("env", {})))
        for name, job in self.doc["jobs"].items():
            with self.subTest(job=name):
                self.assertNotIn("secrets.", str(job.get("env", {})))

    def test_required_environment_mapping(self):
        env_blocks = [step.get("env", {}) or {} for step in _steps(self.doc)]
        merged = {k: str(v) for block in env_blocks for k, v in block.items()}
        expected = {
            "DMI_REMOTE_HOST": "secrets.IFASTNET_SSH_HOST",
            "DMI_REMOTE_USER": "secrets.IFASTNET_SSH_USER",
            "DMI_KNOWN_HOSTS_DATA": "secrets.IFASTNET_KNOWN_HOSTS",
        }
        for key, needle in expected.items():
            with self.subTest(var=key):
                self.assertIn(key, merged)
                self.assertIn(needle, merged[key])
        self.assertEqual(merged.get("DMI_REMOTE_PORT"), "1394")
        self.assertEqual(
            merged.get("DMI_REMOTE_BASE"), "/home/agiraces/dmianalysis"
        )
        for key in ("DMI_REMOTE_KEY", "DMI_KNOWN_HOSTS"):
            with self.subTest(var=key):
                self.assertIn("runner.temp", merged.get(key, ""))

    def test_ssh_key_secret_is_only_exposed_to_the_installer_step(self):
        exposing = [
            str(step.get("name"))
            for step in _steps(self.doc)
            if "IFASTNET_SSH_KEY" in str(step.get("env", {}))
        ]
        self.assertEqual(
            len(exposing), 1,
            f"the private key should reach exactly one step; got {exposing}",
        )
        self.assertIn("key", exposing[0].lower())

    # -- artifact --------------------------------------------------------

    def test_only_the_inventory_json_is_uploaded(self):
        uploads = [
            step for step in _steps(self.doc)
            if "upload-artifact" in str(step.get("uses", ""))
        ]
        self.assertEqual(len(uploads), 1)
        path = str(uploads[0]["with"]["path"])
        self.assertIn("core-withdrawal-inventory.json", path)
        self.assertNotIn("*", path, "no globbing; exactly one named file.")
        self.assertNotIn("\n", path.strip(), "a single path, not a list.")

    def test_upload_fails_if_the_inventory_is_missing(self):
        upload = next(
            step for step in _steps(self.doc)
            if "upload-artifact" in str(step.get("uses", ""))
        )
        self.assertEqual(upload["with"].get("if-no-files-found"), "error")

    def test_no_log_or_environment_dump_is_uploaded(self):
        for forbidden in ("env >", "printenv", "set -x", "env\n",
                          "~/.ssh", "$HOME/.ssh"):
            with self.subTest(token=forbidden):
                self.assertNotIn(forbidden, self.script)

    def test_artifact_is_guarded_against_key_material(self):
        self.assertIn("PRIVATE KEY", self.script,
                      "there should be a pre-upload guard for key material")

    # -- cleanup ---------------------------------------------------------

    def test_cleanup_step_always_runs(self):
        cleanup = [
            step for step in _steps(self.doc)
            if str(step.get("if", "")).strip() == "always()"
        ]
        self.assertTrue(cleanup, "a cleanup step must run on failure too.")
        script = " ".join(str(s.get("run", "")) for s in cleanup)
        self.assertIn("dmi_withdrawal_key", script)
        self.assertIn("dmi_known_hosts", script)

    def test_cleanup_removes_files_without_a_generic_rm(self):
        cleanup = next(
            step for step in _steps(self.doc)
            if str(step.get("if", "")).strip() == "always()"
        )
        script = str(step_run := cleanup.get("run", ""))
        self.assertIn(
            "shred -u", script,
            "overwrite the private key before unlinking it.",
        )
        for line in script.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            self.assertNotIn("rm ", stripped)

    def test_cleanup_never_touches_the_remote(self):
        cleanup = next(
            step for step in _steps(self.doc)
            if str(step.get("if", "")).strip() == "always()"
        )
        script = str(cleanup.get("run", ""))
        for forbidden in ("ssh", "rsync", "scp", "DMI_REMOTE_HOST",
                          "withdraw_remote_artifacts"):
            with self.subTest(token=forbidden):
                self.assertNotIn(forbidden, script)

    # -- secrets never printed -------------------------------------------

    def test_no_step_echoes_a_secret(self):
        offenders = []
        for line in self.run_lines:
            if not re.search(r"\b(echo|printf|cat)\b", line):
                continue
            if re.search(r"secrets\.|IFASTNET_SSH_KEY|IFASTNET_KNOWN_HOSTS"
                         r"|DMI_KNOWN_HOSTS_DATA|DMI_REMOTE_KEY", line):
                offenders.append(line)
        self.assertEqual(offenders, [], f"secret may reach the log: {offenders}")

    def test_no_secret_is_interpolated_into_a_run_body(self):
        """Interpolated secrets can land in the log via shell tracing."""
        for step in _steps(self.doc):
            run = str(step.get("run", ""))
            with self.subTest(step=step.get("name")):
                self.assertNotIn("secrets.IFASTNET_SSH_KEY", run)
                self.assertNotIn("secrets.IFASTNET_KNOWN_HOSTS", run)


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestWithdrawalToolStillEnforcesPinning(unittest.TestCase):
    """The workflow relies on the tool's own guarantees; pin them here."""

    def test_tool_requires_strict_host_key_checking(self):
        src = (ROOT / "scripts" / "withdraw_remote_artifacts.py").read_text()
        self.assertIn('"StrictHostKeyChecking=yes"', src)
        self.assertNotIn("StrictHostKeyChecking=no", src)

    def test_tool_uses_an_explicit_known_hosts_file(self):
        src = (ROOT / "scripts" / "withdraw_remote_artifacts.py").read_text()
        self.assertIn("UserKnownHostsFile=", src)

    def test_tool_obtains_pinned_material_not_a_scan(self):
        src = (ROOT / "scripts" / "withdraw_remote_artifacts.py").read_text()
        self.assertIn("from scripts.install_known_hosts import", src)

    def test_inventory_subcommand_has_no_confirm_flag(self):
        from scripts.withdraw_remote_artifacts import main
        with self.assertRaises(SystemExit):
            main(["inventory", "--output", "/dev/null", "--confirm"])

    def test_inventory_is_read_only_by_construction(self):
        """`cmd_inventory` must not call the deletion helper."""
        import ast
        src = (ROOT / "scripts" / "withdraw_remote_artifacts.py").read_text()
        func = next(
            n for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.FunctionDef) and n.name == "cmd_inventory"
        )
        called = {
            n.func.id for n in ast.walk(func)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        self.assertNotIn("_remote_delete", called)


if __name__ == "__main__":
    unittest.main()
