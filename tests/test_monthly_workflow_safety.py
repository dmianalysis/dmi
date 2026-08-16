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
