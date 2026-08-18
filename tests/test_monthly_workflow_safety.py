#!/usr/bin/env python3
"""Regression coverage for the monthly-preparation and post-merge
deployment workflows (Round-3 §1, §2, §3, §14).

Round-3 split the pre-existing "monthly + deploy" workflow into two
files with distinct authorities:

- ``.github/workflows/monthly_dmi.yml`` — release PREPARATION only.
  Computes DMI, generates manifests + release notes, builds and
  validates a local deployment candidate, and (in ``prepare_release``
  mode) opens a review PR. It MUST NOT configure SSH, rsync/scp/sftp
  to the live site, auto-merge PRs, or perform any production write.
  Default mode is ``validate`` + fixture data (offline, safe).

- ``.github/workflows/deploy_production.yml`` — actual production
  deployment. Runs on push-to-``main`` (post-merge) or explicit
  ``workflow_dispatch`` with ``production=true``. Rebuilds the deploy
  tree via the single builder (``scripts.prepare_deployment --verify``),
  refuses to deploy if any Core artifact is staged, and rsyncs over SSH
  with strict host verification (``ssh-keyscan`` failure is fatal;
  ``StrictHostKeyChecking=yes``).

These tests freeze those structural invariants against the YAML so that
a future accidental revert — reintroducing a deploy step in the monthly
workflow, weakening SSH host checking, hardcoding ``ref: main``, or
adding an auto-merge — is caught before it can ship.
"""

from __future__ import annotations

import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is a repo dependency
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
MONTHLY_PATH = WORKFLOWS / "monthly_dmi.yml"
DEPLOY_PATH = WORKFLOWS / "deploy_production.yml"


def _on_block(doc: dict) -> dict:
    """PyYAML parses the top-level ``on:`` key as Python ``True``.

    Access it via either the string key or the boolean key so both
    interpretations succeed.
    """
    return doc.get("on") or doc.get(True)


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestMonthlyPreparationWorkflow(unittest.TestCase):
    """`.github/workflows/monthly_dmi.yml` — §1 refactor invariants."""

    @classmethod
    def setUpClass(cls):
        cls.raw = MONTHLY_PATH.read_text()
        cls.doc = yaml.safe_load(cls.raw)
        cls.job = cls.doc["jobs"]["prepare-dmi"]
        cls.steps = cls.job["steps"]

    # ---- §1: job identity and inputs -----------------------------------

    def test_job_is_named_prepare_dmi(self):
        # Round-3 §1 renamed the job from `compute-dmi` to `prepare-dmi`
        # to make it structurally impossible to interpret this workflow
        # as a deployer.
        self.assertIn(
            "prepare-dmi", self.doc["jobs"],
            "§1: monthly workflow's single job must be 'prepare-dmi'.",
        )
        self.assertNotIn(
            "compute-dmi", self.doc["jobs"],
            "§1: obsolete 'compute-dmi' job name must be gone.",
        )

    def test_mode_input_defaults_to_validate(self):
        on = _on_block(self.doc)
        inputs = on["workflow_dispatch"]["inputs"]
        self.assertIn("mode", inputs, "§1: 'mode' input must exist.")
        self.assertEqual(
            str(inputs["mode"]["default"]), "validate",
            "§1: 'mode' input must default to 'validate' "
            "(safe/offline default; publishing requires opt-in).",
        )
        self.assertEqual(inputs["mode"]["type"], "choice")
        self.assertEqual(
            sorted(inputs["mode"]["options"]),
            sorted(["validate", "prepare_release"]),
            "§1: 'mode' choices must be exactly [validate, prepare_release].",
        )

    def test_data_source_input_defaults_to_fixture(self):
        on = _on_block(self.doc)
        inputs = on["workflow_dispatch"]["inputs"]
        self.assertIn(
            "data_source", inputs,
            "§1: 'data_source' input must exist.",
        )
        self.assertEqual(
            str(inputs["data_source"]["default"]), "fixture",
            "§1: 'data_source' must default to 'fixture' (offline).",
        )
        self.assertEqual(
            sorted(inputs["data_source"]["options"]),
            sorted(["fixture", "live"]),
            "§1: 'data_source' choices must be exactly [fixture, live].",
        )

    def test_no_legacy_dry_run_input(self):
        # The old `dry_run` boolean was replaced by mode+data_source in
        # §1. Leaving it around invites divergence between the resolver
        # and the input contract.
        on = _on_block(self.doc)
        inputs = on["workflow_dispatch"]["inputs"]
        self.assertNotIn(
            "dry_run", inputs,
            "§1: legacy 'dry_run' input must be removed (superseded by "
            "'mode' + 'data_source').",
        )

    # ---- §1: resolver step behavior ------------------------------------

    def _resolver(self) -> dict:
        return next(s for s in self.steps if s.get("id") == "mode")

    def test_resolver_falls_through_to_validate(self):
        script = self._resolver()["run"]
        self.assertIn(
            'MODE="${INPUT_MODE:-validate}"', script,
            "§1: resolver must fall through to 'validate' when INPUT_MODE "
            "is empty (empty ⇒ safe/offline default).",
        )
        self.assertIn(
            'DATA_SOURCE="${INPUT_DATA_SOURCE:-fixture}"', script,
            "§1: resolver must fall through to 'fixture' when "
            "INPUT_DATA_SOURCE is empty.",
        )

    def test_scheduled_runs_force_prepare_release_live(self):
        script = self._resolver()["run"]
        # Collapse to a single line to make ordering assertion robust
        # against shell reformatting.
        collapsed = " ".join(script.split())
        self.assertRegex(
            collapsed,
            r'EVENT_NAME"\s*=\s*"schedule".*MODE="prepare_release".*'
            r'DATA_SOURCE="live"',
            "§1: scheduled runs must force MODE=prepare_release + "
            "DATA_SOURCE=live (human still reviews and merges PR).",
        )

    def test_resolver_refuses_live_data_in_validate_mode(self):
        script = self._resolver()["run"]
        self.assertIn(
            'DATA_SOURCE" = "live" ] && [ "$MODE" = "validate"', script,
            "§1: resolver must explicitly refuse data_source=live "
            "combined with mode=validate.",
        )

    # ---- §1: NO deployment or auto-merge in this workflow --------------

    def test_no_auto_merge_anywhere(self):
        step_names = [s.get("name", "") for s in self.steps]
        offenders = [
            n for n in step_names
            if "auto-merge" in n.lower() or "automerge" in n.lower()
        ]
        self.assertEqual(
            offenders, [],
            f"§1: auto-merge step(s) must not exist; found: {offenders}",
        )
        for step in self.steps:
            run = step.get("run", "") or ""
            self.assertNotIn(
                "gh pr merge", run,
                f"§1: step {step.get('name')!r} still calls "
                "`gh pr merge` (auto-merge is forbidden).",
            )

    def test_no_ssh_or_rsync_anywhere_in_monthly(self):
        # §1 hard boundary: the preparation workflow is not allowed to
        # contact the live site at all. If any step introduces
        # ssh-keyscan / rsync / scp / sftp / ssh, this test fails.
        forbidden = ("ssh-keyscan", "rsync", "scp ", "sftp ", "ssh -")
        for step in self.steps:
            run = step.get("run", "") or ""
            for needle in forbidden:
                self.assertNotIn(
                    needle, run,
                    f"§1: monthly workflow step {step.get('name')!r} "
                    f"contains forbidden token {needle!r}; deployment "
                    "lives in deploy_production.yml.",
                )

    def test_no_hardcoded_ref_main_in_checkout(self):
        # §1: checkouts must use the triggering ref so repair branches
        # can run manual dispatches. `ref: main` was the pre-repair bug.
        for step in self.steps:
            uses = step.get("uses", "") or ""
            if uses.startswith("actions/checkout@"):
                with_block = step.get("with") or {}
                self.assertNotEqual(
                    str(with_block.get("ref", "")), "main",
                    "§1: actions/checkout must not hardcode ref: main "
                    "(scheduled runs default to main; manual dispatch "
                    "may run on a repair branch).",
                )

    # ---- §5: deployment candidate is built by the central builder ------

    def test_deployment_candidate_built_by_prepare_deployment(self):
        step = next(
            (s for s in self.steps
             if s.get("name") == "Build local deployment candidate "
                                 "(never deployed here)"),
            None,
        )
        self.assertIsNotNone(
            step,
            "§4/§5: 'Build local deployment candidate (never deployed "
            "here)' step is missing.",
        )
        script = step["run"]
        self.assertIn(
            "python -m scripts.prepare_deployment", script,
            "§5: deploy tree must be assembled by "
            "scripts.prepare_deployment (single builder).",
        )
        self.assertIn(
            "--verify", script,
            "§5: prepare_deployment invocation must use --verify.",
        )


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestDeployProductionWorkflow(unittest.TestCase):
    """`.github/workflows/deploy_production.yml` — §2, §3, §5, §7 gates."""

    @classmethod
    def setUpClass(cls):
        cls.raw = DEPLOY_PATH.read_text()
        cls.doc = yaml.safe_load(cls.raw)
        cls.job = cls.doc["jobs"]["deploy-production"]
        cls.steps = cls.job["steps"]

    def test_manual_dispatch_defaults_to_dry_run(self):
        on = _on_block(self.doc)
        inputs = on["workflow_dispatch"]["inputs"]
        self.assertIn("production", inputs)
        self.assertEqual(
            str(inputs["production"]["default"]).lower(), "false",
            "§2: manual dispatch must default to production=false "
            "(dry-run); real deploy requires explicit opt-in.",
        )

    def test_push_trigger_is_scoped_to_main(self):
        on = _on_block(self.doc)
        push = on.get("push") or {}
        self.assertEqual(
            push.get("branches"), ["main"],
            "§2: post-merge deploy trigger must be push to main only.",
        )

    def test_checkout_pins_triggering_commit(self):
        checkout = next(
            s for s in self.steps
            if str(s.get("uses", "")).startswith("actions/checkout@")
        )
        with_block = checkout.get("with") or {}
        self.assertEqual(
            with_block.get("ref"), "${{ github.sha }}",
            "§2: deploy workflow must check out the exact triggering "
            "commit (github.sha), never hardcode 'main'.",
        )

    def test_deploy_tree_rebuilt_via_prepare_deployment(self):
        builder_steps = [
            s for s in self.steps
            if "python -m scripts.prepare_deployment" in (s.get("run", "") or "")
        ]
        self.assertTrue(
            builder_steps,
            "§5: deploy workflow must build staging via "
            "scripts.prepare_deployment (the single builder).",
        )
        for step in builder_steps:
            self.assertIn(
                "--verify", step["run"],
                "§5: every prepare_deployment invocation in the deploy "
                "workflow must pass --verify.",
            )

    def test_refuses_to_deploy_core_artifacts(self):
        step = next(
            (s for s in self.steps
             if s.get("name") == "Refuse to deploy if Core artifacts staged"),
            None,
        )
        self.assertIsNotNone(
            step,
            "§7: 'Refuse to deploy if Core artifacts staged' gate "
            "must exist.",
        )
        script = step["run"]
        # The gate matches both *_core.* and *-core.* filenames.
        self.assertIn("_core.", script)
        self.assertIn("-core.", script)
        self.assertIn("exit 1", script)

    def test_ssh_keyscan_failure_is_fatal(self):
        # §3: strict host verification. ssh-keyscan MUST run without
        # `|| true` swallowing failure, and StrictHostKeyChecking must
        # stay enabled.
        keyscan_step = next(
            (s for s in self.steps
             if "ssh-keyscan" in (s.get("run", "") or "")),
            None,
        )
        self.assertIsNotNone(
            keyscan_step,
            "§3: deploy workflow must use ssh-keyscan to populate "
            "known_hosts.",
        )
        script = keyscan_step["run"]
        self.assertNotRegex(
            script,
            r"ssh-keyscan[^\n]*\|\|\s*true",
            "§3: ssh-keyscan failure must be fatal; `|| true` is "
            "forbidden (that was the pre-repair bug).",
        )

    def _rsync_exec_step(self) -> dict:
        # Pick the step that actually invokes rsync (as an executable
        # token), skipping the dry-run "skipping ... rsync" echo step.
        for step in self.steps:
            run = step.get("run", "") or ""
            for line in run.splitlines():
                stripped = line.strip()
                if stripped.startswith("rsync ") or stripped.startswith("rsync\t"):
                    return step
        raise AssertionError(
            "§3: deploy workflow must contain a step that invokes rsync."
        )

    def test_rsync_uses_strict_host_key_checking(self):
        rsync_step = self._rsync_exec_step()
        self.assertIsNotNone(
            rsync_step, "§3: deploy workflow must rsync via SSH.",
        )
        script = rsync_step["run"]
        self.assertIn(
            "StrictHostKeyChecking=yes", script,
            "§3: rsync SSH command must enforce "
            "StrictHostKeyChecking=yes.",
        )
        self.assertNotIn(
            "StrictHostKeyChecking=no", script,
            "§3: StrictHostKeyChecking=no is forbidden anywhere.",
        )
        self.assertIn(
            "UserKnownHostsFile", script,
            "§3: rsync SSH command must pin UserKnownHostsFile.",
        )

    def test_deploy_step_gated_on_production_flag(self):
        # The rsync step must be conditional on
        # steps.mode.outputs.production == 'true'. Otherwise a
        # workflow_dispatch dry-run could still touch the live site.
        rsync_step = self._rsync_exec_step()
        cond = str(rsync_step.get("if", ""))
        self.assertIn(
            "steps.mode.outputs.production == 'true'", cond,
            "§2: rsync deployment step must be gated on production=true.",
        )


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Round-3 §2 / §3 / §14: coverage for EVERY workflow, not just the two above.
#
# §2 requires "structural tests for all workflows, not only
# monthly_dmi.yml". Before this section, `deploy_web_dashboard.yml` and
# `deploy_wp_plugins.yml` had no tests at all — both could deploy to
# production, and neither was pinned by anything.
#
# §3 requires "a repository-wide test that fails if an active workflow,
# deployment script or runbook contains StrictHostKeyChecking=no". The
# existing coverage checked a single step of a single workflow.
# ---------------------------------------------------------------------------

DASHBOARD_PATH = WORKFLOWS / "deploy_web_dashboard.yml"
WP_PLUGINS_PATH = WORKFLOWS / "deploy_wp_plugins.yml"

#: Every workflow that must obey the deployment-safety policy.
ALL_WORKFLOWS = (
    MONTHLY_PATH,
    DEPLOY_PATH,
    DASHBOARD_PATH,
    WP_PLUGINS_PATH,
)

#: Workflows that are allowed to touch production at all.
DEPLOY_WORKFLOWS = (DEPLOY_PATH, DASHBOARD_PATH, WP_PLUGINS_PATH)


def _steps_of(path: Path) -> list:
    doc = yaml.safe_load(path.read_text())
    steps = []
    for job in (doc.get("jobs") or {}).values():
        steps.extend(job.get("steps") or [])
    return steps


def _run_scripts(path: Path) -> str:
    return "\n".join(
        step.get("run", "") for step in _steps_of(path)
    )


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestEveryWorkflowIsDiscovered(unittest.TestCase):
    """Guard the guards: the workflow list must not go stale.

    If a new workflow is added and this list is not updated, every
    policy test below would silently skip it. So the list is checked
    against the directory itself.
    """

    def test_all_workflow_files_are_covered(self):
        on_disk = sorted(
            p.name for p in WORKFLOWS.glob("*.yml")
        ) + sorted(p.name for p in WORKFLOWS.glob("*.yaml"))
        covered = sorted(p.name for p in ALL_WORKFLOWS)
        self.assertEqual(
            sorted(on_disk), covered,
            "§2: a workflow exists that no policy test covers. Add it to "
            "ALL_WORKFLOWS (and DEPLOY_WORKFLOWS if it can deploy).",
        )

    def test_every_covered_workflow_exists(self):
        for path in ALL_WORKFLOWS:
            with self.subTest(workflow=path.name):
                self.assertTrue(path.is_file(), f"{path} missing")

    def test_every_workflow_parses(self):
        for path in ALL_WORKFLOWS:
            with self.subTest(workflow=path.name):
                doc = yaml.safe_load(path.read_text())
                self.assertIsInstance(doc, dict)
                self.assertIn("jobs", doc)


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestRepositoryWideStrictHostKeyChecking(unittest.TestCase):
    """§3: no active workflow, deployment script, or runbook may disable
    strict host verification."""

    #: Trees that are not part of the active repair: frozen archives,
    #: vendored code, caches. Documented rather than silently skipped.
    EXCLUDED_PARTS = {
        ".git", "venv", ".venv", "node_modules", "__pycache__",
        ".pytest_cache", "dmi-v0.1.10-deployment",
        "dmi-v0.1.11-external-deployment",
    }

    #: This test file necessarily contains the forbidden string in its
    #: own assertions, so it is the single named exemption.
    SELF = Path(__file__).name

    FORBIDDEN = "StrictHostKeyChecking=no"

    #: §3 scopes this sweep to "an active workflow, deployment script or
    #: runbook". Those are enumerated as directories rather than as a
    #: whole-repo glob, because a whole-repo glob also picks up audit
    #: records whose job is to DESCRIBE the check — flagging the
    #: documentation of a control as a violation of it. The
    #: `docs/repair/` and `docs/` runbooks that carry executable SSH
    #: recipes are in scope; the directories are listed so adding a new
    #: one is a deliberate act.
    SCOPED_DIRS = (
        ".github/workflows",
        "scripts",
        "docs/repair",
        "docs/runbooks",
        "docs/deployment",
    )

    #: Individual runbook files outside the scoped directories.
    SCOPED_FILES = (
        "docs/DEPLOYMENT_GUIDE.md",
        "docs/deployment-workflows.md",
    )

    def _candidate_files(self):
        seen = set()
        for rel_dir in self.SCOPED_DIRS:
            base = ROOT / rel_dir
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                if not path.is_file():
                    continue
                if set(path.relative_to(ROOT).parts) & self.EXCLUDED_PARTS:
                    continue
                if path.suffix.lower() not in (
                    ".yml", ".yaml", ".sh", ".py", ".md", ".bash",
                ):
                    continue
                if path.name == self.SELF:
                    continue
                if path not in seen:
                    seen.add(path)
                    yield path
        for rel in self.SCOPED_FILES:
            path = ROOT / rel
            if path.is_file() and path not in seen:
                seen.add(path)
                yield path

    def test_no_active_file_disables_strict_host_checking(self):
        offenders = []
        for path in self._candidate_files():
            try:
                text = path.read_text(errors="ignore")
            except OSError:
                continue
            if self.FORBIDDEN in text:
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(
            offenders, [],
            f"§3: {self.FORBIDDEN} is forbidden in active workflows, "
            f"deployment scripts, and runbooks. Offenders: {offenders}",
        )

    def test_scan_is_not_vacuous(self):
        """The sweep must actually be reading the workflow files."""
        scanned = {p.name for p in self._candidate_files()}
        for path in ALL_WORKFLOWS:
            self.assertIn(
                path.name, scanned,
                f"§3: sweep did not reach {path.name}; it would pass "
                f"vacuously.",
            )

    def test_every_ssh_invocation_requests_strict_checking(self):
        """Absence of `=no` is not presence of `=yes`.

        Any workflow that invokes ssh/rsync-over-ssh must say
        StrictHostKeyChecking=yes explicitly, so an omitted option
        cannot fall back to a permissive default.
        """
        for path in DEPLOY_WORKFLOWS:
            script = _run_scripts(path)
            if "ssh " not in script and "rsync" not in script:
                continue
            with self.subTest(workflow=path.name):
                self.assertIn(
                    "StrictHostKeyChecking=yes", script,
                    f"§3: {path.name} invokes ssh/rsync without "
                    f"explicitly requesting strict host verification.",
                )

    def test_known_hosts_acquisition_failure_is_never_swallowed(self):
        """§3/§14: failed host-key acquisition must not be ignored."""
        for path in DEPLOY_WORKFLOWS:
            script = _run_scripts(path)
            if "ssh-keyscan" not in script:
                continue
            with self.subTest(workflow=path.name):
                for line in script.splitlines():
                    if "ssh-keyscan" in line:
                        self.assertNotIn(
                            "|| true", line,
                            f"§3: {path.name} swallows ssh-keyscan "
                            f"failure with `|| true`.",
                        )

    def test_empty_known_hosts_is_treated_as_failure(self):
        """ssh-keyscan exits 0 when it cannot reach the host.

        Checking only the exit status therefore proves nothing: the run
        would proceed with an empty known_hosts. Each deploy workflow
        must also assert the file is non-empty.
        """
        for path in DEPLOY_WORKFLOWS:
            script = _run_scripts(path)
            if "ssh-keyscan" not in script:
                continue
            with self.subTest(workflow=path.name):
                self.assertIn(
                    "-s /tmp/dmi_known_hosts", script,
                    f"§3: {path.name} must fail when ssh-keyscan "
                    f"produced no host key (exit 0 is not enough).",
                )


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestNoWorkflowAutoMergesOrAutoApproves(unittest.TestCase):
    """§1/§14: no workflow may merge, approve, or close a PR."""

    FORBIDDEN_FRAGMENTS = (
        "gh pr merge",
        "gh pr review",
        "gh pr close",
        "--auto-merge",
        "--admin",
        "pull-request-merge",
        "automerge",
        "auto-merge",
        "enablePullRequestAutoMerge",
    )

    def test_no_workflow_contains_a_merge_or_approve_action(self):
        """Inspect what the workflow EXECUTES, not what it says.

        A raw-text scan cannot express this: the monthly workflow's PR
        body legitimately contains the words "never auto-merged", and
        flagging that would mean the workflow gets safer by deleting the
        sentence promising it is safe. So this checks the parsed `uses:`
        action references and `run:` shell scripts — the only two places
        a workflow can actually merge something.
        """
        offenders = []
        for path in ALL_WORKFLOWS:
            for step in _steps_of(path):
                uses = str(step.get("uses", ""))
                run = str(step.get("run", ""))
                # Strip comment lines from run scripts; a comment cannot
                # merge a PR.
                run_code = "\n".join(
                    line for line in run.splitlines()
                    if not line.strip().startswith("#")
                )
                for fragment in self.FORBIDDEN_FRAGMENTS:
                    if fragment in uses:
                        offenders.append(
                            f"{path.name}: uses {uses!r} ({fragment})"
                        )
                    if fragment in run_code:
                        offenders.append(
                            f"{path.name}: run contains {fragment!r} "
                            f"in step {step.get('name')!r}"
                        )
        self.assertEqual(
            offenders, [],
            f"§1/§14: no workflow may auto-merge or auto-approve a PR: "
            f"{offenders}",
        )

    def test_no_workflow_grants_pr_write_it_does_not_need(self):
        """Deployment workflows must not be able to touch PRs at all."""
        for path in DEPLOY_WORKFLOWS:
            with self.subTest(workflow=path.name):
                doc = yaml.safe_load(path.read_text())
                perms = doc.get("permissions") or {}
                self.assertNotEqual(
                    perms.get("pull-requests"), "write",
                    f"§2: {path.name} does not need pull-request write "
                    f"access.",
                )
                self.assertEqual(
                    perms.get("contents"), "read",
                    f"§2: {path.name} should only need read access to "
                    f"contents.",
                )

    def test_scan_sees_the_pr_creating_step(self):
        """Non-vacuity: the sweep must reach the step that opens the PR."""
        found = any(
            "create-pull-request" in str(s.get("uses", ""))
            for s in _steps_of(MONTHLY_PATH)
        )
        self.assertTrue(
            found,
            "expected to find the PR-creating step; the merge sweep "
            "would otherwise be inspecting nothing relevant.",
        )


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestAllDeploymentWorkflowsDefaultToDryRun(unittest.TestCase):
    """§2/§14: every manual deployment defaults to dry-run."""

    def test_manual_dispatch_defaults_to_non_production(self):
        for path in DEPLOY_WORKFLOWS:
            with self.subTest(workflow=path.name):
                doc = yaml.safe_load(path.read_text())
                dispatch = (_on_block(doc) or {}).get("workflow_dispatch")
                self.assertIsInstance(
                    dispatch, dict,
                    f"§2: {path.name} must expose workflow_dispatch with "
                    f"an explicit production input.",
                )
                inputs = dispatch.get("inputs") or {}
                self.assertIn(
                    "production", inputs,
                    f"§2: {path.name} needs a `production` input.",
                )
                self.assertEqual(
                    str(inputs["production"].get("default")).lower(),
                    "false",
                    f"§2: {path.name} manual dispatch must default to "
                    f"dry-run.",
                )

    def test_production_resolver_falls_through_to_false(self):
        """An unset input must resolve to false, not empty-and-truthy."""
        for path in DEPLOY_WORKFLOWS:
            with self.subTest(workflow=path.name):
                script = _run_scripts(path)
                self.assertIn(
                    'PROD="${INPUT_PRODUCTION:-false}"', script,
                    f"§2: {path.name} must default PROD to false when "
                    f"the input is unset.",
                )

    def test_every_production_step_is_gated_on_the_flag(self):
        """No ssh/rsync step may run unless production resolved true."""
        for path in DEPLOY_WORKFLOWS:
            for step in _steps_of(path):
                run = step.get("run", "") or ""
                if "ssh-keyscan" not in run and "rsync -avz" not in run:
                    continue
                with self.subTest(workflow=path.name,
                                  step=step.get("name")):
                    condition = str(step.get("if", ""))
                    self.assertIn(
                        "production == 'true'", condition,
                        f"§2: {path.name} step {step.get('name')!r} "
                        f"performs a remote action without being gated "
                        f"on the production flag.",
                    )

    def test_deploy_workflows_only_auto_trigger_from_main(self):
        """§2: deployment happens post-merge, never from a branch push."""
        for path in DEPLOY_WORKFLOWS:
            with self.subTest(workflow=path.name):
                push = (_on_block(yaml.safe_load(path.read_text()))
                        or {}).get("push") or {}
                self.assertEqual(
                    push.get("branches"), ["main"],
                    f"§2: {path.name} must auto-trigger only from main.",
                )

    def test_no_deploy_workflow_triggers_on_pull_request(self):
        """A PR trigger would deploy unreviewed code."""
        for path in DEPLOY_WORKFLOWS:
            with self.subTest(workflow=path.name):
                on = _on_block(yaml.safe_load(path.read_text())) or {}
                for trigger in ("pull_request", "pull_request_target"):
                    self.assertNotIn(
                        trigger, on,
                        f"§2: {path.name} must not deploy from a "
                        f"{trigger} event.",
                    )


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestNoWorkflowHardcodesRefMain(unittest.TestCase):
    """§1/§2: checkout must never pin `ref: main`."""

    def test_no_checkout_hardcodes_ref_main(self):
        offenders = []
        for path in ALL_WORKFLOWS:
            for step in _steps_of(path):
                uses = str(step.get("uses", ""))
                if "actions/checkout" not in uses:
                    continue
                ref = str((step.get("with") or {}).get("ref", ""))
                if ref.strip() == "main":
                    offenders.append(f"{path.name}: {step.get('name')}")
        self.assertEqual(
            offenders, [],
            f"§1/§2: `ref: main` must not be hardcoded in checkout: "
            f"{offenders}",
        )

    def test_deploy_workflows_check_out_the_triggering_commit(self):
        for path in DEPLOY_WORKFLOWS:
            with self.subTest(workflow=path.name):
                refs = [
                    str((s.get("with") or {}).get("ref", ""))
                    for s in _steps_of(path)
                    if "actions/checkout" in str(s.get("uses", ""))
                ]
                self.assertTrue(refs, f"{path.name} has no checkout step")
                for ref in refs:
                    self.assertIn(
                        "github.sha", ref,
                        f"§2: {path.name} must check out the exact "
                        f"triggering commit, got {ref!r}.",
                    )


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestDashboardWorkflowUsesTheSingleBuilder(unittest.TestCase):
    """§2: the ad-hoc staging recipe must be gone."""

    @classmethod
    def setUpClass(cls):
        cls.script = _run_scripts(DASHBOARD_PATH)

    def test_staging_is_built_by_prepare_deployment(self):
        self.assertIn(
            "scripts.prepare_deployment", self.script,
            "§2: deploy_web_dashboard.yml must call the single "
            "deployment builder.",
        )

    def test_no_independent_staging_recipe(self):
        """No hand-rolled mkdir/cp tree assembly before deployment."""
        forbidden = ("mkdir -p deploy/data/outputs", "cp -r data/outputs")
        for fragment in forbidden:
            self.assertNotIn(
                fragment, self.script,
                f"§2: ad-hoc staging recipe fragment {fragment!r} must "
                f"be removed; use the central builder.",
            )

    def test_core_guard_runs_against_the_built_tree(self):
        self.assertIn("deploy", self.script)
        self.assertIn("core", self.script.lower())


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestMonthlyWorkflowHasValidationGates(unittest.TestCase):
    """§1 steps 4 and 6: QA runs and every artifact is validated."""

    @classmethod
    def setUpClass(cls):
        cls.steps = _steps_of(MONTHLY_PATH)
        cls.names = [str(s.get("name", "")) for s in cls.steps]
        cls.script = _run_scripts(MONTHLY_PATH)

    def test_qa_reports_are_validated(self):
        self.assertIn(
            "qa_report.schema.json", self.script,
            "§1: the monthly workflow must validate QA reports.",
        )

    def test_public_timeseries_is_validated(self):
        self.assertIn(
            "dmi_timeseries_schema.json", self.script,
            "§1/§15: the monthly workflow must validate the public "
            "timeseries the dashboard fetches.",
        )

    def test_release_artifacts_are_schema_validated(self):
        for schema in ("dmi_output.schema.json", "releases.schema.json",
                       "specifications.schema.json"):
            with self.subTest(schema=schema):
                self.assertIn(schema, self.script)

    def test_validation_gates_run_in_every_mode(self):
        """Gates must not be skipped in fixture/validate mode."""
        for step in self.steps:
            name = str(step.get("name", ""))
            if not name.lower().startswith("validate"):
                continue
            with self.subTest(step=name):
                self.assertNotIn(
                    "data_source == 'live'", str(step.get("if", "")),
                    f"§1: validation gate {name!r} must run in every "
                    f"mode, including fixture/offline.",
                )

    def test_qa_gate_fails_when_it_validates_nothing(self):
        """A gate that silently checks zero files is not a gate."""
        self.assertIn(
            "no QA report was validated", self.script,
            "§1: the QA gate must fail if it validated nothing.",
        )

    def test_deployment_candidate_is_built_after_validation(self):
        build_idx = next(
            i for i, n in enumerate(self.names)
            if "deployment candidate" in n.lower()
        )
        validate_indices = [
            i for i, n in enumerate(self.names)
            if n.lower().startswith("validate")
        ]
        self.assertTrue(validate_indices)
        self.assertGreater(
            build_idx, max(validate_indices),
            "§1: the deployment candidate must be built after the "
            "artifact validation gates.",
        )

    def test_pr_creation_is_the_last_gated_step(self):
        """§1: a release PR may be created only after every gate passes."""
        pr_idx = next(
            i for i, s in enumerate(self.steps)
            if "create-pull-request" in str(s.get("uses", ""))
        )
        for i, name in enumerate(self.names):
            if name.lower().startswith("validate") or \
                    "deployment candidate" in name.lower():
                self.assertLess(
                    i, pr_idx,
                    f"§1: gate {name!r} runs after PR creation.",
                )

    def test_pr_body_does_not_claim_the_site_was_updated(self):
        """§1: PR text must not say the live site was already updated."""
        pr_step = next(
            s for s in self.steps
            if "create-pull-request" in str(s.get("uses", ""))
        )
        body = str((pr_step.get("with") or {}).get("body", "")).lower()
        for claim in (
            "live site has been updated",
            "site is live",
            "deployed to production",
            "deployment complete",
        ):
            self.assertNotIn(
                claim, body,
                f"§1: PR body must not claim {claim!r} before merge.",
            )
        self.assertIn("does not deploy", body)
