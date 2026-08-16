#!/usr/bin/env python3
"""Regression coverage for the monthly-workflow safety posture (§6).

The monthly DMI computation workflow (`.github/workflows/monthly_dmi.yml`)
must, per repair spec §6:

- Default the `dry_run` input to `'true'` (safe default; publishing
  requires an explicit `false`).
- Treat an empty/unset `dry_run` as dry-run (so scheduled cron runs
  never deploy without an operator explicitly opting in).
- NOT auto-merge the release PR (the "Auto-merge release PR" step
  must be absent).
- Use `scripts.prepare_deployment` (with `--verify`) rather than the
  ad-hoc bash recipe to assemble the deploy tree.

These tests parse the workflow file as YAML and enforce those
properties structurally, so a future accidental revert of any of them
is caught by CI before it can ship.
"""

from __future__ import annotations

import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is a repo dependency
    yaml = None

WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent
    / ".github"
    / "workflows"
    / "monthly_dmi.yml"
)


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestMonthlyWorkflowSafetyPosture(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.raw = WORKFLOW_PATH.read_text()
        cls.doc = yaml.safe_load(cls.raw)

    def _steps(self) -> list[dict]:
        job = self.doc["jobs"]["compute-dmi"]
        return job["steps"]

    def test_dry_run_input_defaults_to_true(self):
        # PyYAML parses the top-level `on:` key as Python bool True; access
        # it via the raw string key to be safe on both interpretations.
        on = self.doc.get("on") or self.doc.get(True)
        inputs = on["workflow_dispatch"]["inputs"]
        self.assertIn("dry_run", inputs)
        self.assertEqual(
            str(inputs["dry_run"]["default"]).lower(), "true",
            "§6: dry_run input must default to 'true' (safe default).",
        )

    def test_resolver_treats_empty_as_dry_run(self):
        # The resolver step is a shell script; assert it contains the
        # exact safe-default assignment.
        resolver = next(
            s for s in self._steps() if s.get("id") == "mode"
        )
        script = resolver["run"]
        self.assertIn(
            "DRY_RUN='true'", script,
            "§6: the dry-run resolver must fall through to 'true' when "
            "no input is provided (scheduled runs must be dry-run).",
        )

    def test_no_auto_merge_step_exists(self):
        step_names = [s.get("name", "") for s in self._steps()]
        offenders = [
            name for name in step_names
            if "auto-merge" in name.lower() or "automerge" in name.lower()
        ]
        self.assertEqual(
            offenders, [],
            f"§6: auto-merge step(s) must not exist; found: {offenders}",
        )

        # And no step body may call `gh pr merge` on the freshly-created
        # release PR.
        for step in self._steps():
            run = step.get("run", "") or ""
            self.assertNotIn(
                "gh pr merge", run,
                f"§6: step {step.get('name')!r} still calls `gh pr merge`.",
            )

    def test_deploy_tree_assembled_by_prepare_deployment_script(self):
        prep = next(
            (s for s in self._steps() if s.get("name") == "Prepare deployment package"),
            None,
        )
        self.assertIsNotNone(prep, "Prepare deployment package step is missing")
        script = prep["run"]
        self.assertIn(
            "python -m scripts.prepare_deployment", script,
            "§5/§6: the deploy tree must be assembled by scripts.prepare_deployment.",
        )
        self.assertIn(
            "--verify", script,
            "§6: the prepare_deployment call must use --verify.",
        )


if __name__ == "__main__":
    unittest.main()
