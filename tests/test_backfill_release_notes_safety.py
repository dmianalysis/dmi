#!/usr/bin/env python3
"""The legacy note-backfill entry point must not reconstruct history (§4).

The defect
----------
``scripts/backfill_release_notes.py`` used to call
``compute_dmi_for_period`` to synthesize a missing Slack-Plus companion
in memory, then render a release note describing that synthesized series
as published history. It announced this with one ``!`` line and carried
on, so a note describing a series that was never computed was
indistinguishable from one describing a series that was.

It also recomputed from *current* staged inputs, which are refreshed over
time, so the "recovered" figures need not match what the period would
actually have produced — while being presented as that period's numbers.

The test below is behavioral: it builds a Baseline-only period, runs the
real command, and asserts that it fails, writes no synthetic artifact,
and leaves the manifests and notes byte-identical.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENTRY = REPO_ROOT / "scripts" / "backfill_release_notes.py"
REAL_OUTPUTS = REPO_ROOT / "data" / "outputs"

BASELINE_ONLY_PERIOD = "2026-06"


def _digest_tree(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


class _BaselineOnlyTree:
    """A period that has a Baseline release and NO Slack-Plus companion."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.outputs = self.root / "data" / "outputs"
        (self.outputs / "releases").mkdir(parents=True)
        (self.outputs / "published").mkdir(parents=True)

        for item in sorted(REAL_OUTPUTS.iterdir()):
            if item.is_file():
                shutil.copy2(item, self.outputs / item.name)
        for note in sorted((REAL_OUTPUTS / "releases").glob("*.html")):
            shutil.copy2(note, self.outputs / "releases" / note.name)
        shutil.copy2(
            REAL_OUTPUTS / "published" / "dmi_timeseries.json",
            self.outputs / "published" / "dmi_timeseries.json",
        )
        shutil.copytree(REPO_ROOT / "schemas", self.root / "schemas")

        # Remove the Slack-Plus companion so the period is Baseline-only,
        # and drop it from the manifest so the tree stays self-consistent.
        companion = self.outputs / (
            f"dmi_release_{BASELINE_ONLY_PERIOD}_slack_plus.json"
        )
        self.companion = companion
        if companion.exists():
            companion.unlink()
        for name in ("releases.json", "latest.json"):
            path = self.outputs / name
            doc = json.loads(path.read_text())
            for entry in doc.get("releases", []):
                if entry.get("release_id") == BASELINE_ONLY_PERIOD:
                    entry.get("spec_urls", {}).pop("slack_plus", None)
            path.write_text(json.dumps(doc, indent=2))

    def __enter__(self):
        self._cwd = os.getcwd()
        os.chdir(self.root)
        return self

    def __exit__(self, *exc):
        os.chdir(self._cwd)
        self._tmp.cleanup()
        return False


class TestEntryPointNeverReconstructs(unittest.TestCase):
    """§4: consume existing artifacts only; never synthesize."""

    def test_no_dmi_computation_is_imported(self):
        imported = set()
        for node in ast.walk(ast.parse(ENTRY.read_text())):
            if isinstance(node, ast.ImportFrom):
                imported |= {a.name for a in node.names}
        forbidden = {
            "compute_dmi_for_period", "load_cpi_data", "load_slack_data",
            "load_weights", "staging_window_for_period",
        }
        self.assertEqual(
            sorted(imported & forbidden), [],
            "§4: the entry point must not import DMI computation.",
        )

    def test_no_dmi_computation_is_called(self):
        called = {
            n.func.id for n in ast.walk(ast.parse(ENTRY.read_text()))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        self.assertNotIn("compute_dmi_for_period", called)
        self.assertNotIn("recompute_companion_release", called)

    def test_reconstruction_helper_is_gone(self):
        names = {
            n.name for n in ast.walk(ast.parse(ENTRY.read_text()))
            if isinstance(n, ast.FunctionDef)
        }
        self.assertNotIn(
            "recompute_companion_release", names,
            "§4: the in-memory reconstruction helper must not exist.",
        )

    def test_it_delegates_to_the_safe_implementation(self):
        imported_modules = {
            node.module for node in ast.walk(ast.parse(ENTRY.read_text()))
            if isinstance(node, ast.ImportFrom) and node.module
        }
        self.assertIn(
            "scripts.regenerate_release_notes", imported_modules,
            "§4: it must delegate to the existing-artifact-only "
            "regeneration implementation.",
        )


class TestBaselineOnlyFixtureBehavior(unittest.TestCase):
    """§4: the behavioral proof, on a real Baseline-only period."""

    def test_no_synthetic_companion_is_created(self):
        with _BaselineOnlyTree() as tree:
            from scripts.backfill_release_notes import main
            main(["--periods", BASELINE_ONLY_PERIOD,
                  "--output-dir", str(tree.outputs)])
            self.assertFalse(
                tree.companion.exists(),
                "§4: a missing Slack-Plus artifact must never be "
                "synthesized on disk.",
            )

    def test_manifests_and_notes_are_unchanged(self):
        with _BaselineOnlyTree() as tree:
            before = _digest_tree(tree.outputs)
            from scripts.backfill_release_notes import main
            main(["--periods", BASELINE_ONLY_PERIOD,
                  "--output-dir", str(tree.outputs), "--dry-run"])
            self.assertEqual(
                before, _digest_tree(tree.outputs),
                "§4: a dry run must leave every artifact untouched.",
            )

    def test_regenerated_note_does_not_claim_slack_plus(self):
        """The note must describe only what was actually published."""
        with _BaselineOnlyTree() as tree:
            from scripts.backfill_release_notes import main
            rc = main(["--periods", BASELINE_ONLY_PERIOD,
                       "--output-dir", str(tree.outputs)])
            self.assertEqual(rc, 0)
            note = (tree.outputs / "releases"
                    / f"{BASELINE_ONLY_PERIOD}.html").read_text()
            # The generator's literal is "Slack+"; asserting on
            # "Slack-Plus" would pass vacuously.
            self.assertNotIn(
                "Slack+", note,
                "§4: a Baseline-only period must not render a Slack-Plus "
                "row; that would describe a series nobody computed.",
            )
            self.assertNotIn("Core", note)

    def test_missing_baseline_is_a_clear_failure(self):
        """§4: fail if a required artifact is missing.

        The safe command reports this as a non-zero return rather than an
        exception, so the wrapper must propagate the status rather than
        swallowing it.
        """
        with _BaselineOnlyTree() as tree:
            (tree.outputs / f"dmi_release_{BASELINE_ONLY_PERIOD}.json").unlink()
            from scripts.backfill_release_notes import main
            rc = main(["--periods", BASELINE_ONLY_PERIOD,
                       "--output-dir", str(tree.outputs)])
            self.assertEqual(
                rc, 1,
                "§4: a missing required artifact must fail the command.",
            )

    def test_unknown_period_is_rejected(self):
        with _BaselineOnlyTree() as tree:
            from scripts.backfill_release_notes import main
            rc = main(["--periods", "1999-01",
                       "--output-dir", str(tree.outputs)])
            self.assertEqual(
                rc, 1, "§4: an unknown period must fail, not invent one."
            )


class TestNoActiveThreeSpecWording(unittest.TestCase):
    """§4: 'three-spec' must not describe the current design."""

    ACTIVE_DIRS = ("scripts", ".github/workflows")
    PHRASES = ("three-spec", "three spec", "all three specifications",
               "all three specs", "three-specification")

    def test_active_code_has_no_three_spec_wording(self):
        offenders = []
        for rel in self.ACTIVE_DIRS:
            base = REPO_ROOT / rel
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                if path.suffix not in (".py", ".yml", ".yaml"):
                    continue
                lowered = path.read_text(errors="ignore").lower()
                for phrase in self.PHRASES:
                    if phrase in lowered:
                        offenders.append(f"{path.relative_to(REPO_ROOT)}: {phrase!r}")
        self.assertEqual(
            offenders, [],
            f"§4: active code must not describe a three-specification "
            f"design; v0.1.12 publishes two. Offenders: {offenders}",
        )

    def test_specification_order_contains_exactly_two_specs(self):
        from scripts.build_specifications_manifest import SPEC_ORDER
        self.assertEqual(
            sorted(SPEC_ORDER), ["baseline", "slack_plus"],
            "§4: Core must not be in the specification order.",
        )


if __name__ == "__main__":
    unittest.main()
